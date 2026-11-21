"""Additional edge-case tests for Milestone 2 multi-semester dynamics and CLI run."""

from __future__ import annotations

import json
from pathlib import Path

from scenarios.schema import UniversityPolicyIntervention
from scenarios.university.cli import main as uni_cli_main
from scenarios.university.cohort import build_demo_course_catalog
from scenarios.university.models import StudentAgentRecord, UniversityRuleset
from scenarios.university.semester_engine import run_university_simulation


def test_stop_out_reentry_and_max_stop_out_cap() -> None:
    courses = build_demo_course_catalog(base_capacity=50)
    student = StudentAgentRecord(
        student_id="STU_STOPOUT",
        program_id="PRG_TEST",
        tuition_per_semester=20_000.0,
        liquid_budget=40_000.0,
        semester_earnings=10_000.0,
        gpa=3.0,
    )
    rules = UniversityRuleset(max_stop_out_semesters=2)

    def scripted_override(st, sem, feasible, _u):
        if sem in (1, 2):
            assert "pause_stop_out" in feasible
            return "pause_stop_out"
        # After 2 paused semesters, pause_stop_out must be forbidden in A(i, 3)
        assert "pause_stop_out" not in feasible
        return "enroll_full_load"

    res = run_university_simulation(
        [student],
        courses,
        ruleset=rules,
        semester_count=3,
        seed=42,
        record_decisions=True,
        choice_override_fn=scripted_override,
    )
    assert res.semester_snapshots[1].paused_stop_out_students == 1
    assert res.semester_snapshots[2].paused_stop_out_students == 1
    # Re-entered active in term 3
    assert res.semester_snapshots[3].active_students == 1
    assert res.final_students[0].stop_out_semesters == 0
    assert res.final_students[0].state == "active"


def test_financial_hold_across_terms_and_repeat_grading_policies() -> None:
    courses = build_demo_course_catalog(base_capacity=50)
    broke_student = StudentAgentRecord(
        student_id="STU_HOLD",
        program_id="PRG_TEST",
        tuition_per_semester=50_000.0,
        need_aid_grant=0.0,
        liquid_budget=2_000.0,
        semester_earnings=1_000.0,
        gpa=2.5,
    )
    rules_hold = UniversityRuleset(default_hold_threshold=5_000.0)

    seen_term2_feasible: list[str] = []

    def override_hold(_st, sem, feasible, _u):
        if sem == 1:
            return "enroll_full_load"
        seen_term2_feasible.extend(feasible)
        return "enroll_reduced_load"

    res = run_university_simulation(
        [broke_student],
        courses,
        ruleset=rules_hold,
        semester_count=2,
        seed=42,
        record_decisions=True,
        choice_override_fn=override_hold,
    )
    assert res.semester_snapshots[1].payment_defaults == 1
    # Financial hold incurred after term 1 must exclude enroll_full_load in term 2
    assert "enroll_full_load" not in seen_term2_feasible

    # Repeat policy check: average_all vs replace_highest both maintain valid GPA & earned <= attempted
    res_replace = run_university_simulation(
        [broke_student.model_copy(update={"liquid_budget": 500_000.0})],
        courses,
        ruleset=UniversityRuleset(repeat_policy="replace_highest"),
        intervention=UniversityPolicyIntervention(grading_difficulty_shift=1.5),
        semester_count=2,
        seed=42,
    )
    res_avg = run_university_simulation(
        [broke_student.model_copy(update={"liquid_budget": 500_000.0})],
        courses,
        ruleset=UniversityRuleset(repeat_policy="average_all"),
        intervention=UniversityPolicyIntervention(grading_difficulty_shift=1.5),
        semester_count=2,
        seed=42,
    )
    for st in res_replace.final_students + res_avg.final_students:
        assert 0.0 <= st.gpa <= 4.0
        assert st.earned_credits <= st.attempted_credits


def test_university_cli_run_builtin_yaml() -> None:
    scenario_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "scenarios"
        / "builtin_scenarios"
        / "uni_tuition_hike_001.yaml"
    )
    # Smoke test via direct argparse-friendly invocation (captured by checking return code + valid run)
    rc = uni_cli_main(["run", "--scenario", str(scenario_path), "--size", "40", "--semesters", "2", "--replications", "2", "--json"])
    assert rc == 0
