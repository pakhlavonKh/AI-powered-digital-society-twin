"""Cohort filters and sampling, persona mapping, experiment schema, runner budget guard, retries and replay."""

from __future__ import annotations

import json
import math

import pyarrow as pa
import pytest
from pydantic import ValidationError

from societytwin.national.cohorts import CohortSampleRequest, SamplingError, draw, simple_random, weighted_pps
from societytwin.national.experiments import ExperimentDefinition, example_fare_definition, parse_response
from societytwin.national.generator import COLUMNS
from societytwin.national.personas import build_persona, matraix_persona
from societytwin.national.runner import CallRequest, CallResult, ReplayBackend, StubBackend, execute
from societytwin.national.store import SCHEMA, PopulationFilter


@pytest.fixture
def table(generated):
    return pa.table({c: generated.columns[c] for c in COLUMNS}, schema=SCHEMA)


def _rows(table, spec):
    return table.filter(spec.mask(table)).to_pylist()


def test_filters_province_age_adult_and_unavailable(table):
    adults = _rows(table, PopulationFilter(adult_only=True))
    assert adults and all(r["age"] >= 18 for r in adults)
    bayburt = _rows(table, PopulationFilter(province_codes=["69"]))
    assert bayburt and {r["province_code"] for r in bayburt} == {"69"}
    women_18_34 = _rows(table, PopulationFilter(sexes=["female"], age_min=18, age_max=34))
    assert all(r["sex"] == "female" and 18 <= r["age"] <= 34 for r in women_18_34)
    no_education = _rows(table, PopulationFilter(education_levels=["unavailable"]))
    assert {r["province_code"] for r in no_education} == {"69"}
    with pytest.raises(ValidationError):
        PopulationFilter(province_codes=["82"])
    with pytest.raises(ValidationError):
        PopulationFilter(marital_statuses=["single"])


def test_simple_random_is_reproducible_and_sized():
    ids = [f"id{i:03d}" for i in range(100)]
    a = simple_random(ids, [1.0] * 100, 10, seed=7)
    b = simple_random(list(reversed(ids)), [1.0] * 100, 10, seed=7)
    assert [m.synthetic_id for m in a] == [m.synthetic_id for m in b] and len({m.synthetic_id for m in a}) == 10
    assert all(math.isclose(m.inclusion_probability, 0.1) for m in a)
    assert [m.synthetic_id for m in simple_random(ids, [1.0] * 100, 10, seed=8)] != [m.synthetic_id for m in a]


def test_weighted_pps_probabilities_and_analysis_weights():
    ids = [f"id{i:03d}" for i in range(200)]
    weights = [1.0 + (i % 5) for i in range(200)]
    members = weighted_pps(ids, weights, 25, seed=3)
    assert len(members) == 25 and len({m.synthetic_id for m in members}) == 25
    assert math.isclose(sum(m.analysis_weight for m in members), sum(weights), rel_tol=1e-9)
    big = weighted_pps(["a", "b", "c", "d"], [100.0, 1.0, 1.0, 1.0], 2, seed=1)
    assert next(m for m in big if m.synthetic_id == "a").inclusion_probability == 1.0


def test_stratified_allocation_and_errors(table):
    rows = table.to_pylist()
    ids = [r["synthetic_id"] for r in rows]
    weights = [r["population_weight"] for r in rows]
    out = draw(ids, weights, CohortSampleRequest(size=60, method="stratified", seed=2, strata_field="province_code"),
               [r["province_code"] for r in rows])
    allocated = {s["stratum"]: s["drawn"] for s in out["strata"]}
    assert sum(allocated.values()) == 60 and allocated["06"] > allocated["01"] > allocated["69"]
    with pytest.raises(SamplingError):
        draw(ids[:5], weights[:5], CohortSampleRequest(size=6, seed=1))


def test_persona_for_any_province_maps_sex_and_never_married(generated):
    c = generated.columns
    i = next(i for i in range(len(c["synthetic_id"])) if c["province_code"][i] == "69" and c["age"][i] >= 18
             and c["marital_status"][i] == "never_married")
    record = {k: c[k][i] for k in COLUMNS}
    persona = build_persona(record, generated.manifest)
    assert persona["model_visible"]["sex"] in ("Male", "Female")
    assert persona["model_visible"]["marital_status"] == "Never married"
    assert persona["model_visible"]["province_name"] == "Bayburt"
    statuses = {a["field"]: a["status"] for a in persona["attributes"]}
    assert statuses["age"] == "hidden" and statuses["education_level"] == "unavailable"
    assert any(h["field"] == "age" and "ASSUMED" in h["reason"] for h in persona["hidden"])
    assert "Sex: " in persona["persona_card"] and "Never married" in persona["persona_card"]
    assert persona["eligibility"]["adult"] and persona["provenance"]["synthetic_id"] == record["synthetic_id"]
    assert build_persona(record, generated.manifest)["persona_id"] == persona["persona_id"]
    doc = matraix_persona(persona)
    assert doc["dimensions"]["dst_sex"] in ("Male", "Female")
    assert doc["dimensions"]["dst_marital_status"] == "Never married"
    assert "demo_marital_status" not in doc["dimensions"] and "gender_identity" not in doc["dimensions"]
    assert "dst_evidence_limit" not in doc["dimensions"] and doc["metadata"]["evidence_limitations"]
    with pytest.raises(ValueError):
        build_persona(record, generated.manifest, ["income"])


