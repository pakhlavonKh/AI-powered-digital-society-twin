"""Unit & integration tests for Step 1: UniversityQuerySpec, compiler, scoping, catalog loader, and plan API."""

from __future__ import annotations

from scenarios.compiler import compile_scenario_from_prompt, compile_university_query
from scenarios.placement.cohort_synth import build_standalone_demo_programs
from scenarios.placement.interventions import apply_intervention
from scenarios.placement.models import PlacementRuleset
from scenarios.schema import UniversityPolicyIntervention
from tests.conftest import make_client


def test_compiler_handles_all_twelve_intents_en_and_tr():
    catalog = build_standalone_demo_programs()

    cases = [
        ("How many students would apply to this uni if tuition increased by 30%?", "UNI_ANK_FOUND", "application_demand"),
        ("What happens if this uni's ranking got higher or lower?", "UNI_ANK_FOUND", "ranking_sensitivity"),
        ("What happens if Ankara State University expands quotas by 20%?", None, "quota_capacity"),
        ("How would cutoff scores move at Ankara State University if quotas drop 20%?", None, "cutoff_impact"),
        ("Will programs fill at Istanbul Foundation University or leave empty seats?", None, "placement_fill"),
        ("Who is priced out by income band if tuition rises 30% at this uni?", "UNI_ANK_FOUND", "affordability_equity"),
        ("What if we double Burslu scholarships at Ankara Foundation University?", None, "scholarship_aid"),
        ("What tuition increase maximizes net revenue at this uni?", "UNI_ANK_FOUND", "revenue_tradeoff"),
        ("How does a 25% tuition hike affect 4-semester retention and dropout at this uni?", "UNI_ANK_FOUND", "retention_impact"),
        ("Where do lost applicants go among rival universities if tuition rises 30% at this uni?", "UNI_ANK_FOUND", "competitor_flow"),
        ("Compare +10%, +20%, and +30% tuition hikes at Ankara Foundation University", None, "multi_scenario_compare"),
        ("What if tuition increases by 30% and ranking drops by 15% at this uni?", "UNI_ANK_FOUND", "composite"),
        ("Bu üniversitede harç %30 artarsa kaç öğrenci başvuru yapar?", "UNI_ANK_FOUND", "application_demand"),
    ]

    for prompt, ctx_uid, expected_intent in cases:
        spec = compile_university_query(
            prompt,
            catalog=catalog,
            context_university_id=ctx_uid,
            force_heuristic=True,
        )
        assert spec.intent == expected_intent, f"Prompt {prompt!r} gave {spec.intent} != {expected_intent}"
        assert spec.focus_university_id is not None
        assert not spec.unresolved_entities
        assert not spec.out_of_scope_reasons


def test_compiler_unresolved_and_directional_variants_and_out_of_scope():
    catalog = build_standalone_demo_programs()

    # "this uni" without context_university_id asks for clarification
    unresolved_spec = compile_university_query(
        "How many students would apply to this uni if tuition increased by 30%?",
        catalog=catalog,
        context_university_id=None,
        force_heuristic=True,
    )
    assert unresolved_spec.unresolved_entities
    assert unresolved_spec.unresolved_entities[0].entity_type == "university"

    # Unknown university name is flagged instead of guessing
    unknown_spec = compile_university_query(
        "How many apply to Marmara Horizon University if tuition increases 20%?",
        catalog=catalog,
        force_heuristic=True,
    )
    assert unknown_spec.unresolved_entities
    assert "not found" in unknown_spec.unresolved_entities[0].reason.lower()

    # Directional ranking prompt produces Lower / Baseline / Higher variants
    dir_spec = compile_university_query(
        "How would applications and cutoffs change if this uni's ranking got higher or lower?",
        catalog=catalog,
        context_university_id="UNI_ANK_FOUND",
        force_heuristic=True,
    )
    assert dir_spec.intent == "ranking_sensitivity"
    assert len(dir_spec.comparison_variants) == 3
    assert [v.variant_id for v in dir_spec.comparison_variants] == ["ranking_lower", "baseline", "ranking_higher"]
    assert dir_spec.comparison_variants[0].intervention.ranking_change_pct == -20.0
    assert dir_spec.comparison_variants[2].intervention.ranking_change_pct == 20.0

    # Out-of-scope prompt flagged explicitly
    oos = compile_university_query(
        "What happens if professor salaries and dormitory parking spots change at this uni?",
        catalog=catalog,
        context_university_id="UNI_ANK_FOUND",
        force_heuristic=True,
    )
    assert oos.out_of_scope_reasons

    # Regression check on existing compiler.py domain routing
    sc_rank = compile_scenario_from_prompt(
        "How would applications change if this uni's ranking improves by 20%?",
        force_heuristic=True,
    )
    assert sc_rank.policy.category == "university_placement"


