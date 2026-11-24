"""End-to-end API v2 & SQLite Migration 4 tests for prompt-driven university simulations."""

from __future__ import annotations

from tests.conftest import make_client


def test_end_to_end_tuition_hike_and_ranking_variants_offline(national_settings, national_client, population_id):
    c = national_client

    # 1. Plan & run: "How many students would apply to this uni if tuition increased by 30%?"
    plan1 = c.post(
        "/api/v2/university/query/plan",
        json={
            "prompt": "How many students would apply to this uni if tuition increased by 30%?",
            "context_university_id": "UNI_ANK_FOUND",
            "population_id": population_id,
            "cohort_size": 120,
            "seed": 42,
        },
    )
    assert plan1.status_code == 200, plan1.text
    p1 = plan1.json()
    assert p1["executable"] is True
    assert p1["coefficients_calibrated"] is False
    assert p1["osym_verified"] is False
    assert p1["catalog"]["rivals_fixed"] is True

    run1 = c.post(
        "/api/v2/university/query/runs",
        json={
            "prompt": p1["query_spec"]["original_prompt"],
            "query_spec": p1["query_spec"],
            "population_id": population_id,
            "cohort_size": 120,
            "seed": 42,
            "elasticity_preset": "medium",
        },
    )
    assert run1.status_code == 201, run1.text
    r1 = run1.json()
    assert r1["intent"] == "application_demand"
    assert r1["summary"]["generated_by"] == "deterministic"
    assert "apply" in r1["summary"]["direct_answer"].lower()
    assert r1["manifest"]["rivals_fixed"] is True
    assert r1["manifest"]["cohort_source"] == "tuik_population"
    assert r1["result"]["elasticity_range"] is not None
    sec_types = {s["type"] for s in r1["detailed_statistics"]}
    assert {"tiles", "table", "bar_series", "flow_summary"} <= sec_types

    # 2. Plan & run: "How would applications and cutoffs change if this uni's ranking got higher or lower?"
    plan2 = c.post(
        "/api/v2/university/query/plan",
        json={
            "prompt": "How would applications and cutoffs change if this uni's ranking got higher or lower?",
            "context_university_id": "UNI_ANK_FOUND",
            "cohort_size": 120,
            "seed": 42,
        },
    )
    assert plan2.status_code == 200, plan2.text
    p2 = plan2.json()
    assert p2["executable"] is True
    assert len(p2["query_spec"]["comparison_variants"]) == 3

    run2 = c.post(
        "/api/v2/university/query/runs",
        json={
            "prompt": p2["query_spec"]["original_prompt"],
            "query_spec": p2["query_spec"],
            "cohort_size": 120,
            "seed": 42,
        },
    )
    assert run2.status_code == 201, run2.text
    r2 = run2.json()
    assert r2["intent"] == "ranking_sensitivity"
    variants = r2["result"]["variants"]
    assert [v["variant_id"] for v in variants] == ["ranking_lower", "baseline", "ranking_higher"]
    assert variants[0]["listed_anywhere"] <= variants[1]["listed_anywhere"] <= variants[2]["listed_anywhere"]
    assert any(s["type"] == "comparison_set" for s in r2["detailed_statistics"])

    # 3. Revenue sweep & retention hybrid prompts
    rev_run = c.post(
        "/api/v2/university/query/runs",
        json={
            "prompt": "What tuition increase maximizes net revenue at Ankara Foundation University?",
            "cohort_size": 80,
            "seed": 42,
        },
    )
    assert rev_run.status_code == 201, rev_run.text
    rev_data = rev_run.json()
    assert rev_data["intent"] == "revenue_tradeoff"
    assert len(rev_data["result"]["sweep_rows"]) >= 5
    assert any(s["type"] == "line_series" for s in rev_data["detailed_statistics"])

    ret_run = c.post(
        "/api/v2/university/query/runs",
        json={
            "prompt": "How does a 25% tuition hike affect 4-semester retention and dropout at Ankara Foundation University?",
            "cohort_size": 80,
            "seed": 42,
        },
    )
    assert ret_run.status_code == 201, ret_run.text
    ret_data = ret_run.json()
    assert ret_data["intent"] == "retention_impact"
    assert ret_data["result"]["university_comparison"] is not None
    assert any(s["id"] == "retention_trajectory" for s in ret_data["detailed_statistics"])

    # 4. Persistence across fresh app restart (Migration 4)
    with make_client(national_settings) as restarted:
        listed = restarted.get("/api/v2/university/query/runs").json()
        run_ids = {item["run_id"] for item in listed["items"]}
        assert {r1["run_id"], r2["run_id"], rev_data["run_id"], ret_data["run_id"]} <= run_ids

        fetched = restarted.get(f"/api/v2/university/query/runs/{r1['run_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["result_sha256"] == r1["result_sha256"]
        assert restarted.get("/api/v2/university/query/runs/uquery-nope").status_code == 404


def test_query_edge_cases_aid_state_competitor_and_multi_compare(national_client):
    c = national_client

    # State (0 TL) tuition query emits explicit warning and produces zero spurious rival migration
    state_plan = c.post(
        "/api/v2/university/query/plan",
        json={
            "prompt": "How many students would apply to this uni if tuition increased by 30%?",
            "context_university_id": "UNI_ANK_STATE",
            "cohort_size": 120,
            "seed": 42,
        },
    )
    assert state_plan.status_code == 200
    assert any("0 TL" in w for w in state_plan.json()["warnings"])
    state_run = c.post(
        "/api/v2/university/query/runs",
        json={
            "prompt": "How many students would apply to this uni if tuition increased by 30%?",
            "context_university_id": "UNI_ANK_STATE",
            "cohort_size": 120,
            "seed": 42,
        },
    )
    assert state_run.status_code == 201
    sd = state_run.json()
    assert "0 TL" in sd["summary"]["direct_answer"]
    assert sd["result"]["analytics"]["migration"]["primary_or_placed_shifted_to_rival"] == 0

    # Financial aid increase disburses inferred base_aid_budget pool & lifts fee-paying applicants
    aid_run = c.post(
        "/api/v2/university/query/runs",
        json={
            "prompt": "What happens to applications if financial aid budget increases by 50%?",
            "context_university_id": "UNI_ANK_FOUND",
            "cohort_size": 200,
            "seed": 42,
        },
    )
    assert aid_run.status_code == 201, aid_run.text
    ad = aid_run.json()
    assert ad["query_spec"]["levers"]["base_aid_budget"] is not None
    assert ad["result"]["analytics"]["application_definitions"]["fee_paying_listed"]["delta"] >= 0

    # Competitor flow without crashing even when top_primary_rival_destinations is empty
    comp_run = c.post(
        "/api/v2/university/query/runs",
        json={
            "prompt": "Which rival universities gain our applicants if tuition rises by 30%?",
            "context_university_id": "UNI_IST_FOUND",
            "cohort_size": 200,
            "seed": 42,
        },
    )
    assert comp_run.status_code == 201, comp_run.text
    cd = comp_run.json()
    assert cd["intent"] == "competitor_flow"
    assert cd["result"]["analytics"]["migration"]["shifted_to_rival_uni"] > 0

    # Multi-scenario compare narrates all variants in headline
    mc_run = c.post(
        "/api/v2/university/query/runs",
        json={
            "prompt": "Compare -10% vs +20% vs +40% tuition at this uni.",
            "context_university_id": "UNI_ANK_FOUND",
            "cohort_size": 200,
            "seed": 42,
        },
    )
    assert mc_run.status_code == 201, mc_run.text
    md = mc_run.json()
    assert md["intent"] == "multi_scenario_compare"
    assert "Tuition -10%" in md["summary"]["headline"]
    assert "Tuition +40%" in md["summary"]["headline"]

    # Combined placement + retention question mentions retention pp delta in direct_answer
    both_run = c.post(
        "/api/v2/university/query/runs",
        json={
            "prompt": "How would a 25% tuition increase affect both applications and 4-semester retention at this uni?",
            "context_university_id": "UNI_ANK_FOUND",
            "cohort_size": 200,
            "seed": 42,
        },
    )
    assert both_run.status_code == 201, both_run.text
    bd = both_run.json()
    assert bd["query_spec"]["simulation_mode"] == "both"
    assert "semesters" in bd["summary"]["direct_answer"].lower()
    assert any(s["id"] == "retention_trajectory" for s in bd["detailed_statistics"])


def test_retention_handoff_uses_baseline_enrollees_and_fee_scaling(make_settings, tmp_path):
    import csv
    from societytwin.university.osym_importer import import_validated_osym_csvs

    p_csv = tmp_path / "p.csv"
    a_csv = tmp_path / "a.csv"
    t_csv = tmp_path / "t.csv"
    db_path = tmp_path / "university.sqlite3"

    def _dump(path, cols, rows):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=cols)
            writer.writeheader()
            writer.writerows(rows)

    _dump(
        p_csv,
        [
            "program_code", "admission_year", "campus_city", "university_name_official",
            "university_type", "program_name_official", "faculty_official", "degree_level",
            "score_type", "program_regime", "scholarship_tier", "teaching_language_explicit",
            "official_genel_success_rank_from_next_kilavuz",
        ],
        [
            {
                "program_code": "2001", "admission_year": 2026, "campus_city": "ANKARA",
                "university_name_official": "ANATOLIA VAKIF ÜNİVERSİTESİ", "university_type": "VAKIF",
                "program_name_official": "Bilgisayar Mühendisliği", "faculty_official": "Mühendislik",
                "degree_level": "lisans", "score_type": "SAY", "program_regime": "foundation_partial_or_paid",
                "scholarship_tier": "Ücretli", "teaching_language_explicit": "Türkçe",
                "official_genel_success_rank_from_next_kilavuz": "",
            },
            {
                "program_code": "2002", "admission_year": 2026, "campus_city": "ANKARA",
                "university_name_official": "ANATOLIA VAKIF ÜNİVERSİTESİ", "university_type": "VAKIF",
                "program_name_official": "Bilgisayar Mühendisliği", "faculty_official": "Mühendislik",
                "degree_level": "lisans", "score_type": "SAY", "program_regime": "foundation_partial_or_paid",
                "scholarship_tier": "%50 İndirimli", "teaching_language_explicit": "Türkçe",
                "official_genel_success_rank_from_next_kilavuz": "",
            },
            {
                "program_code": "2003", "admission_year": 2026, "campus_city": "ANKARA",
                "university_name_official": "ANKARA DEVLET ÜNİVERSİTESİ", "university_type": "DEVLET",
                "program_name_official": "Bilgisayar Mühendisliği", "faculty_official": "Mühendislik",
                "degree_level": "lisans", "score_type": "SAY", "program_regime": "state_standard",
                "scholarship_tier": "Devlet", "teaching_language_explicit": "Türkçe",
                "official_genel_success_rank_from_next_kilavuz": "",
            },
        ],
    )
    _dump(
        a_csv,
        ["quota_track", "program_code", "admission_year", "quota", "placed", "official_success_rank"],
        [
            {"quota_track": "genel", "program_code": "2001", "admission_year": 2026, "quota": 60, "placed": 60, "official_success_rank": 120000},
            {"quota_track": "genel", "program_code": "2002", "admission_year": 2026, "quota": 40, "placed": 40, "official_success_rank": 70000},
            {"quota_track": "genel", "program_code": "2003", "admission_year": 2026, "quota": 80, "placed": 80, "official_success_rank": 40000},
        ],
    )
    _dump(
        t_csv,
        [
            "program_code", "academic_year", "full_annual_tuition_try", "net_annual_tuition_try",
            "currency", "fee_type", "verification_status", "source_id", "kdv_included", "fee_basis_note",
        ],
        [
            {"program_code": "2001", "academic_year": "2026-2027", "full_annual_tuition_try": "640000", "net_annual_tuition_try": "640000", "currency": "TRY", "fee_type": "foundation", "verification_status": "verified", "source_id": "s1", "kdv_included": "true", "fee_basis_note": ""},
            {"program_code": "2002", "academic_year": "2026-2027", "full_annual_tuition_try": "640000", "net_annual_tuition_try": "320000", "currency": "TRY", "fee_type": "foundation", "verification_status": "verified", "source_id": "s1", "kdv_included": "true", "fee_basis_note": ""},
            {"program_code": "2003", "academic_year": "2026-2027", "full_annual_tuition_try": "0", "net_annual_tuition_try": "0", "currency": "TRY", "fee_type": "state", "verification_status": "verified", "source_id": "s1", "kdv_included": "true", "fee_basis_note": ""},
        ],
    )
    report = import_validated_osym_csvs(
        programs_csv=p_csv,
        admissions_csv=a_csv,
        tuition_csv=t_csv,
        database_path=db_path,
        target_year=2026,
    )

    with make_client(make_settings(university_db_path=db_path)) as client:
        ret_run = client.post(
            "/api/v2/university/query/runs",
            json={
                "prompt": "How does a 25% tuition increase affect 4-semester retention and dropout at Anatolia Vakif Universitesi?",
                "snapshot_id": report["snapshot_id"],
                "admission_year": 2026,
                "cohort_size": 240,
                "seed": 42,
            },
        )
        assert ret_run.status_code == 201, ret_run.text
        body = ret_run.json()
        assert body["intent"] == "retention_impact"
        ucmp = body["result"]["university_comparison"]
        assert ucmp["coefficients_calibrated"] is False
        assert ucmp["osym_verified"] is False
        ret_effect = ucmp["policy_effects"]["cumulative_retention_rate"]
        assert ret_effect["mean"] < 0.0
        assert ret_effect["baseline_mean"] > ret_effect["policy_mean"]
