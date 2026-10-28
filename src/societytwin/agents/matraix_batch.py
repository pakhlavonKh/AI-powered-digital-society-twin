"""Run MatrAIx's PersonaJsonSurvey for many persona files against one SocietyTwin-generated survey task.

Executed by path under the external MatrAIx runtime interpreter (``python -I -B matraix_batch.py job.json``).
It imports nothing from SocietyTwin. The SocietyTwin service writes the job file, the task directory and
the persona YAMLs, then reads ``trial_result.json`` per trial and ``batch_report.json``.

Transports:
- ``fake``: MatrAIx's own DeterministicSurveyJsonClient (schema-valid placeholder answers, zero provider
  calls). The parent process also points proxy variables at a closed port, so no request can leave.
- ``live``: MatrAIx's ``build_json_client(model)``; SDK retries are disabled and calls stop at ``max_calls``.

The prompts are captured at the transport boundary, i.e. exactly what the model client received.
"""

from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("SYSTEMROOT", r"C:\Windows")
    os.environ.setdefault("WINDIR", r"C:\Windows")
    if os.environ.get("HOME"):
        os.environ.setdefault("USERPROFILE", os.environ["HOME"])

import asyncio
import json
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import patch


class ArtifactEnvironment:
    """The survey agent only uploads two artifacts; keep them in the trial folder."""

    def __init__(self, trial: Path):
        self.trial = trial

    async def upload_file(self, source, destination):
        locations = {"/app/input/persona.yaml": self.trial / "artifacts" / "app" / "input" / "persona.yaml",
                     "/app/output/survey_result.json": self.trial / "artifacts" / "app" / "output" / "survey_result.json"}
        if destination not in locations:
            raise ValueError(f"Unexpected survey upload: {destination}")
        target = locations[destination]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(source).read_bytes())


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(job_path: str) -> int:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    repo = Path(job["matraix_root"])
    sys.path.insert(0, str(repo / "src"))
    from matraix.smoke import DeterministicSurveyJsonClient, ensure_launch_imports
    ensure_launch_imports(repo)
    import matraix
    from pkgutil import extend_path
    matraix.__path__ = extend_path(matraix.__path__, matraix.__name__)
    from harbor.models.agent.context import AgentContext
    from matraix.agents.persona.json_survey import PersonaJsonSurvey
    from playground.inprocess import survey_eval
    from playground.survey_task_content import load_survey_task_content_for_task_path

    content = load_survey_task_content_for_task_path(job["task_dir"], repo_root=repo)
    instrument = content.instrument
    if instrument is None:
        raise SystemExit("generated task has no questionnaire")
    live = job["transport"] == "live"
    calls = 0
    report = {"transport": job["transport"], "model": job.get("model"), "trials": [], "provider_calls": 0}
    for trial in job["trials"]:
        out = Path(trial["output_dir"])
        captured: dict = {}
        if live and calls >= job["max_calls"]:
            _write(out / "trial_result.json", {"ok": False, "error": "call cap reached before this trial", "error_kind": "budget",
                                              "provider_call": False})
            report["trials"].append({"trial_id": trial["trial_id"], "ok": False, "budget": True})
            continue
        if live:
            from playground.model_client import build_json_client
            delegate = build_json_client(job["model"], temperature=job["temperature"])
            if job["model"].startswith("anthropic/"):
                delegate.max_tokens = job["max_output_tokens"]
            elif hasattr(delegate, "_client"):
                delegate._client = delegate._client.with_options(max_retries=0)
        else:
            delegate = DeterministicSurveyJsonClient(instrument)

        class Capturing:
            def complete_json(self, system, user):
                started = time.perf_counter()
                captured.update(system=system, user=user)
                response = delegate.complete_json(system, user)
                captured.update(response=response, latency_ms=round((time.perf_counter() - started) * 1000, 1))
                return response

        client = Capturing()
        logs = out / "agent"
        logs.mkdir(parents=True, exist_ok=True)
        agent = PersonaJsonSurvey(logs_dir=logs, persona_path=trial["persona_path"], survey_task_path=job["task_dir"],
                                  model_name=job["model"] if live else "smoke/fake")

        async def run_one():
            env = ArtifactEnvironment(out)
            await agent.setup(env)
            await agent.run(instruction=content.combined_markdown(), environment=env, context=AgentContext())

        record = {"ok": False, "provider_call": False}
        try:
            with patch.object(survey_eval, "build_json_client", lambda *args, **kwargs: client):
                asyncio.run(run_one())
            if live:
                calls += 1
            result = json.loads((out / "artifacts" / "app" / "output" / "survey_result.json").read_text(encoding="utf-8"))
            record.update(ok=True, answers=result.get("answers"), usage=result.get("usage"), provider_call=live)
        except Exception as exc:  # noqa: BLE001 - every trial failure is recorded, none is retried here
            if live and "system" in captured:
                calls += 1
                record["provider_call"] = True
            record.update(error=f"{type(exc).__name__}: {exc}"[:800], error_kind="backend",
                          traceback=traceback.format_exc()[-1500:])
        record.update(system=captured.get("system"), user=captured.get("user"), response=captured.get("response"),
                      latency_ms=captured.get("latency_ms"))
        _write(out / "trial_result.json", record)
        report["trials"].append({"trial_id": trial["trial_id"], "ok": record["ok"]})
    report["provider_calls"] = calls
    _write(Path(job["report_path"]), report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
