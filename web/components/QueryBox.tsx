"use client";

import { useEffect, useRef, useState } from "react";
import { textDirection, useI18n } from "@/lib/i18n";
import { SendIcon } from "./icons";

interface Props {
  placeholder: string;
  busy: boolean;
  busyLabel: string;
  maxChars: number;
  tooLongMessage: string;
  onSubmit: (text: string) => void;
}

/** Enter sends, Shift+Enter adds a line (SRS 1.11.10). The text box takes the direction
 *  of the first strong character typed, independent of the interface language (1.11.11).
 *  A query over the limit is not sent: M5 is shown and the text is kept (1.11.6, 1.11.7). */
export function QueryBox({ placeholder, busy, busyLabel, maxChars, tooLongMessage, onSubmit }: Props) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    const timer = setInterval(() => setElapsed((Date.now() - started) / 1000), 100);
    return () => {
      clearInterval(timer);
      setElapsed(0);
    };
  }, [busy]);

  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  const tooLong = text.trim().length > maxChars;

  function submit() {
    const query = text.trim();
    if (!query || busy || tooLong) return;
    onSubmit(query);
    setText("");
  }

  return (
    <div className="rounded-xl border border-line-strong bg-surface shadow-[0_1px_0_rgba(0,0,0,0.03)] focus-within:border-accent">
      <textarea
        ref={area}
        value={text}
        dir={textDirection(text) ?? "auto"}
        rows={1}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-relaxed outline-none placeholder:text-muted"
      />
      <div className="flex items-center justify-between gap-3 px-3 pb-2.5">
        <span className="text-xs text-muted" aria-live="polite">
          {tooLong ? (
            <span className="text-ochre">{tooLongMessage}</span>
          ) : busy ? (
            <span className="inline-flex items-center gap-2 text-accent">
              <span className="size-1.5 animate-pulse rounded-full bg-accent" />
              {busyLabel}
              <span className="tabular-nums" dir="ltr">
                {elapsed.toFixed(1)} s
              </span>
            </span>
          ) : (
            t("keyHint")
          )}
        </span>
        <button
          onClick={submit}
          disabled={busy || !text.trim() || tooLong}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-ink disabled:bg-line-strong"
        >
          {t("send")}
          <SendIcon className="flip-rtl size-4" />
        </button>
      </div>
    </div>
  );
}
