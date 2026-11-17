"""Read-only import of the inspected university workbook layout.

Run with ``python -m societytwin.university.importer --help``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from .db import connect, initialize_database

PARSER_VERSION = "university-xlsx-v1"
PROGRAMS = "Programlar"
ANNUAL = "Yıllık Uzun Format"
SUMMARY = "Üniversite Özeti"
NOTES = "Açıklamalar"
YEARS = range(2019, 2027)
BASE_HEADERS = ["Üniversite", "Tür", "Program Kodu", "Bölüm / Program", "Fakülte",
                "Puan Türü", "Burs / İndirim Durumu", "Öğretim Dili", "Diğer Etiket"]
ANNUAL_HEADERS = ["Üniversite", "Program Kodu", "Bölüm", "Burs Durumu", "Yıl",
                  "Kontenjan", "Yerleşen", "Başarı Sırası"]
PROGRAM_HEADERS = BASE_HEADERS + [f"{y} {field}" for y in YEARS for field in
                  ("Kontenjan", "Yerleşen", "Başarı Sırası")] + [
                  f"{y} {field} Ücret (TL)" for y in (2025, 2026) for field in ("Tam", "Net")
                  ] + ["Ücret Notu 2026", "Sınav İzcisi Bağlantısı"]


class WorkbookError(ValueError):
    """The input layout or content cannot be imported safely."""


def _number(value) -> Decimal | None:
    """Parse numeric cells or unambiguous Turkish-formatted numeric strings.

    Dot groups of three denote thousands, comma denotes decimals. A lone dot
    with one/two following digits denotes decimals; ambiguous formats fail.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a number")
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", text):
            text = text.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"[+-]?\d+(?:,\d{1,2})?", text):
            text = text.replace(",", ".")
        elif not re.fullmatch(r"[+-]?\d+\.\d{1,2}", text):
            raise ValueError(f"Unsupported numeric format: {value!r}")
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid number: {value!r}") from exc
    else:
        raise ValueError(f"Unsupported numeric type: {type(value).__name__}")
    if not number.is_finite():
        raise ValueError("Non-finite number")
    return number


def parse_integer(value, *, positive=False) -> int | None:
    number = _number(value)
    if number is None:
        return None
    if number != number.to_integral_value() or number < (1 if positive else 0):
        raise ValueError(f"Invalid integer measure: {value!r}")
    if number > 2**63 - 1:
        raise ValueError("Integer exceeds SQLite range")
    return int(number)


def parse_money(value) -> int | None:
    number = _number(value)
    if number is None:
        return None
    minor = number * 100
    if number < 0 or minor != minor.to_integral_value() or minor > 2**63 - 1:
        raise ValueError(f"Invalid monetary amount: {value!r}")
    return int(minor)


def _code(value) -> str:
    # Refuse numeric codes rather than guessing lost leading zeros/Excel formats.
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise ValueError("Program code must be an explicit digit string")
    return value


def _text(value, *, required=False):
    if value is None or value == "":
        if required:
            raise ValueError("Required text is missing")
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError("Expected source text")
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _read(payload):
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=False)
    try:
        missing = {PROGRAMS, ANNUAL, SUMMARY, NOTES} - set(workbook.sheetnames)
        if missing:
            raise WorkbookError(f"Missing worksheets: {sorted(missing)}")
        sheets = {}
        for sheet in workbook:
            rows = []
            for row_number, cells in enumerate(sheet.iter_rows(), 1):
                if any(cell.data_type == "f" for cell in cells):
                    raise WorkbookError(f"Formula cells are unsupported: {sheet.title}:{row_number}")
                values = [cell.value for cell in cells]
                if any(v is not None for v in values):
                    rows.append((row_number, values))
            sheets[sheet.title] = rows
        for name, required in ((PROGRAMS, PROGRAM_HEADERS), (ANNUAL, ANNUAL_HEADERS),
                               (SUMMARY, ["Üniversite", "Tür", "Program Sayısı"])):
            if not sheets[name] or sheets[name][0][0] != 1:
                raise WorkbookError(f"Expected headers on row 1: {name}")
            headers = sheets[name][0][1]
            if (len(set(headers)) != len(headers) or not set(required) <= set(headers)
                    or (name != SUMMARY and set(headers) != set(required))):
                raise WorkbookError(f"Unsupported or duplicate headers: {name}; expected {required}")
            sheets[name] = [(n, dict(zip(headers, values))) for n, values in sheets[name][1:]]
        return sheets
    finally:
        workbook.close()


