"use client";

import { fmtInt } from "@/lib/format";
import { englishLabelOrNull } from "@/lib/university/labels";
import { missingFields } from "@/lib/university/quality";
import type { ProgramSortKey, ProgramYearRow, SortDirection } from "@/lib/university/types";
import { Icon } from "../Icon";
import { Badge } from "../StatusBadge";
import { ScoreChip, SortHeader, SourceTerm, UniversityLogo, Value } from "./common";

/**
 * Registry rows (one per program and admission year). "Admission rank" is the source's success rank of the last
 * placed candidate; the registry has no minimum admission score, so no score column is shown.
 */
export function ProgramTable({ rows, sort, direction, onSort, onSelect, selected, caption }: {
  rows: ProgramYearRow[]; sort: ProgramSortKey; direction: SortDirection; onSort: (k: ProgramSortKey) => void;
  onSelect: (code: string) => void; selected: string | null; caption: string;
}) {
  const h = (label: string, key: ProgramSortKey, numeric = false, className?: string) => <SortHeader label={label} sortKey={key} current={sort} direction={direction} onSort={onSort} numeric={numeric} className={className} />;
  return (
    <div className="table-wrap">
      <table className="program-table data-table explorer-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {h("University", "university", false, "col-university")}{h("Program", "program", false, "col-program")}{h("Year", "year", true)}
            <th scope="col">Score type</th><th scope="col">Institution type</th><th scope="col" className="col-scholarship">Scholarship</th>
            {h("Quota", "quota", true)}{h("Placed", "placed", true)}{h("Admission rank", "success_rank", true)}
            <th scope="col" className="col-actions"><span className="visually-hidden">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const missing = missingFields(r);
            const above = r.issues.some((i) => i.issue_code === "placed_above_quota");
            const errors = r.issues.filter((i) => i.severity === "error").length;
            const isSelected = selected === r.program.program_code;
            return (
              <tr key={r.key} className={isSelected ? "is-selected" : undefined}>
                <td className="cell-name"><span className="uni-cell"><UniversityLogo code={r.university.official_university_code} name={r.university.name_original} /><span>{r.university.name_original}</span></span></td>
                <th scope="row" className="cell-name">
                  <span className="cell-primary" title={r.program.faculty ?? undefined}>{r.program.name_original}</span>
                  <span className="cell-secondary"><code>{r.program.program_code}</code>
                    {above ? <Badge tone="warn" glyph="!" title="Placed count exceeds the reported quota in the source; preserved unchanged">Placed &gt; quota</Badge> : null}
                    {errors ? <Badge tone="crit" glyph="×" title="The importer rejected a related source row">{errors} import error{errors > 1 ? "s" : ""}</Badge> : null}
                    {missing.length ? <Badge tone="warn" glyph="·" title={`Missing: ${missing.join(", ")}`}>Incomplete ({missing.length})</Badge> : null}
                  </span>
                </th>
                <td className="num"><Value value={r.admission?.admission_year} reason="not_available" /></td>
                <td><ScoreChip value={r.program.score_type} /></td>
                <td><SourceTerm value={r.university.university_type} /></td>
                <td><SourceTerm value={r.program.scholarship_original} /></td>
                <td className="num"><Value value={r.admission?.quota} reason={r.admission ? "missing_from_source" : "not_available"} format={fmtInt} /></td>
                <td className="num"><Value value={r.admission?.placed_students} reason={r.admission ? "missing_from_source" : "not_available"} format={fmtInt} /></td>
                <td className="num"><Value value={r.admission?.success_rank} reason={r.admission ? "missing_from_source" : "not_available"} format={fmtInt} /></td>
                <td className="col-actions">
                  <button type="button" className="button small row-action" aria-pressed={isSelected} onClick={() => onSelect(r.program.program_code)}
                    aria-label={`View details for ${r.program.name_original}, ${r.university.name_original}, ${englishLabelOrNull(r.program.scholarship_original) ?? "scholarship missing"}, code ${r.program.program_code}`}>
                    View details <Icon name="arrow" size={12} />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
