"""Read-only service layer over the university SQLite registry and candidate generator."""

from __future__ import annotations

import math
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from societytwin.candidates import generate as generate_candidates
from societytwin.errors import WorkbenchError, invalid, not_found, unavailable
from societytwin.national.geography import _BY_NAME, name_key, normalize_code
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


def _map_university_type(raw: str | None) -> str:
    txt = (raw or "").strip().lower()
    if txt in ("devlet", "state", "public"):
        return "state"
    if "vak" in txt or txt in ("foundation", "private"):
        return "foundation"
    if "kktc" in txt:
        return "kktc"
    return "other"


def _map_score_type(raw: str | None) -> str | None:
    if not raw:
        return None
    up = raw.strip().upper()
    if up in ("SOZ", "SÖZ"):
        return "SÖZ"
    if up in ("DIL", "DİL"):
        return "DİL"
    if up in ("SAY", "EA", "TYT"):
        return up
    return None


def _map_degree_level(raw: str | None, score_type: str) -> str:
    txt = (raw or "").strip().lower()
    if "önlisans" in txt or "onlisans" in txt or "associate" in txt or score_type == "TYT":
        return "associate"
    return "bachelor"


def _parse_scholarship_pct(raw: str | None) -> float:
    txt = (raw or "").strip().lower()
    if not txt:
        return 0.0
    if "burslu" in txt and "%" not in txt:
        return 100.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*%|%\s*(\d+(?:\.\d+)?)", txt)
    if m:
        val = float(m.group(1) or m.group(2))
        return max(0.0, min(100.0, val))
    return 0.0


def _map_city_to_province_code(city: str | None) -> str | None:
    if not city or not city.strip():
        return None
    cleaned = city.strip()
    if cleaned.isdigit() and 1 <= int(cleaned) <= 81:
        return normalize_code(cleaned)
    prov = _BY_NAME.get(name_key(cleaned))
    return prov.code if prov else None


def list_snapshot_universities(db_path: Path, snapshot_id: str) -> dict:
    """List distinct universities and program counts inside a SQLite snapshot."""
    with _open_existing(db_path) as conn:
        _require_snapshot(conn, snapshot_id)
        rows = conn.execute(
            """
            SELECT u.university_key, u.name_original AS university_name, u.university_type, u.city,
                   COUNT(p.program_id) AS program_count
            FROM universities u
            LEFT JOIN programs p ON p.university_id = u.university_id AND p.snapshot_id = u.snapshot_id
            WHERE u.snapshot_id = ?
            GROUP BY u.university_id
            ORDER BY u.name_original ASC
            """,
            (snapshot_id,),
        ).fetchall()
    return {
        "snapshot_id": snapshot_id,
        "items": [
            {
                "university_id": r["university_key"],
                "university_key": r["university_key"],
                "university_name": r["university_name"],
                "university_type": _map_university_type(r["university_type"]),
                "university_type_raw": r["university_type"],
                "city": r["city"],
                "province_code": _map_city_to_province_code(r["city"]),
                "program_count": int(r["program_count"]),
            }
            for r in rows
        ],
    }


