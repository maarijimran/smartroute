"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, Field, Notice, PageHeader, Table, Toggle, errorText } from "@/components/ui";
import { api, fmtMs, fmtTime } from "@/lib/api";
import type { Model, Tier, TierSlot, Vendor } from "@/lib/types";

const TIERS: { tier: Tier; title: string; hint: string }[] = [
  { tier: "local", title: "Local", hint: "Runs on this server. Confidential requests stay here." },
  { tier: "cheap", title: "Cheap", hint: "Low-cost model for everyday requests." },
  { tier: "strong", title: "Strong", hint: "Most capable model for hard requests." },
];

type Form = {
  vendor: string;
  model_id: string;
  display_name: string;
  base_url: string;
  api_version: string;
  api_key: string;
  context_window: number;
  max_output_tokens: number;
  price_in_per_mtok: number;
  price_out_per_mtok: number;
};

function formFor(slot: TierSlot): Form {
  const m = slot.model;
  const configured = slot.configured && m;
  return {
    vendor: configured ? m.vendor : slot.tier === "local" ? "ollama" : "openai",
    model_id: configured ? m.model_id : "",
    display_name: configured ? m.display_name : "",
    base_url: (configured && m.base_url) || "",
    api_version: slot.api_version ?? "",
    api_key: "",
    context_window: configured ? m.context_window : slot.tier === "local" ? 8192 : 128000,
    max_output_tokens: configured ? m.max_output_tokens : 2048,
    price_in_per_mtok: configured ? m.price_in_per_mtok : 0,
    price_out_per_mtok: configured ? m.price_out_per_mtok : 0,
  };
}

