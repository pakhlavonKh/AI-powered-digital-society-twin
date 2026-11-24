"""Unit tests for Step 2 & Step 3: CRN preference model, monotonicity, extended deltas, and summarizer."""

from __future__ import annotations

import random

from scenarios.compiler import compile_university_query
from scenarios.placement.cohort_synth import build_standalone_demo_programs, build_standalone_test_cohort
from scenarios.placement.comparison import compare_placement_scenarios
from scenarios.placement.engine import run_placement
from scenarios.placement.models import PlacementRuleset
from scenarios.placement.preference_model import (
    apply_behavioral_preferences,
    compute_elasticity_sensitivity_range,
    crn_taste_epsilon,
)
from scenarios.schema import UniversityPolicyIntervention
from scenarios.summary import _llm_numbers_grounded, summarize_university_query
from scenarios.university_analytics import StatisticsSection, compute_target_university_analytics
from scenarios.university_query import preset_preference_config


def test_crn_reproducibility_and_zero_change_identity():
    programs = build_standalone_demo_programs()
    cohort = build_standalone_test_cohort(programs, size=120, seed=42)
    cfg = preset_preference_config("medium")

    # Identical epsilon regardless of program order or run context
    e1 = crn_taste_epsilon("CAND_00001", "PRG_ANK_CS_FOUND_PAID", 42)
    e2 = crn_taste_epsilon("CAND_00001", "PRG_ANK_CS_FOUND_PAID", 42)
    assert e1 == e2

    shuffled_progs = list(programs)
    random.Random(99).shuffle(shuffled_progs)

    base = run_placement(
        cohort.candidates,
        programs,
        seed=42,
        intervention=UniversityPolicyIntervention(target_university_ids=["UNI_ANK_FOUND"]),
        preference_config=cfg,
    )
    shuffled_base = run_placement(
        cohort.candidates,
        shuffled_progs,
        seed=42,
        intervention=UniversityPolicyIntervention(target_university_ids=["UNI_ANK_FOUND"]),
        preference_config=cfg,
    )
    zero_pol = run_placement(
        cohort.candidates,
        shuffled_progs,
        seed=42,
        intervention=UniversityPolicyIntervention(
            target_university_ids=["UNI_ANK_FOUND"],
            tuition_change_pct=0.0,
            ranking_change_pct=0.0,
            capacity_change_pct=0.0,
        ),
        preference_config=cfg,
    )

    assert base.manifest.result_sha256 == shuffled_base.manifest.result_sha256
    assert base.candidate_outcomes == zero_pol.candidate_outcomes
    assert base.program_outcomes == zero_pol.program_outcomes
    cmp_rep = compare_placement_scenarios(base, zero_pol)
    assert all(d.applicant_delta == 0 for d in cmp_rep.program_deltas)
    assert all(d.listed_anywhere_delta == 0 for d in cmp_rep.program_deltas)
    assert all(d.filled_delta == 0 for d in cmp_rep.program_deltas)


def test_tuition_hike_monotonicity_burslu_resilience_and_list_cap():
    programs = build_standalone_demo_programs()
    cohort = build_standalone_test_cohort(programs, size=240, seed=42)
    cfg = preset_preference_config("medium")
    ruleset = PlacementRuleset(max_preferences=4)

    # Check list-length cap respected
    updated, _, _ = apply_behavioral_preferences(
        cohort.candidates,
        programs,
        ruleset,
        None,
        cfg,
        seed=42,
    )
    assert all(len(c.preferences) <= 4 for c in updated)

    # Monotonicity across 0% -> +30% -> +60% tuition at UNI_ANK_FOUND
    results = []
    for pct in (0.0, 30.0, 60.0):
        res = run_placement(
            cohort.candidates,
            programs,
            seed=42,
            intervention=UniversityPolicyIntervention(
                target_university_ids=["UNI_ANK_FOUND"],
                tuition_change_pct=pct,
                affordability_filter_mode="utility_rerank",
            ),
            preference_config=cfg,
        )
        results.append(res)

    def _prog(res, pid):
        return next(po for po in res.program_outcomes if po.program_id == pid)

    paid_apps = [_prog(r, "PRG_ANK_CS_FOUND_PAID").listed_anywhere_count for r in results]
    half_apps = [_prog(r, "PRG_ANK_CS_FOUND_50").listed_anywhere_count for r in results]
    burslu_apps = [_prog(r, "PRG_ANK_CS_FOUND_100").listed_anywhere_count for r in results]

    assert paid_apps[0] >= paid_apps[1] >= paid_apps[2]
    assert paid_apps[0] > paid_apps[2]
    assert half_apps[0] >= half_apps[1] >= half_apps[2]
    # 100% Burslu tuition stays 0 TL, so it does not lose applicants
    assert burslu_apps[1] >= burslu_apps[0]


