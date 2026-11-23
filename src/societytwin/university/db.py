"""Explicit, transactional initialization of a standalone university database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE source_snapshots (
    snapshot_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(snapshot_id)) > 0),
    source_filename TEXT NOT NULL CHECK (length(trim(source_filename)) > 0),
    file_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(file_sha256) = 64 AND file_sha256 NOT GLOB '*[^0-9a-f]*'),
    imported_at TEXT NOT NULL CHECK (length(trim(imported_at)) > 0),
    importer_version TEXT NOT NULL CHECK (length(trim(importer_version)) > 0),
    source_description TEXT,
    source_reference TEXT,
    retrieved_at TEXT,
    verification_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (verification_status IN ('unverified', 'verified', 'rejected')),
    notes TEXT
);
CREATE TABLE universities (
    university_id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
    university_key TEXT NOT NULL CHECK (length(trim(university_key)) > 0),
    name_original TEXT NOT NULL CHECK (length(trim(name_original)) > 0),
    name_normalized TEXT NOT NULL CHECK (length(trim(name_normalized)) > 0),
    official_university_code TEXT,
    university_type TEXT,
    city TEXT,
    UNIQUE (snapshot_id, university_key),
    UNIQUE (university_id, snapshot_id)
);
CREATE TABLE programs (
    program_id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
    university_id INTEGER NOT NULL,
    program_code TEXT NOT NULL CHECK (length(trim(program_code)) > 0),
    name_original TEXT NOT NULL CHECK (length(trim(name_original)) > 0),
    faculty TEXT,
    degree_level TEXT,
    score_type TEXT,
    scholarship_original TEXT,
    teaching_language TEXT CHECK (teaching_language IS NULL OR length(teaching_language) > 0),
    source_sheet TEXT NOT NULL CHECK (length(trim(source_sheet)) > 0),
    source_row INTEGER NOT NULL CHECK (typeof(source_row) = 'integer' AND source_row > 0),
    UNIQUE (snapshot_id, program_code),
    UNIQUE (program_id, snapshot_id),
    FOREIGN KEY (university_id, snapshot_id)
        REFERENCES universities(university_id, snapshot_id)
);
CREATE TABLE annual_admissions (
    admission_id INTEGER PRIMARY KEY,
    program_id INTEGER NOT NULL,
    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
    admission_year INTEGER NOT NULL CHECK (
        typeof(admission_year) = 'integer' AND admission_year BETWEEN 1900 AND 9999),
    quota INTEGER CHECK (quota IS NULL OR (typeof(quota) = 'integer' AND quota >= 0)),
    placed_students INTEGER CHECK (placed_students IS NULL OR (typeof(placed_students) = 'integer' AND placed_students >= 0)),
    success_rank INTEGER CHECK (success_rank IS NULL OR (typeof(success_rank) = 'integer' AND success_rank > 0)),
    source_sheet TEXT NOT NULL CHECK (length(trim(source_sheet)) > 0),
    source_row INTEGER NOT NULL CHECK (typeof(source_row) = 'integer' AND source_row > 0),
    UNIQUE (snapshot_id, program_id, admission_year),
    FOREIGN KEY (program_id, snapshot_id) REFERENCES programs(program_id, snapshot_id)
);
CREATE TABLE annual_tuition (
    tuition_id INTEGER PRIMARY KEY,
    program_id INTEGER NOT NULL,
    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
    academic_year_start INTEGER NOT NULL CHECK (
        typeof(academic_year_start) = 'integer' AND academic_year_start BETWEEN 1900 AND 9998),
    full_amount_minor INTEGER CHECK (full_amount_minor IS NULL OR (typeof(full_amount_minor) = 'integer' AND full_amount_minor >= 0)),
    net_amount_minor INTEGER CHECK (net_amount_minor IS NULL OR (typeof(net_amount_minor) = 'integer' AND net_amount_minor >= 0)),
    currency TEXT NOT NULL CHECK (length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'),
    fee_basis TEXT,
    source_sheet TEXT NOT NULL CHECK (length(trim(source_sheet)) > 0),
    source_row INTEGER NOT NULL CHECK (typeof(source_row) = 'integer' AND source_row > 0),
    UNIQUE (snapshot_id, program_id, academic_year_start),
    FOREIGN KEY (program_id, snapshot_id) REFERENCES programs(program_id, snapshot_id)
);
CREATE TABLE data_quality_issues (
    issue_id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
    issue_key TEXT NOT NULL CHECK (length(trim(issue_key)) > 0),
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    issue_code TEXT NOT NULL CHECK (length(trim(issue_code)) > 0),
    message TEXT NOT NULL CHECK (length(trim(message)) > 0),
    source_sheet TEXT,
    source_row INTEGER CHECK (source_row IS NULL OR (typeof(source_row) = 'integer' AND source_row > 0)),
    source_column TEXT,
    raw_value TEXT,
    program_id INTEGER,
    related_year INTEGER CHECK (related_year IS NULL OR
        (typeof(related_year) = 'integer' AND related_year BETWEEN 1900 AND 9999)),
    review_status TEXT NOT NULL DEFAULT 'open' CHECK (review_status IN ('open', 'resolved', 'accepted')),
    resolution TEXT,
    UNIQUE (snapshot_id, issue_key),
    FOREIGN KEY (program_id, snapshot_id) REFERENCES programs(program_id, snapshot_id)
);
"""


class SchemaVersionError(RuntimeError):
    """The file is not an empty or supported university database."""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a database (creating an empty file if absent) without initializing schema.

    Foreign keys are connection-local: all application access must use this helper.
    The caller owns the connection and must close it.
    """
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(path: str | Path) -> None:
    """Create version 1 atomically, or validate an already initialized database.

    Refuse populated unversioned files and unsupported versions. No migrations,
    deletion, or automatic replacement are performed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        expected = {"universities", "programs", "annual_admissions", "annual_tuition",
                    "source_snapshots", "data_quality_issues"}
        if version == SCHEMA_VERSION:
            if tables != expected:
                raise SchemaVersionError("University schema version 1 has unexpected or missing tables")
            # Also reject partial/foreign schemas that merely claim our version.
            reference = sqlite3.connect(":memory:")
            try:
                reference.executescript(SCHEMA)
                query = "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
                definitions = [tuple(row) for row in conn.execute(query)]
                if definitions != reference.execute(query).fetchall():
                    raise SchemaVersionError("University schema definitions do not match version 1")
            finally:
                reference.close()
        elif version != 0:
            raise SchemaVersionError(
                f"Unsupported university schema version {version}; expected {SCHEMA_VERSION}"
            )
        elif conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
            raise SchemaVersionError("Refusing to initialize a nonempty, unversioned database")
        else:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
