"""Behavioral application-choice model with Common Random Numbers (CRN).

Recomputes candidate preference lists dynamically from exogenous candidate traits,
policy-modified net tuition & program prestige, and deterministic CRN taste noise
epsilon(i, p) drawn once per (candidate_id, program_id, seed).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import numpy as np

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


def _stable_u64(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")


def _splitmix_u01_pair(seed_mat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic vectorized SplitMix64 returning two uniform [0, 1) float64 arrays."""
    c1 = np.uint64(0x9E3779B97F4A7C15)
    c2 = np.uint64(0xBF58476D1CE4E5B9)
    c3 = np.uint64(0x94D049BB133111EB)
    c4 = np.uint64(0xD6E8FEB86659FD93)
    inv53 = 1.0 / float(1 << 53)
    with np.errstate(over="ignore"):
        z1 = seed_mat + c1
        z1 = (z1 ^ (z1 >> np.uint64(30))) * c2
        z1 = (z1 ^ (z1 >> np.uint64(27))) * c3
        z1 = z1 ^ (z1 >> np.uint64(31))

        z2 = z1 + c4
        z2 = (z2 ^ (z2 >> np.uint64(30))) * c2
        z2 = (z2 ^ (z2 >> np.uint64(27))) * c3
        z2 = z2 ^ (z2 >> np.uint64(31))
    u1 = (z1 >> np.uint64(11)).astype(np.float64) * inv53
    u2 = (z2 >> np.uint64(11)).astype(np.float64) * inv53
    return u1, u2


