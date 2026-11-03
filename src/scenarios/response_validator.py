"""Structured agent response contract and validation for scenario experiments.

Validates persona responses against scenario questions without calling LLMs.
Strictly rejects invalid choices, partial answers, or hallucinated option IDs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Union

try:
    from .schema import ScenarioConfig
except ImportError:
    from scenarios.schema import ScenarioConfig  # type: ignore

RESPONSE_SCHEMA_VERSION = "1.0.0"
_FENCE_REGEX = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class ResponseStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    REFUSED = "refused"
    PARSE_ERROR = "parse_error"


@dataclass
class AgentResponseEnvelope:
    """Standardized envelope containing validated answers from an AI persona."""
    scenario_id: str
    resident_id: str
    schema_version: str = RESPONSE_SCHEMA_VERSION
    status: ResponseStatus = ResponseStatus.VALID
    answers: dict[str, Any] = field(default_factory=dict)
    other_text: dict[str, str] = field(default_factory=dict)
    rationale: str | None = None
    errors: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] | None = None

    def is_valid(self) -> bool:
        return self.status == ResponseStatus.VALID

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "resident_id": self.resident_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "answers": self.answers,
            "other_text": self.other_text,
            "rationale": self.rationale,
            "errors": self.errors,
        }


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    """Extract and parse a JSON dictionary from raw model text or fenced blocks."""
    cleaned = _FENCE_REGEX.sub("", raw_text.strip()).strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Fallback: attempt to find outermost braces
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidate = cleaned[start:end + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    raise ValueError("Response text does not contain a valid JSON object.")


def validate_agent_response(
    response_input: Union[str, dict[str, Any]],
    scenario: ScenarioConfig,
    resident_id: str | None = None,
) -> AgentResponseEnvelope:
    """Validate an AI agent's structured response against a ScenarioConfig.

    Args:
        response_input: JSON string or dictionary representing agent output.
        scenario: Validated ScenarioConfig against which answers are checked.
        resident_id: Optional resident ID fallback if not present in the payload.

    Returns:
        AgentResponseEnvelope with status, parsed answers, and diagnostic errors.
    """
    payload: dict[str, Any]
    if isinstance(response_input, dict):
        payload = response_input
    else:
        try:
            payload = _extract_json_payload(str(response_input))
        except Exception as exc:
            return AgentResponseEnvelope(
                scenario_id=scenario.scenario_id,
                resident_id=str(resident_id or "UNKNOWN_RESIDENT"),
                status=ResponseStatus.PARSE_ERROR,
                errors=[f"Failed to parse response as JSON: {exc}"],
            )

    extracted_res_id = str(payload.get("resident_id") or resident_id or "UNKNOWN_RESIDENT")
    extracted_scenario_id = str(payload.get("scenario_id") or scenario.scenario_id)

    errors: list[str] = []

    # 1. Check Scenario ID match
    if "scenario_id" in payload and payload["scenario_id"] != scenario.scenario_id:
        errors.append(
            f"Mismatched scenario_id: response has '{payload['scenario_id']}', but expected '{scenario.scenario_id}'"
        )

    # 2. Extract answers mapping
    raw_answers = payload.get("answers")
    if not isinstance(raw_answers, dict):
        # Fallback: check if answers were flattened at root (e.g. {"q1": "val", "q2": "val"})
        raw_answers = {
            k: v for k, v in payload.items()
            if k not in ("scenario_id", "resident_id", "schema_version", "rationale", "other_text")
        }

    # 3. Validate against each question in the scenario
    parsed_answers: dict[str, Any] = {}
    parsed_other: dict[str, str] = {}
    refused = False

    for question in scenario.questions:
        qid = question.id
        allowed_option_ids = {opt.id for opt in question.options}

        if qid not in raw_answers:
            errors.append(f"Missing answer for question '{qid}'")
            continue

        chosen_val = raw_answers[qid]
        if chosen_val is None:
            errors.append(f"Answer for question '{qid}' is null")
            continue

        if question.type == "multiple_choice":
            if isinstance(chosen_val, (list, tuple, set)):
                items = [str(x).strip() for x in chosen_val]
            elif isinstance(chosen_val, str) and chosen_val.strip().lower() in ("refused", "refuse", "declined"):
                parsed_answers[qid] = ["refused"]
                refused = True
                continue
            elif isinstance(chosen_val, str):
                items = [chosen_val.strip()]
            else:
                errors.append(f"Answer for multiple_choice question '{qid}' must be a list of option IDs")
                continue

            if not items:
                errors.append(f"Answer for multiple_choice question '{qid}' cannot be empty")
                continue

            invalid_items = [it for it in items if it not in allowed_option_ids]
            if invalid_items:
                errors.append(
                    f"Invalid choice(s) {invalid_items} for question '{qid}'. "
                    f"Must be a subset of: {sorted(allowed_option_ids)}"
                )
                continue

            unique_items = list(dict.fromkeys(items))
            parsed_answers[qid] = unique_items

            if "other" in unique_items and question.allow_other:
                other_dict = payload.get("other_text") or {}
                if isinstance(other_dict, dict) and qid in other_dict:
                    parsed_other[qid] = str(other_dict[qid])
                elif "other" in payload and isinstance(payload["other"], str):
                    parsed_other[qid] = payload["other"]

        else:
            # Single choice
            if isinstance(chosen_val, (list, tuple, set)):
                errors.append(
                    f"Question '{qid}' is single_choice, but received a list of choices: {chosen_val}"
                )
                continue

            chosen_str = str(chosen_val).strip()

            # Handle refusal token
            if chosen_str.lower() in ("refused", "refuse", "declined"):
                parsed_answers[qid] = "refused"
                refused = True
                continue

            if chosen_str not in allowed_option_ids:
                errors.append(
                    f"Invalid choice '{chosen_str}' for question '{qid}'. "
                    f"Must be one of: {sorted(allowed_option_ids)}"
                )
                continue

            parsed_answers[qid] = chosen_str

            # Check 'other' text if question allows other
            if chosen_str == "other" and question.allow_other:
                other_dict = payload.get("other_text") or {}
                if isinstance(other_dict, dict) and qid in other_dict:
                    parsed_other[qid] = str(other_dict[qid])
                elif "other" in payload and isinstance(payload["other"], str):
                    parsed_other[qid] = payload["other"]

    # 4. Check for unrequested rogue question IDs
    scenario_qids = {q.id for q in scenario.questions}
    for qid in raw_answers:
        if qid not in scenario_qids:
            errors.append(f"Response contains unexpected question ID '{qid}' not defined in scenario")

    # 5. Extract rationale
    rationale = payload.get("rationale")
    rationale_str = str(rationale).strip() if rationale is not None else None

    # Status resolution
    status = ResponseStatus.VALID
    if errors:
        status = ResponseStatus.INVALID
    elif refused:
        status = ResponseStatus.REFUSED

    return AgentResponseEnvelope(
        scenario_id=extracted_scenario_id,
        resident_id=extracted_res_id,
        schema_version=str(payload.get("schema_version") or RESPONSE_SCHEMA_VERSION),
        status=status,
        answers=parsed_answers,
        other_text=parsed_other,
        rationale=rationale_str,
        errors=errors,
        raw_payload=payload,
    )
