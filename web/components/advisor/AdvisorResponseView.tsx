"use client";

import { textDirection, useI18n } from "@/lib/i18n";
import type { AdvisorResponse } from "@/lib/types";
import { QuoteView } from "../documents";
import { AlertIcon } from "../icons";

/** Output R: the result, the formula line as the user wrote it, the same line with values,
 *  and every input with its source (SRS 2.5, 2.8). Output Q: what is missing or must be
 *  chosen. Output E: a defined message. */
export function AdvisorResponseView({ response }: { response: AdvisorResponse }) {
  const { t } = useI18n();
  const dir = response.lang === "ar" ? "rtl" : "ltr";

  if (response.output === "E") {
    return (
      <p dir={dir} className="text-[15px]">
        {response.message}
      </p>
    );
  }

  return (
    <div dir={dir} className="space-y-5">
      {response.notice && (
        <div className="flex gap-2.5 rounded-lg border border-ochre/30 bg-ochre-wash px-4 py-3 text-[15px] text-ochre">
          <AlertIcon className="mt-0.5 size-5 shrink-0" />
          <p className="font-medium">{response.notice}</p>
        </div>
      )}

      {response.result && (
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
          <p className="text-4xl font-semibold tracking-tight tabular-nums" dir="ltr">
            {response.result.value}
          </p>
          <p className="pb-1 text-lg text-ink-2">{response.result.unit}</p>
          <div className="flex gap-2 pb-1.5">
            {response.estimate && (
              <span className="rounded-full border border-accent/40 px-2 py-0.5 text-xs font-medium text-accent">
                {t("estimate")}
              </span>
            )}
            {response.formula_source === "ai_selected" && (
              <span className="rounded-full border border-ochre/40 px-2 py-0.5 text-xs font-medium text-ochre">
                {t("aiSelected")}
              </span>
            )}
          </div>
        </div>
      )}

      {response.formula && (
        <dl className="grid gap-2 rounded-lg border border-line bg-sunken/50 px-4 py-3 text-sm sm:grid-cols-[8rem_1fr]">
          <dt className="text-muted">{t("formula")}</dt>
          <dd className="font-mono text-ink" dir={textDirection(response.formula)}>
            {response.formula}
          </dd>
          {response.substituted && (
            <>
              <dt className="text-muted">{t("withValues")}</dt>
              <dd className="font-mono text-ink" dir="ltr">
                {response.substituted}
                {response.result && ` = ${response.result.exact}`}
              </dd>
            </>
          )}
        </dl>
      )}

      {response.inputs && response.inputs.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium tracking-wide text-muted uppercase">{t("inputs")}</p>
          <div className="space-y-3">
            {response.inputs.map((input) => (
              <div key={input.term} className="rounded-lg border border-line bg-surface p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="font-medium">{input.term}</p>
                  <p className="tabular-nums">
                    <span dir="ltr">{input.value}</span> <span className="text-sm text-ink-2">{input.unit}</span>
                  </p>
                </div>
                <p className="mt-0.5 text-xs text-muted">
                  {t("source")}: {t(`source_${input.source_type}`)}
                  {input.document_title ? ` · ${input.document_title}` : ""}
                </p>
                {input.citation && (
                  <div className="mt-2">
                    <QuoteView citation={input.citation} />
                  </div>
                )}
                {input.overridden_value && (
                  <div className="mt-2 text-xs text-muted">
                    <p className="mb-1">
                      {t("replaces")} <span dir="ltr">{input.overridden_value}</span>
                      {input.overridden_document_title ? ` · ${input.overridden_document_title}` : ""}
                    </p>
                    {input.overridden_citation && <QuoteView citation={input.overridden_citation} />}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {response.question && <p className="text-[15px]">{response.question}</p>}
      {response.missing && response.missing.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {response.missing.map((m) => (
            <li key={m} className="rounded-full border border-line-strong px-3 py-1 text-sm">
              {m}
            </li>
          ))}
        </ul>
      )}
      {response.choices && response.choices.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {response.choices.map((choice) => (
            <div key={choice.citation.document_id} className="rounded-lg border border-line bg-surface p-3">
              <p className="font-medium tabular-nums">{choice.value}</p>
              <p className="mb-2 text-xs text-muted">{choice.document_title}</p>
              <QuoteView citation={choice.citation} />
            </div>
          ))}
        </div>
      )}

      {response.notes && response.notes.length > 0 && (
        <ul className="space-y-1 text-sm text-ink-2">
          {response.notes.map((note) => (
            <li key={note} className="flex gap-2">
              <span className="text-muted">·</span>
              {note}
            </li>
          ))}
        </ul>
      )}

      {response.disclaimer && <p className="border-t border-line pt-3 text-xs text-muted">{response.disclaimer}</p>}
    </div>
  );
}
