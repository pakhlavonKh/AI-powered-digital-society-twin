"""/api/v2 contract: overview, generation, filters, cohorts, personas, plans, runs, results, replay and guards."""

from __future__ import annotations

import pytest

from societytwin.national.experiments import example_fare_definition


def test_overview_before_anything_is_built(national_settings):
    from tests.conftest import make_client

    with make_client(national_settings) as c:
        body = c.get("/api/v2/overview").json()
        assert body["controls"]["status"] == "not_built" and body["populations"] == [] and body["latest_run"] is None
        r = c.post("/api/v2/populations", json={"synthetic_size": 100})
        assert r.status_code == 503 and r.json()["error"]["code"] == "controls_not_built"
        provinces = c.get("/api/v2/geography/provinces").json()
        assert provinces["province_count"] == 81 and provinces["provinces_with_population_controls"] == 0


def test_generation_summary_filters_and_province_coverage(national_client, population_id):
    c = national_client
    again = c.post("/api/v2/populations", json={"synthetic_size": 3000, "seed": 42}).json()
    assert again["created"] is False and again["population"]["population_id"] == population_id
    s = c.get(f"/api/v2/populations/{population_id}/summary").json()
    assert s["records"] == 3000 and {p["province_code"] for p in s["provinces"]} == {"01", "06", "69"}
    edu = next(d for d in s["distributions"] if d["field"] == "education_level")
    assert edu["available"] and any(cat["value"] == "unavailable" for cat in edu["categories"])
    one = c.get(f"/api/v2/populations/{population_id}/summary", params={"province_codes": ["69"], "adult_only": True}).json()
    assert {p["province_code"] for p in one["provinces"]} == {"69"}
    assert next(d for d in one["distributions"] if d["field"] == "education_level")["available"] is False
    assert c.get(f"/api/v2/populations/{population_id}/summary", params={"province_codes": ["82"]}).status_code == 422
    geo_ = c.get("/api/v2/geography/provinces", params={"population_id": population_id}).json()
    assert geo_["provinces_with_population_controls"] == 3
    assert next(p for p in geo_["provinces"] if p["province_code"] == "34")["records"] == 0
    page = c.get(f"/api/v2/populations/{population_id}/records", params={"limit": 5, "sort": "age", "direction": "desc"}).json()
    assert len(page["items"]) == 5 and page["items"][0]["age"] >= page["items"][-1]["age"]
    assert c.get(f"/api/v2/populations/{population_id}/records", params={"limit": 500}).status_code == 422
    v = c.get(f"/api/v2/populations/{population_id}/validation", params={"province_code": "06"}).json()
    assert [p["province_code"] for p in v["provinces"]] == ["06"] and v["constraint_violations"] == 0
    env = c.get("/api/v2/environments/06").json()
    assert "mobility" in env["domains"] and env["structurally_unavailable_datasets"] == []
    env34 = c.get("/api/v2/environments/34").json()
    assert any(d["source_id"] == "tuik_pkg:air_traffic" for d in env34["structurally_unavailable_datasets"])
    assert c.get("/api/v2/environments/99").status_code == 404


def test_record_detail_shows_visible_and_hidden_attributes(national_client, population_id):
    c = national_client
    rec = c.get(f"/api/v2/populations/{population_id}/records", params={"adult_only": True, "limit": 1}).json()["items"][0]
    detail = c.get(f"/api/v2/populations/{population_id}/records/{rec['synthetic_id']}").json()
    assert "sex" in detail["persona"]["model_visible"] and detail["persona"]["kind_label"].startswith("Fictional")
    narrowed = c.get(f"/api/v2/populations/{population_id}/records/{rec['synthetic_id']}", params={"visible_fields": ["province_name"]}).json()
    assert list(narrowed["persona"]["model_visible"]) == ["province_name"]
    assert any(h["field"] == "sex" for h in narrowed["persona"]["hidden"])


def _cohort(c, population_id, filters) -> str:
    r = c.post("/api/v2/cohorts", json={"name": "test", "population_id": population_id, "filters": filters})
    assert r.status_code == 201, r.text
    return r.json()["cohort_id"]


