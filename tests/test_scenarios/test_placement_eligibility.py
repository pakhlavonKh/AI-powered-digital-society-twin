"""Unit tests for candidate-level and per-choice placement eligibility gates."""

from __future__ import annotations

from scenarios.eligibility import EligibilityStatus
from scenarios.placement.eligibility import evaluate_candidate_and_choices
from scenarios.placement.models import (
    CandidateRecord,
    PlacementRuleset,
    ProgramConditions,
    ProgramOffering,
)
from scenarios.schema import UniversityPolicyIntervention


def _sample_programs() -> dict[str, ProgramOffering]:
    progs = [
        ProgramOffering(
            program_id="MED_01",
            university_id="U1",
            university_name="Uni 1",
            province_code="06",
            department_name="Medicine",
            score_type="SAY",
            baraj_group="medicine",
            capacity=5,
        ),
        ProgramOffering(
            program_id="LAW_01",
            university_id="U1",
            university_name="Uni 1",
            province_code="06",
            department_name="Law",
            score_type="EA",
            baraj_group="law",
            capacity=5,
        ),
        ProgramOffering(
            program_id="CLOSED_01",
            university_id="U1",
            university_name="Uni 1",
            province_code="06",
            department_name="Closed Prog",
            score_type="SAY",
            capacity=5,
            status="closed",
        ),
        ProgramOffering(
            program_id="ZERO_CAP",
            university_id="U1",
            university_name="Uni 1",
            province_code="06",
            department_name="Zero Cap",
            score_type="SAY",
            capacity=0,
        ),
        ProgramOffering(
            program_id="PAID_CS",
            university_id="U2",
            university_name="Uni 2",
            university_type="foundation",
            province_code="06",
            department_name="CS Paid",
            score_type="SAY",
            capacity=10,
            tuition_annual=200_000.0,
            scholarship_pct=0.0,
            min_score=300.0,
            special_conditions=ProgramConditions(required_sex="female", max_age=25),
        ),
    ]
    return {p.program_id: p for p in progs}


def test_missing_diploma_returns_cannot_evaluate():
    progs = _sample_programs()
    cand = CandidateRecord(
        candidate_id="C_MISS",
        diploma_eligible=None,
        scores={"SAY": 420.0},
        preferences=["MED_01"],
    )
    audit = evaluate_candidate_and_choices(cand, progs, PlacementRuleset())
    assert audit.status == EligibilityStatus.CANNOT_EVALUATE
    assert "diploma_eligible" in audit.missing_attributes


def test_ineligible_diploma_excludes_candidate():
    progs = _sample_programs()
    cand = CandidateRecord(
        candidate_id="C_NODIP",
        diploma_eligible=False,
        scores={"SAY": 420.0},
        preferences=["MED_01"],
    )
    audit = evaluate_candidate_and_choices(cand, progs, PlacementRuleset())
    assert audit.status == EligibilityStatus.EXCLUDED
    assert "DIPLOMA_INELIGIBLE" in audit.exclusion_reasons


def test_choice_level_diagnostics_for_unavailable_and_ineligible_options():
    progs = _sample_programs()
    ruleset = PlacementRuleset(max_preferences=8)
    cand = CandidateRecord(
        candidate_id="C_AUDIT",
        diploma_eligible=True,
        sex="male",
        age=20,
        scores={"SAY": 290.0},  # below PAID_CS min_score=300, no EA score
        ranks={"SAY": 60_000},  # fails medicine baraj=50,000
        preferences=[
            "NO_SUCH_PROG",  # UNKNOWN_PROGRAM
            "CLOSED_01",     # PROGRAM_CLOSED
            "ZERO_CAP",      # ZERO_CAPACITY
            "LAW_01",        # SCORE_TYPE_MISMATCH
            "MED_01",        # RANK_THRESHOLD_NOT_MET
            "MED_01",        # DUPLICATE_CHOICE
            "PAID_CS",       # BELOW_MIN_SCORE (290 < 300)
        ],
    )
    audit = evaluate_candidate_and_choices(cand, progs, ruleset)
    assert audit.status == EligibilityStatus.ELIGIBLE
    assert audit.eligible_choices == []
    codes = [ev.reason_code for ev in audit.preference_evaluations]
    assert codes == [
        "UNKNOWN_PROGRAM",
        "PROGRAM_CLOSED",
        "ZERO_CAPACITY",
        "SCORE_TYPE_MISMATCH",
        "RANK_THRESHOLD_NOT_MET",
        "DUPLICATE_CHOICE",
        "BELOW_MIN_SCORE",
    ]


def test_special_conditions_and_affordability_exclusion_vs_installments():
    progs = _sample_programs()
    ruleset = PlacementRuleset()
    cand = CandidateRecord(
        candidate_id="C_ECON",
        diploma_eligible=True,
        sex="female",
        age=20,
        scores={"SAY": 410.0},
        ranks={"SAY": 30_000},
        liquid_budget=60_000.0,
        preferences=["PAID_CS"],
    )

    # Full upfront payment (200,000 > 60,000) -> excluded under hard_exclude
    audit_excluded = evaluate_candidate_and_choices(
        cand,
        progs,
        ruleset,
        intervention=UniversityPolicyIntervention(affordability_filter_mode="hard_exclude"),
    )
    assert audit_excluded.eligible_choices == []
    assert audit_excluded.preference_evaluations[0].reason_code == "AFFORDABILITY_EXCLUDED"

    # 4-installment plan (200,000 / 4 = 50,000 <= 60,000) -> now affordable!
    audit_installment = evaluate_candidate_and_choices(
        cand,
        progs,
        ruleset,
        intervention=UniversityPolicyIntervention(
            installment_count=4,
            affordability_filter_mode="hard_exclude",
        ),
    )
    assert len(audit_installment.eligible_choices) == 1
    assert audit_installment.eligible_choices[0].financials.payments_due_upfront == 50_000.0
    assert audit_installment.eligible_choices[0].financials.liquidity_gap == 0.0

    # Wrong sex fails special condition cleanly
    male_cand = cand.model_copy(update={"sex": "male", "liquid_budget": 300_000.0})
    audit_sex = evaluate_candidate_and_choices(male_cand, progs, ruleset)
    assert audit_sex.preference_evaluations[0].reason_code == "SPECIAL_CONDITION_NOT_MET"


def test_preference_truncation_and_strict_cap():
    progs = _sample_programs()
    cand = CandidateRecord(
        candidate_id="C_PREF",
        diploma_eligible=True,
        scores={"SAY": 450.0},
        ranks={"SAY": 10_000},
        preferences=["MED_01", "CLOSED_01", "ZERO_CAP"],
    )
    audit_trunc = evaluate_candidate_and_choices(cand, progs, PlacementRuleset(max_preferences=2, strict_preference_cap=False))
    assert audit_trunc.status == EligibilityStatus.ELIGIBLE
    assert audit_trunc.preference_evaluations[-1].reason_code == "PREFERENCE_TRUNCATED"

    audit_strict = evaluate_candidate_and_choices(cand, progs, PlacementRuleset(max_preferences=2, strict_preference_cap=True))
    assert audit_strict.status == EligibilityStatus.EXCLUDED
    assert "PREFERENCE_CAP_EXCEEDED" in audit_strict.exclusion_reasons
