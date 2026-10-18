"""Agent runner: executes a reviewed plan through a backend, with a budget guard, retries and validation.

    Synthetic population -> cohort sample -> personas -> prompts -> backend -> structured responses

Backends share one interface (``run(requests) -> results``):

* ``StubBackend``: offline and deterministic. It picks an option from a hash of the prompt; it is NOT a
  model and its output is labelled as a pipeline test everywhere it appears.
* ``MatraixBackend``: MatrAIx's PersonaJsonSurvey in an isolated subprocess under the external runtime
  interpreter, with a SocietyTwin-generated task and per-persona MatrAIx persona files. Transport ``fake``
  uses MatrAIx's zero-cost smoke client; ``live`` calls the provider and is gated by configuration.
* ``ReplayBackend``: serves responses from the response cache of earlier runs; makes no calls. This is how
  a run is reproduced exactly (fresh model calls are expected to differ).

The budget guard counts every attempted backend call, retries included, and never exceeds ``max_calls``.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from societytwin.common import canonical_hash, redact, sha256_bytes, utc_now
from societytwin.national.experiments import ExperimentDefinition, parse_response

RUNNER_VERSION = "national-runner-1.0"
MAX_RAW_CHARS = 4000


@dataclass
class CallRequest:
    key: str                  # persona_id:sample_index
    persona: dict
    sample_index: int
    attempt: int
    system: str
    user: str

    def cache_key(self, definition: ExperimentDefinition) -> str:
        m = definition.model
        return canonical_hash({"backend": m.backend, "transport": m.transport, "model": m.model, "temperature": m.temperature,
                               "seed": m.seed, "max_output_tokens": m.max_output_tokens, "system": self.system,
                               "user": self.user, "sample_index": self.sample_index})


@dataclass
class CallResult:
    text: str | None
    provider_call: bool
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    error: str | None = None
    error_kind: str | None = None
    boundary_system: str | None = None
    boundary_user: str | None = None
    from_cache: bool = False
    attempted: bool = True     # False when the backend did not even start this call (e.g. cap reached inside a batch)


class StubBackend:
    name = "stub"
    label = "Stub backend: deterministic placeholder responses for pipeline testing. Not produced by a model."

    def __init__(self, definition: ExperimentDefinition):
        self.definition = definition

    def run(self, requests: list[CallRequest]) -> list[CallResult]:
        ids = [o.id for o in self.definition.task.options]
        out = []
        for r in requests:
            started = time.perf_counter()
            digest = hashlib.sha256(f"{r.system}\0{r.user}\0{r.sample_index}\0{self.definition.model.seed}".encode()).digest()
            choice = ids[int.from_bytes(digest[:8], "big") % len(ids)]
            payload = {"choice": choice, "rationale": "Stub placeholder; not produced by a model."}
            if choice == "other" and self.definition.task.allow_other_text:
                payload["other_text"] = "Stub placeholder."
            out.append(CallResult(json.dumps(payload), provider_call=False, latency_ms=round((time.perf_counter() - started) * 1000, 3),
                                  input_tokens=None, output_tokens=None, cost_usd=0.0))
        return out


class ReplayBackend:
    name = "replay"
    label = "Replay: responses served from the response cache of an earlier run; no backend was called."

    def __init__(self, definition: ExperimentDefinition, cache_lookup):
        self.definition = definition
        self.lookup = cache_lookup

    def run(self, requests: list[CallRequest]) -> list[CallResult]:
        out = []
        for r in requests:
            hit = self.lookup(r.cache_key(self.definition))
            if hit is None:
                out.append(CallResult(None, provider_call=False, error="no cached response for this prompt", error_kind="cache_miss"))
            else:
                out.append(CallResult(hit["text"], provider_call=False, latency_ms=hit.get("latency_ms"),
                                      input_tokens=hit.get("input_tokens"), output_tokens=hit.get("output_tokens"),
                                      cost_usd=0.0, from_cache=True))
        return out


class MatraixBackend:
    """Batch execution through MatrAIx. Each call is one PersonaJsonSurvey trial for one persona file."""

    name = "matraix"

    def __init__(self, definition: ExperimentDefinition, runtime, run_dir: Path, settings, live_credentials: dict | None):
        self.definition = definition
        self.runtime = runtime
        self.run_dir = run_dir
        self.settings = settings
        self.credentials = live_credentials or {}
        self.batches = 0

    @property
    def label(self) -> str:
        if self.definition.model.transport == "fake":
            return ("MatrAIx PersonaJsonSurvey with MatrAIx's fake transport: schema-valid placeholder answers, zero provider "
                    "calls. Demonstrates the integration, not persona behaviour.")
        return f"MatrAIx PersonaJsonSurvey with live model {self.definition.model.model}."

    def _task_dir(self, persona: dict, user_prompt: str) -> Path:
        task = self.run_dir / "matraix_task"
        if (task / "task.toml").is_file():
            return task
        d = self.definition
        (task / "input").mkdir(parents=True, exist_ok=True)
        (task / "task.toml").write_text(
            'version = "1.0"\nartifacts = [ "/app/output",]\n\n[task]\nname = "societytwin/experiment"\n\n'
            '[metadata]\ntype = "survey"\ndomain = "societytwin"\n\n[agent]\ntimeout_sec = 600.0\n\n'
            '[environment]\ndefinition = "application/shared-survey-form"\n', encoding="utf-8")
        (task / "instruction.md").write_text(
            f"# {d.title}\n\nRead the context, then answer the question with one of the listed option ids.\n", encoding="utf-8")
        context = user_prompt.split("\nTask:")[0].strip()
        (task / "input" / "context.md").write_text(context + "\n", encoding="utf-8")
        # MatrAIx renders the questionnaire description as the prompt's context, so it carries the full context text.
        questionnaire = {"schemaVersion": "1.0", "id": "societytwin_task", "title": d.title, "description": context,
                         "askRationale": d.task.ask_rationale,
                         "questions": [{"id": "q_choice", "prompt": d.task.instruction, "type": "single_choice", "required": True,
                                        "options": [{"id": o.id, "label": o.label} for o in d.task.options]}]}
        (task / "input" / "questionnaire.yaml").write_text(yaml.safe_dump(questionnaire, allow_unicode=True, sort_keys=False),
                                                           encoding="utf-8")
        return task

    def run(self, requests: list[CallRequest]) -> list[CallResult]:
        from societytwin.national.personas import matraix_persona

        if not requests:
            return []
        self.batches += 1
        batch = self.run_dir / f"matraix_batch_{self.batches}"
        task = self._task_dir(requests[0].persona, requests[0].user)
        trials = []
        for i, r in enumerate(requests):
            trial = batch / f"trial_{i:04d}"
            trial.mkdir(parents=True, exist_ok=True)
            persona_path = trial / "persona.yaml"
            persona_path.write_text(yaml.safe_dump(matraix_persona(r.persona), allow_unicode=True, sort_keys=False), encoding="utf-8")
            trials.append({"trial_id": r.key, "persona_path": str(persona_path), "output_dir": str(trial)})
        job = {"matraix_root": str(self.runtime.matraix_root()[0]), "task_dir": str(task), "transport": self.definition.model.transport,
               "model": self.definition.model.model, "temperature": self.definition.model.temperature,
               "max_output_tokens": self.definition.model.max_output_tokens, "max_calls": len(requests),
               "trials": trials, "report_path": str(batch / "batch_report.json")}
        job_path = batch / "job.json"
        job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
        result = self.runtime.run_script(Path(__file__).resolve().parents[1] / "agents" / "matraix_batch.py", [str(job_path)],
                                         batch / "batch.log", live=self.definition.model.transport == "live",
                                         credentials=self.credentials)
        out = []
        for r, trial in zip(requests, trials):
            path = Path(trial["output_dir"]) / "trial_result.json"
            if not path.is_file():
                out.append(CallResult(None, provider_call=False, attempted=False,
                                      error="MatrAIx batch did not produce a result for this trial: " + (result.error_tail or "")[:300],
                                      error_kind="backend"))
                continue
            rec = json.loads(path.read_text(encoding="utf-8"))
            answer = next((a for a in rec.get("answers") or [] if a.get("questionId") == "q_choice"), None)
            text = json.dumps({"choice": answer.get("value"), "rationale": answer.get("rationale") or None}) if answer else None
            usage = rec.get("usage") or {}
            out.append(CallResult(text, provider_call=bool(rec.get("provider_call")), latency_ms=rec.get("latency_ms"),
                                  input_tokens=usage.get("input_tokens") or usage.get("prompt_tokens"),
                                  output_tokens=usage.get("output_tokens") or usage.get("completion_tokens"),
                                  cost_usd=0.0 if self.definition.model.transport == "fake" else None,
                                  error=None if rec.get("ok") else redact(rec.get("error"), max_length=500),
                                  error_kind=None if rec.get("ok") else rec.get("error_kind", "backend"),
                                  boundary_system=rec.get("system"), boundary_user=rec.get("user"),
                                  attempted=rec.get("error_kind") != "budget"))
        return out


def load_prices(path: Path | None) -> dict:
    """Optional user-supplied price table (USD per million tokens). Nothing ships by default, so cost stays unknown."""
    if not path or not path.is_file():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: v for k, v in (payload.get("models") or {}).items() if isinstance(v, dict)}


def price_call(prices: dict, model: str | None, input_tokens, output_tokens) -> float | None:
    p = prices.get(model or "")
    if not p or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * float(p["input_per_mtok"]) + output_tokens * float(p["output_per_mtok"])) / 1e6


@dataclass
class RunOutcome:
    responses: list[dict] = field(default_factory=list)
    calls_attempted: int = 0
    provider_calls: int = 0
    budget_stopped: bool = False
    errors: list[str] = field(default_factory=list)


def execute(definition: ExperimentDefinition, requests: list[CallRequest], backend, prices: dict, cache_store) -> RunOutcome:
    """Run all requests with the retry policy and budget guard. Never raises for backend failures."""
    outcome = RunOutcome()
    cap = definition.execution.max_calls
    cost_cap = definition.execution.max_cost_usd
    pending = list(requests)
    spent = 0.0
    for attempt in range(1, definition.execution.max_attempts + 1):
        if not pending:
            break
        remaining = cap - outcome.calls_attempted
        if cost_cap is not None and spent >= cost_cap:
            remaining = 0
        batch, refused = pending[:max(remaining, 0)], pending[max(remaining, 0):]
        for r in refused:
            outcome.budget_stopped = True
            outcome.responses.append(_row(definition, r, attempt, "budget_exhausted", None, CallResult(None, False, attempted=False),
                                          "The call cap (or cost cap) was reached before this call."))
        if not batch:
            break
        for r in batch:
            r.attempt = attempt
        try:
            results = backend.run(batch)
        except Exception as exc:  # noqa: BLE001 - a backend crash fails these calls, it does not abort the run record
            outcome.errors.append(redact(f"{type(exc).__name__}: {exc}", max_length=500))
            results = [CallResult(None, False, error=str(exc)[:300], error_kind="backend", attempted=False) for _ in batch]
        retry = []
        for r, res in zip(batch, results):
            if res.attempted:
                outcome.calls_attempted += 1
            if res.provider_call:
                outcome.provider_calls += 1
            if res.cost_usd is None and res.provider_call:
                res.cost_usd = price_call(prices, definition.model.model, res.input_tokens, res.output_tokens)
            spent += res.cost_usd or 0.0
            if res.error:
                status = "cache_miss" if res.error_kind == "cache_miss" else "backend_error"
                outcome.responses.append(_row(definition, r, attempt, status, None, res, res.error))
                if res.error_kind not in ("cache_miss", "budget"):
                    retry.append(r)
                continue
            parsed = parse_response(res.text, definition.task)
            status = "ok" if parsed["valid"] else "invalid_output"
            outcome.responses.append(_row(definition, r, attempt, status, parsed, res, None if parsed["valid"] else parsed["error"]))
            if parsed["valid"] and not res.from_cache and cache_store is not None:
                cache_store(r.cache_key(definition), {"text": res.text, "latency_ms": res.latency_ms, "input_tokens": res.input_tokens,
                                                      "output_tokens": res.output_tokens, "created_at": utc_now()})
            if not parsed["valid"]:
                retry.append(r)
        pending = retry
    finals: dict[str, dict] = {}
    for row in outcome.responses:
        finals[row["request_key"]] = row
    for row in outcome.responses:
        row["is_final"] = finals[row["request_key"]] is row
    return outcome


def _row(definition: ExperimentDefinition, r: CallRequest, attempt: int, status: str, parsed: dict | None, res: CallResult,
         error: str | None) -> dict:
    system = res.boundary_system or r.system
    user = res.boundary_user or r.user
    return {
        "request_key": r.key, "persona_id": r.persona["persona_id"], "synthetic_id": r.persona["synthetic_id"],
        "province_code": r.persona["province_code"], "sample_index": r.sample_index, "attempt": attempt, "status": status,
        "choice": parsed.get("choice") if parsed and parsed.get("valid") else None,
        "other_text": parsed.get("other_text") if parsed else None, "rationale": parsed.get("rationale") if parsed else None,
        "raw_response": (res.text or "")[:MAX_RAW_CHARS] or None, "error": error,
        "latency_ms": res.latency_ms, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "cost_usd": res.cost_usd,
        "provider_call": res.provider_call, "from_cache": res.from_cache,
        "system_sha256": sha256_bytes(system.encode()), "user_sha256": sha256_bytes(user.encode()),
        "prompt_source": "transport_boundary" if res.boundary_system else "rendered_by_societytwin",
        "cache_key": r.cache_key(definition), "created_at": utc_now(),
    }


def provider_env_names(model: str | None) -> list[str]:
    prefix = (model or "/").split("/", 1)[0]
    return {"anthropic": ["ANTHROPIC_API_KEY"], "openai": ["OPENAI_API_KEY"], "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"]}.get(prefix, [])


def credentials_for(model: str | None) -> dict:
    return {n: os.environ[n] for n in provider_env_names(model) if os.environ.get(n)}
