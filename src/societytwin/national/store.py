"""Population persistence (Parquet + JSON manifest) and server-side queries over a loaded build.

Layout, under ``data/populations/<population_id>/`` (git-ignored):

    records.parquet   one row per synthetic record (columns in generator.COLUMNS)
    manifest.json     generation config, scope, allocation, calibration, profiles, sources, checksums
    validation.json   source-fit validation report

A population directory is written once. Generating the same configuration again yields the same ID
and content, so the existing build is reused; nothing is overwritten.
"""

from __future__ import annotations

import json
import math
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, field_validator

from societytwin.common import sha256_file, utc_now
from societytwin.national import geography as geo
from societytwin.national.constraints import ADULT_AGE
from societytwin.national.generator import COLUMNS, GeneratedPopulation
from societytwin.national.vocab import AGE_GROUPS, NOT_APPLICABLE, VOCABULARIES

UNAVAILABLE = "unavailable"  # filter/display token for null (no source) values
SCHEMA = pa.schema([
    ("synthetic_id", pa.string()), ("province_code", pa.string()), ("province_name", pa.string()), ("nuts1_code", pa.string()),
    ("nuts2_code", pa.string()), ("nuts3_code", pa.string()), ("age", pa.int16()), ("age_group", pa.string()),
    ("age_top_coded", pa.bool_()), ("sex", pa.string()), ("marital_status", pa.string()), ("education_level", pa.string()),
    ("labour_status", pa.string()), ("household_size_class", pa.string()), ("household_type", pa.string()),
    ("urbanicity", pa.string()), ("population_weight", pa.float64()), ("design_weight", pa.float64()),
    ("provenance_profile", pa.string()), ("reference_year", pa.int16()),
])
CATEGORICAL = ("age_group", "sex", "marital_status", "education_level", "labour_status", "household_size_class",
               "household_type", "urbanicity")
SORTABLE = ("synthetic_id", "province_code", "age", "age_group", "sex", "population_weight")
MAX_PAGE = 200


class PopulationFilter(BaseModel):
    """AND across fields, OR within a field. ``unavailable`` matches records without a source value."""

    model_config = ConfigDict(extra="forbid")
    province_codes: list[str] | None = Field(default=None, min_length=1, max_length=81)
    age_min: int | None = Field(default=None, ge=0, le=120)
    age_max: int | None = Field(default=None, ge=0, le=120)
    age_groups: list[str] | None = Field(default=None, min_length=1)
    sexes: list[str] | None = Field(default=None, min_length=1)
    marital_statuses: list[str] | None = Field(default=None, min_length=1)
    education_levels: list[str] | None = Field(default=None, min_length=1)
    labour_statuses: list[str] | None = Field(default=None, min_length=1)
    household_size_classes: list[str] | None = Field(default=None, min_length=1)
    household_types: list[str] | None = Field(default=None, min_length=1)
    urbanicities: list[str] | None = Field(default=None, min_length=1)
    adult_only: bool = Field(default=False, description=f"Only records aged {ADULT_AGE} or over")

    @field_validator("province_codes")
    @classmethod
    def _codes(cls, value):
        if value is None:
            return value
        try:
            return sorted({geo.normalize_code(v) for v in value})
        except geo.UnknownProvince as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("age_groups")
    @classmethod
    def _bands(cls, value):
        if value and any(v not in AGE_GROUPS for v in value):
            raise ValueError(f"age groups must be among {AGE_GROUPS}")
        return value

    @field_validator("sexes", "marital_statuses", "education_levels", "labour_statuses", "household_size_classes",
                     "household_types", "urbanicities")
    @classmethod
    def _categories(cls, value, info):
        if value is None:
            return value
        attribute = FILTER_FIELDS[info.field_name]
        allowed = set(VOCABULARIES[attribute].codes) | ({NOT_APPLICABLE, UNAVAILABLE} if attribute != "sex" else set())
        bad = [v for v in value if v not in allowed]
        if bad:
            raise ValueError(f"unknown {attribute} values {bad}")
        return sorted(set(value))

    def normalized(self) -> dict:
        return self.model_dump(exclude_none=True, exclude_defaults=True)

    def mask(self, table: pa.Table) -> pa.ChunkedArray | pa.Array:
        conditions = []
        if self.province_codes:
            conditions.append(pc.is_in(table["province_code"], pa.array(self.province_codes)))
        if self.age_min is not None:
            conditions.append(pc.greater_equal(table["age"], self.age_min))
        if self.age_max is not None:
            conditions.append(pc.less_equal(table["age"], self.age_max))
        if self.adult_only:
            conditions.append(pc.greater_equal(table["age"], ADULT_AGE))
        if self.age_groups:
            conditions.append(pc.is_in(table["age_group"], pa.array(self.age_groups)))
        for name, column in FILTER_FIELDS.items():
            values = getattr(self, name)
            if not values:
                continue
            concrete = [v for v in values if v != UNAVAILABLE]
            cond = pc.is_in(table[column], pa.array(concrete, pa.string())) if concrete else None
            if UNAVAILABLE in values:
                nulls = pc.is_null(table[column])
                cond = nulls if cond is None else pc.or_(pc.fill_null(cond, False), nulls)
            conditions.append(pc.fill_null(cond, False))
        if not conditions:
            return pa.array([True] * table.num_rows)
        out = conditions[0]
        for c in conditions[1:]:
            out = pc.and_(out, c)
        return out


