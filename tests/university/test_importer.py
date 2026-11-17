"""Artificial workbooks only; no repository dataset is needed for these tests."""

import hashlib
import json
import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest
from openpyxl import Workbook, load_workbook

from societytwin.university import connect
from societytwin.university.importer import (
    ANNUAL, ANNUAL_HEADERS, NOTES, PARSER_VERSION, PROGRAM_HEADERS, PROGRAMS,
    SUMMARY, WorkbookError, import_workbook, main, parse_integer, parse_money,
)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "artificial.xlsx"
    workbook = Workbook()
    workbook.remove(workbook.active)
    programs = workbook.create_sheet(PROGRAMS)
    programs.append(PROGRAM_HEADERS)
    annual = workbook.create_sheet(ANNUAL)
    annual.append(ANNUAL_HEADERS)
    for i, (name, kind, language, quota, placed, rank) in enumerate([
        ("Synthetic A", "Synthetic foundation", "İngilizce", 1, 2, "12.345"),
        ("Synthetic A", "Synthetic foundation", "Türkçe", 0, 0, None),
        ("Synthetic B", "Synthetic state", None, None, 0, None),
    ], 1):
        record = dict.fromkeys(PROGRAM_HEADERS)
        record.update({"Üniversite": name, "Tür": kind, "Program Kodu": f"000{i}",
            "Bölüm / Program": "Synthetic English department", "Fakülte": "Synthetic faculty",
            "Puan Türü": "Synthetic score", "Burs / İndirim Durumu": "  Synthetic %50 Label  ",
            "Öğretim Dili": language, "Diğer Etiket": "Synthetic tag",
            "2025 Kontenjan": quota, "2025 Yerleşen": placed, "2025 Başarı Sırası": rank,
            "Sınav İzcisi Bağlantısı": f"https://example.invalid/{i}",
            "2026 Tam Ücret (TL)": "1.234.567,89" if i == 1 else (0 if i == 2 else None),
            "2026 Net Ücret (TL)": 0 if i <= 2 else None,
            "Ücret Notu 2026": "Synthetic annual fee note"})
        programs.append([record[h] for h in PROGRAM_HEADERS])
        annual.append([name, f"000{i}", record["Bölüm / Program"], record["Burs / İndirim Durumu"],
                       2025, quota, placed, rank])
    summary = workbook.create_sheet(SUMMARY)
    summary.append(["Üniversite", "Tür", "Program Sayısı"])
    summary.append(["Synthetic A", "Synthetic foundation", 2])
    summary.append(["Synthetic B", "Synthetic state", 1])
    workbook.create_sheet(NOTES).append(["Synthetic provenance; alındığı tarih 2099-01-01"])
    workbook.save(path)
    workbook.close()
    return path, tmp_path / "db.sqlite3"


def edit(path, action):
    workbook = load_workbook(path)
    try:
        action(workbook)
        workbook.save(path)
    finally:
        workbook.close()


def rows(db, query, args=()):
    with closing(connect(db)) as conn:
        return [tuple(r) for r in conn.execute(query, args)]


def test_import_universities_programs_and_annual(source):
    path, db = source
    report = import_workbook(path, db)
    assert report["counts"]["universities"] == 2
    assert report["counts"]["programs"] == 3
    assert report["counts"]["annual_admissions"] == 3
    assert report["admission_years"] == [2025]
    assert rows(db, "SELECT DISTINCT university_type FROM universities ORDER BY university_type") == [
        ("Synthetic foundation",), ("Synthetic state",)]
    assert rows(db, "SELECT official_university_code, city FROM universities") == [(None, None)] * 2
    assert rows(db, "SELECT name_original, faculty FROM programs LIMIT 1") == [
        ("Synthetic English department", "Synthetic faculty")]


def test_tuition_currency_minor_units_and_source_derivation(source):
    path, db = source
    report = import_workbook(path, db)
    assert report["counts"]["annual_tuition"] == 6
    full, net, currency, basis = rows(db, "SELECT full_amount_minor, net_amount_minor, currency, fee_basis FROM annual_tuition WHERE program_id=1 AND academic_year_start=2026")[0]
    assert (full, net, currency) == (123456789, 0, "TRY")
    assert json.loads(basis)["net_provenance"].startswith("source-derived")


def test_exact_scholarship_and_string_codes(source):
    path, db = source
    import_workbook(path, db)
    assert rows(db, "SELECT program_code, typeof(program_code), scholarship_original FROM programs ORDER BY program_code") == [
        (f"000{i}", "text", "  Synthetic %50 Label  ") for i in range(1, 4)]


