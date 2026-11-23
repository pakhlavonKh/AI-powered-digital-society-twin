"""Additional edge-case tests for Milestone 1 placement rules, interventions, and summaries."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scenarios.placement.eligibility import evaluate_candidate_and_choices
from scenarios.placement.engine import run_placement
from scenarios.placement.interventions import apply_intervention
from scenarios.placement.models import (
    CandidateRecord,
    PlacementRuleset,
    ProgramOffering,
    TieBreakPolicy,
)
from scenarios.schema import UniversityPolicyIntervention
from scenarios.summary import summarize_placement_comparison, summarize_placement_result


def _prog(pid: str, *, score_type: str = "SAY", cap: int = 2, tuition: float = 0.0, level: str = "bachelor") -> ProgramOffering:
    return ProgramOffering(
        program_id=pid,
        university_id="U1",
        university_name="Uni",
        province_code="06",
        department_name=pid,
        degree_level=level,  # type: ignore[arg-type]
        score_type=score_type,  # type: ignore[arg-type]
        capacity=cap,
        tuition_annual=tuition,
    )


def test_apply_intervention_rejects_unverified_osym_claim() -> None:
    ruleset = PlacementRuleset()
    bad = UniversityPolicyIntervention(osym_verified=True, rule_fidelity="verified_osym")
    with pytest.raises(ValidationError, match="source_note"):
        apply_intervention([], [_prog("P1")], ruleset, bad)


def test_tyt_prerequisite_missing_blocks_bachelor_while_allowing_associate() -> None:
    progs = {
        "BACH_SAY": _prog("BACH_SAY", score_type="SAY", level="bachelor"),
        "ASSOC_TYT": _prog("ASSOC_TYT", score_type="TYT", level="associate"),
    }
    ruleset = PlacementRuleset(require_tyt_for_bachelor=True)

    no_tyt = CandidateRecord(
        candidate_id="C1",
        diploma_eligible=True,
        scores={"SAY": 420.0, "TYT": None},
        ranks={"SAY": 10_000},
        preferences=["BACH_SAY", "ASSOC_TYT"],
    )
    audit = evaluate_candidate_and_choices(no_tyt, progs, ruleset)
    assert audit.preference_evaluations[0].reason_code == "TYT_PREREQUISITE_MISSING"
    assert audit.preference_evaluations[1].reason_code == "SCORE_TYPE_MISMATCH"


def test_cohort_derived_competition_ranks_and_subgroup_suppression() -> None:
    progs = [_prog("P1", cap=3)]
    cands = [
        CandidateRecord(candidate_id="C1", province_code="06", sex="female", income_band="low", scores={"SAY": 450.0}, preferences=["P1"]),
        CandidateRecord(candidate_id="C2", province_code="06", sex="male", income_band="low", scores={"SAY": 450.0}, preferences=["P1"]),
        CandidateRecord(candidate_id="C3", province_code="34", sex="male", income_band="high", scores={"SAY": 400.0}, preferences=["P1"]),
    ]
    res = run_placement(cands, progs, ruleset=PlacementRuleset(derive_ranks_from_cohort=True), min_group=2)
    by_id = {o.candidate_id: o for o in res.candidate_outcomes}
    assert by_id["C1"].rank_used == 1 and by_id["C1"].rank_source == "cohort_derived"
    assert by_id["C2"].rank_used == 1
    assert by_id["C3"].rank_used == 3

    # Province "34" has only 1 candidate < min_group=2 -> suppressed
    prov_groups = {g["value"]: g for g in res.subgroup_metrics["province_code"]["groups"]}
    assert prov_groups["06"]["suppressed"] is False
    assert prov_groups["34"]["suppressed"] is True


def test_closed_program_overrides_age_tie_and_empty_summary() -> None:
    progs = [_prog("P_CLOSED", cap=2), _prog("P_AGE", cap=1, tuition=100_000.0)]
    cands = [
        CandidateRecord(candidate_id="C_YOUNG", age=18, scores={"SAY": 410.0}, raw_scores={"SAY": 370.0}, obp_contribution=40.0, ranks={"SAY": 1}, preferences=["P_CLOSED", "P_AGE"]),
        CandidateRecord(candidate_id="C_OLD", age=22, scores={"SAY": 410.0}, raw_scores={"SAY": 370.0}, obp_contribution=40.0, ranks={"SAY": 1}, preferences=["P_CLOSED", "P_AGE"]),
    ]

    policy = UniversityPolicyIntervention(
        closed_programs=["P_CLOSED"],
        program_capacity_overrides={"P_AGE": 1},
        tuition_overrides={"P_AGE": 50_000.0},
        min_score_overrides={"P_AGE": 420.0},  # excludes both candidates -> zero placed
    )
    res_none_placed = run_placement(cands, progs, intervention=policy)
    assert res_none_placed.aggregate_metrics["placed_count"] == 0
    s_none = summarize_placement_result(res_none_placed)
    assert s_none["osym_verified"] is False
    assert "placed 0 of 2" in s_none["headline"]

    # Without min_score exclusion, younger_first resolves exact score tie
    res_age = run_placement(
        cands,
        progs,
        ruleset=PlacementRuleset(tie_break_policy=TieBreakPolicy(age_tie_rule="younger_first")),
        intervention=UniversityPolicyIntervention(closed_programs=["P_CLOSED"]),
    )
    assert res_age.tie_break_events[0].admitted_candidate_id == "C_YOUNG"
    assert res_age.tie_break_events[0].deciding_criterion == "age_younger_first"

    from scenarios.placement.comparison import compare_placement_scenarios
    cmp_rep = compare_placement_scenarios(res_age, res_none_placed)
    cmp_sum = summarize_placement_comparison(cmp_rep)
    assert "Counterfactual comparison" in cmp_sum["headline"]
