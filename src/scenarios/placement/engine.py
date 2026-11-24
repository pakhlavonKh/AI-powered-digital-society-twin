"""Deterministic university placement engine using Candidate-Proposing Deferred Acceptance.

Milestone 1 models general quotas only, uses fixed-point quantized score
comparison with a strict total-order tie-break chain, enforces post-run
conservation/stability invariants, and records reproducible canonical hashes.
"""

from __future__ import annotations

import hashlib
import heapq
import math
from collections import deque
from dataclasses import dataclass
from typing import Any

try:
    from ..eligibility import EligibilityStatus
    from ..schema import ScenarioConfig, PlacementScenarioConfig, UniversityPolicyIntervention
    from ..university_query import PreferenceModelConfig
    from .eligibility import (
        CandidateEligibilityAudit,
        EligibleChoice,
        derive_cohort_ranks,
        evaluate_candidate_and_choices,
    )
    from .interventions import apply_intervention
    from .models import (
        CandidatePlacementOutcome,
        CandidateRecord,
        PLACEMENT_ENGINE_VERSION,
        PlacementManifest,
        PlacementResult,
        PlacementRuleset,
        ProgramOffering,
        ProgramPlacementOutcome,
        TieBreakEvent,
        TieBreakPolicy,
        catalog_fee_scale,
    )
    from .preference_model import apply_behavioral_preferences
except ImportError:
    from scenarios.eligibility import EligibilityStatus  # type: ignore
    from scenarios.schema import ScenarioConfig, PlacementScenarioConfig, UniversityPolicyIntervention  # type: ignore
    from scenarios.university_query import PreferenceModelConfig  # type: ignore
    from scenarios.placement.eligibility import (  # type: ignore
        CandidateEligibilityAudit,
        EligibleChoice,
        derive_cohort_ranks,
        evaluate_candidate_and_choices,
    )
    from scenarios.placement.interventions import apply_intervention  # type: ignore
    from scenarios.placement.models import (  # type: ignore
        CandidatePlacementOutcome,
        CandidateRecord,
        PLACEMENT_ENGINE_VERSION,
        PlacementManifest,
        PlacementResult,
        PlacementRuleset,
        ProgramOffering,
        ProgramPlacementOutcome,
        TieBreakEvent,
        TieBreakPolicy,
        catalog_fee_scale,
    )
    from scenarios.placement.preference_model import apply_behavioral_preferences  # type: ignore

from societytwin.common import canonical_hash


class PlacementInvariantError(RuntimeError):
    """Raised if post-allocation conservation or stability invariants fail."""


@dataclass(frozen=True, order=True)
class _CandidatePriority:
    """Strict total order where smaller tuple means strictly better priority."""

    neg_eff_score_q: int
    neg_raw_score_q: int
    neg_obp_q: int
    pref_rank_key: int
    age_key: int
    terminal_key: str
    candidate_id: str


@dataclass(frozen=True)
class _WorstFirst:
    """Heap wrapper reversing _CandidatePriority so heapq[0] is always the weakest held."""

    priority: _CandidatePriority
    candidate_id: str
    choice: EligibleChoice

    def __lt__(self, other: _WorstFirst) -> bool:
        return other.priority < self.priority


def _quantize(value: float | None, precision: int) -> int:
    if value is None:
        return -1
    return int(round(float(value) * (10 ** precision)))


