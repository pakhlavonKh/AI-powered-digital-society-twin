"""Unit tests for agent structured response validation contract."""

import json
from pathlib import Path

from src.scenarios.loader import load_scenario
from src.scenarios.response_validator import (
    ResponseStatus,
    validate_agent_response,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
SCENARIO_PATH = Path(__file__).resolve().parents[2] / "experiments" / "policy_scenarios" / "scenarios" / "transport_fare_001.yaml"
RESPONSES_PATH = FIXTURES_DIR / "sample_agent_responses.json"


def test_validate_standard_valid_response():
    scenario = load_scenario(SCENARIO_PATH)
    with open(RESPONSES_PATH, encoding="utf-8") as f:
        samples = json.load(f)

    res = validate_agent_response(samples["valid_standard_json"], scenario)
    assert res.status == ResponseStatus.VALID
    assert res.is_valid() is True
    assert res.scenario_id == "transport_fare_001"
    assert res.answers["q1_usage_change"] == "reduce_optional_trips"
    assert res.answers["q2_policy_support"] == "somewhat_oppose"
    assert len(res.errors) == 0


def test_validate_markdown_fenced_response():
    scenario = load_scenario(SCENARIO_PATH)
    with open(RESPONSES_PATH, encoding="utf-8") as f:
        samples = json.load(f)

    res = validate_agent_response(samples["valid_fenced_markdown"], scenario)
    assert res.status == ResponseStatus.VALID
    assert res.answers["q1_usage_change"] == "maintain_usage"
    assert res.answers["q2_policy_support"] == "neutral"
    assert res.resident_id == "ANK_TEST_002"


def test_reject_illegal_choice():
    scenario = load_scenario(SCENARIO_PATH)
    with open(RESPONSES_PATH, encoding="utf-8") as f:
        samples = json.load(f)

    res = validate_agent_response(samples["invalid_illegal_choice"], scenario)
    assert res.status == ResponseStatus.INVALID
    assert res.is_valid() is False
    assert any("Invalid choice 'maybe'" in err for err in res.errors)


def test_reject_missing_question():
    scenario = load_scenario(SCENARIO_PATH)
    with open(RESPONSES_PATH, encoding="utf-8") as f:
        samples = json.load(f)

    res = validate_agent_response(samples["invalid_missing_question"], scenario)
    assert res.status == ResponseStatus.INVALID
    assert any("Missing answer for question 'q2_policy_support'" in err for err in res.errors)


def test_flag_mismatched_scenario_id():
    scenario = load_scenario(SCENARIO_PATH)
    with open(RESPONSES_PATH, encoding="utf-8") as f:
        samples = json.load(f)

    res = validate_agent_response(samples["invalid_scenario_id_mismatch"], scenario)
    assert res.status == ResponseStatus.INVALID
    assert any("Mismatched scenario_id" in err for err in res.errors)


def test_handle_refused_response():
    scenario = load_scenario(SCENARIO_PATH)
    with open(RESPONSES_PATH, encoding="utf-8") as f:
        samples = json.load(f)

    res = validate_agent_response(samples["valid_refused"], scenario)
    assert res.status == ResponseStatus.REFUSED
    assert res.answers["q1_usage_change"] == "refused"
    assert res.answers["q2_policy_support"] == "refused"


def test_handle_unparseable_garbage():
    scenario = load_scenario(SCENARIO_PATH)
    res = validate_agent_response("I cannot answer as an AI model and refuse to output JSON.", scenario)
    assert res.status == ResponseStatus.PARSE_ERROR
    assert len(res.errors) > 0
