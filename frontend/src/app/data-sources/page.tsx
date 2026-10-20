"use client";

import Link from "next/link";
import { BuildControlsButton, useCapabilities } from "@/components/national/common";
import { Notice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { StatTile } from "@/components/StatTile";
import { ErrorState, Loading } from "@/components/States";
import { Badge } from "@/components/StatusBadge";
import { v2, type CrossSourceAudit, type DataSources, type Discrepancy, type PackageAudit, type Source, type TableCheck } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { usePopulation } from "@/lib/population";
import { useApi } from "@/lib/useApi";

function Coverage({ n }: { n: number }) {
  return <Badge tone={n === 81 ? "good" : n === 0 ? "neutral" : "warn"}>{n}/81 provinces</Badge>;
}

function show(value: unknown): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "number") return fmtInt(value);
  if (Array.isArray(value)) return value.length > 12 ? `${value.slice(0, 12).join(", ")} … (${value.length})` : value.join(", ") || "none";
  if (typeof value === "object") return Object.entries(value as Record<string, unknown>).map(([k, v]) => `${k} ${show(v)}`).join(" · ");
  return String(value);
}

function years(list: number[] | undefined): string {
  if (!list?.length) return "";
  const runs: string[] = [];
  let start = list[0], prev = list[0];
  for (const y of [...list.slice(1), NaN]) {
    if (y === prev + 1) { prev = y; continue; }
    runs.push(start === prev ? `${start}` : `${start}–${prev}`);
    start = prev = y;
  }
  return runs.join(", ");
}

function CheckLine({ k }: { k: TableCheck }) {
  if (!k.summary) return <div>{k.passed ? "✓" : "×"} {k.detail} {k.sex ? `(${k.sex} ${k.year})` : ""}</div>;
  return (
    <div>{k.passed ? "✓" : "×"} {k.detail} <span className="muted">({fmtInt(k.checked)} checked{k.failed ? `, ${fmtInt(k.failed)} differ in ${years(k.years_failed)}` : ""})</span></div>
  );
}

function DiscrepancyTable({ items, caption }: { items: Discrepancy[]; caption: string }) {
  return (
    <div className="table-wrap"><table><caption>{caption}</caption>
      <thead><tr><th>Dataset</th><th>Field</th><th>Claimed</th><th>Found in the data</th><th>Note</th></tr></thead>
      <tbody>{items.map((d, i) => (
        <tr key={i}><td>{d.dataset ?? "whole package"}</td><td><code>{d.field}</code></td><td className="small">{show(d.claimed)}</td>
          <td className="small">{show(d.actual)}</td><td className="small">{d.note}</td></tr>))}</tbody></table></div>
  );
}

function PackageSummary({ audit }: { audit: PackageAudit }) {
  const c = audit.counts;
  const claims = audit.documentation_claims.claims;
  const dist = Object.entries(c.province_coverage_distribution).map(([n, k]) => `${k} dataset${k === 1 ? "" : "s"} × ${n} provinces`).join(" · ");
  return (
    <>
      <div className="tiles">
        <StatTile label="Datasets" value={fmtInt(c.datasets)} sub={dist} />
        <StatTile label="Long-format rows" value={fmtInt(c.long_rows)} sub={claims.long_rows != null && claims.long_rows !== c.long_rows ? `README claims ${fmtInt(claims.long_rows)}` : "Matches the README"} />
        <StatTile label="Indicators with data" value={fmtInt(c.indicators)} sub={`${fmtInt(c.variable_metadata_indicators)} defined in variable_metadata.csv`} />
        <StatTile label="Blank values" value={fmtInt(c.blank_values)} sub="NOT_REPORTED, never zero" />
        <StatTile label="Multi-year periods" value={fmtInt(c.multi_year_rows)} sub="Kept as published (e.g. 2021-2023)" />
        <StatTile label="Projection rows" value={fmtInt(c.projection_rows)} sub="Never used as current observations" />
      </div>
      <p className="small">
        {fmtInt(audit.files.total)} files in <code>{audit.package_dir}</code>: {audit.files.long_format} long-format datasets, {audit.files.wide} wide files,
        metadata {audit.files.metadata.join(", ")}{audit.files.documentation.length ? ` and ${audit.files.documentation.join(", ")}` : ""}.
        Every long-format row is accounted for: {fmtInt(c.control_cells)} control cells, {fmtInt(c.context_observations)} province context observations,
        {" "}{fmtInt(c.rejected_rows)} rejected; {fmtInt(c.duplicate_keys_conflicting)} conflicting duplicate keys.
        The {audit.wide_files.verified} wide files were compared cell by cell with the long files ({fmtInt(audit.wide_files.cells_compared)} cells,
        {" "}{fmtInt(audit.wide_files.mismatches)} mismatches) and are not imported, so nothing is counted twice.
      </p>
    </>
  );
}

