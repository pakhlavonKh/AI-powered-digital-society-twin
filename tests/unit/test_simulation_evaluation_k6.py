"""Unit tests for Phase 6 Simulation Results Evaluator (K6).

Tests:
1. Consumer-side adapter parses heterogeneous simulation results (dicts, objects, lists).
2. Accounting of failed/missing responses: explicitly reported with categories and resident IDs, never dropped silently.
3. Weighted vs unweighted response distributions using population weights.
4. Demographic subgroup comparisons: accurate splits and small subgroup low-confidence flags (n < 15).
5. Synthetic baseline disclaimer: baseline-vs-intervention delta explicitly carries software testing disclaimer.
6. Missing benchmarks are explicitly reported as 'unavailable' with unverified hypothetical status.
7. End-to-end evaluation of a 100-record synthetic fixture with intentional failures (Task 6 requirement).
8. Report serialization, fingerprint stability, and Markdown rendering.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from societytwin.validation import (
    BenchmarkBundle,
    FailureAuditSummary,
    PersonaExecutionRecord,
    SimulationEvaluationReport,
    SimulationResultsAdapter,
    evaluate_simulation,
    generate_ankara_sample_population,
    get_ankara_transit_fare_bundle,
)


@pytest.fixture(scope="module")
def sample_pop_100():
    """Deterministic 100-person Ankara sample (seed=42)."""
    return generate_ankara_sample_population(100, seed=42)


@pytest.fixture(scope="module")
def synthetic_simulation_fixture_100(sample_pop_100):
    """Generate 100 synthetic agent simulation records with intentional realistic responses and failures.

    Requirements:
    - 100 records total.
    - Explicitly labeled as synthetic for testing.
    - Includes varied responses (maintain_usage, reduce_optional_trips, switch_to_walking, etc.).
    - Includes intentional failures (invalid choice, timeout, refusal, missing answer) to test audit accounting.
    """
    records: list[dict] = []
    cols = sample_pop_100.columns
    n = len(cols["synthetic_id"])

    for i in range(n):
        res_id = cols["synthetic_id"][i]
        age = cols["age"][i]
        sex = cols["sex"][i]
        marital = cols["marital_status"][i]

        # Intentional failures for 8 records:
        if i == 5:
            # Failure 1: Timeout error
            records.append({
                "resident_id": res_id,
                "status": "timeout",
                "answers": {},
                "rationale": None,
                "errors": ["LLM generation timeout after 60s"],
            })
        elif i == 12:
            # Failure 2: Refusal (sensitive political objection)
            records.append({
                "resident_id": res_id,
                "status": "refused",
                "answers": {"q1_usage_change": "refused", "q2_policy_support": "refused"},
                "rationale": "I decline to participate in municipal policy surveys.",
                "errors": ["User refused response"],
            })
        elif i == 23:
            # Failure 3: Invalid choice (unsupported enum)
            records.append({
                "resident_id": res_id,
                "status": "invalid",
                "answers": {"q1_usage_change": "buy_a_helicopter", "q2_policy_support": "strongly_oppose"},
                "rationale": "I will fly instead.",
                "errors": ["Invalid choice 'buy_a_helicopter' for q1_usage_change"],
            })
        elif i == 45:
            # Failure 4: Missing required answer
            records.append({
                "resident_id": res_id,
                "status": "invalid",
                "answers": {"q2_policy_support": "somewhat_oppose"},
                "rationale": "Forgot question 1.",
                "errors": ["Missing answer for 'q1_usage_change'"],
            })
        elif i == 78:
            # Failure 5: Upstream API 500 error
            records.append({
                "resident_id": res_id,
                "status": "failed",
                "answers": {},
                "rationale": None,
                "errors": ["Provider internal server error (HTTP 500)"],
            })
        else:
            # Valid responses conditioned realistically on age / legal concession
            if age >= 65:
                # Statutory free concession for seniors under Law No. 4736
                q1 = "maintain_usage"
                q2 = "neutral"
                rat = f"I am {age} years old and travel free under statutory senior concession; tariff has zero cost impact."
            elif age < 25:
                # Students / youth: high trip reduction or walking
                q1 = "reduce_optional_trips" if i % 2 == 0 else "switch_to_walking"
                q2 = "strongly_oppose"
                rat = f"As a {age}-year-old student/youth, a 20% tariff hike strains my budget."
            else:
                # Working adults: mix of maintain, reduce, and switch
                choices = ["maintain_usage", "reduce_optional_trips", "switch_to_private_car_or_taxi", "switch_to_walking"]
                weights = [0.45, 0.40, 0.10, 0.05]
                q1 = choices[i % len(choices)]
                q2 = "somewhat_oppose" if q1 != "maintain_usage" else "somewhat_support"
                rat = f"Working adult age {age} evaluating 20% fare increase on household budget."

            records.append({
                "resident_id": res_id,
                "status": "valid",
                "answers": {
                    "q1_usage_change": q1,
                    "q2_policy_support": q2,
                },
                "rationale": rat,
                "execution_time_seconds": 1.25,
                "prompt_tokens": 450,
                "completion_tokens": 65,
                "model_name": "matraix-persona-8b-synthetic-test",
            })

    return {
        "scenario_id": "transport_fare_001",
        "run_id": "run-test-synthetic-100-personas",
        "model": "matraix-persona-8b-synthetic-test",
        "temperature": 0.2,
        "records": records,
        "manifest": {
            "synthetic_fixture": True,
            "purpose": "K6 Simulation Evaluator unit testing",
            "seed": 42,
        },
    }


@pytest.fixture(scope="module")
def synthetic_baseline_fixture_100(sample_pop_100):
    """Synthetic status-quo baseline run (before fare increase) for delta comparison."""
    records: list[dict] = []
    cols = sample_pop_100.columns
    for res_id in cols["synthetic_id"]:
        records.append({
            "resident_id": res_id,
            "status": "valid",
            "answers": {
                "q1_usage_change": "maintain_usage",
                "q2_policy_support": "neutral",
            },
        })
    return {
        "scenario_id": "transport_fare_001",
        "run_id": "run-baseline-status-quo-test",
        "model": "matraix-persona-8b-synthetic-test",
        "records": records,
    }


# -----------------------------------------------------------------------------
# Unit Tests
# -----------------------------------------------------------------------------

def test_consumer_side_adapter(synthetic_simulation_fixture_100):
    """Verify consumer-side adapter parses raw dicts and heterogeneous records."""
    adapter = SimulationResultsAdapter.from_any(synthetic_simulation_fixture_100)
    assert adapter.scenario_id == "transport_fare_001"
    assert adapter.run_id == "run-test-synthetic-100-personas"
    assert len(adapter.records) == 100

    # Check first record
    r0 = adapter.records[0]
    assert isinstance(r0, PersonaExecutionRecord)
    assert r0.resident_id == "ST2025-06-0000001"
    assert r0.status == "valid"
    assert "q1_usage_change" in r0.answers


def test_failure_accounting_never_dropped_silently(synthetic_simulation_fixture_100, sample_pop_100):
    """Verify failed, invalid, refused, and timeout responses are recorded explicitly and never dropped."""
    report = evaluate_simulation(
        simulation_results=synthetic_simulation_fixture_100,
        cohort_metadata=sample_pop_100,
    )
    audit = report.failure_audit

    assert audit.total_attempted == 100
    assert audit.successful_valid == 95  # 5 intentional failures
    assert audit.total_failures == 5
    assert audit.completion_rate_pct == 95.0

    # Verify breakdown of failure types
    breakdown = audit.failure_breakdown_by_status
    assert breakdown["timeout"] == 1
    assert breakdown["refused"] == 1
    assert breakdown["invalid"] == 2
    assert breakdown["failed"] == 1

    # Verify distinct errors are captured
    assert any("timeout" in err.lower() for err in audit.distinct_error_messages)
    assert any("buy_a_helicopter" in err for err in audit.distinct_error_messages)
    assert any("500" in err for err in audit.distinct_error_messages)

    # Verify unanswered resident IDs are preserved
    assert len(audit.unanswered_residents) == 5
    assert "ST2025-06-0000006" in audit.unanswered_residents  # index 5


def test_weighted_response_distribution(synthetic_simulation_fixture_100, sample_pop_100):
    """Verify weighted and unweighted choice shares are computed using population weights."""
    report = evaluate_simulation(
        simulation_results=synthetic_simulation_fixture_100,
        cohort_metadata=sample_pop_100,
    )
    q1 = next(q for q in report.overall_question_distributions if q.question_id == "q1_usage_change")

    assert q1.valid_responses_n == 95
    assert q1.valid_weighted_total > 0.0

    # Total unweighted shares must sum to 1.0
    u_sum = sum(c.unweighted_share for c in q1.choices)
    assert pytest.approx(u_sum, 1e-6) == 1.0

    # Total weighted shares must sum to 1.0
    w_sum = sum(c.weighted_share for c in q1.choices)
    assert pytest.approx(w_sum, 1e-6) == 1.0

    # Check that standard errors are strictly non-negative
    for c in q1.choices:
        assert c.std_error_unweighted >= 0.0


def test_subgroup_comparisons_and_small_n_confidence_flag(synthetic_simulation_fixture_100, sample_pop_100):
    """Verify demographic subgroup breakdowns and small-n low-confidence flagging."""
    report = evaluate_simulation(
        simulation_results=synthetic_simulation_fixture_100,
        cohort_metadata=sample_pop_100,
        min_subgroup_n=15,
    )
    subgroups = report.subgroup_comparisons
    assert len(subgroups) > 0

    # Verify age bracket splits exist
    age_groups = [s for s in subgroups if s.subgroup_dimension == "age_bracket"]
    assert len(age_groups) > 0

    # Verify that groups with sample_n < 15 are flagged as low-confidence
    for s in subgroups:
        if s.sample_n < 15:
            assert s.is_low_confidence is True
            assert "LOW CONFIDENCE" in s.confidence_note
        else:
            assert s.is_low_confidence is False

    # Check senior concession group: seniors aged 65+ travel free under Law 4736
    senior_sub = next(s for s in subgroups if s.subgroup_dimension == "statutory_concession" and "senior" in s.subgroup_value)
    # Seniors in fixture chose maintain_usage
    assert senior_sub.choice_shares_unweighted.get("maintain_usage", 0.0) == 1.0


def test_baseline_vs_intervention_synthetic_disclaimer(
    synthetic_simulation_fixture_100,
    synthetic_baseline_fixture_100,
    sample_pop_100,
):
    """Verify baseline-vs-intervention delta comparison carries explicit software testing disclaimer."""
    report = evaluate_simulation(
        simulation_results=synthetic_simulation_fixture_100,
        cohort_metadata=sample_pop_100,
        baseline_simulation_results=synthetic_baseline_fixture_100,
    )
    assert len(report.baseline_deltas) > 0

    delta = report.baseline_deltas[0]
    assert "SYNTHETIC BASELINE DISCLAIMER" in delta.evidence_disclaimer
    assert "CANNOT establish empirical predictive accuracy" in delta.evidence_disclaimer
    assert delta.baseline_run_id == "run-baseline-status-quo-test"
    assert delta.intervention_run_id == "run-test-synthetic-100-personas"


def test_missing_benchmarks_reported_as_unavailable(synthetic_simulation_fixture_100, sample_pop_100):
    """Verify missing benchmarks are explicitly marked as unavailable with unverified status."""
    report = evaluate_simulation(
        simulation_results=synthetic_simulation_fixture_100,
        cohort_metadata=sample_pop_100,
    )
    b_comps = report.benchmark_comparisons

    # EGO observed elasticity must be unavailable
    ego_comp = next(b for b in b_comps if b.benchmark_id == "ankara_ego_observed_elasticity")
    assert ego_comp.benchmark_status == "unavailable"
    assert ego_comp.evidence_status == "unverified_hypothetical"
    assert "BENCHMARK UNAVAILABLE" in ego_comp.evidence_status_statement
    assert ego_comp.benchmark_value is None

    # Stated intention survey benchmark must be unavailable
    stated_comp = next(b for b in b_comps if b.benchmark_id == "ankara_stated_travel_intention")
    assert stated_comp.benchmark_status == "unavailable"
    assert stated_comp.evidence_status == "unverified_hypothetical"

    # Literature elasticity must be available with envelope
    lit_comp = next(b for b in b_comps if b.benchmark_id == "literature_transit_fare_elasticity")
    assert lit_comp.benchmark_status == "available"
    assert lit_comp.evidence_status == "literature_envelope"
    assert lit_comp.benchmark_value == -0.33
    assert lit_comp.simulated_value is not None


def test_markdown_and_json_serialization(synthetic_simulation_fixture_100, sample_pop_100):
    """Verify Markdown generation and JSON round-trip stability."""
    report = evaluate_simulation(
        simulation_results=synthetic_simulation_fixture_100,
        cohort_metadata=sample_pop_100,
    )
    md = report.to_markdown()

    assert "# K6 Simulation Results Evaluation Report" in md
    assert "## 1. Response Distributions" in md
    assert "## 2. Demographic Subgroup Comparisons" in md
    assert "## 3. Behavioral Benchmark Comparisons" in md
    assert "## 5. Failure & Non-Response Audit Summary" in md
    assert "SYNTHETIC SIMULATION BASELINE" in md

    # JSON round-trip
    raw_json = report.model_dump_json()
    roundtrip = SimulationEvaluationReport.model_validate_json(raw_json)
    assert roundtrip.report_fingerprint == report.report_fingerprint
    assert roundtrip.run_id == report.run_id
    assert roundtrip.failure_audit.successful_valid == 95
