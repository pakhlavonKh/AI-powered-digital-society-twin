"""Pure policy intervention transformers for university placement scenarios.

Transforms (candidates, programs, ruleset) according to a UniversityPolicyIntervention
without ever mutating caller-owned input objects.
"""

from __future__ import annotations

import math
from typing import Any

try:
    from ..schema import UniversityPolicyIntervention
    from .models import CandidateRecord, PlacementRuleset, ProgramOffering
except ImportError:
    from scenarios.schema import UniversityPolicyIntervention  # type: ignore
    from scenarios.placement.models import CandidateRecord, PlacementRuleset, ProgramOffering  # type: ignore

from societytwin.national.fitting import largest_remainder


def _program_matches_targets(
    program: ProgramOffering,
    intervention: UniversityPolicyIntervention,
) -> bool:
    """Return True when program is within target scope (empty scope targets all programs)."""
    if (
        not intervention.target_university_ids
        and not intervention.target_program_ids
        and not intervention.target_department_names
    ):
        return True
    if intervention.target_university_ids and program.university_id not in intervention.target_university_ids:
        return False
    if intervention.target_program_ids and program.program_id not in intervention.target_program_ids:
        return False
    if intervention.target_department_names:
        dept_l = program.department_name.lower()
        if not any(d.lower() in dept_l for d in intervention.target_department_names):
            return False
    return True


def _scholarship_tier_key(program: ProgramOffering) -> str:
    if program.tuition_annual <= 0.0:
        return "state_free"
    if program.scholarship_pct >= 99.9:
        return "burslu"
    if program.scholarship_pct >= 49.9:
        return "pct50"
    if program.scholarship_pct >= 24.9:
        return "pct25"
    return "ucretli"


def _apply_exogenous_ranking_shift(
    program: ProgramOffering,
    intervention: UniversityPolicyIntervention,
) -> dict[str, Any]:
    """Apply exogenous prestige/rank_score shift without modifying max_rank_override (ÖSYM baraj)."""
    pct = intervention.ranking_change_pct
    spot_delta = intervention.ranking_rank_delta
    if pct is None and spot_delta is None:
        return {}

    base_prestige = program.effective_prestige_score()
    delta = 0.0
    if pct is not None:
        # Positive pct improves ranking/prestige; negative pct lowers it.
        delta += 0.50 * (float(pct) / 100.0)
    if spot_delta is not None:
        # Positive spot_delta improves by N spots; negative drops by N spots.
        delta += max(-0.45, min(0.45, float(spot_delta) / 150.0))

    new_prestige = round(max(0.02, min(0.99, base_prestige + delta)), 6)
    updates: dict[str, Any] = {"prestige_score": new_prestige}
    if program.university_rank is not None:
        rank_val = program.university_rank
        if pct is not None:
            rank_val = max(1, int(round(rank_val * max(0.1, 1.0 - float(pct) / 100.0))))
        if spot_delta is not None:
            rank_val = max(1, rank_val - int(spot_delta))
        updates["university_rank"] = rank_val
    return updates


def _scale_program_capacities(
    programs: list[ProgramOffering],
    intervention: UniversityPolicyIntervention,
) -> dict[str, int]:
    """Compute new general quota capacities deterministically (scoped to target programs)."""
    targeted_open = [
        i
        for i, p in enumerate(programs)
        if p.status == "open" and p.capacity > 0 and _program_matches_targets(p, intervention)
    ]
    out = {p.program_id: p.capacity for p in programs}
    if intervention.capacity_change_pct is not None and targeted_open:
        factor = max(0.0, 1.0 + intervention.capacity_change_pct / 100.0)
        if intervention.capacity_rounding == "largest_remainder":
            shares = {programs[i].program_id: float(programs[i].capacity) for i in targeted_open}
            total_before = sum(programs[i].capacity for i in targeted_open)
            target_total = max(0, int(round(total_before * factor)))
            if target_total == 0:
                for i in targeted_open:
                    out[programs[i].program_id] = 0
            else:
                out.update(largest_remainder(shares, target_total))
        else:
            for i in targeted_open:
                p = programs[i]
                raw = p.capacity * factor
                if intervention.capacity_rounding == "nearest":
                    out[p.program_id] = max(0, int(round(raw)))
                else:
                    out[p.program_id] = max(0, int(math.floor(raw + 1e-9)))

    if intervention.scholarship_tier_mix:
        tier_map = {k.strip().lower(): float(v) for k, v in intervention.scholarship_tier_mix.items()}
        for i in targeted_open:
            p = programs[i]
            tier = _scholarship_tier_key(p)
            mult = tier_map.get(p.program_id.lower()) or tier_map.get(tier)
            if mult is not None:
                out[p.program_id] = max(0, int(round(out[p.program_id] * mult)))
    return out


