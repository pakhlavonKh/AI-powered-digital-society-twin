"""Comprehensive regression tests verifying fixes for the independent audit findings.

Audit References:
- P0-1: Compiled free-text scenarios fail experiment creation with HTTP 422.
- P0-2: Result summarization must not trigger external provider calls in fake/offline mode.
- P0-3: Agent prompts must not expose internal resident IDs; age bands must have clean Unicode/ASCII.
- P0-4: Latest Population Engine projection contract (dst-matraix-projection-1) integration.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from scenarios.compiler import compile_scenario_from_prompt
from scenarios.adapter import scenario_to_experiment_definition
from scenarios.prompt_renderer import render_scenario_prompt
from scenarios.summary import generate_result_text_summary
from scenarios.schema import (
    ScenarioConfig,
    PolicyConfig,
    PolicyParameters,
    ScenarioLocation,
    ScenarioMetadata,
    QuestionConfig,
    QuestionOption,
    PopulationFilterConfig,
)
from societytwin.national.personas import matraix_persona, _display
from societytwin.national.matraix_projection import project_persona, CROSSWALK_VERSION
from tests.national.conftest import national_settings, store, national_client, population_id  # noqa: F401


def _make_test_scenario(questions: list[QuestionConfig]) -> ScenarioConfig:
    return ScenarioConfig(
        scenario_id="test_audit_scenario",
        version="1.0.0",
        name="Test Audit Scenario",
        description="Testing policy intervention in Ankara.",
        location=ScenarioLocation(
            province_code="06",
            province_name="Ankara",
            nuts2_code="TR51",
        ),
        metadata=ScenarioMetadata(hypothetical=True),
        policy=PolicyConfig(
            category="transportation",
            type="fare_increase",
            parameters=PolicyParameters(
                baseline_fare=20.0,
                new_fare=24.0,
                increase_percentage=20.0,
                currency="TL",
            ),
        ),
        target_population=PopulationFilterConfig(
            minimum_age=18,
            province_codes=["06"],
            adult_only=True,
        ),
        questions=questions,
    )


def test_p0_1_free_text_scenario_experiment_creation_and_execution(national_client, population_id):
    """P0-1 Fix: A free-text scenario must produce a valid ExperimentDefinition accepted

    by the API (no HTTP 422) and executable through the offline stub backend without errors.
    """
    client = national_client

    # 1. Create a free-text policy scenario
    q_free = QuestionConfig(
        id="q1_open_thoughts",
        text="What are your thoughts on public transit fare adjustments in Ankara?",
        type="free_text",
        options=[],
        ask_rationale=False,
    )
    scenario = _make_test_scenario([q_free])
    assert scenario.questions[0].type == "free_text"
    assert len(scenario.questions[0].options) == 0

    # 2. Create matching cohort
    cohort_res = client.post("/api/v2/cohorts", json={
        "name": "Ankara Adults",
        "population_id": population_id,
        "filters": {"age_min": 18, "province_codes": ["06"]},
    })
    assert cohort_res.status_code == 201, cohort_res.text
    cohort_id = cohort_res.json()["cohort_id"]

    # 3. Convert to experiment definition
    exp_def = scenario_to_experiment_definition(scenario, cohort_id=cohort_id)
    assert exp_def["scenario_ref"]["question_type"] == "free_text"
    assert exp_def["task"]["response_type"] == "free_text"
    assert exp_def["task"]["options"] == []

    # 4. Create experiment via POST /api/v2/experiments (Must NOT fail with HTTP 422)
    exp_res = client.post("/api/v2/experiments", json=exp_def)
    assert exp_res.status_code == 201, f"Failed with {exp_res.status_code}: {exp_res.text}"
    exp_data = exp_res.json()
    exp_id = exp_data["experiment_id"]

    # 5. Review plan via POST /api/v2/experiments/{id}/plan
    plan_res = client.post(f"/api/v2/experiments/{exp_id}/plan")
    assert plan_res.status_code == 201, plan_res.text
    plan_data = plan_res.json()
    assert plan_data["executable"] is True
    assert len(plan_data["blockers"]) == 0

    # 6. Execute run via POST /api/v2/experiments/{id}/runs (Stub backend handles free-text without ZeroDivisionError)
    run_res = client.post(f"/api/v2/experiments/{exp_id}/runs", json={
        "plan_hash": plan_data["plan_hash"],
        "idempotency_key": "test-p0-1-run",
        "confirm": True,
    })
    assert run_res.status_code == 202, run_res.text
    run_data = run_res.json()["run"]
    assert run_data["state"] == "completed"

    # 7. Verify textual summary can be generated
    sum_res = client.get(f"/api/v2/runs/{run_data['run_id']}/text-summary")
    assert sum_res.status_code == 200, sum_res.text
    sum_data = sum_res.json()
    assert sum_data["is_free_text"] is True
    assert sum_data["valid_responses"] > 0
    assert sum_data["generated_by"] == "deterministic"


def test_p0_2_summary_zero_provider_calls_when_credentials_present(monkeypatch):
    """P0-2 Fix: Offline / fake-mode simulation summaries make zero external provider requests

    regardless of whether API credentials (OPENAI_API_KEY) are present in the environment.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-dummy-secret-key-that-must-never-be-called")

    called_provider = []

    def fake_llm(**kwargs):
        called_provider.append(True)
        return {"headline": "Leaked LLM call", "generated_by": "llm"}

    monkeypatch.setattr("scenarios.summary._generate_llm_result_summary", fake_llm)

    # 1. Offline experiment definition (stub or fake)
    fake_def = {
        "title": "Offline Transit Policy",
        "model": {"backend": "stub", "transport": "fake"},
        "task": {"instruction": "Choose transit mode", "response_type": "single_choice", "options": [{"id": "bus", "label": "Bus"}]},
    }
    responses = [{"synthetic_id": "ST001", "status": "ok", "choice": "bus", "rationale": "Reason"}]

    summary = generate_result_text_summary(fake_def, responses)
    assert len(called_provider) == 0, "External provider was called in offline mode!"
    assert summary["generated_by"] == "deterministic"

    # 2. Even for free-text offline experiment
    free_def = {
        "title": "Offline Free-text Policy",
        "model": {"backend": "matraix", "transport": "fake"},
        "task": {"instruction": "Explain reasons", "response_type": "free_text", "options": []},
    }
    free_responses = [{"synthetic_id": "ST002", "status": "ok", "choice": "My thoughts", "rationale": "Because of traffic"}]
    free_summary = generate_result_text_summary(free_def, free_responses)
    assert len(called_provider) == 0, "External provider was called for offline free-text summary!"
    assert free_summary["generated_by"] == "deterministic"


