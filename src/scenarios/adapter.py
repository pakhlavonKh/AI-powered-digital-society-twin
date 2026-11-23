"""Adapter converting ScenarioConfig models into SocietyTwin national ExperimentDefinition schemas.

Provides catalog discovery and transformation from multi-question YAML scenarios
into experiment designs ready for API v2 and the experiment runner.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

try:
    from .loader import load_scenario
    from .schema import (
        PlacementScenarioConfig,
        ScenarioConfig,
        UniversityPolicyIntervention,
        UnknownQuestionError,
    )
except ImportError:
    from scenarios.loader import load_scenario
    from scenarios.schema import (
        PlacementScenarioConfig,
        ScenarioConfig,
        UniversityPolicyIntervention,
        UnknownQuestionError,
    )

logger = logging.getLogger(__name__)

_BUILTIN_SCENARIOS_DIR = Path(__file__).resolve().parent / "builtin_scenarios"
_DEFAULT_REL_DIRS = (
    Path("experiments/policy_scenarios/scenarios"),
    Path("scenarios"),
)
DEFAULT_SCENARIOS_DIRS = list(_DEFAULT_REL_DIRS)


def scenario_dirs_for_state(state_dir: Path | None = None) -> tuple[list[Path] | None, Path | None]:
    """Return ``(search_dirs, save_dir)`` scoped to ``state_dir`` unless DEFAULT_SCENARIOS_DIRS was overridden."""
    if tuple(DEFAULT_SCENARIOS_DIRS) != _DEFAULT_REL_DIRS or state_dir is None:
        return None, None
    state_scenarios = state_dir / "scenarios"
    return [state_scenarios, *DEFAULT_SCENARIOS_DIRS, _BUILTIN_SCENARIOS_DIR], state_scenarios

# Question types the national experiment runtime (TaskSpec) can execute.
EXECUTABLE_QUESTION_TYPES = frozenset({"single_choice", "free_text"})
# PopulationFilterConfig fields enforced by the runtime through ExperimentDefinition.scenario_ref.
_ENFORCED_FILTERS = {"minimum_age", "maximum_age", "province_codes", "adult_only", "required_attributes"}


class UnsupportedQuestionTypeError(ValueError):
    """Raised when a question type cannot be executed by the experiment runtime."""


class ScenarioConflictError(ValueError):
    """Raised when saving would overwrite a different scenario with the same scenario_id."""


def find_scenario_paths(custom_dirs: list[Path] | None = None) -> dict[str, Path]:
    """Find all unique YAML scenario files by scenario_id.

    Invalid files and duplicate IDs are skipped with a logged warning (never silently).
    """
    paths: dict[str, Path] = {}
    if custom_dirs is not None:
        search_dirs = list(custom_dirs)
    elif tuple(DEFAULT_SCENARIOS_DIRS) == _DEFAULT_REL_DIRS:
        search_dirs = [*DEFAULT_SCENARIOS_DIRS, _BUILTIN_SCENARIOS_DIR]
    else:
        search_dirs = list(DEFAULT_SCENARIOS_DIRS)

    for s_dir in search_dirs:
        is_builtin_fallback = s_dir == _BUILTIN_SCENARIOS_DIR
        resolved = s_dir if s_dir.is_absolute() else Path.cwd() / s_dir
        if not resolved.is_dir():
            continue
        for ext in ("*.yaml", "*.yml"):
            for file_path in sorted(resolved.glob(ext)):
                try:
                    loaded = load_scenario(file_path)
                except Exception as exc:  # noqa: BLE001 - one bad file must not hide the catalog
                    logger.warning("Skipping invalid scenario file %s: %s", file_path, exc)
                    continue
                if loaded.scenario_id in paths:
                    if not is_builtin_fallback:
                        logger.warning("Duplicate scenario_id '%s' in %s ignored; using %s",
                                       loaded.scenario_id, file_path, paths[loaded.scenario_id])
                    continue
                paths[loaded.scenario_id] = file_path

    return paths


def _matches_province_filter(scenario: ScenarioConfig, province: str) -> bool:
    want = province.strip()
    if not want:
        return True
    want_code: str | None = None
    if want.isdigit() and 1 <= int(want) <= 81:
        want_code = f"{int(want):02d}"
    else:
        try:
            from societytwin.national.geography import _BY_NAME, name_key, normalize_code

            try:
                want_code = normalize_code(want)
            except Exception:  # noqa: BLE001
                prov_obj = _BY_NAME.get(name_key(want))
                if prov_obj is not None:
                    want_code = prov_obj.code
        except ImportError:
            pass
    if want_code is not None:
        if scenario.location.province_code == want_code:
            return True
        if scenario.target_population.province_codes and want_code in scenario.target_population.province_codes:
            return True
        return False
    return (
        scenario.location.province_code.lower() == want.lower()
        or scenario.location.province_name.lower() == want.lower()
    )


def list_available_scenarios(
    custom_dirs: list[Path] | None = None,
    category: str | None = None,
    province: str | None = None,
) -> list[dict[str, Any]]:
    """List summary metadata for all discovered policy scenarios, optionally filtered by category and province."""
    catalog = find_scenario_paths(custom_dirs)
    items: list[dict[str, Any]] = []
    want_category = category.strip().lower() if category and category.strip() else None

    for scenario_id, path in sorted(catalog.items()):
        scenario = load_scenario(path)
        if want_category and scenario.policy.category.lower() != want_category:
            continue
        if province and province.strip() and not _matches_province_filter(scenario, province):
            continue
        shown = scenario.rendered()
        items.append({
            "scenario_id": scenario.scenario_id,
            "version": scenario.version,
            "name": scenario.name,
            "description": shown.description,
            "category": scenario.policy.category,
            "type": scenario.policy.type,
            "location": {
                "province_code": scenario.location.province_code,
                "province_name": scenario.location.province_name,
            },
            "questions_count": len(scenario.questions),
            "questions": [{"id": q.id, "text": q.text, "type": q.type} for q in shown.questions],
        })

    return items


def get_scenario(scenario_id: str, custom_dirs: list[Path] | None = None) -> ScenarioConfig:
    """Load a specific scenario by its unique scenario_id."""
    catalog = find_scenario_paths(custom_dirs)
    if scenario_id not in catalog:
        raise KeyError(f"Scenario with ID '{scenario_id}' not found in registered scenario directories.")
    return load_scenario(catalog[scenario_id])


def scenario_to_experiment_definition(
    scenario: ScenarioConfig,
    cohort_id: str | None = None,
    question_id: str | None = None,
    seed: int = 7,
) -> dict[str, Any]:
    """Transform a ScenarioConfig into an ExperimentDefinition dictionary.

    Args:
        scenario: Validated ScenarioConfig.
        cohort_id: Target cohort identifier (optional when drafting).
        question_id: Specific question to ask; if None, the first question. An unknown ID raises
            UnknownQuestionError (no fallback).
        seed: Random seed for cohort sampling.

    Returns:
        Dictionary conforming to societytwin.national.experiments.ExperimentDefinition. Its
        ``scenario_ref`` block carries scenario ID, version, question ID and targeting so the
        runtime can enforce scope and results stay traceable to the scenario.

    Raises:
        UnknownQuestionError: ``question_id`` is not defined in the scenario.
        UnsupportedQuestionTypeError: the selected question cannot be executed (e.g. multiple_choice).
    """
    source_q = scenario.get_question(question_id) if question_id is not None else scenario.questions[0]
    if source_q.type not in EXECUTABLE_QUESTION_TYPES:
        raise UnsupportedQuestionTypeError(
            f"Question '{source_q.id}' of scenario '{scenario.scenario_id}' is '{source_q.type}', but the experiment "
            f"runtime only executes {sorted(EXECUTABLE_QUESTION_TYPES)}. It is not converted to single choice."
        )
    shown = scenario.rendered()
    target_q = next(q for q in shown.questions if q.id == source_q.id)

    # Build parameters (missing fare value derived from the other two; never invented)
    params: list[dict[str, Any]] = []
    p = scenario.policy.parameters
    fares = p.resolved_fares()

    if fares["baseline_fare"] is not None:
        params.append({
            "name": "baseline_tariff",
            "label": "Baseline Tariff",
            "value": fares["baseline_fare"],
            "unit": p.currency,
        })
    if fares["new_fare"] is not None:
        params.append({
            "name": "new_tariff",
            "label": "Proposed Tariff",
            "value": fares["new_fare"],
            "unit": p.currency,
        })
    if fares["increase_percentage"] is not None:
        params.append({
            "name": "tariff_change_percent",
            "label": "Tariff Adjustment",
            "value": fares["increase_percentage"],
            "unit": "%",
        })
    if p.fare_category:
        params.append({"name": "fare_category", "label": "Fare category the change applies to", "value": p.fare_category})
    if p.effective_date:
        params.append({"name": "baseline_effective_date", "label": "Baseline tariff effective date", "value": p.effective_date})
    if p.subsidized_exemptions_note:
        params.append({"name": "concessions", "label": "Concessions and exemptions", "value": p.subsidized_exemptions_note})

    # Build task options constrained to ExperimentDefinition TaskSpec limits
    options: list[dict[str, str]] = []
    seen_opt_ids: set[str] = set()
    max_base_opts = 11 if (target_q.type == "single_choice" and target_q.allow_other) else 12
    for idx, opt in enumerate(target_q.options[:max_base_opts], start=1):
        norm_id = re.sub(r"[^a-z0-9_]", "_", opt.id.lower()).strip("_")
        if not norm_id or not norm_id[0].isalpha():
            norm_id = f"opt_{norm_id}" if norm_id else f"opt_{idx}"
        norm_id = norm_id[:49]
        if norm_id in seen_opt_ids:
            suffix = f"_{idx}"
            norm_id = f"{norm_id[: 49 - len(suffix)]}{suffix}"
        seen_opt_ids.add(norm_id)
        options.append({"id": norm_id, "label": opt.label[:300]})
    allow_other_text = False
    if target_q.type == "single_choice" and target_q.allow_other:
        if "other" not in seen_opt_ids:
            options.append({"id": "other", "label": "Other"})
        allow_other_text = True

    tp = scenario.target_population
    unenforced = sorted(
        name for name, value in tp.model_dump().items()
        if name not in _ENFORCED_FILTERS and value not in (None, [], ())
    )

    title_suffix = " (Hypothetical)" if scenario.metadata.hypothetical else ""
    exp_title = f"{scenario.name[: 160 - len(title_suffix)]}{title_suffix}"

    # Return structure matching societytwin.national.experiments.ExperimentDefinition
    return {
        "title": exp_title,
        "scenario": {
            "title": scenario.name[:160],
            "description": shown.description[:4000],
            "parameters": params,
            "hypothetical": scenario.metadata.hypothetical,
            "source_note": scenario.metadata.source_note,
            "version": scenario.version,
        },
        "task": {
            "instruction": target_q.text,
            "response_type": target_q.type,
            "options": options,
            "allow_other_text": allow_other_text,
            "ask_rationale": target_q.ask_rationale,
            "adult_only": tp.adult_only,
        },
        "environment": {
            "province_code": scenario.location.province_code,
            "context_indicators": ["total_population", "population_density"],
        },
        "cohort": {
            "cohort_id": cohort_id or "",
            "sample_size": 20,
            "sampling_method": "weighted",
            "seed": seed,
        },
        "model": {
            "backend": "stub",
            "transport": "fake",
            "temperature": 0.0,
        },
        "execution": {
            "repetitions": 1,
            "max_attempts": 1,
            "max_calls": 20,
        },
        "scenario_ref": {
            "scenario_id": scenario.scenario_id,
            "scenario_version": scenario.version,
            "question_id": source_q.id,
            "question_type": source_q.type,
            "province_codes": list(tp.province_codes) if tp.province_codes else [scenario.location.province_code],
            "minimum_age": tp.minimum_age,
            "maximum_age": tp.maximum_age,
            "required_attributes": list(tp.required_attributes),
            "unenforced_filters": unenforced,
        },
    }


def save_custom_scenario(
    data: dict[str, Any] | ScenarioConfig,
    target_dir: Path | None = None,
    overwrite: bool = False,
    search_dirs: list[Path] | None = None,
) -> ScenarioConfig:
    """Validate and persist a custom policy scenario as a YAML file in the scenarios catalog.

    Args:
        data: ScenarioConfig instance or raw dict conforming to ScenarioConfig.
        target_dir: Optional custom storage directory. Defaults to experiments/policy_scenarios/scenarios.
        overwrite: Replace an existing, different scenario with the same scenario_id. Saving an
            identical scenario again is always a no-op.

    Returns:
        The validated and persisted ScenarioConfig.

    Raises:
        ScenarioConflictError: a different scenario with this scenario_id already exists and
            ``overwrite`` is False.
    """
    import yaml

    if hasattr(data, "model_dump"):
        dump_dict = data.model_dump(mode="json", exclude_none=True)
        config = ScenarioConfig.model_validate(dump_dict)
    elif isinstance(data, dict):
        config = ScenarioConfig.model_validate(data)
    else:
        raise ValueError(f"Expected dict or ScenarioConfig, got {type(data)}")

    save_dir = target_dir or DEFAULT_SCENARIOS_DIRS[0]
    resolved_dir = save_dir if save_dir.is_absolute() else Path.cwd() / save_dir
    resolved_dir.mkdir(parents=True, exist_ok=True)

    target_file = resolved_dir / f"{config.scenario_id}.yaml"
    conflict_dirs = search_dirs if search_dirs is not None else ([target_dir] if target_dir else None)
    existing_path = target_file if target_file.exists() else find_scenario_paths(conflict_dirs).get(config.scenario_id)
    if existing_path is not None and not overwrite:
        try:
            existing = load_scenario(existing_path)
        except Exception:  # noqa: BLE001 - an unreadable file is still a file we must not clobber
            existing = None
        if existing is not None and existing.model_dump(mode="json") == config.model_dump(mode="json"):
            return existing
        raise ScenarioConflictError(
            f"A different scenario with ID '{config.scenario_id}' already exists at {existing_path}. "
            f"Use a new scenario_id (or bump the version under a new ID) instead of overwriting it."
        )

    dump_dict = config.model_dump(mode="json", exclude_none=True)

    with open(target_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(dump_dict, f, sort_keys=False, allow_unicode=True)

    return config


def scenario_to_placement_spec(
    scenario: ScenarioConfig | PlacementScenarioConfig,
    candidates: Any = None,
    programs: list[Any] | None = None,
    ruleset: Any = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Transform a university ScenarioConfig or PlacementScenarioConfig into an offline placement input bundle."""
    try:
        from .placement.cohort_synth import build_standalone_demo_programs, build_standalone_test_cohort
        from .placement.models import CandidateCohort, PlacementRuleset
    except ImportError:
        from scenarios.placement.cohort_synth import (  # type: ignore
            build_standalone_demo_programs,
            build_standalone_test_cohort,
        )
        from scenarios.placement.models import CandidateCohort, PlacementRuleset  # type: ignore

    if isinstance(scenario, PlacementScenarioConfig):
        sim_mode = scenario.simulation_mode
        intervention = scenario.university_intervention
    else:
        sim_mode = scenario.effective_simulation_mode
        intervention = scenario.university_intervention

    if sim_mode not in ("university_placement", "university_decision_hybrid") and intervention is None:
        raise ValueError(
            f"Scenario '{scenario.scenario_id}' has simulation_mode='{sim_mode}' and no university_intervention; "
            "cannot convert to a placement specification."
        )

    resolved_programs = list(programs) if programs is not None else build_standalone_demo_programs()
    if candidates is None:
        cohort = build_standalone_test_cohort(resolved_programs, seed=seed)
        resolved_candidates = cohort.candidates
    elif isinstance(candidates, CandidateCohort):
        resolved_candidates = candidates.candidates
    else:
        resolved_candidates = list(candidates)

    resolved_ruleset = ruleset if ruleset is not None else PlacementRuleset()
    if intervention is not None and intervention.ruleset_id:
        resolved_ruleset = resolved_ruleset.model_copy(update={"ruleset_id": intervention.ruleset_id})

    return {
        "scenario": scenario,
        "simulation_mode": sim_mode,
        "candidates": resolved_candidates,
        "programs": resolved_programs,
        "ruleset": resolved_ruleset,
        "intervention": intervention,
        "seed": seed,
        "osym_verified": resolved_ruleset.osym_verified,
        "rule_fidelity": resolved_ruleset.rule_fidelity,
        "disclaimer": resolved_ruleset.disclosure_banner(),
    }