def test_children_are_flagged_ineligible(generated):
    c = generated.columns
    i = next(i for i, a in enumerate(c["age"]) if a < 10)
    persona = build_persona({k: c[k][i] for k in COLUMNS}, generated.manifest)
    assert persona["eligibility"]["adult"] is False
    assert {a["field"]: a["status"] for a in persona["attributes"]}["marital_status"] == "not_applicable"


def _definition(**overrides) -> ExperimentDefinition:
    payload = example_fare_definition("cht_x")
    for key, value in overrides.items():
        payload[key] = {**payload[key], **value}
    return ExperimentDefinition(**payload)


def test_definition_schema_separates_parts_and_rejects_bad_input():
    d = _definition()
    assert d.scenario.hypothetical and d.task.options[0].id == "continue_public_transport" and d.cohort.cohort_id == "cht_x"
    with pytest.raises(ValidationError, match="cite its source"):
        _definition(scenario={"hypothetical": False})
    with pytest.raises(ValidationError, match="unique"):
        _definition(task={"options": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}], "allow_other_text": False})
    with pytest.raises(ValidationError):
        _definition(model={"backend": "stub", "transport": "live"})
    with pytest.raises(ValidationError):
        _definition(model={"backend": "matraix", "transport": "live", "model": None})


@pytest.mark.parametrize("text,valid,choice", [
    ('{"choice": "walk_more", "rationale": "short trips"}', True, "walk_more"),
    ('```json\n{"choice": "other", "other_text": "bike"}\n```', True, "other"),
    ('Sure! {"choice": "car_or_carpool"} hope this helps', True, "car_or_carpool"),
    ('{"choice": "fly"}', False, None),
    ("walk_more", False, None),
    ("", False, None),
    ('["walk_more"]', False, None),
])
def test_structured_responses_are_validated(text, valid, choice):
    out = parse_response(text, _definition().task)
    assert out["valid"] is valid and out.get("choice") == choice


def _requests(n: int) -> list[CallRequest]:
    personas = [{"persona_id": f"per-{i}", "synthetic_id": f"ST-{i}", "province_code": "06"} for i in range(n)]
    return [CallRequest(f"per-{i}:1", p, 1, 1, f"system {i}", f"user {i}") for i, p in enumerate(personas)]


class FlakyBackend:
    name, label = "flaky", "test"

    def __init__(self, bad_first: int, crash: bool = False):
        self.bad_first, self.crash, self.calls = bad_first, crash, 0

    def run(self, requests):
        if self.crash:
            raise RuntimeError("backend exploded")
        out = []
        for _ in requests:
            self.calls += 1
            text = "not json" if self.calls <= self.bad_first else json.dumps({"choice": "walk_more"})
            out.append(CallResult(text, provider_call=True, input_tokens=10, output_tokens=5))
        return out


def test_budget_guard_never_exceeds_the_call_cap():
    d = _definition(execution={"max_calls": 3, "max_attempts": 1})
    outcome = execute(d, _requests(5), StubBackend(d), {}, None)
    assert outcome.calls_attempted == 3 and outcome.budget_stopped
    finals = [r for r in outcome.responses if r["is_final"]]
    assert sum(r["status"] == "budget_exhausted" for r in finals) == 2 and len(finals) == 5


def test_retries_fix_invalid_outputs_within_the_cap():
    d = _definition(execution={"max_calls": 10, "max_attempts": 2})
    backend = FlakyBackend(bad_first=2)
    outcome = execute(d, _requests(4), backend, {"x": {}}, None)
    finals = [r for r in outcome.responses if r["is_final"]]
    assert all(r["status"] == "ok" for r in finals) and outcome.calls_attempted == 6
    assert sum(r["status"] == "invalid_output" for r in outcome.responses) == 2


def test_backend_failures_are_recorded_not_raised():
    d = _definition(execution={"max_calls": 10, "max_attempts": 1})
    outcome = execute(d, _requests(2), FlakyBackend(0, crash=True), {}, None)
    assert outcome.errors and all(r["status"] == "backend_error" for r in outcome.responses)


def test_cache_and_replay_reproduce_responses_exactly():
    d = _definition(execution={"max_calls": 10, "max_attempts": 1})
    cache = {}
    first = execute(d, _requests(4), StubBackend(d), {}, lambda k, v: cache.setdefault(k, v))
    replay = execute(d, _requests(4), ReplayBackend(d, cache.get), {}, None)
    assert [r["choice"] for r in replay.responses] == [r["choice"] for r in first.responses]
    assert all(r["from_cache"] and not r["provider_call"] for r in replay.responses)
    missing = execute(d, _requests(5), ReplayBackend(d, cache.get), {}, None)
    assert [r["status"] for r in missing.responses][-1] == "cache_miss"
