"use client";

import { useState } from "react";

export function CopyId({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="copy">
      <code>{value}</code>
      <button
        type="button"
        className="button small"
        aria-label={`Copy ${label ?? "ID"} ${value}`}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            setCopied(false);
          }
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}
