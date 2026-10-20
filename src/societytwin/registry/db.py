"""SQLite connection handling and ordered migrations.

Statements stay close to portable SQL so that the documented PostgreSQL path remains open;
nothing here claims that migration has happened.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from societytwin.common import utc_now

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial registry", """
        CREATE TABLE builds (
            build_id TEXT PRIMARY KEY,
            variant TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            descriptor_json TEXT NOT NULL,
            registered_at TEXT NOT NULL
        );
        CREATE TABLE cohorts (
            cohort_id TEXT PRIMARY KEY,
            build_id TEXT NOT NULL REFERENCES builds(build_id),
            source_sha256 TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE experiments (
            experiment_id TEXT PRIMARY KEY,
            config_json TEXT NOT NULL,
            config_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE preflights (
            preflight_hash TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
            config_hash TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
            preflight_hash TEXT NOT NULL UNIQUE REFERENCES preflights(preflight_hash),
            mode TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            state TEXT NOT NULL,
            worker_id TEXT,
            output_rel TEXT NOT NULL,
            created_at TEXT NOT NULL,
            claimed_at TEXT,
            provider_window_opened_at TEXT,
            finished_at TEXT,
            error_code TEXT,
            error_message TEXT
        );
        CREATE TABLE personas (
            persona_artifact_id TEXT PRIMARY KEY,
            build_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            path_rel TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            catalog_sha256 TEXT,
            adapter_sha256 TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE imported_runs (
            experiment_id TEXT PRIMARY KEY,
            dirname TEXT NOT NULL,
            file_manifest_json TEXT NOT NULL,
            first_seen_at TEXT NOT NULL
        );
    """),
    (2, "national pipeline", """
        CREATE TABLE national_cohorts (
            cohort_id TEXT PRIMARY KEY,
            population_id TEXT NOT NULL,
            name TEXT NOT NULL,
            definition_json TEXT NOT NULL,
            definition_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE national_cohort_samples (
            sample_id TEXT PRIMARY KEY,
            cohort_id TEXT NOT NULL REFERENCES national_cohorts(cohort_id),
            config_hash TEXT NOT NULL,
            sample_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (cohort_id, config_hash)
        );
        CREATE TABLE national_experiments (
            experiment_id TEXT PRIMARY KEY,
            definition_json TEXT NOT NULL,
            definition_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE national_plans (
            plan_hash TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL REFERENCES national_experiments(experiment_id),
            plan_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE national_runs (
            run_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL REFERENCES national_experiments(experiment_id),
            plan_hash TEXT NOT NULL REFERENCES national_plans(plan_hash),
            kind TEXT NOT NULL,
            replay_of TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            state TEXT NOT NULL,
            worker_id TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            summary_json TEXT,
            error_code TEXT,
            error_message TEXT
        );
        CREATE TABLE national_responses (
            response_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES national_runs(run_id),
            is_final INTEGER NOT NULL,
            row_json TEXT NOT NULL
        );
        CREATE INDEX national_responses_run ON national_responses(run_id, is_final);
        CREATE TABLE response_cache (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """),
]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE takes the write lock up front, so concurrent claims serialise."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection) -> list[int]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
    newly = []
    for version, name, sql in MIGRATIONS:
        if version in applied:
            continue
        with transaction(conn):
            for statement in (s.strip() for s in sql.split(";")):
                if statement:
                    conn.execute(statement)
            conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                         (version, name, utc_now()))
        newly.append(version)
    return newly
