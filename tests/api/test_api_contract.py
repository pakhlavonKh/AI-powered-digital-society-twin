import json

from tests.conftest import make_client

V1 = "/api/v1"


def test_health_is_liveness_only(client):
    body = client.get(f"{V1}/health").json()
    assert body["status"] == "ok" and "capabilities" in body["note"]


def test_capabilities_offline(client):
    caps = client.get(f"{V1}/capabilities").json()
    assert caps["runtime"]["ready"] is False and caps["runtime"]["reasons"]
    assert caps["modes"]["browse_offline"]["available"] is True
    assert caps["modes"]["legacy_ab_live"]["available"] is False
    for mode in ("cohort_execution", "scenario_execution", "stratified_sampling", "reproduce", "export_parquet"):
        assert caps["modes"][mode]["available"] is False and caps["modes"][mode]["reasons"]
    assert set(caps["credentials"]["provider_key_present"]) == {"fakeprov", "otherprov"}
    assert not any(caps["credentials"]["provider_key_present"].values())


def test_builds_are_separate_versions(client, v2_build):
    body = client.get(f"{V1}/builds").json()
    assert len(body["items"]) == 2 and body["default_build_id"] == v2_build
    assert body["relations"][0]["relation"] == "same_residents_extended"
    detail = client.get(f"{V1}/builds/{v2_build}").json()
    assert detail["row_count"] == 40 and detail["availability"]["status"] == "available"
    assert detail["scope"]["province"] == "TESTLAND" and detail["synthetic_label"].endswith("Not a census.")


def test_error_envelope(client, v2_build):
    r = client.get(f"{V1}/builds/nope")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "unknown_build" and err["request_id"] and r.headers["X-Request-ID"] == err["request_id"]
    r = client.get(f"{V1}/builds/{v2_build}/records?gender=other")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert "input" not in json.dumps(r.json()["error"]["details"])
    r = client.get(f"{V1}/builds/{v2_build}/records?limit=1000")
    assert r.status_code == 422


def test_records_filters_and_pagination(client, v2_build):
    url = f"{V1}/builds/{v2_build}/records"
    everything = client.get(url, params={"limit": 200}).json()
    assert everything["total_matching"] == 40 and [i["person_id"] for i in everything["items"]] == sorted(i["person_id"] for i in everything["items"])
    women = client.get(url, params={"gender": "female", "limit": 200}).json()
    assert all(i["gender"] == "female" for i in women["items"]) and women["total_matching"] == len(women["items"])
    two = client.get(url, params=[("age_group", "45-49"), ("age_group", "80-84"), ("gender", "female"), ("limit", 200)]).json()
    assert {i["age_group"] for i in two["items"]} <= {"45-49", "80-84"}
    page1 = client.get(url, params={"sort": "age_group", "limit": 7, "offset": 0}).json()["items"]
    page2 = client.get(url, params={"sort": "age_group", "limit": 7, "offset": 7}).json()["items"]
    again = client.get(url, params={"sort": "age_group", "limit": 14}).json()["items"]
    assert page1 + page2 == again
    exact = client.get(url, params={"person_id": "TST2099_000002"}).json()
    assert exact["total_matching"] == 1 and exact["items"][0]["csv_row"] == 3
    unicode = client.get(url, params={"marital_status": "Eşi öldü", "limit": 200}).json()
    assert all(i["marital_status"] == "Eşi öldü" for i in unicode["items"]) and unicode["total_matching"] >= 1


