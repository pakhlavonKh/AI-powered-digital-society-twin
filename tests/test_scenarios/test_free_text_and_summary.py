"""Tests for free-text (open-ended) questions and prompt summarization in the Scenario Engine."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scenarios.adapter import (
    get_scenario,
    scenario_to_experiment_definition,
    EXECUTABLE_QUESTION_TYPES,
)
from scenarios.compiler import compile_scenario_from_prompt
from scenarios.prompt_renderer import render_scenario_prompt
from scenarios.response_validator import ResponseStatus, validate_agent_response
from scenarios.schema import (
    PolicyConfig,
    PolicyParameters,
    PopulationFilterConfig,
    QuestionConfig,
    QuestionOption,
    ScenarioConfig,
    ScenarioLocation,
    ScenarioMetadata,
)
from scenarios.summary import (
    generate_result_text_summary,
)
from societytwin.national.experiments import TaskSpec, parse_response


def _make_base_scenario(questions: list[QuestionConfig]) -> ScenarioConfig:
    return ScenarioConfig(
        scenario_id="test_free_text_scenario",
        version="1.0.0",
        name="Test Free-Text and Summary Scenario",
        description="Testing free-text policy feedback in Ankara.",
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
                new_fare=25.0,
                increase_percentage=25.0,
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


def test_free_text_question_schema_valid():
    """free_text questions can be created with empty options and length bounds."""
    q = QuestionConfig(
        id="q_feedback",
        text="What are your thoughts on this fare increase?",
        type="free_text",
        options=[],
        min_length=5,
        max_length=500,
        ask_rationale=False,
    )
    assert q.type == "free_text"
    assert len(q.options) == 0
    assert q.min_length == 5
    assert q.max_length == 500


def test_free_text_question_rejects_allow_other():
    """free_text questions must not specify allow_other=True."""
    with pytest.raises(ValidationError) as exc:
        QuestionConfig(
            id="q_feedback",
            text="Describe your opinion.",
            type="free_text",
            options=[],
            allow_other=True,
        )
    assert "cannot specify allow_other=True" in str(exc.value)


def test_free_text_question_rejects_invalid_bounds():
    """min_length cannot exceed max_length."""
    with pytest.raises(ValidationError) as exc:
        QuestionConfig(
            id="q_feedback",
            text="Describe your opinion.",
            type="free_text",
            options=[],
            min_length=500,
            max_length=100,
        )
    assert "min_length (500) cannot exceed max_length (100)" in str(exc.value)


def test_single_choice_still_requires_at_least_two_options():
    """Regression check: single_choice still enforces len(options) >= 2."""
    with pytest.raises(ValidationError) as exc:
        QuestionConfig(
            id="q_choice",
            text="Select an option.",
            type="single_choice",
            options=[QuestionOption(id="opt1", label="Option 1")],
        )
    assert "must have at least 2 options" in str(exc.value)


def test_render_scenario_prompt_with_free_text():
    """Prompt renderer includes open-ended instructions and JSON format for free_text questions."""
    q_choice = QuestionConfig(
        id="q1_support",
        text="Do you support the fare change?",
        type="single_choice",
        options=[
            QuestionOption(id="yes", label="Yes"),
            QuestionOption(id="no", label="No"),
        ],
    )
    q_text = QuestionConfig(
        id="q2_reasons",
        text="Explain in detail how this will affect your monthly commuting habits.",
        type="free_text",
        options=[],
        ask_rationale=False,
    )
    sc = _make_base_scenario([q_choice, q_text])
    persona = {
        "resident_id": "RES_999",
        "age": 28,
        "sex": "female",
        "marital_status": "single",
        "education_level": "university",
        "province_name": "Ankara",
    }
    sys_p, user_p = render_scenario_prompt(sc, persona)

    assert "RES_999" not in sys_p
    assert "Profile Identifier" not in sys_p
    assert "Age: 28" in sys_p
    assert "[q1_support]" in user_p
    assert "[q2_reasons]" in user_p
    assert "Provide an open-ended textual answer / explanation" in user_p
    assert "<your open-ended textual answer>" in user_p


def test_validate_agent_response_free_text_success():
    """Validator accepts valid free_text string responses."""
    q_text = QuestionConfig(
        id="q_feedback",
        text="What are your thoughts on this fare increase?",
        type="free_text",
        options=[],
        min_length=10,
        max_length=300,
    )
    sc = _make_base_scenario([q_text])
    resp = {
        "scenario_id": sc.scenario_id,
        "resident_id": "RES_100",
        "answers": {
            "q_feedback": "As a commuter, this increase will strain my weekly transportation budget significantly.",
        },
        "rationale": "Cost concerns for student commute.",
    }
    env = validate_agent_response(resp, sc)
    assert env.status == ResponseStatus.VALID
    assert "strain my weekly transportation budget" in env.answers["q_feedback"]


def test_validate_agent_response_free_text_rejects_empty_or_non_string():
    """Validator rejects empty strings and non-string types for free_text."""
    q_text = QuestionConfig(
        id="q_feedback",
        text="What are your thoughts?",
        type="free_text",
        options=[],
    )
    sc = _make_base_scenario([q_text])

    # 1. Empty string
    env_empty = validate_agent_response(
        {"scenario_id": sc.scenario_id, "resident_id": "R1", "answers": {"q_feedback": "   "}},
        sc,
    )
    assert env_empty.status == ResponseStatus.INVALID
    assert any("cannot be empty" in err for err in env_empty.errors)

    # 2. List type instead of string
    env_list = validate_agent_response(
        {"scenario_id": sc.scenario_id, "resident_id": "R1", "answers": {"q_feedback": ["thought 1", "thought 2"]}},
        sc,
    )
    assert env_list.status == ResponseStatus.INVALID
    assert any("must be a text string" in err for err in env_list.errors)


def test_validate_agent_response_free_text_length_bounds():
    """Validator enforces min_length and max_length for free_text."""
    q_text = QuestionConfig(
        id="q_feedback",
        text="What are your thoughts?",
        type="free_text",
        options=[],
        min_length=20,
        max_length=50,
    )
    sc = _make_base_scenario([q_text])

    # Too short
    env_short = validate_agent_response(
        {"scenario_id": sc.scenario_id, "resident_id": "R1", "answers": {"q_feedback": "Too short"}},
        sc,
    )
    assert env_short.status == ResponseStatus.INVALID
    assert any("minimum required is 20" in err for err in env_short.errors)

    # Too long
    env_long = validate_agent_response(
        {"scenario_id": sc.scenario_id, "resident_id": "R1", "answers": {"q_feedback": "A" * 60}},
        sc,
    )
    assert env_long.status == ResponseStatus.INVALID
    assert any("exceeds maximum length of 50" in err for err in env_long.errors)


def test_compiler_synthesizes_free_text_for_text_prompts():
    """Compiler creates free_text questions when the user asks for text answers or feedback."""
    # 1. Pure text prompt
    sc_pure = compile_scenario_from_prompt("In Ankara transit fare hike, ask citizens for a text only explanation of concerns", force_heuristic=True)
    assert any(q.type == "free_text" for q in sc_pure.questions)

    # 2. Prompt requesting feedback alongside choices
    sc_feedback = compile_scenario_from_prompt("Ankara public bus fare increases by 20%. Include open ended feedback on alternatives.", force_heuristic=True)
    assert any(q.type == "free_text" for q in sc_feedback.questions)



def test_national_task_spec_supports_free_text():
    """SocietyTwin national TaskSpec and parse_response handle response_type='free_text'."""
    spec = TaskSpec(
        instruction="Describe your primary commuting challenge.",
        response_type="free_text",
        options=[],
    )
    assert spec.response_type == "free_text"
    assert len(spec.options) == 0

    parsed = parse_response('{"answer": "Traffic delays during morning rush hour."}', spec)
    assert parsed["valid"] is True
    assert parsed["answer"] == "Traffic delays during morning rush hour."


def test_adapter_supports_free_text_questions():
    """Adapter includes free_text in EXECUTABLE_QUESTION_TYPES and converts cleanly."""
    assert "free_text" in EXECUTABLE_QUESTION_TYPES

    q_text = QuestionConfig(
        id="q_commute",
        text="Describe your daily commute experience.",
        type="free_text",
        options=[],
    )
    sc = _make_base_scenario([q_text])
    exp_def = scenario_to_experiment_definition(sc, cohort_id="test_cohort", question_id="q_commute")
    assert exp_def["task"]["response_type"] == "free_text"
    assert len(exp_def["task"]["options"]) == 0




def test_generate_result_text_summary_choice():
    """generate_result_text_summary creates comprehensive summary for choice experiments."""
    definition = {
        "title": "Ankara 25% Fare Hike Experiment",
        "scenario": {
            "title": "Ankara Transit Fare Increase",
            "description": "Public transit fare increases from 20 TL to 25 TL.",
        },
        "task": {
            "instruction": "How will your commuting habits change?",
            "response_type": "single_choice",
            "options": [
                {"id": "reduce_trips", "label": "Reduce optional trips"},
                {"id": "maintain", "label": "Maintain usage as before"},
                {"id": "switch_walk", "label": "Switch to walking"},
            ],
        },
    }
    responses = [
        {"synthetic_id": "RES_1", "status": "valid", "choice": "reduce_trips", "rationale": "High inflation."},
        {"synthetic_id": "RES_2", "status": "valid", "choice": "reduce_trips", "rationale": "Ticket prices too high."},
        {"synthetic_id": "RES_3", "status": "valid", "choice": "maintain", "rationale": "I need bus for work."},
        {"synthetic_id": "RES_4", "status": "valid", "choice": "switch_walk", "rationale": "Walking is healthy and free."},
    ]
    summary = generate_result_text_summary(definition, responses)
    assert summary["is_free_text"] is False
    assert summary["total_responses"] == 4
    assert summary["valid_responses"] == 4
    assert "Reduce optional trips" in summary["headline"]
    assert "50.0%" in summary["headline"]
    assert len(summary["key_findings"]) >= 2
    assert "Executive Policy Result Summary" in summary["summary_markdown"]
    assert len(summary["representative_quotes"]) > 0


def test_generate_result_text_summary_free_text():
    """generate_result_text_summary creates qualitative thematic summary for free-text experiments."""
    definition = {
        "title": "Qualitative Commuter Feedback Survey",
        "scenario": {
            "title": "Bursa Natural Gas Tariff Adjustment",
            "description": "Residential natural gas tariffs increase by 15%.",
        },
        "task": {
            "instruction": "In your own words, explain how this policy will impact your household budget.",
            "response_type": "free_text",
            "options": [],
        },
    }
    responses = [
        {
            "synthetic_id": "RES_A",
            "status": "valid",
            "choice": "This winter will be difficult for our family as heating costs will consume a large share of our pension.",
            "province_code": "16",
        },
        {
            "synthetic_id": "RES_B",
            "status": "valid",
            "choice": "We will have to reduce daytime heating temperatures and wear extra layers indoors to balance costs.",
            "province_code": "16",
        },
    ]
    summary = generate_result_text_summary(definition, responses)
    assert summary["is_free_text"] is True
    assert summary["total_responses"] == 2
    assert summary["valid_responses"] == 2
    assert "in-depth qualitative responses" in summary["headline"]
    assert len(summary["representative_quotes"]) == 2
    assert "Resident RES_A" in summary["summary_markdown"]
    assert "heating costs" in summary["summary_markdown"]


def test_generate_result_text_summary_all_failed():
    """When all responses fail (e.g. 401 auth error), summary provides clear failure diagnostics."""
    definition = {
        "title": "Ankara Public Policy Survey",
        "task": {
            "instruction": "What is the best location to open cafe in Ankara?",
            "response_type": "free_text",
            "options": [],
        },
    }
    responses = [
        {
            "synthetic_id": f"RES_{i}",
            "status": "backend_error",
            "error": "AuthenticationError: Error code: 401 - Incorrect API key provided",
        }
        for i in range(20)
    ]
    summary = generate_result_text_summary(definition, responses)
    assert summary["valid_responses"] == 0
    assert summary["total_responses"] == 20
    assert "No valid citizen responses were recorded" in summary["headline"]
    assert "401" in summary["headline"]
    assert summary["generated_by"] == "system"


def test_generate_result_text_summary_with_mocked_llm(monkeypatch):
    """When an LLM call succeeds, summary uses LLM synthesis."""
    monkeypatch.setenv("OPENAI_API_KEY", "mock-test-key")

    mock_llm_result = {
        "title": "Ankara Cafe Feasibility",
        "headline": "Tunali Hilmi and Bahcelievler emerged as the top recommended cafe locations.",
        "key_findings": [
            "High foot traffic in Cankaya",
            "Student density favors 7th street Bahcelievler",
        ],
        "summary_markdown": "# AI Executive Synthesis\n\nHigh consensus on student and pedestrian corridors.",
        "representative_quotes": [{"synthetic_id": "RES_1", "province_code": "06", "quote": "Tunali is best.", "rationale": "High foot traffic"}],
        "generated_by": "llm",
    }

    monkeypatch.setattr("scenarios.summary._generate_llm_result_summary", lambda **kwargs: mock_llm_result)

    definition = {
        "title": "Ankara Cafe Feasibility",
        "model": {"backend": "matraix", "transport": "live"},
        "task": {"instruction": "Where to open cafe?", "response_type": "free_text", "options": []},
    }
    responses = [{"synthetic_id": "RES_1", "status": "valid", "choice": "Tunali is best."}]

    summary = generate_result_text_summary(definition, responses, allow_llm=True)
    assert summary["generated_by"] == "llm"
    assert "Tunali Hilmi" in summary["headline"]
    assert summary["valid_responses"] == 1



def test_summary_never_calls_provider_in_fake_or_offline_mode(monkeypatch):
    """Audit P0-2: Fake or offline experiments must NEVER call LLM summarization even if OPENAI_API_KEY is configured."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-dummy-secret-key-that-should-never-be-used")
    called = []
    monkeypatch.setattr("scenarios.summary._generate_llm_result_summary", lambda **kwargs: called.append(True))

    definition = {
        "title": "Offline Fare Test",
        "model": {"backend": "stub", "transport": "fake"},
        "task": {"instruction": "What transit choice?", "response_type": "single_choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]},
    }
    responses = [{"synthetic_id": "ST1", "status": "ok", "choice": "a"}]
    summary = generate_result_text_summary(definition, responses)
    assert len(called) == 0, "Provider call was unexpectedly initiated during offline experiment summary!"
    assert summary["generated_by"] == "deterministic"
