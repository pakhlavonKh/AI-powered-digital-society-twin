"""Tests for Milestone 2 financial ledger reconciliation and constrained logit choice engine."""

from __future__ import annotations

import math

import pytest

from scenarios.schema import UniversityPolicyIntervention
from scenarios.university.decision_engine import choose_student_action, feasible_choices_for_student
from scenarios.university.financial_ledger import (
    apply_university_economic_policy,
    compute_semester_ledger,
)
from scenarios.university.models import StudentAgentRecord, UniversityRuleset, UtilityWeights


def _make_student(
    student_id: str = "STU_001",
    *,
    tuition: float = 55_000.0,
    scholarship_pct: float = 0.0,
    need_aid_grant: float = 5_000.0,
    income_band: str = "low",
    liquid_budget: float = 15_000.0,
    semester_earnings: float = 8_000.0,
    has_financial_hold: bool = False,
    stop_out_semesters: int = 0,
    transferred: bool = False,
) -> StudentAgentRecord:
    return StudentAgentRecord(
        student_id=student_id,
        program_id="PRG_TEST",
        tuition_per_semester=tuition,
        scholarship_pct=scholarship_pct,
        need_aid_grant=need_aid_grant,
        income_band=income_band,  # type: ignore[arg-type]
        liquid_budget=liquid_budget,
        semester_earnings=semester_earnings,
        has_financial_hold=has_financial_hold,
        stop_out_semesters=stop_out_semesters,
        transferred=transferred,
    )


def test_financial_ledger_reconciliation_and_installment_relief() -> None:
    rules = UniversityRuleset()
    student = _make_student(tuition=60_000.0, scholarship_pct=25.0, need_aid_grant=5_000.0, liquid_budget=18_000.0, semester_earnings=6_000.0)

    lump_ledger = compute_semester_ledger(student, "enroll_full_load", None, rules)
    # 60,000 - 15,000 (25% discount) - 5,000 grant = 40,000 net tuition
    assert lump_ledger.published_tuition == 60_000.0
    assert lump_ledger.discounts == 15_000.0
    assert lump_ledger.grants == 5_000.0
    assert lump_ledger.net_tuition == 40_000.0
    assert lump_ledger.available_cash == 24_000.0
    assert lump_ledger.liquidity_gap == 16_000.0
    assert lump_ledger.payments_paid + lump_ledger.deferred_balance == pytest.approx(lump_ledger.net_tuition, abs=1e-2)

    # UNI-006 installment relief (4 installments -> 25% upfront = 10,000 TL due <= 24,000 available -> 0 gap)
    uni006 = UniversityPolicyIntervention(installment_count=4)
    inst_ledger = compute_semester_ledger(student, "enroll_full_load", uni006, rules)
    assert inst_ledger.payments_due == pytest.approx(10_000.0, abs=1e-2)
    assert inst_ledger.liquidity_gap == 0.0
    assert inst_ledger.payment_default is False
    assert inst_ledger.payments_paid + inst_ledger.deferred_balance == pytest.approx(inst_ledger.net_tuition, abs=1e-2)


def test_targeted_aid_pool_allocates_to_lowest_income_first_within_cap() -> None:
    students = [
        _make_student("STU_HIGH", income_band="high", liquid_budget=120_000.0, need_aid_grant=0.0),
        _make_student("STU_MID", income_band="middle", liquid_budget=45_000.0, need_aid_grant=4_000.0),
        _make_student("STU_LOW", income_band="low", liquid_budget=10_000.0, need_aid_grant=6_000.0),
    ]
    intervention = UniversityPolicyIntervention(base_aid_budget=25_000.0, aid_budget_change_pct=25.0, max_grant_per_student=18_000.0)
    updated, meta = apply_university_economic_policy(students, intervention)

    by_id = {s.student_id: s for s in updated}
    # 25,000 * 1.25 = 31,250 TL pool; high income excluded; low gets capped 18,000 first, middle gets remainder 13,250
    assert meta["aid_pool"] == pytest.approx(31_250.0, abs=1e-2)
    assert meta["aid_allocated"] <= meta["aid_pool"] + 1e-2
    assert by_id["STU_LOW"].need_aid_grant == pytest.approx(18_000.0, abs=1e-2)
    assert by_id["STU_MID"].need_aid_grant == pytest.approx(13_250.0, abs=1e-2)
    assert by_id["STU_HIGH"].need_aid_grant == 0.0


def test_feasible_choice_set_filtering_and_external_override_validation() -> None:
    rules = UniversityRuleset(max_stop_out_semesters=2)
    weights = UtilityWeights()

    # Financial hold excludes enroll_full_load; stop_out_semesters == max_stop_out_semesters excludes pause_stop_out
    constrained = _make_student(
        has_financial_hold=True,
        stop_out_semesters=2,
        transferred=False,
        scholarship_pct=0.0,
    )
    feasible = feasible_choices_for_student(constrained, None, rules)
    assert "enroll_full_load" not in feasible
    assert "pause_stop_out" not in feasible
    assert "enroll_reduced_load" in feasible
    assert "transfer_lower_cost_program" in feasible
    assert "withdraw" in feasible

    # Hard affordability excludes options leaving liquidity_gap > 0
    hard_mode = UniversityPolicyIntervention(affordability_filter_mode="hard_exclude")
    broke = _make_student(tuition=80_000.0, need_aid_grant=0.0, liquid_budget=1_000.0, semester_earnings=1_000.0)
    feasible_hard = feasible_choices_for_student(broke, hard_mode, rules)
    assert "enroll_full_load" not in feasible_hard
    assert "enroll_reduced_load" not in feasible_hard
    assert "withdraw" in feasible_hard

    # External decision hook must be rejected if it returns an infeasible action
    with pytest.raises(ValueError, match="not in permitted feasible_choices"):
        choose_student_action(
            student=constrained,
            semester=1,
            intervention=None,
            ruleset=rules,
            weights=weights,
            seed=42,
            choice_override_fn=lambda _s, _t, _feas, _u: "enroll_full_load",
        )


def test_softmax_probabilities_sum_to_one_and_deterministic_seed() -> None:
    rules = UniversityRuleset()
    weights = UtilityWeights()
    assert weights.coefficients_calibrated is False
    student = _make_student()

    dec1 = choose_student_action(student, semester=1, intervention=None, ruleset=rules, weights=weights, seed=101)
    dec2 = choose_student_action(student, semester=1, intervention=None, ruleset=rules, weights=weights, seed=101)

    assert math.fsum(dec1.probabilities.values()) == pytest.approx(1.0, abs=1e-4)
    assert dec1.chosen_action in dec1.feasible_choices
    assert dec1.chosen_action == dec2.chosen_action
    assert dec1.trace_id == dec2.trace_id
    assert dec1.probabilities == dec2.probabilities
