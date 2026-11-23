"""Offline command-line interface for the deterministic university placement simulator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    from ..loader import load_scenario
    from ..schema import PlacementScenarioConfig, ScenarioConfig
    from ..summary import summarize_placement_comparison, summarize_placement_result
    from .cohort_synth import (
        build_standalone_demo_programs,
        build_standalone_test_cohort,
        build_tuik_anchored_candidates,
        load_candidates_file,
        load_programs_file,
        load_ruleset_file,
    )
    from .comparison import compare_placement_scenarios
    from .engine import run_placement
    from .models import PlacementRuleset
except ImportError:
    from scenarios.loader import load_scenario  # type: ignore
    from scenarios.schema import PlacementScenarioConfig, ScenarioConfig  # type: ignore
    from scenarios.summary import summarize_placement_comparison, summarize_placement_result  # type: ignore
    from scenarios.placement.cohort_synth import (  # type: ignore
        build_standalone_demo_programs,
        build_standalone_test_cohort,
        build_tuik_anchored_candidates,
        load_candidates_file,
        load_programs_file,
        load_ruleset_file,
    )
    from scenarios.placement.comparison import compare_placement_scenarios  # type: ignore
    from scenarios.placement.engine import run_placement  # type: ignore
    from scenarios.placement.models import PlacementRuleset  # type: ignore

from societytwin.national.store import PopulationStore


def _load_any_scenario(path: str | Path) -> ScenarioConfig | PlacementScenarioConfig:
    target = Path(path).resolve()
    text = target.read_text(encoding="utf-8")
    raw = json.loads(text) if target.suffix.lower() == ".json" else yaml.safe_load(text)
    if isinstance(raw, dict) and raw.get("simulation_mode") == "university_placement" and "university_intervention" in raw:
        return PlacementScenarioConfig.model_validate(raw)
    return load_scenario(target)


def _resolve_inputs(args: argparse.Namespace) -> tuple[list[Any], list[Any], PlacementRuleset]:
    programs = load_programs_file(args.programs) if getattr(args, "programs", None) else build_standalone_demo_programs()
    ruleset = load_ruleset_file(args.ruleset) if getattr(args, "ruleset", None) else PlacementRuleset()

    if getattr(args, "candidates", None):
        cohort = load_candidates_file(args.candidates)
    elif getattr(args, "population_id", None):
        pop_dir = Path(args.populations_dir) if getattr(args, "populations_dir", None) else Path("data/populations")
        loaded = PopulationStore(pop_dir).load(args.population_id)
        cohort = build_tuik_anchored_candidates(
            loaded,
            programs=programs,
            sample_size=getattr(args, "sample_size", 120),
            seed=getattr(args, "seed", 42),
        )
    else:
        cohort = build_standalone_test_cohort(
            programs=programs,
            size=getattr(args, "sample_size", 120),
            seed=getattr(args, "seed", 42),
        )
    return cohort.candidates, programs, ruleset


def _write_outputs(out_dir: str | None, files: dict[str, str]) -> None:
    if not out_dir:
        return
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")


def _cmd_run(args: argparse.Namespace) -> int:
    scenario = _load_any_scenario(args.scenario) if args.scenario else None
    candidates, programs, ruleset = _resolve_inputs(args)
    result = run_placement(
        candidates=candidates,
        programs=programs,
        ruleset=ruleset,
        scenario=scenario,
        seed=args.seed,
    )
    summary = summarize_placement_result(result)
    result_json = json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False)
    _write_outputs(args.out, {"placement_result.json": result_json + "\n", "summary.md": summary["summary_markdown"] + "\n"})

    print(summary["headline"])
    print(f"Disclaimer: {result.manifest.disclaimer}")
    print(f"Result SHA-256: {result.manifest.result_sha256}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    baseline_sc = _load_any_scenario(args.baseline) if args.baseline else None
    policy_sc = _load_any_scenario(args.policy)
    candidates, programs, ruleset = _resolve_inputs(args)

    base_res = run_placement(candidates=candidates, programs=programs, ruleset=ruleset, scenario=baseline_sc, seed=args.seed)
    pol_res = run_placement(candidates=candidates, programs=programs, ruleset=ruleset, scenario=policy_sc, seed=args.seed)
    report = compare_placement_scenarios(base_res, pol_res)
    summary = summarize_placement_comparison(report)

    report_json = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False)
    _write_outputs(
        args.out,
        {
            "baseline_result.json": json.dumps(base_res.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            "policy_result.json": json.dumps(pol_res.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            "comparison_report.json": report_json + "\n",
            "comparison_summary.md": summary["summary_markdown"] + "\n",
        },
    )

    print(summary["headline"])
    print(f"Disclaimer: {report.disclaimer}")
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from ..schema import UniversityPolicyIntervention

    programs = build_standalone_demo_programs()
    cohort = build_standalone_test_cohort(programs=programs, size=args.sample_size, seed=args.seed)
    ruleset = PlacementRuleset()

    base_res = run_placement(cohort.candidates, programs, ruleset=ruleset, seed=args.seed)
    pol_res = run_placement(
        cohort.candidates,
        programs,
        ruleset=ruleset,
        intervention=UniversityPolicyIntervention(
            tuition_change_pct=20.0,
            capacity_change_pct=-15.0,
            affordability_filter_mode="hard_exclude",
        ),
        seed=args.seed,
    )
    report = compare_placement_scenarios(base_res, pol_res)
    summary = summarize_placement_comparison(report)
    print(summary["summary_markdown"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scenarios.placement",
        description="Offline deterministic university placement simulator (hypothetical rules unless verified_osym).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--candidates", help="Path to JSON/YAML CandidateCohort or CandidateRecord list")
    common.add_argument("--programs", help="Path to JSON/YAML ProgramOffering list")
    common.add_argument("--ruleset", help="Path to JSON/YAML PlacementRuleset")
    common.add_argument("--population-id", help="Saved national population ID for TÜİK-anchored cohort sampling")
    common.add_argument("--populations-dir", default="data/populations", help="Directory containing saved populations")
    common.add_argument("--sample-size", type=int, default=120, help="Number of synthetic candidates to sample")
    common.add_argument("--seed", type=int, default=42, help="Deterministic seed")
    common.add_argument("--out", help="Optional output directory to save JSON and Markdown artifacts")

    p_run = sub.add_parser("run", parents=[common], help="Run a single offline placement simulation")
    p_run.add_argument("--scenario", help="Path to scenario YAML/JSON file")
    p_run.set_defaults(func=_cmd_run)

    p_cmp = sub.add_parser("compare", parents=[common], help="Compare baseline vs policy scenario")
    p_cmp.add_argument("--baseline", help="Optional baseline scenario YAML/JSON (defaults to zero-intervention baseline)")
    p_cmp.add_argument("--policy", required=True, help="Policy scenario YAML/JSON")
    p_cmp.set_defaults(func=_cmd_compare)

    p_demo = sub.add_parser("demo", help="Run self-contained offline demonstration")
    p_demo.add_argument("--sample-size", type=int, default=120)
    p_demo.add_argument("--seed", type=int, default=42)
    p_demo.set_defaults(func=_cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
