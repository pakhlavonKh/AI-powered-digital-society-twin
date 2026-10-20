"""Rendering utility transforming ScenarioConfig into standardized agent prompts."""

from __future__ import annotations

import json
from typing import Any

try:
    from .schema import ScenarioConfig
except ImportError:
    from scenarios.schema import ScenarioConfig  # type: ignore


def render_scenario_prompt(
    scenario: ScenarioConfig,
    persona_context: dict[str, Any],
) -> tuple[str, str]:
    """Render (system_prompt, user_prompt) pair for persona-conditioned LLM execution.

    Args:
        scenario: Validated ScenarioConfig.
        persona_context: Dictionary with demographic fields (e.g. age, sex, marital_status, province_name).

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)
    """
    # 1. System Prompt: Persona Conditioning
    # Ensure private generator metadata (seed, internal hash) is never exposed
    persona_id = persona_context.get("resident_id") or persona_context.get("synthetic_id") or "RESIDENT"
    age = persona_context.get("age", "Unknown")
    sex = persona_context.get("sex") or persona_context.get("gender") or "Unknown"
    marital = persona_context.get("marital_status", "Not specified")
    education = persona_context.get("education_level", "Not specified")
    province = persona_context.get("province_name") or scenario.location.province_name

    system_lines = [
        f"You are a synthetic resident representing a real-world demographic profile in Türkiye.",
        f"Profile Identifier: {persona_id}",
        f"Location: {province}, Türkiye",
        f"Age: {age}",
        f"Sex: {sex}",
        f"Marital Status: {marital}",
        f"Education Level: {education}",
        "",
        "Instructions:",
        "- Stay in character based on your personal and demographic context.",
        "- Do NOT assume or invent specific wealth, car ownership, or travel habits unless they directly follow from your profile.",
        "- Answer the following policy survey truthfully from your persona's perspective.",
    ]
    system_prompt = "\n".join(system_lines)

    # 2. User Prompt: Scenario Narrative, Policy Parameters, Questions & Response Schema
    user_lines = [
        f"### Policy Scenario: {scenario.name}",
        "",
        scenario.description.strip(),
        "",
        "#### Policy Parameters:",
    ]

    params = scenario.policy.parameters
    if params.baseline_fare is not None and params.new_fare is not None:
        user_lines.append(f"- Current Baseline Fare: {params.baseline_fare:.2f} {params.currency}")
        user_lines.append(f"- Proposed New Fare: {params.new_fare:.2f} {params.currency}")
    if params.increase_percentage is not None:
        user_lines.append(f"- Tariff Adjustment: +{params.increase_percentage:.1f}%")
    if params.subsidized_exemptions_note:
        user_lines.append(f"- Concessions & Subsidies: {params.subsidized_exemptions_note}")

    user_lines.append("")
    user_lines.append("#### Questions:")

    expected_answers_template: dict[str, str] = {}
    for q in scenario.questions:
        user_lines.append(f"\n[{q.id}] {q.text}")
        for opt in q.options:
            user_lines.append(f"  - {opt.id}: {opt.label}")
        expected_answers_template[q.id] = f"<one option id from [{', '.join(opt.id for opt in q.options)}]>"

    output_schema_example = {
        "scenario_id": scenario.scenario_id,
        "resident_id": persona_id,
        "answers": expected_answers_template,
        "rationale": "<brief 1-2 sentence explanation of your decision>",
    }

    user_lines.append("")
    user_lines.append("Respond ONLY with a single valid JSON object strictly matching this format:")
    user_lines.append("```json")
    user_lines.append(json.dumps(output_schema_example, indent=2, ensure_ascii=False))
    user_lines.append("```")

    user_prompt = "\n".join(user_lines)
    return system_prompt, user_prompt
