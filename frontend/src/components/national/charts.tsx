"use client";

import { useId, useState } from "react";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Distribution, OptionShare, PyramidRow } from "@/lib/api/v2";
import { fmtInt, fmtPct } from "@/lib/format";
import { BarChartCard } from "../charts/BarChartCard";
import { useChartTokens } from "../charts/useChartTokens";

/** Weighted share (population estimate) next to the unweighted record share; unavailable fields say why. */
export function DistributionChart({ dist, title, label }: { dist: Distribution; title: string; label: (code: string) => string }) {
  if (!dist.available) {
    return (
      <div className="unavailable-box" role="note">
        <h3>{title}</h3>
        <p>{dist.note ?? "Not available for this selection."}</p>
      </div>
    );
  }
  const shown = dist.categories.filter((c) => c.records > 0 || (c.value !== "unavailable" && c.value !== "not_applicable"));
  const rows = shown.map((c) => ({ category: c.value, label: label(c.value), values: { weighted: c.weighted_share, records: c.record_share } }));
  const outside = dist.categories.filter((c) => c.value === "not_applicable" || c.value === "unavailable").filter((c) => c.records > 0);
  return (
    <div className="stack">
      <BarChartCard title={title} subtitle={`${fmtInt(dist.records)} records`} rows={rows} valueLabel="share"
        series={[{ key: "weighted", label: "Weighted (population estimate)", slot: "series-1" }, { key: "records", label: "Record share", slot: "series-2" }]}
        format={(v) => fmtPct(v, 1)} share />
      {outside.length ? <p className="small muted">{outside.map((c) => `${c.label}: ${fmtInt(c.records)} records (${fmtPct(c.weighted_share)} weighted)`).join(" · ")}.
        Not applicable = outside the source table's universe; not available = no source table for that province.</p> : null}
    </div>
  );
}

export function PopulationPyramid({ rows, weighted = true }: { rows: PyramidRow[]; weighted?: boolean }) {
  const tokens = useChartTokens();
  const id = useId();
  const [table, setTable] = useState(false);
  const data = [...rows].reverse().map((r) => ({ age: r.age_group, male: -(weighted ? r.male_weighted : r.male_records), female: weighted ? r.female_weighted : r.female_records }));
  const raw = Math.max(1, ...data.map((d) => Math.max(-d.male, d.female)));
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((st) => st * 2 >= raw) ?? raw;
  const max = step * 2;
  const ticks = [-max, -step, 0, step, max];
  const fmt = (v: number) => (weighted ? fmtInt(Math.abs(v)) : fmtInt(Math.abs(v)));
  return (
    <figure className="chart-figure" aria-labelledby={`${id}-t`}>
      <figcaption>
        <span><span className="chart-title" id={`${id}-t`}>Age and sex</span><span className="muted small"> · {weighted ? "weighted residents represented" : "records"}</span></span>
        <button type="button" className="button small" aria-pressed={table} onClick={() => setTable(!table)}>{table ? "Show chart" : "Show table"}</button>
      </figcaption>
      <div className="legend"><span><i className="legend-key" style={{ background: tokens["series-1"] }} />Male</span><span><i className="legend-key" style={{ background: tokens["series-2"] }} />Female</span></div>
      {table ? (
        <div className="table-wrap"><table><caption>Age group by sex</caption><thead><tr><th>Age group</th><th className="num">Male</th><th className="num">Female</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.age_group}><th>{r.age_group}</th><td className="num">{fmtInt(weighted ? r.male_weighted : r.male_records)}</td>
            <td className="num">{fmtInt(weighted ? r.female_weighted : r.female_records)}</td></tr>)}</tbody></table></div>
      ) : (
        <div className="chart-box" style={{ height: 360 }} role="img" aria-label="Population pyramid by five-year age group and sex. Use the table view for values.">
          <ResponsiveContainer width="100%" height={360} minWidth={0} initialDimension={{ width: 600, height: 360 }}>
            <BarChart data={data} layout="vertical" stackOffset="sign" margin={{ top: 4, right: 12, bottom: 4, left: 4 }} barCategoryGap={1}>
              <CartesianGrid vertical horizontal={false} stroke={tokens.grid} />
              <XAxis type="number" domain={[-max, max]} ticks={ticks} tickFormatter={fmt} tick={{ fill: tokens["text-muted"], fontSize: 10 }} axisLine={{ stroke: tokens.axis }} tickLine={false} />
              <YAxis type="category" dataKey="age" width={44} tick={{ fill: tokens["text-secondary"], fontSize: 10 }} axisLine={false} tickLine={false} interval={0} />
              <ReferenceLine x={0} stroke={tokens.axis} />
              <Tooltip formatter={(v) => fmt(Number(v))} contentStyle={{ background: "#14232f", border: "1px solid #344b61", fontSize: 11 }} />
              <Bar dataKey="male" name="Male" stackId="p" fill={tokens["series-1"]} isAnimationActive={false} />
              <Bar dataKey="female" name="Female" stackId="p" fill={tokens["series-2"]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}

/** Response shares with approximate 95% intervals drawn as brackets; values always shown as text too. */
export function ShareBars({ options, labels, caption }: { options: OptionShare[]; labels: Record<string, string>; caption: string }) {
  return (
    <div className="stack" role="table" aria-label={caption}>
      {options.map((o) => (
        <div className="share-bar" role="row" key={o.option_id}>
          <span role="rowheader">{labels[o.option_id] ?? o.option_id}</span>
          <span className="track" role="cell" aria-hidden="true">
            <span className="fill" style={{ width: `${(o.weighted_share ?? 0) * 100}%` }} />
            {o.ci95 ? <span className="ci" style={{ left: `${o.ci95[0] * 100}%`, width: `${(o.ci95[1] - o.ci95[0]) * 100}%` }} /> : null}
          </span>
          <span role="cell" className="small">{fmtPct(o.weighted_share)}{o.ci95 ? ` (${fmtPct(o.ci95[0], 0)}–${fmtPct(o.ci95[1], 0)})` : ""} · n={o.responses}</span>
        </div>
      ))}
    </div>
  );
}
