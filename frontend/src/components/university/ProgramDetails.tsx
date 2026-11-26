"use client";

import { useEffect, useRef } from "react";
import { fmtInt, fmtPct } from "@/lib/format";
import { useUniversitySource } from "@/lib/university/context";
import { catalogueChecks, issueToFinding } from "@/lib/university/quality";
import type { ProgramDetail, RegistryCatalogue } from "@/lib/university/types";
import { fmtMoneyMinor } from "@/lib/university/util";
import { useApi } from "@/lib/useApi";
import { CopyId } from "../CopyId";
import { ErrorState, Loading } from "../States";
import { KeyValues } from "../StatTile";
import { DataKindBadge, Missing, ProvenancePanel, SourceBadge, SourceTerm, Value, ValidationList } from "./common";

function feeNote(basis: string | null): string | null {
  if (!basis) return null;
  try {
    const parsed = JSON.parse(basis) as Record<string, string>;
    return [parsed.note, parsed.net, parsed.academic_year_boundaries ? `academic-year boundaries ${parsed.academic_year_boundaries}` : null].filter(Boolean).join("; ");
  } catch {
    return basis;
  }
}

/** Every field the program detail lacks, so incompleteness is listed rather than hidden. */
export function detailMissingFields(d: ProgramDetail, years: number[]): string[] {
  const out: string[] = [];
  const p = d.program;
  if (p.faculty === null) out.push("Faculty");
  if (p.degree_level === null) out.push("Degree level (the importer does not infer it)");
  if (p.score_type === null) out.push("Score type");
  if (p.scholarship_original === null) out.push("Scholarship label");
  if (p.teaching_language === null) out.push("Teaching language (not specified in source)");
  if (d.university.university_type === null) out.push("Institution type");
  if (d.university.city === null) out.push("City (not recorded by the registry)");
  if (d.university.official_university_code === null) out.push("Official university code");
  const rows = new Map(d.admissions.map((a) => [a.admission_year, a]));
  for (const y of years) {
    const a = rows.get(y);
    if (!a) out.push(`${y}: no admission row`);
    else {
      if (a.quota === null) out.push(`${y}: reported quota`);
      if (a.placed_students === null) out.push(`${y}: placed count`);
      if (a.success_rank === null) out.push(`${y}: success rank`);
    }
  }
  for (const t of d.tuition) if (t.full_amount_minor === null && t.net_amount_minor === null) out.push(`Fee year ${t.academic_year_start}: no fee in source`);
  return out;
}

export function ProgramDetails({ snapshotId, programCode, catalogue, onClose }: {
  snapshotId: string; programCode: string; catalogue: RegistryCatalogue | undefined; onClose: () => void;
}) {
  const source = useUniversitySource();
  const detail = useApi(`uni:${source.id}:program:${snapshotId}:${programCode}`, (signal) => source.getProgram(snapshotId, programCode, signal));
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, [programCode, detail.data]);
  const d = detail.data;
  return (
    <section className="card stack program-detail" aria-labelledby="program-detail-h">
      <div className="card-head">
        <h2 id="program-detail-h" tabIndex={-1} ref={heading}>{d ? `${d.program.name_original} · ${d.university.name_original}` : `Program ${programCode}`}</h2>
        <button type="button" className="button small" onClick={onClose}>Close details</button>
      </div>
      {detail.error ? <ErrorState error={detail.error} onRetry={detail.reload} what="program details" /> : null}
      {detail.loading && !d ? <Loading what="program details" /> : null}
      {d ? <DetailBody d={d} catalogue={catalogue} /> : null}
    </section>
  );
}

