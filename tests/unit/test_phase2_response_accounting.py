"""Acceptance tests for Phase 2: Missing, Duplicate, and Invalid Response Accounting.

Verifies:
1. 100 expected, 100 valid responses -> 100 completed valid, 0 missing, 0 failed, 0 duplicate, 0 foreign.
2. 100 expected, 95 returned -> 95 completed valid, 5 missing (explicitly identified).
3. A duplicated final result -> detected as duplicate, not counted twice.
4. A result for a resident outside the cohort -> flagged as foreign respondent, not counted in cohort completions.
5. An empty successful response -> fails question completion check, classified as invalid/failed.
6. A failed respondent followed by a valid retry -> counts as 1 completed participant, retry preserved as diagnostic.
"""

from __future__ import annotations

import pytest

from societytwin.validation import (
    evaluate_simulation,
    generate_ankara_sample_population,
)


@pytest.fixture
def sample_pop_100():
    return generate_ankara_sample_population(100, seed=42)


def test_accounting_100_expected_100_valid(sample_pop_100):
    """Case 1: 100 expected, 100 valid returned."""
    cols = sample_pop_100.columns
    records = [
        {
            "synthetic_id": res_id,
            "status": "ok",
            "choice": "reduce_optional_trips",
            "is_final": True,
            "attempt": 1,
        }
        for res_id in cols["synthetic_id"]
    ]

    report = evaluate_simulation(
        records,
        cohort_metadata=sample_pop_100,
        target_question_id="q1_usage_change",
    )

    audit = report.failure_audit
    assert audit.expected_executions == 100
    assert audit.received_executions == 100
    assert audit.completed_valid_executions == 100
    assert audit.failed_executions == 0
    assert audit.missing_executions == 0
    assert audit.duplicate_executions == 0
    assert audit.foreign_executions == 0
    assert audit.completion_rate_pct == 100.0


def test_accounting_100_expected_95_returned(sample_pop_100):
    """Case 2: 100 expected, 95 returned (5 missing respondents)."""
    cols = sample_pop_100.columns
    # Only return the first 95 residents
    records = [
        {
            "synthetic_id": res_id,
            "status": "ok",
            "choice": "maintain_usage",
            "is_final": True,
            "attempt": 1,
        }
        for res_id in cols["synthetic_id"][:95]
    ]

    report = evaluate_simulation(
        records,
        cohort_metadata=sample_pop_100,
        target_question_id="q1_usage_change",
    )

    audit = report.failure_audit
    assert audit.expected_executions == 100
    assert audit.received_executions == 95
    assert audit.completed_valid_executions == 95
    assert audit.failed_executions == 0
    assert audit.missing_executions == 5
    assert len(audit.missing_residents) == 5
    # The 5 missing residents are exactly the last 5
    expected_missing = set(cols["synthetic_id"][95:])
    assert set(audit.missing_residents) == expected_missing
    assert audit.completion_rate_pct == 95.0


def test_accounting_duplicate_final_result(sample_pop_100):
    """Case 3: Duplicated final result for a resident."""
    cols = sample_pop_100.columns
    records = [
        {
            "synthetic_id": res_id,
            "status": "ok",
            "choice": "maintain_usage",
            "is_final": True,
            "attempt": 1,
        }
        for res_id in cols["synthetic_id"]
    ]
    # Add a duplicate final response for resident 0
    dup_id = cols["synthetic_id"][0]
    records.append({
        "synthetic_id": dup_id,
        "status": "ok",
        "choice": "reduce_optional_trips",
        "is_final": True,
        "attempt": 1,
    })

    report = evaluate_simulation(
        records,
        cohort_metadata=sample_pop_100,
        target_question_id="q1_usage_change",
    )

    audit = report.failure_audit
    assert audit.expected_executions == 100
    assert audit.received_executions == 101
    assert audit.completed_valid_executions == 100
    assert audit.duplicate_executions == 1
    assert dup_id in audit.duplicate_residents


def test_accounting_foreign_resident(sample_pop_100):
    """Case 4: A result for a resident outside the cohort."""
    cols = sample_pop_100.columns
    records = [
        {
            "synthetic_id": res_id,
            "status": "ok",
            "choice": "maintain_usage",
            "is_final": True,
            "attempt": 1,
        }
        for res_id in cols["synthetic_id"]
    ]
    # Add a foreign resident not in sample_pop_100
    records.append({
        "synthetic_id": "FOREIGN_RESIDENT_999",
        "status": "ok",
        "choice": "maintain_usage",
        "is_final": True,
        "attempt": 1,
    })

    report = evaluate_simulation(
        records,
        cohort_metadata=sample_pop_100,
        target_question_id="q1_usage_change",
    )

    audit = report.failure_audit
    assert audit.expected_executions == 100
    assert audit.received_executions == 101
    assert audit.completed_valid_executions == 100
    assert audit.foreign_executions == 1
    assert "FOREIGN_RESIDENT_999" in audit.foreign_residents


