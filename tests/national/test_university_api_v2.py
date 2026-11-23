"""API v2 & SQLite Migration 3 integration tests for university placement & policy routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from societytwin.api.app import create_app
from tests.conftest import make_client


def test_placement_and_university_api_persistence_and_handoff(national_settings, national_client, population_id):
    c = national_client

    # 1. Placement program catalog exposes simplified rules & explicit osym_verified=False
    cat_res = c.get("/api/v2/placement/programs")
    assert cat_res.status_code == 200
    cat = cat_res.json()
    assert cat["osym_verified"] is False
    assert cat["rule_fidelity"] == "hypothetical_simplified"
    assert len(cat["programs"]) >= 4

    # 2. Standalone placement run + baseline comparison + SQLite persistence
    p1 = c.post(
        "/api/v2/placement/runs",
        json={
            "scenario_id": "uni_placement_quota_001",
            "cohort_size": 80,
            "seed": 42,
            "compare_baseline": True,
        },
    )
    assert p1.status_code == 201, p1.text
    p1_data = p1.json()
    assert p1_data["osym_verified"] is False
    assert p1_data["result"]["comparison"] is not None
    assert p1_data["result"]["admitted_count"] > 0

    # 2b. Baseline placement run with identical cohort/seed allows 200 OK paired compare
    p_base = c.post(
        "/api/v2/placement/runs",
        json={
            "cohort_size": 80,
            "seed": 42,
            "compare_baseline": False,
        },
    )
    assert p_base.status_code == 201, p_base.text
    matched_cmp = c.post(
        "/api/v2/placement/compare",
        json={"baseline_run_id": p_base.json()["run_id"], "policy_run_id": p1_data["run_id"]},
    )
    assert matched_cmp.status_code == 200, matched_cmp.text
    cmp_body = matched_cmp.json()
    assert cmp_body["comparison"]["transitions"]["total_candidates"] == 80
    assert cmp_body["summary"]["osym_verified"] is False

    # 3. TÜİK-anchored placement run linked to a persisted synthetic population
    p2 = c.post(
        "/api/v2/placement/runs",
        json={
            "population_id": population_id,
            "cohort_size": 60,
            "seed": 42,
            "compare_baseline": True,
            "intervention": {"tuition_change_pct": 20.0, "affordability_filter_mode": "hard_exclude"},
        },
    )
    assert p2.status_code == 201, p2.text
    p2_data = p2.json()
    assert p2_data["population_id"] == population_id
    assert p2_data["result"]["demographic_source"] == "tuik_population"

    # 4. Counterfactual compare guard rejects mismatched cohorts with 409 conflict
    mismatch = c.post(
        "/api/v2/placement/compare",
        json={"baseline_run_id": p1_data["run_id"], "policy_run_id": p2_data["run_id"]},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "cohort_mismatch"

    # 5. Chain persisted placement run into Milestone 2 multi-semester policy simulation
    u1 = c.post(
        "/api/v2/university/runs",
        json={
            "placement_run_id": p1_data["run_id"],
            "semester_count": 3,
            "replications": 4,
            "seed": 42,
            "compare_baseline": True,
            "intervention": {"tuition_change_pct": 20.0, "installment_count": 4},
        },
    )
    assert u1.status_code == 201, u1.text
    u1_data = u1.json()
    assert u1_data["placement_run_id"] == p1_data["run_id"]
    assert u1_data["osym_verified"] is False
    assert u1_data["coefficients_calibrated"] is False
    assert u1_data["comparison"]["replications"] == 4
    assert len(u1_data["comparison"]["policy_trajectory"]) == 4  # Terms 0..3

    # 6. Tuition sensitivity sweep endpoint
    sweep_res = c.post(
        "/api/v2/university/sweep",
        json={"cohort_size": 60, "semester_count": 2, "replications": 2, "tuition_pcts": [0.0, 20.0]},
    )
    assert sweep_res.status_code == 200, sweep_res.text
    sweep = sweep_res.json()
    assert sweep["osym_verified"] is False
    assert sweep["coefficients_calibrated"] is False
    assert len(sweep["rows"]) == 2

    # 7. Reloading against fresh FastAPI instance verifies SQLite Migration 3 persistence
    with make_client(national_settings) as restarted:
        p_list = restarted.get("/api/v2/placement/runs").json()
        assert p1_data["run_id"] in {item["run_id"] for item in p_list["items"]}
        p_detail = restarted.get(f"/api/v2/placement/runs/{p1_data['run_id']}").json()
        assert p_detail["result_sha256"] == p1_data["result_sha256"]

        u_list = restarted.get("/api/v2/university/runs").json()
        assert u1_data["run_id"] in {item["run_id"] for item in u_list["items"]}
        u_detail = restarted.get(f"/api/v2/university/runs/{u1_data['run_id']}").json()
        assert u_detail["result_sha256"] == u1_data["result_sha256"]

        # 8. Built-in scenario YAML executes directly via /api/v2/university/runs & 404/422 errors are structured
        u_sc = restarted.post(
            "/api/v2/university/runs",
            json={"scenario_id": "uni_tuition_hike_001", "cohort_size": 50, "semester_count": 2, "replications": 2},
        )
        assert u_sc.status_code == 201, u_sc.text
        assert u_sc.json()["scenario_id"] == "uni_tuition_hike_001"
        assert restarted.get("/api/v2/placement/runs/uplace-nope").status_code == 404
        assert restarted.get("/api/v2/university/runs/univ-nope").status_code == 404
        assert restarted.post("/api/v2/placement/runs", json={"scenario_id": "nope_sc"}).status_code == 404
        assert restarted.post("/api/v2/university/runs", json={"cohort_size": 5}).status_code == 422


def test_university_mutations_require_loopback(settings):
    with TestClient(create_app(settings, start_worker=False)) as remote:  # host is "testclient", not loopback
        r1 = remote.post("/api/v2/placement/runs", json={"cohort_size": 40})
        assert r1.status_code == 403 and r1.json()["error"]["code"] == "mutations_local_only"
        r2 = remote.post("/api/v2/university/runs", json={"cohort_size": 40})
        assert r2.status_code == 403 and r2.json()["error"]["code"] == "mutations_local_only"
        assert remote.get("/api/v2/placement/programs").status_code == 200


def test_university_registry_sqlite_endpoints_graceful_when_missing(national_client, national_settings):
    db_path = national_settings.university_db_path
    assert not db_path.exists()
    status = national_client.get("/api/v2/university-registry/status")
    assert status.status_code == 200
    assert status.json()["available"] is False
    assert not db_path.exists(), "Read-only status check must never create an empty SQLite file"
    snaps = national_client.get("/api/v2/university-registry/snapshots")
    assert snaps.status_code == 200 and snaps.json()["available"] is False and snaps.json()["items"] == []
    assert national_client.get("/api/v2/university-registry/snapshots/missing/programs").status_code == 503
    cand = national_client.get("/api/v2/university-registry/candidates/preview", params={"seed": 42, "size": 10})
    assert cand.status_code == 200
    cand_body = cand.json()
    assert cand_body["manifest"]["generator_version"] == "candidate-development-v1"
    assert len(cand_body["candidates"]) == 10


def test_university_registry_sqlite_endpoints_query_imported_snapshot(make_settings, tmp_path):
    from societytwin.university.db import connect, initialize_database

    db_path = tmp_path / "university.sqlite3"
    initialize_database(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO source_snapshots(snapshot_id, source_filename, file_sha256, imported_at, importer_version, verification_status) "
            "VALUES ('snap-2026', 'ankara.xlsx', ?, '2026-10-20T00:00:00Z', 'university-xlsx-v1', 'unverified')",
            ("a" * 64,),
        )
        conn.execute(
            "INSERT INTO universities(university_id, snapshot_id, university_key, name_original, name_normalized, university_type, city) "
            "VALUES (1, 'snap-2026', 'ankara_test_u', 'Ankara Test Üniversitesi', 'ankara test universitesi', 'Vakıf', 'Ankara')"
        )
        conn.execute(
            "INSERT INTO programs(program_id, snapshot_id, university_id, program_code, name_original, degree_level, score_type, scholarship_original, source_sheet, source_row) "
            "VALUES (10, 'snap-2026', 1, '200100101', 'Bilgisayar Mühendisliği', 'Lisans', 'SAY', 'Burslu', 'Programlar', 2)"
        )
        conn.execute(
            "INSERT INTO annual_admissions(program_id, snapshot_id, admission_year, quota, placed_students, success_rank, source_sheet, source_row) "
            "VALUES (10, 'snap-2026', 2025, 40, 40, 12500, 'Yıllık Uzun Format', 2)"
        )
        conn.execute(
            "INSERT INTO annual_tuition(program_id, snapshot_id, academic_year_start, full_amount_minor, net_amount_minor, currency, source_sheet, source_row) "
            "VALUES (10, 'snap-2026', 2025, 45000000, 0, 'TRY', 'Programlar', 2)"
        )
        conn.execute(
            "INSERT INTO data_quality_issues(snapshot_id, issue_key, severity, issue_code, message, program_id, related_year) "
            "VALUES ('snap-2026', 'iss-1', 'warning', 'missing_quota', 'Sample warning', 10, 2024)"
        )
        conn.commit()

    with make_client(make_settings(university_db_path=db_path)) as c:
        st = c.get("/api/v2/university-registry/status").json()
        assert st["available"] is True and st["snapshots"][0]["counts"]["programs"] == 1
        progs = c.get("/api/v2/university-registry/snapshots/snap-2026/programs", params={"score_type": "SAY", "q": "Bilgisayar"}).json()
        assert progs["total"] == 1 and progs["items"][0]["program_code"] == "200100101"
        detail = c.get("/api/v2/university-registry/snapshots/snap-2026/programs/200100101").json()
        assert len(detail["admissions"]) == 1 and detail["tuition"][0]["full_amount_minor"] == 45000000
        issues = c.get("/api/v2/university-registry/snapshots/snap-2026/issues").json()
        assert issues["total"] == 1 and issues["items"][0]["issue_code"] == "missing_quota"
        assert c.get("/api/v2/university-registry/snapshots/snap-2026/programs/999999").status_code == 404
        assert c.get("/api/v2/university-registry/snapshots/nope/programs").status_code == 404
