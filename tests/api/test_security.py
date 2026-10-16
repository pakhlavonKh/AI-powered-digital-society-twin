import os
import subprocess

import pytest

from societytwin.agents.matraix_runtime import MatraixRuntime, UnsafeOutput
from societytwin.common import redact

V1 = "/api/v1"


def test_artifacts_resolve_only_server_ids(client):
    res = client.get(f"{V1}/experiments/imp_ab_complete/results").json()
    report = next(a for a in res["artifacts"] if a["kind"] == "report")
    r = client.get(f"{V1}/artifacts/{report['artifact_id']}")
    assert r.status_code == 200 and r.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in r.headers["content-security-policy"] and r.headers["x-societytwin-caveat"]
    assert b"<script>" in r.content  # served verbatim as text; never rendered as HTML by the server
    assert r.headers["content-type"].startswith("text/markdown")
    for bad in ("../../etc/passwd", "%2e%2e%2fetc%2fpasswd", "art_" + "0" * 16, "comparison.json"):
        assert client.get(f"{V1}/artifacts/{bad}").status_code == 404


def test_symlink_escape_never_listed(client, settings, tmp_path):
    secret = tmp_path / "outside.md"
    secret.write_text("outside report")
    os.symlink(secret, settings.import_runs_root / "ab_complete" / "escape_report.md")
    os.symlink(tmp_path, settings.import_runs_root / "ab_complete" / "linked_dir")
    res = client.get(f"{V1}/experiments/imp_ab_complete/results").json()
    assert all("escape" not in a["relpath"] and "linked_dir" not in a["relpath"] for a in res["artifacts"])
    os.symlink(tmp_path, settings.import_runs_root / "linked_run")
    ids = [i["experiment_id"] for i in client.get(f"{V1}/experiments").json()["items"]]
    assert "imp_linked_run" not in ids


def test_no_host_paths_in_responses(client, settings):
    for url in ("/experiments/imp_ab_complete/results", "/experiments/imp_ab_complete/trials", "/capabilities"):
        text = client.get(f"{V1}{url}").text
        assert "C:\\\\Users" not in text and str(settings.state_dir) not in text and str(settings.experiment_root) not in text


def test_runtime_rejects_forged_outputs_and_arguments(settings, tmp_path):
    runtime = MatraixRuntime(settings)
    with pytest.raises(UnsafeOutput):
        runtime.fresh_output_dir(tmp_path / "elsewhere")
    with pytest.raises(UnsafeOutput):
        runtime.fresh_output_dir(settings.experiment_root / "runs" / "new")
    existing = settings.state_dir / "experiments" / "exists"
    existing.mkdir(parents=True)
    with pytest.raises(UnsafeOutput):
        runtime.fresh_output_dir(existing)

    ready = dict(runtime.file_status(), files_ready=True)
    runtime.file_status = lambda: ready
    for model in ("fakeprov/x; touch /tmp/pwned", "fakeprov/$(id)", "../x", "fakeprov/a b"):
        with pytest.raises(ValueError):
            runtime.run_ab_prepare(settings.state_dir / "experiments" / "new1", model, 0, tmp_path / "l.log")
    for person in ("A;rm", "$(id)", "../x", "a b"):
        with pytest.raises(ValueError):
            runtime.materialize(person, tmp_path / "s.csv", settings.state_dir / "personas" / "p" / "x.yaml", tmp_path / "l.log")


def test_subprocess_invocation_is_isolated(make_settings, tmp_path, monkeypatch):
    python = tmp_path / "fake-python"
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o755)
    root = tmp_path / "matraix"
    (root / "persona" / "schema").mkdir(parents=True)
    (root / "persona" / "schema" / "dimensions.json").write_text("{}")
    task = root / "application" / "tasks" / "example-survey_product-feedback"
    task.mkdir(parents=True)
    (task / "task.toml").write_text("")
    (root / "packages" / "playground").mkdir(parents=True)
    settings = make_settings(runtime_python=python, matraix_root=root)
    monkeypatch.setenv("FAKEPROV_API_KEY", "artificial-value")
    captured = {}

    def fake_run(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runtime = MatraixRuntime(settings)
    result = runtime.run_smoke(settings.state_dir / "experiments" / "fresh", settings.state_dir / "logs" / "x.log")
    assert result.ok
    assert captured["argv"][:3] == [str(python), "-I", "-B"] and "shell" not in captured
    env = captured["env"]
    assert "FAKEPROV_API_KEY" not in env and env["HTTPS_PROXY"] == "http://127.0.0.1:9"
    assert set(env) <= {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE", "MATRAIX_ROOT",
                        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "NO_PROXY"}
    assert captured["cwd"] == settings.repo_root and captured["stdin"] == subprocess.DEVNULL
    log = (settings.state_dir / "logs" / "x.log").read_text()
    assert "artificial-value" not in log


def test_redaction():
    text = f"failed at {os.path.expanduser('~')}/secret/file.py with OPENAI_API_KEY=sk-abc and /Users/x/y and C:\\Users\\z"
    cleaned = redact(text)
    assert "sk-abc" not in cleaned and os.path.expanduser("~") not in cleaned and "/Users/x" not in cleaned
