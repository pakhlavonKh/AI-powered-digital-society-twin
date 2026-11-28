"use client";

import { useEffect, useState } from "react";
import { defaultCandidateState, type CandidateUrlState } from "@/lib/university/candidates";
import { useCatalogue, useRun, useUniversitySource } from "@/lib/university/context";
import { scoreTypeDisplay } from "@/lib/university/labels";
import { PAGE_SIZES } from "@/lib/university/programs";
import { preferenceChecks } from "@/lib/university/quality";
import type { CandidateEligibilityFilter, CandidateSortKey, CandidateStatusFilter, CohortManifest, Finding, RegistrySnapshot, RunListItem } from "@/lib/university/types";
import { fmtInt, fmtPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { Icon } from "../Icon";
import { EmptyState, ErrorState, Loading } from "../States";
import { StatTile } from "../StatTile";
import { CandidateDetails, cohortProvenance } from "./CandidateDetails";
import { ActiveFilters, DataKindBadge, DataQualityPanel, FilterMenu, Missing, Pagination, ProvenancePanel, ScoreChip, SortHeader, SourceTerm, Value } from "./common";
import { PlacementBadge, runLabel } from "./RunPicker";

function NumberInput({ id, label, value, resetKey, onCommit, placeholder }: { id: string; label: string; value: number | null; resetKey: number; onCommit: (v: number | null) => void; placeholder: string }) {
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => { setText(value === null ? "" : String(value)); }, [value, resetKey]);
  const invalid = text !== "" && (!Number.isFinite(Number(text)) || Number(text) < 0 || Number(text) > 10000);
  return (
    <span className="range-input">
      <input id={id} type="number" min={0} max={10000} value={text} aria-label={label} placeholder={placeholder} aria-invalid={invalid || undefined}
        aria-describedby={invalid ? `${id}-err` : undefined}
        onChange={(e) => setText(e.target.value)} onBlur={() => !invalid && onCommit(text === "" ? null : Number(text))}
        onKeyDown={(e) => { if (e.key === "Enter" && !invalid) onCommit(text === "" ? null : Number(text)); }} />
      {invalid ? <span className="field-error" id={`${id}-err`} role="alert">0 to 10,000</span> : null}
    </span>
  );
}

