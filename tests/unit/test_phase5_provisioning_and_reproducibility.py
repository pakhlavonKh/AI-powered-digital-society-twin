"""Acceptance tests for Phase 5: Reproducibility and Data Provisioning.

Verifies:
1. Shell provisioning script (`scripts/provision_reference_data.sh`) copies
   `ankara_district_population_and_growth.csv`, verifies SHA-256 against EvidenceRegistry,
   and fails loudly on SHA-256 mismatch.
2. Table count accounting: 17 registered datasets in EvidenceRegistry = 14 standard built tables +
   3 optional local raw tables (national_age_sex_marital_2025, ankara_household_size_2025,
   national_household_type_size_2025).
3. Independently verified K3 and K7 validation results on the 1,000-person Ankara population (seed=42)
   without self-validating against freshly generated outputs:
   - K3: 5 marginal checks passed, 0 failed, 3 not_evaluable
   - Combined K3+K4: 5 marginal checks passed, 2 proxy conditional checks failed, 6 not_evaluable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from societytwin.common import sha256_bytes
from societytwin.evidence import build_reference_package, load_evidence_registry
from societytwin.validation import (
    DEFAULT_REFERENCE_PACKAGE_DIR,
    generate_ankara_sample_population,
    generate_combined_quality_report,
    load_reference_bundle,
    validate_population,
)


def _find_bash() -> str:
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        shutil.which("bash"),
    ):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("bash executable not found")


def test_provisioning_shell_script_verifies_sha256_and_fails_loudly_on_mismatch(tmp_path: Path):
    """Shell provisioning script (`scripts/provision_reference_data.sh`) verifies SHA-256
    and exits with non-zero status and 'SHA-256 mismatch' if a source CSV is tampered with.
    """
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "provision_reference_data.sh"
    assert script_path.is_file()

    src_dir = repo_root / "tuik_province_data"
    if not src_dir.is_dir():
        src_dir = repo_root.parent / "repo_clone_9b8e227" / "tuik_province_data"
    assert src_dir.is_dir()

    bash_bin = _find_bash()
    env = dict(os.environ)
    env["PYTHON_BIN"] = sys.executable

    # 1. Valid provisioning into tmp_path succeeds and verifies ankara_district_population_and_growth.csv
    target_dir = tmp_path / "tuik_package_valid"
    res_ok = subprocess.run(
        [
            bash_bin,
            str(script_path),
            "--source",
            str(src_dir),
            "--target",
            str(target_dir),
            "--repo-root",
            str(repo_root),
            "--skip-build",
            "--skip-golden",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_ok.returncode == 0, f"Provisioning failed: {res_ok.stdout}\n{res_ok.stderr}"
    copied_district = target_dir / "ankara_district_population_and_growth.csv"
    assert copied_district.is_file()
    reg = load_evidence_registry()
    assert sha256_bytes(copied_district.read_bytes()) == reg.get("ankara_district_population_2025").sha256

    # 2. Tampering with ankara_district_population_and_growth.csv in a staged source directory fails loudly
    corrupted_src = tmp_path / "corrupted_source"
    shutil.copytree(src_dir, corrupted_src)
    district_csv = corrupted_src / "ankara_district_population_and_growth.csv"
    district_csv.write_bytes(district_csv.read_bytes() + b"\n06,9999,corrupted,0,person\n")

    res_bad = subprocess.run(
        [
            bash_bin,
            str(script_path),
            "--source",
            str(corrupted_src),
            "--target",
            str(tmp_path / "tuik_package_corrupted"),
            "--repo-root",
            str(repo_root),
            "--skip-build",
            "--skip-golden",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_bad.returncode != 0
    combined_out = (res_bad.stdout or "") + "\n" + (res_bad.stderr or "")
    assert "SHA-256 mismatch" in combined_out


def test_reference_package_17_vs_14_table_accounting(tmp_path: Path):
    """Verify the exact 17 registered datasets = 14 standard tables + 3 optional local raw tables."""
    reg = load_evidence_registry()
    assert len(reg.datasets) == 17

    optional_ids = {
        ds_id
        for ds_id, entry in reg.datasets.items()
        if entry.retrieval_info.optional_local_file
    }
    assert optional_ids == {
        "national_age_sex_marital_2025",
        "ankara_household_size_2025",
        "national_household_type_size_2025",
    }

    pkg_dir = tmp_path / "ref_pkg"
    manifest = build_reference_package(pkg_dir, registry=reg)
    assert manifest["tables_built_count"] == 14
    assert manifest["optional_local_skipped_count"] == 3
    assert manifest["tables_built_count"] + manifest["optional_local_skipped_count"] == len(reg.datasets) == 17
    skipped_ids = {item["dataset_id"] for item in manifest["skipped_optional_local_datasets"]}
    assert skipped_ids == optional_ids


def test_independent_expected_validation_outcomes_for_ankara_1000():
    """Verify the 1,000-person Ankara population (seed=42) against independently verified expected values

    (5 marginal checks passed, 2 proxy conditional checks failed, 6 not evaluable).
    """
    bundle, _, _, _ = load_reference_bundle(DEFAULT_REFERENCE_PACKAGE_DIR)
    pop_1000 = generate_ankara_sample_population(
        synthetic_size=1000,
        seed=42,
        calibrate=True,
        reference_bundle=bundle,
    )

    # 1. K3 Marginal validation report
    k3 = validate_population(pop_1000, bundle)
    assert k3.population_id == "pop-06-2025-n1000-s42-e6a8e87e"
    assert k3.reference_package_fingerprint == "fa0971ff615e79140f1a74bb18f979e05e0c3175bd0b9ce32fbdea34f9142ca5"
    assert k3.status_counts == {"pass": 5, "fail": 0, "not_evaluable": 3}

    passed_margins = {c.margin for c in k3.checks if c.status == "pass"}
    not_eval_margins = {c.margin for c in k3.checks if c.status == "not_evaluable"}
    assert passed_margins == {"age", "sex", "age_sex", "marital_status", "education"}
    assert not_eval_margins == {"employment_status", "household_size", "household_type"}

    # 2. Combined K3 + K4 Quality Report: 5 marginal passed, 2 proxy conditional failed, 6 not evaluable
    combined = generate_combined_quality_report(pop_1000, bundle, save_to_disk=False)
    assert combined.status_counts == {"pass": 5, "fail": 2, "not_evaluable": 6}

    failed_ids = {c.check_id for c in combined.checks if c.status == "fail"}
    assert failed_ids == {"joint_age_marital", "joint_sex_age_marital"}
    for chk in combined.checks:
        if chk.check_id in failed_ids:
            assert chk.scope_marker == "national proxy, not Ankara-observed"
