import { preferenceChecks } from "./quality";
import type {
  Assignment,
  CandidateDetail,
  CandidateEligibilityFilter,
  CandidatePage,
  CandidateQuery,
  CandidateRow,
  CandidateSortKey,
  CandidateStatusFilter,
  Cohort,
  FacetValue,
  PreferenceOutcome,
  RegistryCatalogue,
  SimulationRun,
  SortDirection,
} from "./types";
import { pageSizeFromParam } from "./programs";
import { compareText, foldTr, scoreTypeKey } from "./util";

export const CANDIDATE_PAGE_SIZE = 25;
export const CANDIDATE_SORTS: { key: CandidateSortKey; label: string }[] = [
  { key: "proxy", label: "Achievement proxy" },
  { key: "rank", label: "Cohort rank (derived)" },
  { key: "id", label: "Candidate ID" },
  { key: "preferences", label: "Preference count" },
];

/** Competition rank by achievement proxy (1 = highest; equal values share a rank). Derived, not a YKS rank. */
export function cohortRanks(cohort: Cohort): Map<string, number | null> {
  const values = cohort.candidates.map((c) => c.achievement?.value ?? null).filter((v): v is number => v !== null).sort((a, b) => b - a);
  const firstIndex = new Map<number, number>();
  values.forEach((v, i) => { if (!firstIndex.has(v)) firstIndex.set(v, i + 1); });
  return new Map(cohort.candidates.map((c) => [c.candidate_id, c.achievement ? firstIndex.get(c.achievement.value) ?? null : null]));
}

export function candidateRows(cohort: Cohort, catalogue: RegistryCatalogue, run: SimulationRun | null): CandidateRow[] {
  const codes = new Set(catalogue.programs.map((p) => p.program_code));
  const ranks = cohortRanks(cohort);
  const counts = new Map<string, { all: number; valid: number }>();
  for (const p of cohort.preferences) {
    const c = counts.get(p.candidate_id) ?? { all: 0, valid: 0 };
    c.all += 1;
    if (codes.has(p.program_id)) c.valid += 1;
    counts.set(p.candidate_id, c);
  }
  const assignments = new Map((run?.assignments ?? []).map((a) => [a.candidate_id, a]));
  return cohort.candidates.map((candidate) => ({
    candidate, cohort_rank: ranks.get(candidate.candidate_id) ?? null,
    preference_count: counts.get(candidate.candidate_id)?.all ?? 0, valid_reference_count: counts.get(candidate.candidate_id)?.valid ?? 0,
    assignment: assignments.get(candidate.candidate_id) ?? null,
  }));
}

function sortValue(r: CandidateRow, key: CandidateSortKey): number | string | null {
  switch (key) {
    case "proxy": return r.candidate.achievement?.value ?? null;
    case "rank": return r.cohort_rank;
    case "id": return r.candidate.candidate_id;
    case "preferences": return r.preference_count;
  }
}