def execute_placement_scenario(
    scenario: ScenarioConfig | PlacementScenarioConfig,
    candidates: Any = None,
    programs: list[Any] | None = None,
    ruleset: Any = None,
    seed: int = 42,
    min_group: int = 1,
) -> Any:
    """Resolve scenario parameters and execute the offline deterministic placement engine."""
    try:
        from .placement.engine import run_placement
    except ImportError:
        from scenarios.placement.engine import run_placement  # type: ignore

    spec = scenario_to_placement_spec(
        scenario=scenario,
        candidates=candidates,
        programs=programs,
        ruleset=ruleset,
        seed=seed,
    )
    return run_placement(
        candidates=spec["candidates"],
        programs=spec["programs"],
        ruleset=spec["ruleset"],
        intervention=spec["intervention"],
        scenario=scenario,
        seed=seed,
        min_group=min_group,
    )


def placement_result_to_student_cohort(
    result: Any,
    candidates: Any,
    programs: list[Any],
) -> dict[str, Any]:
    """Handoff contract converting placed candidates into post-admission student cohort records (Milestone 2)."""
    try:
        from .placement.models import CandidateCohort
    except ImportError:
        from scenarios.placement.models import CandidateCohort  # type: ignore

    cand_list = candidates.candidates if isinstance(candidates, CandidateCohort) else list(candidates)
    cand_map = {c.candidate_id: c for c in cand_list}
    prog_map = {p.program_id: p for p in programs}

    admitted_students: list[dict[str, Any]] = []
    for outcome in result.candidate_outcomes:
        if outcome.placement_status != "placed" or outcome.assigned_program_id is None:
            continue
        cand = cand_map.get(outcome.candidate_id)
        prog = prog_map.get(outcome.assigned_program_id)
        admitted_students.append({
            "student_id": outcome.candidate_id,
            "source_synthetic_id": outcome.source_synthetic_id,
            "province_code": cand.province_code if cand else (prog.province_code if prog else None),
            "age": cand.age if cand else None,
            "sex": cand.sex if cand else None,
            "income_band": cand.income_band if cand else None,
            "liquid_budget": cand.liquid_budget if cand else None,
            "program_id": outcome.assigned_program_id,
            "university_name": prog.university_name if prog else None,
            "department_name": prog.department_name if prog else None,
            "score_type_used": outcome.score_type_used,
            "admission_score": outcome.effective_score,
            "financials": outcome.financials.model_dump(mode="json") if outcome.financials else None,
            "semester_state": "admitted_term_1",
        })

    return {
        "handoff_version": "placement-to-university-1.0",
        "source_result_sha256": result.manifest.result_sha256,
        "scenario_id": result.manifest.scenario_id,
        "osym_verified": result.manifest.osym_verified,
        "rule_fidelity": result.manifest.rule_fidelity,
        "disclaimer": result.manifest.disclaimer,
        "student_count": len(admitted_students),
        "students": admitted_students,
    }


