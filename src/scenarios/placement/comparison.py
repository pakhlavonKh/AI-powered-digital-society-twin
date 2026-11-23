"""Paired counterfactual scenario comparison and CRN quantile aggregation."""

from __future__ import annotations

import math
from typing import Any

try:
    from .models import (
        CandidatePlacementOutcome,
        PlacementComparisonReport,
        PlacementResult,
        ProgramDelta,
        TransitionBreakdown,
    )
except ImportError:
    from scenarios.placement.models import (  # type: ignore
        CandidatePlacementOutcome,
        PlacementComparisonReport,
        PlacementResult,
        ProgramDelta,
        TransitionBreakdown,
    )


class ComparisonMismatchError(ValueError):
    """Raised when comparing placement runs executed on different candidate cohorts."""


_NUMERIC_COMPARE_KEYS: tuple[str, ...] = (
    "eligible_candidates",
    "excluded_candidates",
    "cannot_evaluate_candidates",
    "placed_count",
    "unplaced_count",
    "placement_rate",
    "eligible_placement_rate",
    "first_choice_count",
    "first_choice_rate",
    "top_3_choice_count",
    "top_3_choice_rate",
    "mean_assigned_rank",
    "total_capacity",
    "total_filled",
    "seat_utilization_rate",
    "total_gross_tuition",
    "total_scholarship_discounts",
    "total_need_aid_disbursed",
    "total_net_tuition_revenue",
    "mean_net_tuition",
    "students_with_liquidity_gap",
    "mean_liquidity_gap",
    "tie_break_count",
)


def _classify_transition(
    base: CandidatePlacementOutcome,
    policy: CandidatePlacementOutcome,
) -> str:
    if base.eligibility_status != policy.eligibility_status:
        return "eligibility_changed"
    if base.placement_status != "placed" and policy.placement_status == "placed":
        return "newly_placed"
    if base.placement_status == "placed" and policy.placement_status != "placed":
        return "displaced_to_unplaced"
    if base.placement_status != "placed" and policy.placement_status != "placed":
        return "remained_unplaced"
    if base.assigned_program_id == policy.assigned_program_id:
        return "same_program"
    base_rank = base.assigned_preference_rank or 10**6
    pol_rank = policy.assigned_preference_rank or 10**6
    return "improved_preference" if pol_rank < base_rank else "worsened_preference"


