"""Validated 2019-2026 Ankara ÖSYM & tuition CSV importer into the university SQLite schema.

Run with ``python -m societytwin.university.osym_importer --help``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .db import connect, initialize_database
from .importer import _code, _json, parse_integer, parse_money

PARSER_VERSION = "osym-validated-csv-v1"
DEFAULT_PROGRAMS_CSV = Path("data/raw/university/osym/ankara_programs_2019_2026_validated.csv")
DEFAULT_ADMISSIONS_CSV = Path("data/raw/university/osym/ankara_admissions_tracks_2019_2026_validated.csv")
DEFAULT_TUITION_CSV = Path("data/raw/university/osym/ankara_tuition_2026_2027_complete_validated.csv")
DEFAULT_DATABASE = Path("data/processed/university/university.sqlite3")
DEFAULT_REPORT = Path("data/processed/university/osym-import-report.json")

_TR_UPPER_TO_LOWER = str.maketrans({"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"})
_TR_LOWER_TO_UPPER = str.maketrans({"i": "İ", "ı": "I", "ş": "Ş", "ğ": "Ğ", "ü": "Ü", "ö": "Ö", "ç": "Ç"})
_KEEP_UPPER = {"TED", "TOBB", "OSTİM", "ODTÜ", "SBÜ", "YKS", "UOLP", "KKTC"}
_KEEP_LOWER = {"ve"}
_UNI_CITY_SUFFIX_RE = re.compile(r"\s*\((?:ANKARA|İSTANBUL)\)\s*$", flags=re.IGNORECASE)


def _tr_title(text: str) -> str:
    """Format uppercase Turkish institutional names cleanly while keeping acronyms."""
    cleaned = _UNI_CITY_SUFFIX_RE.sub("", text).strip()
    out: list[str] = []
    for idx, word in enumerate(cleaned.split()):
        up = word.translate(_TR_LOWER_TO_UPPER)
        if up in _KEEP_UPPER:
            out.append(word.upper())
            continue
        low = word.translate(_TR_UPPER_TO_LOWER).lower()
        if idx > 0 and low in _KEEP_LOWER:
            out.append(low)
            continue
        out.append(low[0].translate(_TR_LOWER_TO_UPPER).upper() + low[1:])
    return " ".join(out)


def _read_csv_rows(path: Path) -> tuple[bytes, list[tuple[int, dict[str, str]]]]:
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    return raw, [(idx, dict(row)) for idx, row in enumerate(reader, start=2)]


def import_validated_osym_csvs(
    *,
    programs_csv: str | Path = DEFAULT_PROGRAMS_CSV,
    admissions_csv: str | Path = DEFAULT_ADMISSIONS_CSV,
    tuition_csv: str | Path = DEFAULT_TUITION_CSV,
    database_path: str | Path = DEFAULT_DATABASE,
    target_year: int = 2026,
    campus_city: str = "ANKARA",
) -> dict:
    """Import validated ÖSYM Ankara programs, general tracks, and 2026-2027 fees into SQLite."""
    p_path, a_path, t_path = Path(programs_csv), Path(admissions_csv), Path(tuition_csv)
    database_path = Path(database_path)

    p_raw, p_rows = _read_csv_rows(p_path)
    a_raw, a_rows = _read_csv_rows(a_path)
    t_raw, t_rows = _read_csv_rows(t_path)

    digest = hashlib.sha256(b"||".join((p_raw, a_raw, t_raw))).hexdigest()
    snapshot_id = f"sha256:{digest}"

    initialize_database(database_path)
    conn = connect(database_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT snapshot_id, importer_version FROM source_snapshots WHERE file_sha256=?",
            (digest,),
        ).fetchone()
        if existing:
            counts = {
                tbl: conn.execute(f"SELECT count(*) FROM {tbl} WHERE snapshot_id=?", (existing["snapshot_id"],)).fetchone()[0]
                for tbl in ("universities", "programs", "annual_admissions", "annual_tuition", "data_quality_issues")
            }
            conn.commit()
            return {"snapshot_id": existing["snapshot_id"], "sha256": digest, "counts": counts, "reused_snapshot": True}

        # Identify active programs for (target_year, campus_city)
        by_code_year: dict[tuple[str, int], tuple[int, dict[str, str]]] = {}
        active_2026: list[tuple[int, dict[str, str]]] = []
        for row_num, rec in p_rows:
            yr = parse_integer(rec.get("admission_year"), positive=True)
            code = _code((rec.get("program_code") or "").strip())
            if yr is not None:
                by_code_year[(code, yr)] = (row_num, rec)
            if yr == target_year and (rec.get("campus_city") or "").strip().upper() == campus_city.upper():
                active_2026.append((row_num, rec))

        metadata = {
            "source_counts": {
                "program_rows_total": len(p_rows),
                "active_target_programs": len(active_2026),
                "admissions_track_rows": len(a_rows),
                "tuition_rows": len(t_rows),
            },
            "target_year": target_year,
            "campus_city": campus_city,
            "sources": [p_path.name, a_path.name, t_path.name],
            "reused_code_protection": "Historical admissions joined only when institution/degree/score_type match active target program.",
        }

        conn.execute(
            """
            INSERT INTO source_snapshots (
                snapshot_id, source_filename, file_sha256, imported_at, importer_version,
                source_description, source_reference, retrieved_at, verification_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                f"ankara_validated_{target_year}_osym.csv",
                digest,
                datetime.now(timezone.utc).isoformat(),
                PARSER_VERSION,
                f"Validated 2019-{target_year} Ankara physical-campus ÖSYM & tuition dataset (22 institutions).",
                p_path.as_posix(),
                f"{target_year}-09-01",
                "verified",
                _json(metadata),
            ),
        )

        def _issue(sheet: str, row: int, code: str, msg: str, *, severity: str = "warning", program: int | None = None, year: int | None = None, raw: object = None):
            key = _json([sheet, row, code, year, program])
            conn.execute(
                """
                INSERT INTO data_quality_issues (
                    snapshot_id, issue_key, severity, issue_code, message, source_sheet,
                    source_row, raw_value, program_id, related_year
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, key, severity, code, msg, sheet, row, _json(raw) if raw is not None else None, program, year),
            )

        university_ids: dict[str, int] = {}
        program_db_ids: dict[str, int] = {}
        active_identities: dict[str, tuple[str, str, str]] = {}
        rank_from_progs: dict[tuple[str, int], int] = {}

        for (code, yr), (_, rec) in by_code_year.items():
            rk = parse_integer(rec.get("official_genel_success_rank_from_next_kilavuz"), positive=True)
            if rk is not None:
                rank_from_progs[(code, yr)] = rk

        for row_num, rec in sorted(active_2026, key=lambda x: x[1]["program_code"]):
            code = rec["program_code"].strip()
            raw_uni = rec["university_name_official"].strip()
            uni_display = _tr_title(raw_uni)
            uni_type = "Devlet" if rec["university_type"].strip().upper() == "DEVLET" else "Vakıf"

            if raw_uni not in university_ids:
                uni_key = "name-sha256:" + hashlib.sha256(uni_display.encode("utf-8")).hexdigest()
                city_display = "Ankara" if campus_city.upper() == "ANKARA" else _tr_title(campus_city)
                university_ids[raw_uni] = conn.execute(
                    """
                    INSERT INTO universities (
                        snapshot_id, university_key, name_original, name_normalized, university_type, city
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (snapshot_id, uni_key, uni_display, uni_display, uni_type, city_display),
                ).lastrowid

            regime = (rec.get("program_regime") or "").strip()
            raw_tier = (rec.get("scholarship_tier") or "").strip()
            if regime == "state_standard":
                schol_label = "Devlet (Ücretsiz)"
            elif raw_tier == "Burslu":
                schol_label = "Burslu (%100)"
            else:
                schol_label = raw_tier or None

            lang = (rec.get("teaching_language_explicit") or "").strip() or None
            prog_id = conn.execute(
                """
                INSERT INTO programs (
                    snapshot_id, university_id, program_code, name_original, faculty,
                    degree_level, score_type, scholarship_original, teaching_language,
                    source_sheet, source_row
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    university_ids[raw_uni],
                    code,
                    rec["program_name_official"].strip(),
                    (rec.get("faculty_official") or "").strip() or None,
                    (rec.get("degree_level") or "").strip() or None,
                    (rec.get("score_type") or "").strip() or None,
                    schol_label,
                    lang,
                    p_path.name,
                    row_num,
                ),
            ).lastrowid
            program_db_ids[code] = prog_id
            active_identities[code] = (raw_uni, (rec.get("degree_level") or "").strip(), (rec.get("score_type") or "").strip())

        # Admissions tracks (genel only, enforcing historical identity match to block 30 reused codes)
        adm_inserted = 0
        reused_excluded = 0
        for row_num, rec in a_rows:
            if (rec.get("quota_track") or "").strip() != "genel":
                continue
            code = (rec.get("program_code") or "").strip()
            if code not in program_db_ids:
                continue
            yr = parse_integer(rec.get("admission_year"), positive=True)
            if yr is None:
                continue
            prog_hist = by_code_year.get((code, yr))
            if prog_hist is not None:
                _, hist_rec = prog_hist
                hist_id = (
                    hist_rec["university_name_official"].strip(),
                    (hist_rec.get("degree_level") or "").strip(),
                    (hist_rec.get("score_type") or "").strip(),
                )
                if hist_id != active_identities[code]:
                    reused_excluded += 1
                    _issue(
                        a_path.name,
                        row_num,
                        "reused_program_code_history_excluded",
                        f"Excluded {yr} track row for reused code {code} (prior identity: {hist_id[0]} {hist_id[1]} {hist_id[2]}).",
                        severity="info",
                        program=program_db_ids[code],
                        year=yr,
                    )
                    continue
            quota = parse_integer(rec.get("quota"))
            placed = parse_integer(rec.get("placed"))
            rank = parse_integer(rec.get("official_success_rank"), positive=True) or rank_from_progs.get((code, yr))
            conn.execute(
                """
                INSERT INTO annual_admissions (
                    program_id, snapshot_id, admission_year, quota, placed_students, success_rank,
                    source_sheet, source_row
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (program_db_ids[code], snapshot_id, yr, quota, placed, rank, a_path.name, row_num),
            )
            adm_inserted += 1

        # Tuition schedules
        tuit_inserted = 0
        seen_tuit: set[tuple[int, int]] = set()
        for row_num, rec in t_rows:
            code = (rec.get("program_code") or "").strip()
            if code not in program_db_ids:
                continue
            ac_yr_str = (rec.get("academic_year") or "").strip()
            if not re.match(r"^\d{4}-\d{4}$", ac_yr_str):
                continue
            yr_start = int(ac_yr_str[:4])
            pid = program_db_ids[code]
            if (pid, yr_start) in seen_tuit:
                continue
            seen_tuit.add((pid, yr_start))

            full_minor = parse_money(rec.get("full_annual_tuition_try"))
            net_minor = parse_money(rec.get("net_annual_tuition_try"))
            raw_cur = (rec.get("currency") or "TRY").strip().upper()
            cur = raw_cur if len(raw_cur) == 3 and raw_cur.isalpha() else "TRY"
            if raw_cur != "TRY" and (full_minor is None and net_minor is None):
                _issue(
                    t_path.name,
                    row_num,
                    "foreign_or_missing_fee_schedule",
                    f"Currency {raw_cur} schedule lacks TRY tuition amount ({rec.get('fee_basis_note') or ''}).",
                    severity="warning",
                    program=pid,
                    year=yr_start,
                )
            basis = _json({
                "academic_year": ac_yr_str,
                "fee_type": rec.get("fee_type"),
                "verification_status": rec.get("verification_status"),
                "source_id": rec.get("source_id"),
                "kdv_included": rec.get("kdv_included"),
            })
            conn.execute(
                """
                INSERT INTO annual_tuition (
                    program_id, snapshot_id, academic_year_start, full_amount_minor, net_amount_minor,
                    currency, fee_basis, source_sheet, source_row
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (pid, snapshot_id, yr_start, full_minor, net_minor, cur, basis, t_path.name, row_num),
            )
            tuit_inserted += 1

        ic = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        fk = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
        if ic != ["ok"] or fk:
            raise ValueError(f"Integrity checks failed: ic={ic}, fk={fk}")
        conn.commit()
        return {
            "snapshot_id": snapshot_id,
            "sha256": digest,
            "parser_version": PARSER_VERSION,
            "reused_snapshot": False,
            "counts": {
                "universities": len(university_ids),
                "programs": len(program_db_ids),
                "annual_admissions": adm_inserted,
                "annual_tuition": tuit_inserted,
                "reused_code_history_excluded": reused_excluded,
            },
            "integrity_check": ic,
            "foreign_key_check": fk,
        }
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--programs-csv", type=Path, default=DEFAULT_PROGRAMS_CSV)
    parser.add_argument("--admissions-csv", type=Path, default=DEFAULT_ADMISSIONS_CSV)
    parser.add_argument("--tuition-csv", type=Path, default=DEFAULT_TUITION_CSV)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--target-year", type=int, default=2026)
    args = parser.parse_args(argv)
    report = import_validated_osym_csvs(
        programs_csv=args.programs_csv,
        admissions_csv=args.admissions_csv,
        tuition_csv=args.tuition_csv,
        database_path=args.database,
        target_year=args.target_year,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(_json(report) + "\n", encoding="utf-8")
    print(_json(report))


if __name__ == "__main__":
    main()
