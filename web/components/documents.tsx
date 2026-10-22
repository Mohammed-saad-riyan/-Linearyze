"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { formatDate, textDirection, useI18n } from "@/lib/i18n";
import type { Citation, DocumentCard, PassageView, SourceRef } from "@/lib/types";
import { CloseIcon, DownloadIcon, EyeIcon, FileIcon } from "./icons";

interface Target {
  documentId: string;
  chunkId: number;
  highlight?: { start: number; end: number };
}

const DrawerContext = createContext<(target: Target) => void>(() => {});

export function useOpenDocument() {
  return useContext(DrawerContext);
}

export function sourceLabel(source: SourceRef, t: ReturnType<typeof useI18n>["t"]): string {
  const parts = [];
  if (source.page) parts.push(`${t("page")} ${source.page}`);
  if (source.sheet) parts.push(`${t("sheet")} ${source.sheet}`);
  if (source.cell_range) parts.push(`${t("cells")} ${source.cell_range}`);
  if (source.heading) parts.push(`${t("section")}: ${source.heading}`);
  return parts.join(" · ");
}

/** View opens the cited passage in a side panel with the quote marked (SRS 1.9.1, 1.9.2). */
export function DocumentDrawerProvider({ children }: { children: React.ReactNode }) {
  const [target, setTarget] = useState<Target | null>(null);
  const open = useCallback((next: Target) => setTarget(next), []);
  return (
    <DrawerContext.Provider value={open}>
      {children}
      {target && (
        // Keyed so a new target mounts a fresh drawer instead of resetting state in an effect.
        <DocumentDrawer
          key={`${target.documentId}:${target.chunkId}:${target.highlight?.start ?? ""}`}
          target={target}
          onClose={() => setTarget(null)}
        />
      )}
    </DrawerContext.Provider>
  );
}

function DocumentDrawer({ target, onClose }: { target: Target; onClose: () => void }) {
  const { t } = useI18n();
  const [view, setView] = useState<PassageView | null>(null);
  const [failed, setFailed] = useState(false);
  const cited = useRef<HTMLElement>(null);

  useEffect(() => {
    let live = true;
    api
      .passage(target.documentId, target.chunkId)
      .then((v) => live && setView(v))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [target]);

  useEffect(() => {
    cited.current?.scrollIntoView({ block: "center" });
  }, [view]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true">
      <button className="absolute inset-0 bg-ink/20" aria-label={t("close")} onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-2xl flex-col border-s border-line bg-surface shadow-xl">
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <p className="text-xs text-muted">{view?.file_name}</p>
            <h2 className="mt-0.5 font-medium" dir={textDirection(view?.title ?? "")}>
              {view?.title ?? "…"}
            </h2>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <a
              href={api.downloadUrl(target.documentId)}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-sm text-ink-2 hover:border-line-strong"
            >
              <DownloadIcon /> {t("download")}
            </a>
            <button onClick={onClose} className="rounded-md p-1.5 text-muted hover:bg-sunken" aria-label={t("close")}>
              <CloseIcon />
            </button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-5">
          {failed && <p className="text-sm text-muted">—</p>}
          {view?.passages.map((p) => {
            const isCited = p.id === target.chunkId;
            const text = p.text_original;
            const h = isCited ? target.highlight : undefined;
            return (
              <section
                key={p.id}
                ref={isCited ? cited : undefined}
                className={`mb-4 rounded-lg px-4 py-3 ${isCited ? "border border-accent/40 bg-accent-wash/50" : ""}`}
              >
                {(p.page || p.sheet || p.heading) && (
                  <p className="mb-1.5 text-xs text-muted">
                    {isCited && <span className="me-2 font-medium text-accent">{t("citedPassage")}</span>}
                    {sourceLabel(p, t)}
                  </p>
                )}
                <p
                  dir={view.language === "ar" ? "rtl" : textDirection(text)}
                  className="text-[15px] leading-relaxed whitespace-pre-wrap text-ink-2"
                >
                  {h ? (
                    <>
                      {text.slice(0, h.start)}
                      <mark>{text.slice(h.start, h.end)}</mark>
                      {text.slice(h.end)}
                    </>
                  ) : (
                    text
                  )}
                </p>
              </section>
            );
          })}
        </div>
      </aside>
    </div>
  );
}

export function DocumentCardView({ doc }: { doc: DocumentCard }) {
  const { t, lang } = useI18n();
  const open = useOpenDocument();
  const dateLabel = doc.date_kind ? t(doc.date_kind) : t("dated");
  const party = doc.date_kind === "received" ? doc.sender : doc.recipient;
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-1 gap-3">
        <FileIcon className="mt-0.5 size-5 shrink-0 text-muted" />
        <div className="min-w-0 flex-1 text-start">
          {/* <bdi> orders each title by its own script while the card keeps the interface's alignment. */}
          <h3 className="font-medium leading-snug">
            <bdi>{doc.title}</bdi>
          </h3>
          {doc.title_alt && (
            <p className="text-sm text-muted">
              <bdi>{doc.title_alt}</bdi>
            </p>
          )}
          <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
            {doc.date && (
              <div>
                <dt className="inline text-muted">{dateLabel}: </dt>
                <dd className="inline">{formatDate(doc.date, lang)}</dd>
              </div>
            )}
            {party && (
              <div>
                <dt className="inline text-muted">{doc.date_kind === "received" ? t("from") : t("to")}: </dt>
                <dd className="inline">{party}</dd>
              </div>
            )}
            {doc.reference && (
              <div>
                <dt className="inline text-muted">{t("reference")}: </dt>
                <dd className="inline font-mono">
                  <bdi>{doc.reference}</bdi>
                </dd>
              </div>
            )}
            {doc.version > 1 || !doc.is_latest ? (
              <div>
                <dt className="inline text-muted">{t("version")}: </dt>
                <dd className="inline">{doc.version}</dd>
              </div>
            ) : null}
          </dl>
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        {doc.view_chunk_id != null && (
          <button
            onClick={() => open({ documentId: doc.id, chunkId: doc.view_chunk_id! })}
            className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm hover:border-line-strong"
          >
            <EyeIcon /> {t("view")}
          </button>
        )}
        <a
          href={api.downloadUrl(doc.id)}
          className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm hover:border-line-strong"
        >
          <DownloadIcon /> {t("download")}
        </a>
      </div>
    </article>
  );
}

/** A verbatim quote with its source; clicking opens it in the drawer with the span marked. */
export function QuoteView({ citation, title }: { citation: Citation; title?: string }) {
  const { t } = useI18n();
  const open = useOpenDocument();
  return (
    <button
      onClick={() =>
        open({
          documentId: citation.document_id,
          chunkId: citation.chunk_id,
          highlight: { start: citation.start, end: citation.end },
        })
      }
      className="group block w-full rounded-md border-s-2 border-line-strong bg-sunken/60 px-3 py-2 text-start hover:border-accent"
    >
      <span className="block text-[14px] leading-relaxed whitespace-pre-wrap text-ink" dir={textDirection(citation.quote)}>
        “{citation.quote}”
      </span>
      <span className="mt-1 block text-xs text-muted group-hover:text-accent">
        {title ? `${title} · ` : ""}
        {sourceLabel(citation.source, t)}
      </span>
    </button>
  );
}
