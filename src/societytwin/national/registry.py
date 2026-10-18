"""Registry tables for national cohorts, experiments, plans, runs, responses and the response cache.

Shares the SQLite connection handling of ``societytwin.registry`` (migration 2). JSON payloads are
written once and never rewritten, except run state and summaries, which move forward only.
"""

from __future__ import annotations

import json

from societytwin.common import utc_now
from societytwin.registry.db import transaction
from societytwin.registry.store import Registry

RUN_TERMINAL = {"completed", "completed_with_errors", "failed", "budget_stopped"}


class NationalRegistry:
    def __init__(self, registry: Registry):
        self.registry = registry

    @property
    def conn(self):
        return self.registry.conn

    # cohorts --------------------------------------------------------------
    def insert_cohort(self, cohort: dict) -> None:
        with transaction(self.conn):
            self.conn.execute("INSERT INTO national_cohorts VALUES (?, ?, ?, ?, ?, ?)",
                              (cohort["cohort_id"], cohort["population_id"], cohort["name"], json.dumps(cohort, ensure_ascii=False),
                               cohort["definition_hash"], cohort["created_at"]))

    def cohorts(self) -> list[dict]:
        return [json.loads(r["definition_json"]) for r in
                self.conn.execute("SELECT definition_json FROM national_cohorts ORDER BY created_at DESC, cohort_id")]

    def cohort(self, cohort_id: str) -> dict | None:
        row = self.conn.execute("SELECT definition_json FROM national_cohorts WHERE cohort_id = ?", (cohort_id,)).fetchone()
        return json.loads(row["definition_json"]) if row else None

    def sample_by_config(self, cohort_id: str, config_hash: str) -> dict | None:
        row = self.conn.execute("SELECT sample_json FROM national_cohort_samples WHERE cohort_id = ? AND config_hash = ?",
                                (cohort_id, config_hash)).fetchone()
        return json.loads(row["sample_json"]) if row else None

    def insert_sample(self, sample: dict) -> dict:
        with transaction(self.conn):
            existing = self.conn.execute("SELECT sample_json FROM national_cohort_samples WHERE cohort_id = ? AND config_hash = ?",
                                         (sample["cohort_id"], sample["config_hash"])).fetchone()
            if existing:
                return json.loads(existing["sample_json"])
            self.conn.execute("INSERT INTO national_cohort_samples VALUES (?, ?, ?, ?, ?)",
                              (sample["sample_id"], sample["cohort_id"], sample["config_hash"], json.dumps(sample, ensure_ascii=False),
                               sample["created_at"]))
        return sample

    def sample(self, sample_id: str) -> dict | None:
        row = self.conn.execute("SELECT sample_json FROM national_cohort_samples WHERE sample_id = ?", (sample_id,)).fetchone()
        return json.loads(row["sample_json"]) if row else None

    def samples_for(self, cohort_id: str) -> list[dict]:
        return [json.loads(r["sample_json"]) for r in self.conn.execute(
            "SELECT sample_json FROM national_cohort_samples WHERE cohort_id = ? ORDER BY created_at DESC", (cohort_id,))]

    # experiments ------------------------------------------------------------
    def insert_experiment(self, exp: dict) -> None:
        with transaction(self.conn):
            self.conn.execute("INSERT INTO national_experiments VALUES (?, ?, ?, ?)",
                              (exp["experiment_id"], json.dumps(exp, ensure_ascii=False), exp["definition_hash"], exp["created_at"]))

    def experiments(self) -> list[dict]:
        return [json.loads(r["definition_json"]) for r in
                self.conn.execute("SELECT definition_json FROM national_experiments ORDER BY created_at DESC, experiment_id")]

    def experiment(self, experiment_id: str) -> dict | None:
        row = self.conn.execute("SELECT definition_json FROM national_experiments WHERE experiment_id = ?", (experiment_id,)).fetchone()
        return json.loads(row["definition_json"]) if row else None

    def insert_plan(self, plan: dict) -> None:
        with transaction(self.conn):
            self.conn.execute("INSERT OR IGNORE INTO national_plans VALUES (?, ?, ?, ?)",
                              (plan["plan_hash"], plan["experiment_id"], json.dumps(plan, ensure_ascii=False), plan["created_at"]))

    def plan(self, plan_hash: str) -> dict | None:
        row = self.conn.execute("SELECT plan_json FROM national_plans WHERE plan_hash = ?", (plan_hash,)).fetchone()
        return json.loads(row["plan_json"]) if row else None

    def plans_for(self, experiment_id: str) -> list[dict]:
        return [json.loads(r["plan_json"]) for r in self.conn.execute(
            "SELECT plan_json FROM national_plans WHERE experiment_id = ? ORDER BY created_at DESC", (experiment_id,))]

    # runs -------------------------------------------------------------------
    def create_run(self, run: dict) -> tuple[dict, bool]:
        with transaction(self.conn):
            existing = self.conn.execute("SELECT * FROM national_runs WHERE idempotency_key = ?", (run["idempotency_key"],)).fetchone()
            if existing:
                return self._run_row(existing), False
            if run["kind"] == "execute":
                prior = self.conn.execute("SELECT run_id FROM national_runs WHERE plan_hash = ? AND kind = 'execute'",
                                          (run["plan_hash"],)).fetchone()
                if prior:
                    raise ValueError(f"This reviewed plan already ran as {prior['run_id']}; review a new plan to run again.")
            self.conn.execute(
                "INSERT INTO national_runs (run_id, experiment_id, plan_hash, kind, replay_of, idempotency_key, state, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)",
                (run["run_id"], run["experiment_id"], run["plan_hash"], run["kind"], run.get("replay_of"), run["idempotency_key"], utc_now()))
        return self.run(run["run_id"]), True

    def _run_row(self, row) -> dict:
        out = dict(row)
        out["summary"] = json.loads(out.pop("summary_json")) if out.get("summary_json") else None
        return out

    def run(self, run_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM national_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._run_row(row) if row else None

    def runs(self, experiment_id: str | None = None) -> list[dict]:
        if experiment_id:
            rows = self.conn.execute("SELECT * FROM national_runs WHERE experiment_id = ? ORDER BY created_at DESC", (experiment_id,))
        else:
            rows = self.conn.execute("SELECT * FROM national_runs ORDER BY created_at DESC")
        return [self._run_row(r) for r in rows]

    def claim_next(self, worker_id: str) -> dict | None:
        with transaction(self.conn):
            row = self.conn.execute("SELECT run_id FROM national_runs WHERE state = 'queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            self.conn.execute("UPDATE national_runs SET state = 'running', worker_id = ?, started_at = ? WHERE run_id = ? AND state = 'queued'",
                              (worker_id, utc_now(), row["run_id"]))
        return self.run(row["run_id"])

    def claim(self, run_id: str, worker_id: str) -> bool:
        with transaction(self.conn):
            cur = self.conn.execute("UPDATE national_runs SET state = 'running', worker_id = ?, started_at = ? "
                                    "WHERE run_id = ? AND state = 'queued'", (worker_id, utc_now(), run_id))
            return cur.rowcount == 1

    def finish(self, run_id: str, state: str, summary: dict | None, error_code: str | None = None, error_message: str | None = None) -> None:
        if state not in RUN_TERMINAL:
            raise ValueError(state)
        with transaction(self.conn):
            self.conn.execute("UPDATE national_runs SET state = ?, finished_at = ?, summary_json = ?, error_code = ?, error_message = ? "
                              "WHERE run_id = ? AND state = 'running'",
                              (state, utc_now(), json.dumps(summary, ensure_ascii=False) if summary is not None else None,
                               error_code, error_message, run_id))

    def recover_interrupted(self) -> list[str]:
        with transaction(self.conn):
            rows = [r["run_id"] for r in self.conn.execute("SELECT run_id FROM national_runs WHERE state = 'running'")]
            for run_id in rows:
                self.conn.execute("UPDATE national_runs SET state = 'failed', finished_at = ?, error_code = 'interrupted', "
                                  "error_message = 'The worker stopped while this run was in progress; it was not retried.' WHERE run_id = ?",
                                  (utc_now(), run_id))
        return rows

    def insert_responses(self, run_id: str, rows: list[dict]) -> None:
        with transaction(self.conn):
            self.conn.executemany("INSERT INTO national_responses (run_id, is_final, row_json) VALUES (?, ?, ?)",
                                  [(run_id, 1 if r.get("is_final") else 0, json.dumps(r, ensure_ascii=False)) for r in rows])

    def responses(self, run_id: str, final_only: bool = False) -> list[dict]:
        sql = "SELECT row_json FROM national_responses WHERE run_id = ?" + (" AND is_final = 1" if final_only else "") + " ORDER BY response_id"
        return [json.loads(r["row_json"]) for r in self.conn.execute(sql, (run_id,))]

    # response cache -----------------------------------------------------------
    def cache_get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT payload_json FROM response_cache WHERE cache_key = ?", (key,)).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def cache_put(self, key: str, payload: dict) -> None:
        with transaction(self.conn):
            self.conn.execute("INSERT OR IGNORE INTO response_cache VALUES (?, ?, ?)",
                              (key, json.dumps(payload, ensure_ascii=False), utc_now()))
