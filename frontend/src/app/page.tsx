"use client";

import Link from "next/link";
import { PipelineStatus } from "@/components/dashboard/PipelineStatus";
import { PopulationSnapshot } from "@/components/dashboard/PopulationSnapshot";
import { PopulationGate, useCapabilities } from "@/components/national/common";
import { SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { ProvinceMap } from "@/components/ProvinceMap";
import { RunSnapshot } from "@/components/RunSnapshot";
import { ErrorState, Loading } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { Badge, RunStateBadge } from "@/components/StatusBadge";
import { v2, type Geography, type Overview, type ValidationReport } from "@/lib/api/v2";
import { coverageNote } from "@/lib/coverage";
import { fmtInt } from "@/lib/format";
import { useLinkPop, usePopulation, withPop } from "@/lib/population";
import { featuredRun, useRecordedRuns } from "@/lib/recordedRuns";
import { useApi } from "@/lib/useApi";

export default function DashboardPage() {
  const pop = useLinkPop();
  const { population, populationId } = usePopulation();
  const overview = useApi("v2:overview", (signal) => v2<Overview>("/overview", { signal }));
  const geo = useApi(`v2:geo:${populationId ?? "none"}`, (signal) => v2<Geography>("/geography/provinces", { query: { population_id: populationId }, signal }));
  const validation = useApi(populationId ? `v2:validation:${populationId}` : null, (signal) => v2<ValidationReport>(`/populations/${populationId}/validation`, { signal }));
  const caps = useCapabilities();
  const runs = useRecordedRuns();
  const o = overview.data;
  const latest = o?.latest_run;
  const featured = featuredRun(runs.data?.items);
  const recordedCompleted = runs.data ? runs.data.items.filter((r) => r.display_state === "completed").length : null;
  return (
    <>
      <PageHeader title="SocietyTwin Dashboard">
        Türkiye-wide synthetic society experimentation platform calibrated to official aggregate statistics.
      </PageHeader>
      <SyntheticNotice kind="population" />
      {overview.error ? <ErrorState error={overview.error} onRetry={overview.reload} what="overview" /> : null}
      {overview.loading && !o ? <Loading what="overview" /> : null}

      <div className="tiles summary-tiles" aria-label="Platform summary">
        <StatTile label="Synthetic records" value={population ? fmtInt(population.synthetic_size) : "—"} sub={population ? `Selected population · seed ${population.seed}` : "No population generated yet"} />
        <StatTile label="Residents represented" value={population ? fmtInt(population.represented_population) : "—"} sub={population ? "Sum of population weights" : "Not available"} />
        <StatTile label="Province coverage" value={o ? `${o.provinces_with_population_controls} / ${o.province_count}` : "—"}
          sub={o ? `${o.provinces_with_population_controls} of ${o.province_count} provinces loaded` : "Not available"} />
        <StatTile label="Reference year" value={population ? population.reference_year : "—"} sub={population ? "Source years may be earlier" : "Not available"} />
        <StatTile label="Saved cohorts" value={o ? fmtInt(o.saved_cohorts) : "—"} sub="National pipeline" />
        <StatTile label="Experiments" value={o ? fmtInt(o.experiments) : "—"}
          sub={runs.data ? `National pipeline · ${fmtInt(runs.data.total)} recorded historical runs` : "National pipeline"} />
      </div>

      <div className="dash-grid">
        {geo.data ? (
          <ProvinceMap provinces={geo.data.provinces} referenceYear={population?.reference_year} title="Türkiye province coverage"
            hrefFor={(code) => withPop("/population", pop, { province: code })}
            note={<p className="notice info coverage-note" role="note">{coverageNote(geo.data)} Remaining provinces appear here once their official
              tables are added to the control store (see <Link href={withPop("/data-sources", pop)}>Data sources</Link>).</p>} />
        ) : geo.error ? <ErrorState error={geo.error} onRetry={geo.reload} what="province coverage" /> : <Loading what="province coverage" />}
        <div className="dash-side">
          {featured ? (
            <RunSnapshot run={featured} href="/historical" resultsHref={`/historical/results/${encodeURIComponent(featured.experiment_id)}`} />
          ) : runs.error ? <ErrorState error={runs.error} onRetry={runs.reload} what="recorded experiments" />
            : runs.loading ? <Loading what="recorded experiments" />
            : <section className="card"><h2>Featured experiment</h2><p className="muted small" style={{ margin: 0 }}>No completed recorded experiment.</p></section>}
          <section className="card stack" aria-labelledby="latest-h">
            <div className="card-head" style={{ marginBottom: 0 }}><h2 id="latest-h">Latest national experiment</h2><Link href={withPop("/results", pop)}>All results</Link></div>
            {latest ? (
              <>
                <div className="row"><RunStateBadge state={latest.state} />{latest.backend === "stub" ? <Badge tone="fake" glyph="◇">Stub: not model output</Badge> : null}</div>
                <Link href={withPop(`/results/${latest.run_id}`, pop)}><strong>{latest.title ?? latest.run_id}</strong></Link>
                <span className="small muted">{fmtInt(latest.valid_responses)} valid of {fmtInt(latest.final_responses)} responses · {fmtInt(latest.personas)} personas · {latest.backend_label}</span>
              </>
            ) : o ? (
              <>
                <p className="muted small" style={{ margin: 0 }}>No experiment results yet.</p>
                <Link className="small" href={withPop("/experiments/new", pop)}>Design a controlled experiment</Link>
              </>
            ) : null}
          </section>
        </div>
      </div>

      <PopulationGate what="the dashboard">
        {(id) => <PopulationSnapshot populationId={id} exploreHref={withPop("/population", pop)} />}
      </PopulationGate>

      {o ? <PipelineStatus overview={o} caps={caps.data} validation={validation.data} recordedCompleted={recordedCompleted} pop={pop} /> : null}
    </>
  );
}
