V1 = "/api/v1"
FIXTURE_PAIR = {"name": "fixture pair", "persona_source": "legacy_fixture_pair", "task": {"id": "product_feedback_v1"},
                "mode": "preflight", "model": "fakeprov/artificial-model", "temperature": 0, "calls_limit": 0}
SMOKE = {"name": "smoke", "persona_source": "legacy_fixture_single", "task": {"id": "product_feedback_v1"},
         "mode": "smoke", "calls_limit": 0}
LIVE = dict(FIXTURE_PAIR, name="live", mode="legacy_ab_live", calls_limit=2)


def draft(c, body):
    r = c.post(f"{V1}/experiments", json=body)
    assert r.status_code == 201, r.json()
    return r.json()


def test_unsupported_drafts_are_saved_but_blocked(client, v2_build):
    preview = client.post(f"{V1}/cohorts/preview", json={"build_id": v2_build}).json()
    cohort = client.post(f"{V1}/cohorts", json={"build_id": v2_build, "source_sha256": preview["source_sha256"], "size": 2, "seed": 3}).json()
    d = draft(client, {"name": "cohort", "persona_source": "cohort", "cohort_id": cohort["cohort_id"],
                       "task": {"id": "product_feedback_v1"}, "environment": "SCENARIO", "mode": "legacy_ab_live",
                       "model": "nope/x", "temperature": 0, "calls_limit": 5,
                       "scenario": {"kind": "draft", "text": "An invented scenario."}})
    codes = {b["code"] for b in d["blockers"]}
    assert {"cohort_execution_unsupported", "scenario_execution_unsupported", "environment_not_executable",
            "mode_persona_mismatch", "unsupported_provider", "call_limit_mismatch"} <= codes
    assert d["config"]["realized_ids"] == cohort["realized"]["record_ids"]  # never silently replaced by fixtures
    r = client.post(f"{V1}/experiments/{d['experiment_id']}/preflight")
    assert r.status_code == 409 and r.json()["error"]["code"] == "draft_not_executable"


def test_invalid_drafts_rejected(client):
    assert client.post(f"{V1}/experiments", json=dict(SMOKE, model="fakeprov/x")).status_code == 422
    assert client.post(f"{V1}/experiments", json=dict(FIXTURE_PAIR, task={"id": "other"})).status_code == 422
    assert client.post(f"{V1}/experiments", json=dict(FIXTURE_PAIR, model="fakeprov/x; rm -rf /")).status_code == 422
    assert client.post(f"{V1}/experiments", json=dict(FIXTURE_PAIR, persona_source="cohort")).status_code == 422
    assert client.post(f"{V1}/experiments", json=dict(FIXTURE_PAIR, scenario={"kind": "draft"})).status_code == 422


def test_preflight_without_runtime_is_503(client):
    d = draft(client, FIXTURE_PAIR)
    assert d["preparation_status"] == "blocked_by_dependencies" and d["dependency_reasons"]
    r = client.post(f"{V1}/experiments/{d['experiment_id']}/preflight")
    assert r.status_code == 503 and r.json()["error"]["code"] == "runtime_unavailable"


def test_preflight_makes_zero_provider_calls(fake_runtime_client):
    c = fake_runtime_client
    d = draft(c, FIXTURE_PAIR)
    plan = c.post(f"{V1}/experiments/{d['experiment_id']}/preflight")
    assert plan.status_code == 201
    plan = plan.json()
    assert plan["realized_ids"] == ["TST2099_000001", "TST2099_000002"]
    assert plan["planned_provider_calls"] == 2 and plan["automatic_retries"] == 0 and plan["provider_calls_made"] == 0
    assert plan["cost_estimate_usd"] is None and plan["input_token_estimate"] == 20 and "heuristic" in plan["estimate_method"]
    assert plan["model_seed"] is None and len(plan["prompt_hashes"]) == 4
    assert {b["code"] for b in plan["execution_blockers"]} == {"nothing_to_execute"}
    assert c.runtime.provider_requests == 0 and "execute" not in c.runtime.calls
    r = c.post(f"{V1}/experiments/{d['experiment_id']}/execute", json={"preflight_hash": plan["preflight_hash"], "mode": "smoke", "idempotency_key": "abcdefgh"})
    assert r.status_code == 409


