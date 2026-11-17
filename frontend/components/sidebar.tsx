"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Avatar, usePopover } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { useChats } from "@/lib/chats";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import type { Session } from "@/lib/types";
import {
  ChatsIcon,
  CheckIcon,
  DotsIcon,
  LockIcon,
  LogoutIcon,
  MoonIcon,
  PencilIcon,
  PlusIcon,
  SettingsIcon,
  SidebarIcon,
  SunIcon,
  TrashIcon,
} from "@/components/icons";

const KEY = "smartroute.sidebar";

export function Sidebar() {
  const [open, setOpen] = useState(true);

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem(KEY);
    } catch {
      /* storage blocked */
    }
    setOpen(stored ? stored === "open" : window.innerWidth >= 768);
  }, []);

  function toggle() {
    const next = !open;
    setOpen(next);
    try {
      localStorage.setItem(KEY, next ? "open" : "closed");
    } catch {
      /* storage blocked */
    }
  }

  return (
    <>
      {/* collapsed rail, always present so the toggle never disappears */}
      <aside className={`flex w-[52px] shrink-0 flex-col items-center gap-1 border-r border-slate-200 bg-sidebar py-2.5 ${open ? "max-md:flex md:hidden" : ""}`}>
        <button className="icon-btn" onClick={toggle} aria-label="Open sidebar" title="Open sidebar">
          <SidebarIcon />
        </button>
        <Link href="/chat" className="mt-1 inline-flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-onbrand transition hover:bg-brand-700" aria-label="New chat" title="New chat">
          <PlusIcon size={16} />
        </Link>
        <button className="icon-btn" onClick={toggle} aria-label="Chats" title="Chats">
          <ChatsIcon />
        </button>
        <div className="mt-auto">
          <AccountMenu compact />
        </div>
      </aside>

      {open && (
        <>
          <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={toggle} />
          <aside className="fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col border-r border-slate-200 bg-sidebar md:static md:z-auto">
            <div className="flex items-center gap-2 px-3 pb-2 pt-2.5">
              <button className="icon-btn" onClick={toggle} aria-label="Close sidebar" title="Close sidebar">
                <SidebarIcon />
              </button>
              <Link href="/chat" className="flex items-center gap-1.5 font-serif text-[19px] font-medium tracking-tight text-slate-900">
                SmartRoute
              </Link>
            </div>
            <div className="px-2">
              <Link href="/chat" className="group flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm font-medium text-brand-700 hover:bg-sidebar-active">
                <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-brand-600 text-onbrand transition group-hover:scale-105">
                  <PlusIcon size={14} />
                </span>
                New chat
              </Link>
            </div>
            <ChatList onNavigate={() => window.innerWidth < 768 && toggle()} />
            <div className="border-t border-slate-200 p-2">
              <AccountMenu />
            </div>
          </aside>
        </>
      )}
    </>
  );
}

function ChatList({ onNavigate }: { onNavigate: () => void }) {
  const { sessions, loaded } = useChats();
  const pathname = usePathname();
  const params = useSearchParams();
  const current = pathname === "/chat" ? params.get("c") : null;
  return (
    <div className="thin-scroll mt-3 flex-1 overflow-y-auto px-2 pb-2">
      <div className="px-2 pb-1 text-xs font-medium text-slate-500">Recents</div>
      {sessions.map((s) => (
        <ChatRow key={s.id} session={s} active={s.id === current} onNavigate={onNavigate} />
      ))}
      {loaded && !sessions.length && <p className="px-2 py-1.5 text-sm text-slate-400">No chats yet</p>}
    </div>
  );
}

