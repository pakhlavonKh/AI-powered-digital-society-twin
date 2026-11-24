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
from scenarios.placement.models import PlacementResult, PlacementRuleset, ProgramOffering, catalog_fee_scale
from scenarios.placement.preference_model import compute_elasticity_sensitivity_range
from scenarios.schema import ScenarioConfig, UniversityPolicyIntervention
from scenarios.summary import (
    summarize_placement_comparison,
    summarize_placement_result,
    summarize_university_comparison,
    summarize_university_query,
    summarize_university_result,
)
from scenarios.university.cohort import (
    build_synthetic_university_cohort,
    build_target_university_m2_cohort,
    student_cohort_from_placement_handoff,
)
from scenarios.university.experiments import (
    run_replicated_university_experiment,
    run_tuition_sensitivity_sweep,
)
from scenarios.university.models import UniversityRuleset, UtilityWeights
from scenarios.university.semester_engine import run_university_simulation
from scenarios.university_analytics import compute_target_university_analytics
from scenarios.compiler import compile_university_query
from scenarios.university_query import (
    ElasticityPreset,
    PreferenceModelConfig,
    UniversityQuerySpec,
    preset_preference_config,
)
from societytwin.common import canonical_hash, new_id, utc_now
from societytwin.errors import conflict, invalid, not_found
from societytwin.national.rng import MAX_SEED
from societytwin.university.service import (
    list_snapshot_universities,
    load_programs_from_sqlite_snapshot,
)

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


class UniversityQueryPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=3, max_length=4000)
    context_university_id: str | None = Field(default=None, max_length=128)
    snapshot_id: str | None = Field(default=None, max_length=128)
    admission_year: int | None = Field(default=None, ge=1990, le=2100)
    population_id: str | None = Field(default=None, max_length=160)
    cohort_size: int = Field(default=200, ge=20, le=5000)
    seed: int = Field(default=42, ge=0, le=MAX_SEED)
    elasticity_preset: ElasticityPreset = "medium"
    model: str | None = Field(default=None, max_length=128)


class UniversityQueryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=3, max_length=4000)
    query_spec: UniversityQuerySpec | None = None
    context_university_id: str | None = Field(default=None, max_length=128)
    snapshot_id: str | None = Field(default=None, max_length=128)
    admission_year: int | None = Field(default=None, ge=1990, le=2100)
    population_id: str | None = Field(default=None, max_length=160)
    cohort_size: int = Field(default=200, ge=20, le=5000)
    seed: int = Field(default=42, ge=0, le=MAX_SEED)
    elasticity_preset: ElasticityPreset = "medium"
    preference_config: PreferenceModelConfig | None = None
    model: str | None = Field(default=None, max_length=128)


def resolve_university_catalog(
    service: NationalService,
    snapshot_id: str | None = None,
    admission_year: int | None = None,
) -> tuple[list[ProgramOffering], dict[str, Any]]:
    """Load ProgramOffering catalog from a SQLite snapshot if given, else the built-in demo catalog."""
    if snapshot_id:
        return load_programs_from_sqlite_snapshot(
            service.settings.university_db_path,
            snapshot_id,
            admission_year=admission_year,
        )
    programs = build_standalone_demo_programs()
    return programs, {
        "catalog_source": "standalone_demo_catalog",
        "snapshot_id": None,
        "admission_year": admission_year or 2025,
        "programs_loaded": len(programs),
    }


