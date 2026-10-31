"""Unit tests for Phase 4 Dependency & Joint-Distribution Validation (K4).

Tests:
1. Required test: Two populations with IDENTICAL age and marital-status marginals but
   different age-marital relationships. The validator must evaluate marginals identically
   but detect the unrealistic joint distribution in the second.
2. Bejan default generator output fails joint age-marital check with exact demographic reasons.
3. Explicit national proxy labeling: Supported joint checks carry "national proxy, not Ankara-observed".
4. Unverified relationships: age × education and age × employment are marked not_evaluable
   with zero invented benchmarks.
5. Structural zero enforcement: Child marriage (<15) and underage degree holders fail loudly.
6. Household type × size: Unlinked resident population marked not_evaluable vs. evaluated when
   household records are provided; physical structural zero violations detected.
7. Report partitioning: calibrated_margins, supported_joint_checks, and unverified_relationships
   are explicitly separated.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from societytwin.national.constraints import EDUCATION_MIN_COMPLETION_AGE
from societytwin.validation import (
    DEFAULT_REFERENCE_PACKAGE_DIR,
    CalibrationTolerances,
    DependencyValidationReport,
    JointCheckResult,
    generate_ankara_sample_population,
    load_reference_bundle,
    validate_dependencies,
    validate_population,
)


@pytest.fixture(scope="module")
def sample_pop_1000():
    """Deterministic 1,000-person Ankara sample (seed=42)."""
    return generate_ankara_sample_population(1000, seed=42)


def test_identical_marginals_different_joints_detected(sample_pop_1000):
    """REQUIRED TEST (Task 4): Two populations with IDENTICAL age and marital-status marginals.

    - Population A: Realistic age-marital distribution (teenagers never-married, adults married).
    - Population B: Swapped age-marital distribution (40 married teenagers 15-19, adults never-married).
    - Both populations have bit-for-bit IDENTICAL age, sex, and marital status marginal distributions.
    - Marginal validator must evaluate both identically.
    - Dependency validator must pass Population A and FAIL Population B.
    """
    cols_a = deepcopy(sample_pop_1000.columns)
    ages = cols_a["age"]
    sexes = cols_a["sex"]

    # Construct realistic marital assignments in Population A
    for s in ("male", "female"):
        idx_15plus = [i for i, a in enumerate(ages) if a >= 15 and sexes[i] == s]
        idx_15_19 = [i for i in idx_15plus if 15 <= ages[i] <= 19]
        idx_20_24 = [i for i in idx_15plus if 20 <= ages[i] <= 24]
        idx_25_plus = [i for i in idx_15plus if ages[i] >= 25]

        # 15-19: almost all never_married (at most 1 married female)
        for i in idx_15_19:
            cols_a["marital_status"][i] = "never_married"
        if s == "female" and idx_15_19:
            cols_a["marital_status"][idx_15_19[0]] = "married"

        # 20-24: realistic youth marriage (~5% male, ~10% female)
        for i in idx_20_24:
            cols_a["marital_status"][i] = "never_married"
        n_mar_2024 = 2 if s == "male" else 4
        for i in idx_20_24[:n_mar_2024]:
            cols_a["marital_status"][i] = "married"

        # 25+: realistic adult distribution
        n_25 = len(idx_25_plus)
        ref = (0.20, 0.70, 0.07, 0.03) if s == "male" else (0.12, 0.68, 0.08, 0.12)
        n_nev, n_mar, n_div = int(ref[0] * n_25), int(ref[1] * n_25), int(ref[2] * n_25)
        for idx, i in enumerate(idx_25_plus):
            if idx < n_nev:
                cols_a["marital_status"][i] = "never_married"
            elif idx < n_nev + n_mar:
                cols_a["marital_status"][i] = "married"
            elif idx < n_nev + n_mar + n_div:
                cols_a["marital_status"][i] = "divorced"
            else:
                cols_a["marital_status"][i] = "widowed"

    # Construct Population B by swapping 40 married adults (25+) with 40 never-married teenagers (15-19)
    # Swapping is done strictly within the same sex, and population weights are swapped together,
    # guaranteeing that weighted and unweighted marginal distributions are 100% bit-for-bit IDENTICAL.
    cols_b = deepcopy(cols_a)
    for s in ("male", "female"):
        idx_15_19_nev = [
            i for i, a in enumerate(ages)
            if 15 <= a <= 19 and sexes[i] == s and cols_a["marital_status"][i] == "never_married"
        ]
        idx_25_plus_mar = [
            i for i, a in enumerate(ages)
            if a >= 25 and sexes[i] == s and cols_a["marital_status"][i] == "married"
        ]
        k = 20  # 20 males + 20 females = 40 swaps
        for i1, i2 in zip(idx_15_19_nev[:k], idx_25_plus_mar[:k]):
            cols_b["marital_status"][i1] = "married"
            cols_b["marital_status"][i2] = "never_married"
            # Swap weights so weighted marginal distributions remain identical
            w1, w2 = cols_b["population_weight"][i1], cols_b["population_weight"][i2]
            cols_b["population_weight"][i1], cols_b["population_weight"][i2] = w2, w1

    # Verify marginal identity
    from collections import Counter
    counts_a = Counter(cols_a["marital_status"])
    counts_b = Counter(cols_b["marital_status"])
    assert counts_a == counts_b, f"Marginal counts differ: {counts_a} vs {counts_b}"

    # Verify marginal age counts are identical
    age_counts_a = Counter(cols_a["age_group"])
    age_counts_b = Counter(cols_b["age_group"])
    assert age_counts_a == age_counts_b

    pop_a = {"columns": cols_a, "manifest": sample_pop_1000.manifest}
    pop_b = {"columns": cols_b, "manifest": sample_pop_1000.manifest}

    # 1. Marginal validation check
    rep_a_pop = validate_population(pop_a)
    rep_b_pop = validate_population(pop_b)

    chk_a_pop = rep_a_pop.get_check("marital_status")
    chk_b_pop = rep_b_pop.get_check("marital_status")

    assert chk_a_pop.status == chk_b_pop.status
    assert abs(chk_a_pop.metrics.total_variation_distance_records - chk_b_pop.metrics.total_variation_distance_records) < 1e-12
    assert abs(chk_a_pop.metrics.total_variation_distance_weighted - chk_b_pop.metrics.total_variation_distance_weighted) < 1e-12

    # 2. Dependency validation check
    rep_a_dep = validate_dependencies(pop_a)
    rep_b_dep = validate_dependencies(pop_b)

    chk_a_dep = rep_a_dep.get_check("joint_age_marital")
    chk_b_dep = rep_b_dep.get_check("joint_age_marital")

    # Population A must PASS realistic age-marital check
    assert chk_a_dep.status == "pass", f"Pop A failed: {chk_a_dep.reason}"

    # Population B must FAIL unrealistic age-marital check
    assert chk_b_dep.status == "fail", "Pop B unexpectedly passed joint check"
    assert "Unrealistic teenage marriage rate" in chk_b_dep.reason
    assert "teenagers aged 15-19 are married" in chk_b_dep.reason


def test_bejan_default_generator_fails_joint_age_marital(sample_pop_1000):
    """Verify that Bejan's default generator output fails joint age-marital checks.

    Bejan's default generator models marital_status via ipf_sex assuming independence
    from age for ages 15+, spreading adult marriage (~59%) and widowhood (~9%) onto 15-year-olds.
    """
    rep = validate_dependencies(sample_pop_1000)

    # Overall status must be fail
    assert rep.overall_status == "fail"

    # Joint age × marital status check must fail
    chk_age_mar = rep.get_check("joint_age_marital")
    assert chk_age_mar.status == "fail"
    assert "Unrealistic teenage marriage rate: 44/71 (62.0%)" in chk_age_mar.reason
    assert "Unrealistic teenage widowhood: 4/71" in chk_age_mar.reason
    assert "Unrealistic youth marriage rate: 83/145 (57.2%)" in chk_age_mar.reason

    # 3-way sex × age × marital status check must fail
    chk_sex_age_mar = rep.get_check("joint_sex_age_marital")
    assert chk_sex_age_mar.status == "fail"
    assert "Group (male, 15-24)" in chk_sex_age_mar.reason
    assert "Group (female, 15-24)" in chk_sex_age_mar.reason


def test_national_proxy_labeling_and_provenance(sample_pop_1000):
    """Verify that national proxy benchmarks carry visible labels and provenance."""
    rep = validate_dependencies(sample_pop_1000)

    chk_age_mar = rep.get_check("joint_age_marital")
    assert chk_age_mar.scope == "national_proxy"
    assert chk_age_mar.scope_label == "national proxy, not Ankara-observed"
    assert chk_age_mar.reference_dataset_id == "national_marital_broad_age_sex_2025"
    assert chk_age_mar.reference_geography == "TR"
    assert chk_age_mar.reference_year == 2025

    chk_sex_age_mar = rep.get_check("joint_sex_age_marital")
    assert chk_sex_age_mar.scope == "national_proxy"
    assert chk_sex_age_mar.scope_label == "national proxy, not Ankara-observed"
    assert chk_sex_age_mar.reference_geography == "TR"


def test_unverified_relationships_marked_not_evaluable(sample_pop_1000):
    """Verify that unverified relationships return not_evaluable without inventing benchmarks."""
    rep = validate_dependencies(sample_pop_1000)

    # age × employment
    chk_emp = rep.get_check("joint_age_employment")
    assert chk_emp.status == "not_evaluable"
    assert chk_emp.scope == "unverified_no_reference"
    assert chk_emp.scope_label == "unverified (no empirical reference)"
    assert "UNAVAILABLE" in chk_emp.reason
    assert "Benchmark not invented" in chk_emp.reason

    # age × education
    chk_edu = rep.get_check("joint_age_education")
    assert chk_edu.status == "not_evaluable"
    assert chk_edu.scope == "unverified_no_reference"
    assert chk_edu.scope_label == "unverified (no empirical reference)"
    assert "benchmark not invented per validation protocol" in chk_edu.reason
    assert "0 structural zero violations" in chk_edu.reason


def test_child_marriage_structural_zero_violation_fails(sample_pop_1000):
    """Verify that child marriage (<15) triggers immediate structural zero failure."""
    cols = deepcopy(sample_pop_1000.columns)
    # Find a child under 15 and mark them married
    child_idx = next(i for i, a in enumerate(cols["age"]) if a < 15)
    cols["marital_status"][child_idx] = "married"

    bad_pop = {"columns": cols, "manifest": sample_pop_1000.manifest}
    rep = validate_dependencies(bad_pop)

    chk = rep.get_check("joint_age_marital")
    assert chk.status == "fail"
    assert "Catastrophic structural zero violation" in chk.reason
    assert "children < 15 married" in chk.reason
    assert len(chk.structural_zero_violations) > 0


def test_underage_degree_structural_zero_violation_fails(sample_pop_1000):
    """Verify that an underage degree holder triggers structural zero failure in age × education."""
    cols = deepcopy(sample_pop_1000.columns)
    # Assign doctorate degree to a 15-year-old (minimum completion age is 24)
    idx_15 = next(i for i, a in enumerate(cols["age"]) if a == 15)
    cols["education_level"][idx_15] = "doctorate"

    bad_pop = {"columns": cols, "manifest": sample_pop_1000.manifest}
    rep = validate_dependencies(bad_pop)

    chk = rep.get_check("joint_age_education")
    assert chk.status == "fail"
    assert "Structural zero failure" in chk.reason
    assert any("doctorate" in v and "15" in v for v in chk.structural_zero_violations)


def test_household_type_size_resident_only_vs_companion_records(sample_pop_1000):
    """Verify household_size × household_type on resident population vs companion household records."""
    # 1. Resident-only population without household records
    rep_res = validate_dependencies(sample_pop_1000)
    chk_res = rep_res.get_check("joint_household_size_type")
    assert chk_res.status == "not_evaluable"
    assert chk_res.category == "unverified_relationships"
    assert "D1 discrepancy" in chk_res.reason
    assert "1,987,216" in chk_res.reason

    # 2. With companion household records (realistic)
    hh_records = [
        {"household_type": "one_person", "household_size_class": "1", "household_weight": 1.0}
        for _ in range(100)
    ] + [
        {"household_type": "nuclear_family", "household_size_class": "3", "household_weight": 1.0}
        for _ in range(300)
    ]
    rep_hh = validate_dependencies(sample_pop_1000, households=hh_records)
    chk_hh = rep_hh.get_check("joint_household_size_type")
    assert chk_hh.category == "supported_joint_checks"
    assert chk_hh.scope == "national_proxy"
    assert chk_hh.scope_label == "national proxy, not Ankara-observed"

    # 3. With companion household records violating structural zeros (e.g. one_person with size 4)
    bad_hh_records = [
        {"household_type": "one_person", "household_size_class": "4", "household_weight": 1.0}
    ]
    rep_bad_hh = validate_dependencies(sample_pop_1000, households=bad_hh_records)
    chk_bad_hh = rep_bad_hh.get_check("joint_household_size_type")
    assert chk_bad_hh.status == "fail"
    assert "Structural zero violations" in chk_bad_hh.reason
    assert any("one_person" in v for v in chk_bad_hh.structural_zero_violations)


def test_report_sections_partitioning_and_serialization(sample_pop_1000):
    """Verify that the validation report explicitly partitions sections and serializes to JSON/Markdown."""
    rep = validate_dependencies(sample_pop_1000)

    # Verify sections exist and are mutually disjoint
    assert len(rep.calibrated_margins) > 0
    assert len(rep.supported_joint_checks) > 0
    assert len(rep.unverified_relationships) > 0

    cal_ids = {c.check_id for c in rep.calibrated_margins}
    sup_ids = {c.check_id for c in rep.supported_joint_checks}
    unv_ids = {c.check_id for c in rep.unverified_relationships}

    assert cal_ids.isdisjoint(sup_ids)
    assert cal_ids.isdisjoint(unv_ids)
    assert sup_ids.isdisjoint(unv_ids)

    # Markdown rendering
    md = rep.to_markdown()
    assert "# K4 Dependency & Joint-Distribution Validation Report" in md
    assert "## 1. Calibrated Margins" in md
    assert "## 2. Supported Joint Checks" in md
    assert "## 3. Unverified Relationships" in md
    assert "D1_ANKARA_HH_VS_RESIDENT_POP_2025" in md

    # JSON serialization and fingerprinting
    raw_json = rep.model_dump_json()
    assert len(raw_json) > 1000
    roundtrip = DependencyValidationReport.model_validate_json(raw_json)
    assert roundtrip.report_fingerprint == rep.report_fingerprint
    assert roundtrip.overall_status == rep.overall_status
