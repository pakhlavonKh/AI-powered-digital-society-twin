"""Integration tests for Scenario Engine execution within the SocietyTwin national pipeline.

Verifies:
- P0: Geographic restriction enforcement: Ankara-only scenario cannot execute against an Amasya cohort
  (or any other non-Ankara cohort).
- P0: Full execution flow with stub backend preserves scenario_ref in plan and manifest.
- P0: Nonexistent question ID queries return 404 question_not_found.
- P1: Conflict handling when attempting to overwrite registered scenarios.
"""

from __future__ import annotations

import csv
import shutil
import pytest

from scenarios.adapter import get_scenario, scenario_to_experiment_definition
from tests.conftest import make_client
from tests.national.conftest import MAPPING, PACKAGE
from tests.national.test_api_v2 import _cohort


def _append_amasya_to_package(pkg_dir):
    """Clone Ankara (06) rows in the artificial package as Amasya (05, TR834) for cohort testing."""
    for filename in ("population_by_age_sex.csv", "marital_status_by_sex.csv", "education_by_sex.csv"):
        csv_path = pkg_dir / filename
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        header, body = rows[0], rows[1:]
        amasya_rows = []
        for row in body:
            if row[1] == "06":
                new_row = list(row)
                new_row[1] = "05"
                new_row[2] = "Amasya"
                new_row[3] = "TR834"
                amasya_rows.append(new_row)
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(body + amasya_rows)


def test_ankara_scenario_cannot_execute_against_amasya_cohort(make_settings, tmp_path):
    """P0: Regression test proving that an Ankara-only scenario cannot execute against an Amasya cohort."""
    pkg = tmp_path / "data" / "raw" / "tuik_package"
    shutil.copytree(PACKAGE, pkg)
    _append_amasya_to_package(pkg)
    settings = make_settings(tuik_package_dir=pkg, tuik_mapping_path=MAPPING)

    with make_client(settings) as c:
        assert c.post("/api/v2/controls/build").status_code == 200
        pop_res = c.post(
            "/api/v2/populations",
            json={"synthetic_size": 1000, "seed": 42, "province_codes": ["05", "06"], "min_records_per_province": 100},
        )
        assert pop_res.status_code == 201, pop_res.text
        pop_id = pop_res.json()["population"]["population_id"]

        # 1. Create an Amasya ('05') cohort
        amasya_cohort_id = _cohort(c, pop_id, {"province_codes": ["05"], "adult_only": True})

        # 2. Convert Ankara-only scenario ('transport_fare_001') to experiment definition targeting the Amasya cohort
        scenario = get_scenario("transport_fare_001")
        assert scenario.location.province_code == "06"
        assert scenario.target_population.province_codes == ["06"]

        definition = scenario_to_experiment_definition(
            scenario,
            cohort_id=amasya_cohort_id,
            question_id="q1_usage_change",
        )

        # 3. Create experiment and review plan: must be blocked with scenario_province_mismatch
        exp = c.post("/api/v2/experiments", json=definition).json()
        exp_id = exp["experiment_id"]

        plan = c.post(f"/api/v2/experiments/{exp_id}/plan").json()
        assert plan["executable"] is False
        blocker_codes = [b["code"] for b in plan["blockers"]]
        assert "scenario_province_mismatch" in blocker_codes
        assert any("Ankara (06)" in b["message"] and "Amasya (05)" in b["message"] for b in plan["blockers"])

        # 4. Attempting to execute the run must be rejected with HTTP 409 plan_blocked
        run_attempt = c.post(
            f"/api/v2/experiments/{exp_id}/runs",
            json={"plan_hash": plan["plan_hash"], "idempotency_key": "amasya-blocked-run-1", "confirm": True},
        )
        assert run_attempt.status_code == 409
        assert run_attempt.json()["error"]["code"] == "plan_blocked"


