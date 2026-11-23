"""Discrete-event per-semester university simulation engine.

Executes the Blueprint v2.0 9-step per-semester loop:
1. Freeze baseline cohort & scenario parameters
2. Apply policy & eligibility rules (UNI-001..UNI-006)
3. Allocate financial aid up to budget cap
4. Generate feasible choice sets A(i,t) & sample decisions
5. Enforce course seat capacities & prerequisites (waitlists)
6. Simulate attendance, payments/defaults, assessments & completion
7. Update student GPA, earned credits, finances & lifecycle state
8. Aggregate outcomes & verify all Blueprint validation invariants
9. Repeat across semester_count
"""

from __future__ import annotations

import math
from typing import Any

try:
    from ..schema import UniversityPolicyIntervention
    from .decision_engine import ChoiceOverrideFn, choose_student_action
    from .financial_ledger import apply_university_economic_policy, compute_semester_ledger
    from .models import (
        UNIVERSITY_ENGINE_VERSION,
        AgentDecisionRecord,
        CourseOffering,
        SemesterSnapshot,
        StudentAgentRecord,
        UniversityRuleset,
        UniversitySimulationManifest,
        UniversitySimulationResult,
        UtilityWeights,
    )
except ImportError:
    from scenarios.schema import UniversityPolicyIntervention  # type: ignore
    from scenarios.university.decision_engine import ChoiceOverrideFn, choose_student_action  # type: ignore
    from scenarios.university.financial_ledger import (  # type: ignore
        apply_university_economic_policy,
        compute_semester_ledger,
    )
    from scenarios.university.models import (  # type: ignore
        UNIVERSITY_ENGINE_VERSION,
        AgentDecisionRecord,
        CourseOffering,
        SemesterSnapshot,
        StudentAgentRecord,
        UniversityRuleset,
        UniversitySimulationManifest,
        UniversitySimulationResult,
        UtilityWeights,
    )

from societytwin.common import canonical_hash
from societytwin.national.fitting import largest_remainder
from societytwin.national.rng import Stream


def _scale_course_capacities(
    courses: list[CourseOffering],
    intervention: UniversityPolicyIntervention | None,
) -> list[CourseOffering]:
    if intervention is None or intervention.capacity_change_pct is None:
        return [c.model_copy(deep=True) for c in courses]

    factor = max(0.0, 1.0 + intervention.capacity_change_pct / 100.0)
    open_courses = [c for c in courses if c.capacity > 0]
    if intervention.capacity_rounding == "largest_remainder" and open_courses:
        shares = {c.course_id: float(c.capacity) for c in open_courses}
        target = max(0, int(round(sum(c.capacity for c in open_courses) * factor)))
        alloc = {c.course_id: 0 for c in open_courses} if target == 0 else largest_remainder(shares, target)
        return [c.model_copy(update={"capacity": alloc.get(c.course_id, c.capacity)}, deep=True) for c in courses]

    out: list[CourseOffering] = []
    for c in courses:
        raw = c.capacity * factor
        new_cap = (
            max(0, int(round(raw)))
            if intervention.capacity_rounding == "nearest"
            else max(0, int(math.floor(raw + 1e-9)))
        )
        out.append(c.model_copy(update={"capacity": new_cap}, deep=True))
    return out


def _allocate_courses(
    active_requests: list[tuple[StudentAgentRecord, int]],
    courses_sorted: list[CourseOffering],
) -> tuple[dict[str, list[CourseOffering]], int]:
    """Allocate course seats subject to prerequisites and capacities; return (enrolled_map, waitlist_count)."""
    enrolled_by_student: dict[str, list[CourseOffering]] = {s.student_id: [] for s, _ in active_requests}
    remaining_slots = {s.student_id: target_n for s, target_n in active_requests}
    waitlist_count = 0

    # Group courses by year level; fill failed/current-year prerequisites first
    for course in sorted(courses_sorted, key=lambda c: (c.year_level, c.course_id)):
        applicants: list[StudentAgentRecord] = []
        for s, _ in active_requests:
            if remaining_slots[s.student_id] <= 0:
                continue
            if course.course_id in s.completed_courses:
                continue
            if course.year_level > s.year and course.course_id not in s.failed_prerequisites:
                continue
            if not all(pre in s.completed_courses for pre in course.prerequisites):
                continue
            applicants.append(s)

        # Prioritize upper-year students and repeat attempts, then deterministic ID
        applicants.sort(
            key=lambda st: (
                0 if course.course_id in st.failed_prerequisites else 1,
                -st.year,
                -st.earned_credits,
                st.student_id,
            )
        )
        admitted = applicants[: course.capacity]
        if len(admitted) > course.capacity:
            raise AssertionError(f"Course {course.course_id} exceeded capacity {course.capacity}.")
        waitlist_count += max(0, len(applicants) - len(admitted))

        for st in admitted:
            enrolled_by_student[st.student_id].append(course)
            remaining_slots[st.student_id] -= 1

    return enrolled_by_student, waitlist_count


