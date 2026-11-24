"use client";

import { useId, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BarChartCard, type ChartRow, type ChartSeries } from "@/components/charts/BarChartCard";
import { useChartTokens } from "@/components/charts/useChartTokens";
import { Notice } from "@/components/Notices";
import { StatTile } from "@/components/StatTile";
import { Badge } from "@/components/StatusBadge";
import { RetentionTrajectoryChart } from "@/components/university/UniversityCharts";
import type {
  UniversityQueryRunResponse,
  UniversityQueryStatisticsSection,
  UniversityTrajectoryPoint,
} from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";

function formatNumberOrDash(val: unknown, digits = 2): string {
  if (val === null || val === undefined || val === "") return "—";
  if (typeof val === "number") {
    if (!Number.isFinite(val)) return "—";
    return Number.isInteger(val) ? fmtInt(val) : val.toFixed(digits);
  }
  return String(val);
}

function GenericLineSection({ section }: { section: UniversityQueryStatisticsSection }) {
  const tokens = useChartTokens();
  const [asTable, setAsTable] = useState(false);
  const id = useId();
  const data = section.data ?? {};
  const baseTraj = data.baseline_trajectory as UniversityTrajectoryPoint[] | undefined;
  const polTraj = data.policy_trajectory as UniversityTrajectoryPoint[] | undefined;

  if (Array.isArray(baseTraj) && Array.isArray(polTraj) && baseTraj.length > 0) {
    return (
      <div className="stack">
        <RetentionTrajectoryChart baseline={baseTraj} policy={polTraj} />
        {section.caveat ? <p className="small muted">{section.caveat}</p> : null}
      </div>
    );
  }

  const xKey = String(data.x_key ?? "label");
  const series = (Array.isArray(data.series) ? data.series : []) as ChartSeries[];
  const rows = (Array.isArray(data.rows) ? data.rows : []) as Record<string, unknown>[];

  return (
    <figure className="chart-figure" aria-labelledby={`${id}-title`}>
      <figcaption>
        <span>
          <span className="chart-title" id={`${id}-title`}>{section.title}</span>
          {section.unit ? <span className="muted small"> · {section.unit}</span> : null}
        </span>
        <button
          type="button"
          className="button small"
          aria-pressed={asTable}
          aria-controls={`${id}-body`}
          onClick={() => setAsTable((v) => !v)}
        >
          {asTable ? "Show chart" : "Show table"}
        </button>
      </figcaption>
      <div className="legend" aria-label="Legend">
        {series.map((s) => (
          <span key={s.key}>
            <span className="legend-key" style={{ background: tokens[s.slot] ?? tokens["series-1"] }} aria-hidden="true" />
            {s.label}
          </span>
        ))}
      </div>
      <div id={`${id}-body`}>
        {asTable ? (
          <table className="table">
            <thead>
              <tr>
                <th>{String(data.x_label ?? xKey)}</th>
                {series.map((s) => (
                  <th key={s.key} className="num">{s.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={String(r[xKey] ?? idx)}>
                  <td>{String(r[xKey] ?? idx)}</td>
                  {series.map((s) => (
                    <td key={s.key} className="num">{formatNumberOrDash(r[s.key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                <CartesianGrid stroke={tokens.grid} strokeDasharray="3 3" />
                <XAxis dataKey={xKey} tick={{ fill: tokens.axis, fontSize: 12 }} />
                <YAxis tick={{ fill: tokens.axis, fontSize: 12 }} />
                <Tooltip />
                {series.map((s) => (
                  <Line
                    key={s.key}
                    type="monotone"
                    dataKey={s.key}
                    name={s.label}
                    stroke={tokens[s.slot]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
      {section.caveat ? <p className="small muted">{section.caveat}</p> : null}
    </figure>
  );
}

function renderSection(sec: UniversityQueryStatisticsSection) {
  const data = sec.data ?? {};

  if (sec.type === "tiles") {
    const items = (Array.isArray(data.items) ? data.items : []) as {
      label: string;
      value: string | number;
      sub?: string;
    }[];
    return (
      <section key={sec.id} className="card stack" aria-labelledby={`${sec.id}-h`}>
        <div className="card-head">
          <h3 id={`${sec.id}-h`}>{sec.title}</h3>
          {sec.unit ? <span className="small muted">{sec.unit}</span> : null}
        </div>
        <div className="tiles">
          {items.map((it) => (
            <StatTile key={it.label} label={it.label} value={String(it.value)} sub={it.sub} />
          ))}
        </div>
        {sec.caveat ? <p className="small muted">{sec.caveat}</p> : null}
      </section>
    );
  }

  if (sec.type === "table") {
    const columns = (Array.isArray(data.columns) ? data.columns : []) as string[];
    const rows = (Array.isArray(data.rows) ? data.rows : []) as (string | number | null)[][];
    return (
      <section key={sec.id} className="card stack" aria-labelledby={`${sec.id}-h`}>
        <div className="card-head">
          <h3 id={`${sec.id}-h`}>{sec.title}</h3>
          <span className="small muted">{fmtInt(rows.length)} rows</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((cell, ci) => (
                    <td key={ci}>{cell === null || cell === undefined ? "—" : String(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {sec.caveat ? <p className="small muted">{sec.caveat}</p> : null}
      </section>
    );
  }

  if (sec.type === "bar_series") {
    const series = (Array.isArray(data.series) ? data.series : []) as ChartSeries[];
    const rows = (Array.isArray(data.rows) ? data.rows : []) as ChartRow[];
    const valueLabel = String(data.value_label ?? "Count");
    return (
      <section key={sec.id} className="card stack">
        <BarChartCard
          title={sec.title}
          subtitle={sec.caveat ?? undefined}
          rows={rows}
          series={series}
          valueLabel={valueLabel}
          format={(v) => (v === null ? "—" : Number.isInteger(v) ? fmtInt(v) : v.toFixed(2))}
        />
      </section>
    );
  }

  if (sec.type === "line_series") {
    return (
      <section key={sec.id} className="card stack">
        <GenericLineSection section={sec} />
      </section>
    );
  }

  if (sec.type === "comparison_set") {
    const variants = (Array.isArray(data.variants) ? data.variants : []) as {
      variant_id: string;
      label: string;
      is_baseline?: boolean;
      listed_anywhere: number;
      listed_anywhere_delta?: number | null;
      fee_paying_listed?: number;
      listed_top_k: number;
      first_choice: number;
      placed: number;
      filled?: number;
      capacity?: number;
      mean_cutoff_score?: number | null;
      target_net_revenue?: number;
    }[];
    const hasFeeCol = variants.some((v) => v.fee_paying_listed !== undefined);
    return (
      <section key={sec.id} className="card stack" aria-labelledby={`${sec.id}-h`}>
        <div className="card-head">
          <h3 id={`${sec.id}-h`}>{sec.title}</h3>
          <span className="small muted">{fmtInt(variants.length)} variants</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Variant</th>
                <th className="num">Listed Anywhere</th>
                {hasFeeCol ? <th className="num">Fee-Paying</th> : null}
                <th className="num">Delta vs Baseline</th>
                <th className="num">Top-K</th>
                <th className="num">1st Choice</th>
                <th className="num">Placed</th>
                <th className="num">Filled / Cap</th>
                <th className="num">Mean Cutoff</th>
                <th className="num">Net Revenue (TL)</th>
              </tr>
            </thead>
            <tbody>
              {variants.map((v) => (
                <tr key={v.variant_id}>
                  <td>
                    <strong>{v.label}</strong>{" "}
                    {v.is_baseline ? <Badge tone="neutral">Baseline</Badge> : null}
                  </td>
                  <td className="num">{fmtInt(v.listed_anywhere)}</td>
                  {hasFeeCol ? (
                    <td className="num">
                      {v.fee_paying_listed !== undefined ? fmtInt(v.fee_paying_listed) : "—"}
                    </td>
                  ) : null}
                  <td className="num">
                    {v.listed_anywhere_delta === null || v.listed_anywhere_delta === undefined
                      ? "—"
                      : `${v.listed_anywhere_delta >= 0 ? "+" : ""}${fmtInt(v.listed_anywhere_delta)}`}
                  </td>
                  <td className="num">{fmtInt(v.listed_top_k)}</td>
                  <td className="num">{fmtInt(v.first_choice)}</td>
                  <td className="num">{fmtInt(v.placed)}</td>
                  <td className="num">
                    {v.filled !== undefined && v.capacity !== undefined
                      ? `${fmtInt(v.filled)} / ${fmtInt(v.capacity)}`
                      : "—"}
                  </td>
                  <td className="num">
                    {v.mean_cutoff_score !== null && v.mean_cutoff_score !== undefined
                      ? v.mean_cutoff_score.toFixed(2)
                      : "—"}
                  </td>
                  <td className="num">
                    {v.target_net_revenue !== undefined ? fmtInt(Math.round(v.target_net_revenue)) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {sec.caveat ? <p className="small muted">{sec.caveat}</p> : null}
      </section>
    );
  }

  if (sec.type === "flow_summary") {
    const rivals = (Array.isArray(data.top_rival_destinations) ? data.top_rival_destinations : []) as {
      university_id?: string;
      university_name: string;
      count: number;
    }[];
    const primaryRivals = (Array.isArray(data.top_primary_rival_destinations) ? data.top_primary_rival_destinations : []) as {
      university_name: string;
      count: number;
    }[];
    return (
      <section key={sec.id} className="card stack" aria-labelledby={`${sec.id}-h`}>
        <div className="card-head">
          <h3 id={`${sec.id}-h`}>{sec.title}</h3>
          <span className="small muted">Candidate application transitions</span>
        </div>
        <div className="tiles">
          <StatTile label="Stayed at Target" value={fmtInt(Number(data.stayed_at_target ?? 0))} />
          <StatTile label="Shifted Within Target" value={fmtInt(Number(data.shifted_within_target ?? 0))} />
          <StatTile
            label="Shifted to Fixed Rivals"
            value={fmtInt(Number(data.shifted_to_rival_uni ?? 0))}
            sub={
              Number(data.primary_or_placed_shifted_to_rival ?? 0) > 0
                ? `${fmtInt(Number(data.primary_or_placed_shifted_to_rival))} primary/placed choice shifts`
                : undefined
            }
          />
          <StatTile
            label="Dropped Out / Newly Attracted"
            value={`${fmtInt(Number(data.dropped_out_of_applying ?? 0))} / +${fmtInt(Number(data.newly_attracted ?? 0))}`}
          />
        </div>
        {rivals.length > 0 ? (
          <div className="stack" style={{ gap: 6 }}>
            <strong className="small">Top Fixed Rival Destinations</strong>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {rivals.map((r) => (
                <li key={r.university_id ?? r.university_name} className="small">
                  <strong>{r.university_name}</strong>: {fmtInt(r.count)} shifted applicants
                </li>
              ))}
            </ul>
          </div>
        ) : primaryRivals.length > 0 ? (
          <div className="stack" style={{ gap: 6 }}>
            <strong className="small">Top Fixed Rivals Gaining #1 / Admitted Choices</strong>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {primaryRivals.map((r) => (
                <li key={r.university_name} className="small">
                  <strong>{r.university_name}</strong>: {fmtInt(r.count)} candidates
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="small muted">No applicants shifted away to rival universities in this run.</p>
        )}
        {sec.caveat ? <p className="small muted">{sec.caveat}</p> : null}
      </section>
    );
  }

  return (
    <Notice key={sec.id} tone="info" title={sec.title}>
      {String(data.text ?? JSON.stringify(data))}
    </Notice>
  );
}

export function ExecutiveAnswerCard({ run }: { run: UniversityQueryRunResponse }) {
  const [showMarkdown, setShowMarkdown] = useState(false);
  const [copied, setCopied] = useState(false);
  const { summary } = run;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(summary.summary_markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard API may be unavailable in test environments
    }
  }

  return (
    <section
      className="card stack"
      aria-labelledby="uq-answer-h"
      style={{ borderLeft: "4px solid var(--accent, #2563eb)" }}
    >
      <div className="card-head">
        <div>
          <span className="eyebrow">Question-Specific Executive Summary</span>
          <h2 id="uq-answer-h">{summary.title}</h2>
          <p className="small muted">Question: &ldquo;{run.prompt}&rdquo;</p>
        </div>
        <div className="row" style={{ gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <Badge tone="info">{run.intent}</Badge>
          {run.focus_university_name ? <Badge tone="neutral">{run.focus_university_name}</Badge> : null}
          <Badge tone="warn">osym_verified: {String(run.osym_verified)}</Badge>
          <Badge tone="warn">coefficients_calibrated: {String(run.coefficients_calibrated)}</Badge>
          <Badge tone="neutral">Rivals fixed</Badge>
          <Badge tone="good">Source: {summary.generated_by}</Badge>
        </div>
      </div>

      <div className="panel stack" style={{ padding: 14 }}>
        <strong style={{ fontSize: "1.04rem" }}>{summary.headline}</strong>
        <p style={{ margin: 0 }}>{summary.direct_answer}</p>
      </div>

      {summary.key_findings.length > 0 ? (
        <div className="stack" style={{ gap: 6 }}>
          <strong className="small">Key Quantitative Findings</strong>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {summary.key_findings.map((kf, idx) => (
              <li key={idx} className="small">
                {kf}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <Notice tone="warn" title="Honest Epistemics &amp; Modeling Assumptions:">
        <ul style={{ margin: "6px 0 0 0", paddingLeft: 18 }}>
          {summary.caveats.map((c, idx) => (
            <li key={idx} className="small">
              {c}
            </li>
          ))}
        </ul>
      </Notice>

      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button
          type="button"
          className="button small"
          onClick={() => setShowMarkdown((v) => !v)}
        >
          {showMarkdown ? "Hide Markdown Report" : "View Full Markdown Report"}
        </button>
        <button type="button" className="button small" onClick={handleCopy}>
          {copied ? "Copied ✓" : "Copy Report"}
        </button>
        <span className="small muted">
          Run <code>{run.run_id}</code> · sha256: <code>{run.result_sha256.slice(0, 12)}…</code>
        </span>
      </div>

      {showMarkdown ? (
        <pre
          style={{
            margin: 0,
            padding: 12,
            background: "var(--surface-2, #f8fafc)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            whiteSpace: "pre-wrap",
            fontSize: "0.82rem",
          }}
        >
          {summary.summary_markdown}
        </pre>
      ) : null}
    </section>
  );
}

export function UniversityQueryStats({
  sections,
}: {
  sections: UniversityQueryStatisticsSection[];
}) {
  if (!sections || sections.length === 0) return null;
  return (
    <div className="stack" aria-label="Question-specific detailed statistics">
      {sections.map((sec) => renderSection(sec))}
    </div>
  );
}