FILTER_FIELDS = {"sexes": "sex", "marital_statuses": "marital_status", "education_levels": "education_level",
                 "labour_statuses": "labour_status", "household_size_classes": "household_size_class",
                 "household_types": "household_type", "urbanicities": "urbanicity"}


@dataclass
class LoadedPopulation:
    manifest: dict
    table: pa.Table
    validation: dict | None
    directory: Path

    @property
    def population_id(self) -> str:
        return self.manifest["population_id"]

    def filtered(self, spec: PopulationFilter) -> pa.Table:
        return self.table.filter(spec.mask(self.table))

    def columns(self) -> dict[str, list]:
        return {name: self.table[name].to_pylist() for name in COLUMNS}

    def record(self, synthetic_id: str) -> dict | None:
        rows = self.table.filter(pc.equal(self.table["synthetic_id"], synthetic_id)).to_pylist()
        return rows[0] if rows else None


class PopulationStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[tuple, LoadedPopulation]] = {}

    def _dir(self, population_id: str) -> Path:
        if not population_id or "/" in population_id or ".." in population_id or not population_id.startswith("pop-"):
            raise KeyError(population_id)
        return self.directory / population_id

    def write(self, pop: GeneratedPopulation, validation: dict) -> tuple[dict, bool]:
        """Returns (manifest, created). An existing identical build is reused, never overwritten."""
        pid = pop.manifest["population_id"]
        target = self._dir(pid)
        if (target / "manifest.json").is_file():
            existing = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            if existing.get("content_sha256") != pop.manifest["content_sha256"]:
                raise FileExistsError(f"{pid} exists with different content; it is never overwritten")
            return existing, False
        tmp = self.directory / f".tmp-{pid}"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        table = pa.table({c: pop.columns[c] for c in COLUMNS}, schema=SCHEMA)
        pq.write_table(table, tmp / "records.parquet", compression="zstd")
        manifest = dict(pop.manifest, timings=pop.timings, written_at=utc_now(),
                        files={"records.parquet": {"sha256": sha256_file(tmp / "records.parquet"),
                                                   "bytes": (tmp / "records.parquet").stat().st_size}})
        (tmp / "validation.json").write_text(dumps(validation) + "\n", encoding="utf-8")
        (tmp / "manifest.json").write_text(dumps(manifest, indent=1) + "\n", encoding="utf-8")
        tmp.rename(target)
        return manifest, True

    def manifests(self) -> list[dict]:
        if not self.directory.is_dir():
            return []
        out = []
        for path in sorted(self.directory.glob("pop-*/manifest.json")):
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda m: m.get("generated_at", ""), reverse=True)

    def load(self, population_id: str) -> LoadedPopulation:
        directory = self._dir(population_id)
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise KeyError(population_id)
        signature = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(directory.iterdir()) if p.is_file())
        with self._lock:
            hit = self._cache.get(population_id)
            if hit and hit[0] == signature:
                return hit[1]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = directory / "records.parquet"
        if sha256_file(records) != manifest["files"]["records.parquet"]["sha256"]:
            raise ValueError(f"{population_id}: records.parquet differs from its manifest checksum")
        table = pq.read_table(records, schema=SCHEMA)
        validation_path = directory / "validation.json"
        validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.is_file() else None
        loaded = LoadedPopulation(manifest, table, validation, directory)
        with self._lock:
            self._cache[population_id] = (signature, loaded)
        return loaded


