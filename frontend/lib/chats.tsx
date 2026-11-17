"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Session } from "./types";

interface ChatsState {
  sessions: Session[];
  loaded: boolean;
  refresh: () => Promise<Session[]>;
  /** Insert or replace one session and keep the list ordered by recent activity. */
  upsert: (session: Session) => void;
  rename: (id: string, title: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
}

const ChatsContext = createContext<ChatsState | null>(null);
const byRecent = (a: Session, b: Session) => (a.last_active_at < b.last_active_at ? 1 : -1);

export function ChatsProvider({ children }: { children: React.ReactNode }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    const list = await api<Session[]>("/api/chat/sessions");
    setSessions(list);
    setLoaded(true);
    return list;
  }, []);

  useEffect(() => {
    refresh().catch(() => setLoaded(true));
  }, [refresh]);

  const upsert = useCallback((session: Session) => {
    setSessions((prev) => [session, ...prev.filter((s) => s.id !== session.id)].sort(byRecent));
  }, []);

  const rename = useCallback(async (id: string, title: string) => {
    const updated = await api<Session>(`/api/chat/sessions/${id}`, { method: "PATCH", json: { title } });
    setSessions((prev) => prev.map((s) => (s.id === id ? updated : s)));
  }, []);

  const remove = useCallback(async (id: string) => {
    await api(`/api/chat/sessions/${id}`, { method: "DELETE" });
    setSessions((prev) => prev.filter((s) => s.id !== id));
  }, []);

  const value = useMemo(() => ({ sessions, loaded, refresh, upsert, rename, remove }), [sessions, loaded, refresh, upsert, rename, remove]);
  return <ChatsContext.Provider value={value}>{children}</ChatsContext.Provider>;
}

export function useChats(): ChatsState {
  const ctx = useContext(ChatsContext);
  if (!ctx) throw new Error("useChats must be used inside ChatsProvider");
  return ctx;
}
