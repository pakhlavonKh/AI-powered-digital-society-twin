"""Regression checks against the supplied Ankara fixtures and run3 evidence (skipped when absent).

These expectations describe this exact fixture; the application never hardcodes them.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from societytwin.common import compare_recorded_digest
from societytwin.config import load_settings

REPO = Path(__file__).resolve().parents[2]
EXPERIMENT = REPO / "experiments" / "matraix_simulation"
pytestmark = pytest.mark.local_fixture

if not (EXPERIMENT / "synthetic" / "ankara_population_1000_v2.csv").is_file():
    pytest.skip("Supplied Ankara fixtures are not present", allow_module_level=True)


@pytest.fixture(scope="module")
def wb(tmp_path_factory):
    from societytwin.workbench import Workbench

    settings = load_settings().with_overrides(experiment_root=EXPERIMENT, import_runs_root=EXPERIMENT / "runs",
                                              state_dir=tmp_path_factory.mktemp("state"), start_worker=False)
    workbench = Workbench(settings)
    yield workbench
    workbench.close()


def v2(wb):
    return next(b for b in wb.sync_builds() if b.source.variant == "v2")


def test_population_counts(wb):
    build = v2(wb)
    rows = build.table.rows
    assert build.table.row_count == 1000 and len(build.table.csv_rows) == 1000
    assert sum(r["gender"] == "female" for r in rows) == 499 and sum(r["gender"] == "male" for r in rows) == 501
    assert sum(r["age_group"] in {"0-4", "5-9", "10-14"} for r in rows) == 158
    counts = {s: sum(r["marital_status"] == s for r in rows) for s in ("Evli", "Hiç evlenmedi", "Boşandı", "Eşi öldü", "not_applicable")}
    assert counts == {"Evli": 494, "Hiç evlenmedi": 244, "Boşandı": 70, "Eşi öldü": 34, "not_applicable": 158}
    assert build.descriptor["scope"]["province"] == "Ankara" and build.descriptor["scope"]["reference_year"] == 2025
    assert [r["person_id"] for r in rows][0] == "ANK2025_000001" and [r["person_id"] for r in rows][-1] == "ANK2025_001000"


def test_source_fit_and_totals(wb):
    report = wb.validation(v2(wb).descriptor["build_id"])
    joint = next(m for m in report["metrics"] if m["name"] == "joint_age_gender_tvd")
    assert math.isclose(joint["value"], 0.07019634131485265, rel_tol=0, abs_tol=1e-12)
    assert all(c["passed"] for c in report["checks"])
    ref = wb.population.age_gender()
    assert sum(r["population"] for r in ref.rows) == 5_910_320
    marital = wb.population.marital_gender()
    assert {g: sum(r["population"] for r in marital.rows if r["gender"] == g) for g in ("male", "female")} == {"male": 2_371_482, "female": 2_484_624}


def test_rows_reproduce_with_seed_42():
    """Re-run the experiment's own sampling functions in an isolated process and compare parsed rows."""
    code = (
        "import csv, json, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from src.synthetic_population.generate_population import read_distribution, generate_population, enrich_marital_status, INPUT_PATH\n"
        "from src.data_processing.process_tuik_marital import read_distribution as rm, OUTPUT_PATH as M\n"
        "base = generate_population(read_distribution(INPUT_PATH), 42)\n"
        "v2 = enrich_marital_status(base, rm(M), 42)\n"
        "print(json.dumps({'base': base, 'v2': v2}))\n"
    )
    out = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(EXPERIMENT)], capture_output=True, text=True, check=True, timeout=120)
    generated = json.loads(out.stdout)
    import csv

    with (EXPERIMENT / "synthetic" / "ankara_population_1000.csv").open(encoding="utf-8") as fh:
        assert generated["base"] == list(csv.DictReader(fh))
    with (EXPERIMENT / "synthetic" / "ankara_population_1000_v2.csv").open(encoding="utf-8") as fh:
        assert generated["v2"] == list(csv.DictReader(fh))


def test_persona_digests_are_line_ending_equivalent(wb):
    import yaml

    for name in ("test_persona.yaml", "persona_b.yaml"):
        meta = yaml.safe_load((EXPERIMENT / "personas" / name).read_text(encoding="utf-8"))["metadata"]
        assert compare_recorded_digest(meta["source_sha256"], (EXPERIMENT / meta["source_population"]).read_bytes()) == "line_ending_equivalent"
        for entry in meta["processed_sources"].values():
            assert compare_recorded_digest(entry["sha256"], (EXPERIMENT / entry["path"]).read_bytes()) == "line_ending_equivalent"


@pytest.mark.skipif(not (EXPERIMENT / "runs" / "run3" / "comparison.json").is_file(), reason="run3 evidence not present")
def test_run3_evidence(wb):
    runs = {r["dirname"]: r for r in wb.imported_runs()}
    run3 = runs["run3"]
    assert run3["display_state"] == "completed" and run3["model"] == "gemini/gemini-3.1-flash-lite"
    assert run3["differing_values_recorded"] == run3["differing_values_recomputed"] == 9
    assert run3["usage"]["n_input_tokens"] == 4361 and run3["usage"]["n_output_tokens"] == 643
    assert run3["usage"]["n_cache_tokens"] is None and run3["usage"]["cost_usd"] == 0.00205475
    assert run3["usage"]["cost_source"] == "estimated" and run3["usage"]["billed_cost_usd"] is None
    assert all(c["passed"] for c in run3["consistency_checks"])
    assert [t["persona_id"] for t in run3["trials"]] == ["ANK2025_000001", "ANK2025_000183"]
    assert all(t["answer_count"] == 9 for t in run3["trials"])
    assert {k: runs[k]["display_state"] for k in ("gemini_live", "gemini_live_2", "run1", "matraix_ab_live", "matraix_smoke", "run2")} == {
        "gemini_live": "partial", "gemini_live_2": "outcome_unknown", "run1": "outcome_unknown",
        "matraix_ab_live": "outcome_unknown", "matraix_smoke": "completed_fake", "run2": "completed"}
