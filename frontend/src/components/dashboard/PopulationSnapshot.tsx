"use client";

import Link from "next/link";
import { v2, type Category, type Distribution, type Summary } from "@/lib/api/v2";
import { fmtInt, fmtPct } from "@/lib/format";
import { FILTER_FIELDS } from "@/lib/nationalFilters";
import { usePopulation } from "@/lib/population";
import { useApi } from "@/lib/useApi";
import { PopulationPyramid } from "../national/charts";
import { Icon } from "../Icon";
import { ErrorState, Loading } from "../States";

const OUTSIDE = new Set(["not_applicable", "unavailable"]);
const SEX_COLOR: Record<string, string> = { male: "var(--series-1)", female: "var(--series-2)" };
const MAX_EXTRA_FIELDS = 3;

function fieldTitle(field: string): string {
  return FILTER_FIELDS.find((f) => f.field === field)?.label ?? field.replace(/_/g, " ");
}

/** Categories once each (the API can repeat a structural category), in API order. */
function uniqueCategories(dist: Distribution): Category[] {
  const seen = new Set<string>();
  return dist.categories.filter((c) => !seen.has(c.value) && Boolean(seen.add(c.value)));
}

/** One 100% bar split by sex, in the pyramid's colours; the shares are printed beside it. */
function SexSplit({ dist }: { dist: Distribution }) {
  const cats = uniqueCategories(dist).filter((c) => !OUTSIDE.has(c.value) && (c.weighted_share ?? 0) > 0);
  const text = cats.map((c) => `${c.label} ${fmtPct(c.weighted_share)}`).join(", ");
  return (
    <figure className="chart-figure mini-figure">
      <figcaption><span><span className="chart-title">Sex</span><span className="muted small"> · weighted share of residents</span></span></figcaption>
      <div className="split-bar" role="img" aria-label={`Sex: ${text}.`}>
        {cats.map((c) => <span key={c.value} style={{ flexGrow: c.weighted_share ?? 0, background: SEX_COLOR[c.value] ?? "var(--axis)" }}
          title={`${c.label}: ${fmtPct(c.weighted_share)} weighted · ${fmtInt(c.records)} records`} />)}
      </div>
      <div className="legend">{cats.map((c) => <span key={c.value}><i className="legend-key" style={{ background: SEX_COLOR[c.value] ?? "var(--axis)" }} />{c.label} {fmtPct(c.weighted_share)}</span>)}</div>
    </figure>
  );
}

/** Compact horizontal share bars on a fixed 0–100% scale; structural categories are reported in text, not drawn. */
function MiniShares({ dist }: { dist: Distribution }) {
  const title = fieldTitle(dist.field);
  const cats = uniqueCategories(dist);
  const shown = cats.filter((c) => !OUTSIDE.has(c.value));
  const outside = cats.filter((c) => OUTSIDE.has(c.value) && c.records > 0);
  return (
    <figure className="chart-figure mini-figure">
      <figcaption><span><span className="chart-title">{title}</span><span className="muted small"> · weighted share of residents</span></span></figcaption>
      <div className="mini-shares" role="table" aria-label={`${title}, weighted share of residents`}>
        {shown.map((c) => (
          <div className="mini-share" role="row" key={c.value} title={`${c.label}: ${fmtPct(c.weighted_share)} weighted · ${fmtInt(c.records)} records`}>
            <span role="rowheader">{c.label}</span>
            <span className="track" aria-hidden="true"><span className="fill" style={{ width: `${(c.weighted_share ?? 0) * 100}%` }} /></span>
            <span role="cell" className="num">{fmtPct(c.weighted_share)}</span>
          </div>
        ))}
      </div>
      {outside.length ? <p className="small muted" style={{ margin: 0 }}>{outside.map((c) => `${c.label}: ${fmtPct(c.weighted_share)}`).join(" · ")} (outside the source table&apos;s universe).</p> : null}
    </figure>
  );
}

/** Dashboard preview of the selected population; the Population Explorer holds the full analysis. */
export function PopulationSnapshot({ populationId, exploreHref }: { populationId: string; exploreHref: string }) {
  const { population } = usePopulation();
  const summary = useApi(`v2:summary:${populationId}:`, (signal) => v2<Summary>(`/populations/${populationId}/summary`, { signal }));
  const s = summary.data;
  const sex = s?.distributions.find((d) => d.field === "sex" && d.available);
  const extra = (s?.distributions ?? []).filter((d) => d.available && d.field !== "sex" && d.field !== "age_group").slice(0, MAX_EXTRA_FIELDS);
  const missing = (s?.distributions ?? []).filter((d) => !d.available);
  return (
    <section className="card stack" aria-labelledby="snapshot-h">
      <div className="card-head" style={{ marginBottom: 0 }}>
        <h2 id="snapshot-h">Population snapshot</h2>
        <Link className="button small" href={exploreHref}>Explore population <Icon name="arrow" size={13} /></Link>
      </div>
      {summary.error ? <ErrorState error={summary.error} onRetry={summary.reload} what="population summary" /> : null}
      {summary.loading && !s ? <Loading what="population summary" /> : null}
      {s ? (
        <>
          <p className="small muted" style={{ margin: 0 }}>{s.scope.label} · {fmtInt(s.records)} synthetic records representing {fmtInt(s.represented_population)} residents
            · reference year {s.reference_year}. Weighted by population_weight.</p>
          <div className="snapshot-grid">
            <div className="snapshot-cell"><PopulationPyramid rows={s.pyramid} height={270} /></div>
            <div className="snapshot-cell stack">
              {sex ? <SexSplit dist={sex} /> : null}
              {extra.map((d) => <MiniShares key={d.field} dist={d} />)}
              {missing.length ? (
                <p className="small muted" style={{ margin: 0 }}>Not loaded for this population: {missing.map((d) => fieldTitle(d.field)).join(", ")}.
                  These fields fill in when their official tables are added.</p>
              ) : null}
            </div>
          </div>
        </>
      ) : null}
      {population ? (
        <details>
          <summary>Population provenance</summary>
          <div className="details-body">
            <dl className="kv">
              <dt>Population ID</dt><dd><code>{population.population_id}</code></dd>
              <dt>Scope</dt><dd>{population.scope.label}</dd>
              <dt>Generator</dt><dd>{population.generator_version} · generated {population.generated_at} · seed {population.seed}</dd>
              <dt>Weights</dt><dd>mean {population.weights.mean.toFixed(1)} residents per record · Kish design effect {population.weights.kish_design_effect.toFixed(3)}</dd>
              <dt>What this is</dt><dd>{population.label} Province context (environment) is kept separately from person attributes.</dd>
            </dl>
          </div>
        </details>
      ) : null}
    </section>
  );
}
