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
    dep = v["dependency_validation"]
    assert dep["validator_version"] and dep["overall_status"] in ("pass", "fail", "not_evaluable")
    check_ids = {chk["check_id"] for chk in dep["supported_joint_checks"] + dep["unverified_relationships"]}
    assert {"joint_age_marital", "joint_sex_age_marital", "joint_household_size_type", "joint_age_education", "joint_age_employment"} <= check_ids
    ds = c.get("/api/v2/data-sources").json()
    assert "optional_modules" in ds and set(ds["optional_modules"]) >= {"marital_strategy", "resident_enrichment", "households", "k1_k7_validation"}
    env = c.get("/api/v2/environments/06").json()
    assert "mobility" in env["domains"] and env["structurally_unavailable_datasets"] == []
    env34 = c.get("/api/v2/environments/34").json()
    assert any(d["source_id"] == "tuik_pkg:air_traffic" for d in env34["structurally_unavailable_datasets"])
    assert c.get("/api/v2/environments/99").status_code == 404


def test_optional_modules_status_reads_repo_registries(make_settings, tmp_path):
    from tests.conftest import REPO, make_client

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("datasets: []\n", encoding="utf-8")
    with make_client(make_settings(repo_root=REPO, data_manifest=manifest, state_dir=tmp_path / "state")) as c:
        opt = c.get("/api/v2/data-sources").json()["optional_modules"]
        assert opt["marital_strategy"]["configured"] is True and opt["marital_strategy"]["enabled"] is False
        assert opt["resident_enrichment"]["configured"] is True and "degurba_class" in opt["resident_enrichment"]["attributes"]
        assert opt["households"]["configured"] is True and opt["households"]["linkage_supported"] is False


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


@pytest.mark.parametrize("path", ["/api/v2/populations/pop-missing", "/api/v2/cohorts/nope", "/api/v2/runs/nope", "/api/v2/experiments/nope", "/api/v2/scenarios/nope"])
def test_unknown_ids_are_404(national_client, path):
    assert national_client.get(path).status_code == 404


def test_scenarios_catalog_and_experiment_definition(national_client):
    from pathlib import Path

    c = national_client

    # 1. Catalog listing
    res = c.get("/api/v2/scenarios")
    assert res.status_code == 200
    catalog = res.json()["items"]
    ids = {item["scenario_id"] for item in catalog}
    assert "transport_fare_001" in ids
    assert "energy_subsidy_001" in ids

    # 2. Scenario detail
    detail = c.get("/api/v2/scenarios/transport_fare_001").json()
    assert detail["scenario_id"] == "transport_fare_001"
    assert len(detail["questions"]) == 2

    # 3. Experiment definition generation for a cohort
    exp_def = c.get("/api/v2/scenarios/transport_fare_001/experiment-definition", params={"cohort_id": "c123"}).json()
    assert exp_def["cohort"]["cohort_id"] == "c123"
    assert exp_def["scenario"]["title"] == "Ankara Public Transportation Fare Increase"
    assert any(p["name"] == "baseline_tariff" and p["value"] == 21.0 for p in exp_def["scenario"]["parameters"])
    assert len(exp_def["task"]["options"]) >= 2

    # 4. Multi-question selection
    exp_def_q2 = c.get("/api/v2/scenarios/transport_fare_001/experiment-definition",
                       params={"cohort_id": "c123", "question_id": "q2_policy_support"}).json()
    assert "support or oppose" in exp_def_q2["task"]["instruction"].lower()

    # 5. Backward-compatible /api/v2/examples/fare-experiment
    demo = c.get("/api/v2/examples/fare-experiment", params={"cohort_id": "c123"}).json()
    assert demo["cohort"]["cohort_id"] == "c123"
    assert "options" in demo["task"]

    # 6. Experiment definition without cohort_id (for UI drafting)
    exp_def_no_cohort = c.get("/api/v2/scenarios/transport_fare_001/experiment-definition").json()
    assert exp_def_no_cohort["scenario"]["title"] == "Ankara Public Transportation Fare Increase"
    assert exp_def_no_cohort["cohort"]["cohort_id"] == ""

    # 7. Create custom scenario via POST /api/v2/scenarios
    custom_payload = {
        "scenario_id": "test_custom_001",
        "version": "1.0.0",
        "name": "Custom Rent Control Experiment",
        "description": "A simulation of 25% annual rent increase limits in Ankara.",
        "location": {"province_code": "06", "province_name": "Ankara"},
        "metadata": {"hypothetical": True, "source_note": "Custom workbench test"},
        "policy": {
            "category": "housing",
            "type": "rent_control",
            "parameters": {
                "baseline_fare": 12000.0,
                "new_fare": 15000.0,
                "increase_percentage": 25.0,
                "currency": "TL/month",
            },
        },
        "questions": [
            {
                "id": "q1_affordability",
                "text": "Can your household afford this adjusted rent level?",
                "options": [
                    {"id": "yes_comfortably", "label": "Yes comfortably"},
                    {"id": "no_stretched", "label": "No, financially stretched"},
                ],
            }
        ],
    }
    test_file = Path("experiments/policy_scenarios/scenarios/test_custom_001.yaml")
    prompt_file: Path | None = None
    try:
        create_res = c.post("/api/v2/scenarios", json=custom_payload)
        assert create_res.status_code == 201, create_res.json()
        assert create_res.json()["scenario_id"] == "test_custom_001"
        assert not test_file.exists(), "Custom scenarios must save under state_dir, not the tracked source tree"

        # Verify custom scenario appears in catalog
        cat_after = c.get("/api/v2/scenarios").json()["items"]
        assert any(item["scenario_id"] == "test_custom_001" for item in cat_after)

        # Prompt compilation also writes to state_dir rather than tracked experiments/policy_scenarios/scenarios/
        prompt_res = c.post("/api/v2/scenarios/from-prompt", json={"prompt": "Ankara transit fare rise by 15%"})
        assert prompt_res.status_code == 201, prompt_res.json()
        sid = prompt_res.json()["scenario_id"]
        prompt_file = Path("experiments/policy_scenarios/scenarios") / f"{sid}.yaml"
        assert not prompt_file.exists(), "Prompt scenarios must save under state_dir, not the tracked source tree"
    finally:
        if test_file.exists():
            test_file.unlink()
        if prompt_file is not None and prompt_file.exists():
            prompt_file.unlink()

    # 8. Invalid scenario rejects with 400 or 422
    bad_res = c.post("/api/v2/scenarios", json={"scenario_id": "123_invalid_id"})
    assert bad_res.status_code in (400, 422)