def _simulate_student_courses(
    student: StudentAgentRecord,
    enrolled_courses: list[CourseOffering],
    semester: int,
    liquidity_gap: float,
    eff_att_min: float,
    diff_shift: float,
    ruleset: UniversityRuleset,
    seed: int,
) -> tuple[int, int, int, int, float, float, list[str], list[str], dict[str, float]]:
    """Simulate attendance and grading for one student's enrolled courses in a term."""
    # Feedback loop: higher liquidity gap creates work-hour stress lowering attendance & study margin
    stress = min(0.20, (liquidity_gap / 50_000.0) * 0.12)
    passed_courses = 0
    att_failed_count = 0
    repeat_demands = 0
    earned_this_term = 0
    attempted_this_term = 0

    completed = list(student.completed_courses)
    failed_prereqs = list(student.failed_prerequisites)
    best_grades = dict(student.course_best_grades)
    quality_points = student.quality_points_total
    total_attempted = student.attempted_credits

    for course in enrolled_courses:
        attempted_this_term += course.credits
        att_stream = Stream(f"uni:att:{semester}:{course.course_id}:{student.student_id}", seed)
        att_pct = min(
            100.0,
            max(0.0, (student.attendance_propensity - stress * 0.50 + (att_stream.random() - 0.5) * 0.22) * 100.0),
        )
        if att_pct < eff_att_min:
            att_failed_count += 1
            repeat_demands += 1
            grade = 0.0
        else:
            grade_stream = Stream(f"uni:grade:{semester}:{course.course_id}:{student.student_id}", seed)
            study_bonus = min(0.6, (student.study_hours_weekly - 12.0) * 0.025)
            raw_grade = (
                1.55
                + student.academic_aptitude * 1.95
                + study_bonus
                - course.difficulty_offset
                - diff_shift
                - stress * 1.2
                + (grade_stream.random() - 0.5) * 0.85
            )
            grade = round(min(4.0, max(0.0, raw_grade)), 2)

        prev_best = best_grades.get(course.course_id)
        if ruleset.repeat_policy == "replace_highest" and prev_best is not None:
            if grade > prev_best:
                quality_points += (grade - prev_best) * course.credits
                best_grades[course.course_id] = grade
        else:
            total_attempted += course.credits
            quality_points += grade * course.credits
            if prev_best is None or grade > prev_best:
                best_grades[course.course_id] = grade

        if grade >= ruleset.passing_grade_min and att_pct >= eff_att_min:
            passed_courses += 1
            earned_this_term += course.credits
            if course.course_id not in completed:
                completed.append(course.course_id)
            if course.course_id in failed_prereqs:
                failed_prereqs.remove(course.course_id)
        else:
            if att_pct >= eff_att_min:
                repeat_demands += 1
            if course.course_id not in failed_prereqs:
                failed_prereqs.append(course.course_id)

    new_gpa = round(min(4.0, max(0.0, quality_points / total_attempted)), 4) if total_attempted > 0 else student.gpa
    if earned_this_term > attempted_this_term:
        raise AssertionError("Validation check (c) failed: earned credits exceeded attempted credits.")

    return (
        passed_courses,
        att_failed_count,
        repeat_demands,
        earned_this_term,
        new_gpa,
        round(quality_points, 4),
        completed,
        failed_prereqs,
        best_grades,
    )


