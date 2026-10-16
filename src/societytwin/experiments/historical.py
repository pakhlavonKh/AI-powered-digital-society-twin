"""Import recorded run folders as read-only evidence.

Nothing here executes, modifies or re-runs anything. Display states are derived from all files
present; raw statuses written by the runners are preserved next to them. A folder name never decides
completion, and ``preflight.status == "prepared"`` is expected even in completed runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from societytwin.common import sha256_bytes, sha256_file
from societytwin.experiments.evidence_files import ARTIFACT_MEDIA_TYPES, MAX_ARTIFACT_BYTES, RunFiles
from societytwin.experiments.questionnaire import label_for, parse_questionnaire

RUN_DIR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TRIAL_DIR_PATTERN = re.compile(r"^trial_[A-Za-z0-9]{1,16}$")
USAGE_KEYS = ("n_input_tokens", "n_output_tokens", "n_cache_tokens", "cost_usd", "cost_source",
              "provider", "model", "request_id")
DISPLAY_STATES = {
    "completed": "Completed comparison recorded and every planned trial has a saved result.",
    "completed_fake": "Deterministic fake smoke run: wiring check only, zero provider calls, answers are not persona behaviour.",
    "partial": "At least one trial result is saved, but no completed comparison exists.",
    "outcome_unknown": "A provider request was started, but no response or failure was recorded. Not known to have failed, and not running.",
    "prepared_only": "Only a preflight plan exists; no trial evidence was recorded.",
    "malformed": "Evidence files exist but could not be parsed; nothing is inferred from them.",
    "unrecognized": "The folder does not contain a recognised runner layout.",
}
REPORT_CAVEAT = (
    "Historical descriptive report written by a local report script from saved artifacts. Its date is a file "
    "modification time, missing cost may be shown as zero, and any free-tier or billing statement is not "
    "established by provider usage. Source gender may appear here although it was hidden from the model. "
    "The JSON artifacts are the numerical authority."
)


def artifact_id(experiment_id: str, relpath: str) -> str:
    return "art_" + sha256_bytes(f"{experiment_id}:{relpath}".encode())[:16]


def normalize_usage(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    usage = {key: raw.get(key) for key in USAGE_KEYS}
    for key in ("n_input_tokens", "n_output_tokens", "n_cache_tokens"):
        if not (isinstance(usage[key], int) and not isinstance(usage[key], bool)):
            usage[key] = None
    if not isinstance(usage["cost_usd"], (int, float)) or isinstance(usage["cost_usd"], bool):
        usage["cost_usd"] = None
    usage["billed_cost_usd"] = None  # provider-billed amounts are never recorded by these runners
    return usage


def normalize_answer(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    question_id = raw.get("questionId", raw.get("question_id"))
    if not isinstance(question_id, str):
        return None
    rationale = raw.get("rationale")
    confidence = raw.get("confidence")
    return {
        "question_id": question_id,
        "value": raw.get("value"),
        "rationale": rationale if isinstance(rationale, str) and rationale.strip() else None,
        "confidence": confidence if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None,
    }


def _summarize_persona_snapshot(files: RunFiles, rel: str) -> dict | None:
    data = files.read_bytes(rel)
    if data is None:
        return None
    import yaml  # PyYAML is a declared dependency; safe_load never constructs objects

    try:
        payload = yaml.safe_load(data.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        files.evidence[rel].status = "malformed"
        return {"sha256": sha256_bytes(data), "parse_error": True}
    if not isinstance(payload, dict):
        return {"sha256": sha256_bytes(data), "parse_error": True}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    dimensions = payload.get("dimensions") if isinstance(payload.get("dimensions"), dict) else {}
    return {
        "sha256": sha256_bytes(data),
        "parse_error": False,
        "persona_id": payload.get("persona_id"),
        "dimensions": {str(k): str(v) for k, v in dimensions.items()},
        "source_attributes": metadata.get("source_attributes") if isinstance(metadata.get("source_attributes"), dict) else None,
        "source_csv_row": metadata.get("source_csv_row"),
        "unassigned_fields": metadata.get("unassigned_fields") if isinstance(metadata.get("unassigned_fields"), list) else [],
        "relpath": rel,
    }


def _prompt_record(system, user, source: str) -> dict | None:
    if not isinstance(system, str) or not isinstance(user, str):
        return None
    return {"system": system, "user": user, "system_sha256": sha256_bytes(system.encode()),
            "user_sha256": sha256_bytes(user.encode()), "source": source}


def _parse_trial(files: RunFiles, trial_dir: str, label: str, preflight_trial: dict | None, root_boundary: dict | None) -> dict:
    boundary = files.read_json(f"{trial_dir}/model_boundary.json")
    result = files.read_json(f"{trial_dir}/artifacts/app/output/survey_result.json")
    questionnaire_md = files.read_text(f"{trial_dir}/questionnaire.md")
    persona_meta = files.read_json(f"{trial_dir}/persona_meta.json")
    events, malformed = files.read_jsonl(f"{trial_dir}/events.jsonl")
    snapshot = _summarize_persona_snapshot(files, f"{trial_dir}/artifacts/app/input/persona.yaml")
    for rel in ("context.md", "instruction.md", "output_schema.md", "task_instruction.md"):
        files.read_bytes(f"{trial_dir}/{rel}")

    questions = parse_questionnaire(questionnaire_md) if questionnaire_md else []
    by_id = {q["id"]: q for q in questions}

    answers = None
    instrument = None
    usage = None
    if isinstance(result, dict):
        raw_answers = result.get("answers")
        if isinstance(raw_answers, list):
            answers = []
            for raw in raw_answers:
                answer = normalize_answer(raw)
                if answer is None:
                    continue
                answer["label"], answer["label_source"] = label_for(by_id.get(answer["question_id"]), answer["value"])
                answers.append(answer)
        if isinstance(result.get("instrument"), dict):
            instrument = {"id": result["instrument"].get("id"), "title": result["instrument"].get("title")}
        usage = normalize_usage(result.get("usage"))

    boundary_status = None
    boundary_mode = None
    coerced = []
    prompts = None
    if isinstance(boundary, dict):
        boundary_status = boundary.get("status") if isinstance(boundary.get("status"), str) else None
        boundary_mode = boundary.get("mode") if isinstance(boundary.get("mode"), str) else None
        if isinstance(boundary.get("coerced_answers"), list):
            coerced = [
                {"question_id": c.get("questionId"), "original": c.get("original"), "recorded": c.get("recorded")}
                for c in boundary["coerced_answers"] if isinstance(c, dict)
            ]
        prompts = _prompt_record(boundary.get("system"), boundary.get("user"), f"{trial_dir}/model_boundary.json")
        if usage is None:
            usage = normalize_usage(boundary.get("usage"))
    elif isinstance(root_boundary, dict) and isinstance(root_boundary.get("calls"), list) and root_boundary["calls"]:
        call = root_boundary["calls"][0]
        if isinstance(call, dict):
            prompts = _prompt_record(call.get("system"), call.get("user"), "model_boundary.json (fake transport)")
        boundary_mode = root_boundary.get("mode")
        boundary_status = "fake_response" if boundary_mode == "fake" else None
    if prompts is None and isinstance(preflight_trial, dict):
        prompts = _prompt_record(preflight_trial.get("system"), preflight_trial.get("user"), "preflight.json (planned prompt)")

    persona_id = None
    for candidate in (snapshot or {}).get("persona_id"), (preflight_trial or {}).get("persona_id"), (persona_meta or {}).get("persona_id") if isinstance(persona_meta, dict) else None:
        if isinstance(candidate, str):
            persona_id = candidate
            break

    if answers is not None and boundary_mode == "fake":
        state = "fake_result"
    elif answers is not None:
        state = "result_recorded"
    elif boundary_status == "request_started":
        state = "request_started_no_response"
    elif boundary_status == "response_received":
        state = "response_without_saved_result"
    else:
        state = "no_trial_evidence"

    event_types: dict[str, int] = {}
    for event in events or []:
        kind = event.get("type") if isinstance(event.get("type"), str) else "(untyped)"
        event_types[kind] = event_types.get(kind, 0) + 1

    return {
        "label": label,
        "trial_dir": trial_dir,
        "persona_id": persona_id,
        "state": state,
        "boundary_status_raw": boundary_status,
        "boundary_mode": boundary_mode,
        "instrument": instrument,
        "answers": answers,
        "answer_count": len(answers) if answers is not None else None,
        "usage": usage,
        "coerced_answers": coerced,
        "persona_snapshot": snapshot,
        "preflight_persona_sha256": (preflight_trial or {}).get("sha256") if isinstance(preflight_trial, dict) else None,
        "prompts": prompts,
        "questionnaire": {"questions": questions, "source": f"{trial_dir}/questionnaire.md"} if questions else None,
        "events_summary": {"count": len(events or []), "types": event_types, "malformed_lines": malformed,
                           "note": "Runtime log events; not a durable job queue and not a count of provider calls."},
    }


def _comparison_rows(trials: list[dict], comparison: dict | None) -> tuple[list[dict], list[dict]]:
    """Rows for side-by-side A/B display, recomputed from the trial results; checks against the recorded comparison."""
    checks: list[dict] = []
    if len(trials) != 2 or any(t["answers"] is None for t in trials):
        return [], checks
    a, b = ({x["question_id"]: x for x in t["answers"]} for t in trials)
    questionnaire = next((t["questionnaire"] for t in trials if t["questionnaire"]), None)
    order = [q["id"] for q in questionnaire["questions"]] if questionnaire else []
    order += [qid for qid in list(a) + list(b) if qid not in order]
    prompts = {q["id"]: q for q in (questionnaire or {}).get("questions", [])}
    recorded = {}
    if isinstance(comparison, dict) and isinstance(comparison.get("answers_compared"), list):
        for row in comparison["answers_compared"]:
            if isinstance(row, dict) and isinstance(row.get("question_id"), str):
                recorded[row["question_id"]] = row
    rows = []
    mismatched_values = []
    for qid in order:
        ans_a, ans_b = a.get(qid), b.get(qid)
        differs = None if ans_a is None or ans_b is None else ans_a["value"] != ans_b["value"]
        rec = recorded.get(qid)
        rec_differs = rec.get("value_differs") if isinstance(rec, dict) and isinstance(rec.get("value_differs"), bool) else None
        if rec is not None:
            for side, ans in (("answer_a", ans_a), ("answer_b", ans_b)):
                stored = rec.get(side)
                if not (isinstance(stored, dict) and ans is not None and stored.get("value") == ans["value"]):
                    mismatched_values.append(f"{qid}:{side}")
        question = prompts.get(qid)
        rows.append({
            "question_id": qid,
            "prompt": (question or {}).get("prompt") or (rec or {}).get("prompt"),
            "question_type": (question or {}).get("type"),
            "answer_a": ans_a,
            "answer_b": ans_b,
            "value_differs": differs,
            "recorded_value_differs": rec_differs,
        })
    if recorded:
        checks.append({"name": "comparison_values_match_trial_results", "passed": not mismatched_values,
                       "detail": "Every comparison answer equals the saved trial result." if not mismatched_values
                       else f"Mismatched entries: {', '.join(mismatched_values)}"})
        disagreements = [r["question_id"] for r in rows if r["recorded_value_differs"] is not None and r["recorded_value_differs"] != r["value_differs"]]
        checks.append({"name": "value_differs_recomputed", "passed": not disagreements,
                       "detail": "Recorded value_differs flags equal the recomputed flags." if not disagreements
                       else f"Disagreeing questions: {', '.join(disagreements)}"})
    return rows, checks


def parse_run(run_dir: Path, experiment_id: str, origin: str = "imported") -> dict:
    files = RunFiles(run_dir)
    listing = files.listing()
    preflight = files.read_json("preflight.json")
    comparison = files.read_json("comparison.json")
    smoke_report = files.read_json("smoke_report.json")
    root_boundary = files.read_json("model_boundary.json")
    budget = files.read_json("_matraix_budget.json")

    trial_dirs = sorted({rel.split("/", 1)[0] for rel, _, _ in listing if "/" in rel and TRIAL_DIR_PATTERN.fullmatch(rel.split("/", 1)[0])})
    is_fake = isinstance(smoke_report, dict) or (isinstance(root_boundary, dict) and root_boundary.get("mode") == "fake")
    kind = "fake_smoke" if is_fake else ("legacy_ab" if isinstance(preflight, dict) or trial_dirs else "unrecognized")

    preflight_trials = {}
    if isinstance(preflight, dict) and isinstance(preflight.get("trials"), list):
        for t in preflight["trials"]:
            if isinstance(t, dict) and isinstance(t.get("label"), str):
                preflight_trials[t["label"]] = t

    trials = []
    for trial_dir in trial_dirs:
        label = trial_dir.split("_", 1)[1]
        trials.append(_parse_trial(files, trial_dir, label, preflight_trials.get(label), root_boundary if is_fake else None))
    # Trials that were planned but never got a folder still appear, so absence is visible.
    for label, planned in preflight_trials.items():
        if not any(t["label"] == label for t in trials):
            trials.append({"label": label, "trial_dir": None, "persona_id": planned.get("persona_id"),
                           "state": "no_trial_evidence", "boundary_status_raw": None, "boundary_mode": None,
                           "instrument": None, "answers": None, "answer_count": None, "usage": None,
                           "coerced_answers": [], "persona_snapshot": None, "preflight_persona_sha256": planned.get("sha256"),
                           "prompts": _prompt_record(planned.get("system"), planned.get("user"), "preflight.json (planned prompt)"),
                           "questionnaire": None, "events_summary": {"count": 0, "types": {}, "malformed_lines": 0, "note": ""}})
    trials.sort(key=lambda t: t["label"])

    comparison_completed = isinstance(comparison, dict) and comparison.get("status") == "completed"
    with_results = [t for t in trials if t["answers"] is not None]
    started_only = [t for t in trials if t["state"] == "request_started_no_response"]
    planned_labels = set(preflight_trials) or {t["label"] for t in trials}
    if kind == "fake_smoke" and with_results:
        display_state = "completed_fake"
    elif kind == "legacy_ab" and comparison_completed and planned_labels and all(
            any(t["label"] == label and t["answers"] is not None for t in trials) for label in planned_labels):
        display_state = "completed"
    elif with_results:
        display_state = "partial"
    elif started_only:
        display_state = "outcome_unknown"
    elif isinstance(preflight, dict):
        display_state = "prepared_only"
    elif any(ev.status == "malformed" for ev in files.evidence.values()):
        display_state = "malformed"
    else:
        display_state = "unrecognized"

    rows, checks = _comparison_rows(trials, comparison) if kind == "legacy_ab" else ([], [])
    differing_recomputed = sum(1 for r in rows if r["value_differs"]) if rows else None
    differing_recorded = comparison.get("differing_values") if isinstance(comparison, dict) and isinstance(comparison.get("differing_values"), int) else None
    if rows and differing_recorded is not None:
        checks.append({"name": "differing_values_count", "passed": differing_recorded == differing_recomputed,
                       "detail": f"Recorded {differing_recorded}, recomputed {differing_recomputed}."})
    for t in trials:
        snap = t["persona_snapshot"] or {}
        if t["preflight_persona_sha256"] and snap.get("sha256"):
            checks.append({"name": f"trial_{t['label']}_snapshot_matches_preflight_hash",
                           "passed": snap["sha256"] == t["preflight_persona_sha256"],
                           "detail": "Saved persona snapshot bytes hash to the persona hash recorded in the preflight plan."
                           if snap["sha256"] == t["preflight_persona_sha256"] else "Snapshot hash differs from the preflight plan."})

    meta_source = comparison if isinstance(comparison, dict) else preflight if isinstance(preflight, dict) else {}
    model = meta_source.get("model") if isinstance(meta_source, dict) else None
    if model is None and is_fake:
        model = "smoke/fake"
    temperature = meta_source.get("temperature") if isinstance(meta_source, dict) else None
    limitations = []
    for source in (comparison, preflight, smoke_report):
        if isinstance(source, dict) and isinstance(source.get("limitations"), list):
            limitations = [str(x) for x in source["limitations"]]
            break

    warnings = []
    if files.skipped:
        warnings.append(f"{len(files.skipped)} symlink(s) or unsafe name(s) were ignored inside this folder.")
    for rel, ev in sorted(files.evidence.items()):
        if ev.status in {"malformed", "unreadable", "too_large", "unsafe"}:
            warnings.append(f"{rel}: {ev.status}")
    if started_only:
        warnings.append("Trial(s) " + ", ".join(t["label"] for t in started_only) +
                        " recorded request_started without a response. The outcome is unknown; this does not show a failure, "
                        "and the run is not active.")

    artifacts = []
    for rel, size, _ in listing:
        suffix = Path(rel).suffix.lower()
        if suffix not in ARTIFACT_MEDIA_TYPES or size > MAX_ARTIFACT_BYTES:
            continue
        name = Path(rel).name
        is_report = suffix in {".md", ".pdf"} and "report" in name.lower()
        artifacts.append({
            "artifact_id": artifact_id(experiment_id, rel),
            "relpath": rel,
            "media_type": ARTIFACT_MEDIA_TYPES[suffix],
            "size": size,
            "kind": "report" if is_report else ("snapshot" if suffix in {".md", ".yaml"} else "evidence"),
            "caveat": REPORT_CAVEAT if is_report else None,
        })

    run_usage = None
    if isinstance(comparison, dict):
        run_usage = normalize_usage(comparison.get("usage"))
        if run_usage is not None:
            sources = {t["usage"].get("cost_source") for t in trials if t["usage"]}
            run_usage["cost_source"] = sources.pop() if len(sources) == 1 else None
    budget_file = None
    if isinstance(budget, dict):
        budget_file = {"spent_usd": budget.get("spent_usd") if isinstance(budget.get("spent_usd"), (int, float)) else None,
                       "max_cost_usd": budget.get("max_cost_usd") if isinstance(budget.get("max_cost_usd"), (int, float)) else None,
                       "note": "Value recorded by the external framework's budget file; its existence does not show that a budget was enforced."}

    raw_statuses = {
        "preflight_status": preflight.get("status") if isinstance(preflight, dict) else None,
        "comparison_status": comparison.get("status") if isinstance(comparison, dict) else None,
        "smoke_report_ok": smoke_report.get("ok") if isinstance(smoke_report, dict) else None,
        "trial_boundaries": {t["label"]: t["boundary_status_raw"] for t in trials},
    }
    planned_calls = preflight.get("calls_planned") if isinstance(preflight, dict) else (1 if is_fake else None)
    return {
        "experiment_id": experiment_id,
        "origin": origin,
        "dirname": run_dir.name,
        "kind": kind,
        "evidence_kind": "fake" if is_fake else ("live" if any(t["boundary_mode"] == "live" for t in trials) else "unknown"),
        "display_state": display_state,
        "display_state_reason": DISPLAY_STATES[display_state],
        "raw_statuses": raw_statuses,
        "model": model,
        "temperature": temperature,
        "provider": preflight.get("provider") if isinstance(preflight, dict) else None,
        "task": (preflight.get("task") if isinstance(preflight, dict) else None) or (smoke_report.get("task") if isinstance(smoke_report, dict) else None),
        "planned_calls": planned_calls,
        "recorded_calls": comparison.get("calls") if isinstance(comparison, dict) else None,
        "provider_calls_recorded": (smoke_report.get("provider_calls") if isinstance(smoke_report, dict) else None),
        "automatic_retries": preflight.get("automatic_retries") if isinstance(preflight, dict) else None,
        "max_output_tokens_per_call": preflight.get("max_output_tokens_per_call") if isinstance(preflight, dict) else None,
        "historical_credentials_present": preflight.get("credentials_present") if isinstance(preflight, dict) else None,
        "runtime_seconds": comparison.get("runtime_seconds") if isinstance(comparison, dict) else None,
        "trials": trials,
        "comparison_rows": rows,
        "differing_values_recorded": differing_recorded,
        "differing_values_recomputed": differing_recomputed,
        "consistency_checks": checks,
        "usage": run_usage,
        "budget_file": budget_file,
        "limitations": limitations,
        "warnings": warnings,
        "files": [files.evidence[k].as_dict() for k in sorted(files.evidence)],
        "artifacts": artifacts,
        "listing_signature": sha256_bytes(repr(listing).encode()),
        "file_hashes": {rel: files.evidence[rel].sha256 for rel in files.evidence if files.evidence[rel].sha256},
    }


def file_manifest(run_dir: Path) -> dict[str, str]:
    files = RunFiles(run_dir)
    return {rel: sha256_file(run_dir / rel) for rel, _, _ in files.listing()}