def test_accounting_empty_successful_response(sample_pop_100):
    """Case 5: A response marked 'ok' / 'valid' but missing required question answer."""
    cols = sample_pop_100.columns
    records = [
        {
            "synthetic_id": res_id,
            "status": "ok",
            "choice": "maintain_usage" if i > 0 else None,  # Resident 0 has empty choice!
            "answers": {} if i == 0 else {"q1_usage_change": "maintain_usage"},
            "is_final": True,
            "attempt": 1,
        }
        for i, res_id in enumerate(cols["synthetic_id"])
    ]

    report = evaluate_simulation(
        records,
        cohort_metadata=sample_pop_100,
        target_question_id="q1_usage_change",
    )

    audit = report.failure_audit
    assert audit.expected_executions == 100
    assert audit.completed_valid_executions == 99
    assert audit.failed_executions == 1
    assert cols["synthetic_id"][0] in audit.unanswered_residents


def test_accounting_failed_attempt_with_valid_retry(sample_pop_100):
    """Case 6: A failed attempt followed by a valid retry counts as 1 completed participant."""
    cols = sample_pop_100.columns
    res0 = cols["synthetic_id"][0]

    records = [
        # Resident 0 attempt 1 failed:
        {
            "synthetic_id": res0,
            "status": "backend_error",
            "choice": None,
            "is_final": False,
            "attempt": 1,
            "error": "Timeout 504",
        },
        # Resident 0 attempt 2 ok:
        {
            "synthetic_id": res0,
            "status": "ok",
            "choice": "reduce_optional_trips",
            "is_final": True,
            "attempt": 2,
        },
    ]
    # Other 99 residents have 1 successful attempt:
    for res_id in cols["synthetic_id"][1:]:
        records.append({
            "synthetic_id": res_id,
            "status": "ok",
            "choice": "maintain_usage",
            "is_final": True,
            "attempt": 1,
        })

    report = evaluate_simulation(
        records,
        cohort_metadata=sample_pop_100,
        target_question_id="q1_usage_change",
    )

    audit = report.failure_audit
    assert audit.expected_executions == 100
    assert audit.received_executions == 101  # 100 final + 1 retry diagnostic
    assert audit.completed_valid_executions == 100  # counts as 1 completed participant!
    assert audit.failed_executions == 0
    assert audit.missing_executions == 0


def test_accounting_at_1000_agents_scale():
    """Verify response reconciliation works accurately at 1,000 agents scale."""
    n = 1000
    expected_ids = [f"RES_{i:04d}" for i in range(n)]
    cohort = [{"synthetic_id": rid, "age": 20 + (i % 50), "sex": "female" if i % 2 == 0 else "male", "analysis_weight": 1.0} for i, rid in enumerate(expected_ids)]

    # 950 valid, 30 failed, 20 missing, 10 duplicates, 5 foreign
    records = []
    # 950 valid
    for rid in expected_ids[:950]:
        records.append({
            "synthetic_id": rid,
            "status": "ok",
            "choice": "reduce_optional_trips",
            "is_final": True,
            "attempt": 1,
        })
    # 30 failed
    for rid in expected_ids[950:980]:
        records.append({
            "synthetic_id": rid,
            "status": "backend_error",
            "choice": None,
            "error": "Provider 500",
            "is_final": True,
            "attempt": 1,
        })
    # Next 20 (980:1000) are not returned -> missing!

    # 10 duplicates
    for rid in expected_ids[:10]:
        records.append({
            "synthetic_id": rid,
            "status": "ok",
            "choice": "reduce_optional_trips",
            "is_final": True,
            "attempt": 1,
        })

    # 5 foreign
    for i in range(5):
        records.append({
            "synthetic_id": f"FOREIGN_{i}",
            "status": "ok",
            "choice": "maintain_usage",
            "is_final": True,
            "attempt": 1,
        })

    report = evaluate_simulation(
        records,
        cohort_metadata=cohort,
        target_question_id="task_choice",
    )

    audit = report.failure_audit
    assert audit.expected_executions == 1000
    assert audit.received_executions == 950 + 30 + 10 + 5  # 995
    assert audit.completed_valid_executions == 950
    assert audit.failed_executions == 30
    assert audit.missing_executions == 20
    assert audit.duplicate_executions == 10
    assert audit.foreign_executions == 5
    assert len(audit.missing_residents) == 20
    assert len(audit.duplicate_residents) == 10
    assert len(audit.foreign_residents) == 5
    assert audit.completion_rate_pct == 95.0