function ChatRow({ session, active, onNavigate }: { session: Session; active: boolean; onNavigate: () => void }) {
  const { rename, remove } = useChats();
  const router = useRouter();
  const menu = usePopover();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(session.title);

  async function saveTitle() {
    setEditing(false);
    const next = title.trim();
    if (next && next !== session.title) await rename(session.id, next).catch(() => setTitle(session.title));
    else setTitle(session.title);
  }

  async function del() {
    menu.setOpen(false);
    if (!window.confirm("Delete this chat?")) return;
    await remove(session.id);
    if (active) router.push("/chat");
  }

  if (editing) {
    return (
      <input
        autoFocus
        className="input my-0.5 py-1.5"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={() => void saveTitle()}
        onKeyDown={(e) => {
          if (e.key === "Enter") void saveTitle();
          if (e.key === "Escape") {
            setTitle(session.title);
            setEditing(false);
          }
        }}
      />
    );
  }

  return (
    <div ref={menu.ref} className={`group relative flex items-center rounded-lg ${active ? "bg-sidebar-active" : "hover:bg-sidebar-active"}`}>
      <Link
        href={`/chat?c=${session.id}`}
        onClick={onNavigate}
        className={`flex min-w-0 flex-1 items-center gap-1.5 px-2 py-1.5 text-sm ${active ? "text-slate-900" : "text-slate-700"}`}
        title={session.title}
      >
        <span className="truncate">{session.title}</span>
        {session.confidential && <LockIcon size={12} className="shrink-0 text-slate-400" aria-label="Confidential" />}
      </Link>
      <button
        className={`mr-1 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-500 hover:bg-slate-200 hover:text-slate-900 ${menu.open ? "visible" : "invisible group-hover:visible"}`}
        onClick={() => menu.setOpen(!menu.open)}
        aria-label="Chat options"
      >
        <DotsIcon size={16} />
      </button>
      {menu.open && (
        <div className="menu right-0 top-8 min-w-[10rem]">
          <button
            className="menu-item"
            onClick={() => {
              menu.setOpen(false);
              setEditing(true);
            }}
          >
            <PencilIcon size={15} /> Rename
          </button>
          <button className="menu-item text-red-700" onClick={() => void del()}>
            <TrashIcon size={15} /> Delete
          </button>
        </div>
      )}
    </div>
  );
}

function AccountMenu({ compact = false }: { compact?: boolean }) {
  const { user, logout } = useAuth();
  const theme = useTheme();
  const menu = usePopover();
  if (!user) return null;
  const name = user.name || user.email;
  const themes: [ThemeChoice, string, React.ReactNode][] = [
    ["light", "Light", <SunIcon key="l" size={15} />],
    ["dark", "Dark", <MoonIcon key="d" size={15} />],
    ["system", "System", <SettingsIcon key="s" size={15} />],
  ];

  return (
    <div ref={menu.ref} className="relative">
      <button
        className={`flex items-center gap-2.5 rounded-lg text-left transition hover:bg-sidebar-active ${compact ? "p-1" : "w-full px-2 py-1.5"}`}
        onClick={() => menu.setOpen(!menu.open)}
        aria-label="Account"
        title={compact ? name : undefined}
      >
        <Avatar name={name} />
        {!compact && (
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-slate-900">{name}</span>
            <span className="block text-xs capitalize text-slate-500">{user.role}</span>
          </span>
        )}
      </button>
      {menu.open && (
        <div className={`menu bottom-full mb-2 w-60 ${compact ? "left-0" : "left-0 right-0"}`}>
          <div className="truncate px-2.5 pb-1.5 pt-1 text-xs text-slate-500">{user.email}</div>
          <Link href="/settings" className="menu-item" onClick={() => menu.setOpen(false)}>
            <SettingsIcon size={15} /> Settings
          </Link>
          <div className="my-1 border-t border-slate-200" />
          {themes.map(([value, label, icon]) => (
            <button key={value} className="menu-item" onClick={() => theme.set(value)}>
              {icon}
              <span className="flex-1">{label}</span>
              {theme.choice === value && <CheckIcon size={15} className="text-brand-600" />}
            </button>
          ))}
          <div className="my-1 border-t border-slate-200" />
          <button className="menu-item" onClick={logout}>
            <LogoutIcon size={15} /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

