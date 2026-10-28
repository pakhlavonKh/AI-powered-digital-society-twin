"""Regression tests for Scenario Engine defects identified during audit.

Covers:
- P0: Rejection of unknown question identifiers (no silent fallback).
- P0: Metadata preservation in experiment definition (scenario_ref).
- P1: Parameter change propagation without contradictory values (templating).
- P1: Preservation of fare category, concessions, and effective date.
- P1: Explicit rejection of unsupported question formats (multiple_choice).
- P1: Multiple-choice response validation in response_validator.
- Overwrite protection on save_custom_scenario.
"""

from pathlib import Path
import pytest

from scenarios.adapter import (
    ScenarioConflictError,
    UnsupportedQuestionTypeError,
    get_scenario,
    save_custom_scenario,
    scenario_to_experiment_definition,
)
from scenarios.loader import load_scenario
from scenarios.response_validator import (
    ResponseStatus,
    validate_agent_response,
)
from scenarios.schema import (
    QuestionConfig,
    QuestionOption,
    ScenarioConfig,
    UnknownQuestionError,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "experiments" / "policy_scenarios" / "scenarios"
REFERENCE_SCENARIO_PATH = FIXTURES_DIR / "transport_fare_001.yaml"


def test_reject_nonexistent_question_id():
    """P0: An invalid question_id must raise UnknownQuestionError, not fall back to question[0]."""
    scenario = load_scenario(REFERENCE_SCENARIO_PATH)

    with pytest.raises(UnknownQuestionError) as exc_info:
        scenario_to_experiment_definition(scenario, question_id="nonexistent_question_xyz")

    assert "nonexistent_question_xyz" in str(exc_info.value)
    assert "Available question IDs" in str(exc_info.value)


def test_metadata_preserved_in_experiment_definition():
    """P0: scenario ID, version, question ID, and targeting must be preserved in scenario_ref."""
    scenario = load_scenario(REFERENCE_SCENARIO_PATH)
    definition = scenario_to_experiment_definition(
        scenario,
        cohort_id="cohort_123",
        question_id="q1_usage_change",
        seed=42,
    )

    ref = definition.get("scenario_ref")
    assert ref is not None
    assert ref["scenario_id"] == "transport_fare_001"
    assert ref["scenario_version"] == "1.0.0"
    assert ref["question_id"] == "q1_usage_change"
    assert ref["question_type"] == "single_choice"
    assert ref["province_codes"] == ["06"]
    assert ref["minimum_age"] == 18
    assert ref["maximum_age"] is None
    assert ref["unenforced_filters"] == []

    # Scenario parameters preserved
    params = {p["name"]: p["value"] for p in definition["scenario"]["parameters"]}
    assert params["baseline_tariff"] == 21.0
    assert params["new_tariff"] == 25.2
    assert params["tariff_change_percent"] == 20.0
    assert params["fare_category"] == "full_adult_standard"
    assert params["baseline_effective_date"] == "2024-08-01"
    assert "concessions" in params


def test_parameter_change_propagates_consistently_without_contradiction():
    """P1: Changing increase_percentage updates rendered text and new_fare consistently."""
    scenario = load_scenario(REFERENCE_SCENARIO_PATH)

    # Change intervention to 30% increase
    updated = scenario.model_copy(
        update={
            "policy": scenario.policy.model_copy(
                update={
                    "parameters": scenario.policy.parameters.model_copy(
                        update={"increase_percentage": 30.0, "new_fare": None}
                    )
                }
            )
        }
    )

    rendered = updated.rendered()
    # 21.0 * 1.30 = 27.30 TL
    assert "30%" in rendered.description
    assert "27.30 TL" in rendered.description
    assert "21.00 TL" in rendered.description
    # Question text should also reflect the 30% and 27.30 TL
    q1 = next(q for q in rendered.questions if q.id == "q1_usage_change")
    assert "30%" in q1.text
    assert "27.30 TL" in q1.text
    assert "25.20 TL" not in q1.text  # Old hardcoded fare must not appear


def test_reject_unsupported_question_type_in_experiment_conversion():
    """P1: multiple_choice questions must be rejected explicitly rather than silently converted."""
    scenario = load_scenario(REFERENCE_SCENARIO_PATH)

    mc_question = QuestionConfig(
        id="q_multi",
        text="Which travel modes do you use? (Select all that apply)",
        type="multiple_choice",
        options=[
            QuestionOption(id="bus", label="Bus"),
            QuestionOption(id="metro", label="Metro"),
            QuestionOption(id="dolmus", label="Dolmuş"),
        ],
    )
    mc_scenario = scenario.model_copy(update={"questions": [mc_question]})

    with pytest.raises(UnsupportedQuestionTypeError) as exc_info:
        scenario_to_experiment_definition(mc_scenario, question_id="q_multi")

    assert "multiple_choice" in str(exc_info.value)
    assert "single_choice" in str(exc_info.value)


def test_multiple_choice_response_validation():
    """P1: Response validator properly verifies list of options for multiple_choice questions."""
    scenario = load_scenario(REFERENCE_SCENARIO_PATH)
    mc_question = QuestionConfig(
        id="q_modes",
        text="Which modes do you use?",
        type="multiple_choice",
        options=[
            QuestionOption(id="bus", label="Bus"),
            QuestionOption(id="metro", label="Metro"),
            QuestionOption(id="walking", label="Walking"),
        ],
    )
    test_scenario = scenario.model_copy(update={"questions": [mc_question]})

    # 1. Valid multiple choice response
    valid_resp = {
        "scenario_id": test_scenario.scenario_id,
        "resident_id": "RES_001",
        "answers": {"q_modes": ["bus", "metro"]},
    }
    env = validate_agent_response(valid_resp, test_scenario)
    assert env.status == ResponseStatus.VALID
    assert env.answers["q_modes"] == ["bus", "metro"]

    # 2. Invalid choice in multiple choice
    invalid_resp = {
        "scenario_id": test_scenario.scenario_id,
        "resident_id": "RES_001",
        "answers": {"q_modes": ["bus", "helicopter"]},
    }
    env_invalid = validate_agent_response(invalid_resp, test_scenario)
    assert env_invalid.status == ResponseStatus.INVALID
    assert any("helicopter" in err for err in env_invalid.errors)

    # 3. Empty list for multiple choice
    empty_resp = {
        "scenario_id": test_scenario.scenario_id,
        "resident_id": "RES_001",
        "answers": {"q_modes": []},
    }
    env_empty = validate_agent_response(empty_resp, test_scenario)
    assert env_empty.status == ResponseStatus.INVALID
    assert any("cannot be empty" in err for err in env_empty.errors)


def test_single_choice_rejects_list_of_choices():
    """P1: A single_choice question rejects receiving a list of options."""
    scenario = load_scenario(REFERENCE_SCENARIO_PATH)
    resp = {
        "scenario_id": scenario.scenario_id,
        "resident_id": "RES_001",
        "answers": {
            "q1_usage_change": ["maintain_usage", "switch_to_walking"],
            "q2_policy_support": "neutral",
        },
    }
    env = validate_agent_response(resp, scenario)
    assert env.status == ResponseStatus.INVALID
    assert any("is single_choice, but received a list" in err for err in env.errors)


def test_save_custom_scenario_prevents_accidental_overwrite(tmp_path):
    """Save function must not overwrite a different scenario with the same ID unless overwrite=True."""
    scenario = load_scenario(REFERENCE_SCENARIO_PATH)

    # 1. Save original to temporary directory
    saved1 = save_custom_scenario(scenario, target_dir=tmp_path)
    assert saved1.scenario_id == scenario.scenario_id

    # 2. Saving identical scenario again is allowed (idempotent)
    saved_again = save_custom_scenario(scenario, target_dir=tmp_path)
    assert saved_again.scenario_id == scenario.scenario_id

    # 3. Attempting to overwrite with a different description/name fails
    modified = scenario.model_copy(update={"name": "Different Ankara Transit Name"})
    with pytest.raises(ScenarioConflictError) as exc_info:
        save_custom_scenario(modified, target_dir=tmp_path, overwrite=False)
    assert "already exists" in str(exc_info.value)

    # 4. Explicit overwrite=True succeeds
    overwritten = save_custom_scenario(modified, target_dir=tmp_path, overwrite=True)
    assert overwritten.name == "Different Ankara Transit Name"