function TierCard({ slot, title, hint, vendors, onSaved }: { slot: TierSlot; title: string; hint: string; vendors: Vendor[]; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState<Form>(() => formFor(slot));
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => setForm(formFor(slot)), [slot]);

  const m = slot.model;
  const choices = vendors.filter((v) => (slot.tier === "local" ? v.adapter === "ollama" || v.adapter === "mock" : true));
  const preset = vendors.find((v) => v.id === form.vendor);
  const keyKept = slot.key_vendor === form.vendor && !!slot.key_hint;
  const isCloud = preset ? preset.adapter !== "ollama" && preset.adapter !== "mock" : false;
  const unhealthy = m?.unhealthy_until && new Date(`${m.unhealthy_until}Z`) > new Date();
  const set = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm((f) => {
      const next = { ...f, [key]: value };
      // A new provider or model should not keep showing the previous model's name.
      if ((key === "vendor" || key === "model_id") && m && f.display_name === m.display_name) next.display_name = "";
      return next;
    });
  const num = (key: "context_window" | "max_output_tokens" | "price_in_per_mtok" | "price_out_per_mtok") => ({
    className: "input",
    type: "number",
    step: "any",
    min: 0,
    value: form[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => set(key, Number(e.target.value)),
  });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    const switching = slot.configured && m && (m.vendor !== form.vendor || m.model_id !== form.model_id.trim());
    if (switching && !window.confirm(`Switch ${title.toLowerCase()} to ${form.model_id}? It keeps the trained ${title.toLowerCase()} weights.`)) return;
    setBusy(true);
    try {
      await api(`/api/tiers/${slot.tier}`, {
        method: "PUT",
        json: {
          ...form,
          base_url: form.base_url.trim() || null,
          api_version: form.vendor === "azure_openai" ? form.api_version.trim() || null : null,
          api_key: form.api_key.trim() || null,
        },
      });
      setSaved(true);
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  const status = !slot.configured ? (
    <Badge>Not set</Badge>
  ) : !m?.enabled ? (
    <Badge>Off</Badge>
  ) : unhealthy ? (
    <Badge tone="red">Paused</Badge>
  ) : (
    <Badge tone="green">On</Badge>
  );

  return (
    <Card
      title={title}
      action={
        <div className="flex items-center gap-3">
          {status}
          {slot.configured && m && (
            <Toggle checked={m.enabled} label="" onChange={(v) => void act(() => api(`/api/models/${m.id}`, { method: "PATCH", json: { enabled: v } }))} />
          )}
        </div>
      }
    >
      <p className="-mt-1 mb-4 text-sm text-slate-500">{hint}</p>
      {error && (
        <div className="mb-4">
          <Notice>{error}</Notice>
        </div>
      )}
      <form onSubmit={save} className="grid gap-4 md:grid-cols-3">
        <Field label="Provider">
          <select className="input" value={form.vendor} onChange={(e) => set("vendor", e.target.value)}>
            {choices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Model">
          <input className="input font-mono" required value={form.model_id} placeholder={isCloud ? "Provider's model ID" : "e.g. gpt-oss:20b"} onChange={(e) => set("model_id", e.target.value)} />
        </Field>
        <Field label="Name">
          <input className="input" value={form.display_name} placeholder={form.model_id || "Shown in the model picker"} onChange={(e) => set("display_name", e.target.value)} />
        </Field>
        {preset?.needs_key ? (
          <Field label="Key">
            <input
              className="input"
              type="password"
              autoComplete="off"
              required={!keyKept}
              minLength={4}
              value={form.api_key}
              placeholder={keyKept ? `••••${slot.key_hint} (kept if empty)` : "Required"}
              onChange={(e) => set("api_key", e.target.value)}
            />
          </Field>
        ) : null}
        <Field label="Endpoint">
          <input
            className="input"
            value={form.base_url}
            required={preset?.needs_base_url}
            placeholder={preset?.default_base_url ?? (preset?.needs_base_url ? "https://" : "Default")}
            onChange={(e) => set("base_url", e.target.value)}
          />
        </Field>
        {form.vendor === "azure_openai" && (
          <Field label="Version">
            <input className="input" value={form.api_version} placeholder="2024-10-21" onChange={(e) => set("api_version", e.target.value)} />
          </Field>
        )}
        <Field label="Context">
          <input {...num("context_window")} />
        </Field>
        <Field label="Max output">
          <input {...num("max_output_tokens")} />
        </Field>
        {slot.tier !== "local" && (
          <>
            <Field label="Input $/1M">
              <input {...num("price_in_per_mtok")} />
            </Field>
            <Field label="Output $/1M">
              <input {...num("price_out_per_mtok")} />
            </Field>
          </>
        )}
        <div className="flex flex-wrap items-center gap-3 md:col-span-3">
          <Button type="submit" disabled={busy}>
            Save
          </Button>
          {saved && <span className="text-sm text-emerald-700">Saved</span>}
          {m && slot.configured && (
            <span className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
              <span>Latency {fmtMs(m.latency_ewma_ms)}</span>
              {slot.tier !== "local" && <span>Prices {fmtTime(m.price_updated_at).split(",")[0]}</span>}
              {m.last_error && (
                <span className="max-w-[18rem] truncate" title={m.last_error}>
                  {m.last_error}
                </span>
              )}
              {m.last_error && (
                <Button type="button" variant="ghost" onClick={() => void act(() => api(`/api/models/${m.id}/reset-health`, { method: "POST" }))}>
                  Reset
                </Button>
              )}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}

export default function ModelsPage() {
  const [slots, setSlots] = useState<TierSlot[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [mocks, setMocks] = useState<Model[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const [t, v, m] = await Promise.all([api<TierSlot[]>("/api/tiers"), api<Vendor[]>("/api/vendors"), api<Model[]>("/api/models")]);
    setSlots(t);
    setVendors(v);
    setMocks(m.filter((x) => x.name.startsWith("mock-")));
  }
  useEffect(() => {
    load().catch((e) => setError(errorText(e)));
  }, []);

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Models" subtitle="One model per tier. Changing a tier's model keeps its trained routing." />
      {error && <Notice>{error}</Notice>}
      {TIERS.map(({ tier, title, hint }) => {
        const slot = slots.find((s) => s.tier === tier);
        return slot ? <TierCard key={tier} slot={slot} title={title} hint={hint} vendors={vendors} onSaved={load} /> : null;
      })}
      {mocks.length > 0 && (
        <Card title="Development">
          <Table head={["Model", "Tier", ""]}>
            {mocks.map((m) => (
              <tr key={m.id}>
                <td className="td font-medium text-slate-900">{m.display_name || m.name}</td>
                <td className="td capitalize">{m.tier}</td>
                <td className="td text-right">
                  <Toggle checked={m.enabled} label="" onChange={(v) => void act(() => api(`/api/models/${m.id}`, { method: "PATCH", json: { enabled: v } }))} />
                </td>
              </tr>
            ))}
          </Table>
        </Card>
      )}
    </div>
  );
}
