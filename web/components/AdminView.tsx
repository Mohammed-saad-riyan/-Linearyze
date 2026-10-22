"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { type Key, useI18n } from "@/lib/i18n";

type User = Awaited<ReturnType<typeof api.users>>[number];

/** Admins get account management only (SRS 0.7.5, 1.3.1). The full admin panel is listed
 *  under "Designed, not built" in the README; this page shows the role boundary. */
export function AdminView() {
  const { t } = useI18n();
  const [users, setUsers] = useState<User[]>([]);

  useEffect(() => {
    api.users().then(setUsers).catch(() => setUsers([]));
  }, []);

  return (
    <section>
      <h1 className="text-xl font-semibold tracking-tight">{t("adminTitle")}</h1>
      <p className="mt-2 max-w-2xl text-ink-2">{t("adminIntro")}</p>
      <div className="mt-6 overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full text-start text-sm">
          <thead className="border-b border-line text-xs text-muted">
            <tr>
              <th className="px-4 py-2.5 text-start font-medium">{t("name")}</th>
              <th className="px-4 py-2.5 text-start font-medium">{t("email")}</th>
              <th className="px-4 py-2.5 text-start font-medium">{t("role")}</th>
              <th className="px-4 py-2.5 text-start font-medium">{t("events")}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.email} className="border-b border-line last:border-0">
                <td className="px-4 py-3">{user.name}</td>
                <td className="px-4 py-3 font-mono text-xs" dir="ltr">
                  {user.email}
                </td>
                <td className="px-4 py-3">{t(`role_${user.role}` as Key)}</td>
                <td className="px-4 py-3 text-ink-2">
                  {user.role === "management" ? t("all") : user.events.join(", ") || t("none")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
