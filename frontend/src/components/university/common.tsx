"use client";

import { useState } from "react";
import { countBySeverity, ISSUE_LABELS } from "@/lib/university/quality";
import type { DataOrigin, Finding, IssueSeverity, MissingReason } from "@/lib/university/types";
import { MISSING_DESCRIPTIONS, MISSING_LABELS } from "@/lib/university/util";
import { fmtInt } from "@/lib/format";
import { StatTile } from "../StatTile";
import { Badge } from "../StatusBadge";

/** An explicit missing state. Never rendered as zero. */
export function Missing({ reason = "not_available" }: { reason?: MissingReason }) {
  return <span className="missing" title={MISSING_DESCRIPTIONS[reason]}>{MISSING_LABELS[reason]}</span>;
}

/** Renders `value` (formatted) or an explicit missing state. Zero is a value. */
export function Value<T>({ value, reason = "missing_from_source", format }: { value: T | null | undefined; reason?: MissingReason; format?: (v: T) => React.ReactNode }) {
  if (value === null || value === undefined || (typeof value === "string" && value === "")) return <Missing reason={reason} />;
  return <>{format ? format(value) : String(value)}</>;
}

export function SourceBadge({ origin }: { origin: DataOrigin }) {
  return origin === "fixture"
    ? <Badge tone="fake" glyph="◇" title="Synthetic fixture data generated in the frontend; not from any source workbook or backend.">Fixture data</Badge>
    : <Badge tone="info" glyph="◆" title="Returned by the SocietyTwin API.">API data</Badge>;
}

const KIND = {
  registry: { tone: "neutral" as const, glyph: "⧉", label: "Historical registry data", title: "Observed values from the registry snapshot (reported quotas, placed counts, success ranks). Not simulation output." },
  simulation: { tone: "info" as const, glyph: "▸", label: "Simulated result", title: "Output of a simulation run, not observed admissions." },
  synthetic: { tone: "fake" as const, glyph: "◇", label: "Synthetic candidates", title: "Fictional applicants; not real students, scores or ranks." },
  derived: { tone: "neutral" as const, glyph: "ƒ", label: "Derived", title: "Calculated in the UI from the values shown; not stored in the source." },
};

export function DataKindBadge({ kind }: { kind: keyof typeof KIND }) {
  const k = KIND[kind];
  return <Badge tone={k.tone} glyph={k.glyph} title={k.title}>{k.label}</Badge>;
}

const SEVERITY: Record<IssueSeverity, { tone: "crit" | "warn" | "info"; glyph: string; label: string }> = {
  error: { tone: "crit", glyph: "×", label: "Error" },
  warning: { tone: "warn", glyph: "!", label: "Warning" },
  info: { tone: "info", glyph: "i", label: "Info" },
};

const ORIGIN_LABELS: Record<Finding["origin"], string> = {
  source_import: "Registry importer",
  frontend_check: "Dashboard check",
  simulation: "Simulation",
  scenario_validation: "Scenario validation",
};

export function SeverityBadge({ severity, blocking }: { severity: IssueSeverity; blocking?: boolean }) {
  const s = SEVERITY[severity];
  return <Badge tone={s.tone} glyph={s.glyph}>{blocking ? "Blocking error" : s.label}</Badge>;
}

/**
 * Validation findings grouped by severity. Every finding is counted in the summary line; groups can be collapsed but
 * nothing is dropped. Blocking errors are listed first.
 */
export function ValidationList({ findings, title = "Validation", empty = "No validation findings.", initiallyOpen = true, limit }: {
  findings: Finding[]; title?: string; empty?: string; initiallyOpen?: boolean; limit?: number;
}) {
  const counts = countBySeverity(findings);
  const order: IssueSeverity[] = ["error", "warning", "info"];
  return (
    <section className="finding-list" aria-label={title}>
      <div className="row small" role="status">
        <strong>{title}</strong>
        <span>{counts.blocking ? `${fmtInt(counts.blocking)} blocking · ` : ""}{fmtInt(counts.error)} error{counts.error === 1 ? "" : "s"} · {fmtInt(counts.warning)} warning{counts.warning === 1 ? "" : "s"} · {fmtInt(counts.info)} info</span>
      </div>
      {findings.length === 0 ? <p className="small muted" style={{ margin: 0 }}>{empty}</p> : null}
      {order.map((sev) => {
        const items = findings.filter((f) => f.severity === sev).sort((a, b) => Number(b.blocking) - Number(a.blocking));
        if (!items.length) return null;
        return <FindingGroup key={sev} severity={sev} items={items} open={initiallyOpen && (sev !== "info" || items.length <= 3)} limit={limit} />;
      })}
    </section>
  );
}

function FindingGroup({ severity, items, open, limit = 50 }: { severity: IssueSeverity; items: Finding[]; open: boolean; limit?: number }) {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? items : items.slice(0, limit);
  return (
    <details open={open}>
      <summary>{severity === "info" ? "Info" : `${SEVERITY[severity].label}s`} ({fmtInt(items.length)})</summary>
      <ul className="findings">
        {shown.map((f, i) => (
          <li key={`${f.code}:${f.record ?? ""}:${f.field ?? ""}:${i}`} className={`finding sev-${f.severity}`}>
            <div className="row small">
              <SeverityBadge severity={f.severity} blocking={f.blocking} />
              <span className="finding-code">{ISSUE_LABELS[f.code] ?? f.code}</span>
              {f.record ? <span className="muted">{f.record}{f.field ? ` · ${f.field}` : ""}</span> : null}
              <span className="muted finding-origin">{ORIGIN_LABELS[f.origin]}</span>
            </div>
            <div>{f.message}</div>
            {f.detail ? <div className="small muted finding-detail">{f.detail}</div> : null}
          </li>
        ))}
      </ul>
      {items.length > shown.length ? (
        <div className="details-body"><button type="button" className="button small" onClick={() => setShowAll(true)}>Show all {fmtInt(items.length)}</button></div>
      ) : null}
    </details>
  );
}

