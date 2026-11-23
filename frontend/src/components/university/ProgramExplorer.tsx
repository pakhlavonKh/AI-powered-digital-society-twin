"use client";

import { useCatalogue, useUniversitySource } from "@/lib/university/context";
import { PROGRAM_PAGE_SIZE, programRows, programsWithoutYear, type ProgramUrlState } from "@/lib/university/programs";
import { allFindings, missingFields } from "@/lib/university/quality";
import type { ProgramSortKey, RegistrySnapshot } from "@/lib/university/types";
import { fmtInt } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { EmptyState, ErrorState, Loading } from "../States";
import { StatTile } from "../StatTile";
import { DataKindBadge, DataQualityPanel, Pagination } from "./common";
import { ProgramDetails } from "./ProgramDetails";
import { ProgramFilters } from "./ProgramFilters";
import { ProgramTable } from "./ProgramTable";

/** Controlled explorer: the page owns state (in the URL); this component renders it and reports changes. */
export function ProgramExplorer({ snapshot, state, onChange, selected, onSelect }: {
  snapshot: RegistrySnapshot; state: ProgramUrlState; onChange: (s: ProgramUrlState) => void; selected: string | null; onSelect: (code: string | null) => void;
}) {
  const source = useUniversitySource();
  const latest = snapshot.admission_years[snapshot.admission_years.length - 1] ?? null;
  const query = { ...state, snapshot_id: snapshot.snapshot_id, offset: state.page * PROGRAM_PAGE_SIZE, limit: PROGRAM_PAGE_SIZE };
  const key = JSON.stringify(query);
  const page = useApi(`uni:${source.id}:programs:${key}`, (signal) => source.queryPrograms(query, signal));
  const catalogue = useCatalogue(snapshot.snapshot_id);
  const onSort = (k: ProgramSortKey) => onChange({ ...state, sort: k, direction: state.sort === k && state.direction === "asc" ? "desc" : "asc", page: 0 });
  const p = page.data;
  const cat = catalogue.data;
  const allRows = cat ? programRows(cat, null) : [];
  const findings = cat ? allFindings(cat) : [];
  return (
    <div className="explorer2">
      <ProgramFilters state={state} facets={p?.facets} onChange={onChange} latestYear={latest} />
      <div className="stack">
        {selected ? <ProgramDetails snapshotId={snapshot.snapshot_id} programCode={selected} catalogue={cat} onClose={() => onSelect(null)} /> : null}
        {page.error ? <ErrorState error={page.error} onRetry={page.reload} what="program registry" /> : null}
        {page.loading && !p ? <Loading what="programs" /> : null}
        {p ? (
          <div className={page.stale ? "stack is-stale" : "stack"}>
            <div className="tiles">
              <StatTile label="Matching program-year rows" value={fmtInt(p.total_matching)} sub={state.year === null ? "All admission years" : `Admission year ${state.year}`} />
              <StatTile label="Reported quota (known)" value={fmtInt(p.matching_known_quota)} sub={p.matching_missing_quota ? `${fmtInt(p.matching_missing_quota)} row(s) with quota missing, not counted` : "No missing quotas in this selection"} />
              <StatTile label="Programs in snapshot" value={fmtInt(snapshot.counts.programs)} sub={`${fmtInt(snapshot.counts.universities)} institutions`} />
              <StatTile label="Admission years" value={`${snapshot.admission_years[0]}–${latest}`} sub={state.year !== null && cat ? `${fmtInt(programsWithoutYear(cat, state.year))} programs have no ${state.year} row` : undefined} />
            </div>
            <section className="card" aria-labelledby="programs-h">
              <div className="card-head"><h2 id="programs-h">Program registry</h2><span className="row small"><DataKindBadge kind="registry" /><span className="muted">Observed source values, not simulation results</span></span></div>
              {p.total_matching === 0 ? (
                <EmptyState title="No programs match these filters.">Reset the filters or choose another admission year.</EmptyState>
              ) : (
                <>
                  <ProgramTable rows={p.items} sort={state.sort} direction={state.direction} onSort={onSort} onSelect={onSelect} selected={selected}
                    caption={`${fmtInt(p.total_matching)} matching program-year rows, sorted by ${state.sort.replace("_", " ")} (${state.direction === "asc" ? "ascending" : "descending"}); missing values sort last`} />
                  <Pagination offset={p.offset} limit={p.limit} total={p.total_matching} label="Program" onPage={(n) => onChange({ ...state, page: n })} />
                </>
              )}
            </section>
          </div>
        ) : null}
        {catalogue.error ? <ErrorState error={catalogue.error} onRetry={catalogue.reload} what="data quality" /> : null}
        {cat ? (
          <DataQualityPanel records={allRows.length} recordLabel="Program-year records" incomplete={allRows.filter((r) => missingFields(r).length > 0).length}
            incompleteNote="Missing quota, placed, rank, score type, scholarship or institution type" findings={findings} origin={cat.snapshot.origin}
            source={cat.snapshot.source_filename} version={cat.snapshot.importer_version} />
        ) : null}
      </div>
    </div>
  );
}
