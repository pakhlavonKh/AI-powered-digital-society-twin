"""Synthetic university student cohort builders and Milestone 1 placement handoff.

Supports both:
1. Consuming Milestone 1's placement_result_to_student_cohort(...) handoff output.
2. Generating a multi-year (Years 1-4) synthetic cohort matching the Blueprint v2.0
   demonstration layout (e.g., 1,000 students) with explicit Evidence.ASSUMED tags.
"""

from __future__ import annotations

from typing import Any

try:
    from .models import CourseOffering, StudentAgentRecord
except ImportError:
    from scenarios.university.models import CourseOffering, StudentAgentRecord  # type: ignore

from societytwin.national.rng import Stream
from societytwin.national.vocab import Evidence


def build_demo_course_catalog(base_capacity: int = 240) -> list[CourseOffering]:
    """Create a 4-year structured course catalog with prerequisite dependencies."""
    courses: list[CourseOffering] = []
    # 5 core courses per academic year -> 20 courses total (120 credits)
    for year in range(1, 5):
        for slot in range(1, 6):
            cid = f"CRS_Y{year}_{slot:02d}"
            prereqs = [f"CRS_Y{year - 1}_{slot:02d}"] if year > 1 and slot <= 3 else []
            courses.append(
                CourseOffering(
                    course_id=cid,
                    title=f"Year {year} Core Course {slot}",
                    credits=6,
                    year_level=year,
                    capacity=base_capacity,
                    prerequisites=prereqs,
                    difficulty_offset=0.10 * (year - 1),
                )
            )
    return courses


def _assumed_behavioral_profile(stream: Stream, income_band: str, aptitude_hint: float | None = None) -> dict[str, Any]:
    aptitude = aptitude_hint if aptitude_hint is not None else round(0.45 + stream.random() * 0.50, 4)
    study_hours = round(8.0 + aptitude * 16.0 + stream.random() * 6.0, 2)
    att_prop = round(min(0.98, max(0.55, 0.72 + aptitude * 0.16 + (stream.random() - 0.5) * 0.16)), 4)
    risk_tol = round(0.25 + stream.random() * 0.55, 4)
    pref_stay = round(min(0.96, max(0.45, 0.68 + aptitude * 0.18 + (stream.random() - 0.5) * 0.14)), 4)
    earnings = round(4_000.0 + (12_000.0 if income_band == "low" else 7_500.0 if income_band == "middle" else 2_500.0) * stream.random(), 2)
    return {
        "academic_aptitude": aptitude,
        "study_hours_weekly": study_hours,
        "attendance_propensity": att_prop,
        "risk_tolerance": risk_tol,
        "preference_for_staying": pref_stay,
        "semester_earnings": earnings,
    }


def student_cohort_from_placement_handoff(
    handoff: dict[str, Any],
    *,
    seed: int = 42,
    course_capacity: int | None = None,
) -> tuple[list[StudentAgentRecord], list[CourseOffering]]:
    """Convert Milestone 1's placement_result_to_student_cohort payload into Year-1 StudentAgentRecords."""
    students_raw = handoff.get("students", [])
    stream = Stream("university:handoff_cohort", seed)
    cap = course_capacity if course_capacity is not None else max(20, int(len(students_raw) * 0.95) + 5)
    courses = build_demo_course_catalog(base_capacity=cap)

    students: list[StudentAgentRecord] = []
    for row in sorted(students_raw, key=lambda r: str(r["student_id"])):
        fin = row.get("financials") or {}
        gross_annual = float(fin.get("gross_tuition") or 0.0)
        published_annual = float(fin.get("published_tuition") or 0.0)
        schol_pct = round(((gross_annual - published_annual) / gross_annual) * 100.0, 2) if gross_annual > 0 else 0.0
        sem_tuition = round(gross_annual / 2.0, 2)
        sem_grant = round(float(fin.get("need_aid_grant") or 0.0) / 2.0, 2)
        income_band = row.get("income_band") or "middle"
        liquid_budget = float(row.get("liquid_budget") if row.get("liquid_budget") is not None else 45_000.0)
        score = row.get("admission_score")
        apt_hint = round(min(0.95, max(0.35, (float(score) - 200.0) / 350.0)), 4) if score is not None else None
        beh = _assumed_behavioral_profile(stream, income_band, aptitude_hint=apt_hint)

        prov_map = {
            "program_id": "milestone1_placement_handoff",
            "tuition_per_semester": "milestone1_placement_handoff",
            "study_hours_weekly": Evidence.ASSUMED,
            "attendance_propensity": Evidence.ASSUMED,
            "preference_for_staying": Evidence.ASSUMED,
            "academic_aptitude": Evidence.ASSUMED,
        }

        students.append(
            StudentAgentRecord(
                student_id=str(row["student_id"]),
                source_synthetic_id=row.get("source_synthetic_id"),
                program_id=str(row["program_id"]),
                province_code=row.get("province_code"),
                year=1,
                gpa=2.60,
                earned_credits=0,
                attempted_credits=0,
                quality_points_total=0.0,
                completed_courses=[],
                tuition_per_semester=sem_tuition,
                scholarship_pct=schol_pct,
                need_aid_grant=sem_grant,
                income_band=income_band,
                liquid_budget=liquid_budget,
                state="active",
                field_provenance=prov_map,
                **beh,
            )
        )
    return students, courses