function DetailBody({ d, catalogue }: { d: ProgramDetail; catalogue: RegistryCatalogue | undefined }) {
  const years = d.snapshot.admission_years;
  const rows = new Map(d.admissions.map((a) => [a.admission_year, a]));
  const missing = detailMissingFields(d, years);
  const findings = [
    ...d.issues.map((i) => issueToFinding(i, d.program.program_code)),
    ...(catalogue ? catalogueChecks(catalogue).filter((f) => f.record?.startsWith(`Program ${d.program.program_code}`)) : []),
  ];
  return (
    <>
      <div className="row small"><DataKindBadge kind="registry" /><SourceBadge origin={d.snapshot.origin} /><span>Code <CopyId value={d.program.program_code} label="program code" /></span></div>
      <div className="grid-2">
        <div className="stack">
          <h3>Program identity</h3>
          <KeyValues items={[
            ["University", d.university.name_original],
            ["Institution type", <SourceTerm key="t" value={d.university.university_type} showSource />],
            ["Faculty", <Value key="f" value={d.program.faculty} />],
            ["Degree level", <Value key="dl" value={d.program.degree_level} />],
            ["Score type", <Value key="s" value={d.program.score_type} />],
            ["Scholarship", <SourceTerm key="sc" value={d.program.scholarship_original} showSource />],
            ["Teaching language", d.program.teaching_language ? <SourceTerm key="l" value={d.program.teaching_language} showSource />
              : <span key="l" className="missing" title="The source did not specify a teaching language; it is not presumed Turkish.">Not specified in source</span>],
            ["City", <Value key="c" value={d.university.city} reason="not_available" />],
            ["Official university code", <Value key="o" value={d.university.official_university_code} reason="not_available" />],
          ]} />
        </div>
        <ProvenancePanel title="Source metadata" origin={d.snapshot.origin} items={[
          { label: "Registry snapshot", value: d.snapshot.snapshot_id, mono: true },
          { label: "Source file", value: d.snapshot.source_filename },
          { label: "File SHA-256", value: d.snapshot.file_sha256, missing: d.snapshot.origin === "fixture" ? "not_applicable" : "not_available", mono: true },
          { label: "Importer version", value: d.snapshot.importer_version, mono: true },
          { label: "Imported at", value: d.snapshot.imported_at },
          { label: "Source retrieved", value: d.snapshot.retrieved_at, missing: "missing_from_source" },
          { label: "Verification", value: d.snapshot.verification_status },
          { label: "Program source row", value: `${d.program.source_sheet} row ${d.program.source_row}` },
        ]} />
      </div>
      <div className="table-wrap">
        <table>
          <caption>Admission history: reported quota indicators and placed counts as recorded, never capped</caption>
          <thead><tr><th scope="col">Year</th><th scope="col" className="num">Reported quota</th><th scope="col" className="num">Placed</th><th scope="col" className="num">Success rank (last placed)</th>
            <th scope="col" className="num">Occupancy <span className="muted">(derived)</span></th><th scope="col">Source row</th></tr></thead>
          <tbody>
            {years.map((y) => {
              const a = rows.get(y);
              const issue = d.issues.find((i) => i.related_year === y && i.severity === "error");
              if (!a) {
                return (
                  <tr key={y}><th scope="row">{y}</th><td colSpan={4}>{issue ? <span className="missing">Source row rejected by the importer ({issue.issue_code}); not imported</span> : <Missing reason="not_available" />}</td>
                    <td className="small muted">{issue?.source_row ? `${issue.source_sheet} row ${issue.source_row}` : "No admission row (not zero)"}</td></tr>
                );
              }
              const occupancy = a.quota !== null && a.quota > 0 && a.placed_students !== null ? a.placed_students / a.quota : null;
              return (
                <tr key={y}>
                  <th scope="row">{y}</th>
                  <td className="num"><Value value={a.quota} format={fmtInt} /></td>
                  <td className="num"><Value value={a.placed_students} format={fmtInt} /></td>
                  <td className="num"><Value value={a.success_rank} format={fmtInt} /></td>
                  <td className="num">{occupancy === null ? <Missing reason="not_calculated" /> : <span className={occupancy > 1 ? "warn-text" : undefined}>{fmtPct(occupancy, 0)}</span>}</td>
                  <td className="small muted">{a.source_sheet} row {a.source_row}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="small muted" style={{ margin: 0 }}>Occupancy = placed ÷ reported quota, calculated here; it can exceed 100% because the source reports placed counts above quota. Quotas are reported indicators, not verified official capacities.</p>
      <div className="table-wrap">
        <table>
          <caption>Tuition as quoted in the source (fee-year labels; academic-year boundaries unverified)</caption>
          <thead><tr><th scope="col">Fee year</th><th scope="col" className="num">Full annual fee</th><th scope="col" className="num">Net fee <span className="muted">(source-derived)</span></th><th scope="col">Basis</th></tr></thead>
          <tbody>
            {d.tuition.length === 0 ? <tr><td colSpan={4}><Missing reason="not_available" /></td></tr> : d.tuition.map((t) => (
              <tr key={t.tuition_id}>
                <th scope="row">{t.academic_year_start}</th>
                <td className="num"><Value value={fmtMoneyMinor(t.full_amount_minor, t.currency)} /></td>
                <td className="num"><Value value={fmtMoneyMinor(t.net_amount_minor, t.currency)} /></td>
                <td className="small muted">{feeNote(t.fee_basis) ?? <Missing reason="not_available" />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid-2">
        <section className="stack" aria-label="Missing fields">
          <h3>Missing fields ({missing.length})</h3>
          {missing.length ? <ul className="small missing-list">{missing.map((m) => <li key={m}>{m}</li>)}</ul> : <p className="small muted">No missing fields.</p>}
        </section>
        <ValidationList findings={findings} title="Validation warnings" empty="No importer issues or dashboard warnings for this program." />
      </div>
    </>
  );
}
