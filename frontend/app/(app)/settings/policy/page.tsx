"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, Field, Notice, PageHeader, Spinner, Table, Toggle, errorText } from "@/components/ui";
import { api, fmtTime } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { LearnerVersion, Policy, PolicyChange } from "@/lib/types";

const ENTITY_TYPES: [string, string][] = [
  ["PERSON", "Names"],
  ["EMAIL", "Email"],
  ["PHONE", "Phone"],
  ["NATIONAL_ID", "CNIC"],
  ["CREDIT_CARD", "Card"],
  ["BANK_ACCOUNT", "Bank"],
  ["ADDRESS", "Address"],
  ["OTHER", "Other"],
];
const ROUTERS: { value: Policy["routing_policy"]; label: string }[] = [
  { value: "rules", label: "Rules" },
  { value: "frozen", label: "Frozen" },
  { value: "bandit", label: "ε-greedy" },
  { value: "linucb", label: "LinUCB" },
];

function Num({ label, value, onChange, step = "any", disabled }: { label: string; value: number | null; onChange: (v: number) => void; step?: string; disabled: boolean }) {
  return (
    <Field label={label}>
      <input className="input" type="number" step={step} disabled={disabled} value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))} />
    </Field>
  );
}

export default function PolicyPage() {
  const { user } = useAuth();
  const readOnly = user?.role !== "superadmin";
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [saved, setSaved] = useState<Policy | null>(null);
  const [history, setHistory] = useState<PolicyChange[]>([]);
  const [learner, setLearner] = useState<LearnerVersion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const [p, h, l] = await Promise.all([api<Policy>("/api/policy"), api<PolicyChange[]>("/api/policy/history?limit=30"), api<LearnerVersion[]>("/api/policy/learner")]);
    setPolicy(p);
    setSaved(p);
    setHistory(h);
    setLearner(l);
  }
  useEffect(() => {
    load().catch((e) => setError(errorText(e)));
  }, []);

  if (!policy)
    return error ? (
      <div>
        <Notice>{error}</Notice>
      </div>
    ) : (
      <Spinner />
    );
  const set = <K extends keyof Policy>(key: K, value: Policy[K]) => setPolicy({ ...policy, [key]: value });
  const dirty = JSON.stringify(policy) !== JSON.stringify(saved);
  const weightSum = policy.weights.quality + policy.weights.cost + policy.weights.latency;

  async function save() {
    setError(null);
    setMessage(null);
    try {
      await api("/api/policy", { method: "PUT", json: policy });
      await load();
      setMessage("Saved");
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function learnerAction(path: string, body?: unknown) {
    setError(null);
    setMessage(null);
    try {
      await api(path, { method: "POST", json: body ?? {} });
      setMessage("Done");
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Policy"
        action={
          readOnly ? (
            <Badge>Read only</Badge>
          ) : (
            <Button onClick={() => void save()} disabled={!dirty || Math.abs(weightSum - 1) > 1e-6}>
              Save
            </Button>
          )
        }
      />
      {error && <Notice>{error}</Notice>}
      {message && <Notice tone="green">{message}</Notice>}

      <Card title="Privacy">
        <div className="grid gap-3 md:grid-cols-2">
          <Toggle checked={policy.cloud_enabled} disabled={readOnly} onChange={(v) => set("cloud_enabled", v)} label="Cloud" />
          <Toggle checked={policy.allow_confidential_cloud_default} disabled={readOnly} onChange={(v) => set("allow_confidential_cloud_default", v)} label="Confidential to cloud" />
          <Toggle checked={policy.require_consent_for_confidential} disabled={readOnly} onChange={(v) => set("require_consent_for_confidential", v)} label="Consent" />
          <Toggle checked={policy.exempt_person_in_public_documents} disabled={readOnly} onChange={(v) => set("exempt_person_in_public_documents", v)} label="Ignore names in public files" />
        </div>
        <div className="mt-4 text-xs font-medium uppercase tracking-wide text-slate-500">Detect</div>
        <div className="mt-2 flex flex-wrap gap-4">
          {ENTITY_TYPES.map(([t, name]) => (
            <label key={t} className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                className="accent-brand-600"
                disabled={readOnly}
                checked={policy.blocking_entity_types.includes(t)}
                onChange={(e) => set("blocking_entity_types", e.target.checked ? [...policy.blocking_entity_types, t] : policy.blocking_entity_types.filter((x) => x !== t))}
              />
              {name}
            </label>
          ))}
        </div>
      </Card>

      <Card title="Access">
        <div className="grid gap-3 md:grid-cols-3">
          <Toggle checked={policy.allow_self_registration} disabled={readOnly} onChange={(v) => set("allow_self_registration", v)} label="Registration" />
          <Toggle checked={policy.allow_platform_credentials} disabled={readOnly} onChange={(v) => set("allow_platform_credentials", v)} label="Shared keys" />
          <Toggle checked={policy.users_may_pin_model} disabled={readOnly} onChange={(v) => set("users_may_pin_model", v)} label="Model choice" />
        </div>
      </Card>

      <Card title="Routing">
        <div className="inline-flex overflow-hidden rounded-lg border border-slate-200 text-sm">
          {ROUTERS.map((r) => (
            <button
              key={r.value}
              disabled={readOnly}
              onClick={() => set("routing_policy", r.value)}
              className={`px-4 py-2 disabled:cursor-not-allowed ${policy.routing_policy === r.value ? "bg-slate-900 font-medium text-slate-50" : "bg-white text-slate-700 hover:bg-slate-100"}`}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-4">
          <Field label="Learn">
            <select className="input" disabled={readOnly} value={policy.reward_mode} onChange={(e) => set("reward_mode", e.target.value as Policy["reward_mode"])}>
              <option value="split">Quality</option>
              <option value="full">Reward</option>
            </select>
          </Field>
          <Num label="Quality" disabled={readOnly} value={policy.weights.quality} onChange={(v) => set("weights", { ...policy.weights, quality: v })} />
          <Num label="Cost" disabled={readOnly} value={policy.weights.cost} onChange={(v) => set("weights", { ...policy.weights, cost: v })} />
          <Num label="Latency" disabled={readOnly} value={policy.weights.latency} onChange={(v) => set("weights", { ...policy.weights, latency: v })} />
          <Num label="C_ref (USD)" disabled={readOnly} value={policy.c_ref_usd} onChange={(v) => set("c_ref_usd", v)} />
          <Num label="L_ref (s)" disabled={readOnly} value={policy.l_ref_s} onChange={(v) => set("l_ref_s", v)} />
          <Num label="ε start" disabled={readOnly} value={policy.eps_start} onChange={(v) => set("eps_start", v)} />
          <Num label="ε end" disabled={readOnly} value={policy.eps_end} onChange={(v) => set("eps_end", v)} />
          <Num label="Decay" step="1" disabled={readOnly} value={policy.eps_decay_steps} onChange={(v) => set("eps_decay_steps", v)} />
          <Num label="Batch" step="1" disabled={readOnly} value={policy.update_batch_size} onChange={(v) => set("update_batch_size", v)} />
          <Num label="Retries" step="1" disabled={readOnly} value={policy.max_retries} onChange={(v) => set("max_retries", v)} />
          <Num label="Passages" step="1" disabled={readOnly} value={policy.retrieval_top_k} onChange={(v) => set("retrieval_top_k", v)} />
        </div>
        {Math.abs(weightSum - 1) > 1e-6 && (
          <div className="mt-3">
            <Notice tone="amber">Weights must sum to 1 (now {weightSum.toFixed(2)})</Notice>
          </div>
        )}
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Context">
          <div className="grid gap-4">
            <Num label="History (tokens)" step="1" disabled={readOnly} value={policy.history_budget_tokens} onChange={(v) => set("history_budget_tokens", v)} />
            <Toggle checked={policy.history_summary_enabled} disabled={readOnly} onChange={(v) => set("history_summary_enabled", v)} label="Summaries" />
            <Toggle checked={policy.cache_enabled} disabled={readOnly} onChange={(v) => set("cache_enabled", v)} label="Cache" />
          </div>
        </Card>
        <Card title="Limits">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Budget (USD/month)">
              <input
                className="input"
                type="number"
                step="any"
                disabled={readOnly}
                value={policy.global_monthly_budget_usd ?? ""}
                placeholder="None"
                onChange={(e) => set("global_monthly_budget_usd", e.target.value === "" ? null : Number(e.target.value))}
              />
            </Field>
            <Num label="Expiry (min)" step="1" disabled={readOnly} value={policy.session_expiry_minutes} onChange={(v) => set("session_expiry_minutes", v)} />
            <Num label="Metadata (days)" step="1" disabled={readOnly} value={policy.metadata_retention_days} onChange={(v) => set("metadata_retention_days", v)} />
            <Num label="Audit (days)" step="1" disabled={readOnly} value={policy.audit_retention_days} onChange={(v) => set("audit_retention_days", v)} />
          </div>
        </Card>
      </div>

      <Card
        title="Learner"
        action={
          !readOnly && (
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => void learnerAction("/api/policy/learner/warm-start")}>
                Warm start
              </Button>
              <Button variant="secondary" onClick={() => void learnerAction("/api/policy/learner/apply")}>
                Apply
              </Button>
            </div>
          )
        }
      >
        <Table head={["Name", "Version", "State", "Scored", "Note", "Created", ""]} empty={!learner.length}>
          {learner.map((v) => (
            <tr key={`${v.name}-${v.version}`}>
              <td className="td font-medium text-slate-900">{v.name}</td>
              <td className="td">v{v.version}</td>
              <td className="td">{v.active ? <Badge tone="green">Active</Badge> : <Badge>Saved</Badge>}</td>
              <td className="td">{v.n_scored}</td>
              <td className="td text-xs text-slate-500">{v.note}</td>
              <td className="td whitespace-nowrap">{fmtTime(v.created_at)}</td>
              <td className="td text-right">
                {!readOnly && !v.active && (
                  <Button variant="secondary" onClick={() => void learnerAction("/api/policy/learner/rollback", { name: v.name, version: v.version })}>
                    Restore
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      </Card>

      <Card title="History">
        <Table head={["Time", "By", "Target", "Change"]} empty={!history.length}>
          {history.map((h) => (
            <tr key={h.id}>
              <td className="td whitespace-nowrap">{fmtTime(h.created_at)}</td>
              <td className="td">{h.actor}</td>
              <td className="td">{h.target}</td>
              <td className="td text-xs">
                {Object.entries(h.changes).map(([field, [before, after]]) => (
                  <div key={field}>
                    <b>{field}</b>: {JSON.stringify(before)} → {JSON.stringify(after)}
                  </div>
                ))}
              </td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
