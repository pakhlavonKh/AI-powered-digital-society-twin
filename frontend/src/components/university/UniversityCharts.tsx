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
import type { UniversitySweepResponse, UniversityTrajectoryPoint } from "@/lib/api/v2";
import { useChartTokens } from "@/components/charts/useChartTokens";

type TooltipEntry = { dataKey?: string | number; value?: number; color?: string; name?: string };

function TrajectoryTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="muted small">Semester {label}</div>
      {payload.map((entry) => (
        <div className="tt-row" key={String(entry.dataKey)}>
          <span className="tt-key" style={{ background: entry.color }} aria-hidden="true" />
          <strong>{typeof entry.value === "number" ? entry.value.toFixed(1) : "—"}</strong>
          <span className="muted">{entry.name}</span>
        </div>
      ))}
    </div>
  );
}

export function RetentionTrajectoryChart({
  baseline,
  policy,
}: {
  baseline: UniversityTrajectoryPoint[];
  policy: UniversityTrajectoryPoint[];
}) {
  const tokens = useChartTokens();
  const [asTable, setAsTable] = useState(false);
  const id = useId();

  const rows = baseline.map((b, i) => {
    const p = policy[i];
    return {
      semester: b.semester,
      baselineActive: b.mean_active_students,
      policyActive: p?.mean_active_students ?? b.mean_active_students,
      baselineRetPct: Number((b.mean_retention_rate * 100).toFixed(2)),
      policyRetPct: Number(((p?.mean_retention_rate ?? b.mean_retention_rate) * 100).toFixed(2)),
      policyPaused: p?.mean_paused_stop_out ?? b.mean_paused_stop_out,
      policyWithdrawn: p?.mean_withdrawn_dropout ?? b.mean_withdrawn_dropout,
    };
  });

  return (
    <figure className="chart-figure" aria-labelledby={`${id}-title`}>
      <figcaption>
        <span>
          <span className="chart-title" id={`${id}-title`}>Multi-Semester Active Student Trajectory (CRN Mean)</span>
          <span className="muted small"> · Baseline vs Policy</span>
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
        <span><span className="legend-key" style={{ background: tokens["series-1"] }} aria-hidden="true" />Baseline Active</span>
        <span><span className="legend-key" style={{ background: tokens["series-2"] }} aria-hidden="true" />Policy Active</span>
      </div>
      <div id={`${id}-body`}>
        {asTable ? (
          <div className="table-wrap">
            <table>
              <caption>Semester trajectory comparison</caption>
              <thead>
                <tr>
                  <th scope="col">Term</th>
                  <th scope="col" className="num">Baseline Active</th>
                  <th scope="col" className="num">Policy Active</th>
                  <th scope="col" className="num">Policy Stop-Out</th>
                  <th scope="col" className="num">Policy Dropout</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.semester}>
                    <td>Term {r.semester}</td>
                    <td className="num">{r.baselineActive.toFixed(1)}</td>
                    <td className="num">{r.policyActive.toFixed(1)}</td>
                    <td className="num">{r.policyPaused.toFixed(1)}</td>
                    <td className="num">{r.policyWithdrawn.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={rows} margin={{ top: 10, right: 16, left: 4, bottom: 8 }}>
                <CartesianGrid stroke={tokens.grid} strokeDasharray="3 3" />
                <XAxis dataKey="semester" stroke={tokens.axis} tick={{ fill: tokens["text-secondary"], fontSize: 12 }} />
                <YAxis stroke={tokens.axis} tick={{ fill: tokens["text-secondary"], fontSize: 12 }} />
                <Tooltip content={<TrajectoryTooltip />} />
                <Line
                  type="monotone"
                  dataKey="baselineActive"
                  name="Baseline Active"
                  stroke={tokens["series-1"]}
                  strokeWidth={2.2}
                  dot={{ r: 3 }}
                />
                <Line
                  type="monotone"
                  dataKey="policyActive"
                  name="Policy Active"
                  stroke={tokens["series-2"]}
                  strokeWidth={2.2}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </figure>
  );
}

export function TuitionSweepChart({ rows }: { rows: UniversitySweepResponse["rows"] }) {
  const tokens = useChartTokens();
  const [asTable, setAsTable] = useState(false);
  const id = useId();

  const data = rows.map((r) => ({
    tuition: `${r.tuition_change_pct}%`,
    retentionPct: Number((r.mean_retention_rate * 100).toFixed(2)),
    dropout: r.mean_withdrawn_dropout,
    netRevenueM: Number((r.mean_net_tuition_revenue / 1_000_000).toFixed(2)),
  }));

  return (
    <figure className="chart-figure" aria-labelledby={`${id}-title`}>
      <figcaption>
        <span>
          <span className="chart-title" id={`${id}-title`}>Tuition Sensitivity Sweep (Retention % vs Tuition Increase)</span>
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
      <div id={`${id}-body`}>
        {asTable ? (
          <div className="table-wrap">
            <table>
              <caption>Tuition sensitivity curve</caption>
              <thead>
                <tr>
                  <th scope="col">Tuition Δ</th>
                  <th scope="col" className="num">Retention (%)</th>
                  <th scope="col" className="num">Mean Dropout</th>
                  <th scope="col" className="num">Net Revenue (M TL)</th>
                </tr>
              </thead>
              <tbody>
                {data.map((r) => (
                  <tr key={r.tuition}>
                    <td>{r.tuition}</td>
                    <td className="num">{r.retentionPct.toFixed(2)}%</td>
                    <td className="num">{r.dropout.toFixed(1)}</td>
                    <td className="num">{r.netRevenueM.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <LineChart data={data} margin={{ top: 10, right: 16, left: 4, bottom: 8 }}>
                <CartesianGrid stroke={tokens.grid} strokeDasharray="3 3" />
                <XAxis dataKey="tuition" stroke={tokens.axis} tick={{ fill: tokens["text-secondary"], fontSize: 12 }} />
                <YAxis stroke={tokens.axis} domain={["auto", "auto"]} tick={{ fill: tokens["text-secondary"], fontSize: 12 }} />
                <Tooltip content={<TrajectoryTooltip />} />
                <Line
                  type="monotone"
                  dataKey="retentionPct"
                  name="Retention (%)"
                  stroke={tokens["series-1"]}
                  strokeWidth={2.4}
                  dot={{ r: 3.5 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </figure>
  );
}
