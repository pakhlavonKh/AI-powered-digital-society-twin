"use client";

import { useEffect, useRef, useState } from "react";
import { englishLabel, isTranslated, scoreTypeDisplay } from "@/lib/university/labels";
import { logoFor, type LogoAsset } from "@/lib/university/logos";
import { countBySeverity, ISSUE_LABELS } from "@/lib/university/quality";
import { MISSING_VALUE, type DataOrigin, type FacetValue, type Finding, type IssueSeverity, type MissingReason } from "@/lib/university/types";
import { MISSING_DESCRIPTIONS, MISSING_LABELS } from "@/lib/university/util";
import { fmtInt } from "@/lib/format";
import { Icon } from "../Icon";
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

/**
 * A Turkish source label (scholarship, institution type, teaching language) shown in English. The exact source
 * wording stays in the tooltip, or inline when `showSource` is set (detail views); the stored value is unchanged.
 */
export function SourceTerm({ value, reason = "missing_from_source", showSource = false }: { value: string | null | undefined; reason?: MissingReason; showSource?: boolean }) {
  if (value === null || value === undefined || value === "") return <Missing reason={reason} />;
  if (!isTranslated(value)) return <>{value}</>;
  return showSource
    ? <>{englishLabel(value)} <span className="muted small">(source label: {value})</span></>
    : <span title={`Source label: ${value}`}>{englishLabel(value)}</span>;
}

