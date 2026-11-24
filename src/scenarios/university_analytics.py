"""Target-university application, subgroup, migration, and scaling analytics for prompt-driven queries."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .placement.models import CandidateRecord, PlacementComparisonReport, PlacementResult, ProgramOffering
from .university_query import UniversityQuerySpec

SectionType = Literal[
    "tiles",
    "table",
    "bar_series",
    "line_series",
    "comparison_set",
    "flow_summary",
    "text_note",
]


class StatisticsSection(BaseModel):
    """Generic typed statistics block rendered dynamically by the frontend."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: SectionType
    data: dict[str, Any]
    unit: str | None = None
    caveat: str | None = None


def _scholarship_tier_label(prog: ProgramOffering) -> str:
    if prog.tuition_annual <= 0.0:
        return "State (Free)"
    if prog.scholarship_pct >= 99.9:
        return "100% Burslu"
    if prog.scholarship_pct >= 49.9:
        return "50% Discount"
    if prog.scholarship_pct >= 24.9:
        return "25% Discount"
    return "Full Fee (Ücretli)"


def _target_program_ids(
    programs: list[ProgramOffering],
    query_spec: UniversityQuerySpec,
) -> set[str]:
    lev = query_spec.levers
    has_scope = bool(lev.target_university_ids or lev.target_program_ids or lev.target_department_names)
    if not has_scope:
        return {p.program_id for p in programs}
    out: set[str] = set()
    for p in programs:
        if lev.target_university_ids and p.university_id not in lev.target_university_ids:
            continue
        if lev.target_program_ids and p.program_id not in lev.target_program_ids:
            continue
        if lev.target_department_names and not any(
            d.lower() in p.department_name.lower() for d in lev.target_department_names
        ):
            continue
        out.add(p.program_id)
    return out


def _primary_score_type(cand: CandidateRecord) -> str:
    for st in ("SAY", "EA", "SÖZ", "DİL", "TYT"):
        if st != "TYT" and cand.scores.get(st) is not None:  # type: ignore[arg-type]
            return st
    return "TYT" if cand.scores.get("TYT") is not None else "unknown"


def _candidate_target_status(
    outcome: Any,
    target_pids: set[str],
    top_k: int,
) -> dict[str, Any]:
    listed_pids = [ev.program_id for ev in outcome.preference_evaluations]
    eligible_pids = [ev.program_id for ev in outcome.preference_evaluations if ev.status == "eligible"]
    aff_excluded = any(
        ev.program_id in target_pids and ev.reason_code == "AFFORDABILITY_EXCLUDED"
        for ev in outcome.preference_evaluations
    )
    target_listed = [pid for pid in listed_pids if pid in target_pids]
    target_top_k = [pid for pid in listed_pids[:top_k] if pid in target_pids]
    target_eligible = [pid for pid in eligible_pids if pid in target_pids]
    first_choice_target = bool(eligible_pids and eligible_pids[0] in target_pids) or bool(
        listed_pids and listed_pids[0] in target_pids and not aff_excluded
    )
    placed_at_target = outcome.placement_status == "placed" and outcome.assigned_program_id in target_pids
    placed_pid = outcome.assigned_program_id if outcome.placement_status == "placed" else None
    return {
        "listed_anywhere": bool(target_listed),
        "listed_top_k": bool(target_top_k),
        "eligible_applicant": bool(target_eligible),
        "first_choice": first_choice_target,
        "placed": placed_at_target,
        "placed_program_id": placed_pid,
        "target_listed_pids": target_listed,
        "all_listed_pids": listed_pids,
        "aff_excluded": aff_excluded,
    }


def _pct_change(base: int | float, pol: int | float) -> float | None:
    if base == 0:
        return None
    return round(((float(pol) - float(base)) / float(base)) * 100.0, 2)


