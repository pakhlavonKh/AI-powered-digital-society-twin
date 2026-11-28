/**
 * Normalized frontend types for the University Simulation dashboard.
 *
 * Registry types mirror the SQLite schema in `src/societytwin/university/db.py` (branch
 * `feature/university-sqlite`, schema version 1). Candidate and preference types mirror the handoff contract in
 * `src/societytwin/candidates/__init__.py` (`candidate-development-v1`). `null` always means unknown or missing;
 * an observed zero stays `0`.
 *
 * Simulation types (scenario, run, assignment) describe the browser-fixture explorer contract for `/university/*`.
 * Counterfactual placement and multi-semester APIs live under `/api/v2/placement/*` and `/api/v2/university/*`,
 * and read-only SQLite workbook endpoints live under `/api/v2/university-registry/*`.
 */

/** Where a record came from. `fixture` data is synthetic and was never imported from a source workbook. */
/** `local_preview`: development-only preview of local, git-ignored records (never committed or published). */
export type DataOrigin = "fixture" | "api" | "local_preview";

/** Explicit reasons a value is absent. A missing value is never rendered as zero. */
export type MissingReason =
  | "not_available"
  | "missing_from_source"
  | "not_applicable"
  | "not_calculated"
  | "pending_backend"
  | "not_in_schema";

// ---------------------------------------------------------------- registry (mirrors db.py)

export type VerificationStatus = "unverified" | "verified" | "rejected";

export type RegistrySnapshot = {
  snapshot_id: string;
  source_filename: string;
  /** Lowercase SHA-256 of the original workbook bytes; null for fixtures (no workbook exists). */
  file_sha256: string | null;
  /** UTC ISO-8601 import (or fixture build) timestamp. */
  imported_at: string;
  importer_version: string;
  source_description: string | null;
  source_reference: string | null;
  /** Source-reported retrieval date; never replaced by the import time. */
  retrieved_at: string | null;
  verification_status: VerificationStatus;
  notes: string | null;
  origin: DataOrigin;
  /** Distinct admission years present in annual_admissions for this snapshot, ascending. */
  admission_years: number[];
  counts: { universities: number; programs: number; annual_admissions: number; annual_tuition: number; data_quality_issues: number };
};

export type University = {
  university_id: number;
  snapshot_id: string;
  university_key: string;
  name_original: string;
  name_normalized: string;
  official_university_code: string | null;
  university_type: string | null;
  city: string | null;
};

export type Program = {
  program_id: number;
  snapshot_id: string;
  university_id: number;
  /** Text program code; leading zeros are significant. This is the durable identifier within a snapshot. */
  program_code: string;
  name_original: string;
  faculty: string | null;
  degree_level: string | null;
  score_type: string | null;
  scholarship_original: string | null;
  /** Exact source label; null means the source did not specify a language (never presumed Turkish). */
  teaching_language: string | null;
  source_sheet: string;
  source_row: number;
};

export type AnnualAdmission = {
  admission_id: number;
  program_id: number;
  snapshot_id: string;
  admission_year: number;
  /** Reported quota indicator, not a verified official capacity. */
  quota: number | null;
  /** Placed count; may exceed quota in the source and is never capped. */
  placed_students: number | null;
  /** Last placed candidate's success rank. */
  success_rank: number | null;
  source_sheet: string;
  source_row: number;
};

export type AnnualTuition = {
  tuition_id: number;
  program_id: number;
  snapshot_id: string;
  /** Source fee-year label; academic-year boundaries are unverified. */
  academic_year_start: number;
  full_amount_minor: number | null;
  /** Source-derived (full × payment rate, calculated upstream); not an independent observation. */
  net_amount_minor: number | null;
  currency: string;
  fee_basis: string | null;
  source_sheet: string;
  source_row: number;
};

export type IssueSeverity = "info" | "warning" | "error";

export type QualityIssue = {
  issue_id: number;
  snapshot_id: string;
  issue_key: string;
  severity: IssueSeverity;
  issue_code: string;
  message: string;
  source_sheet: string | null;
  source_row: number | null;
  source_column: string | null;
  raw_value: string | null;
  program_id: number | null;
  related_year: number | null;
  review_status: "open" | "resolved" | "accepted";
  resolution: string | null;
};

/** Every registry table for one snapshot. The registry is small (about 1,300 programs), so the UI can hold it. */
export type RegistryCatalogue = {
  snapshot: RegistrySnapshot;
  universities: University[];
  programs: Program[];
  admissions: AnnualAdmission[];
  tuition: AnnualTuition[];
  issues: QualityIssue[];
};

// ---------------------------------------------------------------- validation findings (frontend presentation)

