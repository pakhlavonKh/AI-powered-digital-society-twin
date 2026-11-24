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


def test_empirical_priors_quota_scaling_vectorized_crn_and_acronym_resolution():
    from scenarios.placement.cohort_synth import catalog_fee_scale
    from scenarios.placement.models import ProgramOffering
    from societytwin.national.university_service import _scale_quotas_to_cohort

    # 1. Empirical priors draw realistic 2026 scores and YÖK Ankara OD provinces (with Ankara plurality)
    demo_progs = build_standalone_demo_programs()
    c1 = build_standalone_test_cohort(
        demo_progs,
        size=160,
        seed=42,
        empirical_priors=True,
        populate_initial_preferences=False,
    )
    c2 = build_standalone_test_cohort(
        demo_progs,
        size=160,
        seed=42,
        empirical_priors=True,
        populate_initial_preferences=False,
    )
    assert c1.candidates == c2.candidates
    assert all(cand.preferences == [] for cand in c1.candidates)
    ank_share = sum(1 for cand in c1.candidates if cand.province_code == "06") / len(c1.candidates)
    assert 0.25 <= ank_share <= 0.70
    for cand in c1.candidates:
        for st_val in cand.scores.values():
            assert 100.0 <= st_val <= 575.0

    # 2. Vectorized CRN preference scoring path (n*m > 20_000) preserves shuffled-program determinism & capacity cap
    many_progs: list[ProgramOffering] = []
    for i in range(205):
        is_state = i % 2 == 0
        many_progs.append(
            ProgramOffering(
                program_id=f"PRG_VEC_{i:03d}",
                university_id=f"UNI_{i % 10:02d}",
                university_name=f"University {i % 10}",
                university_type="state" if is_state else "foundation",
                province_code="06",
                department_name="Computer Engineering" if i % 3 == 0 else "Economics",
                degree_level="bachelor",
                score_type="SAY" if i % 3 == 0 else "EA",
                baraj_group="engineering" if i % 3 == 0 else None,
                capacity=120,
                tuition_annual=0.0 if is_state else 480000.0,
                scholarship_pct=100.0 if is_state else (50.0 if i % 4 == 1 else 0.0),
                university_rank=15000 + i * 700,
                prestige_score=max(0.25, 0.90 - (i % 25) * 0.025),
                status="open",
            )
        )
    assert catalog_fee_scale(many_progs) > 1.0
    vec_cohort = build_standalone_test_cohort(many_progs, size=120, seed=7, empirical_priors=False, populate_initial_preferences=False)
    scaled_progs, scale_factor = _scale_quotas_to_cohort(many_progs, len(vec_cohort.candidates))
    assert 0.0 < scale_factor < 1.0
    assert all(p.capacity >= 1 for p in scaled_progs)

    shuffled_progs = list(scaled_progs)
    random.Random(19).shuffle(shuffled_progs)
    cfg = preset_preference_config("medium")
    ruleset = PlacementRuleset(max_preferences=5)
    pref_cache: dict[str, object] = {}

    res1 = run_placement(
        vec_cohort.candidates,
        scaled_progs,
        ruleset=ruleset,
        seed=42,
        intervention=UniversityPolicyIntervention(target_university_ids=["UNI_01"]),
        preference_config=cfg,
        preference_cache=pref_cache,
    )
    res2 = run_placement(
        vec_cohort.candidates,
        shuffled_progs,
        ruleset=ruleset,
        seed=42,
        intervention=UniversityPolicyIntervention(target_university_ids=["UNI_01"]),
        preference_config=cfg,
        preference_cache=pref_cache,
    )
    assert res1.manifest.result_sha256 == res2.manifest.result_sha256

    # 3. Acronym & distinctive token resolution matches Turkish university names cleanly
    tr_catalog = [
        ProgramOffering(
            program_id="P_ODTU",
            university_id="UNI_ODTU",
            university_name="Orta Doğu Teknik Üniversitesi",
            university_type="state",
            province_code="06",
            department_name="Computer Engineering",
            degree_level="bachelor",
            score_type="SAY",
            baraj_group="engineering",
            capacity=90,
            tuition_annual=0.0,
            scholarship_pct=100.0,
            status="open",
        ),
        ProgramOffering(
            program_id="P_BILKENT",
            university_id="UNI_BILKENT",
            university_name="İhsan Doğramacı Bilkent Üniversitesi",
            university_type="foundation",
            province_code="06",
            department_name="Computer Engineering",
            degree_level="bachelor",
            score_type="SAY",
            baraj_group="engineering",
            capacity=45,
            tuition_annual=640000.0,
            scholarship_pct=0.0,
            status="open",
        ),
    ]
    odtu_spec = compile_university_query("What happens if ODTU expands quota by 10%?", catalog=tr_catalog, force_heuristic=True)
    bilk_spec = compile_university_query("What happens if Bilkent University raises tuition by 20%?", catalog=tr_catalog, force_heuristic=True)
    assert odtu_spec.levers.target_university_ids == ["UNI_ODTU"]
    assert bilk_spec.levers.target_university_ids == ["UNI_BILKENT"]