def plan_university_query_workbench(service: NationalService, req: UniversityQueryPlanRequest) -> dict[str, Any]:
    """Compile a natural-language university query and return a zero-cost reviewable plan."""
    programs, catalog_meta = resolve_university_catalog(
        service,
        snapshot_id=req.snapshot_id,
        admission_year=req.admission_year,
    )
    query_spec = compile_university_query(
        req.prompt,
        catalog=programs,
        context_university_id=req.context_university_id,
        snapshot_id=req.snapshot_id,
        admission_year=catalog_meta.get("admission_year"),
        cohort_size=req.cohort_size,
        seed=req.seed,
        model=req.model,
    )
    pref_cfg = preset_preference_config(req.elasticity_preset)
    ruleset = PlacementRuleset()

    targeted = [
        p
        for p in programs
        if (
            not query_spec.levers.target_university_ids
            and not query_spec.levers.target_program_ids
            and not query_spec.levers.target_department_names
        )
        or (
            (not query_spec.levers.target_university_ids or p.university_id in query_spec.levers.target_university_ids)
            and (not query_spec.levers.target_program_ids or p.program_id in query_spec.levers.target_program_ids)
            and (
                not query_spec.levers.target_department_names
                or any(d.lower() in p.department_name.lower() for d in query_spec.levers.target_department_names)
            )
        )
    ]

    blockers: list[dict[str, str]] = []
    warnings: list[str] = []
    if query_spec.unresolved_entities:
        for ue in query_spec.unresolved_entities:
            blockers.append({"code": f"unresolved_{ue.entity_type}", "message": ue.reason})
    if query_spec.out_of_scope_reasons:
        for reason in query_spec.out_of_scope_reasons:
            blockers.append({"code": "out_of_scope_query", "message": reason})
    if not targeted:
        blockers.append({"code": "no_matching_programs", "message": "No catalog programs match the target university/department filter."})
    if req.population_id:
        try:
            service._load(req.population_id)
        except Exception as exc:  # noqa: BLE001
            blockers.append({"code": "invalid_population", "message": str(exc)})
    if not pref_cfg.coefficients_calibrated:
        warnings.append(
            "Demand elasticities are uncalibrated synthetic assumptions (coefficients_calibrated=false); "
            "execution runs Low / Medium / High elasticity presets and reports a range."
        )
    if targeted and all(p.published_net_tuition_before_aid() <= 0.0 for p in targeted) and (
        query_spec.levers.tuition_change_pct or query_spec.levers.aid_budget_change_pct
    ):
        warnings.append(
            "All targeted programs currently have 0 TL annual tuition (state or 100% scholarship); "
            "percentage tuition scaling leaves net tuition at 0 TL."
        )
    if not ruleset.osym_verified:
        warnings.append(ruleset.disclosure_banner())

    universities = sorted(
        {
            (p.university_id, p.university_name, p.university_type)
            for p in programs
        }
    )
    plan_payload = {
        "query_spec": query_spec.model_dump(mode="json"),
        "preference_config": pref_cfg.model_dump(mode="json"),
        "population_id": req.population_id,
        "catalog_meta": catalog_meta,
    }
    return {
        "plan_hash": canonical_hash(plan_payload),
        "query_spec": query_spec.model_dump(mode="json"),
        "preference_config": pref_cfg.model_dump(mode="json"),
        "elasticity_presets": ["low", "medium", "high"],
        "catalog": {
            **catalog_meta,
            "total_programs": len(programs),
            "targeted_programs": len(targeted),
            "rivals_fixed": bool(
                query_spec.levers.target_university_ids
                or query_spec.levers.target_program_ids
                or query_spec.levers.target_department_names
            ),
            "universities": [
                {"university_id": uid, "university_name": uname, "university_type": utype}
                for uid, uname, utype in universities
            ],
        },
        "population_id": req.population_id,
        "osym_verified": ruleset.osym_verified,
        "coefficients_calibrated": pref_cfg.coefficients_calibrated,
        "blockers": blockers,
        "warnings": warnings,
        "executable": len(blockers) == 0,
        "disclaimers": query_spec.disclaimers,
    }


