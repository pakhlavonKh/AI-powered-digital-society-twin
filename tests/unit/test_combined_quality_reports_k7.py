"""Unit tests for Phase 7 Automated Quality Reports & UI Integration (K7).

Tests:
1. End-to-end integration: combine population validation (K3), dependency validation (K4),
   and simulation evaluation (K6) into CombinedQualityReport.
2. Byte-identical determinism: same input produces bit-for-bit identical JSON and fingerprint.
3. Explicit sections: exact versions, dataset provenance on every check, pass/fail/not_evaluable
   with reasons, limitations, and validation gaps (Ankara household D1, unverified joints).
4. UI / API compatibility: `to_ui_dict()` generates data structures matching `src/societytwin/api/schemas.py:ValidationReport`.
5. On-disk persistence: saved reports are deterministic and keyed by population_id and population_version.
6. Acceptance criteria verification mapping test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from societytwin.validation import (
    COMBINED_REPORT_SCHEMA_VERSION,
    CombinedQualityReport,
    UnifiedCheckRecord,
    ValidationGapRecord,
    generate_ankara_sample_population,
    generate_combined_quality_report,
    get_ankara_transit_fare_bundle,
)


@pytest.fixture(scope="module")
def pop_100():
    return generate_ankara_sample_population(100, seed=42)


@pytest.fixture(scope="module")
def sim_results_100(pop_100):
    cols = pop_100.columns
    records = []
    for i, res_id in enumerate(cols["synthetic_id"]):
        records.append({
            "resident_id": res_id,
            "status": "valid",
            "answers": {
                "q1_usage_change": "maintain_usage" if i % 2 == 0 else "reduce_optional_trips",
                "q2_policy_support": "somewhat_oppose",
            },
        })
    return {
        "scenario_id": "transport_fare_001",
        "run_id": "run-test-k7-100",
        "model": "matraix-test-model",
        "records": records,
    }


def test_combined_quality_report_structure(pop_100, sim_results_100):
    """Verify combined report correctly integrates K3, K4, and K6 layers."""
    report = generate_combined_quality_report(
        population=pop_100,
        simulation_results=sim_results_100,
        save_to_disk=False,
    )

    assert report.report_schema_version == COMBINED_REPORT_SCHEMA_VERSION
    assert report.population_id == pop_100.manifest["population_id"]
    assert report.population_version == pop_100.manifest["population_version"]
    assert report.simulation_run_id == "run-test-k7-100"

    # Verify check layers
    layers = {c.layer for c in report.checks}
    assert "marginal_population" in layers
    assert "joint_dependency" in layers

    # Every check has status and reason
    for chk in report.checks:
        assert chk.status in ("pass", "fail", "not_evaluable")
        assert len(chk.reason) > 5

    # Population marginal checks carry dataset provenance
    margin_checks = [c for c in report.checks if c.layer == "marginal_population"]
    for c in margin_checks:
        assert c.dataset_provenance is not None
        assert c.dataset_provenance.dataset_id is not None
        assert c.dataset_provenance.denominator is not None

    # Verify validation gaps section
    gap_ids = {g.gap_id for g in report.validation_gaps}
    assert "D1_ANKARA_HH_VS_RESIDENT_POP_2025" in gap_ids
    assert "D2_ANKARA_EDUCATION_15PLUS_VS_ADNKS_15PLUS_2025" in gap_ids
    assert "UNAVAILABLE_ANKARA_FARE_ELASTICITY" in gap_ids

    # Verify limitations section
    assert len(report.limitations) >= 4


def test_byte_identical_determinism(pop_100, sim_results_100):
    """Verify that same inputs give bit-for-bit identical output and content hash."""
    rep1 = generate_combined_quality_report(
        population=pop_100,
        simulation_results=sim_results_100,
        save_to_disk=False,
    )
    rep2 = generate_combined_quality_report(
        population=pop_100,
        simulation_results=sim_results_100,
        save_to_disk=False,
    )

    # Content fingerprints must match
    assert rep1.report_fingerprint == rep2.report_fingerprint

    # Serialized JSONs must be byte-identical
    json1 = json.dumps(rep1.deterministic_dict, indent=2, sort_keys=True)
    json2 = json.dumps(rep2.deterministic_dict, indent=2, sort_keys=True)
    assert json1 == json2


def test_ui_api_compatibility_adapter(pop_100, sim_results_100):
    """Verify to_ui_dict() generates payload matching existing API schemas (schemas.py:ValidationReport)."""
    report = generate_combined_quality_report(
        population=pop_100,
        simulation_results=sim_results_100,
        save_to_disk=False,
    )
    ui_dict = report.to_ui_dict()

    # Required fields from schemas.py:ValidationReport
    expected_fields = {
        "build_id",
        "population_id",
        "method_version",
        "population_sha256",
        "metrics",
        "checks",
        "unavailable_evidence",
        "acceptance_status",
        "acceptance_note",
        "reference_tables",
        "synthetic_label",
        "attribution_note",
    }
    assert expected_fields.issubset(ui_dict.keys())

    # Verify metrics list
    assert len(ui_dict["metrics"]) > 0
    m0 = ui_dict["metrics"][0]
    assert "name" in m0
    assert "value" in m0
    assert "unit" in m0
    assert "categories" in m0
    assert "denominator" in m0

    # Verify checks list
    assert len(ui_dict["checks"]) > 0
    c0 = ui_dict["checks"][0]
    assert "name" in c0
    assert "passed" in c0
    assert "detail" in c0

    # Verify unavailable evidence list
    assert len(ui_dict["unavailable_evidence"]) > 0
    u0 = ui_dict["unavailable_evidence"][0]
    assert "name" in u0
    assert "reason" in u0


def test_disk_persistence_deterministic_filenames(pop_100, tmp_path):
    """Verify reports are saved to disk with deterministic filenames keyed by version."""
    report = generate_combined_quality_report(
        population=pop_100,
        save_to_disk=True,
        output_dir=tmp_path,
    )

    pop_slug = f"{report.population_id}_{report.population_version}"
    expected_json = tmp_path / f"quality_report_{pop_slug}.json"

    assert expected_json.exists()
    assert expected_json.stat().st_size > 1000

    # Verify round-trip load
    data = json.loads(expected_json.read_text(encoding="utf-8"))
    assert data["population_id"] == report.population_id
    assert data["report_schema_version"] == COMBINED_REPORT_SCHEMA_VERSION


def test_end_to_end_acceptance_criteria_verification():
    """Verify that all first-milestone acceptance criteria are demonstrably met."""
    # 1. 1,000-person Ankara population validated automatically
    pop_1000 = generate_ankara_sample_population(1000, seed=42)
    report = generate_combined_quality_report(pop_1000, save_to_disk=False)

    # Status must be computed across all checks
    assert report.overall_status in ("pass", "fail", "not_evaluable")
    assert report.status_counts["pass"] > 0
    assert report.status_counts["not_evaluable"] > 0

    # Calibrated margins distinguished from unsupported joints
    calibrated_checks = [c for c in report.checks if c.is_calibrated]
    unsupported_checks = [c for c in report.checks if not c.is_calibrated]
    assert len(calibrated_checks) > 0
    assert len(unsupported_checks) > 0

    # Every check has explicit reason
    for chk in report.checks:
        if chk.status in ("fail", "not_evaluable"):
            assert len(chk.reason) > 10

    # Markdown rendering exists and contains sections
    md = report.to_markdown()
    assert "# Combined Quality & Validation Report" in md
    assert "## 1. Executive Summary of All Quality Checks" in md
    assert "## 2. Validation Gaps & Unresolved Empirical Discrepancies" in md
    assert "## 3. Structural Limitations" in md
