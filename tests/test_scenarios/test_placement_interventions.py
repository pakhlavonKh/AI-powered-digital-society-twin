"""Tests for pure economic, capacity, and placement-rule intervention transforms."""

from __future__ import annotations

from scenarios.placement.engine import run_placement
from scenarios.placement.interventions import apply_intervention
from scenarios.placement.models import CandidateRecord, PlacementRuleset, ProgramOffering
from scenarios.schema import UniversityPolicyIntervention


def test_interventions_do_not_mutate_inputs_and_apply_exact_deltas():
    programs = [
        ProgramOffering(
            program_id="P_PAID",
            university_id="U1",
            university_name="Foundation",
            university_type="foundation",
            province_code="06",
            department_name="CS Paid",
            score_type="SAY",
            baraj_group="engineering",
            capacity=20,
            tuition_annual=100_000.0,
        ),
        ProgramOffering(
            program_id="P_FULL_SCHOL",
            university_id="U1",
            university_name="Foundation",
            university_type="foundation",
            province_code="06",
            department_name="CS 100% Burslu",
            score_type="SAY",
            baraj_group="engineering",
            capacity=10,
            tuition_annual=100_000.0,
            scholarship_pct=100.0,
        ),
    ]
    candidates = [
        CandidateRecord(
            candidate_id="C_LOW_INC",
            income_band="low",
            liquid_budget=30_000.0,
            obp_contribution=40.0,
            scores={"SAY": 400.0},
            ranks={"SAY": 250_000},
            need_aid_grant=20_000.0,
            preferences=["P_PAID"],
        ),
        CandidateRecord(
            candidate_id="C_MID_INC",
            income_band="middle",
            liquid_budget=80_000.0,
            obp_contribution=40.0,
            scores={"SAY": 410.0},
            ranks={"SAY": 210_000},
            need_aid_grant=20_000.0,
            preferences=["P_PAID"],
        ),
    ]
    ruleset = PlacementRuleset()

    intervention = UniversityPolicyIntervention(
        tuition_change_pct=20.0,
        aid_budget_change_pct=25.0,
        capacity_change_pct=-15.0,
        capacity_rounding="largest_remainder",
        rank_threshold_overrides={"engineering": 220_000},
        apply_prior_placement_obp_penalty=True,
    )

    new_cands, new_progs, new_rules, meta = apply_intervention(candidates, programs, ruleset, intervention)

    # Original inputs stay untouched
    assert programs[0].tuition_annual == 100_000.0
    assert programs[0].capacity == 20
    assert candidates[0].previously_placed_penalty is False
    assert ruleset.rank_thresholds["engineering"] == 300_000

    # New programs scaled cleanly (100% burslu still yields 0 published tuition)
    prog_map = {p.program_id: p for p in new_progs}
    assert prog_map["P_PAID"].tuition_annual == 120_000.0
    assert prog_map["P_FULL_SCHOL"].published_net_tuition_before_aid() == 0.0
    assert prog_map["P_PAID"].capacity + prog_map["P_FULL_SCHOL"].capacity == 26  # round((20+10)*0.85) = 26

    # Aid pool increased by +25%: (20k + 20k) * 1.25 = 50k total allocated deterministically
    assert meta["aid_budget_pool"] == 50_000.0
    assert meta["aid_allocated"] == 50_000.0
    assert sum(c.need_aid_grant for c in new_cands) == 50_000.0

    # Prior placement OBP penalty applied cleanly
    assert all(c.previously_placed_penalty is True for c in new_cands)
    assert new_rules.rank_thresholds["engineering"] == 220_000

    # Run placement: C_LOW_INC (rank 250k > 220k) fails tightened baraj; C_MID_INC succeeds with 390 effective score
    res = run_placement(candidates, programs, ruleset=ruleset, intervention=intervention)
    out = {o.candidate_id: o for o in res.candidate_outcomes}
    assert out["C_LOW_INC"].placement_status == "unplaced"
    assert out["C_LOW_INC"].preference_evaluations[0].reason_code == "RANK_THRESHOLD_NOT_MET"
    assert out["C_MID_INC"].placement_status == "placed"
    assert out["C_MID_INC"].effective_score == 390.0  # 410 - 0.5 * 40
