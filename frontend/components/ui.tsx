"use client";

import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-slate-900 text-slate-50 hover:bg-slate-800 disabled:opacity-40",
  secondary: "border border-slate-200 bg-white text-slate-800 hover:bg-slate-100 disabled:opacity-50",
  danger: "border border-red-200 bg-white text-red-700 hover:bg-red-50 disabled:opacity-50",
  ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900 disabled:opacity-40",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
    />
  );
}

export function Card({ title, action, children, className = "" }: { title?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between px-5 pb-1 pt-4">
          <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>
          {action}
        </header>
      )}
      <div className="px-5 pb-5 pt-3">{children}</div>
    </section>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

type Tone = "slate" | "green" | "amber" | "red" | "blue";
const TONES: Record<Tone, string> = {
  slate: "bg-slate-100 text-slate-700",
  green: "bg-emerald-100 text-emerald-800",
  amber: "bg-amber-100 text-amber-800",
  red: "bg-red-100 text-red-800",
  blue: "bg-brand-50 text-brand-700",
};

export function Badge({ tone = "slate", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>{children}</span>;
}

/** On/off switch. */
export function Switch({ checked, onChange, disabled, label }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50 ${checked ? "bg-brand-600" : "bg-slate-300"}`}
    >
      <span className={`inline-block h-4 w-4 rounded-full bg-[#fff] shadow transition ${checked ? "translate-x-[18px]" : "translate-x-0.5"}`} />
    </button>
  );
}

/** A labelled setting row: text on the left, switch on the right. */
export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <div className={`flex items-center justify-between gap-4 py-1.5 ${disabled ? "opacity-70" : ""}`}>
      <span>
        <span className="block text-sm text-slate-800">{label}</span>
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </span>
      <Switch checked={checked} onChange={onChange} disabled={disabled} label={label} />
    </div>
  );
}

export function Notice({ tone = "red", children }: { tone?: "red" | "amber" | "green" | "blue"; children: ReactNode }) {
  const styles = {
    red: "border-red-200 bg-red-50 text-red-800",
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    green: "border-emerald-200 bg-emerald-50 text-emerald-900",
    blue: "border-brand-100 bg-brand-50 text-brand-700",
  }[tone];
  return <div className={`rounded-lg border px-3 py-2 text-sm ${styles}`}>{children}</div>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-slate-500" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      {label}
    </div>
  );
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-slate-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Table({ head, children, empty }: { head: string[]; children: ReactNode; empty?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200">
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} className="th">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200">{children}</tbody>
      </table>
      {empty && <p className="p-4 text-sm text-slate-500">No data</p>}
    </div>
  );
}

/** Open/close state for a popover menu that closes on an outside click or Escape. */
export function usePopover<T extends HTMLElement = HTMLDivElement>() {
  const [open, setOpen] = useState(false);
  const ref = useRef<T>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return { open, setOpen, ref };
}

export function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  const initial = (name.trim()[0] || "?").toUpperCase();
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full bg-slate-800 font-semibold text-slate-50"
      style={{ width: size, height: size, fontSize: size * 0.45 }}
    >
      {initial}
    </span>
  );
}

export const errorText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");
