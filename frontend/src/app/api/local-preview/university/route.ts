/**
 * Opt-in LOCAL PREVIEW of the git-ignored ÖSYM 2025 Table 4 national CSVs, shaped as a RegistryCatalogue.
 *
 * - Development only: in a production build this route answers 404 and reads nothing.
 * - The records are read from disk at request time (data/processed/osym_national_2025/, git-ignored); nothing from
 *   them is committed or bundled. ÖSYM reuse permission is pending, so this is for local review only.
 * - `?scope=logos` keeps only universities whose official_university_code has an entry in the logo registry.
 */
import { promises as fs } from "node:fs";
import path from "node:path";
import { VERIFIED_LOGOS } from "@/lib/university/logos";
import type { AnnualAdmission, Program, QualityIssue, RegistryCatalogue, University } from "@/lib/university/types";

export const dynamic = "force-dynamic";

const DIR = path.join(process.cwd(), "..", "data", "processed", "osym_national_2025");
const SNAPSHOT_ID = "local-preview:osym-2025-table4";

/** RFC 4180 CSV (quoted fields, escaped quotes, CRLF). */
function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(field); field = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else field += ch;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  const [header, ...body] = rows;
  return body.map((r) => Object.fromEntries(header.map((h, i) => [h.replace(/^﻿/, ""), r[i] ?? ""])));
}

const blank = (v: string | undefined) => (v === undefined || v.trim() === "" ? null : v.trim());
const int = (v: string | undefined) => (blank(v) === null ? null : Number.parseInt(v!, 10));

export async function GET(request: Request) {
  if (process.env.NODE_ENV !== "development") return new Response("Not found", { status: 404 });
  const scope = new URL(request.url).searchParams.get("scope");
  let programsCsv: string, tracksCsv: string;
  try {
    [programsCsv, tracksCsv] = await Promise.all([
      fs.readFile(path.join(DIR, "osym_national_programs_2025.csv"), "utf8"),
      fs.readFile(path.join(DIR, "osym_national_admissions_tracks_2025.csv"), "utf8"),
    ]);
  } catch {
    return Response.json({ code: "local_preview_unavailable", message: "The local national CSVs were not found in data/processed/osym_national_2025/." }, { status: 404 });
  }
  const programRows = parseCsv(programsCsv);
  const genel = new Map(parseCsv(tracksCsv).filter((t) => t.quota_track === "genel").map((t) => [t.program_code, t]));

  const universities: University[] = [];
  const uniIds = new Map<string, number>();
  const programs: Program[] = [];
  const admissions: AnnualAdmission[] = [];
  const issues: QualityIssue[] = [];
  for (const r of programRows) {
    const code = r.program_code.slice(0, 4); // official ÖSYM institution code
    if (scope === "logos" && !VERIFIED_LOGOS[code]) continue;
    let universityId = uniIds.get(r.university_name_official);
    if (universityId === undefined) {
      universityId = universities.length + 1;
      uniIds.set(r.university_name_official, universityId);
      universities.push({ university_id: universityId, snapshot_id: SNAPSHOT_ID, university_key: `osym:${code}`, name_original: r.university_name_official,
        name_normalized: r.university_name_official, official_university_code: code, university_type: blank(r.university_type), city: blank(r.hq_city) });
    }
    const programId = programs.length + 1;
    programs.push({ program_id: programId, snapshot_id: SNAPSHOT_ID, university_id: universityId, program_code: r.program_code, name_original: r.program_name_official,
      faculty: blank(r.faculty_official), degree_level: blank(r.degree_level), score_type: blank(r.score_type), scholarship_original: blank(r.scholarship_tier),
      teaching_language: blank(r.teaching_language_explicit), source_sheet: "Sayfa1", source_row: Number(r.source_row) });
    const t = genel.get(r.program_code);
    if (t) {
      admissions.push({ admission_id: admissions.length + 1, program_id: programId, snapshot_id: SNAPSHOT_ID, admission_year: Number(t.admission_year),
        quota: int(t.quota), placed_students: int(t.placed), success_rank: int(t.official_success_rank), source_sheet: "Sayfa1", source_row: Number(r.source_row) });
      if ((int(t.placed_excess_over_track_quota) ?? 0) > 0) {
        issues.push({ issue_id: issues.length + 1, snapshot_id: SNAPSHOT_ID, issue_key: `placed_above_quota:${r.program_code}:2025`, severity: "warning", issue_code: "placed_above_quota",
          message: `Placed count (${t.placed}) exceeds the general quota (${t.quota}) as published; preserved unchanged.`, source_sheet: "Sayfa1", source_row: Number(r.source_row),
          source_column: "Yerleşen", raw_value: t.placed, program_id: programId, related_year: 2025, review_status: "open", resolution: null });
      }
    }
  }
  const catalogue: RegistryCatalogue = {
    snapshot: {
      snapshot_id: SNAPSHOT_ID, source_filename: "tablo4_ykd25082025.xlsx (ÖSYM 2025 YKS Table 4, local CSV)",
      file_sha256: "8def915efd6bbce1f74274bb41e750718f17fa90de337d320fa072153a14c055", imported_at: new Date().toISOString(), importer_version: "local-preview-v1",
      source_description: scope === "logos" ? "Local preview limited to universities with a registered logo" : "Local preview of all national undergraduate programs",
      source_reference: "https://www.osym.gov.tr/2025yks-yerlestirme-sonuclarina-iliskin-sayisal-bilgiler", retrieved_at: null,
      verification_status: "unverified", notes: "Development-only local preview; ÖSYM reuse permission pending; not committed or published.", origin: "local_preview",
      admission_years: [2025],
      counts: { universities: universities.length, programs: programs.length, annual_admissions: admissions.length, annual_tuition: 0, data_quality_issues: issues.length },
    },
    universities, programs, admissions, tuition: [], issues,
  };
  return Response.json(catalogue, { headers: { "Cache-Control": "no-store" } });
}