def _build_priority(
    candidate: CandidateRecord,
    choice: EligibleChoice,
    ruleset: PlacementRuleset,
) -> _CandidatePriority:
    tb: TieBreakPolicy = ruleset.tie_break_policy
    prec = ruleset.score_precision_decimals

    neg_eff = -_quantize(choice.effective_score, prec)
    neg_raw = -_quantize(choice.raw_score, prec) if tb.use_raw_score else 0
    neg_obp = -_quantize(choice.obp_contribution, prec) if tb.use_obp else 0
    pref_rank_key = choice.submitted_rank if tb.prefer_earlier_choice else 0

    if tb.age_tie_rule == "younger_first":
        age_key = candidate.age if candidate.age is not None else 10_000
    elif tb.age_tie_rule == "older_first":
        age_key = -(candidate.age if candidate.age is not None else -1)
    else:
        age_key = 0

    if tb.terminal_tie_breaker == "seeded_hash":
        raw_token = f"{tb.tie_seed}:{choice.program_id}:{candidate.candidate_id}".encode("utf-8")
        terminal_key = hashlib.sha256(raw_token).hexdigest()
    else:
        terminal_key = candidate.candidate_id

    return _CandidatePriority(
        neg_eff_score_q=neg_eff,
        neg_raw_score_q=neg_raw,
        neg_obp_q=neg_obp,
        pref_rank_key=pref_rank_key,
        age_key=age_key,
        terminal_key=terminal_key,
        candidate_id=candidate.candidate_id,
    )


def _deciding_tie_criterion(winner: _CandidatePriority, loser: _CandidatePriority, tb: TieBreakPolicy) -> str:
    if winner.neg_raw_score_q != loser.neg_raw_score_q:
        return "raw_score"
    if winner.neg_obp_q != loser.neg_obp_q:
        return "obp_contribution"
    if winner.pref_rank_key != loser.pref_rank_key:
        return "preference_rank"
    if winner.age_key != loser.age_key:
        return f"age_{tb.age_tie_rule}"
    return f"terminal_{tb.terminal_tie_breaker}"


def _verify_invariants(
    candidates_sorted: list[CandidateRecord],
    programs_by_id: dict[str, ProgramOffering],
    audits: dict[str, CandidateEligibilityAudit],
    held_choice: dict[str, EligibleChoice],
    program_heaps: dict[str, list[_WorstFirst]],
    ruleset: PlacementRuleset,
) -> None:
    """Verify seat conservation, unique assignment, eligibility, and stability (no justified envy)."""
    cands_by_id = {c.candidate_id: c for c in candidates_sorted}

    # 1. Capacity conservation
    for pid, prog in programs_by_id.items():
        filled = len(program_heaps.get(pid, []))
        if filled < 0 or filled > prog.capacity:
            raise PlacementInvariantError(f"Capacity violation in {pid}: filled={filled}, capacity={prog.capacity}")

    # 2. Unique assignment & partition completeness
    placed_ids = set(held_choice.keys())
    all_ids = {c.candidate_id for c in candidates_sorted}
    if not placed_ids.issubset(all_ids):
        raise PlacementInvariantError("Unknown candidate ID found in placed set.")

    # 3. Stability / No justified envy
    weakest_in_program: dict[str, _CandidatePriority] = {}
    for pid, heap in program_heaps.items():
        if heap:
            weakest_in_program[pid] = heap[0].priority

    for cand in candidates_sorted:
        cid = cand.candidate_id
        audit = audits[cid]
        if audit.status != EligibilityStatus.ELIGIBLE:
            if cid in held_choice:
                raise PlacementInvariantError(f"Ineligible candidate {cid} was placed.")
            continue

        assigned = held_choice.get(cid)
        if assigned is not None:
            assigned_pids = [ch.program_id for ch in audit.eligible_choices]
            if assigned.program_id not in assigned_pids:
                raise PlacementInvariantError(f"Candidate {cid} placed in non-eligible program {assigned.program_id}")
            stop_idx = assigned_pids.index(assigned.program_id)
        else:
            stop_idx = len(audit.eligible_choices)

        for preferred in audit.eligible_choices[:stop_idx]:
            pid = preferred.program_id
            prog = programs_by_id[pid]
            held_count = len(program_heaps.get(pid, []))
            if held_count < prog.capacity:
                raise PlacementInvariantError(
                    f"Stability violation: candidate {cid} preferred {pid} which has unfilled seats ({held_count}/{prog.capacity})."
                )
            if prog.capacity > 0:
                cand_prio = _build_priority(cand, preferred, ruleset)
                if cand_prio < weakest_in_program[pid]:
                    raise PlacementInvariantError(
                        f"Justified envy violation: candidate {cid} outranks weakest admitted in {pid}."
                    )


