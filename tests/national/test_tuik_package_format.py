"""Ingestion of the team package's actual layout, on a tiny ARTIFICIAL package written by this test.

The layout is the real one (snake_case indicators, data_catalog.csv with file_name / dataset_title_en / source_url /
reference_year(s) / provinces_covered / missing_provinces, variable_metadata.csv with original_name_tr, a 1/0
coverage matrix, <dataset>_wide.csv twins, a README with counts). Every number is invented.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from societytwin.national.controls import ContextRow, parse_period, read_store, write_store
from societytwin.national.environment import province_environment
from societytwin.national.sources import build_controls, load_mapping, tuik_package

BANDS = [f"{a}_{a + 4}" for a in range(0, 90, 5)] + ["90_plus"]
PROVINCES = {"06": ("Ankara", "TR510"), "69": ("Bayburt", "TRA13")}
LONG = ["province_code", "province_name", "nuts3_code", "year", "indicator", "value", "unit"]
MAPPING = """
version: 1
controls:
  - table: population_age_sex
    dataset: population_by_age_sex
    indicator_pattern: '^pop_age_(?P<age_group>\\d+_\\d+|90_plus)_(?P<sex>male|female)$'
    total_patterns: ['^pop_age_total_(?P<sex>male|female)$']
    source_units: [person]
    universe_min_age: 0
    universe_note: All residents (artificial)
  - table: marital_status_sex
    dataset: marital_status_by_sex
    indicator_pattern: '^pop_15plus_marital_(?P<category>never_married|married|divorced|widowed)_(?P<sex>male|female)$'
    total_patterns: ['^pop_15plus_marital_total_(?P<sex>male|female)$']
    residual_pattern: '^pop_15plus_marital_unknown_(?P<sex>male|female)$'
    source_units: [person]
    universe_min_age: 15
    universe_check: root_universe
datasets:
  population_by_age_sex: {domain: demographics, use: controls}
  marital_status_by_sex: {domain: households, use: controls}
  life_expectancy: {domain: health, use: context, reason: Multi-year life tables (artificial).}
  population_projections: {domain: demographics, use: context, observation_type: projection, projection_baseline_period: '2024'}