def _allocate_need_based_aid(
    candidates: list[CandidateRecord],
    intervention: UniversityPolicyIntervention,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Deterministically allocate need-based grants up to the configured budget cap."""
    existing_total = math.fsum(c.need_aid_grant for c in candidates)
    pct = intervention.aid_budget_change_pct
    base = intervention.base_aid_budget

    if pct is None and base is None:
        return {c.candidate_id: c.need_aid_grant for c in candidates}, {
            "aid_budget_pool": round(existing_total, 2),
            "aid_allocated": round(existing_total, 2),
        }

    if base is not None:
        total_pool = max(0.0, base * (1.0 + (pct or 0.0) / 100.0))
    else:
        total_pool = max(0.0, existing_total * (1.0 + (pct or 0.0) / 100.0))

    if total_pool == 0.0 and existing_total == 0.0:
        return {c.candidate_id: 0.0 for c in candidates}, {
            "aid_budget_pool": 0.0,
            "aid_allocated": 0.0,
            "aid_note": "No base_aid_budget or existing candidate grants supplied; need-based pool remains 0.0.",
        }

    income_rank = {"low": 0, "middle": 1, "high": 2, None: 3}
    eligible: list[CandidateRecord] = []
    for c in candidates:
        if intervention.aid_income_eligibility_max is not None:
            if c.liquid_budget is None or c.liquid_budget > intervention.aid_income_eligibility_max:
                continue
        elif c.income_band == "high" and c.need_aid_grant <= 0.0:
            continue
        eligible.append(c)

    ordered = sorted(
        eligible,
        key=lambda c: (
            income_rank.get(c.income_band, 3),
            c.liquid_budget if c.liquid_budget is not None else float("inf"),
            c.candidate_id,
        ),
    )

    grants: dict[str, float] = {c.candidate_id: 0.0 for c in candidates}
    if not ordered:
        return grants, {"aid_budget_pool": round(total_pool, 2), "aid_allocated": 0.0}

    remaining = total_pool
    cap_per_student = intervention.max_grant_per_student
    scale_factor = (total_pool / existing_total) if existing_total > 0 else None

    if scale_factor is not None and cap_per_student is None:
        # Proportional scaling of existing grants within budget order
        for c in ordered:
            target = round(c.need_aid_grant * scale_factor, 2)
            award = min(remaining, target)
            grants[c.candidate_id] = award
            remaining = round(max(0.0, remaining - award), 2)
            if remaining <= 0.0:
                break
    else:
        default_cap = cap_per_student if cap_per_student is not None else round(total_pool / len(ordered), 2)
        for c in ordered:
            award = min(remaining, default_cap)
            grants[c.candidate_id] = round(award, 2)
            remaining = round(max(0.0, remaining - award), 2)
            if remaining <= 0.0:
                break

    allocated_sum = round(math.fsum(grants.values()), 2)
    return grants, {
        "aid_budget_pool": round(total_pool, 2),
        "aid_allocated": allocated_sum,
        "aid_recipients": sum(1 for v in grants.values() if v > 0.0),
    }


def apply_intervention(
    candidates: list[CandidateRecord],
    programs: list[ProgramOffering],
    ruleset: PlacementRuleset,
    intervention: UniversityPolicyIntervention | None = None,
) -> tuple[list[CandidateRecord], list[ProgramOffering], PlacementRuleset, dict[str, Any]]:
    """Return transformed copies of (candidates, programs, ruleset) plus delta metadata."""
    if intervention is None:
        return (
            [c.model_copy(deep=True) for c in candidates],
            [p.model_copy(deep=True) for p in programs],
            ruleset.model_copy(deep=True),
            {"intervention_applied": False},
        )

    closed_set = set(intervention.closed_programs)
    opened_set = set(intervention.opened_programs)
    scaled_caps = _scale_program_capacities(programs, intervention)
    tuition_factor = (
        max(0.0, 1.0 + intervention.tuition_change_pct / 100.0)
        if intervention.tuition_change_pct is not None
        else 1.0
    )

    new_programs: list[ProgramOffering] = []
    targeted_ids: list[str] = []
    for p in programs:
        is_target = _program_matches_targets(p, intervention)
        if is_target:
            targeted_ids.append(p.program_id)

        updates: dict[str, Any] = {}
        if p.program_id in closed_set:
            updates["status"] = "closed"
        elif p.program_id in opened_set:
            updates["status"] = "open"

        new_cap = intervention.program_capacity_overrides.get(p.program_id, scaled_caps[p.program_id])
        updates["capacity"] = max(0, int(new_cap))

        if p.program_id in intervention.tuition_overrides:
            updates["tuition_annual"] = round(float(intervention.tuition_overrides[p.program_id]), 2)
        elif is_target and intervention.tuition_change_pct is not None and p.tuition_annual > 0.0:
            updates["tuition_annual"] = round(p.tuition_annual * tuition_factor, 2)

        if p.program_id in intervention.min_score_overrides:
            updates["min_score"] = float(intervention.min_score_overrides[p.program_id])

        if is_target:
            updates.update(_apply_exogenous_ranking_shift(p, intervention))

        new_programs.append(p.model_copy(update=updates, deep=True))

    grants, aid_summary = _allocate_need_based_aid(candidates, intervention)
    new_candidates: list[CandidateRecord] = []
    for c in candidates:
        c_updates: dict[str, Any] = {"need_aid_grant": grants[c.candidate_id]}
        if intervention.apply_prior_placement_obp_penalty and c.obp_contribution is not None:
            c_updates["previously_placed_penalty"] = True
        new_candidates.append(c.model_copy(update=c_updates, deep=True))

    new_thresholds = dict(ruleset.rank_thresholds)
    new_thresholds.update(intervention.rank_threshold_overrides)
    rule_updates: dict[str, Any] = {"rank_thresholds": new_thresholds}
    if intervention.ruleset_id:
        rule_updates["ruleset_id"] = intervention.ruleset_id
    if intervention.osym_verified:
        rule_updates["osym_verified"] = True
        rule_updates["rule_fidelity"] = intervention.rule_fidelity
    elif intervention.rule_fidelity != "verified_osym":
        rule_updates["rule_fidelity"] = intervention.rule_fidelity

    new_ruleset = PlacementRuleset.model_validate({**ruleset.model_dump(), **rule_updates})
    metadata = {
        "intervention_applied": True,
        "tuition_change_pct": intervention.tuition_change_pct,
        "capacity_change_pct": intervention.capacity_change_pct,
        "capacity_rounding": intervention.capacity_rounding,
        "affordability_filter_mode": intervention.affordability_filter_mode,
        "installment_count": intervention.installment_count,
        "rank_threshold_overrides": dict(intervention.rank_threshold_overrides),
        "ranking_change_pct": intervention.ranking_change_pct,
        "ranking_rank_delta": intervention.ranking_rank_delta,
        "target_university_ids": list(intervention.target_university_ids),
        "target_program_ids": list(intervention.target_program_ids),
        "target_department_names": list(intervention.target_department_names),
        "targeted_program_count": len(targeted_ids),
        "rivals_fixed": bool(
            intervention.target_university_ids
            or intervention.target_program_ids
            or intervention.target_department_names
        ),
        "apply_prior_placement_obp_penalty": intervention.apply_prior_placement_obp_penalty,
        **aid_summary,
    }
    return new_candidates, new_programs, new_ruleset, metadata