def test_smoke_execution_is_idempotent_and_recorded(fake_runtime_client):
    c = fake_runtime_client
    d = draft(c, SMOKE)
    plan = c.post(f"{V1}/experiments/{d['experiment_id']}/preflight").json()
    assert plan["planned_provider_calls"] == 0 and plan["cost_estimate_usd"] == 0.0
    body = {"preflight_hash": plan["preflight_hash"], "mode": "smoke", "idempotency_key": "smoke-key-1"}
    first = c.post(f"{V1}/experiments/{d['experiment_id']}/execute", json=body)
    assert first.status_code == 202 and first.json()["created"] and first.json()["job"]["state"] == "queued"
    again = c.post(f"{V1}/experiments/{d['experiment_id']}/execute", json=body).json()
    assert again["created"] is False and again["job"]["job_id"] == first.json()["job"]["job_id"]
    other = c.post(f"{V1}/experiments/{d['experiment_id']}/execute", json=dict(body, idempotency_key="smoke-key-2"))
    assert other.status_code == 409 and other.json()["error"]["code"] == "preflight_already_executed"
    from societytwin.worker import LocalWorker

    worker = LocalWorker(c.workbench)
    assert worker.run_once() is True and worker.run_once() is False
    detail = c.get(f"{V1}/experiments/{d['experiment_id']}").json()
    assert detail["display_state"] == "completed" and detail["jobs"][0]["state"] == "completed"
    results = c.get(f"{V1}/experiments/{d['experiment_id']}/results").json()
    assert results["origin"] == "managed" and results["evidence_kind"] == "fake" and results["display_state"] == "completed_fake"
    assert c.runtime.provider_requests == 0
    assert c.post(f"{V1}/experiments/{d['experiment_id']}/execute", json=dict(body, mode="legacy_ab_live")).status_code == 409


def test_stale_preflight_is_rejected(fake_runtime_client, settings):
    c = fake_runtime_client
    d = draft(c, SMOKE)
    plan = c.post(f"{V1}/experiments/{d['experiment_id']}/preflight").json()
    persona = settings.experiment_root / "personas" / "persona_a.yaml"
    persona.write_text(persona.read_text() + "# edited\n")
    r = c.post(f"{V1}/experiments/{d['experiment_id']}/execute", json={"preflight_hash": plan["preflight_hash"], "mode": "smoke", "idempotency_key": "stale-key"})
    assert r.status_code == 409 and r.json()["error"]["code"] in {"stale_preflight", "draft_not_executable"}


