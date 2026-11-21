"""Pydantic data models and validation for SocietyTwin policy scenarios.

Ensures strict schema validation, unique identifiers, bounded parameters,
and domain integrity for policy simulation experiments.
"""

from __future__ import annotations

import re
import string
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"

# Placeholders allowed in scenario description, question texts and option labels.
# They are resolved from the policy parameters at render time, so a parameter change can
# never leave a stale literal value in the text. Write a literal brace as '{{' or '}}'.
TEMPLATE_FIELDS: tuple[str, ...] = (
    "province_name",
    "baseline_fare",
    "new_fare",
    "increase_percentage",
    "currency",
    "fare_category",
    "effective_date",
)

SimulationMode = Literal[
    "survey_experiment",
    "university_placement",
    "university_decision_hybrid",
]
CapacityRoundingMode = Literal["floor", "nearest", "largest_remainder"]
AffordabilityFilterMode = Literal["none", "hard_exclude", "utility_rerank"]
RuleFidelity = Literal["hypothetical_simplified", "calibrated_synthetic", "verified_osym"]


def template_fields(text: str) -> list[str]:
    """Return the placeholder names used in ``text``; raise ValueError on malformed templates."""
    names: list[str] = []
    for _literal, field_name, format_spec, conversion in string.Formatter().parse(text):
        if field_name is None:
            continue
        if field_name == "" or format_spec or conversion:
            raise ValueError(
                f"Unsupported placeholder syntax in {text!r}: use plain named placeholders such as "
                f"{{new_fare}} (allowed: {', '.join(TEMPLATE_FIELDS)}); write literal braces as '{{{{' / '}}}}'"
            )
        names.append(field_name)
    return names


def _fmt_money(value: float) -> str:
    return f"{value:.2f}"


def _fmt_pct(value: float) -> str:
    return f"{value:g}"


class ScenarioMetadata(BaseModel):
    """Metadata describing authorship, reference periods, and empirical grounding."""
    model_config = ConfigDict(extra="forbid")

    hypothetical: bool = Field(
        default=True,
        description="Whether the policy intervention is a hypothetical simulation rather than enacted law.",
    )
    source_note: str | None = Field(
        default=None,
        max_length=2000,
        description="Citation or description of empirical baselines, tariffs, or survey instruments used.",
    )
    author: str | None = Field(default=None, max_length=120)
    reference_year: int | None = Field(default=None, ge=2000, le=2050)


class ScenarioLocation(BaseModel):
    """Geographic scope of the scenario."""
    model_config = ConfigDict(extra="forbid")

    province_code: str = Field(pattern=r"^\d{2}$", description="Two-digit TÜİK province code (e.g. '06' for Ankara)")
    province_name: str = Field(min_length=1, max_length=64)
    nuts2_code: str | None = Field(default=None, pattern=r"^[A-Z0-9]{4,5}$")


