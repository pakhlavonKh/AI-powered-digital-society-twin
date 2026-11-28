import {
  MISSING_VALUE,
  type RegistryCatalogue,
  type FacetValue,
  type ProgramFacets,
  type ProgramPage,
  type ProgramQuery,
  type ProgramSortKey,
  type ProgramYearRow,
  type SortDirection,
} from "./types";
import { scholarshipKind } from "./labels";
import { compareText, foldTr } from "./util";

export const PROGRAM_PAGE_SIZE = 25;
/** Rows-per-page choices offered by the explorers (the URL accepts only these). */
export const PAGE_SIZES = [10, 25, 50, 100] as const;
export const PROGRAM_SORTS: { key: ProgramSortKey; label: string }[] = [
  { key: "university", label: "University" },
  { key: "program", label: "Program" },
  { key: "year", label: "Year" },
  { key: "quota", label: "Quota" },
  { key: "placed", label: "Placed" },
  { key: "success_rank", label: "Admission rank" },
  { key: "code", label: "Program code" },
];

/** One row per (program, admission year). With `year === null`, every observed year plus programs with no rows. */
export function programRows(catalogue: RegistryCatalogue, year: number | null): ProgramYearRow[] {
  const uniById = new Map(catalogue.universities.map((u) => [u.university_id, u]));
  const admissionsByProgram = new Map<number, typeof catalogue.admissions>();
  for (const a of catalogue.admissions) {
    const list = admissionsByProgram.get(a.program_id) ?? [];
    list.push(a);
    admissionsByProgram.set(a.program_id, list);
  }
  const issuesByProgram = new Map<number, typeof catalogue.issues>();
  for (const i of catalogue.issues) {
    if (i.program_id === null) continue;
    const list = issuesByProgram.get(i.program_id) ?? [];
    list.push(i);
    issuesByProgram.set(i.program_id, list);
  }
  const rows: ProgramYearRow[] = [];
  for (const program of catalogue.programs) {
    const university = uniById.get(program.university_id);
    if (!university) continue; // reported by the quality checks as a missing university identifier
    const all = admissionsByProgram.get(program.program_id) ?? [];
    const issues = issuesByProgram.get(program.program_id) ?? [];
    const selected = year === null ? all : all.filter((a) => a.admission_year === year);
    if (selected.length === 0 && year === null) {
      rows.push({ key: `${program.program_code}:none`, program, university, admission: null, issues });
    }
    for (const admission of selected) {
      rows.push({ key: `${program.program_code}:${admission.admission_year}`, program, university, admission,
        issues: issues.filter((i) => i.related_year === null || i.related_year === admission.admission_year) });
    }
  }
  return rows;
}

/** Programs in the catalogue that have no admission row for `year` (not shown for that year; absence is not zero). */
export function programsWithoutYear(catalogue: RegistryCatalogue, year: number): number {
  const withYear = new Set(catalogue.admissions.filter((a) => a.admission_year === year).map((a) => a.program_id));
  return catalogue.programs.filter((p) => !withYear.has(p.program_id)).length;
}

function matchesList(value: string | null, wanted: string[]): boolean {
  if (wanted.length === 0) return true;
  return wanted.includes(value === null ? MISSING_VALUE : value);
}

export function filterProgramRows(rows: ProgramYearRow[], q: Omit<ProgramQuery, "sort" | "direction" | "offset" | "limit" | "snapshot_id" | "year">): ProgramYearRow[] {
  const needle = foldTr(q.search);
  return rows.filter((r) =>
    matchesList(r.program.score_type, q.score_types)
    && matchesList(r.program.scholarship_original, q.scholarships)
    && matchesList(r.university.university_key, q.university_keys)
    && matchesList(r.university.university_type, q.university_types)
    && matchesList(r.program.teaching_language, q.teaching_languages)
    && (needle === "" || foldTr(`${r.university.name_original} ${r.program.name_original} ${r.program.faculty ?? ""} ${r.program.program_code}`).includes(needle)));
}

function sortValue(r: ProgramYearRow, key: ProgramSortKey): string | number | null {
  switch (key) {
    case "university": return r.university.name_original;
    case "program": return r.program.name_original;
    case "year": return r.admission?.admission_year ?? null;
    case "quota": return r.admission?.quota ?? null;
    case "placed": return r.admission?.placed_students ?? null;
    case "success_rank": return r.admission?.success_rank ?? null;
    case "code": return r.program.program_code;
  }
}

/**
 * Deterministic: missing values always sort last (in both directions), then ties break by program code and year,
 * so the same query always yields the same order and pages never overlap.
 */
export function sortProgramRows(rows: ProgramYearRow[], key: ProgramSortKey, direction: SortDirection): ProgramYearRow[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = sortValue(a, key);
    const bv = sortValue(b, key);
    if (av === null && bv !== null) return 1;
    if (bv === null && av !== null) return -1;
    if (av !== null && bv !== null && av !== bv) {
      const c = typeof av === "number" && typeof bv === "number" ? av - bv : compareText(String(av), String(bv));
      if (c !== 0) return sign * c;
    }
    if (a.program.program_code !== b.program.program_code) return a.program.program_code < b.program.program_code ? -1 : 1;
    return (a.admission?.admission_year ?? 0) - (b.admission?.admission_year ?? 0);
  });
}

function facet(values: (string | null)[], label: (v: string) => string = (v) => v): FacetValue[] {
  const counts = new Map<string, number>();
  for (const v of values) counts.set(v ?? MISSING_VALUE, (counts.get(v ?? MISSING_VALUE) ?? 0) + 1);
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count, label: value === MISSING_VALUE ? "Missing from source" : label(value) }))
    .sort((a, b) => (a.value === MISSING_VALUE ? 1 : b.value === MISSING_VALUE ? -1 : compareText(a.label, b.label)));
}

