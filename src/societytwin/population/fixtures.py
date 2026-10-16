"""Strict readers for the synthetic population CSVs and the processed reference tables."""

from __future__ import annotations

import csv
import io
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from societytwin.common import sha256_bytes
from societytwin.population.categories import (
    ADULT_MARITAL_STATUSES,
    AGE_GROUPS,
    CONDITIONING_VALUES,
    GENDERS,
    MARITAL_STATUSES,
)

BASE_FIELDS: tuple[str, ...] = ("person_id", "age_group", "gender")
V2_FIELDS: tuple[str, ...] = BASE_FIELDS + ("marital_status", "marital_status_conditioning")
AGE_GENDER_FIELDS = ("year", "province", "age_group", "gender", "population", "probability")
MARITAL_FIELDS = ("year", "province", "gender", "marital_status", "population", "conditional_probability")
CONTROLS_FIELDS = ("year", "province", "statistic", "value", "unit", "source_workbook", "source_sheet", "source_row")

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_INT = re.compile(r"^\d+$")
_ALLOWED_VALUES: dict[str, tuple[str, ...]] = {
    "age_group": AGE_GROUPS,
    "gender": GENDERS,
    "marital_status": MARITAL_STATUSES,
    "marital_status_conditioning": CONDITIONING_VALUES,
}


class FixtureFormatError(ValueError):
    """A fixture file does not match its documented schema; nothing is repaired silently."""


