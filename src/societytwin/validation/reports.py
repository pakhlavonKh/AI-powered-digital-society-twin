"""Simulation Results Evaluator & Combined Quality Reports (K6/K7) — ``src/societytwin/validation/reports.py``.

Provides:
1. Simulation results evaluation against persona cohorts and behavioral benchmarks (K6).
2. Combined Quality Report (K7) integrating:
   - Population marginal validation (K3)
   - Multidimensional dependency and joint distribution validation (K4)
   - Simulation results evaluation and behavioral benchmarks (K6)
3. UI / API compatibility adapter matching existing endpoints (`/populations/{id}/validation`, `/builds/{id}/validation`).
4. Deterministic, byte-identical on-disk persistence (no timestamps in content hash, sorted keys).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, StrictBool, StrictInt

from societytwin.common import canonical_hash
from societytwin.evidence.registry import (
    ANKARA_HOUSEHOLD_DISCREPANCY_FLAG,
    EDUCATION_UNIVERSE_GAP_FLAG,
    LABOUR_RATE_ONLY_FLAG,
)
from societytwin.national.dependencies import TypedModel
from societytwin.validation.behavioral import (
    BenchmarkBundle,
    BenchmarkStatus,
    EvidenceType,
    get_ankara_transit_fare_bundle,
)
from societytwin.validation.dependencies import (
    DependencyValidationReport,
    validate_dependencies,
)
from societytwin.validation.population import (
    CalibrationTolerances,
    CheckStatus,
    DatasetProvenance,
    PopulationValidationReport,
    validate_population,
)

COMBINED_REPORT_SCHEMA_VERSION = "combined-quality-report-k7-v1"
SIMULATION_REPORT_SCHEMA_VERSION = "simulation-evaluation-report-k6-v1"
EVALUATOR_VERSION = "k7-quality-reports-1.0"
REPORTS_EVALUATOR_VERSION = EVALUATOR_VERSION
MIN_SUBGROUP_N_DEFAULT = 15

ResultStatus = Literal["valid", "invalid", "failed", "refused", "timeout"]
EvidenceStatus = Literal[
    "synthetic_simulation_baseline",
    "empirical_ground_truth",
    "literature_envelope",
    "unverified_hypothetical",
]


def _normalize_dst_status(raw_status_val: Any) -> tuple[ResultStatus, str]:
    """Normalize DST runtime status strings (e.g. 'ok', 'invalid_output', 'backend_error',
    'cache_miss', 'budget_exhausted') into ResultStatus while preserving raw_status.
    """
    raw_status = str(raw_status_val if raw_status_val is not None else "valid").strip()
    lowered = raw_status.lower()
    if lowered in ("ok", "valid", "completed", "success"):
        return "valid", raw_status
    if lowered in ("invalid_output", "invalid", "parse_error", "validation_error"):
        return "invalid", raw_status
    if lowered in ("refused", "refusal"):
        return "refused", raw_status
    if lowered in ("timeout", "timed_out"):
        return "timeout", raw_status
    if lowered in ("backend_error", "cache_miss", "budget_exhausted", "failed", "error"):
        return "failed", raw_status
    if "invalid" in lowered or "parse" in lowered:
        return "invalid", raw_status
    if "refus" in lowered:
        return "refused", raw_status
    if "timeout" in lowered or "timed_out" in lowered:
        return "timeout", raw_status
    return "failed", raw_status


def _resolve_question_and_valid_options(
    experiment_definition: Any,
    default_question_id: str,
    choice: Any,
) -> tuple[str, set[str] | None, bool]:
    """Resolve question_id and allowed option IDs from an experiment or scenario definition.

    Returns (question_id, valid_option_ids_or_None, allow_other).
    """
    question_id = default_question_id or "task_choice"
    valid_options: set[str] | None = None
    allow_other = False

    if not experiment_definition:
        return question_id, valid_options, allow_other

    # 1. Check multi-question scenario / experiment format (`questions`)
    questions = getattr(experiment_definition, "questions", None)
    if questions is None and isinstance(experiment_definition, Mapping):
        questions = experiment_definition.get("questions")
    if questions and isinstance(questions, Sequence):
        matched_qid: str | None = None
        matched_opts: set[str] | None = None
        for q in questions:
            qid = (
                getattr(q, "id", None)
                or getattr(q, "question_id", None)
                or (q.get("id") or q.get("question_id") if isinstance(q, Mapping) else None)
            )
            opts = getattr(q, "options", None) or (q.get("options") if isinstance(q, Mapping) else None)
            opt_ids: set[str] = set()
            for o in opts or ():
                oid = (
                    getattr(o, "id", None)
                    or getattr(o, "option_id", None)
                    or (o.get("id") or o.get("option_id") if isinstance(o, Mapping) else str(o))
                )
                if oid is not None:
                    opt_ids.add(str(oid))
            if choice is not None and str(choice) in opt_ids and qid:
                matched_qid = str(qid)
                matched_opts = opt_ids
                break
        if matched_qid:
            return matched_qid, matched_opts, allow_other
        if len(questions) == 1:
            q0 = questions[0]
            q0_id = (
                getattr(q0, "id", None)
                or getattr(q0, "question_id", None)
                or (q0.get("id") or q0.get("question_id") if isinstance(q0, Mapping) else None)
            )
            if q0_id:
                question_id = str(q0_id)
            opts0 = getattr(q0, "options", None) or (q0.get("options") if isinstance(q0, Mapping) else None)
            if opts0:
                valid_options = {
                    str(
                        getattr(o, "id", None)
                        or getattr(o, "option_id", None)
                        or (o.get("id") or o.get("option_id") if isinstance(o, Mapping) else o)
                    )
                    for o in opts0
                }
            return question_id, valid_options, allow_other

    # 2. Check national ExperimentDefinition format (`task`: TaskSpec or dict)
    task = getattr(experiment_definition, "task", None)
    if task is None and isinstance(experiment_definition, Mapping):
        task = experiment_definition.get("task")
    if task is not None:
        tid = (
            getattr(task, "id", None)
            or getattr(task, "question_id", None)
            or (task.get("id") or task.get("question_id") if isinstance(task, Mapping) else None)
        )
        if tid:
            question_id = str(tid)
        elif default_question_id:
            question_id = default_question_id

        allow_other = bool(
            getattr(task, "allow_other", False)
            or (task.get("allow_other", False) if isinstance(task, Mapping) else False)
        )
        opts = getattr(task, "options", None)
        if opts is None and isinstance(task, Mapping):
            opts = task.get("options")
        if opts:
            valid_options = {
                str(
                    getattr(o, "id", None)
                    or getattr(o, "option_id", None)
                    or (o.get("id") or o.get("option_id") if isinstance(o, Mapping) else o)
                )
                for o in opts
            }

    return question_id, valid_options, allow_other


# -----------------------------------------------------------------------------
# Consumer-Side Adapters for DST / Sam's Simulation Results (K6)
# -----------------------------------------------------------------------------

class PersonaExecutionRecord(TypedModel):
    """Normalized consumer-side representation of an individual persona execution result."""

    resident_id: str = Field(min_length=1)
    status: ResultStatus = "valid"
    raw_status: str = "valid"
    answers: dict[str, str] = Field(default_factory=dict)
    rationale: str | None = None
    execution_time_seconds: float | None = None
    prompt_tokens: StrictInt | None = None
    completion_tokens: StrictInt | None = None
    model_name: str | None = None
    errors: tuple[str, ...] = ()
    raw_payload: dict[str, Any] | None = None

    # DST native execution fields
    is_final: bool = True
    attempt: int = 1
    request_key: str | None = None
    synthetic_id: str | None = None
    persona_id: str | None = None
    province_code: str | None = None
    sample_index: int = 0
    choice: str | None = None
    other_text: str | None = None
    raw_response: str | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    from_cache: bool = False
    provider_call: bool = False
    response_id: int | str | None = None
    system_sha256: str | None = None
    user_sha256: str | None = None
    prompt_source: str | None = None
    cache_key: str | None = None
    created_at: str | None = None

    @classmethod
    def from_any(
        cls,
        obj: Any,
        *,
        experiment_definition: Any = None,
        default_question_id: str = "task_choice",
    ) -> PersonaExecutionRecord:
        """Coerce heterogeneous runtime output formats into a normalized PersonaExecutionRecord."""
        if isinstance(obj, PersonaExecutionRecord):
            return obj

        if isinstance(obj, Mapping):
            d = dict(obj)
        else:
            # Convert dataclass / object attributes into a uniform dict
            d = {}
            for attr in (
                "resident_id",
                "synthetic_id",
                "persona_id",
                "id",
                "status",
                "answers",
                "choice",
                "other_text",
                "rationale",
                "raw_response",
                "errors",
                "error",
                "execution_time_seconds",
                "latency_ms",
                "input_tokens",
                "prompt_tokens",
                "output_tokens",
                "completion_tokens",
                "cost_usd",
                "model_name",
                "is_final",
                "attempt",
                "request_key",
                "province_code",
                "sample_index",
                "from_cache",
                "provider_call",
                "response_id",
                "system_sha256",
                "user_sha256",
                "prompt_source",
                "cache_key",
                "created_at",
            ):
                if hasattr(obj, attr):
                    d[attr] = getattr(obj, attr)

        res_id = str(
            d.get("resident_id")
            or d.get("synthetic_id")
            or d.get("persona_id")
            or d.get("id")
            or "UNKNOWN"
        )
        status, raw_status_str = _normalize_dst_status(d.get("status", "valid"))

        answers = d.get("answers")
        if isinstance(answers, Mapping):
            answers_dict = {
                str(k): str(v)
                for k, v in answers.items()
                if v is not None and str(v).strip() != ""
            }
        else:
            answers_dict = {}

        errors = d.get("errors") or []
        if isinstance(errors, (list, tuple)):
            err_list = [str(e) for e in errors if e is not None and str(e).strip() != ""]
        elif errors:
            err_list = [str(errors)]
        else:
            err_list = []
        err_single = d.get("error")
        if err_single and str(err_single).strip() and str(err_single) not in err_list:
            err_list.append(str(err_single))

        choice = d.get("choice")
        choice_str = str(choice).strip() if choice is not None and str(choice).strip() != "" else None
        question_id, valid_options, allow_other = _resolve_question_and_valid_options(
            experiment_definition,
            default_question_id,
            choice_str,
        )

        if choice_str is not None:
            if valid_options is not None and choice_str not in valid_options and not allow_other:
                status = "invalid"
                msg = f"Invalid choice {choice_str!r} for question {question_id!r}; allowed options: {sorted(valid_options)}"
                if msg not in err_list:
                    err_list.append(msg)
            if question_id not in answers_dict:
                answers_dict[question_id] = choice_str

        # Also validate any pre-populated answer against valid_options if experiment_definition was provided
        if valid_options is not None and question_id in answers_dict and not allow_other:
            ans_val = answers_dict[question_id]
            if ans_val not in valid_options:
                status = "invalid"
                msg = f"Invalid answer {ans_val!r} for question {question_id!r}; allowed options: {sorted(valid_options)}"
                if msg not in err_list:
                    err_list.append(msg)

        err_tuple = tuple(err_list)

        input_tokens_raw = d.get("input_tokens") if d.get("input_tokens") is not None else d.get("prompt_tokens")
        output_tokens_raw = d.get("output_tokens") if d.get("output_tokens") is not None else d.get("completion_tokens")
        input_tokens = int(input_tokens_raw) if input_tokens_raw is not None else None
        output_tokens = int(output_tokens_raw) if output_tokens_raw is not None else None

        latency_ms_raw = d.get("latency_ms")
        latency_ms = float(latency_ms_raw) if latency_ms_raw is not None else None
        exec_time_raw = d.get("execution_time_seconds")
        exec_time = float(exec_time_raw) if exec_time_raw is not None else None
        if exec_time is None and latency_ms is not None:
            exec_time = round(latency_ms / 1000.0, 4)

        cost_raw = d.get("cost_usd")
        cost_usd = float(cost_raw) if cost_raw is not None else None

        is_final_raw = d.get("is_final")
        is_final = True if is_final_raw is None else bool(is_final_raw)
        attempt = int(d.get("attempt", 1) or 1)
        sample_index = int(d.get("sample_index", 0) or 0)
        req_key = d.get("request_key")
        if req_key is None and (d.get("synthetic_id") or d.get("resident_id")):
            req_key = f"{res_id}:{sample_index}"

        return cls(
            resident_id=res_id,
            status=status,
            raw_status=raw_status_str,
            answers=answers_dict,
            rationale=d.get("rationale"),
            execution_time_seconds=exec_time,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            model_name=d.get("model_name"),
            errors=err_tuple,
            raw_payload=d if isinstance(obj, Mapping) else None,
            is_final=is_final,
            attempt=attempt,
            request_key=str(req_key) if req_key is not None else None,
            synthetic_id=str(d.get("synthetic_id") or res_id),
            persona_id=str(d["persona_id"]) if d.get("persona_id") is not None else None,
            province_code=str(d["province_code"]) if d.get("province_code") is not None else None,
            sample_index=sample_index,
            choice=choice_str,
            other_text=d.get("other_text"),
            raw_response=d.get("raw_response"),
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            from_cache=bool(d.get("from_cache", False)),
            provider_call=bool(d.get("provider_call", False)),
            response_id=d.get("response_id"),
            system_sha256=d.get("system_sha256"),
            user_sha256=d.get("user_sha256"),
            prompt_source=d.get("prompt_source"),
            cache_key=d.get("cache_key"),
            created_at=d.get("created_at"),
        )


class SimulationResultsAdapter(TypedModel):
    """Consumer-side adapter for DST and simulation run outputs."""

    scenario_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = 0.0
    records: tuple[PersonaExecutionRecord, ...]
    manifest: dict[str, Any] = Field(default_factory=dict)
    cohort_id: str | None = None
    sample_id: str | None = None
    population_id: str | None = None
    experiment_id: str | None = None
    plan_hash: str | None = None
    total_enveloped: int | None = None
    page_offset: int | None = None
    page_limit: int | None = None

    @classmethod
    def from_any(
        cls,
        obj: Any,
        *,
        experiment_definition: Any = None,
        default_question_id: str = "task_choice",
    ) -> SimulationResultsAdapter:
        """Adapt a SimulationResults object, paginated envelope, dict, or sequence into a typed adapter."""
        if isinstance(obj, SimulationResultsAdapter):
            return obj

        # Support a sequence of paginated API response envelopes ([page1_dict, page2_dict, ...])
        if (
            isinstance(obj, (list, tuple))
            and len(obj) > 0
            and all(isinstance(el, Mapping) and "items" in el and isinstance(el["items"], (list, tuple)) for el in obj)
        ):
            merged_items: list[Any] = []
            first_page = dict(obj[0])
            for page in obj:
                merged_items.extend(page["items"])
            combined_envelope = dict(first_page)
            combined_envelope["items"] = merged_items
            return cls.from_any(
                combined_envelope,
                experiment_definition=experiment_definition,
                default_question_id=default_question_id,
            )

        if isinstance(obj, Mapping):
            total_enveloped = obj.get("total")
            page_offset = obj.get("offset")
            page_limit = obj.get("limit")
            if "items" in obj and isinstance(obj["items"], (list, tuple)):
                raw_recs = obj["items"]
            elif "responses" in obj and isinstance(obj["responses"], (list, tuple)):
                raw_recs = obj["responses"]
            elif "records" in obj and isinstance(obj["records"], (list, tuple)):
                raw_recs = obj["records"]
            elif "results" in obj and isinstance(obj["results"], (list, tuple)):
                raw_recs = obj["results"]
            elif "synthetic_id" in obj or "resident_id" in obj or "choice" in obj:
                raw_recs = [obj]
            else:
                raw_recs = []

            manifest = dict(obj.get("manifest", {}) or {})
            exp_def = (
                experiment_definition
                or manifest.get("definition")
                or manifest.get("experiment")
                or obj.get("definition")
                or obj.get("experiment_definition")
            )

            exp_id = (
                obj.get("experiment_id")
                or manifest.get("experiment_id")
                or (exp_def.get("experiment_id") if isinstance(exp_def, Mapping) else getattr(exp_def, "experiment_id", None))
            )
            sc_id = str(
                obj.get("scenario_id")
                or exp_id
                or (exp_def.get("title") if isinstance(exp_def, Mapping) else getattr(exp_def, "title", None))
                or "transport_fare_001"
            )
            run_id = str(
                obj.get("run_id")
                or manifest.get("run_id")
                or f"run-{canonical_hash(dict(obj))[:12]}"
            )
            model = str(
                obj.get("model")
                or (obj.get("summary") or {}).get("backend")
                or (manifest.get("summary") or {}).get("backend")
                or (
                    exp_def.get("model", {}).get("backend")
                    if isinstance(exp_def, Mapping) and isinstance(exp_def.get("model"), Mapping)
                    else None
                )
                or "unknown-model"
            )
            temp = float(
                obj.get("temperature")
                or (
                    exp_def.get("model", {}).get("temperature")
                    if isinstance(exp_def, Mapping) and isinstance(exp_def.get("model"), Mapping)
                    else 0.0
                )
                or 0.0
            )

            adapted_recs = tuple(
                PersonaExecutionRecord.from_any(
                    r,
                    experiment_definition=exp_def,
                    default_question_id=default_question_id,
                )
                for r in raw_recs
            )

            cohort_id = (
                obj.get("cohort_id")
                or manifest.get("cohort_id")
                or (exp_def.get("cohort_id") if isinstance(exp_def, Mapping) else getattr(exp_def, "cohort_id", None))
            )
            sample_id = obj.get("sample_id") or manifest.get("sample_id")
            population_id = obj.get("population_id") or manifest.get("population_id")
            plan_hash = obj.get("plan_hash") or manifest.get("plan_hash")

            return cls(
                scenario_id=sc_id,
                run_id=run_id,
                model=model,
                temperature=temp,
                records=adapted_recs,
                manifest=manifest,
                cohort_id=str(cohort_id) if cohort_id is not None else None,
                sample_id=str(sample_id) if sample_id is not None else None,
                population_id=str(population_id) if population_id is not None else None,
                experiment_id=str(exp_id) if exp_id is not None else None,
                plan_hash=str(plan_hash) if plan_hash is not None else None,
                total_enveloped=int(total_enveloped) if total_enveloped is not None else None,
                page_offset=int(page_offset) if page_offset is not None else None,
                page_limit=int(page_limit) if page_limit is not None else None,
            )

        if isinstance(obj, (list, tuple)):
            adapted_recs = tuple(
                PersonaExecutionRecord.from_any(
                    r,
                    experiment_definition=experiment_definition,
                    default_question_id=default_question_id,
                )
                for r in obj
            )
            return cls(
                scenario_id="simulation_evaluation",
                run_id="run-direct-list",
                model="direct-model",
                temperature=0.0,
                records=adapted_recs,
                manifest={},
            )

        # Attribute-based object
        sc_id = str(getattr(obj, "scenario_id", None) or getattr(obj, "experiment_id", None) or "transport_fare_001")
        run_id = str(getattr(obj, "run_id", "run-adapter-generic"))
        model = str(getattr(obj, "model", "generic-agent-model"))
        temp = float(getattr(obj, "temperature", 0.0))
        raw_recs = getattr(obj, "records", getattr(obj, "results", getattr(obj, "responses", ())))
        adapted_recs = tuple(
            PersonaExecutionRecord.from_any(
                r,
                experiment_definition=experiment_definition,
                default_question_id=default_question_id,
            )
            for r in raw_recs
        )
        manifest = dict(getattr(obj, "manifest", {}) or {})
        return cls(
            scenario_id=sc_id,
            run_id=run_id,
            model=model,
            temperature=temp,
            records=adapted_recs,
            manifest=manifest,
            cohort_id=getattr(obj, "cohort_id", None),
            sample_id=getattr(obj, "sample_id", None),
            population_id=getattr(obj, "population_id", None),
            experiment_id=getattr(obj, "experiment_id", None),
            plan_hash=getattr(obj, "plan_hash", None),
        )


class QuestionChoiceMetric(TypedModel):
    """Distribution metrics for a single option of a scenario question."""

    choice_id: str = Field(min_length=1)
    unweighted_count: StrictInt = Field(ge=0)
    unweighted_share: float = Field(ge=0.0, le=1.0)
    weighted_count: float = Field(ge=0.0)
    weighted_share: float = Field(ge=0.0, le=1.0)
    std_error_unweighted: float = Field(ge=0.0)


class QuestionDistributionSummary(TypedModel):
    """Aggregate distribution summary for a single scenario question."""

    question_id: str = Field(min_length=1)
    valid_responses_n: StrictInt = Field(ge=0)
    valid_weighted_total: float = Field(ge=0.0)
    choices: tuple[QuestionChoiceMetric, ...]
    weight_source: str = "population_weight"


class SubgroupComparisonMetric(TypedModel):
    """Comparison of response distribution within a demographic subgroup."""

    subgroup_dimension: str = Field(min_length=1)
    subgroup_value: str = Field(min_length=1)
    sample_n: StrictInt = Field(ge=0)
    weighted_total: float = Field(ge=0.0)
    is_low_confidence: StrictBool
    confidence_note: str = Field(min_length=1)
    choice_shares_unweighted: dict[str, float]
    choice_shares_weighted: dict[str, float]


class FailureAuditSummary(TypedModel):
    """Comprehensive accounting of expected, received, valid, failed, missing, duplicate, and foreign responses."""

    total_attempted: StrictInt = Field(ge=0)
    successful_valid: StrictInt = Field(ge=0)
    total_failures: StrictInt = Field(ge=0)
    completion_rate_pct: float = Field(ge=0.0, le=100.0)
    failure_breakdown_by_status: dict[str, StrictInt]
    distinct_error_messages: tuple[str, ...]
    unanswered_residents: tuple[str, ...]

    expected_executions: StrictInt = 0
    received_executions: StrictInt = 0
    received_final_executions: StrictInt = 0
    diagnostic_retry_executions: StrictInt = 0
    completed_valid_executions: StrictInt = 0
    failed_executions: StrictInt = 0
    missing_executions: StrictInt = 0
    duplicate_executions: StrictInt = 0
    conflicting_executions: StrictInt = 0
    foreign_executions: StrictInt = 0
    missing_residents: tuple[str, ...] = ()
    foreign_residents: tuple[str, ...] = ()
    duplicate_residents: tuple[str, ...] = ()
    conflicting_residents: tuple[str, ...] = ()
    expected_request_keys: tuple[str, ...] = ()
    missing_request_keys: tuple[str, ...] = ()


class BenchmarkComparisonResult(TypedModel):
    """Comparison of simulated results against an individual benchmark."""

    benchmark_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    evidence_type: EvidenceType
    benchmark_status: BenchmarkStatus
    evidence_status: EvidenceStatus
    evidence_status_statement: str = Field(min_length=1)
    benchmark_value: float | None = None
    benchmark_range: tuple[float, float] | None = None
    simulated_value: float | None = None
    difference_pp: float | None = None
    is_within_envelope: StrictBool | None = None
    unavailability_reason: str | None = None
    notes: tuple[str, ...] = ()


class InterventionBaselineDelta(TypedModel):
    """Explicit delta between a baseline and an intervention simulation run."""

    metric_name: str = Field(min_length=1)
    baseline_run_id: str = Field(min_length=1)
    intervention_run_id: str = Field(min_length=1)
    baseline_share: float
    intervention_share: float
    percentage_point_delta: float
    relative_change_pct: float
    baseline_share_unweighted: float | None = None
    intervention_share_unweighted: float | None = None
    percentage_point_delta_unweighted: float | None = None
    difference_weighting: str = "weighted"
    evidence_disclaimer: str = Field(
        min_length=1,
        default=(
            "SYNTHETIC BASELINE DISCLAIMER: This baseline-vs-intervention comparison is derived "
            "entirely from synthetic simulation runs for software and pipeline verification. "
            "It CANNOT establish empirical predictive accuracy against real-world human behavior."
        ),
    )


class SimulationEvaluationReport(TypedModel):
    """Comprehensive K6 Simulation Results Evaluation Report."""

    report_schema_version: Literal["simulation-evaluation-report-k6-v1"] = SIMULATION_REPORT_SCHEMA_VERSION
    evaluator_version: Literal["k7-quality-reports-1.0"] = REPORTS_EVALUATOR_VERSION
    scenario_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    cohort_id: str | None = None
    sample_id: str | None = None
    population_id: str | None = None
    experiment_id: str | None = None
    plan_hash: str | None = None
    evaluated_at: str | None = None
    population_size_evaluated: StrictInt = Field(ge=0)
    total_represented_weight: float = Field(ge=0.0)

    # Core required sections
    failure_audit: FailureAuditSummary
    overall_question_distributions: tuple[QuestionDistributionSummary, ...]
    subgroup_comparisons: tuple[SubgroupComparisonMetric, ...]
    benchmark_comparisons: tuple[BenchmarkComparisonResult, ...]
    baseline_deltas: tuple[InterventionBaselineDelta, ...] = ()

    # Explicit evidence and gap statements
    evidence_status_summary: str = Field(min_length=1)
    validation_gap_statement: str = Field(min_length=1)

    # Provenance and weighting fields
    simulation_run_id: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    weight_source: str = "population_weight"
    sampling_method: str | None = None
    input_kind: Literal["sampled_cohort", "full_population"] = "full_population"
    difference_weighting: str = "weighted"

    @property
    def deterministic_content(self) -> dict[str, Any]:
        """Dictionary representation omitting volatile timestamps for byte-identical determinism."""
        d = self.model_dump(mode="json")
        d.pop("evaluated_at", None)
        return d

    @property
    def report_fingerprint(self) -> str:
        return canonical_hash(self.deterministic_content)

    def to_markdown(self) -> str:
        """Render a publication-ready Markdown evaluation report."""
        lines = [
            f"# K6 Simulation Results Evaluation Report — `{self.run_id}`",
            "",
            f"- **Scenario ID:** `{self.scenario_id}`",
            f"- **Run ID:** `{self.run_id}`",
            f"- **Cohort / Sample ID:** `{self.cohort_id or 'N/A'}` / `{self.sample_id or 'N/A'}`",
            f"- **Population ID:** `{self.population_id or 'N/A'}`",
            f"- **Weight Source / Sampling Method:** `{self.weight_source}` / `{self.sampling_method or 'full_population'}`",
            f"- **Evaluated Personas:** `{self.population_size_evaluated:,}` (Weighted Total: `{self.total_represented_weight:,.1f}`)",
            f"- **Valid Responses:** `{self.failure_audit.successful_valid:,}` / `{self.failure_audit.total_attempted:,}` "
            f"({self.failure_audit.completion_rate_pct:.1f}% Completion Rate)",
            f"- **Total Failures / Refusals / Missing:** `{self.failure_audit.total_failures:,}`",
            "",
            "> [!IMPORTANT]",
            f"> **Evidence Status:** {self.evidence_status_summary}",
            "",
            "> [!NOTE]",
            f"> **Validation Gap:** {self.validation_gap_statement}",
            "",
            "---",
            "",
            "## 1. Response Distributions (Overall & Weighted)",
            "",
        ]

        for q in self.overall_question_distributions:
            lines.extend([
                f"### Question `{q.question_id}` ($n = {q.valid_responses_n:,}$, Weighted = {q.valid_weighted_total:,.1f}, Weight Source = `{q.weight_source}`)",
                "",
                "| Option ID | Unweighted Count | Unweighted Share (%) | Weighted Share (%) | Standard Error (SE pp) |",
                "|---|---:|---:|---:|---:|",
            ])
            for c in q.choices:
                lines.append(
                    f"| `{c.choice_id}` | {c.unweighted_count:,} | {c.unweighted_share * 100:.1f}% | "
                    f"**{c.weighted_share * 100:.1f}%** | ±{c.std_error_unweighted * 100:.2f} pp |"
                )
            lines.append("")

        lines.extend([
            "---",
            "",
            "## 2. Demographic Subgroup Comparisons & Confidence Flags",
            "",
            "Small subgroups ($n < 15$) are explicitly flagged as `LOW CONFIDENCE` rather than emitting misleading intervals.",
            "",
            "| Subgroup Dimension | Segment | Sample $n$ | Weighted Total | Confidence Flag | Top Choice (Weighted %) | Second Choice (Weighted %) |",
            "|---|---|---:|---:|:---:|---|---|",
        ])

        for sub in self.subgroup_comparisons:
            conf_str = "LOW CONFIDENCE" if sub.is_low_confidence else "ADEQUATE"
            sorted_wt = sorted(sub.choice_shares_weighted.items(), key=lambda kv: kv[1], reverse=True)
            top1 = f"`{sorted_wt[0][0]}` ({sorted_wt[0][1] * 100:.1f}%)" if len(sorted_wt) > 0 else "N/A"
            top2 = f"`{sorted_wt[1][0]}` ({sorted_wt[1][1] * 100:.1f}%)" if len(sorted_wt) > 1 else "—"
            lines.append(
                f"| `{sub.subgroup_dimension}` | `{sub.subgroup_value}` | {sub.sample_n:,} | "
                f"{sub.weighted_total:,.1f} | **`{conf_str}`** | {top1} | {top2} |"
            )

        lines.extend([
            "",
            "---",
            "",
            "## 3. Behavioral Benchmark Comparisons & Ground Truth Reality",
            "",
            "| Benchmark ID | Evidence Type | Status | Benchmark Value | Simulated Value | Difference (pp) | Within Envelope? |",
            "|---|---|:---:|---:|---:|---:|:---:|",
        ])

        for b in self.benchmark_comparisons:
            val_str = "Unavailable"
            if b.benchmark_value is not None:
                val_str = f"{b.benchmark_value:g}"
            elif b.benchmark_range is not None:
                val_str = f"[{b.benchmark_range[0]:g}, {b.benchmark_range[1]:g}]"

            sim_str = f"{b.simulated_value:g}" if b.simulated_value is not None else "—"
            diff_str = f"{b.difference_pp:+.1f} pp" if b.difference_pp is not None else "—"
            env_str = "YES" if b.is_within_envelope is True else ("NO" if b.is_within_envelope is False else "N/A")

            lines.append(
                f"| `{b.benchmark_id}` | `{b.evidence_type}` | **`{b.benchmark_status.upper()}`** | "
                f"{val_str} | {sim_str} | {diff_str} | {env_str} |"
            )

        if self.baseline_deltas:
            lines.extend([
                "",
                "---",
                "",
                "## 4. Baseline-vs-Intervention Synthetic Comparison",
                "",
                "> [!WARNING]",
                "> **Disclaimer:** All deltas below compare two synthetic simulation runs (e.g. status-quo baseline vs. 20% fare increase). "
                f"They evaluate pipeline responsiveness and persona logic (`difference_weighting={self.difference_weighting}`), NOT predictive accuracy.",
                "",
                "| Metric / Option | Baseline Share (%) | Intervention Share (%) | Delta (pp) | Relative Change (%) |",
                "|---|---:|---:|---:|---:|",
            ])
            for d in self.baseline_deltas:
                lines.append(
                    f"| `{d.metric_name}` | {d.baseline_share * 100:.1f}% | {d.intervention_share * 100:.1f}% | "
                    f"**{d.percentage_point_delta:+.1f} pp** | {d.relative_change_pct:+.1f}% |"
                )

        lines.extend([
            "",
            "---",
            "",
            "## 5. Failure & Non-Response Audit Summary",
            "",
            f"- **Expected Executions:** `{self.failure_audit.expected_executions:,}`",
            f"- **Received Executions (Total / Final / Retries):** `{self.failure_audit.received_executions:,}` / "
            f"`{self.failure_audit.received_final_executions:,}` / `{self.failure_audit.diagnostic_retry_executions:,}`",
            f"- **Total Personas Dispatched:** `{self.failure_audit.total_attempted:,}`",
            f"- **Successful Valid Responses:** `{self.failure_audit.successful_valid:,}`",
            f"- **Failed Executions:** `{self.failure_audit.failed_executions:,}`",
            f"- **Missing Executions:** `{self.failure_audit.missing_executions:,}`",
            f"- **Duplicate / Conflicting Executions:** `{self.failure_audit.duplicate_executions:,}` / `{self.failure_audit.conflicting_executions:,}`",
            f"- **Foreign (Outside Cohort) Executions:** `{self.failure_audit.foreign_executions:,}`",
            f"- **Total Non-Valid / Refused / Missing:** `{self.failure_audit.total_failures:,}`",
            "- **Failure Breakdown by Status:**",
        ])
        for st, cnt in self.failure_audit.failure_breakdown_by_status.items():
            if cnt > 0:
                lines.append(f"  - `{st}`: {cnt:,}")

        if self.failure_audit.distinct_error_messages:
            lines.extend([
                "- **Sample Error Messages:**",
            ])
            for err in self.failure_audit.distinct_error_messages[:5]:
                lines.append(f"  - `{err}`")

        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Combined Quality Report (K7)
# -----------------------------------------------------------------------------

class UnifiedCheckRecord(TypedModel):
    """Normalized representation of an individual validation check across marginal, joint, and behavioral layers."""

    check_id: str = Field(min_length=1)
    layer: Literal["marginal_population", "joint_dependency", "behavioral_simulation"]
    name: str = Field(min_length=1)
    status: CheckStatus
    reason: str = Field(min_length=1)
    dataset_provenance: DatasetProvenance | None = None
    scope_marker: str | None = None
    is_calibrated: StrictBool = False


class ValidationGapRecord(TypedModel):
    """Explicitly documented validation gap, unverified joint, or data-quality discrepancy."""

    gap_id: str = Field(min_length=1)
    category: Literal["data_discrepancy", "unverified_relationship", "unavailable_benchmark"]
    summary: str = Field(min_length=1)
    policy_action: str = Field(min_length=1)
    details: tuple[str, ...] = ()


class CombinedQualityReport(TypedModel):
    """Complete, unified Phase 7 Quality Report combining Population, Dependency, and Simulation Validation.

    Guarantees byte-identical reproducibility:
    - Same inputs produce bit-for-bit identical JSON output.
    - Volatile timestamps are separated from deterministic content hashing.
    - Deterministic ordering across all check lists, metrics, and dictionaries.
    """

    report_schema_version: Literal["combined-quality-report-k7-v1"] = COMBINED_REPORT_SCHEMA_VERSION
    evaluator_version: Literal["k7-quality-reports-1.0"] = REPORTS_EVALUATOR_VERSION
    population_id: str = Field(min_length=1)
    population_version: str = Field(min_length=1)
    population_sha256: str | None = None
    reference_package_version: str = Field(min_length=1)
    reference_package_fingerprint: str = Field(min_length=1)
    simulation_run_id: str | None = None
    cohort_id: str | None = None
    sample_id: str | None = None
    experiment_id: str | None = None
    scenario_id: str | None = None
    plan_hash: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    geography_code: str = Field(min_length=1)
    reference_year: StrictInt
    sample_size: StrictInt = Field(ge=0)
    weighted_population_total: float
    seed: StrictInt | None = None

    # Overall statuses
    overall_status: CheckStatus
    status_counts: dict[CheckStatus, StrictInt]

    # Core integrated sections
    checks: tuple[UnifiedCheckRecord, ...]
    population_report: PopulationValidationReport
    dependency_report: DependencyValidationReport
    simulation_report: SimulationEvaluationReport | None = None

    # Transparency sections
    validation_gaps: tuple[ValidationGapRecord, ...]
    limitations: tuple[str, ...]
    synthetic_label: str = Field(
        min_length=1,
        default="Synthetic population and simulation results calibrated to official aggregate statistics. Fictional residents; no real person is represented.",
    )

    @property
    def deterministic_dict(self) -> dict[str, Any]:
        """Produce a deterministic dictionary representation with sorted keys and no volatile timestamps."""
        d = self.model_dump(mode="json")
        if d.get("simulation_report"):
            d["simulation_report"].pop("evaluated_at", None)
        return d

    @property
    def report_fingerprint(self) -> str:
        """Content SHA-256 hash computed deterministically across all verification results."""
        return canonical_hash(self.deterministic_dict)

    def to_ui_dict(self) -> dict[str, Any]:
        """Convert into the exact dictionary convention consumed by existing API endpoints.

        Matches `src/societytwin/api/schemas.py:ValidationReport` and `/populations/{id}/validation`,
        while strictly separating `population_sha256` from `reference_package_fingerprint`.
        """
        metrics: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        unavailable_evidence: list[dict[str, Any]] = []

        # Strictly use the population artifact hash (never reference_package_fingerprint!)
        pop_sha = self.population_sha256 or self.population_id

        # 1. Transform population checks into ValidationMetric and Check
        for chk in self.population_report.checks:
            passed = chk.status == "pass"
            checks.append({
                "check_id": chk.check_id,
                "name": f"margin_{chk.margin}",
                "status": chk.status,
                "passed": passed,
                "detail": chk.reason,
                "evidence_kind": "source_fit" if chk.is_calibrated_margin else "integrity",
            })
            if chk.metrics:
                cats = [
                    {
                        "category": c.cell_key,
                        "count": c.observed_record_count,
                        "synthetic_share": c.observed_weighted_share,
                        "reference_share": c.reference_share,
                        "difference_pp": c.pp_deviation_weighted,
                    }
                    for c in chk.cells[:20]
                ]
                metrics.append({
                    "name": f"margin_{chk.margin}",
                    "value": chk.metrics.total_variation_distance_weighted,
                    "unit": "TVD",
                    "dimension": chk.margin,
                    "categories": cats,
                    "denominator": chk.metrics.evaluated_records,
                    "population_sha256": pop_sha,
                    "reference_sha256": chk.dataset_provenance.source_sha256,
                    "reference_year": int(chk.dataset_provenance.year) if str(chk.dataset_provenance.year).isdigit() else 2025,
                    "evidence_kind": "source_fit",
                    "availability": "OBSERVED",
                    "method": chk.evaluation_regime,
                    "acceptance_threshold": None,
                    "limitations": list(chk.notes),
                })

        # 2. Add dependency checks
        for chk in self.dependency_report.supported_joint_checks:
            checks.append({
                "check_id": chk.check_id,
                "name": chk.check_id,
                "status": chk.status,
                "passed": chk.status == "pass",
                "detail": chk.reason,
                "evidence_kind": "held_out" if chk.scope == "national_proxy" else "source_fit",
            })

        for chk in self.dependency_report.unverified_relationships:
            checks.append({
                "check_id": chk.check_id,
                "name": chk.check_id,
                "status": chk.status,
                "passed": chk.status != "fail",
                "detail": chk.reason,
                "evidence_kind": "integrity",
            })
            if chk.status == "not_evaluable":
                unavailable_evidence.append({
                    "name": chk.check_id,
                    "evidence_kind": "held_out",
                    "reason": chk.reason,
                })

        # 3. Add behavioral benchmarks
        if self.simulation_report:
            for b in self.simulation_report.benchmark_comparisons:
                if b.benchmark_status == "unavailable":
                    unavailable_evidence.append({
                        "name": b.benchmark_id,
                        "evidence_kind": "behavioral",
                        "reason": b.unavailability_reason or b.evidence_status_statement,
                    })

        # 4. Add documented discrepancies to unavailable evidence
        for gap in self.validation_gaps:
            if gap.category == "data_discrepancy":
                unavailable_evidence.append({
                    "name": gap.gap_id,
                    "evidence_kind": "integrity",
                    "reason": f"{gap.summary} Policy: {gap.policy_action}",
                })

        return {
            "build_id": self.population_id,
            "population_id": self.population_id,
            "population_version": self.population_version,
            "method_version": self.evaluator_version,
            "report_schema_version": self.report_schema_version,
            "population_sha256": pop_sha,
            "reference_package_fingerprint": self.reference_package_fingerprint,
            "reference_package_version": self.reference_package_version,
            "simulation_run_id": self.simulation_run_id,
            "cohort_id": self.cohort_id,
            "sample_id": self.sample_id,
            "experiment_id": self.experiment_id,
            "scenario_id": self.scenario_id,
            "plan_hash": self.plan_hash,
            "overall_status": self.overall_status,
            "status_counts": self.status_counts,
            "metrics": metrics,
            "checks": checks,
            "unavailable_evidence": unavailable_evidence,
            "acceptance_status": None,
            "acceptance_note": (
                "PASS: All calibrated margins and evaluated joints consistent."
                if self.overall_status == "pass" else
                f"FAIL: {self.status_counts['fail']} checks failed."
            ),
            "reference_tables": [
                {
                    "path": f"data/reference_package_k2_v1/tables/{c.dataset_provenance.dataset_id}.csv",
                    "sha256": c.dataset_provenance.source_sha256,
                    "reference_year": int(c.dataset_provenance.year) if str(c.dataset_provenance.year).isdigit() else 2025,
                    "rows": c.metrics.cell_count if c.metrics else 0,
                }
                for c in self.population_report.checks if c.dataset_provenance
            ],
            "synthetic_label": self.synthetic_label,
            "attribution_note": "TÜİK public data tables 2025; SocietyTwin validation engine.",
        }

    def to_markdown(self) -> str:
        """Render an exhaustive, structured Markdown quality report."""
        lines = [
            f"# Combined Quality & Validation Report — `{self.population_id}`",
            "",
            f"- **Report Schema Version:** `{self.report_schema_version}`",
            f"- **Evaluator Version:** `{self.evaluator_version}`",
            f"- **Population ID / Version:** `{self.population_id}` / `{self.population_version}`",
            f"- **Population Hash (SHA-256):** `{self.population_sha256 or 'N/A'}`",
            f"- **Reference Package:** `{self.reference_package_version}` (`{self.reference_package_fingerprint[:16]}...`)",
            f"- **Simulation Run ID:** `{self.simulation_run_id or 'None'}`",
            f"- **Cohort / Sample ID:** `{self.cohort_id or 'None'}` / `{self.sample_id or 'None'}`",
            f"- **Experiment / Scenario ID:** `{self.experiment_id or 'None'}` / `{self.scenario_id or 'None'}`",
            f"- **Plan Hash:** `{self.plan_hash or 'None'}`",
            f"- **Geography / Year:** `{self.geography_code}` / `{self.reference_year}`",
            f"- **Sample Size ($n$):** `{self.sample_size:,}` records (Weighted Total: `{self.weighted_population_total:,.1f}`)",
            f"- **Seed:** `{self.seed}`",
            f"- **Overall Status:** **`{self.overall_status.upper()}`** "
            f"(`pass={self.status_counts['pass']}`, `fail={self.status_counts['fail']}`, `not_evaluable={self.status_counts['not_evaluable']}`)",
            f"- **Deterministic Report Fingerprint:** `{self.report_fingerprint}`",
            "",
            "> [!IMPORTANT]",
            f"> **Synthetic Label:** {self.synthetic_label}",
            "",
            "---",
            "",
            "## 1. Executive Summary of All Quality Checks",
            "",
            "Every check across marginal distributions, multidimensional dependencies, and simulation results.",
            "",
            "| Layer | Check ID | Name | Status | Calibrated? | Dataset ID | Scope Marker | Reason / Evaluation Summary |",
            "|---|---|---|:---:|:---:|---|---|---|",
        ]

        for chk in self.checks:
            ds_id = chk.dataset_provenance.dataset_id if chk.dataset_provenance else "—"
            scope = chk.scope_marker or "—"
            cal_str = "YES" if chk.is_calibrated else "NO"
            lines.append(
                f"| `{chk.layer}` | `{chk.check_id}` | {chk.name} | **`{chk.status.upper()}`** | "
                f"{cal_str} | `{ds_id}` | `{scope}` | {chk.reason} |"
            )

        lines.extend([
            "",
            "---",
            "",
            "## 2. Validation Gaps & Unresolved Empirical Discrepancies",
            "",
            "Documented data quality issues, unverified relationships where no benchmark was invented, and unavailable behavioral data.",
            "",
        ])

        for gap in self.validation_gaps:
            lines.extend([
                f"### `{gap.gap_id}` ({gap.category})",
                f"- **Summary:** {gap.summary}",
                f"- **Policy Action:** `{gap.policy_action}`",
            ])
            if gap.details:
                lines.append("- **Details & Root Causes:**")
                for d in gap.details:
                    lines.append(f"  - {d}")
            lines.append("")

        lines.extend([
            "---",
            "",
            "## 3. Structural Limitations & Methodological Constraints",
            "",
        ])
        for lim in self.limitations:
            lines.append(f"- {lim}")

        if self.simulation_report:
            lines.extend([
                "",
                "---",
                "",
                "## 4. Simulation Results Evaluation Summary",
                "",
                f"- **Evaluated Personas:** `{self.simulation_report.population_size_evaluated:,}`",
                f"- **Valid Completion Rate:** `{self.simulation_report.failure_audit.completion_rate_pct:.1f}%` "
                f"({self.simulation_report.failure_audit.successful_valid:,} valid, {self.simulation_report.failure_audit.total_failures:,} failed)",
                f"- **Evidence Disclaimer:** {self.simulation_report.evidence_status_summary}",
                "",
                "### Primary Question Response Distribution",
                "",
                "| Option ID | Unweighted Share (%) | Weighted Share (%) | Standard Error (SE) |",
                "|---|---:|---:|---:|",
            ])
            if self.simulation_report.overall_question_distributions:
                q0 = self.simulation_report.overall_question_distributions[0]
                for c in q0.choices:
                    lines.append(f"| `{c.choice_id}` | {c.unweighted_share * 100:.1f}% | **{c.weighted_share * 100:.1f}%** | ±{c.std_error_unweighted * 100:.2f} pp |")

        return "\n".join(lines)


def _extract_cohort_or_population_metadata(
    cohort_metadata: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Extract resident id -> demographic/weight dict and cohort/population provenance metadata.

    Handles:
    - Columnar populations (`GeneratedPopulation` / `LoadedPopulation` with `.columns`)
    - Resident-list populations (`GeneratedPopulation` from `population.schemas` with `.residents`)
    - Saved cohort sample dicts (`{"members": [...], "method": ..., "cohort_id": ..., "sample_id": ...}`)
    - `CohortManifest` objects (`realized.record_ids` / `members`)
    - Sequences of member dicts or `cohorts.Member` dataclass instances
    - ID-keyed mappings (`{"RES_1": {...}, "RES_2": {...}}`)
    """
    demographics_by_id: dict[str, dict[str, Any]] = {}
    meta: dict[str, Any] = {
        "cohort_id": None,
        "sample_id": None,
        "population_id": None,
        "sampling_method": None,
        "weight_source_hint": None,
        "input_kind": None,
    }

    if cohort_metadata is None:
        return demographics_by_id, meta

    # 1. Columnar population object (.columns)
    if hasattr(cohort_metadata, "columns") and not callable(cohort_metadata.columns):
        cols = cohort_metadata.columns
        id_col = cols.get("synthetic_id") if "synthetic_id" in cols else cols.get("resident_id", [])
        n = len(id_col)
        keys = list(cols.keys())
        for i in range(n):
            row = {k: cols[k][i] for k in keys}
            res_id = str(row.get("synthetic_id") or row.get("resident_id"))
            demographics_by_id[res_id] = row
        p_man = getattr(cohort_metadata, "manifest", None)
        if isinstance(p_man, Mapping):
            meta["population_id"] = p_man.get("population_id")
            meta["sampling_method"] = p_man.get("sampling_method") or "full_population"
        else:
            meta["sampling_method"] = "full_population"
        meta["input_kind"] = "full_population"
        return demographics_by_id, meta

    # 2. ResidentRecord-based population (.residents)
    if hasattr(cohort_metadata, "residents") and isinstance(getattr(cohort_metadata, "residents"), Sequence):
        for r in getattr(cohort_metadata, "residents"):
            if hasattr(r, "model_dump"):
                row = r.model_dump()
            elif isinstance(r, Mapping):
                row = dict(r)
            else:
                row = {
                    k: getattr(r, k)
                    for k in dir(r)
                    if not k.startswith("_") and not callable(getattr(r, k))
                }
            if "age" not in row and "age_years" in row:
                row["age"] = row["age_years"]
            res_id = str(row.get("resident_id") or row.get("synthetic_id"))
            demographics_by_id[res_id] = row
        gen_meta = getattr(cohort_metadata, "metadata", None)
        if gen_meta is not None:
            meta["population_id"] = getattr(gen_meta, "population_id", None)
        meta["sampling_method"] = "full_population"
        meta["input_kind"] = "full_population"
        return demographics_by_id, meta

    # 3. Sequence of dicts or Member objects
    if isinstance(cohort_metadata, (list, tuple)):
        for item in cohort_metadata:
            if hasattr(item, "as_dict") and callable(item.as_dict):
                row = dict(item.as_dict())
            elif isinstance(item, Mapping):
                row = dict(item)
            elif hasattr(item, "model_dump") and callable(item.model_dump):
                row = dict(item.model_dump())
            else:
                row = {
                    k: getattr(item, k)
                    for k in ("synthetic_id", "resident_id", "analysis_weight", "population_weight", "inclusion_probability", "age", "sex", "marital_status", "education_level")
                    if hasattr(item, k)
                }
            res_id = str(row.get("synthetic_id") or row.get("resident_id") or row.get("id"))
            demographics_by_id[res_id] = row
        return demographics_by_id, meta

    # 4. Mapping: could be saved cohort sample dict (`{"members": [...], ...}`),
    #    columnar dict (`{"columns": {...}}`), or ID-keyed dict (`{"RES_1": {...}}`)
    if isinstance(cohort_metadata, Mapping):
        if "members" in cohort_metadata and isinstance(cohort_metadata["members"], (list, tuple)):
            meta["cohort_id"] = cohort_metadata.get("cohort_id")
            meta["sample_id"] = cohort_metadata.get("sample_id")
            meta["population_id"] = cohort_metadata.get("population_id")
            cfg = cohort_metadata.get("config") if isinstance(cohort_metadata.get("config"), Mapping) else {}
            req = cohort_metadata.get("request") if isinstance(cohort_metadata.get("request"), Mapping) else {}
            meta["sampling_method"] = (
                cohort_metadata.get("sampling_method")
                or cohort_metadata.get("method")
                or cfg.get("sampling_method")
                or cfg.get("method")
                or req.get("method")
                or "sampled_cohort"
            )
            meta["weight_source_hint"] = (
                cohort_metadata.get("weight_source")
                or cfg.get("weight_source")
                or "analysis_weight"
            )
            meta["input_kind"] = "sampled_cohort"
            for item in cohort_metadata["members"]:
                if hasattr(item, "as_dict") and callable(item.as_dict):
                    row = dict(item.as_dict())
                elif isinstance(item, Mapping):
                    row = dict(item)
                else:
                    row = {}
                res_id = str(row.get("synthetic_id") or row.get("resident_id") or row.get("id"))
                demographics_by_id[res_id] = row
            return demographics_by_id, meta

        if "columns" in cohort_metadata and isinstance(cohort_metadata["columns"], Mapping):
            cols = cohort_metadata["columns"]
            id_col = cols.get("synthetic_id") if "synthetic_id" in cols else cols.get("resident_id", [])
            n = len(id_col)
            keys = list(cols.keys())
            for i in range(n):
                row = {k: cols[k][i] for k in keys}
                res_id = str(row.get("synthetic_id") or row.get("resident_id"))
                demographics_by_id[res_id] = row
            p_man = cohort_metadata.get("manifest")
            if isinstance(p_man, Mapping):
                meta["population_id"] = p_man.get("population_id")
            meta["sampling_method"] = "full_population"
            meta["input_kind"] = "full_population"
            return demographics_by_id, meta

        # Otherwise ID-keyed dict: {"RES_1": {...}, "RES_2": {...}}
        for k, v in cohort_metadata.items():
            if isinstance(v, Mapping):
                row = dict(v)
                row.setdefault("resident_id", str(k))
                demographics_by_id[str(k)] = row
        return demographics_by_id, meta

    # 5. Object with .members (e.g. SampledCohort object)
    if hasattr(cohort_metadata, "members") and isinstance(getattr(cohort_metadata, "members"), Sequence):
        meta["cohort_id"] = getattr(cohort_metadata, "cohort_id", None)
        meta["sample_id"] = getattr(cohort_metadata, "sample_id", None)
        meta["population_id"] = getattr(cohort_metadata, "population_id", None)
        meta["sampling_method"] = getattr(cohort_metadata, "method", None) or getattr(cohort_metadata, "sampling_method", "sampled_cohort")
        meta["input_kind"] = "sampled_cohort"
        for item in getattr(cohort_metadata, "members"):
            if hasattr(item, "as_dict") and callable(item.as_dict):
                row = dict(item.as_dict())
            elif isinstance(item, Mapping):
                row = dict(item)
            else:
                row = {
                    k: getattr(item, k)
                    for k in ("synthetic_id", "resident_id", "analysis_weight", "population_weight", "inclusion_probability")
                    if hasattr(item, k)
                }
            res_id = str(row.get("synthetic_id") or row.get("resident_id") or row.get("id"))
            demographics_by_id[res_id] = row

    return demographics_by_id, meta