def test_ankara_scenario_blocked_on_non_ankara_cohort(national_client, population_id):
    """P0: Enforce geographic restrictions on default artificial fixture cohorts (Adana '01')."""
    c = national_client

    # 1. Create a non-Ankara cohort (Adana '01')
    non_ankara_cohort_id = _cohort(c, population_id, {"province_codes": ["01"], "adult_only": True})

    # 2. Convert Ankara scenario to experiment definition
    scenario = get_scenario("transport_fare_001")
    definition = scenario_to_experiment_definition(
        scenario,
        cohort_id=non_ankara_cohort_id,
        question_id="q1_usage_change",
    )
    definition["environment"]["province_code"] = "06"

    # 3. Create experiment & review plan
    exp = c.post("/api/v2/experiments", json=definition).json()
    exp_id = exp["experiment_id"]

    plan = c.post(f"/api/v2/experiments/{exp_id}/plan").json()
    assert plan["executable"] is False
    blocker_codes = [b["code"] for b in plan["blockers"]]
    assert "scenario_province_mismatch" in blocker_codes

    # 4. Attempting to start a run must be rejected with 409 conflict
    run_attempt = c.post(
        f"/api/v2/experiments/{exp_id}/runs",
        json={"plan_hash": plan["plan_hash"], "idempotency_key": "blocked-run-key-1", "confirm": True},
    )
    assert run_attempt.status_code == 409
    assert run_attempt.json()["error"]["code"] == "plan_blocked"


def test_ankara_scenario_succeeds_on_ankara_cohort_and_preserves_metadata(national_client, population_id):
    """P0: An Ankara scenario targeting an Ankara cohort succeeds and preserves scenario_ref."""
    c = national_client

    # 1. Create Ankara cohort ('06')
    ankara_cohort_id = _cohort(c, population_id, {"province_codes": ["06"], "adult_only": True})

    # 2. Convert Ankara scenario
    scenario = get_scenario("transport_fare_001")
    definition = scenario_to_experiment_definition(
        scenario,
        cohort_id=ankara_cohort_id,
        question_id="q1_usage_change",
        seed=11,
    )
    definition["environment"]["province_code"] = "06"

    # 3. Create experiment
    exp = c.post("/api/v2/experiments", json=definition).json()
    exp_id = exp["experiment_id"]

    # 4. Plan: must be executable and carry scenario_ref
    plan = c.post(f"/api/v2/experiments/{exp_id}/plan").json()
    assert plan["executable"] is True
    assert plan["blockers"] == []
    assert "scenario_ref" in plan
    assert plan["scenario_ref"]["scenario_id"] == "transport_fare_001"
    assert plan["scenario_ref"]["question_id"] == "q1_usage_change"
    assert plan["scenario_ref"]["province_codes"] == ["06"]

    # 5. Execute run with stub backend
    run_resp = c.post(
        f"/api/v2/experiments/{exp_id}/runs",
        json={"plan_hash": plan["plan_hash"], "idempotency_key": "ankara-run-key-001", "confirm": True},
    )
    assert run_resp.status_code == 202
    run = run_resp.json()["run"]
    assert run["state"] == "completed"
    assert run["valid_responses"] > 0

    # 6. Verify manifest preserves scenario_ref
    detail = c.get(f"/api/v2/runs/{run['run_id']}").json()
    assert detail["manifest"] is not None
    assert "scenario_ref" in detail["manifest"]
    manifest_ref = detail["manifest"]["scenario_ref"]
    assert manifest_ref["scenario_id"] == "transport_fare_001"
    assert manifest_ref["question_id"] == "q1_usage_change"
    assert manifest_ref["scenario_version"] == "1.0.0"


