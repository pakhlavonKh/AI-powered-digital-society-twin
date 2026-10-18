"use client";

import Link from "next/link";
import { PopulationMap } from "@/components/PopulationMap";
import { RunSnapshot } from "@/components/RunSnapshot";
import { BuildDetails } from "@/components/BuildDetails";
import { SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { RuntimeProbeButton } from "@/components/RuntimeProbeButton";
import { ErrorState, Loading, UnavailableState } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { Badge, OriginBadge, RunStateBadge } from "@/components/StatusBadge";
import { RUN_STATES } from "@/components/status";
import { api, unwrap } from "@/lib/api/client";
import { useBuild, useLinkBuildId } from "@/lib/build";
import { fmtInt } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";

const MODE_LABELS: Record<string, string> = {
  browse_offline: "Offline browsing (population, cohorts, history)",
  preflight: "A/B preflight (no provider calls)",
  smoke: "Fake smoke run (no provider calls)",
  persona_materialization: "Persona materialization",
  legacy_ab_live: "Live two-persona A/B run",
  cohort_execution: "Executing arbitrary cohorts",
  scenario_execution: "Executing custom scenarios",
};

export default function DashboardPage() {
  const { build, loading, error, reload, missingBuildId } = useBuild();
  const linkBuild = useLinkBuildId();
  const caps = useApi("capabilities", (signal) => unwrap(api.GET("/api/v1/capabilities", { signal })));
  const datasets = useApi("datasets", (signal) => unwrap(api.GET("/api/v1/datasets", { signal })));
  const runs = useApi("experiments", (signal) => unwrap(api.GET("/api/v1/experiments", { signal })));

  const personas = useApi(build ? `dashboard-personas:${build.build_id}` : null, (signal) => unwrap(api.GET("/api/v1/personas/{build_id}", { params: { path: { build_id: build!.build_id } }, signal })));
  const completed = runs.data?.items.filter((r) => r.display_state === "completed") ?? [];
  const featured = completed.at(-1);
  const personaCount = personas.data ? new Set(personas.data.items.map((p) => p.record_id)).size : null;

  const counts = new Map<string, number>();
  for (const item of runs.data?.items ?? []) counts.set(item.display_state, (counts.get(item.display_state) ?? 0) + 1);
  const processed = datasets.data?.fixture_evidence.filter((e) => e.kind === "processed_reference") ?? [];

  return (
    <>
      <PageHeader title="Historical Ankara experiment">
        The original proof of concept, kept unchanged for reproducibility: a 1,000-resident synthetic Ankara population, two fixture
        personas and the recorded MatrAIx survey runs (including run3). The national pipeline is on the main dashboard.
      </PageHeader>
      <SyntheticNotice kind="population" />

      {loading && !build ? <Loading what="builds" /> : null}
      {error ? <ErrorState error={error} onRetry={reload} what="builds" /> : null}
      {missingBuildId ? <UnavailableState title={`Build ${missingBuildId} is not registered.`}>Choose a registered build above; no other build was substituted.</UnavailableState> : null}
      {build ? <>
        <div className="dashboard-hero">
          <PopulationMap province={build.scope.province} year={build.scope.reference_year} count={build.row_count} href={withBuild("/historical/population",linkBuild)}/>
          <div className="dashboard-stats">
            <StatTile label="Synthetic residents in this build" value={fmtInt(build.row_count)} sub="Residents in the current dataset"/>
            <StatTile label="Geography" value={build.scope.province} sub={`${build.scope.reference_year} · 1 province with loaded data`}/>
            <StatTile label="Stored personas" value={fmtInt(personaCount)} sub="Residents with a persona YAML"/>
            <StatTile label="Completed experiments" value={runs.data ? completed.length : "—"} sub="Recorded completed comparisons"/>
          </div>
        </div>
        {featured ? <RunSnapshot id={featured.experiment_id} name={featured.name} build={linkBuild}/> : null}
        <BuildDetails build={build}/>
      </> : null}

      <div className="grid-2">
        <section className="card" aria-labelledby="sources-h">
          <div className="card-head"><h2 id="sources-h">Sources and generator</h2><Link href={withBuild("/historical/data-sources", linkBuild)}>Data sources</Link></div>
          {datasets.loading && !datasets.data ? <Loading what="data sources" /> : null}
          {datasets.error ? <ErrorState error={datasets.error} onRetry={datasets.reload} /> : null}
          {datasets.data ? (
            <ul className="stack" style={{ paddingLeft: 18, margin: 0 }}>
              <li>
                <strong>{processed.filter((p) => p.present).length} processed reference tables registered</strong> with current SHA-256 hashes.{" "}
                <Badge tone="warn" glyph="!">Raw-source verification unavailable</Badge>
                <div className="small muted">The original TÜİK downloads are not in this checkout; source attribution is as recorded by the project.</div>
              </li>
              <li>
                <strong>Root data manifest: {datasets.data.manifest.status}</strong> ({datasets.data.manifest.datasets.length} entries).
                <div className="small muted">{datasets.data.manifest.note}</div>
              </li>
              <li>
                <strong>Generator:</strong> {build?.generator.configured_seed !== null && build ? "source present; seed read statically" : "no seed evidence"}.
                <div className="small muted">Fixed-size random sampling from the processed tables. No new population is generated by this workbench.</div>
              </li>
            </ul>
          ) : null}
        </section>

        <section className="card" aria-labelledby="runtime-h">
          <div className="card-head"><h2 id="runtime-h">What can run here</h2></div>
          {caps.loading && !caps.data ? <Loading what="capabilities" /> : null}
          {caps.error ? <ErrorState error={caps.error} onRetry={caps.reload} /> : null}
          {caps.data && caps.data.runtime.files_ready ? (
            <div className="stack" style={{ marginBottom: 12 }}>
              <p className="small">MatrAIx runtime files found. Import probe: <strong>{caps.data.runtime.probe.status.replace("_", " ")}</strong>
                {caps.data.runtime.probe.checked_at ? ` (${caps.data.runtime.probe.checked_at})` : ""}.</p>
              <RuntimeProbeButton onDone={caps.reload} />
            </div>
          ) : null}
          {caps.data ? (
            <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {Object.entries(MODE_LABELS).map(([key, label]) => {
                const mode = caps.data!.modes[key as keyof typeof caps.data.modes];
                return (
                  <li key={key}>
                    <div className="row">
                      {mode.available ? <Badge tone="good" glyph="✓">Available</Badge> : <Badge tone="neutral" glyph="·">Unavailable</Badge>}
                      <span>{label}</span>
                    </div>
                    {!mode.available && mode.reasons[0] ? <div className="small muted">{mode.reasons[0]}</div> : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </section>
      </div>

      <section className="card" aria-labelledby="runs-h">
        <div className="card-head"><h2 id="runs-h">Recorded runs</h2><Link href={withBuild("/historical/results", linkBuild)}>All results</Link></div>
        {runs.loading && !runs.data ? <Loading what="recorded runs" /> : null}
        {runs.error ? <ErrorState error={runs.error} onRetry={runs.reload} /> : null}
        {runs.data && runs.data.items.length === 0 ? <p className="muted">No imported or managed runs were found.</p> : null}
        {runs.data && runs.data.items.length > 0 ? (
          <div className="stack">
            <div className="row" aria-label="Runs by state">
              {[...counts.entries()].map(([state, n]) => (
                <span key={state} className="row" style={{ gap: 4 }}><RunStateBadge state={state} /><span className="small">× {n}</span></span>
              ))}
            </div>
            <p className="small muted">States are derived from the files present in each run folder. {RUN_STATES.outcome_unknown.description}</p>
            <div className="table-wrap">
              <table>
                <caption>Recent results (imported folders and managed experiments)</caption>
                <thead><tr><th scope="col">Run</th><th scope="col">Origin</th><th scope="col">State</th><th scope="col">Model</th><th scope="col" className="num">Trials</th><th scope="col" className="num">Differing values</th></tr></thead>
                <tbody>
                  {runs.data.items.slice(0, 10).map((r) => (
                    <tr key={r.experiment_id}>
                      <th scope="row"><Link href={withBuild(`/historical/results/${encodeURIComponent(r.experiment_id)}`, linkBuild)}>{r.name}</Link></th>
                      <td><OriginBadge origin={r.origin} evidenceKind={r.evidence_kind} /></td>
                      <td><RunStateBadge state={r.display_state} /></td>
                      <td><code>{r.model ?? "–"}</code></td>
                      <td className="num">{r.trial_count}</td>
                      <td className="num">{r.differing_values ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </section>

      <section className="card" aria-labelledby="scope-h">
        <div className="card-head"><h2 id="scope-h">Geographic scope</h2></div>
        <p className="small muted">The map shows province outlines, with the loaded province highlighted. All other provinces have no loaded data. Geometry is from geoBoundaries / OpenStreetMap (2021), distinct from the population reference year.</p>
        <div className="table-wrap">
          <table>
            <caption>Provinces with loaded data</caption>
            <thead><tr><th scope="col">Province</th><th scope="col">Loaded data</th></tr></thead>
            <tbody>
              {build ? (
                <tr><th scope="row">{build.scope.province}</th><td>{fmtInt(build.row_count)} synthetic residents, reference year {build.scope.reference_year}</td></tr>
              ) : null}
              <tr><th scope="row">Any other province</th><td>No loaded data</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
