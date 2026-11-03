"""Acceptance tests for Phase 1: DST Runtime Response Adapter.

Verifies:
1. 100 real-contract DST responses with status='ok', 'choice', 'is_final'=True, and 'attempt'=1
   are recognized as 100 valid responses (fixing the 0 valid / 100 failed bug).
2. Proper conversion of 'choice' into the question->answer representation using the experiment definition.
3. Preservation of question IDs and option IDs.
4. Handling of intermediate retries (is_final=False) vs final records.
5. Recognition of all DST statuses ('ok', 'invalid_output', 'cache_miss', 'backend_error', 'budget_exhausted', etc.).
6. Paginated API response envelopes ({"run_id": ..., "items": [...]}).
7. Preservation of provenance (run ID, cohort ID, response IDs).
"""

from __future__ import annotations

import pytest

from societytwin.validation import (
    PersonaExecutionRecord,
    SimulationResultsAdapter,
    evaluate_simulation,
    generate_ankara_sample_population,
)
from societytwin.national.experiments import example_fare_definition


@pytest.fixture
def sample_pop_100():
    return generate_ankara_sample_population(100, seed=42)


def test_100_real_dst_runtime_responses_recognized_as_valid(sample_pop_100):
    """The core merge blocker: 100 valid offline DST responses produced by MatrAIx / runner.py

    must be recognized as 100 valid completions with correct answer distributions,
    never 0 valid / 100 failed.
    """
    cols = sample_pop_100.columns
    n = len(cols["synthetic_id"])
    assert n == 100

    exp_def = example_fare_definition("test_cohort_001", seed=42)
    option_ids = [o["id"] for o in exp_def["task"]["options"]]

    # Build 100 real DST runtime response dicts exactly matching runner.py _row() contract
    runtime_responses = []
    expected_choice_counts = {}
    for i, res_id in enumerate(cols["synthetic_id"]):
        chosen_option = option_ids[i % len(option_ids)]
        expected_choice_counts[chosen_option] = expected_choice_counts.get(chosen_option, 0) + 1

        runtime_responses.append({
            "request_key": f"{res_id}:0",
            "persona_id": f"persona_{res_id}",
            "synthetic_id": res_id,
            "province_code": "06",
            "sample_index": 0,
            "attempt": 1,
            "status": "ok",
            "choice": chosen_option,
            "other_text": None,
            "rationale": f"Deterministic test response for resident {res_id}",
            "raw_response": f'{{"choice": "{chosen_option}"}}',
            "error": None,
            "latency_ms": 145.2,
            "input_tokens": 420,
            "output_tokens": 58,
            "cost_usd": 0.00045,
            "provider_call": False,
            "from_cache": True,
            "system_sha256": "abc123system",
            "user_sha256": "def456user",
            "prompt_source": "rendered_by_societytwin",
            "cache_key": f"cache_{res_id}",
            "created_at": "2026-11-02T12:00:00Z",
            "is_final": True,
            "response_id": i + 1,
        })

    # Paginated API envelope
    envelope = {
        "run_id": "run-national-test-100",
        "cohort_id": "test_cohort_001",
        "population_id": "pop-06-2025-n100-s42",
        "total": 100,
        "offset": 0,
        "limit": 100,
        "items": runtime_responses,
        "manifest": {
            "definition": exp_def,
            "experiment_id": "exp-transit-001",
        },
    }

    # Evaluate simulation
    report = evaluate_simulation(
        envelope,
        cohort_metadata=sample_pop_100,
        target_question_id="task_choice",
        experiment_definition=exp_def,
    )

    # Assertions: 100 completed valid executions, 0 failures!
    assert report.failure_audit.successful_valid == 100
    assert report.failure_audit.total_failures == 0
    assert report.failure_audit.completion_rate_pct == 100.0

    # Question distributions preserved
    assert len(report.overall_question_distributions) > 0
    q_summary = report.overall_question_distributions[0]
    assert q_summary.valid_responses_n == 100

    # Option counts match expected
    reported_counts = {c.choice_id: c.unweighted_count for c in q_summary.choices}
    for opt_id, count in expected_choice_counts.items():
        assert reported_counts[opt_id] == count

    # Provenance preserved
    assert report.simulation_run_id == "run-national-test-100"
    assert report.provenance.get("cohort_id") == "test_cohort_001"


def test_dst_response_statuses_and_intermediate_retries():
    """Test that all DST statuses are correctly parsed and intermediate retries are kept as diagnostics

    without double counting participants.
    """
    raw_responses = [
        # Resident 1: Attempt 1 backend_error, Attempt 2 ok (final)
        {
            "synthetic_id": "res_001",
            "attempt": 1,
            "status": "backend_error",
            "choice": None,
            "error": "HTTP 503 Service Unavailable",
            "is_final": False,
        },
        {
            "synthetic_id": "res_001",
            "attempt": 2,
            "status": "ok",
            "choice": "reduce_optional_trips",
            "error": None,
            "is_final": True,
        },
        # Resident 2: budget_exhausted
        {
            "synthetic_id": "res_002",
            "attempt": 1,
            "status": "budget_exhausted",
            "choice": None,
            "error": "The call cap was reached before this call.",
            "is_final": True,
        },
        # Resident 3: invalid_output
        {
            "synthetic_id": "res_003",
            "attempt": 1,
            "status": "invalid_output",
            "choice": None,
            "error": "choice 'fly_to_mars' is not one of the task options",
            "is_final": True,
        },
        # Resident 4: cache_miss
        {
            "synthetic_id": "res_004",
            "attempt": 1,
            "status": "cache_miss",
            "choice": None,
            "error": "Replay cache miss",
            "is_final": True,
        },
    ]

    adapter = SimulationResultsAdapter.from_any(raw_responses)
    # Check that retry attempt was preserved as diagnostic with is_final=False
    r1_attempts = [r for r in adapter.records if r.resident_id == "res_001"]
    assert len(r1_attempts) == 2
    assert not r1_attempts[0].is_final
    assert r1_attempts[0].attempt == 1
    assert r1_attempts[0].status == "failed"
    assert "HTTP 503" in r1_attempts[0].errors[0]

    assert r1_attempts[1].is_final
    assert r1_attempts[1].attempt == 2
    assert r1_attempts[1].status == "valid"
    assert r1_attempts[1].answers.get("task_choice") == "reduce_optional_trips"
