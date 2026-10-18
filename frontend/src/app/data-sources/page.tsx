"use client";

import Link from "next/link";
import { BuildControlsButton } from "@/components/national/common";
import { Notice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading } from "@/components/States";
import { Badge } from "@/components/StatusBadge";
import { v2, type DataSources } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { usePopulation } from "@/lib/population";
import { useApi } from "@/lib/useApi";

function Coverage({ n }: { n: number }) {
  return <Badge tone={n === 81 ? "good" : n === 0 ? "neutral" : "warn"}>{n}/81 provinces</Badge>;
}

export default function DataSourcesPage() {
  const { reload: reloadPops } = usePopulation();
  const ds = useApi("v2:data-sources", (signal) => v2<DataSources>("/data-sources", { signal }));
  const c = ds.data?.controls;
  return (
    <>
      <PageHeader title="Data Sources">Official aggregate statistics used by the generator, their years, coverage and limitations. Missing coverage is shown, never filled.</PageHeader>
      {ds.error ? <ErrorState error={ds.error} onRetry={ds.reload} /> : null}
      {ds.loading && !ds.data ? <Loading what="data sources" /> : null}
      {ds.data ? (
        <>
          <section className="card stack" aria-labelledby="pkg-h">
            <h2 id="pkg-h">Long-format TÜİK package</h2>
            {ds.data.package.present ? <p className="small">Found in <code>{ds.data.package.directory}</code>. Indicators become control tables only through rules in <code>{ds.data.package.mapping_file}</code>; every other indicator is province context.</p>
              : <Notice tone="warn" title="Not in this checkout.">The team's 33-dataset package (577 indicators, long format) is not present. Put it in <code>{ds.data.package.directory}/</code> (git-ignored), add control rules to <code>{ds.data.package.mapping_file}</code>, then rebuild. Until then only the historical Ankara extracts below are available, so 80 provinces have no source data.</Notice>}
            <div className="row"><span className="small muted">Control store: <strong>{c?.status}</strong>{c?.built_at ? ` · built ${c.built_at}` : ""} · builder {c?.builder_version}</span></div>
            <BuildControlsButton onDone={() => { ds.reload(); reloadPops(); }} />
          </section>
          {c?.status === "built" ? (
            <>
              <section className="card" aria-labelledby="tab-h">
                <h2 id="tab-h">Standard control tables (generator inputs)</h2>
                <div className="table-wrap"><table><caption>{c.tables?.length} tables · {fmtInt(c.context_indicators)} context indicators</caption>
                  <thead><tr><th>Table</th><th>Universe</th><th>Coverage</th><th>Years</th><th>Sources</th><th>Checks and limitations</th></tr></thead>
                  <tbody>{c.tables?.map((t) => (
                    <tr key={t.table_id}><th><code>{t.table_id}</code><div className="small muted">{t.title}</div></th><td className="small">{t.universe_note} ({t.universe_min_age}+)</td>
                      <td><Coverage n={t.province_coverage} /></td><td>{t.years.join(", ")}</td><td className="small">{t.source_ids.join(", ")}</td>
                      <td className="small">{t.checks.map((k, i) => <div key={i}>{k.passed ? "✓" : "×"} {k.detail} {k.sex ? `(${k.sex} ${k.year})` : ""}</div>)}{t.limitations.map((l) => <div key={l} className="muted">{l}</div>)}</td></tr>))}</tbody></table></div>
              </section>
              <section className="card stack" aria-labelledby="src-h">
                <h2 id="src-h">Sources</h2>
                {c.sources?.map((s) => (
                  <details key={s.source_id}>
                    <summary>{s.title_en ?? s.source_id} <Coverage n={s.province_coverage.length} /> <Badge tone={s.status === "used" ? "good" : "neutral"}>{s.status.replace("_", " ")}</Badge></summary>
                    <div className="details-body">
                      <dl className="kv">
                        <dt>Source ID</dt><dd><code>{s.source_id}</code></dd>
                        <dt>Publisher</dt><dd>{s.publisher}</dd>
                        <dt>Turkish title</dt><dd>{s.title_tr ?? "Not recorded"}</dd>
                        <dt>Identifier</dt><dd>{s.dataset_identifier ?? "Not recorded"}</dd>
                        <dt>URL</dt><dd>{s.url ? <a href={s.url} rel="noreferrer" target="_blank">{s.url}</a> : "Not recorded"}</dd>
                        <dt>Publication / retrieval</dt><dd>{s.publication_date ?? "not recorded"} / {s.retrieval_date ?? "not recorded"}</dd>
                        <dt>Reference years</dt><dd>{s.reference_years.join(", ")}</dd>
                        <dt>Geographic level</dt><dd>{s.geographic_level} · provinces {s.province_coverage.join(", ")}</dd>
                        <dt>Variables</dt><dd className="small">{s.variables.slice(0, 20).join(", ")}{(s.variable_count ?? s.variables.length) > 20 ? ` … (${s.variable_count})` : ""}</dd>
                        <dt>Units</dt><dd>{s.units.join(", ") || "–"}</dd>
                        <dt>Transformations</dt><dd className="small">{s.transformations.join(" ")}</dd>
                        <dt>Checksum</dt><dd className="small">{s.processed_file ? <><code>{s.processed_file.sha256.slice(0, 16)}…</code> ({s.processed_file.path})</> : s.raw_files?.map((f) => <div key={f.path}><code>{f.sha256.slice(0, 16)}…</code> {f.path}</div>)}</dd>
                        {s.value_status_counts ? <><dt>Value statuses</dt><dd>{Object.entries(s.value_status_counts).map(([k, v]) => `${k} ${v}`).join(" · ")}</dd></> : null}
                        <dt>Limitations</dt><dd><ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{s.limitations.map((l) => <li key={l}>{l}</li>)}</ul></dd>
                      </dl>
                    </div>
                  </details>
                ))}
              </section>
              {c.warnings?.length ? <section className="card"><h2>Ingestion warnings</h2><ul className="small">{c.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></section> : null}
            </>
          ) : <p className="muted small">{c?.detail}</p>}
          <section className="card" aria-labelledby="man-h">
            <h2 id="man-h">Root data manifest</h2>
            <p className="small"><code>{ds.data.root_manifest.path}</code>: {ds.data.root_manifest.status} ({ds.data.root_manifest.datasets.length} entries). {ds.data.root_manifest.note}</p>
            <p className="small muted">Missing values keep their status: OBSERVED (a published number, including 0), NOT_REPORTED, UNKNOWN, NOT_APPLICABLE and STRUCTURALLY_UNAVAILABLE (dataset does not cover the province). None is shown as zero. See also <Link href="/historical/data-sources">historical fixture evidence</Link>.</p>
          </section>
        </>
      ) : null}
    </>
  );
}
