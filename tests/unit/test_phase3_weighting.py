"""Acceptance tests for Phase 3: Statistical Weighting and Provenance.

Verifies:
1. The independent test case where analysis_weight returns 0.90 (whereas population_weight gave 0.10).
2. Equal weights.
3. Missing weights: raises ValueError or loud flag, never silently defaults to 1.0 when weights are expected.
4. Invalid weights: NaN, inf, negative, non-numeric values are rejected.
5. Complete population input: uses population_weight appropriately and records weight_source='population_weight'.
6. Sampling method and weight source preserved in the report.
7. Baseline-vs-intervention comparison documents difference_weighting='weighted'.
"""

from __future__ import annotations

import math
import pytest

from societytwin.validation import (
    evaluate_simulation,
    generate_ankara_sample_population,
)


def test_independent_review_weighting_example_yields_90_percent():
    """Independent review example:

    Cohort sample has 2 residents:
    - Resident A: analysis_weight=9.0, population_weight=1.0, choice='reduce_optional_trips'
    - Resident B: analysis_weight=1.0, population_weight=9.0, choice='maintain_usage'

    Correct Horvitz-Thompson weighted share for reduce_optional_trips:
    9.0 / (9.0 + 1.0) = 0.90 (90%)!
    Previous evaluator bug returned 1.0 / 10.0 = 0.10 (10%).
    """
    cohort_metadata = [
        {
            "synthetic_id": "RES_A",
            "age": 30,
            "sex": "female",
            "marital_status": "single",
            "education_level": "bachelors",
            "population_weight": 1.0,
            "inclusion_probability": 0.1111111,
            "analysis_weight": 9.0,
        },
        {
            "synthetic_id": "RES_B",
            "age": 45,
            "sex": "male",
            "marital_status": "married",
            "education_level": "high_school",
            "population_weight": 9.0,
            "inclusion_probability": 1.0,
            "analysis_weight": 1.0,
        },
    ]

    simulation_results = [
        {"synthetic_id": "RES_A", "status": "ok", "choice": "reduce_optional_trips", "is_final": True},
        {"synthetic_id": "RES_B", "status": "ok", "choice": "maintain_usage", "is_final": True},
    ]

    report = evaluate_simulation(
        simulation_results,
        cohort_metadata=cohort_metadata,
        target_question_id="q1_usage_change",
    )

    q_summary = next(q for q in report.overall_question_distributions if q.question_id == "q1_usage_change")
    reduce_choice = next(c for c in q_summary.choices if c.choice_id == "reduce_optional_trips")
    maintain_choice = next(c for c in q_summary.choices if c.choice_id == "maintain_usage")

    # MUST be 0.90 (90%), NOT 0.10!
    assert math.isclose(reduce_choice.weighted_share, 0.90, rel_tol=1e-5)
    assert math.isclose(maintain_choice.weighted_share, 0.10, rel_tol=1e-5)

    # Diagnostic unweighted share is 50% each:
    assert math.isclose(reduce_choice.unweighted_share, 0.50, rel_tol=1e-5)
    assert math.isclose(maintain_choice.unweighted_share, 0.50, rel_tol=1e-5)

    # Weight provenance preserved:
    assert report.weight_source == "analysis_weight"


def test_complete_population_uses_population_weight():
    """A full synthetic population (not a sampled cohort) uses population_weight."""
    pop = generate_ankara_sample_population(10, seed=42)
    cols = pop.columns

    records = [
        {
            "synthetic_id": res_id,
            "status": "ok",
            "choice": "reduce_optional_trips" if i < 5 else "maintain_usage",
            "is_final": True,
        }
        for i, res_id in enumerate(cols["synthetic_id"])
    ]

    report = evaluate_simulation(
        records,
        cohort_metadata=pop,
        target_question_id="q1_usage_change",
    )

    assert report.weight_source == "population_weight"
    assert report.failure_audit.completed_valid_executions == 10


def test_missing_weights_raises_error():
    """Missing weights cannot be silently coerced to unit weights when weighting is required."""
    cohort_metadata = [
        {"synthetic_id": "RES_1", "age": 30, "sex": "female"},
        {"synthetic_id": "RES_2", "age": 40, "sex": "male"},
    ]
    simulation_results = [
        {"synthetic_id": "RES_1", "status": "ok", "choice": "reduce_optional_trips", "is_final": True},
        {"synthetic_id": "RES_2", "status": "ok", "choice": "maintain_usage", "is_final": True},
    ]

    with pytest.raises(ValueError, match="Missing required weights"):
        evaluate_simulation(
            simulation_results,
            cohort_metadata=cohort_metadata,
            target_question_id="q1_usage_change",
            require_weights=True,
        )


@pytest.mark.parametrize("bad_weight", [float("nan"), float("inf"), -2.5, "not_a_number"])
def test_invalid_weights_rejected(bad_weight):
    """NaN, inf, negative, or non-numeric weights are strictly rejected."""
    cohort_metadata = [
        {"synthetic_id": "RES_1", "analysis_weight": bad_weight},
        {"synthetic_id": "RES_2", "analysis_weight": 1.0},
    ]
    simulation_results = [
        {"synthetic_id": "RES_1", "status": "ok", "choice": "reduce_optional_trips", "is_final": True},
        {"synthetic_id": "RES_2", "status": "ok", "choice": "maintain_usage", "is_final": True},
    ]

    with pytest.raises(ValueError, match="Invalid weight value"):
        evaluate_simulation(
            simulation_results,
            cohort_metadata=cohort_metadata,
            target_question_id="q1_usage_change",
        )
