"use client";

import { useEffect, useRef } from "react";
import { textDirection, useI18n } from "@/lib/i18n";
import type { Receipt } from "@/lib/types";
import { QueryBox } from "./QueryBox";
import { ReceiptStrip } from "./Receipt";

export interface Turn<R> {
  id: number;
  query: string;
  response?: R;
  receipt?: Receipt;
  failed?: boolean;
}

interface Props<R> {
  turns: Turn<R>[];
  busy: boolean;
  placeholder: string;
  busyLabel: string;
  examples: string[];
  outputLabel: (response: R) => string;
  render: (response: R) => React.ReactNode;
  onAsk: (query: string) => void;
}

export function Conversation<R extends { debug?: Record<string, unknown> }>({
  turns,
  busy,
  placeholder,
  busyLabel,
  examples,
  outputLabel,
  render,
  onAsk,
}: Props<R>) {
  const { t } = useI18n();
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  return (
    <div className="flex flex-col gap-6">
      {turns.length === 0 && (
        <section>
          <p className="mb-3 text-xs font-medium tracking-wide text-muted uppercase">{t("tryThese")}</p>
          <ul className="grid gap-2">
            {examples.map((example) => (
              <li key={example}>
                <button
                  onClick={() => onAsk(example)}
                  disabled={busy}
                  dir={textDirection(example)}
                  className="w-full rounded-lg border border-line bg-surface px-4 py-3 text-start text-[14px] leading-relaxed text-ink-2 hover:border-accent hover:text-ink"
                >
                  {example}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {turns.map((turn) => (
        <article key={turn.id} className="space-y-3">
          <p
            dir={textDirection(turn.query)}
            className="ms-auto w-fit max-w-[85%] rounded-2xl rounded-ee-sm bg-ink px-4 py-2.5 text-[15px] leading-relaxed text-white"
          >
            {turn.query}
          </p>
          {turn.response && (
            <div className="rounded-xl border border-line bg-surface/70 p-5">
              <p className="mb-3 text-xs font-medium tracking-wide text-accent uppercase">{outputLabel(turn.response)}</p>
              {render(turn.response)}
              {turn.receipt && <ReceiptStrip receipt={turn.receipt} debug={turn.response.debug} />}
            </div>
          )}
          {turn.failed && <p className="text-sm text-ochre">HTTP error</p>}
        </article>
      ))}
      <div ref={end} />

      <div className="sticky bottom-0 -mx-1 bg-gradient-to-t from-paper via-paper to-transparent px-1 pt-6 pb-4">
        <QueryBox placeholder={placeholder} busy={busy} busyLabel={busyLabel} onSubmit={onAsk} />
      </div>
    </div>
  );
}
