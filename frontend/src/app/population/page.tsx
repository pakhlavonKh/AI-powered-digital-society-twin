"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { BuildDetails } from "@/components/BuildDetails";
import { BarChartCard } from "@/components/charts/BarChartCard";
import { FilterControls } from "@/components/FilterControls";
import { SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState, Loading, UnavailableState } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useBuild } from "@/lib/build";
import { filterCount, filtersFromParams, filtersToParams, filtersToQuery, type Filters } from "@/lib/filters";
import { FIELD_LABELS, fmtInt, fmtPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";

const PAGE_SIZES = [25, 50, 100];
type SortField = "person_id" | "age_group" | "gender" | "marital_status";

function categoriesOf(summary: Schemas["Summary"] | undefined) {
  const of = (field: string) => summary?.distributions.find((d) => d.field === field)?.categories.map((c) => c.value) ?? [];
  return { age_group: of("age_group"), gender: of("gender"), marital_status: of("marital_status") };
}

export default function PopulationPage() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { build, missingBuildId, error: buildError, reload: reloadBuilds } = useBuild();
  const filters = filtersFromParams(params);
  const sort = (params.get("sort") as SortField) || "person_id";
  const direction = params.get("dir") === "desc" ? "desc" : "asc";
  const size = PAGE_SIZES.includes(Number(params.get("size"))) ? Number(params.get("size")) : 50;
  const page = Math.max(0, Number(params.get("page") ?? 0) || 0);
  const translations = params.get("tr") === "1";
  const buildId = build?.availability.status === "available" ? build.build_id : null;
  const query = filtersToQuery(filters);
  const fkey = JSON.stringify(query);

  const summary = useApi(buildId ? `summary:${buildId}:${fkey}` : null, (signal) =>
    unwrap(api.GET("/api/v1/builds/{build_id}/summary", { params: { path: { build_id: buildId! }, query: { ...query, crosstab: true } }, signal })));
  const allCats = useApi(buildId ? `cats:${buildId}` : null, (signal) =>
    unwrap(api.GET("/api/v1/builds/{build_id}/summary", { params: { path: { build_id: buildId! } }, signal })));
  const datasets = useApi("datasets", (signal) => unwrap(api.GET("/api/v1/datasets", { signal })));
  const records = useApi(buildId ? `records:${buildId}:${fkey}:${sort}:${direction}:${page}:${size}` : null, (signal) =>
    unwrap(api.GET("/api/v1/builds/{build_id}/records", {
      params: { path: { build_id: buildId! }, query: { ...query, sort, direction, offset: page * size, limit: size } }, signal })));

  const update = (changes: Record<string, string | undefined>, nextFilters?: Filters) => {
    let next = new URLSearchParams(params.toString());
    if (nextFilters) next = filtersToParams(nextFilters, next);
    for (const [k, v] of Object.entries(changes)) {
      if (v === undefined) next.delete(k);
      else next.set(k, v);
    }
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };
  const setFilters = (next: Filters) => update({ page: undefined }, next);
  const reset = () => router.replace(withBuild(pathname, params.get("build")), { scroll: false });
  const sortBy = (field: SortField) => update({ sort: field, dir: sort === field && direction === "asc" ? "desc" : "asc", page: undefined });

  const s = summary.data;
  const cats = categoriesOf(allCats.data);
  const dist = (field: string) => s?.distributions.find((d) => d.field === field);
  const maritalT = s?.display_translations.marital_status ?? {};
  const totalPages = records.data ? Math.max(1, Math.ceil(records.data.total_matching / size)) : 1;
  const available = build?.available_fields ?? [];

  const ageRows = (cats.age_group.length ? cats.age_group : []).map((age) => ({
    category: age, label: age,
    values: Object.fromEntries((s?.crosstab?.cells ?? []).filter((c) => c.row === age).map((c) => [c.column, c.count])),
  }));
  const maritalRows = (dist("marital_status")?.categories ?? []).map((c) => ({
    category: c.value, label: translations && maritalT[c.value] ? `${c.value} (${maritalT[c.value]})` : c.value, values: { count: c.count },
    share: c.share,
  }));

  return (
    <>
      <PageHeader title="Population Explorer">
        Browse the rows of the selected synthetic build. Filters, counts and charts are computed by the API over the actual rows.
      </PageHeader>
      <SyntheticNotice kind="population" />
      {buildError ? <ErrorState error={buildError} onRetry={reloadBuilds} what="builds" /> : null}
      {missingBuildId ? <UnavailableState title={`Build ${missingBuildId} is not registered.`}>Nothing else was selected. Choose a build in the bar above.</UnavailableState> : null}
      {build && build.availability.status !== "available" ? <UnavailableState title="This build's source file has changed." reasons={[build.availability.detail]} /> : null}

      {build && buildId ? (
        <>
          <section className="card" aria-labelledby="filters-h">
            <div className="card-head">
              <h2 id="filters-h">Filters</h2>
              <div className="row">
                <label className="check"><input type="checkbox" checked={translations} onChange={(e) => update({ tr: e.target.checked ? "1" : undefined })} />Show English translations of Turkish labels</label>
                <button type="button" className="button small" onClick={reset} disabled={filterCount(filters) === 0}>Reset filters</button>
              </div>
            </div>
            <FilterControls filters={filters} onChange={setFilters} categories={cats} availableFields={available} translations={maritalT}
              showTranslations={translations} idSearch disabled={!allCats.data} />
            <p className="small muted" style={{ marginTop: 10 }}>
              Geography and year are build context ({build.scope.province}, {build.scope.reference_year}), not row columns, so they cannot be filtered per row.
              {" "}The <code>gender</code> column is TÜİK&apos;s administrative sex category, not gender identity.
            </p>
          </section>

          {summary.error ? <ErrorState error={summary.error} onRetry={summary.reload} what="summary" /> : null}
          {summary.loading && !s ? <Loading what="summary" /> : null}
          {s ? (
            <section className={`card stack ${summary.loading ? "is-stale" : ""}`} aria-busy={summary.loading} aria-labelledby="summary-h">
              <div className="card-head">
                <h2 id="summary-h">{fmtInt(s.denominator)} of {fmtInt(s.total_records)} residents match</h2>
                <span className="small muted">Denominator for every share below: {fmtInt(s.denominator)}</span>
              </div>
              {s.denominator === 0 ? (
                <EmptyState title="No residents match these filters.">Reset or widen the filters. Nothing was substituted.</EmptyState>
              ) : (
                <>
                  <div className="tiles">
                    {(dist("gender")?.categories ?? []).map((c) => (
                      <StatTile key={c.value} label={`Sex: ${c.value}`} value={fmtInt(c.count)} sub={`${fmtPct(c.share)} of matching residents`} />
                    ))}
                  </div>
                  <div className={available.includes("marital_status") ? "grid-2" : "stack"}>
                    <BarChartCard title="Age group by sex" subtitle="residents" rows={ageRows}
                      series={[{ key: "male", label: "male", slot: "series-1" }, { key: "female", label: "female", slot: "series-2" }]}
                      valueLabel="residents" format={(v) => fmtInt(v)} />
                    {available.includes("marital_status") ? (
                      <BarChartCard title="Marital status" subtitle="residents; not_applicable for under-15s by construction" rows={maritalRows}
                        series={[{ key: "count", label: "Residents", slot: "series-1" }]} valueLabel="residents" format={(v) => fmtInt(v)}
                        tableExtra={[{ header: "Share", render: (r) => fmtPct((r as unknown as { share: number | null }).share) }]} />
                    ) : null}
                  </div>
                  <details>
                    <summary>Method and limitations</summary>
                    <div className="details-body">
                      <p>{s.method}</p>
                      <ul>{s.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
                      <h3>Source tables used to generate this build</h3>
                      <ul>
                        {(datasets.data?.fixture_evidence ?? []).filter((e) => e.kind === "processed_reference" && !e.path.includes("controls")
                          && (available.includes("marital_status") || !e.path.includes("marital"))).map((e) => (
                          <li key={e.path}><code>{e.path}</code>: {e.declared_source} <span className="muted small">SHA-256 {e.sha256 ? `${e.sha256.slice(0, 16)}…` : "missing"}</span></li>
                        ))}
                      </ul>
                      <p className="small muted">{datasets.data?.attribution_note}</p>
                      <p className="small muted">Source hash <code>{s.source_sha256}</code></p>
                    </div>
                  </details>
                </>
              )}
            </section>
          ) : null}

          <section className="card stack" aria-labelledby="records-h">
            <div className="card-head">
              <h2 id="records-h">Residents</h2>
              <div className="row small">
                <label htmlFor="page-size">Rows per page</label>
                <select id="page-size" value={size} onChange={(e) => update({ size: e.target.value, page: undefined })}>
                  {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
            </div>
            {records.error ? <ErrorState error={records.error} onRetry={records.reload} what="records" /> : null}
            {records.loading && !records.data ? <Loading what="residents" /> : null}
            {records.data ? (
              <div className={records.loading ? "is-stale" : ""} aria-busy={records.loading}>
                <div className="table-wrap">
                  <table>
                    <caption>Rows {records.data.total_matching === 0 ? 0 : records.data.offset + 1}–{records.data.offset + records.data.items.length} of {fmtInt(records.data.total_matching)} matching</caption>
                    <thead>
                      <tr>
                        {(["person_id", "age_group", "gender", "marital_status"] as SortField[]).filter((f) => available.includes(f)).map((f) => (
                          <th scope="col" key={f} aria-sort={sort === f ? (direction === "asc" ? "ascending" : "descending") : "none"}>
                            <button type="button" className="sort-button" onClick={() => sortBy(f)}>
                              {FIELD_LABELS[f]}{sort === f ? (direction === "asc" ? " ▲" : " ▼") : ""}
                            </button>
                          </th>
                        ))}
                        {available.includes("marital_status_conditioning") ? <th scope="col">Marital conditioning</th> : null}
                        <th scope="col" className="num">CSV row</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records.data.items.map((r) => (
                        <tr key={r.person_id}>
                          <th scope="row"><Link href={withBuild("/personas", params.get("build"), { record: r.person_id })}>{r.person_id}</Link></th>
                          <td>{r.age_group}</td>
                          <td>{r.gender}</td>
                          {available.includes("marital_status") ? <td>{r.marital_status}{translations && r.marital_status && maritalT[r.marital_status] ? <span className="muted"> ({maritalT[r.marital_status]})</span> : null}</td> : null}
                          {available.includes("marital_status_conditioning") ? <td><code>{r.marital_status_conditioning}</code></td> : null}
                          <td className="num">{r.csv_row}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <nav className="row" aria-label="Pagination" style={{ marginTop: 10 }}>
                  <button type="button" className="button small" disabled={page === 0} onClick={() => update({ page: String(page - 1) })}>Previous</button>
                  <span className="small">Page {page + 1} of {totalPages}</span>
                  <button type="button" className="button small" disabled={page + 1 >= totalPages} onClick={() => update({ page: String(page + 1) })}>Next</button>
                </nav>
              </div>
            ) : null}
          </section>
          <BuildDetails build={build} />
        </>
      ) : null}
    </>
  );
}
