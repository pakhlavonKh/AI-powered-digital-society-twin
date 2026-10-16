"""Response models. ``X | None`` without a default means the key is always present and null means unknown."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------- errors / health
class ErrorBody(Model):
    code: str
    message: str
    details: Any | None = None
    request_id: str


class ErrorResponse(Model):
    error: ErrorBody


class Health(Model):
    status: Literal["ok"]
    version: str
    time: str
    note: str


# ---------------------------------------------------------------- capabilities
class ProbeStatus(Model):
    status: Literal["not_run", "passed", "failed"]
    checked_at: str | None
    detail: str | None
    log_relpath: str | None = None


class RuntimeStatus(Model):
    matraix_root_source: str
    matraix_root_present: bool
    catalog_present: bool
    task_present: bool
    playground_package_present: bool
    runtime_python_configured: bool
    runtime_python_present: bool
    adapter_present: bool
    smoke_runner_present: bool
    ab_runner_present: bool
    files_ready: bool
    ready: bool
    probe: ProbeStatus
    reasons: list[str]


class ModeCapability(Model):
    available: bool
    reasons: list[str]


class UnavailableField(Model):
    field: str
    reason: str


class BuildCapability(Model):
    build_id: str
    variant: str
    availability: str
    filterable_fields: list[str]
    available_fields: list[str]
    unavailable_fields: list[UnavailableField]


class LoadError(Model):
    variant: str
    code: str
    message: str


class DataCapabilities(Model):
    builds: list[BuildCapability]
    default_build_id: str | None
    load_errors: list[LoadError]
    imported_runs_root_present: bool


class CredentialPresence(Model):
    provider_key_present: dict[str, bool]
    note: str


class Modes(Model):
    browse_offline: ModeCapability
    preflight: ModeCapability
    smoke: ModeCapability
    legacy_ab_live: ModeCapability
    cohort_execution: ModeCapability
    scenario_execution: ModeCapability
    stratified_sampling: ModeCapability
    persona_materialization: ModeCapability
    cancel: ModeCapability
    reproduce: ModeCapability
    export_parquet: ModeCapability


class MutationPolicy(Model):
    local_only: bool
    note: str


class ApiStatus(Model):
    status: str
    version: str


class RunnerInfo(Model):
    provider_prefixes: list[str]
    fixed_persona_ids: list[str]
    note: str


class Capabilities(Model):
    api: ApiStatus
    data: DataCapabilities
    runtime: RuntimeStatus
    credentials: CredentialPresence
    modes: Modes
    mutations: MutationPolicy
    runner: RunnerInfo


# ---------------------------------------------------------------- builds
class Scope(Model):
    province: str
    reference_year: int
    evidence: str


class Generator(Model):
    method: str
    configured_seed: int | None
    seed_evidence: str


class Availability(Model):
    status: Literal["available", "source_changed"]
    detail: str


class BuildDescriptor(Model):
    build_id: str
    variant: str
    schema_version: str
    schema_note: str
    source_path: str
    source_sha256: str
    source_bytes: int
    row_count: int
    available_fields: list[str]
    filterable_fields: list[str]
    unavailable_fields: list[UnavailableField]
    scope: Scope
    generator: Generator
    origin: str
    is_default: bool
    evidence_gaps: list[str]
    synthetic_label: str
    registered_at: str
    availability: Availability


class BuildRelation(Model):
    from_build_id: str
    to_build_id: str
    relation: str
    detail: str


class BuildList(Model):
    items: list[BuildDescriptor]
    default_build_id: str | None
    relations: list[BuildRelation]
    load_errors: list[LoadError]


class Resident(Model):
    person_id: str
    age_group: str
    gender: str
    marital_status: str | None = None
    marital_status_conditioning: str | None = None
    csv_row: int


class RecordsPage(Model):
    items: list[Resident]
    total_matching: int
    total_records: int
    offset: int
    limit: int
    sort: str
    direction: str
    filters: dict[str, list[str]]
    build_id: str
    source_sha256: str
    synthetic_label: str


class CategoryCount(Model):
    value: str
    count: int
    share: float | None


class Distribution(Model):
    field: str
    denominator: int
    categories: list[CategoryCount]


class CrosstabCell(Model):
    row: str
    column: str
    count: int


class Crosstab(Model):
    row_field: str
    column_field: str
    denominator: int
    cells: list[CrosstabCell]


class Summary(Model):
    build_id: str
    source_sha256: str
    filters: dict[str, list[str]]
    denominator: int
    total_records: int
    distributions: list[Distribution]
    crosstab: Crosstab | None
    display_translations: dict[str, dict[str, str]]
    method: str
    limitations: list[str]
    synthetic_label: str


# ---------------------------------------------------------------- validation
class MetricCategory(Model):
    category: str
    count: int
    synthetic_share: float | None
    reference_share: float
    difference_pp: float | None


class ValidationMetric(Model):
    name: str
    value: float | None
    unit: str
    dimension: str | None
    categories: list[MetricCategory] | None
    denominator: int
    population_sha256: str
    reference_sha256: str | None
    reference_year: int | None
    evidence_kind: Literal["source_fit", "integrity", "held_out", "behavioral"]
    availability: str
    method: str
    acceptance_threshold: None
    limitations: list[str]


class Check(Model):
    name: str
    passed: bool
    detail: str
    evidence_kind: str = "integrity"


class UnavailableEvidence(Model):
    name: str
    evidence_kind: str
    reason: str


class ReferenceTableRef(Model):
    path: str
    sha256: str
    reference_year: int
    rows: int


class HashCheck(Model):
    name: str
    path: str | None
    recorded_sha256: str | None
    status: Literal["match", "line_ending_equivalent", "mismatch", "unavailable"]


class RowCheck(Model):
    passed: bool
    detail: str


class PersonaHashChecks(Model):
    persona_file: str
    persona_id: str
    sha256: str
    checks: list[HashCheck]
    source_row_check: RowCheck | None


class ValidationReport(Model):
    build_id: str
    method_version: str
    population_sha256: str
    metrics: list[ValidationMetric]
    checks: list[Check]
    unavailable_evidence: list[UnavailableEvidence]
    acceptance_status: None
    acceptance_note: str
    reference_tables: list[ReferenceTableRef]
    persona_hash_checks: list[PersonaHashChecks]
    synthetic_label: str
    attribution_note: str


# ---------------------------------------------------------------- cohorts
class CohortPreview(Model):
    build_id: str
    source_sha256: str
    filters: dict[str, list[str]]
    eligible_count: int
    total_records: int
    distributions: list[Distribution]
    can_persist: bool
    note: str
    synthetic_label: str


class CohortRequested(Model):
    filters: dict[str, list[str]]
    size: int
    sampling: Literal["simple_random"]
    seed: int


class CohortRealized(Model):
    record_ids: list[str]
    eligible_count: int
    selected_count: int
    inclusion_probability: float
    synthetic_frame_expansion_weight: float
    weight_scope: str
    realized_counts: dict[str, dict[str, int]]


class CohortStatus(Model):
    status: Literal["valid", "source_changed", "build_unavailable"]
    detail: str


class CohortManifest(Model):
    cohort_id: str
    name: str | None
    build_id: str
    source_sha256: str
    requested: CohortRequested
    realized: CohortRealized
    sampling_algorithm_version: str
    frame_ordering: str
    created_at: str
    scope_note: str
    synthetic_label: str
    current: CohortStatus


class CohortList(Model):
    items: list[CohortManifest]
    total: int


# ---------------------------------------------------------------- personas
class MappedField(Model):
    dimension: str
    value: str
    source_field: str | None
    source_value: str | None
    source_type: str | None
    dataset: str | None
    method: str | None


class PersonaArtifact(Model):
    persona_artifact_id: str
    origin: Literal["fixture", "managed"]
    relpath: str
    sha256: str
    valid: bool
    error: str | None = None
    persona_id: str | None = None
    version: str | None = None
    source: str | None = None
    dimensions: dict[str, str] = {}
    prompt_visible_fields: list[str] = []
    metadata_only_fields: list[str] = []
    unassigned_fields: list[str] = []
    mapped_fields: list[MappedField] = []
    provenance_source_types: list[str] = []
    metadata: dict[str, Any] = {}
    hash_checks: list[HashCheck] = []
    source_row_check: RowCheck | None = None
    mapping_warnings: list[str] = []
    attribution_note: str | None = None


class PersonaIndexItem(Model):
    record_id: str
    origin: Literal["fixture", "managed"]
    persona_artifact_id: str
    relpath: str
    sha256: str
    created_at: str | None


class PersonaIndex(Model):
    build_id: str
    items: list[PersonaIndexItem]
    fixed_pair: list[str]
    note: str


class SourceTableRef(Model):
    field: str
    table: str
    note: str


class SourceCard(Model):
    attributes: dict[str, str]
    csv_row: int
    source_path: str
    source_sha256: str
    context: Scope
    source_tables: list[SourceTableRef]
    display_translations: dict[str, dict[str, str]]
    not_modelled: list[UnavailableField]
    note: str


class Materialization(Model):
    available: bool
    reasons: list[str]
    expected_omissions: list[str]
    output_note: str


class LegacyRunner(Model):
    fixed_ids: list[str]
    in_fixed_pair: bool
    slot: str | None
    note: str


class PromptEvidenceRef(Model):
    experiment_id: str
    trial_label: str
    display_state: str
    evidence_kind: str
    model: str | None
    system_sha256: str
    prompt_source: str
    persona_snapshot_sha256: str | None


class PersonaView(Model):
    build_id: str
    record_id: str
    build_variant: str
    source_card: SourceCard
    persona_status: Literal["source_card_only", "fixture_persona", "materialized_persona", "fixture_and_materialized"]
    personas: list[PersonaArtifact]
    materialization: Materialization
    legacy_runner: LegacyRunner
    historical_prompt_evidence: list[PromptEvidenceRef]
    notes: dict[str, str]
    synthetic_label: str


# ---------------------------------------------------------------- datasets
class ManifestStatus(Model):
    path: str
    status: Literal["empty", "populated", "missing", "invalid"]
    datasets: list[dict[str, Any]]
    error: str | None
    note: str


class FixtureEvidence(Model):
    id: str
    path: str
    kind: str
    declared_source: str
    present: bool
    sha256: str | None
    bytes: int | None
    rows: int | None
    columns: list[str] | None
    raw_evidence_status: str
    licence: str | None
    url: str | None
    download_date: str | None
    raw_checksum: str | None
    gaps: list[str]


class ControlObservation(Model):
    source_workbook: str
    source_sheet: str
    source_row: int
    csv_row: int


class ControlFact(Model):
    year: int
    province: str
    statistic: str
    value: float
    unit: str
    observations: list[ControlObservation]


class Datasets(Model):
    manifest: ManifestStatus
    fixture_evidence: list[FixtureEvidence]
    controls: list[ControlFact]
    controls_note: str
    synthetic_label: str
    attribution_note: str


# ---------------------------------------------------------------- run evidence
class Usage(Model):
    n_input_tokens: int | None
    n_output_tokens: int | None
    n_cache_tokens: int | None
    cost_usd: float | None
    cost_source: str | None
    provider: str | None
    model: str | None
    request_id: str | None
    billed_cost_usd: float | None


class Answer(Model):
    question_id: str
    value: Any
    rationale: str | None
    confidence: float | None
    label: str | None
    label_source: Literal["questionnaire_snapshot", "code_only"]


class Coercion(Model):
    question_id: str | None
    original: Any
    recorded: Any


class PersonaSnapshot(Model):
    sha256: str
    parse_error: bool
    persona_id: str | None = None
    dimensions: dict[str, str] = {}
    source_attributes: dict[str, Any] | None = None
    source_csv_row: int | None = None
    unassigned_fields: list[str] = []
    relpath: str | None = None


class Prompts(Model):
    system: str
    user: str
    system_sha256: str
    user_sha256: str
    source: str


class Choice(Model):
    id: str
    label: str


class Scale(Model):
    min: int
    max: int


class Question(Model):
    id: str
    prompt: str | None
    type: str | None
    construct_id: str | None
    required: bool | None
    scale: Scale | None
    choices: list[Choice]


class Questionnaire(Model):
    questions: list[Question]
    source: str


class EventsSummary(Model):
    count: int
    types: dict[str, int]
    malformed_lines: int
    note: str


class InstrumentRef(Model):
    id: str | None
    title: str | None


class Trial(Model):
    label: str
    trial_dir: str | None
    persona_id: str | None
    state: Literal["result_recorded", "fake_result", "request_started_no_response", "response_without_saved_result", "no_trial_evidence"]
    boundary_status_raw: str | None
    boundary_mode: str | None
    instrument: InstrumentRef | None
    answers: list[Answer] | None
    answer_count: int | None
    usage: Usage | None
    coerced_answers: list[Coercion]
    persona_snapshot: PersonaSnapshot | None
    preflight_persona_sha256: str | None
    prompts: Prompts | None
    questionnaire: Questionnaire | None
    events_summary: EventsSummary


class ComparisonRow(Model):
    question_id: str
    prompt: str | None
    question_type: str | None
    answer_a: Answer | None
    answer_b: Answer | None
    value_differs: bool | None
    recorded_value_differs: bool | None


class FileEvidenceModel(Model):
    relpath: str
    status: str
    size: int | None
    sha256: str | None
    error: str | None


class Artifact(Model):
    artifact_id: str
    relpath: str
    media_type: str
    size: int
    kind: str
    caveat: str | None


class BudgetFile(Model):
    spent_usd: float | None
    max_cost_usd: float | None
    note: str


DisplayState = Literal["completed", "completed_fake", "partial", "outcome_unknown", "prepared_only", "malformed", "unrecognized",
                       "draft", "prepared", "queued", "running", "failed", "stopped", "unknown_after_interruption"]


class RawStatuses(Model):
    preflight_status: str | None
    comparison_status: str | None
    smoke_report_ok: bool | None
    trial_boundaries: dict[str, str | None]


class TrialSummary(Model):
    label: str
    persona_id: str | None
    state: str
    boundary_status_raw: str | None
    answer_count: int | None
    usage: Usage | None
    coerced_answers: list[Coercion]
    answers: list[Answer] | None


class Results(Model):
    experiment_id: str
    origin: Literal["imported", "managed"]
    dirname: str
    display_name: str
    kind: str
    evidence_kind: str
    display_state: DisplayState
    display_state_reason: str
    raw_statuses: RawStatuses
    model: str | None
    temperature: float | None
    provider: str | None
    task: str | None
    planned_calls: int | None
    recorded_calls: int | None
    provider_calls_recorded: int | None
    automatic_retries: int | None
    max_output_tokens_per_call: int | None
    historical_credentials_present: bool | None
    runtime_seconds: float | None
    comparison_rows: list[ComparisonRow]
    differing_values_recorded: int | None
    differing_values_recomputed: int | None
    consistency_checks: list[Check]
    usage: Usage | None
    budget_file: BudgetFile | None
    limitations: list[str]
    warnings: list[str]
    artifacts: list[Artifact]
    files: list[FileEvidenceModel]
    evidence_drift: list[str] | None
    trial_summaries: list[TrialSummary]
    inference_note: str
    historical_credentials_note: str
    synthetic_label: str


class Trials(Model):
    experiment_id: str
    run_experiment_id: str
    origin: str
    evidence_kind: str
    display_state: str
    trials: list[Trial]
    synthetic_label: str


class EventItem(Model):
    trial_label: str
    index: int
    type: str | None
    phase: str | None
    keys: list[str]
    content: dict[str, Any]


class Events(Model):
    experiment_id: str
    items: list[EventItem]
    total: int
    offset: int
    limit: int
    note: str


# ---------------------------------------------------------------- experiments
class ExperimentListItem(Model):
    experiment_id: str
    origin: Literal["imported", "managed"]
    name: str
    kind: str
    display_state: DisplayState
    display_state_reason: str
    model: str | None
    evidence_kind: str | None
    created_at: str | None
    trial_count: int
    differing_values: int | None


class ExperimentList(Model):
    items: list[ExperimentListItem]
    total: int
    synthetic_label: str


class Blocker(Model):
    code: str
    message: str


class FixtureHash(Model):
    label: str
    persona_id: str
    path: str
    sha256: str | None


class ScenarioOut(Model):
    kind: Literal["none", "draft"]
    text: str | None
    version: str | None


class TaskOut(Model):
    id: str
    instrument_id: str
    task_path: str
    content_hash: str | None


class ExperimentConfig(Model):
    experiment_id: str
    origin: Literal["managed"]
    name: str
    persona_source: str
    cohort_id: str | None
    build_id: str | None
    realized_ids: list[str]
    scenario: ScenarioOut
    task: TaskOut
    environment: str
    mode: str
    model: str | None
    temperature: float | None
    calls_limit: int
    persona_artifact_hashes: list[FixtureHash]
    model_seed: None
    provenance_gaps: list[str]
    config_hash: str
    created_at: str


class PreflightTrial(Model):
    label: str
    persona_id: str
    persona_sha256: str
    prompt_visible_fields: list[str]
    dimensions: dict[str, Any]
    system_prompt: str | None
    user_prompt: str | None
    system_sha256: str | None
    user_sha256: str | None
    input_token_estimate: int | None


class DependencyReadiness(Model):
    runtime_files_ready: bool
    runtime_probe: str
    probe_checked_at: str | None
    matraix_root_source: str
    provider_key_present: bool | None
    live_execution_enabled: bool | None
    note: str


class Preflight(Model):
    preflight_hash: str
    experiment_id: str
    config_hash: str
    mode: str
    realized_ids: list[str]
    task_hash: str | None
    task_path: str
    instrument_id: str
    model: str | None
    temperature: float | None
    trials: list[PreflightTrial]
    prompt_hashes: list[str]
    planned_provider_calls: int
    planned_logical_calls: int
    calls_limit: int
    automatic_retries: int
    output_token_cap: int | None
    input_token_estimate: int | None
    estimate_method: str | None
    cost_estimate_usd: float | None
    cost_source: str | None
    cost_note: str | None
    runner_reported_credentials_present: bool | None
    runner_credentials_note: str
    model_seed: None
    persona_artifact_hashes: list[FixtureHash]
    execution_blockers: list[Blocker]
    dependency_readiness: DependencyReadiness | None = None
    warnings: list[str]
    stale_policy: str
    preflight_output_rel: str | None
    provider_calls_made: int
    limitations: list[str]
    synthetic_label: str
    created_at: str


class Job(Model):
    job_id: str
    experiment_id: str
    preflight_hash: str
    mode: str
    idempotency_key: str
    state: Literal["queued", "running", "completed", "failed", "stopped", "unknown_after_interruption"]
    worker_id: str | None
    output_rel: str
    created_at: str
    claimed_at: str | None
    provider_window_opened_at: str | None
    finished_at: str | None
    error_code: str | None
    error_message: str | None


class ExperimentDetail(Model):
    experiment_id: str
    origin: Literal["imported", "managed"]
    name: str
    config: ExperimentConfig | None
    blockers: list[Blocker]
    preflights: list[Preflight]
    jobs: list[Job]
    display_state: DisplayState
    display_state_reason: str
    preparation_status: Literal["blocked_by_config", "ready_for_preflight", "blocked_by_dependencies"] | None
    dependency_reasons: list[str] = []
    synthetic_label: str


class ExecuteResponse(Model):
    job: Job
    created: bool


class CancelResponse(Model):
    job: Job
    cancelled: bool


class TaskInfo(Model):
    id: str
    instrument_id: str
    title: str
    task_path: str
    origin: str
    question_count_from_snapshots: int | None
    external_content_available: bool
    content_hash: str | None
    snapshot_sources: list[str]
    executable_modes: list[str]
    notes: list[str]


class ScenarioKind(Model):
    kind: Literal["none", "draft"]
    status: Literal["executable", "draft_only"]
    description: str


class TaskList(Model):
    items: list[TaskInfo]
    scenario_kinds: list[ScenarioKind]


class EnvironmentInfo(Model):
    name: str
    status: Literal["executable", "draft_only"]
    description: str
    modes: list[str]
    reasons: list[str]


class EnvironmentList(Model):
    items: list[EnvironmentInfo]
