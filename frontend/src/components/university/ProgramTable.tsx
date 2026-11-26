"use client";

import { fmtInt } from "@/lib/format";
import { englishLabelOrNull } from "@/lib/university/labels";
import { missingFields } from "@/lib/university/quality";
import type { ProgramSortKey, ProgramYearRow, SortDirection } from "@/lib/university/types";
import { Badge } from "../StatusBadge";
import { SortHeader, SourceTerm, Value } from "./common";

export function ProgramTable({ rows, sort, direction, onSort, onSelect, selected, caption }: {
  rows: ProgramYearRow[]; sort: ProgramSortKey; direction: SortDirection; onSort: (k: ProgramSortKey) => void;
  onSelect: (code: string) => void; selected: string | null; caption: string;
}) {
  const h = (label: string, key: ProgramSortKey, numeric = false, className?: string) => <SortHeader label={label} sortKey={key} current={sort} direction={direction} onSort={onSort} numeric={numeric} className={className} />;
  return (
    <div className="table-wrap">
      <table className="program-table data-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {h("Code", "code", false, "col-code")}{h("University · type", "university", false, "col-university")}{h("Program", "program", false, "col-program")}{h("Year", "year", true)}
            <th scope="col">Score type</th><th scope="col" className="col-scholarship">Scholarship</th>
            {h("Reported quota", "quota", true)}{h("Placed", "placed", true)}{h("Success rank", "success_rank", true)}
            <th scope="col" className="col-status">Data status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const missing = missingFields(r);
            const above = r.issues.some((i) => i.issue_code === "placed_above_quota");
            const errors = r.issues.filter((i) => i.severity === "error").length;
            return (
              <tr key={r.key} className={selected === r.program.program_code ? "is-selected" : undefined}>
                <td className="nowrap"><code>{r.program.program_code}</code></td>
                <td>{r.university.name_original}<div className="small muted">Type: <SourceTerm value={r.university.university_type} /></div></td>
                <th scope="row">
                  <button type="button" className="linkish" title={r.program.faculty ?? undefined} onClick={() => onSelect(r.program.program_code)} aria-label={`Open details for ${r.program.name_original}, ${r.university.name_original}, ${englishLabelOrNull(r.program.scholarship_original) ?? "scholarship missing"}, code ${r.program.program_code}`}>
                    {r.program.name_original}
                  </button>
                </th>
                <td className="num"><Value value={r.admission?.admission_year} reason="not_available" /></td>
                <td><Value value={r.program.score_type} /></td>
                <td><SourceTerm value={r.program.scholarship_original} /></td>
                <td className="num"><Value value={r.admission?.quota} reason={r.admission ? "missing_from_source" : "not_available"} format={fmtInt} /></td>
                <td className="num"><Value value={r.admission?.placed_students} reason={r.admission ? "missing_from_source" : "not_available"} format={fmtInt} /></td>
                <td className="num"><Value value={r.admission?.success_rank} reason={r.admission ? "missing_from_source" : "not_available"} format={fmtInt} /></td>
                <td className="status-cell">
                  <div className="row" style={{ gap: 4 }}>
                    <Badge tone="neutral" glyph="⧉" title="Historical registry observation">Registry</Badge>
                    {above ? <Badge tone="warn" glyph="!" title="Placed count exceeds the reported quota in the source; preserved unchanged">Placed &gt; quota</Badge> : null}
                    {errors ? <Badge tone="crit" glyph="×" title="The importer rejected a related source row">{errors} import error{errors > 1 ? "s" : ""}</Badge> : null}
                    {missing.length ? <Badge tone="warn" glyph="·" title={`Missing: ${missing.join(", ")}`}>Incomplete ({missing.length})</Badge> : null}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