class UniversityPolicyIntervention(BaseModel):
    """Economic, capacity, and academic parameters for university placement and policy scenarios."""
    model_config = ConfigDict(extra="forbid")

    # Economic levers (UNI-001, UNI-002, UNI-006)
    tuition_change_pct: float | None = Field(default=None, gt=-100.0, le=1000.0)
    tuition_overrides: dict[str, float] = Field(default_factory=dict)
    aid_budget_change_pct: float | None = Field(default=None, gt=-100.0, le=1000.0)
    base_aid_budget: float | None = Field(default=None, ge=0.0)
    aid_income_eligibility_max: float | None = Field(default=None, ge=0.0)
    max_grant_per_student: float | None = Field(default=None, ge=0.0)
    installment_count: int | None = Field(default=None, ge=1, le=24)
    installment_upfront_share: float | None = Field(default=None, gt=0.0, le=1.0)
    affordability_filter_mode: AffordabilityFilterMode = "none"

    # Placement & capacity levers (UNI-005, OSYM-BARAJ, OBP penalty)
    capacity_change_pct: float | None = Field(default=None, ge=-100.0, le=1000.0)
    capacity_rounding: CapacityRoundingMode = "floor"
    program_capacity_overrides: dict[str, int] = Field(default_factory=dict)
    closed_programs: list[str] = Field(default_factory=list)
    rank_threshold_overrides: dict[str, int] = Field(default_factory=dict)
    min_score_overrides: dict[str, float] = Field(default_factory=dict)
    apply_prior_placement_obp_penalty: bool = False

    # Longitudinal / post-admission levers (shared contract for Milestone 2 university module)
    attendance_min_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    grading_difficulty_shift: float | None = Field(default=None, ge=-4.0, le=4.0)
    semester_count: int = Field(default=1, ge=1, le=16)
    replications: int = Field(default=1, ge=1, le=1000)

    # Rule provenance & non-official disclosure
    ruleset_id: str | None = Field(default=None, max_length=64)
    rule_fidelity: RuleFidelity = "hypothetical_simplified"
    osym_verified: bool = False

    @model_validator(mode="after")
    def _validate_university_intervention(self) -> UniversityPolicyIntervention:
        for pid, amount in self.tuition_overrides.items():
            if amount < 0:
                raise ValueError(f"tuition_overrides[{pid!r}] cannot be negative ({amount})")
        for pid, cap in self.program_capacity_overrides.items():
            if cap < 0:
                raise ValueError(f"program_capacity_overrides[{pid!r}] cannot be negative ({cap})")
        for group, rank in self.rank_threshold_overrides.items():
            if rank < 1:
                raise ValueError(f"rank_threshold_overrides[{group!r}] must be >= 1, got {rank}")
        for pid, score in self.min_score_overrides.items():
            if score < 0:
                raise ValueError(f"min_score_overrides[{pid!r}] cannot be negative ({score})")
        if self.osym_verified and self.rule_fidelity != "verified_osym":
            raise ValueError("osym_verified=True requires rule_fidelity='verified_osym'")
        if self.rule_fidelity == "verified_osym" and not self.osym_verified:
            raise ValueError("rule_fidelity='verified_osym' requires osym_verified=True")
        return self


class PolicyParameters(BaseModel):
    """Parameters specific to a public policy intervention."""
    model_config = ConfigDict(extra="forbid")

    baseline_fare: float | None = Field(default=None, gt=0, description="Pre-intervention baseline fare in currency units")
    new_fare: float | None = Field(default=None, gt=0, description="Post-intervention fare in currency units")
    increase_percentage: float | None = Field(
        default=None, gt=-100, le=1000,
        description="Percentage change in tariff (e.g. 20.0 for +20%; negative for a reduction)",
    )
    currency: str = Field(default="TL", max_length=10)
    fare_category: str | None = Field(default=None, max_length=64)
    effective_date: str | None = Field(default=None, max_length=32)
    subsidized_exemptions_note: str | None = Field(default=None, max_length=1000)
    policy_summary: str | None = Field(default=None, max_length=2000, description="Summary or rationale of the policy intervention")
    custom_details: dict[str, Any] = Field(default_factory=dict, description="Arbitrary policy domain attributes")

    @model_validator(mode="after")
    def _validate_consistency(self) -> PolicyParameters:
        if self.baseline_fare is not None and self.increase_percentage is not None and self.new_fare is not None:
            expected_new = self.baseline_fare * (1.0 + self.increase_percentage / 100.0)
            if abs(expected_new - self.new_fare) > 0.05:
                raise ValueError(
                    f"Inconsistent fare parameters: baseline {self.baseline_fare} with {self.increase_percentage}% "
                    f"increase implies {expected_new:.2f}, but new_fare was set to {self.new_fare}"
                )
        if "simulation_mode" in self.custom_details:
            mode = self.custom_details["simulation_mode"]
            if mode not in ("survey_experiment", "university_placement", "university_decision_hybrid"):
                raise ValueError(
                    f"Invalid simulation_mode {mode!r} in custom_details; expected one of "
                    "'survey_experiment', 'university_placement', 'university_decision_hybrid'."
                )
        if "university_intervention" in self.custom_details and self.custom_details["university_intervention"] is not None:
            raw_uni = self.custom_details["university_intervention"]
            validated = (
                raw_uni
                if isinstance(raw_uni, UniversityPolicyIntervention)
                else UniversityPolicyIntervention.model_validate(raw_uni)
            )
            self.custom_details["university_intervention"] = validated.model_dump(mode="json", exclude_none=True)
        return self

    @property
    def simulation_mode(self) -> SimulationMode:
        """Execution mode declared in custom_details, defaulting to 'survey_experiment'."""
        raw = self.custom_details.get("simulation_mode", "survey_experiment")
        if raw in ("survey_experiment", "university_placement", "university_decision_hybrid"):
            return raw  # type: ignore[return-value]
        return "survey_experiment"

    @property
    def university_intervention(self) -> UniversityPolicyIntervention | None:
        """Return typed UniversityPolicyIntervention when configured in custom_details."""
        raw = self.custom_details.get("university_intervention")
        if raw is None:
            return None
        if isinstance(raw, UniversityPolicyIntervention):
            return raw
        return UniversityPolicyIntervention.model_validate(raw)

    def resolved_fares(self) -> dict[str, float | None]:
        """Baseline, new fare and percentage with the missing one derived from the other two.

        Derivation is not persisted: authors may set any two of the three values and the third is
        computed consistently wherever the scenario is rendered or converted.
        """
        base, new, pct = self.baseline_fare, self.new_fare, self.increase_percentage
        if base is not None and pct is not None and new is None:
            new = round(base * (1.0 + pct / 100.0), 2)
        elif base is not None and new is not None and pct is None:
            pct = round((new - base) / base * 100.0, 2)
        elif new is not None and pct is not None and base is None and (1.0 + pct / 100.0) > 0:
            base = round(new / (1.0 + pct / 100.0), 2)
        return {"baseline_fare": base, "new_fare": new, "increase_percentage": pct}


