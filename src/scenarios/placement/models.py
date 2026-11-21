"""Typed Pydantic models for the offline deterministic university placement simulator.

All default thresholds and rulesets are explicitly marked simplified/hypothetical
until verified ÖSYM capacity and kılavuz datasets are ingested.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

try:
    from ..schema import AffordabilityFilterMode, RuleFidelity
except ImportError:
    from scenarios.schema import AffordabilityFilterMode, RuleFidelity  # type: ignore

PLACEMENT_ENGINE_VERSION = "placement-engine-1.0"

DEFAULT_HYPOTHETICAL_DISCLAIMER = (
    "SIMPLIFIED / HYPOTHETICAL RULES: This output uses illustrative rules and "
    "TÜİK-anchored synthetic candidate data for offline policy exploration. "
    "It does NOT reproduce official ÖSYM placement outcomes."
)

ScoreType = Literal["TYT", "SAY", "EA", "SÖZ", "DİL"]
VALID_SCORE_TYPES: tuple[ScoreType, ...] = ("TYT", "SAY", "EA", "SÖZ", "DİL")

BarajGroup = Literal[
    "medicine",
    "dentistry",
    "pharmacy",
    "law",
    "engineering",
    "architecture",
    "teaching",
]

# Illustrative placeholder success-rank ceilings for simplified/hypothetical rulesets.
# Never treat these defaults as official current-year ÖSYM thresholds without verified kılavuz data.
ILLUSTRATIVE_RANK_THRESHOLDS: dict[str, int] = {
    "medicine": 50_000,
    "dentistry": 80_000,
    "pharmacy": 100_000,
    "law": 100_000,
    "architecture": 250_000,
    "engineering": 300_000,
    "teaching": 300_000,
}

ChoiceAuditStatus = Literal["eligible", "unavailable"]
PlacementStatus = Literal["placed", "unplaced", "not_applicable"]
TerminalTieBreaker = Literal["canonical_id", "seeded_hash"]
AgeTieRule = Literal["none", "younger_first", "older_first"]
DuplicatePrefPolicy = Literal["deduplicate_keep_first", "reject_candidate"]


class TieBreakPolicy(BaseModel):
    """Explicit, total-order tie-breaking policy for boundary candidates."""
    model_config = ConfigDict(extra="forbid")

    use_raw_score: bool = True
    use_obp: bool = True
    prefer_earlier_choice: bool = False
    age_tie_rule: AgeTieRule = "none"
    terminal_tie_breaker: TerminalTieBreaker = "canonical_id"
    tie_seed: int = Field(default=42, ge=0)


class PlacementRuleset(BaseModel):
    """Versioned rules governing eligibility, baraj checks, score resolution, and ties."""
    model_config = ConfigDict(extra="forbid")

    ruleset_id: str = Field(default="hypothetical_yks_v1", pattern=r"^[a-z][a-z0-9_]{1,63}$")
    rule_fidelity: RuleFidelity = "hypothetical_simplified"
    osym_verified: bool = False
    max_preferences: int = Field(default=24, ge=1, le=100)
    strict_preference_cap: bool = False
    duplicate_preference_policy: DuplicatePrefPolicy = "deduplicate_keep_first"
    require_tyt_for_bachelor: bool = False
    derive_ranks_from_cohort: bool = True
    prior_placement_obp_multiplier: float = Field(default=0.5, ge=0.0, le=1.0)
    score_precision_decimals: int = Field(default=5, ge=0, le=8)
    rank_thresholds: dict[str, int] = Field(
        default_factory=lambda: dict(ILLUSTRATIVE_RANK_THRESHOLDS),
        description="Success-rank ceilings by baraj_group; illustrative placeholders unless osym_verified=True.",
    )
    tie_break_policy: TieBreakPolicy = Field(default_factory=TieBreakPolicy)
    source_note: str | None = Field(default=None, max_length=2000)
    osym_kilavuz_year: int | None = Field(default=None, ge=2000, le=2050)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_provenance_and_thresholds(self) -> PlacementRuleset:
        for group, rank in self.rank_thresholds.items():
            if rank < 1:
                raise ValueError(f"rank_thresholds[{group!r}] must be >= 1, got {rank}")
        if self.osym_verified and self.rule_fidelity != "verified_osym":
            raise ValueError("osym_verified=True requires rule_fidelity='verified_osym'.")
        if self.rule_fidelity == "verified_osym" and not self.osym_verified:
            raise ValueError("rule_fidelity='verified_osym' requires osym_verified=True.")
        if self.osym_verified:
            if not (self.source_note and self.source_note.strip()):
                raise ValueError("Verified ÖSYM rulesets must supply source_note.")
            if self.osym_kilavuz_year is None:
                raise ValueError("Verified ÖSYM rulesets must supply osym_kilavuz_year.")
            if not self.source_sha256:
                raise ValueError("Verified ÖSYM rulesets must supply 64-hex source_sha256.")
        return self

    def disclosure_banner(self) -> str:
        """Human-readable disclosure reflecting whether verified ÖSYM rules are active."""
        if self.osym_verified:
            return (
                f"VERIFIED ÖSYM RULESET ({self.osym_kilavuz_year}): {self.source_note} "
                f"[sha256:{self.source_sha256}]"
            )
        return DEFAULT_HYPOTHETICAL_DISCLAIMER


class ProgramConditions(BaseModel):
    """Special program eligibility requirements beyond score type and rank threshold."""
    model_config = ConfigDict(extra="forbid")

    requires_diploma: bool = True
    required_sex: Literal["male", "female"] | None = None
    min_age: int | None = Field(default=None, ge=15, le=120)
    max_age: int | None = Field(default=None, ge=15, le=120)

    @model_validator(mode="after")
    def _validate_age_bounds(self) -> ProgramConditions:
        if self.min_age is not None and self.max_age is not None and self.min_age > self.max_age:
            raise ValueError(f"min_age ({self.min_age}) cannot exceed max_age ({self.max_age})")
        return self


class ProgramOffering(BaseModel):
    """Single selectable university program offering (Milestone 1: general quota only)."""
    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(min_length=1, max_length=64)
    university_id: str = Field(min_length=1, max_length=64)
    university_name: str = Field(min_length=1, max_length=200)
    university_type: Literal["state", "foundation", "kktc", "other"] = "state"
    province_code: str = Field(pattern=r"^\d{2}$")
    department_name: str = Field(min_length=1, max_length=200)
    degree_level: Literal["associate", "bachelor"] = "bachelor"
    score_type: ScoreType
    baraj_group: BarajGroup | None = None
    capacity: int = Field(ge=0, description="General quota seat capacity (Milestone 1: general quotas only)")
    status: Literal["open", "closed", "suspended"] = "open"
    min_score: float | None = Field(default=None, ge=0.0, le=600.0)
    max_rank_override: int | None = Field(default=None, ge=1)
    tuition_annual: float = Field(default=0.0, ge=0.0)
    scholarship_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    currency: str = Field(default="TL", max_length=10)
    special_conditions: ProgramConditions = Field(default_factory=ProgramConditions)

    def published_net_tuition_before_aid(self) -> float:
        """Tuition after institutional scholarship discount, before need-based grants."""
        return round(self.tuition_annual * (1.0 - self.scholarship_pct / 100.0), 2)


class CandidateRecord(BaseModel):
    """Single applicant record with optional TÜİK anchor metadata and exam/financial attributes."""
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=64)
    source_synthetic_id: str | None = None
    source_population_id: str | None = None
    province_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    age: int | None = Field(default=None, ge=0, le=120)
    sex: str | None = None
    education_level: str | None = None
    population_weight: float | None = Field(default=None, gt=0.0)
    diploma_eligible: bool | None = True
    scores: dict[ScoreType, float | None] = Field(default_factory=dict)
    raw_scores: dict[ScoreType, float | None] = Field(default_factory=dict)
    ranks: dict[ScoreType, int | None] = Field(default_factory=dict)
    obp_contribution: float | None = Field(default=None, ge=0.0, le=60.0)
    previously_placed_penalty: bool = False
    preferences: list[str] = Field(default_factory=list)
    income_band: Literal["low", "middle", "high"] | None = None
    liquid_budget: float | None = Field(default=None, ge=0.0)
    max_affordable_tuition: float | None = Field(default=None, ge=0.0)
    need_aid_grant: float = Field(default=0.0, ge=0.0)
    field_provenance: dict[str, str] = Field(default_factory=dict)


class CandidateCohort(BaseModel):
    """Versioned candidate cohort carrying demographic anchor and field provenance."""
    model_config = ConfigDict(extra="forbid")

    cohort_id: str = Field(min_length=1, max_length=80)
    demographic_source: Literal["tuik_population", "standalone_test_fixture"]
    source_population_id: str | None = None
    population_content_sha256: str | None = None
    seed: int | None = None
    field_provenance: dict[str, dict[str, Any]] = Field(default_factory=dict)
    candidates: list[CandidateRecord]


class ChoiceEvaluation(BaseModel):
    """Audit record for one submitted preference in a candidate's list."""
    model_config = ConfigDict(extra="forbid")

    submitted_rank: int = Field(ge=1)
    program_id: str
    status: ChoiceAuditStatus
    reason_code: str
    detail: str


