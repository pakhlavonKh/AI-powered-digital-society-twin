"""National generator: size, determinism, coverage, weights, dependency model, constraints and validation."""

from __future__ import annotations

import math
from collections import Counter

import pytest

from societytwin.national import geography as geo
from societytwin.national.constraints import EDUCATION_MIN_COMPLETION_AGE, check_records
from societytwin.national.fitting import Margin, ipf_2d, largest_remainder, rake
from societytwin.national.generator import GenerationConfig, GenerationError, generate
from societytwin.national.validation import validate
from societytwin.national.vocab import NOT_APPLICABLE, Evidence


def _weighted(columns, *keys, where=lambda i: True):
    out = Counter()
    for i in range(len(columns["synthetic_id"])):
        if where(i):
            out[tuple(columns[k][i] for k in keys)] += columns["population_weight"][i]
    return out


def test_largest_remainder_preserves_totals_and_floors():
    alloc = largest_remainder({"a": 1.0, "b": 1.0, "c": 1.0}, 10)
    assert sum(alloc.values()) == 10 and sorted(alloc.values()) == [3, 3, 4]
    floored = largest_remainder({"a": 1000.0, "b": 1.0}, 10, {"a": 0, "b": 3})
    assert floored == {"a": 7, "b": 3}


def test_ipf_matches_margins_and_keeps_structural_zeros():
    fit = ipf_2d([60.0, 40.0], [30.0, 70.0], [[1, 1], [0, 1]])
    assert fit.converged and fit.table[1][0] == 0.0
    assert math.isclose(sum(fit.table[0]), 60) and math.isclose(fit.table[0][0] + fit.table[1][0], 30)


def test_raking_reaches_targets_and_reports_unreachable_cells():
    w = [1.0, 1.0, 1.0, 1.0]
    rr = rake(w, [Margin("a", [("x",), ("y",)], [30.0, 10.0], [0, 0, 1, 1]),
                  Margin("b", [("p",), ("q",), ("r",)], [20.0, 20.0, 5.0], [0, 1, 0, 1])])
    assert rr.unreachable_cells and rr.unreachable_cells[0]["cell"] == ["r"]


def test_requested_size_and_all_covered_provinces(generated):
    c = generated.columns
    assert len(c["synthetic_id"]) == 5000 and len(set(c["synthetic_id"])) == 5000
    assert set(c["province_code"]) == {"01", "06", "69"}
    assert all(code in geo.BY_CODE for code in c["province_code"])
    assert generated.manifest["scope"]["province_count"] == 3
    assert len(generated.manifest["scope"]["excluded"]) == 78


def test_same_seed_is_identical_and_other_seed_differs(store, generated):
    again = generate(store, GenerationConfig(synthetic_size=5000, seed=42))
    other = generate(store, GenerationConfig(synthetic_size=5000, seed=43))
    assert again.manifest["content_sha256"] == generated.manifest["content_sha256"]
    assert again.manifest["population_id"] == generated.manifest["population_id"]
    assert other.manifest["content_sha256"] != generated.manifest["content_sha256"]
    # allocation is deterministic; only within-cell draws change with the seed
    assert Counter(other.columns["age_group"]) == Counter(generated.columns["age_group"])
    assert other.columns["marital_status"] != generated.columns["marital_status"]


def test_single_province_generation_uses_the_same_generator(store):
    pop = generate(store, GenerationConfig(synthetic_size=800, seed=1, provinces=("69",)))
    assert set(pop.columns["province_code"]) == {"69"} and len(pop.columns["synthetic_id"]) == 800
    assert pop.manifest["scope"]["label"] == "Bayburt"
    with pytest.raises(GenerationError):
        generate(store, GenerationConfig(synthetic_size=10, provinces=("34",)))


