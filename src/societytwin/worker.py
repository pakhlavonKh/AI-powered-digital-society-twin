"""The single local worker. Jobs are claimed transactionally and never retried or resumed."""

from __future__ import annotations

import os
import secrets
import socket
import threading

from societytwin.workbench import Workbench


class LocalWorker:
    def __init__(self, workbench: Workbench, poll_seconds: float = 1.0):
        self.workbench = workbench
        self.poll_seconds = poll_seconds
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.recovered: list[str] = []

    def recover(self) -> list[str]:
        # This deployment runs one local worker, so a job still 'running' at start-up belongs to a
        # worker that no longer exists. Its outcome is unknown; it is not retried.
        self.recovered = self.workbench.registry.recover_interrupted({self.worker_id})
        return self.recovered

    def run_once(self) -> bool:
        job = self.workbench.registry.claim_next_job(self.worker_id)
        if job is None:
            return False
        self.workbench.run_job(job)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(self.poll_seconds)

    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self._loop, name="societytwin-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
