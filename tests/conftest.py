"""Shared test fixtures. CI uses only the artificial fixture; provider traffic is impossible."""

from __future__ import annotations

import json
import os
import shutil
import socket
from pathlib import Path

import pytest

from societytwin.agents.matraix_runtime import MatraixRuntime, ProcessResult
from societytwin.config import ExperimentLayout, Settings

REPO = Path(__file__).resolve().parents[1]
ARTIFICIAL = Path(__file__).resolve().parent / "fixtures" / "artificial_experiment"


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in {"127.0.0.1", "::1", "localhost"} and not host.startswith("/"):
            raise RuntimeError(f"Network access is blocked in tests (attempted {host})")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    for name in list(os.environ):
        if name.endswith("_API_KEY") or name in {"MATRAIX_ROOT", "SOCIETYTWIN_RUNTIME_PYTHON", "SOCIETYTWIN_ENABLE_LIVE_EXECUTION"}:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def experiment_root(tmp_path) -> Path:
    target = tmp_path / "experiment"
    shutil.copytree(ARTIFICIAL, target)
    return target


@pytest.fixture
def make_settings(tmp_path, experiment_root):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("datasets: []\n", encoding="utf-8")

    def _make(**overrides) -> Settings:
        base = dict(repo_root=tmp_path, experiment_root=experiment_root, import_runs_root=experiment_root / "runs",
                    state_dir=tmp_path / "state", data_manifest=manifest, matraix_root=tmp_path / "no_matraix",
                    runtime_python=None, start_worker=False, layout=ExperimentLayout.load(experiment_root))
        base.update(overrides)
        return Settings(**base)

    return _make


@pytest.fixture
def settings(make_settings) -> Settings:
    return make_settings()


@pytest.fixture
def workbench(settings):
    from societytwin.workbench import Workbench

    wb = Workbench(settings)
    yield wb
    wb.close()


def make_client(settings, workbench=None):
    from fastapi.testclient import TestClient

    from societytwin.api.app import create_app

    return TestClient(create_app(settings, workbench=workbench, start_worker=False, loopback_hosts=("testclient",)))


@pytest.fixture
def client(settings):
    with make_client(settings) as c:
        yield c


@pytest.fixture
def v2_build(client) -> str:
    return client.get("/api/v1/builds").json()["default_build_id"]


class FakeRuntime(MatraixRuntime):
    """Stands in for the external framework. Records every call; never contacts anything."""

    def __init__(self, settings, *, fail_execute: bool = False):
        super().__init__(settings)
        self.calls: list[str] = []
        self.provider_requests = 0
        self.fail_execute = fail_execute

    def file_status(self) -> dict:
        status = super().file_status()
        status.update(matraix_root_present=True, catalog_present=True, task_present=True, runtime_python_configured=True,
                      runtime_python_present=True, files_ready=True, ready=self._probe["status"] == "passed", reasons=[])
        return status

    def probe(self, timeout: int = 180) -> dict:
        self.calls.append("probe")
        self._probe = {"status": "passed", "checked_at": "2099-01-01T00:00:00Z", "detail": None, "log_relpath": None}
        return dict(self._probe)

    def task_content_hash(self):
        return "f" * 64

    def catalog_bytes(self):
        return None

    def _personas(self):
        from societytwin.common import sha256_bytes

        root = self.settings.experiment_root / "personas"
        return [("A", "TST2099_000001", root / "persona_a.yaml"), ("B", "TST2099_000002", root / "persona_b.yaml")], sha256_bytes

    def run_ab_prepare(self, output_dir, model, temperature, log_path):
        self.calls.append("prepare")
        self.fresh_output_dir(output_dir)
        output_dir.mkdir(parents=True)
        personas, h = self._personas()
        plan = {"status": "prepared", "model": model, "temperature": temperature, "provider": model.split("/")[0],
                "credentials_present": False, "task": "application/tasks/example-survey_product-feedback",
                "calls_planned": 2, "automatic_retries": 0, "max_output_tokens_per_call": None, "expected_answer_count": 4,
                "trials": [{"label": l, "persona_id": pid, "path": str(p), "sha256": h(p.read_bytes()),
                            "dimensions": {"dst_age_group": "45-49"}, "system": f"system {pid}", "user": "user prompt",
                            "estimated_input_tokens_chars_div_4": 10} for l, pid, p in personas],
                "limitations": []}
        (output_dir / "preflight.json").write_text(json.dumps(plan), encoding="utf-8")
        return ProcessResult(0, 0.01, "logs/fake.log", "")

    def run_smoke(self, output_dir, log_path):
        self.calls.append("smoke")
        self.fresh_output_dir(output_dir)
        shutil.copytree(self.settings.experiment_root / "runs" / "smoke_fake", output_dir)
        return ProcessResult(0, 0.01, "logs/fake.log", "")

    def run_ab_execute(self, output_dir, model, temperature, log_path, credential_env):
        self.calls.append("execute")
        self.fresh_output_dir(output_dir)
        self.provider_requests += 2
        if self.fail_execute:
            return ProcessResult(1, 0.01, "logs/fake.log", "RuntimeError: artificial failure")
        shutil.copytree(self.settings.experiment_root / "runs" / "ab_complete", output_dir)
        return ProcessResult(0, 0.01, "logs/fake.log", "")


@pytest.fixture
def fake_runtime_client(settings):
    from societytwin.workbench import Workbench

    runtime = FakeRuntime(settings)
    wb = Workbench(settings, runtime=runtime)
    with make_client(settings, wb) as c:
        c.runtime = runtime
        c.workbench = wb
        yield c
    wb.close()
