"use client";

import { useEffect, useState } from "react";
import { CANDIDATE_PAGE_SIZE, type CandidateUrlState } from "@/lib/university/candidates";
import { useCatalogue, useUniversitySource } from "@/lib/university/context";
import { preferenceChecks } from "@/lib/university/quality";
import type { CandidateSortKey, CohortManifest, Finding, RegistrySnapshot, RunListItem } from "@/lib/university/types";
import { fmtInt } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { EmptyState, ErrorState, Loading } from "../States";
import { StatTile } from "../StatTile";
import { CandidateDetails, cohortProvenance } from "./CandidateDetails";
import { DataKindBadge, DataQualityPanel, Missing, Pagination, ProvenancePanel, SortHeader, Value } from "./common";
import { PlacementBadge, RunPicker } from "./RunPicker";

function NumberInput({ id, label, value, resetKey, onCommit }: { id: string; label: string; value: number | null; resetKey: number; onCommit: (v: number | null) => void }) {
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => { setText(value === null ? "" : String(value)); }, [value, resetKey]);
  const invalid = text !== "" && (!Number.isFinite(Number(text)) || Number(text) < 0 || Number(text) > 10000);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="number" min={0} max={10000} value={text} aria-invalid={invalid || undefined}
        onChange={(e) => setText(e.target.value)} onBlur={() => !invalid && onCommit(text === "" ? null : Number(text))}
        onKeyDown={(e) => { if (e.key === "Enter" && !invalid) onCommit(text === "" ? null : Number(text)); }} />
      {invalid ? <span className="field-error" role="alert">Enter a number from 0 to 10,000.</span> : null}
    </div>
  );
}

