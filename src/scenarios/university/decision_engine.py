"""Constrained random-utility (softmax logit) student choice engine.

Implements Blueprint v2.0 Section 4 & Section 8:
- Builds strictly feasible choice sets A(i,t) before any decision sampling.
- Evaluates U(i,a,t) = b0(a) + b1*NetCost + b2*ExpectedCredits + b3*ExpectedGPA
  + b4*TimeToDegree + b5*PersonalFactors.
- Enforces probability normalization (sum == 1.0) and deterministic CRN sampling.
"""

from __future__ import annotations

import math
from typing import Any, Callable

try:
    from ..schema import UniversityPolicyIntervention
    from .financial_ledger import compute_semester_ledger
    from .models import (
        AgentDecisionRecord,
        ChoiceAction,
        StudentAgentRecord,
        UniversityRuleset,
        UtilityWeights,
    )
except ImportError:
    from scenarios.schema import UniversityPolicyIntervention  # type: ignore
    from scenarios.university.financial_ledger import compute_semester_ledger  # type: ignore
    from scenarios.university.models import (  # type: ignore
        AgentDecisionRecord,
        ChoiceAction,
        StudentAgentRecord,
        UniversityRuleset,
        UtilityWeights,
    )

from societytwin.common import canonical_hash
from societytwin.national.rng import Stream

ChoiceOverrideFn = Callable[[StudentAgentRecord, int, list[ChoiceAction], dict[str, Any]], ChoiceAction]


def feasible_choices_for_student(
    student: StudentAgentRecord,
    intervention: UniversityPolicyIntervention | None,
    ruleset: UniversityRuleset,
) -> list[ChoiceAction]:
    """Compute the strictly feasible alternative set A(i,t) for student i in semester t."""
    if student.state in ("withdrawn", "graduated"):
        return []

    hard_affordability = (
        intervention is not None and intervention.affordability_filter_mode == "hard_exclude"
    )
    feasible: list[ChoiceAction] = []

    full_ledger = compute_semester_ledger(student, "enroll_full_load", intervention, ruleset)
    if not student.has_financial_hold and not (hard_affordability and full_ledger.liquidity_gap > 0.0):
        feasible.append("enroll_full_load")

    reduced_ledger = compute_semester_ledger(student, "enroll_reduced_load", intervention, ruleset)
    if not (hard_affordability and reduced_ledger.liquidity_gap > 0.0):
        feasible.append("enroll_reduced_load")

    if (
        not student.transferred
        and student.tuition_per_semester > 0.0
        and student.scholarship_pct < ruleset.transfer_tuition_discount_pct
    ):
        transfer_ledger = compute_semester_ledger(student, "transfer_lower_cost_program", intervention, ruleset)
        if not (hard_affordability and transfer_ledger.liquidity_gap > 0.0):
            feasible.append("transfer_lower_cost_program")

    if student.stop_out_semesters < ruleset.max_stop_out_semesters:
        feasible.append("pause_stop_out")

    feasible.append("withdraw")
    return feasible


