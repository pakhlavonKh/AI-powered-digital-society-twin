"""Validated request models for cohorts and experiment drafts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from societytwin.sampling.filters import FilterSpec
from societytwin.sampling.srs import MAX_SEED

ModeName = Literal["preflight", "smoke", "legacy_ab_live"]
PersonaSource = Literal["cohort", "legacy_fixture_pair", "legacy_fixture_single"]
EnvironmentName = Literal["SURVEY", "SCENARIO"]
MODEL_PATTERN = r"^[a-z0-9]{2,32}/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class CohortPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    build_id: str = Field(min_length=1, max_length=128)
    filters: FilterSpec = Field(default_factory=FilterSpec)


class CohortCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    build_id: str = Field(min_length=1, max_length=128)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Hash returned by the preview; a changed source is rejected.")
    filters: FilterSpec = Field(default_factory=FilterSpec)
    size: int = Field(ge=1, le=1_000_000)
    sampling: Literal["simple_random"] = "simple_random"
    seed: int = Field(ge=0, le=MAX_SEED)
    name: str | None = Field(default=None, max_length=120)


class ScenarioSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["none", "draft"] = "none"
    text: str | None = Field(default=None, max_length=4000)
    version: str | None = Field(default=None, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")

    @model_validator(mode="after")
    def _text_matches_kind(self):
        if self.kind == "draft" and not (self.text and self.text.strip()):
            raise ValueError("A draft scenario needs text")
        if self.kind == "none" and self.text:
            raise ValueError("Scenario text requires kind 'draft'")
        return self


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["product_feedback_v1"] = Field(description="The only verified task: MatrAIx example-survey_product-feedback.")


class ExperimentDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    persona_source: PersonaSource
    cohort_id: str | None = Field(default=None, max_length=64)
    scenario: ScenarioSpec = Field(default_factory=ScenarioSpec)
    task: TaskSpec
    environment: EnvironmentName = "SURVEY"
    mode: ModeName = "preflight"
    model: str | None = Field(default=None, pattern=MODEL_PATTERN)
    temperature: float | None = Field(default=None, ge=0, le=1)
    calls_limit: int = Field(ge=0, le=10, description="Maximum provider calls the researcher authorises for this draft.")

    @model_validator(mode="after")
    def _consistent(self):
        if self.persona_source == "cohort" and not self.cohort_id:
            raise ValueError("persona_source 'cohort' requires cohort_id")
        if self.persona_source != "cohort" and self.cohort_id:
            raise ValueError("cohort_id is only valid with persona_source 'cohort'")
        if self.mode == "smoke" and (self.model is not None or self.temperature is not None):
            raise ValueError("Smoke mode uses the deterministic fake transport; leave model and temperature empty")
        return self


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preflight_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: Literal["smoke", "legacy_ab_live"]
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
