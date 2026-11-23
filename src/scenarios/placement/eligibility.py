"""Candidate and per-choice eligibility checks for offline university placement.

Reuses the fail-closed EligibilityStatus taxonomy of scenarios.eligibility:
missing required attributes produce CANNOT_EVALUATE rather than silent guesses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from ..eligibility import EligibilityStatus
    from ..schema import AffordabilityFilterMode, UniversityPolicyIntervention
    from .models import (
        CandidateFinancials,
        CandidateRecord,
        ChoiceEvaluation,
        PlacementRuleset,
        ProgramOffering,
        ScoreType,
        VALID_SCORE_TYPES,
    )
except ImportError:
    from scenarios.eligibility import EligibilityStatus  # type: ignore
    from scenarios.schema import AffordabilityFilterMode, UniversityPolicyIntervention  # type: ignore
    from scenarios.placement.models import (  # type: ignore
        CandidateFinancials,
        CandidateRecord,
        ChoiceEvaluation,
        PlacementRuleset,
        ProgramOffering,
        ScoreType,
        VALID_SCORE_TYPES,
    )


@dataclass(frozen=True)
class EligibleChoice:
    """Validated eligible program choice queued for the allocation engine."""

    program_id: str
    submitted_rank: int
    score_type: ScoreType
    effective_score: float
    raw_score: float | None
    obp_contribution: float | None
    rank_used: int | None
    rank_source: str
    financials: CandidateFinancials


@dataclass
class CandidateEligibilityAudit:
    """Complete Phase A + Phase B eligibility audit for one candidate."""

    candidate_id: str
    status: EligibilityStatus
    missing_attributes: list[str] = field(default_factory=list)
    exclusion_reasons: list[str] = field(default_factory=list)
    eligible_choices: list[EligibleChoice] = field(default_factory=list)
    preference_evaluations: list[ChoiceEvaluation] = field(default_factory=list)


def resolve_effective_score(
    candidate: CandidateRecord,
    score_type: ScoreType,
    ruleset: PlacementRuleset,
) -> float | None:
    """Compute effective placement score after optional prior-placement OBP penalty."""
    base = candidate.scores.get(score_type)
    if base is None:
        return None
    score = float(base)
    if candidate.previously_placed_penalty and candidate.obp_contribution is not None:
        penalty = float(candidate.obp_contribution) * (1.0 - ruleset.prior_placement_obp_multiplier)
        score = max(0.0, score - penalty)
    return round(score, ruleset.score_precision_decimals)


def derive_cohort_ranks(
    candidates: list[CandidateRecord],
    ruleset: PlacementRuleset,
) -> dict[str, dict[ScoreType, int]]:
    """Deterministically compute competition ranks (1, 1, 3...) per score type within the cohort."""
    derived: dict[str, dict[ScoreType, int]] = {c.candidate_id: {} for c in candidates}
    if not ruleset.derive_ranks_from_cohort:
        return derived

    scale = 10 ** ruleset.score_precision_decimals
    for score_type in VALID_SCORE_TYPES:
        scored: list[tuple[int, str]] = []
        for cand in candidates:
            eff = resolve_effective_score(cand, score_type, ruleset)
            if eff is not None:
                scored.append((int(round(eff * scale)), cand.candidate_id))
        scored.sort(key=lambda item: (-item[0], item[1]))

        prev_score_q: int | None = None
        current_rank = 0
        for idx, (score_q, cid) in enumerate(scored, start=1):
            if score_q != prev_score_q:
                current_rank = idx
                prev_score_q = score_q
            derived[cid][score_type] = current_rank

    return derived


def compute_candidate_program_financials(
    candidate: CandidateRecord,
    program: ProgramOffering,
    intervention: UniversityPolicyIntervention | None = None,
) -> CandidateFinancials:
    """Compute net tuition, scholarship discount, grants, and upfront liquidity gap."""
    gross = float(program.tuition_annual)
    published = program.published_net_tuition_before_aid()
    scholarship_discount = round(max(0.0, gross - published), 2)
    need_grant = round(min(published, float(candidate.need_aid_grant)), 2)
    net_tuition = round(max(0.0, published - need_grant), 2)

    upfront_share = 1.0
    if intervention is not None:
        if intervention.installment_upfront_share is not None:
            upfront_share = float(intervention.installment_upfront_share)
        elif intervention.installment_count is not None and intervention.installment_count > 1:
            upfront_share = 1.0 / float(intervention.installment_count)

    payments_due_upfront = round(net_tuition * upfront_share, 2)
    liquidity_gap: float | None = None
    if candidate.liquid_budget is not None:
        liquidity_gap = round(max(0.0, payments_due_upfront - float(candidate.liquid_budget)), 2)

    return CandidateFinancials(
        gross_tuition=round(gross, 2),
        scholarship_discount=scholarship_discount,
        published_tuition=published,
        need_aid_grant=need_grant,
        net_tuition=net_tuition,
        payments_due_upfront=payments_due_upfront,
        liquidity_gap=liquidity_gap,
    )


def _check_special_conditions(
    candidate: CandidateRecord,
    program: ProgramOffering,
) -> tuple[str, str] | None:
    cond = program.special_conditions
    if cond.required_sex is not None:
        if candidate.sex is None or candidate.sex == "":
            return ("MISSING_ELIGIBILITY_ATTR", f"Program '{program.program_id}' requires sex, which is missing.")
        if candidate.sex.lower() != cond.required_sex.lower():
            return (
                "SPECIAL_CONDITION_NOT_MET",
                f"Program '{program.program_id}' requires sex='{cond.required_sex}', candidate has '{candidate.sex}'.",
            )
    if cond.min_age is not None or cond.max_age is not None:
        if candidate.age is None:
            return ("MISSING_ELIGIBILITY_ATTR", f"Program '{program.program_id}' has age bounds, but age is missing.")
        if cond.min_age is not None and candidate.age < cond.min_age:
            return (
                "SPECIAL_CONDITION_NOT_MET",
                f"Candidate age {candidate.age} is below program minimum {cond.min_age}.",
            )
        if cond.max_age is not None and candidate.age > cond.max_age:
            return (
                "SPECIAL_CONDITION_NOT_MET",
                f"Candidate age {candidate.age} exceeds program maximum {cond.max_age}.",
            )
    return None


def _resolve_rank(
    candidate: CandidateRecord,
    score_type: ScoreType,
    derived_ranks: dict[ScoreType, int] | None,
) -> tuple[int | None, str]:
    explicit = candidate.ranks.get(score_type)
    if explicit is not None:
        return explicit, "explicit"
    if derived_ranks and score_type in derived_ranks:
        return derived_ranks[score_type], "cohort_derived"
    return None, "none"


def _evaluate_single_choice(
    rank_idx: int,
    pid: str,
    candidate: CandidateRecord,
    program: ProgramOffering | None,
    ruleset: PlacementRuleset,
    derived_ranks: dict[ScoreType, int] | None,
    intervention: UniversityPolicyIntervention | None,
    affordability_mode: AffordabilityFilterMode,
) -> tuple[ChoiceEvaluation, EligibleChoice | None]:
    """Validate one candidate preference against catalog, score, baraj, and affordability rules."""
    if program is None:
        return (
            ChoiceEvaluation(
                submitted_rank=rank_idx,
                program_id=pid,
                status="unavailable",
                reason_code="UNKNOWN_PROGRAM",
                detail=f"Program '{pid}' is not present in the active catalog.",
            ),
            None,
        )
    if program.status != "open":
        return (
            ChoiceEvaluation(
                submitted_rank=rank_idx,
                program_id=pid,
                status="unavailable",
                reason_code="PROGRAM_CLOSED",
                detail=f"Program '{pid}' has status '{program.status}'.",
            ),
            None,
        )
    if program.capacity <= 0:
        return (
            ChoiceEvaluation(
                submitted_rank=rank_idx,
                program_id=pid,
                status="unavailable",
                reason_code="ZERO_CAPACITY",
                detail=f"Program '{pid}' has zero general quota seats available.",
            ),
            None,
        )

    eff_score = resolve_effective_score(candidate, program.score_type, ruleset)
    if eff_score is None:
        return (
            ChoiceEvaluation(
                submitted_rank=rank_idx,
                program_id=pid,
                status="unavailable",
                reason_code="SCORE_TYPE_MISMATCH",
                detail=f"Candidate has no valid '{program.score_type}' score for program '{pid}'.",
            ),
            None,
        )

    if ruleset.require_tyt_for_bachelor and program.degree_level == "bachelor":
        if resolve_effective_score(candidate, "TYT", ruleset) is None:
            return (
                ChoiceEvaluation(
                    submitted_rank=rank_idx,
                    program_id=pid,
                    status="unavailable",
                    reason_code="TYT_PREREQUISITE_MISSING",
                    detail=f"Program '{pid}' requires a valid TYT score.",
                ),
                None,
            )

    if program.min_score is not None and eff_score < program.min_score:
        return (
            ChoiceEvaluation(
                submitted_rank=rank_idx,
                program_id=pid,
                status="unavailable",
                reason_code="BELOW_MIN_SCORE",
                detail=f"Effective {program.score_type} score {eff_score:.3f} < minimum {program.min_score:.3f}.",
            ),
            None,
        )

    rank_used, rank_source = _resolve_rank(candidate, program.score_type, derived_ranks)
    max_rank = (
        program.max_rank_override
        if program.max_rank_override is not None
        else (ruleset.rank_thresholds.get(program.baraj_group) if program.baraj_group else None)
    )
    if max_rank is not None:
        if rank_used is None:
            return (
                ChoiceEvaluation(
                    submitted_rank=rank_idx,
                    program_id=pid,
                    status="unavailable",
                    reason_code="MISSING_RANK_FOR_THRESHOLD",
                    detail=f"Program '{pid}' enforces rank <= {max_rank}, but candidate rank is missing.",
                ),
                None,
            )
        if rank_used > max_rank:
            return (
                ChoiceEvaluation(
                    submitted_rank=rank_idx,
                    program_id=pid,
                    status="unavailable",
                    reason_code="RANK_THRESHOLD_NOT_MET",
                    detail=(
                        f"Candidate {program.score_type} rank {rank_used} exceeds threshold {max_rank} "
                        f"(baraj_group={program.baraj_group})."
                    ),
                ),
                None,
            )

    cond_failure = _check_special_conditions(candidate, program)
    if cond_failure is not None:
        code, detail = cond_failure
        return (
            ChoiceEvaluation(
                submitted_rank=rank_idx,
                program_id=pid,
                status="unavailable",
                reason_code=code,
                detail=detail,
            ),
            None,
        )

    fin = compute_candidate_program_financials(candidate, program, intervention)
    if affordability_mode == "hard_exclude" and fin.net_tuition > 0.0:
        exceeds_max = candidate.max_affordable_tuition is not None and fin.net_tuition > candidate.max_affordable_tuition
        has_gap = fin.liquidity_gap is not None and fin.liquidity_gap > 0.0
        if exceeds_max or has_gap:
            return (
                ChoiceEvaluation(
                    submitted_rank=rank_idx,
                    program_id=pid,
                    status="unavailable",
                    reason_code="AFFORDABILITY_EXCLUDED",
                    detail=(
                        f"Net tuition {fin.net_tuition:.2f} / upfront due {fin.payments_due_upfront:.2f} "
                        f"exceeds candidate affordability constraints."
                    ),
                ),
                None,
            )

    return (
        ChoiceEvaluation(
            submitted_rank=rank_idx,
            program_id=pid,
            status="eligible",
            reason_code="ELIGIBLE",
            detail="Choice satisfies score type, threshold, capacity, and condition checks.",
        ),
        EligibleChoice(
            program_id=pid,
            submitted_rank=rank_idx,
            score_type=program.score_type,
            effective_score=eff_score,
            raw_score=candidate.raw_scores.get(program.score_type),
            obp_contribution=candidate.obp_contribution,
            rank_used=rank_used,
            rank_source=rank_source,
            financials=fin,
        ),
    )


def evaluate_candidate_and_choices(
    candidate: CandidateRecord,
    programs_by_id: dict[str, ProgramOffering],
    ruleset: PlacementRuleset,
    derived_ranks: dict[ScoreType, int] | None = None,
    intervention: UniversityPolicyIntervention | None = None,
) -> CandidateEligibilityAudit:
    """Run Phase A candidate pre-screening and Phase B per-choice audit."""
    affordability_mode: AffordabilityFilterMode = (
        intervention.affordability_filter_mode if intervention is not None else "none"
    )
    missing: list[str] = []

    requires_diploma = any(p.special_conditions.requires_diploma for p in programs_by_id.values()) if programs_by_id else True
    if requires_diploma and candidate.diploma_eligible is None:
        missing.append("diploma_eligible")

    if affordability_mode == "hard_exclude" and candidate.liquid_budget is None and candidate.max_affordable_tuition is None:
        missing.append("liquid_budget")

    if missing:
        return CandidateEligibilityAudit(
            candidate_id=candidate.candidate_id,
            status=EligibilityStatus.CANNOT_EVALUATE,
            missing_attributes=missing,
        )

    exclusions: list[str] = []
    if requires_diploma and candidate.diploma_eligible is False:
        exclusions.append("DIPLOMA_INELIGIBLE")
    if ruleset.strict_preference_cap and len(candidate.preferences) > ruleset.max_preferences:
        exclusions.append("PREFERENCE_CAP_EXCEEDED")
    if exclusions:
        return CandidateEligibilityAudit(
            candidate_id=candidate.candidate_id,
            status=EligibilityStatus.EXCLUDED,
            exclusion_reasons=exclusions,
        )

    evaluations: list[ChoiceEvaluation] = []
    eligible_choices: list[EligibleChoice] = []
    seen: set[str] = set()

    prefs_to_eval = candidate.preferences[: ruleset.max_preferences]
    truncated_prefs = candidate.preferences[ruleset.max_preferences :]

    for rank_idx, pid in enumerate(prefs_to_eval, start=1):
        if pid in seen:
            if ruleset.duplicate_preference_policy == "reject_candidate":
                return CandidateEligibilityAudit(
                    candidate_id=candidate.candidate_id,
                    status=EligibilityStatus.EXCLUDED,
                    exclusion_reasons=["DUPLICATE_CHOICE"],
                )
            evaluations.append(
                ChoiceEvaluation(
                    submitted_rank=rank_idx,
                    program_id=pid,
                    status="unavailable",
                    reason_code="DUPLICATE_CHOICE",
                    detail=f"Duplicate program_id '{pid}' ignored after earlier occurrence.",
                )
            )
            continue
        seen.add(pid)
        ev, choice = _evaluate_single_choice(
            rank_idx,
            pid,
            candidate,
            programs_by_id.get(pid),
            ruleset,
            derived_ranks,
            intervention,
            affordability_mode,
        )
        evaluations.append(ev)
        if choice is not None:
            eligible_choices.append(choice)

    for offset, pid in enumerate(truncated_prefs, start=ruleset.max_preferences + 1):
        evaluations.append(
            ChoiceEvaluation(
                submitted_rank=offset,
                program_id=pid,
                status="unavailable",
                reason_code="PREFERENCE_TRUNCATED",
                detail=f"Preference rank {offset} exceeds max_preferences={ruleset.max_preferences}.",
            )
        )

    if affordability_mode == "utility_rerank" and len(eligible_choices) > 1:
        def _rerank_key(choice: EligibleChoice) -> tuple[int, float, int]:
            fin = choice.financials
            over_cap = (
                candidate.max_affordable_tuition is not None and fin.net_tuition > candidate.max_affordable_tuition
            )
            has_gap = fin.liquidity_gap is not None and fin.liquidity_gap > 0.0
            return (1 if (over_cap or has_gap) else 0, fin.net_tuition, choice.submitted_rank)

        eligible_choices.sort(key=_rerank_key)

    return CandidateEligibilityAudit(
        candidate_id=candidate.candidate_id,
        status=EligibilityStatus.ELIGIBLE,
        eligible_choices=eligible_choices,
        preference_evaluations=evaluations,
    )
