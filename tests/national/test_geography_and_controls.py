"""Geography reference table, long-format ingestion, missing values and the control store."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from societytwin.national import geography as geo
from societytwin.national.controls import ControlsError, read_store, write_store
from societytwin.national.sources import build_controls, parse_value, tuik_package
from societytwin.national.vocab import EDUCATION, MARITAL, SEX, ValueStatus

REPO = Path(__file__).resolve().parents[2]


def test_reference_table_has_81_unique_provinces_and_consistent_nuts_codes():
    assert len(geo.PROVINCES) == 81
    assert [p.code for p in geo.PROVINCES] == [f"{i:02d}" for i in range(1, 82)]
    assert len({p.nuts3 for p in geo.PROVINCES}) == 81
    assert len({p.nuts2 for p in geo.PROVINCES}) == 26
    assert len({p.nuts1 for p in geo.PROVINCES}) == 12
    assert all(re.fullmatch(r"TR[1-9A-C]\d{2}|TR[1-9A-C]\d\d", p.nuts3) for p in geo.PROVINCES)
    assert geo.province("06").nuts3 == "TR510" and geo.province("34").nuts3 == "TR100" and geo.province("69").nuts3 == "TRA13"


def test_reference_table_matches_the_map_geometry_iso_codes():
    text = (REPO / "frontend" / "src" / "lib" / "turkey-provinces.ts").read_text(encoding="utf-8")
    shapes = json.loads(text[text.index("["): text.rindex("]") + 1])
    by_iso = {s["iso"]: s["name"] for s in shapes}
    assert set(by_iso) == {p.iso for p in geo.PROVINCES}
    for p in geo.PROVINCES:
        assert geo.name_key(by_iso[p.iso]) in {geo.name_key(n) for n in (p.name, *p.aliases)}


@pytest.mark.parametrize("value,code", [("6", "06"), ("06", "06"), (6, "06"), ("TR-34", "34"), ("81", "81"), ("1.0", "01")])
def test_codes_are_normalised(value, code):
    assert geo.normalize_code(value) == code


@pytest.mark.parametrize("value", ["0", "82", "Ankara", "", "TR510"])
def test_invalid_codes_are_rejected_and_names_are_never_codes(value):
    with pytest.raises(geo.UnknownProvince):
        geo.normalize_code(value)


def test_names_resolve_with_turkish_characters_and_aliases_only():
    assert geo.by_name("İSTANBUL").code == "34"
    assert geo.by_name("istanbul").code == "34"
    assert geo.by_name("Iğdır").code == "76" and geo.by_name("IGDIR").code == "76"
    assert geo.by_name("Hakkâri").code == "30"
    assert geo.by_name("Içel").code == "33"
    with pytest.raises(geo.UnknownProvince):
        geo.by_name("Ankaraa")


def test_vocabularies_map_every_tuik_label_and_reject_unknown_ones():
    assert MARITAL.from_source("Hiç evlenmedi") == "never_married"
    assert MARITAL.from_source("Eşi öldü") == "widowed"
    assert MARITAL.display("never_married") == "Never married"
    assert SEX.from_source("Kadın") == "female" and SEX.from_source("ERKEK") == "male"
    assert EDUCATION.from_source("Lise veya dengi meslek okulu") == "upper_secondary"
    with pytest.raises(ValueError, match="Unmapped"):
        MARITAL.from_source("Nişanlı")


def test_missing_values_are_never_zero():
    markers = {ValueStatus.NOT_REPORTED: ["", "-", ".."], ValueStatus.UNKNOWN: ["?"]}
    assert parse_value("-", markers) == (None, ValueStatus.NOT_REPORTED)
    assert parse_value("", markers) == (None, ValueStatus.NOT_REPORTED)
    assert parse_value("?", markers) == (None, ValueStatus.UNKNOWN)
    assert parse_value("0", markers) == (0.0, ValueStatus.OBSERVED)
    assert parse_value("12345.6", markers) == (12345.6, ValueStatus.OBSERVED)
    with pytest.raises(ValueError):
        parse_value("12,3", markers)


def test_package_ingestion_validates_keys_and_preserves_missingness(national_settings):
    res = tuik_package(national_settings.tuik_package_dir, national_settings.tuik_mapping_path, national_settings.repo_root)
    assert res.status == "loaded"
    joined = "\n".join(res.warnings)
    assert "out of range 01–81" in joined                    # province 99 rejected
    assert "does not match province 06" in joined           # NUTS-3 mismatch rejected
    assert "duplicate key" in joined                        # conflicting duplicate flagged
    by_id = {(c.indicator_id, c.geo_code, c.year): c for c in res.context}
    air = [c for c in res.context if c.indicator_id.startswith("air_traffic")]
    assert {(c.geo_code, c.year, c.value_status) for c in air} == {("06", 2024, "OBSERVED"), ("06", 2025, "NOT_REPORTED")}
    gdp_bayburt = next(c for k, c in by_id.items() if k[0].startswith("gdp_per_capita") and k[1] == "69")
    assert gdp_bayburt.value is None and gdp_bayburt.value_status == ValueStatus.NOT_REPORTED
    zero = next(c for c in res.context if c.indicator_id.endswith("sifir"))
    assert zero.value == 0.0 and zero.value_status == ValueStatus.OBSERVED
    air_source = next(s for s in res.sources if s["source_id"] == "tuik_pkg:air_traffic")
    assert air_source["province_coverage"] == ["06"] and "1 of 81" in air_source["limitations"][0]
    assert {d["dataset"]: d["province_count"] for d in res.datasets}["population_by_age_sex"] == 3


def test_store_round_trip_and_tamper_detection(national_settings):
    store, report = build_controls(national_settings)
    assert {r["adapter"]: r["status"] for r in report} == {"legacy_ankara_extracts": "failed", "tuik_long_format_package": "loaded"}
    assert set(store.tables) == {"population_age_sex", "marital_status_sex", "education_sex"}
    write_store(national_settings.national_controls_dir, store)
    again = read_store(national_settings.national_controls_dir)
    assert len(again.rows) == len(store.rows) and again.fingerprint
    assert again.provinces_with("population_age_sex", 2025) == ["01", "06", "69"]
    assert again.provinces_with("education_sex", 2025) == ["01", "06"]  # Bayburt only has a 2026 projection
    assert again.best("population_age_sex", geo.province("01"), 2025).year == 2025
    assert again.best("population_age_sex", geo.province("01"), 2024).year == 2024
    path = national_settings.national_controls_dir / "controls.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("population_age_sex,province,01", "population_age_sex,province,02", 1),
                    encoding="utf-8")
    with pytest.raises(ControlsError, match="checksum"):
        read_store(national_settings.national_controls_dir)


def test_conflicting_cells_from_two_sources_are_an_error(national_settings, tmp_path):
    extra = national_settings.tuik_package_dir / "population_copy.csv"
    lines = (national_settings.tuik_package_dir / "population_by_age_sex.csv").read_text(encoding="utf-8").splitlines()
    header, first = lines[0], lines[1].split(",")
    first[6] = str(int(first[6]) + 1)
    extra.write_text(header + "\n" + ",".join(first).replace("population_by_age_sex,", "population_by_age_sex,", 1) + "\n", encoding="utf-8")
    # Same dataset id and key with a different value -> flagged as a duplicate, first value kept.
    store, report = build_controls(national_settings)
    warnings = next(r for r in report if r["adapter"] == "tuik_long_format_package")["warnings"]
    assert any("duplicate key" in w for w in warnings)
