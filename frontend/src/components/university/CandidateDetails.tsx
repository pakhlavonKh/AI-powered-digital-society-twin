"use client";

import { useEffect, useRef } from "react";
import { OUTCOME_LABELS, preferenceViews, type PreferenceView } from "@/lib/university/candidates";
import { useUniversitySource } from "@/lib/university/context";
import type { Assignment, CandidateDetail, CohortManifest, RegistryCatalogue } from "@/lib/university/types";
import { fmtInt } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { CopyId } from "../CopyId";
import { ErrorState, Loading } from "../States";
import { KeyValues } from "../StatTile";
import { Badge } from "../StatusBadge";
import { DataKindBadge, Missing, ProvenancePanel, ScoreChip, SourceTerm, Value, ValidationList } from "./common";
import { PlacementBadge } from "./RunPicker";

/**
 * Ordered preference table. Order is the handoff's `position` (never re-sorted); outcomes are shown only when the
 * selected run supplied them, and the eligibility column is the structural and score-type check, not a decision.
 */
export function CandidatePreferenceList({ views, runSelected }: { views: PreferenceView[]; runSelected: boolean }) {
  if (views.length === 0) return <p className="small muted">This candidate has no preferences in the handoff. That does not mean the candidate has no real preferences.</p>;
  return (
    <div className="table-wrap">
      <table className="data-table pref-table" aria-label="Ranked preferences">
        <thead>
          <tr>
            <th scope="col" className="num">Rank</th><th scope="col">University</th><th scope="col">Program</th><th scope="col">Scholarship</th>
            <th scope="col">Score type</th><th scope="col">Eligibility</th><th scope="col">Placement outcome</th>
          </tr>
        </thead>
        <tbody>
          {views.map((v) => {
            const outcome = v.outcome ? OUTCOME_LABELS[v.outcome] : null;
            return (
              <tr key={v.position} className={v.outcome === "assigned" ? "is-assigned" : undefined} aria-label={`Preference ${v.position}: ${v.program ?? "unknown program"}`}>
                <th scope="row" className="num"><span className="pref-pos">{v.position}</span></th>
                <td>{v.university ?? <span className="missing">No such program in the registry snapshot</span>}</td>
                <td className="cell-name">
                  <span className="cell-primary">{v.program ?? <span className="missing">Unknown program</span>}</span>
                  <span className="cell-secondary"><code>{v.program_code}</code></span>
                </td>
                <td>{v.reference_valid ? <SourceTerm value={v.scholarship} /> : <Missing reason="not_applicable" />}</td>
                <td>{v.reference_valid ? <ScoreChip value={v.program_score_type} /> : <Missing reason="not_applicable" />}</td>
                <td>
                  {!v.reference_valid ? <Badge tone="crit" glyph="×">Invalid reference</Badge>
                    : v.outcome === "ineligible_score_type" ? <Badge tone="neutral" glyph="≠">Not eligible (score type)</Badge>
                    : v.score_type_matches ? <Badge tone="neutral" glyph="=" title="Program score type matches the candidate's (SÖZ = SOZ, DİL = DIL). Eligibility itself is decided by the simulation.">Score type matches</Badge>
                    : <Badge tone="neutral" glyph="≠" title="Program score type differs from the candidate's. Eligibility itself is decided by the simulation.">Score type differs</Badge>}
                </td>
                <td>
                  {outcome ? <Badge tone={outcome.tone}>{outcome.label}</Badge>
                    : <span className="missing small">{runSelected ? "No outcome supplied by the run" : "Select a run for outcomes"}</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function cohortProvenance(m: CohortManifest) {
  return [
    { label: "Cohort ID", value: m.cohort_id, mono: true },
    { label: "Generator version", value: m.generator_version, mono: true },
    { label: "Random stream", value: m.stream_version, mono: true },
    { label: "Seed / size", value: `${m.configuration.seed} / ${fmtInt(m.configuration.size)}` },
    { label: "Registry snapshot for preferences", value: m.registry_snapshot, mono: true, missing: "not_available" as const },
    { label: "Preference source", value: m.preference_source },
    { label: "Applicant evidence", value: m.data_versions.applicant_data, missing: "not_available" as const },
  ];
}

export function CandidateDetails({ cohortId, candidateId, runId, catalogue, onClose }: {
  cohortId: string; candidateId: string; runId: string | null; catalogue: RegistryCatalogue | undefined; onClose: () => void;
}) {
  const source = useUniversitySource();
  const detail = useApi(`uni:${source.id}:candidate:${cohortId}:${candidateId}:${runId ?? "none"}`, (signal) => source.getCandidate(cohortId, candidateId, runId, signal));
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, [candidateId, detail.data]);
  return (
    <section className="card stack detail-panel" aria-labelledby="candidate-detail-h">
      <div className="card-head">
        <h2 id="candidate-detail-h" tabIndex={-1} ref={heading}>Synthetic candidate {candidateId}</h2>
        <button type="button" className="button small" onClick={onClose}>Close details</button>
      </div>
      {detail.error ? <ErrorState error={detail.error} onRetry={detail.reload} what="candidate" /> : null}
      {detail.loading && !detail.data ? <Loading what="candidate" /> : null}
      {detail.data && catalogue ? <Body d={detail.data} catalogue={catalogue} runSelected={runId !== null} /> : null}
    </section>
  );
}

function eligibilityText(a: Assignment | null, runSelected: boolean) {
  if (!runSelected) return <span className="missing" title="Eligibility is decided by a simulation run.">Select a run</span>;
  if (!a) return <Missing reason="not_available" />;
  return a.status === "ineligible" ? <Badge tone="neutral" glyph="–">Ineligible</Badge> : <Badge tone="good" glyph="✓">Eligible</Badge>;
}

function PlacementOutcome({ a, catalogue, runSelected }: { a: Assignment | null; catalogue: RegistryCatalogue; runSelected: boolean }) {
  if (!runSelected) return <p className="small muted" style={{ margin: 0 }}>Select a simulation run to see this candidate&apos;s placement outcome.</p>;
  if (!a) return <p className="small muted" style={{ margin: 0 }}>The selected run has no record for this candidate.</p>;
  const p = a.program_code ? catalogue.programs.find((x) => x.program_code === a.program_code) : undefined;
  const u = p ? catalogue.universities.find((x) => x.university_id === p.university_id) : undefined;
  return (
    <KeyValues items={[
      ["Placement status", <PlacementBadge key="s" status={a.status} />],
      ["Assigned university", a.status === "placed" ? (u ? u.name_original : <Missing key="u" reason="not_available" />) : <Missing key="u" reason="not_applicable" />],
      ["Assigned program", a.status === "placed"
        ? (p ? <span key="p">{p.name_original} · <SourceTerm value={p.scholarship_original} /> <span className="muted small">(<code>{p.program_code}</code>)</span></span> : <code key="p">{a.program_code}</code>)
        : <Missing key="p" reason="not_applicable" />],
      ["Successful preference rank", a.status === "placed" && a.preference_position ? `Preference ${a.preference_position}` : <Missing key="r" reason="not_applicable" />],
      ["Explanation", a.reason ? <span key="e" className="small">{a.reason}</span>
        : <span key="e" className="missing small">{a.status === "placed" ? "The simulation supplied no explanation beyond the assigned preference." : "The simulation gave no reason."}</span>],
    ]} />
  );
}

function Body({ d, catalogue, runSelected }: { d: CandidateDetail; catalogue: RegistryCatalogue; runSelected: boolean }) {
  const c = d.row.candidate;
  const a = d.row.assignment;
  const views = preferenceViews(d, catalogue, a);
  return (
    <>
      <div className="row small"><DataKindBadge kind="synthetic" />{runSelected ? <DataKindBadge kind="simulation" /> : null}<span>ID <CopyId value={c.candidate_id} label="candidate ID" /></span></div>
      <div className="detail-sections">
        <section className="detail-section" aria-labelledby="cand-overview-h">
          <h3 id="cand-overview-h">Candidate overview</h3>
          <KeyValues items={[
            ["Candidate ID", <code key="id">{c.candidate_id}</code>],
            ["Province", <Value key="pr" value={c.home_location} reason="not_available" />],
            ["Age", fmtInt(c.age)],
            ["Educational interests", <Value key="i" value={c.educational_interests?.join(", ") ?? null} reason="not_available" />],
            ["Annual budget (TRY)", <Value key="b" value={c.annual_budget_try} reason="not_available" format={fmtInt} />],
            ["Eligibility status", <span key="el">{eligibilityText(a, runSelected)}</span>],
          ]} />
        </section>
        <section className="detail-section" aria-labelledby="cand-performance-h">
          <h3 id="cand-performance-h">Admission performance</h3>
          <KeyValues items={[
            ["Score type", <ScoreChip key="s" value={c.score_type} />],
            ["Achievement proxy", c.achievement ? <span key="a">{fmtInt(c.achievement.value)} <span className="muted small">({c.achievement.scale})</span></span> : <Missing key="a" reason="missing_from_source" />],
            ["Cohort rank (derived)", d.row.cohort_rank === null ? <Missing key="r" reason="not_calculated" /> : <span key="r">{fmtInt(d.row.cohort_rank)} of {fmtInt(d.manifest.configuration.size)} <span className="muted small">by achievement proxy; not a YKS rank</span></span>],
            ["YKS score / official rank", <Missing key="y" reason="not_in_schema" />],
          ]} />
        </section>
        <section className="detail-section" aria-labelledby="cand-placement-h">
          <h3 id="cand-placement-h">Placement outcome</h3>
          <PlacementOutcome a={a} catalogue={catalogue} runSelected={runSelected} />
        </section>
      </div>
      <section className="stack" aria-labelledby="pref-h">
        <h3 id="pref-h">University preferences ({views.length}) <span className="muted small">in the candidate&apos;s original order</span></h3>
        <CandidatePreferenceList views={views} runSelected={runSelected} />
      </section>
      <ValidationList findings={d.findings} title="Candidate validation" empty="No structural problems in this candidate's preferences." />
      {/* The cohort's provenance is also on the page (Data information); here it stays one click away. */}
      <details>
        <summary>Cohort provenance and generator assumptions</summary>
        <div className="details-body">
          <ProvenancePanel title="Cohort provenance" origin={d.manifest.origin} items={cohortProvenance(d.manifest)}>
            <KeyValues items={Object.entries(d.manifest.assumptions).map(([k, v]) => [k, v])} />
          </ProvenancePanel>
          <p className="small muted" style={{ margin: 0 }}>Not in the candidate contract: eligibility constraints, scholarship preferences and institution preferences (only through the ranked program list).</p>
        </div>
      </details>
    </>
  );
}