def test_p0_3_agent_prompts_omit_internal_ids_and_have_clean_age_unicode():
    """P0-3 Fix: Agent prompts do not expose internal resident IDs, and age bands are standard ASCII."""
    # 1. Prompt renderer omits internal identifier
    q = QuestionConfig(id="q1", text="Do you agree?", type="single_choice", options=[QuestionOption(id="yes", label="Yes"), QuestionOption(id="no", label="No")])
    scenario = _make_test_scenario([q])

    persona_ctx = {
        "resident_id": "ST2025-06-0000502",
        "synthetic_id": "ST2025-06-0000502",
        "age": 34,
        "sex": "female",
        "marital_status": "married",
        "province_name": "Ankara",
    }

    system_prompt, user_prompt = render_scenario_prompt(scenario, persona_ctx)
    assert "ST2025-06-0000502" not in system_prompt
    assert "Profile Identifier" not in system_prompt
    assert "resident_id" not in user_prompt
    assert "Location: Ankara, Türkiye" in system_prompt
    assert "Age: 34" in system_prompt

    # 2. Age-group display produces valid, uncorrupted UTF-8 en-dash without mojibake
    record = {"age_group": "45-49", "age": 47}
    age_disp = _display("age_group", record)
    assert age_disp == "45–49"
    assert age_disp.encode("utf-8") == b"45\xe2\x80\x9349"
    assert "â" not in age_disp


def test_p0_4_matraix_persona_projection_contract():
    """P0-4 Fix: Scenario Engine uses the reviewed MatrAIx projection contract, masks display_name

    to 'Resident' to prevent prompt leakage, and adheres to dst-matraix-projection-1.
    """
    persona = {
        "persona_id": "per-test12345678",
        "synthetic_id": "ST2025-06-0000999",
        "population_id": "pop-06-2025-n10000-s42-e901eaa4",
        "province_code": "06",
        "province_name": "Ankara",
        "template_version": "tr-persona-card-1",
        "model_visible": {
            "province_name": "Ankara",
            "age_group": "45-49",
            "sex": "female",
            "marital_status": "married",
            "education_level": "higher_education",
        },
        "model_visible_fields": ["age_group", "education_level", "marital_status", "province_name", "sex"],
        "attributes": [
            {"field": "province_name", "status": "visible", "value": "06", "display": "Ankara"},
            {"field": "age_group", "status": "visible", "value": "45-49", "display": "45-49"},
            {"field": "sex", "status": "visible", "value": "female", "display": "female"},
            {"field": "marital_status", "status": "visible", "value": "married", "display": "married"},
            {"field": "education_level", "status": "visible", "value": "higher_education", "display": "higher_education"},
        ],
        "hidden": [],
        "limitations": [],
        "provenance": {},
    }

    projected = matraix_persona(persona)

    # Must set display_name = 'Resident' to mask internal technical ID
    assert projected["display_name"] == "Resident"
    assert projected["persona_id"] == "ST2025-06-0000999"

    # Must use reviewed dst_ dimension catalog
    dims = projected["dimensions"]
    assert dims["dst_residence_province"] == "Ankara"
    assert dims["dst_age_group"] == "45-49"
    assert dims["dst_marital_status"] == "married"
    assert dims["demo_marital_status"] == "Married"

    # Crosswalk version binding
    proj_meta = projected["metadata"]["projection"]
    assert proj_meta["crosswalk_version"] == CROSSWALK_VERSION
