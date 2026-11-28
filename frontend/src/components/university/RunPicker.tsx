"use client";

import type { AssignmentStatus, RunListItem } from "@/lib/university/types";
import { Badge } from "../StatusBadge";

const KIND_LABEL: Record<RunListItem["kind"], string> = { builtin_fixture: "built-in fixture", session_fixture: "fixture preview, this session", api: "API run" };

export function runLabel(r: RunListItem): string {
  return `${r.name} · ${r.admission_year} · ${r.cohort_size.toLocaleString("en-GB")} candidates · ${KIND_LABEL[r.kind]}`;
}

export function RunPicker({ id, label, runs, value, onChange, allowNone, noneLabel = "No run (candidates only)", hint }: {
  id: string; label: string; runs: RunListItem[]; value: string | null; onChange: (runId: string | null) => void; allowNone?: boolean; noneLabel?: string; hint?: string;
}) {
  const known = value === null || runs.some((r) => r.run_id === value);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}>
        {allowNone ? <option value="">{noneLabel}</option> : null}
        {!known && value ? <option value={value}>{value} (not found)</option> : null}
        {runs.map((r) => <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>)}
      </select>
      {hint ? <span className="field-hint">{hint}</span> : null}
    </div>
  );
}

export function PlacementBadge({ status }: { status: AssignmentStatus | null | undefined }) {
  if (status === "placed") return <Badge tone="good" glyph="✓" title="Placed by the selected simulation run">Placed</Badge>;
  if (status === "unplaced") return <Badge tone="warn" glyph="○" title="Eligible but not placed in the selected run">Not placed</Badge>;
  if (status === "ineligible") return <Badge tone="neutral" glyph="–" title="Not eligible for any preference in the selected run; excluded from the placement-rate denominator">Ineligible</Badge>;
  return <Badge tone="neutral" glyph="…" title="Pending: select a simulation run to see placement outcomes.">No run selected</Badge>;
}