def _compute_subgroup_metrics(
    candidates_sorted: list[CandidateRecord],
    outcomes: list[CandidatePlacementOutcome],
    min_group: int,
) -> dict[str, Any]:
    """Compute subgroup placement rates with configurable small-cell suppression."""
    cand_map = {c.candidate_id: c for c in candidates_sorted}
    groups: dict[str, Any] = {}

    for field in ("province_code", "sex", "income_band", "score_type_used"):
        buckets: dict[str, list[CandidatePlacementOutcome]] = {}
        for out in outcomes:
            if field == "score_type_used":
                val = out.score_type_used or "unplaced_or_none"
            else:
                raw = getattr(cand_map[out.candidate_id], field)
                val = str(raw) if raw is not None else "unavailable"
            buckets.setdefault(val, []).append(out)

        entries: list[dict[str, Any]] = []
        for val in sorted(buckets):
            rows = buckets[val]
            total = len(rows)
            if total < min_group:
                entries.append({
                    "value": val,
                    "candidates": total,
                    "suppressed": True,
                    "reason": f"Fewer than {min_group} candidates; suppressed.",
                })
                continue
            placed = sum(1 for r in rows if r.placement_status == "placed")
            first_choice = sum(1 for r in rows if r.assigned_preference_rank == 1)
            entries.append({
                "value": val,
                "candidates": total,
                "suppressed": False,
                "placed_count": placed,
                "placement_rate": round(placed / total, 4) if total else 0.0,
                "first_choice_count": first_choice,
                "first_choice_rate": round(first_choice / total, 4) if total else 0.0,
            })
        groups[field] = {"min_group_candidates": min_group, "groups": entries}

    return groups


def _build_candidate_outcomes(
    eff_cands_sorted: list[CandidateRecord],
    audits: dict[str, CandidateEligibilityAudit],
    held_choice: dict[str, EligibleChoice],
) -> tuple[list[CandidatePlacementOutcome], dict[str, int], dict[str, int]]:
    outcomes: list[CandidatePlacementOutcome] = []
    unplaced_reasons: dict[str, int] = {}
    unavailable_reasons: dict[str, int] = {}

    for cand in eff_cands_sorted:
        cid = cand.candidate_id
        audit = audits[cid]
        for ev in audit.preference_evaluations:
            if ev.status == "unavailable":
                unavailable_reasons[ev.reason_code] = unavailable_reasons.get(ev.reason_code, 0) + 1

        if audit.status == EligibilityStatus.CANNOT_EVALUATE:
            unplaced_reasons["CANNOT_EVALUATE"] = unplaced_reasons.get("CANNOT_EVALUATE", 0) + 1
            outcomes.append(
                CandidatePlacementOutcome(
                    candidate_id=cid,
                    source_synthetic_id=cand.source_synthetic_id,
                    eligibility_status="cannot_evaluate",
                    placement_status="not_applicable",
                    unplaced_reason="CANNOT_EVALUATE",
                    missing_attributes=audit.missing_attributes,
                    preference_evaluations=audit.preference_evaluations,
                )
            )
            continue

        if audit.status == EligibilityStatus.EXCLUDED:
            unplaced_reasons["CANDIDATE_EXCLUDED"] = unplaced_reasons.get("CANDIDATE_EXCLUDED", 0) + 1
            outcomes.append(
                CandidatePlacementOutcome(
                    candidate_id=cid,
                    source_synthetic_id=cand.source_synthetic_id,
                    eligibility_status="excluded",
                    placement_status="not_applicable",
                    unplaced_reason="CANDIDATE_EXCLUDED",
                    exclusion_reasons=audit.exclusion_reasons,
                    preference_evaluations=audit.preference_evaluations,
                )
            )
            continue

        assigned = held_choice.get(cid)
        if assigned is not None:
            outcomes.append(
                CandidatePlacementOutcome(
                    candidate_id=cid,
                    source_synthetic_id=cand.source_synthetic_id,
                    eligibility_status="eligible",
                    placement_status="placed",
                    assigned_program_id=assigned.program_id,
                    quota_bucket="general",
                    assigned_preference_rank=assigned.submitted_rank,
                    score_type_used=assigned.score_type,
                    effective_score=assigned.effective_score,
                    rank_used=assigned.rank_used,
                    rank_source=assigned.rank_source,  # type: ignore[arg-type]
                    financials=assigned.financials,
                    preference_evaluations=audit.preference_evaluations,
                )
            )
            continue

        if not cand.preferences:
            reason = "NO_PREFERENCES"
        elif not audit.eligible_choices:
            reason = "NO_ELIGIBLE_CHOICES"
        else:
            reason = "CAPACITY_EXHAUSTED"
        unplaced_reasons[reason] = unplaced_reasons.get(reason, 0) + 1
        outcomes.append(
            CandidatePlacementOutcome(
                candidate_id=cid,
                source_synthetic_id=cand.source_synthetic_id,
                eligibility_status="eligible",
                placement_status="unplaced",
                unplaced_reason=reason,
                preference_evaluations=audit.preference_evaluations,
            )
        )

    return outcomes, unplaced_reasons, unavailable_reasons


