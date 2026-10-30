"""Experiment definitions: Scenario, Task, Environment, Cohort, Model and Execution are separate parts.

    SCENARIO     what is happening (with explicit parameters; hypothetical unless a source is cited)
    TASK         what the agent must do (a closed set of options; structured output)
    ENVIRONMENT  where it happens (province context indicators, each with its own source year)
    COHORT       who is asked (a saved cohort plus a seeded sample of bounded size)
    MODEL        which backend, model and settings execute it
    EXECUTION    repetitions, retry policy and the budget guard (call and cost caps)

Nothing here calls a model. ``render_prompts`` produces the exact text a backend receives and
``parse_response`` validates a backend's structured answer against the task's options.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from societytwin.common import canonical_hash
from societytwin.national.cohorts import STRATIFIABLE
from societytwin.national.rng import MAX_SEED
from societytwin.national.persona_selection import FieldSelection

DEFINITION_VERSION = "experiment-definition-1"
PROMPT_TEMPLATE_VERSION = "tr-task-prompt-1"
MODEL_PATTERN = r"^[a-z0-9]{2,32}/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
HARD_MAX_AGENTS = 1000
HARD_MAX_CALLS = 5000


class ScenarioParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    label: str = Field(min_length=1, max_length=120)
    value: float | str
    unit: str | None = Field(default=None, max_length=24)


class ScenarioSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    parameters: list[ScenarioParameter] = Field(default_factory=list, max_length=20)
    hypothetical: bool = True
    source_note: str | None = Field(default=None, max_length=1000,
                                    description="Required when the scenario is presented as factual: where its values come from.")
    version: str = Field(default="1", pattern=r"^[A-Za-z0-9._-]{1,32}$")

    @model_validator(mode="after")
    def _sourced(self):
        if not self.hypothetical and not (self.source_note and self.source_note.strip()):
            raise ValueError("A non-hypothetical scenario must cite its source in source_note")
        names = [p.name for p in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("Scenario parameter names must be unique")
        return self


class TaskOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,48}$")
    label: str = Field(min_length=1, max_length=300)


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1, max_length=2000)
    response_type: str = Field(default="single_choice", pattern="^single_choice$")
    options: list[TaskOption] = Field(min_length=2, max_length=12)
    allow_other_text: bool = False
    ask_rationale: bool = True
    adult_only: bool = True
    version: str = Field(default="1", pattern=r"^[A-Za-z0-9._-]{1,32}$")

    @model_validator(mode="after")
    def _options(self):
        ids = [o.id for o in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("Option ids must be unique")
        if self.allow_other_text and "other" not in ids:
            raise ValueError("allow_other_text requires an option with id 'other'")
        return self


class EnvironmentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    province_code: str | None = Field(default=None, pattern=r"^\d{2}$",
                                      description="Province whose context is shown; None means each persona's own province.")
    context_indicators: list[str] = Field(default_factory=list, max_length=20)


class CohortSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cohort_id: str = Field(min_length=1, max_length=64)
    sample_size: int = Field(ge=1, le=HARD_MAX_AGENTS)
    sampling_method: str = Field(default="weighted", pattern="^(simple_random|weighted|stratified)$")
    seed: int = Field(ge=0, le=MAX_SEED)
    strata_field: str | None = Field(default=None, pattern="^(" + "|".join(STRATIFIABLE) + ")$")


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: str = Field(pattern="^(stub|matraix)$",
                         description="stub: offline deterministic placeholder (not a model). matraix: MatrAIx survey agent.")
    transport: str = Field(default="fake", pattern="^(fake|live)$",
                           description="matraix only: fake = MatrAIx's zero-cost smoke client; live = provider calls (gated).")
    model: str | None = Field(default=None, pattern=MODEL_PATTERN)
    temperature: float = Field(default=0.0, ge=0, le=2)
    seed: int | None = Field(default=None, ge=0, le=MAX_SEED, description="Passed to backends that support a sampling seed.")
    max_output_tokens: int = Field(default=512, ge=16, le=4096)

    @model_validator(mode="after")
    def _consistent(self):
        if self.backend == "matraix" and self.transport == "live" and not self.model:
            raise ValueError("Live execution needs an explicit provider/model")
        if self.backend == "stub" and self.transport != "fake":
            raise ValueError("The stub backend never calls a provider")
        return self


class ExecutionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repetitions: int = Field(default=1, ge=1, le=5, description="Independent responses per persona.")
    max_attempts: int = Field(default=1, ge=1, le=3, description="1 = no retry. Retries apply to failed or invalid responses only.")
    max_calls: int = Field(ge=1, le=HARD_MAX_CALLS, description="Hard cap on backend calls, retries included.")
    max_cost_usd: float | None = Field(default=None, ge=0, le=1000)


class PersonaPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visible_fields: list[str] | None = Field(default=None, description="None = default policy (see personas.DEFAULT_VISIBLE).")
    field_selection: FieldSelection | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def _selection(self):
        if self.field_selection is not None and self.visible_fields is not None:
            raise ValueError("Use either visible_fields or field_selection")
        return self


class ScenarioReference(BaseModel):
    """Provenance and targeting of a definition built from a Scenario Engine config (src/scenarios).

    Optional: hand-written definitions omit it. When present, the plan enforces its geographic and age
    scope against every sampled persona and blocks execution on any mismatch.
    """
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    scenario_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    question_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    question_type: str = Field(default="single_choice", pattern="^single_choice$")
    province_codes: list[str] | None = Field(default=None, max_length=81,
                                             description="Provinces the scenario applies to; None = no restriction.")
    minimum_age: int | None = Field(default=None, ge=0, le=120)
    maximum_age: int | None = Field(default=None, ge=0, le=120)
    required_attributes: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Population attributes required by the scenario; missing or unavailable values block the plan.",
    )
    unenforced_filters: list[str] = Field(default_factory=list, max_length=10,
                                          description="Scenario filters this runtime cannot enforce; a non-empty list blocks the plan.")

    @model_validator(mode="after")
    def _codes(self):
        for code in self.province_codes or []:
            if not re.fullmatch(r"\d{2}", code):
                raise ValueError(f"Invalid province code {code!r} in scenario_ref")
        if self.minimum_age is not None and self.maximum_age is not None and self.minimum_age > self.maximum_age:
            raise ValueError("scenario_ref minimum_age exceeds maximum_age")
        self.required_attributes = [str(f).strip() for f in self.required_attributes if str(f).strip()]
        return self


def scenario_scope_issues(ref: ScenarioReference, record: dict) -> list[str]:
    """Reasons a population record falls outside a scenario's target scope ([] = in scope).

    Missing values are reported, never assumed to match.
    """
    issues = []
    if ref.province_codes:
        code = record.get("province_code")
        if code is None:
            issues.append("province_missing")
        elif code not in ref.province_codes:
            issues.append("province_outside_scope")
    if ref.minimum_age is not None or ref.maximum_age is not None:
        age = record.get("age")
        if age is None:
            issues.append("age_missing")
        elif (ref.minimum_age is not None and age < ref.minimum_age) or (ref.maximum_age is not None and age > ref.maximum_age):
            issues.append("age_outside_scope")
    for attr in ref.required_attributes:
        val = record.get(attr)
        if val is None or val == "" or val == "unavailable":
            issues.append(f"required_attribute_missing:{attr}")
    return issues


def scenario_parameter_issues(definition: "ExperimentDefinition") -> list[str]:
    """Check mathematical and prompt-text consistency of tariff/fare scenario parameters."""
    params = {p.name: p.value for p in definition.scenario.parameters}
    base = params.get("baseline_tariff")
    new = params.get("new_tariff")
    pct = params.get("tariff_change_percent")

    def _is_num(v) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    issues: list[str] = []
    if _is_num(base) and _is_num(new) and _is_num(pct):
        expected_new = float(base) * (1.0 + float(pct) / 100.0)
        if abs(expected_new - float(new)) > 0.05:
            issues.append(
                f"Scenario parameters are mathematically inconsistent: baseline_tariff ({float(base):g}) "
                f"with tariff_change_percent ({float(pct):g}%) implies {expected_new:.2f}, "
                f"but new_tariff is {float(new):g}."
            )

    for label, text in (
        ("scenario description", definition.scenario.description),
        ("task instruction", definition.task.instruction),
    ):
        if _is_num(pct):
            pct_matches = re.findall(r"([+-]?\d+(?:\.\d+)?)\s*%", text)
            if pct_matches and not any(abs(abs(float(m)) - abs(float(pct))) <= 0.05 for m in pct_matches):
                found_str = ", ".join(f"{m}%" for m in pct_matches)
                issues.append(
                    f"The {label} mentions {found_str}, which contradicts parameter "
                    f"tariff_change_percent ({float(pct):g}%)."
                )
        if _is_num(new):
            from_to = re.search(
                r"\bfrom\s+(\d+(?:\.\d+)?)\s*(?:[A-Za-z/₺]+)?\s+to\s+(\d+(?:\.\d+)?)",
                text,
                flags=re.IGNORECASE,
            )
            if from_to:
                text_base = float(from_to.group(1))
                text_new = float(from_to.group(2))
                if _is_num(base) and abs(text_base - float(base)) > 0.05:
                    issues.append(
                        f"The {label} states a baseline of {text_base:g}, which contradicts "
                        f"parameter baseline_tariff ({float(base):g})."
                    )
                if abs(text_new - float(new)) > 0.05:
                    issues.append(
                        f"The {label} states a proposed value of {text_new:g}, which contradicts "
                        f"parameter new_tariff ({float(new):g})."
                    )
    return issues


class ExperimentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    scenario: ScenarioSpec
    task: TaskSpec
    environment: EnvironmentSpec = Field(default_factory=EnvironmentSpec)
    cohort: CohortSpec
    model: ModelSpec
    execution: ExecutionSpec
    persona: PersonaPolicy = Field(default_factory=PersonaPolicy)
    scenario_ref: ScenarioReference | None = Field(default=None, exclude_if=lambda v: v is None)

    def definition_hash(self) -> str:
        return canonical_hash({"version": DEFINITION_VERSION, **self.model_dump()})


def _fmt_value(value) -> str:
    """Readable numbers in prompts: thousands separators; non-integers to one decimal."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"
    return str(value)


