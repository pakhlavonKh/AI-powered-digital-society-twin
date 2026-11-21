"use client";

import { useState } from "react";
import { fmtInt, fmtPct } from "@/lib/format";
import type { RunSummary } from "@/lib/university/metrics";
import type { DataOrigin } from "@/lib/university/types";
import { ordinal } from "@/lib/university/util";
import { BarChartCard } from "../charts/BarChartCard";
import { ChartPanel, Missing } from "./common";

const count = (v: number | null) => fmtInt(v);

/** Charts 1–5 plus the scholarship breakdown, all drawn from the run's assignment-level output. */
export function PlacementCharts({ s, origin }: { s: RunSummary; origin: DataOrigin }) {
  const universities = s.by_university.map((u) => u.key);
  const [uni, setUni] = useState<string>(universities[0] ?? "");
  const programs = s.by_program.filter((p) => p.university === uni);
  const known = programs.filter((p) => p.capacity !== null);
  const unknown = programs.filter((p) => p.capacity === null);

  return (
    <div className="uni-charts">
      <ChartPanel title="Placement overview" origin={origin} units="candidates" axes={{ value: "Synthetic candidates", category: "Outcome" }}
        empty={s.total === 0} explanation="How many synthetic candidates were placed, eligible but not placed, or ineligible. Ineligible candidates are excluded from the placement rate.">
        <BarChartCard title="Placement overview" subtitle={`${fmtInt(s.total)} candidates`} valueLabel="candidates" format={count} valueAxisLabel="Candidates (count)"
          series={[{ key: "n", label: "Candidates", slot: "series-1" }]}
          rows={[
            { category: "placed", label: "Placed", values: { n: s.placed } },
            { category: "unplaced", label: "Not placed (eligible)", values: { n: s.unplaced } },
            { category: "ineligible", label: "Ineligible (excluded)", values: { n: s.ineligible } },
          ]} />
      </ChartPanel>

      <ChartPanel title="Preference ranking" origin={origin} units="placed candidates" axes={{ value: "Placed candidates", category: "Preference position received" }}
        empty={s.placed === 0} emptyText="No candidate was placed, so there is no preference ranking."
        explanation="Which of their ranked choices placed candidates received. Counts sum to the placed total.">
        <BarChartCard title="Preference ranking" subtitle={`${fmtInt(s.placed)} placed`} valueLabel="placed candidates" format={count} valueAxisLabel="Placed candidates (count)"
          series={[{ key: "n", label: "Placed candidates", slot: "series-1" }]}
          rows={s.preference_rank.map((r) => ({ category: String(r.position), label: `${ordinal(r.position)} preference`, values: { n: r.count } }))}
          tableExtra={[{ header: "Share of placed", render: (r) => fmtPct(s.placed ? (r.values.n ?? 0) / s.placed : null) }]} />
      </ChartPanel>

      <ChartPanel title="University distribution" origin={origin} units="seats" wide axes={{ value: "Seats", category: "Institution" }}
        empty={s.by_university.length === 0}
        explanation="Simulated placements by institution next to the institution's known scenario capacity (programs with unknown capacity are not counted in capacity).">
        <BarChartCard title="Placements by institution" valueLabel="seats" format={count} valueAxisLabel="Seats (count)"
          series={[{ key: "placed", label: "Simulated placements", slot: "series-1" }, { key: "capacity", label: "Known capacity", slot: "series-2" }]}
          rows={s.by_university.map((u) => ({ category: u.key, label: u.label, values: { placed: u.placed, capacity: u.capacity } }))}
          tableExtra={[{ header: "Programs with unknown capacity", render: (r) => fmtInt(s.by_university.find((u) => u.key === r.category)?.unknown_capacity_programs ?? 0) }]} />
      </ChartPanel>

      <ChartPanel title="Program capacity" origin={origin} units="seats" wide axes={{ value: "Seats", category: "Program (scholarship)" }}
        empty={programs.length === 0} emptyText="This institution has no programs in the scenario."
        explanation="Scenario capacity against simulated placements for each program of one institution. Placements above capacity are flagged as errors in the summary, never capped.">
        <div className="field" style={{ maxWidth: 360 }}>
          <label htmlFor="capacity-uni">Institution</label>
          <select id="capacity-uni" value={uni} onChange={(e) => setUni(e.target.value)}>
            {universities.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        {known.length ? (
          <BarChartCard title={`Program capacity · ${uni}`} valueLabel="seats" format={count} valueAxisLabel="Seats (count)"
            series={[{ key: "placed", label: "Simulated placements", slot: "series-1" }, { key: "capacity", label: "Scenario capacity", slot: "series-2" }]}
            rows={known.map((p) => ({ category: p.program_code, label: p.label, values: { placed: p.placed, capacity: p.capacity } }))}
            tableExtra={[
              { header: "Reported quota", render: (r) => { const q = known.find((p) => p.program_code === r.category)?.base_quota; return q === null || q === undefined ? <Missing reason="missing_from_source" /> : fmtInt(q); } },
              { header: "Utilization", render: (r) => fmtPct(r.values.capacity ? (r.values.placed ?? 0) / r.values.capacity : null) },
            ]} />
        ) : <p className="small muted">No program at this institution has a known capacity.</p>}
        {unknown.length ? <p className="small muted" style={{ margin: 0 }}>Capacity unknown (no reported quota for the year), so not charted: {unknown.map((p) => `${p.label} (${p.program_code})`).join("; ")}.</p> : null}
      </ChartPanel>

      <ChartPanel title="Score type distribution" origin={origin} units="candidates" axes={{ value: "Synthetic candidates", category: "Candidate score type" }}
        empty={s.by_score_type.length === 0}
        explanation="Eligible candidates and placements by the candidate's score type. Compare the bars to see which score types face the most competition.">
        <BarChartCard title="Placements by score type" valueLabel="candidates" format={count} valueAxisLabel="Candidates (count)"
          series={[{ key: "placed", label: "Placed", slot: "series-1" }, { key: "eligible", label: "Eligible", slot: "series-2" }]}
          rows={s.by_score_type.map((t) => ({ category: t.key, label: t.label, values: { placed: t.placed, eligible: t.eligible } }))}
          tableExtra={[
            { header: "All candidates", render: (r) => fmtInt(s.by_score_type.find((t) => t.key === r.category)?.total ?? null) },
            { header: "Placement rate", render: (r) => fmtPct(r.values.eligible ? (r.values.placed ?? 0) / r.values.eligible : null) },
          ]} />
      </ChartPanel>

      <ChartPanel title="Scholarship category" origin={origin} units="seats" axes={{ value: "Seats", category: "Scholarship label (as in source)" }}
        empty={s.by_scholarship.length === 0}
        explanation="Simulated placements by the program's scholarship label next to the known capacity in that category.">
        <BarChartCard title="Placements by scholarship category" valueLabel="seats" format={count} valueAxisLabel="Seats (count)"
          series={[{ key: "placed", label: "Simulated placements", slot: "series-1" }, { key: "capacity", label: "Known capacity", slot: "series-2" }]}
          rows={s.by_scholarship.map((b) => ({ category: b.key, label: b.label, values: { placed: b.placed, capacity: b.capacity } }))}
          tableExtra={[{ header: "Utilization", render: (r) => fmtPct(r.values.capacity ? (r.values.placed ?? 0) / r.values.capacity : null) }]} />
      </ChartPanel>
    </div>
  );
}
