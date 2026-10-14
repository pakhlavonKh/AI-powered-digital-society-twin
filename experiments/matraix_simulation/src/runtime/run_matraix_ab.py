"""Prepare or execute two persona-conditioned survey trials; no enrichment or retries."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from pkgutil import extend_path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.runtime.run_matraix_smoke import ArtifactEnvironment, TASK, write_json

PERSONAS = (ROOT / "personas" / "test_persona.yaml", ROOT / "personas" / "persona_b.yaml")
EXPECTED_IDS = ("ANK2025_000001", "ANK2025_000183")
KEYS = {
    "anthropic": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"), "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "dashscope": ("DASHSCOPE_API_KEY",), "openrouter": ("OPENROUTER_API_KEY",),
    "xai": ("XAI_API_KEY",), "deepseek": ("DEEPSEEK_API_KEY",), "zai": ("ZAI_API_KEY",),
}


def default_matraix_root() -> Path:
    configured = os.environ.get("MATRAIX_ROOT")
    if configured:
        return Path(configured).expanduser()
    return ROOT.parents[2] / "MatrAIx-Persona-8B"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def setup_imports(repo):
    sys.path.insert(0, str(repo / "src"))
    from matraix.smoke import ensure_launch_imports
    ensure_launch_imports(repo)
    import matraix
    matraix.__path__ = extend_path(matraix.__path__, matraix.__name__)


def prepare(repo, output, model, temperature):
    from matraix.agents.persona.loader import load_persona
    from matraix.agents.persona.json_survey import _eval_persona
    from playground.survey_task_content import load_survey_task_content_for_task_path
    from playground.inprocess.survey_eval import persona_system_prompt, build_survey_task_prompt
    from playground.model_client import _llm_proxy_base_url
    from playground.openai_client import openai_model_supports_custom_temperature

    provider = model.split("/", 1)[0]
    if provider not in KEYS:
        raise ValueError("Select an explicitly supported provider/model prefix")
    if not 0 <= temperature <= 1:
        raise ValueError("This minimal test requires temperature in [0, 1]")
    if not openai_model_supports_custom_temperature(model.split("/", 1)[1]):
        raise ValueError("Select a model that supports explicit equal temperature settings")
    proxy = provider == "anthropic" and bool(_llm_proxy_base_url())
    if proxy:
        raise ValueError("This minimal test requires direct Anthropic or an explicitly selected compatible provider")
    content = load_survey_task_content_for_task_path(TASK, repo_root=repo)
    instrument = content.instrument
    user = build_survey_task_prompt(instrument=instrument)
    planned = []
    for label, path, expected_id in zip(("A", "B"), PERSONAS, EXPECTED_IDS):
        loaded = load_persona(str(path))
        if loaded.persona_id != expected_id:
            raise ValueError(f"Wrong existing persona in slot {label}")
        system = persona_system_prompt(_eval_persona(loaded), persona_yaml_path=str(path))
        if "Ankara" not in system or loaded.dimensions["dst_age_group"] not in system or loaded.dimensions["demo_marital_status"] not in system:
            raise ValueError("Persona failed to reach rendered context")
        if "source_sha256" in system or "generation_seed" in system:
            raise ValueError("Private metadata leaked into prompt")
        planned.append(dict(label=label, persona_id=expected_id, path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            dimensions=loaded.dimensions, system=system, user=user,
                            estimated_input_tokens_chars_div_4=round((len(system) + len(user)) / 4)))
    if planned[0]["user"] != planned[1]["user"] or planned[0]["system"] == planned[1]["system"]:
        raise ValueError("A/B task must match and persona contexts must differ")
    plan = dict(status="prepared", model=model, temperature=temperature, provider=provider,
                required_env_any_of=KEYS[provider], credentials_present=any(os.environ.get(k) for k in KEYS[provider]),
                task=TASK, calls_planned=2, automatic_retries=0,
                max_output_tokens_per_call=2048 if provider == "anthropic" else None,
                expected_answer_count=len(instrument.questions), trials=planned,
                estimate_note="Character-count heuristic only; exact input/output tokens come from provider usage.",
                limitations=["Two trials cannot establish causality or population validity.",
                             "Marital status was sampled by gender only, not jointly with age.",
                             "The task requires preferences absent from these personas; model defaults may fill gaps."])
    write_json(output / "preflight.json", plan)
    return plan, instrument


async def execute(repo, output, plan, instrument):
    from matraix.agents.persona.json_survey import PersonaJsonSurvey
    from harbor.models.agent.context import AgentContext
    from playground.inprocess import survey_eval
    from playground.model_client import build_json_client

    if not plan["credentials_present"]:
        raise RuntimeError("No configured API key; live execution blocked before any call")
    if (output / "comparison.json").exists() or any(output.glob("trial_*/model_boundary.json")):
        raise RuntimeError("Existing live evidence found; choose a fresh output directory to avoid repeating calls")
    completed, calls = [], 0
    started = time.perf_counter()
    for trial_plan in plan["trials"]:
        trial = output / f"trial_{trial_plan['label']}"
        logs = trial / "agent"
        logs.mkdir(parents=True, exist_ok=True)
        client = build_json_client(plan["model"], temperature=plan["temperature"])
        if plan["provider"] == "anthropic":
            client.max_tokens = 2048
        elif hasattr(client, "_client"):
            client._client = client._client.with_options(max_retries=0)
        requests = []

        class CapturingLiveClient:
            def complete_json_with_usage(self, system, user):
                nonlocal calls
                if requests or calls >= 2:
                    raise RuntimeError("Two-call cap or single-trial call cap exceeded")
                if system != trial_plan["system"] or user != trial_plan["user"]:
                    raise ValueError("Actual client input differs from the prepared A/B prompts")
                calls += 1
                boundary = dict(mode="live", model=plan["model"], temperature=plan["temperature"],
                                system=system, user=user, status="request_started")
                requests.append(boundary)
                write_json(trial / "model_boundary.json", boundary)
                completion = client.complete_json_with_usage(system, user)
                answers = completion.data.get("answers", [])
                expected = {q.id: q for q in instrument.questions}
                ids = [a.get("questionId") for a in answers if isinstance(a, dict)]
                if len(ids) != len(answers) or len(ids) != len(set(ids)) or set(ids) != set(expected):
                    raise ValueError("Live answer IDs are missing, duplicated, or unknown; no neutral fill-in accepted")
                for answer in answers:
                    if answer.get("value") != survey_eval._normalize_value(answer.get("value"), expected[answer["questionId"]]):
                        raise ValueError("Invalid model answer; runtime normalization would change it")
                boundary.update(status="response_received", response=completion.data,
                                usage=completion.usage.to_dict() if completion.usage else None)
                write_json(trial / "model_boundary.json", boundary)
                return completion

        transport = CapturingLiveClient()

        def factory(model):
            if model != plan["model"]:
                raise ValueError("Unexpected runtime model")
            return transport

        agent = PersonaJsonSurvey(logs_dir=logs, persona_path=trial_plan["path"],
                                  survey_task_path=str(repo / TASK), model_name=plan["model"])
        context = AgentContext()
        environment = ArtifactEnvironment(trial)
        trial_start = time.perf_counter()
        with patch.object(survey_eval, "build_json_client", factory):
            await agent.setup(environment)
            await agent.run(instruction="", environment=environment, context=context)
        result_path = trial / "artifacts" / "app" / "output" / "survey_result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if hashlib.sha256(Path(trial_plan["path"]).read_bytes()).hexdigest() != trial_plan["sha256"]:
            raise ValueError("Persona changed during trial")
        completed.append(dict(label=trial_plan["label"], persona_id=trial_plan["persona_id"],
                              answers=result["answers"], usage=result.get("usage"), result_path=str(result_path),
                              runtime_seconds=time.perf_counter() - trial_start))
    compared = []
    a = {r["questionId"]: r for r in completed[0]["answers"]}
    b = {r["questionId"]: r for r in completed[1]["answers"]}
    for question in instrument.questions:
        compared.append(dict(question_id=question.id, prompt=question.prompt, answer_a=a[question.id],
                             answer_b=b[question.id], value_differs=a[question.id]["value"] != b[question.id]["value"]))
    usages = [t["usage"] or {} for t in completed]
    aggregate = {key: sum(u[key] for u in usages) if all(key in u for u in usages) else None
                 for key in ("n_input_tokens", "n_output_tokens", "n_cache_tokens", "cost_usd")}
    report = dict(status="completed", model=plan["model"], temperature=plan["temperature"],
                  calls=calls, trials=completed, answers_compared=compared,
                  differing_values=sum(r["value_differs"] for r in compared), usage=aggregate,
                  cost_note="Provider-reported or MatrAIx local-table estimate; absent cost is unknown, not zero.",
                  runtime_seconds=time.perf_counter() - started, limitations=plan["limitations"])
    write_json(output / "comparison.json", report)
    return report


def main():
    load_env_file(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matraix-root", type=Path, default=default_matraix_root())
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / "matraix_ab_live")
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--execute", action="store_true", help="Make at most two live calls; default is preparation only")
    args = parser.parse_args()
    repo, output = args.matraix_root.resolve(), args.output_dir.resolve()
    setup_imports(repo)
    from playground.persona_model import resolve_persona_model
    model = resolve_persona_model(model_name=args.model)
    plan, instrument = prepare(repo, output, model, args.temperature)
    print(json.dumps({k: v for k, v in plan.items() if k != "trials"}, indent=2))
    print("Estimated input tokens per persona:", [(t["label"], t["estimated_input_tokens_chars_div_4"]) for t in plan["trials"]])
    if args.execute:
        report = asyncio.run(execute(repo, output, plan, instrument))
        print(json.dumps({k: v for k, v in report.items() if k not in {"trials", "answers_compared"}}, indent=2))


if __name__ == "__main__":
    main()