def _build_program_outcomes(
    eff_cands_sorted: list[CandidateRecord],
    eff_progs_sorted: list[ProgramOffering],
    initial_caps: dict[str, int],
    audits: dict[str, CandidateEligibilityAudit],
    program_heaps: dict[str, list[_WorstFirst]],
    tie_events: list[TieBreakEvent],
    *,
    top_k: int = 3,
    pre_dropped_affordability: dict[str, int] | None = None,
) -> list[ProgramPlacementOutcome]:
    program_ties: dict[str, list[TieBreakEvent]] = {}
    for ev in tie_events:
        program_ties.setdefault(ev.program_id, []).append(ev)

    eligible_applicants: dict[str, set[str]] = {p.program_id: set() for p in eff_progs_sorted}
    listed_anywhere: dict[str, set[str]] = {p.program_id: set() for p in eff_progs_sorted}
    listed_top_k: dict[str, set[str]] = {p.program_id: set() for p in eff_progs_sorted}
    first_choice_counts: dict[str, int] = {p.program_id: 0 for p in eff_progs_sorted}
    ineligible_by_prog: dict[str, dict[str, int]] = {p.program_id: {} for p in eff_progs_sorted}

    for cand in eff_cands_sorted:
        seen_raw: set[str] = set()
        for rank_idx, pid in enumerate(cand.preferences, start=1):
            if pid in listed_anywhere and pid not in seen_raw:
                seen_raw.add(pid)
                listed_anywhere[pid].add(cand.candidate_id)
                if rank_idx <= top_k:
                    listed_top_k[pid].add(cand.candidate_id)

        audit = audits[cand.candidate_id]
        if audit.eligible_choices:
            first_pid = audit.eligible_choices[0].program_id
            if first_pid in first_choice_counts:
                first_choice_counts[first_pid] += 1
        for ch in audit.eligible_choices:
            if ch.program_id in eligible_applicants:
                eligible_applicants[ch.program_id].add(cand.candidate_id)
        for ev in audit.preference_evaluations:
            if ev.status == "unavailable" and ev.program_id in ineligible_by_prog:
                counts = ineligible_by_prog[ev.program_id]
                counts[ev.reason_code] = counts.get(ev.reason_code, 0) + 1

    outcomes: list[ProgramPlacementOutcome] = []
    for prog in eff_progs_sorted:
        pid = prog.program_id
        admitted = program_heaps.get(pid, [])
        filled = len(admitted)
        remaining = max(0, prog.capacity - filled)
        fill_rate = round(filled / prog.capacity, 4) if prog.capacity > 0 else 0.0

        if admitted:
            sorted_admitted = sorted(admitted, key=lambda item: item.priority)
            highest = sorted_admitted[0].choice.effective_score
            weakest = sorted_admitted[-1]
            cutoff_score = weakest.choice.effective_score
            cutoff_rank = weakest.choice.rank_used
        else:
            highest = cutoff_score = cutoff_rank = None

        aff_drops = ineligible_by_prog[pid].get("AFFORDABILITY_EXCLUDED", 0)
        if pre_dropped_affordability and pid in pre_dropped_affordability:
            aff_drops += int(pre_dropped_affordability[pid])

        outcomes.append(
            ProgramPlacementOutcome(
                program_id=pid,
                university_name=prog.university_name,
                department_name=prog.department_name,
                province_code=prog.province_code,
                score_type=prog.score_type,
                quota_bucket="general",
                initial_capacity=initial_caps[pid],
                effective_capacity=prog.capacity,
                status=prog.status,
                filled=filled,
                remaining_seats=remaining,
                fill_rate=fill_rate,
                cutoff_score=cutoff_score,
                cutoff_is_binding=(prog.capacity > 0 and filled == prog.capacity),
                highest_score=highest,
                cutoff_rank=cutoff_rank,
                applicant_count=len(eligible_applicants[pid]),
                listed_anywhere_count=len(listed_anywhere[pid]),
                listed_top_k_count=len(listed_top_k[pid]),
                first_choice_count=first_choice_counts[pid],
                dropped_due_to_affordability=aff_drops,
                ineligible_attempts_by_reason=ineligible_by_prog[pid],
                tie_breaks_at_cutoff=sorted(
                    program_ties.get(pid, []),
                    key=lambda e: (e.admitted_candidate_id, e.displaced_candidate_id),
                ),
            )
        )
    return outcomes