/**
 * One validation finding, whatever produced it. `blocking` findings prevent the related operation (for example
 * running a scenario); non-blocking ones stay visible. Source import issues keep their importer code and key.
 */
export type Finding = {
  code: string;
  severity: IssueSeverity;
  message: string;
  origin: "source_import" | "frontend_check" | "simulation" | "scenario_validation";
  blocking: boolean;
  /** Human-readable record reference such as "Program 000010101" or "candidate-00000012". */
  record?: string;
  field?: string;
  detail?: string;
};

// ---------------------------------------------------------------- program explorer rows

/** One program in one admission year (or with no admission row when the program has none for that year). */
export type ProgramYearRow = {
  key: string;
  program: Program;
  university: University;
  admission: AnnualAdmission | null;
  issues: QualityIssue[];
};

export type ProgramSortKey = "university" | "program" | "year" | "quota" | "placed" | "success_rank" | "code";
export type SortDirection = "asc" | "desc";

/** Sentinel filter value selecting records whose field is null (missing in the source). */
export const MISSING_VALUE = "__missing__";

export type ProgramQuery = {
  snapshot_id: string;
  /** null = all years. */
  year: number | null;
  score_types: string[];
  scholarships: string[];
  university_keys: string[];
  university_types: string[];
  teaching_languages: string[];
  search: string;
  sort: ProgramSortKey;
  direction: SortDirection;
  offset: number;
  limit: number;
};

export type FacetValue = { value: string; label: string; count: number };

/** Filter options observed in the snapshot. Only fields with data are offered as filters. */
export type ProgramFacets = {
  years: number[];
  score_types: FacetValue[];
  scholarships: FacetValue[];
  universities: FacetValue[];
  university_types: FacetValue[];
  teaching_languages: FacetValue[];
  /** Cities are offered only when at least one university has a city (parser v1 infers none). */
  cities: FacetValue[];
};

export type ProgramPage = {
  items: ProgramYearRow[];
  total_matching: number;
  /** Matching rows whose quota is null (missing), so totals are never silently understated. */
  matching_missing_quota: number;
  /** Sum of known quotas among matching rows. */
  matching_known_quota: number;
  /** Counts over every matching row (not just this page), for the summary tiles. */
  summary: {
    /** Distinct program codes among matching rows. */
    programs: number;
    /** Distinct universities among matching rows. */
    universities: number;
    /** Matching rows whose scholarship label is a full scholarship or a tuition discount (see labels.ts). */
    scholarship_rows: number;
    /** Matching rows with a known (non-null) reported quota: the denominator of the average quota. */
    known_quota_rows: number;
  };
  offset: number;
  limit: number;
  facets: ProgramFacets;
};

export type ProgramDetail = {
  snapshot: RegistrySnapshot;
  program: Program;
  university: University;
  admissions: AnnualAdmission[];
  tuition: AnnualTuition[];
  issues: QualityIssue[];
};

// ---------------------------------------------------------------- candidates (mirrors candidates/__init__.py)

export type Achievement = { kind: string; value: number; scale: string };

export type Candidate = {
  candidate_id: string;
  age: number;
  home_location: string | null;
  score_type: string | null;
  achievement: Achievement | null;
  educational_interests: string[] | null;
  annual_budget_try: number | null;
};

export type Preference = {
  candidate_id: string;
  /** Registry program_code (text, leading zeros kept), interpreted with the manifest's registry_snapshot. */
  program_id: string;
  /** Positive, contiguous, one-based. */
  position: number;
};

export type CohortManifest = {
  cohort_id: string;
  generator_version: string;
  stream_version: string;
  configuration: { size: number; seed: number };
  data_versions: Record<string, string | null>;
  evidence: Record<string, string>;
  assumptions: Record<string, string>;
  preference_source: string;
  registry_snapshot: string | null;
  origin: DataOrigin;
  /** Free-text caveats specific to this frontend fixture. */
  fixture_notes?: string[];
};

/** A cohort handoff: manifest, candidates and ranked preferences (the JSON written by `python -m societytwin.candidates`). */
export type Cohort = { manifest: CohortManifest; candidates: Candidate[]; preferences: Preference[] };

export type CandidateStatusFilter = "placed" | "unplaced" | "ineligible";
/** Eligibility comes from the selected run: eligible = placed or not placed; ineligible = excluded by the simulation. */
export type CandidateEligibilityFilter = "eligible" | "ineligible";
export type CandidateSortKey = "proxy" | "rank" | "id" | "preferences";

