"use client";

import { CopyId } from "@/components/CopyId";
import { Notice, SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { Badge } from "@/components/StatusBadge";
import { ValidationTabs } from "@/components/ValidationTabs";
import { api, unwrap } from "@/lib/api/client";
import { fmtInt } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const STAT_LABELS: Record<string, string> = {
  total_population: "Total population", male_population: "Male population", female_population: "Female population",
  population_density: "Population density", total_median_age: "Median age (total)", male_median_age: "Median age (male)",
  female_median_age: "Median age (female)",
};

export default function DataSourcesPage() {
  const data = useApi("datasets", (signal) => unwrap(api.GET("/api/v1/datasets", { signal })));
  const d = data.data;
  return (
    <>
      <PageHeader title="Data Sources">
        What the fixtures in this checkout are, where the project recorded them as coming from, and what provenance is missing.
      </PageHeader>
      <ValidationTabs />
      <SyntheticNotice kind="population" />
      {data.loading && !d ? <Loading what="data sources" /> : null}
      {data.error ? <ErrorState error={data.error} onRetry={data.reload} /> : null}
      {d ? (
        <>
          <section className="card stack" aria-labelledby="manifest-h">
            <div className="card-head"><h2 id="manifest-h">Root data manifest</h2><code>{d.manifest.path}</code></div>
            <p className="row"><Badge tone="neutral" glyph="○">{`Status: ${d.manifest.status}`}</Badge><span className="small">{d.manifest.note}</span></p>
            {d.manifest.datasets.length === 0 ? <EmptyState title="No datasets are registered in the root manifest.">The processed fixtures below are listed separately and are not manifest entries.</EmptyState> : (
              <pre className="prompt">{JSON.stringify(d.manifest.datasets, null, 2)}</pre>
            )}
            {d.manifest.error ? <Notice tone="crit" title="The manifest could not be read:">{d.manifest.error}</Notice> : null}
          </section>

          <section className="card stack" aria-labelledby="fixtures-h">
            <h2 id="fixtures-h">Fixture evidence in this checkout</h2>
            <p className="small muted">{d.attribution_note} No source URL, download date or raw checksum is invented here.</p>
            <div className="table-wrap">
              <table>
                <caption>Files with their current SHA-256</caption>
                <thead><tr><th scope="col">File</th><th scope="col">Kind</th><th scope="col">Declared source</th><th scope="col" className="num">Rows</th><th scope="col">Raw evidence</th><th scope="col">Licence</th><th scope="col">Gaps</th></tr></thead>
                <tbody>
                  {d.fixture_evidence.map((e) => (
                    <tr key={e.path}>
                      <th scope="row"><code>{e.path}</code>{e.sha256 ? <div className="small"><CopyId value={e.sha256} label={`SHA-256 of ${e.path}`} /></div> : <div className="small">missing</div>}</th>
                      <td>{e.kind.replaceAll("_", " ")}</td>
                      <td className="small">{e.declared_source}</td>
                      <td className="num">{e.rows === null ? "–" : fmtInt(e.rows)}</td>
                      <td>{e.raw_evidence_status === "unavailable" ? <Badge tone="warn" glyph="!">Unavailable</Badge> : e.raw_evidence_status.replaceAll("_", " ")}</td>
                      <td>{e.licence ?? "Unknown"}</td>
                      <td className="small"><ul style={{ margin: 0, paddingLeft: 16 }}>{e.gaps.map((g) => <li key={g}>{g}</li>)}</ul></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card stack" aria-labelledby="controls-h">
            <h2 id="controls-h">Demographic controls</h2>
            <p className="small muted">{d.controls_note}</p>
            <div className="table-wrap">
              <table>
                <caption>Distinct facts by year (source observations grouped when they agree)</caption>
                <thead><tr><th scope="col">Year</th><th scope="col">Statistic</th><th scope="col" className="num">Value</th><th scope="col">Unit</th><th scope="col">Source observations</th></tr></thead>
                <tbody>
                  {d.controls.map((c) => (
                    <tr key={`${c.year}:${c.statistic}`}>
                      <td>{c.year}</td>
                      <th scope="row">{STAT_LABELS[c.statistic] ?? c.statistic} <span className="small muted"><code>{c.statistic}</code></span></th>
                      <td className="num">{c.unit === "persons" ? fmtInt(c.value) : c.value.toFixed(2)}</td>
                      <td>{c.unit}</td>
                      <td className="small">
                        {c.observations.length} {c.observations.length === 1 ? "observation" : "agreeing observations"}
                        <ul style={{ margin: 0, paddingLeft: 16 }}>{c.observations.map((o) => <li key={`${o.source_workbook}:${o.csv_row}`}><code>{o.source_workbook}</code>, sheet {o.source_sheet}, row {o.source_row}</li>)}</ul>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </>
  );
}
