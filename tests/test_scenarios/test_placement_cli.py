"""End-to-end offline CLI tests for python -m scenarios.placement."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scenarios.placement.cli import main as cli_main


def test_cli_run_and_compare_end_to_end(tmp_path):
    scenario_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "scenarios"
        / "builtin_scenarios"
        / "uni_placement_quota_001.yaml"
    )
    out_run = tmp_path / "run_out"
    exit_code = cli_main([
        "run",
        "--scenario",
        str(scenario_path),
        "--sample-size",
        "50",
        "--seed",
        "42",
        "--out",
        str(out_run),
    ])
    assert exit_code == 0
    result_data = json.loads((out_run / "placement_result.json").read_text(encoding="utf-8"))
    assert result_data["manifest"]["osym_verified"] is False
    assert result_data["manifest"]["invariants_passed"] is True
    assert (out_run / "summary.md").is_file()

    out_cmp = tmp_path / "cmp_out"
    exit_cmp = cli_main([
        "compare",
        "--policy",
        str(scenario_path),
        "--sample-size",
        "50",
        "--seed",
        "42",
        "--out",
        str(out_cmp),
    ])
    assert exit_cmp == 0
    cmp_data = json.loads((out_cmp / "comparison_report.json").read_text(encoding="utf-8"))
    assert cmp_data["transitions"]["total_candidates"] == 50
    assert (out_cmp / "comparison_summary.md").is_file()


def test_cli_module_invocation_demo():
    proc = subprocess.run(
        [sys.executable, "-m", "scenarios.placement", "demo", "--sample-size", "40", "--seed", "7"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "SIMPLIFIED / HYPOTHETICAL RULES" in proc.stdout
    assert "Counterfactual Placement Comparison Report" in proc.stdout
