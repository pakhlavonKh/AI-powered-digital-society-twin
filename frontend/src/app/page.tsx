"use client";

import Link from "next/link";
import { PopulationGate, useCapabilities } from "@/components/national/common";
import { SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { ProvinceMap } from "@/components/ProvinceMap";
import { ErrorState, Loading } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { Badge, RunStateBadge } from "@/components/StatusBadge";
import { v2, type Geography, type Overview } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { useLinkPop, usePopulation, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

export default function DashboardPage() {
  const pop = useLinkPop();
  const { population, populationId } = usePopulation();
  const overview = useApi("v2:overview", (signal) => v2<Overview>("/overview", { signal }));
  const geo = useApi(`v2:geo:${populationId ?? "none"}`, (signal) => v2<Geography>("/geography/provinces", { query: { population_id: populationId }, signal }));
  const caps = useCapabilities();
  const o = overview.data;
  const latest = o?.latest_run;
  return (
    <>
      <PageHeader title="Dashboard">
        Türkiye-wide synthetic population calibrated to official aggregate statistics, and controlled persona-conditioned AI experiments.
      </PageHeader>
      <SyntheticNotice kind="population" />
      {overview.error ? <ErrorState error={overview.error} onRetry={overview.reload} what="overview" /> : null}
      {overview.loading && !o ? <Loading what="overview" /> : null}
      <div className="dash-grid">
        {geo.data ? (
          <ProvinceMap provinces={geo.data.provinces} hrefFor={(code) => withPop("/population", pop, { province: code })} />
        ) : geo.error ? <ErrorState error={geo.error} onRetry={geo.reload} what="province coverage" /> : <Loading what="province coverage" />}
        <div className="dash-side">
          <div className="tiles tight">
            <StatTile label="Synthetic records" value={population ? fmtInt(population.synthetic_size) : "—"} sub={population ? `seed ${population.seed}` : "No population yet"} />
            <StatTile label="Residents represented" value={population ? fmtInt(population.represented_population) : "—"} sub="Sum of population weights" />
            <StatTile label="Provinces with source data" value={o ? `${o.provinces_with_population_controls} / ${o.province_count}` : "—"} sub="Population controls loaded" />
            <StatTile label="Reference year" value={population ? population.reference_year : "—"} sub="Source years may be earlier" />
            <StatTile label="Saved cohorts" value={o ? fmtInt(o.saved_cohorts) : "—"} />
            <StatTile label="Experiments" value={o ? fmtInt(o.experiments) : "—"} sub={o ? `${fmtInt(o.personas_used_in_completed_runs)} personas in completed runs` : undefined} />
          </div>
          <section className="card stack" aria-labelledby="latest-h">
            <div className="card-head"><h2 id="latest-h">Latest run</h2><Link href={withPop("/results", pop)}>All results</Link></div>
            {latest ? (
              <>
                <div className="row"><RunStateBadge state={latest.state} />{latest.backend === "stub" ? <Badge tone="fake" glyph="◇">Stub: not model output</Badge> : null}</div>
                <Link href={withPop(`/results/${latest.run_id}`, pop)}><strong>{latest.title ?? latest.run_id}</strong></Link>
                <span className="small muted">{fmtInt(latest.valid_responses)} valid of {fmtInt(latest.final_responses)} responses · {fmtInt(latest.personas)} personas · {latest.backend_label}</span>
              </>
            ) : <p className="muted small" style={{ margin: 0 }}>No experiment results yet.</p>}
          </section>
          {caps.data ? (
            <section className="card stack" aria-labelledby="exec-h">
              <h2 id="exec-h">Execution backends</h2>
              {(["stub", "matraix_fake", "matraix_live"] as const).map((k) => (
                <div key={k} className="small">
                  <Badge tone={caps.data!.backends[k].available ? "good" : "neutral"} glyph={caps.data!.backends[k].available ? "✓" : "·"}>
                    {k === "stub" ? "Stub (offline)" : k === "matraix_fake" ? "MatrAIx fake transport" : "MatrAIx live provider"}</Badge>{" "}
                  <span className="muted">{caps.data!.backends[k].available ? "" : caps.data!.backends[k].reasons[0]}</span>
                </div>
              ))}
              <Link className="small" href={withPop("/settings", pop)}>Settings and readiness</Link>
            </section>
          ) : null}
        </div>
      </div>
      <PopulationGate what="the dashboard">
        {(id) => (
          <section className="card" aria-labelledby="scope-h">
            <div className="card-head"><h2 id="scope-h">Selected population</h2><Link href={withPop("/population", pop)}>Explore</Link></div>
            {population ? (
              <dl className="kv">
                <dt>Population ID</dt><dd><code>{id}</code></dd>
                <dt>Scope</dt><dd>{population.scope.label}</dd>
                <dt>Generator</dt><dd>{population.generator_version} · generated {population.generated_at}</dd>
                <dt>Weights</dt><dd>mean {population.weights.mean.toFixed(1)} residents per record · Kish design effect {population.weights.kish_design_effect.toFixed(3)}</dd>
                <dt>What this is</dt><dd>{population.label} Province context (environment) is kept separately from person attributes.</dd>
              </dl>
            ) : null}
          </section>
        )}
      </PopulationGate>
    </>
  );
}