# -----------------------------------------------------------------------------
# Evaluator Functions (K6 evaluate_simulation & K7 generate_combined_quality_report)
# -----------------------------------------------------------------------------

def evaluate_simulation(
    simulation_results: Any,
    cohort_metadata: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | Any,
    benchmark_bundle: BenchmarkBundle | None = None,
    *,
    baseline_simulation_results: Any = None,
    target_question_id: str = "q1_usage_change",
    min_subgroup_n: int = MIN_SUBGROUP_N_DEFAULT,
    experiment_definition: Any = None,
    repetitions: int = 1,
    require_weights: bool = True,
) -> SimulationEvaluationReport:
    """Evaluate simulation results against demographic personas and behavioral benchmarks."""
    if benchmark_bundle is None:
        benchmark_bundle = get_ankara_transit_fare_bundle()

    run_adapter = SimulationResultsAdapter.from_any(
        simulation_results,
        experiment_definition=experiment_definition,
        default_question_id=target_question_id,
    )
    all_received_records = run_adapter.records
    received_executions = len(all_received_records)

    demographics_by_id, extracted_meta = _extract_cohort_or_population_metadata(cohort_metadata)

    # Detect weight contract:
    # - Sampled cohorts provide `analysis_weight` (Horvitz-Thompson weight = population_weight / inclusion_probability).
    #   We NEVER recompute `analysis_weight` when the cohort contract provides it.
    # - Full generated populations provide `population_weight`.
    has_analysis_weight = any("analysis_weight" in row for row in demographics_by_id.values())
    has_population_weight = any("population_weight" in row for row in demographics_by_id.values())

    input_kind: Literal["sampled_cohort", "full_population"]
    if has_analysis_weight:
        weight_source = "analysis_weight"
        input_kind = "sampled_cohort"
    elif has_population_weight:
        weight_source = "population_weight"
        input_kind = extracted_meta.get("input_kind") or "full_population"
    else:
        if require_weights and demographics_by_id:
            first_missing = next(iter(demographics_by_id.keys()), "unknown")
            raise ValueError(
                f"Missing required weights: cohort member '{first_missing}' does not have analysis_weight or population_weight."
            )
        weight_source = "unweighted"
        input_kind = extracted_meta.get("input_kind") or "sampled_cohort"

    # Validate weights across all members if weighting is used or required
    if weight_source in ("analysis_weight", "population_weight"):
        for res_id, demo in demographics_by_id.items():
            raw_w = demo.get(weight_source)
            if raw_w is None or isinstance(raw_w, bool):
                if require_weights:
                    raise ValueError(
                        f"Missing required weights: cohort member '{res_id}' does not have {weight_source}."
                    )
                raw_w = 1.0
            try:
                w_val = float(raw_w)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid weight value {raw_w!r} for resident '{res_id}': weights must be numeric, finite, and positive."
                ) from exc
            if not math.isfinite(w_val) or w_val <= 0.0:
                raise ValueError(
                    f"Invalid weight value {raw_w!r} for resident '{res_id}': weights must be numeric, finite, and positive."
                )

    expected_resident_ids = set(demographics_by_id.keys())
    reps = max(1, int(repetitions))
    expected_executions = len(expected_resident_ids) * reps
    expected_request_keys = tuple(
        f"{rid}:{rep_idx}"
        for rid in sorted(expected_resident_ids)
        for rep_idx in range(reps)
    )

    # Separate diagnostic retry attempts (is_final == False) from final records (is_final == True)
    diagnostic_retries = [r for r in all_received_records if not r.is_final]
    final_records = [r for r in all_received_records if r.is_final]

    distinct_errors: set[str] = set()
    for r in diagnostic_retries:
        for err in r.errors:
            distinct_errors.add(err)

    # 1. Foreign respondents (outside expected cohort membership)
    foreign_records = [r for r in final_records if r.resident_id not in expected_resident_ids]
    foreign_residents = tuple(sorted({r.resident_id for r in foreign_records}))
    foreign_executions = len(foreign_records)

    # 2. Expected cohort final records, duplicates, and conflicting duplicates
    cohort_final_records = [r for r in final_records if r.resident_id in expected_resident_ids]
    records_by_resident: dict[str, list[PersonaExecutionRecord]] = {}
    for r in cohort_final_records:
        records_by_resident.setdefault(r.resident_id, []).append(r)

    duplicate_residents_set: set[str] = set()
    conflicting_residents_set: set[str] = set()
    duplicate_executions = 0
    conflicting_executions = 0
    primary_records: list[PersonaExecutionRecord] = []

    for res_id, r_list in records_by_resident.items():
        if len(r_list) > reps:
            duplicate_residents_set.add(res_id)
            extra_count = len(r_list) - reps
            duplicate_executions += extra_count
            # Check whether duplicate final records conflict in their answers/status
            distinct_outcomes = {
                (rec.status, tuple(sorted(rec.answers.items())))
                for rec in r_list
            }
            if len(distinct_outcomes) > 1:
                conflicting_residents_set.add(res_id)
                conflicting_executions += extra_count
        primary_records.extend(r_list[:reps])

    duplicate_residents = tuple(sorted(duplicate_residents_set))
    conflicting_residents = tuple(sorted(conflicting_residents_set))

    # 3. Missing executions & missing request keys
    missing_residents_set = expected_resident_ids - set(records_by_resident.keys())
    missing_executions = len(missing_residents_set) * reps
    missing_req_keys_list: list[str] = []
    for rid in sorted(missing_residents_set):
        for rep_idx in range(reps):
            missing_req_keys_list.append(f"{rid}:{rep_idx}")

    for res_id, r_list in sorted(records_by_resident.items()):
        if len(r_list) < reps:
            missing_executions += (reps - len(r_list))
            missing_residents_set.add(res_id)
            observed_indices = {r.sample_index for r in r_list}
            for rep_idx in range(reps):
                if rep_idx not in observed_indices:
                    missing_req_keys_list.append(f"{res_id}:{rep_idx}")

    missing_residents = tuple(sorted(missing_residents_set))
    missing_request_keys = tuple(sorted(dict.fromkeys(missing_req_keys_list)))

    # 4. Evaluate primary records for questionnaire completion & validity
    # Resolve the effective target question ID if experiment_definition maps choice to a specific question ID
    effective_target_qid = target_question_id
    if experiment_definition is not None:
        resolved_qid, _, _ = _resolve_question_and_valid_options(
            experiment_definition,
            target_question_id,
            None,
        )
        if resolved_qid:
            effective_target_qid = resolved_qid

    valid_records: list[PersonaExecutionRecord] = []
    status_counts: dict[str, int] = {
        "valid": 0,
        "invalid": 0,
        "failed": 0,
        "refused": 0,
        "timeout": 0,
    }
    if missing_executions > 0:
        status_counts["missing"] = missing_executions

    unanswered_residents: list[str] = []
    completed_valid_executions = 0
    failed_executions = 0

    for r in primary_records:
        ans_for_target = r.answers.get(effective_target_qid) or r.answers.get(target_question_id)
        has_any_non_empty_answer = any(
            v is not None and str(v).strip() != ""
            for v in r.answers.values()
        )
        if effective_target_qid in r.answers or target_question_id in r.answers:
            has_required_answer = bool(ans_for_target and str(ans_for_target).strip() != "")
        else:
            # If the record answered other questions (e.g. q2_policy_support) while omitting target_question_id,
            # check whether target_question_id was expected
            if r.answers and target_question_id not in r.answers and effective_target_qid not in r.answers:
                # Check if any record in the batch uses target_question_id
                batch_has_target = any(
                    (target_question_id in rec.answers or effective_target_qid in rec.answers)
                    for rec in primary_records
                )
                has_required_answer = (not batch_has_target) and has_any_non_empty_answer
            else:
                has_required_answer = has_any_non_empty_answer

        if r.status == "valid" and not has_required_answer:
            status_counts["invalid"] = status_counts.get("invalid", 0) + 1
            unanswered_residents.append(r.resident_id)
            failed_executions += 1
            distinct_errors.add(f"Missing required answer for '{effective_target_qid}'")
        elif r.status == "valid" and has_required_answer:
            status_counts["valid"] = status_counts.get("valid", 0) + 1
            valid_records.append(r)
            completed_valid_executions += 1
        else:
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
            unanswered_residents.append(r.resident_id)
            failed_executions += 1
            for err in r.errors:
                distinct_errors.add(err)

    # Also include missing residents in unanswered_residents if not already present
    for m_rid in missing_residents:
        if m_rid not in unanswered_residents:
            unanswered_residents.append(m_rid)

    successful_valid = completed_valid_executions
    total_failures = failed_executions + missing_executions
    total_attempted = expected_executions if expected_executions > 0 else len(primary_records)
    comp_rate = (
        (100.0 * completed_valid_executions / expected_executions)
        if expected_executions > 0
        else 0.0
    )

    failure_audit = FailureAuditSummary(
        total_attempted=total_attempted,
        successful_valid=successful_valid,
        total_failures=total_failures,
        completion_rate_pct=comp_rate,
        failure_breakdown_by_status=status_counts,
        distinct_error_messages=tuple(sorted(distinct_errors)),
        unanswered_residents=tuple(unanswered_residents),
        expected_executions=expected_executions,
        received_executions=received_executions,
        received_final_executions=len(final_records),
        diagnostic_retry_executions=len(diagnostic_retries),
        completed_valid_executions=completed_valid_executions,
        failed_executions=failed_executions,
        missing_executions=missing_executions,
        duplicate_executions=duplicate_executions,
        conflicting_executions=conflicting_executions,
        foreign_executions=foreign_executions,
        missing_residents=missing_residents,
        foreign_residents=foreign_residents,
        duplicate_residents=duplicate_residents,
        conflicting_residents=conflicting_residents,
        expected_request_keys=expected_request_keys,
        missing_request_keys=missing_request_keys,
    )

    def _resident_weight(res_id: str) -> float:
        demo = demographics_by_id.get(res_id, {})
        if weight_source == "analysis_weight":
            w = float(demo.get("analysis_weight", 1.0))
        elif weight_source == "population_weight":
            w = float(demo.get("population_weight", 1.0))
        else:
            w = 1.0
        return w / reps

    all_question_ids = sorted({q for r in valid_records for q in r.answers.keys()})
    question_summaries: list[QuestionDistributionSummary] = []
    total_weighted_evaluated = 0.0

    for q_id in all_question_ids:
        unweighted_counter: Counter[str] = Counter()
        weighted_counter: Counter[str] = Counter()
        q_valid_n = 0
        q_valid_weight = 0.0

        for r in valid_records:
            ans = r.answers.get(q_id)
            if ans is None or str(ans).strip() == "":
                continue
            w = _resident_weight(r.resident_id)
            unweighted_counter[ans] += 1
            weighted_counter[ans] += w
            q_valid_n += 1
            q_valid_weight += w

        if q_id in (target_question_id, effective_target_qid):
            total_weighted_evaluated = q_valid_weight

        choices: list[QuestionChoiceMetric] = []
        for choice_id, u_cnt in sorted(unweighted_counter.items()):
            w_cnt = weighted_counter[choice_id]
            u_share = u_cnt / q_valid_n if q_valid_n > 0 else 0.0
            w_share = w_cnt / q_valid_weight if q_valid_weight > 0.0 else 0.0
            se = math.sqrt(u_share * (1.0 - u_share) / q_valid_n) if q_valid_n > 0 else 0.0
            choices.append(
                QuestionChoiceMetric(
                    choice_id=choice_id,
                    unweighted_count=u_cnt,
                    unweighted_share=u_share,
                    weighted_count=w_cnt,
                    weighted_share=w_share,
                    std_error_unweighted=se,
                )
            )

        question_summaries.append(
            QuestionDistributionSummary(
                question_id=q_id,
                valid_responses_n=q_valid_n,
                valid_weighted_total=q_valid_weight,
                choices=tuple(choices),
                weight_source=weight_source,
            )
        )

    if total_weighted_evaluated == 0.0 and question_summaries:
        total_weighted_evaluated = question_summaries[0].valid_weighted_total

    subgroup_metrics: list[SubgroupComparisonMetric] = []
    candidate_dimensions = ("age_bracket", "sex", "marital_status", "education_level", "statutory_concession")

    def _age_bracket(age: Any) -> str:
        try:
            a = int(age)
            if a < 18:
                return "<18 (minor)"
            if a <= 29:
                return "18-29 (young adult)"
            if a <= 44:
                return "30-44 (middle age)"
            if a <= 64:
                return "45-64 (older adult)"
            return "65+ (senior)"
        except (ValueError, TypeError):
            return "unknown"

    def _concession_status(age: Any) -> str:
        try:
            a = int(age)
            return "senior_free_concession_law4736" if a >= 65 else "standard_fare_passenger"
        except (ValueError, TypeError):
            return "unknown"

    primary_qid = (
        effective_target_qid
        if any(q.question_id == effective_target_qid for q in question_summaries)
        else (
            target_question_id
            if any(q.question_id == target_question_id for q in question_summaries)
            else (question_summaries[0].question_id if question_summaries else target_question_id)
        )
    )

    for dim in candidate_dimensions:
        groups: dict[str, list[PersonaExecutionRecord]] = {}
        for r in valid_records:
            demo = demographics_by_id.get(r.resident_id, {})
            age_val = demo.get("age") if demo.get("age") is not None else demo.get("age_years")
            val: str
            if dim == "age_bracket":
                val = _age_bracket(age_val)
            elif dim == "statutory_concession":
                val = _concession_status(age_val)
            else:
                raw_val = demo.get(dim)
                val = str(raw_val) if raw_val is not None else "unknown"

            groups.setdefault(val, []).append(r)

        for seg_val, seg_records in sorted(groups.items()):
            n_seg = len(seg_records)
            w_seg = sum(_resident_weight(r.resident_id) for r in seg_records)

            is_low_conf = n_seg < min_subgroup_n
            conf_note = (
                f"LOW CONFIDENCE: Sample size n={n_seg} < threshold {min_subgroup_n}. "
                "Point estimates carry high sampling variance; interval omitted to prevent misleading inference."
                if is_low_conf else
                f"Adequate sample size (n={n_seg} >= {min_subgroup_n}) for subgroup analysis."
            )

            seg_u_counts: Counter[str] = Counter()
            seg_w_counts: Counter[str] = Counter()
            for r in seg_records:
                ans = r.answers.get(primary_qid)
                if ans:
                    w = _resident_weight(r.resident_id)
                    seg_u_counts[ans] += 1
                    seg_w_counts[ans] += w

            u_shares = {c: cnt / n_seg for c, cnt in seg_u_counts.items()} if n_seg > 0 else {}
            w_shares = {c: cnt / w_seg for c, cnt in seg_w_counts.items()} if w_seg > 0.0 else {}

            subgroup_metrics.append(
                SubgroupComparisonMetric(
                    subgroup_dimension=dim,
                    subgroup_value=seg_val,
                    sample_n=n_seg,
                    weighted_total=w_seg,
                    is_low_confidence=is_low_conf,
                    confidence_note=conf_note,
                    choice_shares_unweighted=u_shares,
                    choice_shares_weighted=w_shares,
                )
            )

    benchmark_results: list[BenchmarkComparisonResult] = []
    q1_summary = next((q for q in question_summaries if q.question_id == primary_qid), None)
    simulated_reduce_share = 0.0
    if q1_summary:
        for c in q1_summary.choices:
            if c.choice_id == "reduce_optional_trips":
                simulated_reduce_share = c.weighted_share

    for b in benchmark_bundle.benchmarks:
        if b.status == "unavailable":
            benchmark_results.append(
                BenchmarkComparisonResult(
                    benchmark_id=b.benchmark_id,
                    name=b.name,
                    evidence_type=b.evidence_type,
                    benchmark_status="unavailable",
                    evidence_status="unverified_hypothetical",
                    evidence_status_statement=(
                        f"BENCHMARK UNAVAILABLE: No empirical ground truth exists for {b.name!r}. "
                        "The evaluation layer refuses to invent synthetic numbers for unobserved behavioral benchmarks."
                    ),
                    unavailability_reason=b.unavailability_reason,
                    notes=(
                        "See docs/benchmark_availability.md for complete documentation of this validation gap.",
                    ),
                )
            )
        elif b.benchmark_id == "literature_transit_fare_elasticity":
            sim_pct = simulated_reduce_share * 100.0
            lit_expected_drop_pct = 6.6
            diff_pp = sim_pct - lit_expected_drop_pct
            within_env = (b.observed_range is not None and -0.50 <= (-(sim_pct / 20.0)) <= -0.20)
            benchmark_results.append(
                BenchmarkComparisonResult(
                    benchmark_id=b.benchmark_id,
                    name=b.name,
                    evidence_type=b.evidence_type,
                    benchmark_status="available",
                    evidence_status="literature_envelope",
                    evidence_status_statement=(
                        "LITERATURE ENVELOPE: Evaluates stated trip reductions against international econometric "
                        "meta-analyses (Litman / TRRL 920: e_p in [-0.50, -0.20]). Stated intention typically exceeds "
                        "revealed elasticity by 3x–6x due to hypothetical bias."
                    ),
                    benchmark_value=-0.33,
                    benchmark_range=b.observed_range,
                    simulated_value=round(sim_pct, 1),
                    difference_pp=round(diff_pp, 1),
                    is_within_envelope=within_env,
                    notes=(
                        f"Simulated stated trip reduction: {sim_pct:.1f}% (stated choice: reduce_optional_trips).",
                        f"Expected literature ridership drop: ~{lit_expected_drop_pct:.1f}% (e_p = -0.33).",
                        f"The {diff_pp:+.1f} pp gap illustrates classic stated-preference protest/hypothetical bias.",
                    ),
                )
            )
        elif b.benchmark_id == "tuik_tr51_household_transport_expenditure_share":
            benchmark_results.append(
                BenchmarkComparisonResult(
                    benchmark_id=b.benchmark_id,
                    name=b.name,
                    evidence_type=b.evidence_type,
                    benchmark_status="available",
                    evidence_status="empirical_ground_truth",
                    evidence_status_statement=(
                        "MACROECONOMIC CONTEXT: TÜİK Household Budget Survey (HBA) establishes that 23.6% of Ankara "
                        "household consumption goes to transport (2nd highest in Türkiye), validating high economic "
                        "sensitivity to public transit tariffs."
                    ),
                    benchmark_value=b.observed_value,
                    benchmark_range=b.observed_range,
                    simulated_value=None,
                    difference_pp=None,
                    is_within_envelope=True,
                    notes=(
                        "Economic context benchmark: validates why lower- and middle-income personas exhibit high opposition.",
                    ),
                )
            )
        else:
            benchmark_results.append(
                BenchmarkComparisonResult(
                    benchmark_id=b.benchmark_id,
                    name=b.name,
                    evidence_type=b.evidence_type,
                    benchmark_status=b.status,
                    evidence_status="synthetic_simulation_baseline" if b.evidence_type == "hypothetical_assumption" else "literature_envelope",
                    evidence_status_statement=f"Benchmark evaluated under evidence type {b.evidence_type!r}.",
                    benchmark_value=b.observed_value,
                    benchmark_range=b.observed_range,
                    simulated_value=None,
                    difference_pp=None,
                    is_within_envelope=None,
                    notes=b.comparability.limitations,
                )
            )

    difference_weighting = "weighted" if weight_source in ("analysis_weight", "population_weight") else "unweighted"
    baseline_deltas: list[InterventionBaselineDelta] = []
    if baseline_simulation_results is not None:
        base_adapter = SimulationResultsAdapter.from_any(
            baseline_simulation_results,
            experiment_definition=experiment_definition,
            default_question_id=primary_qid,
        )
        base_valid = [r for r in base_adapter.records if r.is_final and r.status == "valid" and r.answers.get(primary_qid)]
        base_u_cnt: Counter[str] = Counter()
        base_w_cnt: Counter[str] = Counter()
        base_n = 0
        base_w_tot = 0.0
        for r in base_valid:
            ans = r.answers.get(primary_qid)
            if ans:
                w = _resident_weight(r.resident_id)
                base_u_cnt[ans] += 1
                base_w_cnt[ans] += w
                base_n += 1
                base_w_tot += w

        if base_n > 0 and q1_summary:
            for c in q1_summary.choices:
                b_u_share = base_u_cnt.get(c.choice_id, 0) / base_n
                b_w_share = base_w_cnt.get(c.choice_id, 0.0) / base_w_tot if base_w_tot > 0.0 else b_u_share
                i_u_share = c.unweighted_share
                i_w_share = c.weighted_share

                if difference_weighting == "weighted":
                    base_share = b_w_share
                    interv_share = i_w_share
                else:
                    base_share = b_u_share
                    interv_share = i_u_share

                pp_delta = (interv_share - base_share) * 100.0
                pp_delta_unweighted = (i_u_share - b_u_share) * 100.0
                rel_chg = ((interv_share - base_share) / base_share * 100.0) if base_share > 0 else 0.0
                baseline_deltas.append(
                    InterventionBaselineDelta(
                        metric_name=f"{primary_qid}:{c.choice_id}",
                        baseline_run_id=base_adapter.run_id,
                        intervention_run_id=run_adapter.run_id,
                        baseline_share=base_share,
                        intervention_share=interv_share,
                        percentage_point_delta=round(pp_delta, 2),
                        relative_change_pct=round(rel_chg, 2),
                        baseline_share_unweighted=b_u_share,
                        intervention_share_unweighted=i_u_share,
                        percentage_point_delta_unweighted=round(pp_delta_unweighted, 2),
                        difference_weighting=difference_weighting,
                    )
                )

    evidence_status_summary = (
        "SYNTHETIC SIMULATION BASELINE: All simulated response distributions represent generative agent "
        "persona outputs for software and pipeline evaluation. They CANNOT be interpreted as observed empirical "
        "human behavior, nor do they establish real-world predictive validity."
    )
    val_gap_statement = (
        "VALIDATION GAP: No empirical econometric fare elasticity micro-data exists in Ankara (EGO publishes raw "
        "boardings only). Missing benchmarks are reported as 'unavailable' in accordance with project rules. "
        "Literature elasticity envelopes (-0.20 to -0.50) serve only as broad plausibility sanity checks."
    )

    resolved_cohort_id = run_adapter.cohort_id or extracted_meta.get("cohort_id")
    resolved_sample_id = run_adapter.sample_id or extracted_meta.get("sample_id")
    resolved_population_id = run_adapter.population_id or extracted_meta.get("population_id")
    resolved_experiment_id = run_adapter.experiment_id
    resolved_plan_hash = run_adapter.plan_hash

    sampling_method = (
        run_adapter.manifest.get("sampling_method")
        or run_adapter.manifest.get("method")
        or (
            run_adapter.manifest.get("cohort", {}).get("sampling_method")
            if isinstance(run_adapter.manifest.get("cohort"), Mapping)
            else None
        )
        or extracted_meta.get("sampling_method")
        or ("sampled_cohort" if input_kind == "sampled_cohort" else "full_population")
    )

    provenance = {
        "run_id": run_adapter.run_id,
        "simulation_run_id": run_adapter.run_id,
        "cohort_id": resolved_cohort_id,
        "sample_id": resolved_sample_id,
        "population_id": resolved_population_id,
        "experiment_id": resolved_experiment_id,
        "scenario_id": run_adapter.scenario_id,
        "plan_hash": resolved_plan_hash,
        "weight_source": weight_source,
        "sampling_method": sampling_method,
        "input_kind": input_kind,
        "manifest": run_adapter.manifest,
    }

    return SimulationEvaluationReport(
        report_schema_version=SIMULATION_REPORT_SCHEMA_VERSION,
        evaluator_version=REPORTS_EVALUATOR_VERSION,
        scenario_id=run_adapter.scenario_id,
        run_id=run_adapter.run_id,
        cohort_id=resolved_cohort_id,
        sample_id=resolved_sample_id,
        population_id=resolved_population_id,
        experiment_id=resolved_experiment_id,
        plan_hash=resolved_plan_hash,
        evaluated_at=None,
        population_size_evaluated=total_attempted,
        total_represented_weight=total_weighted_evaluated,
        failure_audit=failure_audit,
        overall_question_distributions=tuple(question_summaries),
        subgroup_comparisons=tuple(subgroup_metrics),
        benchmark_comparisons=tuple(benchmark_results),
        baseline_deltas=tuple(baseline_deltas),
        evidence_status_summary=evidence_status_summary,
        validation_gap_statement=val_gap_statement,
        simulation_run_id=run_adapter.run_id,
        provenance=provenance,
        weight_source=weight_source,
        sampling_method=sampling_method,
        input_kind=input_kind,
        difference_weighting=difference_weighting,
    )


