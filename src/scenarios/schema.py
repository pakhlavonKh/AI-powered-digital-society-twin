"""Pydantic data models and validation for SocietyTwin policy scenarios.

Ensures strict schema validation, unique identifiers, bounded parameters,
and domain integrity for policy simulation experiments.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"


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


class PolicyParameters(BaseModel):
    """Parameters specific to a public policy intervention."""
    model_config = ConfigDict(extra="forbid")

    baseline_fare: float | None = Field(default=None, gt=0, description="Pre-intervention baseline fare in currency units")
    new_fare: float | None = Field(default=None, gt=0, description="Post-intervention fare in currency units")
    increase_percentage: float | None = Field(default=None, description="Percentage change in tariff (e.g. 20.0 for +20%)")
    currency: str = Field(default="TL", max_length=10)
    fare_category: str | None = Field(default="full_adult_standard", max_length=64)
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
        return self


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
    type: Literal["single_choice", "multiple_choice"] = Field(default="single_choice")
    options: list[QuestionOption] = Field(min_length=2, max_length=20, description="Permitted answer options")
    allow_other: bool = Field(default=False, description="Whether free-text input is allowed for an 'other' option")
    ask_rationale: bool = Field(default=True, description="Whether the agent is asked to supply a 1-2 sentence reason")

    @model_validator(mode="after")
    def _validate_unique_options(self) -> QuestionConfig:
        option_ids = [opt.id for opt in self.options]
        if len(option_ids) != len(set(option_ids)):
            duplicates = [oid for oid in option_ids if option_ids.count(oid) > 1]
            raise ValueError(f"Question '{self.id}' contains duplicate option IDs: {set(duplicates)}")
        if self.allow_other and "other" not in option_ids:
            raise ValueError(f"Question '{self.id}' specifies allow_other=True but has no option with id 'other'")
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

    @model_validator(mode="after")
    def _validate_unique_questions(self) -> ScenarioConfig:
        q_ids = [q.id for q in self.questions]
        if len(q_ids) != len(set(q_ids)):
            duplicates = [qid for qid in q_ids if q_ids.count(qid) > 1]
            raise ValueError(f"Scenario '{self.scenario_id}' contains duplicate question IDs: {set(duplicates)}")
        return self