const STATUS_OPTIONS: [CandidateStatusFilter | "", string][] = [["", "Any"], ["placed", "Placed"], ["unplaced", "Not placed"]];
const ELIGIBILITY_OPTIONS: [CandidateEligibilityFilter | "", string][] = [["", "Any"], ["eligible", "Eligible"], ["ineligible", "Ineligible"]];

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
  const query = { ...state, cohort_id: cohortId, run_id: runId, status: runId ? state.status : null, eligibility: runId ? state.eligibility : null,
    offset: state.page * state.size, limit: state.size };
  const page = useApi(`uni:${source.id}:candidates:${JSON.stringify(query)}`, (signal) => source.queryCandidates(query, signal));
  const cohort = useApi(`uni:${source.id}:cohort:${cohortId}`, (signal) => source.getCohort(cohortId, signal));
  const runDetail = useRun(runId);
  const set = (patch: Partial<CandidateUrlState>) => onChange({ ...state, ...patch, page: 0 });
  const onSort = (k: CandidateSortKey) => onChange({ ...state, sort: k, direction: state.sort === k ? (state.direction === "asc" ? "desc" : "asc") : k === "id" || k === "rank" ? "asc" : "desc", page: 0 });
  const reset = () => { setText(""); setResetNonce((n) => n + 1); onChange({ ...defaultCandidateState(), sort: state.sort, direction: state.direction, size: state.size }); };
  const p = page.data;
  const manifest = cohorts.find((c) => c.cohort_id === cohortId) ?? p?.manifest;
  const run = runs.find((r) => r.run_id === runId) ?? null;
  const cat = catalogue.data;
  const programNames = new Map((cat?.programs ?? []).map((x) => [x.program_code, x]));
  const uniNames = new Map((cat?.universities ?? []).map((u) => [u.university_id, u.name_original]));
  const showProvince = (p?.provinces.length ?? 0) > 0;

  // Summary over the whole cohort and the selected run (not just the filtered page). Without a run, placement figures are unavailable, never zero.
  const total = manifest?.configuration.size ?? cohort.data?.candidates.length ?? null;
  const assignments = runId ? runDetail.data?.assignments ?? null : null;
  const counts = assignments ? {
    placed: assignments.filter((a) => a.status === "placed").length,
    unplaced: assignments.filter((a) => a.status === "unplaced").length,
    ineligible: assignments.filter((a) => a.status === "ineligible").length,
  } : null;
  const eligible = counts ? counts.placed + counts.unplaced : null;
  const needRun = <span className="tile-text missing">{runId && runDetail.loading ? "Loading…" : "Select a run"}</span>;

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

  const chips: { key: string; label: string; onRemove: () => void }[] = [];
  if (state.search) chips.push({ key: "q", label: `ID: “${state.search}”`, onRemove: () => { setText(""); set({ search: "" }); } });
  for (const s of state.score_types) chips.push({ key: `s:${s}`, label: `Score type: ${scoreTypeDisplay(s)}`, onRemove: () => set({ score_types: state.score_types.filter((x) => x !== s) }) });
  if (state.proxy_min !== null || state.proxy_max !== null) chips.push({ key: "proxy", label: `Achievement proxy: ${state.proxy_min ?? 0}–${state.proxy_max ?? "10,000"}`, onRemove: () => { setResetNonce((n) => n + 1); set({ proxy_min: null, proxy_max: null }); } });
  if (runId && state.eligibility) chips.push({ key: "elig", label: `Eligibility: ${state.eligibility === "eligible" ? "Eligible" : "Ineligible"}`, onRemove: () => set({ eligibility: null }) });
  if (runId && state.status) chips.push({ key: "status", label: `Placement: ${state.status === "placed" ? "Placed" : state.status === "unplaced" ? "Not placed" : "Ineligible"}`, onRemove: () => set({ status: null }) });
  for (const pr of state.provinces) chips.push({ key: `p:${pr}`, label: `Province: ${pr}`, onRemove: () => set({ provinces: state.provinces.filter((x) => x !== pr) }) });

  return (
    <div className="stack uni-explorer">
      <section className="card filter-toolbar" aria-label="Candidate filters">
        <div className="toolbar-grid candidate-toolbar">
          <form className="field toolbar-field toolbar-search" role="search" onSubmit={(e) => { e.preventDefault(); set({ search: text.trim() }); }}>
            <label className="toolbar-label" htmlFor="candidate-search">Search candidate ID</label>
            <div className="search-input">
              <Icon name="search" size={14} />
              <input id="candidate-search" type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. candidate-00000042, press Enter" />
            </div>
          </form>
          <div className="field toolbar-field toolbar-wide">
            <label className="toolbar-label" htmlFor="candidate-run">Simulation run</label>
            <select id="candidate-run" value={runId ?? ""} onChange={(e) => onRun(e.target.value === "" ? null : e.target.value)} title={run ? runLabel(run) : undefined}>
              <option value="">No run (candidates only)</option>
              {runs.map((r) => <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>)}
            </select>
          </div>
          <div className="field toolbar-field">
            <label className="toolbar-label" htmlFor="candidate-cohort">Candidate cohort</label>
            <select id="candidate-cohort" value={cohortId} disabled={runId !== null} onChange={(e) => onCohort(e.target.value)} title={runId ? "Set by the selected run" : undefined}>
              {cohorts.map((c) => <option key={c.cohort_id} value={c.cohort_id}>{c.cohort_id}</option>)}
              {!cohorts.some((c) => c.cohort_id === cohortId) ? <option value={cohortId}>{cohortId}</option> : null}
            </select>
          </div>
          <FilterMenu id="cand-score" label="Score type" options={p?.score_types ?? []} selected={state.score_types} display={scoreTypeDisplay}
            onToggle={(v) => set({ score_types: state.score_types.includes(v) ? state.score_types.filter((x) => x !== v) : [...state.score_types, v] })}
            onClear={() => set({ score_types: [] })} hint="Shown with official ÖSYM spelling; the cohort writes SOZ and DIL." />
          <div className="field toolbar-field toolbar-wide">
            <span className="toolbar-label" id="proxy-label">Achievement proxy range</span>
            <div className="range-row" role="group" aria-labelledby="proxy-label">
              <NumberInput id="proxy-min" label="Proxy from" placeholder="From 0" value={state.proxy_min} resetKey={resetNonce} onCommit={(v) => set({ proxy_min: v })} />
              <span className="muted" aria-hidden="true">–</span>
              <NumberInput id="proxy-max" label="Proxy to" placeholder="To 10,000" value={state.proxy_max} resetKey={resetNonce} onCommit={(v) => set({ proxy_max: v })} />
            </div>
          </div>
          <div className="field toolbar-field">
            <label className="toolbar-label" htmlFor="candidate-eligibility">Eligibility</label>
            <select id="candidate-eligibility" value={state.eligibility ?? ""} disabled={runId === null} title={runId ? undefined : "Select a run: eligibility is decided by the simulation"}
              onChange={(e) => set({ eligibility: (e.target.value || null) as CandidateEligibilityFilter | null })}>
              {ELIGIBILITY_OPTIONS.map(([v, l]) => <option key={l} value={v}>{l}</option>)}
            </select>
          </div>
          <div className="field toolbar-field">
            <label className="toolbar-label" htmlFor="candidate-status">Placement status</label>
            <select id="candidate-status" value={state.status ?? ""} disabled={runId === null} title={runId ? undefined : "Select a run to filter by placement"}
              onChange={(e) => set({ status: (e.target.value || null) as CandidateStatusFilter | null })}>
              {STATUS_OPTIONS.map(([v, l]) => <option key={l} value={v}>{l}</option>)}
              {state.status === "ineligible" ? <option value="ineligible">Ineligible</option> : null}
            </select>
          </div>
          {showProvince ? (
            <FilterMenu id="cand-province" label="Province" options={p!.provinces} selected={state.provinces}
              onToggle={(v) => set({ provinces: state.provinces.includes(v) ? state.provinces.filter((x) => x !== v) : [...state.provinces, v] })}
              onClear={() => set({ provinces: [] })} />
          ) : null}
          <div className="toolbar-actions">
            <button type="button" className="button" onClick={reset}><Icon name="refresh" size={13} /> Reset filters</button>
          </div>
        </div>
        <ActiveFilters items={chips} onClearAll={reset} />
        {runId === null ? <p className="field-hint" style={{ margin: 0 }}>Eligibility and placement filters need a simulation run; choose one above.</p> : null}
      </section>

      <div className="tiles tiles-4 summary-strip" aria-label="Candidate summary">
        <StatTile label="Total candidates" value={total === null ? <Missing reason="not_available" /> : fmtInt(total)} sub={manifest ? `Cohort ${manifest.cohort_id} · seed ${manifest.configuration.seed}` : undefined} />
        <StatTile label="Eligible candidates" value={eligible === null ? needRun : fmtInt(eligible)}
          sub={counts && total ? `${fmtPct(eligible! / total, 1)} of the cohort · ${fmtInt(counts.ineligible)} ineligible` : "Eligibility comes from a simulation run"} />
        <StatTile label="Placed candidates" value={counts ? fmtInt(counts.placed) : needRun}
          sub={counts && eligible ? `Placement rate ${fmtPct(counts.placed / eligible, 1)} of eligible` : "Placement comes from a simulation run"} />
        <StatTile label="Unplaced candidates" value={counts ? fmtInt(counts.unplaced) : needRun}
          sub={counts ? "Eligible but not assigned a program" : "Placement comes from a simulation run"} />
      </div>

      {selected ? <CandidateDetails cohortId={cohortId} candidateId={selected} runId={runId} catalogue={cat} onClose={() => onSelect(null)} /> : null}
      {page.error ? <ErrorState error={page.error} onRetry={page.reload} what="candidates" /> : null}
      {page.loading && !p ? <Loading what="synthetic candidates" /> : null}
      {p ? (
        <section className={page.stale ? "card table-card is-stale" : "card table-card"} aria-labelledby="cand-h">
          <div className="card-head">
            <h2 id="cand-h">Candidates <span className="count-pill">{fmtInt(p.total_matching)}</span></h2>
            <span className="row small"><DataKindBadge kind="synthetic" />{run ? <DataKindBadge kind="simulation" /> : null}<span className="muted">{run ? `Outcomes from ${run.name}` : "No run selected: outcomes pending"}</span></span>
          </div>
          {p.total_matching === 0 ? <EmptyState title="No candidates match these filters.">Reset the filters or widen the achievement proxy range.</EmptyState> : (
            <>
              <div className="table-wrap">
                <table className="candidate-table data-table explorer-table">
                  <caption>{fmtInt(p.total_matching)} matching synthetic candidates; cohort rank is derived from the achievement proxy (ties share a rank)</caption>
                  <thead>
                    <tr>
                      <SortHeader label="Candidate ID" sortKey="id" current={state.sort} direction={state.direction} onSort={onSort} className="col-id" />
                      {showProvince ? <th scope="col">Province</th> : null}
                      <th scope="col">Score type</th>
                      <SortHeader label="Achievement proxy" sortKey="proxy" current={state.sort} direction={state.direction} onSort={onSort} numeric />
                      <SortHeader label="Cohort rank" sortKey="rank" current={state.sort} direction={state.direction} onSort={onSort} numeric />
                      <SortHeader label="Preferences" sortKey="preferences" current={state.sort} direction={state.direction} onSort={onSort} numeric />
                      <th scope="col">Placement</th><th scope="col" className="col-assigned">Assigned program</th>
                      <th scope="col" className="col-actions"><span className="visually-hidden">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.items.map((r) => {
                      const a = r.assignment;
                      const prog = a?.program_code ? programNames.get(a.program_code) : undefined;
                      const isSelected = selected === r.candidate.candidate_id;
                      return (
                        <tr key={r.candidate.candidate_id} className={isSelected ? "is-selected" : undefined}>
                          <th scope="row" className="nowrap"><code>{r.candidate.candidate_id}</code></th>
                          {showProvince ? <td><Value value={r.candidate.home_location} reason="not_available" /></td> : null}
                          <td><ScoreChip value={r.candidate.score_type} /></td>
                          <td className="num"><Value value={r.candidate.achievement?.value} format={fmtInt} /></td>
                          <td className="num"><Value value={r.cohort_rank} reason="not_calculated" format={fmtInt} /></td>
                          <td className="num">{fmtInt(r.preference_count)}{r.valid_reference_count < r.preference_count ? <span className="warn-text" title="Some preferences reference unknown program codes"> ({fmtInt(r.preference_count - r.valid_reference_count)} invalid)</span> : null}</td>
                          <td><PlacementBadge status={runId ? a?.status ?? null : null} /></td>
                          <td className="cell-name">{a?.status === "placed" ? (prog ? <>
                              <span className="cell-primary">{prog.name_original}</span>
                              <span className="cell-secondary">{uniNames.get(prog.university_id)} · <SourceTerm value={prog.scholarship_original} /> · pref. {a.preference_position}</span>
                            </> : <code>{a.program_code}</code>)
                            : runId ? <Missing reason="not_applicable" /> : <Missing reason="not_calculated" />}</td>
                          <td className="col-actions">
                            <button type="button" className="button small row-action" aria-pressed={isSelected} onClick={() => onSelect(r.candidate.candidate_id)}
                              aria-label={`View details for ${r.candidate.candidate_id}`}>View details <Icon name="arrow" size={12} /></button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <Pagination offset={p.offset} limit={p.limit} total={p.total_matching} label="Candidate" onPage={(n) => onChange({ ...state, page: n })}
                pageSizes={PAGE_SIZES} onPageSize={(size) => onChange({ ...state, size, page: 0 })} />
            </>
          )}
        </section>
      ) : null}

      <div className="data-info-grid">
        {manifest ? (
          <ProvenancePanel title="Data information" origin={manifest.origin} items={[
            ...cohortProvenance(manifest),
            { label: "Simulation run", value: run ? `${runLabel(run)} (${run.run_id})` : null, missing: "not_calculated" as const },
            { label: "Scores and ranks", value: "Achievement proxy: synthetic 0–10,000, higher is better. Cohort rank is derived from it. Neither is a YKS score or rank." },
            { label: "Not in this cohort", value: showProvince ? "YKS scores and official ranks" : "Province (home location), YKS scores and official ranks: the cohort handoff records none, so no province column or filter is shown." },
          ]} />
        ) : null}
        {cohort.data && cat ? (
          <DataQualityPanel title="Cohort data quality" records={cohort.data.candidates.length} recordLabel="Candidates loaded" incomplete={incomplete}
            incompleteNote="Candidates with no preferences or invalid preference references" findings={findings} origin={cohort.data.manifest.origin}
            source={cohort.data.manifest.preference_source} version={cohort.data.manifest.generator_version} />
        ) : cohort.error ? <ErrorState error={cohort.error} onRetry={cohort.reload} what="cohort" /> : null}
      </div>
    </div>
  );
}