UNIT_DISPLAY = {"percent": "%", "per_thousand": "per 1,000", "per_100k": "per 100,000", "persons_per_km2": "persons per km²",
                "person": "persons", "per_100_persons": "per 100 persons", "thousand_try": "thousand TRY", "try": "TRY", "usd": "USD"}


def _with_unit(value, unit: str | None) -> str:
    if not unit:
        return _fmt_value(value)
    unit = UNIT_DISPLAY.get(unit, unit.replace("_", " ") if "_" in unit else unit)
    return f"{_fmt_value(value)}{unit}" if unit == "%" else f"{_fmt_value(value)} {unit}"


def render_prompts(definition: ExperimentDefinition, persona: dict, context: list[dict], context_province: str) -> tuple[str, str]:
    """(system, user). The system prompt is the persona card; the user prompt holds environment, scenario and task."""
    task, scenario = definition.task, definition.scenario
    lines = []
    if context:
        lines.append(f"Context: {context_province}, as published in official statistics")
        for c in context:
            lines.append(f"- {c['label']}: {_with_unit(c['value'], c.get('unit'))} ({c.get('source_period') or c['source_year']})")
        lines.append("")
    lines.append(f"Scenario{' (hypothetical)' if scenario.hypothetical else ''}: {scenario.title}")
    lines.append(scenario.description.strip())
    if scenario.parameters:
        lines.append("Parameters:")
        for p in scenario.parameters:
            lines.append(f"- {p.label}: {_with_unit(p.value, p.unit)}")
    if scenario.hypothetical:
        lines.append("These values are hypothetical and set for this experiment; they are not a statement of current policy.")
    lines += ["", f"Task: {task.instruction.strip()}", "Options:"]
    lines += [f"- {o.id}: {o.label}" for o in task.options]
    shape = {"choice": "<one option id from the list>"}
    if task.allow_other_text:
        shape["other_text"] = "<only if choice is other>"
    if task.ask_rationale:
        shape["rationale"] = "<one or two sentences>"
    lines += ["", "Respond with a single JSON object and nothing else, in this shape:", json.dumps(shape, ensure_ascii=False)]
    return persona["persona_card"], "\n".join(lines)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_response(text: str | None, task: TaskSpec) -> dict:
    """Validate a structured answer. Never guesses a choice from free text."""
    if text is None or not text.strip():
        return {"valid": False, "error": "empty response"}
    raw = _FENCE.sub("", text.strip())
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return {"valid": False, "error": "response is not a JSON object"}
        try:
            payload = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return {"valid": False, "error": "response is not valid JSON"}
    if not isinstance(payload, dict):
        return {"valid": False, "error": "response JSON is not an object"}
    choice = payload.get("choice")
    ids = [o.id for o in task.options]
    if choice not in ids:
        return {"valid": False, "error": f"choice {choice!r} is not one of the task options"}
    other = payload.get("other_text") if task.allow_other_text and choice == "other" else None
    rationale = payload.get("rationale")
    return {"valid": True, "choice": choice, "other_text": other if isinstance(other, str) else None,
            "rationale": rationale if isinstance(rationale, str) else None}


