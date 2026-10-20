"use client";

import { useId, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useChartTokens } from "./useChartTokens";

export type DivergingRow = { category: string; label: string; value: number | null; detail?: string };

type ShapeProps = { x?: number; y?: number; width?: number; height?: number; fill?: string; value?: number | [number, number] };

function RoundedEnd(props: ShapeProps) {
  const { y = 0, height = 0, fill } = props;
  const left = Math.min(props.x ?? 0, (props.x ?? 0) + (props.width ?? 0));
  const width = Math.abs(props.width ?? 0);
  if (width < 0.5) return null;
  const raw = Array.isArray(props.value) ? props.value[1] - props.value[0] : props.value ?? 0;
  const r = Math.min(4, width, height / 2);
  // Round only the data end (away from the zero baseline); the baseline end stays square.
  const d = raw >= 0
    ? `M${left},${y} h${width - r} q${r},0 ${r},${r} v${height - 2 * r} q0,${r} ${-r},${r} h${-(width - r)} z`
    : `M${left + width},${y} h${-(width - r)} q${-r},0 ${-r},${r} v${height - 2 * r} q0,${r} ${r},${r} h${width - r} z`;
  return <path d={d} fill={fill} />;
}

/** Differences from a reference (percentage points): two opposite hues and a neutral zero line, plus a table twin. */
export function DivergingBars({ title, subtitle, rows, positiveLabel, negativeLabel, format }: {
  title: string; subtitle?: string; rows: DivergingRow[]; positiveLabel: string; negativeLabel: string; format: (v: number | null) => string;
}) {
  const tokens = useChartTokens();
  const [asTable, setAsTable] = useState(false);
  const id = useId();
  const extent = Math.max(0.5, ...rows.map((r) => Math.abs(r.value ?? 0)));
  const domain: [number, number] = [-Math.ceil(extent), Math.ceil(extent)];
  const data = rows.map((r) => ({ label: r.label, value: r.value ?? 0 }));
  const height = Math.max(120, rows.length * 22 + 44);
  const longest = Math.max(...rows.map((r) => r.label.length), 4);

  return (
    <figure className="chart-figure" aria-labelledby={`${id}-title`}>
      <figcaption>
        <span>
          <span className="chart-title" id={`${id}-title`}>{title}</span>
          {subtitle ? <span className="muted small"> · {subtitle}</span> : null}
        </span>
        <button type="button" className="button small" aria-pressed={asTable} aria-controls={`${id}-body`} onClick={() => setAsTable((v) => !v)}>
          {asTable ? "Show chart" : "Show table"}
        </button>
      </figcaption>
      <div className="legend" aria-label="Legend">
        <span><span className="legend-key" style={{ background: tokens["div-pos"] }} aria-hidden="true" />{positiveLabel}</span>
        <span><span className="legend-key" style={{ background: tokens["div-neg"] }} aria-hidden="true" />{negativeLabel}</span>
      </div>
      <div id={`${id}-body`}>
        {asTable ? (
          <div className="table-wrap">
            <table>
              <caption>{title}</caption>
              <thead><tr><th scope="col">Category</th><th scope="col" className="num">Difference</th><th scope="col">Detail</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.category}><th scope="row">{r.label}</th><td className="num">{format(r.value)}</td><td className="small">{r.detail ?? ""}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="chart-box" role="group" aria-label={`${title}. ${rows.length} categories. Use the table view for exact values.`} style={{ height }}>
            <ResponsiveContainer width="100%" height={height} minWidth={0} initialDimension={{ width: 600, height }}>
              <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 4 }} barCategoryGap={6}>
                <CartesianGrid horizontal={false} stroke={tokens.grid} />
                <XAxis type="number" domain={domain} tickFormatter={(v: number) => format(v)} tick={{ fill: tokens["text-muted"], fontSize: 12 }}
                  axisLine={{ stroke: tokens.axis }} tickLine={false} />
                <YAxis type="category" dataKey="label" width={Math.min(170, 8 + longest * 7)} interval={0}
                  tick={{ fill: tokens["text-secondary"], fontSize: 12 }} axisLine={false} tickLine={false} />
                <ReferenceLine x={0} stroke={tokens.axis} />
                <Tooltip cursor={{ fill: tokens["surface-2"] }}
                  content={(props) => {
                    const p = props as unknown as { active?: boolean; payload?: readonly { value?: number }[]; label?: string };
                    if (!p.active || !p.payload?.length) return null;
                    const row = rows.find((r) => r.label === p.label);
                    return (
                      <div className="chart-tooltip">
                        <div className="muted small">{p.label}</div>
                        <strong>{format(row?.value ?? null)}</strong>
                        {row?.detail ? <div className="small muted">{row.detail}</div> : null}
                      </div>
                    );
                  }} />
                <Bar dataKey="value" barSize={12} isAnimationActive={false} shape={(props: unknown) => <RoundedEnd {...(props as ShapeProps)} />}>
                  {data.map((d) => <Cell key={d.label} fill={d.value >= 0 ? tokens["div-pos"] : tokens["div-neg"]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </figure>
  );
}
