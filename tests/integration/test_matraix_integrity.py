"""Opt-in real MatrAIx agent checks using scripted completions and no provider transport."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from societytwin.agents.matraix_runtime import MatraixRuntime
from societytwin.national.runner import MatraixBackend, execute
from tests.national.test_matraix_integrity import definition, requests

ROOT = os.environ.get("SOCIETYTWIN_TEST_MATRAIX_ROOT")
PYTHON = os.environ.get("SOCIETYTWIN_TEST_RUNTIME_PYTHON")
pytestmark = [pytest.mark.matraix, pytest.mark.skipif(not (ROOT and PYTHON), reason="external MatrAIx runtime not configured")]


@pytest.mark.parametrize("invalid", [False, True])
def test_real_agent_preserves_context_usage_and_rejects_normalization(make_settings, tmp_path, invalid):
    # Run the production batch module and agent, replacing only its fake client
    # with a scripted completion. The isolated runtime keeps network proxies blocked.
    wrapper = tmp_path / "scripted_batch.py"
    wrapper.write_text('''
import importlib.util
import sys
spec = importlib.util.spec_from_file_location("batch", sys.argv[1])
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)
original = batch.CapturingClient
class ScriptedClient:
    def complete_json_with_usage(self, system, user):
        from playground.llm_usage import JsonCompletion, LlmUsage
        return JsonCompletion(
            data={"answers": [{"questionId": "q_choice", "value": "fly" if sys.argv[3] == "invalid" else "walk_more"}]},
            usage=LlmUsage(n_input_tokens=17, n_output_tokens=0, cost_usd=0.001))
class Capturing(original):
    def __init__(self, delegate, instrument, captured):
        super().__init__(ScriptedClient(), instrument, captured)
batch.CapturingClient = Capturing
raise SystemExit(batch.main(sys.argv[2]))
''')

    class ScriptedRuntime(MatraixRuntime):
        def run_script(self, script, args, log, **kwargs):
            assert kwargs["live"] is False
            return super().run_script(wrapper, [str(script), *args, "invalid" if invalid else "valid"], log, **kwargs)

    settings = make_settings(matraix_root=Path(ROOT), runtime_python=Path(PYTHON))
    d = definition("fake")
    run_dir = settings.state_dir / "run"
    backend = MatraixBackend(d, ScriptedRuntime(settings), run_dir, settings, {})
    reqs = requests()
    cache = {}
    outcome = execute(d, reqs, backend, {}, lambda k, v: cache.update({k: v}))
    assert outcome.provider_calls == 0 and outcome.calls_attempted == 3
    assert len(outcome.responses) == 3
    assert len(cache) == (0 if invalid else 3)
    for i, (row, request) in enumerate(zip(outcome.responses, reqs)):
        trial = json.loads((run_dir / "matraix_batch_1" / f"trial_{i:04d}" / "trial_result.json").read_text())
        province = request.persona["model_visible"]["province_name"]
        other_province = "Bayburt" if province == "Ankara" else "Ankara"
        assert f"Province: {province}" in trial["user"] and f"Province: {other_province}" not in trial["user"]
        assert trial["usage"]["n_input_tokens"] == row["input_tokens"] == 17
        assert row["output_tokens"] == 0 and row["cost_usd"] == 0
        assert row["status"] == ("invalid_output" if invalid else "ok")
        assert row["choice"] == (None if invalid else "walk_more")
        if invalid:
            assert trial["error_kind"] == "invalid_output" and trial["response"]["answers"][0]["value"] == "fly"
