"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Role } from "@/lib/types";

// The demo accounts from seed/users.yaml. Their passwords are public on purpose.
const ACCOUNTS: { role: Role; email: string; password: string; name: string }[] = [
  { role: "management", email: "management@demo.lnz", password: "demo-management", name: "Faisal Al-Harbi" },
  { role: "employee", email: "employee@demo.lnz", password: "demo-employee", name: "Noura Al-Mutairi" },
  { role: "admin", email: "admin@demo.lnz", password: "demo-admin", name: "Khalid Al-Zahrani" },
];

export default function LoginPage() {
  const { t, lang, setLang } = useI18n();
  const router = useRouter();
  const [busy, setBusy] = useState<Role | null>(null);
  const [failed, setFailed] = useState(false);

  async function signIn(account: (typeof ACCOUNTS)[number]) {
    setBusy(account.role);
    setFailed(false);
    try {
      await api.login(account.email, account.password);
      router.push("/");
    } catch {
      setFailed(true);
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-4 py-12 sm:px-6">
      <div className="mb-10 flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium tracking-wide text-accent uppercase">{t("pocTag")}</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">{t("appName")}</h1>
          <p className="mt-3 max-w-xl text-ink-2">{t("signInIntro")}</p>
        </div>
        <button
          onClick={() => setLang(lang === "en" ? "ar" : "en")}
          className="shrink-0 rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink-2 hover:border-line-strong"
        >
          {t("language")}
        </button>
      </div>

      <ul className="grid gap-3">
        {ACCOUNTS.map((account) => (
          <li key={account.role}>
            <button
              onClick={() => signIn(account)}
              disabled={busy !== null}
              className="group flex w-full items-center justify-between gap-4 rounded-lg border border-line bg-surface px-5 py-4 text-start transition hover:border-accent disabled:opacity-60"
            >
              <span>
                <span className="flex items-center gap-2">
                  <span className="font-medium">{t(`role_${account.role}`)}</span>
                  <span className="text-sm text-muted">{account.name}</span>
                </span>
                <span className="mt-1 block text-sm text-ink-2">{t(`scope_${account.role}`)}</span>
                <span className="mt-2 block font-mono text-xs text-muted" dir="ltr">
                  {account.email} · {account.password}
                </span>
              </span>
              <span className="shrink-0 text-sm font-medium text-accent group-hover:underline">
                {busy === account.role ? "…" : t("signInAs")}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {failed && <p className="mt-4 text-sm text-ochre">{t("signInFailed")}</p>}
    </main>
  );
}
