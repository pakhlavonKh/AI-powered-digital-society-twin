"""Common Random Numbers (CRN) counterfactual experiment runner and sensitivity sweeps."""

from __future__ import annotations

import math
from typing import Any

try:
    from ..schema import UniversityPolicyIntervention
    from .models import (
        CourseOffering,
        StudentAgentRecord,
        UniversityComparisonReport,
        UniversityRuleset,
        UniversitySimulationResult,
        UtilityWeights,
    )
    from .semester_engine import run_university_simulation
except ImportError:
    from scenarios.schema import UniversityPolicyIntervention  # type: ignore
    from scenarios.university.models import (  # type: ignore
        CourseOffering,
        StudentAgentRecord,
        UniversityComparisonReport,
        UniversityRuleset,
        UniversitySimulationResult,
        UtilityWeights,
    )
    from scenarios.university.semester_engine import run_university_simulation  # type: ignore


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = min(len(sorted_vals) - 1, lo + 1)
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _summarize_paired_metric(
    baseline_vals: list[float],
    policy_vals: list[float],
) -> dict[str, float]:
    n = len(baseline_vals)
    deltas = [p - b for b, p in zip(baseline_vals, policy_vals)]
    mean_delta = math.fsum(deltas) / n
    if n > 1:
        var = math.fsum((d - mean_delta) ** 2 for d in deltas) / (n - 1)
        std_delta = math.sqrt(var)
    else:
        std_delta = 0.0
    sorted_deltas = sorted(deltas)
    return {
        "baseline_mean": round(math.fsum(baseline_vals) / n, 4),
        "policy_mean": round(math.fsum(policy_vals) / n, 4),
        "mean": round(mean_delta, 4),
        "std": round(std_delta, 4),
        "min": round(sorted_deltas[0], 4),
        "p05": round(_percentile(sorted_deltas, 0.05), 4),
        "p50": round(_percentile(sorted_deltas, 0.50), 4),
        "p95": round(_percentile(sorted_deltas, 0.95), 4),
        "max": round(sorted_deltas[-1], 4),
    }


def _aggregate_trajectories(runs: list[UniversitySimulationResult]) -> list[dict[str, float | int]]:
    if not runs:
        return []
    term_count = len(runs[0].semester_snapshots)
    n = len(runs)
    trajectory: list[dict[str, float | int]] = []
    for idx in range(term_count):
        snaps = [r.semester_snapshots[idx] for r in runs]
        actives = sorted(float(s.active_students) for s in snaps)
        ret_vals = [float(s.retention_rate_from_prev) for s in snaps if s.retention_rate_from_prev is not None]
        trajectory.append({
            "semester": snaps[0].semester,
            "mean_active_students": round(math.fsum(actives) / n, 2),
            "p05_active_students": round(_percentile(actives, 0.05), 2),
            "p95_active_students": round(_percentile(actives, 0.95), 2),
            "mean_paused_stop_out": round(math.fsum(s.paused_stop_out_students for s in snaps) / n, 2),
            "mean_transferred": round(math.fsum(s.transferred_students for s in snaps) / n, 2),
            "mean_withdrawn_dropout": round(math.fsum(s.withdrawn_dropout_students for s in snaps) / n, 2),
            "mean_graduated": round(math.fsum(s.graduated_students for s in snaps) / n, 2),
            "mean_retention_rate": round(math.fsum(ret_vals) / len(ret_vals), 4) if ret_vals else 1.0,
            "mean_gpa": round(math.fsum(s.mean_gpa for s in snaps) / n, 4),
            "mean_waitlisted": round(math.fsum(s.total_waitlisted_requests for s in snaps) / n, 2),
            "mean_net_tuition_revenue": round(math.fsum(s.total_net_tuition_revenue for s in snaps) / n, 2),
            "mean_aid_disbursed": round(math.fsum(s.total_aid_disbursed for s in snaps) / n, 2),
        })
    return trajectory


_PAIRED_SUMMARY_KEYS: tuple[str, ...] = (
    "cumulative_retention_rate",
    "final_active_students",
    "final_paused_stop_out",
    "final_withdrawn_dropout",
    "final_graduated",
    "final_mean_gpa",
    "total_net_tuition_revenue",
    "total_aid_disbursed",
    "total_waitlisted_requests",
    "total_payment_defaults",
)