def _sync_edited_query_spec(
    spec: UniversityQuerySpec,
    programs: list[ProgramOffering],
    req: UniversityQueryRunRequest,
) -> UniversityQuerySpec:
    """Keep target university scoping and cohort parameters consistent if user edited the plan."""
    levers = spec.levers
    focus_uid = req.context_university_id or spec.focus_university_id
    focus_uname = spec.focus_university_name
    if focus_uid:
        uni_names = {p.university_id: p.university_name for p in programs}
        if focus_uid in uni_names:
            focus_uname = uni_names[focus_uid]
        if not levers.target_university_ids or (req.context_university_id and levers.target_university_ids != [focus_uid]):
            levers = levers.model_copy(update={"target_university_ids": [focus_uid]})

    synced_variants = []
    for v in spec.comparison_variants:
        v_int = v.intervention
        if focus_uid and v_int.target_university_ids != [focus_uid]:
            v_int = v_int.model_copy(update={"target_university_ids": [focus_uid]})
        if not v.is_baseline:
            if v.variant_id == "ranking_higher" and levers.ranking_change_pct is not None:
                mag = abs(float(levers.ranking_change_pct))
                v_int = v_int.model_copy(update={"ranking_change_pct": mag})
                v = v.model_copy(update={"label": f"Higher Ranking (+{mag:g}%)"})
            elif v.variant_id == "ranking_lower" and levers.ranking_change_pct is not None:
                mag = abs(float(levers.ranking_change_pct))
                v_int = v_int.model_copy(update={"ranking_change_pct": -mag})
                v = v.model_copy(update={"label": f"Lower Ranking (-{mag:g}%)"})
        synced_variants.append(v.model_copy(update={"intervention": v_int}))

    return spec.model_copy(
        update={
            "focus_university_id": focus_uid,
            "focus_university_name": focus_uname,
            "levers": levers,
            "comparison_variants": synced_variants,
            "cohort_size": req.cohort_size,
            "seed": req.seed,
            "snapshot_id": req.snapshot_id if req.snapshot_id is not None else spec.snapshot_id,
            "admission_year": req.admission_year if req.admission_year is not None else spec.admission_year,
        }
    )


def _scale_quotas_to_cohort(
    programs: list[ProgramOffering],
    cohort_size: int,
    overrides: dict[str, int] | None = None,
) -> tuple[list[ProgramOffering], float]:
    """Scale oversized real program seat totals proportionally to the sample cohort while keeping >=1 seat/open program."""
    open_progs = [p for p in programs if p.status == "open" and p.capacity > 0]
    total_open = sum(p.capacity for p in open_progs)
    if len(open_progs) < 20 or total_open <= max(int(round(cohort_size * 1.1)), len(open_progs)):
        return programs, 1.0

    target_total = max(len(open_progs), int(round(cohort_size * 0.86)))
    lo, hi = 0.0, float(target_total) / float(max(1, total_open))
    for _ in range(28):
        mid = 0.5 * (lo + hi)
        s = sum(max(1, int(round(p.capacity * mid))) for p in open_progs)
        if s > target_total:
            hi = mid
        else:
            lo = mid
    factor = 0.5 * (lo + hi)
    ov = overrides or {}
    scaled: list[ProgramOffering] = []
    new_total = 0
    for p in programs:
        if p.status == "open" and p.capacity > 0 and p.program_id not in ov:
            new_cap = max(1, int(round(p.capacity * factor)))
            new_total += new_cap
            scaled.append(p.model_copy(update={"capacity": new_cap}))
        else:
            if p.status == "open" and p.capacity > 0:
                new_total += p.capacity
            scaled.append(p)
    eff_factor = round(new_total / total_open, 4) if total_open > 0 else 1.0
    return scaled, eff_factor