class CandidateFinancials(BaseModel):
    """Deterministic tuition, grant, and upfront liquidity calculation."""
    model_config = ConfigDict(extra="forbid")

    gross_tuition: float
    scholarship_discount: float
    published_tuition: float
    need_aid_grant: float
    net_tuition: float
    payments_due_upfront: float
    liquidity_gap: float | None = None


class TieBreakEvent(BaseModel):
    """Logged tie resolution at a program's capacity boundary."""
    model_config = ConfigDict(extra="forbid")

    program_id: str
    quota_bucket: str = "general"
    tied_effective_score: float
    admitted_candidate_id: str
    displaced_candidate_id: str
    deciding_criterion: str


class CandidatePlacementOutcome(BaseModel):
    """Reproducible per-candidate placement result and preference audit trail."""
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    source_synthetic_id: str | None = None
    eligibility_status: Literal["eligible", "excluded", "cannot_evaluate"]
    placement_status: PlacementStatus
    assigned_program_id: str | None = None
    quota_bucket: str = "general"
    assigned_preference_rank: int | None = None
    score_type_used: ScoreType | None = None
    effective_score: float | None = None
    rank_used: int | None = None
    rank_source: Literal["explicit", "cohort_derived", "none"] = "none"
    unplaced_reason: str | None = None
    missing_attributes: list[str] = Field(default_factory=list)
    exclusion_reasons: list[str] = Field(default_factory=list)
    financials: CandidateFinancials | None = None
    preference_evaluations: list[ChoiceEvaluation] = Field(default_factory=list)


