"""Regression on the real TÜİK-derived Ankara extracts shipped with the historical experiment.

Skipped when they are absent. Checks that the national pipeline reproduces the published Ankara 2025
controls and that it never modifies the historical experiment files.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from societytwin.common import sha256_file
from societytwin.config import ExperimentLayout, Settings

REPO = Path(__file__).resolve().parents[2]
EXPERIMENT = REPO / "experiments" / "matraix_simulation"
pytestmark = pytest.mark.local_fixture


@pytest.fixture
def real_settings(tmp_path):
    if not (EXPERIMENT / "processed" / "ankara_age_gender.csv").is_file():
        pytest.skip("historical Ankara extracts not present")
    return Settings(repo_root=tmp_path, experiment_root=EXPERIMENT, import_runs_root=EXPERIMENT / "runs", state_dir=tmp_path / "state",
                    data_manifest=tmp_path / "m.yaml", matraix_root=None, runtime_python=None, start_worker=False,
                    layout=ExperimentLayout.load(EXPERIMENT), tuik_package_dir=tmp_path / "none",
                    tuik_mapping_path=tmp_path / "none.yaml")


def test_ankara_2025_controls_are_reproduced_and_history_is_untouched(real_settings):
    from societytwin.national.controls import read_store, write_store
    from societytwin.national.generator import GenerationConfig, generate
    from societytwin.national.sources import build_controls
    from societytwin.national.validation import validate

    tracked = sorted(p for p in EXPERIMENT.rglob("*") if p.is_file() and "runs" not in p.parts and "__pycache__" not in p.parts)
    before = {p: sha256_file(p) for p in tracked}
    store, _ = build_controls(real_settings)
    write_store(real_settings.national_controls_dir, store)
    store = read_store(real_settings.national_controls_dir)
    checks = store.tables["marital_status_sex"].checks
    assert all(c["passed"] for c in checks), "marital universe should equal the 15+ population exactly"
    pop = generate(store, GenerationConfig(synthetic_size=10_000, seed=42))
    c = pop.columns
    assert pop.manifest["scope"]["provinces_with_records"] == ["06"]
    assert math.isclose(sum(c["population_weight"]), 5_910_320, rel_tol=1e-9)
    expected = {("female", "never_married"): 633_169, ("female", "married"): 1_453_591, ("female", "divorced"): 182_966,
                ("female", "widowed"): 214_898, ("male", "never_married"): 771_997, ("male", "married"): 1_438_683,
                ("male", "divorced"): 127_592, ("male", "widowed"): 33_210}
    got = {}
    for sex, status, w in zip(c["sex"], c["marital_status"], c["population_weight"]):
        if status != "not_applicable":
            got[(sex, status)] = got.get((sex, status), 0.0) + w
    for key, value in expected.items():
        assert math.isclose(got[key], value, rel_tol=1e-9), key
    report = validate(c, pop.manifest, store)
    assert report["constraint_violations"] == 0
    assert all(chk["passed"] for chk in report["provinces"][0]["cross_source_checks"])
    assert {p: sha256_file(p) for p in tracked} == before
