"""Typed query specification and behavioral preference configuration for prompt-driven university simulations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .schema import UniversityPolicyIntervention

UniversityIntent = Literal[
    "application_demand",
    "ranking_sensitivity",
    "cutoff_impact",
    "placement_fill",
    "affordability_equity",
    "scholarship_aid",
    "quota_capacity",
    "revenue_tradeoff",
    "retention_impact",
    "competitor_flow",
    "multi_scenario_compare",
    "composite",
]

ElasticityPreset = Literal["low", "medium", "high"]
QuerySimulationMode = Literal["placement", "retention", "both"]


class PreferenceModelConfig(BaseModel):
    """Uncalibrated synthetic random-utility parameters for policy-responsive applications."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    elasticity_preset: ElasticityPreset = "medium"
    beta_rank: float = Field(default=2.2, ge=0.0, le=20.0)
    beta_cost_by_income: dict[str, float] = Field(
        default_factory=lambda: {"low": 1.45, "middle": 0.72, "high": 0.42}
    )
    beta_home: float = Field(default=0.65, ge=0.0, le=10.0)
    beta_fit: float = Field(default=0.85, ge=0.0, le=10.0)
    outside_option_threshold: float = Field(default=0.72, ge=-10.0, le=10.0)
    top_k_definition: int = Field(default=3, ge=1, le=24)
    coefficients_calibrated: bool = False
    calibration_note: str = (
        "Synthetic uncalibrated behavioral elasticities; low/medium/high sensitivity range reported."
    )


def preset_preference_config(
    preset: ElasticityPreset,
    *,
    top_k_definition: int = 3,
    enabled: bool = True,
) -> PreferenceModelConfig:
    """Return a deterministic low/medium/high sensitivity preset."""
    presets: dict[ElasticityPreset, dict[str, Any]] = {
        "low": {
            "beta_rank": 1.6,
            "beta_cost_by_income": {"low": 0.90, "middle": 0.40, "high": 0.20},
            "beta_home": 0.70,
            "beta_fit": 0.90,
            "outside_option_threshold": 0.52,
        },
        "medium": {
            "beta_rank": 2.2,
            "beta_cost_by_income": {"low": 1.45, "middle": 0.72, "high": 0.42},
            "beta_home": 0.65,
            "beta_fit": 0.85,
            "outside_option_threshold": 0.72,
        },
        "high": {
            "beta_rank": 3.0,
            "beta_cost_by_income": {"low": 2.20, "middle": 1.15, "high": 0.68},
            "beta_home": 0.55,
            "beta_fit": 0.75,
            "outside_option_threshold": 0.92,
        },
    }
    cfg = presets[preset]
    return PreferenceModelConfig(
        enabled=enabled,
        elasticity_preset=preset,
        top_k_definition=top_k_definition,
        coefficients_calibrated=False,
        **cfg,
    )


class QueryAssumption(BaseModel):
    """Explicit assumption parsed or defaulted from an NLP university query."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=160)
    value: Any
    source: Literal["user", "default", "inferred"] = "default"
    editable: bool = True
    unit: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=500)


class QueryVariantSpec(BaseModel):
    """Named counterfactual policy variant for directional or multi-scenario comparisons."""

    model_config = ConfigDict(extra="forbid")

    variant_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=160)
    intervention: UniversityPolicyIntervention
    is_baseline: bool = False


class UnresolvedEntity(BaseModel):
    """Ambiguous or unmatched university/department/lever mention requiring user confirmation."""

    model_config = ConfigDict(extra="forbid")

    mention: str = Field(min_length=1, max_length=200)
    entity_type: Literal["university", "department", "program", "lever"]
    reason: str = Field(min_length=1, max_length=500)
    candidates: list[dict[str, str]] = Field(default_factory=list)


class UniversityQuerySpec(BaseModel):
    """Structured representation of a natural-language university simulation query."""

    model_config = ConfigDict(extra="forbid")

    original_prompt: str = Field(min_length=3, max_length=4000)
    language: Literal["en", "tr", "mixed"] = "en"
    intent: UniversityIntent = "application_demand"
    focus_university_id: str | None = Field(default=None, max_length=128)
    focus_university_name: str | None = Field(default=None, max_length=200)
    focus_program_ids: list[str] = Field(default_factory=list)
    focus_department_names: list[str] = Field(default_factory=list)
    snapshot_id: str | None = Field(default=None, max_length=128)
    admission_year: int | None = Field(default=None, ge=1990, le=2100)
    levers: UniversityPolicyIntervention = Field(default_factory=UniversityPolicyIntervention)
    comparison_variants: list[QueryVariantSpec] = Field(default_factory=list)
    sweep_tuition_pcts: list[float] = Field(default_factory=list)
    metrics_requested: list[str] = Field(default_factory=list)
    subgroup_dimensions_requested: list[str] = Field(default_factory=list)
    simulation_mode: QuerySimulationMode = "placement"
    cohort_size: int = Field(default=200, ge=20, le=5000)
    seed: int = Field(default=42, ge=0)
    assumptions: list[QueryAssumption] = Field(default_factory=list)
    disclaimers: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    unresolved_entities: list[UnresolvedEntity] = Field(default_factory=list)
    out_of_scope_reasons: list[str] = Field(default_factory=list)
