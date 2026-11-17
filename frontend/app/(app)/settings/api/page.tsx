"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, Field, Notice, PageHeader, Table, Toggle, errorText } from "@/components/ui";
import { API_URL, api, fmtTime } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ApiKey, Credential, PrivacyMode, Vendor } from "@/lib/types";

export default function KeysPage() {
  const { user } = useAuth();
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  const [vendor, setVendor] = useState("anthropic");
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiVersion, setApiVersion] = useState("");
  const [platform, setPlatform] = useState(false);

  const [keyName, setKeyName] = useState("");
  const [keyMode, setKeyMode] = useState<PrivacyMode>("cloud_allowed");

  async function load() {
    const [v, c, k] = await Promise.all([api<Vendor[]>("/api/vendors"), api<Credential[]>("/api/credentials"), api<ApiKey[]>("/api/keys")]);
    setVendors(v.filter((x) => x.needs_key));
    setCredentials(c);
    setKeys(k);
  }
  useEffect(() => {
    load().catch((e) => setError(errorText(e)));
  }, []);

  const preset = vendors.find((v) => v.id === vendor);

  async function addCredential(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/credentials", {
        method: "POST",
        json: { vendor, label, api_key: secret, base_url: baseUrl || null, api_version: apiVersion || null, platform },
      });
      setSecret("");
      setLabel("");
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

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

      <Card title="Provider keys">
        <form onSubmit={addCredential} className="grid gap-4 md:grid-cols-2">
          <Field label="Provider">
            <select className="input" value={vendor} onChange={(e) => setVendor(e.target.value)}>
              {vendors.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Label">
            <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label="Key">
            <input className="input" type="password" required minLength={4} value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Endpoint">
            <input
              className="input"
              value={baseUrl}
              required={preset?.needs_base_url}
              placeholder={preset?.default_base_url ?? "https://<resource>.openai.azure.com"}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </Field>
          {vendor === "azure_openai" && (
            <Field label="Version">
              <input className="input" value={apiVersion} placeholder="2024-10-21" onChange={(e) => setApiVersion(e.target.value)} />
            </Field>
          )}
          <div className="flex items-center gap-6 md:col-span-2">
            {user?.role === "superadmin" && <Toggle checked={platform} onChange={setPlatform} label="Shared" />}
            <Button type="submit" className="ml-auto">
              Save
            </Button>
          </div>
        </form>
        <div className="mt-4">
          <Table head={["Provider", "Label", "Key", "Endpoint", "Scope", "Added", ""]} empty={!credentials.length}>
            {credentials.map((c) => (
              <tr key={c.id}>
                <td className="td font-medium text-slate-900">{vendors.find((v) => v.id === c.vendor)?.label ?? c.vendor}</td>
                <td className="td">{c.label || "–"}</td>
                <td className="td font-mono">••••{c.key_hint}</td>
                <td className="td">{c.base_url || "Default"}</td>
                <td className="td">{c.user_id ? <Badge>Personal</Badge> : <Badge tone="blue">Shared</Badge>}</td>
                <td className="td">{fmtTime(c.created_at)}</td>
                <td className="td text-right">
                  <Button
                    variant="danger"
                    onClick={async () => {
                      await api(`/api/credentials/${c.id}`, { method: "DELETE" });
                      await load();
                    }}
                  >
                    Remove
                  </Button>
                </td>
              </tr>
            ))}
          </Table>
        </div>
      </Card>

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