def clean(value):
    """JSON-safe copy: non-finite floats become null (JSON has no Infinity), sets become sorted lists."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, set):
        return sorted(clean(v) for v in value)
    return value


def dumps(value, indent: int | None = None) -> str:
    return json.dumps(clean(value), ensure_ascii=False, indent=indent, allow_nan=False)


# ---------------------------------------------------------------- queries
def _group_sums(table: pa.Table, keys: list[str]) -> list[dict]:
    if table.num_rows == 0:
        return []
    grouped = table.group_by(keys).aggregate([("population_weight", "sum"), ("synthetic_id", "count")])
    return grouped.to_pylist()


def distribution(table: pa.Table, field: str) -> dict:
    vocab = VOCABULARIES.get(field)
    rows = _group_sums(table, [field])
    total_w = sum(r["population_weight_sum"] for r in rows)
    total_n = sum(r["synthetic_id_count"] for r in rows)
    by_value = {r[field]: r for r in rows}
    order = list(AGE_GROUPS) if field == "age_group" else list(vocab.codes if vocab else [])
    extras = [v for v in by_value if v not in order and v is not None]
    categories = []
    for value in [*order, *sorted(extras), NOT_APPLICABLE, None]:
        if value in (NOT_APPLICABLE, None) and value not in by_value:
            continue
        r = by_value.get(value)
        w = r["population_weight_sum"] if r else 0.0
        n = r["synthetic_id_count"] if r else 0
        categories.append({"value": value if value is not None else UNAVAILABLE,
                           "label": (vocab.display(value) if vocab else (value or "Not available")),
                           "records": n, "weighted": w,
                           "weighted_share": w / total_w if total_w else None, "record_share": n / total_n if total_n else None})
    available = any(c["value"] not in (UNAVAILABLE,) for c in categories if c["records"])
    return {"field": field, "records": total_n, "weighted_total": total_w, "categories": categories,
            "available": available,
            "note": None if available else "No source table is loaded for this field in the selected provinces."}


def province_breakdown(table: pa.Table) -> list[dict]:
    rows = {r["province_code"]: r for r in _group_sums(table, ["province_code"])}
    return [{"province_code": code, "province_name": geo.province(code).name, "records": r["synthetic_id_count"],
             "weighted": r["population_weight_sum"]} for code, r in sorted(rows.items())]


def pyramid(table: pa.Table) -> list[dict]:
    rows = {(r["age_group"], r["sex"]): r for r in _group_sums(table, ["age_group", "sex"])}
    out = []
    for band in AGE_GROUPS:
        entry = {"age_group": band}
        for sex in VOCABULARIES["sex"].codes:
            r = rows.get((band, sex))
            entry[f"{sex}_weighted"] = r["population_weight_sum"] if r else 0.0
            entry[f"{sex}_records"] = r["synthetic_id_count"] if r else 0
        out.append(entry)
    return out


def page(table: pa.Table, sort: str, direction: str, offset: int, limit: int) -> list[dict]:
    if sort not in SORTABLE:
        raise ValueError(f"sort must be one of {SORTABLE}")
    if not 1 <= limit <= MAX_PAGE or offset < 0:
        raise ValueError(f"limit must be within 1..{MAX_PAGE} and offset >= 0")
    order = [(sort, "descending" if direction == "desc" else "ascending")]
    if sort != "synthetic_id":
        order.append(("synthetic_id", "ascending"))
    indices = pc.sort_indices(table, sort_keys=order)
    return table.take(indices[offset:offset + limit]).to_pylist()
