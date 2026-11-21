/**
 * Data-quality checks. Source issues recorded by the registry importer are passed through unchanged (with their
 * importer code and key); the frontend adds its own derived checks and labels them as such. Nothing is suppressed:
 * every finding is counted and listed.
 */
import type { Finding, IssueSeverity, Preference, ProgramYearRow, QualityIssue, RegistryCatalogue } from "./types";
import { isContractScoreType, scoreTypeKey } from "./util";

export const ISSUE_LABELS: Record<string, string> = {
  placed_above_quota: "Placed count above reported quota",
  invalid_annual: "Annual row rejected by the importer",
  invalid_program: "Program row rejected by the importer",
  duplicate_program: "Duplicate program row collapsed",
  duplicate_annual: "Duplicate annual row collapsed",
  conflicting_program: "Conflicting program rows quarantined",
  conflicting_annual: "Conflicting annual rows quarantined",
  sheet_disagreement: "Long and wide sheets disagree",
  missing_long_record: "Wide-sheet data without a long-format row",
  unknown_program: "Annual row without an accepted program",
  summary_disagreement: "University summary disagrees",
  invalid_tuition: "Tuition value rejected",
  missing_quota: "Missing program quota",
  missing_score_type: "Missing score type",
  unknown_score_type: "Unknown score type",
  missing_university: "Missing university identifier",
  duplicate_program_record: "Duplicate program record",
  invalid_preference_reference: "Invalid preference reference",
  no_valid_preferences: "Candidate with no valid preferences",
  no_preferences: "Candidate with no preferences",
  invalid_preference_positions: "Preference positions not contiguous",
  over_capacity: "Placement count exceeding capacity",
  missing_provenance: "Missing simulation provenance",
  totals_do_not_reconcile: "Totals do not reconcile",
};

export function issueToFinding(issue: QualityIssue, programCode?: string): Finding {
  return {
    code: issue.issue_code,
    severity: issue.severity,
    origin: "source_import",
    // Importer errors quarantine source rows; the remaining data is still usable, so they do not block browsing.
    blocking: false,
    message: issue.message,
    record: programCode ? `Program ${programCode}${issue.related_year ? ` · ${issue.related_year}` : ""}` : issue.source_row ? `${issue.source_sheet} row ${issue.source_row}` : undefined,
    field: issue.source_column ?? undefined,
    detail: [issue.source_sheet && issue.source_row ? `${issue.source_sheet}:${issue.source_row}` : null, issue.raw_value ? `raw ${issue.raw_value}` : null,
      `review ${issue.review_status}`].filter(Boolean).join(" · "),
  };
}

/** Frontend checks over the whole catalogue (in addition to the importer's issues). */
export function catalogueChecks(catalogue: RegistryCatalogue): Finding[] {
  const out: Finding[] = [];
  const uniIds = new Set(catalogue.universities.filter((u) => u.university_key.trim() !== "").map((u) => u.university_id));
  const seen = new Map<string, number>();
  for (const p of catalogue.programs) seen.set(`${p.snapshot_id}|${p.program_code}`, (seen.get(`${p.snapshot_id}|${p.program_code}`) ?? 0) + 1);
  const reportedAbove = new Set(catalogue.issues.filter((i) => i.issue_code === "placed_above_quota").map((i) => `${i.program_id}:${i.related_year}`));
  const programById = new Map(catalogue.programs.map((p) => [p.program_id, p]));

  for (const p of catalogue.programs) {
    const record = `Program ${p.program_code}`;
    if (!uniIds.has(p.university_id)) {
      out.push({ code: "missing_university", severity: "error", origin: "frontend_check", blocking: false, record,
        message: "The program references no known university; it cannot be shown under an institution." });
    }
    if (p.score_type === null) {
      out.push({ code: "missing_score_type", severity: "warning", origin: "frontend_check", blocking: false, record, field: "score_type",
        message: "The source gives no score type; candidates cannot be matched to this program." });
    } else if (!isContractScoreType(p.score_type)) {
      out.push({ code: "unknown_score_type", severity: "warning", origin: "frontend_check", blocking: false, record, field: "score_type",
        message: `Score type "${p.score_type}" is not one of the candidate contract's types (SAY, EA, SOZ, DIL); no synthetic candidate can match it.` });
    }
  }
  for (const [key, n] of seen) {
    if (n > 1) out.push({ code: "duplicate_program_record", severity: "error", origin: "frontend_check", blocking: false,
      record: `Program ${key.split("|")[1]}`, message: `${n} program records share this code in one snapshot; the registry requires it to be unique.` });
  }
  for (const a of catalogue.admissions) {
    const p = programById.get(a.program_id);
    const record = `Program ${p?.program_code ?? a.program_id} · ${a.admission_year}`;
    if (a.quota === null) {
      out.push({ code: "missing_quota", severity: "warning", origin: "frontend_check", blocking: false, record, field: "quota",
        message: "Reported quota is missing; it is shown as missing (not zero) and the program cannot receive simulated placements for this year." });
    }
    if (a.quota !== null && a.placed_students !== null && a.placed_students > a.quota && !reportedAbove.has(`${a.program_id}:${a.admission_year}`)) {
      out.push({ code: "placed_above_quota", severity: "warning", origin: "frontend_check", blocking: false, record,
        message: `Placed ${a.placed_students} exceeds the reported quota ${a.quota}; preserved unchanged.` });
    }
  }
  return out;
}

