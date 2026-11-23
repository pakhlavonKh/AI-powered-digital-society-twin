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
        UniversityPolicyIntervention,
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
        UniversityPolicyIntervention,
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

        if baseline is not None and baseline <= 0:
            baseline = None
        if new_val is not None and new_val <= 0:
            new_val = None

        if baseline is not None and new_val is not None and pct is None and baseline > 0:
            pct = round(((new_val - baseline) / baseline) * 100.0, 1)
        elif baseline is not None and pct is not None and new_val is None and (1.0 + pct / 100.0) > 0:
            new_val = round(baseline * (1.0 + pct / 100.0), 2)
        elif new_val is not None and pct is not None and baseline is None and (1.0 + pct / 100.0) > 0:
            baseline = round(new_val / (1.0 + pct / 100.0), 2)

    if pct is not None:
        pct = max(-99.9, min(1000.0, pct))
    if baseline is not None and baseline <= 0:
        baseline = None
    if new_val is not None and new_val <= 0:
        new_val = None

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

    if _has_keyword(
        text,
        (
            "ösym", "osym", "yks", "tyt", "ayt", "ydt", "yerleştirme", "tercih",
            "kontenjan", "taban puan", "başarı sırası", "baraj", "placement",
            "burslu", "kırık obp", "seat quota", "admission quota",
        ),
    ):
        if _has_keyword(text, ("kontenjan", "quota", "capacity", "seat", "seats", "kapasite")):
            return "university_placement", "quota_adjustment"
        if _has_keyword(text, ("baraj", "rank", "sıra", "başarı sırası", "threshold")):
            return "university_placement", "rank_threshold_adjustment"
        return "university_placement", "placement_simulation"

    if _has_keyword(
        text,
        (
            "tuition", "harç", "öğrenim ücreti", "need-based aid", "financial aid",
            "burs bütçesi", "installment", "taksit", "attendance", "devamsızlık",
            "course seat", "course seats", "grading", "gpa", "stop-out",
        ),
    ):
        if _has_keyword(text, ("tuition", "harç", "öğrenim ücreti")):
            return "university_policy", "tuition_adjustment"
        if _has_keyword(text, ("aid", "burs", "scholarship", "grant")):
            return "university_policy", "financial_aid"
        if _has_keyword(text, ("installment", "taksit")):
            return "university_policy", "installment_plan"
        if _has_keyword(text, ("attendance", "devamsızlık", "grading", "gpa")):
            return "university_policy", "academic_rule_change"
        return "university_policy", "capacity_adjustment"

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


def _extract_signed_pct_near(text: str, anchors: tuple[str, ...]) -> float | None:
    """Extract a percentage near one of the given domain anchors."""
    anchor_pat = "|".join(re.escape(a) for a in anchors)
    patterns = (
        rf"(?:{anchor_pat})\b[^.;,\n]{{0,40}}?([+-]?\d+(?:\.\d+)?)\s*%",
        rf"([+-]?\d+(?:\.\d+)?)\s*%\s*(?:[a-zçğıöşüâîû]+\s+){{0,3}}(?:{anchor_pat})\b",
    )
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            val = float(m.group(1))
            window = text[max(0, m.start() - 25) : min(len(text), m.end() + 25)].lower()
            if not m.group(1).startswith(("+", "-")) and any(
                w in window for w in ("cut", "drop", "reduce", "reduction", "decrease", "discount", "indirim", "azalt", "düş")
            ):
                return -abs(val)
            return val
    return None


def _parse_rank_number(raw: str, unit: str | None) -> int:
    clean = raw.replace(",", "").replace(".", "").replace("_", "")
    val = int(clean)
    if unit and unit.lower() in ("k", "bin"):
        val *= 1000
    return val