def test_target_scoping_keeps_rivals_fixed_and_preserves_baraj():
    programs = build_standalone_demo_programs()
    ruleset = PlacementRuleset()
    intervention = UniversityPolicyIntervention(
        target_university_ids=["UNI_ANK_FOUND"],
        tuition_change_pct=30.0,
        ranking_change_pct=20.0,
    )

    _, eff_progs, eff_rules, meta = apply_intervention([], programs, ruleset, intervention)
    assert meta["rivals_fixed"] is True

    by_id = {p.program_id: p for p in eff_progs}
    orig_by_id = {p.program_id: p for p in programs}

    # Targeted university changed
    assert by_id["PRG_ANK_CS_FOUND_PAID"].tuition_annual == round(240_000.0 * 1.3, 2)
    assert by_id["PRG_ANK_CS_FOUND_PAID"].effective_prestige_score() > orig_by_id["PRG_ANK_CS_FOUND_PAID"].effective_prestige_score()

    # Rival universities stayed completely unchanged
    assert by_id["PRG_IST_ECON_FOUND_50"].tuition_annual == orig_by_id["PRG_IST_ECON_FOUND_50"].tuition_annual
    assert by_id["PRG_IST_ECON_FOUND_50"].effective_prestige_score() == orig_by_id["PRG_IST_ECON_FOUND_50"].effective_prestige_score()
    assert by_id["PRG_ANK_CS_STATE"].effective_prestige_score() == orig_by_id["PRG_ANK_CS_STATE"].effective_prestige_score()

    # Exogenous ranking never mutates ÖSYM baraj thresholds
    assert eff_rules.rank_thresholds == ruleset.rank_thresholds
    assert all(by_id[pid].max_rank_override == orig_by_id[pid].max_rank_override for pid in by_id)


def test_sqlite_catalog_loader_and_plan_endpoint(make_settings, tmp_path):
    from societytwin.university.db import connect, initialize_database
    from societytwin.university.service import load_programs_from_sqlite_snapshot

    db_path = tmp_path / "university.sqlite3"
    initialize_database(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO source_snapshots(snapshot_id, source_filename, file_sha256, imported_at, importer_version, verification_status) "
            "VALUES ('snap-q1', 'uni.xlsx', ?, '2026-10-20T00:00:00Z', 'university-xlsx-v1', 'unverified')",
            ("b" * 64,),
        )
        conn.execute(
            "INSERT INTO universities(university_id, snapshot_id, university_key, name_original, name_normalized, university_type, city) "
            "VALUES (1, 'snap-q1', 'uni_alpha', 'Alpha Üniversitesi', 'Alpha Üniversitesi', 'Vakıf', NULL)"
        )
        conn.execute(
            "INSERT INTO universities(university_id, snapshot_id, university_key, name_original, name_normalized, university_type, city) "
            "VALUES (2, 'snap-q1', 'uni_beta', 'Beta Devlet Üniversitesi', 'Beta Devlet Üniversitesi', 'Devlet', 'Ankara')"
        )
        conn.execute(
            "INSERT INTO programs(program_id, snapshot_id, university_id, program_code, name_original, degree_level, score_type, scholarship_original, source_sheet, source_row) "
            "VALUES (10, 'snap-q1', 1, '200100101', 'Bilgisayar Mühendisliği', NULL, 'SAY', '%50 İndirimli', 'Programlar', 2)"
        )
        conn.execute(
            "INSERT INTO programs(program_id, snapshot_id, university_id, program_code, name_original, degree_level, score_type, scholarship_original, source_sheet, source_row) "
            "VALUES (11, 'snap-q1', 2, '100100101', 'Bilgisayar Mühendisliği', NULL, 'SAY', 'Devlet (Ücretsiz)', 'Programlar', 3)"
        )
        conn.execute(
            "INSERT INTO annual_admissions(program_id, snapshot_id, admission_year, quota, placed_students, success_rank, source_sheet, source_row) "
            "VALUES (10, 'snap-q1', 2025, 30, 30, 42000, 'Yıllık Uzun Format', 2)"
        )
        conn.execute(
            "INSERT INTO annual_admissions(program_id, snapshot_id, admission_year, quota, placed_students, success_rank, source_sheet, source_row) "
            "VALUES (11, 'snap-q1', 2025, 50, 50, 18000, 'Yıllık Uzun Format', 3)"
        )
        conn.execute(
            "INSERT INTO annual_tuition(program_id, snapshot_id, academic_year_start, full_amount_minor, net_amount_minor, currency, source_sheet, source_row) "
            "VALUES (10, 'snap-q1', 2025, 40000000, 20000000, 'TRY', 'Programlar', 2)"
        )
        conn.commit()

    programs, meta = load_programs_from_sqlite_snapshot(db_path, "snap-q1")
    assert meta["catalog_source"] == "sqlite_snapshot"
    assert len(programs) == 2
    alpha = next(p for p in programs if p.university_id == "uni_alpha")
    beta = next(p for p in programs if p.university_id == "uni_beta")
    assert alpha.university_type == "foundation"
    assert alpha.province_code is None
    assert alpha.tuition_annual == 400_000.0
    assert alpha.scholarship_pct == 50.0
    assert alpha.published_net_tuition_before_aid() == 200_000.0
    assert beta.university_type == "state"
    assert beta.province_code == "06"

    with make_client(make_settings(university_db_path=db_path)) as c:
        unis = c.get("/api/v2/university-registry/snapshots/snap-q1/universities")
        assert unis.status_code == 200
        assert len(unis.json()["items"]) == 2

        plan_res = c.post(
            "/api/v2/university/query/plan",
            json={
                "prompt": "How many students would apply to this uni if tuition increased by 30%?",
                "context_university_id": "uni_alpha",
                "snapshot_id": "snap-q1",
                "cohort_size": 100,
            },
        )
        assert plan_res.status_code == 200, plan_res.text
        plan = plan_res.json()
        assert plan["executable"] is True
        assert plan["coefficients_calibrated"] is False
        assert plan["osym_verified"] is False
        assert plan["catalog"]["rivals_fixed"] is True
        assert plan["query_spec"]["focus_university_id"] == "uni_alpha"
        assert plan["query_spec"]["levers"]["tuition_change_pct"] == 30.0


