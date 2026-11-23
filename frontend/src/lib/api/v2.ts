import { ApiError, toApiError } from "./client";

/**
 * Typed client for /api/v2 (the national pipeline). Requests go to the page's own origin; Next forwards
 * them to the local API. The types mirror societytwin.national.service; null always means "unknown".
 */

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

function qs(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export async function v2<T>(path: string, opts: { query?: Query; body?: unknown; method?: "GET" | "POST"; signal?: AbortSignal } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v2${path}${qs(opts.query)}`, {
      method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
      headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (err) {
    throw toApiError(err);
  }
  const text = await response.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!response.ok) {
    const env = (data ?? {}) as { error?: { code?: string; message?: string; details?: unknown; request_id?: string } };
    throw new ApiError(response.status, env.error?.code ?? `http_${response.status}`, env.error?.message ?? `Request failed (${response.status})`,
      env.error?.details, env.error?.request_id);
  }
  return data as T;
}

// ---------------------------------------------------------------- shared
export type Scope = {
  label: string; scope_code: string; requested_provinces: string[] | "all"; provinces_with_records: string[];
  province_count: number; province_reference_count: number; excluded_count: number;
};
export type Weights = { sum: number; mean: number; min: number; max: number; cv: number; kish_design_effect: number; definition: string };
export type PopulationListItem = {
  population_id: string; generated_at: string; reference_year: number; seed: number; synthetic_size: number; scope: Scope;
  represented_population: number; generator_version: string; weights: Weights; timings: { generation_seconds: number } | null;
  label: string; controls_fingerprint: string;
};
export type PopulationList = { items: PopulationListItem[]; default_population_id: string | null };

export type FieldEvidence = {
  evidence: string; table_id?: string; source_year?: number; geo_level?: string; source_ids?: string[]; method?: string;
  method_text?: string; conditioning?: string[]; unobserved_joint_with?: string[]; limitations?: string[]; reason?: string;
  universe_min_age?: number | null; universe_note?: string; structural_zeros?: boolean;
};
export type Profile = { profile_id: string; province_code: string; province_name: string; reference_year: number;
  fields: Record<string, FieldEvidence>; source_years: Record<string, number> };

export type PopulationDetail = PopulationListItem & {
  excluded_provinces: { province_code: string; province_name: string; reason: string }[];
  allocation: { method: string; rule: string; min_records_per_province: number;
    provinces: { province_code: string; province_name: string; records: number; population: number; root_year?: number;
      collapsed_cells?: { cell: string[]; population: number; into: string[] | null }[] }[] };
  calibration: { province_code: string; calibrated: boolean; converged: boolean; iterations: number; max_relative_error: number;
    margins: string[]; unreachable_cells: unknown[]; weight_ratio_min: number; weight_ratio_max: number }[];
  profiles: Record<string, Profile>;
  dependency_model: { nodes: { id: string; kind: string; evidence?: string; options?: { table_id: string; method: string }[] }[];
    edges: { from: string; to: string; basis: string }[]; not_modelled: Record<string, string>; methods: Record<string, string> };
  constraint_rules: { rule_id: string; kind: string; fields: string[]; description: string; justification: string }[];
  fields_not_modelled: Record<string, string>; source_versions: { controls_fingerprint: string; sources: Source[] };
  content_sha256: string; config: Record<string, unknown>; files: Record<string, { sha256: string; bytes: number }>;
};

export type Category = { value: string; label: string; records: number; weighted: number; weighted_share: number | null; record_share: number | null };
export type Distribution = { field: string; records: number; weighted_total: number; categories: Category[]; available: boolean; note: string | null };
export type ProvinceCount = { province_code: string; province_name: string; records: number; weighted: number };
export type PyramidRow = { age_group: string; male_weighted: number; female_weighted: number; male_records: number; female_records: number };
export type Summary = {
  population_id: string; filters: Record<string, unknown>; records: number; total_records: number; represented_population: number;
  reference_year: number; provinces: ProvinceCount[]; distributions: Distribution[]; pyramid: PyramidRow[]; scope: Scope;
  source_years: { province_code: string; province_name: string; reference_year: number; source_years: Record<string, number> }[];
  weighting: string; label: string;
};

export type RecordRow = Record<string, string | number | boolean | null> & { synthetic_id: string; province_code: string; province_name: string;
  age: number; age_group: string; sex: string; population_weight: number };
export type RecordsPage = { items: RecordRow[]; total_matching: number; offset: number; limit: number; sort: string; direction: string };

export type PersonaAttribute = { field: string; label: string; value: string | number | null; display: string;
  status: "visible" | "hidden" | "unavailable" | "not_applicable"; reason: string | null; evidence: FieldEvidence };
export type Persona = {
  persona_id: string; kind_label: string; template_version: string; synthetic_id: string; population_id: string;
  province_code: string; province_name: string; attributes: PersonaAttribute[]; model_visible: Record<string, string>;
  hidden: { field: string; reason: string }[]; model_visible_fields: string[]; persona_card: string; persona_card_sha256: string;
  eligibility: { adult: boolean; age: number; rule: string }; limitations: string[];
  provenance: { population_id: string; synthetic_id: string; provenance_profile: string; generator_version: string; generation_seed: number;
    reference_year: number; source_years: Record<string, number>; source_ids: string[] };
  population_weight: number;
};
export type RecordDetail = { record: RecordRow; persona: Persona; profile: Profile; evidence_levels: Record<string, string>; label: string };

export type ProvinceCoverage = {
  province_code: string; province_name: string; nuts3_code: string; nuts2_code: string; nuts1_code: string; nuts1_name: string;
  iso_3166_2: string; has_population_controls: boolean; control_tables: string[]; context_indicators: number; records: number;
  represented_population: number | null;
};
export type Geography = { classification: string; provinces: ProvinceCoverage[]; controls_status: string;
  provinces_with_population_controls: number; province_count: number };

export type EnvironmentPoint = { period: string; year: number | null; value: number | null; value_status: string; observation_type: string };
export type EnvironmentIndicator = { indicator_id: string; label: string; label_tr: string | null; unit: string; value: number | null;
  value_status: string; source_year: number | null; source_period?: string | null; multi_year_period?: boolean; years_from_reference: number | null;
  geo_level: string; source_id: string; source_ref: string; history: EnvironmentPoint[]; projections?: EnvironmentPoint[]; note: string | null };
export type EnvironmentProjection = { indicator_id: string; label: string; label_tr: string | null; unit: string; source_id: string; theme: string;
  points: EnvironmentPoint[]; note: string };
export type Environment = {
  province: { province_code: string; province_name: string; nuts3_code: string }; reference_year: number;
  domains: Record<string, EnvironmentIndicator[]>; empty_domains: string[]; indicator_count: number; projections?: EnvironmentProjection[];
  structurally_unavailable_datasets: { source_id: string; title: string | null; theme: string | null; coverage: string; value_status: string; note: string }[];
  population_controls: { table_id: string; attribute: string | null; title: string; available: boolean; source_year: number | null; geo_level: string | null }[];
  notes: string[]; empty: boolean;
};

export type Filters = {
  province_codes?: string[]; age_min?: number; age_max?: number; age_groups?: string[]; sexes?: string[]; marital_statuses?: string[];
  education_levels?: string[]; labour_statuses?: string[]; household_size_classes?: string[]; household_types?: string[];
  urbanicities?: string[]; adult_only?: boolean;
};

export type CohortSampleSummary = { sample_id: string; config: SampleConfig; selected: number; created_at: string };
export type SampleConfig = { size: number; method: "simple_random" | "weighted" | "stratified"; seed: number; strata_field: string | null };
export type Cohort = {
  cohort_id: string; name: string; description: string | null; population_id: string; population_content_sha256: string;
  filters: Filters; definition_hash: string; created_at: string; status: string; status_detail: string;
  eligible_records: number | null; eligible_weighted_population: number | null; minors: number | null; samples: CohortSampleSummary[];
};
export type CohortPreview = { population_id: string; filters: Filters; eligible_records: number; eligible_weighted_population: number;
  minors: number; provinces: ProvinceCount[]; distributions: Distribution[]; note: string };
export type Sample = {
  sample_id: string; cohort_id: string; population_id: string; config: SampleConfig; config_hash: string; eligible_records: number;
  eligible_weighted_population: number; selected: number; strata: { stratum: string; eligible: number; weighted: number; allocated: number; drawn: number }[] | null;
  sum_analysis_weights: number; algorithm_version: string; members_sha256: string; created_at: string; weight_note: string;
  members: { synthetic_id: string; inclusion_probability: number; population_weight: number; analysis_weight: number }[];
};
export type SamplePersona = { persona_id: string; synthetic_id: string; province_code: string; province_name: string;
  model_visible: Record<string, string>; eligibility: Persona["eligibility"]; persona_card_sha256: string;
  attributes: Record<string, string>; inclusion_probability: number; analysis_weight: number };
export type SamplePersonas = { sample_id: string; population_id: string; total: number; offset: number; limit: number; items: SamplePersona[]; template_version: string };

export type ExperimentDefinition = {
  title: string;
  scenario: { title: string; description: string; parameters: { name: string; label: string; value: number | string; unit: string | null }[];
    hypothetical: boolean; source_note?: string | null; version?: string };
  task: { instruction: string; response_type?: string; options: { id: string; label: string }[]; allow_other_text: boolean;
    ask_rationale: boolean; adult_only: boolean; version?: string };
  environment: { province_code: string | null; context_indicators: string[] };
  cohort: { cohort_id: string; sample_size: number; sampling_method: string; seed: number; strata_field?: string | null };
  model: { backend: "stub" | "matraix"; transport: "fake" | "live"; model?: string | null; temperature: number; seed?: number | null; max_output_tokens?: number };
  execution: { repetitions: number; max_attempts: number; max_calls: number; max_cost_usd?: number | null };
  persona?: {
    visible_fields?: string[] | null;
    field_selection?: {
      schema_version?: "persona-field-selection-1";
      allowlist: string[];
      required?: string[];
      optional?: string[];
      max_attributes?: number;
      missingness?: "omit" | "error";
      sidecar_root?: string | null;
      sidecar_id?: string | null;
    } | null;
  };
  scenario_ref?: {
    scenario_id: string;
    scenario_version: string;
    question_id: string;
    question_type?: string;
    province_codes?: string[] | null;
    minimum_age?: number | null;
    maximum_age?: number | null;
    required_attributes?: string[];
    unenforced_filters?: string[];
  } | null;
};
export type Blocker = { code: string; message: string };
export type Plan = {
  plan_hash: string; experiment_id: string; definition_hash: string; population_id: string; cohort_id: string; sample_id: string;
  eligible_records: number; eligible_weighted_population: number; selected_records: number; active_personas: number; minors_in_sample: number;
  calls: { planned: number; maximum_with_retries: number; cap: number; provider_calls_expected: number };
  tokens: { input_estimate_per_repetition: number; method: string; max_output_tokens_per_call: number };
  cost: { estimate_usd: number | null; basis: string; cap_usd: number | null };
  backend: { backend: string; transport: string; model: string | null; temperature: number; seed: number | null };
  personas: { persona_id: string; synthetic_id: string; province_code: string; age_group: string; sex: string; adult: boolean;
    model_visible_fields: string[]; analysis_weight: number }[];
  example_prompt: { synthetic_id: string; system: string; user: string } | null;
  persona_template_version: string; prompt_template_version: string; visible_fields_policy: string[];
  blockers: Blocker[]; warnings: string[]; executable: boolean; created_at: string;
};
export type RunView = {
  run_id: string; experiment_id: string; plan_hash: string; kind: "execute" | "replay"; replay_of: string | null; state: string;
  created_at: string; started_at: string | null; finished_at: string | null; error_code: string | null; error_message: string | null;
  backend: string | null; backend_label: string | null; personas: number | null; valid_responses: number | null; final_responses: number | null;
  calls_attempted: number | null; provider_calls: number | null;
  usage: { input_tokens: number | null; output_tokens: number | null; cost_usd: number | null; latency_ms_mean: number | null } | null;
  status_counts: Record<string, number> | null; title?: string | null;
};
export type Experiment = { experiment_id: string; definition: ExperimentDefinition; definition_hash: string; created_at: string;
  plans: Pick<Plan, "plan_hash" | "created_at" | "blockers" | "warnings" | "calls" | "active_personas">[]; runs: RunView[] };
export type ExperimentListItem = { experiment_id: string; title: string; created_at: string; backend: string; transport: string;
  model: string | null; cohort_id: string; sample_size: number; latest_run: RunView | null; run_count: number };
export type RunDetail = {
  run: RunView; title: string; definition: ExperimentDefinition; cohort: Cohort | null;
  plan: Pick<Plan, "plan_hash" | "active_personas" | "eligible_records" | "eligible_weighted_population" | "calls" | "cost" | "warnings"
    | "population_id" | "sample_id" | "visible_fields_policy" | "persona_template_version" | "prompt_template_version">;
  manifest: Record<string, unknown> & { code_version?: { commit: string | null; ref: string | null; note: string };
    population?: { population_id: string; content_sha256: string; seed: number; generator_version: string; reference_year: number; synthetic_size: number };
    reference_years?: { population: number; source_years: Record<string, Record<string, number>> } } | null;
  is_stub: boolean; is_placeholder: boolean; label: string;
};
export type OptionShare = { option_id: string; responses: number; weighted_share: number | null; unweighted_share: number | null; ci95: [number, number] | null };
export type DistributionOut = { responses: number; personas: number; effective_n: number; options: OptionShare[] };
export type Aggregate = {
  overall: DistributionOut; status_counts: Record<string, number>; valid_responses: number; final_responses: number; inference_note: string;
  weighting: string; options: { id: string; label: string }[]; is_stub: boolean; is_placeholder: boolean;
  by: Record<string, { min_group_personas: number; comparisons: string[];
    groups: ({ value: string; personas: number; suppressed: true; reason: string } | ({ value: string; personas: number; suppressed: false } & DistributionOut))[] }>;
};
export type ResponseRow = { request_key: string; persona_id: string; synthetic_id: string; province_code: string; sample_index: number; attempt: number;
  status: string; choice: string | null; other_text: string | null; rationale: string | null; raw_response: string | null; error: string | null;
  latency_ms: number | null; input_tokens: number | null; output_tokens: number | null; cost_usd: number | null; provider_call: boolean;
  from_cache: boolean; prompt_source: string; created_at: string; is_final: boolean };
export type ResponsesPage = { run_id: string; total: number; offset: number; limit: number; items: ResponseRow[] };

export type CellFit = { cell: string[]; source_count: number; synthetic_weighted_count: number; synthetic_records: number; source_share: number | null;
  synthetic_share: number | null; record_share: number | null; absolute_error: number; relative_error: number | null; pp_error: number | null;
  record_pp_error: number | null; record_z: number | null };
export type TableFit = {
  table_id: string; attribute: string | null; cells?: CellFit[]; cell_count?: number; calibrated?: boolean;
  summary?: { max_relative_error: number | null; max_abs_pp_error_weighted: number; max_abs_pp_error_records: number; tvd_weighted: number;
    tvd_records: number; jsd_weighted: number | null; srmse_weighted: number | null; max_abs_record_z: number; record_z_threshold: number };
  weighted_status?: string; record_status?: string; status?: string; detail?: string; evidence?: string;
  source?: { geo_level: string; geo_code: string; year: number; source_ids: string[]; universe_min_age: number; universe_note: string };
  source_to_population_scale?: number; source_to_population_scale_by_sex?: Record<string, number> | null; records_without_value?: number; provinces?: string[]; note?: string;
  notes?: string[]; calibration_note?: string; provinces_not_calibrated?: string[];
};
export type ProvinceCalibration = { province_code: string; calibrated: boolean; margins: string[]; weight_ratio_bounds?: [number, number];
  margins_not_calibrated?: { margin: string; records: number; converged?: boolean; reason: string }[] };
export type DependencyJointCheck = {
  check_id: string;
  name: string;
  dimensions: string[];
  category: string;
  status: string;
  scope: string;
  scope_label: string;
  reason: string;
  reference_dataset_id?: string | null;
  reference_title?: string | null;
  evaluated_records: number;
  overall_tvd_records?: number | null;
  overall_tvd_weighted?: number | null;
  max_abs_z?: number | null;
  structural_zero_violations?: string[];
  notes?: string[];
};
export type DependencyValidation = {
  report_schema_version: string;
  validator_version: string;
  geography_code: string;
  overall_status: string;
  status_counts: Record<string, number>;
  summary_reason: string;
  supported_joint_checks: DependencyJointCheck[];
  unverified_relationships: DependencyJointCheck[];
  documented_discrepancies: string[];
};
export type ValidationReport = {
  method_version: string; population_id: string; statement: string; tolerances: Record<string, number>; tolerance_justification: Record<string, string>;
  national: { scope: string; province_count: number; province_reference_count: number; tables: TableFit[]; note?: string | null };
  calibration?: ProvinceCalibration[];
  provinces: { province_code: string; province_name: string; records: number; tables: TableFit[]; fields_without_source: { field: string; reason: string }[];
    cross_source_checks: { name: string; year: number; root_table: number; context: number; difference: number; passed: boolean; detail: string }[] }[];
  constraints: { rule_id: string; kind: string; description: string; checked: number; violations: number; examples: { synthetic_id: string; detail: string }[] }[];
  constraint_violations: number; weights: Weights; not_validated: string[];
  dependency_validation?: DependencyValidation;
};

export type Discrepancy = { dataset: string | null; field: string; claimed: unknown; actual: unknown; note: string };
export type Source = {
  source_id: string; publisher: string; title_en: string | null; title_tr: string | null; dataset_identifier: string | null; theme?: string | null;
  url: string | null; publication_date: string | null; retrieval_date: string | null; reference_years: number[]; geographic_level: string;
  province_coverage: string[]; variables: string[]; variable_count?: number; units: string[]; transformations: string[]; limitations: string[];
  status: string; processed_file?: { path: string; sha256: string; bytes: number } | null; raw_files?: { path: string; sha256: string }[];
  value_status_counts?: Record<string, number>; rows?: number;
  // TÜİK package datasets only
  domain?: string; source_tables?: string[]; reference_periods?: string[]; catalog_reference_years?: string | null; missing_provinces?: string[];
  blank_values?: number; multi_year_rows?: number; multi_year_periods?: Record<string, number>; projection_rows?: number; absent_province_rows?: number;
  observation_type?: string; accounting?: { read: number; control_cells: number; context_observations: number; rejected: number; duplicates_agreeing: number };
  mapping?: { use: "controls" | "context"; tables: string[]; reason: string | null }; discrepancies?: Discrepancy[];
  wide_files?: { file: string; sha256: string; cells_compared: number; mismatches: number; wide_only_values: number; long_only_keys: number }[];
};
export type TableCheck = { name: string; passed: boolean; detail: string; sex?: string; year?: number; summary?: boolean; checked?: number;
  failed?: number; years_passed?: number[]; years_failed?: number[]; relative_gap_range?: [number, number] };
export type ControlTable = { table_id: string; kind: string; title: string; unit: string; universe_min_age: number; universe_note: string;
  source_ids: string[]; transformations: string[]; checks: TableCheck[];
  limitations: string[]; province_coverage: number; provinces: string[]; years: number[]; rows: number };
export type PackageAudit = {
  adapter: "tuik_long_format_package"; package_dir: string; mapping_file: string;
  files: { total: number; long_format: number; wide: number; metadata: string[]; documentation: string[] };
  counts: { datasets: number; indicators: number; long_rows: number; datasets_with_full_coverage: number; not_province_level_datasets: number;
    rejected_rows: number; blank_values: number; multi_year_rows: number; projection_rows: number; control_cells: number; context_observations: number;
    duplicate_keys_conflicting: number; variable_metadata_indicators: number; province_coverage_distribution: Record<string, number> };
  documentation_claims: { source: string | null; claims: Record<string, number | null>; note: string };
  wide_files: { verified: number; cells_compared: number; mismatches: number; unmatched_files: string[] };
  discrepancies: Discrepancy[];
  not_province_level: { title_en: string | null; title_tr: string | null; theme: string | null; geographic_level: string | null; reason: string | null; url: string | null }[];
};
export type CrossSourceAudit = { adapter: "cross_source"; checks: { check: string; detail?: string; passed?: boolean; cells?: number; indicator?: string;
  package_indicator?: string; geo_code?: string; period?: string; legacy?: number; package?: number }[] };
export type ControlsStatus = { status: "built" | "not_built" | "invalid"; detail?: string; built_at?: string; fingerprint?: string;
  tables?: ControlTable[]; sources?: Source[]; inputs?: { path: string; role: string; sha256: string; bytes: number }[]; warnings?: string[];
  context_indicators?: number; context_observations?: number; context_domains?: Record<string, number>; multi_year_observations?: number;
  projection_observations?: number; audits?: (PackageAudit | CrossSourceAudit)[]; package_dir_present: boolean; builder_version: string };
export type OptionalModules = {
  marital_strategy: { configured: boolean; registry_version?: string; enabled: boolean; strategy?: string | null; seed_present: boolean };
  resident_enrichment: { configured: boolean; registry_version?: string; enabled: boolean; attributes: string[]; sources_present: Record<string, boolean> };
  households: { configured: boolean; size_enabled: boolean; type_size_enabled: boolean; linkage_supported: boolean; linkage_evidence_present: boolean; sources_present: Record<string, boolean> };
  k1_k7_validation: { district_csv_present: boolean; built_reference_package_present: boolean; joint_dependency_checks_active: boolean; note: string };
};
export type DataSources = { controls: ControlsStatus; root_manifest: { path: string; status: string; datasets: unknown[]; note: string; error: string | null };
  package: { directory: string; present: boolean; files?: number; mapping_file: string; mapping_present: boolean };
  optional_modules?: OptionalModules };

export type Overview = {
  controls: { status: string; built_at: string | null; tables: string[] }; populations: PopulationListItem[]; default_population_id: string | null;
  provinces_with_population_controls: number; province_count: number; saved_cohorts: number; experiments: number;
  personas_used_in_completed_runs: number; latest_run: (RunView & { title: string | null }) | null;
};
export type Capabilities = {
  backends: Record<"stub" | "matraix_fake" | "matraix_live", { available: boolean; reasons: string[]; note?: string }>;
  provider_key_present: Record<string, boolean>; max_agents_per_run: number; price_table_configured: boolean; generator_version: string;
  constraint_rules: PopulationDetail["constraint_rules"]; dependency_model: PopulationDetail["dependency_model"];
  tolerances: Record<string, number>; tolerance_justification: Record<string, string>;
  vocabularies: Record<string, { attribute: string; note: string; categories: { code: string; label_en: string; label_tr: string | null }[] }>;
  evidence_levels: Record<string, string>; persona_fields: { all: string[]; default_visible: string[] }; groupable: string[];
};

export type ScenarioListItem = {
  scenario_id: string;
  version: string;
  name: string;
  description: string;
  category: string;
  type: string;
  location: { province_code: string; province_name: string };
  questions_count: number;
  questions: { id: string; text: string; type?: "single_choice" | "multiple_choice" | "free_text" | string }[];
};
export type ScenarioList = { items: ScenarioListItem[] };

export type CreateScenarioPayload = {
  scenario_id: string;
  version?: string;
  name: string;
  description: string;
  location: { province_code: string; province_name: string; nuts2_code?: string | null };
  metadata?: { hypothetical?: boolean; source_note?: string | null; author?: string | null; reference_year?: number | null };
  policy: {
    category: string;
    type: string;
    parameters: {
      baseline_fare?: number | null;
      new_fare?: number | null;
      increase_percentage?: number | null;
      currency?: string;
      fare_category?: string | null;
      effective_date?: string | null;
      subsidized_exemptions_note?: string | null;
      policy_summary?: string | null;
      custom_details?: Record<string, unknown>;
    };
  };
  target_population?: {
    minimum_age?: number | null;
    maximum_age?: number | null;
    province_codes?: string[] | null;
    sexes?: string[] | null;
    marital_statuses?: string[] | null;
    education_levels?: string[] | null;
    adult_only?: boolean;
    required_attributes?: string[];
  };
  questions: {
    id: string;
    text: string;
    type?: "single_choice" | "multiple_choice" | "free_text";
    options: { id: string; label: string }[];
    min_length?: number | null;
    max_length?: number | null;
    allow_other?: boolean;
    ask_rationale?: boolean;
  }[];
};

export type ScenarioPromptRequest = {
  prompt: string;
  model?: string | null;
  save?: boolean;
};

export type CompiledScenarioResponse = CreateScenarioPayload;

export type ResultTextSummary = {
  title: string;
  headline: string;
  key_findings: string[];
  summary_markdown: string;
  representative_quotes: {
    synthetic_id: string;
    province_code: string;
    choice?: string;
    quote: string;
    rationale?: string | null;
  }[];
  is_free_text: boolean;
  total_responses: number;
  valid_responses: number;
  generated_by?: string;
};

// ---------------------------------------------------------------- university placement & policy
export type UniversityInterventionPayload = {
  tuition_change_pct?: number | null;
  aid_budget_change_pct?: number | null;
  capacity_change_pct?: number | null;
  capacity_rounding?: "floor" | "nearest" | "largest_remainder";
  installment_count?: number | null;
  installment_upfront_share?: number | null;
  affordability_filter_mode?: "none" | "hard_exclude" | "utility_rerank";
  attendance_min_pct?: number | null;
  grading_difficulty_shift?: number | null;
  semester_count?: number;
  replications?: number;
  rank_threshold_overrides?: Record<string, number>;
  apply_prior_placement_obp_penalty?: boolean;
  osym_verified?: boolean;
};

export type PlacementProgram = {
  program_id: string;
  university_id: string;
  university_name: string;
  university_type: "state" | "foundation";
  province_code: string;
  department_name: string;
  degree_level: "associate" | "bachelor";
  score_type: "TYT" | "SAY" | "EA" | "SÖZ" | "DİL";
  baraj_group?: string | null;
  capacity: number;
  tuition_annual: number;
  scholarship_pct: number;
  status: string;
};

export type PlacementProgramsCatalog = {
  osym_verified: boolean;
  rule_fidelity: string;
  disclaimer: string;
  score_types: string[];
  rank_thresholds: Record<string, number>;
  programs: PlacementProgram[];
};

export type PlacementProgramDelta = {
  program_id: string;
  baseline_capacity: number;
  policy_capacity: number;
  capacity_delta: number;
  baseline_filled: number;
  policy_filled: number;
  filled_delta: number;
  baseline_cutoff_score: number | null;
  policy_cutoff_score: number | null;
  cutoff_score_delta: number | null;
  first_choice_delta: number;
};

export type PlacementTransitionBreakdown = {
  total_candidates: number;
  same_program: number;
  improved_preference: number;
  worsened_preference: number;
  newly_placed: number;
  displaced_to_unplaced: number;
  remained_unplaced: number;
  eligibility_changed: number;
};

export type PlacementComparisonReport = {
  baseline_result_sha256: string;
  policy_result_sha256: string;
  candidates_sha256: string;
  osym_verified: boolean;
  rule_fidelity: string;
  disclaimer: string;
  metric_deltas: Record<string, { baseline: number | null; policy: number | null; delta: number | null }>;
  transitions: PlacementTransitionBreakdown;
  program_deltas: PlacementProgramDelta[];
};

export type PlacementRunResponse = {
  run_id: string;
  scenario_id: string | null;
  population_id: string | null;
  osym_verified: boolean;
  rule_fidelity?: string;
  disclaimer?: string;
  result_sha256: string;
  created_at: string;
  summary: {
    title: string;
    headline: string;
    key_findings: string[];
    summary_markdown: string;
    osym_verified: boolean;
    rule_fidelity: string;
    disclaimer: string;
  };
  result?: {
    placement_result: {
      manifest: Record<string, unknown>;
      aggregate_metrics: Record<string, number | Record<string, number> | null>;
      program_outcomes: {
        program_id: string;
        university_name: string;
        department_name: string;
        score_type: string;
        effective_capacity: number;
        filled: number;
        cutoff_score: number | null;
        first_choice_count: number;
      }[];
    };
    comparison: PlacementComparisonReport | null;
    handoff: { student_count: number; source_result_sha256: string };
    demographic_source: string;
    admitted_count: number;
  };
};

export type UniversityTrajectoryPoint = {
  semester: number;
  mean_active_students: number;
  p05_active_students: number;
  p95_active_students: number;
  mean_paused_stop_out: number;
  mean_transferred: number;
  mean_withdrawn_dropout: number;
  mean_graduated: number;
  mean_retention_rate: number;
  mean_gpa: number;
  mean_waitlisted: number;
  mean_net_tuition_revenue: number;
  mean_aid_disbursed: number;
};

export type UniversityRunResponse = {
  run_id: string;
  scenario_id: string | null;
  placement_run_id: string | null;
  osym_verified: boolean;
  coefficients_calibrated: boolean;
  disclaimer?: string;
  result_sha256: string;
  created_at: string;
  summary: {
    title: string;
    headline: string;
    key_findings: string[];
    summary_markdown: string;
    osym_verified: boolean;
    coefficients_calibrated: boolean;
    disclaimer: string;
  };
  result?: {
    manifest: Record<string, unknown>;
    semester_snapshots: {
      semester: number;
      active_students: number;
      paused_stop_out_students: number;
      transferred_students: number;
      withdrawn_dropout_students: number;
      graduated_students: number;
      mean_gpa: number;
      total_waitlisted_requests: number;
      total_net_tuition_revenue: number;
      course_pass_rate?: number | null;
    }[];
    final_summary: Record<string, number>;
  };
  comparison?: {
    replications: number;
    osym_verified: boolean;
    coefficients_calibrated: boolean;
    disclaimer: string;
    policy_effects: Record<string, {
      baseline_mean: number;
      policy_mean: number;
      mean: number;
      std: number;
      p05: number;
      p50: number;
      p95: number;
    }>;
    baseline_trajectory: UniversityTrajectoryPoint[];
    policy_trajectory: UniversityTrajectoryPoint[];
  } | null;
};

export type UniversitySweepResponse = {
  placement_run_id: string | null;
  cohort_size: number;
  semester_count: number;
  replications: number;
  osym_verified: boolean;
  coefficients_calibrated: boolean;
  disclaimer: string;
  rows: {
    tuition_change_pct: number;
    aid_budget_change_pct: number;
    mean_retention_rate: number;
    retention_delta_vs_zero: number;
    mean_withdrawn_dropout: number;
    mean_paused_stop_out: number;
    mean_net_tuition_revenue: number;
    mean_aid_disbursed: number;
  }[];
};

export type UniversityRegistryStatus = {
  available: boolean;
  db_path: string;
  schema_version: number | null;
  snapshots: {
    snapshot_id: string;
    source_filename: string;
    imported_at: string;
    verification_status: string;
    counts: { universities: number; programs: number; open_quality_issues: number };
    admission_years: number[];
  }[];
  note: string;
};