export function SourceBadge({ origin }: { origin: DataOrigin }) {
  if (origin === "local_preview") {
    return <Badge tone="warn" glyph="⌂" title="Read from the git-ignored ÖSYM 2025 Table 4 CSVs on this machine; development only; not committed or published; ÖSYM reuse permission pending.">Local preview data</Badge>;
  }
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
        <div className="details-body"><ValidationList findings={findings} title="Findings" /></div>
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

/** Page numbers to show: first, last, and a window around the current page; null marks a gap. */
function pageWindow(page: number, pages: number): (number | null)[] {
  const keep = new Set([0, pages - 1, page - 1, page, page + 1].filter((p) => p >= 0 && p < pages));
  const out: (number | null)[] = [];
  [...keep].sort((a, b) => a - b).forEach((p, i, all) => { if (i > 0 && p - all[i - 1] > 1) out.push(null); out.push(p); });
  return out;
}

/**
 * Pager. The explorers pass `pageSizes` and `onPageSize`, which add numbered pages and a rows-per-page choice; other
 * pages keep the compact Previous / Next form.
 */
export function Pagination({ offset, limit, total, onPage, label, pageSizes, onPageSize }: {
  offset: number; limit: number; total: number; onPage: (page: number) => void; label: string;
  pageSizes?: readonly number[]; onPageSize?: (size: number) => void;
}) {
  const page = Math.floor(offset / limit);
  const pages = Math.max(1, Math.ceil(total / limit));
  if (pageSizes && onPageSize) {
    return (
      <nav className="pager pager-numbered" aria-label={`${label} pages`}>
        <span className="small muted">{total === 0 ? "No rows" : `Showing ${fmtInt(offset + 1)}–${fmtInt(Math.min(total, offset + limit))} of ${fmtInt(total)}`}</span>
        <span className="pager-pages">
          <button type="button" className="button small pager-step" disabled={page === 0} onClick={() => onPage(page - 1)} aria-label="Previous page">‹</button>
          {pageWindow(page, pages).map((p, i) => p === null
            ? <span key={`gap-${i}`} className="pager-gap" aria-hidden="true">…</span>
            : <button key={p} type="button" className={`button small pager-num${p === page ? " is-current" : ""}`} aria-current={p === page ? "page" : undefined}
                aria-label={`Page ${p + 1}`} onClick={() => onPage(p)}>{fmtInt(p + 1)}</button>)}
          <button type="button" className="button small pager-step" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">›</button>
        </span>
        <label className="pager-size small">
          <span className="muted">Rows per page</span>
          <select value={limit} onChange={(e) => onPageSize(Number(e.target.value))}>
            {pageSizes.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </nav>
    );
  }
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

/** A score-type code in its official ÖSYM spelling (SAY, EA, SÖZ, DİL); the label as written stays in the tooltip. */
export function ScoreChip({ value }: { value: string | null | undefined }) {
  if (value === null || value === undefined || value === "") return <Missing reason="missing_from_source" />;
  const shown = scoreTypeDisplay(value);
  return <span className="badge score-chip" title={shown === value ? `Score type ${value}` : `Score type ${shown} (written ${value} in this data)`}>{shown}</span>;
}

/**
 * Multi-select filter as a compact dropdown: a summary button that opens a list of checkboxes with counts. Values
 * are the exact data values (URL state); `display` only changes what is shown. Closes on outside click or Escape.
 */
export function FilterMenu({ id, label, options, selected, onToggle, onClear, display, hint }: {
  id: string; label: string; options: FacetValue[]; selected: string[]; onToggle: (value: string) => void; onClear: () => void;
  display?: (label: string) => string; hint?: string;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  useEffect(() => {
    if (!open) return;
    // Keep the list on screen: menus near the right edge open towards the left.
    const pop = ref.current?.querySelector<HTMLElement>(".filter-pop");
    if (pop) setAlignRight(ref.current!.getBoundingClientRect().left + pop.offsetWidth > document.documentElement.clientWidth - 8);
    const close = (focus: boolean) => { if (ref.current) { ref.current.open = false; if (focus) ref.current.querySelector("summary")?.focus(); } };
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) close(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(true); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const shown = (o: FacetValue) => (o.value === MISSING_VALUE || !display ? o.label : display(o.label));
  const names = options.filter((o) => selected.includes(o.value)).map(shown);
  const summary = selected.length === 0 ? "All" : names.length && selected.length <= 2 ? names.join(", ") : `${selected.length} selected`;
  return (
    <div className="field toolbar-field">
      <span className="toolbar-label" id={`${id}-label`}>{label}</span>
      <details ref={ref} className={`filter-menu${selected.length ? " is-active" : ""}${alignRight ? " align-right" : ""}`} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary aria-label={`${label}: ${summary}`}><span className="filter-menu-value">{summary}</span><span className="filter-menu-caret" aria-hidden="true">▾</span></summary>
        <div className="filter-pop" role="group" aria-labelledby={`${id}-label`}>
          {options.length === 0 ? <p className="small muted" style={{ margin: 0 }}>No values in this data.</p> : null}
          {options.map((o) => {
            const text = shown(o);
            return (
              <label className="check" key={o.value} title={text !== o.label && o.value !== MISSING_VALUE ? `Source label: ${o.label}` : undefined}>
                <input type="checkbox" name={id} value={o.value} checked={selected.includes(o.value)} onChange={() => onToggle(o.value)} />
                <span className={o.value === MISSING_VALUE ? "missing" : undefined}>{text}</span> <span className="muted small">({fmtInt(o.count)})</span>
              </label>
            );
          })}
          {hint ? <p className="field-hint" style={{ margin: "4px 0 0" }}>{hint}</p> : null}
          {selected.length ? <button type="button" className="linkish small" onClick={onClear}>Clear {label.toLowerCase()}</button> : null}
        </div>
      </details>
    </div>
  );
}

/** Removable chips for the filters in force, so a combined filter is readable at a glance. */
export function ActiveFilters({ items, onClearAll }: { items: { key: string; label: string; onRemove: () => void }[]; onClearAll: () => void }) {
  if (items.length === 0) return null;
  return (
    <div className="active-filters" aria-label="Active filters">
      <span className="small muted">Active filters:</span>
      {items.map((i) => (
        <button key={i.key} type="button" className="filter-chip" onClick={i.onRemove} aria-label={`Remove filter ${i.label}`}>{i.label} <span aria-hidden="true">×</span></button>
      ))}
      <button type="button" className="linkish small" onClick={onClearAll}>Clear all</button>
    </div>
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

export function SortHeader<K extends string>({ label, sortKey, current, direction, onSort, numeric, className }: {
  label: string; sortKey: K; current: K; direction: "asc" | "desc"; onSort: (key: K) => void; numeric?: boolean; className?: string;
}) {
  const active = current === sortKey;
  return (
    <th scope="col" className={[numeric ? "num" : "", className ?? ""].join(" ").trim() || undefined} aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort-button" onClick={() => onSort(sortKey)}>
        {label}{active ? (direction === "asc" ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
}

/**
 * Fixed-size logo slot. Shows a verified official logo (proportions kept, dark variant when published) or a neutral
 * institution mark when no verified logo exists or the image fails to load. Decorative by default because the
 * university name is always shown beside it.
 */
export function UniversityLogo({ code, name, size = 28, registry, decorative = true }: {
  code: string | null | undefined; name: string; size?: number; registry?: Readonly<Record<string, LogoAsset>>; decorative?: boolean;
}) {
  const logo = logoFor(code, registry);
  const [failed, setFailed] = useState(false);
  const shown = logo ? logo.srcDark ?? logo.src : null;
  useEffect(() => { setFailed(false); }, [code, shown]);
  const a11y = decorative ? { "aria-hidden": true as const } : { role: "img", "aria-label": `${name} logo` };
  if (!logo || failed) {
    return (
      <span className="uni-logo uni-logo-fallback" style={{ width: size, height: size }} data-logo="fallback" {...a11y}>
        <Icon name="university" size={Math.round(size * 0.6)} />
      </span>
    );
  }
  return (
    <span className={`uni-logo${logo.srcDark ? "" : " uni-logo-plate"}`} style={{ width: size, height: size }} data-logo="verified" {...a11y}>
      {/* eslint-disable-next-line @next/next/no-img-element -- small same-origin static asset; next/image adds nothing here */}
      <img src={logo.srcDark ?? logo.src} width={logo.width} height={logo.height} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
    </span>
  );
}
