"""Integration tests for university scenario compilation, adapter execution, and handoff."""

from __future__ import annotations

from scenarios.adapter import (
    execute_placement_scenario,
    get_scenario,
    list_available_scenarios,
    placement_result_to_student_cohort,
    scenario_to_placement_spec,
)
from scenarios.compiler import compile_scenario_from_prompt
from scenarios.placement.cohort_synth import build_standalone_demo_programs, build_standalone_test_cohort
from scenarios.summary import summarize_placement_comparison, summarize_placement_result
from scenarios.placement.comparison import compare_placement_scenarios


def test_compiler_routes_university_placement_and_policy_without_regressing_transit():
    # Existing transit prompt for university students must stay transportation
    transit_sc = compile_scenario_from_prompt(
        "How would university students in Istanbul respond to a 50% transit pass discount?",
        force_heuristic=True,
    )
    assert transit_sc.policy.category == "transportation"

    # Placement prompt compiles to university_placement with baraj & quota extraction
    place_sc = compile_scenario_from_prompt(
        "What if ÖSYM engineering quotas in Ankara drop by 15% and the engineering rank baraj tightens to 200k?",
        force_heuristic=True,
    )
    assert place_sc.policy.category == "university_placement"
    assert place_sc.effective_simulation_mode == "university_placement"
    uni = place_sc.university_intervention
    assert uni is not None
    assert uni.capacity_change_pct == -15.0
    assert uni.rank_threshold_overrides.get("engineering") == 200_000
    assert uni.osym_verified is False

    # Economic university policy prompt (UNI-001 + UNI-006)
    tuition_sc = compile_scenario_from_prompt(
        "Simulate a 20% university tuition increase in Izmir with a 4 installment plan",
        force_heuristic=True,
    )
    assert tuition_sc.policy.category == "university_policy"
    assert tuition_sc.effective_simulation_mode == "university_decision_hybrid"
    assert tuition_sc.university_intervention is not None
    assert tuition_sc.university_intervention.tuition_change_pct == 20.0
    assert tuition_sc.university_intervention.installment_count == 4


def test_builtin_university_scenarios_discoverable_and_executable():
    items = list_available_scenarios()
    ids = {i["scenario_id"] for i in items}
    assert "uni_tuition_hike_001" in ids
    assert "uni_placement_quota_001" in ids

    sc = get_scenario("uni_placement_quota_001")
    programs = build_standalone_demo_programs()
    cohort = build_standalone_test_cohort(programs, size=80, seed=42)

    spec = scenario_to_placement_spec(sc, candidates=cohort, programs=programs, seed=42)
    assert spec["osym_verified"] is False
    assert "does NOT reproduce official ÖSYM" in spec["disclaimer"]

    result = execute_placement_scenario(sc, candidates=cohort, programs=programs, seed=42)
    assert result.manifest.scenario_id == "uni_placement_quota_001"
    assert result.manifest.invariants_passed is True

    # Deterministic executive summary
    text_sum = summarize_placement_result(result)
    assert text_sum["generated_by"] == "deterministic"
    assert text_sum["osym_verified"] is False
    assert "PRG_ANK_CS_STATE" in text_sum["summary_markdown"]

    # Clean handoff contract to Milestone 2 separate university module
    handoff = placement_result_to_student_cohort(result, cohort, programs)
    assert handoff["handoff_version"] == "placement-to-university-1.0"
    assert handoff["student_count"] == result.aggregate_metrics["placed_count"]
    assert handoff["source_result_sha256"] == result.manifest.result_sha256

    # Comparison summary integration
    tuition_sc = get_scenario("uni_tuition_hike_001")
    tuition_res = execute_placement_scenario(tuition_sc, candidates=cohort, programs=programs, seed=42)
    cmp_report = compare_placement_scenarios(result, tuition_res)
    cmp_sum = summarize_placement_comparison(cmp_report)
    assert "Counterfactual Placement Comparison Report" in cmp_sum["summary_markdown"]
