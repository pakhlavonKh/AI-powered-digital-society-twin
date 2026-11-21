"""Offline CLI entrypoint for multi-semester university policy simulation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from ..adapter import execute_university_scenario
    from ..loader import load_scenario
    from ..schema import UniversityPolicyIntervention
    from .cohort import build_synthetic_university_cohort, student_cohort_from_placement_handoff
    from .experiments import run_replicated_university_experiment, run_tuition_sensitivity_sweep
    from .models import DEFAULT_UNIVERSITY_DISCLAIMER
except ImportError:
    from scenarios.adapter import execute_university_scenario  # type: ignore
    from scenarios.loader import load_scenario  # type: ignore
    from scenarios.schema import UniversityPolicyIntervention  # type: ignore
    from scenarios.university.cohort import (  # type: ignore
        build_synthetic_university_cohort,
        student_cohort_from_placement_handoff,
    )
    from scenarios.university.experiments import (  # type: ignore
        run_replicated_university_experiment,
        run_tuition_sensitivity_sweep,
    )
    from scenarios.university.models import DEFAULT_UNIVERSITY_DISCLAIMER  # type: ignore


def _cmd_demo_uni001(args: argparse.Namespace) -> dict[str, Any]:
    students, courses = build_synthetic_university_cohort(size=args.size, seed=args.seed)
    base_pol = UniversityPolicyIntervention(
        tuition_change_pct=0.0,
        semester_count=args.semesters,
        replications=args.replications,
    )
    arms = {
        f"UNI-001 (+{args.tuition_pct:g}% tuition)": UniversityPolicyIntervention(
            tuition_change_pct=args.tuition_pct,
            semester_count=args.semesters,
            replications=args.replications,
        ),
        f"UNI-001+UNI-002 (+{args.tuition_pct:g}% tuition, +{args.aid_pct:g}% aid)": UniversityPolicyIntervention(
            tuition_change_pct=args.tuition_pct,
            aid_budget_change_pct=args.aid_pct,
            semester_count=args.semesters,
            replications=args.replications,
        ),
        f"UNI-001+UNI-006 (+{args.tuition_pct:g}% tuition, {args.installment_count}x installments)": UniversityPolicyIntervention(
            tuition_change_pct=args.tuition_pct,
            installment_count=args.installment_count,
            semester_count=args.semesters,
            replications=args.replications,
        ),
    }
    reports: dict[str, Any] = {}
    for label, pol in arms.items():
        comp = run_replicated_university_experiment(
            students,
            courses,
            policy_intervention=pol,
            baseline_intervention=base_pol,
            semester_count=args.semesters,
            replications=args.replications,
            base_seed=args.seed,
            baseline_scenario_id="baseline",
            policy_scenario_id=label,
        )
        reports[label] = comp.model_dump(mode="json")
    return {
        "mode": "demo-uni001",
        "size": len(students),
        "semesters": args.semesters,
        "replications": args.replications,
        "osym_verified": False,
        "coefficients_calibrated": False,
        "disclaimer": DEFAULT_UNIVERSITY_DISCLAIMER,
        "comparisons": reports,
    }


def _cmd_sweep(args: argparse.Namespace) -> dict[str, Any]:
    students, courses = build_synthetic_university_cohort(size=args.size, seed=args.seed)
    pcts = tuple(float(x.strip()) for x in args.tuition_pcts.split(",") if x.strip())
    rows = run_tuition_sensitivity_sweep(
        students,
        courses,
        tuition_pcts=pcts,
        aid_budget_pct=args.aid_pct if args.aid_pct != 0.0 else None,
        semester_count=args.semesters,
        replications=args.replications,
        base_seed=args.seed,
    )
    return {
        "mode": "sweep",
        "size": len(students),
        "semesters": args.semesters,
        "replications": args.replications,
        "osym_verified": False,
        "coefficients_calibrated": False,
        "disclaimer": DEFAULT_UNIVERSITY_DISCLAIMER,
        "rows": rows,
    }


def _cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    scenario = load_scenario(Path(args.scenario))
    if args.placement_handoff:
        handoff = json.loads(Path(args.placement_handoff).read_text(encoding="utf-8"))
        students, courses = student_cohort_from_placement_handoff(handoff, seed=args.seed)
    else:
        students, courses = build_synthetic_university_cohort(size=args.size, seed=args.seed)

    output = execute_university_scenario(
        scenario,
        students=students,
        courses=courses,
        semester_count=args.semesters,
        replications=args.replications,
        seed=args.seed,
    )
    return output


def _render_human_text(payload: dict[str, Any]) -> str:
    lines = [
        f"University Policy Simulation CLI ({payload.get('mode', 'run')})",
        f"osym_verified={payload.get('osym_verified', False)} | coefficients_calibrated={payload.get('coefficients_calibrated', False)}",
        payload.get("disclaimer", DEFAULT_UNIVERSITY_DISCLAIMER),
        "",
    ]
    mode = payload.get("mode")
    if mode == "demo-uni001":
        lines.append(
            f"{'Arm':52s} | {'Base Ret':>8s} | {'Pol Ret':>8s} | {'Delta Ret':>9s} | {'Delta Drop':>10s} | {'Delta Rev':>12s}"
        )
        lines.append("-" * 112)
        for label, rep in payload["comparisons"].items():
            eff = rep["policy_effects"]
            ret = eff["cumulative_retention_rate"]
            drp = eff["final_withdrawn_dropout"]
            rev = eff["total_net_tuition_revenue"]
            lines.append(
                f"{label[:52]:52s} | {ret['baseline_mean']:8.4f} | {ret['policy_mean']:8.4f} | "
                f"{ret['mean']:+9.4f} | {drp['mean']:+10.2f} | {rev['mean']:+12.2f}"
            )
    elif mode == "sweep":
        lines.append(
            f"{'Tuition %':>9s} | {'Aid %':>7s} | {'Ret Rate':>8s} | {'Delta vs 0':>10s} | {'Dropout':>8s} | {'Net Revenue':>13s}"
        )
        lines.append("-" * 70)
        for row in payload["rows"]:
            lines.append(
                f"{row['tuition_change_pct']:9.1f} | {row['aid_budget_change_pct']:7.1f} | "
                f"{row['mean_retention_rate']:8.4f} | {row['retention_delta_vs_zero']:+10.4f} | "
                f"{row['mean_withdrawn_dropout']:8.2f} | {row['mean_net_tuition_revenue']:13.2f}"
            )
    else:
        if "summary" in payload and isinstance(payload["summary"], dict):
            lines.append(payload["summary"].get("summary_markdown", json.dumps(payload, indent=2)))
        else:
            lines.append(json.dumps(payload, indent=2, default=str))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scenarios.university",
        description="Offline multi-semester university policy simulator (synthetic / uncalibrated defaults).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo-uni001", help="Run UNI-001 (+tuition) paired CRN counterfactual arms.")
    p_demo.add_argument("--size", type=int, default=200, help="Synthetic cohort size.")
    p_demo.add_argument("--semesters", type=int, default=4, help="Semesters to simulate.")
    p_demo.add_argument("--replications", type=int, default=10, help="CRN replications.")
    p_demo.add_argument("--seed", type=int, default=42, help="Base deterministic seed.")
    p_demo.add_argument("--tuition-pct", type=float, default=20.0, help="Tuition increase %%.")
    p_demo.add_argument("--aid-pct", type=float, default=25.0, help="Targeted aid increase %%.")
    p_demo.add_argument("--installment-count", type=int, default=4, help="Installment count for UNI-006 arm.")
    p_demo.add_argument("--json", action="store_true", help="Emit structured JSON output.")

    p_sweep = sub.add_parser("sweep", help="Sweep tuition sensitivity curve (0%% to 30%%).")
    p_sweep.add_argument("--size", type=int, default=200)
    p_sweep.add_argument("--semesters", type=int, default=4)
    p_sweep.add_argument("--replications", type=int, default=10)
    p_sweep.add_argument("--seed", type=int, default=42)
    p_sweep.add_argument("--tuition-pcts", type=str, default="0,5,10,15,20,25,30")
    p_sweep.add_argument("--aid-pct", type=float, default=0.0)
    p_sweep.add_argument("--json", action="store_true")

    p_run = sub.add_parser("run", help="Execute a university ScenarioConfig YAML/JSON offline.")
    p_run.add_argument("--scenario", required=True, help="Path to ScenarioConfig YAML or JSON.")
    p_run.add_argument("--placement-handoff", default=None, help="Optional Milestone 1 placement handoff JSON.")
    p_run.add_argument("--size", type=int, default=200)
    p_run.add_argument("--semesters", type=int, default=None)
    p_run.add_argument("--replications", type=int, default=None)
    p_run.add_argument("--seed", type=int, default=42)
    p_run.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "demo-uni001":
        payload = _cmd_demo_uni001(args)
    elif args.command == "sweep":
        payload = _cmd_sweep(args)
    elif args.command == "run":
        payload = _cmd_run(args)
    else:
        parser.error(f"Unknown command: {args.command}")
        return 2

    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(_render_human_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
