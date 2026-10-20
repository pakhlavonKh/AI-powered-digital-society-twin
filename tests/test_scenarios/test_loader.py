"""Unit tests for scenario loading, file parsing, and error diagnostics."""

import tempfile
from pathlib import Path
import pytest

from src.scenarios.loader import (
    ScenarioNotFoundError,
    ScenarioParseError,
    ScenarioValidationError,
    load_scenario,
    save_scenario,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "experiments" / "policy_scenarios" / "scenarios"
REFERENCE_SCENARIO_PATH = FIXTURES_DIR / "transport_fare_001.yaml"


def test_load_reference_scenario():
    assert REFERENCE_SCENARIO_PATH.is_file(), f"Missing reference scenario at: {REFERENCE_SCENARIO_PATH}"
    scenario = load_scenario(REFERENCE_SCENARIO_PATH)

    assert scenario.scenario_id == "transport_fare_001"
    assert scenario.version == "1.0.0"
    assert scenario.location.province_code == "06"
    assert scenario.policy.parameters.baseline_fare == 21.0
    assert scenario.policy.parameters.increase_percentage == 20.0
    assert len(scenario.questions) == 2
    assert scenario.questions[0].id == "q1_usage_change"
    assert scenario.questions[1].id == "q2_policy_support"


def test_load_from_dict():
    raw_dict = {
        "scenario_id": "inline_scenario",
        "name": "Inline Test Scenario",
        "description": "A valid inline scenario dictionary.",
        "location": {"province_code": "06", "province_name": "Ankara"},
        "policy": {
            "category": "transportation",
            "type": "fare_increase",
            "parameters": {"baseline_fare": 15.0, "increase_percentage": 10.0, "new_fare": 16.5},
        },
        "questions": [
            {
                "id": "q1",
                "text": "Do you support this?",
                "options": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}],
            }
        ],
    }
    scenario = load_scenario(raw_dict)
    assert scenario.scenario_id == "inline_scenario"
    assert scenario.policy.parameters.new_fare == 16.5


def test_load_nonexistent_file():
    with pytest.raises(ScenarioNotFoundError):
        load_scenario("non_existent_scenario_file_xyz123.yaml")


def test_load_malformed_yaml():
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write("scenario_id: [broken yaml mapping: :::")
        f.flush()
        broken_path = f.name

    try:
        with pytest.raises(ScenarioParseError):
            load_scenario(broken_path)
    finally:
        Path(broken_path).unlink(missing_ok=True)


def test_load_invalid_validation_diagnostics():
    invalid_dict = {
        "scenario_id": "test_invalid",
        "name": "Invalid Scenario",
        "description": "Short description.",
        # Missing 'location' and 'policy'
        "questions": [],
    }
    with pytest.raises(ScenarioValidationError) as exc_info:
        load_scenario(invalid_dict)

    err_text = str(exc_info.value)
    assert "location" in err_text or "policy" in err_text


def test_save_and_reload_roundtrip():
    scenario = load_scenario(REFERENCE_SCENARIO_PATH)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "roundtrip.yaml"
        save_scenario(scenario, tmp_path, file_format="yaml")
        assert tmp_path.exists()

        reloaded = load_scenario(tmp_path)
        assert reloaded.scenario_id == scenario.scenario_id
        assert reloaded.policy.parameters.baseline_fare == scenario.policy.parameters.baseline_fare
        assert len(reloaded.questions) == len(scenario.questions)
