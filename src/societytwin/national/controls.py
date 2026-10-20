"""Standard internal control tables: the single boundary between official sources and the generator.

Every source (the historical Ankara extracts, the team's long-format TÜİK package, or any later
download) is normalised into rows of this one shape:

    table_id, geo_level, geo_code, year, sex, age_group, category, value, value_status, source_id, source_ref

``geo_level`` is province (plate code), nuts2, nuts1 or country. Empty ``sex`` / ``age_group`` /
``category`` mean "not broken down". Missing numbers keep their ``value_status``; they are never zero.

Province-level context indicators (the environment) are kept in a separate file of the same spirit. Each
context observation keeps its reference period exactly as published (a calendar year such as ``2025`` or a
multi-year period such as ``2021-2023``) and its observation type (``observed``, or ``projection`` /
``projection_baseline`` for official projections, which are never treated as current observations). Labels,
theme and source of an indicator are stored once in the manifest's indicator dictionary, not on every row.

The generator only ever reads this store, so it has no source-specific code.
"""

from __future__ import annotations

import csv
import functools
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from societytwin.common import sha256_bytes, utc_now
from societytwin.national import geography as geo
from societytwin.national.vocab import AGE_GROUPS, VOCABULARIES, ValueStatus

STORE_VERSION = "controls-store-2"
CONTROL_COLUMNS = ("table_id", "geo_level", "geo_code", "year", "sex", "age_group", "category", "value",
                   "value_status", "source_id", "source_ref")
CONTEXT_COLUMNS = ("indicator_id", "geo_level", "geo_code", "period", "value", "value_status", "observation_type", "unit",
                   "source_ref")
INDICATOR_FIELDS = ("theme", "label_en", "label_tr", "source_id")
GEO_LEVELS = ("province", "nuts2", "nuts1", "country")
OBSERVATION_TYPES = ("observed", "projection", "projection_baseline")
_PERIOD = re.compile(r"(\d{4})(?:\s*[-–]\s*(\d{4}))?")


@functools.lru_cache(maxsize=4096)
def parse_period(text: str) -> tuple[str, int, int]:
    """A reference period as published: one calendar year (``2025``) or a multi-year period (``2021-2023``).

    Returns (label, first year, last year). The label is kept verbatim; nothing is reduced to a single year.
    """
    label = str(text).strip()
    m = _PERIOD.fullmatch(label)
    if m is None:
        try:  # tolerate spreadsheet-style years such as "2025.0"
            value = float(label)
        except ValueError:
            raise ValueError(f"unparseable reference period {text!r}") from None
        if not value.is_integer():
            raise ValueError(f"unparseable reference period {text!r}")
        label = str(int(value))
        m = _PERIOD.fullmatch(label)
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    if not (1900 <= start <= end <= 2100):
        raise ValueError(f"reference period {text!r} out of range")
    return label, start, end


@dataclass(frozen=True)
class TableKind:
    kind: str
    dims: tuple[str, ...]           # subset of ("age_group", "sex", "category"), in key order
    attribute: str | None           # person attribute it controls; None for the root table
    description: str


TABLE_KINDS: dict[str, TableKind] = {k.kind: k for k in (
    TableKind("population_age_sex", ("age_group", "sex"), None,
              "Resident population by five-year age group and sex (ADNKS). Root table of the generator."),
    TableKind("marital_status_age_sex", ("age_group", "sex", "category"), "marital_status",
              "Population by marital status, age group and sex."),
    TableKind("marital_status_sex", ("sex", "category"), "marital_status", "Population by marital status and sex."),
    TableKind("education_age_sex", ("age_group", "sex", "category"), "education_level",
              "Population by completed education, age group and sex."),
    TableKind("education_sex", ("sex", "category"), "education_level", "Population by completed education and sex."),
    TableKind("labour_status_age_sex", ("age_group", "sex", "category"), "labour_status",
              "Population by labour status, age group and sex (HLFS; usually regional)."),
    TableKind("labour_status_sex", ("sex", "category"), "labour_status", "Population by labour status and sex (HLFS)."),
    TableKind("household_size_persons", ("category",), "household_size_class",
              "Persons by size of the household they live in."),
    TableKind("household_type_persons", ("category",), "household_type", "Persons by household type."),
    TableKind("urbanicity_sex", ("sex", "category"), "urbanicity", "Population by settlement type and sex."),
    TableKind("urbanicity", ("category",), "urbanicity", "Population by settlement type."),
)}


