import json
import os
import shutil

import pytest

from societytwin.experiments.evidence_files import RunFiles
from societytwin.experiments.historical import parse_run
from societytwin.experiments.questionnaire import label_for, parse_questionnaire


def run(settings, name, new_name=None):
    path = settings.import_runs_root / name
    if new_name:
        target = settings.import_runs_root / new_name
        shutil.move(path, target)
        path = target
    return parse_run(path, f"imp_{path.name}")


def test_completed_ab_run(settings):
    r = run(settings, "ab_complete")
    assert r["kind"] == "legacy_ab" and r["display_state"] == "completed" and r["evidence_kind"] == "live"
    assert r["raw_statuses"]["preflight_status"] == "prepared"  # preserved even though the run completed
    assert r["differing_values_recorded"] == r["differing_values_recomputed"] == 2
    assert all(c["passed"] for c in r["consistency_checks"])
    ids = [row["question_id"] for row in r["comparison_rows"]]
    assert ids == ["q_pick", "q_scale", "q_beta", "q_unlisted"]  # unlisted IDs appear once, after the snapshot order
    rows = {row["question_id"]: row for row in r["comparison_rows"]}
    assert rows["q_pick"]["value_differs"] is False and rows["q_scale"]["value_differs"] is True
    assert rows["q_pick"]["answer_a"]["label"] == "Invented option A."
    assert rows["q_scale"]["answer_a"]["label"] == "4 on a 1–5 scale"
    unlisted = rows["q_unlisted"]["answer_a"]
    assert unlisted["label"] is None and unlisted["label_source"] == "code_only" and unlisted["value"] == "mystery_code"
    a = r["trials"][0]
    assert a["coerced_answers"] == [{"question_id": "q_beta", "original": True, "recorded": "true"}]
    assert a["answers"][0]["rationale"] is None and a["answers"][0]["confidence"] is None
    assert a["usage"]["n_cache_tokens"] is None and a["usage"]["cost_source"] == "estimated"
    assert a["usage"]["billed_cost_usd"] is None
    assert r["usage"]["n_cache_tokens"] is None and r["usage"]["cost_usd"] == 0.0003
    assert r["usage"]["cost_source"] == "estimated"
    assert "C:\\\\Users" not in json.dumps(r) and "C:\\Users" not in json.dumps(r)
    reports = [x for x in r["artifacts"] if x["kind"] == "report"]
    assert reports and "numerical authority" in reports[0]["caveat"]


def test_fake_smoke_is_separate(settings):
    r = run(settings, "smoke_fake")
    assert r["kind"] == "fake_smoke" and r["display_state"] == "completed_fake" and r["evidence_kind"] == "fake"
    assert r["provider_calls_recorded"] == 0 and r["model"] == "smoke/fake"
    assert r["trials"][0]["state"] == "fake_result"
    assert r["trials"][0]["prompts"]["source"].startswith("model_boundary.json")


@pytest.mark.parametrize("name, state", [("partial", "partial"), ("started_only", "outcome_unknown"),
                                         ("prepared_only", "prepared_only"), ("malformed", "malformed"),
                                         ("unrecognized", "unrecognized")])
def test_incomplete_states(settings, name, state):
    r = run(settings, name)
    assert r["display_state"] == state
    assert r["comparison_rows"] == []


def test_request_started_is_neither_failed_nor_running(settings):
    r = run(settings, "started_only")
    assert r["trials"][0]["state"] == "request_started_no_response"
    assert r["trials"][1]["state"] == "no_trial_evidence"  # planned in preflight, never started
    text = " ".join(r["warnings"]) + r["display_state_reason"]
    assert "unknown" in text and "not running" in r["display_state_reason"].lower()


def test_partial_run_exposes_accepted_trial_without_comparison(settings):
    r = run(settings, "partial")
    a, b = r["trials"]
    assert a["answers"] and a["state"] == "result_recorded"
    assert b["state"] == "request_started_no_response" and b["answers"] is None
    assert r["differing_values_recomputed"] is None


def test_directory_name_does_not_decide_completion(settings):
    assert run(settings, "ab_complete", "run_FAILED")["display_state"] == "completed"
    path = settings.import_runs_root / "run_FAILED" / "trial_B" / "artifacts" / "app" / "output" / "survey_result.json"
    path.unlink()
    assert parse_run(path.parents[4], "imp_x")["display_state"] == "partial"


def test_recorded_comparison_disagreement_is_reported(settings):
    path = settings.import_runs_root / "ab_complete" / "comparison.json"
    data = json.loads(path.read_text())
    data["differing_values"] = 4
    data["answers_compared"][0]["value_differs"] = True
    path.write_text(json.dumps(data))
    r = run(settings, "ab_complete")
    checks = {c["name"]: c["passed"] for c in r["consistency_checks"]}
    assert checks["differing_values_count"] is False and checks["value_differs_recomputed"] is False
    assert r["differing_values_recomputed"] == 2  # recomputed from trial results, not copied


def test_snake_case_answers_are_accepted(settings):
    path = settings.import_runs_root / "partial" / "trial_A" / "artifacts" / "app" / "output" / "survey_result.json"
    data = json.loads(path.read_text())
    data["answers"] = [{"question_id": a["questionId"], "value": a["value"]} for a in data["answers"]]
    path.write_text(json.dumps(data))
    assert [a["question_id"] for a in run(settings, "partial")["trials"][0]["answers"]][:2] == ["q_pick", "q_scale"]


def test_symlinks_and_unsafe_paths_are_ignored(settings, tmp_path):
    outside = tmp_path / "secret.json"
    outside.write_text('{"secret": true}')
    os.symlink(outside, settings.import_runs_root / "ab_complete" / "leak.json")
    r = run(settings, "ab_complete")
    assert all(a["relpath"] != "leak.json" for a in r["artifacts"])
    files = RunFiles(settings.import_runs_root / "ab_complete")
    assert files.read_bytes("leak.json") is None and files.evidence["leak.json"].status == "unsafe"
    for bad in ("../ab_complete/comparison.json", "/etc/passwd", "trial_A/../../x"):
        assert files.read_bytes(bad) is None


def test_questionnaire_parser_ignores_non_question_sections():
    text = "## q1\n\nPrompt: Hello\n\n- Type: `likert`\n- Scale: `1`-`3`\n\n## Answer envelope\n\nNo prompt here.\n"
    questions = parse_questionnaire(text)
    assert [q["id"] for q in questions] == ["q1"]
    assert label_for(questions[0], 2) == ("2 on a 1–3 scale", "questionnaire_snapshot")
    assert label_for(questions[0], True) == (None, "code_only")
    assert label_for(None, "x") == (None, "code_only")