class PolicyConfig(BaseModel):
    """High-level policy category and configuration."""
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=2, max_length=64, description="E.g., 'transportation', 'energy', 'housing'")
    type: str = Field(min_length=2, max_length=64, description="E.g., 'fare_increase', 'subsidy', 'tax_relief'")
    parameters: PolicyParameters


class PopulationFilterConfig(BaseModel):
    """Criteria defining which synthetic residents are eligible to participate in the scenario."""
    model_config = ConfigDict(extra="forbid")

    minimum_age: int | None = Field(default=0, ge=0, le=120)
    maximum_age: int | None = Field(default=None, ge=0, le=120)
    province_codes: list[str] | None = Field(default=None, description="List of 2-digit province codes")
    sexes: list[str] | None = Field(default=None, description="E.g. ['male', 'female']")
    marital_statuses: list[str] | None = Field(default=None)
    education_levels: list[str] | None = Field(default=None)
    adult_only: bool = Field(default=True, description="Strict filter requiring age >= 18")
    required_attributes: list[str] = Field(
        default_factory=lambda: ["age", "province_code"],
        description="Attributes that must not be null/missing in the synthetic resident record to evaluate eligibility",
    )

    @model_validator(mode="after")
    def _validate_age_bounds(self) -> PopulationFilterConfig:
        if self.adult_only:
            if self.minimum_age is None or self.minimum_age < 18:
                self.minimum_age = 18
        if self.minimum_age is not None and self.maximum_age is not None:
            if self.minimum_age > self.maximum_age:
                raise ValueError(f"minimum_age ({self.minimum_age}) cannot exceed maximum_age ({self.maximum_age})")
        if self.province_codes:
            for p in self.province_codes:
                if not re.match(r"^\d{2}$", p):
                    raise ValueError(f"Invalid province code '{p}': must be a 2-digit string")
        return self


