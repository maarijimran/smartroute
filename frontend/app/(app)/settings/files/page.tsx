"use client";

import { useEffect, useRef, useState } from "react";
import { Badge, Button, Card, Field, Notice, PageHeader, Table, Toggle, errorText } from "@/components/ui";
import { api, fmtTime } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Doc } from "@/lib/types";

const IMAGE_TYPES = ".png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp";

export default function DocumentsPage() {
  const { permissions } = useAuth();
  const ocr = !!permissions?.ocr_enabled;
  const [docs, setDocs] = useState<Doc[]>([]);
  const [label, setLabel] = useState<"confidential" | "public">("confidential");
  const [persist, setPersist] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const load = async () => setDocs(await api<Doc[]>("/api/documents"));
  useEffect(() => {
    load().catch((e) => setError(errorText(e)));
  }, []);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    const chosen = file.current?.files?.[0];
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", chosen);
      form.append("label", label);
      form.append("persist", String(persist));
      await api("/api/documents", { method: "POST", form });
      if (file.current) file.current.value = "";
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(doc: Doc) {
    await api(`/api/documents/${doc.id}`, { method: "DELETE" });
    await load();
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Files" />
      <Card title="Upload" className="mb-6">
        <form onSubmit={upload} className="grid gap-4 md:grid-cols-[1fr_200px_auto_auto] md:items-end">
          <Field label="File">
            <input ref={file} type="file" accept={ocr ? `.pdf,.txt,${IMAGE_TYPES}` : ".pdf,.txt"} required className="input" />
          </Field>
          <Field label="Label">
            <select className="input" value={label} onChange={(e) => setLabel(e.target.value as "confidential" | "public")}>
              <option value="confidential">Confidential</option>
              <option value="public">Public</option>
            </select>
          </Field>
          <div className="pb-2">
            <Toggle checked={persist} onChange={setPersist} label="Keep" />
          </div>
          <Button type="submit" disabled={busy}>
            {busy ? "Reading" : "Upload"}
          </Button>
        </form>
        {error && (
          <div className="mt-4">
            <Notice>{error}</Notice>
          </div>
        )}
      </Card>
      <Card title="Files">
        <Table head={["File", "Label", "Pages", "Source", "Chunks", "Added", ""]} empty={!docs.length}>
          {docs.map((d) => (
            <tr key={d.id}>
              <td className="td font-medium text-slate-900">{d.filename}</td>
              <td className="td">
                <Badge tone={d.label === "public" ? "green" : "amber"}>{d.label === "public" ? "Public" : "Confidential"}</Badge>
              </td>
              <td className="td">{d.pages}</td>
              <td className="td">{d.ocr_pages ? <Badge tone="blue">OCR · {d.ocr_pages}</Badge> : "Text"}</td>
              <td className="td">{d.n_chunks}</td>
              <td className="td">{fmtTime(d.created_at)}</td>
              <td className="td text-right">
                <Button variant="danger" onClick={() => void remove(d)}>
                  Delete
                </Button>
              </td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