def test_weights_are_positive_and_reproduce_the_controls(store, generated):
    c = generated.columns
    assert all(w > 0 and math.isfinite(w) for w in c["population_weight"])
    for code in ("01", "06", "69"):
        sel = store.best("population_age_sex", geo.province(code), 2025)
        source = sel.counts()
        synth = _weighted(c, "age_group", "sex", where=lambda i: c["province_code"][i] == code)
        assert math.isclose(sum(synth.values()), sum(source.values()), rel_tol=1e-9)
    for code in ("01", "06"):  # large enough that every marital cell has records
        marital = store.best("marital_status_sex", geo.province(code), 2025).counts()
        got = _weighted(c, "sex", "marital_status", where=lambda i: c["province_code"][i] == code and c["age"][i] >= 15)
        assert set(got) == set(marital)
        for k, target in marital.items():
            assert math.isclose(got[k], target, rel_tol=1e-6), (code, k)


def test_universe_rule_children_have_no_marital_status(generated):
    c = generated.columns
    for age, status in zip(c["age"], c["marital_status"]):
        assert (status == NOT_APPLICABLE) == (age < 15)


def test_education_structural_zeros_and_unavailable_province(generated):
    c = generated.columns
    profiles = generated.profiles
    assert profiles["prov-01"]["fields"]["education_level"]["evidence"] == Evidence.MARGINAL_INFERENCE
    assert profiles["prov-01"]["fields"]["education_level"]["structural_zeros"] is True
    bayburt = profiles["prov-69"]["fields"]["education_level"]
    assert bayburt["evidence"] == Evidence.UNAVAILABLE and "2026" in bayburt["reason"]
    for code, age, edu in zip(c["province_code"], c["age"], c["education_level"]):
        if code == "69":
            assert edu is None
        elif edu not in (None, NOT_APPLICABLE):
            assert age >= EDUCATION_MIN_COMPLETION_AGE.get(edu, 0)
    assert profiles["prov-06"]["fields"]["marital_status"]["unobserved_joint_with"] == ["age_group"]
    assert profiles["prov-06"]["fields"]["age"]["evidence"] == Evidence.ASSUMED


def test_small_sizes_collapse_cells_without_losing_population(store):
    pop = generate(store, GenerationConfig(synthetic_size=60, seed=3))
    bayburt = next(a for a in pop.manifest["allocation"]["provinces"] if a["province_code"] == "69")
    assert bayburt["records"] >= 1
    rep = sum(w for code, w in zip(pop.columns["province_code"], pop.columns["population_weight"]) if code == "69")
    assert math.isclose(rep, bayburt["population"], rel_tol=1e-6)


def test_floor_oversamples_small_provinces_and_weights_correct_for_it(store):
    pop = generate(store, GenerationConfig(synthetic_size=3000, seed=5, min_records_per_province=400))
    counts = Counter(pop.columns["province_code"])
    assert counts["69"] >= 400
    rep = sum(w for code, w in zip(pop.columns["province_code"], pop.columns["population_weight"]) if code == "69")
    assert math.isclose(rep, next(a["population"] for a in pop.manifest["allocation"]["provinces"] if a["province_code"] == "69"))


def test_validation_reports_fit_noise_and_zero_violations(store, generated):
    report = validate(generated.columns, generated.manifest, store)
    assert report["constraint_violations"] == 0
    ankara = next(p for p in report["provinces"] if p["province_code"] == "06")
    statuses = {t["table_id"]: (t["weighted_status"], t["record_status"]) for t in ankara["tables"]}
    assert statuses["population_age_sex"][0] == "fit_by_construction"
    assert statuses["marital_status_sex"][0] == "fit_by_construction"
    assert statuses["education_sex"][0] == "fit_by_construction"
    assert all(s[1] in ("within_sampling_noise", "not_assessed_small_sample") for s in statuses.values())
    bayburt = next(p for p in report["provinces"] if p["province_code"] == "69")
    assert {f["field"] for f in bayburt["fields_without_source"]} >= {"education_level"}
    assert report["tolerance_justification"]["familywise_alpha"]
    assert "does not show that AI personas behave like real people" in report["statement"]


