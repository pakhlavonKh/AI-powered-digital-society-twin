"""Tests for TÜİK-anchored synthetic candidate cohort generation and provenance tagging."""

from __future__ import annotations

from scenarios.placement.cohort_synth import (
    build_standalone_demo_programs,
    build_standalone_test_cohort,
    build_tuik_anchored_candidates,
)
from societytwin.national.generator import GenerationConfig, generate
from societytwin.national.store import PopulationStore
from societytwin.national.validation import validate
from societytwin.national.vocab import Evidence
from tests.national.conftest import national_settings, store  # noqa: F401


def test_standalone_test_cohort_deterministic_and_assumed_tagged():
    programs = build_standalone_demo_programs()
    c1 = build_standalone_test_cohort(programs=programs, size=40, seed=17)
    c2 = build_standalone_test_cohort(programs=programs, size=40, seed=17)
    c3 = build_standalone_test_cohort(programs=programs, size=40, seed=99)

    assert c1.demographic_source == "standalone_test_fixture"
    assert len(c1.candidates) == 40
    assert [c.model_dump() for c in c1.candidates] == [c.model_dump() for c in c2.candidates]
    assert [c.scores for c in c1.candidates] != [c.scores for c in c3.candidates]
    assert c1.candidates[0].field_provenance["scores"] == Evidence.ASSUMED
    assert c1.candidates[0].field_provenance["liquid_budget"] == Evidence.ASSUMED


def test_tuik_anchored_cohort_preserves_population_and_tags_assumed_fields(store, tmp_path):
    pop = generate(store, GenerationConfig(synthetic_size=1500, seed=42))
    report = validate(pop.columns, pop.manifest, store)
    pop_store = PopulationStore(tmp_path / "populations")
    pop_store.write(pop, report)
    loaded = pop_store.load(pop.manifest["population_id"])

    parquet_path = loaded.directory / "records.parquet"
    bytes_before = parquet_path.read_bytes()

    programs = build_standalone_demo_programs()
    cohort = build_tuik_anchored_candidates(
        loaded,
        programs=programs,
        sample_size=50,
        seed=11,
        age_min=17,
        age_max=25,
    )

    # Population parquet file must never be mutated
    assert parquet_path.read_bytes() == bytes_before
    assert cohort.demographic_source == "tuik_population"
    assert cohort.source_population_id == loaded.population_id
    assert cohort.population_content_sha256 == loaded.manifest["content_sha256"]
    assert 1 <= len(cohort.candidates) <= 50

    for cand in cohort.candidates:
        assert cand.source_synthetic_id is not None
        assert cand.age is not None and 17 <= cand.age <= 25
        assert cand.field_provenance["province_code"] != Evidence.ASSUMED
        assert cand.field_provenance["scores"] == Evidence.ASSUMED
        assert cand.field_provenance["preferences"] == Evidence.ASSUMED
        assert cand.field_provenance["liquid_budget"] == Evidence.ASSUMED

    # Reproducibility with same seed
    cohort_again = build_tuik_anchored_candidates(
        loaded,
        programs=programs,
        sample_size=50,
        seed=11,
        age_min=17,
        age_max=25,
    )
    assert [c.model_dump() for c in cohort.candidates] == [c.model_dump() for c in cohort_again.candidates]
