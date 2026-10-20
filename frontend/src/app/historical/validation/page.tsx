"use client";

import { DivergingBars } from "@/components/charts/DivergingBars";
import { Notice, SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading, UnavailableState } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { Badge, CheckBadge, HashBadge } from "@/components/StatusBadge";
import { ValidationTabs } from "@/components/ValidationTabs";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useBuild } from "@/lib/build";
import { fmtDecimal, fmtInt, fmtPct, fmtPp } from "@/lib/format";
import { useApi } from "@/lib/useApi";

function ShareTable({ metric, caption }: { metric: Omit<Schemas["ValidationMetric"], "acceptance_threshold">; caption: string }) {
  return (
    <div className="table-wrap">
      <table>
        <caption>{caption} · denominator {fmtInt(metric.denominator)}</caption>
        <thead><tr><th scope="col">Category</th><th scope="col" className="num">Synthetic count</th><th scope="col" className="num">Synthetic share</th><th scope="col" className="num">Reference share</th><th scope="col" className="num">Difference</th></tr></thead>
        <tbody>
          {(metric.categories ?? []).map((c) => (
            <tr key={c.category}><th scope="row">{c.category}</th><td className="num">{fmtInt(c.count)}</td><td className="num">{fmtPct(c.synthetic_share, 2)}</td><td className="num">{fmtPct(c.reference_share, 2)}</td><td className="num">{fmtPp(c.difference_pp)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ValidationPage() {
  const { build, missingBuildId } = useBuild();
  const buildId = build?.availability.status === "available" ? build.build_id : null;
  const report = useApi(buildId ? `validation:${buildId}` : null, (signal) =>
    unwrap(api.GET("/api/v1/builds/{build_id}/validation", { params: { path: { build_id: buildId! } }, signal })));
  const v = report.data;
  const metric = (name: string) => v?.metrics.find((m) => m.name === name);
  const age = metric("age_group_marginal_share_difference");
  const sex = metric("gender_marginal_share_difference");
  const joint = metric("joint_age_gender_tvd");
  const maritalMetrics = v?.metrics.filter((m) => m.name.startsWith("marital_within_")) ?? [];

  return (
    <>
      <PageHeader title="Validation">
        Integrity checks and source-table comparisons for the selected build, computed by the API. No acceptance thresholds are agreed in
        the project docs, so nothing here is a pass mark or an accuracy score.
      </PageHeader>
      <ValidationTabs />
      <SyntheticNotice kind="population" />
      {missingBuildId ? <UnavailableState title={`Build ${missingBuildId} is not registered.`} /> : null}
      {report.loading && !v ? <Loading what="validation report" /> : null}
      {report.error ? <ErrorState error={report.error} onRetry={report.reload} what="validation" /> : null}
      {v ? (
        <>
          <Notice tone="info" title="What this evidence can show.">
            These compare the synthetic rows with the same tables used to generate them (source-table comparison). They check the
            implementation; they are not independent validation. {v.acceptance_note}
          </Notice>

          <section className="card stack" aria-labelledby="integrity-h">
            <div className="card-head"><h2 id="integrity-h">Integrity checks</h2><Badge tone="neutral" glyph="▤">Implementation checks</Badge></div>
            <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {v.checks.map((c) => <li key={c.name}><div className="row"><CheckBadge passed={c.passed} /><code>{c.name}</code></div><div className="small muted">{c.detail}</div></li>)}
            </ul>
          </section>

          <section className="card stack" aria-labelledby="fit-h">
            <div className="card-head"><h2 id="fit-h">Source-table fit</h2><Badge tone="neutral" glyph="≈">Evidence A: source tables</Badge></div>
            <div className="tiles">
              {joint ? <StatTile label="Joint age × sex TVD" value={fmtDecimal(joint.value, 4)} sub="Total variation distance: 0 is identical, 1 is disjoint. No threshold agreed." /> : null}
              {maritalMetrics.map((m) => (
                <StatTile key={m.name} label={`Marital status TVD, ${m.name.includes("_male_") ? "male" : "female"} 15+`} value={fmtDecimal(m.value, 4)}
                  sub={`Among ${fmtInt(m.denominator)} synthetic residents aged 15+`} />
              ))}
            </div>
            {age ? (
              <DivergingBars title="Age group share: synthetic minus reference" subtitle="percentage points"
                rows={(age.categories ?? []).map((c) => ({ category: c.category, label: c.category, value: c.difference_pp,
                  detail: `synthetic ${fmtPct(c.synthetic_share, 2)} vs reference ${fmtPct(c.reference_share, 2)} (${fmtInt(c.count)} residents)` }))}
                positiveLabel="Synthetic share higher" negativeLabel="Synthetic share lower" format={(x) => fmtPp(x)} />
            ) : null}
            {sex ? <ShareTable metric={sex} caption="Sex (administrative category) shares" /> : null}
            {maritalMetrics.length ? (
              <div className="grid-2">
                {maritalMetrics.map((m) => (
                  <div className="stack" key={m.name}>
                    <DivergingBars title={`Marital status, ${m.name.includes("_male_") ? "male" : "female"} aged 15+`} subtitle="synthetic minus T10 share, percentage points"
                      rows={(m.categories ?? []).map((c) => ({ category: c.category, label: c.category, value: c.difference_pp,
                        detail: `synthetic ${fmtPct(c.synthetic_share, 2)} vs reference ${fmtPct(c.reference_share, 2)}` }))}
                      positiveLabel="Synthetic share higher" negativeLabel="Synthetic share lower" format={(x) => fmtPp(x)} />
                    <p className="small muted">{m.limitations.join(" ")}</p>
                  </div>
                ))}
              </div>
            ) : <p className="small muted">This build has no marital status, so marital fit is not computed.</p>}
            <details>
              <summary>Metric definitions and reference tables</summary>
              <div className="details-body">
                <ul>{v.metrics.map((m) => <li key={m.name}><code>{m.name}</code>: {m.method} <span className="muted">({m.evidence_kind}; threshold: none agreed)</span></li>)}</ul>
                <div className="table-wrap">
                  <table>
                    <caption>Reference tables</caption>
                    <thead><tr><th scope="col">Path</th><th scope="col">Year</th><th scope="col" className="num">Rows</th><th scope="col">SHA-256</th></tr></thead>
                    <tbody>{v.reference_tables.map((t) => <tr key={t.path}><td><code>{t.path}</code></td><td>{t.reference_year}</td><td className="num">{t.rows}</td><td><code>{t.sha256}</code></td></tr>)}</tbody>
                  </table>
                </div>
                <p className="small muted">Population SHA-256 <code>{v.population_sha256}</code> · method {v.method_version}</p>
              </div>
            </details>
          </section>

          <section className="card stack" aria-labelledby="missing-h">
            <h2 id="missing-h">Evidence that is not available</h2>
            <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {v.unavailable_evidence.map((u) => (
                <li key={u.name}><div className="row"><Badge tone="neutral" glyph="·">Unavailable</Badge><strong>{u.name.replaceAll("_", " ")}</strong><span className="small muted">({u.evidence_kind})</span></div><div className="small">{u.reason}</div></li>
              ))}
            </ul>
          </section>

          <section className="card stack" aria-labelledby="persona-hash-h">
            <h2 id="persona-hash-h">Persona provenance digests</h2>
            <p className="small muted">Digests recorded inside the persona fixtures, compared with today&apos;s files. Historical values are kept unchanged.</p>
            {v.persona_hash_checks.length === 0 ? <p className="muted">No persona fixture is linked to this build.</p> : (
              <div className="table-wrap">
                <table>
                  <caption>Persona fixtures linked to this build</caption>
                  <thead><tr><th scope="col">Persona file</th><th scope="col">Recorded input</th><th scope="col">Comparison</th></tr></thead>
                  <tbody>
                    {v.persona_hash_checks.flatMap((p) => p.checks.map((c, i) => (
                      <tr key={`${p.persona_file}:${c.name}`}>
                        <th scope="row">{i === 0 ? <><code>{p.persona_file}</code><div className="small muted">{p.persona_id}</div></> : null}</th>
                        <td><code>{c.name}</code></td>
                        <td><HashBadge status={c.status} /></td>
                      </tr>
                    )))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="small muted">{v.attribution_note}</p>
          </section>
        </>
      ) : null}
    </>
  );
}
