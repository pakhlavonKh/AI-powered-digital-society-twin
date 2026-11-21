"""Tests for paired counterfactual placement comparisons and CRN quantile aggregation."""

from __future__ import annotations

import pytest

from scenarios.placement.cohort_synth import build_standalone_demo_programs, build_standalone_test_cohort
from scenarios.placement.comparison import (
    ComparisonMismatchError,
    aggregate_replicated_comparisons,
    compare_placement_scenarios,
)
from scenarios.placement.engine import run_placement
from scenarios.placement.models import CandidateRecord, ProgramOffering
from scenarios.schema import UniversityPolicyIntervention


def test_compare_scenarios_transition_conservation_and_program_deltas():
    programs = [
        ProgramOffering(
            program_id="P_TOP",
            university_id="U1",
            university_name="Uni",
            province_code="06",
            department_name="Top",
            score_type="SAY",
            capacity=2,
            tuition_annual=150_000.0,
        ),
        ProgramOffering(
            program_id="P_SAFE",
            university_id="U1",
            university_name="Uni",
            province_code="06",
            department_name="Safe",
            score_type="SAY",
            capacity=1,
            tuition_annual=0.0,
        ),
    ]
    cands = [
        CandidateRecord(candidate_id="C1", scores={"SAY": 480.0}, ranks={"SAY": 1}, liquid_budget=200_000.0, preferences=["P_TOP", "P_SAFE"]),
        CandidateRecord(candidate_id="C2", scores={"SAY": 450.0}, ranks={"SAY": 2}, liquid_budget=50_000.0, preferences=["P_TOP", "P_SAFE"]),
        CandidateRecord(candidate_id="C3", scores={"SAY": 420.0}, ranks={"SAY": 3}, liquid_budget=200_000.0, preferences=["P_TOP", "P_SAFE"]),
        CandidateRecord(candidate_id="C4", scores={"SAY": 390.0}, ranks={"SAY": 4}, liquid_budget=200_000.0, preferences=["P_SAFE"]),
    ]

    base = run_placement(cands, programs)
    pol = run_placement(
        cands,
        programs,
        intervention=UniversityPolicyIntervention(affordability_filter_mode="hard_exclude"),
    )

    report = compare_placement_scenarios(base, pol)
    tr = report.transitions
    assert (
        tr.same_program
        + tr.improved_preference
        + tr.worsened_preference
        + tr.newly_placed
        + tr.displaced_to_unplaced
        + tr.remained_unplaced
        + tr.eligibility_changed
    ) == tr.total_candidates == 4
    # Baseline: C1,C2->P_TOP; C3->P_SAFE; C4->unplaced
    # Policy:   C1,C3->P_TOP (C3 improved); C2->P_SAFE (worsened); C4->unplaced (still behind C2 in P_SAFE)
    assert tr.same_program == 1
    assert tr.improved_preference == 1
    assert tr.worsened_preference == 1
    assert tr.remained_unplaced == 1
    assert report.osym_verified is False
    assert "does NOT reproduce official ÖSYM" in report.disclaimer


def test_compare_captures_newly_placed_displaced_and_eligibility_changed():
    programs = [
        ProgramOffering(
            program_id="P_PAID",
            university_id="U1",
            university_name="Uni",
            university_type="foundation",
            province_code="06",
            department_name="Paid",
            score_type="SAY",
            baraj_group="engineering",
            capacity=1,
            tuition_annual=120_000.0,
        )
    ]
    cands = [
        CandidateRecord(candidate_id="C1", scores={"SAY": 480.0}, ranks={"SAY": 1}, liquid_budget=40_000.0, preferences=["P_PAID"]),
        CandidateRecord(candidate_id="C2", scores={"SAY": 450.0}, ranks={"SAY": 2}, liquid_budget=200_000.0, preferences=["P_PAID"]),
    ]
    base = run_placement(cands, programs)
    pol = run_placement(
        cands,
        programs,
        intervention=UniversityPolicyIntervention(affordability_filter_mode="hard_exclude"),
    )
    report = compare_placement_scenarios(base, pol)
    assert report.transitions.displaced_to_unplaced == 1
    assert report.transitions.newly_placed == 1


def test_compare_rejects_mismatched_cohorts():
    progs = build_standalone_demo_programs()
    c1 = build_standalone_test_cohort(progs, size=20, seed=1)
    c2 = build_standalone_test_cohort(progs, size=20, seed=2)

    r1 = run_placement(c1.candidates, progs, seed=1)
    r2 = run_placement(c2.candidates, progs, seed=2)

    with pytest.raises(ComparisonMismatchError, match="different candidate cohorts"):
        compare_placement_scenarios(r1, r2)


def test_crn_replicated_comparison_aggregation():
    progs = build_standalone_demo_programs()
    reports = []
    for seed in (10, 11, 12, 13, 14):
        cohort = build_standalone_test_cohort(progs, size=60, seed=seed)
        base = run_placement(cohort.candidates, progs, seed=seed)
        pol = run_placement(
            cohort.candidates,
            progs,
            intervention=UniversityPolicyIntervention(capacity_change_pct=-15.0),
            seed=seed,
        )
        reports.append(compare_placement_scenarios(base, pol))

    summary = aggregate_replicated_comparisons(reports)
    assert summary["replications"] == 5
    assert summary["osym_verified"] is False
    cap_stats = summary["metric_delta_distributions"]["total_capacity"]
    assert cap_stats["mean_delta"] < 0
    assert cap_stats["p05_delta"] <= cap_stats["p50_delta"] <= cap_stats["p95_delta"]
