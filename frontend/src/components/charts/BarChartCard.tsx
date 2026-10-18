"use client";

import { useId, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useChartTokens } from "./useChartTokens";

export type ChartSeries = { key: string; label: string; slot: "series-1" | "series-2" };
export type ChartRow = { category: string; label: string; values: Record<string, number | null> };

type Props = {
  orientation?: "rows" | "columns";
  title: string;
  subtitle?: string;
  rows: ChartRow[];
  series: ChartSeries[];
  valueLabel: string;
  format: (value: number | null) => string;
  tableExtra?: { header: string; render: (row: ChartRow) => React.ReactNode }[];
};

type TooltipPayload = { dataKey?: string | number; value?: number; color?: string; name?: string };

function ChartTooltip({ active, payload, label, series, format }: {
  active?: boolean; payload?: TooltipPayload[]; label?: string; series: ChartSeries[]; format: Props["format"];
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="muted small">{label}</div>
      {series.map((s) => {
        const entry = payload.find((p) => p.dataKey === s.key);
        return (
          <div className="tt-row" key={s.key}>
            <span className="tt-key" style={{ background: entry?.color }} aria-hidden="true" />
            <strong>{format(typeof entry?.value === "number" ? entry.value : null)}</strong>
            <span className="muted">{s.label}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Horizontal bars (thin, rounded data end, 2px gap) with a legend for 2+ series and a table-view twin. */
export function BarChartCard({ title, subtitle, rows, series, valueLabel, format, tableExtra = [], orientation = "rows" }: Props) {
  const tokens = useChartTokens();
  const [asTable, setAsTable] = useState(false);
  const id = useId();
  const data = rows.map((r) => ({ label: r.label, ...Object.fromEntries(series.map((s) => [s.key, r.values[s.key] ?? 0])) }));
  const barSize = series.length > 1 ? 9 : 14;
  const columns = orientation === "columns";
  const height = columns ? 230 : Math.max(120, rows.length * (series.length * (barSize + 2) + 10) + 44);
  const longest = Math.max(...rows.map((r) => r.label.length), 4);
  const summary = `${title}. ${rows.length} categories, ${series.map((s) => s.label).join(" and ")}. Use the table view for exact values.`;

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
      {series.length > 1 ? (
        <div className="legend" aria-label="Legend">
          {series.map((s) => (
            <span key={s.key}><span className="legend-key" style={{ background: tokens[s.slot] }} aria-hidden="true" />{s.label}</span>
          ))}
        </div>
      ) : null}
      <div id={`${id}-body`}>
        {asTable ? (
          <div className="table-wrap">
            <table>
              <caption>{title} ({valueLabel})</caption>
              <thead>
                <tr>
                  <th scope="col">Category</th>
                  {series.map((s) => <th scope="col" className="num" key={s.key}>{s.label}</th>)}
                  {tableExtra.map((e) => <th scope="col" key={e.header}>{e.header}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.category}>
                    <th scope="row">{r.label}</th>
                    {series.map((s) => <td className="num" key={s.key}>{format(r.values[s.key] ?? null)}</td>)}
                    {tableExtra.map((e) => <td key={e.header}>{e.render(r)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="chart-box" role="group" aria-label={summary} style={{ height }}>
            <ResponsiveContainer width="100%" height={height} minWidth={0} initialDimension={{ width: 600, height }}>
              <BarChart data={data} layout={columns ? "horizontal" : "vertical"} margin={{ top: 4, right: 12, bottom: columns ? 20 : 4, left: 4 }} barGap={columns ? 0 : 2} barCategoryGap={columns ? "22%" : 8}>
                <CartesianGrid horizontal={columns} vertical={!columns} stroke={tokens.grid} />
                {columns ? <><XAxis type="category" dataKey="label" interval={0} angle={-45} textAnchor="end" tick={{fill:tokens["text-muted"],fontSize:9}} axisLine={{stroke:tokens.axis}} tickLine={false}/><YAxis type="number" width={30} tick={{fill:tokens["text-muted"],fontSize:10}} axisLine={false} tickLine={false}/></> : <><XAxis type="number" tickFormatter={(v: number) => format(v)} tick={{ fill: tokens["text-muted"], fontSize: 12 }} axisLine={{ stroke: tokens.axis }} tickLine={false} allowDecimals={false} /><YAxis type="category" dataKey="label" width={Math.min(170, 8 + longest * 7)} interval={0} tick={{ fill: tokens["text-secondary"], fontSize: 12 }} axisLine={{ stroke: tokens.axis }} tickLine={false} /></>}
                <Tooltip cursor={{ fill: tokens["surface-2"] }}
                  content={(props) => <ChartTooltip {...(props as object)} series={series} format={format} />} />
                {series.map((s) => (
                  <Bar key={s.key} stackId={columns ? "residents" : undefined} dataKey={s.key} name={s.label} fill={tokens[s.slot]} radius={columns ? [3,3,0,0] : [0,4,4,0]} barSize={columns ? undefined : barSize} isAnimationActive={false} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </figure>
  );
}
