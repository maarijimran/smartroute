"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";

const TABS: { href: string; label: string; roles?: Role[]; section?: string }[] = [
  { href: "/settings", label: "General" },
  { href: "/settings/files", label: "Files" },
  { href: "/settings/api", label: "API" },
  { href: "/settings/analytics", label: "Analytics" },
  { href: "/settings/users", label: "Users", roles: ["superadmin", "admin"], section: "Admin" },
  { href: "/settings/audit", label: "Audit", roles: ["superadmin", "admin"] },
  { href: "/settings/policy", label: "Policy", roles: ["superadmin", "admin"] },
  { href: "/settings/models", label: "Models", roles: ["superadmin"] },
];

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const pathname = usePathname();
  const tabs = TABS.filter((t) => !t.roles || (user && t.roles.includes(user.role)));
  const isActive = (href: string) => (href === "/settings" ? pathname === href : pathname.startsWith(href));

  return (
    <div className="thin-scroll h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 pb-16 pt-10 sm:px-8">
        <h1 className="mb-8 font-serif text-[2rem] font-normal tracking-tight text-slate-900">Settings</h1>
        <div className="flex flex-col gap-8 md:flex-row">
          <nav className="flex shrink-0 gap-1 overflow-x-auto md:w-44 md:flex-col md:overflow-visible">
            {tabs.map((t) => (
              <div key={t.href} className="contents md:block">
                {t.section && <div className="hidden px-3 pb-1 pt-5 text-xs font-medium text-slate-500 md:block">{t.section}</div>}
                <Link
                  href={t.href}
                  className={`block whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition ${
                    isActive(t.href) ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  }`}
                >
                  {t.label}
                </Link>
              </div>
            ))}
          </nav>
          <div className="min-w-0 flex-1">{children}</div>
        </div>
      </div>
    </div>
  );
}