def _extract_university_mode_and_intervention(
    scenario: ScenarioConfig | PlacementScenarioConfig,
) -> tuple[str, Any]:
    if isinstance(scenario, PlacementScenarioConfig):
        return scenario.simulation_mode, scenario.university_intervention
    return scenario.effective_simulation_mode, scenario.university_intervention


def scenario_to_university_spec(
    scenario: ScenarioConfig | PlacementScenarioConfig,
    *,
    students: list[Any] | None = None,
    courses: list[Any] | None = None,
    ruleset: Any = None,
    weights: Any = None,
    semester_count: int | None = None,
    replications: int | None = None,
    seed: int = 42,
    cohort_size: int = 200,
) -> dict[str, Any]:
    """Transform a university ScenarioConfig into an offline Milestone 2 simulation specification."""
    try:
        from .university.cohort import (
            build_synthetic_university_cohort,
            student_cohort_from_placement_handoff,
        )
        from .university.models import UniversityRuleset, UtilityWeights
    except ImportError:
        from scenarios.university.cohort import (  # type: ignore
            build_synthetic_university_cohort,
            student_cohort_from_placement_handoff,
        )
        from scenarios.university.models import UniversityRuleset, UtilityWeights  # type: ignore

    sim_mode, intervention = _extract_university_mode_and_intervention(scenario)
    if sim_mode not in ("university_decision", "university_decision_hybrid") and intervention is None:
        raise ValueError(
            f"Scenario '{scenario.scenario_id}' has simulation_mode='{sim_mode}' and no university_intervention; "
            "cannot convert to a university multi-semester specification."
        )

    eff_intervention = intervention or UniversityPolicyIntervention()
    eff_semesters = semester_count if semester_count is not None else eff_intervention.semester_count
    eff_replications = replications if replications is not None else eff_intervention.replications

    if students is not None and courses is not None:
        resolved_students, resolved_courses = list(students), list(courses)
    elif sim_mode == "university_decision_hybrid" and students is None:
        placement_spec = scenario_to_placement_spec(scenario=scenario, seed=seed)
        placement_result = execute_placement_scenario(
            scenario=scenario,
            candidates=placement_spec["candidates"],
            programs=placement_spec["programs"],
            ruleset=placement_spec["ruleset"],
            seed=seed,
        )
        handoff = placement_result_to_student_cohort(
            placement_result,
            placement_spec["candidates"],
            placement_spec["programs"],
        )
        resolved_students, resolved_courses = student_cohort_from_placement_handoff(handoff, seed=seed)
        if courses is not None:
            resolved_courses = list(courses)
    else:
        syn_students, syn_courses = build_synthetic_university_cohort(size=cohort_size, seed=seed)
        resolved_students = list(students) if students is not None else syn_students
        resolved_courses = list(courses) if courses is not None else syn_courses

    resolved_ruleset = ruleset if ruleset is not None else UniversityRuleset()
    resolved_weights = weights if weights is not None else UtilityWeights()

    return {
        "scenario": scenario,
        "simulation_mode": sim_mode,
        "students": resolved_students,
        "courses": resolved_courses,
        "ruleset": resolved_ruleset,
        "weights": resolved_weights,
        "intervention": eff_intervention,
        "semester_count": eff_semesters,
        "replications": eff_replications,
        "seed": seed,
        "osym_verified": resolved_ruleset.osym_verified,
        "coefficients_calibrated": resolved_weights.coefficients_calibrated,
        "disclaimer": resolved_ruleset.disclosure_banner(),
    }


