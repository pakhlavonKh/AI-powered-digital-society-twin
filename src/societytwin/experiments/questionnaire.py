"""Parse the questionnaire Markdown snapshot that MatrAIx wrote into each trial folder.

Labels are only ever taken from such a snapshot. When a value is not listed, the raw code is shown.
"""

from __future__ import annotations

import re

_SECTION = re.compile(r"^## (\S+)\s*$")
_PROMPT = re.compile(r"^Prompt:\s*(.+)$")
_TYPE = re.compile(r"^- Type: `([^`]+)`")
_REQUIRED = re.compile(r"^- Required: `([^`]+)`")
_CONSTRUCT = re.compile(r"^- Construct: `([^`]+)`")
_SCALE = re.compile(r"^- Scale: `(-?\d+)`-`(-?\d+)`")
_CHOICE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|\s*$")


def parse_questionnaire(markdown: str) -> list[dict]:
    questions: list[dict] = []
    current: dict | None = None
    for line in markdown.splitlines():
        heading = _SECTION.match(line)
        if heading:
            if heading.group(1).lower() in {"answer", "answer_envelope"}:
                current = None
                continue
            current = {"id": heading.group(1), "prompt": None, "type": None, "construct_id": None, "required": None,
                       "scale": None, "choices": []}
            questions.append(current)
            continue
        if current is None:
            continue
        if (m := _PROMPT.match(line)):
            current["prompt"] = m.group(1).strip()
        elif (m := _TYPE.match(line)):
            current["type"] = m.group(1)
        elif (m := _CONSTRUCT.match(line)):
            current["construct_id"] = m.group(1)
        elif (m := _REQUIRED.match(line)):
            current["required"] = m.group(1) == "true"
        elif (m := _SCALE.match(line)):
            current["scale"] = {"min": int(m.group(1)), "max": int(m.group(2))}
        elif (m := _CHOICE.match(line)):
            if m.group(1) != "choice_id":
                current["choices"].append({"id": m.group(1), "label": m.group(2)})
    # A heading without a prompt is not a question (for example "## Answer envelope").
    return [q for q in questions if q["prompt"] is not None]


def label_for(question: dict | None, value) -> tuple[str | None, str]:
    """Return (label, label_source). The source is 'questionnaire_snapshot' or 'code_only'."""
    if question is None:
        return None, "code_only"
    if isinstance(value, str):
        for choice in question.get("choices", []):
            if choice["id"] == value:
                return choice["label"], "questionnaire_snapshot"
    if isinstance(value, int) and not isinstance(value, bool) and question.get("scale"):
        scale = question["scale"]
        return f"{value} on a {scale['min']}–{scale['max']} scale", "questionnaire_snapshot"
    return None, "code_only"
