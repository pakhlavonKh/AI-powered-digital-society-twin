"""Tests for CRN experiments, tuition sweeps, Scenario Engine adapters, summaries, and CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scenarios import (
    compile_scenario_from_prompt,
    execute_university_scenario,
    get_scenario,
    summarize_university_result,
)
from scenarios.schema import UniversityPolicyIntervention
from scenarios.university.cli import main as uni_cli_main
from scenarios.university.cohort import build_synthetic_university_cohort
from scenarios.university.experiments import (
    run_replicated_university_experiment,
    run_tuition_sensitivity_sweep,
)
from scenarios.university.semester_engine import run_university_simulation


def test_crn_paired_replications_and_sensitivity_sweep() -> None:
    students, courses = build_synthetic_university_cohort(size=100, seed=42)
    policy = UniversityPolicyIntervention(tuition_change_pct=20.0, semester_count=3, replications=5)
    base = UniversityPolicyIntervention(tuition_change_pct=0.0, semester_count=3, replications=5)

    report = run_replicated_university_experiment(
        students,
        courses,
        policy_intervention=policy,
        baseline_intervention=base,
        semester_count=3,
        replications=5,
        base_seed=42,
    )

    assert report.replications == 5
    assert report.osym_verified is False
    assert report.coefficients_calibrated is False
    ret = report.policy_effects["cumulative_retention_rate"]
    assert ret["p05"] <= ret["p50"] <= ret["p95"]
    assert len(report.baseline_trajectory) == 4
    assert len(report.policy_trajectory) == 4

    sweep = run_tuition_sensitivity_sweep(
        students,
        courses,
        tuition_pcts=(0.0, 15.0, 30.0),
        semester_count=3,
        replications=4,
        base_seed=42,
    )
    assert len(sweep) == 3
    assert sweep[0]["tuition_change_pct"] == 0.0
    assert sweep[0]["retention_delta_vs_zero"] == 0.0
    assert sweep[-1]["mean_retention_rate"] <= sweep[0]["mean_retention_rate"]


def test_scenario_compiler_adapter_hybrid_and_summaries() -> None:
    compiled = compile_scenario_from_prompt(
        "Simulate a 20% university tuition increase in Izmir with a 4 installment plan",
        force_heuristic=True,
    )
    assert compiled.effective_simulation_mode == "university_decision_hybrid"

    out = execute_university_scenario(compiled, semester_count=2, replications=3, seed=42)
    assert out["mode"] == "university_decision_hybrid"
    assert out["osym_verified"] is False
    assert out["coefficients_calibrated"] is False
    assert out["comparison"] is not None
    assert "policy_effects" in out["comparison"]
    assert out["summary"]["generated_by"] == "deterministic"
    assert "CRN counterfactual" in out["summary"]["headline"]

    # Built-in Milestone 1/2 scenario YAML also runs directly via execute_university_scenario
    builtin_sc = get_scenario("uni_tuition_hike_001")
    builtin_out = execute_university_scenario(builtin_sc, semester_count=2, replications=2, seed=42)
    assert builtin_out["scenario_id"] == "uni_tuition_hike_001"
    assert builtin_out["comparison"] is not None

    # Also test single-run summary formatter directly
    students, courses = build_synthetic_university_cohort(size=60, seed=7)
    single = run_university_simulation(students, courses, semester_count=2, seed=7)
    summary = summarize_university_result(single)
    assert summary["osym_verified"] is False
    assert summary["coefficients_calibrated"] is False
    assert "Semester Trajectory" in summary["summary_markdown"]


def test_university_cli_demo_and_sweep(capsys) -> None:
    rc_demo = uni_cli_main(["demo-uni001", "--size", "60", "--semesters", "2", "--replications", "3", "--json"])
    assert rc_demo == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["mode"] == "demo-uni001"
    assert payload["coefficients_calibrated"] is False
    assert len(payload["comparisons"]) == 3

    rc_sweep = uni_cli_main(
        ["sweep", "--size", "60", "--semesters", "2", "--replications", "3", "--tuition-pcts", "0,20", "--json"]
    )
    assert rc_sweep == 0
    sweep_out = json.loads(capsys.readouterr().out)
    assert sweep_out["mode"] == "sweep"
    assert len(sweep_out["rows"]) == 2


def test_university_module_subprocess_entrypoint() -> None:
    root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-m", "scenarios.university", "demo-uni001", "--size", "40", "--semesters", "2", "--replications", "2"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "coefficients_calibrated=False" in proc.stdout
    assert "UNI-001" in proc.stdout
