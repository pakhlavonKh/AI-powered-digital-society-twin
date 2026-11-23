"use client";

import Link from "next/link";
import { useState } from "react";
import { fmtInt, fmtPct, fmtPp } from "@/lib/format";
import { uniHref } from "@/lib/university/context";
import { compareRuns, TRANSITION_LABELS, type RunComparison, type TransitionKind } from "@/lib/university/metrics";
import type { RegistryCatalogue, SimulationRun } from "@/lib/university/types";
import { fmtSignedInt, fmtSignedPct, ordinal } from "@/lib/university/util";
import { BarChartCard } from "../charts/BarChartCard";
import { DivergingBars } from "../charts/DivergingBars";
import { StatTile } from "../StatTile";
import { ChartPanel, Missing, Pagination } from "./common";

const PAGE = 25;

function Delta({ value, kind }: { value: number | null; kind: "int" | "pp" | "pct" }) {
  if (value === null) return <Missing reason="not_calculated" />;
  const text = kind === "int" ? fmtSignedInt(value) : kind === "pp" ? fmtPp(value, 1) : fmtSignedPct(value, 1);
  // Neutral ink: whether a change is good depends on the metric, so the sign alone carries direction.
  return <span>{text}</span>;
}

function codeLabel(catalogue: RegistryCatalogue, code: string | null): string {
  if (!code) return "–";
  const p = catalogue.programs.find((x) => x.program_code === code);
  return p ? `${p.name_original} · ${p.scholarship_original ?? "?"}` : code;
}

