"""Integration with an external MatrAIx checkout and runtime interpreter (opt-in).

Set SOCIETYTWIN_TEST_MATRAIX_ROOT and SOCIETYTWIN_TEST_RUNTIME_PYTHON to run. No provider key is passed
to any subprocess, proxies point at a closed port, and every output goes to a temporary state directory.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from societytwin.config import load_settings
from societytwin.experiments.models import ExecuteRequest, ExperimentDraftRequest

REPO = Path(__file__).resolve().parents[2]
EXPERIMENT = REPO / "experiments" / "matraix_simulation"
ROOT = os.environ.get("SOCIETYTWIN_TEST_MATRAIX_ROOT")
PYTHON = os.environ.get("SOCIETYTWIN_TEST_RUNTIME_PYTHON")
pytestmark = [pytest.mark.matraix,
              pytest.mark.skipif(not (ROOT and PYTHON), reason="external MatrAIx runtime not configured")]


def tree_hashes(path: Path) -> dict[str, str]:
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


@pytest.fixture(scope="module")
def wb(tmp_path_factory):
    from societytwin.workbench import Workbench

    settings = load_settings().with_overrides(experiment_root=EXPERIMENT, import_runs_root=EXPERIMENT / "runs",
                                              state_dir=tmp_path_factory.mktemp("state"), matraix_root=Path(ROOT),
                                              runtime_python=Path(PYTHON), start_worker=False)
    before = tree_hashes(EXPERIMENT)
    workbench = Workbench(settings)
    yield workbench
    workbench.close()
    assert tree_hashes(EXPERIMENT) == before, "protected experiment files or runs changed"


def test_probe(wb):
    assert wb.runtime.probe()["status"] == "passed"


def test_smoke_runs_real_agent_with_zero_provider_calls(wb):
    from societytwin.worker import LocalWorker

    draft = wb.create_draft(ExperimentDraftRequest(name="smoke", persona_source="legacy_fixture_single",
                                                   task={"id": "product_feedback_v1"}, mode="smoke", calls_limit=0))
    plan = wb.preflight(draft["experiment_id"])
    job = wb.execute(draft["experiment_id"], ExecuteRequest(preflight_hash=plan["preflight_hash"], mode="smoke",
                                                            idempotency_key="itest-smoke"))["job"]
    LocalWorker(wb).run_once()
    assert wb.registry.job(job["job_id"])["state"] == "completed"
    results = wb.results(draft["experiment_id"])
    assert results["display_state"] == "completed_fake" and results["provider_calls_recorded"] == 0
    assert results["trial_summaries"][0]["answer_count"] == 9


def test_ab_preflight_matches_recorded_prompts(wb):
    draft = wb.create_draft(ExperimentDraftRequest(name="ab", persona_source="legacy_fixture_pair", task={"id": "product_feedback_v1"},
                                                   mode="preflight", model="gemini/gemini-3.1-flash-lite", temperature=0, calls_limit=0))
    plan = wb.preflight(draft["experiment_id"])
    assert plan["provider_calls_made"] == 0 and plan["planned_provider_calls"] == 2 and plan["automatic_retries"] == 0
    assert plan["runner_reported_credentials_present"] is False
    runs = {r["dirname"]: r for r in wb.imported_runs()}
    if "run3" in runs:
        for trial, recorded in zip(plan["trials"], runs["run3"]["trials"]):
            assert trial["system_prompt"] == recorded["prompts"]["system"]
            assert trial["user_prompt"] == recorded["prompts"]["user"]


def test_materialization_writes_new_artifact_and_omits_unmapped_status(wb):
    build = next(b.descriptor["build_id"] for b in wb.sync_builds() if b.source.variant == "v2")
    view = wb.materialize_persona(build, "ANK2025_000003")
    persona = next(p for p in view["personas"] if p["origin"] == "managed")
    assert "demo_marital_status" not in persona["dimensions"] and "marital_status" in persona["metadata_only_fields"]
    assert {c["name"]: c["status"] for c in persona["hash_checks"]}["source_population"] == "match"
    assert not (EXPERIMENT / "personas" / "ANK2025_000003.yaml").exists()
