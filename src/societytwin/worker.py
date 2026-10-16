"""The single local worker. Jobs are claimed transactionally and never retried or resumed."""

from __future__ import annotations

import logging
import os
import secrets
import socket
import threading

from societytwin.workbench import Workbench

try:
    import fcntl
except ImportError:  # Windows: no advisory lock; the single-worker assumption applies unchanged.
    fcntl = None

logger = logging.getLogger("societytwin.worker")


class LocalWorker:
    def __init__(self, workbench: Workbench, poll_seconds: float = 1.0):
        self.workbench = workbench
        self.poll_seconds = poll_seconds
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock_handle = None
        self.recovered: list[str] = []
        self.active = False

    def _acquire_lock(self) -> bool:
        """Only one worker per state directory may run and recover jobs (advisory lock where supported)."""
        if fcntl is None:
            return True
        path = self.workbench.settings.state_dir / "worker.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+", encoding="utf-8")  # noqa: SIM115 - held open for the worker's lifetime
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(f"{self.worker_id}\n")
        handle.flush()
        self._lock_handle = handle
        return True

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

    def start(self) -> bool:
        """Start the worker thread. Returns False, without recovering anything, if another worker owns the state directory."""
        if not self._acquire_lock():
            logger.warning("Another SocietyTwin worker is using %s; this process will not run or recover jobs.",
                           self.workbench.settings.state_dir)
            return False
        self.recover()
        self._thread = threading.Thread(target=self._loop, name="societytwin-worker", daemon=True)
        self._thread.start()
        self.active = True
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        if self._lock_handle is not None:
            self._lock_handle.close()
            self._lock_handle = None
        self.active = False
