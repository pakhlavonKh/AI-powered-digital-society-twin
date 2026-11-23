"use client";

import Link from "next/link";
import type { ApiError } from "@/lib/api/client";
import { uniHref } from "@/lib/university/context";
import type { SimulationRun } from "@/lib/university/types";
import { CopyId } from "../CopyId";
import { ErrorState } from "../States";
import { Badge } from "../StatusBadge";
import { SourceBadge } from "./common";

export type ExecutionState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "submitted"; run: SimulationRun; duplicateOf: string | null }
  | { phase: "error"; error: ApiError };

const RUN_STATE = {
  pending: { tone: "info" as const, glyph: "…", label: "Pending", text: "Accepted and waiting to start." },
  running: { tone: "info" as const, glyph: "▸", label: "Running", text: "The simulation is running; status refreshes automatically." },
  completed: { tone: "good" as const, glyph: "✓", label: "Completed", text: "Results are available." },
  failed: { tone: "crit" as const, glyph: "×", label: "Failed", text: "The simulation reported a failure." },
};

/**
 * Execution state for a scenario. A fixture preview says so in its label; success is only reported for a run the
 * data source returned as completed, never assumed.
 */
export function SimulationStatus({ state, snapshot, onRetry, onRefresh }: {
  state: ExecutionState; snapshot: string | null; onRetry: () => void; onRefresh: () => void;
}) {
  if (state.phase === "idle") return <p className="small muted" role="status">Not run yet. Fix any blocking errors, then run the scenario.</p>;
  if (state.phase === "submitting") return <p className="small" role="status" aria-live="polite"><Badge tone="info" glyph="…">Submitting</Badge> Sending the scenario to the data source…</p>;
  if (state.phase === "error") {
    return (
      <div className="stack" role="status">
        <ErrorState error={state.error} what="scenario execution" />
        <div><button type="button" className="button small" onClick={onRetry}>Retry submission</button></div>
      </div>
    );
  }
  const { run, duplicateOf } = state;
  const s = RUN_STATE[run.status];
  const fixture = run.origin === "fixture";
  return (
    <div className="stack" role="status" aria-live="polite">
      <div className="run-status">
        <Badge tone={s.tone} glyph={s.glyph}>{fixture && run.status === "completed" ? "Fixture preview completed" : s.label}</Badge>
        <SourceBadge origin={run.origin} />
        <span className="small">Run <CopyId value={run.run_id} label="run ID" /></span>
      </div>
      <p className="small" style={{ margin: 0 }}>
        {fixture ? "Demo mode: computed in this browser by the illustrative fixture allocation. No backend simulation ran." : s.text}
        {run.error ? <> Error: {run.error}</> : null}
      </p>
      {duplicateOf ? <p className="notice info small" style={{ margin: 0 }}>An identical configuration was already run, so no duplicate was created. Showing the existing run.</p> : null}
      {run.status === "pending" || run.status === "running" ? <div><button type="button" className="button small" onClick={onRefresh}>Refresh status</button></div> : null}
      {run.status === "failed" ? <div><button type="button" className="button small" onClick={onRetry}>Retry</button></div> : null}
      {run.status === "completed" ? (
        <div className="row">
          <Link className="button primary small" href={uniHref("/university/results", snapshot, { run: run.run_id })}>View placement results</Link>
          <Link className="button small" href={uniHref("/university/compare", snapshot, { b: run.run_id })}>Compare with another run</Link>
          <Link className="button small" href={uniHref("/university/candidates", snapshot, { run: run.run_id })}>Inspect candidates</Link>
        </div>
      ) : null}
    </div>
  );
}
