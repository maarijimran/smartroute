"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import {
  ArrowUpIcon,
  CheckIcon,
  ChevronDownIcon,
  CloseIcon,
  CopyIcon,
  FileIcon,
  InfoIcon,
  LockIcon,
  PencilIcon,
  PlusIcon,
  RouteMark,
  SlidersIcon,
  StarIcon,
  StopIcon,
  TrashIcon,
  UploadIcon,
} from "@/components/icons";
import { Badge, Button, Notice, Spinner, Switch, errorText, usePopover } from "@/components/ui";
import { api, fmtMs, fmtUsd, streamChat } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useChats } from "@/lib/chats";
import type { Doc, Message, Model, PrivacyMode, RouteMeta, Session } from "@/lib/types";

const DIMENSIONS = ["correctness", "relevance", "completeness", "usefulness"] as const;
const HISTORY_MODES: Record<string, string> = { none: "None", full: "Full", summary: "Summary", relevant_turns: "Relevant" };
const UPLOAD_TYPES = ".pdf,.txt,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp";
const TIER: Record<string, string> = { local: "Local", cheap: "Fast", strong: "Strong" };

export default function ChatPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <ChatView />
    </Suspense>
  );
}

/** Settings chosen before the first message of a new chat. */
interface Draft {
  privacy_mode: PrivacyMode;
  document_ids: string[];
  persist: boolean;
}
const EMPTY_DRAFT: Draft = { privacy_mode: "cloud_allowed", document_ids: [], persist: true };