def _report(conn, snapshot_id):
    counts = {table: conn.execute(f"SELECT count(*) FROM {table} WHERE snapshot_id=?",
                                 (snapshot_id,)).fetchone()[0] for table in
              ("universities", "programs", "annual_admissions", "annual_tuition", "data_quality_issues")}
    scalar = lambda sql: conn.execute(sql, (snapshot_id,)).fetchone()[0]
    snapshot = dict(conn.execute("SELECT * FROM source_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone())
    metadata = json.loads(snapshot["notes"])
    years = [row[0] for row in conn.execute("SELECT DISTINCT admission_year FROM annual_admissions WHERE snapshot_id=? ORDER BY admission_year", (snapshot_id,))]
    issues = [dict(row) for row in conn.execute("SELECT * FROM data_quality_issues WHERE snapshot_id=? ORDER BY issue_key", (snapshot_id,))]
    tuition = [dict(row) for row in conn.execute(
        "SELECT academic_year_start AS fee_year, count(*) AS records, "
        "sum(full_amount_minor IS NULL) AS missing_full, sum(net_amount_minor IS NULL) AS missing_net, "
        "sum(full_amount_minor IS NOT NULL OR net_amount_minor IS NOT NULL) AS records_with_amount "
        "FROM annual_tuition WHERE snapshot_id=? GROUP BY academic_year_start ORDER BY academic_year_start", (snapshot_id,))]
    return {
        "snapshot_id": snapshot_id, "sha256": snapshot["file_sha256"], "parser_version": snapshot["importer_version"],
        "counts": counts, "source_counts": metadata["source_counts"], "admission_years": years,
        "missing_language": scalar("SELECT count(*) FROM programs WHERE snapshot_id=? AND teaching_language IS NULL"),
        "missing_rankings": scalar("SELECT count(*) FROM annual_admissions WHERE snapshot_id=? AND success_rank IS NULL"),
        "tuition_by_year": tuition,
        "admissions_by_year": [dict(row) for row in conn.execute(
            "SELECT admission_year, count(*) AS records FROM annual_admissions WHERE snapshot_id=? GROUP BY admission_year ORDER BY admission_year", (snapshot_id,))],
        "reconciliation": {
            "program_rows_not_inserted": metadata["source_counts"][PROGRAMS] - counts["programs"],
            "annual_rows_not_inserted": metadata["source_counts"][ANNUAL] - counts["annual_admissions"],
            "fee_year_slots_not_inserted": 2 * metadata["source_counts"][PROGRAMS] - counts["annual_tuition"],
        },
        "source_cautions": [
            "Net tuition is calculated in the source, not an independent observation; retained without recomputation.",
            "Fee labels specify 2025 and 2026; academic-year boundaries are unverified.",
            "Source provenance is workbook-reported; no external verification was performed.",
        ],
        "issue_counts": dict(sorted(Counter(i["issue_code"] for i in issues).items())),
        "issues": issues, "source_notes": metadata["source_notes"],
        "integrity_check": [row[0] for row in conn.execute("PRAGMA integrity_check")],
        "foreign_key_check": [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")],
    }


def import_workbook(workbook_path: str | Path, database_path: str | Path) -> dict:
    """Import one immutable byte snapshot; return counts and full quality report.

    Invalid rows and conflicting identities are quarantined as quality issues.
    Structural errors or unexpected exceptions roll back the entire data import.
    An empty initialized schema may remain after a failed import.
    """
    workbook_path, database_path = Path(workbook_path), Path(database_path)
    if workbook_path.resolve() == database_path.resolve():
        raise WorkbookError("Source workbook and database must be different files")
    payload = workbook_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    snapshot_id = f"sha256:{digest}"
    sheets = _read(payload)
    initialize_database(database_path)
    conn = connect(database_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT snapshot_id, importer_version FROM source_snapshots WHERE file_sha256=?", (digest,)).fetchone()
        if existing:
            if existing["importer_version"] != PARSER_VERSION:
                raise WorkbookError("This file was imported with a different parser; explicit migration is required")
            report = _report(conn, existing["snapshot_id"])
            if report["integrity_check"] != ["ok"] or report["foreign_key_check"]:
                raise WorkbookError("Database integrity checks failed")
            conn.commit()
            return {**report, "reused_snapshot": True}
        notes = [value for _, row in sheets[NOTES] for value in row if value is not None]
        metadata = {
            "source_counts": {name: len(sheets[name]) for name in (PROGRAMS, ANNUAL, SUMMARY)},
            "source_notes": notes, "program_metadata": [],
            "tuition_semantics": "Source fee-year labels retained; academic-year boundaries unverified. Net fees are source-derived, not independently observed or recomputed.",
        }
        retrieval_dates = {match.group(1) for note in notes if isinstance(note, str)
                           for match in re.finditer(r"alındığı tarih (\d{4}-\d{2}-\d{2})", note)}
        retrieved_at = next(iter(retrieval_dates)) if len(retrieval_dates) == 1 else None
        if retrieved_at:
            try:
                datetime.strptime(retrieved_at, "%Y-%m-%d")
            except ValueError:
                retrieved_at = None
        metadata["retrieval_date_provenance"] = "Workbook Açıklamalar; source data retrieval, not file creation or independent verification"
        conn.execute("INSERT INTO source_snapshots (snapshot_id, source_filename, file_sha256, imported_at, importer_version, source_description, source_reference, retrieved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (snapshot_id, workbook_path.name, digest, datetime.now(timezone.utc).isoformat(),
                      PARSER_VERSION, "University workbook; original source statements preserved in notes", workbook_path.as_posix(), retrieved_at))

        def issue(sheet, row, code, message, raw=None, program=None, year=None, severity="warning", column=None):
            key = _json([sheet, row, column, code, year])
            conn.execute("INSERT INTO data_quality_issues (snapshot_id, issue_key, severity, issue_code, message, source_sheet, source_row, source_column, raw_value, program_id, related_year) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (snapshot_id, key, severity, code, message, sheet, row, column,
                          _json(raw) if raw is not None else None, program, year))

        grouped = defaultdict(list)
        institution_types = defaultdict(set)
        for row, record in sheets[PROGRAMS]:
            metadata["program_metadata"].append({"source_row": row, "program_code": record["Program Kodu"],
                "source_url": record["Sınav İzcisi Bağlantısı"], "other_label": record["Diğer Etiket"],
                "fee_note_2026": record["Ücret Notu 2026"]})
            try:
                code = _code(record["Program Kodu"])
            except ValueError as exc:
                issue(PROGRAMS, row, "invalid_program", str(exc), record, severity="error")
                continue
            grouped[code].append((row, record))
            if isinstance(record["Üniversite"], str):
                institution_types[record["Üniversite"]].add(record["Tür"])

        programs, originals, university_ids = {}, {}, {}
        for code in sorted(grouped):
            records = grouped[code]
            row, record = records[0]
            if any(other != record for _, other in records[1:]):
                for n, other in records:
                    issue(PROGRAMS, n, "conflicting_program", "All rows for conflicting program code quarantined", other, severity="error")
                continue
            try:
                name = _text(record["Üniversite"], required=True)
                kind = _text(record["Tür"], required=True)
                department = _text(record["Bölüm / Program"], required=True)
                fields = [_text(record[h]) for h in ("Fakülte", "Puan Türü", "Burs / İndirim Durumu", "Öğretim Dili")]
                if len(institution_types[name]) != 1:
                    raise ValueError("Conflicting institution types for exact university name")
            except ValueError as exc:
                issue(PROGRAMS, row, "invalid_program", str(exc), record, severity="error")
                continue
            if name not in university_ids:
                # Exact-name matching; preserve distinct source labels without merging.
                university_ids[name] = conn.execute(
                    "INSERT INTO universities (snapshot_id, university_key, name_original, name_normalized, university_type) VALUES (?, ?, ?, ?, ?)",
                    (snapshot_id, "name-sha256:" + hashlib.sha256(name.encode("utf-8")).hexdigest(), name, name, kind)).lastrowid
            programs[code] = conn.execute(
                "INSERT INTO programs (snapshot_id, university_id, program_code, name_original, faculty, score_type, scholarship_original, teaching_language, source_sheet, source_row) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snapshot_id, university_ids[name], code, department, *fields, PROGRAMS, row)).lastrowid
            originals[code] = record
            for n, other in records[1:]:
                issue(PROGRAMS, n, "duplicate_program", "Identical duplicate collapsed", other, programs[code])
            for year in (2025, 2026):
                full, net = (record[f"{year} {label} Ücret (TL)"] for label in ("Tam", "Net"))
                try:
                    full_minor, net_minor = parse_money(full), parse_money(net)
                except ValueError as exc:
                    issue(PROGRAMS, row, "invalid_tuition", str(exc), {"full": full, "net": net}, programs[code], year, "error")
                    continue
                basis = _json({"fee_year_label": year, "unit": "TL per year", "net_provenance": "source-derived; see Açıklamalar",
                               "academic_year_boundaries": "unverified", "source_note": record["Ücret Notu 2026"] if year == 2026 else None})
                # Keep explicit NULL quotes for both fee years: absence is not zero.
                conn.execute("INSERT INTO annual_tuition (program_id, snapshot_id, academic_year_start, full_amount_minor, net_amount_minor, currency, fee_basis, source_sheet, source_row) VALUES (?, ?, ?, ?, ?, 'TRY', ?, ?, ?)",
                             (programs[code], snapshot_id, year, full_minor, net_minor, basis, PROGRAMS, row))

        annual_groups = defaultdict(list)
        for row, record in sheets[ANNUAL]:
            try:
                code = _code(record["Program Kodu"])
                year = parse_integer(record["Yıl"], positive=True)
                if year not in YEARS:
                    raise ValueError("Unsupported admission year")
            except ValueError as exc:
                issue(ANNUAL, row, "invalid_annual_identity", str(exc), record, severity="error")
                continue
            annual_groups[code, year].append((row, record))

        for (code, year), records in sorted(annual_groups.items()):
            program = programs.get(code)
            row, record = records[0]
            if program is None:
                for n, other in records:
                    issue(ANNUAL, n, "unknown_program", "No accepted parent program; annual row quarantined", other, year=year, severity="error")
                continue
            source = originals[code]
            if any(other != record for _, other in records[1:]):
                for n, other in records:
                    issue(ANNUAL, n, "conflicting_annual", "All conflicting annual rows quarantined", other, program, year, "error")
                continue
            try:
                if (record["Üniversite"], record["Bölüm"], record["Burs Durumu"]) != (source["Üniversite"], source["Bölüm / Program"], source["Burs / İndirim Durumu"]):
                    raise ValueError("Annual identity disagrees with Programlar")
                values = tuple(parse_integer(record[h], positive=h == "Başarı Sırası") for h in ("Kontenjan", "Yerleşen", "Başarı Sırası"))
                wide = tuple(parse_integer(source[f"{year} {h}"], positive=h == "Başarı Sırası") for h in ("Kontenjan", "Yerleşen", "Başarı Sırası"))
                if values != wide:
                    issue(ANNUAL, row, "sheet_disagreement", "Annual observation quarantined: long and wide values differ", {"long": record, "wide": wide}, program, year, "error")
                    continue
            except ValueError as exc:
                issue(ANNUAL, row, "invalid_annual", str(exc), record, program, year, "error")
                continue
            conn.execute("INSERT INTO annual_admissions (program_id, snapshot_id, admission_year, quota, placed_students, success_rank, source_sheet, source_row) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (program, snapshot_id, year, *values, ANNUAL, row))
            for n, other in records[1:]:
                issue(ANNUAL, n, "duplicate_annual", "Identical duplicate collapsed", other, program, year)
            if values[0] is not None and values[1] is not None and values[1] > values[0]:
                issue(ANNUAL, row, "placed_above_quota", "Source placed count exceeds displayed quota; preserved unchanged", record, program, year)

        for code, source in sorted(originals.items()):
            for year in YEARS:
                if (code, year) not in annual_groups and any(source[f"{year} {h}"] is not None for h in ("Kontenjan", "Yerleşen", "Başarı Sırası")):
                    issue(PROGRAMS, grouped[code][0][0], "missing_long_record", "Wide data has no authoritative long-format row; not synthesized", source, programs[code], year, "error")

        # Summary is a calculated cross-check, never an observations source.
        summary_names = set()
        for row, record in sheets[SUMMARY]:
            name = record["Üniversite"]
            summary_names.add(name)
            source_records = [r for _, r in sheets[PROGRAMS] if r["Üniversite"] == name]
            mismatches = {}
            if name not in university_ids or record["Tür"] not in institution_types.get(name, set()):
                mismatches["identity"] = record
            try:
                if parse_integer(record["Program Sayısı"]) != len(source_records):
                    mismatches["program_count"] = record["Program Sayısı"]
                for year in YEARS:
                    for label in ("Kontenjan", "Yerleşen"):
                        header = f"{year} Toplam {label}"
                        if header in record:
                            total = sum(parse_integer(r[f"{year} {label}"]) or 0 for r in source_records)
                            if parse_integer(record[header]) != total:
                                mismatches[header] = {"summary": record[header], "wide_sum": total}
            except ValueError as exc:
                mismatches["invalid_summary_measure"] = str(exc)
            if mismatches:
                issue(SUMMARY, row, "summary_disagreement", "Calculated university summary disagrees with program sheet", mismatches)
        metadata["source_counts"]["distinct_universities"] = len(institution_types)
        metadata["universities_missing_summary"] = sorted(set(university_ids) - summary_names)
        conn.execute("UPDATE source_snapshots SET notes=? WHERE snapshot_id=?", (_json(metadata), snapshot_id))
        report = _report(conn, snapshot_id)
        if report["integrity_check"] != ["ok"] or report["foreign_key_check"]:
            raise WorkbookError("Database integrity checks failed")
        conn.commit()
        return {**report, "reused_snapshot": False}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=Path("data/raw/university/Universite_Bolum_Kontenjan_Yerlesen_Sira_Burs_Ucret.xlsx"))
    parser.add_argument("--database", type=Path, default=Path("data/processed/university/university.sqlite3"))
    parser.add_argument("--report", type=Path, default=Path("data/processed/university/import-report.json"))
    args = parser.parse_args(argv)
    if args.report.resolve() in (args.workbook.resolve(), args.database.resolve()):
        parser.error("Report must not overwrite the workbook or database")
    report = import_workbook(args.workbook, args.database)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(_json(report) + "\n", encoding="utf-8")
    print(_json({k: v for k, v in report.items() if k not in ("issues", "source_notes")}))


if __name__ == "__main__":
    main()