def test_ranking_monotonicity_and_cutoffs():
    programs = build_standalone_demo_programs()
    cohort = build_standalone_test_cohort(programs, size=220, seed=42)
    cfg = preset_preference_config("medium")

    low_res = run_placement(
        cohort.candidates,
        programs,
        seed=42,
        intervention=UniversityPolicyIntervention(
            target_university_ids=["UNI_ANK_FOUND"],
            ranking_change_pct=-25.0,
        ),
        preference_config=cfg,
    )
    base_res = run_placement(
        cohort.candidates,
        programs,
        seed=42,
        intervention=UniversityPolicyIntervention(target_university_ids=["UNI_ANK_FOUND"]),
        preference_config=cfg,
    )
    high_res = run_placement(
        cohort.candidates,
        programs,
        seed=42,
        intervention=UniversityPolicyIntervention(
            target_university_ids=["UNI_ANK_FOUND"],
            ranking_change_pct=25.0,
        ),
        preference_config=cfg,
    )

    target_pids = {"PRG_ANK_CS_FOUND_100", "PRG_ANK_CS_FOUND_50", "PRG_ANK_CS_FOUND_PAID"}

    def _target_totals(res):
        listed = sum(po.listed_anywhere_count for po in res.program_outcomes if po.program_id in target_pids)
        fc = sum(po.first_choice_count for po in res.program_outcomes if po.program_id in target_pids)
        return listed, fc

    l_low, fc_low = _target_totals(low_res)
    l_base, fc_base = _target_totals(base_res)
    l_high, fc_high = _target_totals(high_res)

    assert l_low <= l_base <= l_high
    assert l_low < l_high
    assert fc_low <= fc_base <= fc_high


def test_analytics_summarizer_elasticity_range_and_llm_grounding_guard():
    programs = build_standalone_demo_programs()
    cohort = build_standalone_test_cohort(programs, size=200, seed=42)
    spec = compile_university_query(
        "How many students would apply to this uni if tuition increased by 30%?",
        catalog=programs,
        context_university_id="UNI_ANK_FOUND",
        force_heuristic=True,
    )
    cfg = preset_preference_config("medium")
    base_res = run_placement(
        cohort.candidates,
        programs,
        seed=42,
        intervention=UniversityPolicyIntervention(target_university_ids=["UNI_ANK_FOUND"]),
        preference_config=cfg,
    )
    pol_res = run_placement(
        cohort.candidates,
        programs,
        seed=42,
        intervention=spec.levers,
        preference_config=cfg,
    )
    cmp_rep = compare_placement_scenarios(base_res, pol_res)
    analytics = compute_target_university_analytics(
        query_spec=spec,
        candidates=cohort.candidates,
        programs=programs,
        baseline_result=base_res,
        policy_result=pol_res,
        comparison=cmp_rep,
        cohort_source="standalone_test_fixture",
        seed=42,
    )
    el_range = compute_elasticity_sensitivity_range(
        candidates=cohort.candidates,
        programs=programs,
        target_program_ids=set(analytics["target_program_ids"]),
        intervention=spec.levers,
        seed=42,
    )
    summary = summarize_university_query(spec, analytics, elasticity_range=el_range)

    assert summary["generated_by"] == "deterministic"
    assert "apply" in summary["direct_answer"].lower()
    assert "rivals" in " ".join(summary["caveats"]).lower()
    assert "coefficients_calibrated=false" in " ".join(summary["caveats"]).lower()
    for sec in summary["detailed_statistics"]:
        StatisticsSection.model_validate(sec)

    # Number grounding guard rejects ungrounded/hallucinated figures
    assert _llm_numbers_grounded(["Applicants changed from 120 to 95."], {120.0, 95.0}) is True
    assert _llm_numbers_grounded(["Applicants changed to 99999."], {120.0, 95.0}) is False