def compare_placement_scenarios(
    baseline: PlacementResult,
    policy: PlacementResult,
    *,
    sample_limit: int = 10,
) -> PlacementComparisonReport:
    """Compute exact counterfactual deltas and candidate migration matrix between two runs."""
    if baseline.manifest.candidates_sha256 != policy.manifest.candidates_sha256:
        raise ComparisonMismatchError(
            "Cannot compare placement runs with different candidate cohorts: "
            f"baseline={baseline.manifest.candidates_sha256}, policy={policy.manifest.candidates_sha256}."
        )

    base_cands = {o.candidate_id: o for o in baseline.candidate_outcomes}
    pol_cands = {o.candidate_id: o for o in policy.candidate_outcomes}
    if set(base_cands) != set(pol_cands):
        raise ComparisonMismatchError("Candidate IDs differ between baseline and policy results.")

    counts: dict[str, int] = {
        "same_program": 0,
        "improved_preference": 0,
        "worsened_preference": 0,
        "newly_placed": 0,
        "displaced_to_unplaced": 0,
        "remained_unplaced": 0,
        "eligibility_changed": 0,
    }
    samples: dict[str, list[str]] = {k: [] for k in counts}

    for cid in sorted(base_cands):
        bucket = _classify_transition(base_cands[cid], pol_cands[cid])
        counts[bucket] += 1
        if len(samples[bucket]) < sample_limit:
            samples[bucket].append(cid)

    total = len(base_cands)
    if sum(counts.values()) != total:
        raise AssertionError("Transition matrix counts do not sum to total_candidates.")

    transitions = TransitionBreakdown(
        total_candidates=total,
        same_program=counts["same_program"],
        improved_preference=counts["improved_preference"],
        worsened_preference=counts["worsened_preference"],
        newly_placed=counts["newly_placed"],
        displaced_to_unplaced=counts["displaced_to_unplaced"],
        remained_unplaced=counts["remained_unplaced"],
        eligibility_changed=counts["eligibility_changed"],
        sample_candidate_ids={k: v for k, v in samples.items() if v},
    )

    metric_deltas: dict[str, dict[str, float | int | None]] = {}
    for key in _NUMERIC_COMPARE_KEYS:
        b_val = baseline.aggregate_metrics.get(key)
        p_val = policy.aggregate_metrics.get(key)
        if b_val is None or p_val is None:
            delta = None
        elif isinstance(b_val, int) and isinstance(p_val, int):
            delta = p_val - b_val
        else:
            delta = round(float(p_val) - float(b_val), 4)
        metric_deltas[key] = {"baseline": b_val, "policy": p_val, "delta": delta}

    base_progs = {p.program_id: p for p in baseline.program_outcomes}
    pol_progs = {p.program_id: p for p in policy.program_outcomes}
    program_deltas: list[ProgramDelta] = []
    for pid in sorted(set(base_progs) | set(pol_progs)):
        bp = base_progs.get(pid)
        pp = pol_progs.get(pid)
        b_cap = bp.effective_capacity if bp else 0
        p_cap = pp.effective_capacity if pp else 0
        b_fill = bp.filled if bp else 0
        p_fill = pp.filled if pp else 0
        b_cut = bp.cutoff_score if bp else None
        p_cut = pp.cutoff_score if pp else None
        cut_delta = round(p_cut - b_cut, 5) if (b_cut is not None and p_cut is not None) else None
        b_fc = bp.first_choice_count if bp else 0
        p_fc = pp.first_choice_count if pp else 0
        program_deltas.append(
            ProgramDelta(
                program_id=pid,
                baseline_capacity=b_cap,
                policy_capacity=p_cap,
                capacity_delta=p_cap - b_cap,
                baseline_filled=b_fill,
                policy_filled=p_fill,
                filled_delta=p_fill - b_fill,
                baseline_cutoff_score=b_cut,
                policy_cutoff_score=p_cut,
                cutoff_score_delta=cut_delta,
                first_choice_delta=p_fc - b_fc,
            )
        )

    osym_verified = baseline.manifest.osym_verified and policy.manifest.osym_verified
    rule_fidelity = (
        policy.manifest.rule_fidelity
        if policy.manifest.rule_fidelity == baseline.manifest.rule_fidelity
        else "hypothetical_simplified"
    )
    disclaimer = policy.manifest.disclaimer if not policy.manifest.osym_verified else baseline.manifest.disclaimer

    return PlacementComparisonReport(
        baseline_result_sha256=baseline.manifest.result_sha256,
        policy_result_sha256=policy.manifest.result_sha256,
        candidates_sha256=baseline.manifest.candidates_sha256,
        baseline_scenario_id=baseline.manifest.scenario_id,
        policy_scenario_id=policy.manifest.scenario_id,
        osym_verified=osym_verified,
        rule_fidelity=rule_fidelity,
        disclaimer=disclaimer,
        metric_deltas=metric_deltas,
        transitions=transitions,
        program_deltas=program_deltas,
    )


def _linear_quantile(sorted_vals: list[float], q: float) -> float:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def aggregate_replicated_comparisons(
    comparisons: list[PlacementComparisonReport],
) -> dict[str, Any]:
    """Summarize paired Common Random Numbers (CRN) replications with mean, std, and quantiles."""
    if not comparisons:
        raise ValueError("At least one paired PlacementComparisonReport is required.")

    n = len(comparisons)
    metric_summary: dict[str, dict[str, float]] = {}

    for key in _NUMERIC_COMPARE_KEYS:
        deltas = [
            float(c.metric_deltas[key]["delta"])
            for c in comparisons
            if c.metric_deltas.get(key) and c.metric_deltas[key]["delta"] is not None
        ]
        if not deltas:
            continue
        sorted_d = sorted(deltas)
        mean = math.fsum(deltas) / len(deltas)
        var = math.fsum((d - mean) ** 2 for d in deltas) / (len(deltas) - 1) if len(deltas) > 1 else 0.0
        metric_summary[key] = {
            "mean_delta": round(mean, 4),
            "std_delta": round(math.sqrt(var), 4),
            "p05_delta": round(_linear_quantile(sorted_d, 0.05), 4),
            "p50_delta": round(_linear_quantile(sorted_d, 0.50), 4),
            "p95_delta": round(_linear_quantile(sorted_d, 0.95), 4),
        }

    return {
        "replications": n,
        "osym_verified": all(c.osym_verified for c in comparisons),
        "disclaimer": comparisons[0].disclaimer,
        "metric_delta_distributions": metric_summary,
    }