class QuestionOption(BaseModel):
    """A single allowed option in a survey or choice question."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN, description="Unique alphanumeric identifier for the option")
    label: str = Field(min_length=1, max_length=500, description="Human-readable text presented to the respondent/agent")


class QuestionConfig(BaseModel):
    """Specification of an individual question presented to an AI persona."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN, description="Unique alphanumeric identifier for the question")
    text: str = Field(min_length=3, max_length=2000, description="The prompt/question text")
    type: Literal["single_choice", "multiple_choice", "free_text"] = Field(default="single_choice")
    options: list[QuestionOption] = Field(
        default_factory=list,
        max_length=20,
        description="Permitted answer options (required for choice questions; empty for free_text)",
    )
    min_length: int | None = Field(default=None, ge=1, le=5000, description="Minimum characters required for free_text")
    max_length: int | None = Field(default=2000, ge=1, le=10000, description="Maximum characters allowed for free_text")
    allow_other: bool = Field(default=False, description="Whether free-text input is allowed for an 'other' option")
    ask_rationale: bool = Field(default=True, description="Whether the agent is asked to supply a 1-2 sentence reason")

    @model_validator(mode="after")
    def _validate_unique_options(self) -> QuestionConfig:
        if self.type in ("single_choice", "multiple_choice"):
            if len(self.options) < 2:
                raise ValueError(
                    f"Question '{self.id}' of type '{self.type}' must have at least 2 options, found {len(self.options)}"
                )
            option_ids = [opt.id for opt in self.options]
            if len(option_ids) != len(set(option_ids)):
                duplicates = [oid for oid in option_ids if option_ids.count(oid) > 1]
                raise ValueError(f"Question '{self.id}' contains duplicate option IDs: {set(duplicates)}")
            if self.allow_other and "other" not in option_ids:
                raise ValueError(f"Question '{self.id}' specifies allow_other=True but has no option with id 'other'")
        elif self.type == "free_text":
            if self.allow_other:
                raise ValueError(f"Question '{self.id}' of type 'free_text' cannot specify allow_other=True")
            if self.min_length is not None and self.max_length is not None and self.min_length > self.max_length:
                raise ValueError(f"min_length ({self.min_length}) cannot exceed max_length ({self.max_length})")
        return self


class ScenarioConfig(BaseModel):
    """Root configuration model representing a complete policy scenario."""
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=ID_PATTERN, description="Unique identifier for the scenario (e.g. 'transport_fare_001')")
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$", description="Semantic version string")
    name: str = Field(min_length=3, max_length=160, description="Short human-readable title")
    description: str = Field(min_length=10, max_length=5000, description="Detailed narrative of the policy change")
    location: ScenarioLocation
    metadata: ScenarioMetadata = Field(default_factory=ScenarioMetadata)
    policy: PolicyConfig
    target_population: PopulationFilterConfig = Field(default_factory=PopulationFilterConfig)
    questions: list[QuestionConfig] = Field(min_length=1, max_length=30)

    @property
    def effective_simulation_mode(self) -> SimulationMode:
        """Execution mode declared for this scenario."""
        return self.policy.parameters.simulation_mode

    @property
    def university_intervention(self) -> UniversityPolicyIntervention | None:
        """Typed university intervention payload if present."""
        return self.policy.parameters.university_intervention

    @model_validator(mode="after")
    def _validate_unique_questions(self) -> ScenarioConfig:
        q_ids = [q.id for q in self.questions]
        if len(q_ids) != len(set(q_ids)):
            duplicates = [qid for qid in q_ids if q_ids.count(qid) > 1]
            raise ValueError(f"Scenario '{self.scenario_id}' contains duplicate question IDs: {set(duplicates)}")
        uni = self.policy.parameters.university_intervention
        if uni is not None and uni.osym_verified:
            if self.metadata.hypothetical:
                raise ValueError("An osym_verified=True scenario cannot mark metadata.hypothetical=True.")
            if not (self.metadata.source_note and self.metadata.source_note.strip()):
                raise ValueError("An osym_verified=True scenario must cite its official source in metadata.source_note.")
        return self

    @model_validator(mode="after")
    def _validate_templates(self) -> ScenarioConfig:
        values = self.template_values()
        for where, text in self._templated_texts():
            for name in template_fields(text):
                if name not in TEMPLATE_FIELDS:
                    raise ValueError(
                        f"Unknown placeholder '{{{name}}}' in {where}; allowed: {', '.join(TEMPLATE_FIELDS)}"
                    )
                if values[name] is None:
                    raise ValueError(
                        f"Placeholder '{{{name}}}' in {where} cannot be resolved: the corresponding policy "
                        f"parameter is not set (set it, or two of baseline_fare/new_fare/increase_percentage)"
                    )
        return self

    def _templated_texts(self) -> list[tuple[str, str]]:
        texts = [("description", self.description)]
        for q in self.questions:
            texts.append((f"question '{q.id}' text", q.text))
            texts.extend((f"question '{q.id}' option '{o.id}' label", o.label) for o in q.options)
        return texts

    def template_values(self) -> dict[str, str | None]:
        """Display strings for every placeholder (None when the value is not available)."""
        p = self.policy.parameters
        fares = p.resolved_fares()
        return {
            "province_name": self.location.province_name,
            "baseline_fare": _fmt_money(fares["baseline_fare"]) if fares["baseline_fare"] is not None else None,
            "new_fare": _fmt_money(fares["new_fare"]) if fares["new_fare"] is not None else None,
            "increase_percentage": (
                _fmt_pct(fares["increase_percentage"]) if fares["increase_percentage"] is not None else None
            ),
            "currency": p.currency,
            "fare_category": p.fare_category,
            "effective_date": p.effective_date,
        }

    def render_text(self, text: str) -> str:
        """Substitute placeholders in ``text`` with the scenario's current parameter values."""
        return text.format(**self.template_values())

    def rendered(self) -> ScenarioConfig:
        """A display copy with every placeholder resolved. Never save it back as a configuration."""
        questions = [
            q.model_copy(update={
                "text": self.render_text(q.text),
                "options": [o.model_copy(update={"label": self.render_text(o.label)}) for o in q.options],
            })
            for q in self.questions
        ]
        return self.model_copy(update={"description": self.render_text(self.description), "questions": questions})

    def get_question(self, question_id: str) -> QuestionConfig:
        """Return the question with ``question_id``; raise UnknownQuestionError if it does not exist."""
        for q in self.questions:
            if q.id == question_id:
                return q
        raise UnknownQuestionError(
            f"Scenario '{self.scenario_id}' has no question '{question_id}'. "
            f"Available question IDs: {[q.id for q in self.questions]}"
        )