export type CandidateQuery = {
  cohort_id: string;
  search: string;
  score_types: string[];
  proxy_min: number | null;
  proxy_max: number | null;
  /** Requires run_id; ignored without a run. */
  status: CandidateStatusFilter | null;
  /** Requires run_id; ignored without a run. */
  eligibility: CandidateEligibilityFilter | null;
  /** Home locations (provinces); only offered when the cohort records any. */
  provinces: string[];
  run_id: string | null;
  sort: CandidateSortKey;
  direction: SortDirection;
  offset: number;
  limit: number;
};

export type CandidateRow = {
  candidate: Candidate;
  /** Derived competition rank within the cohort by achievement proxy (1 = highest); ties share a rank. */
  cohort_rank: number | null;
  preference_count: number;
  /** Preferences whose program code exists in the registry snapshot (structural check only). */
  valid_reference_count: number;
  assignment: Assignment | null;
};

export type CandidatePage = {
  items: CandidateRow[];
  total_matching: number;
  offset: number;
  limit: number;
  score_types: FacetValue[];
  /** Home locations present in the cohort; empty when the cohort records none (then no province filter is offered). */
  provinces: FacetValue[];
  manifest: CohortManifest;
};

export type CandidateDetail = {
  manifest: CohortManifest;
  row: CandidateRow;
  preferences: Preference[];
  findings: Finding[];
};

// ---------------------------------------------------------------- simulation (PROVISIONAL contract)

export type PresetId = "baseline" | "quota_increase" | "quota_decrease" | "scholarship_change" | "preference_change" | "custom";

export type ScenarioConfig = {
  name: string;
  preset: PresetId;
  admission_year: number;
  registry_snapshot_id: string;
  cohort: { cohort_id: string; generator_version: string; seed: number; size: number };
  /** Simulation random seed (tie-breaking). */
  seed: number;
  /** Applied to every included program's reported quota, in percent (-50 means half). */
  quota_adjustment_pct: number;
  /** Absolute capacity overrides by program_code; applied after the percentage adjustment. */
  program_quota_overrides: Record<string, number>;
  /** null = every university in the snapshot. */
  included_university_keys: string[] | null;
};

export type RunStatus = "pending" | "running" | "completed" | "failed";
export type AssignmentStatus = "placed" | "unplaced" | "ineligible";

export type PreferenceOutcome =
  | "assigned"
  | "full"
  | "ineligible_score_type"
  | "invalid_reference"
  | "excluded_by_scenario"
  | "capacity_unknown"
  | "not_reached";

export type Assignment = {
  candidate_id: string;
  status: AssignmentStatus;
  program_code: string | null;
  preference_position: number | null;
  /** Reason code supplied by the simulation; null when the simulation gave none (the UI never infers one). */
  reason_code: string | null;
  reason: string | null;
  /** Per-preference outcomes, when the simulation supplies them. */
  evaluated: { position: number; program_code: string; outcome: PreferenceOutcome }[] | null;
};

export type ProgramCapacity = {
  program_code: string;
  /** Reported quota for the scenario year (null = missing in the source or no admission row). */
  base_quota: number | null;
  /** Capacity used by the simulation after adjustments (null = not allocatable). */
  capacity: number | null;
  placed: number;
};

export type RunProvenance = {
  engine: string;
  engine_version: string | null;
  simulation_seed: number;
  registry_snapshot_id: string;
  cohort_id: string;
  cohort_generator_version: string;
  cohort_seed: number;
  cohort_size: number;
  config_hash: string;
  created_at: string;
};

export type SimulationRun = {
  run_id: string;
  status: RunStatus;
  origin: DataOrigin;
  /** Built-in fixture runs are listed by default; session runs were previewed in this browser session. */
  kind: "builtin_fixture" | "session_fixture" | "api";
  config: ScenarioConfig;
  provenance: RunProvenance;
  assignments: Assignment[];
  capacities: ProgramCapacity[];
  findings: Finding[];
  error: string | null;
};

export type RunListItem = Pick<SimulationRun, "run_id" | "status" | "origin" | "kind"> & {
  name: string;
  preset: PresetId;
  admission_year: number;
  cohort_id: string;
  cohort_size: number;
  created_at: string;
};

/** What the active data source can do, shown to the user instead of hiding unavailable features. */
export type UniversityCapabilities = {
  origin: DataOrigin;
  registry: { available: boolean; detail: string };
  candidates: { available: boolean; detail: string };
  execution: { mode: "fixture_preview" | "api" | "unavailable"; detail: string };
  supported_presets: PresetId[];
  unsupported_presets: { preset: PresetId; reason: string }[];
  limits: { max_cohort_size: number; quota_adjustment_pct: [number, number] };
};
