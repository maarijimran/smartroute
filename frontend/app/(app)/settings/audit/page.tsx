"use client";

import { useEffect, useState } from "react";
import { Badge, Card, Notice, PageHeader, Table, errorText } from "@/components/ui";
import { api, fmtTime } from "@/lib/api";
import type { AuditRow } from "@/lib/types";

const REASONS: Record<string, string> = {
  not_confidential: "Not confidential",
  confidential_permitted: "Permitted",
  confidential_not_permitted: "Not permitted",
  consent_required: "No consent",
  local_only_mode: "Local only",
  scanner_failure: "Scanner error",
  institutional_policy: "Cloud off",
};

export default function AuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [days, setDays] = useState(30);
  const [decision, setDecision] = useState("");
  const [leftOnly, setLeftOnly] = useState(false);
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams({ days: String(days) });
    if (decision) params.set("decision", decision);
    if (leftOnly) params.set("left_boundary", "true");
    if (email.trim()) params.set("user_email", email.trim());
    api<AuditRow[]>(`/api/audit/confidential?${params.toString()}`)
      .then(setRows)
      .catch((e) => setError(errorText(e)));
  }, [days, decision, leftOnly, email]);

  return (
    <div className="space-y-6">
      <PageHeader title="Audit" />
      {error && <Notice>{error}</Notice>}
      <Card>
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <select className="input w-auto" value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">
            {[1, 7, 30, 90, 365].map((d) => (
              <option key={d} value={d}>
                {d} {d === 1 ? "day" : "days"}
              </option>
            ))}
          </select>
          <select className="input w-auto" value={decision} onChange={(e) => setDecision(e.target.value)} aria-label="Decision">
            <option value="">All</option>
            <option value="cloud_blocked">Blocked</option>
            <option value="cloud_allowed">Allowed</option>
          </select>
          <input className="input w-56" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="User email" />
          <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
            <input type="checkbox" className="accent-brand-600" checked={leftOnly} onChange={(e) => setLeftOnly(e.target.checked)} />
            Sent out
          </label>
          <span className="ml-auto pb-2 text-sm text-slate-500">{rows.length}</span>
        </div>
        <Table head={["Time", "User", "Source", "Reason", "Decision", "Destination", "Preview", "Hash"]} empty={!rows.length}>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="td whitespace-nowrap">{fmtTime(r.created_at)}</td>
              <td className="td">{r.user_email}</td>
              <td className="td">{r.source}</td>
              <td className="td">
                <div className="flex flex-wrap gap-1">
                  {r.triggers.map((t) => (
                    <Badge key={t} tone="amber">
                      {t.replace(/_/g, " ")}
                    </Badge>
                  ))}
                </div>
                {r.entity_types.length > 0 && <div className="mt-1 text-xs text-slate-500">{r.entity_types.join(", ")}</div>}
              </td>
              <td className="td">
                <Badge tone={r.decision === "cloud_blocked" ? "green" : "red"}>{r.decision === "cloud_blocked" ? "Blocked" : "Allowed"}</Badge>
                <div className="mt-1 text-xs text-slate-500">
                  {REASONS[r.decision_reason] ?? r.decision_reason}
                  {r.consent_given ? " · consent" : ""}
                </div>
              </td>
              <td className="td">
                {r.destination_model ?? "–"}
                <div className="mt-1">{r.left_trusted_boundary ? <Badge tone="red">Sent out</Badge> : <Badge tone="green">Local</Badge>}</div>
              </td>
              <td className="td max-w-sm text-xs text-slate-600">{r.masked_preview || "–"}</td>
              <td className="td font-mono text-xs" title={r.payload_sha256}>
                {r.payload_sha256.slice(0, 10)}…
              </td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
