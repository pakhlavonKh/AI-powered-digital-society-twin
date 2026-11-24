"""Behavioral application-choice model with Common Random Numbers (CRN).

Recomputes candidate preference lists dynamically from exogenous candidate traits,
policy-modified net tuition & program prestige, and deterministic CRN taste noise
epsilon(i, p) drawn once per (candidate_id, program_id, seed).
"""

from __future__ import annotations

import math
import re
from typing import Any

from societytwin.national.rng import Stream

from ..schema import UniversityPolicyIntervention
from ..university_query import ElasticityPreset, PreferenceModelConfig, preset_preference_config
from .eligibility import compute_candidate_program_financials, resolve_effective_score
from .models import CandidateRecord, PlacementRuleset, ProgramOffering, catalog_fee_scale


def crn_taste_epsilon(candidate_id: str, program_id: str, seed: int) -> float:
    """Draw deterministic zero-mean taste shock epsilon(i, p) invariant across policy runs."""
    stream = Stream(f"pref:epsilon:{candidate_id}:{program_id}", seed)
    # Centered triangular shock in [-0.45, +0.45]
    u = (stream.random() + stream.random()) / 2.0
    return round((u - 0.5) * 0.9, 6)


_SCHOL_SUFFIX_RE = re.compile(r"\s*\([^)]*\)\s*$")


def crn_department_affinity(candidate_id: str, department_name: str, seed: int) -> float:
    """Deterministic CRN major-interest score invariant across policy and elasticity runs."""
    root = _SCHOL_SUFFIX_RE.sub("", department_name).strip().lower()
    u = Stream(f"pref:dept:{candidate_id}:{root}", seed).random()
    # Top ~18% of majors act as preferred career tracks (+0.95..+1.40); others act as neutral/unwanted (-0.85..-0.48).
    if u >= 0.82:
        return round(0.95 + ((u - 0.82) / 0.18) * 0.45, 6)
    return round(-0.85 + u * 0.45, 6)


def score_candidate_program_utility(
    candidate: CandidateRecord,
    program: ProgramOffering,
    *,
    intervention: UniversityPolicyIntervention | None,
    ruleset: PlacementRuleset,
    config: PreferenceModelConfig,
    seed: int,
    cost_unit: float = 100_000.0,
    baseline_rank: int | None = None,
    multi_major_catalog: bool = False,
) -> tuple[float | None, str | None]:
    """Compute U(i, p) or return (None, drop_reason) if candidate would not apply."""
    if program.status != "open" or program.capacity <= 0:
        return None, "PROGRAM_UNAVAILABLE"

    eff_score = resolve_effective_score(candidate, program.score_type, ruleset)
    if eff_score is None:
        return None, "SCORE_TYPE_MISMATCH"

    fin = compute_candidate_program_financials(candidate, program, intervention)
    if fin.net_tuition > 0.0:
        if candidate.max_affordable_tuition is not None and fin.net_tuition > candidate.max_affordable_tuition:
            return None, "DROPPED_AFFORDABILITY"
        if (
            intervention is not None
            and intervention.affordability_filter_mode == "hard_exclude"
            and fin.liquidity_gap is not None
            and fin.liquidity_gap > 0.0
        ):
            return None, "DROPPED_AFFORDABILITY"

    rank_score = program.effective_prestige_score()
    income_key = candidate.income_band or "middle"
    beta_cost = float(config.beta_cost_by_income.get(income_key, 0.95))
    cost_scaled = fin.net_tuition / max(1.0, float(cost_unit))
    same_province = (
        1.0
        if (candidate.province_code and program.province_code and candidate.province_code == program.province_code)
        else 0.0
    )
    eff_rank = baseline_rank if baseline_rank is not None else program.university_rank
    if eff_rank is not None and eff_rank >= 100:
        cand_log_rank = max(2.2, min(6.3, 6.4 - ((eff_score - 200.0) / 360.0) * 4.0))
        prog_log_rank = math.log10(max(100, eff_rank))
        log_diff = prog_log_rank - cand_log_rank
        if log_diff < -0.25:
            score_fit = max(-1.2, 0.7 - 1.35 * (-0.25 - log_diff))
        elif log_diff <= 1.2:
            score_fit = 1.0 - 0.15 * abs(log_diff - 0.25)
        else:
            score_fit = max(0.35, 0.85 - 0.25 * (log_diff - 1.2))
        if multi_major_catalog and program.degree_level == "associate":
            primary_scores = [float(v) for k, v in candidate.scores.items() if k != "TYT" and v is not None]
            if primary_scores and max(primary_scores) >= 300.0:
                score_fit -= 0.55
    else:
        score_fit = max(0.0, min(1.0, (eff_score - 180.0) / 320.0))
    dept_aff = crn_department_affinity(candidate.candidate_id, program.department_name, seed) if multi_major_catalog else 0.0
    eps = crn_taste_epsilon(candidate.candidate_id, program.program_id, seed)

    utility = (
        config.beta_rank * rank_score
        - beta_cost * cost_scaled
        + config.beta_home * same_province
        + config.beta_fit * score_fit
        + dept_aff
        + eps
    )
    if utility < config.outside_option_threshold:
        return None, "BELOW_UTILITY_THRESHOLD"
    return round(utility, 6), None


