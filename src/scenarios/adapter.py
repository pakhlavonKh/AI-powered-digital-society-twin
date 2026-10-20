"""Adapter converting ScenarioConfig models into SocietyTwin national ExperimentDefinition schemas.

Provides catalog discovery and transformation from multi-question YAML scenarios
into experiment designs ready for API v2 and the experiment runner.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from .loader import load_scenario
    from .schema import ScenarioConfig
except ImportError:
    from scenarios.loader import load_scenario
    from scenarios.schema import ScenarioConfig

DEFAULT_SCENARIOS_DIRS = [
    Path("experiments/policy_scenarios/scenarios"),
    Path("scenarios"),
]


def find_scenario_paths(custom_dirs: list[Path] | None = None) -> dict[str, Path]:
    """Find all unique YAML scenario files by scenario_id."""
    paths: dict[str, Path] = {}
    search_dirs = custom_dirs or DEFAULT_SCENARIOS_DIRS

    for s_dir in search_dirs:
        resolved = s_dir if s_dir.is_absolute() else Path.cwd() / s_dir
        if not resolved.is_dir():
            continue
        for ext in ("*.yaml", "*.yml"):
            for file_path in resolved.glob(ext):
                try:
                    loaded = load_scenario(file_path)
                    if loaded.scenario_id not in paths:
                        paths[loaded.scenario_id] = file_path
                except Exception:
                    continue

    return paths


def list_available_scenarios(custom_dirs: list[Path] | None = None) -> list[dict[str, Any]]:
    """List summary metadata for all discovered policy scenarios."""
    catalog = find_scenario_paths(custom_dirs)
    items: list[dict[str, Any]] = []

    for scenario_id, path in sorted(catalog.items()):
        scenario = load_scenario(path)
        items.append({
            "scenario_id": scenario.scenario_id,
            "version": scenario.version,
            "name": scenario.name,
            "description": scenario.description,
            "category": scenario.policy.category,
            "type": scenario.policy.type,
            "location": {
                "province_code": scenario.location.province_code,
                "province_name": scenario.location.province_name,
            },
            "questions_count": len(scenario.questions),
            "questions": [{"id": q.id, "text": q.text} for q in scenario.questions],
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
        question_id: Specific question to ask; if None, defaults to the first question.
        seed: Random seed for cohort sampling.

    Returns:
        Dictionary conforming to societytwin.national.experiments.ExperimentDefinition.
    """
    # Select question
    target_q = scenario.questions[0]
    if question_id:
        matched = next((q for q in scenario.questions if q.id == question_id), None)
        if matched:
            target_q = matched

    # Build parameters
    params: list[dict[str, Any]] = []
    p = scenario.policy.parameters

    if p.baseline_fare is not None:
        params.append({
            "name": "baseline_tariff",
            "label": "Baseline Tariff",
            "value": p.baseline_fare,
            "unit": p.currency,
        })
    if p.new_fare is not None:
        params.append({
            "name": "new_tariff",
            "label": "Proposed Tariff",
            "value": p.new_fare,
            "unit": p.currency,
        })
    if p.increase_percentage is not None:
        params.append({
            "name": "tariff_change_percent",
            "label": "Tariff Adjustment",
            "value": p.increase_percentage,
            "unit": "%",
        })

    # Build task options
    options = [{"id": opt.id, "label": opt.label} for opt in target_q.options]

    # Return structure matching societytwin.national.experiments.ExperimentDefinition
    return {
        "title": f"{scenario.name} (Hypothetical)" if scenario.metadata.hypothetical else scenario.name,
        "scenario": {
            "title": scenario.name,
            "description": scenario.description,
            "parameters": params,
            "hypothetical": scenario.metadata.hypothetical,
            "source_note": scenario.metadata.source_note,
        },
        "task": {
            "instruction": target_q.text,
            "options": options,
            "allow_other_text": target_q.allow_other,
            "ask_rationale": target_q.ask_rationale,
            "adult_only": scenario.target_population.adult_only,
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
    }


def save_custom_scenario(
    data: dict[str, Any] | ScenarioConfig,
    target_dir: Path | None = None,
) -> ScenarioConfig:
    """Validate and persist a custom policy scenario as a YAML file in the scenarios catalog.

    Args:
        data: ScenarioConfig instance or raw dict conforming to ScenarioConfig.
        target_dir: Optional custom storage directory. Defaults to experiments/policy_scenarios/scenarios.

    Returns:
        The validated and persisted ScenarioConfig.
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
    dump_dict = config.model_dump(mode="json", exclude_none=True)

    with open(target_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(dump_dict, f, sort_keys=False, allow_unicode=True)

    return config