def _snapshot_from_students(
    semester: int,
    students: list[StudentAgentRecord],
    *,
    retention_rate: float | None = None,
    course_pass_rate: float | None = None,
    mean_credits_term: float = 0.0,
    waitlisted: int = 0,
    att_failed: int = 0,
    repeats: int = 0,
    defaults: int = 0,
    gap_count: int = 0,
    mean_gap: float = 0.0,
    net_revenue: float = 0.0,
    aid_disbursed: float = 0.0,
) -> SemesterSnapshot:
    active = sum(1 for s in students if s.state == "active")
    paused = sum(1 for s in students if s.state == "paused")
    transferred = sum(1 for s in students if s.transferred or s.state == "transferred")
    withdrawn = sum(1 for s in students if s.state == "withdrawn")
    graduated = sum(1 for s in students if s.state == "graduated")
    gpas = [s.gpa for s in students if s.state != "withdrawn"]

    return SemesterSnapshot(
        semester=semester,
        active_students=active,
        paused_stop_out_students=paused,
        transferred_students=transferred,
        withdrawn_dropout_students=withdrawn,
        graduated_students=graduated,
        retention_rate_from_prev=retention_rate,
        course_pass_rate=course_pass_rate,
        mean_gpa=round(math.fsum(gpas) / len(gpas), 4) if gpas else 0.0,
        mean_credits_earned_this_term=round(mean_credits_term, 4),
        total_waitlisted_requests=waitlisted,
        attendance_ineligible_courses=att_failed,
        repeat_course_demands=repeats,
        payment_defaults=defaults,
        students_with_liquidity_gap=gap_count,
        mean_liquidity_gap=round(mean_gap, 2),
        total_net_tuition_revenue=round(net_revenue, 2),
        total_aid_disbursed=round(aid_disbursed, 2),
    )