def load_programs_from_sqlite_snapshot(
    db_path: Path,
    snapshot_id: str,
    admission_year: int | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Build ProgramOffering models from an imported SQLite snapshot (with honest missingness metadata)."""
    from scenarios.placement.models import ProgramOffering

    with _open_existing(db_path) as conn:
        snap = _require_snapshot(conn, snapshot_id)
        years = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT admission_year FROM annual_admissions WHERE snapshot_id=? ORDER BY admission_year ASC",
                (snapshot_id,),
            ).fetchall()
        ]
        target_year = admission_year if admission_year is not None else (years[-1] if years else None)
        if admission_year is not None and years and admission_year not in years:
            raise invalid(
                "unknown_admission_year",
                f"Admission year {admission_year} has no rows in snapshot '{snapshot_id}' (available: {years}).",
            )

        rows = conn.execute(
            """
            SELECT p.program_id AS db_program_id, p.program_code, p.name_original AS program_name,
                   p.degree_level, p.score_type, p.scholarship_original,
                   u.university_key, u.name_original AS university_name, u.university_type, u.city
            FROM programs p
            JOIN universities u ON p.university_id = u.university_id AND p.snapshot_id = u.snapshot_id
            WHERE p.snapshot_id = ?
            ORDER BY p.program_code ASC
            """,
            (snapshot_id,),
        ).fetchall()

        adm_map: dict[int, sqlite3.Row] = {}
        prior_rank_map: dict[int, int] = {}
        if target_year is not None:
            for a in conn.execute(
                """
                SELECT program_id, quota, placed_students, success_rank
                FROM annual_admissions
                WHERE snapshot_id = ? AND admission_year = ?
                """,
                (snapshot_id, target_year),
            ).fetchall():
                adm_map[a["program_id"]] = a
            for pr in conn.execute(
                """
                SELECT a1.program_id, a1.success_rank
                FROM annual_admissions a1
                WHERE a1.snapshot_id = ?
                  AND a1.admission_year <= ?
                  AND a1.success_rank IS NOT NULL
                  AND a1.admission_year = (
                      SELECT MAX(a2.admission_year)
                      FROM annual_admissions a2
                      WHERE a2.snapshot_id = a1.snapshot_id
                        AND a2.program_id = a1.program_id
                        AND a2.admission_year <= ?
                        AND a2.success_rank IS NOT NULL
                  )
                """,
                (snapshot_id, target_year, target_year),
            ).fetchall():
                prior_rank_map[pr["program_id"]] = int(pr["success_rank"])

        tuit_map: dict[int, sqlite3.Row] = {}
        for t in conn.execute(
            """
            SELECT t1.program_id, t1.academic_year_start, t1.full_amount_minor, t1.net_amount_minor, t1.currency
            FROM annual_tuition t1
            WHERE t1.snapshot_id = ?
              AND t1.academic_year_start = (
                  SELECT MAX(t2.academic_year_start)
                  FROM annual_tuition t2
                  WHERE t2.snapshot_id = t1.snapshot_id AND t2.program_id = t1.program_id
              )
            """,
            (snapshot_id,),
        ).fetchall():
            tuit_map[t["program_id"]] = t

    offerings: list[ProgramOffering] = []
    skipped_missing_score_type = 0
    missing_quota_count = 0
    missing_tuition_count = 0
    missing_rank_count = 0
    prior_year_rank_fallback_count = 0

    for r in rows:
        score_type = _map_score_type(r["score_type"])
        if score_type is None:
            skipped_missing_score_type += 1
            continue

        pid = r["db_program_id"]
        adm = adm_map.get(pid)
        tuit = tuit_map.get(pid)

        quota = adm["quota"] if adm is not None else None
        if quota is None:
            missing_quota_count += 1
            capacity = 0
            status = "suspended"
        else:
            capacity = max(0, int(quota))
            status = "open" if capacity > 0 else "closed"

        success_rank = adm["success_rank"] if adm is not None and adm["success_rank"] is not None else None
        if success_rank is None:
            fallback_rk = prior_rank_map.get(pid)
            if fallback_rk is not None:
                success_rank = fallback_rk
                prior_year_rank_fallback_count += 1
        if success_rank is None:
            missing_rank_count += 1
            prestige = 0.22
        else:
            prestige = round(
                max(0.15, min(0.96, 0.96 - 0.18 * max(0.0, math.log10(max(1, int(success_rank))) - 2.0))),
                6,
            )

        schol_pct = _parse_scholarship_pct(r["scholarship_original"])
        tuition_annual = 0.0
        currency = "TL"
        if tuit is not None:
            currency = "TL" if tuit["currency"] == "TRY" else str(tuit["currency"] or "TL")
            full_minor = tuit["full_amount_minor"]
            net_minor = tuit["net_amount_minor"]
            if full_minor is not None and full_minor > 0:
                tuition_annual = round(full_minor / 100.0, 2)
                if net_minor is not None:
                    schol_pct = round(max(0.0, min(100.0, (1.0 - net_minor / full_minor) * 100.0)), 2)
            elif net_minor is not None:
                # Net fee is already post-discount; keep scholarship_pct=0 so published_net_tuition_before_aid stays exact.
                tuition_annual = round(net_minor / 100.0, 2)
                schol_pct = 0.0
            elif _map_university_type(r["university_type"]) == "foundation":
                missing_tuition_count += 1
        elif _map_university_type(r["university_type"]) == "foundation":
            missing_tuition_count += 1

        dept_label = str(r["program_name"])
        if r["scholarship_original"] and str(r["scholarship_original"]) not in dept_label:
            dept_label = f"{dept_label} ({r['scholarship_original']})"

        offerings.append(
            ProgramOffering(
                program_id=str(r["program_code"]),
                university_id=str(r["university_key"]),
                university_name=str(r["university_name"]),
                university_type=_map_university_type(r["university_type"]),  # type: ignore[arg-type]
                province_code=_map_city_to_province_code(r["city"]),
                department_name=dept_label,
                degree_level=_map_degree_level(r["degree_level"], score_type),  # type: ignore[arg-type]
                score_type=score_type,  # type: ignore[arg-type]
                baraj_group=None,
                capacity=capacity,
                status=status,  # type: ignore[arg-type]
                university_rank=int(success_rank) if success_rank is not None else None,
                prestige_score=prestige,
                tuition_annual=tuition_annual,
                scholarship_pct=schol_pct,
                currency=currency,
            )
        )

    meta = {
        "catalog_source": "sqlite_snapshot",
        "snapshot_id": snapshot_id,
        "source_filename": snap["source_filename"],
        "verification_status": snap["verification_status"],
        "admission_year": target_year,
        "available_admission_years": years,
        "programs_loaded": len(offerings),
        "skipped_missing_score_type": skipped_missing_score_type,
        "missing_quota_count": missing_quota_count,
        "missing_tuition_count": missing_tuition_count,
        "missing_rank_count": missing_rank_count,
        "prior_year_rank_fallback_count": prior_year_rank_fallback_count,
    }
    return offerings, meta