def _read_rows(data: bytes, expected_fields: tuple[str, ...], label: str) -> list[tuple[int, dict[str, str]]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FixtureFormatError(f"{label}: not valid UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != expected_fields:
        raise FixtureFormatError(f"{label}: header {reader.fieldnames!r} != {list(expected_fields)!r}")
    rows = []
    for row_number, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise FixtureFormatError(f"{label}: malformed CSV row {row_number}")
        if any(value == "" for value in row.values()):
            raise FixtureFormatError(f"{label}: empty value in row {row_number}")
        rows.append((row_number, dict(row)))
    if not rows:
        raise FixtureFormatError(f"{label}: no data rows")
    return rows


@dataclass(frozen=True)
class PopulationTable:
    fields: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    csv_rows: dict[str, int]
    sha256: str
    byte_size: int

    @property
    def row_count(self) -> int:
        return len(self.rows)


def parse_population(data: bytes, expected_fields: tuple[str, ...], label: str = "population") -> PopulationTable:
    parsed = _read_rows(data, expected_fields, label)
    rows: list[dict[str, str]] = []
    csv_rows: dict[str, int] = {}
    for row_number, row in parsed:
        person_id = row["person_id"]
        if not ID_PATTERN.fullmatch(person_id):
            raise FixtureFormatError(f"{label}: invalid person_id in row {row_number}")
        if person_id in csv_rows:
            raise FixtureFormatError(f"{label}: duplicate person_id {person_id!r} in row {row_number}")
        for column, allowed in _ALLOWED_VALUES.items():
            if column in row and row[column] not in allowed:
                raise FixtureFormatError(f"{label}: unknown {column} category {row[column]!r} in row {row_number}")
        csv_rows[person_id] = row_number
        rows.append(row)
    return PopulationTable(tuple(expected_fields), tuple(rows), csv_rows, sha256_bytes(data), len(data))


def read_population(path: Path, expected_fields: tuple[str, ...]) -> PopulationTable:
    return parse_population(path.read_bytes(), expected_fields, path.name)


def _finite_probability(value: str, label: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise FixtureFormatError(f"{label}: probability {value!r} is not numeric") from exc
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise FixtureFormatError(f"{label}: probability {value!r} is not finite in [0, 1]")
    return number


def _count(value: str, label: str) -> int:
    if not _INT.fullmatch(value):
        raise FixtureFormatError(f"{label}: population {value!r} is not a nonnegative integer")
    return int(value)


@dataclass(frozen=True)
class ReferenceTable:
    name: str
    fields: tuple[str, ...]
    rows: tuple[dict, ...]
    sha256: str
    byte_size: int
    year: int
    province: str


def _single_scope(rows: list[dict], label: str) -> tuple[int, str]:
    scopes = {(row["year"], row["province"]) for row in rows}
    if len(scopes) != 1:
        raise FixtureFormatError(f"{label}: expected exactly one year/province, found {sorted(scopes)}")
    return scopes.pop()


def parse_age_gender(data: bytes, label: str = "age_gender") -> ReferenceTable:
    rows = []
    for row_number, raw in _read_rows(data, AGE_GENDER_FIELDS, label):
        where = f"{label} row {row_number}"
        if raw["age_group"] not in AGE_GROUPS or raw["gender"] not in GENDERS:
            raise FixtureFormatError(f"{where}: unknown age group or gender")
        rows.append(dict(year=_count(raw["year"], where), province=raw["province"], age_group=raw["age_group"],
                         gender=raw["gender"], population=_count(raw["population"], where),
                         probability=_finite_probability(raw["probability"], where)))
    year, province = _single_scope(rows, label)
    keys = [(r["age_group"], r["gender"]) for r in rows]
    expected = {(age, gender) for age in AGE_GROUPS for gender in GENDERS}
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise FixtureFormatError(f"{label}: expected each of {len(expected)} age×gender cells exactly once")
    total = sum(r["population"] for r in rows)
    if total <= 0:
        raise FixtureFormatError(f"{label}: total population must be positive")
    for row in rows:
        if not math.isclose(row["probability"], row["population"] / total, rel_tol=0, abs_tol=1e-12):
            raise FixtureFormatError(f"{label}: stored probability disagrees with population/total")
    if not math.isclose(math.fsum(r["probability"] for r in rows), 1.0, rel_tol=0, abs_tol=1e-9):
        raise FixtureFormatError(f"{label}: probabilities do not sum to one")
    return ReferenceTable(label, AGE_GENDER_FIELDS, tuple(rows), sha256_bytes(data), len(data), year, province)


def parse_marital_gender(data: bytes, label: str = "marital_gender") -> ReferenceTable:
    rows = []
    for row_number, raw in _read_rows(data, MARITAL_FIELDS, label):
        where = f"{label} row {row_number}"
        if raw["gender"] not in GENDERS or raw["marital_status"] not in ADULT_MARITAL_STATUSES:
            raise FixtureFormatError(f"{where}: unknown gender or marital category")
        rows.append(dict(year=_count(raw["year"], where), province=raw["province"], gender=raw["gender"],
                         marital_status=raw["marital_status"], population=_count(raw["population"], where),
                         conditional_probability=_finite_probability(raw["conditional_probability"], where)))
    year, province = _single_scope(rows, label)
    keys = [(r["gender"], r["marital_status"]) for r in rows]
    expected = {(g, s) for g in GENDERS for s in ADULT_MARITAL_STATUSES}
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise FixtureFormatError(f"{label}: expected four marital categories for each gender exactly once")
    for gender in GENDERS:
        subset = [r for r in rows if r["gender"] == gender]
        denominator = sum(r["population"] for r in subset)
        if denominator <= 0:
            raise FixtureFormatError(f"{label}: {gender} denominator must be positive")
        for row in subset:
            if not math.isclose(row["conditional_probability"], row["population"] / denominator, rel_tol=0, abs_tol=1e-12):
                raise FixtureFormatError(f"{label}: conditional probability disagrees with the gender denominator")
        if not math.isclose(math.fsum(r["conditional_probability"] for r in subset), 1.0, rel_tol=0, abs_tol=1e-9):
            raise FixtureFormatError(f"{label}: {gender} conditional probabilities do not sum to one")
    return ReferenceTable(label, MARITAL_FIELDS, tuple(rows), sha256_bytes(data), len(data), year, province)


@dataclass(frozen=True)
class ControlFact:
    """One deduplicated (year, province, statistic) fact with every agreeing source observation."""

    year: int
    province: str
    statistic: str
    value: float
    unit: str
    observations: tuple[dict, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ControlsTable:
    observations: tuple[dict, ...]
    facts: tuple[ControlFact, ...]
    sha256: str
    byte_size: int


def parse_controls(data: bytes, label: str = "controls") -> ControlsTable:
    observations = []
    for row_number, raw in _read_rows(data, CONTROLS_FIELDS, label):
        where = f"{label} row {row_number}"
        try:
            value = float(raw["value"])
        except ValueError as exc:
            raise FixtureFormatError(f"{where}: value is not numeric") from exc
        if not math.isfinite(value) or value <= 0:
            raise FixtureFormatError(f"{where}: value must be finite and positive")
        observations.append(dict(year=_count(raw["year"], where), province=raw["province"], statistic=raw["statistic"],
                                 value=value, unit=raw["unit"], source_workbook=raw["source_workbook"],
                                 source_sheet=raw["source_sheet"], source_row=_count(raw["source_row"], where),
                                 csv_row=row_number))
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for obs in observations:
        grouped[(obs["year"], obs["province"], obs["statistic"])].append(obs)
    facts = []
    for (year, province, statistic), group in sorted(grouped.items()):
        values = {obs["value"] for obs in group}
        units = {obs["unit"] for obs in group}
        if len(values) != 1 or len(units) != 1:
            raise FixtureFormatError(f"{label}: conflicting observations for {year} {province} {statistic}")
        facts.append(ControlFact(year, province, statistic, group[0]["value"], group[0]["unit"], tuple(group)))
    by_key = {(f.year, f.province, f.statistic): f.value for f in facts}
    for year, province in {(f.year, f.province) for f in facts}:
        parts = [by_key.get((year, province, s)) for s in ("total_population", "male_population", "female_population")]
        if any(p is not None for p in parts):
            if any(p is None for p in parts) or parts[0] != parts[1] + parts[2]:
                raise FixtureFormatError(f"{label}: population controls do not reconcile for {province} {year}")
    return ControlsTable(tuple(observations), tuple(facts), sha256_bytes(data), len(data))
