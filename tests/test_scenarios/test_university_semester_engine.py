"""Tests for Milestone 2 multi-semester engine, UNI-001..UNI-006, and Milestone 1 handoff."""

from __future__ import annotations

import pytest

from scenarios.adapter import execute_placement_scenario, placement_result_to_student_cohort
from scenarios.placement.cohort_synth import build_standalone_demo_programs, build_standalone_test_cohort
from scenarios.schema import (
    PlacementScenarioConfig,
    PolicyConfig,
    PolicyParameters,
    ScenarioLocation,
    UniversityPolicyIntervention,
)
from scenarios.university.cohort import (
    build_synthetic_university_cohort,
    student_cohort_from_placement_handoff,
)
from scenarios.university.models import DEFAULT_UNIVERSITY_DISCLAIMER, UniversityRuleset
from scenarios.university.semester_engine import run_university_simulation


def test_multi_semester_baseline_invariants_and_reproducibility() -> None:
    students, courses = build_synthetic_university_cohort(size=120, seed=42)
    res1 = run_university_simulation(
        students,
        courses,
        semester_count=4,
        seed=77,
        record_decisions=True,
        scenario_id="baseline_check",
    )
    res2 = run_university_simulation(
        students,
        courses,
        semester_count=4,
        seed=77,
        record_decisions=True,
        scenario_id="baseline_check",
    )

    assert res1.manifest.osym_verified is False
    assert res1.manifest.coefficients_calibrated is False
    assert res1.manifest.disclaimer == DEFAULT_UNIVERSITY_DISCLAIMER
    assert res1.manifest.result_sha256 == res2.manifest.result_sha256
    assert res1.final_summary == res2.final_summary
    assert all(res1.manifest.validation_checks.values())
    assert len(res1.decision_records) > 0

    # Conservation invariant: every student is in exactly one lifecycle state bucket per semester
    for snap in res1.semester_snapshots:
        total_state_count = (
            snap.active_students
            + snap.paused_stop_out_students
            + snap.withdrawn_dropout_students
            + snap.graduated_students
        )
        assert total_state_count == len(students)

    # Academic invariant: earned_credits <= attempted_credits and GPAs within [0, 4]
    for st in res1.final_students:
        assert 0 <= st.earned_credits <= st.attempted_credits
        assert 0.0 <= st.gpa <= 4.0


def test_uni001_tuition_hike_vs_uni002_aid_and_uni006_installments() -> None:
    students, courses = build_synthetic_university_cohort(size=240, seed=42)

    base = run_university_simulation(
        students, courses, intervention=UniversityPolicyIntervention(tuition_change_pct=0.0, semester_count=4), seed=42
    )
    hike = run_university_simulation(
        students, courses, intervention=UniversityPolicyIntervention(tuition_change_pct=20.0, semester_count=4), seed=42
    )
    hike_plus_aid = run_university_simulation(
        students,
        courses,
        intervention=UniversityPolicyIntervention(tuition_change_pct=20.0, aid_budget_change_pct=40.0, semester_count=4),
        seed=42,
    )
    hike_plus_inst = run_university_simulation(
        students,
        courses,
        intervention=UniversityPolicyIntervention(tuition_change_pct=20.0, installment_count=4, semester_count=4),
        seed=42,
    )

    # UNI-001 (+20% tuition) lowers active/retention or raises attrition/transfers vs baseline
    assert hike.final_summary["cumulative_retention_rate"] <= base.final_summary["cumulative_retention_rate"]
    # UNI-002 (+40% aid offset) and UNI-006 (installments) improve retention over unmitigated hike
    assert hike_plus_aid.final_summary["cumulative_retention_rate"] >= hike.final_summary["cumulative_retention_rate"]
    assert hike_plus_inst.final_summary["cumulative_retention_rate"] >= hike.final_summary["cumulative_retention_rate"]
    assert hike_plus_aid.final_summary["total_aid_disbursed"] > hike.final_summary["total_aid_disbursed"]


def test_uni003_attendance_uni004_grading_and_uni005_capacity_waitlists() -> None:
    students, courses = build_synthetic_university_cohort(size=200, seed=99)

    base = run_university_simulation(
        students, courses, intervention=UniversityPolicyIntervention(semester_count=2), seed=99
    )
    # UNI-003: raising mandatory attendance threshold from 70% -> 82% increases attendance failures
    uni003 = run_university_simulation(
        students,
        courses,
        intervention=UniversityPolicyIntervention(attendance_min_pct=82.0, semester_count=2),
        seed=99,
    )
    assert sum(s.attendance_ineligible_courses for s in uni003.semester_snapshots[1:]) > sum(
        s.attendance_ineligible_courses for s in base.semester_snapshots[1:]
    )

    # UNI-004: stricter grading lowers mean GPA
    uni004 = run_university_simulation(
        students,
        courses,
        intervention=UniversityPolicyIntervention(grading_difficulty_shift=0.45, semester_count=2),
        seed=99,
    )
    assert uni004.final_summary["final_mean_gpa"] < base.final_summary["final_mean_gpa"]

    # UNI-005: -25% course seat capacity creates/increases waitlists without ever exceeding seat capacity
    uni005 = run_university_simulation(
        students,
        courses,
        intervention=UniversityPolicyIntervention(capacity_change_pct=-25.0, semester_count=2),
        seed=99,
    )
    assert uni005.final_summary["total_waitlisted_requests"] > base.final_summary["total_waitlisted_requests"]


def test_milestone1_placement_to_milestone2_university_handoff() -> None:
    programs = build_standalone_demo_programs()
    cohort = build_standalone_test_cohort(programs, size=80, seed=11)
    scenario = PlacementScenarioConfig(
        scenario_id="handoff_uni_test",
        name="Handoff Integration Test",
        description="Tests Milestone 1 placement handoff into Milestone 2 post-admission simulation.",
        location=ScenarioLocation(province_code="06", province_name="Ankara"),
        policy=PolicyConfig(
            category="university_placement",
            type="tuition_adjustment",
            parameters=PolicyParameters(increase_percentage=10.0, currency="TL"),
        ),
        university_intervention=UniversityPolicyIntervention(tuition_change_pct=10.0, semester_count=2),
    )

    placement_res = execute_placement_scenario(
        scenario=scenario,
        candidates=cohort,
        programs=programs,
        seed=11,
    )
    handoff = placement_result_to_student_cohort(placement_res, cohort, programs)
    uni_students, uni_courses = student_cohort_from_placement_handoff(handoff, seed=11)

    assert len(uni_students) == handoff["student_count"]
    assert len(uni_students) > 0
    assert all(s.year == 1 and s.state == "active" for s in uni_students)

    uni_res = run_university_simulation(
        uni_students,
        uni_courses,
        ruleset=UniversityRuleset(),
        intervention=scenario.university_intervention,
        scenario_id=scenario.scenario_id,
        semester_count=2,
        seed=11,
    )
    assert uni_res.final_summary["initial_students"] == len(uni_students)
    assert len(uni_res.semester_snapshots) == 3  # term 0, 1, 2
    assert uni_res.manifest.osym_verified is False
    assert uni_res.manifest.coefficients_calibrated is False