export function queryCandidateRows(rows: CandidateRow[], q: CandidateQuery, cohort: Cohort): CandidatePage {
  const needle = foldTr(q.search);
  const filtered = rows.filter((r) =>
    (needle === "" || foldTr(r.candidate.candidate_id).includes(needle))
    && (q.score_types.length === 0 || q.score_types.includes(r.candidate.score_type ?? ""))
    && (q.proxy_min === null || (r.candidate.achievement !== null && r.candidate.achievement.value >= q.proxy_min))
    && (q.proxy_max === null || (r.candidate.achievement !== null && r.candidate.achievement.value <= q.proxy_max))
    && (q.status === null || q.run_id === null || r.assignment?.status === q.status)
    && (q.eligibility === null || q.run_id === null
      || (q.eligibility === "ineligible" ? r.assignment?.status === "ineligible" : r.assignment?.status === "placed" || r.assignment?.status === "unplaced"))
    && (q.provinces.length === 0 || (r.candidate.home_location !== null && q.provinces.includes(r.candidate.home_location))));
  const sign = q.direction === "asc" ? 1 : -1;
  filtered.sort((a, b) => {
    const av = sortValue(a, q.sort);
    const bv = sortValue(b, q.sort);
    if (av === null && bv !== null) return 1;
    if (bv === null && av !== null) return -1;
    if (av !== null && bv !== null && av !== bv) {
      const c = typeof av === "number" && typeof bv === "number" ? av - bv : compareText(String(av), String(bv));
      if (c !== 0) return sign * c;
    }
    return a.candidate.candidate_id < b.candidate.candidate_id ? -1 : 1;
  });
  const limit = Math.max(1, q.limit);
  const lastOffset = Math.max(0, Math.floor((filtered.length - 1) / limit) * limit);
  const offset = Math.min(Math.max(0, q.offset), lastOffset);
  const typeCounts = new Map<string, number>();
  for (const r of rows) if (r.candidate.score_type) typeCounts.set(r.candidate.score_type, (typeCounts.get(r.candidate.score_type) ?? 0) + 1);
  const score_types: FacetValue[] = [...typeCounts.entries()].map(([value, count]) => ({ value, label: value, count })).sort((a, b) => compareText(a.label, b.label));
  const provinceCounts = new Map<string, number>();
  for (const r of rows) if (r.candidate.home_location) provinceCounts.set(r.candidate.home_location, (provinceCounts.get(r.candidate.home_location) ?? 0) + 1);
  const provinces: FacetValue[] = [...provinceCounts.entries()].map(([value, count]) => ({ value, label: value, count })).sort((a, b) => compareText(a.label, b.label));
  return { items: filtered.slice(offset, offset + limit), total_matching: filtered.length, offset, limit, score_types, provinces, manifest: cohort.manifest };
}

export function candidateDetail(cohort: Cohort, catalogue: RegistryCatalogue, run: SimulationRun | null, candidateId: string): CandidateDetail | null {
  const row = candidateRows(cohort, catalogue, run).find((r) => r.candidate.candidate_id === candidateId);
  if (!row) return null;
  const preferences = cohort.preferences.filter((p) => p.candidate_id === candidateId).sort((a, b) => a.position - b.position);
  const findings = preferenceChecks(candidateId, preferences, new Set(catalogue.programs.map((p) => p.program_code)));
  if (row.candidate.score_type === null) {
    findings.push({ code: "missing_score_type", severity: "warning", origin: "frontend_check", blocking: false, record: candidateId,
      message: "The candidate has no score type." });
  }
  return { manifest: cohort.manifest, row, preferences, findings };
}

// ---------------------------------------------------------------- preference list view

export const OUTCOME_LABELS: Record<PreferenceOutcome, { label: string; tone: "good" | "warn" | "crit" | "neutral" | "info" }> = {
  assigned: { label: "Placed here", tone: "good" },
  full: { label: "Not placed: full at this candidate's turn", tone: "warn" },
  ineligible_score_type: { label: "Not eligible: score type does not match", tone: "neutral" },
  invalid_reference: { label: "Invalid: program not in registry snapshot", tone: "crit" },
  excluded_by_scenario: { label: "Not in this scenario's programs", tone: "neutral" },
  capacity_unknown: { label: "Not allocatable: quota missing for this year", tone: "warn" },
  not_reached: { label: "Not evaluated: placed at an earlier preference", tone: "info" },
};

export type PreferenceView = {
  position: number;
  program_code: string;
  university: string | null;
  program: string | null;
  program_score_type: string | null;
  scholarship: string | null;
  /** Structural reference check, done in the UI (the same rule as validate_handoff). */
  reference_valid: boolean;
  /** Score-type comparison, informational only; eligibility is decided by the simulation. */
  score_type_matches: boolean | null;
  /** Supplied by the selected run; null when no run is selected or the run gave no per-preference outcome. */
  outcome: PreferenceOutcome | null;
};