def _build_aggregate_metrics(
    candidate_outcomes: list[CandidatePlacementOutcome],
    program_outcomes: list[ProgramPlacementOutcome],
    unplaced_reasons: dict[str, int],
    unavailable_reasons: dict[str, int],
    tie_count: int,
    intervention_meta: dict[str, Any],
) -> dict[str, Any]:
    total_cands = len(candidate_outcomes)
    eligible_cands = sum(1 for o in candidate_outcomes if o.eligibility_status == "eligible")
    excluded_cands = sum(1 for o in candidate_outcomes if o.eligibility_status == "excluded")
    cannot_eval_cands = sum(1 for o in candidate_outcomes if o.eligibility_status == "cannot_evaluate")
    placed = [o for o in candidate_outcomes if o.placement_status == "placed"]
    placed_count = len(placed)
    unplaced_count = sum(1 for o in candidate_outcomes if o.placement_status == "unplaced")
    first_choice = sum(1 for o in placed if o.assigned_preference_rank == 1)
    top_3 = sum(1 for o in placed if o.assigned_preference_rank is not None and o.assigned_preference_rank <= 3)
    assigned_ranks = [o.assigned_preference_rank for o in placed if o.assigned_preference_rank is not None]
    total_cap = sum(p.effective_capacity for p in program_outcomes if p.status == "open")
    total_filled = sum(p.filled for p in program_outcomes)

    gross = round(math.fsum(o.financials.gross_tuition for o in placed if o.financials), 2)
    disc = round(math.fsum(o.financials.scholarship_discount for o in placed if o.financials), 2)
    aid = round(math.fsum(o.financials.need_aid_grant for o in placed if o.financials), 2)
    net = round(math.fsum(o.financials.net_tuition for o in placed if o.financials), 2)
    gaps = [o.financials.liquidity_gap for o in placed if o.financials and o.financials.liquidity_gap is not None]

    return {
        "total_candidates": total_cands,
        "eligible_candidates": eligible_cands,
        "excluded_candidates": excluded_cands,
        "cannot_evaluate_candidates": cannot_eval_cands,
        "placed_count": placed_count,
        "unplaced_count": unplaced_count,
        "placement_rate": round(placed_count / total_cands, 4) if total_cands else 0.0,
        "eligible_placement_rate": round(placed_count / eligible_cands, 4) if eligible_cands else 0.0,
        "first_choice_count": first_choice,
        "first_choice_rate": round(first_choice / placed_count, 4) if placed_count else 0.0,
        "top_3_choice_count": top_3,
        "top_3_choice_rate": round(top_3 / placed_count, 4) if placed_count else 0.0,
        "mean_assigned_rank": round(math.fsum(assigned_ranks) / len(assigned_ranks), 4) if assigned_ranks else None,
        "total_capacity": total_cap,
        "total_filled": total_filled,
        "seat_utilization_rate": round(total_filled / total_cap, 4) if total_cap else 0.0,
        "total_gross_tuition": gross,
        "total_scholarship_discounts": disc,
        "total_need_aid_disbursed": aid,
        "total_net_tuition_revenue": net,
        "mean_net_tuition": round(net / placed_count, 2) if placed_count else 0.0,
        "students_with_liquidity_gap": sum(1 for g in gaps if g > 0.0),
        "mean_liquidity_gap": round(math.fsum(gaps) / len(gaps), 2) if gaps else 0.0,
        "unplaced_reasons_breakdown": dict(sorted(unplaced_reasons.items())),
        "unavailable_choice_reasons_breakdown": dict(sorted(unavailable_reasons.items())),
        "tie_break_count": tie_count,
        "intervention_metadata": intervention_meta,
    }


