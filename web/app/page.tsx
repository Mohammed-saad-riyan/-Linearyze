"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { AdminView } from "@/components/AdminView";
import { AdvisorResponseView } from "@/components/advisor/AdvisorResponseView";
import { AssistantResponseView } from "@/components/assistant/AssistantResponseView";
import { Conversation, type Turn } from "@/components/Conversation";
import { DocumentDrawerProvider } from "@/components/documents";
import { SearchIcon } from "@/components/icons";
import { ApiError, api, postMeasured } from "@/lib/api";
import { EXAMPLES, type Key, useI18n } from "@/lib/i18n";
import type { AdvisorResponse, AssistantResponse, Me } from "@/lib/types";

type Tab = "assistant" | "advisor";

function useConversation<R>(path: string, withHistory: boolean) {
  const router = useRouter();
  const [turns, setTurns] = useState<Turn<R>[]>([]);
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);
  const asked = useRef<string[]>([]);

  const ask = useCallback(
    async (query: string) => {
      const id = nextId.current++;
      // The Advisor reads values from earlier messages (SRS 2.8); the Assistant has no memory in this PoC.
      const history = withHistory ? asked.current.map((text) => ({ role: "user", text })) : undefined;
      asked.current = [...asked.current, query];
      setTurns((prev) => [...prev, { id, query }]);
      setBusy(true);
      try {
        const { data, receipt } = await postMeasured<R>(path, { query, debug: true, history });
        setTurns((prev) => prev.map((turn) => (turn.id === id ? { ...turn, response: data, receipt } : turn)));
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) router.push("/login");
        setTurns((prev) => prev.map((turn) => (turn.id === id ? { ...turn, failed: true } : turn)));
      } finally {
        setBusy(false);
      }
    },
    [path, withHistory, router],
  );
  return { turns, busy, ask };
}

export default function Workspace() {
  const { t, lang, setLang } = useI18n();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [tab, setTab] = useState<Tab>("assistant");
  const [search, setSearch] = useState("");
  const assistant = useConversation<AssistantResponse>("/api/assistant/query", false);
  const advisor = useConversation<AdvisorResponse>("/api/advisor/query", true);

  useEffect(() => {
    api.me().then(setMe, () => router.replace("/login"));
  }, [router]);

  if (!me) return null;
  const canAssist = me.capabilities.includes("search_assistant");
  const canAdvise = me.capabilities.includes("operational_advisor");

  async function signOut() {
    await api.logout();
    router.replace("/login");
  }

  return (
    <DocumentDrawerProvider>
      <header className="sticky top-0 z-30 border-b border-line bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-md bg-accent text-sm font-semibold text-white">L</span>
            <span className="font-semibold tracking-tight">{t("appName")}</span>
          </div>

          {canAssist && (
            // SRS 1.11.1: a search box on every screen. It sends the text to the Assistant.
            <form
              className="order-last flex w-full items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 sm:order-none sm:ms-4 sm:w-auto sm:flex-1"
              onSubmit={(e) => {
                e.preventDefault();
                if (!search.trim()) return;
                setTab("assistant");
                assistant.ask(search.trim());
                setSearch("");
              }}
            >
              <SearchIcon className="size-4 text-muted" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("searchPlaceholder")}
                className="w-full bg-transparent text-sm outline-none placeholder:text-muted"
              />
            </form>
          )}

          <div className="ms-auto flex items-center gap-3 text-sm">
            <button onClick={() => setLang(lang === "en" ? "ar" : "en")} className="text-ink-2 hover:text-ink">
              {t("language")}
            </button>
            <span className="hidden h-4 w-px bg-line-strong sm:block" />
            <span className="hidden text-ink-2 sm:inline">{me.name}</span>
            <span className="rounded-full bg-accent-wash px-2 py-0.5 text-xs font-medium text-accent-ink">
              {t(`role_${me.role}` as Key)}
            </span>
            <button onClick={signOut} className="text-ink-2 hover:text-ink">
              {t("signOut")}
            </button>
          </div>
        </div>

        {(canAssist || canAdvise) && (
          <nav className="mx-auto flex max-w-4xl gap-6 px-4 sm:px-6" aria-label="Tabs">
            {(["assistant", "advisor"] as const)
              .filter((name) => (name === "assistant" ? canAssist : canAdvise))
              .map((name) => (
                <button
                  key={name}
                  onClick={() => setTab(name)}
                  className={`-mb-px border-b-2 pb-2.5 text-sm font-medium ${
                    tab === name ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink-2"
                  }`}
                >
                  {t(name)}
                </button>
              ))}
          </nav>
        )}
      </header>

      <main className="mx-auto max-w-4xl px-4 pt-8 sm:px-6">
        {!canAssist && !canAdvise && <AdminView />}

        {canAssist && tab === "assistant" && (
          <Conversation
            turns={assistant.turns}
            busy={assistant.busy}
            onAsk={assistant.ask}
            placeholder={t("askPlaceholder")}
            busyLabel={t("working")}
            examples={EXAMPLES.assistant.map((e) => e[lang])}
            outputLabel={(r) => t(`output_${r.output}` as Key)}
            render={(r) => <AssistantResponseView response={r} onOption={assistant.ask} />}
          />
        )}

        {canAdvise && tab === "advisor" && (
          <Conversation
            turns={advisor.turns}
            busy={advisor.busy}
            onAsk={advisor.ask}
            placeholder={t("advisorPlaceholder")}
            busyLabel={t("calculating")}
            examples={EXAMPLES.advisor.map((e) => e[lang])}
            outputLabel={(r) => t(`output_${r.output}` as Key)}
            render={(r) => <AdvisorResponseView response={r} />}
          />
        )}
      </main>
    </DocumentDrawerProvider>
  );
}