def test_full_experiment_flow_with_stub_backend(national_client, population_id):
    c = national_client
    preview = c.post("/api/v2/cohorts/preview", json={"population_id": population_id, "filters": {"adult_only": True}}).json()
    assert preview["minors"] == 0 and preview["eligible_records"] > 0
    cid = _cohort(c, population_id, {"adult_only": True})
    sample = c.post(f"/api/v2/cohorts/{cid}/samples", json={"size": 12, "method": "weighted", "seed": 4}).json()
    assert sample["selected"] == 12
    assert c.post(f"/api/v2/cohorts/{cid}/samples", json={"size": 12, "method": "weighted", "seed": 4}).json()["sample_id"] == sample["sample_id"]
    personas = c.get(f"/api/v2/samples/{sample['sample_id']}/personas").json()
    assert personas["total"] == 12 and all(p["eligibility"]["adult"] for p in personas["items"])
    definition = example_fare_definition(cid)
    definition["environment"]["province_code"] = None
    exp = c.post("/api/v2/experiments", json=definition).json()
    plan = c.post(f"/api/v2/experiments/{exp['experiment_id']}/plan").json()
    assert plan["executable"] and plan["active_personas"] == 20 and plan["calls"]["planned"] == 20
    assert plan["cost"]["estimate_usd"] == 0.0 and any("Stub backend" in w for w in plan["warnings"])
    bad = c.post(f"/api/v2/experiments/{exp['experiment_id']}/runs", json={"plan_hash": plan["plan_hash"], "idempotency_key": "abcdefgh"})
    assert bad.status_code == 422  # explicit confirmation is required
    run = c.post(f"/api/v2/experiments/{exp['experiment_id']}/runs",
                 json={"plan_hash": plan["plan_hash"], "idempotency_key": "run-key-0001", "confirm": True}).json()["run"]
    assert run["state"] == "completed" and run["valid_responses"] == 20 and run["provider_calls"] == 0
    detail = c.get(f"/api/v2/runs/{run['run_id']}").json()
    assert detail["is_stub"] and detail["manifest"]["population"]["population_id"] == population_id
    assert detail["manifest"]["persona_template_version"] and detail["manifest"]["definition_hash"] == exp["definition_hash"]
    responses = c.get(f"/api/v2/runs/{run['run_id']}/responses").json()
    assert responses["total"] == 20 and all(r["choice"] for r in responses["items"])
    agg = c.get(f"/api/v2/runs/{run['run_id']}/aggregate", params={"group_by": ["sex", "province_code"], "min_group": 1}).json()
    assert agg["is_stub"] and math_close(sum(o["weighted_share"] for o in agg["overall"]["options"]), 1.0)
    assert not any(g["suppressed"] for g in agg["by"]["sex"]["groups"])
    small = c.get(f"/api/v2/runs/{run['run_id']}/aggregate", params={"group_by": ["sex"], "min_group": 100}).json()
    assert all(g["suppressed"] and "options" not in g for g in small["by"]["sex"]["groups"])
    assert small["by"]["sex"]["comparisons"] == []
    assert c.get(f"/api/v2/runs/{run['run_id']}/aggregate", params={"group_by": ["weight"]}).status_code == 422
    replay = c.post(f"/api/v2/runs/{run['run_id']}/replay", json={"idempotency_key": "replay-0001"}).json()["run"]
    assert replay["state"] == "completed" and replay["kind"] == "replay"
    again = c.post(f"/api/v2/experiments/{exp['experiment_id']}/runs",
                   json={"plan_hash": plan["plan_hash"], "idempotency_key": "run-key-0002", "confirm": True})
    assert again.status_code == 409
    listed = c.get("/api/v2/runs").json()
    assert listed["total"] == 2


def math_close(a, b):
    return abs(a - b) < 1e-9


def test_plans_block_minors_oversized_samples_and_unavailable_backends(national_client, population_id):
    c = national_client
    cid = _cohort(c, population_id, {})
    definition = example_fare_definition(cid)
    definition["cohort"]["sample_size"] = 40
    definition["execution"]["max_calls"] = 30
    exp = c.post("/api/v2/experiments", json=definition).json()
    codes = {b["code"] for b in c.post(f"/api/v2/experiments/{exp['experiment_id']}/plan").json()["blockers"]}
    assert {"minors_in_adult_task", "call_cap_below_plan"} <= codes
    definition = example_fare_definition(_cohort(c, population_id, {"adult_only": True}))
    definition["model"] = {"backend": "matraix", "transport": "live", "model": "anthropic/test-model", "temperature": 0}
    definition["execution"]["max_cost_usd"] = 1.0
    exp = c.post("/api/v2/experiments", json=definition).json()
    plan = c.post(f"/api/v2/experiments/{exp['experiment_id']}/plan").json()
    codes = {b["code"] for b in plan["blockers"]}
    assert {"runtime_unavailable", "live_execution_disabled", "credentials_missing", "cost_cap_unenforceable"} <= codes
    run = c.post(f"/api/v2/experiments/{exp['experiment_id']}/runs",
                 json={"plan_hash": plan["plan_hash"], "idempotency_key": "blocked-0001", "confirm": True})
    assert run.status_code == 409 and run.json()["error"]["code"] == "plan_blocked"


def test_mutations_are_loopback_only(national_settings):
    from fastapi.testclient import TestClient

    from societytwin.api.app import create_app

    with TestClient(create_app(national_settings, start_worker=False)) as c:
        assert c.post("/api/v2/controls/build").status_code == 403
        assert c.get("/api/v2/overview").status_code == 200


@pytest.mark.parametrize("path", ["/api/v2/populations/pop-missing", "/api/v2/cohorts/nope", "/api/v2/runs/nope", "/api/v2/experiments/nope"])
def test_unknown_ids_are_404(national_client, path):
    assert national_client.get(path).status_code == 404
