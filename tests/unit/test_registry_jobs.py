import threading

import pytest

from societytwin.registry.db import MIGRATIONS
from societytwin.registry.store import Conflict, Registry


@pytest.fixture
def registry(tmp_path):
    reg = Registry(tmp_path / "r.sqlite3")
    reg.insert_experiment({"experiment_id": "exp_1", "config_hash": "c", "created_at": "t"})
    for h in ("p1", "p2"):
        reg.insert_preflight({"preflight_hash": h, "experiment_id": "exp_1", "config_hash": "c", "created_at": "t"})
    yield reg
    reg.close()


def job(key, preflight="p1", job_id=None):
    return {"job_id": job_id or f"job_{key}", "experiment_id": "exp_1", "preflight_hash": preflight, "mode": "smoke",
            "idempotency_key": key, "output_rel": f"experiments/exp_1/{key}"}


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "m.sqlite3"
    Registry(path).close()
    reg = Registry(path)
    versions = [r["version"] for r in reg.conn.execute("SELECT version FROM schema_migrations")]
    assert versions == [m[0] for m in MIGRATIONS]
    reg.close()


def test_build_registration_is_idempotent(registry):
    descriptor = {"build_id": "b1", "variant": "v2", "source_sha256": "x"}
    assert registry.register_build(descriptor) is True
    assert registry.register_build(dict(descriptor, variant="changed")) is False
    assert registry.build("b1")["variant"] == "v2"


def test_idempotency_and_one_execution_per_plan(registry):
    first, created = registry.create_job(job("key-aaaa"))
    again, created_again = registry.create_job(job("key-aaaa", job_id="job_other"))
    assert created and not created_again and again["job_id"] == first["job_id"]
    with pytest.raises(Conflict) as info:
        registry.create_job(job("key-aaaa", preflight="p2"))
    assert info.value.code == "idempotency_key_reused"
    with pytest.raises(Conflict) as info:
        registry.create_job(job("key-bbbb"))
    assert info.value.code == "preflight_already_executed"


def test_only_one_worker_claims_a_job(registry, tmp_path):
    registry.create_job(job("key-claim"))
    claims = []

    def claim(i):
        reg = Registry(tmp_path / "r.sqlite3")
        claims.append(reg.claim_next_job(f"w{i}"))
        reg.close()

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for c in claims if c) == 1


def test_interrupted_job_becomes_unknown_and_is_never_replayed(registry):
    registry.create_job(job("key-crash"))
    claimed = registry.claim_next_job("dead-worker")
    registry.mark_provider_window_open(claimed["job_id"])
    assert registry.recover_interrupted({"new-worker"}) == [claimed["job_id"]]
    after = registry.job(claimed["job_id"])
    assert after["state"] == "unknown_after_interruption" and after["provider_window_opened_at"]
    assert registry.claim_next_job("new-worker") is None


def test_cancel_only_queued(registry):
    registry.create_job(job("key-cancel"))
    assert registry.cancel_queued("job_key-cancel") is True
    assert registry.job("job_key-cancel")["state"] == "stopped"
    assert registry.claim_next_job("w") is None