function SourceDetails({ s }: { s: Source }) {
  const periods = s.reference_periods ?? s.reference_years.map(String);
  const multi = periods.filter((p) => p.includes("-"));
  return (
    <details>
      <summary>{s.title_en ?? s.source_id} <Coverage n={s.province_coverage.length} />{" "}
        <Badge tone={s.status === "used" ? "good" : "neutral"}>{s.status === "used" ? (s.mapping ? `control: ${s.mapping.tables.join(", ")}` : "used")
          : s.status === "corroborating" ? "corroborating" : "context only"}</Badge>
        {s.observation_type === "projection" ? <> <Badge tone="warn">projection</Badge></> : null}
        {s.discrepancies?.length ? <> <Badge tone="warn">{s.discrepancies.length} discrepanc{s.discrepancies.length === 1 ? "y" : "ies"}</Badge></> : null}
      </summary>
      <div className="details-body">
        <dl className="kv">
          <dt>Source ID</dt><dd><code>{s.source_id}</code></dd>
          <dt>Publisher</dt><dd>{s.publisher}</dd>
          <dt>Turkish title</dt><dd>{s.title_tr ?? "Not recorded"}</dd>
          <dt>Identifier</dt><dd>{s.dataset_identifier ?? "Not recorded"}</dd>
          <dt>URL</dt><dd>{s.url ? <a href={s.url} rel="noreferrer" target="_blank">{s.url}</a> : "Not recorded"}</dd>
          <dt>Publication / retrieval</dt><dd>{s.publication_date ?? "not recorded"} / {s.retrieval_date ?? "not recorded"}</dd>
          <dt>Reference periods</dt><dd>{years(s.reference_years)}{multi.length ? `${s.reference_years.length ? "; " : ""}periods ${multi.join(", ")}` : ""}
            {s.catalog_reference_years ? <span className="small muted"> (catalog: {s.catalog_reference_years})</span> : null}</dd>
          <dt>Geographic level</dt><dd>{s.geographic_level} · {s.province_coverage.length}/81 provinces
            {s.missing_provinces?.length && s.missing_provinces.length < 81 ? <span className="small muted"> · not covered: {s.missing_provinces.join(", ")}</span> : null}</dd>
          {s.mapping ? <><dt>Use</dt><dd className="small">{s.mapping.use === "controls" ? `Generator control table${s.mapping.tables.length > 1 ? "s" : ""} ${s.mapping.tables.join(", ")}; aggregate rows and other indicators are context.` : "Province context only."}{s.mapping.reason ? ` ${s.mapping.reason}` : ""}</dd></> : null}
          <dt>Variables</dt><dd className="small">{s.variables.slice(0, 20).join(", ")}{(s.variable_count ?? s.variables.length) > 20 ? ` … (${s.variable_count})` : ""}</dd>
          <dt>Units</dt><dd>{s.units.join(", ") || "–"}</dd>
          {s.accounting ? <><dt>Rows</dt><dd className="small">{fmtInt(s.accounting.read)} read · {fmtInt(s.accounting.control_cells)} control cells · {fmtInt(s.accounting.context_observations)} context · {fmtInt(s.accounting.rejected)} rejected
            {s.blank_values ? ` · ${fmtInt(s.blank_values)} blank (NOT_REPORTED)` : ""}{s.absent_province_rows ? ` · ${fmtInt(s.absent_province_rows)} absent province rows (not zero)` : ""}</dd></> : null}
          {s.value_status_counts ? <><dt>Value statuses</dt><dd>{Object.entries(s.value_status_counts).map(([k, v]) => `${k} ${fmtInt(v)}`).join(" · ")}</dd></> : null}
          <dt>Transformations</dt><dd className="small">{s.transformations.join(" ")}</dd>
          <dt>Checksum</dt><dd className="small">{s.processed_file ? <><code>{s.processed_file.sha256.slice(0, 16)}…</code> ({s.processed_file.path})</> : s.raw_files?.map((f) => <div key={f.path}><code>{f.sha256.slice(0, 16)}…</code> {f.path}</div>)}
            {s.wide_files?.map((w) => <div key={w.file}><code>{w.sha256.slice(0, 16)}…</code> {w.file} · verified, {fmtInt(w.mismatches)} mismatches in {fmtInt(w.cells_compared)} cells</div>)}</dd>
          <dt>Limitations</dt><dd><ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{s.limitations.map((l) => <li key={l}>{l}</li>)}</ul></dd>
        </dl>
        {s.discrepancies?.length ? <DiscrepancyTable items={s.discrepancies} caption="Package metadata compared with the data" /> : null}
      </div>
    </details>
  );
}

