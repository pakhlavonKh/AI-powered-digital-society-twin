"use client";

import Link from "next/link";
import { BuildDetails } from "@/components/BuildDetails";
import { ArtifactTable } from "@/components/historical/ArtifactTable";
import { ComparisonTable } from "@/components/historical/ComparisonTable";
import { LocationCard } from "@/components/historical/LocationCard";
import { matchedArtifact, PersonaPair } from "@/components/historical/PersonaPair";
import { Icon } from "@/components/Icon";
import { Notice, SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { RuntimeProbeButton } from "@/components/RuntimeProbeButton";
import { EmptyState, ErrorState, Loading, UnavailableState } from "@/components/States";
import { KeyValues, StatTile } from "@/components/StatTile";
import { Badge, CheckBadge, OriginBadge, RunStateBadge } from "@/components/StatusBadge";
import { RUN_STATES, statusInfo } from "@/components/status";
import { UsageTable } from "@/components/UsageTable";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useBuild, useLinkBuildId } from "@/lib/build";
import { fmtInt, fmtUsd } from "@/lib/format";
import { featuredRun, NOT_RECORDED, RUN_KIND_LABELS, runContext, useRecordedRun, useRecordedRuns } from "@/lib/recordedRuns";
import { useApi } from "@/lib/useApi";
import { apiPath, withBuild } from "@/lib/urls";

const MODE_LABELS: Record<string, string> = {
  browse_offline: "Offline browsing (population, cohorts, history)",
  preflight: "A/B preflight (no provider calls)",
  smoke: "Fake smoke run (no provider calls)",
  persona_materialization: "Persona materialization",
  legacy_ab_live: "Live two-persona A/B run",
  cohort_execution: "Executing arbitrary cohorts",
  scenario_execution: "Executing custom scenarios",
};

const ARCHIVE_PAGES: [string, string][] = [
  ["/historical/population", "Population"], ["/historical/cohorts", "Cohorts"], ["/historical/personas", "Personas"],
  ["/historical/experiments/new", "Experiment drafts"], ["/historical/results", "All recorded results"],
  ["/historical/validation", "Validation"], ["/historical/data-sources", "Data sources"],
];

/** MatrAIx example tasks live under application/tasks/example-*; the project README lists the run3 task as one of them. */
const EXAMPLE_TASK = /(^|\/)tasks\/example-/;

function orRecorded(value: React.ReactNode | null | undefined): React.ReactNode {
  return value === null || value === undefined || value === "" ? <span className="muted">{NOT_RECORDED}</span> : value;
}

