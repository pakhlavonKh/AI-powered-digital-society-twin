"""Unit tests for synthetic resident eligibility evaluation and filtering."""

import json
from pathlib import Path

from src.scenarios.eligibility import (
    EligibilityStatus,
    evaluate_resident,
    filter_population,
)
from src.scenarios.schema import PopulationFilterConfig

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
RESIDENTS_FIXTURE_PATH = FIXTURES_DIR / "sample_residents.json"


def test_evaluate_eligible_resident():
    resident = {
        "resident_id": "ANK_001",
        "age": 25,
        "province_code": "06",
        "sex": "female",
    }
    filter_cfg = PopulationFilterConfig(
        minimum_age=18,
        province_codes=["06"],
        adult_only=True,
    )
    result = evaluate_resident(resident, filter_cfg)
    assert result.status == EligibilityStatus.ELIGIBLE
    assert len(result.failed_criteria) == 0
    assert "satisfies all" in result.explanation


def test_evaluate_excluded_minor():
    resident = {
        "resident_id": "ANK_MIN_002",
        "age": 16,
        "province_code": "06",
        "sex": "male",
    }
    filter_cfg = PopulationFilterConfig(
        minimum_age=18,
        province_codes=["06"],
        adult_only=True,
    )
    result = evaluate_resident(resident, filter_cfg)
    assert result.status == EligibilityStatus.EXCLUDED
    assert any("below minimum age 18" in reason for reason in result.failed_criteria)


def test_evaluate_excluded_wrong_province():
    resident = {
        "resident_id": "IST_003",
        "age": 30,
        "province_code": "34",
        "sex": "male",
    }
    filter_cfg = PopulationFilterConfig(
        minimum_age=18,
        province_codes=["06"],
        adult_only=True,
    )
    result = evaluate_resident(resident, filter_cfg)
    assert result.status == EligibilityStatus.EXCLUDED
    assert any("not in target provinces" in reason for reason in result.failed_criteria)


def test_evaluate_cannot_evaluate_missing_age():
    resident = {
        "resident_id": "ANK_MISSING_004",
        "age": None,
        "province_code": "06",
        "sex": "female",
    }
    filter_cfg = PopulationFilterConfig(
        minimum_age=18,
        province_codes=["06"],
        required_attributes=["age", "province_code"],
    )
    result = evaluate_resident(resident, filter_cfg)
    assert result.status == EligibilityStatus.CANNOT_EVALUATE
    assert "age" in result.missing_attributes
    assert "required attribute(s) missing" in result.explanation


def test_filter_population_batch():
    with open(RESIDENTS_FIXTURE_PATH, encoding="utf-8") as f:
        residents = json.load(f)

    filter_cfg = PopulationFilterConfig(
        minimum_age=18,
        province_codes=["06"],
        adult_only=True,
        required_attributes=["age", "province_code"],
    )

    result = filter_population(residents, filter_cfg)

    # From fixture: ANK_TEST_001 (age 28, 06) and ANK_TEST_002 (age 67, 06) are eligible
    assert result.total_evaluated == 6
    assert result.eligible_count == 2
    assert result.excluded_count == 2          # minor (16) and Istanbul (34)
    assert result.cannot_evaluate_count == 2   # missing age and missing province

    summary = result.summary()
    assert summary["eligible_count"] == 2
    assert summary["excluded_count"] == 2
    assert summary["cannot_evaluate_count"] == 2
    assert len(summary["exclusion_reasons_breakdown"]) > 0
    assert "age" in summary["missing_attributes_breakdown"]
    assert "province_code" in summary["missing_attributes_breakdown"]