def test_live_mode_is_disabled_by_default(fake_runtime_client):
    c = fake_runtime_client
    d = draft(c, LIVE)
    plan = c.post(f"{V1}/experiments/{d['experiment_id']}/preflight").json()
    assert {"live_execution_disabled", "credentials_missing"} <= {b["code"] for b in plan["execution_blockers"]}
    r = c.post(f"{V1}/experiments/{d['experiment_id']}/execute", json={"preflight_hash": plan["preflight_hash"], "mode": "legacy_ab_live", "idempotency_key": "live-key-1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "live_execution_disabled"
    assert c.runtime.provider_requests == 0


def _live_client(settings, monkeypatch, fail=False):
    from societytwin.workbench import Workbench
    from tests.conftest import FakeRuntime, make_client

    monkeypatch.setenv("FAKEPROV_API_KEY", "artificial-test-value-not-a-secret")
    s = settings.with_overrides(live_execution_enabled=True)
    runtime = FakeRuntime(s, fail_execute=fail)
    wb = Workbench(s, runtime=runtime)
    return make_client(s, wb), wb, runtime


def test_enabled_live_path_runs_once_with_explicit_start(settings, monkeypatch):
    client, wb, runtime = _live_client(settings, monkeypatch)
    with client as c:
        d = draft(c, LIVE)
        plan = c.post(f"{V1}/experiments/{d['experiment_id']}/preflight").json()
        assert plan["execution_blockers"] == []
        assert runtime.provider_requests == 0
        body = {"preflight_hash": plan["preflight_hash"], "mode": "legacy_ab_live", "idempotency_key": "live-key-ok"}
        job = c.post(f"{V1}/experiments/{d['experiment_id']}/execute", json=body).json()["job"]
        from societytwin.worker import LocalWorker

        LocalWorker(wb).run_once()
        assert runtime.provider_requests == 2 and runtime.calls.count("execute") == 1
        stored = wb.registry.job(job["job_id"])
        assert stored["state"] == "completed" and stored["provider_window_opened_at"]
        assert c.post(f"{V1}/experiments/{d['experiment_id']}/execute", json=dict(body, idempotency_key="live-key-2")).status_code == 409
        caps = c.get(f"{V1}/capabilities").text
        assert "artificial-test-value-not-a-secret" not in caps
    wb.close()


def test_failed_live_run_is_recorded_without_retry(settings, monkeypatch):
    client, wb, runtime = _live_client(settings, monkeypatch, fail=True)
    with client as c:
        d = draft(c, LIVE)
        plan = c.post(f"{V1}/experiments/{d['experiment_id']}/preflight").json()
        job = c.post(f"{V1}/experiments/{d['experiment_id']}/execute",
                     json={"preflight_hash": plan["preflight_hash"], "mode": "legacy_ab_live", "idempotency_key": "live-fail"}).json()["job"]
        from societytwin.worker import LocalWorker

        worker = LocalWorker(wb)
        worker.run_once()
        stored = wb.registry.job(job["job_id"])
        assert stored["state"] == "failed" and stored["error_code"] == "runner_exit_nonzero"
        assert "unknown" in stored["error_message"]
        assert worker.run_once() is False and runtime.calls.count("execute") == 1
    wb.close()


def test_worker_crash_leaves_unknown_state_and_no_replay(fake_runtime_client):
    c = fake_runtime_client
    d = draft(c, SMOKE)
    plan = c.post(f"{V1}/experiments/{d['experiment_id']}/preflight").json()
    job = c.post(f"{V1}/experiments/{d['experiment_id']}/execute",
                 json={"preflight_hash": plan["preflight_hash"], "mode": "smoke", "idempotency_key": "crash-key"}).json()["job"]
    claimed = c.workbench.registry.claim_next_job("worker-that-dies")
    assert claimed["job_id"] == job["job_id"]
    from societytwin.worker import LocalWorker

    fresh = LocalWorker(c.workbench)
    assert fresh.recover() == [job["job_id"]]
    assert fresh.run_once() is False
    assert c.get(f"{V1}/experiments/{d['experiment_id']}").json()["display_state"] == "unknown_after_interruption"
    assert "smoke" not in c.runtime.calls


def test_cancel_queued_only(fake_runtime_client):
    c = fake_runtime_client
    d = draft(c, SMOKE)
    plan = c.post(f"{V1}/experiments/{d['experiment_id']}/preflight").json()
    job = c.post(f"{V1}/experiments/{d['experiment_id']}/execute",
                 json={"preflight_hash": plan["preflight_hash"], "mode": "smoke", "idempotency_key": "cancel-key"}).json()["job"]
    r = c.post(f"{V1}/experiments/{d['experiment_id']}/jobs/{job['job_id']}/cancel")
    assert r.status_code == 200 and r.json()["job"]["state"] == "stopped"
    again = c.post(f"{V1}/experiments/{d['experiment_id']}/jobs/{job['job_id']}/cancel")
    assert again.status_code == 409 and again.json()["error"]["code"] == "job_already_finished"


def test_imported_runs_cannot_be_prepared(client):
    r = client.post(f"{V1}/experiments/imp_ab_complete/preflight")
    assert r.status_code == 409 and r.json()["error"]["code"] == "imported_runs_are_read_only"
