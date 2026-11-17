"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, tokenStore } from "./api";
import type { Permissions, User } from "./types";

interface AuthState {
  user: User | null;
  permissions: Permissions | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [permissions, setPermissions] = useState<Permissions | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!tokenStore.get()) {
      setUser(null);
      setPermissions(null);
      setLoading(false);
      return;
    }
    try {
      const [me, perms] = await Promise.all([api<User>("/api/auth/me"), api<Permissions>("/api/auth/permissions")]);
      setUser(me);
      setPermissions(perms);
    } catch {
      setUser(null);
      setPermissions(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await api<{ access_token: string }>("/api/auth/login", { method: "POST", json: { email, password } });
      tokenStore.set(result.access_token);
      setLoading(true);
      await refresh();
    },
    [refresh],
  );

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
    setPermissions(null);
    window.location.href = "/login";
  }, []);

  const value = useMemo(
    () => ({ user, permissions, loading, login, logout, refresh }),
    [user, permissions, loading, login, logout, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