def _utility_inputs_for_action(
    student: StudentAgentRecord,
    action: ChoiceAction,
    intervention: UniversityPolicyIntervention | None,
    ruleset: UniversityRuleset,
) -> dict[str, float]:
    ledger = compute_semester_ledger(student, action, intervention, ruleset)
    diff_shift = float(intervention.grading_difficulty_shift or 0.0) if intervention else 0.0
    att_min = float(intervention.attendance_min_pct) if (intervention and intervention.attendance_min_pct is not None) else ruleset.attendance_min_pct
    att_buffer = max(0.0, student.attendance_propensity * 100.0 - att_min) / 100.0
    pass_prob_approx = max(0.25, min(0.98, 0.55 + 0.45 * student.academic_aptitude - 0.12 * diff_shift + 0.25 * att_buffer))

    if action == "enroll_full_load":
        exp_credits = ruleset.full_load_courses * ruleset.credits_per_course * pass_prob_approx
        exp_gpa = max(0.0, min(4.0, student.gpa - 0.30 * diff_shift))
        personal = student.preference_for_staying
    elif action == "enroll_reduced_load":
        exp_credits = ruleset.reduced_load_courses * ruleset.credits_per_course * pass_prob_approx
        exp_gpa = max(0.0, min(4.0, student.gpa + 0.10 - 0.25 * diff_shift))
        personal = student.preference_for_staying * 0.85
    elif action == "transfer_lower_cost_program":
        exp_credits = ruleset.full_load_courses * ruleset.credits_per_course * pass_prob_approx * 0.90
        exp_gpa = max(0.0, min(4.0, student.gpa - 0.05 - 0.25 * diff_shift))
        personal = student.preference_for_staying * 0.75 + (1.0 - student.risk_tolerance) * 0.2
    elif action == "pause_stop_out":
        exp_credits = 0.0
        exp_gpa = student.gpa
        personal = (1.0 - student.preference_for_staying) * 0.6
    else:  # withdraw
        exp_credits = 0.0
        exp_gpa = 0.0
        personal = 1.0 - student.preference_for_staying

    remaining_credits = max(0.0, float(ruleset.degree_credits_required - student.earned_credits))
    if action in ("enroll_full_load", "enroll_reduced_load", "transfer_lower_cost_program"):
        rem_terms = remaining_credits / max(6.0, exp_credits)
    elif action == "pause_stop_out":
        rem_terms = (remaining_credits / max(12.0, float(ruleset.full_load_courses * ruleset.credits_per_course) * 0.75)) + 1.5
    else:
        rem_terms = 12.0

    # Monetary pressure combines net tuition and acute upfront liquidity gap
    net_cost_scaled = (ledger.net_tuition + 1.5 * ledger.liquidity_gap) / 10_000.0

    return {
        "net_cost": round(net_cost_scaled, 4),
        "expected_credits": round(exp_credits, 4),
        "expected_gpa": round(exp_gpa, 4),
        "time_to_degree": round(rem_terms, 4),
        "personal_factors": round(personal, 4),
        "net_tuition_tl": ledger.net_tuition,
        "liquidity_gap_tl": ledger.liquidity_gap,
    }


def choose_student_action(
    student: StudentAgentRecord,
    semester: int,
    intervention: UniversityPolicyIntervention | None,
    ruleset: UniversityRuleset,
    weights: UtilityWeights,
    seed: int,
    choice_override_fn: ChoiceOverrideFn | None = None,
) -> AgentDecisionRecord:
    """Compute utilities U(i,a,t), normalize softmax probabilities, and draw a feasible action."""
    feasible = feasible_choices_for_student(student, intervention, ruleset)
    if not feasible:
        raise ValueError(f"Student '{student.student_id}' has no feasible actions in state '{student.state}'.")

    utility_inputs: dict[str, Any] = {}
    utilities: dict[ChoiceAction, float] = {}
    for action in feasible:
        inp = _utility_inputs_for_action(student, action, intervention, ruleset)
        utility_inputs[action] = inp
        u = (
            weights.beta_intercepts.get(action, 0.0)
            + weights.beta_net_cost * inp["net_cost"]
            + weights.beta_expected_credits * inp["expected_credits"]
            + weights.beta_expected_gpa * inp["expected_gpa"]
            + weights.beta_time_to_degree * inp["time_to_degree"]
            + weights.beta_personal * inp["personal_factors"]
        )
        utilities[action] = u

    max_u = max(utilities.values())
    exps = {a: math.exp(utilities[a] - max_u) for a in feasible}
    denom = math.fsum(exps.values())
    probs: dict[str, float] = {a: exps[a] / denom for a in feasible}

    prob_sum = math.fsum(probs.values())
    if abs(prob_sum - 1.0) > 1e-7:
        raise AssertionError(f"Softmax probabilities failed sum==1 check: {prob_sum}")

    if choice_override_fn is not None:
        chosen = choice_override_fn(student, semester, feasible, utility_inputs)
        if chosen not in feasible:
            raise ValueError(
                f"External choice '{chosen}' is not in permitted feasible_choices={feasible} "
                f"for student '{student.student_id}'."
            )
    else:
        stream = Stream(f"uni:choice:{semester}:{student.student_id}", seed)
        draw = stream.random()
        acc = 0.0
        chosen = feasible[-1]
        for action in feasible:
            acc += probs[action]
            if draw < acc:
                chosen = action
                break

    trace_id = "trc-" + canonical_hash({
        "agent_id": student.student_id,
        "semester": semester,
        "feasible": feasible,
        "chosen": chosen,
        "seed": seed,
    })[:12]

    return AgentDecisionRecord(
        agent_id=student.student_id,
        semester=semester,
        feasible_choices=feasible,
        chosen_action=chosen,
        utility_inputs=utility_inputs,
        probabilities={k: round(v, 6) for k, v in probs.items()},
        seed=seed,
        trace_id=trace_id,
    )
