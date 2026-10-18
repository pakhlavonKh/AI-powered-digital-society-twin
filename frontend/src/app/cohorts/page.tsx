"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { PopulationGate, useCapabilities } from "@/components/national/common";
import { FilterPanel } from "@/components/national/FilterPanel";
import { SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { Badge } from "@/components/StatusBadge";
import { toApiError, type ApiError } from "@/lib/api/client";
import { v2, type Cohort, type CohortPreview, type Filters, type Geography, type Sample } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { describeFilters } from "@/lib/nationalFilters";
import { useLinkPop, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

function SampleForm({ cohort, onDone }: { cohort: Cohort; onDone: () => void }) {
  const pop = useLinkPop();
  const [size, setSize] = useState(Math.min(20, cohort.eligible_records ?? 20));
  const [method, setMethod] = useState<"weighted" | "simple_random" | "stratified">("weighted");
  const [seed, setSeed] = useState(7);
  const [strata, setStrata] = useState("province_code");
  const [error, setError] = useState<ApiError | null>(null);
  const [sample, setSample] = useState<Sample | null>(null);
  return (
    <form className="stack" onSubmit={async (e) => {
      e.preventDefault(); setError(null);
      try {
        const s = await v2<Sample>(`/cohorts/${cohort.cohort_id}/samples`, { body: { size, method, seed, strata_field: method === "stratified" ? strata : null } });
        setSample(s); onDone();
      } catch (err) { setError(toApiError(err)); }
    }}>
      <div className="form-grid">
        <div className="field"><label htmlFor={`sz-${cohort.cohort_id}`}>Sample size</label>
          <input id={`sz-${cohort.cohort_id}`} type="number" min={1} max={10000} value={size} onChange={(e) => setSize(Number(e.target.value))} /></div>
        <div className="field"><label htmlFor={`m-${cohort.cohort_id}`}>Sampling method</label>
          <select id={`m-${cohort.cohort_id}`} value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>
            <option value="weighted">Weighted (probability ∝ population weight)</option>
            <option value="simple_random">Simple random (equal probability)</option>
            <option value="stratified">Stratified (proportional allocation)</option>
          </select></div>
        {method === "stratified" ? <div className="field"><label htmlFor={`st-${cohort.cohort_id}`}>Strata</label>
          <select id={`st-${cohort.cohort_id}`} value={strata} onChange={(e) => setStrata(e.target.value)}>
            {["province_code", "sex", "age_group", "marital_status", "education_level"].map((f) => <option key={f} value={f}>{f}</option>)}</select></div> : null}
        <div className="field"><label htmlFor={`sd-${cohort.cohort_id}`}>Seed</label>
          <input id={`sd-${cohort.cohort_id}`} type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></div>
      </div>
      <div><button className="button small" type="submit">Draw sample</button></div>
      {error ? <ErrorState error={error} /> : null}
      {sample ? <p className="small">Sample <code>{sample.sample_id}</code>: {fmtInt(sample.selected)} of {fmtInt(sample.eligible_records)} eligible records ·{" "}
        <Link href={withPop("/personas", pop, { sample: sample.sample_id })}>View personas</Link></p> : null}
    </form>
  );
}

function CohortCard({ cohort, provinceName, reload }: { cohort: Cohort; provinceName: (c: string) => string; reload: () => void }) {
  const pop = useLinkPop();
  return (
    <article className="card stack" aria-labelledby={`c-${cohort.cohort_id}`}>
      <div className="card-head"><h3 id={`c-${cohort.cohort_id}`}>{cohort.name}</h3>
        <Badge tone={cohort.status === "valid" ? "good" : "warn"} glyph={cohort.status === "valid" ? "✓" : "!"}>{cohort.status === "valid" ? "Valid" : cohort.status_detail}</Badge></div>
      <dl className="kv">
        <dt>Filters</dt><dd>{describeFilters(cohort.filters, provinceName)}</dd>
        <dt>Eligible records</dt><dd>{fmtInt(cohort.eligible_records)}</dd>
        <dt>Represented population</dt><dd>{fmtInt(cohort.eligible_weighted_population)}</dd>
        <dt>Minors</dt><dd>{cohort.minors ? <Badge tone="warn" glyph="!">{fmtInt(cohort.minors)} under 18 — not usable for adult tasks</Badge> : "None"}</dd>
        <dt>Cohort ID</dt><dd><code>{cohort.cohort_id}</code> · population <code>{cohort.population_id}</code></dd>
      </dl>
      {cohort.samples.length ? (
        <div className="table-wrap"><table><caption>Saved samples (members stored separately from the definition)</caption>
          <thead><tr><th>Sample</th><th>Method</th><th className="num">Size</th><th className="num">Seed</th><th>Personas</th></tr></thead>
          <tbody>{cohort.samples.map((s) => <tr key={s.sample_id}><th><code>{s.sample_id}</code></th><td>{s.config.method}</td><td className="num">{s.selected}</td>
            <td className="num">{s.config.seed}</td><td><Link href={withPop("/personas", pop, { sample: s.sample_id })}>View</Link></td></tr>)}</tbody></table></div>
      ) : <p className="small muted">No sample drawn yet.</p>}
      <details><summary>Draw a seeded sample</summary><div className="details-body"><SampleForm cohort={cohort} onDone={reload} /></div></details>
      <div className="row"><Link className="button small" href={withPop("/experiments/new", pop, { cohort: cohort.cohort_id })}>Use in a new experiment</Link></div>
    </article>
  );
}

function Cohorts({ populationId }: { populationId: string }) {
  const params = useSearchParams();
  const caps = useCapabilities();
  const prefill = (() => { try { return JSON.parse(params.get("prefill") ?? "{}") as Filters; } catch { return {}; } })();
  const [filters, setFilters] = useState<Filters>(prefill);
  const [name, setName] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const geo = useApi(`v2:geo:${populationId}`, (signal) => v2<Geography>("/geography/provinces", { query: { population_id: populationId }, signal }));
  const list = useApi("v2:cohorts", (signal) => v2<{ items: Cohort[] }>("/cohorts", { signal }));
  const fkey = JSON.stringify(filters);
  const preview = useApi(`v2:preview:${populationId}:${fkey}`, (signal) => v2<CohortPreview>("/cohorts/preview", { body: { population_id: populationId, filters }, signal }));
  const provinceName = (code: string) => geo.data?.provinces.find((p) => p.province_code === code)?.province_name ?? code;
  return (
    <div className="explorer2">
      <FilterPanel title="Cohort filters" filters={filters} onChange={setFilters} provinces={geo.data?.provinces ?? []} caps={caps.data} />
      <div className="stack">
        <section className="card stack" aria-labelledby="new-h">
          <h2 id="new-h">New cohort</h2>
          <p className="small muted">{describeFilters(filters, provinceName)}</p>
          {preview.error ? <ErrorState error={preview.error} /> : null}
          {preview.data ? (
            <div className="tiles">
              <div className="tile"><div className="tile-label">Eligible synthetic records</div><div className="tile-value">{fmtInt(preview.data.eligible_records)}</div></div>
              <div className="tile"><div className="tile-label">Represented population</div><div className="tile-value">{fmtInt(preview.data.eligible_weighted_population)}</div></div>
              <div className="tile"><div className="tile-label">Minors in selection</div><div className="tile-value">{fmtInt(preview.data.minors)}</div>
                <div className="tile-sub">{preview.data.minors ? "Add “Adults only” for adult experiments" : "Adults only"}</div></div>
            </div>
          ) : <Loading what="preview" />}
          <form className="row" onSubmit={async (e) => {
            e.preventDefault(); setError(null);
            try { await v2("/cohorts", { body: { name: name || "Untitled cohort", population_id: populationId, filters } }); setName(""); list.reload(); }
            catch (err) { setError(toApiError(err)); }
          }}>
            <div className="field" style={{ flex: 1 }}><label htmlFor="cohort-name">Cohort name</label>
              <input id="cohort-name" type="text" value={name} placeholder="e.g. Ankara adults" onChange={(e) => setName(e.target.value)} /></div>
            <button type="submit" className="button primary" style={{ alignSelf: "end" }} disabled={!preview.data?.eligible_records}>Save cohort</button>
          </form>
          {error ? <ErrorState error={error} /> : null}
        </section>
        <section aria-labelledby="saved-h" className="stack">
          <h2 id="saved-h">Saved cohorts</h2>
          {list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : null}
          {list.data && list.data.items.length === 0 ? <EmptyState title="No cohorts yet.">Define filters and save a cohort.</EmptyState> : null}
          {list.data?.items.map((c) => <CohortCard key={c.cohort_id} cohort={c} provinceName={provinceName} reload={list.reload} />)}
        </section>
      </div>
    </div>
  );
}

export default function CohortsPage() {
  return (
    <>
      <PageHeader title="Cohorts">Reusable, filtered selections of synthetic records. Definitions are stored separately from seeded samples drawn from them.</PageHeader>
      <SyntheticNotice kind="population" />
      <PopulationGate what="cohorts">{(id) => <Cohorts populationId={id} />}</PopulationGate>
    </>
  );
}