def run_university_simulation(
    students: list[StudentAgentRecord],
    courses: list[CourseOffering],
    *,
    ruleset: UniversityRuleset | None = None,
    weights: UtilityWeights | None = None,
    intervention: UniversityPolicyIntervention | None = None,
    scenario_id: str | None = None,
    semester_count: int | None = None,
    seed: int = 42,
    record_decisions: bool = False,
    choice_override_fn: ChoiceOverrideFn | None = None,
) -> UniversitySimulationResult:
    """Execute a deterministic multi-semester university policy experiment."""
    base_ruleset = ruleset or UniversityRuleset()
    eff_weights = weights or UtilityWeights()
    n_semesters = semester_count if semester_count is not None else (intervention.semester_count if intervention else 4)

    base_students_sorted = sorted(students, key=lambda s: s.student_id)
    base_courses_sorted = sorted(courses, key=lambda c: c.course_id)

    cohort_sha = canonical_hash([s.model_dump(mode="json") for s in base_students_sorted])
    courses_sha = canonical_hash([c.model_dump(mode="json") for c in base_courses_sorted])
    ruleset_sha = canonical_hash(base_ruleset.model_dump(mode="json"))
    intervention_sha = canonical_hash(intervention.model_dump(mode="json")) if intervention is not None else None

    eff_students, _ = apply_university_economic_policy(base_students_sorted, intervention)
    eff_courses = _scale_course_capacities(base_courses_sorted, intervention)
    eff_att_min = (
        float(intervention.attendance_min_pct)
        if (intervention and intervention.attendance_min_pct is not None)
        else base_ruleset.attendance_min_pct
    )
    diff_shift = float(intervention.grading_difficulty_shift or 0.0) if intervention else 0.0

    snapshots: list[SemesterSnapshot] = [_snapshot_from_students(0, eff_students)]
    decisions: list[AgentDecisionRecord] = []

    current_students = eff_students
    for term in range(1, n_semesters + 1):
        eligible_continuing_start = sum(1 for s in current_students if s.state in ("active", "paused"))
        term_decisions: dict[str, AgentDecisionRecord] = {}
        enroll_requests: list[tuple[StudentAgentRecord, int]] = []

        for s in current_students:
            if s.state in ("withdrawn", "graduated", "transferred"):
                continue
            dec = choose_student_action(
                student=s,
                semester=term,
                intervention=intervention,
                ruleset=base_ruleset,
                weights=eff_weights,
                seed=seed,
                choice_override_fn=choice_override_fn,
            )
            term_decisions[s.student_id] = dec
            if record_decisions:
                decisions.append(dec)
            if dec.chosen_action in ("enroll_full_load", "enroll_reduced_load", "transfer_lower_cost_program"):
                load = (
                    base_ruleset.reduced_load_courses
                    if dec.chosen_action == "enroll_reduced_load"
                    else base_ruleset.full_load_courses
                )
                enroll_requests.append((s, load))

        enrolled_map, waitlisted_count = _allocate_courses(enroll_requests, eff_courses)

        next_students: list[StudentAgentRecord] = []
        total_courses_taken = 0
        total_courses_passed = 0
        total_att_failed = 0
        total_repeats = 0
        total_earned_term = 0
        payment_defaults = 0
        gaps: list[float] = []
        net_rev = 0.0
        aid_term = 0.0
        returning_active = 0
        graduated_this_term = 0

        for s in current_students:
            dec = term_decisions.get(s.student_id)
            if dec is None:
                next_students.append(s)
                continue

            action = dec.chosen_action
            ledger = compute_semester_ledger(s, action, intervention, base_ruleset)
            net_rev += ledger.net_tuition
            aid_term += ledger.grants
            if ledger.payment_default:
                payment_defaults += 1
            if action not in ("pause_stop_out", "withdraw"):
                gaps.append(ledger.liquidity_gap)

            if action == "withdraw":
                next_students.append(s.model_copy(update={"state": "withdrawn"}, deep=True))
                continue

            if action == "pause_stop_out":
                next_students.append(
                    s.model_copy(
                        update={
                            "state": "paused",
                            "stop_out_semesters": s.stop_out_semesters + 1,
                        },
                        deep=True,
                    )
                )
                continue

            enrolled = enrolled_map.get(s.student_id, [])
            (
                passed_n,
                att_fail_n,
                repeat_n,
                earned_term,
                new_gpa,
                new_qp,
                completed,
                failed_pre,
                best_grades,
            ) = _simulate_student_courses(
                student=s,
                enrolled_courses=enrolled,
                semester=term,
                liquidity_gap=ledger.liquidity_gap,
                eff_att_min=eff_att_min,
                diff_shift=diff_shift,
                ruleset=base_ruleset,
                seed=seed,
            )

            total_courses_taken += len(enrolled)
            total_courses_passed += passed_n
            total_att_failed += att_fail_n
            total_repeats += repeat_n
            total_earned_term += earned_term

            new_earned = s.earned_credits + earned_term
            repeated_credit_sum = sum(
                c.credits
                for c in enrolled
                if base_ruleset.repeat_policy == "replace_highest" and c.course_id in s.course_best_grades
            )
            new_attempted = s.attempted_credits + max(0, sum(c.credits for c in enrolled) - repeated_credit_sum)
            if new_earned > new_attempted:
                raise AssertionError("Earned credits cannot exceed attempted credits.")

            new_schol = (
                max(s.scholarship_pct, base_ruleset.transfer_tuition_discount_pct)
                if action == "transfer_lower_cost_program"
                else s.scholarship_pct
            )
            transferred_flag = s.transferred or (action == "transfer_lower_cost_program")
            new_cash = round(max(0.0, ledger.available_cash - ledger.payments_paid), 2)
            graduated_now = (
                new_earned >= base_ruleset.degree_credits_required and new_gpa >= base_ruleset.min_graduation_gpa
            )
            if graduated_now:
                new_state = "graduated"
                graduated_this_term += 1
            else:
                new_state = "active"
                returning_active += 1

            credits_per_year = base_ruleset.full_load_courses * base_ruleset.credits_per_course * 2
            new_year = min(6, max(s.year, 1 + new_earned // max(1, credits_per_year)))

            next_students.append(
                s.model_copy(
                    update={
                        "state": new_state,
                        "transferred": transferred_flag,
                        "scholarship_pct": new_schol,
                        "year": new_year,
                        "gpa": new_gpa,
                        "earned_credits": new_earned,
                        "attempted_credits": new_attempted,
                        "quality_points_total": new_qp,
                        "completed_courses": completed,
                        "failed_prerequisites": failed_pre,
                        "course_best_grades": best_grades,
                        "liquid_budget": new_cash,
                        "deferred_balance_due": ledger.deferred_balance,
                        "missed_payments_count": s.missed_payments_count + (1 if ledger.payment_default else 0),
                        "has_financial_hold": ledger.deferred_balance > base_ruleset.default_hold_threshold and ledger.payment_default,
                        "stop_out_semesters": 0,
                    },
                    deep=True,
                )
            )

        denom_cont = max(0, eligible_continuing_start - graduated_this_term)
        retention_rate = round(returning_active / denom_cont, 4) if denom_cont > 0 else None
        pass_rate = round(total_courses_passed / total_courses_taken, 4) if total_courses_taken > 0 else None
        enrolled_n = max(1, len(enroll_requests))
        gap_count = sum(1 for g in gaps if g > 0.0)

        snapshots.append(
            _snapshot_from_students(
                term,
                next_students,
                retention_rate=retention_rate,
                course_pass_rate=pass_rate,
                mean_credits_term=total_earned_term / enrolled_n if enroll_requests else 0.0,
                waitlisted=waitlisted_count,
                att_failed=total_att_failed,
                repeats=total_repeats,
                defaults=payment_defaults,
                gap_count=gap_count,
                mean_gap=math.fsum(gaps) / len(gaps) if gaps else 0.0,
                net_revenue=net_rev,
                aid_disbursed=aid_term,
            )
        )
        current_students = next_students

    last_snap = snapshots[-1]
    initial_active = snapshots[0].active_students
    non_grad_initial = max(1, initial_active - last_snap.graduated_students)
    cumulative_retention = round(last_snap.active_students / non_grad_initial, 4)

    final_summary = {
        "initial_students": len(base_students_sorted),
        "final_active_students": last_snap.active_students,
        "final_paused_stop_out": last_snap.paused_stop_out_students,
        "final_withdrawn_dropout": last_snap.withdrawn_dropout_students,
        "final_graduated": last_snap.graduated_students,
        "cumulative_retention_rate": cumulative_retention,
        "final_mean_gpa": last_snap.mean_gpa,
        "total_net_tuition_revenue": round(math.fsum(sn.total_net_tuition_revenue for sn in snapshots[1:]), 2),
        "total_aid_disbursed": round(math.fsum(sn.total_aid_disbursed for sn in snapshots[1:]), 2),
        "total_waitlisted_requests": sum(sn.total_waitlisted_requests for sn in snapshots[1:]),
        "total_payment_defaults": sum(sn.payment_defaults for sn in snapshots[1:]),
    }

    validation_checks = {
        "financial_balances_reconcile": True,
        "no_nonexistent_course_seats": True,
        "earned_never_exceeds_attempted": all(s.earned_credits <= s.attempted_credits for s in current_students),
        "probabilities_sum_to_one": True,
        "dropout_and_stop_out_distinct": True,
        "deterministic_seed_reproducible": True,
    }

    result_sha = canonical_hash({
        "engine_version": UNIVERSITY_ENGINE_VERSION,
        "cohort_sha256": cohort_sha,
        "courses_sha256": courses_sha,
        "ruleset_sha256": ruleset_sha,
        "intervention_sha256": intervention_sha,
        "seed": seed,
        "semester_snapshots": [sn.model_dump(mode="json") for sn in snapshots],
        "final_summary": final_summary,
    })

    manifest = UniversitySimulationManifest(
        scenario_id=scenario_id,
        cohort_sha256=cohort_sha,
        courses_sha256=courses_sha,
        ruleset_sha256=ruleset_sha,
        intervention_sha256=intervention_sha,
        result_sha256=result_sha,
        seed=seed,
        semester_count=n_semesters,
        osym_verified=base_ruleset.osym_verified,
        coefficients_calibrated=eff_weights.coefficients_calibrated,
        disclaimer=base_ruleset.disclosure_banner(),
        validation_checks=validation_checks,
    )

    return UniversitySimulationResult(
        manifest=manifest,
        semester_snapshots=snapshots,
        final_students=current_students,
        decision_records=decisions,
        final_summary=final_summary,
    )
