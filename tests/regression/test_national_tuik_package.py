"""Regression on the team's real TÜİK province package (git-ignored, data/raw/tuik_package/).

Skipped when the package is absent. Re-checks the recorded package findings (row, indicator and coverage counts,
blank values, multi-year periods, wide/long agreement, documentation discrepancies), the control tables for all 81
provinces, the environment's handling of periods and projections, and a 20,000-record national smoke build.
Nothing is written into the repository: the store and population go to a temporary directory.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from societytwin.config import ExperimentLayout, Settings

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "data" / "raw" / "tuik_package"
EXPERIMENT = REPO / "experiments" / "matraix_simulation"
pytestmark = pytest.mark.tuik_package
MULTI_YEAR = {"2013-2014", "2015-2017", "2018-2020", "2021-2023", "2023-2024", "2024-2025", "2023-2030"}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if not (PACKAGE / "data_catalog.csv").is_file():
        pytest.skip("TÜİK province package not present in data/raw/tuik_package")
    from societytwin.national.controls import read_store, write_store
    from societytwin.national.sources import build_controls

    tmp = tmp_path_factory.mktemp("tuik_package")
    settings = Settings(repo_root=REPO, experiment_root=EXPERIMENT, import_runs_root=EXPERIMENT / "runs", state_dir=tmp / "state",
                        data_manifest=REPO / "data" / "manifest.yaml", matraix_root=None, runtime_python=None, start_worker=False,
                        layout=ExperimentLayout.load(EXPERIMENT), national_controls_dir=tmp / "controls", populations_dir=tmp / "pops",
                        tuik_package_dir=PACKAGE, tuik_mapping_path=REPO / "data" / "tuik_package_mapping.yaml")
    store, report = build_controls(settings)
    write_store(settings.national_controls_dir, store)
    return read_store(settings.national_controls_dir), report


def _audit(store):
    return next(a for a in store.audits if a["adapter"] == "tuik_long_format_package")


def test_recorded_package_findings_hold(built):
    store, report = built
    audit = _audit(store)
    assert audit["files"]["total"] == 71 and audit["files"]["long_format"] == 33 and audit["files"]["wide"] == 33
    c = audit["counts"]
    assert (c["datasets"], c["long_rows"], c["indicators"], c["variable_metadata_indicators"]) == (33, 431_071, 568, 577)
    assert (c["blank_values"], c["multi_year_rows"], c["rejected_rows"], c["duplicate_keys_conflicting"]) == (20_431, 1_923, 0, 0)
    assert c["province_coverage_distribution"] == {"81": 30, "51": 1, "35": 1, "6": 1}
    assert c["control_cells"] + c["context_observations"] == 431_071
    assert audit["wide_files"] == {"verified": 33, "cells_compared": 431_071, "mismatches": 0, "unmatched_files": []}
    claims = audit["documentation_claims"]["claims"]
    assert claims["long_rows"] == 411_132 and claims["indicators"] == 577
    absent = next(d for d in audit["discrepancies"] if d["dataset"] == "road_motor_vehicles_and_transfers")
    assert absent["note"].count("transferred_vehicles_") == 9
    assert {d["field"] for d in audit["discrepancies"]} == {"variable_metadata", "README.indicators", "README.long_rows",
                                                            "variable_metadata.rows"}
    coverage = {s["source_id"]: len(s["province_coverage"]) for s in store.sources if s["source_id"].startswith("tuik_pkg:")}
    assert coverage["tuik_pkg:air_traffic_by_province"] == 51 and coverage["tuik_pkg:agricultural_wages_by_province"] == 35
    assert coverage["tuik_pkg:opera_and_ballet_by_province"] == 6
    periods = {p for s in store.sources if s["source_id"].startswith("tuik_pkg:") for p in s["reference_periods"] if "-" in p}
    assert periods == MULTI_YEAR
    assert len(audit["not_province_level"]) == 10
    assert next(r for r in report if r["adapter"] == "legacy_ankara_extracts")["status"] == "loaded"


def test_control_tables_cover_all_provinces_with_recorded_checks(built):
    store, _ = built
    assert set(store.tables) == {"population_age_sex", "marital_status_sex", "education_sex", "urbanicity_sex"}
    for table in store.tables:
        assert len(store.provinces_with(table, 2025)) == 81, table
    checks = {t: {c["name"]: c for c in m.checks if c.get("summary")} for t, m in store.tables.items()}
    for table, named in checks.items():
        assert named["labels_match_source_names"]["passed"], table
        assert all(c["passed"] for n, c in named.items() if n.startswith("cells_sum_to_published_total")), table
    assert checks["marital_status_sex"]["universe_equals_root_population"]["years_failed"] == [2016, 2017, 2018, 2019, 2020]
    assert checks["education_sex"]["universe_equals_root_population"]["years_failed"] == list(range(2016, 2026))
    assert checks["urbanicity_sex"]["universe_equals_root_population"]["passed"]
    cross = next(a for a in store.audits if a["adapter"] == "cross_source")["checks"]
    assert {(k["corroborating_source"], k["cells"]) for k in cross if k["check"] == "agreeing_cells"} == {
        ("legacy:tuik_t16_age_sex", 38), ("legacy:tuik_t10_marital_sex", 8)}
    assert all(k["passed"] for k in cross if k["check"] == "legacy_context_equals_package")


def test_environment_keeps_periods_projections_and_gaps(built):
    from societytwin.national.environment import province_environment

    store, _ = built
    env = province_environment(store, "06", 2025)
    entries = {e["indicator_id"]: e for rows in env["domains"].values() for e in rows}
    le = entries["vital_mortality_and_life_expectancy_life_expectancy_at_birth_total"]
    assert le["source_period"] == "2021-2023" and le["source_year"] is None
    assert "population_projections_2024_2030_projected_population" not in entries
    assert any(p["indicator_id"] == "population_projections_2024_2030_projected_population" for p in env["projections"])
    villages = entries["population_urban_rural_pop_towns_and_villages_total"]
    assert villages["source_year"] == 2012 and "absent rows are not zero" in villages["note"]
    assert entries["population_total_and_growth_total_population"]["value"] == 5_910_320
    afyon = province_environment(store, "03", 2025)
    assert any(d["source_id"] == "tuik_pkg:air_traffic_by_province" for d in afyon["structurally_unavailable_datasets"])


def test_national_smoke_build(built):
    from societytwin.national.generator import GenerationConfig, generate
    from societytwin.national.validation import validate

    store, _ = built
    pop = generate(store, GenerationConfig(synthetic_size=20_000, seed=42))
    m, c = pop.manifest, pop.columns
    assert m["scope"]["province_count"] == 81 and m["scope"]["excluded"] == []
    totals = [r.value for r in store.context if r.indicator_id == "population_total_and_growth_total_population" and r.year == 2025]
    assert len(totals) == 81 and math.isclose(m["represented_population"], math.fsum(totals), rel_tol=1e-12)
    assert all(w > 0 and math.isfinite(w) for w in c["population_weight"])
    assert all(x["converged"] for x in m["calibration"])
    for prof in m["profiles"].values():
        fields = prof["fields"]
        for f in ("age_group", "marital_status", "education_level", "urbanicity"):
            assert fields[f]["source_year"] == 2025 and all(s.startswith("tuik_pkg:") for s in fields[f]["source_ids"]), (prof["profile_id"], f)
        for f in ("labour_status", "household_size_class", "household_type"):
            assert fields[f]["evidence"] == "UNAVAILABLE"
    assert set(c["labour_status"]) == {None} and set(c["household_type"]) == {None}
    report = validate(c, m, store)
    assert report["constraint_violations"] == 0
    assert all(chk["passed"] for p in report["provinces"] for chk in p["cross_source_checks"])
    ankara = next(x for x in m["calibration"] if x["province_code"] == "06")
    assert "marital_status_sex" in ankara["margins"]
    got = {}
    for code, sex, status, w in zip(c["province_code"], c["sex"], c["marital_status"], c["population_weight"]):
        if code == "06" and status != "not_applicable":
            got[(sex, status)] = got.get((sex, status), 0.0) + w
    assert math.isclose(got[("female", "never_married")], 633_169, rel_tol=1e-6)
    assert math.isclose(got[("male", "widowed")], 33_210, rel_tol=1e-6)
