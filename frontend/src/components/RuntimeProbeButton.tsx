"use client";

import { useState } from "react";
import { api, toApiError, unwrap, type ApiError } from "@/lib/api/client";
import { ErrorState } from "./States";
import { Badge } from "./StatusBadge";

/** Runs the import probe in the runtime interpreter (no provider calls, no writes outside managed logs). */
export function RuntimeProbeButton({ onDone }: { onDone?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | undefined>();
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row">
        <button type="button" className="button small" disabled={busy} onClick={async () => {
          setBusy(true);
          setError(undefined);
          try {
            const probe = await unwrap(api.POST("/api/v1/runtime/probe"));
            setResult(probe.status);
            onDone?.();
          } catch (err) {
            setError(toApiError(err));
          } finally {
            setBusy(false);
          }
        }}>{busy ? "Checking runtime…" : "Check runtime"}</button>
        {result === "passed" ? <Badge tone="good" glyph="✓">Import probe passed</Badge> : null}
        {result === "failed" ? <Badge tone="crit" glyph="×">Import probe failed</Badge> : null}
      </div>
      {error ? <ErrorState error={error} what="runtime check" /> : null}
    </div>
  );
}