def _run_deferred_acceptance(
    eff_cands_sorted: list[CandidateRecord],
    eff_progs_sorted: list[ProgramOffering],
    audits: dict[str, CandidateEligibilityAudit],
    eff_ruleset: PlacementRuleset,
) -> tuple[dict[str, EligibleChoice], dict[str, list[_WorstFirst]], list[TieBreakEvent]]:
    """Run Candidate-Proposing DA with fixed-point priority tie-breaking."""
    cands_by_id = {c.candidate_id: c for c in eff_cands_sorted}
    programs_by_id = {p.program_id: p for p in eff_progs_sorted}
    program_heaps: dict[str, list[_WorstFirst]] = {
        p.program_id: [] for p in eff_progs_sorted if p.status == "open" and p.capacity > 0
    }
    held_choice: dict[str, EligibleChoice] = {}
    proposal_ptr: dict[str, int] = {}
    unmatched: deque[str] = deque()
    tie_events: list[TieBreakEvent] = []
    seen_tie_keys: set[tuple[str, str, str]] = set()

    for cand in eff_cands_sorted:
        audit = audits[cand.candidate_id]
        if audit.status == EligibilityStatus.ELIGIBLE and audit.eligible_choices:
            proposal_ptr[cand.candidate_id] = 0
            unmatched.append(cand.candidate_id)

    while unmatched:
        cid = unmatched.popleft()
        choices = audits[cid].eligible_choices
        idx = proposal_ptr[cid]
        if idx >= len(choices):
            continue
        proposal_ptr[cid] = idx + 1
        choice = choices[idx]
        pid = choice.program_id
        prog = programs_by_id[pid]
        heap = program_heaps[pid]
        cand_prio = _build_priority(cands_by_id[cid], choice, eff_ruleset)

        if len(heap) < prog.capacity:
            heapq.heappush(heap, _WorstFirst(cand_prio, cid, choice))
            held_choice[cid] = choice
            continue

        weakest = heap[0]
        if cand_prio < weakest.priority:
            if cand_prio.neg_eff_score_q == weakest.priority.neg_eff_score_q:
                sig = (pid, cid, weakest.candidate_id)
                if sig not in seen_tie_keys:
                    seen_tie_keys.add(sig)
                    tie_events.append(
                        TieBreakEvent(
                            program_id=pid,
                            quota_bucket="general",
                            tied_effective_score=choice.effective_score,
                            admitted_candidate_id=cid,
                            displaced_candidate_id=weakest.candidate_id,
                            deciding_criterion=_deciding_tie_criterion(
                                cand_prio, weakest.priority, eff_ruleset.tie_break_policy
                            ),
                        )
                    )
            heapq.heapreplace(heap, _WorstFirst(cand_prio, cid, choice))
            held_choice[cid] = choice
            held_choice.pop(weakest.candidate_id, None)
            unmatched.append(weakest.candidate_id)
        else:
            if cand_prio.neg_eff_score_q == weakest.priority.neg_eff_score_q:
                sig = (pid, weakest.candidate_id, cid)
                if sig not in seen_tie_keys:
                    seen_tie_keys.add(sig)
                    tie_events.append(
                        TieBreakEvent(
                            program_id=pid,
                            quota_bucket="general",
                            tied_effective_score=choice.effective_score,
                            admitted_candidate_id=weakest.candidate_id,
                            displaced_candidate_id=cid,
                            deciding_criterion=_deciding_tie_criterion(
                                weakest.priority, cand_prio, eff_ruleset.tie_break_policy
                            ),
                        )
                    )
            unmatched.append(cid)

    return held_choice, program_heaps, tie_events