def test_language_preservation_and_missing_no_inference(source):
    path, db = source
    import_workbook(path, db)
    assert rows(db, "SELECT teaching_language FROM programs ORDER BY program_code") == [("İngilizce",), ("Türkçe",), (None,)]


@pytest.mark.parametrize("language", ["", "  Other LABEL  ", "türkçe", "Deutsch"])
def test_language_empty_and_arbitrary_labels(source, language):
    path, db = source
    edit(path, lambda w: setattr(w[PROGRAMS].cell(2, 8), "value", language))
    import_workbook(path, db)
    assert rows(db, "SELECT teaching_language FROM programs WHERE program_code='0001'") == [(language or None,)]


def test_ranks_missing_zero_and_placed_above_quota(source):
    path, db = source
    report = import_workbook(path, db)
    assert rows(db, "SELECT quota, placed_students, success_rank FROM annual_admissions ORDER BY program_id") == [(1, 2, 12345), (0, 0, None), (None, 0, None)]
    assert report["missing_rankings"] == 2
    assert report["issue_counts"]["placed_above_quota"] == 1


def test_identical_program_duplicate_collapsed(source):
    path, db = source
    edit(path, lambda w: w[PROGRAMS].append([c.value for c in w[PROGRAMS][2]]))
    report = import_workbook(path, db)
    assert report["counts"]["programs"] == 3
    assert report["issue_counts"]["duplicate_program"] == 1


def test_conflicting_program_quarantines_all_variants(source):
    path, db = source
    def action(w):
        values = [c.value for c in w[PROGRAMS][2]]
        values[3] = "Conflicting department"
        w[PROGRAMS].append(values)
    edit(path, action)
    report = import_workbook(path, db)
    assert report["counts"]["programs"] == 2
    assert report["issue_counts"]["conflicting_program"] == 2
    assert report["issue_counts"]["unknown_program"] == 1


def test_conflicting_annual_quarantines_all_variants(source):
    path, db = source
    def action(w):
        values = [c.value for c in w[ANNUAL][2]]
        values[5] = 100
        w[ANNUAL].append(values)
    edit(path, action)
    report = import_workbook(path, db)
    assert report["counts"]["annual_admissions"] == 2
    assert report["issue_counts"]["conflicting_annual"] == 2


def test_duplicate_annual_collapsed(source):
    path, db = source
    edit(path, lambda w: w[ANNUAL].append([c.value for c in w[ANNUAL][2]]))
    report = import_workbook(path, db)
    assert report["counts"]["annual_admissions"] == 3
    assert report["issue_counts"]["duplicate_annual"] == 1


def test_cross_sheet_disagreement_quarantined(source):
    path, db = source
    edit(path, lambda w: setattr(w[ANNUAL].cell(2, 6), "value", 999))
    report = import_workbook(path, db)
    assert report["counts"]["annual_admissions"] == 2
    assert report["issue_counts"]["sheet_disagreement"] == 1


def test_repeated_import_preserves_all_logical_records(source):
    path, db = source
    first = import_workbook(path, db)
    with closing(connect(db)) as conn:
        before = list(conn.iterdump())
    second = import_workbook(path, db)
    with closing(connect(db)) as conn:
        assert list(conn.iterdump()) == before
    assert second == {**first, "reused_snapshot": True}


def test_failure_rolls_back_data_transaction(source):
    path, db = source
    with patch("societytwin.university.importer._report", side_effect=RuntimeError("injected failure")):
        with pytest.raises(RuntimeError, match="injected failure"):
            import_workbook(path, db)
    for table in ("source_snapshots", "universities", "programs", "annual_admissions", "annual_tuition", "data_quality_issues"):
        assert rows(db, f"SELECT count(*) FROM {table}") == [(0,)]
    assert import_workbook(path, db)["counts"]["programs"] == 3


def test_snapshot_provenance_and_original_unchanged(source):
    path, db = source
    before = path.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    report = import_workbook(path, db)
    assert path.read_bytes() == before
    assert report["snapshot_id"] == f"sha256:{digest}"
    assert report["sha256"] == digest
    assert report["integrity_check"] == ["ok"]
    assert report["foreign_key_check"] == []
    parser, reference, notes = rows(db, "SELECT importer_version, source_reference, notes FROM source_snapshots")[0]
    assert parser == PARSER_VERSION
    assert reference == path.as_posix()
    assert json.loads(notes)["program_metadata"][0]["source_url"] == "https://example.invalid/1"
    assert json.loads(notes)["program_metadata"][0]["other_label"] == "Synthetic tag"
    assert rows(db, "SELECT retrieved_at, verification_status FROM source_snapshots") == [("2099-01-01", "unverified")]