def compute_target_university_analytics(
    *,
    query_spec: UniversityQuerySpec,
    candidates: list[CandidateRecord],
    programs: list[ProgramOffering],
    baseline_result: PlacementResult,
    policy_result: PlacementResult,
    comparison: PlacementComparisonReport,
    cohort_source: str,
    seed: int,
    top_k: int = 3,
    pre_dropped_policy: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Compute target-university application metrics, subgroup tables, migration flows, and scaling."""
    target_pids = _target_program_ids(programs, query_spec)
    prog_map = {p.program_id: p for p in programs}
    cand_map = {c.candidate_id: c for c in candidates}

    target_provinces = {
        prog_map[pid].province_code
        for pid in target_pids
        if pid in prog_map and prog_map[pid].province_code is not None
    }

    base_out_map = {o.candidate_id: o for o in baseline_result.candidate_outcomes}
    pol_out_map = {o.candidate_id: o for o in policy_result.candidate_outcomes}
    fee_target_pids = {
        pid
        for pid in target_pids
        if pid in prog_map and prog_map[pid].published_net_tuition_before_aid() > 0.0
    }

    # Candidate-level application definitions (counted per distinct candidate for the target uni)
    counts_base = {
        "listed_anywhere": 0,
        "fee_paying_listed": 0,
        "listed_top_k": 0,
        "eligible_applicants": 0,
        "first_choice": 0,
        "placed": 0,
    }
    counts_pol = {
        "listed_anywhere": 0,
        "fee_paying_listed": 0,
        "listed_top_k": 0,
        "eligible_applicants": 0,
        "first_choice": 0,
        "placed": 0,
    }

    # Subgroup buckets: dim -> bucket -> metric dict
    subgroup_dims = ("income_band", "province_code", "province_origin", "sex", "score_type_used")
    sub_buckets: dict[str, dict[str, dict[str, int]]] = {d: {} for d in subgroup_dims}

    # Migration counters
    migration = {
        "stayed_at_target": 0,
        "shifted_within_target": 0,
        "shifted_to_rival_uni": 0,
        "primary_or_placed_shifted_to_rival": 0,
        "dropped_out_of_applying": 0,
        "newly_attracted": 0,
        "unaffected_non_applicants": 0,
    }
    rival_destinations: dict[str, int] = {}
    primary_rival_destinations: dict[str, int] = {}

    for cid in sorted(cand_map):
        cand = cand_map[cid]
        b_st = _candidate_target_status(base_out_map[cid], target_pids, top_k)
        p_st = _candidate_target_status(pol_out_map[cid], target_pids, top_k)

        for key, st_key in (
            ("listed_anywhere", "listed_anywhere"),
            ("listed_top_k", "listed_top_k"),
            ("eligible_applicants", "eligible_applicant"),
            ("first_choice", "first_choice"),
            ("placed", "placed"),
        ):
            if b_st[st_key]:
                counts_base[key] += 1
            if p_st[st_key]:
                counts_pol[key] += 1

        if any(pid in fee_target_pids for pid in b_st["target_listed_pids"]):
            counts_base["fee_paying_listed"] += 1
        if any(pid in fee_target_pids for pid in p_st["target_listed_pids"]):
            counts_pol["fee_paying_listed"] += 1

        # Track shifts only when the candidate's primary (#1/placed) outcome actually changed away from target
        b_outcome_pid = b_st["placed_program_id"] or (b_st["all_listed_pids"][0] if b_st["all_listed_pids"] else None)
        p_outcome_pid = p_st["placed_program_id"] or (p_st["all_listed_pids"][0] if p_st["all_listed_pids"] else None)
        b_fc_pid = next((ev.program_id for ev in base_out_map[cid].preference_evaluations if ev.status == "eligible"), None)
        p_fc_pid = next((ev.program_id for ev in pol_out_map[cid].preference_evaluations if ev.status == "eligible"), None)
        placed_moved_to_rival = (
            bool(b_st["placed_program_id"] in target_pids)
            and bool(p_st["placed_program_id"] and p_st["placed_program_id"] not in target_pids)
        )
        fc_moved_to_rival = (
            bool(b_fc_pid in target_pids)
            and bool(p_fc_pid and p_fc_pid not in target_pids)
            and p_outcome_pid != b_outcome_pid
        )
        if placed_moved_to_rival or fc_moved_to_rival:
            dest_rival_pid = (
                p_st["placed_program_id"]
                if (p_st["placed_program_id"] and p_st["placed_program_id"] not in target_pids)
                else p_fc_pid
            )
            if dest_rival_pid and dest_rival_pid in prog_map:
                migration["primary_or_placed_shifted_to_rival"] += 1
                p_r_name = prog_map[dest_rival_pid].university_name
                primary_rival_destinations[p_r_name] = primary_rival_destinations.get(p_r_name, 0) + 1

        # Subgroup labels
        origin_lbl = (
            "unknown_uni_province"
            if not target_provinces
            else ("same_province" if cand.province_code in target_provinces else "out_of_province")
        )
        dim_vals = {
            "income_band": cand.income_band or "unknown",
            "province_code": cand.province_code or "unknown",
            "province_origin": origin_lbl,
            "sex": cand.sex or "unknown",
            "score_type_used": _primary_score_type(cand),
        }
        for dim, val in dim_vals.items():
            bkt = sub_buckets[dim].setdefault(
                val,
                {
                    "cohort_candidates": 0,
                    "baseline_listed": 0,
                    "policy_listed": 0,
                    "baseline_first_choice": 0,
                    "policy_first_choice": 0,
                    "baseline_placed": 0,
                    "policy_placed": 0,
                },
            )
            bkt["cohort_candidates"] += 1
            if b_st["listed_anywhere"]:
                bkt["baseline_listed"] += 1
            if p_st["listed_anywhere"]:
                bkt["policy_listed"] += 1
            if b_st["first_choice"]:
                bkt["baseline_first_choice"] += 1
            if p_st["first_choice"]:
                bkt["policy_first_choice"] += 1
            if b_st["placed"]:
                bkt["baseline_placed"] += 1
            if p_st["placed"]:
                bkt["policy_placed"] += 1

        # Migration classification for target university applicants
        b_app = b_st["listed_anywhere"]
        p_app = p_st["listed_anywhere"]
        if b_app and p_app:
            if b_st["target_listed_pids"] != p_st["target_listed_pids"] or (
                b_st["placed_program_id"] != p_st["placed_program_id"] and p_st["placed"]
            ):
                migration["shifted_within_target"] += 1
            else:
                migration["stayed_at_target"] += 1
        elif b_app and not p_app:
            rival_pids = [pid for pid in p_st["all_listed_pids"] if pid not in target_pids]
            dest_pid = p_st["placed_program_id"] if (p_st["placed_program_id"] and p_st["placed_program_id"] not in target_pids) else (rival_pids[0] if rival_pids else None)
            if dest_pid and dest_pid in prog_map:
                migration["shifted_to_rival_uni"] += 1
                uname = prog_map[dest_pid].university_name
                rival_destinations[uname] = rival_destinations.get(uname, 0) + 1
            else:
                migration["dropped_out_of_applying"] += 1
        elif not b_app and p_app:
            migration["newly_attracted"] += 1
        else:
            migration["unaffected_non_applicants"] += 1

    # Program & scholarship tier tables scoped to target
    tier_rows: dict[str, dict[str, Any]] = {}
    program_rows: list[dict[str, Any]] = []
    base_po = {po.program_id: po for po in baseline_result.program_outcomes}
    pol_po = {po.program_id: po for po in policy_result.program_outcomes}

    target_rev_base = 0.0
    target_rev_pol = 0.0
    target_cap_base = 0
    target_cap_pol = 0
    target_filled_base = 0
    target_filled_pol = 0
    target_aff_drops = 0

    for d in comparison.program_deltas:
        if d.program_id not in target_pids:
            continue
        prog = prog_map[d.program_id]
        tier = _scholarship_tier_label(prog)
        tier_entry = tier_rows.setdefault(
            tier,
            {
                "tier": tier,
                "programs": 0,
                "baseline_listed": 0,
                "policy_listed": 0,
                "baseline_first_choice": 0,
                "policy_first_choice": 0,
                "baseline_filled": 0,
                "policy_filled": 0,
                "baseline_capacity": 0,
                "policy_capacity": 0,
                "dropped_due_to_affordability": 0,
            },
        )
        tier_entry["programs"] += 1
        tier_entry["baseline_listed"] += d.baseline_listed_anywhere
        tier_entry["policy_listed"] += d.policy_listed_anywhere
        tier_entry["baseline_first_choice"] += d.baseline_first_choice
        tier_entry["policy_first_choice"] += d.policy_first_choice
        tier_entry["baseline_filled"] += d.baseline_filled
        tier_entry["policy_filled"] += d.policy_filled
        tier_entry["baseline_capacity"] += d.baseline_capacity
        tier_entry["policy_capacity"] += d.policy_capacity
        pre_drop_cnt = len(pre_dropped_policy.get(d.program_id, ())) if pre_dropped_policy else 0
        eff_aff_drop = max(d.dropped_due_to_affordability, pre_drop_cnt)
        tier_entry["dropped_due_to_affordability"] += eff_aff_drop

        target_cap_base += d.baseline_capacity
        target_cap_pol += d.policy_capacity
        target_filled_base += d.baseline_filled
        target_filled_pol += d.policy_filled
        target_aff_drops += eff_aff_drop

        program_rows.append({
            "program_id": d.program_id,
            "university_name": prog.university_name,
            "department_name": prog.department_name,
            "scholarship_tier": tier,
            "score_type": prog.score_type,
            "baseline_capacity": d.baseline_capacity,
            "policy_capacity": d.policy_capacity,
            "baseline_listed_anywhere": d.baseline_listed_anywhere,
            "policy_listed_anywhere": d.policy_listed_anywhere,
            "listed_anywhere_delta": d.listed_anywhere_delta,
            "listed_anywhere_pct_change": d.listed_anywhere_pct_change,
            "baseline_first_choice": d.baseline_first_choice,
            "policy_first_choice": d.policy_first_choice,
            "first_choice_delta": d.first_choice_delta,
            "baseline_filled": d.baseline_filled,
            "policy_filled": d.policy_filled,
            "filled_delta": d.filled_delta,
            "baseline_fill_rate": d.baseline_fill_rate,
            "policy_fill_rate": d.policy_fill_rate,
            "baseline_cutoff_score": d.baseline_cutoff_score,
            "policy_cutoff_score": d.policy_cutoff_score,
            "cutoff_score_delta": d.cutoff_score_delta,
            "baseline_cutoff_rank": d.baseline_cutoff_rank,
            "policy_cutoff_rank": d.policy_cutoff_rank,
            "cutoff_rank_delta": d.cutoff_rank_delta,
            "dropped_due_to_affordability": eff_aff_drop,
        })

    # Target net tuition revenue (from placed outcomes at target programs)
    for o in baseline_result.candidate_outcomes:
        if o.placement_status == "placed" and o.assigned_program_id in target_pids and o.financials:
            target_rev_base += float(o.financials.net_tuition)
    for o in policy_result.candidate_outcomes:
        if o.placement_status == "placed" and o.assigned_program_id in target_pids and o.financials:
            target_rev_pol += float(o.financials.net_tuition)
    target_rev_base = round(target_rev_base, 2)
    target_rev_pol = round(target_rev_pol, 2)

    # Cohort scaling factor
    weights = [float(c.population_weight) for c in candidates if c.population_weight is not None]
    sample_size = len(candidates)
    if cohort_source == "tuik_population" and weights and len(weights) == sample_size:
        total_weighted_pop = round(math.fsum(weights), 2)
        scale_factor = round(total_weighted_pop / sample_size, 4) if sample_size > 0 else 1.0
        scale_label = "tuik_weighted_estimates_available"
    else:
        total_weighted_pop = float(sample_size)
        scale_factor = 1.0
        scale_label = "cohort_counts_only"

    application_definitions = {
        key: {
            "baseline": counts_base[key],
            "policy": counts_pol[key],
            "delta": counts_pol[key] - counts_base[key],
            "pct_change": _pct_change(counts_base[key], counts_pol[key]),
        }
        for key in ("listed_anywhere", "fee_paying_listed", "listed_top_k", "eligible_applicants", "first_choice", "placed")
    }

    subgroups_formatted: dict[str, list[dict[str, Any]]] = {}
    for dim, bmap in sub_buckets.items():
        rows = []
        for val, m in sorted(bmap.items()):
            rows.append({
                "group": val,
                **m,
                "listed_delta": m["policy_listed"] - m["baseline_listed"],
                "listed_pct_change": _pct_change(m["baseline_listed"], m["policy_listed"]),
                "placed_delta": m["policy_placed"] - m["baseline_placed"],
            })
        subgroups_formatted[dim] = rows

    tiers_formatted = []
    for t_entry in tier_rows.values():
        tiers_formatted.append({
            **t_entry,
            "listed_delta": t_entry["policy_listed"] - t_entry["baseline_listed"],
            "listed_pct_change": _pct_change(t_entry["baseline_listed"], t_entry["policy_listed"]),
            "first_choice_delta": t_entry["policy_first_choice"] - t_entry["baseline_first_choice"],
            "filled_delta": t_entry["policy_filled"] - t_entry["baseline_filled"],
        })

    top_rivals = [
        {"university_name": uname, "count": cnt}
        for uname, cnt in sorted(rival_destinations.items(), key=lambda x: (-x[1], x[0]))[:6]
    ]
    top_primary_rivals = [
        {"university_name": uname, "count": cnt}
        for uname, cnt in sorted(primary_rival_destinations.items(), key=lambda x: (-x[1], x[0]))[:6]
    ]

    return {
        "target_program_ids": sorted(target_pids),
        "fee_target_program_ids": sorted(fee_target_pids),
        "all_target_programs_free": len(fee_target_pids) == 0,
        "top_k_definition": top_k,
        "cohort_metadata": {
            "sample_size": sample_size,
            "seed": seed,
            "cohort_source": cohort_source,
            "cohort_scale_factor": scale_factor,
            "represented_population": total_weighted_pop,
            "reporting_basis": scale_label,
        },
        "application_definitions": application_definitions,
        "target_capacity": {
            "baseline": target_cap_base,
            "policy": target_cap_pol,
            "delta": target_cap_pol - target_cap_base,
            "baseline_filled": target_filled_base,
            "policy_filled": target_filled_pol,
            "filled_delta": target_filled_pol - target_filled_base,
            "baseline_fill_rate": round(target_filled_base / target_cap_base, 4) if target_cap_base else 0.0,
            "policy_fill_rate": round(target_filled_pol / target_cap_pol, 4) if target_cap_pol else 0.0,
        },
        "target_revenue": {
            "baseline": target_rev_base,
            "policy": target_rev_pol,
            "delta": round(target_rev_pol - target_rev_base, 2),
            "pct_change": _pct_change(target_rev_base, target_rev_pol),
            "dropped_due_to_affordability": target_aff_drops,
        },
        "subgroups": subgroups_formatted,
        "scholarship_tiers": tiers_formatted,
        "programs": program_rows,
        "migration": {
            **migration,
            "top_rival_destinations": top_rivals,
            "top_primary_rival_destinations": top_primary_rivals,
        },
        "overall_transitions": comparison.transitions.model_dump(mode="json"),
        "baseline_program_outcomes": [base_po[pid].model_dump(mode="json") for pid in sorted(target_pids) if pid in base_po],
        "policy_program_outcomes": [pol_po[pid].model_dump(mode="json") for pid in sorted(target_pids) if pid in pol_po],
    }