def run_replicated_university_experiment(
    students: list[StudentAgentRecord],
    courses: list[CourseOffering],
    policy_intervention: UniversityPolicyIntervention,
    *,
    baseline_intervention: UniversityPolicyIntervention | None = None,
    ruleset: UniversityRuleset | None = None,
    weights: UtilityWeights | None = None,
    semester_count: int | None = None,
    replications: int = 100,
    base_seed: int = 42,
    baseline_scenario_id: str | None = "baseline",
    policy_scenario_id: str | None = "policy",
    program_university_map: dict[str, str] | None = None,
) -> UniversityComparisonReport:
    """Run paired Common Random Numbers (CRN) baseline vs policy replications."""
    if replications < 1:
        raise ValueError("replications must be at least 1.")

    eff_terms = semester_count or policy_intervention.semester_count
    baseline_runs: list[UniversitySimulationResult] = []
    policy_runs: list[UniversitySimulationResult] = []

    for r in range(replications):
        rep_seed = base_seed + r
        base_res = run_university_simulation(
            students,
            courses,
            ruleset=ruleset,
            weights=weights,
            intervention=baseline_intervention,
            scenario_id=baseline_scenario_id,
            semester_count=eff_terms,
            seed=rep_seed,
            record_decisions=False,
            program_university_map=program_university_map,
        )
        pol_res = run_university_simulation(
            students,
            courses,
            ruleset=ruleset,
            weights=weights,
            intervention=policy_intervention,
            scenario_id=policy_scenario_id,
            semester_count=eff_terms,
            seed=rep_seed,
            record_decisions=False,
            program_university_map=program_university_map,
        )
        baseline_runs.append(base_res)
        policy_runs.append(pol_res)

    policy_effects: dict[str, dict[str, float]] = {}
    for key in _PAIRED_SUMMARY_KEYS:
        b_vals = [float(run.final_summary[key]) for run in baseline_runs]
        p_vals = [float(run.final_summary[key]) for run in policy_runs]
        policy_effects[key] = _summarize_paired_metric(b_vals, p_vals)

    ref_manifest = policy_runs[0].manifest
    return UniversityComparisonReport(
        baseline_scenario_id=baseline_scenario_id,
        policy_scenario_id=policy_scenario_id,
        replications=replications,
        cohort_sha256=ref_manifest.cohort_sha256,
        osym_verified=ref_manifest.osym_verified,
        coefficients_calibrated=ref_manifest.coefficients_calibrated,
        disclaimer=ref_manifest.disclaimer,
        policy_effects=policy_effects,
        baseline_trajectory=_aggregate_trajectories(baseline_runs),
        policy_trajectory=_aggregate_trajectories(policy_runs),
    )


def run_tuition_sensitivity_sweep(
    students: list[StudentAgentRecord],
    courses: list[CourseOffering],
    *,
    tuition_pcts: tuple[float, ...] = (0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0),
    aid_budget_pct: float | None = None,
    semester_count: int = 4,
    replications: int = 10,
    base_seed: int = 42,
    ruleset: UniversityRuleset | None = None,
    weights: UtilityWeights | None = None,
) -> list[dict[str, Any]]:
    """Sweep tuition changes (paired by CRN against 0% baseline) with optional aid offset."""
    if not tuition_pcts:
        return []

    rows: list[dict[str, Any]] = []
    for pct in tuition_pcts:
        pol = UniversityPolicyIntervention(
            tuition_change_pct=pct,
            aid_budget_change_pct=aid_budget_pct,
            semester_count=semester_count,
            replications=replications,
        )
        comp = run_replicated_university_experiment(
            students,
            courses,
            policy_intervention=pol,
            baseline_intervention=UniversityPolicyIntervention(
                tuition_change_pct=0.0,
                semester_count=semester_count,
                replications=replications,
            ),
            ruleset=ruleset,
            weights=weights,
            semester_count=semester_count,
            replications=replications,
            base_seed=base_seed,
            baseline_scenario_id="sweep_base_0pct",
            policy_scenario_id=f"sweep_tuition_{pct:g}pct",
        )
        ret = comp.policy_effects["cumulative_retention_rate"]
        drop = comp.policy_effects["final_withdrawn_dropout"]
        pause = comp.policy_effects["final_paused_stop_out"]
        rev = comp.policy_effects["total_net_tuition_revenue"]
        aid = comp.policy_effects["total_aid_disbursed"]
        rows.append({
            "tuition_change_pct": float(pct),
            "aid_budget_change_pct": float(aid_budget_pct) if aid_budget_pct is not None else 0.0,
            "mean_retention_rate": ret["policy_mean"],
            "retention_delta_vs_zero": ret["mean"],
            "retention_delta_p05": ret["p05"],
            "retention_delta_p95": ret["p95"],
            "mean_withdrawn_dropout": drop["policy_mean"],
            "withdrawn_delta_vs_zero": drop["mean"],
            "mean_paused_stop_out": pause["policy_mean"],
            "mean_net_tuition_revenue": rev["policy_mean"],
            "mean_aid_disbursed": aid["policy_mean"],
            "osym_verified": comp.osym_verified,
            "coefficients_calibrated": comp.coefficients_calibrated,
        })
    return rows