export function allFindings(catalogue: RegistryCatalogue): Finding[] {
  const codes = new Map(catalogue.programs.map((p) => [p.program_id, p.program_code]));
  return [...catalogue.issues.map((i) => issueToFinding(i, i.program_id === null ? undefined : codes.get(i.program_id))), ...catalogueChecks(catalogue)];
}

/** Fields whose absence makes a program-year row incomplete. teaching_language is excluded: NULL means "unspecified". */
export function missingFields(row: ProgramYearRow): string[] {
  const out: string[] = [];
  if (row.admission === null) out.push("admission row");
  else {
    if (row.admission.quota === null) out.push("quota");
    if (row.admission.placed_students === null) out.push("placed");
    if (row.admission.success_rank === null) out.push("success rank");
  }
  if (row.program.score_type === null) out.push("score type");
  if (row.program.scholarship_original === null) out.push("scholarship");
  if (row.university.university_type === null) out.push("institution type");
  return out;
}

/** Structural checks matching validate_handoff, reported instead of raised, plus "no valid preferences". */
export function preferenceChecks(candidateId: string, preferences: Preference[], programCodes: Set<string>): Finding[] {
  const out: Finding[] = [];
  const record = candidateId;
  if (preferences.length === 0) {
    out.push({ code: "no_preferences", severity: "warning", origin: "frontend_check", blocking: false, record,
      message: "This candidate has no preferences in the handoff. An empty list does not mean the candidate has no real preferences." });
    return out;
  }
  const invalid = preferences.filter((p) => !programCodes.has(p.program_id));
  for (const p of invalid) {
    out.push({ code: "invalid_preference_reference", severity: "error", origin: "frontend_check", blocking: false, record,
      field: `preference ${p.position}`, message: `Program code ${p.program_id} does not exist in the registry snapshot.` });
  }
  if (invalid.length === preferences.length) {
    out.push({ code: "no_valid_preferences", severity: "error", origin: "frontend_check", blocking: false, record,
      message: "None of this candidate's preferences reference a program in the registry snapshot." });
  }
  const positions = preferences.map((p) => p.position).sort((a, b) => a - b);
  if (positions.some((pos, i) => pos !== i + 1)) {
    out.push({ code: "invalid_preference_positions", severity: "error", origin: "frontend_check", blocking: false, record,
      message: "Preference positions must be unique and contiguous from 1." });
  }
  return out;
}

export function countBySeverity(findings: Finding[]): Record<IssueSeverity, number> & { blocking: number } {
  const out = { info: 0, warning: 0, error: 0, blocking: 0 };
  for (const f of findings) {
    out[f.severity] += 1;
    if (f.blocking) out.blocking += 1;
  }
  return out;
}

export function scoreTypesCompatible(candidateType: string | null, programType: string | null): boolean {
  return scoreTypeKey(candidateType) !== null && scoreTypeKey(candidateType) === scoreTypeKey(programType);
}
