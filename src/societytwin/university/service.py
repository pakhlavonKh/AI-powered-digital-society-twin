"""Read-only service layer over the university SQLite registry and candidate generator."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from societytwin.candidates import generate as generate_candidates
from societytwin.errors import WorkbenchError, invalid, not_found, unavailable
from societytwin.national.rng import MAX_SEED
from societytwin.university.db import SCHEMA_VERSION


@contextmanager
def _open_existing(db_path: Path):
    """Open an existing university SQLite registry strictly read-only and map corrupt/partial DBs to 503."""
    if not db_path.is_file():
        raise unavailable(
            "university_registry_unavailable",
            f"University SQLite registry is not present at {db_path}. Import a workbook first.",
        )
    try:
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.DatabaseError as exc:
        raise unavailable("university_registry_invalid", f"University SQLite database could not be opened: {exc}") from exc
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_snapshots'"
        ).fetchone()
        if not has_table:
            raise unavailable("university_registry_invalid", "University SQLite database has not been initialized.")
        yield conn
    except WorkbenchError:
        raise
    except sqlite3.DatabaseError as exc:
        raise unavailable("university_registry_invalid", f"University SQLite database schema/read error: {exc}") from exc
    finally:
        conn.close()


def _snapshot_rows(conn: sqlite3.Connection) -> list[dict]:
    snaps = conn.execute(
        """
        SELECT snapshot_id, source_filename, file_sha256, imported_at, importer_version,
               source_description, source_reference, retrieved_at, verification_status, notes
        FROM source_snapshots
        ORDER BY imported_at DESC, snapshot_id DESC
        """
    ).fetchall()
    out = []
    for row in snaps:
        sid = row["snapshot_id"]
        uni_count = conn.execute("SELECT COUNT(*) FROM universities WHERE snapshot_id=?", (sid,)).fetchone()[0]
        prog_count = conn.execute("SELECT COUNT(*) FROM programs WHERE snapshot_id=?", (sid,)).fetchone()[0]
        issue_count = conn.execute(
            "SELECT COUNT(*) FROM data_quality_issues WHERE snapshot_id=? AND review_status='open'", (sid,)
        ).fetchone()[0]
        years = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT admission_year FROM annual_admissions WHERE snapshot_id=? ORDER BY admission_year",
                (sid,),
            ).fetchall()
        ]
        out.append({
            **dict(row),
            "counts": {
                "universities": uni_count,
                "programs": prog_count,
                "open_quality_issues": issue_count,
            },
            "admission_years": years,
        })
    return out


def _require_snapshot(conn: sqlite3.Connection, snapshot_id: str) -> dict:
    row = conn.execute("SELECT * FROM source_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    if row is None:
        raise not_found("unknown_snapshot", f"No university registry snapshot {snapshot_id!r}")
    return dict(row)


def university_registry_status(db_path: Path) -> dict:
    if not db_path.is_file():
        return {
            "available": False,
            "db_path": str(db_path),
            "schema_version": None,
            "snapshots": [],
            "note": "No imported university SQLite registry exists at the configured path yet.",
        }
    with _open_existing(db_path) as conn:
        user_ver = conn.execute("PRAGMA user_version").fetchone()[0]
        snaps = _snapshot_rows(conn)
    return {
        "available": True,
        "db_path": str(db_path),
        "schema_version": user_ver or SCHEMA_VERSION,
        "snapshots": snaps,
        "note": f"Read-only SQLite registry with {len(snaps)} imported snapshot(s).",
    }


def list_university_snapshots(db_path: Path) -> dict:
    if not db_path.is_file():
        return {"available": False, "items": [], "total": 0}
    with _open_existing(db_path) as conn:
        items = _snapshot_rows(conn)
    return {"available": True, "items": items, "total": len(items)}


def query_university_programs(
    db_path: Path,
    snapshot_id: str,
    university_key: str | None = None,
    score_type: str | None = None,
    degree_level: str | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict:
    with _open_existing(db_path) as conn:
        _require_snapshot(conn, snapshot_id)
        where = ["p.snapshot_id = ?"]
        params: list[object] = [snapshot_id]
        if university_key:
            where.append("u.university_key = ?")
            params.append(university_key)
        if score_type:
            where.append("p.score_type = ?")
            params.append(score_type)
        if degree_level:
            where.append("p.degree_level = ?")
            params.append(degree_level)
        if q and q.strip():
            like = f"%{q.strip()}%"
            where.append("(p.program_code LIKE ? OR p.name_original LIKE ? OR u.name_original LIKE ?)")
            params.extend([like, like, like])
        clause = " AND ".join(where)
        total = conn.execute(
            f"SELECT COUNT(*) FROM programs p JOIN universities u ON p.university_id=u.university_id AND p.snapshot_id=u.snapshot_id WHERE {clause}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT p.program_id, p.program_code, p.name_original AS program_name, p.faculty, p.degree_level,
                   p.score_type, p.scholarship_original, p.teaching_language, p.source_sheet, p.source_row,
                   u.university_key, u.name_original AS university_name, u.university_type, u.city
            FROM programs p
            JOIN universities u ON p.university_id = u.university_id AND p.snapshot_id = u.snapshot_id
            WHERE {clause}
            ORDER BY u.name_original ASC, p.program_code ASC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        items = []
        for r in rows:
            pid = r["program_id"]
            latest_adm = conn.execute(
                """
                SELECT admission_year, quota, placed_students, success_rank
                FROM annual_admissions
                WHERE snapshot_id=? AND program_id=?
                ORDER BY admission_year DESC LIMIT 1
                """,
                (snapshot_id, pid),
            ).fetchone()
            latest_tuit = conn.execute(
                """
                SELECT academic_year_start, full_amount_minor, net_amount_minor, currency
                FROM annual_tuition
                WHERE snapshot_id=? AND program_id=?
                ORDER BY academic_year_start DESC LIMIT 1
                """,
                (snapshot_id, pid),
            ).fetchone()
            items.append({
                "program_code": r["program_code"],
                "program_name": r["program_name"],
                "faculty": r["faculty"],
                "degree_level": r["degree_level"],
                "score_type": r["score_type"],
                "scholarship_original": r["scholarship_original"],
                "teaching_language": r["teaching_language"],
                "university_key": r["university_key"],
                "university_name": r["university_name"],
                "university_type": r["university_type"],
                "city": r["city"],
                "source_sheet": r["source_sheet"],
                "source_row": r["source_row"],
                "latest_admission": dict(latest_adm) if latest_adm else None,
                "latest_tuition": dict(latest_tuit) if latest_tuit else None,
            })
    return {"snapshot_id": snapshot_id, "total": total, "offset": offset, "limit": limit, "items": items}


def get_university_program(db_path: Path, snapshot_id: str, program_code: str) -> dict:
    with _open_existing(db_path) as conn:
        snap = _require_snapshot(conn, snapshot_id)
        r = conn.execute(
            """
            SELECT p.*, u.university_key, u.name_original AS university_name,
                   u.official_university_code, u.university_type, u.city
            FROM programs p
            JOIN universities u ON p.university_id = u.university_id AND p.snapshot_id = u.snapshot_id
            WHERE p.snapshot_id=? AND p.program_code=?
            """,
            (snapshot_id, program_code),
        ).fetchone()
        if r is None:
            raise not_found("unknown_program", f"No program {program_code!r} in snapshot {snapshot_id!r}")
        pid = r["program_id"]
        admissions = [
            dict(x)
            for x in conn.execute(
                """
                SELECT admission_year, quota, placed_students, success_rank, source_sheet, source_row
                FROM annual_admissions WHERE snapshot_id=? AND program_id=? ORDER BY admission_year ASC
                """,
                (snapshot_id, pid),
            ).fetchall()
        ]
        tuition = [
            dict(x)
            for x in conn.execute(
                """
                SELECT academic_year_start, full_amount_minor, net_amount_minor, currency, fee_basis, source_sheet, source_row
                FROM annual_tuition WHERE snapshot_id=? AND program_id=? ORDER BY academic_year_start ASC
                """,
                (snapshot_id, pid),
            ).fetchall()
        ]
        issues = [
            dict(x)
            for x in conn.execute(
                """
                SELECT issue_key, severity, issue_code, message, source_sheet, source_row, source_column,
                       raw_value, related_year, review_status, resolution
                FROM data_quality_issues WHERE snapshot_id=? AND program_id=? ORDER BY issue_id ASC
                """,
                (snapshot_id, pid),
            ).fetchall()
        ]
    return {
        "snapshot": snap,
        "program": {
            "program_code": r["program_code"],
            "program_name": r["name_original"],
            "faculty": r["faculty"],
            "degree_level": r["degree_level"],
            "score_type": r["score_type"],
            "scholarship_original": r["scholarship_original"],
            "teaching_language": r["teaching_language"],
            "source_sheet": r["source_sheet"],
            "source_row": r["source_row"],
            "university_key": r["university_key"],
            "university_name": r["university_name"],
            "official_university_code": r["official_university_code"],
            "university_type": r["university_type"],
            "city": r["city"],
        },
        "admissions": admissions,
        "tuition": tuition,
        "quality_issues": issues,
    }


def list_university_issues(
    db_path: Path,
    snapshot_id: str,
    severity: str | None = None,
    review_status: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict:
    with _open_existing(db_path) as conn:
        _require_snapshot(conn, snapshot_id)
        where = ["i.snapshot_id = ?"]
        params: list[object] = [snapshot_id]
        if severity:
            where.append("i.severity = ?")
            params.append(severity)
        if review_status:
            where.append("i.review_status = ?")
            params.append(review_status)
        clause = " AND ".join(where)
        total = conn.execute(f"SELECT COUNT(*) FROM data_quality_issues i WHERE {clause}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT i.issue_key, i.severity, i.issue_code, i.message, i.source_sheet, i.source_row,
                   i.source_column, i.raw_value, i.related_year, i.review_status, i.resolution,
                   p.program_code
            FROM data_quality_issues i
            LEFT JOIN programs p ON i.program_id = p.program_id AND i.snapshot_id = p.snapshot_id
            WHERE {clause}
            ORDER BY i.issue_id ASC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return {"snapshot_id": snapshot_id, "total": total, "offset": offset, "limit": limit, "items": [dict(r) for r in rows]}


def preview_candidates(db_path: Path | None, seed: int = 42, size: int = 50, snapshot_id: str | None = None) -> dict:
    if size < 1 or size > 500:
        raise invalid("invalid_sample_size", "Candidate preview size must be between 1 and 500.")
    if seed < 0 or seed > MAX_SEED:
        raise invalid("invalid_seed", f"Seed must be between 0 and {MAX_SEED}.")
    if snapshot_id is not None:
        if db_path is None:
            raise unavailable("university_registry_unavailable", "No university SQLite path configured.")
        with _open_existing(db_path) as conn:
            _require_snapshot(conn, snapshot_id)
    out = generate_candidates(size, seed)
    return {"snapshot_id": snapshot_id, **out}