class PlacementScenarioConfig(BaseModel):
    """Standalone university placement scenario model permitting empty survey questions."""
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=ID_PATTERN)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    simulation_mode: SimulationMode = "university_placement"
    name: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=5000)
    location: ScenarioLocation
    metadata: ScenarioMetadata = Field(default_factory=ScenarioMetadata)
    policy: PolicyConfig
    target_population: PopulationFilterConfig = Field(default_factory=PopulationFilterConfig)
    university_intervention: UniversityPolicyIntervention = Field(default_factory=UniversityPolicyIntervention)
    questions: list[QuestionConfig] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _validate_placement_scenario(self) -> PlacementScenarioConfig:
        if self.simulation_mode != "university_placement" and len(self.questions) < 1:
            raise ValueError(
                f"Scenario '{self.scenario_id}' with simulation_mode='{self.simulation_mode}' "
                "must define at least 1 question."
            )
        if self.university_intervention.osym_verified:
            if self.metadata.hypothetical:
                raise ValueError("An osym_verified=True scenario cannot mark metadata.hypothetical=True.")
            if not (self.metadata.source_note and self.metadata.source_note.strip()):
                raise ValueError("An osym_verified=True scenario must cite its official source in metadata.source_note.")
        return self

    @classmethod
    def from_scenario_config(cls, scenario: ScenarioConfig) -> PlacementScenarioConfig:
        """Build a PlacementScenarioConfig from a ScenarioConfig."""
        uni = scenario.university_intervention or UniversityPolicyIntervention()
        return cls(
            scenario_id=scenario.scenario_id,
            version=scenario.version,
            simulation_mode=scenario.effective_simulation_mode,
            name=scenario.name,
            description=scenario.description,
            location=scenario.location,
            metadata=scenario.metadata,
            policy=scenario.policy,
            target_population=scenario.target_population,
            university_intervention=uni,
            questions=scenario.questions,
        )


class UnknownQuestionError(LookupError):
    """Raised when a question ID does not exist in a scenario. Not a KeyError, so it is never
    confused with a missing scenario."""
