"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, Field, Notice, PageHeader, Table, Toggle, errorText } from "@/components/ui";
import { api, fmtMs, fmtTime } from "@/lib/api";
import type { Model, Vendor } from "@/lib/types";

const EMPTY = {
  name: "",
  display_name: "",
  vendor: "anthropic",
  model_id: "",
  tier: "cheap" as Model["tier"],
  base_url: "",
  context_window: 128000,
  max_output_tokens: 4096,
  price_in_per_mtok: 0,
  price_out_per_mtok: 0,
  params: "{}",
};
const TIER: Record<Model["tier"], string> = { local: "Local", cheap: "Cheap", strong: "Strong" };

export default function ModelsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState<Model | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const [m, v] = await Promise.all([api<Model[]>("/api/models"), api<Vendor[]>("/api/vendors")]);
    setModels(m);
    setVendors(v);
  }
  useEffect(() => {
    load().catch((e) => setError(errorText(e)));
  }, []);

  function parseParams(text: string): Record<string, unknown> {
    const value = JSON.parse(text || "{}");
    if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("Options must be a JSON object");
    return value as Record<string, unknown>;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const params = parseParams(form.params);
      if (editing) {
        await api(`/api/models/${editing.id}`, {
          method: "PATCH",
          json: {
            display_name: form.display_name,
            model_id: form.model_id,
            tier: form.tier,
            base_url: form.base_url || null,
            context_window: form.context_window,
            max_output_tokens: form.max_output_tokens,
            price_in_per_mtok: form.price_in_per_mtok,
            price_out_per_mtok: form.price_out_per_mtok,
            params,
          },
        });
      } else {
        const adapter = vendors.find((v) => v.id === form.vendor)?.adapter;
        await api("/api/models", { method: "POST", json: { ...form, base_url: form.base_url || null, params, is_local: adapter === "ollama" || form.tier === "local" } });
      }
      setForm(EMPTY);
      setEditing(null);
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  function edit(m: Model) {
    setEditing(m);
    setForm({
      name: m.name,
      display_name: m.display_name,
      vendor: m.vendor,
      model_id: m.model_id,
      tier: m.tier,
      base_url: m.base_url ?? "",
      context_window: m.context_window,
      max_output_tokens: m.max_output_tokens,
      price_in_per_mtok: m.price_in_per_mtok,
      price_out_per_mtok: m.price_out_per_mtok,
      params: JSON.stringify(m.params ?? {}, null, 2),
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  const num = (key: "context_window" | "max_output_tokens" | "price_in_per_mtok" | "price_out_per_mtok") => ({
    className: "input",
    type: "number",
    step: "any",
    min: 0,
    value: form[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: Number(e.target.value) }),
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Models" />
      {error && <Notice>{error}</Notice>}

      <Card title={editing ? `Edit ${editing.name}` : "Add"}>
        <form onSubmit={submit} className="grid gap-4 md:grid-cols-4">
          <Field label="Name">
            <input className="input" required disabled={!!editing} pattern="[a-z0-9][a-z0-9._\-]{1,62}" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Display">
            <input className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          </Field>
          <Field label="Provider">
            <select className="input" disabled={!!editing} value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })}>
              {vendors.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Model ID">
            <input className="input" required value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })} />
          </Field>
          <Field label="Tier">
            <select className="input" value={form.tier} onChange={(e) => setForm({ ...form, tier: e.target.value as Model["tier"] })}>
              <option value="local">Local</option>
              <option value="cheap">Cheap</option>
              <option value="strong">Strong</option>
            </select>
          </Field>
          <Field label="Context">
            <input {...num("context_window")} />
          </Field>
          <Field label="Max output">
            <input {...num("max_output_tokens")} />
          </Field>
          <Field label="Endpoint">
            <input className="input" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
          </Field>
          <Field label="Input $/1M">
            <input {...num("price_in_per_mtok")} />
          </Field>
          <Field label="Output $/1M">
            <input {...num("price_out_per_mtok")} />
          </Field>
          <div className="md:col-span-2">
            <Field label="Options (JSON)">
              <textarea className="input font-mono text-xs" rows={3} value={form.params} onChange={(e) => setForm({ ...form, params: e.target.value })} />
            </Field>
          </div>
          <div className="flex gap-2 md:col-span-4">
            <Button type="submit">{editing ? "Save" : "Add"}</Button>
            {editing && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setEditing(null);
                  setForm(EMPTY);
                }}
              >
                Cancel
              </Button>
            )}
          </div>
        </form>
      </Card>

      <Card title="Registry">
        <Table head={["Model", "Provider", "Tier", "Price in / out", "Context", "Latency", "Health", "On", ""]} empty={!models.length}>
          {models.map((m) => {
            const unhealthy = m.unhealthy_until && new Date(`${m.unhealthy_until}Z`) > new Date();
            return (
              <tr key={m.id}>
                <td className="td">
                  <div className="font-medium text-slate-900">{m.display_name || m.name}</div>
                  <div className="font-mono text-xs text-slate-500">{m.model_id}</div>
                </td>
                <td className="td">{vendors.find((v) => v.id === m.vendor)?.label ?? m.vendor}</td>
                <td className="td">
                  <Badge tone={m.is_local ? "green" : m.tier === "strong" ? "blue" : "slate"}>{TIER[m.tier]}</Badge>
                </td>
                <td className="td whitespace-nowrap">
                  ${m.price_in_per_mtok} / ${m.price_out_per_mtok}
                  <div className="text-xs text-slate-500">{fmtTime(m.price_updated_at).split(",")[0]}</div>
                </td>
                <td className="td">{m.context_window.toLocaleString()}</td>
                <td className="td">{fmtMs(m.latency_ewma_ms)}</td>
                <td className="td">
                  {unhealthy ? <Badge tone="red">Paused</Badge> : <Badge tone="green">OK</Badge>}
                  {m.last_error && (
                    <div className="mt-1 max-w-[14rem] truncate text-xs text-slate-500" title={m.last_error}>
                      {m.last_error}
                    </div>
                  )}
                </td>
                <td className="td">
                  <Toggle checked={m.enabled} label="" onChange={(v) => void act(() => api(`/api/models/${m.id}`, { method: "PATCH", json: { enabled: v } }))} />
                </td>
                <td className="td whitespace-nowrap text-right">
                  <Button variant="ghost" onClick={() => edit(m)}>
                    Edit
                  </Button>
                  {m.last_error && (
                    <Button variant="ghost" onClick={() => void act(() => api(`/api/models/${m.id}/reset-health`, { method: "POST" }))}>
                      Reset
                    </Button>
                  )}
                  <Button
                    variant="danger"
                    onClick={() => {
                      if (window.confirm(`Remove ${m.name}?`)) void act(() => api(`/api/models/${m.id}`, { method: "DELETE" }));
                    }}
                  >
                    Remove
                  </Button>
                </td>
              </tr>
            );
          })}
        </Table>
      </Card>
    </div>
  );
}
