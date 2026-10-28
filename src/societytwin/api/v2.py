"""/api/v2: the national pipeline (Türkiye-wide populations, cohorts, personas, experiments, runs).

/api/v1 stays unchanged and serves the historical Ankara fixtures and recorded MatrAIx runs.
Handlers validate input and delegate to ``NationalService``; mutations are loopback-only (app middleware).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from scenarios.schema import ScenarioConfig
from societytwin.errors import WorkbenchError, conflict, invalid, not_found
from societytwin.national.cohorts import CohortDefinitionRequest, CohortSampleRequest
from societytwin.national.experiments import ExperimentDefinition, example_fare_definition
from societytwin.national.generator import MAX_SIZE, GenerationConfig
from societytwin.national.rng import MAX_SEED
from societytwin.national.service import NationalService
from societytwin.national.store import MAX_PAGE, SORTABLE, PopulationFilter


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_year: int = Field(default=2025, ge=1990, le=2100)
    synthetic_size: int = Field(default=10_000, ge=1, le=MAX_SIZE)
    seed: int = Field(default=42, ge=0, le=MAX_SEED)
    province_codes: list[str] | None = Field(default=None, max_length=81)
    min_records_per_province: int = Field(default=0, ge=0, le=100_000)
    calibrate: bool = True


class CohortPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    population_id: str = Field(min_length=1, max_length=160)
    filters: PopulationFilter = Field(default_factory=PopulationFilter)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    confirm: Literal[True] = Field(description="Explicit confirmation that the reviewed plan should execute.")


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ScenarioPromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=3, max_length=4000, description="Natural language prompt describing the policy scenario")
    model: str | None = Field(default=None, max_length=128, description="Optional LLM model identifier")
    save: bool = Field(default=True, description="Whether to register and save the generated scenario to catalog")


def _filters(
    province_codes: Annotated[list[str] | None, Query()] = None,
    age_min: Annotated[int | None, Query(ge=0, le=120)] = None,
    age_max: Annotated[int | None, Query(ge=0, le=120)] = None,
    age_groups: Annotated[list[str] | None, Query()] = None,
    sexes: Annotated[list[str] | None, Query()] = None,
    marital_statuses: Annotated[list[str] | None, Query()] = None,
    education_levels: Annotated[list[str] | None, Query()] = None,
    labour_statuses: Annotated[list[str] | None, Query()] = None,
    household_size_classes: Annotated[list[str] | None, Query()] = None,
    household_types: Annotated[list[str] | None, Query()] = None,
    urbanicities: Annotated[list[str] | None, Query()] = None,
    adult_only: bool = False,
) -> PopulationFilter:
    try:
        return PopulationFilter(province_codes=province_codes, age_min=age_min, age_max=age_max, age_groups=age_groups, sexes=sexes,
                                marital_statuses=marital_statuses, education_levels=education_levels, labour_statuses=labour_statuses,
                                household_size_classes=household_size_classes, household_types=household_types,
                                urbanicities=urbanicities, adult_only=adult_only)
    except ValueError as exc:
        raise WorkbenchError("invalid", "invalid_filter", "Invalid population filter", [str(exc)]) from exc


def _svc(request: Request) -> NationalService:
    return request.app.state.workbench.national


S = Annotated[NationalService, Depends(_svc)]
F = Annotated[PopulationFilter, Depends(_filters)]


def build_router() -> APIRouter:
    r = APIRouter(prefix="/api/v2")

    @r.get("/overview", tags=["national"])
    def overview(s: S):
        return s.overview()

    @r.get("/capabilities", tags=["national"])
    def capabilities(s: S):
        return s.capabilities()

    @r.get("/geography/provinces", tags=["national"])
    def provinces(s: S, reference_year: Annotated[int, Query(ge=1990, le=2100)] = 2025, population_id: str | None = None):
        return s.geography(reference_year, population_id)

    @r.get("/environments/{province_code}", tags=["national"])
    def environment(province_code: str, s: S, reference_year: Annotated[int, Query(ge=1990, le=2100)] = 2025):
        return s.environment(province_code, reference_year)

    @r.get("/controls", tags=["data"])
    def controls(s: S):
        return s.controls_status()

    @r.post("/controls/build", tags=["data"], description="Normalise the available official tables into the control store.")
    def controls_build(s: S):
        return s.build_controls()

    @r.get("/data-sources", tags=["data"])
    def data_sources(request: Request, s: S):
        wb = request.app.state.workbench
        return {"controls": s.controls_status(), "root_manifest": wb.datasets()["manifest"],
                "package": {"directory": "data/raw/tuik_package", "present": s.settings.tuik_package_dir.is_dir(),
                            "files": sum(1 for p in s.settings.tuik_package_dir.iterdir() if p.is_file() and not p.name.startswith("."))
                            if s.settings.tuik_package_dir.is_dir() else 0,
                            "mapping_file": "data/tuik_package_mapping.yaml", "mapping_present": s.settings.tuik_mapping_path.is_file()}}

    @r.get("/populations", tags=["population"])
    def populations(s: S):
        return s.list_populations()

    @r.post("/populations", status_code=201, tags=["population"],
            description="Generate a synthetic population (or reuse the identical existing build) and validate it.")
    def generate(body: GenerateRequest, s: S):
        return s.generate(GenerationConfig(reference_year=body.reference_year, synthetic_size=body.synthetic_size, seed=body.seed,
                                           provinces=tuple(PopulationFilter(province_codes=body.province_codes).province_codes)
                                           if body.province_codes else None,
                                           min_records_per_province=body.min_records_per_province, calibrate=body.calibrate))

    @r.get("/populations/{population_id}", tags=["population"])
    def population(population_id: str, s: S):
        return s.population(population_id)

    @r.get("/populations/{population_id}/summary", tags=["population"])
    def summary(population_id: str, s: S, filters: F):
        return s.summary(population_id, filters)

    @r.get("/populations/{population_id}/records", tags=["population"])
    def records(population_id: str, s: S, filters: F, sort: Literal[SORTABLE] = "synthetic_id",  # type: ignore[valid-type]
                direction: Literal["asc", "desc"] = "asc", offset: Annotated[int, Query(ge=0)] = 0,
                limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50):
        return s.records(population_id, filters, sort, direction, offset, limit)

    @r.get("/populations/{population_id}/records/{synthetic_id}", tags=["population"])
    def record(population_id: str, synthetic_id: str, s: S, visible_fields: Annotated[list[str] | None, Query()] = None):
        return s.record(population_id, synthetic_id, visible_fields)

    @r.get("/populations/{population_id}/validation", tags=["validation"])
    def validation(population_id: str, s: S, province_code: str | None = None):
        return s.validation(population_id, province_code)

    @r.post("/cohorts/preview", tags=["cohorts"], description="Counts only; nothing is saved.")
    def cohort_preview(body: CohortPreviewRequest, s: S):
        return s.preview_cohort(body.population_id, body.filters)

    @r.post("/cohorts", status_code=201, tags=["cohorts"])
    def cohort_create(body: CohortDefinitionRequest, s: S):
        return s.create_cohort(body)

    @r.get("/cohorts", tags=["cohorts"])
    def cohort_list(s: S):
        return s.cohorts()

    @r.get("/cohorts/{cohort_id}", tags=["cohorts"])
    def cohort_get(cohort_id: str, s: S):
        return s.cohort(cohort_id)

    @r.post("/cohorts/{cohort_id}/samples", status_code=201, tags=["cohorts"],
            description="Draw (or reuse the identical) seeded sample from the cohort.")
    def cohort_sample(cohort_id: str, body: CohortSampleRequest, s: S):
        return s.draw_sample(cohort_id, body)

    @r.get("/samples/{sample_id}", tags=["cohorts"])
    def sample(sample_id: str, s: S):
        return s.sample(sample_id)

    @r.get("/samples/{sample_id}/personas", tags=["personas"])
    def sample_personas(sample_id: str, s: S, offset: Annotated[int, Query(ge=0)] = 0,
                        limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 24,
                        visible_fields: Annotated[list[str] | None, Query()] = None):
        return s.sample_personas(sample_id, offset, limit, visible_fields)

    @r.get("/scenarios", tags=["experiments"],
           description="List all available policy scenarios from registered scenario directories.")
    def list_scenarios():
        from scenarios.adapter import list_available_scenarios
        return {"items": list_available_scenarios()}

    @r.get("/scenarios/{scenario_id}", tags=["experiments"],
           description="Retrieve full scenario configuration by scenario_id.")
    def get_scenario_detail(scenario_id: str):
        from scenarios.adapter import get_scenario
        try:
            return get_scenario(scenario_id).model_dump(mode="json")
        except KeyError as exc:
            raise not_found("scenario_not_found", str(exc))

    @r.get("/scenarios/{scenario_id}/experiment-definition", tags=["experiments"],
           description="Transform a scenario into an experiment definition for a given cohort.")
    def get_scenario_experiment_definition(
        scenario_id: str,
        cohort_id: Annotated[str | None, Query()] = None,
        question_id: Annotated[str | None, Query()] = None,
        seed: Annotated[int, Query()] = 7,
    ):
        from scenarios.adapter import get_scenario, scenario_to_experiment_definition, UnsupportedQuestionTypeError
        from scenarios.schema import UnknownQuestionError
        try:
            scenario = get_scenario(scenario_id)
            return scenario_to_experiment_definition(scenario, cohort_id or "", question_id, seed)
        except KeyError as exc:
            raise not_found("scenario_not_found", str(exc))
        except UnknownQuestionError as exc:
            raise not_found("question_not_found", str(exc))
        except UnsupportedQuestionTypeError as exc:
            raise invalid("unsupported_question_type", str(exc))

    @r.post("/scenarios", status_code=201, tags=["experiments"],
           description="Create and register a custom policy scenario definition.")
    def create_scenario(body: ScenarioConfig):
        from scenarios.adapter import save_custom_scenario, ScenarioConflictError
        try:
            saved = save_custom_scenario(body)
            return saved.model_dump(mode="json")
        except ScenarioConflictError as exc:
            raise conflict("scenario_conflict", str(exc))
        except (ValueError, KeyError) as exc:
            raise invalid("scenario_invalid", str(exc))

    @r.post("/scenarios/from-prompt", status_code=201, tags=["experiments"],
           description="Compile a natural language prompt into a validated policy scenario.")
    def create_scenario_from_prompt(body: ScenarioPromptRequest):
        from scenarios.compiler import compile_scenario_from_prompt
        from scenarios.adapter import save_custom_scenario
        try:
            scenario = compile_scenario_from_prompt(body.prompt, model=body.model)
            if body.save:
                saved = save_custom_scenario(scenario)
                return saved.model_dump(mode="json")
            return scenario.model_dump(mode="json")
        except Exception as exc:
            raise invalid("scenario_compilation_failed", str(exc))

    @r.get("/examples/fare-experiment", tags=["experiments"],
           description="The demonstration design with explicitly HYPOTHETICAL fare parameters.")
    def example(cohort_id: str):
        try:
            from scenarios.adapter import get_scenario, scenario_to_experiment_definition
            scenario = get_scenario("transport_fare_001")
            return scenario_to_experiment_definition(scenario, cohort_id)
        except KeyError:
            return example_fare_definition(cohort_id)

    @r.post("/experiments", status_code=201, tags=["experiments"], description="Saves a definition. Nothing runs.")
    def experiment_create(body: ExperimentDefinition, s: S):
        return s.create_experiment(body)

    @r.get("/experiments", tags=["experiments"])
    def experiment_list(s: S):
        return s.experiments()

    @r.get("/experiments/{experiment_id}", tags=["experiments"])
    def experiment_get(experiment_id: str, s: S):
        return s.experiment(experiment_id)

    @r.post("/experiments/{experiment_id}/plan", status_code=201, tags=["experiments"],
            description="Reviewed plan: eligible records, sample, personas, calls, cost, warnings, blockers. Makes no calls.")
    def experiment_plan(experiment_id: str, s: S):
        return s.plan(experiment_id)

    @r.post("/experiments/{experiment_id}/runs", status_code=202, tags=["experiments"],
            description="Executes a reviewed plan once. Stub runs complete in the request; MatrAIx runs are queued for the worker.")
    def experiment_run(experiment_id: str, body: RunRequest, s: S):
        return s.start_run(experiment_id, body.plan_hash, body.idempotency_key)

    @r.get("/runs", tags=["results"])
    def runs(s: S):
        return s.runs()

    @r.get("/runs/{run_id}", tags=["results"])
    def run(run_id: str, s: S):
        return s.run(run_id)

    @r.get("/runs/{run_id}/responses", tags=["results"])
    def run_responses(run_id: str, s: S, final_only: bool = True, offset: Annotated[int, Query(ge=0)] = 0,
                      limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50):
        return s.run_responses(run_id, final_only, offset, limit)

    @r.get("/runs/{run_id}/aggregate", tags=["results"])
    def run_aggregate(run_id: str, s: S, group_by: Annotated[list[str] | None, Query()] = None,
                      min_group: Annotated[int, Query(ge=1, le=1000)] = 10):
        return s.run_aggregate(run_id, group_by or [], min_group)

    @r.post("/runs/{run_id}/replay", status_code=202, tags=["results"],
            description="Reproduces a completed run exactly from the response cache; makes no backend calls.")
    def run_replay(run_id: str, body: ReplayRequest, s: S):
        return s.replay(run_id, body.idempotency_key)

    return r
