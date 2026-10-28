"""Offline regression tests for the MatrAIx transport and national backend boundary."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

from societytwin.agents.matraix_batch import CapturingClient, InvalidRawAnswer
from societytwin.national.experiments import ExperimentDefinition, example_fare_definition
from societytwin.national.runner import CallRequest, MatraixBackend, execute


@pytest.fixture
def completion_type(monkeypatch):
    # Only the completion envelope is substituted. No provider SDK is loaded.
    @dataclass
    class Completion:
        data: dict
        usage: object = None

    playground = ModuleType("playground")
    usage = ModuleType("playground.llm_usage")
    usage.JsonCompletion = Completion
    monkeypatch.setitem(sys.modules, "playground", playground)
    monkeypatch.setitem(sys.modules, "playground.llm_usage", usage)
    return Completion


def instrument():
    return SimpleNamespace(questions=[SimpleNamespace(id="q_choice", type="single_choice", options=["walk_more", "other"])])


def test_usage_transport_captures_exact_prompts_and_zero_tokens(completion_type):
    usage = {"n_input_tokens": 123, "n_output_tokens": 0, "cost_usd": 0.004}
    raw = {"answers": [{"questionId": "q_choice", "value": "walk_more"}]}
    completion = completion_type(raw, SimpleNamespace(to_dict=lambda: usage))
    delegate = SimpleNamespace(complete_json_with_usage=lambda system, user: completion)
    captured = {}
    assert CapturingClient(delegate, instrument(), captured).complete_json_with_usage("system", "user") is completion
    assert captured["usage"] == usage and captured["response"] == raw
    assert captured["system"] == "system" and captured["user"] == "user"
    assert captured["latency_ms"] >= 0


@pytest.mark.parametrize("raw", [None, {}, {"answers": None}, {"answers": []}, {"answers": [None]},
    {"answers": [{"questionId": "unknown", "value": "walk_more"}]},
    {"answers": [{"questionId": [], "value": "walk_more"}]},
    {"answers": [{"questionId": "q_choice", "value": "walk_more"}] * 2},
    {"answers": [{"questionId": "q_choice"}]},
    {"answers": [{"questionId": "q_choice", "value": "fly"}]},
    {"answers": [{"questionId": "q_choice", "value": ["walk_more"]}]},
])
def test_invalid_raw_answers_are_rejected_with_usage_preserved(completion_type, raw):
    captured = {}
    delegate = SimpleNamespace(complete_json_with_usage=lambda *args: completion_type(
        raw, SimpleNamespace(to_dict=lambda: {"n_input_tokens": 12, "cost_usd": 0.01})))
    with pytest.raises(InvalidRawAnswer):
        CapturingClient(delegate, instrument(), captured).complete_json("system", "user")
    assert captured["response"] == raw and captured["usage"]["n_input_tokens"] == 12
    assert captured["latency_ms"] >= 0


def test_legacy_fake_transport_works_without_usage(completion_type):
    raw = {"answers": [{"questionId": "q_choice", "value": "walk_more"}]}
    captured = {}
    client = CapturingClient(SimpleNamespace(complete_json=lambda *args: raw), instrument(), captured)
    assert client.complete_json("s", "u") == raw and captured["usage"] is None


class ArtifactRuntime:
    """Writes scripted trial artifacts; never launches a subprocess or provider."""
    def __init__(self, records):
        self.records = records
        self.jobs = []

    def matraix_root(self):
        return Path("/unused"), None

    def run_script(self, script, args, log, **kwargs):
        job = json.loads(Path(args[0]).read_text())
        self.jobs.append(job)
        for trial, record in zip(job["trials"], self.records):
            (Path(trial["output_dir"]) / "trial_result.json").write_text(json.dumps(record))
        return SimpleNamespace(error_tail="")


def definition(transport="live", attempts=1):
    payload = example_fare_definition("cht_test")
    payload["model"] = {"backend": "matraix", "transport": transport, "model": "openai/test", "temperature": 0}
    payload["execution"].update(max_attempts=attempts, max_calls=10)
    return ExperimentDefinition(**payload)


def requests():
    return [CallRequest(f"per-{i}:1", {
        "persona_id": f"per-{i}", "synthetic_id": f"ST-{i}", "province_code": province,
        "model_visible": {"province_name": name}, "attributes": [], "template_version": "1",
        "population_id": "test", "hidden": [], "limitations": [], "provenance": {}},
        1, 1, f"system {i}", f"Province: {name}\nTask:\nChoose")
        for i, (province, name) in enumerate([("06", "Ankara"), ("69", "Bayburt"), ("06", "Ankara")])]


def record(usage=None, **overrides):
    return {"ok": True, "answers": [{"questionId": "q_choice", "value": "walk_more"}],
            "provider_call": True, "usage": usage, "system": "actual system", "user": "actual user", **overrides}


@pytest.mark.parametrize("usage,expected", [
    ({"n_input_tokens": 10, "n_output_tokens": 0, "input_tokens": 999, "cost_usd": 0.03}, (10, 0, 0.03)),
    ({"input_tokens": 0, "output_tokens": 2}, (0, 2, 0.000004)),
    ({"prompt_tokens": 10, "completion_tokens": 3}, (10, 3, 0.000016)),
    (None, (None, None, None)),
])
def test_artifact_usage_maps_to_response_and_price_fallback(tmp_path, usage, expected):
    d = definition()
    runtime = ArtifactRuntime([record(usage)])
    backend = MatraixBackend(d, runtime, tmp_path, None, {})
    prices = {"openai/test": {"input_per_mtok": 1, "output_per_mtok": 2}}
    rows = execute(d, requests()[:1], backend, prices, None).responses
    assert (rows[0]["input_tokens"], rows[0]["output_tokens"], rows[0]["cost_usd"]) == expected
    assert rows[0]["status"] == "ok" and rows[0]["prompt_source"] == "transport_boundary"


def test_context_is_selected_per_person_and_reused_across_retries(tmp_path):
    d = definition("fake")
    runtime = ArtifactRuntime([record()] * 3)
    backend = MatraixBackend(d, runtime, tmp_path, None, {})
    reqs = requests()
    assert all(r.cost_usd == 0 and r.text for r in backend.run(reqs))
    first = runtime.jobs[0]["trials"]
    assert first[0]["task_dir"] == first[2]["task_dir"] != first[1]["task_dir"]
    for req, trial in zip(reqs, first):
        task = Path(trial["task_dir"])
        context = task.joinpath("input/context.md").read_text().strip()
        questionnaire = yaml.safe_load(task.joinpath("input/questionnaire.yaml").read_text())
        assert context == req.user.split("\nTask:")[0] == questionnaire["description"]
    backend.run([reqs[1]])
    assert runtime.jobs[1]["trials"][0]["task_dir"] == first[1]["task_dir"]


def test_invalid_output_is_not_cached_and_retains_usage_on_retry(tmp_path):
    raw = {"answers": [{"questionId": "q_choice", "value": "fly"}]}
    invalid = record({"n_input_tokens": 10, "n_output_tokens": 2, "cost_usd": 0.01},
                     ok=False, answers=None, response=raw, error_kind="invalid_output", error="Invalid model answer")
    d = definition(attempts=2)
    runtime = ArtifactRuntime([invalid])
    backend = MatraixBackend(d, runtime, tmp_path, None, {})
    cache = {}
    outcome = execute(d, requests()[:1], backend, {}, lambda k, v: cache.update({k: v}))
    assert not cache and outcome.provider_calls == outcome.calls_attempted == 2
    assert [r["is_final"] for r in outcome.responses] == [False, True]
    for row in outcome.responses:
        assert row["status"] == "invalid_output" and row["choice"] is None and row["error"]
        assert row["cost_usd"] == 0.01 and row["input_tokens"] == 10
        assert json.loads(row["raw_response"]) == raw
