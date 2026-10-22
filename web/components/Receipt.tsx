"use client";

import { useState } from "react";
import { useI18n } from "@/lib/i18n";
import type { Receipt } from "@/lib/types";

/** What the browser received: size, SHA-256 of the exact bytes and the time it took.
 *  Two M1 responses with the same hash were byte-identical (SRS 1.5.4). */
export function ReceiptStrip({ receipt, debug }: { receipt: Receipt; debug?: Record<string, unknown> }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3 text-xs text-muted">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono" dir="ltr">
        <span>HTTP {receipt.status}</span>
        <span>
          {receipt.bytes} {t("bytes")}
        </span>
        <span title={receipt.sha256}>sha256 {receipt.sha256.slice(0, 12)}</span>
        <span>{(receipt.ms / 1000).toFixed(2)} s</span>
        {debug && (
          <button onClick={() => setOpen(!open)} className="font-sans text-accent hover:underline">
            {t("debug")} {open ? "−" : "+"}
          </button>
        )}
      </div>
      {open && debug && (
        <pre
          dir="ltr"
          className="mt-2 max-h-80 overflow-auto rounded-md border border-line bg-surface p-3 text-[11px] leading-relaxed text-ink-2"
        >
          {JSON.stringify(debug, null, 2)}
        </pre>
      )}
    </div>
  );
}
