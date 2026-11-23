"use client";

import { fmtInt, fmtPct } from "@/lib/format";
import type { RunSummary } from "@/lib/university/metrics";
import type { SimulationRun } from "@/lib/university/types";
import { StatTile } from "../StatTile";
import { Badge } from "../StatusBadge";
import { Missing, type ProvenanceItem } from "./common";

export function runProvenanceItems(run: SimulationRun): ProvenanceItem[] {
  const p = run.provenance;
  return [
    { label: "Simulation run ID", value: run.run_id, mono: true },
    { label: "Status", value: run.status },
    { label: "Data origin", value: run.origin === "fixture" ? "Fixture (computed in the browser)" : "API" },
    { label: "Simulation engine", value: p.engine, mono: true },
    { label: "Simulation version", value: p.engine_version, mono: true, missing: "not_available" },
    { label: "Simulation seed", value: p.simulation_seed === null || p.simulation_seed === undefined ? null : String(p.simulation_seed) },
    { label: "Registry snapshot", value: p.registry_snapshot_id, mono: true },
    { label: "Admission year", value: String(run.config.admission_year) },
    { label: "Candidate cohort", value: `${p.cohort_id} (${p.cohort_generator_version}, seed ${p.cohort_seed}, ${fmtInt(p.cohort_size)} candidates)` },
    { label: "Quota adjustment", value: `${run.config.quota_adjustment_pct > 0 ? "+" : ""}${run.config.quota_adjustment_pct}%${Object.keys(run.config.program_quota_overrides).length ? ` and ${Object.keys(run.config.program_quota_overrides).length} override(s)` : ""}` },
    { label: "Institutions", value: run.config.included_university_keys === null ? "All in snapshot" : `${run.config.included_university_keys.length} selected` },
    { label: "Configuration fingerprint", value: p.config_hash, mono: true },
    { label: "Created", value: p.created_at },
  ];
}

/** Headline placement metrics. Every rate states its denominator; unknown capacities are excluded and counted. */
export function ResultsOverview({ s }: { s: RunSummary }) {
  return (
    <section className="card stack" aria-labelledby="overview-h">
      <div className="card-head">
        <h2 id="overview-h">Placement summary</h2>
        {s.reconciles
          ? <Badge tone="good" glyph="✓" title="placed + not placed + ineligible = total, and program placements sum to the placed count">Totals reconcile</Badge>
          : <Badge tone="crit" glyph="×">Totals do not reconcile</Badge>}
      </div>
      <div className="tiles">
        <StatTile label="Total synthetic candidates" value={fmtInt(s.total)} sub={`${fmtInt(s.eligible)} eligible · ${fmtInt(s.ineligible)} ineligible`} />
        <StatTile label="Placed" value={fmtInt(s.placed)} sub="Candidates assigned a program" />
        <StatTile label="Not placed (eligible)" value={fmtInt(s.unplaced)} sub="Eligible but not assigned a program" />
        <StatTile label="Placement rate" value={s.placement_rate === null ? <Missing reason="not_calculated" /> : fmtPct(s.placement_rate, 1)} sub={`Placed ÷ eligible (${fmtInt(s.placed)} ÷ ${fmtInt(s.eligible)})`} />
        <StatTile label="Occupied seats" value={fmtInt(s.occupied_seats)} sub={`of ${fmtInt(s.capacity_known)} seats with known capacity`} />
        <StatTile label="Remaining capacity" value={fmtInt(s.remaining_capacity)} sub={s.programs_unknown_capacity ? `${fmtInt(s.programs_unknown_capacity)} program(s) with unknown capacity not counted` : "All programs have a known capacity"} />
        <StatTile label="Capacity utilization" value={s.utilization === null ? <Missing reason="not_calculated" /> : fmtPct(s.utilization, 1)} sub="Occupied ÷ available seats (known capacity)" />
        <StatTile label="First-choice placements" value={s.first_choice_share === null ? <Missing reason="not_calculated" /> : fmtPct(s.first_choice_share, 1)} sub="Placed at preference 1 ÷ placed" />
      </div>
      <p className="formula" aria-label="Placement rate formula">
        Placement rate (%) = placed ÷ eligible × 100 = {fmtInt(s.placed)} ÷ {fmtInt(s.eligible)} × 100 = {s.placement_rate === null ? "not calculated (no eligible candidates)" : `${(s.placement_rate * 100).toFixed(1)}%`}.
        {" "}Eligible = placed + not placed. The {fmtInt(s.ineligible)} candidate(s) the simulation marked ineligible (no eligible preference, or no preferences) are excluded from the denominator.
      </p>
      {s.over_capacity.length ? (
        <p className="notice crit" role="alert" style={{ margin: 0 }}>
          <strong>Capacity exceeded.</strong> {s.over_capacity.length} program(s) have more placements than their scenario capacity: {s.over_capacity.map((o) => `${o.program_code} (${o.placed} > ${o.capacity})`).join(", ")}. Counts are shown unchanged.
        </p>
      ) : null}
    </section>
  );
}