class ProgramPlacementOutcome(BaseModel):
    """Reproducible per-program fill, cutoff, and demand summary."""
    model_config = ConfigDict(extra="forbid")

    program_id: str
    university_name: str
    department_name: str
    province_code: str
    score_type: ScoreType
    quota_bucket: str = "general"
    initial_capacity: int
    effective_capacity: int
    status: Literal["open", "closed", "suspended"]
    filled: int
    remaining_seats: int
    fill_rate: float
    cutoff_score: float | None = None
    cutoff_is_binding: bool = False
    highest_score: float | None = None
    cutoff_rank: int | None = None
    applicant_count: int = 0
    first_choice_count: int = 0
    ineligible_attempts_by_reason: dict[str, int] = Field(default_factory=dict)
    tie_breaks_at_cutoff: list[TieBreakEvent] = Field(default_factory=list)


class PlacementManifest(BaseModel):
    """Cryptographic provenance and rule disclosure manifest for a placement run."""
    model_config = ConfigDict(extra="forbid")

    engine_version: str = PLACEMENT_ENGINE_VERSION
    scenario_id: str | None = None
    scenario_version: str | None = None
    scenario_sha256: str | None = None
    candidates_sha256: str
    programs_sha256: str
    ruleset_sha256: str
    intervention_sha256: str | None = None
    result_sha256: str
    seed: int | None = None
    affordability_filter_mode: AffordabilityFilterMode = "none"
    quota_scope: Literal["general_only"] = "general_only"
    rule_fidelity: RuleFidelity
    osym_verified: bool
    disclaimer: str
    invariants_passed: bool


class PlacementResult(BaseModel):
    """Complete, deterministic output bundle for an offline placement run."""
    model_config = ConfigDict(extra="forbid")

    manifest: PlacementManifest
    candidate_outcomes: list[CandidatePlacementOutcome]
    program_outcomes: list[ProgramPlacementOutcome]
    aggregate_metrics: dict[str, Any]
    subgroup_metrics: dict[str, Any] = Field(default_factory=dict)
    tie_break_events: list[TieBreakEvent] = Field(default_factory=list)


class TransitionBreakdown(BaseModel):
    """Exact candidate migration counts between baseline and policy runs."""
    model_config = ConfigDict(extra="forbid")

    total_candidates: int
    same_program: int
    improved_preference: int
    worsened_preference: int
    newly_placed: int
    displaced_to_unplaced: int
    remained_unplaced: int
    eligibility_changed: int
    sample_candidate_ids: dict[str, list[str]] = Field(default_factory=dict)


class ProgramDelta(BaseModel):
    """Per-program cutoff, capacity, and fill differences."""
    model_config = ConfigDict(extra="forbid")

    program_id: str
    baseline_capacity: int
    policy_capacity: int
    capacity_delta: int
    baseline_filled: int
    policy_filled: int
    filled_delta: int
    baseline_cutoff_score: float | None
    policy_cutoff_score: float | None
    cutoff_score_delta: float | None
    first_choice_delta: int


class PlacementComparisonReport(BaseModel):
    """Paired counterfactual comparison between baseline and policy PlacementResult runs."""
    model_config = ConfigDict(extra="forbid")

    baseline_result_sha256: str
    policy_result_sha256: str
    candidates_sha256: str
    baseline_scenario_id: str | None = None
    policy_scenario_id: str | None = None
    osym_verified: bool
    rule_fidelity: RuleFidelity
    disclaimer: str
    metric_deltas: dict[str, dict[str, float | int | None]]
    transitions: TransitionBreakdown
    program_deltas: list[ProgramDelta]
