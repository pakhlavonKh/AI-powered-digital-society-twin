"""Prompt-to-UniversityQuerySpec compiler (deterministic EN/TR parser + gated LLM fallback).

Translates free-form questions about a target university into a structured, reviewable
UniversityQuerySpec without ever inventing simulation results.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from .placement.models import ProgramOffering, catalog_fee_scale
from .schema import UniversityPolicyIntervention
from .university_query import (
    QueryAssumption,
    QuerySimulationMode,
    QueryVariantSpec,
    UniversityIntent,
    UniversityQuerySpec,
    UnresolvedEntity,
)

logger = logging.getLogger(__name__)

_DEFAULT_DIRECTIONAL_PCT = 20.0
_DEFAULT_RANK_SPOTS = 15

_DEICTIC_UNI_RE = re.compile(
    r"\b(?:this|our|the)\s+(?:uni|university|college|school|institution)\b"
    r"|\b(?:bu|bizim)\s+(?:üniversite|universite|okul)(?:nin|nın|ye|ya|de|da|yi|yı|müz|miz)?\b",
    flags=re.IGNORECASE,
)

_NEGATIVE_WORDS = (
    "drop", "drops", "dropped", "fall", "falls", "fell", "lower", "worse", "worsen",
    "worsens", "decline", "declines", "decrease", "decreases", "decreased", "cut",
    "cuts", "reduce", "reduces", "reduced", "reduction", "discount", "cheaper",
    "düş", "düşer", "düşerse", "azalt", "azalır", "azalırsa", "indirim", "ucuz", "gerile",
)
_POSITIVE_WORDS = (
    "increase", "increases", "increased", "raise", "raises", "raised", "hike",
    "higher", "rise", "rises", "rose", "improve", "improves", "improved", "better",
    "climb", "climbs", "boost", "expand", "expands", "expanded",
    "art", "artar", "artarsa", "zam", "yüksel", "yükselir", "yükselirse", "iyileş",
)
_DIRECTIONAL_PAIR_RE = re.compile(
    r"\b(?:higher\s+or\s+lower|lower\s+or\s+higher|rise\s+or\s+fall|increase\s+or\s+decrease|"
    r"up\s+or\s+down|improve\s+or\s+worsen|worsen\s+or\s+improve|either\s+way|"
    r"yükselir\s+(?:mi\s+)?(?:yoksa\s+)?düşer|artar\s+(?:mı\s+)?(?:yoksa\s+)?azalır)\b",
    flags=re.IGNORECASE,
)


def _norm(text: str) -> str:
    cleaned = re.sub(r"\([^)]*\)", " ", str(text))
    cleaned = cleaned.replace("İ", "i").replace("I", "i").lower()
    cleaned = cleaned.translate(str.maketrans("çğıöşüâîû", "cgiosuaiu"))
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _detect_language(prompt: str) -> str:
    lower = prompt.lower()
    tr_hits = sum(
        1
        for tok in (
            "üniversite", "universite", "harç", "burs", "kontenjan", "sıralama",
            "başvuru", "ücret", "artarsa", "düşerse", "öğrenci", "kaç", "nasıl",
            "tercih", "taban", "puan", "yüksel", "azal",
        )
        if tok in lower
    )
    has_tr_chars = any(c in lower for c in "çğıöşü")
    en_hits = sum(
        1
        for tok in (
            "how", "what", "would", "if", "tuition", "ranking", "apply", "students",
            "quota", "cutoff", "scholarship", "university", "uni", "retention",
        )
        if re.search(rf"\b{re.escape(tok)}\b", lower)
    )
    if (tr_hits > 0 or has_tr_chars) and en_hits >= 2:
        return "mixed"
    if tr_hits > 0 or has_tr_chars:
        return "tr"
    return "en"


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    lower = text.lower()
    tokens = set(re.findall(r"[a-zçğıöşüâîû0-9_%+-]+", lower))
    for w in words:
        if " " in w:
            if w in lower:
                return True
        elif w in tokens or any(tok.startswith(w) for tok in tokens if len(w) >= 4):
            return True
    return False


def _extract_signed_pct_near(text: str, anchors: tuple[str, ...]) -> float | None:
    anchor_pat = "|".join(re.escape(a) for a in anchors)
    patterns = (
        rf"(?:{anchor_pat})\b[^.;,\n]{{0,50}}?([+-]?\d+(?:\.\d+)?)\s*%",
        rf"([+-]?\d+(?:\.\d+)?)\s*%\s*(?:[a-zçğıöşüâîû]+\s+){{0,4}}(?:{anchor_pat})\b",
        rf"(?:{anchor_pat})\b[^.;,\n]{{0,40}}?%\s*([+-]?\d+(?:\.\d+)?)",
    )
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            val = float(m.group(1))
            window = text[max(0, m.start() - 30) : min(len(text), m.end() + 30)].lower()
            if not m.group(1).startswith(("+", "-")) and any(w in window for w in _NEGATIVE_WORDS):
                return -abs(val)
            return val
    return None


def _extract_multi_percentages(text: str) -> list[float]:
    matches = re.findall(r"([+-]?\d+(?:\.\d+)?)\s*%", text)
    if not matches:
        matches = re.findall(r"%\s*([+-]?\d+(?:\.\d+)?)", text)
    vals: list[float] = []
    for m in matches:
        v = float(m)
        if v not in vals:
            vals.append(v)
    return vals


def _resolve_entities(
    prompt: str,
    catalog: list[ProgramOffering],
    context_university_id: str | None,
) -> tuple[str | None, str | None, list[str], list[str], list[UnresolvedEntity]]:
    """Resolve target university, departments, and programs against active catalog."""
    unis: dict[str, str] = {}
    for p in catalog:
        unis.setdefault(p.university_id, p.university_name)

    unresolved: list[UnresolvedEntity] = []
    norm_prompt = _norm(prompt)

    # 1. Explicit university name / ID / common Turkish acronym match
    uni_aliases: dict[str, tuple[str, ...]] = {
        "ihsan dogramaci bilkent universitesi": ("bilkent",),
        "orta dogu teknik universitesi": ("odtu", "metu", "middle east technical"),
        "tobb ekonomi ve teknoloji universitesi": ("tobb etu", "tobb"),
        "ankara haci bayram veli universitesi": ("ahbvu", "ahbv", "haci bayram veli", "haci bayram"),
        "ankara yildirim beyazit universitesi": ("aybu", "yildirim beyazit"),
        "ankara sosyal bilimler universitesi": ("asbu", "sosyal bilimler"),
        "turk hava kurumu universitesi": ("thku", "thk"),
        "ted universitesi": ("tedu",),
        "ostim teknik universitesi": ("ostim",),
        "saglik bilimleri universitesi": ("sbu",),
    }
    uni_scores: list[tuple[int, str, str]] = []
    stop = {"university", "universitesi", "hypothetical", "institute", "college", "synthetic"}
    for uid, uname in sorted(unis.items()):
        if uid.lower() in prompt.lower():
            uni_scores.append((100, uid, uname))
            continue
        norm_name = _norm(uname)
        core_tokens = [t for t in norm_name.split() if t not in stop and len(t) >= 2]
        full_core = " ".join(core_tokens)
        aliases = uni_aliases.get(norm_name, ())
        matched_aliases = [
            a for a in aliases if re.search(rf"\b{re.escape(a)}\b", norm_prompt)
        ]
        if full_core and full_core in norm_prompt:
            uni_scores.append((len(full_core) + 20, uid, uname))
        elif matched_aliases:
            uni_scores.append((max(len(a) for a in matched_aliases) + 15, uid, uname))
        elif core_tokens:
            hits = sum(1 for t in core_tokens if re.search(rf"\b{re.escape(t)}\b", norm_prompt))
            if hits == len(core_tokens) or (hits >= 2 and hits >= len(core_tokens) - 1):
                uni_scores.append((hits * 10, uid, uname))

    focus_uid: str | None = None
    focus_uname: str | None = None
    if uni_scores:
        uni_scores.sort(key=lambda x: (-x[0], x[1]))
        top_score = uni_scores[0][0]
        tied = [u for u in uni_scores if u[0] == top_score]
        if len(tied) == 1:
            focus_uid, focus_uname = tied[0][1], tied[0][2]
        else:
            unresolved.append(
                UnresolvedEntity(
                    mention=prompt[:120],
                    entity_type="university",
                    reason="Multiple universities matched the prompt equally; select one target university.",
                    candidates=[{"id": u[1], "name": u[2]} for u in tied[:6]],
                )
            )

    # 2. Check deictic reference ("this uni") or unmatched explicit named university
    if focus_uid is None and not unresolved:
        if _DEICTIC_UNI_RE.search(prompt):
            if context_university_id and context_university_id in unis:
                focus_uid = context_university_id
                focus_uname = unis[context_university_id]
            else:
                unresolved.append(
                    UnresolvedEntity(
                        mention="this uni",
                        entity_type="university",
                        reason="Prompt refers to 'this uni' without naming one; select a Target University.",
                        candidates=[{"id": uid, "name": uname} for uid, uname in sorted(unis.items())[:8]],
                    )
                )
        else:
            named_m = re.search(
                r"\b([A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü0-9&\.-]{1,30}(?:\s+[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü0-9&\.-]{1,30}){0,3})\s+"
                r"(?:University|Üniversitesi|Institute)\b",
                prompt,
            )
            if named_m:
                unresolved.append(
                    UnresolvedEntity(
                        mention=named_m.group(0),
                        entity_type="university",
                        reason=f"University '{named_m.group(0)}' was not found in the active catalog.",
                        candidates=[{"id": uid, "name": uname} for uid, uname in sorted(unis.items())[:8]],
                    )
                )
            elif context_university_id and context_university_id in unis:
                focus_uid = context_university_id
                focus_uname = unis[context_university_id]

    # 3. Department / program matching
    dept_aliases: dict[str, tuple[str, ...]] = {
        "Computer Engineering": ("computer engineering", "bilgisayar mühendisliği", "bilgisayar"),
        "Medicine": ("medicine", "tıp", "tip"),
        "Law": ("law", "hukuk"),
        "Economics": ("economics", "işletme", "iktisat", "econ"),
        "Psychology": ("psychology", "psikoloji"),
        "Architecture": ("architecture", "mimarlık"),
        "Turkish Language Teaching": ("teaching", "öğretmenlik", "turkish language teaching"),
        "English Translation": ("translation", "mütercim", "tercümanlık"),
    }
    matched_depts: list[str] = []
    catalog_depts = {p.department_name for p in catalog}
    for dept in sorted(catalog_depts):
        base_dept = re.sub(r"\s*\([^)]*\)", "", dept).strip()
        aliases = dept_aliases.get(base_dept, (base_dept.lower(),))
        if any(re.search(rf"\b{re.escape(a)}\b", norm_prompt) for a in (_norm(x) for x in aliases) if a):
            if base_dept not in matched_depts:
                matched_depts.append(base_dept)

    matched_progs: list[str] = []
    for p in catalog:
        if p.program_id.lower() in prompt.lower():
            matched_progs.append(p.program_id)

    return focus_uid, focus_uname, matched_progs, matched_depts, unresolved


def _classify_intent(
    prompt: str,
    *,
    has_tuition: bool,
    has_ranking: bool,
    has_quota: bool,
    has_aid: bool,
    has_baraj: bool,
    is_directional_rank: bool,
    multi_pcts: list[float],
) -> tuple[UniversityIntent, QuerySimulationMode]:
    lower = prompt.lower()
    asks_retention = _has_any(
        lower,
        ("retention", "dropout", "drop out", "withdraw", "stop-out", "stop out", "semester", "semesters", "bırakma", "devam"),
    )
    asks_apply = _has_any(
        lower,
        ("apply", "applies", "applicant", "applicants", "application", "applications", "demand", "first choice", "1st choice", "başvuru", "tercih"),
    )

    sim_mode: QuerySimulationMode = "placement"
    if asks_retention and asks_apply:
        sim_mode = "both"
    elif asks_retention:
        sim_mode = "retention"

    if _has_any(lower, ("revenue", "break-even", "breakeven", "revenue-maximizing", "maximize revenue", "net revenue", "gelir")):
        return "revenue_tradeoff", sim_mode
    if asks_retention and not asks_apply and not has_ranking:
        return "retention_impact", sim_mode
    if _has_any(lower, ("where do", "where would", "switch to", "rival", "competitor", "other uni", "nereye gider", "rakip")):
        return "competitor_flow", sim_mode
    if _has_any(lower, ("afford", "priced out", "equity", "low-income", "low income", "income band", "composition", "gelir grubu", "kimler")):
        return "affordability_equity", sim_mode

    active_levers = sum(bool(x) for x in (has_tuition, has_ranking, has_quota, has_aid, has_baraj))
    if active_levers >= 2:
        return "composite", sim_mode
    if len(multi_pcts) >= 2 and _has_any(lower, ("compare", "vs", "versus", "sweep", "sensitivity", "karşılaştır")):
        return "multi_scenario_compare", sim_mode
    if has_ranking or is_directional_rank:
        return "ranking_sensitivity", sim_mode
    if has_aid or _has_any(lower, ("burslu", "scholarship", "burs", "indirimli", "free tuition")):
        return "scholarship_aid", sim_mode
    if _has_any(lower, ("fill rate", "unfilled", "empty seats", "will programs fill", "will seats fill", "doluluk", "boş kontenjan")):
        return "placement_fill", sim_mode
    if _has_any(lower, ("cutoff", "cutoffs", "taban puan", "taban", "score threshold")):
        return "cutoff_impact", sim_mode
    if has_quota and not asks_apply:
        return "quota_capacity", sim_mode
    if asks_apply or has_tuition:
        return "application_demand", sim_mode
    if has_quota:
        return "quota_capacity", sim_mode
    if asks_retention:
        return "retention_impact", sim_mode
    return "application_demand", sim_mode


def _detect_out_of_scope(prompt: str, catalog: list[ProgramOffering]) -> list[str]:
    lower = prompt.lower()
    reasons: list[str] = []
    unsupported = (
        ("professor salary", "faculty salary", "instructor pay", "maaş", "akademisyen maaşı"),
        ("dormitory", "dorm", "yurt", "housing capacity", "cafeteria", "yemekhane", "parking"),
        ("erasmus", "exchange program", "international ranking qs", "research grant"),
    )
    for kws in unsupported:
        if any(k in lower for k in kws):
            reasons.append(f"Mentioned topic ({kws[0]}) has no simulation mechanism in SocietyTwin.")

    has_uni_signal = _has_any(
        lower,
        (
            "uni", "university", "üniversite", "tuition", "harç", "ücret", "ranking", "sıralama",
            "apply", "applicant", "application", "başvuru", "quota", "kontenjan", "seat", "seats",
            "scholarship", "burs", "cutoff", "taban", "placement", "yerleştirme", "retention",
            "dropout", "semester", "student", "öğrenci", "revenue", "gelir", "baraj",
        ),
    ) or any(p.program_id.lower() in lower for p in catalog)
    if not has_uni_signal:
        reasons.append("Prompt does not reference university admissions, tuition, ranking, capacity, or retention.")
    return reasons


def _extract_subgroups(prompt: str) -> list[str]:
    lower = prompt.lower()
    dims: list[str] = []
    checks = (
        ("income_band", ("income", "afford", "rich", "poor", "gelir")),
        ("province_code", ("province", "city", "local", "out-of-province", "şehir", "il")),
        ("sex", ("sex", "gender", "female", "male", "kadın", "erkek")),
        ("score_type_used", ("score type", "say", "ea", "söz", "dil", "tyt", "puan türü")),
        ("scholarship_tier", ("burslu", "scholarship", "tier", "ücretli", "indirimli", "burs")),
    )
    for dim, kws in checks:
        if _has_any(lower, kws):
            dims.append(dim)
    return dims or ["income_band", "scholarship_tier", "province_code"]


def compile_university_query_heuristic(
    prompt: str,
    *,
    catalog: list[ProgramOffering],
    context_university_id: str | None = None,
    snapshot_id: str | None = None,
    admission_year: int | None = None,
    cohort_size: int = 200,
    seed: int = 42,
) -> UniversityQuerySpec:
    """Deterministic EN/TR parser turning a university question into a UniversityQuerySpec."""
    clean = (prompt or "").strip()
    if len(clean) < 3:
        raise ValueError("Prompt must be at least 3 characters long.")

    lower = clean.lower()
    lang = _detect_language(clean)
    focus_uid, focus_uname, focus_progs, focus_depts, unresolved = _resolve_entities(
        clean, catalog, context_university_id
    )
    out_of_scope = _detect_out_of_scope(clean, catalog)
    assumptions: list[QueryAssumption] = []

    # Year override
    year_m = re.search(r"\b(2019|202[0-9])\b", clean)
    eff_year = int(year_m.group(1)) if year_m else admission_year

    # Tuition extraction
    tuition_pct = _extract_signed_pct_near(
        clean, ("tuition", "fee", "fees", "harç", "öğrenim ücreti", "ücret")
    )
    if tuition_pct is None and _has_any(lower, ("free tuition", "zero tuition", "ücretsiz", "tuition free")):
        tuition_pct = -100.0
    if tuition_pct is None:
        tl_m = re.search(
            r"(?:tuition|fee|fees|harç|ücret)[^.;\n]{0,40}?(?:by|of)?\s*([+-]?\d[\d,\.]*)\s*(?:tl|try|₺)",
            clean,
            flags=re.IGNORECASE,
        )
        if tl_m:
            raw_amt = float(tl_m.group(1).replace(",", ""))
            if any(w in lower for w in _NEGATIVE_WORDS):
                raw_amt = -abs(raw_amt)
            target_fees = [
                p.published_net_tuition_before_aid()
                for p in catalog
                if (not focus_uid or p.university_id == focus_uid) and p.published_net_tuition_before_aid() > 0
            ]
            avg_fee = sum(target_fees) / len(target_fees) if target_fees else 200_000.0
            tuition_pct = round(max(-100.0, min(1000.0, (raw_amt / avg_fee) * 100.0)), 2)
            assumptions.append(
                QueryAssumption(
                    key="tuition_tl_to_pct",
                    label="Converted TL tuition delta to %",
                    value=tuition_pct,
                    source="inferred",
                    unit="%",
                    description=f"Derived from {raw_amt:,.0f} TL relative to average targeted net fee ({avg_fee:,.0f} TL).",
                )
            )

    # Ranking extraction (exogenous prestige)
    ranking_pct = _extract_signed_pct_near(clean, ("ranking", "rank", "prestige", "sıralama", "prestij"))
    ranking_spots: int | None = None
    spots_m = re.search(
        r"(?:rank(?:ing)?|sıralama)[^.;\n]{0,35}?(?:by\s+)?([+-]?\d+)\s*(?:spots?|places?|positions?|sıra)\b",
        clean,
        flags=re.IGNORECASE,
    )
    if not spots_m:
        spots_m = re.search(
            r"\b(?:improves?|drops?|falls?|rises?|gains?|loses?|yüksel\w*|düş\w*)\s+(?:by\s+)?(\d+)\s*(?:spots?|places?|positions?|sıra)\b",
            clean,
            flags=re.IGNORECASE,
        )
    if spots_m:
        val = int(spots_m.group(1))
        win = clean[max(0, spots_m.start() - 25) : min(len(clean), spots_m.end() + 25)].lower()
        if any(w in win for w in _NEGATIVE_WORDS):
            val = -abs(val)
        ranking_spots = val

    top_n_m = re.search(r"(?:ranking|rank|sıralama)[^.;\n]{0,30}?\btop\s+(\d+)\b", clean, flags=re.IGNORECASE)
    if top_n_m and ranking_spots is None and ranking_pct is None:
        desired_rank = max(1, int(top_n_m.group(1)))
        cur_ranks = [
            p.university_rank for p in catalog
            if (not focus_uid or p.university_id == focus_uid) and p.university_rank is not None
        ]
        if cur_ranks:
            cur_rank = int(round(sum(cur_ranks) / len(cur_ranks)))
            ranking_spots = cur_rank - desired_rank
            assumptions.append(
                QueryAssumption(
                    key="target_top_rank",
                    label="Target rank shift to reach Top-N",
                    value=ranking_spots,
                    source="inferred",
                    unit="spots",
                    description=f"Shift from baseline rank ~{cur_rank} to #{desired_rank}.",
                )
            )

    is_directional_rank = bool(
        _DIRECTIONAL_PAIR_RE.search(clean) and _has_any(lower, ("ranking", "rank", "prestige", "sıralama"))
    )
    is_directional_tuition = bool(
        _DIRECTIONAL_PAIR_RE.search(clean) and _has_any(lower, ("tuition", "fee", "harç", "ücret"))
    )

    # Quota, aid, baraj, scholarship mix
    quota_pct = _extract_signed_pct_near(clean, ("quota", "quotas", "seat", "seats", "capacity", "kontenjan", "kapasite"))
    aid_pct = _extract_signed_pct_near(clean, ("aid", "financial aid", "scholarship", "burs", "grant"))

    schol_mix: dict[str, float] = {}
    if _has_any(lower, ("double burslu", "double full scholarship", "2x burslu")):
        schol_mix["burslu"] = 2.0
    elif _has_any(lower, ("shift to burslu", "more burslu", "more full scholarship")):
        schol_mix["burslu"] = 1.5
        schol_mix["ucretli"] = 0.75

    multi_pcts = _extract_multi_percentages(clean)
    if tuition_pct is None and len(multi_pcts) == 1 and _has_any(lower, ("tuition", "harç", "ücret")):
        tuition_pct = multi_pcts[0]
        if _has_any(lower, _NEGATIVE_WORDS) and tuition_pct > 0:
            tuition_pct = -tuition_pct
    if quota_pct is None and len(multi_pcts) == 1 and _has_any(lower, ("quota", "kontenjan", "seat", "capacity")) and tuition_pct is None:
        quota_pct = multi_pcts[0]
        if _has_any(lower, _NEGATIVE_WORDS) and quota_pct > 0:
            quota_pct = -quota_pct
    if aid_pct is None and len(multi_pcts) == 1 and _has_any(lower, ("aid", "burs", "grant")) and tuition_pct is None and quota_pct is None:
        aid_pct = multi_pcts[0]

    # Build base targeting lists
    target_uids = [focus_uid] if focus_uid else []
    target_depts = list(focus_depts)
    target_progs = list(focus_progs)

    affordability_mode = "none"
    if _has_any(lower, ("hard exclude", "strict affordability", "cannot afford")):
        affordability_mode = "hard_exclude"

    # When candidates start with need_aid_grant == 0 and the prompt introduces/scales aid,
    # infer a transparent baseline annual aid pool proportional to targeted fee revenue so
    # aid levers produce a real counterfactual effect rather than scaling 0 TL by X%.
    inferred_base_aid: float | None = None
    if aid_pct is not None:
        scoped_fee_tuition = sum(
            max(1, p.capacity) * p.published_net_tuition_before_aid()
            for p in catalog
            if (not target_uids or p.university_id in target_uids)
            and (not target_progs or p.program_id in target_progs)
            and (not target_depts or any(d.lower() in p.department_name.lower() for d in target_depts))
            and p.published_net_tuition_before_aid() > 0
        )
        if scoped_fee_tuition > 0:
            inferred_base_aid = round(max(400_000.0, scoped_fee_tuition * 0.25), 2)
        elif not target_uids:
            inferred_base_aid = 1_000_000.0
        if inferred_base_aid is not None:
            assumptions.append(
                QueryAssumption(
                    key="base_aid_budget",
                    label="Inferred baseline annual aid pool",
                    value=inferred_base_aid,
                    source="inferred",
                    unit="TL",
                    description=(
                        "Synthetic candidates start with 0 TL need_aid_grant; inferred baseline pool (~25% of targeted "
                        "fee-seat revenue) scaled by aid_budget_change_pct."
                    ),
                )
            )

    fee_scale = catalog_fee_scale(catalog)
    base_intervention = UniversityPolicyIntervention(
        tuition_change_pct=tuition_pct,
        aid_budget_change_pct=aid_pct,
        base_aid_budget=inferred_base_aid,
        max_grant_per_student=round(95_000.0 * fee_scale, 2) if inferred_base_aid is not None else None,
        capacity_change_pct=quota_pct,
        ranking_change_pct=ranking_pct,
        ranking_rank_delta=ranking_spots,
        scholarship_tier_mix=schol_mix,
        affordability_filter_mode=affordability_mode,  # type: ignore[arg-type]
        target_university_ids=target_uids,
        target_program_ids=target_progs,
        target_department_names=target_depts,
        semester_count=4,
        replications=8,
        rule_fidelity="hypothetical_simplified",
        osym_verified=False,
    )

    intent, sim_mode = _classify_intent(
        clean,
        has_tuition=(tuition_pct is not None or is_directional_tuition),
        has_ranking=(ranking_pct is not None or ranking_spots is not None),
        has_quota=(quota_pct is not None),
        has_aid=(aid_pct is not None or bool(schol_mix)),
        has_baraj=_has_any(lower, ("baraj", "threshold")),
        is_directional_rank=is_directional_rank,
        multi_pcts=multi_pcts,
    )

    # Comparison variants and sweeps
    variants: list[QueryVariantSpec] = []
    sweep_pcts: list[float] = []

    if is_directional_rank and ranking_pct is None and ranking_spots is None:
        mag = _DEFAULT_DIRECTIONAL_PCT
        base_intervention = base_intervention.model_copy(update={"ranking_change_pct": mag})
        variants = [
            QueryVariantSpec(
                variant_id="ranking_lower",
                label=f"Lower Ranking (-{mag:g}%)",
                intervention=base_intervention.model_copy(update={"ranking_change_pct": -mag}),
            ),
            QueryVariantSpec(
                variant_id="baseline",
                label="Baseline (0%)",
                intervention=UniversityPolicyIntervention(
                    target_university_ids=target_uids,
                    target_program_ids=target_progs,
                    target_department_names=target_depts,
                ),
                is_baseline=True,
            ),
            QueryVariantSpec(
                variant_id="ranking_higher",
                label=f"Higher Ranking (+{mag:g}%)",
                intervention=base_intervention.model_copy(update={"ranking_change_pct": mag}),
            ),
        ]
        assumptions.append(
            QueryAssumption(
                key="ranking_variant_magnitude_pct",
                label="Default ranking shift for 'higher or lower'",
                value=mag,
                source="default",
                unit="%",
                description="Directional ranking prompt tested at -20% (lower) vs Baseline vs +20% (higher).",
            )
        )
    elif is_directional_tuition and tuition_pct is None:
        mag = _DEFAULT_DIRECTIONAL_PCT
        base_intervention = base_intervention.model_copy(update={"tuition_change_pct": mag})
        variants = [
            QueryVariantSpec(
                variant_id="tuition_lower",
                label=f"Lower Tuition (-{mag:g}%)",
                intervention=base_intervention.model_copy(update={"tuition_change_pct": -mag}),
            ),
            QueryVariantSpec(
                variant_id="baseline",
                label="Baseline (0%)",
                intervention=UniversityPolicyIntervention(
                    target_university_ids=target_uids,
                    target_program_ids=target_progs,
                    target_department_names=target_depts,
                ),
                is_baseline=True,
            ),
            QueryVariantSpec(
                variant_id="tuition_higher",
                label=f"Higher Tuition (+{mag:g}%)",
                intervention=base_intervention.model_copy(update={"tuition_change_pct": mag}),
            ),
        ]
        assumptions.append(
            QueryAssumption(
                key="tuition_variant_magnitude_pct",
                label="Default tuition shift for directional prompt",
                value=mag,
                source="default",
                unit="%",
            )
        )
    elif len(multi_pcts) >= 2 and intent == "multi_scenario_compare":
        variants = [
            QueryVariantSpec(
                variant_id="baseline",
                label="Baseline (0%)",
                intervention=UniversityPolicyIntervention(
                    target_university_ids=target_uids,
                    target_program_ids=target_progs,
                    target_department_names=target_depts,
                ),
                is_baseline=True,
            )
        ]
        for idx, pct in enumerate(multi_pcts[:6], start=1):
            is_quota = _has_any(lower, ("quota", "seat", "kontenjan", "capacity")) and not _has_any(lower, ("tuition", "harç", "ücret"))
            var_int = base_intervention.model_copy(
                update={
                    "tuition_change_pct": None if is_quota else pct,
                    "capacity_change_pct": pct if is_quota else base_intervention.capacity_change_pct,
                }
            )
            sign = "+" if pct > 0 else ""
            variants.append(
                QueryVariantSpec(
                    variant_id=f"var_{idx}",
                    label=f"{'Quota' if is_quota else 'Tuition'} {sign}{pct:g}%",
                    intervention=var_int,
                )
            )

    if intent == "revenue_tradeoff" or _has_any(lower, ("sweep", "break-even", "breakeven", "revenue-maximizing", "how sensitive")):
        sweep_pcts = [-20.0, 0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 75.0, 100.0]
        if tuition_pct is not None and tuition_pct not in sweep_pcts:
            sweep_pcts = sorted(set(sweep_pcts + [tuition_pct]))
        assumptions.append(
            QueryAssumption(
                key="tuition_sweep_grid",
                label="Tuition sweep grid (%)",
                value=sweep_pcts,
                source="default",
                unit="%",
                description="Grid evaluated to locate break-even and revenue-maximizing tuition.",
            )
        )

    # Record user/inferred assumptions transparently
    if tuition_pct is not None:
        assumptions.append(
            QueryAssumption(
                key="tuition_change_pct",
                label="Target tuition change",
                value=tuition_pct,
                source="user",
                unit="%",
            )
        )
    if ranking_pct is not None:
        assumptions.append(
            QueryAssumption(
                key="ranking_change_pct",
                label="Exogenous ranking shift",
                value=ranking_pct,
                source="user",
                unit="%",
            )
        )
    if ranking_spots is not None:
        assumptions.append(
            QueryAssumption(
                key="ranking_rank_delta",
                label="Exogenous rank-spot shift",
                value=ranking_spots,
                source="user",
                unit="spots",
            )
        )
    if quota_pct is not None:
        assumptions.append(
            QueryAssumption(
                key="capacity_change_pct",
                label="Program seat quota change",
                value=quota_pct,
                source="user",
                unit="%",
            )
        )
    if aid_pct is not None:
        assumptions.append(
            QueryAssumption(
                key="aid_budget_change_pct",
                label="Need-based aid budget change",
                value=aid_pct,
                source="user",
                unit="%",
            )
        )

    assumptions.append(
        QueryAssumption(
            key="cohort_size",
            label="Synthetic applicant cohort size",
            value=cohort_size,
            source="default",
            unit="candidates",
        )
    )
    assumptions.append(
        QueryAssumption(
            key="rivals_fixed",
            label="Competitor universities held fixed",
            value=True,
            source="default",
            editable=False,
            description="Only targeted university/programs change; rival institutions remain unchanged outside options.",
        )
    )

    metrics_requested = ["listed_anywhere", "listed_top_k", "first_choice", "placed"]
    if sim_mode in ("retention", "both"):
        metrics_requested.append("retained")
    if intent in ("cutoff_impact", "ranking_sensitivity", "quota_capacity"):
        metrics_requested.extend(["cutoff_score", "cutoff_rank", "fill_rate"])
    if intent in ("revenue_tradeoff", "scholarship_aid", "application_demand") or tuition_pct is not None:
        metrics_requested.append("net_tuition_revenue")

    disclaimers = [
        "HYPOTHETICAL / UNCALIBRATED PROTOTYPE (osym_verified=false, coefficients_calibrated=false).",
        "Rival universities stay fixed as unchanged outside options and do not strategically react.",
        "Synthetic candidate scores, preferences, and price/prestige elasticities are uncalibrated assumptions.",
    ]

    confidence = 0.88
    if unresolved:
        confidence = 0.45
    elif out_of_scope:
        confidence = 0.25
    elif is_directional_rank or is_directional_tuition:
        confidence = 0.78

    return UniversityQuerySpec(
        original_prompt=clean,
        language=lang,  # type: ignore[arg-type]
        intent=intent,
        focus_university_id=focus_uid,
        focus_university_name=focus_uname,
        focus_program_ids=target_progs,
        focus_department_names=target_depts,
        snapshot_id=snapshot_id,
        admission_year=eff_year,
        levers=base_intervention,
        comparison_variants=variants,
        sweep_tuition_pcts=sweep_pcts,
        metrics_requested=metrics_requested,
        subgroup_dimensions_requested=_extract_subgroups(clean),
        simulation_mode=sim_mode,
        cohort_size=cohort_size,
        seed=seed,
        assumptions=assumptions,
        disclaimers=disclaimers,
        confidence=confidence,
        unresolved_entities=unresolved,
        out_of_scope_reasons=out_of_scope,
    )


def compile_university_query_with_llm(
    prompt: str,
    *,
    catalog: list[ProgramOffering],
    context_university_id: str | None = None,
    snapshot_id: str | None = None,
    admission_year: int | None = None,
    cohort_size: int = 200,
    seed: int = 42,
    model: str | None = None,
) -> UniversityQuerySpec | None:
    """Optional gated LLM query compiler; validates strictly via Pydantic and falls back on failure."""
    if os.environ.get("SOCIETYTWIN_ENABLE_LIVE_SCENARIO_LLM", "").lower() not in ("1", "true", "yes"):
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    unis = sorted({(p.university_id, p.university_name) for p in catalog})
    depts = sorted({p.department_name for p in catalog})[:30]
    catalog_ctx = {
        "universities": [{"university_id": uid, "university_name": uname} for uid, uname in unis],
        "sample_departments": depts,
        "context_university_id": context_university_id,
        "snapshot_id": snapshot_id,
        "admission_year": admission_year,
    }
    try:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=api_key)
        sys_msg = (
            "You convert natural-language questions about a university in Türkiye into a strict UniversityQuerySpec JSON. "
            "Never fabricate simulation numbers or results. Only extract intent, target university/program IDs from the "
            "provided catalog (resolving 'this uni' to context_university_id if given, else record unresolved_entities), "
            "and policy levers. Return ONLY valid JSON matching UniversityQuerySpec."
        )
        resp = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": sys_msg},
                {
                    "role": "user",
                    "content": f"Catalog:\n{json.dumps(catalog_ctx, ensure_ascii=False)}\n\nPrompt:\n{prompt}\n\nDefaults: cohort_size={cohort_size}, seed={seed}",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        content = resp.choices[0].message.content
        if not content:
            return None
        parsed = UniversityQuerySpec.model_validate(json.loads(content))
        # Ensure target IDs exist in catalog
        valid_uids = {p.university_id for p in catalog}
        if parsed.focus_university_id and parsed.focus_university_id not in valid_uids:
            return None
        return parsed
    except Exception as exc:
        logger.warning("LLM university query compilation failed, falling back to heuristic: %s", exc)
        return None


def compile_university_query(
    prompt: str,
    *,
    catalog: list[ProgramOffering],
    context_university_id: str | None = None,
    snapshot_id: str | None = None,
    admission_year: int | None = None,
    cohort_size: int = 200,
    seed: int = 42,
    model: str | None = None,
    force_heuristic: bool = False,
) -> UniversityQuerySpec:
    """Compile a university prompt into UniversityQuerySpec (LLM if enabled, deterministic otherwise)."""
    clean = (prompt or "").strip()
    if len(clean) < 3:
        raise ValueError("Prompt must be at least 3 characters long.")
    if not force_heuristic:
        llm_spec = compile_university_query_with_llm(
            clean,
            catalog=catalog,
            context_university_id=context_university_id,
            snapshot_id=snapshot_id,
            admission_year=admission_year,
            cohort_size=cohort_size,
            seed=seed,
            model=model,
        )
        if llm_spec is not None:
            return llm_spec
    return compile_university_query_heuristic(
        clean,
        catalog=catalog,
        context_university_id=context_university_id,
        snapshot_id=snapshot_id,
        admission_year=admission_year,
        cohort_size=cohort_size,
        seed=seed,
    )
