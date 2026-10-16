"""Isolated subprocess adapter around the existing experiment runners and persona adapter.

Rules enforced here:
- an explicit interpreter, cwd and a minimal environment; never ``shell=True``;
- arguments are validated against allowlist patterns and paths are server-generated;
- outputs go to fresh managed directories, checked before the runner is started;
- the experiment fixtures, runners and imported runs are never write targets;
- ``-I -B`` keeps the child isolated from user site-packages and stops bytecode writes into source trees;
- without live mode, proxy variables point at a closed local port so no network request can succeed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from societytwin.common import is_within, redact, sha256_bytes, utc_now
from societytwin.config import Settings

TASK_RELATIVE = "application/tasks/example-survey_product-feedback"
INSTRUMENT_ID = "product_feedback_v1"
PERSON_ID = re.compile(r"^[A-Za-z0-9_]{1,64}$")
MODEL = re.compile(r"^[a-z0-9]{2,32}/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CLOSED_PROXY = "http://127.0.0.1:9"
PROBE_CODE = """
import json, sys
from pathlib import Path
repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / "src"))
import yaml
from matraix.smoke import ensure_launch_imports
ensure_launch_imports(repo)
import matraix
from pkgutil import extend_path
matraix.__path__ = extend_path(matraix.__path__, matraix.__name__)
from matraix.agents.persona.json_survey import PersonaJsonSurvey
from matraix.agents.persona.loader import load_persona
from playground.survey_task_content import load_survey_task_content_for_task_path
from harbor.models.agent.context import AgentContext
print(json.dumps({"ok": True, "python": sys.version.split()[0]}))
"""


def _shape(arg: str) -> str:
    """Log the shape of an argument: inline code is elided and paths are reduced to their last component."""
    if "\n" in arg or len(arg) > 160:
        return "<inline code>"
    return Path(arg).name if os.sep in arg else arg


class RuntimeUnavailable(Exception):
    code = "runtime_unavailable"


class UnsafeOutput(Exception):
    code = "unsafe_output_path"


@dataclass
class ProcessResult:
    returncode: int | None
    duration_seconds: float
    log_relpath: str
    error_tail: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class MatraixRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._probe: dict = {"status": "not_run", "checked_at": None, "detail": None}
        self._probe_lock = threading.Lock()

    # ---------------------------------------------------------------- discovery
    def matraix_root(self) -> tuple[Path | None, str]:
        if self.settings.matraix_root is not None:
            return self.settings.matraix_root, "MATRAIX_ROOT"
        # Same default as the experiment runners: a sibling checkout named MatrAIx-Persona-8B.
        return self.settings.repo_root.parent / "MatrAIx-Persona-8B", "default_sibling_path"

    def catalog_path(self) -> Path | None:
        root, _ = self.matraix_root()
        return root / "persona" / "schema" / "dimensions.json" if root else None

    def task_dir(self) -> Path | None:
        root, _ = self.matraix_root()
        return root / TASK_RELATIVE if root else None

    def catalog_bytes(self) -> bytes | None:
        path = self.catalog_path()
        try:
            return path.read_bytes() if path and path.is_file() else None
        except OSError:
            return None

    def task_content_hash(self) -> str | None:
        task = self.task_dir()
        if not task or not (task / "task.toml").is_file():
            return None
        entries = []
        for path in sorted(task.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and not path.is_symlink():
                entries.append(f"{path.relative_to(task).as_posix()}\0{sha256_bytes(path.read_bytes())}")
        return sha256_bytes("\n".join(entries).encode())

    def file_status(self) -> dict:
        root, source = self.matraix_root()
        python = self.settings.runtime_python
        layout = self.settings.layout
        status = {
            "matraix_root_source": source,
            "matraix_root_present": bool(root and root.is_dir()),
            "catalog_present": bool(self.catalog_path() and self.catalog_path().is_file()),
            "task_present": bool(self.task_dir() and (self.task_dir() / "task.toml").is_file()),
            "playground_package_present": bool(root and (root / "packages" / "playground").is_dir()),
            "runtime_python_configured": python is not None,
            "runtime_python_present": bool(python and python.is_file() and os.access(python, os.X_OK)),
            "adapter_present": self.settings.experiment_file(layout.adapter_source).is_file(),
            "smoke_runner_present": self.settings.experiment_file(layout.smoke_runner).is_file(),
            "ab_runner_present": self.settings.experiment_file(layout.ab_runner).is_file(),
            "probe": dict(self._probe),
        }
        reasons = []
        if not status["matraix_root_present"]:
            reasons.append("No MatrAIx checkout found (set MATRAIX_ROOT; the default is a sibling folder named MatrAIx-Persona-8B).")
        else:
            if not status["catalog_present"]:
                reasons.append("The MatrAIx persona catalog (persona/schema/dimensions.json) is missing.")
            if not status["task_present"]:
                reasons.append(f"The external task {TASK_RELATIVE} is missing.")
        if not status["runtime_python_configured"]:
            reasons.append("No runtime interpreter configured (set SOCIETYTWIN_RUNTIME_PYTHON to a Python 3.12 environment with MatrAIx installed editable).")
        elif not status["runtime_python_present"]:
            reasons.append("The configured runtime interpreter does not exist or is not executable.")
        for key, label in (("adapter_present", "persona adapter"), ("smoke_runner_present", "smoke runner"), ("ab_runner_present", "A/B runner")):
            if not status[key]:
                reasons.append(f"The experiment {label} source is missing from this checkout.")
        if self._probe["status"] == "failed":
            reasons.append("The last runtime import probe failed.")
        status["files_ready"] = all(status[k] for k in ("matraix_root_present", "catalog_present", "task_present",
                                                       "runtime_python_present", "adapter_present", "smoke_runner_present",
                                                       "ab_runner_present"))
        status["ready"] = status["files_ready"] and self._probe["status"] == "passed"
        if not reasons and not status["ready"]:
            reasons.append("Runtime files are present; run the import probe to confirm the interpreter can load MatrAIx.")
        status["reasons"] = reasons
        return status

    # ------------------------------------------------------------------ process
    def _env(self, *, allow_network: bool, extra: dict[str, str] | None = None) -> dict[str, str]:
        root, _ = self.matraix_root()
        self.settings.runtime_home.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.settings.runtime_home),
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "MATRAIX_ROOT": str(root),
        }
        if not allow_network:
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                env[name] = CLOSED_PROXY
            env["NO_PROXY"] = ""
        env.update(extra or {})
        return env

    def _require_ready_files(self) -> tuple[Path, Path]:
        status = self.file_status()
        if not status["files_ready"]:
            raise RuntimeUnavailable("; ".join(status["reasons"]) or "Runtime unavailable")
        root, _ = self.matraix_root()
        return self.settings.runtime_python, root  # type: ignore[return-value]

    def fresh_output_dir(self, path: Path) -> Path:
        """The wrapper, not the runner, rejects existing or unmanaged output paths before anything starts."""
        if not is_within(path, self.settings.state_dir):
            raise UnsafeOutput("Output must be inside the managed state directory")
        for protected in self.settings.protected_roots():
            if is_within(path, protected):
                raise UnsafeOutput("Output must not be inside the experiment fixtures or imported runs")
        if path.exists():
            raise UnsafeOutput("Output directory already exists; a fresh directory is required")
        return path

    def _invoke(self, args: list[str], *, log_path: Path, allow_network: bool,
                extra_env: dict[str, str] | None = None, timeout: int | None = None) -> ProcessResult:
        python, _ = self._require_ready_files()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [str(python), "-I", "-B", *args]
        started = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(  # noqa: S603 - argv is fully server-controlled, no shell
                argv, cwd=self.settings.repo_root, env=self._env(allow_network=allow_network, extra=extra_env),
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=timeout or self.settings.subprocess_timeout_seconds, check=False)
            returncode, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = None
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        duration = time.monotonic() - started
        # The log never contains environment values: only the child's own output, already redacted.
        log_path.write_text(
            json.dumps({"argv_shape": [_shape(a) for a in argv[3:]],
                        "returncode": returncode, "timed_out": timed_out, "duration_seconds": round(duration, 3),
                        "finished_at": utc_now()}, indent=2) + "\n--- stdout ---\n" + redact(stdout, max_length=200_000)
            + "\n--- stderr ---\n" + redact(stderr, max_length=200_000), encoding="utf-8")
        tail = redact("\n".join((stderr or "").strip().splitlines()[-6:]), max_length=800)
        return ProcessResult(returncode, duration, log_path.relative_to(self.settings.state_dir).as_posix(), tail, timed_out)

    def probe(self, timeout: int = 180) -> dict:
        with self._probe_lock:
            _, root = self._require_ready_files()
            log = self.settings.state_dir / "logs" / f"runtime_probe_{int(time.time())}.log"
            result = self._invoke(["-c", PROBE_CODE, str(root)], log_path=log, allow_network=False, timeout=timeout)
            self._probe = {
                "status": "passed" if result.ok else "failed",
                "checked_at": utc_now(),
                "detail": None if result.ok else (result.error_tail or "Import probe failed"),
                "log_relpath": result.log_relpath,
            }
            return dict(self._probe)

    # ------------------------------------------------------------------ actions
    def run_smoke(self, output_dir: Path, log_path: Path) -> ProcessResult:
        _, root = self._require_ready_files()
        self.fresh_output_dir(output_dir)
        script = self.settings.experiment_file(self.settings.layout.smoke_runner)
        return self._invoke([str(script), "--matraix-root", str(root), "--output-dir", str(output_dir)],
                            log_path=log_path, allow_network=False)

    def run_ab_prepare(self, output_dir: Path, model: str, temperature: float, log_path: Path) -> ProcessResult:
        _, root = self._require_ready_files()
        if not MODEL.fullmatch(model):
            raise ValueError("Model must look like provider/model")
        self.fresh_output_dir(output_dir)
        script = self.settings.experiment_file(self.settings.layout.ab_runner)
        return self._invoke([str(script), "--matraix-root", str(root), "--output-dir", str(output_dir),
                             "--model", model, "--temperature", repr(float(temperature))],
                            log_path=log_path, allow_network=False)

    def run_ab_execute(self, output_dir: Path, model: str, temperature: float, log_path: Path,
                       credential_env: dict[str, str]) -> ProcessResult:
        """Exactly the existing runner with --execute: two calls at most, zero automatic retries."""
        _, root = self._require_ready_files()
        if not MODEL.fullmatch(model):
            raise ValueError("Model must look like provider/model")
        self.fresh_output_dir(output_dir)
        script = self.settings.experiment_file(self.settings.layout.ab_runner)
        return self._invoke([str(script), "--matraix-root", str(root), "--output-dir", str(output_dir),
                             "--model", model, "--temperature", repr(float(temperature)), "--execute"],
                            log_path=log_path, allow_network=True, extra_env=credential_env)

    def materialize(self, person_id: str, source_csv: Path, output_yaml: Path, log_path: Path) -> ProcessResult:
        _, root = self._require_ready_files()
        if not PERSON_ID.fullmatch(person_id):
            raise ValueError("Invalid person ID")
        if output_yaml.suffix != ".yaml":
            raise UnsafeOutput("Persona output must be a .yaml file")
        self.fresh_output_dir(output_yaml.parent)
        script = self.settings.experiment_file(self.settings.layout.adapter_source)
        return self._invoke([str(script), "--person-id", person_id, "--source", str(source_csv),
                             "--output", str(output_yaml), "--matraix-root", str(root)],
                            log_path=log_path, allow_network=False)