def apply_behavioral_preferences(
    candidates: list[CandidateRecord],
    programs: list[ProgramOffering],
    ruleset: PlacementRuleset,
    intervention: UniversityPolicyIntervention | None,
    config: PreferenceModelConfig,
    *,
    seed: int = 42,
    max_list_length: int | None = None,
    cost_unit: float | None = None,
    baseline_ranks: dict[str, int | None] | None = None,
) -> tuple[list[CandidateRecord], dict[str, int], dict[str, set[str]]]:
    """Generate policy-responsive preference lists bounded by ruleset.max_preferences."""
    cap = min(max_list_length or ruleset.max_preferences, ruleset.max_preferences)
    cap = max(1, cap)
    is_multi_major = len(programs) > 30
    eff_cost_unit = (
        cost_unit
        if cost_unit is not None
        else round(100_000.0 * catalog_fee_scale(programs) * (1.35 if is_multi_major else 1.0), 2)
    )

    pre_drop_counts: dict[str, int] = {p.program_id: 0 for p in programs}
    pre_dropped_cids: dict[str, set[str]] = {p.program_id: set() for p in programs}
    updated_candidates: list[CandidateRecord] = []

    for cand in candidates:
        scored: list[tuple[float, str]] = []
        for prog in programs:
            u, drop_reason = score_candidate_program_utility(
                cand,
                prog,
                intervention=intervention,
                ruleset=ruleset,
                config=config,
                seed=seed,
                cost_unit=eff_cost_unit,
                baseline_rank=baseline_ranks.get(prog.program_id) if baseline_ranks else None,
                multi_major_catalog=is_multi_major,
            )
            if drop_reason == "DROPPED_AFFORDABILITY":
                pre_drop_counts[prog.program_id] += 1
                pre_dropped_cids[prog.program_id].add(cand.candidate_id)
                continue
            if u is not None:
                scored.append((u, prog.program_id))

        scored.sort(key=lambda item: (-item[0], item[1]))
        new_prefs = [pid for _, pid in scored[:cap]]
        updated_candidates.append(cand.model_copy(update={"preferences": new_prefs}, deep=True))

    return updated_candidates, pre_drop_counts, pre_dropped_cids


def compute_elasticity_sensitivity_range(
    *,
    candidates: list[CandidateRecord],
    programs: list[ProgramOffering],
    target_program_ids: set[str],
    fee_target_program_ids: set[str] | None = None,
    ruleset: PlacementRuleset | None = None,
    intervention: UniversityPolicyIntervention | None = None,
    seed: int = 42,
    top_k: int = 3,
    presets: tuple[ElasticityPreset, ...] = ("low", "medium", "high"),
) -> dict[str, Any]:
    """Run Low/Medium/High elasticity presets under CRN and summarize min/central/max range."""
    from .engine import run_placement

    fee_pids = fee_target_program_ids if fee_target_program_ids is not None else {
        p.program_id
        for p in programs
        if p.program_id in target_program_ids and p.published_net_tuition_before_aid() > 0.0
    }
    by_preset: dict[str, dict[str, int]] = {}
    for preset in presets:
        cfg = preset_preference_config(preset, top_k_definition=top_k)
        base_res = run_placement(
            candidates,
            programs,
            ruleset=ruleset,
            intervention=UniversityPolicyIntervention(
                target_university_ids=intervention.target_university_ids if intervention else [],
                target_program_ids=intervention.target_program_ids if intervention else [],
                target_department_names=intervention.target_department_names if intervention else [],
            ),
            seed=seed,
            preference_config=cfg,
        )
        pol_res = run_placement(
            candidates,
            programs,
            ruleset=ruleset,
            intervention=intervention,
            seed=seed,
            preference_config=cfg,
        )

        def _count_target(res) -> dict[str, int]:
            listed = 0
            fee_listed = 0
            top_k_cnt = 0
            fc = 0
            placed = 0
            for out in res.candidate_outcomes:
                pids = [ev.program_id for ev in out.preference_evaluations]
                elig = [ev.program_id for ev in out.preference_evaluations if ev.status == "eligible"]
                if any(pid in target_program_ids for pid in pids):
                    listed += 1
                if fee_pids and any(pid in fee_pids for pid in pids):
                    fee_listed += 1
                if any(pid in target_program_ids for pid in pids[:top_k]):
                    top_k_cnt += 1
                if elig and elig[0] in target_program_ids:
                    fc += 1
                if out.placement_status == "placed" and out.assigned_program_id in target_program_ids:
                    placed += 1
            return {
                "listed_anywhere": listed,
                "fee_paying_listed": fee_listed,
                "listed_top_k": top_k_cnt,
                "first_choice": fc,
                "placed": placed,
            }

        b_cnt = _count_target(base_res)
        p_cnt = _count_target(pol_res)
        by_preset[preset] = {
            "baseline_listed_anywhere": b_cnt["listed_anywhere"],
            "baseline_fee_paying_listed": b_cnt["fee_paying_listed"],
            "listed_anywhere": p_cnt["listed_anywhere"],
            "listed_anywhere_delta": p_cnt["listed_anywhere"] - b_cnt["listed_anywhere"],
            "fee_paying_listed": p_cnt["fee_paying_listed"],
            "fee_paying_listed_delta": p_cnt["fee_paying_listed"] - b_cnt["fee_paying_listed"],
            "listed_top_k": p_cnt["listed_top_k"],
            "first_choice": p_cnt["first_choice"],
            "placed": p_cnt["placed"],
        }

    metrics: dict[str, Any] = {"by_preset": by_preset}
    for m in ("listed_anywhere", "fee_paying_listed", "listed_top_k", "first_choice", "placed"):
        vals = [by_preset[p][m] for p in presets]
        metrics[m] = {
            "min": min(vals),
            "central": by_preset["medium"][m],
            "max": max(vals),
        }
    return metrics