def test_alignment_regression_guards(national_client, population_id):
    c = national_client

    # Unknown province on validation returns 404, not 500
    bad_prov = c.get(f"/api/v2/populations/{population_id}/validation?province_code=99")
    assert bad_prov.status_code == 404
    assert bad_prov.json()["error"]["code"] == "unknown_province"

    # Unknown visible_fields on sample personas returns 422, not 500
    cid = _cohort(c, population_id, {"adult_only": True})
    smp = c.post(f"/api/v2/cohorts/{cid}/samples", json={"size": 5, "method": "simple_random", "seed": 7})
    assert smp.status_code == 201
    sid = smp.json()["sample_id"]
    bad_fields = c.get(f"/api/v2/samples/{sid}/personas?visible_fields=telepathic_power")
    assert bad_fields.status_code == 422
    assert bad_fields.json()["error"]["code"] == "invalid_persona_fields"

    # Prompt with curly braces, >2000 chars, and extreme numbers compiles and creates valid experiment definition
    long_prompt = ("Public policy {test} from 0 TL to 20 TL cut by 150% attendance threshold 120% " + "detail " * 350).strip()
    comp = c.post("/api/v2/scenarios/from-prompt", json={"prompt": long_prompt, "save": True})
    assert comp.status_code == 201, comp.text
    scen_id = comp.json()["scenario_id"]
    exp_def = c.get(f"/api/v2/scenarios/{scen_id}/experiment-definition", params={"cohort_id": cid})
    assert exp_def.status_code == 200, exp_def.text
    created_exp = c.post("/api/v2/experiments", json=exp_def.json())
    assert created_exp.status_code == 201, created_exp.text

    # generate_result_text_summary handles explicit None shares cleanly
    from scenarios.summary import generate_result_text_summary

    res_summary = generate_result_text_summary(
        definition=created_exp.json(),
        agg={"overall": {"options": [{"option_id": "adapt_positively", "weighted_share": None, "unweighted_share": None}]}},
        responses=[{"status": "valid", "choice": "adapt_positively", "rationale": "ok"}],
    )
    assert res_summary["valid_responses"] == 1

    # Stratified sampling redistributes spare capacity across under-capacity strata
    from societytwin.national.cohorts import stratified

    members, _ = stratified(["a", "b", "c", "d", "e"], [100.0, 1.0, 1.0, 1.0, 1.0], ["S1", "S2", "S2", "S2", "S2"], 3, seed=42)
    assert len(members) == 3