export function CandidateExplorer({ snapshot, cohorts, runs, cohortId, runId, onRun, onCohort, state, onChange, selected, onSelect }: {
  snapshot: RegistrySnapshot; cohorts: CohortManifest[]; runs: RunListItem[]; cohortId: string; runId: string | null;
  onRun: (id: string | null) => void; onCohort: (id: string) => void; state: CandidateUrlState; onChange: (s: CandidateUrlState) => void;
  selected: string | null; onSelect: (id: string | null) => void;
}) {
  const source = useUniversitySource();
  const catalogue = useCatalogue(snapshot.snapshot_id);
  const [text, setText] = useState(state.search);
  const [resetNonce, setResetNonce] = useState(0);
  useEffect(() => { setText(state.search); }, [state.search]);
  const query = { ...state, cohort_id: cohortId, run_id: runId, status: runId ? state.status : null, offset: state.page * CANDIDATE_PAGE_SIZE, limit: CANDIDATE_PAGE_SIZE };
  const page = useApi(`uni:${source.id}:candidates:${JSON.stringify(query)}`, (signal) => source.queryCandidates(query, signal));
  const cohort = useApi(`uni:${source.id}:cohort:${cohortId}`, (signal) => source.getCohort(cohortId, signal));
  const set = (patch: Partial<CandidateUrlState>) => onChange({ ...state, ...patch, page: 0 });
  const onSort = (k: CandidateSortKey) => onChange({ ...state, sort: k, direction: state.sort === k ? (state.direction === "asc" ? "desc" : "asc") : k === "id" || k === "rank" ? "asc" : "desc", page: 0 });
  const p = page.data;
  const manifest = cohorts.find((c) => c.cohort_id === cohortId) ?? p?.manifest;
  const run = runs.find((r) => r.run_id === runId) ?? null;
  const cat = catalogue.data;
  const programNames = new Map((cat?.programs ?? []).map((x) => [x.program_code, x]));
  const uniNames = new Map((cat?.universities ?? []).map((u) => [u.university_id, u.name_original]));

  let findings: Finding[] = [];
  let incomplete = 0;
  if (cohort.data && cat) {
    const codes = new Set(cat.programs.map((x) => x.program_code));
    const byCandidate = new Map<string, typeof cohort.data.preferences>();
    for (const pref of cohort.data.preferences) byCandidate.set(pref.candidate_id, [...(byCandidate.get(pref.candidate_id) ?? []), pref]);
    for (const c of cohort.data.candidates) {
      const f = preferenceChecks(c.candidate_id, byCandidate.get(c.candidate_id) ?? [], codes);
      if (f.length) incomplete += 1;
      findings = findings.concat(f);
    }
  }

  return (
    <div className="explorer2">
      <section className="card filters2" aria-label="Candidate filters">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Filters</h2>
          <button type="button" className="button small" onClick={() => { setText(""); setResetNonce((n) => n + 1); onChange({ search: "", score_types: [], proxy_min: null, proxy_max: null, status: null, sort: state.sort, direction: state.direction, page: 0 }); }}>Reset filters</button>
        </div>
        <RunPicker id="candidate-run" label="Placement shown from run" runs={runs} value={runId} onChange={onRun} allowNone
          hint="Placement status comes from the selected simulation run. Choosing a run also selects its cohort." />
        <div className="field">
          <label htmlFor="candidate-cohort">Candidate cohort</label>
          <select id="candidate-cohort" value={cohortId} disabled={runId !== null} onChange={(e) => onCohort(e.target.value)}>
            {cohorts.map((c) => <option key={c.cohort_id} value={c.cohort_id}>{c.cohort_id}</option>)}
            {!cohorts.some((c) => c.cohort_id === cohortId) ? <option value={cohortId}>{cohortId}</option> : null}
          </select>
        </div>
        <form className="field" role="search" onSubmit={(e) => { e.preventDefault(); set({ search: text.trim() }); }}>
          <label htmlFor="candidate-search">Search synthetic candidate ID</label>
          <div className="row">
            <input id="candidate-search" type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="candidate-00000042" style={{ flex: "1 1 140px" }} />
            <button type="submit" className="button small">Search</button>
          </div>
        </form>
        <fieldset>
          <legend>Score type</legend>
          <div className="checks">
            {(p?.score_types ?? []).map((s) => (
              <label className="check" key={s.value}>
                <input type="checkbox" checked={state.score_types.includes(s.value)}
                  onChange={() => set({ score_types: state.score_types.includes(s.value) ? state.score_types.filter((x) => x !== s.value) : [...state.score_types, s.value] })} />
                {s.label} <span className="muted small">({fmtInt(s.count)})</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="age-row">
          <NumberInput id="proxy-min" label="Proxy from" value={state.proxy_min} resetKey={resetNonce} onCommit={(v) => set({ proxy_min: v })} />
          <NumberInput id="proxy-max" label="Proxy to" value={state.proxy_max} resetKey={resetNonce} onCommit={(v) => set({ proxy_max: v })} />
        </div>
        <p className="field-hint" style={{ margin: 0 }}>Achievement proxy: synthetic 0–10,000, higher is better. Not a YKS score or rank.</p>
        <fieldset disabled={runId === null}>
          <legend>Placement status{runId === null ? " · select a run" : ""}</legend>
          <div className="checks">
            {([[null, "Any"], ["placed", "Placed"], ["unplaced", "Not placed"], ["ineligible", "Ineligible"]] as const).map(([v, l]) => (
              <label className="check" key={l}><input type="radio" name="candidate-status" checked={state.status === v} onChange={() => set({ status: v })} />{l}</label>
            ))}
          </div>
        </fieldset>
      </section>
      <div className="stack">
        {selected ? <CandidateDetails cohortId={cohortId} candidateId={selected} runId={runId} catalogue={cat} onClose={() => onSelect(null)} /> : null}
        {page.error ? <ErrorState error={page.error} onRetry={page.reload} what="candidates" /> : null}
        {page.loading && !p ? <Loading what="synthetic candidates" /> : null}
        {p ? (
          <div className={page.stale ? "stack is-stale" : "stack"}>
            <div className="tiles">
              <StatTile label="Matching candidates" value={fmtInt(p.total_matching)} sub={`of ${fmtInt(p.manifest.configuration.size)} in the cohort`} />
              <StatTile label="Cohort seed" value={p.manifest.configuration.seed} sub={p.manifest.generator_version} />
              <StatTile label="Placement context" value={<span className="tile-text">{run ? run.name : "No run selected"}</span>} sub={run ? `Admission year ${run.admission_year}` : "Select a run to see outcomes"} />
            </div>
            <section className="card" aria-labelledby="cand-h">
              <div className="card-head"><h2 id="cand-h">Synthetic candidates</h2><span className="row small"><DataKindBadge kind="synthetic" />{run ? <DataKindBadge kind="simulation" /> : null}</span></div>
              {p.total_matching === 0 ? <EmptyState title="No candidates match these filters.">Reset the filters or widen the proxy range.</EmptyState> : (
                <>
                  <div className="table-wrap">
                    <table className="candidate-table data-table">
                      <caption>{fmtInt(p.total_matching)} matching synthetic candidates; cohort rank is derived from the proxy (ties share a rank)</caption>
                      <thead>
                        <tr>
                          <SortHeader label="Candidate ID" sortKey="id" current={state.sort} direction={state.direction} onSort={onSort} className="col-id" />
                          <th scope="col" className="num">Age</th><th scope="col">Score type</th>
                          <SortHeader label="Achievement proxy" sortKey="proxy" current={state.sort} direction={state.direction} onSort={onSort} numeric />
                          <SortHeader label="Cohort rank (derived)" sortKey="rank" current={state.sort} direction={state.direction} onSort={onSort} numeric />
                          <SortHeader label="Preferences" sortKey="preferences" current={state.sort} direction={state.direction} onSort={onSort} numeric />
                          <th scope="col">Placement</th><th scope="col" className="col-assigned">Assigned program</th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.items.map((r) => {
                          const a = r.assignment;
                          const prog = a?.program_code ? programNames.get(a.program_code) : undefined;
                          return (
                            <tr key={r.candidate.candidate_id} className={selected === r.candidate.candidate_id ? "is-selected" : undefined}>
                              <th scope="row" className="nowrap"><button type="button" className="linkish" onClick={() => onSelect(r.candidate.candidate_id)}><code>{r.candidate.candidate_id}</code></button></th>
                              <td className="num">{r.candidate.age}</td>
                              <td><Value value={r.candidate.score_type} /></td>
                              <td className="num"><Value value={r.candidate.achievement?.value} format={fmtInt} /></td>
                              <td className="num"><Value value={r.cohort_rank} reason="not_calculated" format={fmtInt} /></td>
                              <td className="num">{fmtInt(r.preference_count)}{r.valid_reference_count < r.preference_count ? <span className="warn-text" title="Some preferences reference unknown program codes"> ({fmtInt(r.preference_count - r.valid_reference_count)} invalid)</span> : null}</td>
                              <td><PlacementBadge status={runId ? a?.status ?? null : null} /></td>
                              <td>{a?.status === "placed" ? (prog ? <>{prog.name_original}<div className="small muted">{uniNames.get(prog.university_id)} · pref. {a.preference_position}</div></> : <code>{a.program_code}</code>)
                                : runId ? <Missing reason="not_applicable" /> : <Missing reason="not_calculated" />}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <Pagination offset={p.offset} limit={p.limit} total={p.total_matching} label="Candidate" onPage={(n) => onChange({ ...state, page: n })} />
                </>
              )}
            </section>
          </div>
        ) : null}
        {cohort.data && cat ? (
          <DataQualityPanel title="Cohort data quality" records={cohort.data.candidates.length} recordLabel="Candidates loaded" incomplete={incomplete}
            incompleteNote="Candidates with no preferences or invalid preference references" findings={findings} origin={cohort.data.manifest.origin}
            source={cohort.data.manifest.preference_source} version={cohort.data.manifest.generator_version} />
        ) : cohort.error ? <ErrorState error={cohort.error} onRetry={cohort.reload} what="cohort" /> : null}
        {manifest ? <ProvenancePanel title="Cohort provenance" origin={manifest.origin} items={cohortProvenance(manifest)} /> : null}
      </div>
    </div>
  );
}