def test_sqlite_long_sha_keys_and_real_scale_run(make_settings, tmp_path):
    """Importer generates 76-char 'name-sha256:...' university keys and high-TL fees."""
    from societytwin.university.db import connect, initialize_database
    from societytwin.university.service import load_programs_from_sqlite_snapshot

    db_path = tmp_path / "university.sqlite3"
    initialize_database(db_path)
    long_uid = "name-sha256:" + ("a" * 64)
    long_snap = "sha256:" + ("c" * 64)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO source_snapshots(snapshot_id, source_filename, file_sha256, imported_at, importer_version, verification_status) "
            "VALUES (?, 'uni.xlsx', ?, '2026-10-20T00:00:00Z', 'university-xlsx-v1', 'unverified')",
            (long_snap, "c" * 64),
        )
        conn.execute(
            "INSERT INTO universities(university_id, snapshot_id, university_key, name_original, name_normalized, university_type, city) "
            "VALUES (1, ?, ?, 'Real Scale Foundation Uni', 'Real Scale Foundation Uni', 'Vakıf', 'Ankara')",
            (long_snap, long_uid),
        )
        conn.execute(
            "INSERT INTO programs(program_id, snapshot_id, university_id, program_code, name_original, degree_level, score_type, scholarship_original, source_sheet, source_row) "
            "VALUES (10, ?, 1, '200100102', 'Psikoloji', NULL, 'EA', '%50 İndirimli', 'Programlar', 2)",
            (long_snap,),
        )
        conn.execute(
            "INSERT INTO annual_admissions(program_id, snapshot_id, admission_year, quota, placed_students, success_rank, source_sheet, source_row) "
            "VALUES (10, ?, 2026, 40, 40, 42000, 'Yıllık Uzun Format', 2)",
            (long_snap,),
        )
        conn.execute(
            "INSERT INTO annual_tuition(program_id, snapshot_id, academic_year_start, full_amount_minor, net_amount_minor, currency, source_sheet, source_row) "
            "VALUES (10, ?, 2026, 128000000, 64000000, 'TRY', 'Programlar', 2)",
            (long_snap,),
        )
        conn.commit()

    programs, _ = load_programs_from_sqlite_snapshot(db_path, long_snap)
    assert len(programs) == 1
    assert programs[0].university_id == long_uid
    assert 0.15 <= (programs[0].prestige_score or 0.0) <= 0.96

    with make_client(make_settings(university_db_path=db_path)) as c:
        run_res = c.post(
            "/api/v2/university/query/runs",
            json={
                "prompt": "How many students would apply to this uni if tuition increased by 30%?",
                "context_university_id": long_uid,
                "snapshot_id": long_snap,
                "cohort_size": 80,
                "seed": 42,
            },
        )
        assert run_res.status_code == 201, run_res.text
        body = run_res.json()
        assert body["focus_university_id"] == long_uid
        assert body["manifest"]["catalog_source"] == "sqlite_snapshot"