def run_placement(
    candidates: list[CandidateRecord],
    programs: list[ProgramOffering],
    ruleset: PlacementRuleset | None = None,
    intervention: UniversityPolicyIntervention | None = None,
    scenario: ScenarioConfig | PlacementScenarioConfig | None = None,
    seed: int | None = None,
    min_group: int = 1,
    preference_config: PreferenceModelConfig | None = None,
    preference_cache: dict[str, Any] | None = None,
) -> PlacementResult:
    """Execute deterministic Candidate-Proposing Deferred Acceptance over general quotas."""
    base_ruleset = ruleset or PlacementRuleset()
    if intervention is None and scenario is not None:
        intervention = (
            scenario.university_intervention
            if isinstance(scenario, PlacementScenarioConfig)
            else scenario.university_intervention
        )

    base_cands_sorted = sorted(candidates, key=lambda c: c.candidate_id)
    base_progs_sorted = sorted(programs, key=lambda p: p.program_id)

    candidates_sha256 = canonical_hash([c.model_dump(mode="json") for c in base_cands_sorted])
    programs_sha256 = canonical_hash([p.model_dump(mode="json") for p in base_progs_sorted])
    ruleset_sha256 = canonical_hash(base_ruleset.model_dump(mode="json"))
    intervention_sha256 = (
        canonical_hash(intervention.model_dump(mode="json")) if intervention is not None else None
    )
    scenario_sha256 = canonical_hash(scenario.model_dump(mode="json")) if scenario is not None else None

    eff_cands, eff_progs, eff_ruleset, intervention_meta = apply_intervention(
        base_cands_sorted,
        base_progs_sorted,
        base_ruleset,
        intervention,
    )
    if seed is not None and eff_ruleset.tie_break_policy.tie_seed != seed:
        eff_ruleset = eff_ruleset.model_copy(
            update={"tie_break_policy": eff_ruleset.tie_break_policy.model_copy(update={"tie_seed": seed})}
        )

    eff_cands_sorted = sorted(eff_cands, key=lambda c: c.candidate_id)
    eff_progs_sorted = sorted(eff_progs, key=lambda p: p.program_id)

    pre_dropped_counts: dict[str, int] | None = None
    top_k = preference_config.top_k_definition if preference_config is not None else 3
    if preference_config is not None and preference_config.enabled:
        # Anchor utility cost denominator and reachability baseline rank to pre-intervention catalog
        # so policy shifts do not distort their own reference frame.
        is_multi_major = len(base_progs_sorted) > 30
        baseline_cost_unit = round(100_000.0 * catalog_fee_scale(base_progs_sorted) * (1.35 if is_multi_major else 1.0), 2)
        baseline_ranks = {p.program_id: p.university_rank for p in base_progs_sorted}
        eff_cands_sorted, pre_dropped_counts, _ = apply_behavioral_preferences(
            eff_cands_sorted,
            eff_progs_sorted,
            eff_ruleset,
            intervention,
            preference_config,
            seed=eff_ruleset.tie_break_policy.tie_seed,
            cost_unit=baseline_cost_unit,
            baseline_ranks=baseline_ranks,
            preference_cache=preference_cache,
        )
        intervention_meta = {
            **intervention_meta,
            "preference_model_enabled": True,
            "elasticity_preset": preference_config.elasticity_preset,
            "coefficients_calibrated": preference_config.coefficients_calibrated,
            "top_k_definition": top_k,
        }

    initial_caps = {p.program_id: p.capacity for p in base_progs_sorted}
    programs_by_id = {p.program_id: p for p in eff_progs_sorted}
    derived_ranks = derive_cohort_ranks(eff_cands_sorted, eff_ruleset)

    audits = {
        cand.candidate_id: evaluate_candidate_and_choices(
            candidate=cand,
            programs_by_id=programs_by_id,
            ruleset=eff_ruleset,
            derived_ranks=derived_ranks.get(cand.candidate_id),
            intervention=intervention,
        )
        for cand in eff_cands_sorted
    }

    held_choice, program_heaps, tie_events = _run_deferred_acceptance(
        eff_cands_sorted, eff_progs_sorted, audits, eff_ruleset
    )
    _verify_invariants(
        candidates_sorted=eff_cands_sorted,
        programs_by_id=programs_by_id,
        audits=audits,
        held_choice=held_choice,
        program_heaps=program_heaps,
        ruleset=eff_ruleset,
    )

    candidate_outcomes, unplaced_reasons, unavailable_reasons = _build_candidate_outcomes(
        eff_cands_sorted, audits, held_choice
    )
    program_outcomes = _build_program_outcomes(
        eff_cands_sorted,
        eff_progs_sorted,
        initial_caps,
        audits,
        program_heaps,
        tie_events,
        top_k=top_k,
        pre_dropped_affordability=pre_dropped_counts,
    )
    aggregate_metrics = _build_aggregate_metrics(
        candidate_outcomes, program_outcomes, unplaced_reasons, unavailable_reasons, len(tie_events), intervention_meta
    )
    subgroup_metrics = _compute_subgroup_metrics(eff_cands_sorted, candidate_outcomes, min_group=max(1, min_group))
    sorted_ties = sorted(tie_events, key=lambda e: (e.program_id, e.admitted_candidate_id, e.displaced_candidate_id))

    result_sha256 = canonical_hash(
        {
            "engine_version": PLACEMENT_ENGINE_VERSION,
            "candidates_sha256": candidates_sha256,
            "programs_sha256": programs_sha256,
            "ruleset_sha256": ruleset_sha256,
            "intervention_sha256": intervention_sha256,
            "seed": eff_ruleset.tie_break_policy.tie_seed,
            "candidate_outcomes": [o.model_dump(mode="json") for o in candidate_outcomes],
            "program_outcomes": [p.model_dump(mode="json") for p in program_outcomes],
            "aggregate_metrics": aggregate_metrics,
        }
    )

    manifest = PlacementManifest(
        engine_version=PLACEMENT_ENGINE_VERSION,
        scenario_id=scenario.scenario_id if scenario is not None else None,
        scenario_version=scenario.version if scenario is not None else None,
        scenario_sha256=scenario_sha256,
        candidates_sha256=candidates_sha256,
        programs_sha256=programs_sha256,
        ruleset_sha256=ruleset_sha256,
        intervention_sha256=intervention_sha256,
        result_sha256=result_sha256,
        seed=eff_ruleset.tie_break_policy.tie_seed,
        affordability_filter_mode=(
            intervention.affordability_filter_mode if intervention is not None else "none"
        ),
        quota_scope="general_only",
        rule_fidelity=eff_ruleset.rule_fidelity,
        osym_verified=eff_ruleset.osym_verified,
        disclaimer=eff_ruleset.disclosure_banner(),
        invariants_passed=True,
    )

    return PlacementResult(
        manifest=manifest,
        candidate_outcomes=candidate_outcomes,
        program_outcomes=program_outcomes,
        aggregate_metrics=aggregate_metrics,
        subgroup_metrics=subgroup_metrics,
        tie_break_events=sorted_ties,
    )
