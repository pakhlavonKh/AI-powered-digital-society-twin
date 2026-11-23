"""Deterministic financial ledger and aid budget allocation for university policy simulations.

Enforces exact Blueprint v2.0 accounting identities:
  NetTuition = PublishedTuition - Grants - Discounts
  LiquidityGap = max(0, PaymentsDue - AvailableCash)
  PaymentsPaid + DeferredBalance == NetTuition
"""

from __future__ import annotations

import math
from typing import Any

try:
    from ..schema import UniversityPolicyIntervention
    from .models import ChoiceAction, SemesterFinancialLedger, StudentAgentRecord, UniversityRuleset
except ImportError:
    from scenarios.schema import UniversityPolicyIntervention  # type: ignore
    from scenarios.university.models import (  # type: ignore
        ChoiceAction,
        SemesterFinancialLedger,
        StudentAgentRecord,
        UniversityRuleset,
    )


def apply_university_economic_policy(
    students: list[StudentAgentRecord],
    intervention: UniversityPolicyIntervention | None = None,
) -> tuple[list[StudentAgentRecord], dict[str, Any]]:
    """Return deep-copied students with tuition and aid-budget interventions applied."""
    if intervention is None:
        return [s.model_copy(deep=True) for s in students], {"aid_pool": 0.0, "aid_allocated": 0.0}

    tuition_factor = (
        max(0.0, 1.0 + intervention.tuition_change_pct / 100.0)
        if intervention.tuition_change_pct is not None
        else 1.0
    )

    existing_aid = math.fsum(s.need_aid_grant for s in students)
    aid_pct = intervention.aid_budget_change_pct
    base_aid = intervention.base_aid_budget

    if aid_pct is None and base_aid is None:
        grants = {s.student_id: s.need_aid_grant for s in students}
        pool = existing_aid
    else:
        pool = (
            max(0.0, base_aid * (1.0 + (aid_pct or 0.0) / 100.0))
            if base_aid is not None
            else max(0.0, existing_aid * (1.0 + (aid_pct or 0.0) / 100.0))
        )
        income_rank = {"low": 0, "middle": 1, "high": 2}
        eligible = [
            s
            for s in students
            if (
                intervention.aid_income_eligibility_max is not None
                and s.liquid_budget <= intervention.aid_income_eligibility_max
            )
            or (intervention.aid_income_eligibility_max is None and s.income_band != "high")
        ]
        ordered = sorted(
            eligible,
            key=lambda s: (income_rank.get(s.income_band, 2), s.liquid_budget, s.student_id),
        )
        grants = {s.student_id: 0.0 for s in students}
        remaining = pool
        if ordered and remaining > 0.0:
            eligible_existing = math.fsum(max(0.0, s.need_aid_grant) for s in ordered)
            if eligible_existing > 0.0 and intervention.max_grant_per_student is None:
                scale = pool / eligible_existing
                for s in ordered:
                    base_g = max(0.0, s.need_aid_grant)
                    award = min(remaining, round(base_g * scale, 2))
                    grants[s.student_id] = award
                    remaining = round(max(0.0, remaining - award), 2)
                    if remaining <= 0.0:
                        break
            else:
                cap = intervention.max_grant_per_student or round(pool / len(ordered), 2)
                for s in ordered:
                    award = min(remaining, cap)
                    grants[s.student_id] = round(award, 2)
                    remaining = round(max(0.0, remaining - award), 2)
                    if remaining <= 0.0:
                        break

    out: list[StudentAgentRecord] = []
    for s in students:
        new_tuition = s.tuition_per_semester
        if s.program_id in intervention.tuition_overrides:
            new_tuition = round(float(intervention.tuition_overrides[s.program_id]) / 2.0, 2)
        elif intervention.tuition_change_pct is not None and new_tuition > 0.0:
            new_tuition = round(new_tuition * tuition_factor, 2)

        out.append(
            s.model_copy(
                update={
                    "tuition_per_semester": new_tuition,
                    "need_aid_grant": grants[s.student_id],
                },
                deep=True,
            )
        )

    return out, {
        "aid_pool": round(pool, 2),
        "aid_allocated": round(math.fsum(grants.values()), 2),
    }


def compute_semester_ledger(
    student: StudentAgentRecord,
    action: ChoiceAction,
    intervention: UniversityPolicyIntervention | None,
    ruleset: UniversityRuleset,
) -> SemesterFinancialLedger:
    """Compute and reconcile a student's financial ledger for a chosen semester action."""
    if action in ("pause_stop_out", "withdraw"):
        published = 0.0
        discounts = 0.0
        grants = 0.0
    else:
        load_mult = (
            float(ruleset.reduced_load_courses) / float(ruleset.full_load_courses)
            if action == "enroll_reduced_load"
            else 1.0
        )
        published = round(student.tuition_per_semester * load_mult, 2)
        eff_schol = student.scholarship_pct
        if action == "transfer_lower_cost_program" or student.transferred:
            eff_schol = max(eff_schol, ruleset.transfer_tuition_discount_pct)
        discounts = round(published * (eff_schol / 100.0), 2)
        after_discount = round(max(0.0, published - discounts), 2)
        grants = round(min(after_discount, student.need_aid_grant), 2)

    net_tuition = round(max(0.0, published - discounts - grants), 2)
    upfront_share = 1.0
    if intervention is not None:
        if intervention.installment_upfront_share is not None:
            upfront_share = float(intervention.installment_upfront_share)
        elif intervention.installment_count is not None and intervention.installment_count > 1:
            upfront_share = 1.0 / float(intervention.installment_count)

    prior_due = round(student.deferred_balance_due, 2)
    payments_due = round(net_tuition * upfront_share + prior_due, 2)
    available_cash = round(max(0.0, student.liquid_budget + student.semester_earnings), 2)
    liquidity_gap = round(max(0.0, payments_due - available_cash), 2)

    total_obligation = round(net_tuition + prior_due, 2)
    payments_paid = round(min(available_cash, total_obligation), 2)
    deferred_balance = round(max(0.0, total_obligation - payments_paid), 2)
    payment_default = liquidity_gap > 0.0

    # Conservation / reconciliation guard
    if abs((published - discounts - grants) - net_tuition) > 0.02:
        raise AssertionError("NetTuition reconciliation mismatch.")
    if abs((payments_paid + deferred_balance) - total_obligation) > 0.02:
        raise AssertionError("Payment balance reconciliation mismatch.")

    return SemesterFinancialLedger(
        published_tuition=published,
        grants=grants,
        discounts=discounts,
        net_tuition=net_tuition,
        payments_due=payments_due,
        available_cash=available_cash,
        liquidity_gap=liquidity_gap,
        payments_paid=payments_paid,
        deferred_balance=deferred_balance,
        payment_default=payment_default,
    )