export function preferenceViews(detail: CandidateDetail, catalogue: RegistryCatalogue, assignment: Assignment | null): PreferenceView[] {
  const programs = new Map(catalogue.programs.map((p) => [p.program_code, p]));
  const unis = new Map(catalogue.universities.map((u) => [u.university_id, u]));
  const outcomes = new Map((assignment?.evaluated ?? []).map((e) => [e.position, e.outcome]));
  return detail.preferences.map((pref) => {
    const p = programs.get(pref.program_id);
    return {
      position: pref.position, program_code: pref.program_id, university: p ? unis.get(p.university_id)?.name_original ?? null : null,
      program: p?.name_original ?? null, program_score_type: p?.score_type ?? null, scholarship: p?.scholarship_original ?? null,
      reference_valid: !!p,
      score_type_matches: p ? scoreTypeKey(p.score_type) !== null && scoreTypeKey(p.score_type) === scoreTypeKey(detail.row.candidate.score_type) : null,
      outcome: outcomes.get(pref.position) ?? null,
    };
  });
}

// ---------------------------------------------------------------- URL state

export type CandidateUrlState = { search: string; score_types: string[]; proxy_min: number | null; proxy_max: number | null;
  status: CandidateStatusFilter | null; eligibility: CandidateEligibilityFilter | null; provinces: string[];
  sort: CandidateSortKey; direction: SortDirection; page: number; size: number };

export function defaultCandidateState(): CandidateUrlState {
  return { search: "", score_types: [], proxy_min: null, proxy_max: null, status: null, eligibility: null, provinces: [],
    sort: "proxy", direction: "desc", page: 0, size: CANDIDATE_PAGE_SIZE };
}

export function candidateStateFromParams(params: URLSearchParams): CandidateUrlState {
  const num = (v: string | null) => (v !== null && v !== "" && Number.isFinite(Number(v)) ? Number(v) : null);
  const status = params.get("status");
  const eligibility = params.get("elig");
  const sort = params.get("sort");
  const page = Number(params.get("page") ?? "1");
  return {
    search: params.get("q") ?? "", score_types: params.getAll("score").filter(Boolean),
    proxy_min: num(params.get("min")), proxy_max: num(params.get("max")),
    status: status === "placed" || status === "unplaced" || status === "ineligible" ? status : null,
    eligibility: eligibility === "eligible" || eligibility === "ineligible" ? eligibility : null,
    provinces: params.getAll("prov").filter(Boolean),
    sort: CANDIDATE_SORTS.some((s) => s.key === sort) ? (sort as CandidateSortKey) : "proxy",
    direction: params.get("dir") === "asc" ? "asc" : "desc",
    page: Number.isInteger(page) && page >= 1 ? page - 1 : 0,
    size: pageSizeFromParam(params.get("size"), CANDIDATE_PAGE_SIZE),
  };
}

export function candidateStateToParams(state: CandidateUrlState, base?: URLSearchParams): URLSearchParams {
  const params = new URLSearchParams(base?.toString() ?? "");
  for (const p of ["q", "score", "min", "max", "status", "elig", "prov", "sort", "dir", "page", "size"]) params.delete(p);
  if (state.search) params.set("q", state.search);
  for (const s of state.score_types) params.append("score", s);
  if (state.proxy_min !== null) params.set("min", String(state.proxy_min));
  if (state.proxy_max !== null) params.set("max", String(state.proxy_max));
  if (state.status) params.set("status", state.status);
  if (state.eligibility) params.set("elig", state.eligibility);
  for (const p of state.provinces) params.append("prov", p);
  if (state.sort !== "proxy") params.set("sort", state.sort);
  if (state.direction === "asc") params.set("dir", "asc");
  if (state.page > 0) params.set("page", String(state.page + 1));
  if (state.size !== CANDIDATE_PAGE_SIZE) params.set("size", String(state.size));
  return params;
}
