"""Workbench service bridge for Milestone 1 placement & Milestone 2 university simulations.

Provides persisted `/api/v2/placement/*` and `/api/v2/university/*` operations backed by SQLite
Migration 3 (`university_placement_runs`, `university_policy_runs`) while always enforcing explicit
hypothetical/uncalibrated disclosures (`osym_verified=False`, `coefficients_calibrated=False`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from scenarios.adapter import get_scenario, placement_result_to_student_cohort
from scenarios.placement.cohort_synth import (
    build_standalone_demo_programs,
    build_standalone_test_cohort,
    build_tuik_anchored_candidates,
)
from scenarios.placement.comparison import ComparisonMismatchError, compare_placement_scenarios
from scenarios.placement.engine import run_placement
from scenarios.placement.models import PlacementResult, PlacementRuleset, ProgramOffering
from scenarios.schema import ScenarioConfig, UniversityPolicyIntervention
from scenarios.summary import (
    summarize_placement_comparison,
    summarize_placement_result,
    summarize_university_comparison,
    summarize_university_result,
)
from scenarios.university.cohort import (
    build_synthetic_university_cohort,
    student_cohort_from_placement_handoff,
)
from scenarios.university.experiments import (
    run_replicated_university_experiment,
    run_tuition_sensitivity_sweep,
)
from scenarios.university.models import UniversityRuleset, UtilityWeights
from scenarios.university.semester_engine import run_university_simulation
from societytwin.common import canonical_hash, new_id, utc_now
from societytwin.errors import conflict, invalid, not_found
from societytwin.national.rng import MAX_SEED

if TYPE_CHECKING:
    from societytwin.national.service import NationalService


class PlacementRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str | None = Field(default=None, max_length=128)
    population_id: str | None = Field(default=None, max_length=160)
    cohort_size: int = Field(default=200, ge=20, le=5000)
    seed: int = Field(default=42, ge=0, le=MAX_SEED)
    compare_baseline: bool = True
    intervention: UniversityPolicyIntervention | None = None
    ruleset: PlacementRuleset | None = None


class PlacementCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_run_id: str = Field(min_length=1, max_length=128)
    policy_run_id: str = Field(min_length=1, max_length=128)


class UniversityRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str | None = Field(default=None, max_length=128)
    placement_run_id: str | None = Field(default=None, max_length=128)
    cohort_size: int = Field(default=200, ge=20, le=2000)
    semester_count: int | None = Field(default=None, ge=1, le=8)
    replications: int | None = Field(default=None, ge=1, le=100)
    seed: int = Field(default=42, ge=0, le=MAX_SEED)
    compare_baseline: bool = True
    intervention: UniversityPolicyIntervention | None = None
    ruleset: UniversityRuleset | None = None
    weights: UtilityWeights | None = None


class UniversitySweepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    placement_run_id: str | None = Field(default=None, max_length=128)
    cohort_size: int = Field(default=160, ge=20, le=2000)
    semester_count: int = Field(default=4, ge=1, le=8)
    replications: int = Field(default=5, ge=1, le=50)
    seed: int = Field(default=42, ge=0, le=MAX_SEED)
    tuition_pcts: list[float] = Field(default_factory=lambda: [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0], min_length=2, max_length=15)
    aid_budget_pct: float | None = Field(default=None, ge=-100.0, le=500.0)


def _resolve_scenario_and_intervention(
    scenario_id: str | None,
    explicit: UniversityPolicyIntervention | None,
) -> tuple[ScenarioConfig | None, UniversityPolicyIntervention]:
    scenario: ScenarioConfig | None = None
    if scenario_id:
        try:
            scenario = get_scenario(scenario_id)
        except KeyError as exc:
            raise not_found("scenario_not_found", str(exc)) from exc
        base_int = scenario.university_intervention or UniversityPolicyIntervention()
    else:
        base_int = UniversityPolicyIntervention()

    if explicit is not None:
        return scenario, explicit
    return scenario, base_int


def placement_programs_catalog() -> dict[str, Any]:
    """Return the built-in hypothetical demo placement programs and score metadata."""
    programs = build_standalone_demo_programs()
    ruleset = PlacementRuleset()
    return {
        "osym_verified": ruleset.osym_verified,
        "rule_fidelity": ruleset.rule_fidelity,
        "disclaimer": ruleset.disclosure_banner(),
        "score_types": ["SAY", "EA", "SÖZ", "DİL", "TYT"],
        "rank_thresholds": ruleset.rank_thresholds,
        "programs": [p.model_dump(mode="json") for p in programs],
    }


def _resolve_candidate_cohort(
    service: NationalService,
    population_id: str | None,
    programs: list[ProgramOffering],
    cohort_size: int,
    seed: int,
):
    if population_id:
        loaded = service._load(population_id)
        try:
            return build_tuik_anchored_candidates(
                loaded,
                programs,
                sample_size=cohort_size,
                seed=seed,
            )
        except ValueError as exc:
            raise invalid("insufficient_cohort", str(exc)) from exc
    return build_standalone_test_cohort(programs, size=cohort_size, seed=seed)


def run_placement_workbench(service: NationalService, req: PlacementRunRequest) -> dict[str, Any]:
    """Execute Milestone 1 central placement (with optional baseline comparison) and persist it."""
    scenario, intervention = _resolve_scenario_and_intervention(req.scenario_id, req.intervention)
    programs = build_standalone_demo_programs()
    ruleset = req.ruleset or PlacementRuleset()
    cohort = _resolve_candidate_cohort(service, req.population_id, programs, req.cohort_size, req.seed)

    policy_result = run_placement(
        candidates=cohort.candidates,
        programs=programs,
        ruleset=ruleset,
        intervention=intervention,
        scenario=scenario,
        seed=req.seed,
    )

    comparison_dict: dict[str, Any] | None = None
    if req.compare_baseline:
        baseline_result = run_placement(
            candidates=cohort.candidates,
            programs=programs,
            ruleset=ruleset,
            intervention=UniversityPolicyIntervention(),
            scenario=None,
            seed=req.seed,
        )
        comp = compare_placement_scenarios(baseline_result, policy_result)
        comparison_dict = comp.model_dump(mode="json")
        summary = summarize_placement_comparison(comp)
    else:
        summary = summarize_placement_result(policy_result)

    handoff = placement_result_to_student_cohort(policy_result, cohort, programs)
    result_payload = {
        "placement_result": policy_result.model_dump(mode="json"),
        "comparison": comparison_dict,
        "handoff": handoff,
        "demographic_source": cohort.demographic_source,
        "admitted_count": handoff["student_count"],
    }

    req_payload = req.model_dump(mode="json")
    run_id = new_id("uplace")
    created_at = utc_now()
    record = {
        "run_id": run_id,
        "scenario_id": req.scenario_id,
        "population_id": req.population_id,
        "request_hash": canonical_hash(req_payload),
        "result_sha256": policy_result.manifest.result_sha256,
        "osym_verified": policy_result.manifest.osym_verified,
        "request": req_payload,
        "result": result_payload,
        "summary": summary,
        "created_at": created_at,
    }
    service.db.insert_placement_run(record)
    return {
        "run_id": run_id,
        "scenario_id": req.scenario_id,
        "population_id": req.population_id,
        "osym_verified": policy_result.manifest.osym_verified,
        "rule_fidelity": policy_result.manifest.rule_fidelity,
        "disclaimer": policy_result.manifest.disclaimer,
        "result_sha256": policy_result.manifest.result_sha256,
        "created_at": created_at,
        "summary": summary,
        "result": result_payload,
    }


def list_placement_runs_workbench(service: NationalService) -> dict[str, Any]:
    rows = service.db.placement_runs()
    return {"items": rows, "total": len(rows)}


def get_placement_run_workbench(service: NationalService, run_id: str) -> dict[str, Any]:
    row = service.db.placement_run(run_id)
    if row is None:
        raise not_found("unknown_placement_run", f"No placement run '{run_id}'.")
    return row


def compare_placement_runs_workbench(service: NationalService, req: PlacementCompareRequest) -> dict[str, Any]:
    base_row = get_placement_run_workbench(service, req.baseline_run_id)
    pol_row = get_placement_run_workbench(service, req.policy_run_id)
    base_res = PlacementResult.model_validate(base_row["result"]["placement_result"])
    pol_res = PlacementResult.model_validate(pol_row["result"]["placement_result"])
    try:
        comp = compare_placement_scenarios(base_res, pol_res)
    except ComparisonMismatchError as exc:
        raise conflict("cohort_mismatch", str(exc)) from exc
    return {
        "baseline_run_id": req.baseline_run_id,
        "policy_run_id": req.policy_run_id,
        "comparison": comp.model_dump(mode="json"),
        "summary": summarize_placement_comparison(comp),
    }


def _resolve_university_cohort(
    service: NationalService,
    placement_run_id: str | None,
    cohort_size: int,
    seed: int,
):
    if placement_run_id:
        place_row = get_placement_run_workbench(service, placement_run_id)
        handoff = place_row["result"]["handoff"]
        if not handoff.get("students"):
            raise invalid("empty_placement_handoff", f"Placement run '{placement_run_id}' has 0 admitted students.")
        return student_cohort_from_placement_handoff(handoff, seed=seed)
    return build_synthetic_university_cohort(size=cohort_size, seed=seed)


def run_university_workbench(service: NationalService, req: UniversityRunRequest) -> dict[str, Any]:
    """Execute Milestone 2 multi-semester policy simulation (with optional CRN comparison) and persist it."""
    _, intervention = _resolve_scenario_and_intervention(req.scenario_id, req.intervention)
    eff_semesters = req.semester_count if req.semester_count is not None else intervention.semester_count
    eff_replications = req.replications if req.replications is not None else (intervention.replications if req.compare_baseline else 1)
    eff_replications = min(eff_replications, 100)

    students, courses = _resolve_university_cohort(service, req.placement_run_id, req.cohort_size, req.seed)
    ruleset = req.ruleset or UniversityRuleset()
    weights = req.weights or UtilityWeights()

    single_result = run_university_simulation(
        students=students,
        courses=courses,
        ruleset=ruleset,
        weights=weights,
        intervention=intervention,
        scenario_id=req.scenario_id,
        semester_count=eff_semesters,
        seed=req.seed,
        record_decisions=False,
    )

    comparison_dict: dict[str, Any] | None = None
    if req.compare_baseline:
        comp = run_replicated_university_experiment(
            students=students,
            courses=courses,
            policy_intervention=intervention,
            baseline_intervention=UniversityPolicyIntervention(semester_count=eff_semesters),
            ruleset=ruleset,
            weights=weights,
            semester_count=eff_semesters,
            replications=max(1, eff_replications),
            base_seed=req.seed,
            baseline_scenario_id=f"{req.scenario_id or 'university'}_baseline",
            policy_scenario_id=req.scenario_id or "policy",
        )
        comparison_dict = comp.model_dump(mode="json")
        summary = summarize_university_comparison(comp)
    else:
        summary = summarize_university_result(single_result)

    # Compact per-student tail inside result_json to keep SQLite rows fast and crisp for UI
    single_dump = single_result.model_dump(mode="json")
    single_dump["final_students"] = single_dump["final_students"][:150]

    req_payload = req.model_dump(mode="json")
    run_id = new_id("univ")
    created_at = utc_now()
    record = {
        "run_id": run_id,
        "scenario_id": req.scenario_id,
        "placement_run_id": req.placement_run_id,
        "request_hash": canonical_hash(req_payload),
        "result_sha256": single_result.manifest.result_sha256,
        "osym_verified": single_result.manifest.osym_verified,
        "coefficients_calibrated": single_result.manifest.coefficients_calibrated,
        "request": req_payload,
        "result": single_dump,
        "comparison": comparison_dict,
        "summary": summary,
        "created_at": created_at,
    }
    service.db.insert_university_run(record)
    return {
        "run_id": run_id,
        "scenario_id": req.scenario_id,
        "placement_run_id": req.placement_run_id,
        "osym_verified": single_result.manifest.osym_verified,
        "coefficients_calibrated": single_result.manifest.coefficients_calibrated,
        "disclaimer": single_result.manifest.disclaimer,
        "result_sha256": single_result.manifest.result_sha256,
        "created_at": created_at,
        "summary": summary,
        "result": single_dump,
        "comparison": comparison_dict,
    }


def list_university_runs_workbench(service: NationalService) -> dict[str, Any]:
    rows = service.db.university_runs()
    return {"items": rows, "total": len(rows)}


def get_university_run_workbench(service: NationalService, run_id: str) -> dict[str, Any]:
    row = service.db.university_run(run_id)
    if row is None:
        raise not_found("unknown_university_run", f"No university simulation run '{run_id}'.")
    return row


def run_university_sweep_workbench(service: NationalService, req: UniversitySweepRequest) -> dict[str, Any]:
    students, courses = _resolve_university_cohort(service, req.placement_run_id, req.cohort_size, req.seed)
    rows = run_tuition_sensitivity_sweep(
        students=students,
        courses=courses,
        tuition_pcts=tuple(req.tuition_pcts),
        aid_budget_pct=req.aid_budget_pct,
        semester_count=req.semester_count,
        replications=req.replications,
        base_seed=req.seed,
    )
    rules = UniversityRuleset()
    return {
        "placement_run_id": req.placement_run_id,
        "cohort_size": len(students),
        "semester_count": req.semester_count,
        "replications": req.replications,
        "osym_verified": rules.osym_verified,
        "coefficients_calibrated": rules.coefficients_calibrated,
        "disclaimer": rules.disclosure_banner(),
        "rows": rows,
    }
