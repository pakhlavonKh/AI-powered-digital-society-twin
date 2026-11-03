"""Acceptance tests for Phase 6 — Report Identity, Provenance, and Output Paths.

Covers:
1. Distinct report filenames when multiple runs use the same population:
   quality_report_{pop_slug}_{run_id}.json / .md vs quality_report_{pop_slug}.json / .md.
2. Both JSON and Markdown reports written inside specified output_dir (no hardcoded docs/).
3. Hash semantics in to_ui_dict(): population_sha256 matches population, not reference package;
   reference_package_fingerprint provided as its own field.
4. Full run provenance preserved: run ID, cohort ID, population ID, experiment ID, plan hash.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from societytwin.validation import (
    generate_ankara_sample_population,
    generate_combined_quality_report,
)


@pytest.fixture
def test_population():
    return generate_ankara_sample_population(100, seed=42)


def make_sim_results(run_id: str, pop):
    cols = pop.columns
    records = []
    for i, res_id in enumerate(cols["synthetic_id"]):
        records.append({
            "resident_id": res_id,
            "status": "valid",
            "answers": {
                "q1_usage_change": "maintain_usage" if i % 2 == 0 else "reduce_optional_trips",
            },
        })
    return {
        "scenario_id": "transport_fare_001",
        "run_id": run_id,
        "cohort_id": f"cohort-{run_id}",
        "population_id": pop.manifest["population_id"],
        "experiment_id": "exp-transit-fare-2025",
        "plan_hash": f"hash-{run_id}-plan",
        "records": records,
        "manifest": {
            "sampling_method": "stratified_random",
            "method": "stratified_random",
        },
    }


def test_phase6_distinct_filenames_for_multiple_runs_on_same_population(test_population, tmp_path: Path):
    """Running combined quality report on two runs of the same population produces distinct filenames."""
    sim1 = make_sim_results("run_alpha", test_population)
    sim2 = make_sim_results("run_beta", test_population)

    rep1 = generate_combined_quality_report(
        population=test_population,
        simulation_results=sim1,
        save_to_disk=True,
        output_dir=tmp_path,
    )

    rep2 = generate_combined_quality_report(
        population=test_population,
        simulation_results=sim2,
        save_to_disk=True,
        output_dir=tmp_path,
    )

    pop_slug = f"{test_population.manifest['population_id']}_{test_population.manifest['population_version']}"

    # 1. Distinct filenames inside tmp_path
    json1 = tmp_path / f"quality_report_{pop_slug}_run_alpha.json"
    md1 = tmp_path / f"quality_report_{pop_slug}_run_alpha.md"
    json2 = tmp_path / f"quality_report_{pop_slug}_run_beta.json"
    md2 = tmp_path / f"quality_report_{pop_slug}_run_beta.md"

    assert json1.is_file(), f"Expected {json1} to exist"
    assert md1.is_file(), f"Expected {md1} to exist"
    assert json2.is_file(), f"Expected {json2} to exist"
    assert md2.is_file(), f"Expected {md2} to exist"

    # 2. Both files are in tmp_path, neither in hardcoded docs/
    assert json1.parent == tmp_path
    assert md1.parent == tmp_path
    assert json2.parent == tmp_path
    assert md2.parent == tmp_path

    # Verify content differs by run_id
    data1 = json.loads(json1.read_text(encoding="utf-8"))
    data2 = json.loads(json2.read_text(encoding="utf-8"))
    assert data1["simulation_run_id"] == "run_alpha"
    assert data2["simulation_run_id"] == "run_beta"


def test_phase6_filename_without_simulation_run(test_population, tmp_path: Path):
    """When no simulation run is present, filenames do not have a run_id suffix."""
    rep = generate_combined_quality_report(
        population=test_population,
        save_to_disk=True,
        output_dir=tmp_path,
    )

    pop_slug = f"{test_population.manifest['population_id']}_{test_population.manifest['population_version']}"
    expected_json = tmp_path / f"quality_report_{pop_slug}.json"
    expected_md = tmp_path / f"quality_report_{pop_slug}.md"

    assert expected_json.is_file()
    assert expected_md.is_file()
    assert rep.simulation_run_id is None


def test_phase6_hash_semantics_in_to_ui_dict(test_population):
    """population_sha256 matches the population artifact hash, NOT the reference package fingerprint."""
    sim = make_sim_results("run_hash_test", test_population)
    rep = generate_combined_quality_report(
        population=test_population,
        simulation_results=sim,
        save_to_disk=False,
    )

    ui_dict = rep.to_ui_dict()

    expected_pop_hash = test_population.manifest.get("content_sha256")
    assert expected_pop_hash is not None
    assert len(expected_pop_hash) == 64

    # 1. population_sha256 matches population, NOT reference package
    assert ui_dict["population_sha256"] == expected_pop_hash
    assert ui_dict["population_sha256"] != rep.reference_package_fingerprint

    # 2. reference_package_fingerprint is present as its own field
    assert "reference_package_fingerprint" in ui_dict
    assert ui_dict["reference_package_fingerprint"] == rep.reference_package_fingerprint


def test_phase6_full_run_provenance_preserved(test_population):
    """Simulation evaluation report preserves run_id, cohort_id, population_id, experiment_id, plan_hash."""
    sim = make_sim_results("run_prov_test", test_population)
    rep = generate_combined_quality_report(
        population=test_population,
        simulation_results=sim,
        save_to_disk=False,
    )

    sim_rep = rep.simulation_report
    assert sim_rep is not None

    # Top-level fields on simulation report
    assert sim_rep.run_id == "run_prov_test"
    assert sim_rep.cohort_id == "cohort-run_prov_test"
    assert sim_rep.population_id == test_population.manifest["population_id"]
    assert sim_rep.experiment_id == "exp-transit-fare-2025"
    assert sim_rep.plan_hash == "hash-run_prov_test-plan"

    # Provenance dictionary on simulation report
    assert sim_rep.provenance["run_id"] == "run_prov_test"
    assert sim_rep.provenance["cohort_id"] == "cohort-run_prov_test"
    assert sim_rep.provenance["population_id"] == test_population.manifest["population_id"]
    assert sim_rep.provenance["experiment_id"] == "exp-transit-fare-2025"
    assert sim_rep.provenance["plan_hash"] == "hash-run_prov_test-plan"

    # Preserved in combined quality report as well
    assert rep.simulation_run_id == "run_prov_test"
    assert rep.cohort_id == "cohort-run_prov_test"
    assert rep.experiment_id == "exp-transit-fare-2025"
    assert rep.plan_hash == "hash-run_prov_test-plan"
