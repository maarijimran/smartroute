import type { ChatEvent } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "smartroute.token";

export const tokenStore = {
  get: (): string | null => (typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY)),
  set: (token: string) => window.localStorage.setItem(TOKEN_KEY, token),
  clear: () => window.localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail ?? body?.error?.message;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d: { msg?: string; loc?: string[] }) => `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg ?? ""}`).join("; ");
    }
  } catch {
    /* not JSON */
  }
  return `Request failed (${response.status})`;
}

function authHeaders(): Record<string, string> {
  const token = tokenStore.get();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function handleUnauthorized(status: number) {
  if (status === 401 && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    tokenStore.clear();
    window.location.href = "/login";
  }
}

type Options = Omit<RequestInit, "body"> & { json?: unknown; form?: FormData };

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { json, form, headers, ...rest } = options;
  const response = await fetch(`${API_URL}${path}`, {
    ...rest,
    headers: {
      ...authHeaders(),
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(headers as Record<string, string> | undefined),
    },
    body: form ?? (json !== undefined ? JSON.stringify(json) : undefined),
  });
  if (!response.ok) {
    handleUnauthorized(response.status);
    throw new ApiError(await errorMessage(response), response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Sends a chat message and calls `onEvent` for every server-sent event. */
export async function streamChat(
  sessionId: string,
  body: { content: string; consent: boolean; confidential: boolean; model: string | null },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_URL}/api/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    handleUnauthorized(response.status);
    throw new ApiError(await errorMessage(response), response.status);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const line of frame.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)) as ChatEvent);
          } catch {
            /* ignore a malformed frame */
          }
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}

export const fmtUsd = (value: number | null | undefined, digits = 4) =>
  value === null || value === undefined ? "n/a" : `$${value.toFixed(digits)}`;
export const fmtPct = (value: number | null | undefined) =>
  value === null || value === undefined ? "n/a" : `${(value * 100).toFixed(1)}%`;
export const fmtMs = (value: number | null | undefined) =>
  value === null || value === undefined ? "n/a" : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
/** Server timestamps are naive UTC. */
export const fmtTime = (iso: string) => new Date(iso.endsWith("Z") ? iso : `${iso}Z`).toLocaleString();
