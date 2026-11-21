"""Typed Pydantic models for post-admission multi-semester university policy simulations.

Implements the University Decision Simulation Blueprint (v2.0) contracts:
synthetic student attributes, constrained choice sets A(i,t), utility weights,
agent decision traces, semester snapshots, and CRN counterfactual comparisons.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

UNIVERSITY_ENGINE_VERSION = "university-engine-1.0"

DEFAULT_UNIVERSITY_DISCLAIMER = (
    "SYNTHETIC / UNCALIBRATED PROTOTYPE: Student utility weights, behavioral traits, "
    "and multi-semester trajectories are hypothetical defaults for policy exploration, "
    "not empirically validated predictions about any real university."
)

StudentState = Literal["active", "paused", "transferred", "withdrawn", "graduated"]
ChoiceAction = Literal[
    "enroll_full_load",
    "enroll_reduced_load",
    "transfer_lower_cost_program",
    "pause_stop_out",
    "withdraw",
]

ALL_CHOICE_ACTIONS: tuple[ChoiceAction, ...] = (
    "enroll_full_load",
    "enroll_reduced_load",
    "transfer_lower_cost_program",
    "pause_stop_out",
    "withdraw",
)


class UtilityWeights(BaseModel):
    """Random-utility multinomial logit coefficients (uncalibrated defaults unless stated)."""
    model_config = ConfigDict(extra="forbid")

    beta_intercepts: dict[ChoiceAction, float] = Field(
        default_factory=lambda: {
            "enroll_full_load": 2.4,
            "enroll_reduced_load": 1.4,
            "transfer_lower_cost_program": 0.6,
            "pause_stop_out": -0.4,
            "withdraw": -1.3,
        }
    )
    beta_net_cost: float = -0.32          # per 10,000 TL of semester net cost / gap pressure
    beta_expected_credits: float = 0.08   # per expected credit earned this semester
    beta_expected_gpa: float = 0.45       # per expected grade point (0..4 scale)
    beta_time_to_degree: float = -0.18    # per remaining expected semester beyond baseline
    beta_personal: float = 1.10           # multiplier on preference_for_staying / stability
    coefficients_calibrated: bool = False
    calibration_note: str = (
        "Default synthetic beta coefficients; estimate and validate against historical "
        "institutional transitions before empirical claims."
    )


class CourseOffering(BaseModel):
    """Semester course offering with seat capacity and prerequisite dependencies."""
    model_config = ConfigDict(extra="forbid")

    course_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    credits: int = Field(default=6, ge=1, le=30)
    year_level: int = Field(default=1, ge=1, le=4)
    capacity: int = Field(ge=0)
    prerequisites: list[str] = Field(default_factory=list)
    difficulty_offset: float = Field(default=0.0, ge=-2.0, le=2.0)


class UniversityRuleset(BaseModel):
    """Academic, attendance, grading, and financial rules for multi-semester execution."""
    model_config = ConfigDict(extra="forbid")

    ruleset_id: str = Field(default="hypothetical_uni_rules_v1", pattern=r"^[a-z][a-z0-9_]{1,63}$")
    degree_credits_required: int = Field(default=120, ge=30, le=360)
    credits_per_course: int = Field(default=6, ge=1, le=30)
    full_load_courses: int = Field(default=5, ge=1, le=10)
    reduced_load_courses: int = Field(default=3, ge=1, le=8)
    attendance_min_pct: float = Field(default=70.0, ge=0.0, le=100.0)
    passing_grade_min: float = Field(default=2.0, ge=0.0, le=4.0)
    min_graduation_gpa: float = Field(default=2.0, ge=0.0, le=4.0)
    repeat_policy: Literal["replace_highest", "average_all"] = "replace_highest"
    max_stop_out_semesters: int = Field(default=2, ge=0, le=8)
    transfer_tuition_discount_pct: float = Field(default=50.0, ge=0.0, le=100.0)
    default_hold_threshold: float = Field(default=5_000.0, ge=0.0)
    osym_verified: bool = False
    coefficients_calibrated: bool = False
    source_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _validate_loads(self) -> UniversityRuleset:
        if self.reduced_load_courses > self.full_load_courses:
            raise ValueError("reduced_load_courses cannot exceed full_load_courses")
        return self

    def disclosure_banner(self) -> str:
        if self.osym_verified and self.coefficients_calibrated and self.source_note:
            return f"CALIBRATED RULESET: {self.source_note}"
        return DEFAULT_UNIVERSITY_DISCLAIMER


class StudentAgentRecord(BaseModel):
    """Synthetic student state tracking academic, financial, behavioral, and retention fields."""
    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(min_length=1, max_length=64)
    source_synthetic_id: str | None = None
    program_id: str = Field(min_length=1, max_length=64)
    province_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    year: int = Field(default=1, ge=1, le=6)
    gpa: float = Field(default=2.5, ge=0.0, le=4.0)
    earned_credits: int = Field(default=0, ge=0)
    attempted_credits: int = Field(default=0, ge=0)
    quality_points_total: float = Field(default=0.0, ge=0.0)
    completed_courses: list[str] = Field(default_factory=list)
    course_best_grades: dict[str, float] = Field(default_factory=dict)
    failed_prerequisites: list[str] = Field(default_factory=list)

    # Financial state (per-semester baseline values)
    tuition_per_semester: float = Field(default=50_000.0, ge=0.0)
    scholarship_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    need_aid_grant: float = Field(default=0.0, ge=0.0)
    income_band: Literal["low", "middle", "high"] = "middle"
    liquid_budget: float = Field(default=35_000.0, ge=0.0)
    semester_earnings: float = Field(default=10_000.0, ge=0.0)
    deferred_balance_due: float = Field(default=0.0, ge=0.0)
    missed_payments_count: int = Field(default=0, ge=0)
    has_financial_hold: bool = False

    # Behavioral traits (ASSUMED)
    study_hours_weekly: float = Field(default=14.0, ge=0.0, le=80.0)
    attendance_propensity: float = Field(default=0.84, ge=0.0, le=1.0)
    risk_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    preference_for_staying: float = Field(default=0.75, ge=0.0, le=1.0)
    academic_aptitude: float = Field(default=0.65, ge=0.0, le=1.0)

    # Lifecycle state
    state: StudentState = "active"
    stop_out_semesters: int = Field(default=0, ge=0)
    transferred: bool = False
    field_provenance: dict[str, str] = Field(default_factory=dict)


class AgentDecisionRecord(BaseModel):
    """Blueprint Section 8 per-agent, per-semester decision and trace record."""
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    semester: int = Field(ge=1)
    feasible_choices: list[ChoiceAction]
    chosen_action: ChoiceAction
    utility_inputs: dict[str, Any]
    probabilities: dict[str, float]
    seed: int
    trace_id: str


class SemesterFinancialLedger(BaseModel):
    """Per-student per-semester deterministic financial reconciliation."""
    model_config = ConfigDict(extra="forbid")

    published_tuition: float
    grants: float
    discounts: float
    net_tuition: float
    payments_due: float
    available_cash: float
    liquidity_gap: float
    payments_paid: float
    deferred_balance: float
    payment_default: bool = False


class SemesterSnapshot(BaseModel):
    """Aggregate academic, financial, and retention state at the end of a semester."""
    model_config = ConfigDict(extra="forbid")

    semester: int = Field(ge=0)
    active_students: int
    paused_stop_out_students: int
    transferred_students: int
    withdrawn_dropout_students: int
    graduated_students: int
    retention_rate_from_prev: float | None = None
    course_pass_rate: float | None = None
    mean_gpa: float
    mean_credits_earned_this_term: float
    total_waitlisted_requests: int = 0
    attendance_ineligible_courses: int = 0
    repeat_course_demands: int = 0
    payment_defaults: int = 0
    students_with_liquidity_gap: int = 0
    mean_liquidity_gap: float = 0.0
    total_net_tuition_revenue: float = 0.0
    total_aid_disbursed: float = 0.0


class UniversitySimulationManifest(BaseModel):
    """Reproducibility and validation manifest for a multi-semester simulation run."""
    model_config = ConfigDict(extra="forbid")

    engine_version: str = UNIVERSITY_ENGINE_VERSION
    scenario_id: str | None = None
    cohort_sha256: str
    courses_sha256: str
    ruleset_sha256: str
    intervention_sha256: str | None = None
    result_sha256: str
    seed: int
    semester_count: int
    osym_verified: bool
    coefficients_calibrated: bool
    disclaimer: str
    validation_checks: dict[str, bool]


class UniversitySimulationResult(BaseModel):
    """Complete output of a single deterministic multi-semester simulation run."""
    model_config = ConfigDict(extra="forbid")

    manifest: UniversitySimulationManifest
    semester_snapshots: list[SemesterSnapshot]
    final_students: list[StudentAgentRecord]
    decision_records: list[AgentDecisionRecord] = Field(default_factory=list)
    final_summary: dict[str, Any]


class UniversityComparisonReport(BaseModel):
    """Paired CRN counterfactual comparison across baseline and policy runs."""
    model_config = ConfigDict(extra="forbid")

    baseline_scenario_id: str | None = None
    policy_scenario_id: str | None = None
    replications: int
    cohort_sha256: str
    osym_verified: bool
    coefficients_calibrated: bool
    disclaimer: str
    policy_effects: dict[str, dict[str, float]]
    baseline_trajectory: list[dict[str, float | int]]
    policy_trajectory: list[dict[str, float | int]]