def extract_university_parameters(text: str, category: str, global_pct: float | None) -> UniversityPolicyIntervention:
    """Extract typed economic, capacity, and placement rule levers from natural language."""
    lower = text.lower()
    tuition_pct = _extract_signed_pct_near(text, ("tuition", "harç", "öğrenim ücreti", "fee", "fees"))
    aid_pct = _extract_signed_pct_near(text, ("aid", "need-based aid", "financial aid", "burs", "scholarship", "grant"))
    cap_pct = _extract_signed_pct_near(text, ("quota", "quotas", "kontenjan", "seat", "seats", "capacity", "kapasite"))

    if tuition_pct is None and global_pct is not None and _has_keyword(text, ("tuition", "harç", "öğrenim ücreti")):
        tuition_pct = global_pct
    if aid_pct is None and global_pct is not None and _has_keyword(text, ("aid", "burs", "scholarship", "grant")) and tuition_pct is None:
        aid_pct = global_pct
    if cap_pct is None and global_pct is not None and _has_keyword(text, ("quota", "kontenjan", "seat", "seats", "capacity")):
        cap_pct = global_pct

    installment_count: int | None = None
    inst_match = re.search(r"(\d+)\s*(?:installments?|taksit)", lower)
    if inst_match:
        installment_count = max(1, min(24, int(inst_match.group(1))))
    elif _has_keyword(text, ("installment", "installments", "taksit")):
        installment_count = 4

    attendance_min: float | None = None
    att_to = re.search(r"(?:attendance|devamsızlık)[^.\n]{0,40}?(?:to|→|->)\s*(\d+(?:\.\d+)?)\s*%", lower)
    if att_to:
        attendance_min = max(0.0, min(100.0, float(att_to.group(1))))
    else:
        att_single = re.search(r"(?:attendance|devamsızlık)[^.\n]{0,30}?(\d+(?:\.\d+)?)\s*%", lower)
        if att_single:
            attendance_min = max(0.0, min(100.0, float(att_single.group(1))))

    rank_overrides: dict[str, int] = {}
    baraj_aliases = {
        "medicine": ("medicine", "tıp"),
        "dentistry": ("dentistry", "diş"),
        "pharmacy": ("pharmacy", "eczacılık"),
        "law": ("law", "hukuk"),
        "engineering": ("engineering", "mühendislik"),
        "architecture": ("architecture", "mimarlık"),
        "teaching": ("teaching", "öğretmenlik"),
    }
    for group, aliases in baraj_aliases.items():
        alias_pat = "|".join(re.escape(a) for a in aliases)
        rank_pat = re.compile(
            rf"(?:{alias_pat})[^.;\n]{{0,50}}?(?:top|ilk|<=|threshold|baraj|rank|sıra|to)\s*(\d[\d,.]*)\s*(k|bin)?\b(?!\s*%)"
        )
        for m in rank_pat.finditer(lower):
            if _has_keyword(text, ("rank", "baraj", "sıra", "top", "ilk", "threshold")):
                val = _parse_rank_number(m.group(1), m.group(2))
                if val >= 100:
                    rank_overrides[group] = val
                    break

    apply_obp_penalty = any(p in lower for p in ("kırık obp", "prior placement penalty", "obp penalty"))

    affordability_mode = "none"
    if "utility rerank" in lower or "rerank" in lower or "re-rank" in lower:
        affordability_mode = "utility_rerank"
    elif (tuition_pct is not None or aid_pct is not None or installment_count is not None) and category == "university_placement":
        affordability_mode = "hard_exclude"
    elif "cannot afford" in lower or "affordability" in lower or "liquidity" in lower:
        affordability_mode = "hard_exclude"

    return UniversityPolicyIntervention(
        tuition_change_pct=tuition_pct,
        aid_budget_change_pct=aid_pct,
        capacity_change_pct=cap_pct,
        installment_count=installment_count,
        attendance_min_pct=attendance_min,
        rank_threshold_overrides=rank_overrides,
        apply_prior_placement_obp_penalty=apply_obp_penalty,
        affordability_filter_mode=affordability_mode,  # type: ignore[arg-type]
        rule_fidelity="hypothetical_simplified",
        osym_verified=False,
    )


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
    is_pure_text_prompt = _has_keyword(
        prompt,
        (
            "only text", "text only", "no options", "pure text", "open ended question",
            "sadece metin", "açık uçlu", "free text", "free-text", "open-ended",
            "open ended", "open response", "in your own words", "qualitative",
            "kendi cümlelerinizle",
        ),
    )
    def _safe_q_prompt(raw_text: str) -> str:
        escaped = raw_text.strip().rstrip("?.").replace("{", "{{").replace("}", "}}")
        return escaped[:1800]

    if is_pure_text_prompt:
        clean_prompt = _safe_q_prompt(prompt)
        return [
            QuestionConfig(
                id="q1_text_response",
                text=f"Regarding the policy situation: '{clean_prompt}', please provide your detailed thoughts and perspective in your own words."[:2000],
                type="free_text",
                options=[],
                ask_rationale=True,
            )
        ]
    if domain == "transportation":
        action = "decrease" if (pct is not None and pct < 0) else "increase"
        pct_text = f" by {abs(pct):.0f}%" if pct is not None else ""
        questions = [
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

    elif domain == "housing":
        questions = [
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

    elif domain == "university_placement":
        questions = [
            QuestionConfig(
                id="q1_placement_preference_response",
                text=f"Under this hypothetical university placement rule change in {province_name}, how would a candidate most likely adjust their preference strategy?",
                type="single_choice",
                options=[
                    QuestionOption(id="keep_preferences", label="Submit original ordered program preferences unchanged"),
                    QuestionOption(id="shift_to_scholarship_or_state", label="Prioritize state or full-scholarship programs to manage costs"),
                    QuestionOption(id="broaden_safety_choices", label="Add lower-cutoff safety programs across provinces"),
                    QuestionOption(id="defer_next_cycle", label="Wait for the next admission cycle if desired seats are unavailable"),
                ],
                allow_other=False,
                ask_rationale=True,
            ),
        ]

    elif domain == "university_policy":
        questions = [
            QuestionConfig(
                id="q1_enrollment_decision",
                text=f"Given this hypothetical university policy change in {province_name}, which feasible enrollment decision best fits the student profile?",
                type="single_choice",
                options=[
                    QuestionOption(id="enroll_full_load", label="Enroll full-time as planned"),
                    QuestionOption(id="enroll_reduced_load", label="Enroll with a reduced course load or installment plan"),
                    QuestionOption(id="transfer_lower_cost_program", label="Transfer to a lower-tuition or scholarship program"),
                    QuestionOption(id="pause_stop_out", label="Temporarily pause enrollment (stop-out)"),
                    QuestionOption(id="withdraw", label="Withdraw from the university program"),
                ],
                allow_other=False,
                ask_rationale=True,
            ),
        ]

    else:
        # Default / general public policy
        clean_prompt = _safe_q_prompt(prompt)
        questions = [
            QuestionConfig(
                id="q1_behavioral_response",
                text=f"Regarding the policy situation: '{clean_prompt}', how would you personally respond?"[:2000],
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

    has_text_request = _has_keyword(
        prompt,
        ("free text", "text answer", "open ended", "in your own words", "describe", "explain", "thoughts", "opinion", "feedback", "kendi cümlelerinizle", "yorum", "görüş")
    )
    if has_text_request:
        questions.append(
            QuestionConfig(
                id="q_qualitative_feedback",
                text=f"In your own words, what is your primary personal view, concern, or suggestion regarding this policy in {province_name}?",
                type="free_text",
                options=[],
                ask_rationale=False,
            )
        )
    return questions


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
    cat_label = category.replace("_", " ").title() if "_" in category else category.capitalize()
    title = f"{prov_name} {cat_label} Policy{pct_str}"[:160]
    raw_prompt_trimmed = prompt.strip()
    escaped_prompt = raw_prompt_trimmed.replace("{", "{{").replace("}", "}}")[:4700]
    description = (
        f"A simulation scenario generated from user prompt: '{escaped_prompt}'. "
        f"Evaluates the demographic and behavioral reactions of synthetic residents in {prov_name}."
    )[:5000]

    custom_details: dict[str, Any] = {}
    source_note = "Compiled automatically from natural language prompt input."
    if category in ("university_placement", "university_policy"):
        uni_intervention = extract_university_parameters(prompt, category, pct)
        sim_mode = "university_placement" if category == "university_placement" else "university_decision_hybrid"
        custom_details["simulation_mode"] = sim_mode
        custom_details["university_intervention"] = uni_intervention.model_dump(mode="json", exclude_none=True)
        source_note = (
            "Compiled automatically from natural language prompt input. "
            "Uses simplified/hypothetical university rules; does NOT reproduce official ÖSYM placement."
        )

    parameters = PolicyParameters(
        baseline_fare=baseline,
        new_fare=new_val,
        increase_percentage=pct,
        currency="TL",
        policy_summary=raw_prompt_trimmed[:2000],
        custom_details=custom_details,
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
            source_note=source_note,
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
