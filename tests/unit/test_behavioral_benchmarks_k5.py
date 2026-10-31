"""Unit tests for Phase 5 Behavioral Benchmark Research (K5).

Tests:
1. BenchmarkSpec and BenchmarkBundle models: validation, typing, and invariants.
2. Missing benchmark is reported as unavailable with an explicit reason (core prompt requirement).
3. Stated intention vs revealed behavior non-equivalence distinction is enforced.
4. Canonical Ankara fare increase benchmark bundle: structure, classification, and metadata.
5. Search, filtering, fingerprint reproducibility, and Markdown rendering.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from societytwin.validation import (
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkBundle,
    BenchmarkProvenance,
    BenchmarkSpec,
    BenchmarkStatus,
    ComparabilityNotes,
    EvidenceType,
    MeasurementDefinition,
    get_ankara_transit_fare_bundle,
)


def test_benchmark_models_and_evidence_typology():
    """Verify BenchmarkSpec and BenchmarkBundle instantiation across all four evidence types."""
    prov = BenchmarkProvenance(
        source_id="test_src_1",
        title="Test Transport Study",
        publisher_agency="Test Agency",
        publication_year=2024,
        citation="Test Author (2024). Test Citation.",
        url="https://example.invalid/study",
        geography="06",
        geography_name="Ankara",
        sample_size=1000,
        sample_denominator="Surveyed residents",
        collection_method="Questionnaire",
    )
    meas = MeasurementDefinition(
        metric_name="test_elasticity",
        metric_unit="coefficient",
        target_variable="demand_change",
        formula_or_description="(dQ/Q) / (dP/P)",
    )
    comp = ComparabilityNotes(
        scenario_id="transport_fare_001",
        applicability_scope="Urban transit users",
        is_direct_ground_truth=False,
        stated_vs_revealed_distinction="Stated intentions reflect survey declarations, not observed card taps.",
        limitations=("Hypothetical bias",),
    )

    spec = BenchmarkSpec(
        benchmark_id="test_bench_1",
        name="Test Benchmark",
        scenario_id="transport_fare_001",
        status="available",
        evidence_type="literature_estimate",
        provenance=prov,
        measurement=meas,
        comparability=comp,
        observed_value=-0.33,
        observed_range=(-0.5, -0.2),
        unavailability_reason=None,
    )

    assert spec.is_available is True
    assert spec.is_ground_truth is False
    assert spec.evidence_type == "literature_estimate"

    bundle = BenchmarkBundle(
        bundle_id="test_bundle",
        scenario_id="transport_fare_001",
        title="Test Bundle",
        description="A test bundle",
        benchmarks=(spec,),
    )
    assert bundle.schema_version == BENCHMARK_SCHEMA_VERSION
    assert len(bundle.benchmarks) == 1
    assert bundle.get_benchmark("test_bench_1") == spec


def test_missing_benchmark_is_reported_as_unavailable():
    """CORE REQUIREMENT: Missing benchmarks must be reported as unavailable with an explicit reason.

    Never fabricate ground truth when data does not exist.
    """
    prov = BenchmarkProvenance(
        source_id="missing_ego_model",
        title="Nonexistent Econometric Model of Ankara Fare Elasticity",
        publisher_agency="EGO Genel Müdürlüğü",
        publication_year=2024,
        citation="Unpublished / Nonexistent study.",
        geography="06",
        geography_name="Ankara",
        sample_denominator="Transit riders",
        collection_method="None",
    )
    meas = MeasurementDefinition(
        metric_name="observed_elasticity",
        metric_unit="coefficient",
        target_variable="ridership_ratio",
        formula_or_description="Observed elasticity",
    )
    comp = ComparabilityNotes(
        scenario_id="transport_fare_001",
        applicability_scope="Ankara transit",
        is_direct_ground_truth=True,
        stated_vs_revealed_distinction="Revealed turnstile taps, but unmodelled.",
    )

    spec = BenchmarkSpec(
        benchmark_id="missing_benchmark_spec",
        name="Missing Benchmark",
        scenario_id="transport_fare_001",
        status="unavailable",
        evidence_type="observed_behavior",
        provenance=prov,
        measurement=meas,
        comparability=comp,
        observed_value=None,
        observed_range=None,
        unavailability_reason="No econometric model or micro-data isolating fare elasticity has been published by EGO.",
    )

    # Missing benchmark invariants:
    assert spec.status == "unavailable"
    assert spec.is_available is False
    assert spec.observed_value is None
    assert spec.observed_range is None
    assert spec.unavailability_reason is not None
    assert "No econometric model" in spec.unavailability_reason


def test_stated_vs_revealed_distinction_enforced():
    """Verify that stated intention is NOT equivalent to observed ridership decrease."""
    bundle = get_ankara_transit_fare_bundle()

    # Stated intention survey benchmark
    stated_bench = bundle.get_benchmark("ankara_stated_travel_intention")
    assert stated_bench.evidence_type == "survey_response"
    assert stated_bench.is_ground_truth is False
    assert "STATED INTENTION IS NOT EQUIVALENT TO REVEALED RIDERSHIP DECREASE" in stated_bench.comparability.stated_vs_revealed_distinction
    assert "hypothetical bias" in stated_bench.comparability.stated_vs_revealed_distinction.lower()

    # Observed behavior benchmark (EGO)
    ego_bench = bundle.get_benchmark("ankara_ego_observed_elasticity")
    assert ego_bench.evidence_type == "observed_behavior"
    assert "card validations" in ego_bench.comparability.stated_vs_revealed_distinction.lower()
    assert ego_bench.status == "unavailable"


def test_canonical_ankara_transit_fare_bundle_structure():
    """Verify that the canonical Ankara fare increase benchmark bundle meets all requirements."""
    bundle = get_ankara_transit_fare_bundle()

    assert bundle.scenario_id == "transport_fare_001"
    assert len(bundle.benchmarks) == 6

    avail = bundle.available_benchmarks()
    unavail = bundle.unavailable_benchmarks()

    # Check partition
    assert len(avail) == 4
    assert len(unavail) == 2

    # Verify unavailable benchmarks
    unavail_ids = {b.benchmark_id for b in unavail}
    assert "ankara_ego_observed_elasticity" in unavail_ids
    assert "ankara_stated_travel_intention" in unavail_ids

    for b in unavail:
        assert b.observed_value is None
        assert b.unavailability_reason is not None
        assert len(b.unavailability_reason) > 20

    # Verify available benchmarks
    avail_ids = {b.benchmark_id for b in avail}
    assert "literature_transit_fare_elasticity" in avail_ids
    assert "tuik_tr51_household_transport_expenditure_share" in avail_ids
    assert "auap_ankara_transit_modal_split" in avail_ids
    assert "hypothetical_agent_fare_reduction_assumption" in avail_ids

    # 1. Literature elasticity: check range and values
    lit_b = bundle.get_benchmark("literature_transit_fare_elasticity")
    assert lit_b.observed_value == -0.33
    assert lit_b.observed_range == (-0.50, -0.20)
    assert lit_b.evidence_type == "literature_estimate"
    assert lit_b.provenance.url == "https://www.vtpi.org/tranelas.pdf"

    # 2. TÜİK TR51 expenditure share: check exact published number
    tuik_b = bundle.get_benchmark("tuik_tr51_household_transport_expenditure_share")
    assert tuik_b.observed_value == 23.6
    assert tuik_b.provenance.geography == "TR51"
    assert tuik_b.evidence_type == "survey_response"

    # 3. AUAP transit modal split: check published share
    auap_b = bundle.get_benchmark("auap_ankara_transit_modal_split")
    assert auap_b.observed_value == 0.32
    assert auap_b.provenance.geography == "06"
    assert auap_b.evidence_type == "survey_response"

    # 4. Hypothetical scenario assumption: no fabricated numbers
    hypo_b = bundle.get_benchmark("hypothetical_agent_fare_reduction_assumption")
    assert hypo_b.evidence_type == "hypothetical_assumption"
    assert hypo_b.observed_value is None
    assert "ENTIRELY HYPOTHETICAL" in hypo_b.comparability.stated_vs_revealed_distinction


def test_bundle_search_and_markdown_rendering():
    """Verify bundle query methods, fingerprint stability, and Markdown rendering."""
    bundle = get_ankara_transit_fare_bundle()

    # Query by evidence type
    obs_benchmarks = bundle.by_evidence_type("observed_behavior")
    assert len(obs_benchmarks) == 1
    assert obs_benchmarks[0].benchmark_id == "ankara_ego_observed_elasticity"

    survey_benchmarks = bundle.by_evidence_type("survey_response")
    assert len(survey_benchmarks) == 3

    lit_benchmarks = bundle.by_evidence_type("literature_estimate")
    assert len(lit_benchmarks) == 1

    hypo_benchmarks = bundle.by_evidence_type("hypothetical_assumption")
    assert len(hypo_benchmarks) == 1

    # Fingerprint stability
    fp1 = bundle.bundle_fingerprint
    fp2 = bundle.bundle_fingerprint
    assert fp1 == fp2
    assert len(fp1) == 64

    # Markdown rendering
    md = bundle.to_markdown()
    assert "# Behavioral Benchmark Inventory" in md
    assert "transport_fare_001" in md
    assert "ankara_ego_observed_elasticity" in md
    assert "literature_transit_fare_elasticity" in md
    assert "tuik_tr51_household_transport_expenditure_share" in md
    assert "UNAVAILABLE" in md
    assert "AVAILABLE" in md