def execute_university_query_workbench(service: NationalService, req: UniversityQueryRunRequest) -> dict[str, Any]:
    """Execute a compiled/edited university query plan, compute question-aware stats & summary, and persist."""
    eff_snapshot = req.snapshot_id or (req.query_spec.snapshot_id if req.query_spec else None)
    eff_year = req.admission_year or (req.query_spec.admission_year if req.query_spec else None)
    raw_programs, catalog_meta = resolve_university_catalog(
        service,
        snapshot_id=eff_snapshot,
        admission_year=eff_year,
    )

    if req.query_spec is not None:
        query_spec = _sync_edited_query_spec(req.query_spec, raw_programs, req)
    else:
        query_spec = compile_university_query(
            req.prompt,
            catalog=raw_programs,
            context_university_id=req.context_university_id,
            snapshot_id=eff_snapshot,
            admission_year=catalog_meta.get("admission_year"),
            cohort_size=req.cohort_size,
            seed=req.seed,
            model=req.model,
        )

    if query_spec.unresolved_entities:
        raise invalid(
            "unresolved_university_entity",
            query_spec.unresolved_entities[0].reason,
            {"unresolved_entities": [u.model_dump(mode="json") for u in query_spec.unresolved_entities]},
        )
    if query_spec.out_of_scope_reasons:
        raise invalid(
            "out_of_scope_university_query",
            query_spec.out_of_scope_reasons[0],
            {"out_of_scope_reasons": query_spec.out_of_scope_reasons},
        )

    programs, quota_scale_factor = _scale_quotas_to_cohort(
        raw_programs,
        query_spec.cohort_size,
        overrides=query_spec.levers.program_capacity_overrides,
    )
    if quota_scale_factor < 1.0 and query_spec.levers.base_aid_budget is not None:
        # Keep inferred baseline aid pools proportional when quotas are scaled to the sample cohort
        has_inferred_aid = any(a.key == "base_aid_budget" and a.source == "inferred" for a in query_spec.assumptions)
        if has_inferred_aid:
            scaled_aid = round(max(100_000.0, float(query_spec.levers.base_aid_budget) * quota_scale_factor), 2)
            query_spec = query_spec.model_copy(
                update={
                    "levers": query_spec.levers.model_copy(update={"base_aid_budget": scaled_aid}),
                    "comparison_variants": [
                        v.model_copy(
                            update={"intervention": v.intervention.model_copy(update={"base_aid_budget": scaled_aid})}
                        )
                        for v in query_spec.comparison_variants
                    ],
                }
            )

    use_empirical_priors = bool(eff_snapshot or len(programs) > 30)
    pref_cfg = req.preference_config or preset_preference_config(req.elasticity_preset)
    ruleset = PlacementRuleset()
    cohort = _resolve_candidate_cohort(
        service,
        req.population_id,
        programs,
        query_spec.cohort_size,
        query_spec.seed,
        empirical_priors=use_empirical_priors,
        populate_initial_preferences=False,
    )

    preference_cache: dict[str, Any] = {}
    base_scope_int = UniversityPolicyIntervention(
        target_university_ids=list(query_spec.levers.target_university_ids),
        target_program_ids=list(query_spec.levers.target_program_ids),
        target_department_names=list(query_spec.levers.target_department_names),
        base_aid_budget=query_spec.levers.base_aid_budget,
        max_grant_per_student=query_spec.levers.max_grant_per_student,
    )

    def _run_one(intervention: UniversityPolicyIntervention, cfg: PreferenceModelConfig = pref_cfg) -> PlacementResult:
        return run_placement(
            candidates=cohort.candidates,
            programs=programs,
            ruleset=ruleset,
            intervention=intervention,
            seed=query_spec.seed,
            preference_config=cfg,
            preference_cache=preference_cache,
        )

    variant_summaries: list[dict[str, Any]] | None = None
    sweep_rows: list[dict[str, Any]] | None = None
    baseline_result: PlacementResult | None = None
    policy_result: PlacementResult | None = None
    active_policy_int = query_spec.levers

    # 1. Multi-variant path (e.g. "ranking got higher or lower" or "compare +10/+20/+30%")
    if query_spec.comparison_variants:
        variant_runs: list[tuple[Any, PlacementResult]] = []
        for var in query_spec.comparison_variants:
            res = _run_one(var.intervention)
            variant_runs.append((var, res))
            if var.is_baseline:
                baseline_result = res

        if baseline_result is None:
            baseline_result = _run_one(base_scope_int)

        non_base = [(v, r) for v, r in variant_runs if not v.is_baseline]
        if non_base:
            # Prefer positive/higher variant as primary comparison pair for detailed breakdown
            chosen_var, policy_result = non_base[-1]
            active_policy_int = chosen_var.intervention
        else:
            policy_result = baseline_result

        variant_summaries = []
        for var, res in variant_runs:
            cmp_v = compare_placement_scenarios(baseline_result, res)
            an_v = compute_target_university_analytics(
                query_spec=query_spec,
                candidates=cohort.candidates,
                programs=programs,
                baseline_result=baseline_result,
                policy_result=res,
                comparison=cmp_v,
                cohort_source=cohort.demographic_source,
                seed=query_spec.seed,
                top_k=pref_cfg.top_k_definition,
            )
            defs_v = an_v["application_definitions"]
            cut_scores = [p["policy_cutoff_score"] for p in an_v["programs"] if p["policy_cutoff_score"] is not None]
            variant_summaries.append({
                "variant_id": var.variant_id,
                "label": var.label,
                "is_baseline": var.is_baseline,
                "listed_anywhere": defs_v["listed_anywhere"]["policy"],
                "listed_anywhere_delta": defs_v["listed_anywhere"]["delta"],
                "fee_paying_listed": defs_v["fee_paying_listed"]["policy"],
                "listed_top_k": defs_v["listed_top_k"]["policy"],
                "first_choice": defs_v["first_choice"]["policy"],
                "placed": defs_v["placed"]["policy"],
                "filled": an_v["target_capacity"]["policy_filled"],
                "capacity": an_v["target_capacity"]["policy"],
                "mean_cutoff_score": round(sum(cut_scores) / len(cut_scores), 2) if cut_scores else None,
                "target_net_revenue": an_v["target_revenue"]["policy"],
            })

    # 2. Revenue / Tuition sweep path
    elif query_spec.sweep_tuition_pcts or query_spec.intent == "revenue_tradeoff":
        grid = query_spec.sweep_tuition_pcts or [-20.0, 0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 75.0, 100.0]
        if 0.0 not in grid:
            grid = sorted(set([0.0, *grid]))
        baseline_result = _run_one(base_scope_int)
        sweep_rows = []
        best_res: PlacementResult | None = None
        best_rev = -1.0
        best_int = active_policy_int
        for pct in grid:
            step_int = query_spec.levers.model_copy(
                update={
                    "tuition_change_pct": float(pct),
                }
            )
            res = baseline_result if pct == 0.0 else _run_one(step_int)
            cmp_s = compare_placement_scenarios(baseline_result, res)
            an_s = compute_target_university_analytics(
                query_spec=query_spec,
                candidates=cohort.candidates,
                programs=programs,
                baseline_result=baseline_result,
                policy_result=res,
                comparison=cmp_s,
                cohort_source=cohort.demographic_source,
                seed=query_spec.seed,
                top_k=pref_cfg.top_k_definition,
            )
            defs_s = an_s["application_definitions"]
            rev_s = an_s["target_revenue"]["policy"]
            sweep_rows.append({
                "tuition_change_pct": float(pct),
                "listed_anywhere": defs_s["listed_anywhere"]["policy"],
                "listed_top_k": defs_s["listed_top_k"]["policy"],
                "first_choice": defs_s["first_choice"]["policy"],
                "placed": defs_s["placed"]["policy"],
                "target_net_revenue": rev_s,
            })
            if rev_s > best_rev:
                best_rev = rev_s
                best_res = res
                best_int = step_int
        if query_spec.levers.tuition_change_pct is not None:
            policy_result = _run_one(query_spec.levers)
        else:
            policy_result = best_res or baseline_result
            active_policy_int = best_int

    # 3. Single baseline vs policy path
    else:
        baseline_result = _run_one(base_scope_int)
        policy_result = _run_one(query_spec.levers)

    assert baseline_result is not None and policy_result is not None
    comparison = compare_placement_scenarios(baseline_result, policy_result)
    analytics = compute_target_university_analytics(
        query_spec=query_spec,
        candidates=cohort.candidates,
        programs=programs,
        baseline_result=baseline_result,
        policy_result=policy_result,
        comparison=comparison,
        cohort_source=cohort.demographic_source,
        seed=query_spec.seed,
        top_k=pref_cfg.top_k_definition,
    )

    analytics["cohort_metadata"]["quota_scale_factor"] = quota_scale_factor
    analytics["cohort_metadata"]["empirical_priors_active"] = bool(
        use_empirical_priors and (cohort.field_provenance.get("scores", {}) or cohort.field_provenance.get("all_attributes", {})).get("source", "").startswith("osym")
    )

    elasticity_range = None
    if not pref_cfg.coefficients_calibrated:
        preset_cache_map: dict[ElasticityPreset, tuple[PlacementResult, PlacementResult]] | None = None
        if not query_spec.comparison_variants and not (query_spec.sweep_tuition_pcts or query_spec.intent == "revenue_tradeoff"):
            preset_cache_map = {pref_cfg.elasticity_preset: (baseline_result, policy_result)}
        elasticity_range = compute_elasticity_sensitivity_range(
            candidates=cohort.candidates,
            programs=programs,
            target_program_ids=set(analytics["target_program_ids"]),
            fee_target_program_ids=set(analytics.get("fee_target_program_ids", [])),
            ruleset=ruleset,
            intervention=active_policy_int,
            seed=query_spec.seed,
            top_k=pref_cfg.top_k_definition,
            preference_cache=preference_cache,
            preset_results=preset_cache_map,
        )

    # 4. Optional Milestone 2 retention simulation (anchored on pre-policy baseline enrollees!)
    university_comparison = None
    if query_spec.simulation_mode in ("retention", "both") or query_spec.intent == "retention_impact":
        target_set = set(analytics["target_program_ids"])
        target_progs = [p for p in programs if p.program_id in target_set]
        fee_scale = catalog_fee_scale(programs)
        base_handoff = placement_result_to_student_cohort(baseline_result, cohort, programs)
        scoped_students = [s for s in base_handoff.get("students", []) if s.get("program_id") in target_set]
        has_paid_enrollees = any(
            float((s.get("financials") or {}).get("published_tuition") or 0.0) > 0.0
            for s in scoped_students
        )
        all_free_target = bool(analytics.get("all_target_programs_free", False))
        if len(scoped_students) >= 5 and (all_free_target or has_paid_enrollees):
            base_handoff["students"] = scoped_students
            base_handoff["student_count"] = len(scoped_students)
            students, courses = student_cohort_from_placement_handoff(base_handoff, seed=query_spec.seed, fee_scale=fee_scale)
        elif target_progs:
            students, courses = build_target_university_m2_cohort(
                target_progs,
                size=min(max(60, len(scoped_students) or 120), 200),
                seed=query_spec.seed,
                fee_scale=fee_scale,
            )
        else:
            students, courses = build_synthetic_university_cohort(size=min(query_spec.cohort_size, 200), seed=query_spec.seed)
        prog_uni_map = {p.program_id: p.university_id for p in programs}
        eff_terms = max(2, active_policy_int.semester_count)
        m2_ruleset = UniversityRuleset(default_hold_threshold=round(5_000.0 * fee_scale, 2))
        m2_weights = UtilityWeights(beta_net_cost=round(-0.32 / max(1.0, fee_scale), 4))
        university_comparison = run_replicated_university_experiment(
            students=students,
            courses=courses,
            policy_intervention=active_policy_int,
            baseline_intervention=base_scope_int.model_copy(update={"semester_count": eff_terms}),
            ruleset=m2_ruleset,
            weights=m2_weights,
            semester_count=eff_terms,
            replications=min(8, max(2, active_policy_int.replications)),
            base_seed=query_spec.seed,
            baseline_scenario_id="query_retention_baseline",
            policy_scenario_id="query_retention_policy",
            program_university_map=prog_uni_map,
        )

    summary = summarize_university_query(
        query_spec,
        analytics,
        elasticity_range=elasticity_range,
        variant_summaries=variant_summaries,
        sweep_rows=sweep_rows,
        university_comparison=university_comparison,
        allow_llm=bool(service.settings.live_execution_enabled),
    )

    req_payload = req.model_dump(mode="json")
    result_payload = {
        "analytics": analytics,
        "elasticity_range": elasticity_range,
        "variants": variant_summaries,
        "sweep_rows": sweep_rows,
        "comparison": comparison.model_dump(mode="json"),
        "university_comparison": university_comparison.model_dump(mode="json") if university_comparison is not None else None,
        "catalog_meta": catalog_meta,
    }
    result_sha256 = canonical_hash({
        "query_spec": query_spec.model_dump(mode="json"),
        "policy_result_sha256": policy_result.manifest.result_sha256,
        "baseline_result_sha256": baseline_result.manifest.result_sha256,
        "analytics": analytics,
    })
    manifest = {
        "engine_version": policy_result.manifest.engine_version,
        "catalog_source": catalog_meta["catalog_source"],
        "snapshot_id": catalog_meta.get("snapshot_id"),
        "admission_year": catalog_meta.get("admission_year"),
        "cohort_source": cohort.demographic_source,
        "cohort_size": len(cohort.candidates),
        "seed": query_spec.seed,
        "elasticity_preset": pref_cfg.elasticity_preset,
        "preference_model": pref_cfg.model_dump(mode="json"),
        "rivals_fixed": True,
        "osym_verified": ruleset.osym_verified,
        "coefficients_calibrated": pref_cfg.coefficients_calibrated,
        "disclaimer": ruleset.disclosure_banner(),
        "result_sha256": result_sha256,
    }

    run_id = new_id("uquery")
    created_at = utc_now()
    record = {
        "run_id": run_id,
        "prompt": query_spec.original_prompt,
        "intent": query_spec.intent,
        "snapshot_id": eff_snapshot,
        "focus_university_id": query_spec.focus_university_id,
        "request_hash": canonical_hash(req_payload),
        "result_sha256": result_sha256,
        "osym_verified": ruleset.osym_verified,
        "coefficients_calibrated": pref_cfg.coefficients_calibrated,
        "query_spec": query_spec.model_dump(mode="json"),
        "request": req_payload,
        "result": result_payload,
        "summary": summary,
        "detailed_statistics": summary["detailed_statistics"],
        "manifest": manifest,
        "created_at": created_at,
    }
    service.db.insert_university_query_run(record)
    return {
        "run_id": run_id,
        "prompt": query_spec.original_prompt,
        "intent": query_spec.intent,
        "snapshot_id": eff_snapshot,
        "focus_university_id": query_spec.focus_university_id,
        "focus_university_name": query_spec.focus_university_name,
        "osym_verified": ruleset.osym_verified,
        "coefficients_calibrated": pref_cfg.coefficients_calibrated,
        "result_sha256": result_sha256,
        "created_at": created_at,
        "query_spec": record["query_spec"],
        "summary": summary,
        "detailed_statistics": record["detailed_statistics"],
        "result": result_payload,
        "manifest": manifest,
    }


