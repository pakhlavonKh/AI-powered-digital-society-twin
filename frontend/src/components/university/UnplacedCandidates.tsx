"use client";

import Link from "next/link";
import { useState } from "react";
import { cohortRanks } from "@/lib/university/candidates";
import { uniHref } from "@/lib/university/context";
import type { Cohort, SimulationRun } from "@/lib/university/types";
import { fmtInt } from "@/lib/format";
import { EmptyState } from "../States";
import { Missing, Pagination, Value } from "./common";
import { PlacementBadge } from "./RunPicker";

const PAGE = 25;

/**
 * Candidates the run did not place. The reason column shows only what the simulation supplied; when it supplied
 * none, the cell says so instead of guessing.
 */
export function UnplacedCandidates({ run, cohort, snapshot }: { run: SimulationRun; cohort: Cohort; snapshot: string | null }) {
  const [includeIneligible, setIncludeIneligible] = useState(false);
  const [page, setPage] = useState(0);
  const byId = new Map(cohort.candidates.map((c) => [c.candidate_id, c]));
  const prefCount = new Map<string, number>();
  for (const p of cohort.preferences) prefCount.set(p.candidate_id, (prefCount.get(p.candidate_id) ?? 0) + 1);
  const ranks = cohortRanks(cohort);
  const rows = run.assignments
    .filter((a) => a.status === "unplaced" || (includeIneligible && a.status === "ineligible"))
    .sort((a, b) => (byId.get(b.candidate_id)?.achievement?.value ?? -1) - (byId.get(a.candidate_id)?.achievement?.value ?? -1) || (a.candidate_id < b.candidate_id ? -1 : 1));
  const offset = Math.min(page * PAGE, Math.max(0, Math.floor((rows.length - 1) / PAGE) * PAGE));
  const unplaced = run.assignments.filter((a) => a.status === "unplaced").length;
  const ineligible = run.assignments.filter((a) => a.status === "ineligible").length;
  return (
    <section className="card stack" aria-labelledby="unplaced-h" id="unplaced">
      <div className="card-head">
        <h2 id="unplaced-h">Candidates not placed</h2>
        <label className="check"><input type="checkbox" checked={includeIneligible} onChange={(e) => { setIncludeIneligible(e.target.checked); setPage(0); }} />
          Include {fmtInt(ineligible)} ineligible candidate(s)</label>
      </div>
      <p className="small muted" style={{ margin: 0 }}>{fmtInt(unplaced)} eligible candidates were not placed. Sorted by achievement proxy, highest first. Reasons are shown only when the simulation supplied one.</p>
      {rows.length === 0 ? <EmptyState title="Every eligible candidate was placed." /> : (
        <>
          <div className="table-wrap">
            <table>
              <caption>{fmtInt(rows.length)} synthetic candidates without a placement in run {run.run_id}</caption>
              <thead><tr><th scope="col">Candidate ID</th><th scope="col">Status</th><th scope="col">Score type</th><th scope="col" className="num">Achievement proxy</th>
                <th scope="col" className="num">Cohort rank</th><th scope="col" className="num">Preferences</th><th scope="col">Reason (from simulation)</th></tr></thead>
              <tbody>
                {rows.slice(offset, offset + PAGE).map((a) => {
                  const c = byId.get(a.candidate_id);
                  return (
                    <tr key={a.candidate_id}>
                      <th scope="row" className="nowrap"><Link href={uniHref("/university/candidates", snapshot, { run: run.run_id, candidate: a.candidate_id, q: a.candidate_id })}><code>{a.candidate_id}</code></Link></th>
                      <td><PlacementBadge status={a.status} /></td>
                      <td><Value value={c?.score_type} /></td>
                      <td className="num"><Value value={c?.achievement?.value} format={fmtInt} /></td>
                      <td className="num"><Value value={ranks.get(a.candidate_id)} reason="not_calculated" format={fmtInt} /></td>
                      <td className="num">{fmtInt(prefCount.get(a.candidate_id) ?? 0)}</td>
                      <td className="small">{a.reason ?? <Missing reason="not_available" />}{a.reason_code ? <div className="muted"><code>{a.reason_code}</code></div> : null}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination offset={offset} limit={PAGE} total={rows.length} label="Unplaced candidate" onPage={setPage} />
        </>
      )}
    </section>
  );
}
