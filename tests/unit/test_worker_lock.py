import sys

import pytest

from societytwin.worker import LocalWorker

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="advisory worker lock uses fcntl")


def _running_job(workbench, worker_id: str) -> str:
    reg = workbench.registry
    reg.insert_experiment({"experiment_id": "exp_lock", "config_hash": "c", "created_at": "t"})
    reg.insert_preflight({"preflight_hash": "p_lock", "experiment_id": "exp_lock", "config_hash": "c", "created_at": "t"})
    job, _ = reg.create_job({"job_id": "job_lock", "experiment_id": "exp_lock", "preflight_hash": "p_lock", "mode": "smoke",
                             "idempotency_key": "lock-key-1", "output_rel": "experiments/exp_lock/job_lock"})
    assert reg.claim_next_job(worker_id)["job_id"] == job["job_id"]
    return job["job_id"]


def test_second_worker_on_the_same_state_dir_neither_runs_nor_recovers(workbench):
    first = LocalWorker(workbench, poll_seconds=0.05)
    assert first.start() is True
    try:
        job_id = _running_job(workbench, first.worker_id)
        second = LocalWorker(workbench)
        assert second.start() is False and second.active is False
        assert workbench.registry.job(job_id)["state"] == "running"  # not clobbered by the second process
    finally:
        first.stop()
    third = LocalWorker(workbench, poll_seconds=0.05)
    assert third.start() is True
    try:
        assert workbench.registry.job(job_id)["state"] == "unknown_after_interruption"
    finally:
        third.stop()
