"use client";

import { useState } from "react";
import { PopulationGate, useLabels } from "@/components/national/common";
import { Notice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { Badge } from "@/components/StatusBadge";
import { v2, type TableFit, type ValidationReport } from "@/lib/api/v2";
import { fmtInt, fmtPct, fmtPp } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const STATUS: Record<string, { tone: "good" | "warn" | "crit" | "neutral" | "info"; label: string }> = {
  fit_by_construction: { tone: "good", label: "Fit by construction (calibrated)" },
  calibration_gap: { tone: "warn", label: "Calibration gap" },
  not_calibrated: { tone: "neutral", label: "Not calibrated" },
  within_sampling_noise: { tone: "good", label: "Records within sampling noise" },
  outside_sampling_noise: { tone: "crit", label: "Records outside sampling noise" },
  not_assessed_small_sample: { tone: "neutral", label: "Too few records to assess" },
  not_validated_regional_source: { tone: "neutral", label: "Regional source: not validated per province" },
};

function StatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const s = STATUS[status] ?? { tone: "neutral", label: status };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

function TableCard({ t, label }: { t: TableFit; label: (field: string, code: string) => string }) {
  if (!t.cells) return <div className="notice"><strong>{t.table_id}</strong> <StatusBadge status={t.status} /> <span className="small muted">{t.detail}</span></div>;
  const dims = t.table_id === "population_age_sex" ? ["age_group", "sex"] : t.table_id.includes("_age_sex") ? ["age_group", "sex", t.attribute ?? ""] :
    t.table_id.endsWith("_sex") ? ["sex", t.attribute ?? ""] : [t.attribute ?? ""];
  return (
    <details>
      <summary>{t.table_id} <StatusBadge status={t.weighted_status} /> <StatusBadge status={t.record_status} />
        <span className="small muted"> · max |error| weighted {fmtPp(t.summary?.max_abs_pp_error_weighted)} · records {fmtPp(t.summary?.max_abs_pp_error_records)} · TVD records {t.summary?.tvd_records.toFixed(4)}</span></summary>
      <div className="details-body">
        {t.source ? <p className="small muted">Source {t.source.source_ids.join(", ")} · {t.source.geo_level} {t.source.geo_code} · year {t.source.year} · universe: {t.source.universe_note}
          {t.source_to_population_scale && Math.abs(t.source_to_population_scale - 1) > 1e-9 ? ` · scaled ×${t.source_to_population_scale.toFixed(4)} to the root universe` : ""}
          {t.evidence ? ` · evidence ${t.evidence}` : ""}</p> : <p className="small muted">{t.note}</p>}
        <div className="table-wrap"><table><caption>Shares are within each parent group (e.g. marital status within sex); z is the record share's deviation in binomial standard errors (threshold {t.summary?.record_z_threshold.toFixed(2)}).</caption>
          <thead><tr><th>Cell</th><th className="num">Source count</th><th className="num">Synthetic (weighted)</th><th className="num">Source share</th><th className="num">Synthetic share</th>
            <th className="num">Difference</th><th className="num">Records</th><th className="num">Record share</th><th className="num">z</th></tr></thead>
          <tbody>{t.cells.map((c) => (
            <tr key={c.cell.join("|")}><th>{c.cell.map((v, i) => label(dims[i] ?? "", v)).join(" · ")}</th><td className="num">{fmtInt(c.source_count)}</td>
              <td className="num">{fmtInt(c.synthetic_weighted_count)}</td><td className="num">{fmtPct(c.source_share, 2)}</td><td className="num">{fmtPct(c.synthetic_share, 2)}</td>
              <td className="num">{fmtPp(c.pp_error, 3)}</td><td className="num">{fmtInt(c.synthetic_records)}</td><td className="num">{fmtPct(c.record_share, 2)}</td>
              <td className="num">{c.record_z === null ? "–" : c.record_z.toFixed(2)}</td></tr>))}</tbody></table></div>
      </div>
    </details>
  );
}

function Validation({ populationId }: { populationId: string }) {
  const [province, setProvince] = useState("");
  const labels = useLabels();
  const report = useApi(`v2:val:${populationId}`, (signal) => v2<ValidationReport>(`/populations/${populationId}/validation`, { signal }));
  if (report.error) return <ErrorState error={report.error} onRetry={report.reload} what="validation" />;
  if (!report.data) return <Loading what="validation report" />;
  const r = report.data;
  const scopes = province ? r.provinces.filter((p) => p.province_code === province) : [];
  return (
    <div className="stack">
      <Notice tone="info" title="Source-fit validation only.">{r.statement}</Notice>
      <div className="tiles">
        <StatTile label="Constraint violations" value={fmtInt(r.constraint_violations)} sub="Target: zero (any violation is a generator bug)" />
        <StatTile label="Provinces validated" value={`${r.national.province_count} / ${r.national.province_reference_count}`} sub="Provinces with records" />
        <StatTile label="Weight CV" value={r.weights.cv.toFixed(3)} sub={`Kish design effect ${r.weights.kish_design_effect.toFixed(3)}`} />
        <StatTile label="Method" value={r.method_version} />
      </div>
      <div className="field" style={{ maxWidth: 320 }}><label htmlFor="val-scope">Scope</label>
        <select id="val-scope" value={province} onChange={(e) => setProvince(e.target.value)}>
          <option value="">Türkiye (covered provinces combined)</option>
          {r.provinces.map((p) => <option key={p.province_code} value={p.province_code}>{p.province_name}</option>)}
        </select></div>
      {!province ? (
        <section className="card stack" aria-labelledby="nat-h"><h2 id="nat-h">Covered provinces combined</h2>
          {r.national.tables.map((t) => <TableCard key={t.table_id} t={t} label={labels} />)}</section>
      ) : scopes.map((s) => (
        <section key={s.province_code} className="card stack" aria-labelledby={`p-${s.province_code}`}>
          <h2 id={`p-${s.province_code}`}>{s.province_name} · {fmtInt(s.records)} records</h2>
          {s.tables.map((t) => <TableCard key={t.table_id} t={t} label={labels} />)}
          {s.fields_without_source.length ? <p className="small muted">Not validated (no source table): {s.fields_without_source.map((f) => f.field).join(", ")}.</p> : null}
          {s.cross_source_checks.length ? <div className="table-wrap"><table><caption>Cross-source checks</caption><thead><tr><th>Check</th><th className="num">Root table</th><th className="num">Other source</th><th>Result</th></tr></thead>
            <tbody>{s.cross_source_checks.map((c) => <tr key={c.name}><th>{c.name}<div className="small muted">{c.detail}</div></th><td className="num">{fmtInt(c.root_table)}</td><td className="num">{fmtInt(c.context)}</td>
              <td>{c.passed ? <Badge tone="good" glyph="✓">Agree</Badge> : <Badge tone="crit" glyph="×">Differ by {fmtInt(c.difference)}</Badge>}</td></tr>)}</tbody></table></div> : null}
        </section>
      ))}
      <section className="card" aria-labelledby="con-h"><h2 id="con-h">Logical constraints</h2>
        <div className="table-wrap"><table><caption>Every rule runs on every record</caption><thead><tr><th>Rule</th><th>Description</th><th className="num">Checked</th><th className="num">Violations</th></tr></thead>
          <tbody>{r.constraints.map((c) => <tr key={c.rule_id}><th><code>{c.rule_id}</code></th><td className="small">{c.description}</td><td className="num">{fmtInt(c.checked)}</td>
            <td className="num">{c.violations ? <Badge tone="crit">{fmtInt(c.violations)}</Badge> : "0"}</td></tr>)}</tbody></table></div></section>
      <section className="card" aria-labelledby="tol-h"><h2 id="tol-h">Configured tolerances and methodology</h2>
        <dl className="kv">{Object.entries(r.tolerances).map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt><code>{k}</code> = {String(v)}</dt><dd className="small">{r.tolerance_justification[k]}</dd></div>)}</dl>
        <p className="small muted">Not validated here: {r.not_validated.join(" ")}</p>
      </section>
    </div>
  );
}

export default function ValidationPage() {
  return (
    <>
      <PageHeader title="Validation">Does the synthetic population reproduce the official tables it was generated from? Weighted fit and record-level fit are reported separately.</PageHeader>
      <PopulationGate what="validation">{(id) => <Validation populationId={id} />}</PopulationGate>
    </>
  );
}
