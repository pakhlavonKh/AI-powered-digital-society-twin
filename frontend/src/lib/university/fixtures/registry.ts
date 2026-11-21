/**
 * Deterministic SYNTHETIC registry fixture shaped exactly like the university SQLite schema (db.py, version 1).
 *
 * Every institution, program, code, quota, rank and fee here is invented for frontend development. Names say
 * "Synthetic" so they cannot be mistaken for real institutions. Some records are deliberately incomplete so the UI's
 * missing-data and validation states are exercised (listed in docs/university-simulation-ui.md):
 *   - university F has no institution type;
 *   - one program has no score type, and the vocational programs use "TYT", which the candidate contract lacks;
 *   - one 2025 admission row has a NULL quota; some 2026 success ranks are NULL;
 *   - one 2023 annual row is quarantined by an `invalid_annual` error, so it has no admission row;
 *   - placed counts above quota are preserved and reported as `placed_above_quota`, like the real importer.
 */
import type { AnnualAdmission, AnnualTuition, Program, QualityIssue, RegistryCatalogue, RegistrySnapshot, University } from "../types";
import { below, canonicalJson, fnv1a, rng } from "../util";

export type { RegistryCatalogue } from "../types";

export const FIXTURE_SNAPSHOT_ID = "fixture:university-ui-v1";
export const FIXTURE_IMPORTER_VERSION = "frontend-fixture-registry-v1";
export const FIXTURE_YEARS = [2022, 2023, 2024, 2025, 2026] as const;
const FEE_YEARS = [2025, 2026] as const;
const PROGRAM_SHEET = "Programlar";
const ANNUAL_SHEET = "Yıllık Uzun Format";

type Dept = { name: string; faculty: string; score: string | null; base: number; rank: number; popularity: number; english?: boolean };

const DEPARTMENTS: Dept[] = [
  { name: "Bilgisayar Mühendisliği", faculty: "Mühendislik Fakültesi", score: "SAY", base: 30, rank: 15000, popularity: 9, english: true },
  { name: "Makine Mühendisliği", faculty: "Mühendislik Fakültesi", score: "SAY", base: 26, rank: 60000, popularity: 5 },
  { name: "Tıp", faculty: "Tıp Fakültesi", score: "SAY", base: 22, rank: 8000, popularity: 10, english: true },
  { name: "Mimarlık", faculty: "Mimarlık Fakültesi", score: "SAY", base: 16, rank: 70000, popularity: 4 },
  { name: "Hukuk", faculty: "Hukuk Fakültesi", score: "EA", base: 26, rank: 20000, popularity: 8 },
  { name: "İşletme", faculty: "İktisadi ve İdari Bilimler Fakültesi", score: "EA", base: 32, rank: 120000, popularity: 5, english: true },
  { name: "Psikoloji", faculty: "Fen-Edebiyat Fakültesi", score: "EA", base: 18, rank: 45000, popularity: 7 },
  { name: "Tarih", faculty: "Fen-Edebiyat Fakültesi", score: "SÖZ", base: 18, rank: 90000, popularity: 3 },
  { name: "Türk Dili ve Edebiyatı", faculty: "Fen-Edebiyat Fakültesi", score: "SÖZ", base: 16, rank: 85000, popularity: 3 },
  { name: "İngiliz Dili ve Edebiyatı", faculty: "Fen-Edebiyat Fakültesi", score: "DİL", base: 16, rank: 30000, popularity: 4, english: true },
  { name: "Mütercim ve Tercümanlık", faculty: "Fen-Edebiyat Fakültesi", score: "DİL", base: 14, rank: 25000, popularity: 4 },
  { name: "Bilgisayar Programcılığı", faculty: "Meslek Yüksekokulu", score: "TYT", base: 30, rank: 400000, popularity: 2 },
];

type UniSpec = { label: string; type: string | null; depts: number[]; variants: string[] | null };

/** variants === null: one state program per department with the source's state label. */
const UNIVERSITIES: UniSpec[] = [
  { label: "A", type: "Devlet", depts: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11], variants: null },
  { label: "B", type: "Devlet", depts: [0, 1, 2, 4, 5, 7, 8, 9, 10], variants: null },
  { label: "C", type: "Vakıf", depts: [0, 2, 4, 5, 6, 10], variants: ["Burslu", "%50 İndirimli", "Ücretli"] },
  { label: "D", type: "Vakıf", depts: [0, 1, 4, 5, 6, 9], variants: ["Burslu", "%25 İndirimli", "Ücretli"] },
  { label: "E", type: "Vakıf", depts: [0, 3, 4, 5, 7, 11], variants: ["Burslu", "%50 İndirimli"] },
  { label: "F", type: null, depts: [0, 4, 5, 9], variants: ["Burslu", "Ücretli"] },
];

