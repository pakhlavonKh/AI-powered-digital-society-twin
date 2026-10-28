"""Adapter converting ScenarioConfig models into SocietyTwin national ExperimentDefinition schemas.

Provides catalog discovery and transformation from multi-question YAML scenarios
into experiment designs ready for API v2 and the experiment runner.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

try:
    from .loader import load_scenario
    from .schema import ScenarioConfig, UnknownQuestionError
except ImportError:
    from scenarios.loader import load_scenario
    from scenarios.schema import ScenarioConfig, UnknownQuestionError

logger = logging.getLogger(__name__)

DEFAULT_SCENARIOS_DIRS = [
    Path("experiments/policy_scenarios/scenarios"),
    Path("scenarios"),
]

# Question types the national experiment runtime (TaskSpec) can execute.
EXECUTABLE_QUESTION_TYPES = frozenset({"single_choice"})
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
    search_dirs = custom_dirs or DEFAULT_SCENARIOS_DIRS

    for s_dir in search_dirs:
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
                    logger.warning("Duplicate scenario_id '%s' in %s ignored; using %s",
                                   loaded.scenario_id, file_path, paths[loaded.scenario_id])
                    continue
                paths[loaded.scenario_id] = file_path

    return paths


def list_available_scenarios(custom_dirs: list[Path] | None = None) -> list[dict[str, Any]]:
    """List summary metadata for all discovered policy scenarios."""
    catalog = find_scenario_paths(custom_dirs)
    items: list[dict[str, Any]] = []

    for scenario_id, path in sorted(catalog.items()):
        scenario = load_scenario(path)
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

    # Build task options
    options = [{"id": opt.id, "label": opt.label} for opt in target_q.options]

    tp = scenario.target_population
    unenforced = sorted(
        name for name, value in tp.model_dump().items()
        if name not in _ENFORCED_FILTERS and value not in (None, [], ())
    )

    # Return structure matching societytwin.national.experiments.ExperimentDefinition
    return {
        "title": f"{scenario.name} (Hypothetical)" if scenario.metadata.hypothetical else scenario.name,
        "scenario": {
            "title": scenario.name,
            "description": shown.description,
            "parameters": params,
            "hypothetical": scenario.metadata.hypothetical,
            "source_note": scenario.metadata.source_note,
            "version": scenario.version,
        },
        "task": {
            "instruction": target_q.text,
            "options": options,
            "allow_other_text": target_q.allow_other,
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
            "unenforced_filters": unenforced,
        },
    }


def save_custom_scenario(
    data: dict[str, Any] | ScenarioConfig,
    target_dir: Path | None = None,
    overwrite: bool = False,
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
    existing_path = target_file if target_file.exists() else find_scenario_paths(
        [target_dir] if target_dir else None).get(config.scenario_id)
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