def list_university_query_runs_workbench(service: NationalService) -> dict[str, Any]:
    rows = service.db.university_query_runs()
    return {"items": rows, "total": len(rows)}


def get_university_query_run_workbench(service: NationalService, run_id: str) -> dict[str, Any]:
    row = service.db.university_query_run(run_id)
    if row is None:
        raise not_found("unknown_university_query_run", f"No university query run '{run_id}'.")
    return row


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
    *,
    empirical_priors: bool = False,
    populate_initial_preferences: bool = True,
):
    if population_id:
        loaded = service._load(population_id)
        try:
            return build_tuik_anchored_candidates(
                loaded,
                programs,
                sample_size=cohort_size,
                seed=seed,
                empirical_priors=empirical_priors,
                populate_initial_preferences=populate_initial_preferences,
            )
        except ValueError as exc:
            raise invalid("insufficient_cohort", str(exc)) from exc
    return build_standalone_test_cohort(
        programs,
        size=cohort_size,
        seed=seed,
        empirical_priors=empirical_priors,
        populate_initial_preferences=populate_initial_preferences,
    )


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
    summary_disc = (row.get("summary") or {}).get("disclaimer")
    row.setdefault("disclaimer", summary_disc or PlacementRuleset().disclosure_banner())
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
    comp_disc = (row.get("comparison") or {}).get("disclaimer")
    summary_disc = (row.get("summary") or {}).get("disclaimer")
    row.setdefault("disclaimer", comp_disc or summary_disc or UniversityRuleset().disclosure_banner())
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
