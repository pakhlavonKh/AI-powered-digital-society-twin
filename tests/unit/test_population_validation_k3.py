"""Unit tests for Phase 3 — Population Distribution Validator (K3)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from societytwin.evidence.loaders import ReferenceDataset
from societytwin.evidence.normalization import NormalizedRow
from societytwin.validation.population import (
    DEFAULT_REFERENCE_PACKAGE_DIR,
    SUPPORTED_MARGINS,
    CalibrationTolerances,
    PopulationValidationReport,
    generate_ankara_sample_population,
    load_reference_bundle,
    validate_population,
)


@pytest.fixture(scope="module")
def reference_bundle():
    datasets, _, _, _ = load_reference_bundle(DEFAULT_REFERENCE_PACKAGE_DIR)
    return datasets


@pytest.fixture(scope="module")
def ankara_1000_population(reference_bundle):
    return generate_ankara_sample_population(
        synthetic_size=1000,
        seed=42,
        calibrate=True,
        reference_bundle=reference_bundle,
    )


def test_good_1000_person_ankara_sample_passes_calibrated_margins_and_flags_not_evaluable(
    ankara_1000_population,
    reference_bundle,
):
    """A good 1,000-person Ankara sample passes calibrated margins and returns not_evaluable for unsupported checks."""
    report = validate_population(ankara_1000_population, reference_bundle)

    assert isinstance(report, PopulationValidationReport)
    assert report.sample_size == 1000
    assert report.geography_code == "06"
    assert report.reference_year == 2025
    assert report.seed == 42
    assert report.population_id == "pop-06-2025-n1000-s42-e6a8e87e"
    assert report.population_version == "national-generator-1.1"
    assert pytest.approx(report.weighted_population_total, rel=1e-9) == 5_910_320.0
    assert report.overall_status == "pass"

    # All 8 required margins are present
    assert tuple(c.margin for c in report.checks) == SUPPORTED_MARGINS

    # Calibrated resident margins must pass
    for margin in ("age", "sex", "age_sex", "marital_status", "education"):
        chk = report.get_check(margin)
        assert chk.status == "pass", f"{margin} failed: {chk.reason}"
        assert chk.is_calibrated_margin is True
        assert chk.evaluation_regime == "calibrated_margin_tolerance"
        assert chk.calibration_tolerance_applied is True
        assert chk.population_version == "national-generator-1.1"
        assert chk.dataset_provenance.year == 2025
        assert chk.dataset_provenance.geography == "06"
        assert chk.dataset_provenance.denominator.unit == "person"
        assert chk.metrics is not None
        assert chk.metrics.total_variation_distance_weighted <= 1e-9
        assert chk.metrics.max_abs_pp_deviation_weighted <= 1e-6
        assert chk.sampling_uncertainty is not None
        assert chk.sampling_uncertainty.within_sampling_uncertainty is True
        assert chk.sampling_uncertainty.expected_tvd_for_n > 0.0
        assert len(chk.cells) > 0

    # Unsupported / non-comparable person-level checks must return not_evaluable with explicit reasons
    emp_chk = report.get_check("employment_status")
    assert emp_chk.status == "not_evaluable"
    assert emp_chk.dataset_provenance.dataset_id == "ankara_labour_force_rates_2025"
    assert emp_chk.dataset_provenance.denominator.unit == "percent"
    assert "D7_PROVINCIAL_LABOUR_FORCE_RATES_ONLY_NO_SEX_OR_COUNTS" in emp_chk.reason

    hh_size_chk = report.get_check("household_size")
    assert hh_size_chk.status == "not_evaluable"
    assert hh_size_chk.dataset_provenance.dataset_id == "ankara_household_size_2025"
    assert hh_size_chk.dataset_provenance.denominator.expected_total == 1_987_216
    assert "D1_ANKARA_HH_VS_RESIDENT_POP_2025" in hh_size_chk.reason
    assert "219,693" in hh_size_chk.reason

    hh_type_chk = report.get_check("household_type")
    assert hh_type_chk.status == "not_evaluable"
    assert hh_type_chk.dataset_provenance.dataset_id == "ankara_household_types_2025"
    assert hh_type_chk.dataset_provenance.denominator.expected_total == 1_987_216
    assert "D1_ANKARA_HH_VS_RESIDENT_POP_2025" in hh_type_chk.reason


def test_uncalibrated_distributions_report_sampling_uncertainty_without_calibration_tolerances(
    reference_bundle,
):
    """Uncalibrated distributions report sampling uncertainty for n=1000 and do not use calibration tolerances."""
    uncalibrated_pop = generate_ankara_sample_population(
        synthetic_size=1000,
        seed=42,
        calibrate=False,
        reference_bundle=reference_bundle,
    )
    report = validate_population(uncalibrated_pop, reference_bundle)
    assert report.overall_status == "pass"

    # Root age_sex is still stratified by design weights, while marital_status and education are uncalibrated
    for margin in ("marital_status", "education"):
        chk = report.get_check(margin)
        assert chk.status == "pass"
        assert chk.is_calibrated_margin is False
        assert chk.evaluation_regime == "uncalibrated_sampling_uncertainty"
        assert chk.calibration_tolerance_applied is False
        assert "Calibration tolerances were not applied" in chk.reason
        assert chk.sampling_uncertainty is not None
        assert chk.sampling_uncertainty.sample_size_n > 800
        assert chk.sampling_uncertainty.expected_tvd_for_n > 0.0
        assert chk.sampling_uncertainty.within_sampling_uncertainty is True
        # Note: weighted TVD is ~0.03-0.08 because raking was disabled, which would have failed 1e-5 calibration
        # tolerance if calibration tolerance had been wrongly applied!
        assert chk.metrics is not None
        assert chk.metrics.total_variation_distance_weighted > 1e-3


def test_corrupted_population_skewed_ages_fails_with_clear_reason(
    ankara_1000_population,
    reference_bundle,
):
    """Skewing ages (forcing 60% of records into 20-24) produces a meaningful failure on age and age_sex."""
    corrupted_cols = copy.deepcopy(ankara_1000_population.columns)
    for i in range(600):
        corrupted_cols["age_group"][i] = "20-24"
        corrupted_cols["age"][i] = 22

    report = validate_population(
        {"columns": corrupted_cols, "manifest": ankara_1000_population.manifest},
        reference_bundle,
    )
    assert report.overall_status == "fail"

    age_chk = report.get_check("age")
    assert age_chk.status == "fail"
    assert "weighted TVD" in age_chk.reason or "stratified record count error" in age_chk.reason
    assert age_chk.metrics is not None
    assert age_chk.metrics.total_variation_distance_records > 0.40
    assert age_chk.metrics.max_abs_standardized_residual is not None
    assert age_chk.metrics.max_abs_standardized_residual > 15.0

    joint_chk = report.get_check("age_sex")
    assert joint_chk.status == "fail"


def test_corrupted_population_wrong_sex_ratio_fails_with_clear_reason(
    ankara_1000_population,
    reference_bundle,
):
    """Corrupting the sex ratio (90% male, 10% female) fails sex and age_sex checks with clear reasons."""
    corrupted_cols = copy.deepcopy(ankara_1000_population.columns)
    for i in range(900):
        corrupted_cols["sex"][i] = "male"
    for i in range(900, 1000):
        corrupted_cols["sex"][i] = "female"

    report = validate_population(
        {"columns": corrupted_cols, "manifest": ankara_1000_population.manifest},
        reference_bundle,
    )
    assert report.overall_status == "fail"

    sex_chk = report.get_check("sex")
    assert sex_chk.status == "fail"
    assert sex_chk.metrics is not None
    assert sex_chk.metrics.max_abs_pp_deviation_records > 35.0
    assert sex_chk.metrics.max_abs_standardized_residual is not None
    assert sex_chk.metrics.max_abs_standardized_residual > 20.0


def test_corrupted_population_impossible_marital_values_and_child_marriage_fail(
    ankara_1000_population,
    reference_bundle,
):
    """Impossible marital status values and under-15 married records fail with explicit domain violation reasons."""
    corrupted_cols = copy.deepcopy(ankara_1000_population.columns)
    # 1. Find a child under 15 and assign 'married'
    child_idx = next(i for i, a in enumerate(corrupted_cols["age"]) if a < 15)
    corrupted_cols["marital_status"][child_idx] = "married"
    # 2. Find an adult 15+ and assign an impossible marital status
    adult_idx = next(i for i, a in enumerate(corrupted_cols["age"]) if a >= 25)
    corrupted_cols["marital_status"][adult_idx] = "impossible_status_xyz"

    report = validate_population(
        {"columns": corrupted_cols, "manifest": ankara_1000_population.manifest},
        reference_bundle,
    )
    assert report.overall_status == "fail"

    marital_chk = report.get_check("marital_status")
    assert marital_chk.status == "fail"
    assert "Domain/structural integrity failure on marital_status" in marital_chk.reason
    assert any("under 15" in v for v in marital_chk.domain_violations)
    assert any("impossible_status_xyz" in v for v in marital_chk.domain_violations)


def test_corrupted_population_education_structural_zero_fails(
    ankara_1000_population,
    reference_bundle,
):
    """Assigning 'doctorate' to a 16-year-old violates the minimum-completion-age structural zero and fails."""
    corrupted_cols = copy.deepcopy(ankara_1000_population.columns)
    teen_idx = next(i for i, a in enumerate(corrupted_cols["age"]) if 15 <= a <= 17)
    corrupted_cols["education_level"][teen_idx] = "doctorate"

    report = validate_population(
        {"columns": corrupted_cols, "manifest": ankara_1000_population.manifest},
        reference_bundle,
    )
    assert report.overall_status == "fail"
    edu_chk = report.get_check("education")
    assert edu_chk.status == "fail"
    assert any("structural zero" in v for v in edu_chk.domain_violations)


def test_household_type_and_size_validation_with_household_sample(
    ankara_1000_population,
    reference_bundle,
):
    """When a household sample is provided, household_type and household_size evaluate pass/fail properly."""
    ds_hh_type = reference_bundle["ankara_household_types_2025"]
    # Build a 1,000-household sample proportional to ankara_household_types_2025 (1,987,216 households)
    # one_person=407306, nuclear_family=1312420, extended_family=193972, non_family_multi_person=73518
    alloc = {
        "one_person": 205,
        "nuclear_family": 660,
        "extended_family": 98,
        "non_family_multi_person": 37,
    }
    ref_counts = {r.dimensions["household_type"]: float(r.value) for r in ds_hh_type.rows}
    hh_types: list[str] = []
    hh_weights: list[float] = []
    for k, n_k in alloc.items():
        hh_types.extend([k] * n_k)
        hh_weights.extend([ref_counts[k] / n_k] * n_k)

    hh_sample = {
        "columns": {
            "household_type": hh_types,
            "household_weight": hh_weights,
        },
        "manifest": {"fit": True},
    }
    report = validate_population(ankara_1000_population, reference_bundle, households=hh_sample)
    hht_chk = report.get_check("household_type")
    assert hht_chk.status == "pass"
    assert hht_chk.dataset_provenance.dataset_id == "ankara_household_types_2025"
    assert hht_chk.dataset_provenance.denominator.expected_total == 1_987_216
    assert "D1_ANKARA_HH_VS_RESIDENT_POP_2025" in hht_chk.dataset_provenance.data_quality_flags

    # Now corrupt household types (set all 1,000 households to one_person) -> must fail
    corrupted_hh = {
        "columns": {
            "household_type": ["one_person"] * 1000,
            "household_weight": [1987.216] * 1000,
        },
        "manifest": {"fit": True},
    }
    bad_report = validate_population(ankara_1000_population, reference_bundle, households=corrupted_hh)
    assert bad_report.get_check("household_type").status == "fail"


def test_saved_ankara_1000_sample_report_matches_live_validation(
    ankara_1000_population,
    reference_bundle,
):
    """The saved JSON and Markdown reports for the 1,000-person Ankara population match live execution."""
    report = validate_population(ankara_1000_population, reference_bundle)
    json_path = DEFAULT_REFERENCE_PACKAGE_DIR / "ankara_1000_validation_report_k3.json"
    md_path = DEFAULT_REFERENCE_PACKAGE_DIR.parent.parent / "docs" / "ankara_1000_validation_report_k3.md"

    assert json_path.is_file()
    assert md_path.is_file()

    saved_payload = json.loads(json_path.read_text(encoding="utf-8"))
    saved_report = PopulationValidationReport.model_validate(saved_payload)
    assert saved_report.report_fingerprint == report.report_fingerprint
    assert md_path.read_text(encoding="utf-8") == report.to_markdown()