def test_base_build_rejects_marital_filter(client):
    base = next(b["build_id"] for b in client.get(f"{V1}/builds").json()["items"] if b["variant"] == "base")
    r = client.get(f"{V1}/builds/{base}/records", params={"marital_status": "Evli"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "field_unavailable"
    r = client.get(f"{V1}/builds/{base}/summary", params={"group_by": "marital_status"})
    assert r.status_code == 422


def test_summary_sums_to_denominator(client, v2_build):
    body = client.get(f"{V1}/builds/{v2_build}/summary", params={"gender": "male", "crosstab": True}).json()
    for dist in body["distributions"]:
        assert sum(c["count"] for c in dist["categories"]) == body["denominator"] == dist["denominator"]
    assert sum(c["count"] for c in body["crosstab"]["cells"]) == body["denominator"]
    assert client.get(f"{V1}/builds/{v2_build}/summary", params={"group_by": "income"}).status_code == 422


def test_validation_report(client, v2_build):
    body = client.get(f"{V1}/builds/{v2_build}/validation").json()
    assert body["acceptance_status"] is None and all(m["acceptance_threshold"] is None for m in body["metrics"])
    assert body["persona_hash_checks"] and body["reference_tables"][0]["reference_year"] == 2099
    assert any(c["name"] == "base_and_v2_share_residents" and c["passed"] for c in body["checks"])


def test_datasets_keeps_empty_manifest_visible(client):
    body = client.get(f"{V1}/datasets").json()
    assert body["manifest"]["status"] == "empty" and body["manifest"]["datasets"] == []
    processed = [e for e in body["fixture_evidence"] if e["kind"] == "processed_reference"]
    assert processed and all(e["url"] is None and e["download_date"] is None and e["raw_checksum"] is None for e in processed)
    median = next(c for c in body["controls"] if c["statistic"] == "total_median_age")
    assert len(median["observations"]) == 2


def test_cohort_persists_across_restart_and_detects_stale_source(settings, client, v2_build):
    preview = client.post(f"{V1}/cohorts/preview", json={"build_id": v2_build, "filters": {"genders": ["female"]}}).json()
    assert preview["can_persist"] and preview["eligible_count"] > 3
    body = {"build_id": v2_build, "source_sha256": preview["source_sha256"], "filters": {"genders": ["female"]},
            "size": 3, "seed": 11, "name": "three women"}
    created = client.post(f"{V1}/cohorts", json=body)
    assert created.status_code == 201
    manifest = created.json()
    assert manifest["realized"]["selected_count"] == 3 and manifest["current"]["status"] == "valid"
    assert manifest["realized"]["inclusion_probability"] == 3 / preview["eligible_count"]
    repeat = client.post(f"{V1}/cohorts", json=body).json()
    assert repeat["realized"]["record_ids"] == manifest["realized"]["record_ids"] and repeat["cohort_id"] != manifest["cohort_id"]
    with make_client(settings) as restarted:
        reloaded = restarted.get(f"{V1}/cohorts/{manifest['cohort_id']}").json()
        assert reloaded["realized"]["record_ids"] == manifest["realized"]["record_ids"]
    empty = client.post(f"{V1}/cohorts", json=dict(body, filters={"person_ids": ["TST2099_999999"]}))
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "empty_frame"
    assert client.post(f"{V1}/cohorts", json=dict(body, size=999)).json()["error"]["code"] == "oversample"
    assert client.post(f"{V1}/cohorts", json=dict(body, sampling="stratified")).status_code == 422
    path = settings.experiment_file(settings.layout.v2_population)
    path.write_bytes(path.read_bytes() + b"TST2099_000099,30-34,male,Evli,gender_only\n")
    stale = client.get(f"{V1}/cohorts/{manifest['cohort_id']}").json()
    assert stale["current"]["status"] == "build_unavailable"
    assert client.post(f"{V1}/cohorts", json=body).json()["error"]["code"] == "build_source_changed"
    assert client.get(f"{V1}/builds/{v2_build}/records").status_code == 409
    assert client.get(f"{V1}/builds/{v2_build}").json()["availability"]["status"] == "source_changed"


def test_get_requests_have_no_execution_side_effects(client, v2_build, workbench):
    before = client.app.state.workbench.registry.counts()
    for url in ["/capabilities", "/builds", f"/builds/{v2_build}/records", f"/builds/{v2_build}/summary",
                f"/builds/{v2_build}/validation", f"/personas/{v2_build}/TST2099_000001", "/datasets", "/experiments",
                "/experiments/imp_ab_complete/results", "/experiments/imp_ab_complete/trials", "/tasks", "/environments",
                "/experiments/imp_ab_complete/events", "/experiments/imp_ab_complete/export"]:
        assert client.get(f"{V1}{url}").status_code == 200, url
    after = client.app.state.workbench.registry.counts()
    for table in ("cohorts", "experiments", "preflights", "jobs", "personas"):
        assert after[table] == before[table]


def test_imported_results_and_exports(client):
    listing = client.get(f"{V1}/experiments").json()
    states = {i["experiment_id"]: i["display_state"] for i in listing["items"]}
    assert states["imp_ab_complete"] == "completed" and states["imp_smoke_fake"] == "completed_fake"
    assert states["imp_started_only"] == "outcome_unknown"
    res = client.get(f"{V1}/experiments/imp_ab_complete/results").json()
    assert res["differing_values_recomputed"] == 2 and "not population percentages" in res["inference_note"]
    assert res["usage"]["billed_cost_usd"] is None and res["usage"]["n_cache_tokens"] is None
    exported = client.get(f"{V1}/experiments/imp_ab_complete/export", params={"format": "json"})
    payload = exported.json()
    assert payload["synthetic_label"].startswith("Synthetic personas") and "null means unknown" in payload["unknown_value_policy"]
    assert len(payload["rows"]) == 8
    csv_text = client.get(f"{V1}/experiments/imp_ab_complete/export", params={"format": "csv"}).text
    assert csv_text.splitlines()[0].startswith("experiment_id,origin,evidence_kind") and "Not real people" in csv_text
    assert client.get(f"{V1}/experiments/imp_ab_complete/export", params={"format": "parquet"}).status_code == 422
    events = client.get(f"{V1}/experiments/imp_ab_complete/events", params={"trial": "A"}).json()
    assert events["total"] == 5 and events["items"][0]["type"] == "instruction"
    assert client.get(f"{V1}/experiments/imp_nope/results").status_code == 404


def test_reproduce_is_not_pretended(client):
    r = client.post(f"{V1}/experiments/imp_ab_complete/reproduce")
    assert r.status_code == 501 and r.json()["error"]["code"] == "reproduce_unavailable"


def test_mutations_require_loopback(settings):
    from fastapi.testclient import TestClient

    from societytwin.api.app import create_app

    with TestClient(create_app(settings, start_worker=False)) as remote:  # TestClient host is "testclient"
        r = remote.post(f"{V1}/cohorts/preview", json={"build_id": "x"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "mutations_local_only"
        assert remote.get(f"{V1}/builds").status_code == 200
    with TestClient(create_app(settings.with_overrides(local_mutations=False), start_worker=False,
                               loopback_hosts=("testclient",))) as readonly:
        assert readonly.post(f"{V1}/cohorts/preview", json={"build_id": "x"}).json()["error"]["code"] == "mutations_disabled"


def test_cors_is_restricted(client):
    allowed = client.options(f"{V1}/builds", headers={"Origin": "http://127.0.0.1:3000", "Access-Control-Request-Method": "GET"})
    assert allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"
    denied = client.options(f"{V1}/builds", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert denied.headers.get("access-control-allow-origin") is None


def test_openapi_snapshot_matches_frontend_client():
    from pathlib import Path

    from societytwin.api.openapi_export import openapi_document

    snapshot = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
    assert snapshot.is_file(), "Run scripts/export_openapi.sh to create frontend/openapi.json"
    assert json.loads(snapshot.read_text(encoding="utf-8")) == openapi_document(), (
        "OpenAPI drift: run scripts/export_openapi.sh and regenerate the typed client")


def test_persona_index_lists_only_stored_personas(client, v2_build):
    body = client.get(f"{V1}/personas/{v2_build}").json()
    assert [i["record_id"] for i in body["items"]] == ["TST2099_000001", "TST2099_000002"]
    assert body["fixed_pair"] == ["TST2099_000001", "TST2099_000002"]
    base = next(b["build_id"] for b in client.get(f"{V1}/builds").json()["items"] if b["variant"] == "base")
    assert client.get(f"{V1}/personas/{base}").json()["items"] == []
    caps = client.get(f"{V1}/capabilities").json()
    assert caps["runner"]["provider_prefixes"] == ["fakeprov", "otherprov"]
