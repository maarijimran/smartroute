"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, Field, Notice, PageHeader, Table, errorText } from "@/components/ui";
import { API_URL, api, fmtTime } from "@/lib/api";
import type { ApiKey, PrivacyMode } from "@/lib/types";

export default function KeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  const [keyName, setKeyName] = useState("");
  const [keyMode, setKeyMode] = useState<PrivacyMode>("cloud_allowed");

  async function load() {
    setKeys(await api<ApiKey[]>("/api/keys"));
  }
  useEffect(() => {
    load().catch((e) => setError(errorText(e)));
  }, []);

  async function createKey(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const key = await api<ApiKey>("/api/keys", { method: "POST", json: { name: keyName, default_privacy_mode: keyMode } });
      setCreated(key.key ?? null);
      setKeyName("");
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  const curl = `curl ${API_URL}/v1/chat/completions \\
  -H "Authorization: Bearer sr-YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "smartroute/auto",
       "messages": [{"role": "user", "content": "Hello"}]}'`;
  const python = `from openai import OpenAI

client = OpenAI(base_url="${API_URL}/v1", api_key="sr-YOUR_KEY")
reply = client.chat.completions.create(
    model="smartroute/auto",
    messages=[{"role": "user", "content": "Hello"}],
    extra_body={"smartroute": {"privacy_mode": "cloud_allowed", "consent": False}},
)
print(reply.choices[0].message.content)
print(reply.model_extra["smartroute"])`;

  return (
    <div className="space-y-6">
      <PageHeader title="API" />
      {error && <Notice>{error}</Notice>}

      <Card title="API keys">
        <form onSubmit={createKey} className="grid gap-4 md:grid-cols-[1fr_200px_auto] md:items-end">
          <Field label="Name">
            <input className="input" value={keyName} onChange={(e) => setKeyName(e.target.value)} />
          </Field>
          <Field label="Mode">
            <select className="input" value={keyMode} onChange={(e) => setKeyMode(e.target.value as PrivacyMode)}>
              <option value="cloud_allowed">Cloud</option>
              <option value="local_only">Local</option>
            </select>
          </Field>
          <Button type="submit">Create</Button>
        </form>
        {created && (
          <div className="mt-4">
            <Notice tone="green">
              <div className="font-medium">Copy now. Shown once.</div>
              <code className="mt-1 block break-all font-mono text-xs">{created}</code>
              <button className="mt-2 text-xs font-medium underline" onClick={() => void navigator.clipboard.writeText(created)}>
                Copy
              </button>
            </Notice>
          </div>
        )}
        <div className="mt-4">
          <Table head={["Name", "Key", "Mode", "Created", "Last used", "Status", ""]} empty={!keys.length}>
            {keys.map((k) => (
              <tr key={k.id}>
                <td className="td font-medium text-slate-900">{k.name || "–"}</td>
                <td className="td font-mono">{k.prefix}…</td>
                <td className="td">{k.default_privacy_mode === "local_only" ? "Local" : "Cloud"}</td>
                <td className="td">{fmtTime(k.created_at)}</td>
                <td className="td">{k.last_used_at ? fmtTime(k.last_used_at) : "Never"}</td>
                <td className="td">{k.revoked ? <Badge tone="red">Revoked</Badge> : <Badge tone="green">Active</Badge>}</td>
                <td className="td text-right">
                  {!k.revoked && (
                    <Button
                      variant="danger"
                      onClick={async () => {
                        await api(`/api/keys/${k.id}`, { method: "DELETE" });
                        await load();
                      }}
                    >
                      Revoke
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        </div>
      </Card>

      <Card title="Usage">
        <div className="grid gap-3 lg:grid-cols-2">
          <pre className="code-block">{curl}</pre>
          <pre className="code-block">{python}</pre>
        </div>
      </Card>
    </div>
  );
}
