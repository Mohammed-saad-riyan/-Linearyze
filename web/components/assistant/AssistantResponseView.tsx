"use client";

import { textDirection, useI18n } from "@/lib/i18n";
import type { AssistantResponse } from "@/lib/types";
import { DocumentCardView, QuoteView } from "../documents";
import { AlertIcon } from "../icons";

/** Renders outputs A to E. Order inside B follows SRS 1.8.2.1: conflict notice first,
 *  then the answer with its quotes, then document cards, then M8. */
export function AssistantResponseView({
  response,
  onOption,
}: {
  response: AssistantResponse;
  onOption: (text: string) => void;
}) {
  const { t } = useI18n();
  const dir = response.lang === "ar" ? "rtl" : "ltr";

  if (response.output === "E") {
    return (
      <p dir={dir} className="text-[15px] text-ink">
        {response.message}
      </p>
    );
  }

  const titles = Object.fromEntries((response.documents ?? []).map((d) => [d.id, d.title]));

  return (
    <div dir={dir} className="space-y-4">
      {response.notice && (
        <div className="flex gap-2.5 rounded-lg border border-ochre/30 bg-ochre-wash px-4 py-3 text-[15px] text-ochre">
          <AlertIcon className="mt-0.5 size-5 shrink-0" />
          <p className="font-medium">{response.notice}</p>
        </div>
      )}

      {response.conflicts?.map((conflict) => (
        <div key={conflict.fact_key} className="rounded-lg border border-line bg-surface p-4">
          <p className="mb-3 text-xs font-medium tracking-wide text-muted uppercase">{t("conflictingValues")}</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {conflict.values.map((v) => (
              <div key={v.document_id}>
                <p className="mb-1.5 text-sm font-medium">{titles[v.document_id] ?? v.document_id}</p>
                <QuoteView citation={v.citation} />
              </div>
            ))}
          </div>
        </div>
      ))}

      {response.sentences && response.sentences.length > 0 && (
        <div className="space-y-4">
          {response.sentences.map((s, i) => (
            <div key={i}>
              <p className="text-[15px] leading-relaxed" dir={textDirection(s.text)}>
                {s.text}
              </p>
              <div className="mt-2 space-y-1.5">
                {s.citations.map((c, j) => (
                  <QuoteView key={j} citation={c} title={titles[c.document_id]} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {response.output === "C" && (
        <div>
          <p className="text-[15px]">{response.question}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {response.options?.map((option, i) => {
              const isOther = i === (response.options?.length ?? 0) - 1;
              return (
                <button
                  key={option}
                  onClick={() => !isOther && onOption(option.replace(/^[^:]+:\s*/, ""))}
                  disabled={isOther}
                  className="rounded-full border border-line-strong bg-surface px-3.5 py-1.5 text-sm hover:border-accent disabled:text-muted"
                >
                  {option}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {response.documents && response.documents.length > 0 && (
        <div className="space-y-2">
          {response.output === "B" && (
            <p className="text-xs font-medium tracking-wide text-muted uppercase">{t("sources")}</p>
          )}
          {response.documents.map((doc) => (
            <DocumentCardView key={doc.id} doc={doc} />
          ))}
        </div>
      )}

      {response.disclaimer && <p className="border-t border-line pt-3 text-xs text-muted">{response.disclaimer}</p>}
    </div>
  );
}
