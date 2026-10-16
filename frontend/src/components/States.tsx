"use client";

import { describeDetails, type ApiError } from "@/lib/api/client";

export function Loading({ what }: { what: string }) {
  return <p className="muted" role="status" aria-live="polite">Loading {what}…</p>;
}

export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="notice" role="status">
      <strong>{title}</strong>
      {children ? <div className="small muted">{children}</div> : null}
    </div>
  );
}

export function UnavailableState({ title, reasons, children }: { title: string; reasons?: string[]; children?: React.ReactNode }) {
  return (
    <div className="notice warn" role="status">
      <strong>{title}</strong>
      {reasons && reasons.length ? <ul>{reasons.map((r) => <li key={r}>{r}</li>)}</ul> : null}
      {children}
    </div>
  );
}

const TITLES: Record<string, string> = {
  network: "Cannot reach the API",
  422: "The request was not accepted",
  404: "Not found",
  409: "Conflict with the current state",
  503: "Unavailable",
  501: "Not available in this release",
  403: "Not permitted from this client",
};

export function ErrorState({ error, onRetry, what }: { error: ApiError; onRetry?: () => void; what?: string }) {
  const key = error.kind === "network" ? "network" : String(error.status);
  const lines = describeDetails(error.details);
  return (
    <div className={`notice ${error.status === 503 || error.status === 409 ? "warn" : "crit"}`} role="alert">
      <strong>{TITLES[key] ?? "Request failed"}{what ? ` (${what})` : ""}.</strong> {error.message}
      {lines.length ? <ul>{lines.map((l, i) => <li key={i}>{l}</li>)}</ul> : null}
      <div className="row small" style={{ marginTop: 6 }}>
        {error.code ? <span className="muted">Code <code>{error.code}</code></span> : null}
        {error.requestId ? <span className="muted">Request <code>{error.requestId}</code></span> : null}
        {onRetry ? <button type="button" className="button small" onClick={onRetry}>Retry</button> : null}
      </div>
    </div>
  );
}
