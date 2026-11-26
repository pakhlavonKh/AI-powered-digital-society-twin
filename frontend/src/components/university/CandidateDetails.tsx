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
import { DataKindBadge, Missing, ProvenancePanel, SourceTerm, Value, ValidationList } from "./common";
import { PlacementBadge } from "./RunPicker";

/** Ordered preference list. Order is the handoff's `position`; outcomes are shown only when the run supplied them. */
export function CandidatePreferenceList({ views, runSelected }: { views: PreferenceView[]; runSelected: boolean }) {
  if (views.length === 0) return <p className="small muted">This candidate has no preferences in the handoff. That does not mean the candidate has no real preferences.</p>;
  return (
    <ol className="pref-list" aria-label="Ranked preferences">
      {views.map((v) => {
        const outcome = v.outcome ? OUTCOME_LABELS[v.outcome] : null;
        return (
          <li key={v.position} className={`pref-item${v.outcome === "assigned" ? " is-assigned" : ""}`} aria-label={`Preference ${v.position}: ${v.program ?? "unknown program"}`}>
            <span className="pref-pos" aria-hidden="true">{v.position}</span>
            <div className="pref-main">
              <strong>{v.program ?? <span className="missing">Unknown program</span>} <span className="muted small">· {v.scholarship ? <SourceTerm value={v.scholarship} /> : "scholarship missing"}</span></strong>
              <span>{v.university ?? <span className="missing">No such program in the registry snapshot</span>}</span>
              <span className="muted">Code <code>{v.program_code}</code> · Program score type: {v.reference_valid ? <Value value={v.program_score_type} /> : <Missing reason="not_applicable" />}</span>
            </div>
            <div className="pref-tags">
              {!v.reference_valid ? <Badge tone="crit" glyph="×">Invalid reference</Badge>
                : v.score_type_matches ? <Badge tone="neutral" glyph="=" title="Program score type matches the candidate's after folding (SÖZ = SOZ, DİL = DIL). Eligibility itself is decided by the simulation.">Score type matches</Badge>
                  : <Badge tone="neutral" glyph="≠" title="Program score type differs from the candidate's. Eligibility itself is decided by the simulation.">Score type differs</Badge>}
              {outcome ? <Badge tone={outcome.tone}>{outcome.label}</Badge>
                : <span className="missing small">{runSelected ? "No outcome supplied by the run" : "Select a run for outcomes"}</span>}
            </div>
          </li>
        );
      })}
    </ol>
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
    <section className="card stack" aria-labelledby="candidate-detail-h">
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

function placementText(a: Assignment | null, catalogue: RegistryCatalogue) {
  if (!a) return <PlacementBadge status={null} />;
  if (a.status !== "placed") return <><PlacementBadge status={a.status} /> {a.reason ? <span className="small">{a.reason}</span> : <span className="missing small">The simulation gave no reason.</span>}</>;
  const p = catalogue.programs.find((x) => x.program_code === a.program_code);
  const u = p ? catalogue.universities.find((x) => x.university_id === p.university_id) : undefined;
  return <><PlacementBadge status="placed" /> {p ? <>{p.name_original} · <SourceTerm value={p.scholarship_original} /> · {u?.name_original ?? ""}</> : <code>{a.program_code}</code>} {a.preference_position ? <span className="muted small">(preference {a.preference_position})</span> : null}</>;
}

function Body({ d, catalogue, runSelected }: { d: CandidateDetail; catalogue: RegistryCatalogue; runSelected: boolean }) {
  const c = d.row.candidate;
  const views = preferenceViews(d, catalogue, d.row.assignment);
  return (
    <>
      <div className="row small"><DataKindBadge kind="synthetic" /><span>ID <CopyId value={c.candidate_id} label="candidate ID" /></span></div>
      <div className="grid-2">
        <div className="stack">
          <h3>Candidate attributes</h3>
          <KeyValues items={[
            ["Age", fmtInt(c.age)],
            ["Score type", <Value key="s" value={c.score_type} />],
            ["Achievement proxy", c.achievement ? <span key="a">{fmtInt(c.achievement.value)} <span className="muted small">({c.achievement.scale})</span></span> : <Missing key="a" reason="missing_from_source" />],
            ["Cohort rank (derived)", d.row.cohort_rank === null ? <Missing key="r" reason="not_calculated" /> : <span key="r">{fmtInt(d.row.cohort_rank)} of {fmtInt(d.manifest.configuration.size)} <span className="muted small">by achievement proxy; not a YKS rank</span></span>],
            ["YKS score / official rank", <Missing key="y" reason="not_in_schema" />],
            ["Home location", <Value key="h" value={c.home_location} reason="not_available" />],
            ["Educational interests", <Value key="i" value={c.educational_interests?.join(", ") ?? null} reason="not_available" />],
            ["Annual budget (TRY)", <Value key="b" value={c.annual_budget_try} reason="not_available" format={fmtInt} />],
            ["Eligibility constraints", <Missing key="e" reason="not_in_schema" />],
            ["Scholarship preferences", <Missing key="sp" reason="not_in_schema" />],
            ["Institution preferences", <span key="ip" className="small">Only through the ranked program list below</span>],
            ["Simulated placement", <span key="pl">{placementText(d.row.assignment, catalogue)}</span>],
          ]} />
        </div>
        <ProvenancePanel title="Cohort provenance" origin={d.manifest.origin} items={cohortProvenance(d.manifest)}>
          <details>
            <summary>Generator assumptions ({Object.keys(d.manifest.assumptions).length})</summary>
            <div className="details-body"><KeyValues items={Object.entries(d.manifest.assumptions).map(([k, v]) => [k, v])} /></div>
          </details>
        </ProvenancePanel>
      </div>
      <section className="stack" aria-labelledby="pref-h">
        <h3 id="pref-h">Ranked preferences ({views.length})</h3>
        <CandidatePreferenceList views={views} runSelected={runSelected} />
      </section>
      <ValidationList findings={d.findings} title="Candidate validation" empty="No structural problems in this candidate's preferences." />
    </>
  );
}