missing_value_markers: {}
"""


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _wide(path: Path, long_rows: list[list], corrupt: bool = False) -> None:
    indicators = sorted({r[4] for r in long_rows})
    keyed = {}
    for r in long_rows:
        keyed.setdefault(tuple(r[:4]), {})[r[4]] = r[5]
    rows = []
    for key, values in sorted(keyed.items()):
        rows.append([*key, *[values.get(i, "") for i in indicators]])
    if corrupt:  # change one published number in the wide copy
        rows[0][-1] = "99.9"
    _write(path, ["province_code", "province_name", "nuts3_code", "year", *indicators], rows)


def build_package(root: Path, corrupt_wide: bool = False) -> Path:
    pkg = root / "data" / "raw" / "tuik_package"
    pkg.mkdir(parents=True)
    pop, marital, life, proj = [], [], [], []
    variables = []
    for code, (name, nuts) in PROVINCES.items():
        scale = 100 if code == "06" else 3
        for sex in ("male", "female"):
            total = adult = 0
            for i, band in enumerate(BANDS):
                v = scale * (20 - i)
                total += v
                adult += v if i >= 3 else 0
                pop.append([code, name, nuts, "2025", f"pop_age_{band}_{sex}", v, "person"])
            pop.append([code, name, nuts, "2025", f"pop_age_total_{sex}", total, "person"])
            parts = [adult // 4, adult // 2, adult // 8]
            parts.append(adult - sum(parts))
            for cat, v in zip(("never_married", "married", "divorced", "widowed"), parts):
                marital.append([code, name, nuts, "2025", f"pop_15plus_marital_{cat}_{sex}", v, "person"])
            marital.append([code, name, nuts, "2025", f"pop_15plus_marital_total_{sex}", adult, "person"])
        life += [[code, name, nuts, "2021-2023", "life_expectancy_total", "78.5", "year"],
                 [code, name, nuts, "2018-2020", "life_expectancy_total", "78.1", "year"]]
        proj += [[code, name, nuts, "2024", "projected_population", 1000, "person"],
                 [code, name, nuts, "2025", "projected_population", 1010, "person"],
                 [code, name, nuts, "2030", "projected_population", 1050, "person"]]
    life.append(["06", "Ankara", "TR510", "2025", "life_expectancy_blank", "", "year"])
    datasets = {"population_by_age_sex": pop, "marital_status_by_sex": marital, "life_expectancy": life, "population_projections": proj}
    for ds, rows in datasets.items():
        _write(pkg / f"{ds}.csv", LONG, rows)
        _wide(pkg / f"{ds}_wide.csv", rows, corrupt=corrupt_wide and ds == "life_expectancy")
    for band in BANDS:
        label = band.replace("_plus", "+").replace("_", "-")
        for sex, tr in (("male", "Erkek"), ("female", "Kadın")):
            variables.append(["population_by_age_sex.csv", f"pop_age_{band}_{sex}", f"Nüfus ({label} yaş, {tr})", "x", "person", "T16"])
    for sex, tr in (("male", "Erkek"), ("female", "Kadın")):
        variables.append(["population_by_age_sex.csv", f"pop_age_total_{sex}", f"Nüfus (Toplam yaş, {tr})", "x", "person", "T16"])
        for cat, label in (("never_married", "Hiç evlenmedi"), ("married", "Evli"), ("divorced", "Boşandı"), ("widowed", "Eşi öldü"),
                           ("total", "Toplam (15+ yaş)")):
            variables.append(["marital_status_by_sex.csv", f"pop_15plus_marital_{cat}_{sex}", f"15+ yaş nüfus - {label} ({tr})", "x", "person", "T10"])
    variables += [["life_expectancy.csv", "life_expectancy_total", "Doğuşta beklenen yaşam süresi", "Life expectancy", "year", "LT"],
                  ["life_expectancy.csv", "life_expectancy_blank", "Boş", "Blank", "year", "LT"],
                  ["life_expectancy.csv", "life_expectancy_never_published", "Hiç", "Defined, no rows", "year", "LT"],
                  ["population_projections.csv", "projected_population", "Projeksiyon", "Projection", "person", "PR"]]
    _write(pkg / "variable_metadata.csv", ["file_name", "indicator", "original_name_tr", "description_en", "unit", "source_table_or_flow"], variables)
    _write(pkg / "data_catalog.csv",
           ["file_name", "wide_file_name", "dataset_title_tr", "dataset_title_en", "theme", "source_url", "publication_date",
            "reference_year(s)", "unit", "provinces_covered", "missing_provinces", "retrieval_date", "notes"],
           [["population_by_age_sex.csv", "population_by_age_sex_wide.csv", "YAPAY", "ARTIFICIAL population", "Population",
             "https://example.invalid/pop", "2026-02-06", "2025", "person", "2", "None", "2026-10-18", ""],
            ["marital_status_by_sex.csv", "marital_status_by_sex_wide.csv", "YAPAY", "ARTIFICIAL marital", "Households",
             "https://example.invalid/mar", "2026-02-06", "2025", "person", "2", "None", "2026-10-18", ""],
            ["life_expectancy.csv", "life_expectancy_wide.csv", "YAPAY", "ARTIFICIAL life tables", "Population",
             "https://example.invalid/le", "2026-06-23", "2018-2025 (3 periods)", "year", "81", "None", "2026-10-18", ""],
            ["population_projections.csv", "population_projections_wide.csv", "YAPAY", "ARTIFICIAL projections", "Population",
             "https://example.invalid/pr", "2024-07-31", "2024-2030 (3 periods)", "person", "2", "None", "2026-10-18", ""]])
    files = [f"{ds}.csv" for ds in datasets]
    _write(pkg / "coverage_report.csv", ["province_code", "province_name", "nuts3_code", *files],
           [[c, n, nuts, *(["1"] * len(files))] for c, (n, nuts) in PROVINCES.items()])
    _write(pkg / "not_province_level.csv", ["dataset_title_tr", "dataset_title_en", "theme", "geographic_level_available",
                                            "reason_excluded", "source_url"],
           [["YAPAY", "ARTIFICIAL regional survey", "Income", "NUTS-2", "Published only for NUTS-2", "https://example.invalid/r"]])
    (pkg / "README.md").write_text("# Artificial\n\n**4 official province-level datasets**, **99 distinct indicators** and "
                                   "**12 long-format data rows**.\n", encoding="utf-8")
    (root / "data" / "tuik_package_mapping.yaml").write_text(MAPPING, encoding="utf-8")
    return pkg


@pytest.fixture
def team_settings(make_settings, tmp_path):
    pkg = build_package(tmp_path)
    return make_settings(tuik_package_dir=pkg, tuik_mapping_path=tmp_path / "data" / "tuik_package_mapping.yaml")


def test_periods_are_parsed_without_inventing_a_single_year():
    assert parse_period("2025") == ("2025", 2025, 2025)
    assert parse_period("2021-2023") == ("2021-2023", 2021, 2023)
    assert parse_period("2025.0") == ("2025", 2025, 2025)
    for bad in ("2023-2021", "20x5", "1850", "2021/2023"):
        with pytest.raises(ValueError):
            parse_period(bad)
    row = ContextRow("x", "other", "x", "", "province", "06", None, 1.0, "OBSERVED", "", "s", "r", "2021-2023")
    assert row.year is None and (row.period_start, row.period_end) == (2021, 2023) and row.is_multi_year


def test_team_layout_metadata_and_audit(team_settings, tmp_path):
    res = tuik_package(team_settings.tuik_package_dir, team_settings.tuik_mapping_path, tmp_path)
    assert res.status == "loaded", res.detail
    audit = res.audit
    assert audit["counts"]["datasets"] == 4 and audit["counts"]["rejected_rows"] == 0
    assert audit["counts"]["blank_values"] == 1 and audit["counts"]["multi_year_rows"] == 4
    assert audit["wide_files"]["verified"] == 4 and audit["wide_files"]["mismatches"] == 0
    assert audit["not_province_level"][0]["geographic_level"] == "NUTS-2"
    fields = {(d["dataset"], d["field"]) for d in audit["discrepancies"]}
    assert (None, "README.long_rows") in fields and (None, "README.indicators") in fields   # claims re-counted, not trusted
    assert ("life_expectancy", "variable_metadata") in fields                                 # defined but absent indicator
    assert ("life_expectancy", "provinces_covered") in fields                                 # catalog says 81, data has 2
    src = {s["source_id"]: s for s in res.sources}
    pop = src["tuik_pkg:population_by_age_sex"]
    assert pop["title_en"] == "ARTIFICIAL population" and pop["url"] == "https://example.invalid/pop"
    assert pop["publication_date"] == "2026-02-06" and pop["retrieval_date"] == "2026-10-18" and pop["dataset_identifier"] == "T16"
    assert pop["status"] == "used" and pop["accounting"]["rejected"] == 0
    assert pop["accounting"]["read"] == pop["accounting"]["control_cells"] + pop["accounting"]["context_observations"]
    le = src["tuik_pkg:life_expectancy"]
    assert le["reference_periods"] == ["2018-2020", "2021-2023", "2025"] and le["status"] == "context_only"
    assert "Multi-year life tables" in " ".join(le["limitations"])


def test_controls_checks_and_label_verification(team_settings, tmp_path):
    res = tuik_package(team_settings.tuik_package_dir, team_settings.tuik_mapping_path, tmp_path)
    cells = [r for r in res.rows if r.table_id == "population_age_sex"]
    assert len(cells) == 2 * 2 * 19 and {r.age_group for r in cells} >= {"0-4", "90+"}
    # Published totals are context, never summed into cells.
    assert any(c.indicator_id == "population_by_age_sex_pop_age_total_male" for c in res.context)
    checks = {c["name"]: c for c in res.tables["population_age_sex"].checks}
    assert checks["cells_sum_to_published_total[0]"]["passed"] and checks["labels_match_source_names"]["passed"]
    universe = next(c for c in res.tables["marital_status_sex"].checks if c["name"] == "universe_equals_root_population")
    assert universe["passed"] and universe["checked"] == 4


def test_mislabelled_mapping_is_rejected(make_settings, tmp_path):
    pkg = build_package(tmp_path)
    meta = (pkg / "variable_metadata.csv").read_text(encoding="utf-8-sig").replace("Nüfus (0-4 yaş, Erkek)", "Nüfus (5-9 yaş, Erkek)")
    (pkg / "variable_metadata.csv").write_text(meta, encoding="utf-8-sig")
    res = tuik_package(pkg, tmp_path / "data" / "tuik_package_mapping.yaml", tmp_path)
    assert any("not recognisable in the source name" in w for w in res.warnings)
    assert not any(r.age_group == "0-4" and r.sex == "male" for r in res.rows)
    label = next(c for c in res.tables["population_age_sex"].checks if c["name"] == "labels_match_source_names")
    assert not label["passed"]


def test_wide_file_disagreement_is_reported(make_settings, tmp_path):
    pkg = build_package(tmp_path, corrupt_wide=True)
    res = tuik_package(pkg, tmp_path / "data" / "tuik_package_mapping.yaml", tmp_path)
    assert res.audit["wide_files"]["mismatches"] == 1
    assert any(d["field"] == "wide_file" for d in res.audit["discrepancies"])
    # The wide file is never imported: the long value stands.
    assert {c.value for c in res.context if c.indicator_id == "life_expectancy_life_expectancy_total"} == {78.5, 78.1}


def test_environment_keeps_periods_blanks_and_projections_apart(team_settings):
    store, _ = build_controls(team_settings)
    write_store(team_settings.national_controls_dir, store)
    store = read_store(team_settings.national_controls_dir)
    env = province_environment(store, "06", 2025)
    entries = {e["indicator_id"]: e for rows in env["domains"].values() for e in rows}
    le = entries["life_expectancy_life_expectancy_total"]
    assert le["source_period"] == "2021-2023" and le["source_year"] is None and le["multi_year_period"] and le["value"] == 78.5
    blank = entries["life_expectancy_life_expectancy_blank"]
    assert blank["value"] is None and blank["value_status"] == "NOT_REPORTED"
    # Projections are never a current value, even for years up to the reference year.
    assert "population_projections_projected_population" not in entries
    proj = next(p for p in env["projections"] if p["indicator_id"] == "population_projections_projected_population")
    assert [(p["period"], p["observation_type"]) for p in proj["points"]] == [("2024", "projection_baseline"), ("2025", "projection"),
                                                                               ("2030", "projection")]
    assert store.provinces_with("marital_status_sex", 2025) == ["06", "69"]


def test_mapping_rejects_projection_controls_and_unknown_keys(tmp_path):
    bad = tmp_path / "m.yaml"
    bad.write_text(MAPPING.replace("population_projections: {domain: demographics, use: context,",
                                   "population_by_age_sex2: {domain: demographics, use: controls,"), encoding="utf-8")
    with pytest.raises(Exception, match="no control rule names it"):
        load_mapping(bad)
    bad.write_text(MAPPING.replace("    universe_note: All residents (artificial)", "    universe_note: x\n    typo_key: 1"), encoding="utf-8")
    with pytest.raises(Exception, match="unknown keys"):
        load_mapping(bad)


def test_period_rows_never_become_control_cells(make_settings, tmp_path):
    pkg = build_package(tmp_path)
    with (pkg / "population_by_age_sex.csv").open("a", encoding="utf-8", newline="") as handle:
        handle.write("06,Ankara,TR510,2021-2023,pop_age_0_4_male,5,person\n")
    res = tuik_package(pkg, tmp_path / "data" / "tuik_package_mapping.yaml", tmp_path)
    assert any("single reference year" in w for w in res.warnings)
    assert all(r.year == 2025 for r in res.rows)


def test_universe_gap_is_scaled_per_sex_and_reported(team_settings):
    """A table whose total is below the root's universe (like education vs ADNKS 15+) is checked, flagged as a
    limitation, applied to the root population per sex, and validation says the comparison is of shares."""
    from societytwin.national.generator import GenerationConfig, generate
    from societytwin.national.validation import validate

    path = team_settings.tuik_package_dir / "marital_status_by_sex.csv"
    rows = path.read_text(encoding="utf-8-sig").splitlines()
    shrink = {"pop_15plus_marital_never_married_female", "pop_15plus_marital_total_female"}
    out = []
    for line in rows:
        parts = line.split(",")
        if parts[0] == "06" and parts[4] in shrink:
            parts[5] = str(int(parts[5]) - 50)          # the source universe misses 50 women in Ankara
        out.append(",".join(parts))
    path.write_text("\n".join(out) + "\n", encoding="utf-8-sig")
    store, _ = build_controls(team_settings)
    meta = store.tables["marital_status_sex"]
    universe = next(c for c in meta.checks if c["name"] == "universe_equals_root_population")
    assert not universe["passed"] and universe["years_failed"] == [2025]
    assert any("differs from the age × sex table's 15+ population" in x for x in meta.limitations)
    pop = generate(store, GenerationConfig(synthetic_size=2000, seed=1))
    report = validate(pop.columns, pop.manifest, store)
    ankara = next(t for p in report["provinces"] if p["province_code"] == "06" for t in p["tables"] if t["table_id"] == "marital_status_sex")
    assert ankara["source_to_population_scale_by_sex"]["male"] == pytest.approx(1.0)
    assert ankara["source_to_population_scale_by_sex"]["female"] > 1.0
    assert any("checks shares within sex" in n for n in ankara["notes"])
    if ankara["weighted_status"] != "not_calibrated":
        assert ankara["weighted_status"] == "fit_by_construction"   # per-sex scaling: no artificial gap
    national = next(t for t in report["national"]["tables"] if t["table_id"] == "marital_status_sex")
    assert any("universe differs from the root population" in n for n in national["notes"])


def test_blank_later_rows_are_named_not_called_absent(make_settings, tmp_path):
    pkg = build_package(tmp_path)
    with (pkg / "life_expectancy.csv").open("a", encoding="utf-8", newline="") as handle:
        handle.write("06,Ankara,TR510,2024,life_expectancy_blank,77.0,year\n")
    settings = make_settings(tuik_package_dir=pkg, tuik_mapping_path=tmp_path / "data" / "tuik_package_mapping.yaml")
    store, _ = build_controls(settings)
    env = province_environment(store, "06", 2025)
    blank = next(e for rows in env["domains"].values() for e in rows if e["indicator_id"] == "life_expectancy_life_expectancy_blank")
    assert blank["value"] == 77.0 and blank["source_period"] == "2024"
    assert blank["note"].startswith("Later row(s) 2025 carry no number (NOT_REPORTED)")
