"""Unit tests for the deterministic Deferred Acceptance allocation engine and invariants."""

from __future__ import annotations

import random

from scenarios.placement.cohort_synth import build_standalone_demo_programs, build_standalone_test_cohort
from scenarios.placement.engine import run_placement
from scenarios.placement.models import CandidateRecord, PlacementRuleset, ProgramOffering, TieBreakPolicy


def _prog(pid: str, score_type: str = "SAY", cap: int = 1) -> ProgramOffering:
    return ProgramOffering(
        program_id=pid,
        university_id="U1",
        university_name="Uni",
        province_code="06",
        department_name=pid,
        score_type=score_type,  # type: ignore[arg-type]
        capacity=cap,
    )


def test_known_answer_cascading_displacement():
    programs = [_prog("P_A", cap=1), _prog("P_B", cap=1)]
    candidates = [
        CandidateRecord(candidate_id="C_LOW", scores={"SAY": 350.0}, ranks={"SAY": 3}, preferences=["P_A", "P_B"]),
        CandidateRecord(candidate_id="C_MID", scores={"SAY": 400.0}, ranks={"SAY": 2}, preferences=["P_A", "P_B"]),
        CandidateRecord(candidate_id="C_HIGH", scores={"SAY": 450.0}, ranks={"SAY": 1}, preferences=["P_A", "P_B"]),
    ]

    result = run_placement(candidates, programs)
    outcomes = {o.candidate_id: o for o in result.candidate_outcomes}

    assert outcomes["C_HIGH"].assigned_program_id == "P_A"
    assert outcomes["C_MID"].assigned_program_id == "P_B"
    assert outcomes["C_LOW"].placement_status == "unplaced"
    assert outcomes["C_LOW"].unplaced_reason == "CAPACITY_EXHAUSTED"
    assert result.manifest.invariants_passed is True
    assert result.aggregate_metrics["placed_count"] == 2
    assert result.aggregate_metrics["unplaced_count"] == 1


def test_permutation_invariance_on_shuffled_inputs():
    programs = build_standalone_demo_programs()
    cohort = build_standalone_test_cohort(programs=programs, size=100, seed=7)
    base_res = run_placement(cohort.candidates, programs, seed=7)

    rng = random.Random(1234)
    shuffled_cands = list(cohort.candidates)
    shuffled_progs = list(programs)
    rng.shuffle(shuffled_cands)
    rng.shuffle(shuffled_progs)

    perm_res = run_placement(shuffled_cands, shuffled_progs, seed=7)
    assert perm_res.manifest.result_sha256 == base_res.manifest.result_sha256
    assert perm_res.candidate_outcomes == base_res.candidate_outcomes
    assert perm_res.program_outcomes == base_res.program_outcomes


def test_tie_breaking_chain_and_event_logging():
    programs = [_prog("P_TIE", cap=1)]
    candidates = [
        CandidateRecord(
            candidate_id="C_1",
            scores={"SAY": 420.0},
            raw_scores={"SAY": 370.0},
            obp_contribution=50.0,
            ranks={"SAY": 1},
            preferences=["P_TIE"],
        ),
        CandidateRecord(
            candidate_id="C_2",
            scores={"SAY": 420.0},
            raw_scores={"SAY": 375.0},
            obp_contribution=45.0,
            ranks={"SAY": 1},
            preferences=["P_TIE"],
        ),
    ]
    res = run_placement(candidates, programs)
    outcomes = {o.candidate_id: o for o in res.candidate_outcomes}
    assert outcomes["C_2"].assigned_program_id == "P_TIE"
    assert outcomes["C_1"].placement_status == "unplaced"
    assert len(res.tie_break_events) == 1
    assert res.tie_break_events[0].deciding_criterion == "raw_score"

    # When raw_score and obp are identical, canonical_id vs seeded_hash resolve deterministically
    tied_equal = [
        CandidateRecord(candidate_id="C_A", scores={"SAY": 420.0}, raw_scores={"SAY": 370.0}, obp_contribution=50.0, ranks={"SAY": 1}, preferences=["P_TIE"]),
        CandidateRecord(candidate_id="C_B", scores={"SAY": 420.0}, raw_scores={"SAY": 370.0}, obp_contribution=50.0, ranks={"SAY": 1}, preferences=["P_TIE"]),
    ]
    res_canon = run_placement(
        tied_equal,
        programs,
        ruleset=PlacementRuleset(tie_break_policy=TieBreakPolicy(terminal_tie_breaker="canonical_id")),
    )
    assert {o.candidate_id: o.placement_status for o in res_canon.candidate_outcomes} == {
        "C_A": "placed",
        "C_B": "unplaced",
    }
    assert res_canon.tie_break_events[0].deciding_criterion == "terminal_canonical_id"

    res_hash_1 = run_placement(
        tied_equal,
        programs,
        ruleset=PlacementRuleset(tie_break_policy=TieBreakPolicy(terminal_tie_breaker="seeded_hash", tie_seed=99)),
    )
    res_hash_2 = run_placement(
        list(reversed(tied_equal)),
        programs,
        ruleset=PlacementRuleset(tie_break_policy=TieBreakPolicy(terminal_tie_breaker="seeded_hash", tie_seed=99)),
    )
    assert res_hash_1.manifest.result_sha256 == res_hash_2.manifest.result_sha256
    assert res_hash_1.tie_break_events[0].deciding_criterion == "terminal_seeded_hash"


def test_edge_cases_empty_and_undersubscribed():
    # Empty candidates
    empty_res = run_placement([], [_prog("P_1", cap=5)])
    assert empty_res.aggregate_metrics["placed_count"] == 0
    assert empty_res.program_outcomes[0].cutoff_score is None
    assert empty_res.program_outcomes[0].cutoff_is_binding is False

    # Under-subscribed program + candidate with empty preferences
    cands = [
        CandidateRecord(candidate_id="C_EMPTY_PREF", scores={"SAY": 400.0}, preferences=[]),
        CandidateRecord(candidate_id="C_PLACED", scores={"SAY": 360.0}, ranks={"SAY": 1}, preferences=["P_1"]),
    ]
    res = run_placement(cands, [_prog("P_1", cap=5)])
    outcomes = {o.candidate_id: o for o in res.candidate_outcomes}
    assert outcomes["C_EMPTY_PREF"].unplaced_reason == "NO_PREFERENCES"
    assert outcomes["C_PLACED"].assigned_program_id == "P_1"
    po = res.program_outcomes[0]
    assert po.filled == 1
    assert po.remaining_seats == 4
    assert po.cutoff_score == 360.0
    assert po.cutoff_is_binding is False
