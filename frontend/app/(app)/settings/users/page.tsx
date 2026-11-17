"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, Field, Notice, PageHeader, Table, errorText } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Policy, Role, User } from "@/lib/types";

export default function UsersPage() {
  const { user: me } = useAuth();
  const isSuper = me?.role === "superadmin";
  const [users, setUsers] = useState<User[]>([]);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ email: "", name: "", password: "", role: "user" as Role });

  async function load() {
    const [list, p] = await Promise.all([api<User[]>("/api/users"), api<Policy>("/api/policy")]);
    setUsers(list);
    setPolicy(p);
  }
  useEffect(() => {
    load().catch((e) => setError(errorText(e)));
  }, []);

  async function patch(id: string, body: Record<string, unknown>) {
    setError(null);
    try {
      await api(`/api/users/${id}`, { method: "PATCH", json: body });
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/users", { method: "POST", json: form });
      setForm({ email: "", name: "", password: "", role: "user" });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  const orgDefault = policy?.allow_confidential_cloud_default ? "allow" : "deny";

  return (
    <div className="space-y-6">
      <PageHeader title="Users" />
      {error && <Notice>{error}</Notice>}

      <Card title="Add">
        <form onSubmit={create} className="grid gap-4 md:grid-cols-[1fr_1fr_1fr_150px_auto] md:items-end">
          <Field label="Email">
            <input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field label="Name">
            <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Password">
            <input className="input" type="password" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <Field label="Role">
            <select className="input" value={form.role} disabled={!isSuper} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              <option value="user">User</option>
              <option value="admin">Admin</option>
              <option value="superadmin">Superadmin</option>
            </select>
          </Field>
          <Button type="submit">Add</Button>
        </form>
      </Card>

      <Card title="Accounts">
        <Table head={["User", "Role", "Confidential", "Budget", "Status", ""]} empty={!users.length}>
          {users.map((u) => {
            const editable = isSuper || u.role === "user";
            const permission = u.allow_confidential_cloud === null ? "inherit" : u.allow_confidential_cloud ? "allow" : "deny";
            return (
              <tr key={u.id}>
                <td className="td">
                  <div className="font-medium text-slate-900">{u.name || u.email}</div>
                  <div className="text-xs text-slate-500">{u.email}</div>
                </td>
                <td className="td">
                  {isSuper ? (
                    <select className="input w-auto" value={u.role} onChange={(e) => void patch(u.id, { role: e.target.value })}>
                      <option value="user">User</option>
                      <option value="admin">Admin</option>
                      <option value="superadmin">Superadmin</option>
                    </select>
                  ) : (
                    <Badge tone={u.role === "user" ? "slate" : "blue"}>{u.role}</Badge>
                  )}
                </td>
                <td className="td">
                  <select
                    className="input w-auto"
                    value={permission}
                    disabled={!isSuper}
                    onChange={(e) =>
                      void patch(u.id, e.target.value === "inherit" ? { inherit_confidential_default: true } : { allow_confidential_cloud: e.target.value === "allow" })
                    }
                  >
                    <option value="inherit">Default ({orgDefault})</option>
                    <option value="allow">Allow</option>
                    <option value="deny">Deny</option>
                  </select>
                </td>
                <td className="td">
                  <BudgetInput value={u.monthly_budget_usd} disabled={!editable} onSave={(v) => void patch(u.id, v === null ? { clear_budget: true } : { monthly_budget_usd: v })} />
                </td>
                <td className="td">{u.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Disabled</Badge>}</td>
                <td className="td text-right">
                  {editable && u.id !== me?.id && (
                    <Button variant={u.is_active ? "danger" : "secondary"} onClick={() => void patch(u.id, { is_active: !u.is_active })}>
                      {u.is_active ? "Disable" : "Enable"}
                    </Button>
                  )}
                </td>
              </tr>
            );
          })}
        </Table>
      </Card>
    </div>
  );
}

function BudgetInput({ value, onSave, disabled }: { value: number | null; onSave: (v: number | null) => void; disabled: boolean }) {
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => setText(value === null ? "" : String(value)), [value]);
  const parsed = text.trim() === "" ? null : Number(text);
  const dirty = parsed !== value;
  return (
    <div className="flex items-center gap-2">
      <input className="input w-24" placeholder="None" inputMode="decimal" value={text} disabled={disabled} onChange={(e) => setText(e.target.value)} />
      {dirty && !disabled && (parsed === null || (!Number.isNaN(parsed) && parsed >= 0)) && (
        <Button variant="secondary" onClick={() => onSave(parsed)}>
          Save
        </Button>
      )}
    </div>
  );
}
