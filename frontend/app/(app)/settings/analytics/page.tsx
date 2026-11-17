"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, LabelList, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, Notice, PageHeader, Spinner, Table, errorText } from "@/components/ui";
import { api, fmtMs, fmtPct, fmtTime, fmtUsd } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { EventRow, Summary } from "@/lib/types";

const AXIS = { fontSize: 11, fill: "var(--chart-axis)" };
const TOOLTIP = {
  contentStyle: { background: "rgb(var(--white))", border: "1px solid rgb(var(--slate-200))", borderRadius: 8, fontSize: 12, color: "rgb(var(--slate-900))" },
  labelStyle: { color: "rgb(var(--slate-900))" },
  cursor: { stroke: "var(--chart-grid)" },
};

function Stat({ label, value, note, estimate }: { label: string; value: string; note?: string; estimate?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
        {estimate && <Badge tone="amber">Est.</Badge>}
      </div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
      {note && <div className="mt-1 text-xs text-slate-500">{note}</div>}
    </div>
  );
}

export default function AnalyticsPage() {
  const { user } = useAuth();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = user?.role !== "user";

  useEffect(() => {
    setError(null);
    Promise.all([api<Summary>(`/api/analytics/summary?days=${days}&scope=${scope}`), api<EventRow[]>(`/api/analytics/events?limit=50&scope=${scope}`)])
      .then(([s, e]) => {
        setSummary(s);
        setEvents(e);
      })
      .catch((e) => setError(errorText(e)));
  }, [scope, days]);

  if (error)
    return (
      <div>
        <Notice>{error}</Notice>
      </div>
    );
  if (!summary) return <Spinner />;
  const { measured, estimated, privacy } = summary;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analytics"
        action={
          <div className="flex gap-2">
            {isAdmin && (
              <select className="input w-auto" value={scope} onChange={(e) => setScope(e.target.value as "mine" | "all")}>
                <option value="mine">Mine</option>
                <option value="all">All</option>
              </select>
            )}
            <select className="input w-auto" value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {[7, 30, 90].map((d) => (
                <option key={d} value={d}>
                  {d} days
                </option>
              ))}
            </select>
          </div>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Requests" value={String(measured.requests)} note={`${measured.answered} answered · ${measured.cache_hits} cached`} />
        <Stat label="Cost" value={fmtUsd(measured.cost_usd)} />
        <Stat label="Local" value={fmtPct(measured.local_share)} />
        <Stat label="Latency" value={fmtMs(measured.latency_p50_ms)} note={`p95 ${fmtMs(measured.latency_p95_ms)}`} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Strong-only" value={fmtUsd(estimated.strong_only_cost_usd)} note={estimated.reference_model ?? undefined} estimate />
        <Stat label="Saving" value={fmtPct(estimated.saving_vs_strong_only)} estimate />
        <Stat label="Confidential" value={String(privacy.confidential_requests)} />
        <Stat label="Blocked" value={String(privacy.cloud_blocked)} />
        <Stat label="Consented" value={String(privacy.sent_to_cloud_with_consent)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Daily cost">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={summary.daily}>
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="date" tick={AXIS} stroke="var(--chart-grid)" />
                <YAxis tick={AXIS} stroke="var(--chart-grid)" />
                <Tooltip {...TOOLTIP} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="cost_usd" name="Measured" stroke="var(--chart-main)" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="est_strong_only_usd" name="Strong-only (est.)" stroke="var(--chart-muted)" strokeWidth={2} strokeDasharray="5 4" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Answers by model">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={summary.by_model} margin={{ top: 18 }}>
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="model" tick={AXIS} stroke="var(--chart-grid)" />
                <YAxis allowDecimals={false} tick={AXIS} stroke="var(--chart-grid)" />
                <Tooltip {...TOOLTIP} cursor={{ fill: "rgb(var(--slate-100))" }} />
                <Bar dataKey="requests" name="Answers" fill="var(--chart-main)" radius={[4, 4, 0, 0]}>
                  <LabelList dataKey="requests" position="top" fill="var(--chart-axis)" fontSize={11} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card title="Models">
        <Table head={["Model", "Tier", "Answers", "Cost", "Latency", "Quality", "Rated"]} empty={!summary.by_model.length}>
          {summary.by_model.map((m) => (
            <tr key={m.model}>
              <td className="td font-medium text-slate-900">{m.model}</td>
              <td className="td">{m.tier ?? "–"}</td>
              <td className="td">{m.requests}</td>
              <td className="td">{fmtUsd(m.cost_usd)}</td>
              <td className="td">{fmtMs(m.avg_latency_ms)}</td>
              <td className="td">{m.avg_quality === null ? "–" : m.avg_quality.toFixed(2)}</td>
              <td className="td">{m.rated}</td>
            </tr>
          ))}
        </Table>
      </Card>

      <Card title="Recent">
        <Table head={["Time", "Source", "Task", "Model", "Status", "Reason", "Tokens", "Cost", "Latency", "Reward"]} empty={!events.length}>
          {events.map((e) => (
            <tr key={e.id}>
              <td className="td whitespace-nowrap">{fmtTime(e.created_at)}</td>
              <td className="td">{e.source}</td>
              <td className="td">{e.task}</td>
              <td className="td font-medium text-slate-900">{e.model ?? "–"}</td>
              <td className="td">
                <Badge tone={e.status === "ok" ? "green" : e.status === "abstained" ? "amber" : e.status === "cache_hit" ? "slate" : "red"}>{e.status}</Badge>
                {e.sensitive && (
                  <span className="ml-1">
                    <Badge tone="amber">Confidential</Badge>
                  </span>
                )}
              </td>
              <td className="td max-w-xs text-xs text-slate-500">{e.explanation}</td>
              <td className="td whitespace-nowrap">
                {e.in_tokens}/{e.out_tokens}
              </td>
              <td className="td">{fmtUsd(e.cost_usd, 5)}</td>
              <td className="td">{fmtMs(e.latency_ms)}</td>
              <td className="td">{e.reward === null ? "–" : e.reward.toFixed(2)}</td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