export default function DataSourcesPage() {
  const { reload: reloadPops } = usePopulation();
  const caps = useCapabilities();
  const ds = useApi("v2:data-sources", (signal) => v2<DataSources>("/data-sources", { signal }));
  const c = ds.data?.controls;
  const audit = c?.audits?.find((a): a is PackageAudit => a.adapter === "tuik_long_format_package");
  const cross = c?.audits?.find((a): a is CrossSourceAudit => a.adapter === "cross_source");
  const tables = new Set(c?.tables?.map((t) => t.table_id) ?? []);
  const unsupported = Object.entries({ labour_status: ["labour_status_sex", "labour_status_age_sex"], household_size_class: ["household_size_persons"],
    household_type: ["household_type_persons"] }).filter(([, ids]) => !ids.some((t) => tables.has(t))).map(([a]) => a);
  const partial = (c?.sources ?? []).filter((s) => s.source_id.startsWith("tuik_pkg:") && s.province_coverage.length < 81);
  const packageSources = (c?.sources ?? []).filter((s) => s.source_id.startsWith("tuik_pkg:"));
  const otherSources = (c?.sources ?? []).filter((s) => !s.source_id.startsWith("tuik_pkg:"));
  return (
    <>
      <PageHeader title="Data Sources">Official aggregate statistics used by the generator and the province environment, their periods, coverage and limitations. Missing coverage is shown, never filled.</PageHeader>
      {ds.error ? <ErrorState error={ds.error} onRetry={ds.reload} /> : null}
      {ds.loading && !ds.data ? <Loading what="data sources" /> : null}
      {ds.data ? (
        <>
          <section className="card stack" aria-labelledby="pkg-h">
            <h2 id="pkg-h">Long-format TÜİK package</h2>
            {!ds.data.package.present ? <Notice tone="warn" title="Not in this checkout.">The team's province package (33 datasets, long and wide format) is not present. Put its files directly in <code>{ds.data.package.directory}/</code> (git-ignored), then rebuild. Until then only the historical Ankara extracts are available.</Notice>
              : audit ? <PackageSummary audit={audit} />
              : <p className="small">Found in <code>{ds.data.package.directory}</code> ({ds.data.package.files} files). Build the control tables to read it.</p>}
            <p className="small muted">Indicators become generator control tables only through the rules in <code>{ds.data.package.mapping_file}</code>; every other indicator is province context (environment) with its own reference period and value status.</p>
            <div className="row"><span className="small muted">Control store: <strong>{c?.status}</strong>{c?.built_at ? ` · built ${c.built_at}` : ""} · builder {c?.builder_version}</span></div>
            <BuildControlsButton onDone={() => { ds.reload(); reloadPops(); }} />
          </section>
          {audit?.discrepancies.length ? (
            <section className="card stack" aria-labelledby="disc-h">
              <h2 id="disc-h">Package documentation compared with the data</h2>
              <p className="small">{audit.documentation_claims.note} The data is what the pipeline uses; the differences below are recorded, not corrected.</p>
              <DiscrepancyTable items={audit.discrepancies} caption={`${audit.discrepancies.length} discrepancies`} />
            </section>
          ) : null}
          {c?.status === "built" ? (
            <>
              <section className="card" aria-labelledby="tab-h">
                <h2 id="tab-h">Standard control tables (generator inputs)</h2>
                <div className="table-wrap"><table><caption>{c.tables?.length} tables · {fmtInt(c.context_indicators)} context indicators ({fmtInt(c.context_observations)} observations{c.multi_year_observations ? `, ${fmtInt(c.multi_year_observations)} for multi-year periods` : ""}{c.projection_observations ? `, ${fmtInt(c.projection_observations)} projections` : ""})</caption>
                  <thead><tr><th>Table</th><th>Universe</th><th>Coverage</th><th>Years</th><th>Sources</th><th>Checks and limitations</th></tr></thead>
                  <tbody>{c.tables?.map((t) => (
                    <tr key={t.table_id}><th><code>{t.table_id}</code><div className="small muted">{t.title}</div></th><td className="small">{t.universe_note} ({t.universe_min_age}+)</td>
                      <td><Coverage n={t.province_coverage} /></td><td>{years(t.years)}</td><td className="small">{t.source_ids.join(", ")}</td>
                      <td className="small">{t.checks.map((k, i) => <CheckLine key={i} k={k} />)}{t.limitations.map((l) => <div key={l} className="muted">{l}</div>)}</td></tr>))}</tbody></table></div>
              </section>
              <section className="card stack" aria-labelledby="gap-h">
                <h2 id="gap-h">Remaining gaps</h2>
                <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                  {unsupported.length ? <li>No province-level table supports {unsupported.map((a) => <code key={a}>{a}</code>).reduce((acc: React.ReactNode[], el, i) => [...acc, i ? ", " : "", el], [])}: these person attributes stay unavailable (null) everywhere. The related package data (labour-force rates, household counts) is province context; see each source for the reason.</li> : null}
                  {caps.data ? Object.entries(caps.data.dependency_model.not_modelled).map(([k, v]) => <li key={k}><code>{k}</code>: {v}</li>) : null}
                  {partial.map((s) => <li key={s.source_id}>{s.title_en}: {s.province_coverage.length}/81 provinces; the others are STRUCTURALLY_UNAVAILABLE, not zero.</li>)}
                  <li>Marital status and education are published by sex only (15+); their relationship with age is inferred (IPF), not observed.</li>
                </ul>
                {audit?.not_province_level.length ? (
                  <div className="table-wrap"><table><caption>TÜİK datasets not published by province (not_province_level.csv; not loaded)</caption>
                    <thead><tr><th>Dataset</th><th>Published level</th><th>Reason</th></tr></thead>
                    <tbody>{audit.not_province_level.map((d, i) => (
                      <tr key={i}><th className="small">{d.url ? <a href={d.url} rel="noreferrer" target="_blank">{d.title_en}</a> : d.title_en}</th><td className="small">{d.geographic_level}</td><td className="small">{d.reason}</td></tr>))}</tbody></table></div>
                ) : null}
              </section>
              <section className="card stack" aria-labelledby="src-h">
                <h2 id="src-h">Sources</h2>
                {packageSources.length ? <p className="small muted">{packageSources.length} package datasets · {packageSources.filter((s) => s.status === "used").length} feed control tables · the rest are province context.</p> : null}
                {[...packageSources, ...otherSources].map((s) => <SourceDetails key={s.source_id} s={s} />)}
              </section>
              {cross?.checks.length ? (
                <section className="card stack" aria-labelledby="cross-h">
                  <h2 id="cross-h">Cross-source checks</h2>
                  <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                    {cross.checks.filter((k) => k.check === "agreeing_cells").map((k, i) => <li key={i}>✓ {k.detail}</li>)}
                    {(() => {
                      const ctx = cross.checks.filter((k) => k.check === "legacy_context_equals_package");
                      const failed = ctx.filter((k) => !k.passed);
                      return ctx.length ? <li>{failed.length ? "×" : "✓"} {ctx.length - failed.length} of {ctx.length} historical Ankara context values equal the package values{failed.length ? `; different: ${failed.map((k) => `${k.indicator} ${k.period}`).join(", ")}` : ""}.</li> : null;
                    })()}
                  </ul>
                </section>
              ) : null}
              {c.warnings?.length ? <section className="card"><h2>Ingestion warnings</h2><ul className="small">{c.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></section> : null}
            </>
          ) : <p className="muted small">{c?.detail}</p>}
          <section className="card" aria-labelledby="man-h">
            <h2 id="man-h">Root data manifest</h2>
            <p className="small"><code>{ds.data.root_manifest.path}</code>: {ds.data.root_manifest.status} ({ds.data.root_manifest.datasets.length} entries). {ds.data.root_manifest.note}</p>
            <p className="small muted">Missing values keep their status: OBSERVED (a published number, including 0), NOT_REPORTED (blank), UNKNOWN, NOT_APPLICABLE and STRUCTURALLY_UNAVAILABLE (dataset does not cover the province). None is shown as zero. Rows absent from the package are not created. See also <Link href="/historical/data-sources">historical fixture evidence</Link>.</p>
          </section>
        </>
      ) : null}
    </>
  );
}
