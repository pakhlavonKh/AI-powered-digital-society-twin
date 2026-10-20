"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { DistributionChart, PopulationPyramid } from "@/components/national/charts";
import { GenerateForm, PopulationGate, useCapabilities, useLabels } from "@/components/national/common";
import { FilterPanel } from "@/components/national/FilterPanel";
import { SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { v2, type Environment, type Filters, type Geography, type RecordsPage, type Summary } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { describeFilters, filtersFromParams, filtersToParams, filtersToQuery } from "@/lib/nationalFilters";
import { useLinkPop, usePopulation, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

const FIELD_TITLES: Record<string, string> = {
  sex: "Sex (administrative)", marital_status: "Marital status", education_level: "Education", labour_status: "Labour status",
  household_size_class: "Household size", household_type: "Household type", urbanicity: "Settlement type", age_group: "Age group",
};

function Explorer({ populationId }: { populationId: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const pop = useLinkPop();
  const caps = useCapabilities();
  const labels = useLabels();
  const filters = filtersFromParams(params);
  const [page, setPage] = useState(0);
  const key = filtersToParams(filters).toString();
  const geo = useApi(`v2:geo:${populationId}`, (signal) => v2<Geography>("/geography/provinces", { query: { population_id: populationId }, signal }));
  const summary = useApi(`v2:summary:${populationId}:${key}`, (signal) => v2<Summary>(`/populations/${populationId}/summary`, { query: filtersToQuery(filters), signal }));
  const records = useApi(`v2:records:${populationId}:${key}:${page}`, (signal) => v2<RecordsPage>(`/populations/${populationId}/records`,
    { query: { ...filtersToQuery(filters), limit: 25, offset: page * 25 }, signal }));
  const province = filters.province_codes?.length === 1 ? filters.province_codes[0] : null;
  const env = useApi(province ? `v2:env:${province}` : null, (signal) => v2<Environment>(`/environments/${province}`, { signal }));
  const setFilters = (f: Filters) => { setPage(0); router.replace(`${pathname}?${filtersToParams(f, params).toString()}`); };
  const provinceName = (code: string) => geo.data?.provinces.find((p) => p.province_code === code)?.province_name ?? code;
  const s = summary.data;
  const available = new Set((s?.distributions ?? []).filter((d) => d.available).map((d) => d.field));
  const cohortHref = withPop("/cohorts", pop, { prefill: JSON.stringify(filters) });
  return (
    <div className="explorer2">
      <FilterPanel filters={filters} onChange={setFilters} provinces={geo.data?.provinces ?? []} caps={caps.data} available={s ? available : undefined} />
      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <span className="small muted">Selection: {describeFilters(filters, provinceName)}</span>
          <Link className="button primary small" href={cohortHref}>Create cohort from this selection</Link>
        </div>
        {summary.error ? <ErrorState error={summary.error} onRetry={summary.reload} what="summary" /> : null}
        {summary.loading && !s ? <Loading what="distributions" /> : null}
        {s ? (
          <div className={summary.stale ? "stack is-stale" : "stack"}>
            <div className="tiles">
              <StatTile label="Synthetic records" value={fmtInt(s.records)} sub={`of ${fmtInt(s.total_records)} in this population`} />
              <StatTile label="Residents represented" value={fmtInt(s.represented_population)} sub="Weighted (population_weight)" />
              <StatTile label="Provinces" value={s.provinces.length} sub={s.provinces.map((p) => p.province_name).slice(0, 4).join(", ") || "none"} />
              <StatTile label="Population reference year" value={s.reference_year} sub="Source years listed below" />
            </div>
            {s.records === 0 ? <p className="notice warn">No synthetic records match these filters.</p> : (
              <div className="charts2">
                <div className="wide"><PopulationPyramid rows={s.pyramid} /></div>
                {s.distributions.filter((d) => d.field !== "age_group").map((d) => (
                  <DistributionChart key={d.field} dist={d} title={FIELD_TITLES[d.field] ?? d.field} label={(c) => labels(d.field, c)} />
                ))}
              </div>
            )}
            <section className="card" aria-labelledby="years-h">
              <div className="card-head"><h2 id="years-h">Source years and coverage</h2><Link href={withPop("/data-sources", pop)}>Data sources</Link></div>
              <div className="table-wrap"><table><caption>Population reference year {s.reference_year}; each field keeps its own source year</caption>
                <thead><tr><th>Province</th><th>Records</th><th>Represented</th><th>Field source years</th></tr></thead>
                <tbody>{s.source_years.map((y) => {
                  const p = s.provinces.find((q) => q.province_code === y.province_code);
                  return <tr key={y.province_code}><th>{y.province_name}</th><td className="num">{fmtInt(p?.records)}</td><td className="num">{fmtInt(p?.weighted)}</td>
                    <td>{Object.entries(y.source_years).filter(([f]) => !["province_code", "sex"].includes(f)).map(([f, yr]) => `${f.replace("_", " ")} ${yr}`).join(" · ")}</td></tr>;
                })}</tbody></table></div>
              <p className="small muted">{s.weighting} Fields not listed have no source table for that province and stay unavailable.</p>
            </section>
          </div>
        ) : null}
        {province && env.data ? (
          <section className="card stack" aria-labelledby="env-h">
            <div className="card-head"><h2 id="env-h">{env.data.province.province_name} environment</h2><span className="small muted">Province context, not person attributes</span></div>
            {env.data.empty ? <p className="muted small">No context indicators are loaded for this province.</p> : (
              <>
                <p className="small muted" style={{ margin: 0 }}>{fmtInt(env.data.indicator_count)} indicators: the latest observation whose reference period ends by {env.data.reference_year}, with its own period as published. Nothing is interpolated; projections are listed separately.</p>
                {Object.entries(env.data.domains).map(([domain, rows]) => (
                  <details key={domain}>
                    <summary>{domain} <span className="small muted">({rows.length})</span></summary>
                    <div className="table-wrap"><table><caption>{domain}: value at or before reference year {env.data!.reference_year}</caption>
                      <thead><tr><th>Indicator</th><th className="num">Value</th><th>Period</th><th>Status</th><th>Note</th></tr></thead>
                      <tbody>{rows.map((r) => (
                        <tr key={r.indicator_id}><th>{r.label}{r.label_tr ? <div className="small muted">{r.label_tr}</div> : null}</th>
                          <td className="num">{r.value === null ? "–" : `${r.value.toLocaleString("en-GB", { maximumFractionDigits: 1 })} ${r.unit}`}</td>
                          <td>{r.source_period ?? r.source_year ?? "–"}{r.multi_year_period ? <div className="small muted">multi-year period</div> : null}</td>
                          <td className="status-pill">{r.value_status}</td><td className="small muted">{r.note ?? ""}</td></tr>))}</tbody></table></div>
                  </details>
                ))}
                {env.data.projections?.length ? (
                  <details>
                    <summary>Official projections <span className="small muted">({env.data.projections.length}; not observations)</span></summary>
                    <div className="table-wrap"><table><caption>Projections are never used as current values, including years up to the reference year</caption>
                      <thead><tr><th>Indicator</th><th>Periods</th></tr></thead>
                      <tbody>{env.data.projections.map((r) => (
                        <tr key={r.indicator_id}><th>{r.label}</th><td className="small">{r.points.map((pt) => `${pt.period}${pt.observation_type === "projection_baseline" ? " (baseline)" : ""}: ${pt.value === null ? "–" : pt.value.toLocaleString("en-GB", { maximumFractionDigits: 1 })}`).join(" · ")} {r.unit}</td></tr>))}</tbody></table></div>
                  </details>
                ) : null}
              </>
            )}
            {env.data.structurally_unavailable_datasets.length ? <p className="small muted">Not covered for this province (structurally unavailable, not zero): {env.data.structurally_unavailable_datasets.map((d) => `${d.title ?? d.source_id} (${d.coverage})`).join(", ")}.</p> : null}
          </section>
        ) : null}
        <section className="card" aria-labelledby="rec-h">
          <div className="card-head"><h2 id="rec-h">Records</h2><span className="small muted">Server-side pages of 25; never the whole population</span></div>
          {records.error ? <ErrorState error={records.error} onRetry={records.reload} /> : null}
          {records.data ? (
            <>
              <div className="table-wrap"><table><caption>{fmtInt(records.data.total_matching)} matching synthetic records</caption>
                <thead><tr><th>Synthetic ID</th><th>Province</th><th>Age group</th><th>Sex</th><th>Marital status</th><th>Education</th><th className="num">Weight</th></tr></thead>
                <tbody>{records.data.items.map((r) => (
                  <tr key={r.synthetic_id}><th><Link href={withPop(`/personas/${r.synthetic_id}`, pop)}><code>{r.synthetic_id}</code></Link></th>
                    <td>{r.province_name}</td><td>{r.age_group}</td><td>{labels("sex", r.sex)}</td><td>{labels("marital_status", r.marital_status as string)}</td>
                    <td>{labels("education_level", r.education_level as string | null)}</td><td className="num">{r.population_weight.toFixed(1)}</td></tr>))}</tbody></table></div>
              <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
                <button type="button" className="button small" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</button>
                <span className="small muted">Page {page + 1} of {Math.max(1, Math.ceil(records.data.total_matching / 25))}</span>
                <button type="button" className="button small" disabled={(page + 1) * 25 >= records.data.total_matching} onClick={() => setPage((p) => p + 1)}>Next</button>
              </div>
            </>
          ) : records.loading ? <Loading what="records" /> : null}
        </section>
      </div>
    </div>
  );
}

export default function PopulationPage() {
  const { reload, select } = usePopulation();
  const [showGen, setShowGen] = useState(false);
  return (
    <>
      <PageHeader title="Population Explorer" actions={<button type="button" className="button small" onClick={() => setShowGen((v) => !v)}>{showGen ? "Close" : "Generate another population"}</button>}>
        Weighted distributions of the selected synthetic population, for all of Türkiye or one province. Synthetic population — no real individual records.
      </PageHeader>
      <SyntheticNotice kind="population" />
      {showGen ? <section className="card stack"><h2>Generate a population</h2><GenerateForm onDone={(id) => { reload(); select(id); setShowGen(false); }} /></section> : null}
      <PopulationGate what="the Population Explorer">{(id) => <Explorer populationId={id} />}</PopulationGate>
    </>
  );
}