def _get_crn_matrices(
    candidates: list[CandidateRecord],
    programs: list[ProgramOffering],
    seed: int,
    multi_major: bool,
    cache: dict[str, Any] | None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Return cached (N, M) CRN taste epsilon and optional department affinity arrays."""
    cids = tuple(c.candidate_id for c in candidates)
    pids = tuple(p.program_id for p in programs)
    cache_key = (len(cids), len(pids), cids[0] if cids else "", pids[0] if pids else "", seed, multi_major)
    if cache is not None and cache.get("key") == cache_key:
        return cache["eps"], cache["dept_aff"]

    n, m = len(candidates), len(programs)
    if n == 0 or m == 0:
        eps = np.zeros((n, m), dtype=np.float64)
        dept_aff = np.zeros((n, m), dtype=np.float64) if multi_major else None
    elif n * m <= 20_000:
        eps = np.array(
            [[crn_taste_epsilon(c.candidate_id, p.program_id, seed) for p in programs] for c in candidates],
            dtype=np.float64,
        )
        dept_aff = (
            np.array(
                [[crn_department_affinity(c.candidate_id, p.department_name, seed) for p in programs] for c in candidates],
                dtype=np.float64,
            )
            if multi_major
            else None
        )
    else:
        cid_u64 = np.array([_stable_u64(cid) for cid in cids], dtype=np.uint64)[:, None]
        pid_u64 = np.array([_stable_u64(pid) for pid in pids], dtype=np.uint64)[None, :]
        with np.errstate(over="ignore"):
            mix = (cid_u64 * np.uint64(0x9E3779B97F4A7C15)) ^ (pid_u64 * np.uint64(0xBF58476D1CE4E5B9)) ^ np.uint64(seed)
        u1, u2 = _splitmix_u01_pair(mix)
        eps = np.round(((u1 + u2) * 0.5 - 0.5) * 0.9, 6)

        if multi_major:
            roots = [_SCHOL_SUFFIX_RE.sub("", p.department_name).strip().lower() for p in programs]
            uniq_roots = sorted(set(roots))
            root_idx_map = {r: idx for idx, r in enumerate(uniq_roots)}
            prog_root_idx = np.array([root_idx_map[r] for r in roots], dtype=np.intp)
            root_u64 = np.array([_stable_u64(f"dept:{r}") for r in uniq_roots], dtype=np.uint64)[None, :]
            with np.errstate(over="ignore"):
                dmix = (cid_u64 * np.uint64(0x94D049BB133111EB)) ^ (root_u64 * np.uint64(0xD6E8FEB86659FD93)) ^ np.uint64(seed)
            du, _ = _splitmix_u01_pair(dmix)
            uniq_aff = np.where(
                du >= 0.82,
                np.round(0.95 + ((du - 0.82) / 0.18) * 0.45, 6),
                np.round(-0.85 + du * 0.45, 6),
            )
            dept_aff = uniq_aff[:, prog_root_idx]
        else:
            dept_aff = None

    if cache is not None:
        cache["key"] = cache_key
        cache["eps"] = eps
        cache["dept_aff"] = dept_aff
    return eps, dept_aff


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
    preference_cache: dict[str, Any] | None = None,
) -> tuple[list[CandidateRecord], dict[str, int], dict[str, set[str]]]:
    """Generate policy-responsive preference lists bounded by ruleset.max_preferences."""
    cap = min(max_list_length or ruleset.max_preferences, ruleset.max_preferences)
    cap = max(1, cap)
    is_multi_major = len(programs) > 30
    eff_cost_unit = max(
        1.0,
        float(
            cost_unit
            if cost_unit is not None
            else round(100_000.0 * catalog_fee_scale(programs) * (1.35 if is_multi_major else 1.0), 2)
        ),
    )

    n = len(candidates)
    m = len(programs)
    pre_drop_counts: dict[str, int] = {p.program_id: 0 for p in programs}
    pre_dropped_cids: dict[str, set[str]] = {p.program_id: set() for p in programs}
    if n == 0 or m == 0:
        return [c.model_copy(update={"preferences": []}, deep=True) for c in candidates], pre_drop_counts, pre_dropped_cids

    eps_mat, dept_mat = _get_crn_matrices(candidates, programs, seed, is_multi_major, preference_cache)

    # Candidate arrays (N,)
    score_types = ("TYT", "SAY", "EA", "SÖZ", "DİL")
    cand_scores_by_type = {
        st: np.array(
            [
                np.nan if (v := resolve_effective_score(c, st, ruleset)) is None else float(v)
                for c in candidates
            ],
            dtype=np.float64,
        )
        for st in score_types
    }
    best_primary = np.array(
        [
            max(
                (float(v) for k, v in c.scores.items() if k != "TYT" and v is not None),
                default=0.0,
            )
            for c in candidates
        ],
        dtype=np.float64,
    )[:, None]
    need_grant = np.array([float(c.need_aid_grant) for c in candidates], dtype=np.float64)[:, None]
    max_aff = np.array(
        [np.inf if c.max_affordable_tuition is None else float(c.max_affordable_tuition) for c in candidates],
        dtype=np.float64,
    )[:, None]
    liq_budget = np.array(
        [np.nan if c.liquid_budget is None else float(c.liquid_budget) for c in candidates],
        dtype=np.float64,
    )[:, None]
    beta_cost = np.array(
        [float(config.beta_cost_by_income.get(c.income_band or "middle", 0.95)) for c in candidates],
        dtype=np.float64,
    )[:, None]
    cand_prov = np.array([c.province_code or "" for c in candidates], dtype=object)[:, None]

    # Program arrays (M,)
    prog_ids = [p.program_id for p in programs]
    open_mask = np.array([p.status == "open" and p.capacity > 0 for p in programs], dtype=bool)[None, :]
    published = np.array([p.published_net_tuition_before_aid() for p in programs], dtype=np.float64)[None, :]
    rank_score = np.array([p.effective_prestige_score() for p in programs], dtype=np.float64)[None, :]
    prog_prov = np.array([p.province_code or "" for p in programs], dtype=object)[None, :]
    is_assoc = np.array([p.degree_level == "associate" for p in programs], dtype=bool)[None, :]
    eff_ranks = np.array(
        [
            (
                baseline_ranks[p.program_id]
                if baseline_ranks is not None and p.program_id in baseline_ranks and baseline_ranks[p.program_id] is not None
                else (p.university_rank if p.university_rank is not None else -1)
            )
            for p in programs
        ],
        dtype=np.int64,
    )[None, :]

    eff_score_mat = np.full((n, m), np.nan, dtype=np.float64)
    for st in score_types:
        col_mask = np.array([p.score_type == st for p in programs], dtype=bool)
        if np.any(col_mask):
            eff_score_mat[:, col_mask] = cand_scores_by_type[st][:, None]

    score_valid = ~np.isnan(eff_score_mat)

    net_tuition = np.round(np.maximum(0.0, published - np.minimum(published, need_grant)), 2)
    aff_drop = (net_tuition > 0.0) & (net_tuition > max_aff)
    if intervention is not None and intervention.affordability_filter_mode == "hard_exclude":
        upfront_share = 1.0
        if intervention.installment_upfront_share is not None:
            upfront_share = float(intervention.installment_upfront_share)
        elif intervention.installment_count is not None and intervention.installment_count > 1:
            upfront_share = 1.0 / float(intervention.installment_count)
        payments_due = np.round(net_tuition * upfront_share, 2)
        liq_gap = np.where(~np.isnan(liq_budget), np.round(np.maximum(0.0, payments_due - liq_budget), 2), 0.0)
        aff_drop = aff_drop | ((net_tuition > 0.0) & (liq_gap > 0.0))

    elig_aff_drop = open_mask & score_valid & aff_drop
    if np.any(elig_aff_drop):
        for r_idx, c_idx in np.argwhere(elig_aff_drop):
            pid = prog_ids[int(c_idx)]
            pre_drop_counts[pid] += 1
            pre_dropped_cids[pid].add(candidates[int(r_idx)].candidate_id)

    eligible_mask = open_mask & score_valid & (~aff_drop)

    # Vectorized score_fit
    safe_score = np.where(score_valid, eff_score_mat, 0.0)
    real_rank_cols = eff_ranks >= 100
    score_fit = np.clip((safe_score - 180.0) / 320.0, 0.0, 1.0)
    if np.any(real_rank_cols):
        cand_log = np.clip(6.4 - ((safe_score - 200.0) / 360.0) * 4.0, 2.2, 6.3)
        prog_log = np.log10(np.maximum(100, eff_ranks).astype(np.float64))
        log_diff = prog_log - cand_log
        reach_fit = np.where(
            log_diff < -0.25,
            np.maximum(-1.2, 0.7 - 1.35 * (-0.25 - log_diff)),
            np.where(
                log_diff <= 1.2,
                1.0 - 0.15 * np.abs(log_diff - 0.25),
                np.maximum(0.35, 0.85 - 0.25 * (log_diff - 1.2)),
            ),
        )
        if is_multi_major:
            reach_fit = np.where(is_assoc & (best_primary >= 300.0), reach_fit - 0.55, reach_fit)
        score_fit = np.where(real_rank_cols, reach_fit, score_fit)

    same_prov = ((cand_prov != "") & (prog_prov != "") & (cand_prov == prog_prov)).astype(np.float64)

    utility = (
        float(config.beta_rank) * rank_score
        - beta_cost * (net_tuition / eff_cost_unit)
        + float(config.beta_home) * same_prov
        + float(config.beta_fit) * score_fit
        + eps_mat
    )
    if dept_mat is not None:
        utility = utility + dept_mat
    utility = np.round(utility, 6)

    keep_mask = eligible_mask & (utility >= float(config.outside_option_threshold))
    updated_candidates: list[CandidateRecord] = []
    masked_u = np.where(keep_mask, utility, -np.inf)
    for i, cand in enumerate(candidates):
        valid_cols = np.flatnonzero(keep_mask[i])
        if valid_cols.size == 0:
            new_prefs: list[str] = []
        else:
            if valid_cols.size > cap:
                # Extract top-cap candidates in O(K) via NumPy before tie-breaking ties by program_id
                row_vals = masked_u[i, valid_cols]
                top_local = np.argpartition(row_vals, -cap)[-cap:]
                min_top = float(np.min(row_vals[top_local]))
                # Include any exact ties at the boundary so lexicographical tie-break stays exact
                cand_cols = valid_cols[row_vals >= (min_top - 1e-9)]
            else:
                cand_cols = valid_cols
            scored = [(float(utility[i, j]), prog_ids[int(j)]) for j in cand_cols]
            scored.sort(key=lambda item: (-item[0], item[1]))
            new_prefs = [pid for _, pid in scored[:cap]]
        updated_candidates.append(cand.model_copy(update={"preferences": new_prefs}))

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
    preference_cache: dict[str, Any] | None = None,
    preset_results: dict[ElasticityPreset, tuple[Any, Any]] | None = None,
) -> dict[str, Any]:
    """Run Low/Medium/High elasticity presets under CRN and summarize min/central/max range."""
    from .engine import run_placement

    cache = preference_cache if preference_cache is not None else {}
    fee_pids = fee_target_program_ids if fee_target_program_ids is not None else {
        p.program_id
        for p in programs
        if p.program_id in target_program_ids and p.published_net_tuition_before_aid() > 0.0
    }
    by_preset: dict[str, dict[str, int]] = {}
    for preset in presets:
        cfg = preset_preference_config(preset, top_k_definition=top_k)
        if preset_results is not None and preset in preset_results:
            base_res, pol_res = preset_results[preset]
        else:
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
                preference_cache=cache,
            )
            pol_res = run_placement(
                candidates,
                programs,
                ruleset=ruleset,
                intervention=intervention,
                seed=seed,
                preference_config=cfg,
                preference_cache=cache,
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