def test_revision_retains_history(source):
    path, db = source
    first = import_workbook(path, db)
    edit(path, lambda w: setattr(w[PROGRAMS].cell(2, 8), "value", "Revised label"))
    second = import_workbook(path, db)
    assert first["snapshot_id"] != second["snapshot_id"]
    assert rows(db, "SELECT count(*) FROM source_snapshots") == [(2,)]
    assert rows(db, "SELECT count(*) FROM programs") == [(6,)]
    assert rows(db, "SELECT teaching_language FROM programs WHERE snapshot_id=? AND program_code='0001'", (first["snapshot_id"],)) == [("İngilizce",)]
    assert second["foreign_key_check"] == []


@pytest.mark.parametrize("value,expected", [("1.234", 1234), (1234.0, 1234), ("1234,00", 1234), (None, None), (0, 0)])
def test_integer_parsing(value, expected):
    assert parse_integer(value) == expected


@pytest.mark.parametrize("value,expected", [("1.234,56", 123456), ("1.234.567", 123456700), (1234.56, 123456), ("1234.56", 123456), ("1,50", 150), (0, 0), (None, None)])
def test_money_parsing(value, expected):
    assert parse_money(value) == expected


@pytest.mark.parametrize("value", [-1, True, float("nan"), float("inf"), "1,234.56", "12.34.567", "unknown", 1.001, 2**63])
def test_invalid_money_rejected(value):
    with pytest.raises(ValueError):
        parse_money(value)


@pytest.mark.parametrize("value", [-1, True, 1.5, "1,5", "unknown"])
def test_invalid_integer_rejected(value):
    with pytest.raises(ValueError):
        parse_integer(value)


def test_invalid_measures_quarantined(source):
    path, db = source
    def action(w):
        w[ANNUAL].cell(2, 6).value = -1
        col = PROGRAM_HEADERS.index("2026 Net Ücret (TL)") + 1
        w[PROGRAMS].cell(2, col).value = -1
    edit(path, action)
    report = import_workbook(path, db)
    assert report["issue_counts"]["invalid_annual"] == 1
    assert report["issue_counts"]["invalid_tuition"] == 1
    assert report["counts"]["annual_admissions"] == 2
    assert report["counts"]["annual_tuition"] == 5


def test_formula_rejected_before_data_import(source):
    path, db = source
    edit(path, lambda w: setattr(w[PROGRAMS].cell(2, 8), "value", '=CONCAT("x", "y")'))
    with pytest.raises(WorkbookError, match="Formula"):
        import_workbook(path, db)
    assert not db.exists()


def test_layout_mismatch_rejected(source):
    path, db = source
    edit(path, lambda w: setattr(w[PROGRAMS].cell(1, 1), "value", "Unexpected"))
    with pytest.raises(WorkbookError, match="headers"):
        import_workbook(path, db)


def test_parser_mismatch_rejected(source):
    path, db = source
    import_workbook(path, db)
    with closing(connect(db)) as conn:
        conn.execute("UPDATE source_snapshots SET importer_version='different-parser'")
        conn.commit()
    with pytest.raises(WorkbookError, match="different parser"):
        import_workbook(path, db)


def test_numeric_program_code_is_not_guessed(source):
    path, db = source
    edit(path, lambda w: setattr(w[PROGRAMS].cell(2, 3), "value", 1))
    report = import_workbook(path, db)
    assert report["counts"]["programs"] == 2
    assert report["issue_counts"]["invalid_program"] == 1


def test_missing_long_row_not_synthesized(source):
    path, db = source
    edit(path, lambda w: w[ANNUAL].delete_rows(2))
    report = import_workbook(path, db)
    assert report["counts"]["annual_admissions"] == 2
    assert report["issue_counts"]["missing_long_record"] == 1


def test_summary_is_cross_check_not_import_source(source):
    path, db = source
    edit(path, lambda w: setattr(w[SUMMARY].cell(2, 3), "value", 999))
    report = import_workbook(path, db)
    assert report["counts"]["programs"] == 3
    assert report["issue_counts"]["summary_disagreement"] == 1


def test_cli_writes_report_and_protects_source(source, tmp_path, capsys):
    path, db = source
    report_path = tmp_path / "report.json"
    main(["--workbook", str(path), "--database", str(db), "--report", str(report_path)])
    assert json.loads(report_path.read_text(encoding="utf-8"))["counts"]["programs"] == 3
    assert json.loads(capsys.readouterr().out)["counts"]["programs"] == 3
    with pytest.raises(SystemExit):
        main(["--workbook", str(path), "--database", str(db), "--report", str(path)])