/** Reusable data-quality summary: what was loaded, how much is incomplete, and every warning and error. */
export function DataQualityPanel({ title = "Data quality", records, recordLabel = "Records loaded", incomplete, incompleteNote, findings, origin, source, version, open = false }: {
  title?: string; records: number; recordLabel?: string; incomplete: number; incompleteNote?: string; findings: Finding[]; origin: DataOrigin;
  source: string; version: string | null; open?: boolean;
}) {
  const counts = countBySeverity(findings);
  return (
    <section className="card stack data-quality" aria-label={title}>
      <div className="card-head"><h2>{title}</h2><SourceBadge origin={origin} /></div>
      <div className="tiles">
        <StatTile label={recordLabel} value={fmtInt(records)} />
        <StatTile label="Incomplete records" value={fmtInt(incomplete)} sub={incompleteNote} />
        <StatTile label="Warnings" value={fmtInt(counts.warning)} sub={counts.info ? `${fmtInt(counts.info)} info` : undefined} />
        <StatTile label="Errors" value={fmtInt(counts.error)} sub={counts.blocking ? `${fmtInt(counts.blocking)} blocking` : "none blocking"} />
        <StatTile label="Data source" value={<span className="tile-text">{source}</span>} sub={<>Version: {version ?? <Missing reason="not_available" />}</>} />
      </div>
      <details open={open}>
        <summary>Record-level findings ({fmtInt(findings.length)})</summary>
        <div className="details-body"><ValidationList findings={findings} title="Findings" initiallyOpen={false} /></div>
      </details>
    </section>
  );
}

export type ProvenanceItem = { label: string; value: React.ReactNode | null | undefined; missing?: MissingReason; mono?: boolean };

export function ProvenancePanel({ title = "Data provenance", items, origin, children }: { title?: string; items: ProvenanceItem[]; origin: DataOrigin; children?: React.ReactNode }) {
  return (
    <section className="card stack provenance" aria-label={title}>
      <div className="card-head"><h2>{title}</h2><SourceBadge origin={origin} /></div>
      <dl className="kv">
        {items.map((i) => (
          <div key={i.label} style={{ display: "contents" }}>
            <dt>{i.label}</dt>
            <dd>{i.value === null || i.value === undefined || i.value === "" ? <Missing reason={i.missing ?? "not_available"} /> : i.mono ? <code>{i.value}</code> : i.value}</dd>
          </div>
        ))}
      </dl>
      {children}
    </section>
  );
}

export function Pagination({ offset, limit, total, onPage, label }: { offset: number; limit: number; total: number; onPage: (page: number) => void; label: string }) {
  const page = Math.floor(offset / limit);
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <nav className="row pager" aria-label={`${label} pages`}>
      <span className="small muted">{total === 0 ? "No rows" : `Rows ${fmtInt(offset + 1)}–${fmtInt(Math.min(total, offset + limit))} of ${fmtInt(total)}`}</span>
      <span className="row">
        <button type="button" className="button small" disabled={page === 0} onClick={() => onPage(page - 1)}>Previous</button>
        <span className="small muted" aria-live="polite">Page {page + 1} of {pages}</span>
        <button type="button" className="button small" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </span>
    </nav>
  );
}

/** Frame for every chart: what the metric means, units, data origin, and an explicit empty state. */
export function ChartPanel({ title, explanation, units, origin, empty, emptyText = "No data for this selection.", axes, children, wide }: {
  title: string; explanation: React.ReactNode; units: string; origin: DataOrigin; empty: boolean; emptyText?: string;
  axes: { value: string; category: string }; children: React.ReactNode; wide?: boolean;
}) {
  return (
    <section className={`chart-panel${wide ? " wide" : ""}`} aria-label={title}>
      {empty ? (
        <div className="unavailable-box" role="note"><h3>{title}</h3><p>{emptyText}</p></div>
      ) : children}
      <p className="small muted chart-note">
        <span className="axis-note">Value axis: {axes.value}, in {units} · Category axis: {axes.category}.</span>{" "}
        {explanation}
      </p>
      <div className="row small"><SourceBadge origin={origin} />{origin === "fixture" ? <span className="muted">Fixture result: illustrative, not a forecast or official outcome.</span> : null}</div>
    </section>
  );
}

export function SortHeader<K extends string>({ label, sortKey, current, direction, onSort, numeric }: {
  label: string; sortKey: K; current: K; direction: "asc" | "desc"; onSort: (key: K) => void; numeric?: boolean;
}) {
  const active = current === sortKey;
  return (
    <th scope="col" className={numeric ? "num" : undefined} aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort-button" onClick={() => onSort(sortKey)}>
        {label}{active ? (direction === "asc" ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
}
