"use client";

import { useCatalogue, useUniversitySource } from "@/lib/university/context";
import { PAGE_SIZES, programRows, programsWithoutYear, type ProgramUrlState } from "@/lib/university/programs";
import { allFindings, missingFields } from "@/lib/university/quality";
import type { ProgramSortKey, RegistrySnapshot } from "@/lib/university/types";
import { fmtInt, fmtPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { EmptyState, ErrorState, Loading } from "../States";
import { StatTile } from "../StatTile";
import { DataKindBadge, DataQualityPanel, Missing, Pagination, ProvenancePanel } from "./common";
import { ProgramDetails } from "./ProgramDetails";
import { ProgramFilters } from "./ProgramFilters";
import { ProgramTable } from "./ProgramTable";

const SORT_LABEL: Record<ProgramSortKey, string> = {
  university: "university", program: "program", year: "year", quota: "quota", placed: "placed", success_rank: "admission rank", code: "program code",
};

/**
 * Controlled explorer: the page owns state (in the URL); this component renders it and reports changes.
 * Layout, top to bottom: filters, summary, (details), table with pagination, data information and quality.
 */
export function ProgramExplorer({ snapshot, state, onChange, selected, onSelect }: {
  snapshot: RegistrySnapshot; state: ProgramUrlState; onChange: (s: ProgramUrlState) => void; selected: string | null; onSelect: (code: string | null) => void;
}) {
  const source = useUniversitySource();
  const latest = snapshot.admission_years[snapshot.admission_years.length - 1] ?? null;
  const query = { ...state, snapshot_id: snapshot.snapshot_id, offset: state.page * state.size, limit: state.size };
  const key = JSON.stringify(query);
  const page = useApi(`uni:${source.id}:programs:${key}`, (signal) => source.queryPrograms(query, signal));
  const catalogue = useCatalogue(snapshot.snapshot_id);
  const onSort = (k: ProgramSortKey) => onChange({ ...state, sort: k, direction: state.sort === k && state.direction === "asc" ? "desc" : "asc", page: 0 });
  const p = page.data;
  const cat = catalogue.data;
  const allRows = cat ? programRows(cat, null) : [];
  const findings = cat ? allFindings(cat) : [];
  const yearText = state.year === null ? "all admission years" : `admission year ${state.year}`;
  const avgQuota = p && p.summary.known_quota_rows > 0 ? p.matching_known_quota / p.summary.known_quota_rows : null;
  return (
    <div className="stack uni-explorer">
      <ProgramFilters state={state} facets={p?.facets} onChange={onChange} latestYear={latest} />
      {page.error ? <ErrorState error={page.error} onRetry={page.reload} what="program registry" /> : null}
      {page.loading && !p ? <Loading what="programs" /> : null}
      {p ? (
        <div className="tiles tiles-4 summary-strip" aria-label="Program summary">
          <StatTile label="Total programs" value={fmtInt(p.summary.programs)} sub={`${fmtInt(p.total_matching)} program-year rows · ${yearText}`} />
          <StatTile label="Universities" value={fmtInt(p.summary.universities)} sub={`of ${fmtInt(snapshot.counts.universities)} in the registry snapshot`} />
          <StatTile label="Scholarship programs" value={<>{fmtInt(p.summary.scholarship_rows)} <span className="tile-share">{p.total_matching ? `(${fmtPct(p.summary.scholarship_rows / p.total_matching, 1)})` : ""}</span></>}
            sub="Full scholarship or tuition discount" />
          <StatTile label="Average program quota" value={avgQuota === null ? <Missing reason="not_calculated" /> : avgQuota.toLocaleString("en-GB", { maximumFractionDigits: 1 })}
            sub={p.matching_missing_quota ? `Over ${fmtInt(p.summary.known_quota_rows)} rows with a reported quota; ${fmtInt(p.matching_missing_quota)} missing, not counted` : "Reported quota; no quota missing in this selection"} />
        </div>
      ) : null}
      {selected ? <ProgramDetails snapshotId={snapshot.snapshot_id} programCode={selected} catalogue={cat} onClose={() => onSelect(null)} /> : null}
      {p ? (
        <section className={page.stale ? "card table-card is-stale" : "card table-card"} aria-labelledby="programs-h">
          <div className="card-head">
            <h2 id="programs-h">Programs <span className="count-pill">{fmtInt(p.total_matching)}</span></h2>
            <span className="row small"><DataKindBadge kind="registry" /><span className="muted">Observed source values, not simulation results</span></span>
          </div>
          {p.total_matching === 0 ? (
            <EmptyState title="No programs match these filters.">Reset the filters or choose another admission year.</EmptyState>
          ) : (
            <>
              <ProgramTable rows={p.items} sort={state.sort} direction={state.direction} onSort={onSort} onSelect={onSelect} selected={selected}
                caption={`${fmtInt(p.total_matching)} matching program-year rows, sorted by ${SORT_LABEL[state.sort]} (${state.direction === "asc" ? "ascending" : "descending"}); missing values sort last`} />
              <Pagination offset={p.offset} limit={p.limit} total={p.total_matching} label="Program" onPage={(n) => onChange({ ...state, page: n })}
                pageSizes={PAGE_SIZES} onPageSize={(size) => onChange({ ...state, size, page: 0 })} />
            </>
          )}
        </section>
      ) : null}
      {cat ? (
        <div className="data-info-grid">
          <ProvenancePanel title="Data information" origin={cat.snapshot.origin} items={[
            { label: "Registry snapshot", value: cat.snapshot.snapshot_id, mono: true },
            { label: "Source", value: cat.snapshot.source_filename },
            { label: "Data origin", value: cat.snapshot.origin === "fixture" ? "Synthetic fixture generated for UI exploration; not official ÖSYM records"
              : cat.snapshot.origin === "local_preview" ? "Local preview of the ÖSYM 2025 Table 4 national CSV (git-ignored, development only; reuse permission pending)" : "Registry API" },
            { label: "Importer version", value: cat.snapshot.importer_version, mono: true },
            { label: "Admission years", value: `${snapshot.admission_years.join(", ")}${state.year !== null ? ` · ${fmtInt(programsWithoutYear(cat, state.year))} program(s) have no ${state.year} row (not shown; absence is not zero)` : ""}` },
            { label: "Verification", value: cat.snapshot.verification_status },
            { label: "Values shown", value: "Reported quota, placed count and admission rank (success rank of the last placed candidate), as recorded. Quotas are reported indicators, not verified capacities; placed counts are never capped." },
            { label: "Not in the registry", value: "Minimum admission score (taban puan) and city: the registry schema has no such fields, so they are not shown or estimated." },
            { label: "Labels", value: "University and program names are as written in the source. Scholarship, institution-type and language labels are shown in English (hover for the source label); score types use the official ÖSYM codes." },
          ]} />
          <DataQualityPanel records={allRows.length} recordLabel="Program-year records" incomplete={allRows.filter((r) => missingFields(r).length > 0).length}
            incompleteNote="Missing quota, placed, rank, score type, scholarship or institution type" findings={findings} origin={cat.snapshot.origin}
            source={cat.snapshot.source_filename} version={cat.snapshot.importer_version} />
        </div>
      ) : catalogue.error ? <ErrorState error={catalogue.error} onRetry={catalogue.reload} what="data quality" /> : null}
    </div>
  );
}