def test_constraint_checks_detect_injected_violations(generated):
    c = {k: list(v) for k, v in generated.columns.items()}
    child = next(i for i, a in enumerate(c["age"]) if a < 10)
    c["marital_status"][child] = "married"
    c["province_name"][0] = "Wrong"
    c["population_weight"][1] = -1.0
    results = {r["rule_id"]: r["violations"] for r in check_records(c, generated.profiles)}
    assert results["source_universe"] >= 1 and results["geography_consistent"] >= 1 and results["weight_positive_finite"] >= 1


def test_unattainable_margin_is_reported_everywhere_not_forced(store, monkeypatch):
    """A margin raking cannot meet in a province is dropped and reported in the calibration report, the field provenance
    (persona limitations) and the validation report; it is never forced onto degenerate weights. Adana (about 1,650
    records here) is made to fail; artificial Bayburt (about 50 records) cannot meet its marital margin at all."""
    import societytwin.national.generator as gen
    from societytwin.national.fitting import RakeReport
    from societytwin.national.personas import build_persona

    real = gen.rake

    def failing_for_adana(weights, margins, **kw):
        if 1000 < len(weights) < 2500 and margins[-1].name == "marital_status_sex":
            return RakeReport(False, 1, 0.5, [])
        return real(weights, margins, **kw)

    monkeypatch.setattr(gen, "rake", failing_for_adana)
    pop = generate(store, GenerationConfig(synthetic_size=5000, seed=42))
    cal = {c["province_code"]: c for c in pop.manifest["calibration"]}
    assert {code: [d["margin"] for d in c["margins_not_calibrated"]] for code, c in cal.items()} == {
        "01": ["marital_status_sex"], "06": [], "69": ["marital_status_sex"]}
    assert cal["01"]["margins"] == ["population_age_sex", "education_sex"]
    assert cal["01"]["margins_not_calibrated"][0]["reason"].startswith("Not imposed on the weights")
    field = pop.manifest["profiles"]["prov-01"]["fields"]["marital_status"]
    assert field["calibration"]["imposed"] is False and any("not calibrated to marital_status_sex" in x for x in field["limitations"])
    assert pop.manifest["profiles"]["prov-06"]["fields"]["marital_status"]["calibration"] == {"imposed": True}
    assert min(pop.columns["population_weight"]) > 0
    report = validate(pop.columns, pop.manifest, store)
    adana = next(t for p in report["provinces"] if p["province_code"] == "01" for t in p["tables"] if t["table_id"] == "marital_status_sex")
    assert adana["weighted_status"] == "not_calibrated" and adana["notes"][0].startswith("Not imposed on the weights")
    national = next(t for t in report["national"]["tables"] if t["table_id"] == "marital_status_sex")
    assert national["weighted_status"] == "partially_calibrated" and national["provinces_not_calibrated"] == ["01", "69"]
    assert "Adana (01), Bayburt (69)" in national["notes"][0]
    record = next(i for i, c in enumerate(pop.columns["province_code"]) if c == "01" and pop.columns["age"][i] >= 18)
    persona = build_persona({k: pop.columns[k][record] for k in pop.columns}, pop.manifest)
    assert any("not calibrated to marital_status_sex" in x for x in persona["limitations"])


def test_degenerate_weights_are_rejected_by_the_ratio_bounds(store, monkeypatch):
    import societytwin.national.generator as gen

    real = gen.rake

    def squeeze_one_record(weights, margins, **kw):
        rr = real(weights, margins, **kw)
        if margins[-1].name == "education_sex" and 1000 < len(weights) < 2500:
            weights[0] *= 0.001  # pretend raking only "converged" by nearly deleting a record
        return rr

    monkeypatch.setattr(gen, "rake", squeeze_one_record)
    pop = generate(store, GenerationConfig(synthetic_size=5000, seed=42))
    dropped = {c["province_code"]: c["margins_not_calibrated"] for c in pop.manifest["calibration"]}
    assert [d["margin"] for d in dropped["01"]] == ["education_sex"]
    assert "accepted range ×0.05–×20" in dropped["01"][0]["reason"]
    assert all(c["weight_ratio_bounds"] == [0.05, 20.0] for c in pop.manifest["calibration"])
    assert min(pop.columns["population_weight"]) > 0