def build_synthetic_university_cohort(
    size: int = 1000,
    seed: int = 42,
    years: tuple[int, ...] = (1, 2, 3, 4),
    base_semester_tuition: float = 55_000.0,
) -> tuple[list[StudentAgentRecord], list[CourseOffering]]:
    """Generate a multi-year synthetic university cohort matching Blueprint v2.0 defaults."""
    stream = Stream("university:synthetic_cohort", seed)
    # Tight enough per-year capacity that -15% course seats (UNI-005) creates realistic waitlists
    per_year_share = max(1, int(round(size / len(years))))
    courses = build_demo_course_catalog(base_capacity=max(10, int(round(per_year_share * 0.96))))
    courses_by_year = {y: [c for c in courses if c.year_level == y] for y in range(1, 5)}

    students: list[StudentAgentRecord] = []
    for idx in range(1, size + 1):
        yr = years[(idx - 1) % len(years)]
        income_roll = stream.random()
        if income_roll < 0.35:
            income_band = "low"
            liquid_budget = round(14_000.0 + stream.random() * 26_000.0, 2)
            grant = round(12_000.0 + stream.random() * 10_000.0, 2)
        elif income_roll < 0.78:
            income_band = "middle"
            liquid_budget = round(42_000.0 + stream.random() * 48_000.0, 2)
            grant = round(3_000.0 + stream.random() * 5_000.0, 2)
        else:
            income_band = "high"
            liquid_budget = round(110_000.0 + stream.random() * 140_000.0, 2)
            grant = 0.0

        schol_roll = stream.random()
        scholarship_pct = 100.0 if schol_roll < 0.15 else (50.0 if schol_roll < 0.40 else 0.0)

        completed: list[str] = []
        best_grades: dict[str, float] = {}
        earned = 0
        q_points = 0.0
        beh = _assumed_behavioral_profile(stream, income_band)
        base_gpa = round(min(3.95, max(1.85, 2.0 + beh["academic_aptitude"] * 1.65)), 3)

        for prev_y in range(1, yr):
            for c in courses_by_year[prev_y]:
                completed.append(c.course_id)
                best_grades[c.course_id] = base_gpa
                earned += c.credits
                q_points += base_gpa * c.credits

        students.append(
            StudentAgentRecord(
                student_id=f"STU_{idx:05d}",
                program_id="PRG_UNI_DEMO",
                province_code="06",
                year=yr,
                gpa=base_gpa,
                earned_credits=earned,
                attempted_credits=earned,
                quality_points_total=round(q_points, 4),
                completed_courses=completed,
                course_best_grades=best_grades,
                tuition_per_semester=base_semester_tuition,
                scholarship_pct=scholarship_pct,
                need_aid_grant=grant,
                income_band=income_band,
                liquid_budget=liquid_budget,
                state="active",
                field_provenance={"all_synthetic_attributes": Evidence.ASSUMED},
                **beh,
            )
        )

    return students, courses
