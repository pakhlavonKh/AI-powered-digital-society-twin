"""Scenario Compiler: Transforms natural language policy prompts into validated ScenarioConfig models.

Provides a unified interface accepting conversational prompt strings (e.g.
"What would happen in Ankara if transit fares increase by 30%?") and compiling
them into reproducible, structured SocietyTwin policy scenarios with target
population filters, calibrated parameters, and balanced multi-choice survey questions.

Works both with live LLM extraction (when provider API keys are configured)
and deterministic heuristic synthesis (for offline, zero-cost, and test environments).
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any

try:
    from societytwin.national.geography import PROVINCES, _BY_NAME, name_key
    from .schema import (
        PolicyConfig,
        PolicyParameters,
        PopulationFilterConfig,
        QuestionConfig,
        QuestionOption,
        ScenarioConfig,
        ScenarioLocation,
        ScenarioMetadata,
    )
except ImportError:
    from societytwin.national.geography import PROVINCES, _BY_NAME, name_key  # type: ignore
    from scenarios.schema import (  # type: ignore
        PolicyConfig,
        PolicyParameters,
        PopulationFilterConfig,
        QuestionConfig,
        QuestionOption,
        ScenarioConfig,
        ScenarioLocation,
        ScenarioMetadata,
    )

logger = logging.getLogger(__name__)

DEFAULT_PROVINCE_CODE = "06"
DEFAULT_PROVINCE_NAME = "Ankara"
DEFAULT_NUTS2 = "TR51"


def extract_location(text: str) -> tuple[str, str, str]:
    """Extract (province_code, province_name, nuts2_code) from text.

    Scans text against Türkiye's 81 provinces using Turkish-aware diacritic normalisation.
    Defaults to Ankara ('06', 'Ankara', 'TR51') if no specific province is named.
    """
    words = re.findall(r"\b[A-Za-zÇĞİÖŞÜçğıöşüâîû]+\b", text)

    # Check multi-word province names or single tokens
    for w in words:
        key = name_key(w)
        if key in _BY_NAME:
            prov = _BY_NAME[key]
            return prov.code, prov.name, prov.nuts2

    return DEFAULT_PROVINCE_CODE, DEFAULT_PROVINCE_NAME, DEFAULT_NUTS2


def extract_percentages_and_numbers(text: str) -> tuple[float | None, float | None, float | None]:
    """Extract (increase_percentage, baseline_fare, new_fare) from prompt text."""
    pct: float | None = None
    baseline: float | None = None
    new_val: float | None = None

    # Matches "30%", "+25%", "20 percent", "%20"
    pct_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", text) or re.search(r"%\s*([+-]?\d+(?:\.\d+)?)", text)
    if not pct_match:
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|yüzde)", text, flags=re.IGNORECASE)
    if pct_match:
        raw_num = pct_match.group(1)
        try:
            pct = float(raw_num)
            if not raw_num.startswith(("+", "-")) and _has_keyword(
                text,
                ("discount", "reduction", "decrease", "cut", "drop", "lower", "indirim", "ucuz", "düşüş", "azalma"),
            ):
                pct = -abs(pct)
        except ValueError:
            pass

    # Matches numbers with currency units, e.g. "from 20 TL to 25 TL" or "20 to 25 lira"
    from_to = re.search(
        r"(?:from|den|dan)\s*(\d+(?:\.\d+)?)\s*(?:tl|lira)?\s*(?:to|ye|ya|e|a)\s*(\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if from_to:
        try:
            baseline = float(from_to.group(1))
            new_val = float(from_to.group(2))
            if baseline > 0 and pct is None:
                pct = round(((new_val - baseline) / baseline) * 100.0, 1)
        except ValueError:
            pass
    else:
        # Standalone baseline fare, e.g. "from 21 TL", "currently 21 TL", "baseline 21 TL", "21 TL'den"
        base_match = (
            re.search(
                r"\b(?:from|currently|baseline(?:\s+of)?|at|mevcut)\s*(\d+(?:\.\d+)?)\s*(?:tl|lira|try|₺)\b",
                text,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"(\d+(?:\.\d+)?)\s*(?:tl|lira|try|₺)\s*(?:'?den|'?dan)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        if base_match:
            try:
                baseline = float(base_match.group(1))
            except ValueError:
                pass

        # Standalone target/new fare, e.g. "to 27.3 TL", "27.3 TL'ye"
        new_match = (
            re.search(
                r"\bto\s*(\d+(?:\.\d+)?)\s*(?:tl|lira|try|₺)\b",
                text,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"(\d+(?:\.\d+)?)\s*(?:tl|lira|try|₺)\s*(?:'?ye|'?ya|'?e|'?a)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        if new_match:
            try:
                new_val = float(new_match.group(1))
            except ValueError:
                pass

        if baseline is not None and new_val is not None and pct is None and baseline > 0:
            pct = round(((new_val - baseline) / baseline) * 100.0, 1)
        elif baseline is not None and pct is not None and new_val is None:
            new_val = round(baseline * (1.0 + pct / 100.0), 2)
        elif new_val is not None and pct is not None and baseline is None and (1.0 + pct / 100.0) > 0:
            baseline = round(new_val / (1.0 + pct / 100.0), 2)

    return pct, baseline, new_val


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """Check if any keyword appears in text as a whole word or phrase."""
    lower = text.lower()
    tokens = set(re.findall(r"\b[a-za-zçğıöşüâîû0-9+-]+\b", lower))
    for kw in keywords:
        if " " in kw:
            if kw in lower:
                return True
        elif kw in tokens:
            return True
    return False


def detect_domain_and_category(text: str) -> tuple[str, str]:
    """Classify prompt into policy category and intervention type."""
    if _has_keyword(text, ("transit", "bus", "metro", "fare", "bilet", "otobüs", "dolmuş", "ego", "iett", "transport", "ulaşım")):
        p_type = "fare_increase" if _has_keyword(text, ("increase", "zam", "hike", "raise", "artış")) else "fare_adjustment"
        return "transportation", p_type

    if _has_keyword(text, ("rent", "housing", "kira", "konut", "ev", "barınma", "apartment", "deprem", "earthquake")):
        p_type = "subsidy" if _has_keyword(text, ("subsidy", "destek", "yardım", "relief")) else "rent_regulation"
        return "housing", p_type

    if _has_keyword(text, ("electricity", "elektrik", "water", "su", "gas", "doğalgaz", "energy", "enerji", "tariff")):
        return "energy", "tariff_adjustment"

    if _has_keyword(text, ("wage", "salary", "maaş", "ücret", "income", "gelir", "tax", "vergi", "pension", "emekli")):
        return "economic", "income_support"

    if _has_keyword(text, ("student", "öğrenci", "school", "okul", "university", "üniversite", "burs", "scholarship")):
        return "education", "student_support"

    return "public_policy", "policy_intervention"


def detect_target_population(text: str, province_code: str) -> PopulationFilterConfig:
    """Infer demographic filters from prompt keywords."""
    lower = text.lower()
    min_age = 18
    max_age: int | None = None

    if any(k in lower for k in ("elderly", "senior", "pensioner", "emekli", "yaşlı", "65+")):
        min_age = 65
    elif any(k in lower for k in ("student", "öğrenci", "university student")):
        min_age = 18
        max_age = 26
    elif any(k in lower for k in ("youth", "genç", "young adults")):
        min_age = 18
        max_age = 30

    return PopulationFilterConfig(
        minimum_age=min_age,
        maximum_age=max_age,
        province_codes=[province_code],
        adult_only=True,
        required_attributes=["age", "province_code", "sex"],
    )


def synthesize_questions(
    prompt: str,
    domain: str,
    province_name: str,
    pct: float | None,
) -> list[QuestionConfig]:
    """Generate balanced, relevant survey questions and options based on policy context."""
    if domain == "transportation":
        action = "decrease" if (pct is not None and pct < 0) else "increase"
        pct_text = f" by {abs(pct):.0f}%" if pct is not None else ""
        return [
            QuestionConfig(
                id="q1_usage_change",
                text=f"If public transit fares in {province_name} {action}{pct_text}, how would your daily travel habits most likely change?",
                type="single_choice",
                options=[
                    QuestionOption(id="maintain_usage", label="Continue using public transit as before (no significant change)"),
                    QuestionOption(id="reduce_optional_trips", label="Reduce optional or leisure trips (shopping, social outings)"),
                    QuestionOption(id="switch_to_walking", label="Walk more for short or intermediate distances"),
                    QuestionOption(id="switch_to_private_car_or_taxi", label="Use a private car, carpool, or taxi more frequently"),
                    QuestionOption(id="unsure", label="Unsure / Depends on weather and schedule"),
                ],
                allow_other=False,
                ask_rationale=True,
            ),
            QuestionConfig(
                id="q2_policy_support",
                text=f"Would you support or oppose this municipal transit tariff adjustment in {province_name}?",
                type="single_choice",
                options=[
                    QuestionOption(id="strongly_support", label="Strongly support"),
                    QuestionOption(id="somewhat_support", label="Somewhat support"),
                    QuestionOption(id="neutral", label="Neutral / Indifferent"),
                    QuestionOption(id="somewhat_oppose", label="Somewhat oppose"),
                    QuestionOption(id="strongly_oppose", label="Strongly oppose"),
                ],
                allow_other=False,
                ask_rationale=True,
            ),
        ]

    if domain == "housing":
        return [
            QuestionConfig(
                id="q1_housing_impact",
                text=f"How would this municipal housing policy in {province_name} impact your household budget?",
                type="single_choice",
                options=[
                    QuestionOption(id="major_relief", label="Provides major financial relief for housing costs"),
                    QuestionOption(id="moderate_relief", label="Provides moderate assistance with monthly bills"),
                    QuestionOption(id="minimal_impact", label="Minimal or negligible impact on our household"),
                    QuestionOption(id="not_applicable", label="Does not apply to our housing situation"),
                ],
                allow_other=False,
                ask_rationale=True,
            ),
            QuestionConfig(
                id="q2_policy_support",
                text=f"Do you support implementing this housing measure in {province_name}?",
                type="single_choice",
                options=[
                    QuestionOption(id="strongly_support", label="Strongly support"),
                    QuestionOption(id="somewhat_support", label="Somewhat support"),
                    QuestionOption(id="neutral", label="Neutral"),
                    QuestionOption(id="somewhat_oppose", label="Somewhat oppose"),
                    QuestionOption(id="strongly_oppose", label="Strongly oppose"),
                ],
                allow_other=False,
                ask_rationale=True,
            ),
        ]

    # Default / general public policy
    clean_prompt = prompt.strip().rstrip("?.")
    return [
        QuestionConfig(
            id="q1_behavioral_response",
            text=f"Regarding the policy situation: '{clean_prompt}', how would you personally respond?",
            type="single_choice",
            options=[
                QuestionOption(id="adapt_positively", label="Adapt positively and make use of the policy change"),
                QuestionOption(id="no_change", label="Maintain current routine without change"),
                QuestionOption(id="financially_strained", label="Feel financially strained or inconvenienced"),
                QuestionOption(id="seek_alternatives", label="Actively look for alternative solutions or services"),
            ],
            allow_other=False,
            ask_rationale=True,
        ),
        QuestionConfig(
            id="q2_policy_support",
            text=f"Overall, do you support or oppose this policy in {province_name}?",
            type="single_choice",
            options=[
                QuestionOption(id="strongly_support", label="Strongly support"),
                QuestionOption(id="somewhat_support", label="Somewhat support"),
                QuestionOption(id="neutral", label="Neutral / Undecided"),
                QuestionOption(id="somewhat_oppose", label="Somewhat oppose"),
                QuestionOption(id="strongly_oppose", label="Strongly oppose"),
            ],
            allow_other=False,
            ask_rationale=True,
        ),
    ]


def compile_scenario_from_prompt_heuristic(prompt: str) -> ScenarioConfig:
    """Deterministic, zero-cost compiler producing a fully validated ScenarioConfig."""
    prov_code, prov_name, nuts2 = extract_location(prompt)
    pct, baseline, new_val = extract_percentages_and_numbers(prompt)
    category, policy_type = detect_domain_and_category(prompt)
    population_filter = detect_target_population(prompt, prov_code)
    questions = synthesize_questions(prompt, category, prov_name, pct)

    # Unique slug-based scenario_id
    raw_slug = re.sub(r"[^a-z0-9]+", "_", f"{prov_name}_{category}".lower()).strip("_")
    short_uuid = uuid.uuid4().hex[:6]
    scenario_id = f"prompt_{raw_slug}_{short_uuid}"[:63]

    # Format title and description
    pct_str = f" (+{pct:.0f}%)" if pct and pct > 0 else (f" ({pct:.0f}%)" if pct else "")
    title = f"{prov_name} {category.capitalize()} Policy{pct_str}"[:160]
    description = (
        f"A simulation scenario generated from user prompt: '{prompt.strip()}'. "
        f"Evaluates the demographic and behavioral reactions of synthetic residents in {prov_name}."
    )

    parameters = PolicyParameters(
        baseline_fare=baseline,
        new_fare=new_val,
        increase_percentage=pct,
        currency="TL",
        policy_summary=prompt.strip(),
    )

    return ScenarioConfig(
        scenario_id=scenario_id,
        version="1.0.0",
        name=title,
        description=description,
        location=ScenarioLocation(
            province_code=prov_code,
            province_name=prov_name,
            nuts2_code=nuts2,
        ),
        metadata=ScenarioMetadata(
            hypothetical=True,
            source_note="Compiled automatically from natural language prompt input.",
            author="SocietyTwin Prompt Compiler",
        ),
        policy=PolicyConfig(
            category=category,
            type=policy_type,
            parameters=parameters,
        ),
        target_population=population_filter,
        questions=questions,
    )


def compile_scenario_with_llm(prompt: str, model: str | None = None) -> ScenarioConfig | None:
    """Compile scenario using an LLM provider if credentials are available and live execution is enabled."""
    if os.environ.get("SOCIETYTWIN_ENABLE_LIVE_SCENARIO_LLM", "").lower() not in ("1", "true", "yes"):
        return None

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=api_key)
        system_instruction = (
            "You are an expert public policy analyst and survey methodologist for Türkiye. "
            "Convert the user's policy query into a strictly valid ScenarioConfig JSON object. "
            "Rules:\n"
            "- scenario_id must match ^[a-z][a-z0-9_]{1,63}$\n"
            "- location province_code must be a 2-digit string (e.g. '06' for Ankara, '34' for Istanbul)\n"
            "- policy must include category, type, and parameters\n"
            "- target_population must include minimum_age, adult_only, province_codes\n"
            "- questions must have at least 1 single_choice question with 2 to 5 options having unique alphanumeric IDs and human labels.\n"
            "- Return ONLY valid JSON."
        )

        model_name = model or "gpt-4o-mini"
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if not content:
            return None

        data = json.loads(content)
        return ScenarioConfig.model_validate(data)
    except Exception as exc:
        logger.warning("LLM scenario compilation encountered an issue, falling back to heuristic: %s", exc)
        return None


def compile_scenario_from_prompt(
    prompt: str,
    model: str | None = None,
    force_heuristic: bool = False,
) -> ScenarioConfig:
    """Main entrypoint: compiles a natural language prompt into a validated ScenarioConfig.

    Attempts LLM synthesis if configured and not explicitly forced to heuristic mode;
    otherwise falls back to deterministic heuristic synthesis.

    Args:
        prompt: Natural language policy prompt.
        model: Optional LLM model identifier.
        force_heuristic: If True, bypasses LLM calls and uses deterministic parsing.

    Returns:
        Validated ScenarioConfig ready for catalog saving or experiment execution.
    """
    clean_prompt = (prompt or "").strip()
    if len(clean_prompt) < 3:
        raise ValueError("Prompt must be at least 3 characters long.")

    if not force_heuristic:
        compiled = compile_scenario_with_llm(clean_prompt, model=model)
        if compiled is not None:
            return compiled

    return compile_scenario_from_prompt_heuristic(clean_prompt)
