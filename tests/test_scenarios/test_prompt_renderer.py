"""Unit tests for scenario prompt rendering."""

from pathlib import Path

from src.scenarios.loader import load_scenario
from src.scenarios.prompt_renderer import render_scenario_prompt

SCENARIO_PATH = Path(__file__).resolve().parents[2] / "experiments" / "policy_scenarios" / "scenarios" / "transport_fare_001.yaml"


def test_render_scenario_prompt():
    scenario = load_scenario(SCENARIO_PATH)
    resident = {
        "resident_id": "ANK_TEST_001",
        "age": 28,
        "sex": "female",
        "province_name": "Ankara",
        "marital_status": "married",
        "education_level": "tertiary_university",
        "secret_seed_should_not_leak": 999999,
    }

    system_prompt, user_prompt = render_scenario_prompt(scenario, resident)

    # 1. System prompt assertions
    assert "ANK_TEST_001" in system_prompt
    assert "Ankara" in system_prompt
    assert "28" in system_prompt
    assert "female" in system_prompt
    # Confidentiality check: internal generator seeds must never leak into prompt
    assert "999999" not in system_prompt
    assert "secret_seed" not in system_prompt

    # 2. User prompt assertions
    assert scenario.name in user_prompt
    assert "21.00 TL" in user_prompt
    assert "25.20 TL" in user_prompt
    assert "q1_usage_change" in user_prompt
    assert "q2_policy_support" in user_prompt
    assert "```json" in user_prompt
