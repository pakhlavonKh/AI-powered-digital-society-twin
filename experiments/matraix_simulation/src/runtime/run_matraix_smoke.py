"""Run one real MatrAIx survey agent with its existing zero-cost smoke client.

Only the model transport is replaced. Answers demonstrate wiring, not persona behavior.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TASK = "application/tasks/example-survey_product-feedback"
PERSONA = ROOT / "personas" / "test_persona.yaml"


def default_matraix_root() -> Path:
    configured = os.environ.get("MATRAIX_ROOT")
    if configured:
        return Path(configured).expanduser()
    return ROOT.parents[2] / "MatrAIx-Persona-8B"


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ArtifactEnvironment:
    """The survey agent needs only upload_file; persist its two artifacts locally."""

    def __init__(self, trial):
        self.trial = trial

    async def upload_file(self, source, destination):
        locations = {
            "/app/input/persona.yaml": self.trial / "artifacts" / "app" / "input" / "persona.yaml",
            "/app/output/survey_result.json": self.trial / "artifacts" / "app" / "output" / "survey_result.json",
        }
        if destination not in locations:
            raise ValueError(f"Unexpected survey upload: {destination}")
        target = locations[destination]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(source).read_bytes())


async def run(repo, output):
    sys.path.insert(0, str(repo / "src"))
    from matraix.smoke import DeterministicSurveyJsonClient, ensure_launch_imports, _check_envelope
    ensure_launch_imports(repo)
    import matraix
    from pkgutil import extend_path
    matraix.__path__ = extend_path(matraix.__path__, matraix.__name__)
    from matraix.agents.persona.json_survey import PersonaJsonSurvey
    from harbor.models.agent.context import AgentContext
    from playground.survey_task_content import load_survey_task_content_for_task_path
    from playground.inprocess import survey_eval
    from matraix.agents.persona.loader import load_persona
    from matraix.agents.persona.templating import PERSONA_SYSTEM_TEMPLATE, render_persona_template, resolve_persona_template

    checksum = hashlib.sha256(PERSONA.read_bytes()).hexdigest()
    loaded = load_persona(str(PERSONA))
    expected_system = render_persona_template(resolve_persona_template(loaded, None, PERSONA_SYSTEM_TEMPLATE), loaded).strip()
    content = load_survey_task_content_for_task_path(TASK, repo_root=repo)
    instrument = content.instrument
    if instrument is None:
        raise ValueError("Existing task has no questionnaire")
    trial = output / "trial_001"
    logs = trial / "agent"
    logs.mkdir(parents=True, exist_ok=True)
    environment = ArtifactEnvironment(trial)
    delegate = DeterministicSurveyJsonClient(instrument)
    calls = []

    class CapturingSmokeClient:
        def complete_json(self, system, user):
            # Assert at the transport boundary, not just against a rendered preview.
            if system.strip() != expected_system:
                raise ValueError("Runner did not deliver the actual persona template to the client")
            for fragment in ("Ankara", "45-49", "Married", "gender_only"):
                if fragment not in system:
                    raise ValueError(f"Persona attribute absent from system context: {fragment}")
            if "source_sha256" in system or "generation_seed" in system:
                raise ValueError("Private provenance leaked into model context")
            if not user.strip() or any(q.id not in user for q in instrument.questions):
                raise ValueError("Task questions missing from user context")
            response = delegate.complete_json(system, user)
            calls.append(dict(system=system, user=user, response=response))
            write_json(output / "model_boundary.json", dict(mode="fake", provider_calls=0, calls=calls))
            return response

    client = CapturingSmokeClient()
    factories = []

    def client_factory(model):
        factories.append(model)
        if model != "smoke/fake":
            raise ValueError(f"Unexpected model request: {model}")
        return client

    agent = PersonaJsonSurvey(logs_dir=logs, persona_path=str(PERSONA),
                              survey_task_path=str(repo / TASK), model_name="smoke/fake")
    if agent._persona.persona_id != "ANK2025_000001":
        raise ValueError("Agent loaded the wrong resident")
    context = AgentContext()
    with patch.object(survey_eval, "build_json_client", client_factory):
        await agent.setup(environment)
        await agent.run(instruction=content.combined_markdown(), environment=environment, context=context)
    result_path = trial / "artifacts" / "app" / "output" / "survey_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    errors = _check_envelope(result, instrument=instrument)
    if errors or len(calls) != 1 or len(factories) != 1 or delegate.calls != 1:
        raise ValueError(f"Single-trial validation failed: {errors}")
    if len(result["answers"]) != len(instrument.questions):
        raise ValueError("Not all task questions answered")
    if calls[0]["response"]["answers"] != result["answers"]:
        # Compare values explicitly because the runtime may add defaults/metadata.
        expected = {a["questionId"]: a["value"] for a in calls[0]["response"]["answers"]}
        actual = {a["questionId"]: a["value"] for a in result["answers"]}
        if expected != actual:
            raise ValueError("Stored result differs from model-client answers")
    if hashlib.sha256(PERSONA.read_bytes()).hexdigest() != checksum:
        raise ValueError("Source persona changed")
    uploaded = trial / "artifacts" / "app" / "input" / "persona.yaml"
    if uploaded.read_bytes() != PERSONA.read_bytes():
        raise ValueError("Agent upload does not match the existing persona")
    report = dict(ok=True, task=TASK, persona_id=loaded.persona_id, persona_path=str(PERSONA),
                  persona_sha256=checksum, agent=agent.name(), agent_class=f"{type(agent).__module__}.{type(agent).__name__}",
                  runtime="host json_survey; actual PersonaJsonSurvey.setup/run; local artifact-transfer adapter",
                  trials=1, persona_loaded=True, prompt_conditioning_verified=True,
                  model_mode="fake", logical_calls=len(calls), provider_calls=0, cost_usd=0,
                  answered_questions=len(result["answers"]), trajectory_events=len(result["trajectory"]),
                  result_path=str(result_path), prompt_evidence=str(output / "model_boundary.json"),
                  limitations=["No live LLM was called; deterministic answers are not persona-faithful.",
                               "No Harbor job scheduler, Docker environment, or task verifier was run."])
    write_json(output / "smoke_report.json", report)
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matraix-root", type=Path, default=default_matraix_root())
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / "matraix_smoke")
    args = parser.parse_args()
    asyncio.run(run(args.matraix_root.resolve(), args.output_dir.resolve()))


if __name__ == "__main__":
    main()