const STATE_LABEL = "Devlet (Ücretsiz)";
const PAYMENT_RATE: Record<string, number> = { Burslu: 0, "%25 İndirimli": 0.75, "%50 İndirimli": 0.5, Ücretli: 1 };
const VARIANT_SHARE: Record<string, number> = { Burslu: 0.2, "%25 İndirimli": 0.25, "%50 İndirimli": 0.35, Ücretli: 0.3 };

/** Program popularity used only by the fixture preference generator (not part of the registry schema). */
export const FIXTURE_POPULARITY = new Map<string, number>();

let cached: RegistryCatalogue | null = null;

/** Cached for the session; the catalogue is immutable once built. */
export function buildRegistryFixture(): RegistryCatalogue {
  if (!cached) cached = generateRegistryFixture();
  return cached;
}

/** Pure, uncached generator (same output on every call). */
export function generateRegistryFixture(): RegistryCatalogue {
  const draw = rng(20261121, "fixture:registry:v1");
  const universities: University[] = [];
  const programs: Program[] = [];
  const admissions: AnnualAdmission[] = [];
  const tuition: AnnualTuition[] = [];
  const issues: QualityIssue[] = [];
  let programId = 0;
  let admissionId = 0;
  let tuitionId = 0;
  let annualRow = 1;

  const issue = (i: Omit<QualityIssue, "issue_id" | "snapshot_id" | "issue_key" | "review_status" | "resolution">) => {
    issues.push({
      ...i, issue_id: issues.length + 1, snapshot_id: FIXTURE_SNAPSHOT_ID, review_status: "open", resolution: null,
      issue_key: canonicalJson([i.source_sheet, i.source_row, i.source_column, i.issue_code, i.related_year]),
    });
  };

  UNIVERSITIES.forEach((spec, u) => {
    const name = spec.type === "Devlet" ? `Synthetic State University ${spec.label}`
      : spec.type === "Vakıf" ? `Synthetic Foundation University ${spec.label}` : `Synthetic Institute ${spec.label}`;
    const university: University = {
      university_id: u + 1, snapshot_id: FIXTURE_SNAPSHOT_ID, university_key: `fixture-name:${fnv1a(name)}`,
      name_original: name, name_normalized: name, official_university_code: null, university_type: spec.type, city: null,
    };
    universities.push(university);
    for (const d of spec.depts) {
      const dept = DEPARTMENTS[d];
      for (const variant of spec.variants ?? [STATE_LABEL]) {
        programId += 1;
        const code = `00${String(u + 1)}${String(d + 1).padStart(2, "0")}${String((spec.variants ?? [STATE_LABEL]).indexOf(variant) + 1).padStart(2, "0")}01`;
        const english = !!dept.english && (spec.type !== "Devlet" || draw() < 0.4);
        // One deliberately incomplete program: no score type in the source.
        const score = spec.label === "F" && d === 9 ? null : dept.score;
        const program: Program = {
          program_id: programId, snapshot_id: FIXTURE_SNAPSHOT_ID, university_id: university.university_id, program_code: code,
          name_original: dept.name, faculty: dept.faculty, degree_level: null, score_type: score,
          scholarship_original: variant, teaching_language: english ? "İngilizce" : null,
          source_sheet: PROGRAM_SHEET, source_row: programId + 1,
        };
        programs.push(program);
        FIXTURE_POPULARITY.set(code, dept.popularity * (variant === "Burslu" ? 1.6 : variant === "Ücretli" ? 0.6 : 1) * (spec.type === "Devlet" ? 1.3 : 1));

        const opens = draw() < 0.15 ? 2024 : 2022;
        const share = spec.variants ? VARIANT_SHARE[variant] ?? 0.3 : 1;
        const base = Math.max(2, Math.round(dept.base * share * (0.8 + draw() * 0.4)));
        for (const year of FIXTURE_YEARS) {
          if (year < opens) continue;
          const row = ++annualRow;
          // A quarantined annual row: the importer rejects it, so no admission row exists for that year.
          if (spec.label === "D" && d === 6 && variant === "Burslu" && year === 2023) {
            issue({ severity: "error", issue_code: "invalid_annual", message: "Invalid integer measure: 'on beş'", source_sheet: ANNUAL_SHEET,
              source_row: row, source_column: "Kontenjan", raw_value: JSON.stringify({ Kontenjan: "on beş", Yıl: year }), program_id: program.program_id, related_year: year });
            continue;
          }
          const quota = Math.max(1, base + below(draw, 3) - 1);
          let placed = spec.variants ? Math.max(0, quota - below(draw, Math.max(1, Math.ceil(quota * 0.3)))) : quota;
          if (!spec.variants && draw() < 0.35) placed = quota + 1 + below(draw, 4);
          const quotaValue = spec.label === "B" && d === 5 && year === 2025 ? null : quota;
          let rank: number | null = placed === 0 ? null : Math.round(dept.rank * (spec.variants ? 1.4 + (PAYMENT_RATE[variant] ?? 1) : 1) * (0.85 + draw() * 0.3) * (1 + (2026 - year) * 0.03));
          if (year === 2026 && draw() < 0.18) rank = null;
          admissions.push({
            admission_id: ++admissionId, program_id: program.program_id, snapshot_id: FIXTURE_SNAPSHOT_ID, admission_year: year,
            quota: quotaValue, placed_students: placed, success_rank: rank, source_sheet: ANNUAL_SHEET, source_row: row,
          });
          if (quotaValue !== null && placed > quotaValue) {
            issue({ severity: "warning", issue_code: "placed_above_quota", message: "Source placed count exceeds displayed quota; preserved unchanged",
              source_sheet: ANNUAL_SHEET, source_row: row, source_column: null,
              raw_value: JSON.stringify({ Kontenjan: quotaValue, Yerleşen: placed, Yıl: year }), program_id: program.program_id, related_year: year });
          }
        }
        for (const feeYear of FEE_YEARS) {
          let full: number | null = null;
          let net: number | null = null;
          let basis: Record<string, unknown> = { academic_year_boundaries: "unverified", fee_year_label: String(feeYear) };
          if (spec.variants) {
            const missing = feeYear === 2025 && draw() < 0.12;
            if (!missing) {
              const annual = Math.round((250000 + dept.popularity * 30000 + below(draw, 40) * 1000) * (feeYear === 2026 ? 1.3 : 1));
              full = annual * 100;
              net = Math.round(annual * (PAYMENT_RATE[variant] ?? 1)) * 100;
              basis = { ...basis, net: "source-derived: full fee × payment rate (calculated upstream)" };
            } else {
              basis = { ...basis, note: "no fee supplied in source" };
            }
          } else {
            basis = { ...basis, note: "state program; the source omits fees and labels it Devlet (Ücretsiz)" };
          }
          tuition.push({
            tuition_id: ++tuitionId, program_id: program.program_id, snapshot_id: FIXTURE_SNAPSHOT_ID, academic_year_start: feeYear,
            full_amount_minor: full, net_amount_minor: net, currency: "TRY", fee_basis: canonicalJson(basis), source_sheet: PROGRAM_SHEET, source_row: program.source_row,
          });
        }
      }
    }
  });

  // An identical duplicate row collapsed by the importer (warning, data unchanged).
  const dup = programs.find((p) => p.name_original === "Hukuk" && p.university_id === 3) ?? programs[0];
  issue({ severity: "warning", issue_code: "duplicate_program", message: "Identical duplicate collapsed", source_sheet: PROGRAM_SHEET,
    source_row: programs.length + 2, source_column: null, raw_value: JSON.stringify({ "Program Kodu": dup.program_code }), program_id: dup.program_id, related_year: null });

  const years = [...new Set(admissions.map((a) => a.admission_year))].sort((a, b) => a - b);
  const snapshot: RegistrySnapshot = {
    snapshot_id: FIXTURE_SNAPSHOT_ID,
    source_filename: "synthetic-university-fixture (no workbook)",
    file_sha256: null,
    imported_at: "2026-11-21T00:00:00Z",
    importer_version: FIXTURE_IMPORTER_VERSION,
    source_description: "Synthetic frontend fixture shaped like the university SQLite registry (schema v1). Not imported from any source.",
    source_reference: null,
    retrieved_at: null,
    verification_status: "unverified",
    notes: "Invented institutions, programs, quotas, ranks and fees for UI development only.",
    origin: "fixture",
    admission_years: years,
    counts: { universities: universities.length, programs: programs.length, annual_admissions: admissions.length, annual_tuition: tuition.length, data_quality_issues: issues.length },
  };
  return { snapshot, universities, programs, admissions, tuition, issues };
}