def generate_combined_quality_report(
    population: Any,
    reference_bundle: Any = None,
    *,
    simulation_results: Any = None,
    baseline_simulation_results: Any = None,
    benchmark_bundle: BenchmarkBundle | None = None,
    tolerances: CalibrationTolerances | None = None,
    households: Any = None,
    save_to_disk: bool = True,
    output_dir: Path | str | None = None,
) -> CombinedQualityReport:
    """Generate a comprehensive Phase 7 Combined Quality Report integrating K3, K4, and K6.

    Saves deterministically named JSON and Markdown files to disk inside `output_dir` if `save_to_disk=True`.
    """
    if tolerances is None:
        tolerances = CalibrationTolerances()
    if benchmark_bundle is None:
        benchmark_bundle = get_ankara_transit_fare_bundle()

    # 1. Run K3 Population Marginal Validation
    pop_report = validate_population(
        population,
        reference_bundle=reference_bundle,
        tolerances=tolerances,
        households=households,
    )

    # 2. Run K4 Dependency Validation
    dep_report = validate_dependencies(
        population,
        reference_bundle=reference_bundle,
        tolerances=tolerances,
        households=households,
        marginal_report=pop_report,
    )

    # 3. Run K6 Simulation Evaluation (if simulation results provided)
    sim_report: SimulationEvaluationReport | None = None
    if simulation_results is not None:
        sim_report = evaluate_simulation(
            simulation_results=simulation_results,
            cohort_metadata=population,
            benchmark_bundle=benchmark_bundle,
            baseline_simulation_results=baseline_simulation_results,
        )

    # 4. Integrate into UnifiedCheckRecords
    unified_checks: list[UnifiedCheckRecord] = []

    # Population margin checks
    for chk in pop_report.checks:
        unified_checks.append(
            UnifiedCheckRecord(
                check_id=chk.check_id,
                layer="marginal_population",
                name=f"Marginal {chk.margin.replace('_', ' ').title()}",
                status=chk.status,
                reason=chk.reason,
                dataset_provenance=chk.dataset_provenance,
                scope_marker=chk.dataset_provenance.scope_marker,
                is_calibrated=chk.is_calibrated_margin,
            )
        )

    # Dependency joint checks
    for chk in dep_report.supported_joint_checks:
        unified_checks.append(
            UnifiedCheckRecord(
                check_id=chk.check_id,
                layer="joint_dependency",
                name=chk.name,
                status=chk.status,
                reason=chk.reason,
                scope_marker=chk.scope_label,
                is_calibrated=False,
            )
        )

    for chk in dep_report.unverified_relationships:
        unified_checks.append(
            UnifiedCheckRecord(
                check_id=chk.check_id,
                layer="joint_dependency",
                name=chk.name,
                status=chk.status,
                reason=chk.reason,
                scope_marker=chk.scope_label,
                is_calibrated=False,
            )
        )

    # 5. Compile Validation Gaps & Limitations
    gaps: list[ValidationGapRecord] = [
        ValidationGapRecord(
            gap_id=ANKARA_HOUSEHOLD_DISCREPANCY_FLAG.flag_id,
            category="data_discrepancy",
            summary=ANKARA_HOUSEHOLD_DISCREPANCY_FLAG.summary,
            policy_action=ANKARA_HOUSEHOLD_DISCREPANCY_FLAG.handling_policy,
            details=ANKARA_HOUSEHOLD_DISCREPANCY_FLAG.root_causes,
        ),
        ValidationGapRecord(
            gap_id=EDUCATION_UNIVERSE_GAP_FLAG.flag_id,
            category="data_discrepancy",
            summary=EDUCATION_UNIVERSE_GAP_FLAG.summary,
            policy_action=EDUCATION_UNIVERSE_GAP_FLAG.handling_policy,
            details=EDUCATION_UNIVERSE_GAP_FLAG.root_causes,
        ),
        ValidationGapRecord(
            gap_id=LABOUR_RATE_ONLY_FLAG.flag_id,
            category="data_discrepancy",
            summary=LABOUR_RATE_ONLY_FLAG.summary,
            policy_action=LABOUR_RATE_ONLY_FLAG.handling_policy,
            details=LABOUR_RATE_ONLY_FLAG.root_causes,
        ),
        ValidationGapRecord(
            gap_id="UNVERIFIED_AGE_EDUCATION_JOINT",
            category="unverified_relationship",
            summary="Empirical age × education joint distribution is unobserved in public TÜİK tables.",
            policy_action="Never invent synthetic benchmark; verify deterministic structural zeros only.",
            details=("TÜİK NESD publishes sex-only marginals; age-conditional tables are unobserved at province level.",),
        ),
        ValidationGapRecord(
            gap_id="UNAVAILABLE_ANKARA_FARE_ELASTICITY",
            category="unavailable_benchmark",
            summary="Ankara EGO General Directorate publishes aggregate boardings only; no econometric fare elasticity is available.",
            policy_action="Report status as 'unavailable'; use international literature meta-estimates as sanity envelope only.",
            details=("Macroeconomic inflation (>60%) and statutory 65+ free transit confound simple time-series differencing.",),
        ),
    ]

    limitations: list[str] = [
        "1. Calibrated Margins vs. Joint Realism: Exact marginal convergence (K3) does not guarantee realistic multivariate associations (K4).",
        "2. National Proxy Scope: Age-conditional marital benchmarks derive from national broad-age tables (Table 1.9), labeled 'national proxy, not Ankara-observed'.",
        "3. Stated Intention Non-Equivalence: Stated survey responses systematically over-report trip reduction due to protest and hypothetical bias; they cannot be equated to observed turnstile ridership drops.",
        "4. Unlinked Resident Population: Resident personas do not carry empirical household membership links (D1 discrepancy: 1,987,216 private households vs 5,910,320 residents).",
    ]

    # Overall status calculation
    all_statuses = [c.status for c in unified_checks]
    status_counts = {
        "pass": all_statuses.count("pass"),
        "fail": all_statuses.count("fail"),
        "not_evaluable": all_statuses.count("not_evaluable"),
    }
    overall_status: CheckStatus = "fail" if status_counts["fail"] > 0 else ("pass" if status_counts["pass"] > 0 else "not_evaluable")

    # Extract population artifact content hash (distinct from reference_package_fingerprint)
    pop_sha: str | None = None
    if hasattr(population, "manifest") and isinstance(population.manifest, Mapping):
        pop_sha = population.manifest.get("content_sha256") or population.manifest.get("sha256")
    elif isinstance(population, Mapping):
        if "manifest" in population and isinstance(population["manifest"], Mapping):
            pop_sha = population["manifest"].get("content_sha256") or population["manifest"].get("sha256")
        elif "content_sha256" in population:
            pop_sha = population["content_sha256"]
    if not pop_sha:
        from societytwin.validation.population import _extract_population_columns_and_manifest
        try:
            cols, p_manifest, _, _ = _extract_population_columns_and_manifest(population)
            pop_sha = p_manifest.get("content_sha256") or canonical_hash(cols)
        except Exception:
            pop_sha = canonical_hash(str(population))

    sim_run_id = sim_report.run_id if sim_report else None
    cohort_id = sim_report.cohort_id if sim_report else None
    sample_id = sim_report.sample_id if sim_report else None
    experiment_id = sim_report.experiment_id if sim_report else None
    scenario_id = sim_report.scenario_id if sim_report else None
    plan_hash = sim_report.plan_hash if sim_report else None
    sim_provenance = dict(sim_report.provenance) if sim_report else {}
    sim_provenance.update(
        {
            "population_id": pop_report.population_id,
            "population_version": pop_report.population_version,
            "population_sha256": pop_sha,
            "reference_package_version": pop_report.reference_package_version,
            "reference_package_fingerprint": pop_report.reference_package_fingerprint,
            "report_schema_version": COMBINED_REPORT_SCHEMA_VERSION,
            "evaluator_version": REPORTS_EVALUATOR_VERSION,
        }
    )

    combined_report = CombinedQualityReport(
        report_schema_version=COMBINED_REPORT_SCHEMA_VERSION,
        evaluator_version=REPORTS_EVALUATOR_VERSION,
        population_id=pop_report.population_id,
        population_version=pop_report.population_version,
        population_sha256=pop_sha,
        reference_package_version=pop_report.reference_package_version,
        reference_package_fingerprint=pop_report.reference_package_fingerprint,
        simulation_run_id=sim_run_id,
        cohort_id=cohort_id,
        sample_id=sample_id,
        experiment_id=experiment_id,
        scenario_id=scenario_id,
        plan_hash=plan_hash,
        provenance=sim_provenance,
        geography_code=pop_report.geography_code,
        reference_year=pop_report.reference_year,
        sample_size=pop_report.sample_size,
        weighted_population_total=pop_report.weighted_population_total,
        seed=pop_report.seed,
        overall_status=overall_status,
        status_counts=status_counts,
        checks=tuple(unified_checks),
        population_report=pop_report,
        dependency_report=dep_report,
        simulation_report=sim_report,
        validation_gaps=tuple(gaps),
        limitations=tuple(limitations),
    )

    if save_to_disk:
        if output_dir is None:
            output_dir = Path("data/reference_package_k2_v1")
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Deterministic file naming:
        # Include BOTH population ID/version and simulation_run_id when simulation run is present
        pop_slug = f"{combined_report.population_id}_{combined_report.population_version}"
        if combined_report.simulation_run_id:
            file_stem = f"quality_report_{pop_slug}_{combined_report.simulation_run_id}"
        else:
            file_stem = f"quality_report_{pop_slug}"

        json_file = output_dir / f"{file_stem}.json"
        md_file = output_dir / f"{file_stem}.md"

        # Write byte-identical deterministic JSON (sorted keys, indent=2) and Markdown in output_dir
        json_file.write_text(json.dumps(combined_report.deterministic_dict, indent=2, sort_keys=True), encoding="utf-8")
        md_file.write_text(combined_report.to_markdown(), encoding="utf-8")

    return combined_report