export default function HistoricalPage() {
  const { build, loading, error, reload, missingBuildId } = useBuild();
  const linkBuild = useLinkBuildId();
  const caps = useApi("capabilities", (signal) => unwrap(api.GET("/api/v1/capabilities", { signal })));
  const datasets = useApi("datasets", (signal) => unwrap(api.GET("/api/v1/datasets", { signal })));
  const runs = useRecordedRuns();
  const featured = featuredRun(runs.data?.items);
  const { results, trials } = useRecordedRun(featured?.experiment_id);
  const r = results.data;
  const trialList = trials.data?.trials ?? [];
  const ctx = runContext(trialList);
  const personaIds = trialList.map((t) => t.persona_id).filter((id): id is string => Boolean(id));
  const views = useApi(build && personaIds.length ? `v1:persona-views:${build.build_id}:${personaIds.join(",")}` : null, async (signal) => {
    const out = await Promise.all(personaIds.map((id) => api.GET("/api/v1/personas/{build_id}/{record_id}", { params: { path: { build_id: build!.build_id, record_id: id } }, signal })
      .then((res) => res.data ?? null, () => null)));
    return new Map<string, Schemas["PersonaView"] | null>(personaIds.map((id, i) => [id, out[i]]));
  });
  // The selected build is the run's source population only if every trial's snapshot is a stored persona of this build whose row still matches.
  const verified = trialList.length > 0 && views.data !== undefined && trialList.every((t) => {
    const art = matchedArtifact(t, t.persona_id ? views.data!.get(t.persona_id) : null);
    return Boolean(art?.source_row_check?.passed);
  });
  const saved = r?.trial_summaries.filter((t) => t.answers !== null).length ?? 0;
  const counts = new Map<string, number>();
  for (const item of runs.data?.items ?? []) counts.set(item.display_state, (counts.get(item.display_state) ?? 0) + 1);
  const processed = datasets.data?.fixture_evidence.filter((e) => e.kind === "processed_reference") ?? [];
  const exportBase = featured ? apiPath(`/experiments/${encodeURIComponent(featured.experiment_id)}/export`) : "";
  const resultsHref = featured ? withBuild(`/historical/results/${encodeURIComponent(featured.experiment_id)}`, linkBuild) : "";
  const boundaryModes = [...new Set(trialList.map((t) => t.boundary_mode).filter(Boolean))].join(", ");
  const unassigned = [...new Set(trialList.flatMap((t) => t.persona_snapshot?.unassigned_fields ?? []))];
  const model = r?.model ?? featured?.model ?? null;
  const runTitle = featured ? `Historical ${ctx.location ? `${ctx.location} ` : ""}${featured.name}` : "";

  return (
    <>
      <PageHeader title="Historical Ankara Experiment" actions={<Badge tone="neutral" glyph="⧉">Historical / Recorded</Badge>}>
        Original SocietyTwin proof of concept preserved for reproducibility. Everything below is read from the saved run folder and the
        historical build; nothing is re-run or regenerated in this session.
      </PageHeader>
      <SyntheticNotice kind="population" />
      <SyntheticNotice kind="responses" />

      {loading && !build ? <Loading what="builds" /> : null}
      {error ? <ErrorState error={error} onRetry={reload} what="builds" /> : null}
      {missingBuildId ? <UnavailableState title={`Build ${missingBuildId} is not registered.`}>Choose a registered build above; no other build was substituted.</UnavailableState> : null}
      {runs.error ? <ErrorState error={runs.error} onRetry={runs.reload} what="recorded runs" /> : null}
      {runs.loading && !runs.data ? <Loading what="recorded runs" /> : null}
      {runs.data && !featured ? <EmptyState title="No completed recorded run.">The archive has no completed comparison to feature; every recorded run is listed below.</EmptyState> : null}

      {featured ? (
        <nav className="reference-tabs" aria-label="Experiment sections">
          <a href="#summary-h">Summary</a><a href="#pair-h">Personas</a><a href="#answers-h">Recorded answers</a><a href="#meta-h">Run metadata</a>
          <a href="#limits-h">Limitations</a><a href="#prov-h">Provenance</a><a href="#runs-h">All recorded runs</a>
        </nav>
      ) : null}

      <div className="historical-top">
        {featured ? (
          <section className="card run-hero" aria-labelledby="summary-h">
            <div className="stack">
              <span className="eyebrow"><Icon name="archive" size={15} /> Recorded experiment</span>
              <h2 id="summary-h" style={{ margin: 0 }}>{runTitle}</h2>
              <div className="row">
                <RunStateBadge state={featured.display_state} />
                <Badge tone="neutral" glyph="⧉">Historical / Recorded</Badge>
                {featured.evidence_kind === "live" ? <Badge tone="info" glyph="◆">Live provider output (recorded)</Badge> : null}
                {featured.evidence_kind === "fake" ? <Badge tone="fake" glyph="◇">Fake transport: not model behaviour</Badge> : null}
              </div>
              <p className="small muted" style={{ margin: 0 }}>{r?.display_state_reason ?? featured.display_state_reason} No live model call was made to show this page.</p>
              {results.error ? <ErrorState error={results.error} onRetry={results.reload} what="recorded results" /> : null}
              <dl className="facts facts-wide">
                <div><dt>Status</dt><dd>{statusInfo(RUN_STATES, featured.display_state).label} / Recorded</dd></div>
                <div><dt>Location</dt><dd>{orRecorded(ctx.location)}</dd></div>
                <div><dt>Model</dt><dd>{orRecorded(model ? <code>{model}</code> : null)}</dd></div>
                <div><dt>Experiment type</dt><dd>{RUN_KIND_LABELS[featured.kind] ?? featured.kind}{ctx.instrument?.title ? ` · ${ctx.instrument.title}` : ""}</dd></div>
                <div><dt>Reference year</dt><dd>{orRecorded(ctx.referenceYear)}</dd></div>
                <div><dt>Temperature</dt><dd>{orRecorded(r?.temperature != null ? String(r.temperature) : null)}</dd></div>
              </dl>
              <div className="row">
                <Link className="button primary small" href={resultsHref}>Full run evidence <Icon name="arrow" size={13} /></Link>
                <a className="button small" href={`${exportBase}?format=json`} download>Export JSON</a>
                <a className="button small" href={`${exportBase}?format=csv`} download>Export CSV</a>
              </div>
            </div>
            <div className="run-hero-stats">
              <StatTile label="Synthetic population" value={build ? fmtInt(build.row_count) : "—"}
                sub={build ? (verified ? `Residents in the ${build.variant} build; both persona rows verified` : `Residents in the selected ${build.variant} build`) : "No build"} />
              <StatTile label="Personas executed" value={r ? `${saved}` : "—"} sub={r ? `of ${r.trial_summaries.length} with saved answers` : undefined} />
              <StatTile label="Answers that differed" value={r && r.comparison_rows.length ? `${fmtInt(r.differing_values_recomputed)} / ${r.comparison_rows.length}` : "—"}
                sub="Recomputed from the saved trial results" />
            </div>
          </section>
        ) : null}
        {build ? <LocationCard build={build} exploreHref={withBuild("/historical/population", linkBuild)} /> : null}
      </div>

      {r && trials.data ? <PersonaPair result={r} trials={trialList} views={views.data} linkBuild={linkBuild} /> : null}
      {featured && trials.error ? <ErrorState error={trials.error} onRetry={trials.reload} what="recorded trials" /> : null}

      {r && r.comparison_rows.length ? (
        <section className="card stack" aria-labelledby="answers-h">
          <div className="card-head" style={{ marginBottom: 0 }}>
            <h2 id="answers-h">Recorded answers</h2>
            <span className="small">{r.differing_values_recomputed} of {r.comparison_rows.length} recorded values differ
              {r.differing_values_recorded !== null ? ` (comparison file: ${r.differing_values_recorded})` : ""}</span>
          </div>
          <ComparisonTable result={r} />
          <p className="small muted" style={{ margin: 0 }}>Answers and labels exactly as saved in the run folder; nothing was regenerated.</p>
        </section>
      ) : null}

      {r && featured ? (
        <div className="grid-2">
          <section className="card stack" aria-labelledby="meta-h">
            <h2 id="meta-h" style={{ margin: 0 }}>Run metadata and reproducibility</h2>
            <KeyValues items={[
              ["Run ID", <span key="id"><code>{r.experiment_id}</code> · folder <code>{r.dirname}</code></span>],
              ["Origin", <OriginBadge key="o" origin={r.origin} />],
              ["Model", orRecorded(r.model ? <code>{r.model}</code> : null)],
              ["Provider", orRecorded(r.provider)],
              ["Temperature", orRecorded(r.temperature != null ? String(r.temperature) : null)],
              ["Task", orRecorded(r.task ? <code>{r.task}</code> : null)],
              ["Survey instrument", orRecorded(ctx.instrument ? `${ctx.instrument.title ?? ""}${ctx.instrument.id ? ` (${ctx.instrument.id})` : ""}` : null)],
              ["Persona IDs", trialList.length ? trialList.map((t) => `${t.label}: ${t.persona_id ?? "unknown"}`).join(" · ") : orRecorded(null)],
              ["Calls", `${r.planned_calls ?? "?"} planned · ${r.recorded_calls ?? "?"} recorded · ${r.automatic_retries ?? "?"} automatic retries`],
              ["Token usage (run total)", orRecorded(r.usage && r.usage.n_input_tokens != null ? `${fmtInt(r.usage.n_input_tokens)} input · ${fmtInt(r.usage.n_output_tokens)} output` : null)],
              ["Estimated cost", orRecorded(r.usage?.cost_usd != null ? `${fmtUsd(r.usage.cost_usd)} (${r.usage.cost_source ?? "source unknown"}; provider-billed cost not recorded)` : null)],
              ["Runtime", orRecorded(r.runtime_seconds != null ? `${r.runtime_seconds.toFixed(2)} s` : null)],
              ["Timestamps", orRecorded(featured.created_at)],
              ["Source population", build ? <span key="sp"><code>{build.source_path}</code> · {fmtInt(build.row_count)} rows · {verified ? "both persona snapshots match stored personas of this build" : "link to this run not verified"}</span> : orRecorded(null)],
              ["Population seed", orRecorded(build?.generator.configured_seed != null ? `${build.generator.configured_seed} (${build.generator.seed_evidence})` : null)],
              ["MatrAIx runtime", `Model boundary ${boundaryModes || "unknown"} · trial statuses ${Object.entries(r.raw_statuses.trial_boundaries).map(([k, v]) => `${k} ${v ?? "none"}`).join(", ")} · ${trialList.reduce((n, t) => n + t.events_summary.count, 0)} runtime events`],
              ["Artifacts", `${r.artifacts.length} files in the run folder`],
            ]} />
          </section>
          <section className="card stack" aria-labelledby="usage-h">
            <h2 id="usage-h" style={{ margin: 0 }}>Usage and cost</h2>
            <UsageTable caption="Null values are unknown, not zero" rows={[
              ...r.trial_summaries.map((t) => ({ label: `Trial ${t.label}`, usage: t.usage })),
              ...(r.usage ? [{ label: "Run total (comparison file)", usage: r.usage }] : []),
            ]} />
            <p className="small muted" style={{ margin: 0 }}>Costs marked estimated come from a local price table in the external framework. No provider-billed amount is recorded.</p>
            {r.budget_file ? <p className="small muted" style={{ margin: 0 }}>Budget file: spent {fmtUsd(r.budget_file.spent_usd)}, cap {r.budget_file.max_cost_usd === null ? "none" : fmtUsd(r.budget_file.max_cost_usd)}. {r.budget_file.note}</p> : null}
          </section>
        </div>
      ) : null}

      {r ? (
        <section className="card stack limitations" aria-labelledby="limits-h">
          <h2 id="limits-h" style={{ margin: 0 }}>Research limitations</h2>
          <Notice tone="warn" title="How to read this run.">{r.inference_note}</Notice>
          <div className="grid-2">
            <div>
              <h3>Recorded with the run</h3>
              <ul className="limit-list">{r.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            </div>
            <div>
              <h3>From the persona snapshots and task</h3>
              <ul className="limit-list">
                <li>This is a recorded proof of concept, not population-level behavioural validation.</li>
                {unassigned.length ? <li>Persona dimensions not assigned in the saved snapshots: {unassigned.join(", ")}.</li> : null}
                {r.task && EXAMPLE_TASK.test(r.task) ? <li>The survey is MatrAIx&apos;s example task (<code>{r.task}</code>), not an instrument designed for Türkiye.</li> : null}
                {[...new Set(trialList.flatMap((t) => matchedArtifact(t, t.persona_id ? views.data?.get(t.persona_id) : null)?.mapping_warnings ?? []))].map((w) => <li key={w}>{w}</li>)}
              </ul>
            </div>
          </div>
          {r.warnings.length ? <Notice tone="warn" title="Evidence warnings:"><ul>{r.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Notice> : null}
        </section>
      ) : null}

      <section className="card stack" aria-labelledby="prov-h">
        <h2 id="prov-h" style={{ margin: 0 }}>Provenance and artifacts</h2>
        {r ? (
          <>
            <h3 style={{ margin: 0 }}>Consistency checks</h3>
            {r.consistency_checks.length === 0 ? <p className="muted small">No cross-file checks apply to this evidence.</p> : (
              <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {r.consistency_checks.map((c) => <li key={c.name} className="row"><CheckBadge passed={c.passed} /><code>{c.name}</code><span className="small">{c.detail}</span></li>)}
              </ul>
            )}
            <details>
              <summary>Artifacts ({r.artifacts.length} files)</summary>
              <div className="details-body"><ArtifactTable artifacts={r.artifacts} /></div>
            </details>
          </>
        ) : null}
        {build ? <BuildDetails build={build} /> : null}
        <details>
          <summary>Sources and generator</summary>
          <div className="details-body">
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
            <Link className="small" href={withBuild("/historical/data-sources", linkBuild)}>Historical data sources</Link>
          </div>
        </details>
      </section>

      <section className="card" aria-labelledby="runs-h">
        <div className="card-head"><h2 id="runs-h">All recorded runs</h2><Link href={withBuild("/historical/results", linkBuild)}>All results</Link></div>
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
                  {runs.data.items.slice(0, 10).map((run) => (
                    <tr key={run.experiment_id}>
                      <th scope="row"><Link href={withBuild(`/historical/results/${encodeURIComponent(run.experiment_id)}`, linkBuild)}>{run.name}</Link>
                        {run.experiment_id === featured?.experiment_id ? <> <Badge tone="info" glyph="★">Featured</Badge></> : null}</th>
                      <td><OriginBadge origin={run.origin} evidenceKind={run.evidence_kind} /></td>
                      <td><RunStateBadge state={run.display_state} /></td>
                      <td><code>{run.model ?? "–"}</code></td>
                      <td className="num">{run.trial_count}</td>
                      <td className="num">{run.differing_values ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </section>

      <section className="card stack" aria-labelledby="archive-h">
        <h2 id="archive-h" style={{ margin: 0 }}>Historical workbench</h2>
        <nav className="row small" aria-label="Historical workbench pages">
          {ARCHIVE_PAGES.map(([href, label]) => <Link key={href} className="chip" href={withBuild(href, linkBuild)}>{label}</Link>)}
        </nav>
        <details>
          <summary>What can run here</summary>
          <div className="details-body">
            {caps.loading && !caps.data ? <Loading what="capabilities" /> : null}
            {caps.error ? <ErrorState error={caps.error} onRetry={caps.reload} /> : null}
            {caps.data && caps.data.runtime.files_ready ? (
              <div className="stack">
                <p className="small" style={{ margin: 0 }}>MatrAIx runtime files found. Import probe: <strong>{caps.data.runtime.probe.status.replace("_", " ")}</strong>
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
          </div>
        </details>
      </section>
    </>
  );
}
