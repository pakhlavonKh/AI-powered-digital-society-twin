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


def _scale_program_capacities(
    programs: list[ProgramOffering],
    intervention: UniversityPolicyIntervention,
) -> dict[str, int]:
    """Compute new general quota capacities deterministically."""
    open_indices = [i for i, p in enumerate(programs) if p.status == "open" and p.capacity > 0]
    if intervention.capacity_change_pct is None or not open_indices:
        return {p.program_id: p.capacity for p in programs}

    factor = max(0.0, 1.0 + intervention.capacity_change_pct / 100.0)
    out = {p.program_id: p.capacity for p in programs}

    if intervention.capacity_rounding == "largest_remainder":
        shares = {programs[i].program_id: float(programs[i].capacity) for i in open_indices}
        total_before = sum(programs[i].capacity for i in open_indices)
        target_total = max(0, int(round(total_before * factor)))
        if target_total == 0:
            for i in open_indices:
                out[programs[i].program_id] = 0
        else:
            allocated = largest_remainder(shares, target_total)
            out.update(allocated)
        return out

    for i in open_indices:
        p = programs[i]
        raw = p.capacity * factor
        if intervention.capacity_rounding == "nearest":
            out[p.program_id] = max(0, int(round(raw)))
        else:
            out[p.program_id] = max(0, int(math.floor(raw + 1e-9)))
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
    scaled_caps = _scale_program_capacities(programs, intervention)
    tuition_factor = (
        max(0.0, 1.0 + intervention.tuition_change_pct / 100.0)
        if intervention.tuition_change_pct is not None
        else 1.0
    )

    new_programs: list[ProgramOffering] = []
    for p in programs:
        updates: dict[str, Any] = {}
        if p.program_id in closed_set:
            updates["status"] = "closed"
        new_cap = intervention.program_capacity_overrides.get(p.program_id, scaled_caps[p.program_id])
        updates["capacity"] = max(0, int(new_cap))

        if p.program_id in intervention.tuition_overrides:
            updates["tuition_annual"] = round(float(intervention.tuition_overrides[p.program_id]), 2)
        elif intervention.tuition_change_pct is not None and p.tuition_annual > 0.0:
            updates["tuition_annual"] = round(p.tuition_annual * tuition_factor, 2)

        if p.program_id in intervention.min_score_overrides:
            updates["min_score"] = float(intervention.min_score_overrides[p.program_id])

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
        "apply_prior_placement_obp_penalty": intervention.apply_prior_placement_obp_penalty,
        **aid_summary,
    }
    return new_candidates, new_programs, new_ruleset, metadata
