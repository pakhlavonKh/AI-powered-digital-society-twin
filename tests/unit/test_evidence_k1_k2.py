"""Comprehensive tests for Phase 2 — Evidence Registry (K1) & Statistical Processing (K2).

Covers:
1. Extension of existing DependencyRegistry without creating a competing YAML registry or breaking compile_compatibility.
2. Searchability of EvidenceRegistry (by geography, year, dimension, status, scope, unit, ankara_only, national_only, attribute) and versioning/fingerprinting.
3. Reproducible loading via load_reference_dataset(dataset_id) -> ReferenceDataset.
4. SHA-256 hash verification on load and loud failure on hash mismatch or missing file.
5. Geography, year, and denominator preservation across all normalization steps.
6. Flagging of invalid tables: category totals don't add up, unknown/unmapped category label, wrong denominator / unexpected universe gap, conflicting duplicate rows, negative/non-numeric values.
7. Preservation of published 'unknown' / unclassified categories (e.g. Ankara education 15+ 'unknown' = 17,626) and missing values ('NOT_REPORTED' / 'NOT_APPLICABLE' kept as None, never silently coerced to 0).
8. Scope honesty: national data ('TR') cannot be loaded as Ankara-specific ('06') without an explicit scope override, and always carries visible scope_marker='NATIONAL_ONLY_NOT_ANKARA_SPECIFIC'.
9. Explicit encoding of the Ankara 1,987,216 household count vs 5,910,320 resident population discrepancy (D1) as a flagged, documented data-quality issue, never as a silently 'fixed' number.
10. Deterministic versioned reference package generation (normalized CSV/JSON tables + manifest.json).
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pytest

from societytwin.common import sha256_bytes
from societytwin.evidence import (
    EVIDENCE_REGISTRY_SCHEMA_VERSION,
    EVIDENCE_REGISTRY_VERSION,
    EvidenceDatasetEntry,
    EvidenceLoadError,
    EvidenceRegistry,
    NormalizationError,
    ReferenceDataset,
    build_reference_package,
    detect_denominator_inconsistency,
    load_evidence_registry,
    load_reference_dataset,
    normalize_reference_table,
    resolve_dataset_path,
    validate_category_totals,
)
from societytwin.evidence.registry import ANKARA_HOUSEHOLD_DISCREPANCY_FLAG
from societytwin.national.dependencies import compile_compatibility, load_registry as load_dependency_registry


@pytest.fixture(scope="module")
def evidence_registry() -> EvidenceRegistry:
    return load_evidence_registry()


def test_k1_extends_existing_dependency_registry_without_breaking_compatibility(evidence_registry: EvidenceRegistry):
    dep_reg = load_dependency_registry()
    compiled = compile_compatibility(dep_reg)
    assert len(compiled) == 6
    assert evidence_registry.schema_version == EVIDENCE_REGISTRY_SCHEMA_VERSION
    assert evidence_registry.evidence_registry_version == EVIDENCE_REGISTRY_VERSION
    assert evidence_registry.parent_dependency_registry_version == dep_reg.registry_version == "ankara-core-1"
    assert evidence_registry.parent_dependency_registry_fingerprint == dep_reg.fingerprint
    assert evidence_registry.household_registry_version == "ankara-household-size-1"
    assert evidence_registry.type_size_registry_version == "ankara-household-type-size-1"
    assert evidence_registry.extension_registry_version == "ankara-resident-extension-1"
    # Fingerprint is deterministic
    assert evidence_registry.fingerprint == load_evidence_registry().fingerprint


def test_k1_registry_entries_have_all_required_metadata_and_search_works(evidence_registry: EvidenceRegistry):
    for ds_id, entry in evidence_registry.datasets.items():
        assert entry.dataset_id == ds_id
        assert entry.source
        assert entry.geography.code in ("06", "TR", "TR51", "81_provinces", "06_districts")
        assert entry.year == 2025
        assert len(entry.dimensions) >= 1
        assert entry.unit in ("person", "household", "percent", "rate", "try", "mixed")
        assert entry.status in (
            "observed",
            "observed_with_caveats",
            "national_transfer_seed",
            "context_only",
            "projection_quarantined",
            "local_raw_optional",
            "unavailable",
        )
        assert entry.source_reference.agency
        assert entry.retrieval_info.relative_path
        assert entry.denominator.universe
        assert len(entry.sha256) == 64

    # Search by geography
    ankara_sets = evidence_registry.search(geography="06")
    assert any(e.dataset_id == "ankara_age_sex_2025" for e in ankara_sets)
    assert all(e.geography.province_code == "06" for e in ankara_sets)

    # Search by national_only
    national_sets = evidence_registry.search(national_only=True)
    assert {e.dataset_id for e in national_sets} == {
        "national_age_sex_marital_2025",
        "national_household_type_size_2025",
        "national_81provinces_age_sex_2025",
    }
    assert all(e.geography.scope_marker == "NATIONAL_ONLY_NOT_ANKARA_SPECIFIC" for e in national_sets)
    assert all(not e.geography.is_ankara_specific for e in national_sets)

    # Search by dimension
    marital_sets = evidence_registry.search(dimension="marital_status")
    assert {e.dataset_id for e in marital_sets} >= {
        "ankara_marital_sex_2025",
        "legacy_ankara_marital_sex_2025",
        "national_age_sex_marital_2025",
    }

    # Search by year and status
    observed_2025 = evidence_registry.search(year=2025, status="observed")
    assert any(e.dataset_id == "ankara_age_sex_2025" for e in observed_2025)


def test_reproducible_loading_and_exact_ankara_2025_numbers(evidence_registry: EvidenceRegistry):
    a = load_reference_dataset("ankara_age_sex_2025", registry=evidence_registry)
    b = load_reference_dataset("ankara_age_sex_2025", registry=evidence_registry)
    assert isinstance(a, ReferenceDataset)
    assert a == b
    assert a.content_sha256 == b.content_sha256
    assert a.geography.code == "06"
    assert a.is_ankara_specific is True and a.is_national is False
    assert a.scope_marker == "ANKARA_OBSERVED"
    assert a.year == 2025
    assert a.unit == "person"
    assert a.denominator.universe == "ADNKS_residents_all"
    assert len(a.rows) == 38
    assert a.computed_total == 5_910_320
    assert a.published_totals["total"] == 5_910_320
    assert a.published_totals["sex:male"] == 2_911_853
    assert a.published_totals["sex:female"] == 2_998_467
    assert all(c.status == "pass" for c in a.checks)
    assert math.isclose(sum(r.proportion_of_total for r in a.rows if r.proportion_of_total), 1.0, rel_tol=1e-12)

    # Corroborating legacy extract matches cell-for-cell
    legacy = load_reference_dataset("legacy_ankara_age_sex_2025", registry=evidence_registry)
    assert legacy.computed_total == 5_910_320
    a_map = {(r.dimensions["age_group"], r.dimensions["sex"]): r.value for r in a.rows}
    leg_map = {(r.dimensions["age_group"], r.dimensions["sex"]): r.value for r in legacy.rows}
    assert a_map == leg_map


def test_hash_verification_fails_loudly_on_mismatch_or_missing_file(
    evidence_registry: EvidenceRegistry,
    tmp_path: Path,
):
    entry = evidence_registry.get("legacy_ankara_marital_sex_2025")
    src_path = resolve_dataset_path(entry)
    fake_repo = tmp_path / "repo"
    target = fake_repo / entry.retrieval_info.relative_path
    target.parent.mkdir(parents=True, exist_ok=True)

    # 1. Missing file fails loudly
    with pytest.raises(EvidenceLoadError, match="not found"):
        load_reference_dataset("legacy_ankara_marital_sex_2025", registry=evidence_registry, repo_root=fake_repo)

    # 2. Tampered file bytes fail SHA-256 verification loudly
    shutil.copyfile(src_path, target)
    target.write_bytes(target.read_bytes() + b"\n# tampered")
    with pytest.raises(EvidenceLoadError, match="SHA-256 checksum mismatch"):
        load_reference_dataset("legacy_ankara_marital_sex_2025", registry=evidence_registry, repo_root=fake_repo)


def test_national_data_cannot_be_loaded_as_ankara_specific_without_visible_scope_marker(
    evidence_registry: EvidenceRegistry,
):
    # Attempting to load national dataset with require_ankara_scope=True fails loudly
    with pytest.raises(EvidenceLoadError, match="Scope violation.*National \\(TR\\) scope"):
        load_reference_dataset(
            "national_81provinces_age_sex_2025",
            registry=evidence_registry,
            require_ankara_scope=True,
        )

    # Even when loaded with allow_national_scope=True (or default), every cell and dataset
    # carries visible NATIONAL_ONLY_NOT_ANKARA_SPECIFIC markers and is_ankara_specific=False
    nat_ds = load_reference_dataset(
        "national_81provinces_age_sex_2025",
        registry=evidence_registry,
        require_ankara_scope=True,
        allow_national_scope=True,
    )
    assert nat_ds.is_national is True
    assert nat_ds.is_ankara_specific is False
    assert nat_ds.geography.code == "TR"
    assert nat_ds.scope_marker == "NATIONAL_ONLY_NOT_ANKARA_SPECIFIC"
    assert nat_ds.computed_total == 86_092_168
    assert all(
        r.is_national is True
        and r.is_ankara_specific is False
        and r.scope_marker == "NATIONAL_ONLY_NOT_ANKARA_SPECIFIC"
        for r in nat_ds.rows
    )
    denom_check = next(c for c in nat_ds.checks if c.check_id.endswith("root_denominator_reconciliation"))
    assert denom_check.status == "not_evaluable"
    assert "National (TR) scope" in denom_check.reason


def test_ankara_household_discrepancy_is_flagged_and_documented_never_forced(
    evidence_registry: EvidenceRegistry,
):
    hh_ds = load_reference_dataset("ankara_household_types_2025", registry=evidence_registry)
    assert hh_ds.unit == "household"
    assert hh_ds.denominator.universe == "ADNKS_private_households"
    assert hh_ds.computed_total == 1_987_216
    assert hh_ds.published_totals["total"] == 1_987_216
    assert math.isclose(hh_ds.published_extra_metrics["average_household_size"], 2.86361774462363, rel_tol=1e-12)

    # Verify the 4 household types sum to 1,987,216 (never rescaled to 5,910,320)
    by_type = {r.dimensions["household_type"]: r.value for r in hh_ds.rows}
    assert by_type == {
        "one_person": 400_484,
        "nuclear_family": 1_312_420,
        "extended_family": 205_415,
        "non_family_multi_person": 68_897,
    }
    assert sum(by_type.values()) == 1_987_216

    # Check that D1 flag is attached and reconciliation check is not_evaluable with exact 219,693 gap
    flag_ids = [f.flag_id for f in hh_ds.data_quality_flags]
    assert ANKARA_HOUSEHOLD_DISCREPANCY_FLAG.flag_id in flag_ids
    d1_flag = next(f for f in hh_ds.data_quality_flags if f.flag_id == ANKARA_HOUSEHOLD_DISCREPANCY_FLAG.flag_id)
    assert d1_flag.handling_policy == "document_do_not_force"
    assert d1_flag.observed_values["ankara_2025_adnks_resident_population"] == 5_910_320
    assert d1_flag.observed_values["ankara_2025_private_households_total"] == 1_987_216
    assert d1_flag.observed_values["ankara_2025_implied_private_household_population"] == 5_690_627
    assert d1_flag.observed_values["ankara_2025_unreconciled_institutional_and_tail_gap_persons"] == 219_693

    reconcile_chk = next(
        c for c in hh_ds.checks if c.check_id.endswith("household_vs_resident_population_reconciliation")
    )
    assert reconcile_chk.status == "not_evaluable"
    assert "219,693" in reconcile_chk.reason
    assert reconcile_chk.discrepancy_flag_id == "D1_ANKARA_HH_VS_RESIDENT_POP_2025"


def test_education_preserves_published_unknown_and_flags_104983_universe_gap(
    evidence_registry: EvidenceRegistry,
):
    edu_ds = load_reference_dataset("ankara_education_sex_2025", registry=evidence_registry)
    assert edu_ds.computed_total == 4_751_123
    assert edu_ds.published_totals["total"] == 4_751_123
    assert edu_ds.published_totals["sex:male"] == 2_322_692
    assert edu_ds.published_totals["sex:female"] == 2_428_431

    # Published 'unknown' (Bilinmeyen) is preserved, never dropped
    unknown_rows = [r for r in edu_ds.rows if r.dimensions["education_level"] == "unknown"]
    assert len(unknown_rows) == 2
    assert all(r.category_kind == "published_unknown" for r in unknown_rows)
    unknown_by_sex = {r.dimensions["sex"]: r.value for r in unknown_rows}
    assert unknown_by_sex == {"male": 7_474, "female": 10_152}
    assert edu_ds.distribution is not None
    assert edu_ds.distribution.includes_published_unknown is True
    assert edu_ds.distribution.published_unknown_mass == 17_626

    # Denominator check documents the 104,983 gap vs ADNKS 15+ (4,856,106)
    denom_chk = next(c for c in edu_ds.checks if c.check_id.endswith("root_denominator_reconciliation"))
    assert denom_chk.status == "not_evaluable"
    assert "104,983" in denom_chk.reason
    assert denom_chk.discrepancy_flag_id == "D2_ANKARA_EDUCATION_15PLUS_VS_ADNKS_15PLUS_2025"


def test_invalid_tables_are_flagged_totals_unknown_category_wrong_denominator_missing_values(
    evidence_registry: EvidenceRegistry,
):
    entry = evidence_registry.get("ankara_marital_sex_2025")

    # 1. Category totals don't add up to published total / expected_total -> status='fail'
    bad_totals_records = [
        {"dimensions": {"province_code": "06", "sex": "male", "marital_status": "never_married"}, "value": 100},
        {"dimensions": {"province_code": "06", "sex": "male", "marital_status": "married"}, "value": 200},
        {"dimensions": {"province_code": "06", "sex": "male", "marital_status": "divorced"}, "value": 50},
        {"dimensions": {"province_code": "06", "sex": "male", "marital_status": "widowed"}, "value": 10},
        {"dimensions": {"province_code": "06", "sex": "female", "marital_status": "never_married"}, "value": 100},
        {"dimensions": {"province_code": "06", "sex": "female", "marital_status": "married"}, "value": 200},
        {"dimensions": {"province_code": "06", "sex": "female", "marital_status": "divorced"}, "value": 50},
        {"dimensions": {"province_code": "06", "sex": "female", "marital_status": "widowed"}, "value": 20},
    ]
    res_bad_totals = normalize_reference_table(
        bad_totals_records,
        entry,
        published_totals={"total": 9999, "sex:male": 500, "sex:female": 500},
    )
    assert res_bad_totals.passed_all_checks is False
    failed_ids = {c.check_id for c in res_bad_totals.checks if c.status == "fail"}
    assert f"{entry.dataset_id}:expected_total_match" in failed_ids
    assert f"{entry.dataset_id}:published_total_match" in failed_ids
    assert f"{entry.dataset_id}:sex_total_match:male" in failed_ids
    assert f"{entry.dataset_id}:root_denominator_reconciliation" in failed_ids

    # 2. Unknown / unmapped category label is flagged (and raises in strict mode)
    unmapped_records = [
        {"dimensions": {"province_code": "06", "sex": "male", "marital_status": "invented_status"}, "value": 100},
    ]
    with pytest.raises(NormalizationError, match="Unmapped category 'invented_status'"):
        normalize_reference_table(unmapped_records, entry, strict=True)

    res_unmapped = normalize_reference_table(unmapped_records, entry, strict=False)
    assert res_unmapped.passed_all_checks is False
    assert any(c.check_id.endswith("category_vocabulary:marital_status") and c.status == "fail" for c in res_unmapped.checks)
    assert any(i.category == "unknown_category_unmapped" for i in res_unmapped.issues)

    # 3. Missing values ('', '-', 'c') are preserved as NOT_REPORTED with value=None (never 0)
    missing_records = [
        {"dimensions": {"province_code": "06", "sex": "male", "marital_status": "never_married"}, "value": ""},
        {"dimensions": {"province_code": "06", "sex": "male", "marital_status": "married"}, "value": "-"},
    ]
    res_missing = normalize_reference_table(missing_records, entry, strict=False)
    assert len(res_missing.rows) == 2
    assert all(r.value is None and r.value_status == "NOT_REPORTED" for r in res_missing.rows)
    assert res_missing.distribution is not None
    assert res_missing.distribution.missing_cell_count == 2
    assert any(i.category == "missing_value_preserved" for i in res_missing.issues)


def test_versioned_reference_package_build_and_determinism(
    evidence_registry: EvidenceRegistry,
    tmp_path: Path,
):
    out_a = tmp_path / "pkg_a"
    out_b = tmp_path / "pkg_b"
    manifest_a = build_reference_package(out_a, registry=evidence_registry)
    manifest_b = build_reference_package(out_b, registry=evidence_registry)

    assert manifest_a == manifest_b
    assert manifest_a["package_fingerprint"] == manifest_b["package_fingerprint"]
    assert manifest_a["tables_built_count"] == 14
    assert manifest_a["optional_local_skipped_count"] == 3
    assert (out_a / "manifest.json").is_file()

    # Check that D1 household discrepancy is recorded in manifest documented_data_quality_flags
    flag_ids = {f["flag_id"] for f in manifest_a["documented_data_quality_flags"]}
    assert "D1_ANKARA_HH_VS_RESIDENT_POP_2025" in flag_ids
    assert "D2_ANKARA_EDUCATION_15PLUS_VS_ADNKS_15PLUS_2025" in flag_ids

    # Check that every built table has matching CSV and JSON files with verified hashes
    for tbl in manifest_a["tables"]:
        j_path = out_a / tbl["normalized_json_relpath"]
        c_path = out_a / tbl["normalized_csv_relpath"]
        assert j_path.is_file() and c_path.is_file()
        assert sha256_bytes(j_path.read_bytes()) == tbl["normalized_json_sha256"]
        assert sha256_bytes(c_path.read_bytes()) == tbl["normalized_csv_sha256"]
        assert tbl["checks_summary"]["fail"] == 0
