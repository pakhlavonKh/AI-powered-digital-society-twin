"""Read repository over the CSV fixtures.

The interface is deliberately small so that a DuckDB/Parquet implementation can replace it later;
no such migration has happened.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from societytwin.config import Settings
from societytwin.population.builds import BuildSource, build_sources, describe_build, read_configured_seed
from societytwin.population.fixtures import (
    ControlsTable,
    FixtureFormatError,
    PopulationTable,
    ReferenceTable,
    parse_age_gender,
    parse_controls,
    parse_marital_gender,
    parse_population,
)


class PopulationError(Exception):
    code = "population_error"


class UnknownBuild(PopulationError):
    code = "unknown_build"


class BuildSourceChanged(PopulationError):
    code = "build_source_changed"


class FixtureUnavailable(PopulationError):
    code = "fixture_unavailable"


@dataclass(frozen=True)
class LoadedBuild:
    descriptor: dict
    source: BuildSource
    table: PopulationTable


class PopulationRepository(Protocol):
    def current_builds(self) -> list[LoadedBuild]: ...
    def build_errors(self) -> list[dict]: ...
    def load(self, build_id: str) -> LoadedBuild: ...
    def age_gender(self) -> ReferenceTable: ...
    def marital_gender(self) -> ReferenceTable: ...
    def controls(self) -> ControlsTable: ...


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


class CsvPopulationRepository:
    """Loads the small fixture files into memory and re-reads them when their size or mtime changes.

    Every load re-hashes the bytes it parses, so a build ID always matches the bytes served.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[tuple[int, int] | None, object]] = {}

    def _cached(self, key: str, path: Path, parse):
        signature = _signature(path)
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] == signature and signature is not None:
                return hit[1]
        if signature is None:
            raise FixtureUnavailable(f"{key} is not present")
        value = parse(path.read_bytes())
        with self._lock:
            self._cache[key] = (signature, value)
        return value

    def age_gender(self) -> ReferenceTable:
        path = self.settings.experiment_file(self.settings.layout.age_gender)
        return self._cached("age_gender", path, lambda b: parse_age_gender(b, Path(self.settings.layout.age_gender).name))

    def marital_gender(self) -> ReferenceTable:
        path = self.settings.experiment_file(self.settings.layout.marital_gender)
        return self._cached("marital_gender", path,
                            lambda b: parse_marital_gender(b, Path(self.settings.layout.marital_gender).name))

    def controls(self) -> ControlsTable:
        path = self.settings.experiment_file(self.settings.layout.controls)
        return self._cached("controls", path, lambda b: parse_controls(b, Path(self.settings.layout.controls).name))

    def _scan(self) -> tuple[list[LoadedBuild], list[dict]]:
        builds: list[LoadedBuild] = []
        errors: list[dict] = []
        try:
            reference = self.age_gender()
        except (FixtureUnavailable, FixtureFormatError) as exc:
            return [], [{"variant": "*", "code": "reference_unavailable", "message": str(exc)}]
        seed, seed_evidence = read_configured_seed(self.settings.experiment_file(self.settings.layout.generator_source))
        for source in build_sources(self.settings.layout):
            path = self.settings.experiment_file(source.relative_path)
            try:
                table = self._cached(f"population:{source.variant}", path,
                                     lambda b, s=source: parse_population(b, s.fields, Path(s.relative_path).name))
                descriptor = describe_build(source, table, reference, seed, seed_evidence, self.settings.layout.fixture_kind)
            except FixtureUnavailable as exc:
                errors.append({"variant": source.variant, "code": "missing", "message": str(exc)})
                continue
            except (FixtureFormatError, ValueError) as exc:
                errors.append({"variant": source.variant, "code": "invalid", "message": str(exc)})
                continue
            builds.append(LoadedBuild(descriptor, source, table))
        return builds, errors

    def current_builds(self) -> list[LoadedBuild]:
        return self._scan()[0]

    def build_errors(self) -> list[dict]:
        return self._scan()[1]

    def load(self, build_id: str) -> LoadedBuild:
        for build in self.current_builds():
            if build.descriptor["build_id"] == build_id:
                return build
        raise UnknownBuild(build_id)
