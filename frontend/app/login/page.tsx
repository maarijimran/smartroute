"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { RouteMark } from "@/components/icons";
import { Button, Notice, errorText } from "@/components/ui";
import { api, tokenStore } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { user, loading, login, refresh } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace("/chat");
  }, [loading, user, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        const result = await api<{ access_token: string }>("/api/auth/register", {
          method: "POST",
          json: { email, name, password },
        });
        tokenStore.set(result.access_token);
        await refresh();
      }
      router.replace("/chat");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-6 pb-[10vh]">
      <div className="mb-10 flex items-center gap-2.5 text-slate-900">
        <RouteMark size={30} className="text-brand-600" />
        <span className="font-serif text-[1.9rem] tracking-tight">SmartRoute</span>
      </div>
      <h1 className="mb-8 text-center font-serif text-[2.4rem] leading-tight tracking-tight text-slate-800">
        {mode === "login" ? "Welcome back" : "Create account"}
      </h1>
      <div className="w-full max-w-[380px] rounded-2xl border border-slate-200 bg-white p-6 shadow-[0_2px_16px_rgba(0,0,0,0.05)]">
        <form onSubmit={submit} className="space-y-3">
          <input className="input py-2.5" type="email" placeholder="Email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          {mode === "register" && <input className="input py-2.5" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />}
          <input
            className="input py-2.5"
            type="password"
            placeholder="Password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={mode === "register" ? 8 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <Notice>{error}</Notice>}
          <Button type="submit" disabled={busy} className="w-full py-2.5">
            {busy ? "Wait" : mode === "login" ? "Continue" : "Create account"}
          </Button>
        </form>
      </div>
      <button
        type="button"
        className="mt-5 text-sm text-slate-500 hover:text-slate-900"
        onClick={() => {
          setMode(mode === "login" ? "register" : "login");
          setError(null);
        }}
      >
        {mode === "login" ? "Create account" : "Sign in"}
      </button>
    </main>
  );
}
