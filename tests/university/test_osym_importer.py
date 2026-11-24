"""Synthetic unit tests for the validated ÖSYM Ankara CSV importer and rank fallback."""

from __future__ import annotations

import csv
from contextlib import closing
from pathlib import Path

from societytwin.university import connect
from societytwin.university.osym_importer import import_validated_osym_csvs
from societytwin.university.service import load_programs_from_sqlite_snapshot


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_import_validated_osym_csvs_filters_protects_codes_and_uses_prior_rank(tmp_path):
    p_csv = tmp_path / "programs.csv"
    a_csv = tmp_path / "admissions.csv"
    t_csv = tmp_path / "tuition.csv"
    db_path = tmp_path / "university.sqlite3"

    p_fields = [
        "program_code",
        "admission_year",
        "campus_city",
        "university_name_official",
        "university_type",
        "program_name_official",
        "faculty_official",
        "degree_level",
        "score_type",
        "program_regime",
        "scholarship_tier",
        "teaching_language_explicit",
        "official_genel_success_rank_from_next_kilavuz",
    ]
    a_fields = [
        "quota_track",
        "program_code",
        "admission_year",
        "quota",
        "placed",
        "official_success_rank",
    ]
    t_fields = [
        "program_code",
        "academic_year",
        "full_annual_tuition_try",
        "net_annual_tuition_try",
        "currency",
        "fee_type",
        "verification_status",
        "source_id",
        "kdv_included",
        "fee_basis_note",
    ]

    _write_csv(
        p_csv,
        p_fields,
        [
            # Active 2026 Ankara program whose 2025 code belonged to a different institution (reused code)
            {
                "program_code": "1001",
                "admission_year": 2026,
                "campus_city": "ANKARA",
                "university_name_official": "BAŞKENT ÜNİVERSİTESİ (ANKARA)",
                "university_type": "VAKIF",
                "program_name_official": "Bilgisayar Mühendisliği",
                "faculty_official": "Mühendislik Fakültesi",
                "degree_level": "lisans",
                "score_type": "SAY",
                "program_regime": "foundation_partial_or_paid",
                "scholarship_tier": "%50 İndirimli",
                "teaching_language_explicit": "Türkçe",
                "official_genel_success_rank_from_next_kilavuz": "",
            },
            {
                "program_code": "1001",
                "admission_year": 2025,
                "campus_city": "ANKARA",
                "university_name_official": "ESKİ ÜNİVERSİTE",
                "university_type": "VAKIF",
                "program_name_official": "Tarih",
                "faculty_official": "Edebiyat Fakültesi",
                "degree_level": "lisans",
                "score_type": "SÖZ",
                "program_regime": "foundation_partial_or_paid",
                "scholarship_tier": "Ücretli",
                "teaching_language_explicit": "Türkçe",
                "official_genel_success_rank_from_next_kilavuz": "",
            },
            # Active 2026 Ankara state program with NULL 2026 rank and clean 2025 history
            {
                "program_code": "1002",
                "admission_year": 2026,
                "campus_city": "ANKARA",
                "university_name_official": "ORTA DOĞU TEKNİK ÜNİVERSİTESİ",
                "university_type": "DEVLET",
                "program_name_official": "Bilgisayar Mühendisliği",
                "faculty_official": "Mühendislik Fakültesi",
                "degree_level": "lisans",
                "score_type": "SAY",
                "program_regime": "state_standard",
                "scholarship_tier": "Devlet",
                "teaching_language_explicit": "İngilizce",
                "official_genel_success_rank_from_next_kilavuz": "",
            },
            {
                "program_code": "1002",
                "admission_year": 2025,
                "campus_city": "ANKARA",
                "university_name_official": "ORTA DOĞU TEKNİK ÜNİVERSİTESİ",
                "university_type": "DEVLET",
                "program_name_official": "Bilgisayar Mühendisliği",
                "faculty_official": "Mühendislik Fakültesi",
                "degree_level": "lisans",
                "score_type": "SAY",
                "program_regime": "state_standard",
                "scholarship_tier": "Devlet",
                "teaching_language_explicit": "İngilizce",
                "official_genel_success_rank_from_next_kilavuz": "",
            },
            # Non-Ankara campus should be excluded
            {
                "program_code": "9999",
                "admission_year": 2026,
                "campus_city": "İSTANBUL",
                "university_name_official": "İSTANBUL ÜNİVERSİTESİ",
                "university_type": "DEVLET",
                "program_name_official": "Hukuk",
                "faculty_official": "Hukuk Fakültesi",
                "degree_level": "lisans",
                "score_type": "EA",
                "program_regime": "state_standard",
                "scholarship_tier": "Devlet",
                "teaching_language_explicit": "Türkçe",
                "official_genel_success_rank_from_next_kilavuz": "",
            },
        ],
    )

    _write_csv(
        a_csv,
        a_fields,
        [
            {"quota_track": "genel", "program_code": "1001", "admission_year": 2026, "quota": 50, "placed": 50, "official_success_rank": 65000},
            # Reused-code historical row (should be excluded!)
            {"quota_track": "genel", "program_code": "1001", "admission_year": 2025, "quota": 20, "placed": 20, "official_success_rank": 500000},
            # Active 2026 row with NULL rank + clean 2025 fallback rank (42000)
            {"quota_track": "genel", "program_code": "1002", "admission_year": 2026, "quota": 90, "placed": 90, "official_success_rank": ""},
            {"quota_track": "genel", "program_code": "1002", "admission_year": 2025, "quota": 90, "placed": 90, "official_success_rank": 42000},
            # Non-genel track must be skipped
            {"quota_track": "okul_birincisi", "program_code": "1002", "admission_year": 2026, "quota": 3, "placed": 3, "official_success_rank": ""},
        ],
    )

    _write_csv(
        t_csv,
        t_fields,
        [
            {
                "program_code": "1001",
                "academic_year": "2026-2027",
                "full_annual_tuition_try": "600000",
                "net_annual_tuition_try": "300000",
                "currency": "TRY",
                "fee_type": "foundation",
                "verification_status": "verified",
                "source_id": "src-1",
                "kdv_included": "true",
                "fee_basis_note": "",
            },
            {
                "program_code": "1002",
                "academic_year": "2026-2027",
                "full_annual_tuition_try": "0",
                "net_annual_tuition_try": "0",
                "currency": "TRY",
                "fee_type": "state",
                "verification_status": "verified",
                "source_id": "src-1",
                "kdv_included": "true",
                "fee_basis_note": "",
            },
        ],
    )

    report = import_validated_osym_csvs(
        programs_csv=p_csv,
        admissions_csv=a_csv,
        tuition_csv=t_csv,
        database_path=db_path,
        target_year=2026,
    )
    assert report["reused_snapshot"] is False
    assert report["counts"] == {
        "universities": 2,
        "programs": 2,
        "annual_admissions": 3,
        "annual_tuition": 2,
        "reused_code_history_excluded": 1,
    }
    assert report["integrity_check"] == ["ok"]
    assert report["foreign_key_check"] == []

    # Idempotent re-import reuses snapshot without duplicating data
    again = import_validated_osym_csvs(
        programs_csv=p_csv,
        admissions_csv=a_csv,
        tuition_csv=t_csv,
        database_path=db_path,
        target_year=2026,
    )
    assert again["reused_snapshot"] is True
    assert again["snapshot_id"] == report["snapshot_id"]

    with closing(connect(db_path)) as conn:
        cities = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT name_normalized, city FROM universities WHERE snapshot_id=?",
                (report["snapshot_id"],),
            )
        }
        assert cities == {
            "Başkent Üniversitesi": "Ankara",
            "Orta Doğu Teknik Üniversitesi": "Ankara",
        }
        ver_status = conn.execute(
            "SELECT verification_status FROM source_snapshots WHERE snapshot_id=?",
            (report["snapshot_id"],),
        ).fetchone()[0]
        assert ver_status == "verified"

    loaded, load_report = load_programs_from_sqlite_snapshot(db_path, report["snapshot_id"], admission_year=2026)
    assert load_report["programs_loaded"] == 2
    assert load_report["prior_year_rank_fallback_count"] == 1
    assert load_report["missing_rank_count"] == 0
    assert all(p.province_code == "06" for p in loaded)
    by_code = {p.program_id: p for p in loaded}
    assert by_code["1002"].university_rank == 42000
    assert (by_code["1002"].prestige_score or 0.0) > 0.22
