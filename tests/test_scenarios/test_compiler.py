"""Unit tests for the Scenario Compiler module."""

import pytest
from pydantic import ValidationError

from scenarios.compiler import (
    compile_scenario_from_prompt,
    compile_scenario_from_prompt_heuristic,
    detect_domain_and_category,
    detect_target_population,
    extract_location,
    extract_percentages_and_numbers,
)
from scenarios.schema import ScenarioConfig


def test_extract_location_ankara_default():
    code, name, nuts2 = extract_location("What happens if transit fares increase?")
    assert code == "06"
    assert name == "Ankara"
    assert nuts2 == "TR51"


def test_extract_location_specific_provinces():
    code, name, _ = extract_location("Simulating a new water subsidy in Istanbul")
    assert code == "34"
    assert name == "İstanbul"

    code, name, _ = extract_location("How would residents in İzmir react to peak electricity pricing?")
    assert code == "35"
    assert name == "İzmir"

    code, name, _ = extract_location("Bursa municipality considers new bike lanes")
    assert code == "16"
    assert name == "Bursa"


def test_extract_percentages_and_numbers():
    pct, base, new_val = extract_percentages_and_numbers("Bus fares increase by 25% in Ankara")
    assert pct == 25.0
    assert base is None
    assert new_val is None

    pct, base, new_val = extract_percentages_and_numbers("Ankara public transport fares rise by 30% from 21 TL")
    assert pct == 30.0
    assert base == 21.0
    assert new_val == 27.3

    pct, base, new_val = extract_percentages_and_numbers("Fare change from 20 TL to 30 TL")
    assert base == 20.0
    assert new_val == 30.0
    assert pct == 50.0


def test_detect_domain_and_category():
    cat, p_type = detect_domain_and_category("Metro and bus fare hike of 20%")
    assert cat == "transportation"
    assert p_type == "fare_increase"

    cat, p_type = detect_domain_and_category("Monthly rent subsidy for low-income families")
    assert cat == "housing"
    assert p_type == "subsidy"

    cat, p_type = detect_domain_and_category("Electricity tariff adjustment during peak hours")
    assert cat == "energy"
    assert p_type == "tariff_adjustment"


def test_detect_target_population():
    # Elderly
    filt = detect_target_population("Free transit for elderly pensioners aged 65+", "06")
    assert filt.minimum_age == 65
    assert filt.province_codes == ["06"]

    # Student
    filt_student = detect_target_population("Discounted meal cards for university students", "34")
    assert filt_student.minimum_age == 18
    assert filt_student.maximum_age == 26

    # Default
    filt_default = detect_target_population("General municipal sales tax", "06")
    assert filt_default.minimum_age == 18
    assert filt_default.maximum_age is None


def test_compile_scenario_from_prompt_heuristic():
    prompt = "What happens in Ankara if transit fares increase by 30%? Will people switch to walking or driving?"
    scenario = compile_scenario_from_prompt_heuristic(prompt)

    assert isinstance(scenario, ScenarioConfig)
    assert scenario.location.province_code == "06"
    assert scenario.location.province_name == "Ankara"
    assert scenario.policy.category == "transportation"
    assert scenario.policy.parameters.increase_percentage == 30.0
    assert len(scenario.questions) >= 2
    assert scenario.questions[0].id == "q1_usage_change"
    assert any(opt.id == "switch_to_walking" for opt in scenario.questions[0].options)
    assert scenario.target_population.adult_only is True


def test_compile_scenario_housing_prompt():
    prompt = "Evaluating a 20% rent subsidy for families living in Izmir"
    scenario = compile_scenario_from_prompt(prompt, force_heuristic=True)

    assert isinstance(scenario, ScenarioConfig)
    assert scenario.location.province_code == "35"
    assert scenario.policy.category == "housing"
    assert len(scenario.questions) >= 1
    assert any("relief" in opt.id for opt in scenario.questions[0].options)


def test_compile_rejects_empty_or_too_short():
    with pytest.raises(ValueError, match="at least 3 characters"):
        compile_scenario_from_prompt("  ")


def test_api_compile_scenario_from_prompt(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from societytwin.api.app import create_app
    from scenarios import adapter

    monkeypatch.setattr(adapter, "DEFAULT_SCENARIOS_DIRS", [tmp_path])

    client = TestClient(create_app(), client=("127.0.0.1", 50000))
    resp = client.post(
        "/api/v2/scenarios/from-prompt",
        json={"prompt": "How do residents in Bursa adapt to an 18% electricity tariff increase?"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["location"]["province_code"] == "16"
    assert data["location"]["province_name"] == "Bursa"
    assert data["policy"]["category"] == "energy"
    assert len(data["questions"]) >= 1


def test_compile_discount_prompt_uses_negative_percentage():
    prompt = "How would university students in Istanbul respond to a 50% transit pass discount?"
    scenario = compile_scenario_from_prompt(prompt, force_heuristic=True)
    assert scenario.location.province_code == "34"
    assert scenario.policy.parameters.increase_percentage == -50.0
    assert scenario.policy.parameters.baseline_fare is None
    assert scenario.policy.parameters.new_fare is None
    assert "(-50%)" in scenario.name
    assert "decrease by 50%" in scenario.questions[0].text
    assert scenario.target_population.minimum_age == 18
    assert scenario.target_population.maximum_age == 26
    assert scenario.target_population.province_codes == ["34"]