class ControlsError(ValueError):
    pass


@dataclass
class TableMeta:
    table_id: str
    kind: str
    title: str
    unit: str = "persons"
    universe_min_age: int = 0
    universe_note: str = "All residents"
    source_ids: list[str] = field(default_factory=list)
    transformations: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ControlRow:
    table_id: str
    geo_level: str
    geo_code: str
    year: int
    sex: str
    age_group: str
    category: str
    value: float | None
    value_status: str
    source_id: str
    source_ref: str

    def key(self, dims: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(getattr(self, d) for d in dims)


@dataclass(frozen=True, slots=True)
class ContextRow:
    indicator_id: str
    theme: str
    label_en: str
    label_tr: str
    geo_level: str
    geo_code: str
    year: int | None            # calendar year of a single-year observation; None for a multi-year period
    value: float | None
    value_status: str
    unit: str
    source_id: str
    source_ref: str
    period: str = ""            # reference period as published ("2025", "2021-2023"); defaults to the year
    observation_type: str = "observed"

    def __post_init__(self):
        if not self.period:
            if self.year is None:
                raise ControlsError(f"{self.indicator_id}: a context row needs a year or a period")
            object.__setattr__(self, "period", str(self.year))
        if self.observation_type not in OBSERVATION_TYPES:
            raise ControlsError(f"{self.indicator_id}: invalid observation type {self.observation_type!r}")

    @property
    def period_start(self) -> int:
        return parse_period(self.period)[1]

    @property
    def period_end(self) -> int:
        return parse_period(self.period)[2]

    @property
    def is_multi_year(self) -> bool:
        return self.year is None

    @property
    def is_projection(self) -> bool:
        return self.observation_type != "observed"


def validate_row(row: ControlRow, meta: TableMeta) -> None:
    kind = TABLE_KINDS.get(meta.kind)
    if kind is None:
        raise ControlsError(f"Unknown table kind {meta.kind!r}")
    if row.geo_level not in GEO_LEVELS:
        raise ControlsError(f"Invalid geo_level {row.geo_level!r}")
    geo.provinces_in(row.geo_level, row.geo_code)  # raises for unknown codes
    if not 1900 <= row.year <= 2100:
        raise ControlsError(f"Invalid year {row.year}")
    if row.value_status not in ValueStatus.ALL:
        raise ControlsError(f"Invalid value_status {row.value_status!r}")
    if row.value_status == ValueStatus.OBSERVED and (row.value is None or row.value < 0):
        raise ControlsError("An observed control value must be a nonnegative number")
    if row.value_status != ValueStatus.OBSERVED and row.value is not None:
        raise ControlsError("Only observed cells carry a value")
    for dim in ("age_group", "sex", "category"):
        value = getattr(row, dim)
        if dim not in kind.dims:
            if value:
                raise ControlsError(f"{meta.table_id} has no {dim} dimension")
            continue
        if not value:
            raise ControlsError(f"{meta.table_id} row lacks {dim}")
        if dim == "age_group" and value not in AGE_GROUPS:
            raise ControlsError(f"Unknown age group {value!r}")
        if dim == "sex" and value not in VOCABULARIES["sex"].codes:
            raise ControlsError(f"Unknown sex {value!r}")
        if dim == "category" and value not in VOCABULARIES[kind.attribute].codes:
            raise ControlsError(f"Unknown {kind.attribute} category {value!r}")


@dataclass
class ControlStore:
    tables: dict[str, TableMeta]
    rows: list[ControlRow]
    context: list[ContextRow]
    sources: list[dict]
    built_at: str | None = None
    inputs: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fingerprint: str = ""
    audits: list[dict] = field(default_factory=list)       # per-adapter source audits (package checks, discrepancies)

    def __post_init__(self):
        self._index: dict[tuple[str, str, str, int], list[ControlRow]] = {}
        self._years: dict[tuple[str, str, str], set[int]] = {}
        for row in self.rows:
            self._index.setdefault((row.table_id, row.geo_level, row.geo_code, row.year), []).append(row)
            self._years.setdefault((row.table_id, row.geo_level, row.geo_code), set()).add(row.year)
        self._last_end = None
        self._context_index: dict[tuple[str, str], list[ContextRow]] = {}
        for row in self.context:
            self._context_index.setdefault((row.geo_level, row.geo_code), []).append(row)

    # ------------------------------------------------------------ lookups
    def years(self, table_id: str, geo_level: str, geo_code: str) -> list[int]:
        return sorted(self._years.get((table_id, geo_level, geo_code), ()))

    def cells(self, table_id: str, geo_level: str, geo_code: str, year: int) -> list[ControlRow]:
        return self._index.get((table_id, geo_level, geo_code, year), [])

    def best(self, table_id: str, province: geo.Province, reference_year: int) -> "Selection | None":
        """Most specific geography with observed cells, then the latest year not after the reference year."""
        if table_id not in self.tables:
            return None
        for level, code in geo.containing_geographies(province):
            years = [y for y in self.years(table_id, level, code) if y <= reference_year]
            for year in sorted(years, reverse=True):
                rows = self.cells(table_id, level, code, year)
                if any(r.value_status == ValueStatus.OBSERVED for r in rows):
                    return Selection(self.tables[table_id], level, code, year, rows)
        return None

    def later_years_only(self, table_id: str, province: geo.Province, reference_year: int) -> list[int]:
        out = set()
        for level, code in geo.containing_geographies(province):
            out.update(y for y in self.years(table_id, level, code) if y > reference_year)
        return sorted(out)

    def provinces_with(self, table_id: str, reference_year: int | None = None) -> list[str]:
        covered = []
        for p in geo.PROVINCES:
            if reference_year is None:
                hit = any(self.years(table_id, lvl, code) for lvl, code in geo.containing_geographies(p))
            else:
                hit = self.best(table_id, p, reference_year) is not None
            if hit:
                covered.append(p.code)
        return covered

    def context_for(self, province: geo.Province) -> list[ContextRow]:
        return [c for g in geo.containing_geographies(province) for c in self._context_index.get(g, [])]

    def indicator_last_period_end(self) -> dict[str, int]:
        """Latest observed (non-projection) period end per indicator over all geographies (cached)."""
        cached = getattr(self, "_last_end", None)
        if cached is None:
            cached = {}
            for c in self.context:
                if not c.is_projection and cached.get(c.indicator_id, 0) < c.period_end:
                    cached[c.indicator_id] = c.period_end
            self._last_end = cached
        return cached

    def indicators(self) -> dict[str, dict]:
        """Indicator dictionary: id -> theme, labels, unit(s), source and observation counts."""
        out: dict[str, dict] = {}
        for c in self.context:
            entry = out.get(c.indicator_id)
            if entry is None:
                entry = out[c.indicator_id] = {"indicator_id": c.indicator_id, "theme": c.theme, "label_en": c.label_en,
                                               "label_tr": c.label_tr, "source_id": c.source_id, "units": set(), "rows": 0}
            entry["units"].add(c.unit)
            entry["rows"] += 1
        for entry in out.values():
            entry["units"] = sorted(entry["units"])
        return out

    def source(self, source_id: str) -> dict | None:
        return next((s for s in self.sources if s.get("source_id") == source_id), None)


@dataclass(frozen=True)
class Selection:
    meta: TableMeta
    geo_level: str
    geo_code: str
    year: int
    rows: list[ControlRow]

    def counts(self) -> dict[tuple[str, ...], float]:
        dims = TABLE_KINDS[self.meta.kind].dims
        out: dict[tuple[str, ...], float] = {}
        for row in self.rows:
            if row.value_status == ValueStatus.OBSERVED:
                out[row.key(dims)] = out.get(row.key(dims), 0.0) + float(row.value)
        return out

    @property
    def source_ids(self) -> list[str]:
        """Sources of the selected cells (a table can merge several sources; only the cited ones are listed)."""
        return sorted({r.source_id for r in self.rows})

    def describe(self) -> dict:
        return {"table_id": self.meta.table_id, "geo_level": self.geo_level, "geo_code": self.geo_code, "year": self.year,
                "source_ids": self.source_ids}


# ---------------------------------------------------------------- persistence
def _num(text: str) -> float | None:
    return None if text == "" else float(text)


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _indicator_dictionary(context: list[ContextRow]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in context:
        entry = {f: getattr(c, f) for f in INDICATOR_FIELDS}
        known = out.setdefault(c.indicator_id, entry)
        if known != entry:
            raise ControlsError(f"Context indicator {c.indicator_id!r} has inconsistent labels, theme or source")
    return dict(sorted(out.items()))


def write_store(directory: Path, store: ControlStore) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    controls = io.StringIO()
    writer = csv.writer(controls, lineterminator="\n")
    writer.writerow(CONTROL_COLUMNS)
    for r in sorted(store.rows, key=lambda r: (r.table_id, r.geo_level, r.geo_code, r.year, r.sex, r.age_group, r.category)):
        writer.writerow([r.table_id, r.geo_level, r.geo_code, r.year, r.sex, r.age_group, r.category, _fmt(r.value),
                         r.value_status, r.source_id, r.source_ref])
    indicators = _indicator_dictionary(store.context)
    context = io.StringIO()
    writer = csv.writer(context, lineterminator="\n")
    writer.writerow(CONTEXT_COLUMNS)
    for c in sorted(store.context, key=lambda c: (c.indicator_id, c.geo_level, c.geo_code, c.period_start, c.period_end)):
        writer.writerow([c.indicator_id, c.geo_level, c.geo_code, c.period, _fmt(c.value), c.value_status, c.observation_type,
                         c.unit, c.source_ref])
    files = {"controls.csv": controls.getvalue().encode("utf-8"), "context.csv": context.getvalue().encode("utf-8")}
    for name, data in files.items():
        (directory / name).write_bytes(data)
    manifest = {
        "store_version": STORE_VERSION,
        "built_at": store.built_at or utc_now(),
        "tables": [t.as_dict() for t in store.tables.values()],
        "sources": store.sources,
        "indicators": indicators,
        "audits": store.audits,
        "inputs": store.inputs,
        "warnings": store.warnings,
        "files": {name: {"sha256": sha256_bytes(data), "bytes": len(data)} for name, data in files.items()},
        "row_counts": {"controls": len(store.rows), "context": len(store.context), "context_indicators": len(indicators)},
    }
    manifest["fingerprint"] = sha256_bytes(json.dumps({k: manifest[k] for k in ("tables", "sources", "indicators", "files")},
                                                      sort_keys=True, ensure_ascii=False).encode())
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def read_store(directory: Path) -> ControlStore:
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Control tables have not been built ({directory.name}/manifest.json is missing)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("store_version") != STORE_VERSION:
        raise ControlsError(f"Unsupported control store version {manifest.get('store_version')!r}; rebuild the controls")
    for name, info in manifest["files"].items():
        if sha256_bytes((directory / name).read_bytes()) != info["sha256"]:
            raise ControlsError(f"{name} differs from its manifest checksum; rebuild the controls")
    tables = {t["table_id"]: TableMeta(**t) for t in manifest["tables"]}
    rows = []
    with (directory / "controls.csv").open(encoding="utf-8", newline="") as handle:
        for rec in csv.DictReader(handle):
            row = ControlRow(rec["table_id"], rec["geo_level"], rec["geo_code"], int(rec["year"]), rec["sex"], rec["age_group"],
                             rec["category"], _num(rec["value"]), rec["value_status"], rec["source_id"], rec["source_ref"])
            validate_row(row, tables[row.table_id])
            rows.append(row)
    indicators = manifest["indicators"]
    context = []
    years: dict[str, int | None] = {}
    with (directory / "context.csv").open(encoding="utf-8", newline="") as handle:
        for rec in csv.DictReader(handle):
            info = indicators[rec["indicator_id"]]
            period = rec["period"]
            if period not in years:
                _, start, end = parse_period(period)
                years[period] = start if start == end else None
            context.append(ContextRow(rec["indicator_id"], info["theme"], info["label_en"], info["label_tr"], rec["geo_level"],
                                      rec["geo_code"], years[period], _num(rec["value"]), rec["value_status"], rec["unit"],
                                      info["source_id"], rec["source_ref"], period, rec["observation_type"]))
    return ControlStore(tables, rows, context, manifest["sources"], manifest["built_at"], manifest.get("inputs", []),
                        manifest.get("warnings", []), manifest["fingerprint"], manifest.get("audits", []))