function ChatView() {
  const { user, permissions } = useAuth();
  const chats = useChats();
  const params = useSearchParams();
  const router = useRouter();
  const requested = params.get("c");

  const [active, setActive] = useState<Session | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [input, setInput] = useState("");
  const [consent, setConsent] = useState(false);
  const [confidential, setConfidential] = useState(false);
  const [pinned, setPinned] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeId = useRef<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [documents, registry] = await Promise.all([api<Doc[]>("/api/documents"), api<Model[]>("/api/models")]);
        setDocs(documents);
        setModels(registry.filter((m) => m.enabled));
      } catch (e) {
        setError(errorText(e));
      }
    })();
  }, []);

  // Follow the ?c= parameter (sidebar links, back/forward).
  useEffect(() => {
    if (requested === activeId.current) return;
    activeId.current = requested;
    setError(null);
    setConsent(false);
    setConfidential(false);
    if (!requested) {
      setActive(null);
      setMessages([]);
      setDraft(EMPTY_DRAFT);
      return;
    }
    setLoadingThread(true);
    void (async () => {
      try {
        const known = chats.sessions.find((s) => s.id === requested);
        const [session, thread] = await Promise.all([
          known ? Promise.resolve(known) : api<Session[]>("/api/chat/sessions").then((all) => all.find((s) => s.id === requested) ?? null),
          api<Message[]>(`/api/chat/sessions/${requested}/messages`),
        ]);
        if (activeId.current !== requested) return;
        if (!session) {
          router.replace("/chat");
          return;
        }
        setActive(session);
        setMessages(thread);
      } catch (e) {
        setError(errorText(e));
      } finally {
        setLoadingThread(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested]);

  // Keep the open chat in step with renames and deletions from the sidebar.
  useEffect(() => {
    if (!active) return;
    const fresh = chats.sessions.find((s) => s.id === active.id);
    if (fresh && fresh !== active) setActive(fresh);
  }, [chats.sessions, active]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const settings: Draft = active ? { privacy_mode: active.privacy_mode, document_ids: active.document_ids, persist: active.persist } : draft;

  async function changeSettings(changes: Partial<Draft>) {
    if (!active) {
      setDraft((d) => ({ ...d, ...changes }));
      return;
    }
    try {
      const updated = await api<Session>(`/api/chat/sessions/${active.id}`, { method: "PATCH", json: changes });
      setActive(updated);
      chats.upsert(updated);
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function send() {
    const content = input.trim();
    if (!content || streaming) return;
    setError(null);
    setStreaming(true);
    setInput("");
    const controller = new AbortController();
    abort.current = controller;
    const pendingId = `pending-${Date.now()}`;
    try {
      let session = active;
      if (!session) {
        session = await api<Session>("/api/chat/sessions", { method: "POST", json: draft });
        activeId.current = session.id;
        setActive(session);
        chats.upsert(session);
        // update the address without remounting the page mid-stream
        window.history.replaceState(null, "", `/chat?c=${session.id}`);
      }
      const stamp = new Date().toISOString();
      setMessages((prev) => [
        ...prev,
        { id: `${pendingId}-u`, role: "user", content, event_id: null, meta: {}, created_at: stamp },
        { id: pendingId, role: "assistant", content: "", event_id: null, meta: { status: "streaming" }, created_at: stamp },
      ]);
      const update = (fn: (m: Message) => Message) => setMessages((prev) => prev.map((m) => (m.id === pendingId ? fn(m) : m)));
      await streamChat(
        session.id,
        { content, consent, confidential, model: pinned || null },
        (event) => {
          if (event.type === "route") {
            update((m) => ({ ...m, event_id: event.event_id, meta: { ...m.meta, model: event.model, explanation: event.explanation, sensitive: event.sensitive } }));
          } else if (event.type === "delta") {
            update((m) => ({ ...m, content: m.content + event.text }));
          } else {
            update((m) => ({ ...m, content: event.text, event_id: event.meta.event_id, meta: event.meta }));
          }
        },
        controller.signal,
      );
      setConsent(false); // consent covers one message only
      setConfidential(false);
      const list = await chats.refresh();
      const fresh = list.find((s) => s.id === session.id);
      if (fresh) setActive(fresh);
    } catch (e) {
      if (controller.signal.aborted) {
        setMessages((prev) => prev.map((m) => (m.id === pendingId ? { ...m, meta: { ...m.meta, status: "cancelled" } } : m)));
      } else {
        setMessages((prev) => prev.filter((m) => m.id !== pendingId || m.content));
        setError(errorText(e));
      }
    } finally {
      abort.current = null;
      setStreaming(false);
    }
  }

  async function deleteChat() {
    if (!active || !window.confirm("Delete this chat?")) return;
    await chats.remove(active.id);
    router.push("/chat");
  }

  const composer = (
    <Composer
      value={input}
      onChange={setInput}
      onSend={() => void send()}
      onStop={() => abort.current?.abort()}
      streaming={streaming}
      placeholder={active ? "Reply" : "Message"}
      settings={settings}
      onSettings={(c) => void changeSettings(c)}
      cloudOff={permissions ? !permissions.cloud_enabled : false}
      confidential={confidential}
      setConfidential={setConfidential}
      consent={consent}
      setConsent={setConsent}
      canConsent={!!permissions?.may_send_confidential_to_cloud}
      docs={docs}
      ocr={!!permissions?.ocr_enabled}
      onUploaded={(doc) => {
        setDocs((prev) => [doc, ...prev]);
        void changeSettings({ document_ids: [...settings.document_ids, doc.id] });
      }}
      onError={setError}
      models={permissions?.may_pin_model ? models : []}
      pinned={pinned}
      setPinned={setPinned}
      sensitive={!!active?.confidential}
    />
  );

  // New chat: greeting with the composer in the middle of the page.
  if (!active && !requested) {
    const first = (user?.name || "").split(" ")[0];
    return (
      <div className="flex h-full flex-col items-center justify-center px-4 pb-[12vh]">
        <h1 className="mb-8 flex items-center gap-3 text-center font-serif text-[2.1rem] font-normal tracking-tight text-slate-800 sm:text-[2.5rem]">
          <RouteMark size={34} className="text-brand-600" />
          {greeting()}
          {first ? `, ${first}` : ""}
        </h1>
        <div className="w-full max-w-2xl">
          {error && (
            <div className="mb-3">
              <Notice>{error}</Notice>
            </div>
          )}
          {composer}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <ChatHeader session={active} onRename={(t) => active && void chats.rename(active.id, t)} onDelete={() => void deleteChat()} />
      <div className="thin-scroll flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4 pb-8 pt-4">
          {loadingThread && !messages.length && <Spinner />}
          {messages.map((m) => (
            <MessageView key={m.id} message={m} />
          ))}
          <div ref={bottom} />
        </div>
      </div>
      <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4">
        {error && (
          <div className="mb-3">
            <Notice>{error}</Notice>
          </div>
        )}
        {composer}
      </div>
    </div>
  );
}

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Good evening" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

/* ------------------------------------------------------------------ header */

function ChatHeader({ session, onRename, onDelete }: { session: Session | null; onRename: (title: string) => void; onDelete: () => void }) {
  const menu = usePopover();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  if (!session) return <div className="h-12 shrink-0" />;

  function save() {
    setEditing(false);
    const next = title.trim();
    if (next && session && next !== session.title) onRename(next);
  }

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 px-4">
      <div ref={menu.ref} className="relative min-w-0">
        {editing ? (
          <input
            autoFocus
            className="input w-72 py-1"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
              if (e.key === "Escape") setEditing(false);
            }}
          />
        ) : (
          <button className="flex max-w-full items-center gap-1 rounded-lg px-2 py-1 text-sm text-slate-800 hover:bg-slate-100" onClick={() => menu.setOpen(!menu.open)}>
            <span className="truncate">{session.title}</span>
            <ChevronDownIcon size={15} className="shrink-0 text-slate-500" />
          </button>
        )}
        {menu.open && (
          <div className="menu left-0 top-9 min-w-[10rem]">
            <button
              className="menu-item"
              onClick={() => {
                menu.setOpen(false);
                setTitle(session.title);
                setEditing(true);
              }}
            >
              <PencilIcon size={15} /> Rename
            </button>
            <button
              className="menu-item text-red-700"
              onClick={() => {
                menu.setOpen(false);
                onDelete();
              }}
            >
              <TrashIcon size={15} /> Delete
            </button>
          </div>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2">
        {session.privacy_mode === "local_only" && <Pill>Local only</Pill>}
        {session.confidential && (
          <Pill tone="amber">
            <LockIcon size={12} /> Confidential
          </Pill>
        )}
      </div>
    </header>
  );
}

function Pill({ children, tone = "slate", onClear }: { children: React.ReactNode; tone?: "slate" | "amber" | "brand"; onClear?: () => void }) {
  const styles = { slate: "bg-slate-100 text-slate-700", amber: "bg-amber-100 text-amber-800", brand: "bg-brand-50 text-brand-700" }[tone];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${styles}`}>
      {children}
      {onClear && (
        <button onClick={onClear} className="-mr-1 rounded-full p-0.5 hover:bg-black/10" aria-label="Remove">
          <CloseIcon size={11} />
        </button>
      )}
    </span>
  );
}

/* ------------------------------------------------------------------ composer */

function Composer(props: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  placeholder: string;
  settings: Draft;
  onSettings: (changes: Partial<Draft>) => void;
  cloudOff: boolean;
  confidential: boolean;
  setConfidential: (v: boolean) => void;
  consent: boolean;
  setConsent: (v: boolean) => void;
  canConsent: boolean;
  docs: Doc[];
  ocr: boolean;
  onUploaded: (doc: Doc) => void;
  onError: (message: string) => void;
  models: Model[];
  pinned: string;
  setPinned: (v: string) => void;
  sensitive: boolean;
}) {
  const { settings, onSettings } = props;
  const box = useRef<HTMLTextAreaElement>(null);
  const localOnly = settings.privacy_mode === "local_only" || props.cloudOff;
  const attached = props.docs.filter((d) => settings.document_ids.includes(d.id));
  const showConsent = props.canConsent && !localOnly;

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [props.value]);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-3 pb-2.5 pt-3 shadow-[0_2px_12px_rgba(0,0,0,0.04)] transition focus-within:border-slate-300 focus-within:shadow-[0_2px_16px_rgba(0,0,0,0.07)]">
      {attached.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2 px-1">
          {attached.map((d) => (
            <span key={d.id} className="inline-flex max-w-[16rem] items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700">
              <FileIcon size={14} className="shrink-0 text-slate-500" />
              <span className="truncate">{d.filename}</span>
              {d.ocr_pages > 0 && <span className="text-slate-400">OCR</span>}
              <button
                onClick={() => onSettings({ document_ids: settings.document_ids.filter((id) => id !== d.id) })}
                className="rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-800"
                aria-label={`Remove ${d.filename}`}
              >
                <CloseIcon size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      <textarea
        ref={box}
        rows={1}
        className="block max-h-[260px] w-full resize-none bg-transparent px-1.5 py-1 text-[15px] leading-6 text-slate-900 outline-none placeholder:text-slate-400"
        placeholder={props.placeholder}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            props.onSend();
          }
        }}
      />
      <div className="mt-2 flex items-center gap-1.5">
        <AttachMenu
          docs={props.docs}
          selected={settings.document_ids}
          ocr={props.ocr}
          onToggle={(id) =>
            onSettings({ document_ids: settings.document_ids.includes(id) ? settings.document_ids.filter((x) => x !== id) : [...settings.document_ids, id] })
          }
          onUploaded={props.onUploaded}
          onError={props.onError}
        />
        <OptionsMenu
          localOnly={localOnly}
          cloudOff={props.cloudOff}
          setLocalOnly={(v) => onSettings({ privacy_mode: v ? "local_only" : "cloud_allowed" })}
          confidential={props.confidential}
          setConfidential={props.setConfidential}
          consent={props.consent}
          setConsent={props.setConsent}
          showConsent={showConsent}
          persist={settings.persist}
          setPersist={(v) => onSettings({ persist: v })}
        />
        <div className="flex min-w-0 flex-wrap gap-1.5">
          {localOnly && <Pill onClear={props.cloudOff ? undefined : () => onSettings({ privacy_mode: "cloud_allowed" })}>{props.cloudOff ? "Cloud off" : "Local only"}</Pill>}
          {props.confidential && (
            <Pill tone="amber" onClear={() => props.setConfidential(false)}>
              Confidential
            </Pill>
          )}
          {props.consent && showConsent && (
            <Pill tone="brand" onClear={() => props.setConsent(false)}>
              Consent
            </Pill>
          )}
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {props.models.length > 0 && <ModelMenu models={props.models} pinned={props.pinned} setPinned={props.setPinned} />}
          {props.streaming ? (
            <button onClick={props.onStop} className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-slate-50 transition hover:bg-slate-700" aria-label="Stop">
              <StopIcon size={16} />
            </button>
          ) : (
            <button
              onClick={props.onSend}
              disabled={!props.value.trim()}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-onbrand transition hover:bg-brand-700 disabled:opacity-40"
              aria-label="Send"
            >
              <ArrowUpIcon size={17} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function AttachMenu({
  docs,
  selected,
  ocr,
  onToggle,
  onUploaded,
  onError,
}: {
  docs: Doc[];
  selected: string[];
  ocr: boolean;
  onToggle: (id: string) => void;
  onUploaded: (doc: Doc) => void;
  onError: (message: string) => void;
}) {
  const menu = usePopover();
  const [uploading, setUploading] = useState(false);

  async function upload(file: File) {
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("label", "confidential"); // chat uploads are confidential by default
      onUploaded(await api<Doc>("/api/documents", { method: "POST", form }));
      menu.setOpen(false);
    } catch (e) {
      onError(errorText(e));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div ref={menu.ref} className="relative">
      <button className="icon-btn border border-slate-200" onClick={() => menu.setOpen(!menu.open)} aria-label="Add files" title="Add files">
        {uploading ? <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" /> : <PlusIcon size={17} />}
      </button>
      {menu.open && (
        <div className="menu bottom-10 left-0 w-72">
          <label className={`menu-item cursor-pointer ${uploading ? "opacity-50" : ""}`}>
            <UploadIcon size={15} /> {uploading ? "Reading" : "Upload file"}
            <input
              type="file"
              className="hidden"
              disabled={uploading}
              accept={ocr ? UPLOAD_TYPES : ".pdf,.txt"}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void upload(f);
              }}
            />
          </label>
          {docs.length > 0 && (
            <>
              <div className="my-1 border-t border-slate-200" />
              <div className="px-2.5 pb-1 pt-1 text-xs text-slate-500">Files</div>
              <div className="thin-scroll max-h-60 overflow-y-auto">
                {docs.map((d) => (
                  <button key={d.id} className="menu-item" onClick={() => onToggle(d.id)}>
                    <FileIcon size={15} className="shrink-0 text-slate-500" />
                    <span className="min-w-0 flex-1 truncate">{d.filename}</span>
                    {d.label === "confidential" && <LockIcon size={12} className="shrink-0 text-slate-400" />}
                    <span className="w-4 shrink-0">{selected.includes(d.id) && <CheckIcon size={15} className="text-brand-600" />}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function OptionsMenu(props: {
  localOnly: boolean;
  cloudOff: boolean;
  setLocalOnly: (v: boolean) => void;
  confidential: boolean;
  setConfidential: (v: boolean) => void;
  consent: boolean;
  setConsent: (v: boolean) => void;
  showConsent: boolean;
  persist: boolean;
  setPersist: (v: boolean) => void;
}) {
  const menu = usePopover();
  const row = (label: string, checked: boolean, onChange: (v: boolean) => void, disabled = false) => (
    <div className={`flex items-center justify-between gap-4 rounded-lg px-2.5 py-2 ${disabled ? "opacity-50" : ""}`}>
      <span className="text-slate-700">{label}</span>
      <Switch checked={checked} onChange={onChange} disabled={disabled} label={label} />
    </div>
  );
  return (
    <div ref={menu.ref} className="relative">
      <button className="icon-btn border border-slate-200" onClick={() => menu.setOpen(!menu.open)} aria-label="Options" title="Options">
        <SlidersIcon size={17} />
      </button>
      {menu.open && (
        <div className="menu bottom-10 left-0 w-64">
          {row("Local only", props.localOnly, props.setLocalOnly, props.cloudOff)}
          {row("Confidential", props.confidential, props.setConfidential)}
          {props.showConsent && row("Consent", props.consent, props.setConsent)}
          <div className="my-1 border-t border-slate-200" />
          {row("Keep history", props.persist, props.setPersist)}
        </div>
      )}
    </div>
  );
}

function ModelMenu({ models, pinned, setPinned }: { models: Model[]; pinned: string; setPinned: (v: string) => void }) {
  const menu = usePopover();
  const current = models.find((m) => m.name === pinned);
  const item = (value: string, label: string, sub: string) => (
    <button
      key={value || "auto"}
      className="menu-item"
      onClick={() => {
        setPinned(value);
        menu.setOpen(false);
      }}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-slate-900">{label}</span>
        <span className="block text-xs text-slate-500">{sub}</span>
      </span>
      {pinned === value && <CheckIcon size={15} className="shrink-0 text-brand-600" />}
    </button>
  );
  return (
    <div ref={menu.ref} className="relative">
      <button className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm text-slate-700 hover:bg-slate-100" onClick={() => menu.setOpen(!menu.open)}>
        {current ? current.display_name || current.name : "Auto"}
        <ChevronDownIcon size={14} className="text-slate-500" />
      </button>
      {menu.open && (
        <div className="menu bottom-10 right-0 w-64">
          {item("", "Auto", "Best route per message")}
          <div className="my-1 border-t border-slate-200" />
          {models.map((m) => item(m.name, m.display_name || m.name, `${TIER[m.tier] ?? m.tier} · ${m.is_local ? "Local" : "Cloud"}`))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ messages */

function MessageView({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end py-3">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-bubble px-4 py-2.5 text-[15px] leading-6 text-slate-900">{message.content}</div>
      </div>
    );
  }
  const meta = message.meta as Partial<RouteMeta>;
  const status = meta.status ?? "ok";
  const refused = status === "abstained";
  const failed = ["failed", "empty", "refused"].includes(status);

  if (status === "streaming" && !message.content) {
    return (
      <div className="py-4">
        <RouteMark size={24} className="animate-pulse text-brand-600" />
      </div>
    );
  }
  return (
    <div className="group py-3">
      {refused || failed ? (
        <div className={`flex gap-2.5 rounded-xl border px-4 py-3 text-sm ${refused ? "border-amber-200 bg-amber-50 text-amber-900" : "border-red-200 bg-red-50 text-red-900"}`}>
          <LockIcon size={16} className="mt-0.5 shrink-0" />
          <span className="whitespace-pre-wrap">{message.content || meta.error || "No answer"}</span>
        </div>
      ) : (
        <div className="whitespace-pre-wrap font-serif text-[16.5px] leading-[1.7] text-slate-900">
          {message.content}
          {status === "streaming" && <span className="ml-0.5 inline-block h-4 w-2 animate-pulse rounded-sm bg-brand-600 align-middle" />}
        </div>
      )}
      {status !== "streaming" && <MessageActions message={message} meta={meta} />}
    </div>
  );
}

function MessageActions({ message, meta }: { message: Message; meta: Partial<RouteMeta> }) {
  const [panel, setPanel] = useState<"none" | "details" | "rate">("none");
  const [copied, setCopied] = useState(false);
  const ok = meta.status === "ok" || meta.status === "truncated";

  async function copy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  }

  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-1 text-xs text-slate-500">
        {ok && (
          <button className="icon-btn h-7 w-7" onClick={() => void copy()} aria-label="Copy" title="Copy">
            {copied ? <CheckIcon size={15} /> : <CopyIcon size={15} />}
          </button>
        )}
        {ok && message.event_id && (
          <button className={`icon-btn h-7 w-7 ${panel === "rate" ? "bg-slate-100 text-slate-900" : ""}`} onClick={() => setPanel(panel === "rate" ? "none" : "rate")} aria-label="Rate" title="Rate">
            <StarIcon size={15} />
          </button>
        )}
        <button className={`icon-btn h-7 w-7 ${panel === "details" ? "bg-slate-100 text-slate-900" : ""}`} onClick={() => setPanel(panel === "details" ? "none" : "details")} aria-label="Details" title="Details">
          <InfoIcon size={15} />
        </button>
        <span className="ml-1.5 flex flex-wrap items-center gap-1.5">
          {meta.model && <span className="text-slate-600">{meta.model}</span>}
          {meta.is_local === true && <span>· Local</span>}
          {meta.is_local === false && <span>· Cloud</span>}
          {meta.sensitive && <Badge tone="amber">{meta.entity_types?.length ? meta.entity_types.join(", ") : "Confidential"}</Badge>}
          {meta.follow_up && <Badge>Follow-up</Badge>}
          {meta.cache_hit && <Badge>Cache</Badge>}
          {meta.status === "truncated" && <Badge tone="amber">Truncated</Badge>}
          {meta.status === "cancelled" && <Badge>Stopped</Badge>}
        </span>
      </div>
      {panel === "details" && <RouteDetails meta={meta} />}
      {panel === "rate" && message.event_id && <Feedback eventId={message.event_id} onDone={() => setPanel("none")} />}
    </div>
  );
}

function RouteDetails({ meta }: { meta: Partial<RouteMeta> }) {
  const excluded = Object.entries(meta.exclusions ?? {});
  const rows: [string, React.ReactNode][] = [
    ["Decision", `${meta.explanation || "–"} · ${meta.policy ?? ""}${meta.policy_version ? ` v${meta.policy_version}` : ""}`],
  ];
  if (excluded.length) rows.push(["Excluded", excluded.map(([n, r]) => `${n} (${r.replace(/^(privacy|final_gate|attempt):/, "").replace(/_/g, " ")})`).join(", ")]);
  if (meta.model) rows.push(["Usage", `${fmtMs(meta.latency_ms)} · ${fmtUsd(meta.cost_usd, 5)} · ${meta.in_tokens ?? 0} in / ${meta.out_tokens ?? 0} out`]);
  if ((meta.history_messages ?? 0) > 0) rows.push(["Context", `${HISTORY_MODES[meta.history_mode ?? "full"]} · ${meta.history_sent}/${meta.history_messages}`]);
  if (meta.sources?.length) rows.push(["Sources", meta.sources.map((s) => `[${s.n}] ${s.document} p.${s.page}`).join("; ")]);
  if (meta.fallback_from) rows.push(["Retry", `${meta.fallback_from} · ${meta.attempts} attempts`]);
  rows.push(["Timing", `First token ${fmtMs(meta.ttft_ms)} · routing ${fmtMs(meta.routing_overhead_ms)}${(meta.cache_read_tokens ?? 0) > 0 ? ` · cached ${meta.cache_read_tokens}` : ""}`]);
  if (meta.notices?.length) rows.push(["Notes", meta.notices.join(" ")]);
  if (meta.error) rows.push(["Error", meta.error]);
  return (
    <dl className="mt-2 grid grid-cols-[84px_1fr] gap-x-3 gap-y-1.5 rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-600">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="font-medium text-slate-800">{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Feedback({ eventId, onDone }: { eventId: string; onDone: () => void }) {
  const [scores, setScores] = useState<Record<string, number>>({ correctness: 4, relevance: 4, completeness: 4, usefulness: 4 });
  const [state, setState] = useState<"idle" | "saving" | "done" | string>("idle");

  async function submit() {
    setState("saving");
    try {
      await api("/api/feedback", { method: "POST", json: { event_id: eventId, ...scores } });
      setState("done");
      setTimeout(onDone, 900);
    } catch (e) {
      setState(errorText(e));
    }
  }

  if (state === "done") return <div className="mt-2 text-xs text-emerald-700">Thanks</div>;
  return (
    <div className="mt-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs">
      <div className="grid gap-2 sm:grid-cols-2">
        {DIMENSIONS.map((d) => (
          <div key={d} className="flex items-center justify-between gap-3">
            <span className="capitalize text-slate-600">{d}</span>
            <span className="inline-flex overflow-hidden rounded-lg border border-slate-200">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  onClick={() => setScores({ ...scores, [d]: n })}
                  className={`h-7 w-7 ${scores[d] === n ? "bg-brand-600 font-semibold text-onbrand" : "text-slate-600 hover:bg-slate-100"}`}
                >
                  {n}
                </button>
              ))}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <Button onClick={() => void submit()} disabled={state === "saving"} className="px-3 py-1.5 text-xs">
          Submit
        </Button>
        {state !== "idle" && state !== "saving" && <span className="text-red-600">{state}</span>}
      </div>
    </div>
  );
}