def example_fare_definition(cohort_id: str, seed: int = 7) -> dict:
    """The SocietyTwin demonstration design. Fare values are HYPOTHETICAL experiment parameters, not current fares."""
    return {
        "title": "Ankara public transport fare increase (hypothetical)",
        "scenario": {
            "title": "Public transport fares increase by 20%",
            "description": "The single-ride public transport fare in the persona's city rises from 40 TL to 48 TL starting next month. "
                           "Nothing else about the service changes.",
            "parameters": [{"name": "old_fare", "label": "Current fare (scenario baseline)", "value": 40, "unit": "TL"},
                           {"name": "new_fare", "label": "New fare", "value": 48, "unit": "TL"},
                           {"name": "increase_percent", "label": "Increase", "value": 20, "unit": "%"}],
            "hypothetical": True,
        },
        "task": {
            "instruction": "Which transportation response would this person most likely choose?",
            "options": [{"id": "continue_public_transport", "label": "Continue using public transport as before"},
                        {"id": "reduce_optional_trips", "label": "Reduce optional, non-essential trips"},
                        {"id": "walk_more", "label": "Walk for some short trips"},
                        {"id": "car_or_carpool", "label": "Use a car or carpool for some trips"},
                        {"id": "switch_transport_mode", "label": "Switch to another motorised mode (taxi, dolmuş, scooter)"},
                        {"id": "other", "label": "Something else"}],
            "allow_other_text": True, "ask_rationale": True, "adult_only": True,
        },
        "environment": {"province_code": "06", "context_indicators": ["total_population", "population_density"]},
        "cohort": {"cohort_id": cohort_id, "sample_size": 20, "sampling_method": "weighted", "seed": seed},
        "model": {"backend": "stub", "transport": "fake", "temperature": 0.0},
        "execution": {"repetitions": 1, "max_attempts": 1, "max_calls": 20},
    }
