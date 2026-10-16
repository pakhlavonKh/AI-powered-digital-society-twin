"""Server-side settings. Every filesystem root the service may read or write is declared here."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

REPO_ROOT_DEFAULT = Path(__file__).resolve().parents[2]
EXPERIMENT_REL = Path("experiments") / "matraix_simulation"


@dataclass(frozen=True)
class ExperimentLayout:
    """Relative file layout of an experiment fixture directory.

    The defaults mirror ``experiments/matraix_simulation``. A ``layout.json`` file in the
    experiment root may override them (used by the artificial test fixtures).
    """

    base_population: str = "synthetic/ankara_population_1000.csv"
    v2_population: str = "synthetic/ankara_population_1000_v2.csv"
    age_gender: str = "processed/ankara_age_gender.csv"
    marital_gender: str = "processed/ankara_marital_gender.csv"
    controls: str = "processed/ankara_demographic_controls.csv"
    personas_dir: str = "personas"
    runs_dir: str = "runs"
    generator_source: str = "src/synthetic_population/generate_population.py"
    adapter_source: str = "src/persona_adapter/build_matraix_persona.py"
    smoke_runner: str = "src/runtime/run_matraix_smoke.py"
    ab_runner: str = "src/runtime/run_matraix_ab.py"
    fixture_kind: str = "project_fixture"

    @classmethod
    def load(cls, experiment_root: Path) -> "ExperimentLayout":
        path = experiment_root / "layout.json"
        if not path.is_file():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        allowed = set(cls.__dataclass_fields__)
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown layout keys: {sorted(unknown)}")
        return cls(**payload)


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    experiment_root: Path
    import_runs_root: Path
    state_dir: Path
    data_manifest: Path
    matraix_root: Path | None
    runtime_python: Path | None
    frontend_origins: tuple[str, ...] = ("http://127.0.0.1:3000", "http://localhost:3000")
    local_mutations: bool = True
    live_execution_enabled: bool = False
    start_worker: bool = True
    subprocess_timeout_seconds: int = 600
    layout: ExperimentLayout = field(default_factory=ExperimentLayout)

    @property
    def registry_path(self) -> Path:
        return self.state_dir / "registry.sqlite3"

    @property
    def managed_experiments_dir(self) -> Path:
        return self.state_dir / "experiments"

    @property
    def managed_personas_dir(self) -> Path:
        return self.state_dir / "personas"

    @property
    def runtime_home(self) -> Path:
        return self.state_dir / "runtime_home"

    def experiment_file(self, relative: str) -> Path:
        return self.experiment_root / relative

    def protected_roots(self) -> tuple[Path, ...]:
        """Directories the service must never write into."""
        return (self.experiment_root, self.import_runs_root)

    def with_overrides(self, **kwargs) -> "Settings":
        return replace(self, **kwargs)


def load_settings() -> Settings:
    repo_root = _env_path("SOCIETYTWIN_REPO_ROOT") or REPO_ROOT_DEFAULT
    experiment_root = _env_path("SOCIETYTWIN_EXPERIMENT_ROOT") or repo_root / EXPERIMENT_REL
    layout = ExperimentLayout.load(experiment_root)
    import_runs_root = _env_path("SOCIETYTWIN_IMPORT_RUNS_DIR") or experiment_root / layout.runs_dir
    # data/results/* is git-ignored; managed state never shares a folder with imported evidence.
    state_dir = _env_path("SOCIETYTWIN_STATE_DIR") or repo_root / "data" / "results" / "societytwin_local"
    origins = tuple(
        o.strip() for o in os.environ.get("SOCIETYTWIN_FRONTEND_ORIGINS", "").split(",") if o.strip()
    ) or ("http://127.0.0.1:3000", "http://localhost:3000")
    timeout = int(os.environ.get("SOCIETYTWIN_SUBPROCESS_TIMEOUT", "600"))
    return Settings(
        repo_root=repo_root,
        experiment_root=experiment_root,
        import_runs_root=import_runs_root,
        state_dir=state_dir,
        data_manifest=_env_path("SOCIETYTWIN_DATA_MANIFEST") or repo_root / "data" / "manifest.yaml",
        matraix_root=_env_path("MATRAIX_ROOT"),
        runtime_python=_env_path("SOCIETYTWIN_RUNTIME_PYTHON"),
        frontend_origins=origins,
        local_mutations=_env_flag("SOCIETYTWIN_LOCAL_MUTATIONS", True),
        live_execution_enabled=_env_flag("SOCIETYTWIN_ENABLE_LIVE_EXECUTION", False),
        start_worker=_env_flag("SOCIETYTWIN_START_WORKER", True),
        subprocess_timeout_seconds=timeout,
        layout=layout,
    )