/** Options are the values present in the snapshot (counted per program), never a hardcoded list. */
export function programFacets(catalogue: RegistryCatalogue): ProgramFacets {
  const uniById = new Map(catalogue.universities.map((u) => [u.university_id, u]));
  const programs = catalogue.programs;
  const unis = programs.map((p) => uniById.get(p.university_id)).filter((u): u is NonNullable<typeof u> => !!u);
  const names = new Map(catalogue.universities.map((u) => [u.university_key, u.name_original]));
  const cities = catalogue.universities.some((u) => u.city !== null) ? facet(catalogue.universities.map((u) => u.city)) : [];
  return {
    years: [...catalogue.snapshot.admission_years],
    score_types: facet(programs.map((p) => p.score_type)),
    scholarships: facet(programs.map((p) => p.scholarship_original)),
    universities: facet(unis.map((u) => u.university_key), (k) => names.get(k) ?? k),
    university_types: facet(unis.map((u) => u.university_type)),
    teaching_languages: facet(programs.map((p) => p.teaching_language)).map((f) => f.value === MISSING_VALUE ? { ...f, label: "Not specified in source" } : f),
    cities,
  };
}

export function queryProgramRows(catalogue: RegistryCatalogue, q: ProgramQuery): ProgramPage {
  const filtered = sortProgramRows(filterProgramRows(programRows(catalogue, q.year), q), q.sort, q.direction);
  const limit = Math.max(1, q.limit);
  const lastOffset = Math.max(0, Math.floor((filtered.length - 1) / limit) * limit);
  const offset = Math.min(Math.max(0, q.offset), lastOffset);
  let missing = 0;
  let known = 0;
  let scholarship = 0;
  const programs = new Set<string>();
  const universities = new Set<number>();
  for (const r of filtered) {
    if (r.admission?.quota === null || r.admission?.quota === undefined) missing += 1;
    else known += r.admission.quota;
    const kind = scholarshipKind(r.program.scholarship_original);
    if (kind === "full" || kind === "discount") scholarship += 1;
    programs.add(r.program.program_code);
    universities.add(r.university.university_id);
  }
  return {
    items: filtered.slice(offset, offset + limit), total_matching: filtered.length, matching_missing_quota: missing,
    matching_known_quota: known, offset, limit, facets: programFacets(catalogue),
    summary: { programs: programs.size, universities: universities.size, scholarship_rows: scholarship, known_quota_rows: filtered.length - missing },
  };
}

// ---------------------------------------------------------------- URL state

type ListKey = "score_types" | "scholarships" | "university_keys" | "university_types" | "teaching_languages";
const LIST_PARAMS: [ListKey, string][] = [
  ["score_types", "score"], ["scholarships", "scholarship"], ["university_keys", "university"],
  ["university_types", "type"], ["teaching_languages", "lang"],
];

export type ProgramUrlState = Omit<ProgramQuery, "snapshot_id" | "limit" | "offset"> & { page: number; size: number };

/** `size` from the URL when it is one of PAGE_SIZES; otherwise the default. */
export function pageSizeFromParam(value: string | null, fallback = PROGRAM_PAGE_SIZE): number {
  const n = Number(value);
  return (PAGE_SIZES as readonly number[]).includes(n) ? n : fallback;
}

export function defaultProgramState(latestYear: number | null): ProgramUrlState {
  return { year: latestYear, score_types: [], scholarships: [], university_keys: [], university_types: [], teaching_languages: [],
    search: "", sort: "university", direction: "asc", page: 0, size: PROGRAM_PAGE_SIZE };
}

/** `year` absent → latest year; `year=all` → every year. Unknown sort keys fall back to the default. */
export function programStateFromParams(params: URLSearchParams, latestYear: number | null): ProgramUrlState {
  const state = defaultProgramState(latestYear);
  const y = params.get("year");
  if (y === "all") state.year = null;
  else if (y !== null && /^\d{4}$/.test(y)) state.year = Number(y);
  for (const [key, param] of LIST_PARAMS) state[key] = params.getAll(param).filter(Boolean);
  state.search = params.get("q") ?? "";
  const sort = params.get("sort");
  if (sort && PROGRAM_SORTS.some((s) => s.key === sort)) state.sort = sort as ProgramSortKey;
  if (params.get("dir") === "desc") state.direction = "desc";
  const page = Number(params.get("page") ?? "1");
  state.page = Number.isInteger(page) && page >= 1 ? page - 1 : 0;
  state.size = pageSizeFromParam(params.get("size"));
  return state;
}

export function programStateToParams(state: ProgramUrlState, latestYear: number | null, base?: URLSearchParams): URLSearchParams {
  const params = new URLSearchParams(base?.toString() ?? "");
  for (const p of ["year", "q", "sort", "dir", "page", "size", ...LIST_PARAMS.map(([, p]) => p)]) params.delete(p);
  if (state.year === null) params.set("year", "all");
  else if (state.year !== latestYear) params.set("year", String(state.year));
  for (const [key, param] of LIST_PARAMS) for (const v of state[key]) params.append(param, v);
  if (state.search) params.set("q", state.search);
  if (state.sort !== "university") params.set("sort", state.sort);
  if (state.direction === "desc") params.set("dir", "desc");
  if (state.page > 0) params.set("page", String(state.page + 1));
  if (state.size !== PROGRAM_PAGE_SIZE) params.set("size", String(state.size));
  return params;
}

export function isFiltered(state: ProgramUrlState, latestYear: number | null): boolean {
  return programStateToParams({ ...state, sort: "university", direction: "asc", page: 0, size: PROGRAM_PAGE_SIZE }, latestYear).toString() !== "";
}