def execute_university_scenario(
    scenario: ScenarioConfig | PlacementScenarioConfig,
    *,
    students: list[Any] | None = None,
    courses: list[Any] | None = None,
    ruleset: Any = None,
    weights: Any = None,
    semester_count: int | None = None,
    replications: int | None = None,
    seed: int = 42,
    cohort_size: int = 200,
    run_comparison: bool | None = None,
) -> dict[str, Any]:
    """Resolve and execute a Milestone 2 university scenario (single run or paired CRN comparison)."""
    try:
        from .summary import summarize_university_comparison, summarize_university_result
        from .university.experiments import run_replicated_university_experiment
        from .university.semester_engine import run_university_simulation
    except ImportError:
        from scenarios.summary import (  # type: ignore
            summarize_university_comparison,
            summarize_university_result,
        )
        from scenarios.university.experiments import run_replicated_university_experiment  # type: ignore
        from scenarios.university.semester_engine import run_university_simulation  # type: ignore

    spec = scenario_to_university_spec(
        scenario=scenario,
        students=students,
        courses=courses,
        ruleset=ruleset,
        weights=weights,
        semester_count=semester_count,
        replications=replications,
        seed=seed,
        cohort_size=cohort_size,
    )

    eff_reps = int(spec["replications"])
    do_compare = run_comparison if run_comparison is not None else (eff_reps > 1)

    single_result = run_university_simulation(
        students=spec["students"],
        courses=spec["courses"],
        ruleset=spec["ruleset"],
        weights=spec["weights"],
        intervention=spec["intervention"],
        scenario_id=scenario.scenario_id,
        semester_count=spec["semester_count"],
        seed=seed,
        record_decisions=(not do_compare),
    )

    comparison = None
    if do_compare:
        comparison = run_replicated_university_experiment(
            students=spec["students"],
            courses=spec["courses"],
            policy_intervention=spec["intervention"],
            baseline_intervention=UniversityPolicyIntervention(semester_count=spec["semester_count"]),
            ruleset=spec["ruleset"],
            weights=spec["weights"],
            semester_count=spec["semester_count"],
            replications=eff_reps,
            base_seed=seed,
            baseline_scenario_id=f"{scenario.scenario_id}_baseline",
            policy_scenario_id=scenario.scenario_id,
        )
        summary = summarize_university_comparison(comparison)
    else:
        summary = summarize_university_result(single_result)

    return {
        "mode": spec["simulation_mode"],
        "scenario_id": scenario.scenario_id,
        "osym_verified": spec["osym_verified"],
        "coefficients_calibrated": spec["coefficients_calibrated"],
        "disclaimer": spec["disclaimer"],
        "result": single_result.model_dump(mode="json"),
        "comparison": comparison.model_dump(mode="json") if comparison is not None else None,
        "summary": summary,
    }