/** Comparison of two compatible runs. A = reference, B = modified scenario; every difference is B − A. */
export function ScenarioComparison({ runA, runB, catalogue, scoreTypes, snapshot }: {
  runA: SimulationRun; runB: SimulationRun; catalogue: RegistryCatalogue; scoreTypes?: Map<string, string | null>; snapshot: string | null;
}) {
  const cmp: RunComparison = compareRuns(runA, runB, catalogue, scoreTypes);
  const [allPrograms, setAllPrograms] = useState(false);
  const [page, setPage] = useState(0);
  const { a, b } = cmp;
  const programs = allPrograms ? cmp.programs : cmp.programs.filter((p) => p.diff !== 0 || p.a_capacity !== p.b_capacity);
  const changed = cmp.candidates.changed;
  const offset = Math.min(page * PAGE, Math.max(0, Math.floor((changed.length - 1) / PAGE) * PAGE));
  const origin = runA.origin;

  return (
    <div className="stack">
      <section className="card stack" aria-labelledby="diff-h">
        <div className="card-head"><h2 id="diff-h">What changed (B − A)</h2><span className="small muted">pp = percentage points; % = relative change</span></div>
        <div className="tiles">
          <StatTile label="Placement rate A → B" value={<>{fmtPct(a.placement_rate, 1)} → {fmtPct(b.placement_rate, 1)}</>}
            sub={<>Difference <Delta value={cmp.placement_rate_pp} kind="pp" /> · relative <Delta value={cmp.placement_rate_rel_pct} kind="pct" /></>} />
          <StatTile label="Placed candidates" value={<Delta value={cmp.placed_diff} kind="int" />} sub={`${fmtInt(a.placed)} → ${fmtInt(b.placed)}`} />
          <StatTile label="Unplaced candidates (eligible)" value={<Delta value={cmp.unplaced_diff} kind="int" />} sub={`${fmtInt(a.unplaced)} → ${fmtInt(b.unplaced)}`} />
          <StatTile label="Ineligible candidates" value={<Delta value={cmp.ineligible_diff} kind="int" />} sub={`${fmtInt(a.ineligible)} → ${fmtInt(b.ineligible)}`} />
          <StatTile label="Known capacity (seats)" value={<Delta value={cmp.capacity_diff} kind="int" />} sub={`${fmtInt(a.capacity_known)} → ${fmtInt(b.capacity_known)}`} />
          <StatTile label="Capacity utilization" value={<Delta value={cmp.utilization_pp} kind="pp" />} sub={`${fmtPct(a.utilization, 1)} → ${fmtPct(b.utilization, 1)}`} />
          <StatTile label="First-choice share" value={<Delta value={cmp.first_choice_pp} kind="pp" />} sub={`${fmtPct(a.first_choice_share, 1)} → ${fmtPct(b.first_choice_share, 1)}`} />
        </div>
        <p className="formula" aria-label="Comparison formulas">
          Placement rate difference = B − A = {fmtPct(b.placement_rate, 2)} − {fmtPct(a.placement_rate, 2)} = {fmtPp(cmp.placement_rate_pp, 2)}.
          {" "}Relative change = (B − A) ÷ A × 100 = {fmtSignedPct(cmp.placement_rate_rel_pct, 2)}.
          {" "}Unplaced candidate difference = B unplaced − A unplaced = {fmtInt(b.unplaced)} − {fmtInt(a.unplaced)} = {fmtSignedInt(cmp.unplaced_diff)}.
          {" "}Capacity utilization = occupied seats ÷ available seats × 100 (known capacities only).
        </p>
      </section>

      <div className="uni-charts">
        <ChartPanel title="Scenario comparison by institution" origin={origin} units="seats" wide axes={{ value: "Simulated placements", category: "Institution" }}
          empty={cmp.universities.length === 0} explanation="Simulated placements per institution in Scenario A and Scenario B.">
          <BarChartCard title="Placements by institution: A vs B" valueLabel="seats" format={(v) => fmtInt(v)} valueAxisLabel="Placements (count)"
            series={[{ key: "a", label: `A · ${runA.config.name}`, slot: "series-2" }, { key: "b", label: `B · ${runB.config.name}`, slot: "series-1" }]}
            rows={cmp.universities.map((u) => ({ category: u.key, label: u.label, values: { a: u.a, b: u.b } }))}
            tableExtra={[{ header: "B − A", render: (r) => fmtSignedInt((r.values.b ?? 0) - (r.values.a ?? 0)) },
              { header: "Relative change", render: (r) => fmtSignedPct(cmp.universities.find((u) => u.key === r.category)?.rel_pct ?? null) }]} />
        </ChartPanel>
        <ChartPanel title="Change in placements by institution" origin={origin} units="seats" axes={{ value: "Change in placements, B − A", category: "Institution" }}
          empty={cmp.universities.length === 0} explanation="Positive bars: more placements in B than A; negative bars: fewer.">
          <DivergingBars title="Change in placements (B − A)" rowHeight={36} positiveLabel="More placements in B" negativeLabel="Fewer placements in B" format={(v) => fmtSignedInt(v)}
            rows={cmp.universities.map((u) => ({ category: u.key, label: u.label, value: u.diff, detail: `${fmtInt(u.a)} → ${fmtInt(u.b)}` }))} />
        </ChartPanel>
        <ChartPanel title="Preference satisfaction" origin={origin} units="counts" axes={{ value: "Placed candidates", category: "Preference position received" }}
          empty={cmp.preference_rank.length === 0} emptyText="Neither run placed anyone." explanation="How many placed candidates received each preference position in A and B.">
          <BarChartCard title="Preference received: A vs B" valueLabel="placed candidates" format={(v) => fmtInt(v)} valueAxisLabel="Placed candidates (count)"
            series={[{ key: "a", label: "Scenario A", slot: "series-2" }, { key: "b", label: "Scenario B", slot: "series-1" }]}
            rows={cmp.preference_rank.map((r) => ({ category: String(r.position), label: `${ordinal(r.position)} preference`, values: { a: r.a, b: r.b } }))}
            tableExtra={[{ header: "B − A", render: (r) => fmtSignedInt((r.values.b ?? 0) - (r.values.a ?? 0)) }]} />
        </ChartPanel>
      </div>

      <section className="card stack" aria-labelledby="prog-h">
        <div className="card-head">
          <h2 id="prog-h">Program-level changes</h2>
          <label className="check"><input type="checkbox" checked={allPrograms} onChange={(e) => setAllPrograms(e.target.checked)} />Show unchanged programs too</label>
        </div>
        {programs.length === 0 ? <p className="small muted">No program changed its capacity or placements.</p> : (
          <div className="table-wrap">
            <table>
              <caption>{fmtInt(programs.length)} program(s){allPrograms ? "" : " with a change"}; utilization = placed ÷ capacity, change in percentage points</caption>
              <thead><tr><th scope="col">Program</th><th scope="col">Institution</th><th scope="col" className="num">Capacity A → B</th><th scope="col" className="num">Placed A → B</th>
                <th scope="col" className="num">B − A</th><th scope="col" className="num">Utilization A → B</th><th scope="col" className="num">Utilization change</th></tr></thead>
              <tbody>
                {programs.map((p) => (
                  <tr key={p.program_code}>
                    <th scope="row">{p.label}<div className="small muted"><code>{p.program_code}</code></div></th>
                    <td>{p.university}</td>
                    <td className="num">{p.a_capacity === null ? <Missing reason="not_available" /> : fmtInt(p.a_capacity)} → {p.b_capacity === null ? <Missing reason="not_available" /> : fmtInt(p.b_capacity)}</td>
                    <td className="num">{fmtInt(p.a_placed)} → {fmtInt(p.b_placed)}</td>
                    <td className="num"><Delta value={p.diff} kind="int" /></td>
                    <td className="num">{fmtPct(p.a_util, 0)} → {fmtPct(p.b_util, 0)}</td>
                    <td className="num"><Delta value={p.util_pp} kind="pp" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card stack" aria-labelledby="cand-diff-h">
        <div className="card-head"><h2 id="cand-diff-h">Candidate-level changes</h2><span className="small muted">Matched by synthetic candidate ID within the same cohort</span></div>
        <div className="table-wrap">
          <table>
            <caption>{fmtInt(cmp.candidates.matched)} candidates in both runs{cmp.candidates.only_a || cmp.candidates.only_b ? `; ${fmtInt(cmp.candidates.only_a)} only in A, ${fmtInt(cmp.candidates.only_b)} only in B (not compared)` : ""}</caption>
            <thead><tr><th scope="col">Outcome A → B</th><th scope="col" className="num">Candidates</th></tr></thead>
            <tbody>{(Object.keys(TRANSITION_LABELS) as TransitionKind[]).map((k) => (
              <tr key={k}><th scope="row">{TRANSITION_LABELS[k]}</th><td className="num">{fmtInt(cmp.candidates.transitions[k])}</td></tr>
            ))}</tbody>
          </table>
        </div>
        {changed.length ? (
          <>
            <div className="table-wrap">
              <table>
                <caption>{fmtInt(changed.length)} candidates whose outcome changed</caption>
                <thead><tr><th scope="col">Candidate</th><th scope="col">Change</th><th scope="col">In A</th><th scope="col">In B</th></tr></thead>
                <tbody>
                  {changed.slice(offset, offset + PAGE).map((c) => (
                    <tr key={c.candidate_id}>
                      <th scope="row" className="nowrap"><Link href={uniHref("/university/candidates", snapshot, { run: runB.run_id, candidate: c.candidate_id, q: c.candidate_id })}><code>{c.candidate_id}</code></Link></th>
                      <td>{TRANSITION_LABELS[c.kind]}</td>
                      <td>{c.a_status === "placed" ? codeLabel(catalogue, c.a_program) : c.a_status}</td>
                      <td>{c.b_status === "placed" ? codeLabel(catalogue, c.b_program) : c.b_status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination offset={offset} limit={PAGE} total={changed.length} label="Changed candidate" onPage={setPage} />
          </>
        ) : <p className="small muted">No candidate changed outcome.</p>}
      </section>
    </div>
  );
}
