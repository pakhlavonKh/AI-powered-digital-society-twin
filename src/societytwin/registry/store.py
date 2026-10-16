"""Repository classes over the registry tables. JSON payloads are stored verbatim and never rewritten."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from societytwin.common import utc_now
from societytwin.registry.db import connect, migrate, transaction

TERMINAL_JOB_STATES = {"completed", "failed", "stopped", "unknown_after_interruption"}


class Conflict(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Registry:
    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._guard = threading.Lock()
        migrate(self.conn)

    @property
    def conn(self) -> sqlite3.Connection:
        """One connection per thread; SQLite's file locking serialises writers across them."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self.path)
            self._local.conn = conn
            with self._guard:
                self._all.append(conn)
        return conn

    def close(self) -> None:
        with self._guard:
            for conn in self._all:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            self._all.clear()
        self._local = threading.local()

    # builds ---------------------------------------------------------------
    def register_build(self, descriptor: dict) -> bool:
        """Idempotent: an existing build ID is never overwritten."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO builds (build_id, variant, source_sha256, descriptor_json, registered_at) VALUES (?, ?, ?, ?, ?)",
                (descriptor["build_id"], descriptor["variant"], descriptor["source_sha256"],
                 json.dumps(descriptor, ensure_ascii=False), utc_now()))
            return cur.rowcount == 1

    def builds(self) -> list[dict]:
        rows = self.conn.execute("SELECT descriptor_json, registered_at FROM builds ORDER BY registered_at, build_id")
        return [dict(json.loads(r["descriptor_json"]), registered_at=r["registered_at"]) for r in rows]

    def build(self, build_id: str) -> dict | None:
        row = self.conn.execute("SELECT descriptor_json, registered_at FROM builds WHERE build_id = ?", (build_id,)).fetchone()
        return dict(json.loads(row["descriptor_json"]), registered_at=row["registered_at"]) if row else None

    # cohorts --------------------------------------------------------------
    def insert_cohort(self, manifest: dict) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO cohorts (cohort_id, build_id, source_sha256, manifest_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (manifest["cohort_id"], manifest["build_id"], manifest["source_sha256"],
                 json.dumps(manifest, ensure_ascii=False), manifest["created_at"]))

    def cohorts(self) -> list[dict]:
        rows = self.conn.execute("SELECT manifest_json FROM cohorts ORDER BY created_at DESC, cohort_id")
        return [json.loads(r["manifest_json"]) for r in rows]

    def cohort(self, cohort_id: str) -> dict | None:
        row = self.conn.execute("SELECT manifest_json FROM cohorts WHERE cohort_id = ?", (cohort_id,)).fetchone()
        return json.loads(row["manifest_json"]) if row else None

    # experiments ----------------------------------------------------------
    def insert_experiment(self, config: dict) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO experiments (experiment_id, config_json, config_hash, created_at) VALUES (?, ?, ?, ?)",
                (config["experiment_id"], json.dumps(config, ensure_ascii=False), config["config_hash"], config["created_at"]))

    def experiments(self) -> list[dict]:
        rows = self.conn.execute("SELECT config_json FROM experiments ORDER BY created_at DESC, experiment_id")
        return [json.loads(r["config_json"]) for r in rows]

    def experiment(self, experiment_id: str) -> dict | None:
        row = self.conn.execute("SELECT config_json FROM experiments WHERE experiment_id = ?", (experiment_id,)).fetchone()
        return json.loads(row["config_json"]) if row else None

    def insert_preflight(self, plan: dict) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR IGNORE INTO preflights (preflight_hash, experiment_id, config_hash, plan_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (plan["preflight_hash"], plan["experiment_id"], plan["config_hash"],
                 json.dumps(plan, ensure_ascii=False), plan["created_at"]))

    def preflight(self, preflight_hash: str) -> dict | None:
        row = self.conn.execute("SELECT plan_json FROM preflights WHERE preflight_hash = ?", (preflight_hash,)).fetchone()
        return json.loads(row["plan_json"]) if row else None

    def preflights_for(self, experiment_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT plan_json FROM preflights WHERE experiment_id = ? ORDER BY created_at DESC", (experiment_id,))
        return [json.loads(r["plan_json"]) for r in rows]

    # jobs -----------------------------------------------------------------
    def create_job(self, job: dict) -> tuple[dict, bool]:
        """Insert a queued job, or return the existing one for a repeated idempotency key.

        Returns (job, created). A reused key with a different preflight, or a second job for the
        same preflight, is a conflict: one reviewed plan executes at most once.
        """
        with transaction(self.conn):
            existing = self.conn.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (job["idempotency_key"],)).fetchone()
            if existing:
                if existing["preflight_hash"] != job["preflight_hash"] or existing["mode"] != job["mode"]:
                    raise Conflict("idempotency_key_reused", "This idempotency key was already used for a different plan")
                return dict(existing), False
            other = self.conn.execute("SELECT job_id FROM jobs WHERE preflight_hash = ?", (job["preflight_hash"],)).fetchone()
            if other:
                raise Conflict("preflight_already_executed",
                               f"This reviewed plan already has job {other['job_id']}; prepare a new preflight to run again")
            self.conn.execute(
                "INSERT INTO jobs (job_id, experiment_id, preflight_hash, mode, idempotency_key, state, output_rel, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)",
                (job["job_id"], job["experiment_id"], job["preflight_hash"], job["mode"], job["idempotency_key"],
                 job["output_rel"], utc_now()))
            row = self.conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job["job_id"],)).fetchone()
            return dict(row), True

    def job(self, job_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def jobs_for(self, experiment_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM jobs WHERE experiment_id = ? ORDER BY created_at DESC", (experiment_id,))
        return [dict(r) for r in rows]

    def claim_next_job(self, worker_id: str) -> dict | None:
        with transaction(self.conn):
            row = self.conn.execute("SELECT * FROM jobs WHERE state = 'queued' ORDER BY created_at, job_id LIMIT 1").fetchone()
            if not row:
                return None
            cur = self.conn.execute(
                "UPDATE jobs SET state = 'running', worker_id = ?, claimed_at = ? WHERE job_id = ? AND state = 'queued'",
                (worker_id, utc_now(), row["job_id"]))
            if cur.rowcount != 1:
                return None
            return dict(self.conn.execute("SELECT * FROM jobs WHERE job_id = ?", (row["job_id"],)).fetchone())

    def mark_provider_window_open(self, job_id: str) -> None:
        """Persisted before any process that may contact a provider is started."""
        with transaction(self.conn):
            self.conn.execute("UPDATE jobs SET provider_window_opened_at = ? WHERE job_id = ? AND state = 'running'",
                              (utc_now(), job_id))

    def finish_job(self, job_id: str, state: str, error_code: str | None = None, error_message: str | None = None) -> None:
        if state not in TERMINAL_JOB_STATES:
            raise ValueError(state)
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE jobs SET state = ?, finished_at = ?, error_code = ?, error_message = ? WHERE job_id = ? AND state = 'running'",
                (state, utc_now(), error_code, error_message, job_id))

    def cancel_queued(self, job_id: str) -> bool:
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE jobs SET state = 'stopped', finished_at = ?, error_code = 'cancelled_before_start' WHERE job_id = ? AND state = 'queued'",
                (utc_now(), job_id))
            return cur.rowcount == 1

    def recover_interrupted(self, live_worker_ids: set[str]) -> list[str]:
        """Jobs left 'running' by a worker that no longer exists become unknown_after_interruption.

        They are never retried or resumed: a provider request may already have been sent.
        """
        recovered = []
        with transaction(self.conn):
            rows = self.conn.execute("SELECT job_id, worker_id FROM jobs WHERE state = 'running'").fetchall()
            for row in rows:
                if row["worker_id"] in live_worker_ids:
                    continue
                self.conn.execute(
                    "UPDATE jobs SET state = 'unknown_after_interruption', finished_at = ?, error_code = 'worker_interrupted', "
                    "error_message = 'The worker stopped while this job was running; outcome unknown and not retried.' WHERE job_id = ?",
                    (utc_now(), row["job_id"]))
                recovered.append(row["job_id"])
        return recovered

    # personas -------------------------------------------------------------
    def insert_persona(self, record: dict) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO personas (persona_artifact_id, build_id, record_id, path_rel, sha256, source_sha256, catalog_sha256, adapter_sha256, created_at) "
                "VALUES (:persona_artifact_id, :build_id, :record_id, :path_rel, :sha256, :source_sha256, :catalog_sha256, :adapter_sha256, :created_at)",
                record)

    def personas_for(self, build_id: str, record_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM personas WHERE build_id = ? AND record_id = ? ORDER BY created_at DESC",
                                 (build_id, record_id))
        return [dict(r) for r in rows]

    # imported runs ----------------------------------------------------------
    def imported_manifest(self, experiment_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM imported_runs WHERE experiment_id = ?", (experiment_id,)).fetchone()
        return dict(row, file_manifest=json.loads(row["file_manifest_json"])) if row else None

    def register_import(self, experiment_id: str, dirname: str, manifest: dict) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR IGNORE INTO imported_runs (experiment_id, dirname, file_manifest_json, first_seen_at) VALUES (?, ?, ?, ?)",
                (experiment_id, dirname, json.dumps(manifest, sort_keys=True), utc_now()))

    def counts(self) -> dict[str, int]:
        out = {}
        for table in ("builds", "cohorts", "experiments", "preflights", "jobs", "personas", "imported_runs"):
            out[table] = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        return out


def open_registry(path: Path) -> Registry:
    return Registry(path)


__all__ = ["Conflict", "Registry", "open_registry", "TERMINAL_JOB_STATES", "sqlite3"]
