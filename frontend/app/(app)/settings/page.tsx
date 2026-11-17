"use client";

import { Avatar, Card, Field } from "@/components/ui";
import { MoonIcon, SettingsIcon, SunIcon } from "@/components/icons";
import { fmtUsd } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTheme, type ThemeChoice } from "@/lib/theme";

export default function GeneralSettings() {
  const { user, permissions } = useAuth();
  const theme = useTheme();
  if (!user) return null;

  const modes: [ThemeChoice, string, React.ReactNode, string][] = [
    ["light", "Light", <SunIcon key="l" />, "bg-[#faf9f5] border-[#e5e2d8]"],
    ["dark", "Dark", <MoonIcon key="d" />, "bg-[#262624] border-[#3e3e38]"],
    ["system", "System", <SettingsIcon key="s" />, "bg-[linear-gradient(135deg,#faf9f5_50%,#262624_50%)] border-[#9c9a92]"],
  ];

  const access: [string, string][] = permissions
    ? [
        ["Cloud models", permissions.cloud_enabled ? "On" : "Off"],
        ["Confidential to cloud", permissions.may_send_confidential_to_cloud ? "Allowed" : "Not allowed"],
        ["Consent per message", permissions.consent_required ? "Required" : "Not required"],
        ["Choose model", permissions.may_pin_model ? "Allowed" : "Auto only"],
        ["OCR", permissions.ocr_enabled ? "On" : "Off"],
        ["Monthly budget", permissions.monthly_budget_usd == null ? "None" : fmtUsd(permissions.monthly_budget_usd, 2)],
      ]
    : [];

  return (
    <div className="space-y-6">
      <Card title="Profile">
        <div className="flex items-center gap-4">
          <Avatar name={user.name || user.email} size={44} />
          <div className="grid flex-1 gap-4 sm:grid-cols-2">
            <Field label="Name">
              <input className="input" value={user.name} disabled />
            </Field>
            <Field label="Email">
              <input className="input" value={user.email} disabled />
            </Field>
          </div>
        </div>
      </Card>

      <Card title="Appearance">
        <div className="grid max-w-md grid-cols-3 gap-3">
          {modes.map(([value, label, icon, swatch]) => (
            <button key={value} onClick={() => theme.set(value)} className="group text-left">
              <span
                className={`flex h-16 items-center justify-center rounded-xl border-2 ${swatch} ${
                  theme.choice === value ? "ring-2 ring-brand-600 ring-offset-2 ring-offset-white" : "group-hover:opacity-90"
                }`}
              >
                <span className="rounded-full bg-[#d97757] p-1.5 text-[#fff]">{icon}</span>
              </span>
              <span className={`mt-2 block text-center text-sm ${theme.choice === value ? "font-medium text-slate-900" : "text-slate-600"}`}>{label}</span>
            </button>
          ))}
        </div>
      </Card>

      <Card title="Access">
        <dl className="divide-y divide-slate-200">
          <div className="flex justify-between py-2 text-sm">
            <dt className="text-slate-600">Role</dt>
            <dd className="font-medium capitalize text-slate-900">{user.role}</dd>
          </div>
          {access.map(([k, v]) => (
            <div key={k} className="flex justify-between py-2 text-sm">
              <dt className="text-slate-600">{k}</dt>
              <dd className="font-medium text-slate-900">{v}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}
