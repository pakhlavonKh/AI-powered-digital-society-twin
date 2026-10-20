"""National MatrAIx backend with an external checkout and runtime interpreter (opt-in, fake transport only).

Set SOCIETYTWIN_TEST_MATRAIX_ROOT and SOCIETYTWIN_TEST_RUNTIME_PYTHON to run. Personas from the ARTIFICIAL
package (three provinces) run through MatrAIx's PersonaJsonSurvey with its zero-cost smoke client.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from societytwin.national.experiments import example_fare_definition

ROOT = os.environ.get("SOCIETYTWIN_TEST_MATRAIX_ROOT")
PYTHON = os.environ.get("SOCIETYTWIN_TEST_RUNTIME_PYTHON")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
pytestmark = [pytest.mark.matraix,
              pytest.mark.skipif(not (ROOT and PYTHON), reason="external MatrAIx runtime not configured")]


def test_arbitrary_personas_run_through_matraix_with_zero_provider_calls(make_settings, tmp_path):
    from tests.conftest import make_client

    package = tmp_path / "pkg"
    shutil.copytree(FIXTURES / "artificial_tuik_package", package)
    settings = make_settings(tuik_package_dir=package, tuik_mapping_path=FIXTURES / "artificial_tuik_package_mapping.yaml",
                             matraix_root=Path(ROOT), runtime_python=Path(PYTHON))
    with make_client(settings) as c:
        c.post("/api/v2/controls/build")
        pid = c.post("/api/v2/populations", json={"synthetic_size": 2000, "seed": 1}).json()["population"]["population_id"]
        cid = c.post("/api/v2/cohorts", json={"name": "adults", "population_id": pid, "filters": {"adult_only": True}}).json()["cohort_id"]
        definition = example_fare_definition(cid)
        definition.update(environment={"province_code": None, "context_indicators": []},
                          model={"backend": "matraix", "transport": "fake", "temperature": 0})
        definition["cohort"]["sample_size"] = 3
        definition["execution"]["max_calls"] = 3
        exp = c.post("/api/v2/experiments", json=definition).json()
        plan = c.post(f"/api/v2/experiments/{exp['experiment_id']}/plan").json()
        assert plan["executable"], plan["blockers"]
        run = c.post(f"/api/v2/experiments/{exp['experiment_id']}/runs",
                     json={"plan_hash": plan["plan_hash"], "idempotency_key": "matraix-int-01", "confirm": True}).json()["run"]
        assert run["state"] == "queued"
        assert c.app.state.workbench.national.claim_and_run("test")
        done = c.get(f"/api/v2/runs/{run['run_id']}").json()["run"]
        assert done["state"] == "completed" and done["valid_responses"] == 3 and done["provider_calls"] == 0
        rows = c.get(f"/api/v2/runs/{run['run_id']}/responses").json()["items"]
        assert all(r["prompt_source"] == "transport_boundary" for r in rows)
        trial = json.loads((settings.national_runs_dir / run["run_id"] / "matraix_batch_1" / "trial_0000" / "trial_result.json")
                           .read_text(encoding="utf-8"))
        assert "dst sex" in trial["system"] and "48 TL" in trial["user"]