def test_api_rejects_nonexistent_question_id(national_client):
    """P0: API endpoint for scenario-to-experiment conversion rejects invalid question_id with 404."""
    c = national_client
    resp = c.get(
        "/api/v2/scenarios/transport_fare_001/experiment-definition",
        params={"question_id": "nonexistent_q_xyz"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "question_not_found"
    assert "nonexistent_q_xyz" in body["error"]["message"]


def test_api_scenario_creation_conflict(national_client):
    """P1: Attempting to register a different scenario with an existing ID returns 409 conflict."""
    c = national_client
    scenario = get_scenario("transport_fare_001")
    conflicting = scenario.model_dump(mode="json")
    conflicting["name"] = "Conflicting Scenario Name With Existing ID"

    resp = c.post("/api/v2/scenarios", json=conflicting)
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "scenario_conflict"


def test_required_attributes_enforced_in_national_plan(national_client, population_id):
    """Audit Repro 1: Adding an unavailable attribute ('income') to required_attributes blocks the plan."""
    from scenarios.eligibility import EligibilityStatus, evaluate_resident

    c = national_client
    ankara_cohort_id = _cohort(c, population_id, {"province_codes": ["06"], "adult_only": True})

    scenario = get_scenario("transport_fare_001")
    updated_tp = scenario.target_population.model_copy(
        update={"required_attributes": ["age", "province_code", "sex", "income"]}
    )
    scenario_with_income = scenario.model_copy(update={"target_population": updated_tp})

    # Standalone evaluator returns cannot_evaluate for a record lacking 'income'
    ev = evaluate_resident(
        {"synthetic_id": "ST-1", "age": 34, "province_code": "06", "sex": "female"},
        scenario_with_income.target_population,
    )
    assert ev.status == EligibilityStatus.CANNOT_EVALUATE
    assert "income" in ev.missing_attributes

    # National pipeline plan must also block when sampled personas lack 'income'
    definition = scenario_to_experiment_definition(
        scenario_with_income,
        cohort_id=ankara_cohort_id,
        question_id="q1_usage_change",
    )
    assert "income" in definition["scenario_ref"]["required_attributes"]

    exp = c.post("/api/v2/experiments", json=definition).json()
    plan = c.post(f"/api/v2/experiments/{exp['experiment_id']}/plan").json()
    assert plan["executable"] is False
    blocker_codes = [b["code"] for b in plan["blockers"]]
    assert "scenario_required_attribute_missing" in blocker_codes
    assert any("income" in b["message"] for b in plan["blockers"])


def test_stale_text_or_inconsistent_parameters_blocked_in_plan(national_client, population_id):
    """Audit Repro 2: Editing parameters without updating prompt text (or inconsistent math) blocks the plan."""
    c = national_client
    ankara_cohort_id = _cohort(c, population_id, {"province_codes": ["06"], "adult_only": True})

    scenario = get_scenario("transport_fare_001")
    definition = scenario_to_experiment_definition(
        scenario,
        cohort_id=ankara_cohort_id,
        question_id="q1_usage_change",
    )

    # Simulate stale wizard state: parameters edited to 27.3 TL / 30%, but description & question left at 20% / 25.20 TL
    for p in definition["scenario"]["parameters"]:
        if p["name"] == "new_tariff":
            p["value"] = 27.3
        elif p["name"] == "tariff_change_percent":
            p["value"] = 30.0

    exp_stale = c.post("/api/v2/experiments", json=definition).json()
    plan_stale = c.post(f"/api/v2/experiments/{exp_stale['experiment_id']}/plan").json()
    assert plan_stale["executable"] is False
    blocker_codes = [b["code"] for b in plan_stale["blockers"]]
    assert "scenario_parameter_inconsistency" in blocker_codes

    # When description and task instruction are updated to match 30% and 27.30 TL, the plan is executable
    definition["scenario"]["description"] = (
        definition["scenario"]["description"].replace("20%", "30%").replace("25.20 TL", "27.30 TL")
    )
    definition["task"]["instruction"] = (
        definition["task"]["instruction"].replace("20%", "30%").replace("25.20 TL", "27.30 TL")
    )
    exp_synced = c.post("/api/v2/experiments", json=definition).json()
    plan_synced = c.post(f"/api/v2/experiments/{exp_synced['experiment_id']}/plan").json()
    assert plan_synced["executable"] is True
    assert plan_synced["blockers"] == []


def test_api_scenarios_filtering_by_category_and_province(national_client):
    """Audit Repro 4: GET /api/v2/scenarios supports category and province query filters."""
    c = national_client

    # Filter by category=energy and province=06 -> returns energy_subsidy_001
    res_ankara_energy = c.get("/api/v2/scenarios", params={"category": "energy", "province": "06"})
    assert res_ankara_energy.status_code == 200
    items_ae = res_ankara_energy.json()["items"]
    assert [i["scenario_id"] for i in items_ae] == ["energy_subsidy_001"]

    # Filter by category=energy and province=34 (Istanbul) -> empty for Ankara-only builtin scenarios
    res_ist_energy = c.get("/api/v2/scenarios", params={"category": "energy", "province": "34"})
    assert res_ist_energy.status_code == 200
    assert res_ist_energy.json()["items"] == []

    # Filter by category=transportation and province=Ankara
    res_ankara_trans = c.get("/api/v2/scenarios", params={"category": "transportation", "province": "Ankara"})
    assert res_ankara_trans.status_code == 200
    items_at = res_ankara_trans.json()["items"]
    assert [i["scenario_id"] for i in items_at] == ["transport_fare_001"]
