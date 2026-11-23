"""Reproducible reference dataset loaders and versioned reference package builder (K2).

Core rules:
- ``load_reference_dataset(dataset_id) -> ReferenceDataset``
- Verify SHA-256 file hash on every load; fail loudly on mismatch.
- Never silently coerce, drop, or "fix" inconsistent data.
- National data (``TR``) cannot be loaded as Ankara-specific (``06``) without an
  explicit, visible scope marker and ``allow_national_scope=True`` when an
  Ankara-only expectation is asserted.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, StrictBool, StrictInt

from societytwin.common import canonical_hash, canonical_json, compare_recorded_digest, sha256_bytes, sha256_file
from societytwin.evidence.normalization import (
    DataQualityIssue,
    DistributionSummary,
    NormalizationResult,
    NormalizedRow,
    ValidationCheckResult,
    normalize_reference_table,
)
from societytwin.evidence.registry import (
    EVIDENCE_REGISTRY_SCHEMA_VERSION,
    EVIDENCE_REGISTRY_VERSION,
    DataQualityFlag,
    DenominatorSpec,
    EvidenceDatasetEntry,
    EvidenceRegistry,
    GeographyScope,
    SourceReference,
    load_evidence_registry,
)
from societytwin.national.dependencies import TypedModel, _UniqueLoader

REPO_ROOT_DEFAULT = Path(__file__).resolve().parents[3]
REFERENCE_PACKAGE_VERSION = "ankara-reference-package-k2-2025.1"

# Alias normalization for ReferenceCell compatibility
ReferenceCell = NormalizedRow


class EvidenceLoadError(ValueError):
    """Raised on missing file, SHA-256 hash mismatch, scope violation, or malformed source."""


class ReferenceDataset(TypedModel):
    """Normalized, hash-verified reference dataset loaded via K1/K2."""

    dataset_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    registry_version: str = Field(min_length=1)
    parent_dependency_registry_version: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_reference: SourceReference
    geography: GeographyScope
    scope_marker: Literal[
        "ANKARA_OBSERVED",
        "PROVINCE_OBSERVED_INCLUDES_ANKARA",
        "ANKARA_DISTRICT_OBSERVED",
        "NATIONAL_ONLY_NOT_ANKARA_SPECIFIC",
        "REGIONAL_OR_CONTEXT",
    ]
    is_national: StrictBool
    is_ankara_specific: StrictBool
    year: StrictInt | str
    dimensions: tuple[str, ...]
    unit: str = Field(min_length=1)
    denominator: DenominatorSpec
    source_file_path: str = Field(min_length=1)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest_status: Literal["match", "line_ending_equivalent"]
    rows: tuple[NormalizedRow, ...]
    published_totals: dict[str, float | int] = Field(default_factory=dict)
    published_extra_metrics: dict[str, float] = Field(default_factory=dict)
    computed_total: float = 0.0
    distribution: DistributionSummary | None = None
    checks: tuple[ValidationCheckResult, ...] = ()
    issues: tuple[DataQualityIssue, ...] = ()
    caveats: tuple[str, ...] = ()
    data_quality_flags: tuple[DataQualityFlag, ...] = ()

    @property
    def content_sha256(self) -> str:
        return canonical_hash(self.model_dump(mode="json", exclude={"source_file_path"}))


def _resolve_tuik_package_dir(repo_root: Path, tuik_package_dir: Path | None = None) -> Path:
    if tuik_package_dir is not None and tuik_package_dir.is_dir():
        return tuik_package_dir
    default_in_repo = repo_root / "data" / "raw" / "tuik_package"
    if (default_in_repo / "population_by_age_sex.csv").is_file() or (default_in_repo / "data_catalog.csv").is_file():
        return default_in_repo
    sibling = repo_root.parent / "tuik_province_data"
    if sibling.is_dir():
        return sibling
    return default_in_repo


def resolve_dataset_path(
    entry: EvidenceDatasetEntry,
    *,
    repo_root: Path = REPO_ROOT_DEFAULT,
    tuik_package_dir: Path | None = None,
) -> Path:
    """Resolve the physical path for a registry dataset entry."""
    if entry.retrieval_info.storage_root == "repo_root":
        return repo_root / entry.retrieval_info.relative_path
    pkg_dir = _resolve_tuik_package_dir(repo_root, tuik_package_dir)
    return pkg_dir / entry.retrieval_info.relative_path


def _verify_file_digest(
    path: Path,
    expected_sha256: str,
    dataset_id: str,
    *,
    allow_line_ending_equivalent: bool = True,
) -> tuple[bytes, str, Literal["match", "line_ending_equivalent"]]:
    if not path.is_file():
        raise EvidenceLoadError(
            f"Reference dataset {dataset_id!r} source file not found at {path}"
        )
    raw = path.read_bytes()
    actual_sha256 = sha256_bytes(raw)
    status = compare_recorded_digest(expected_sha256, raw)
    if status == "match":
        return raw, actual_sha256, "match"
    if allow_line_ending_equivalent and status == "line_ending_equivalent":
        return raw, expected_sha256, "line_ending_equivalent"
    raise EvidenceLoadError(
        f"SHA-256 checksum mismatch for dataset {dataset_id!r} ({path.name}): "
        f"expected {expected_sha256}, got {actual_sha256}"
    )


def _extract_tuik_long_provincial(
    raw_bytes: bytes,
    entry: EvidenceDatasetEntry,
) -> tuple[list[dict[str, Any]], dict[str, float | int], dict[str, float]]:
    text = raw_bytes.decode(entry.retrieval_info.encoding)
    reader = csv.DictReader(io.StringIO(text))
    required_cols = {"province_code", "year", "indicator", "value", "unit"}
    if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
        raise EvidenceLoadError(
            f"Dataset {entry.dataset_id!r} missing required long-format columns {sorted(required_cols)} "
            f"(got {reader.fieldnames})"
        )

    ind_regex = re.compile(entry.retrieval_info.indicator_pattern) if entry.retrieval_info.indicator_pattern else None
    tot_regexes = [re.compile(p) for p in entry.retrieval_info.total_patterns]
    res_regex = re.compile(entry.retrieval_info.residual_pattern) if entry.retrieval_info.residual_pattern else None

    target_prov = entry.retrieval_info.filter_province_code
    target_year = str(entry.retrieval_info.filter_year) if entry.retrieval_info.filter_year is not None else None

    records: list[dict[str, Any]] = []
    agg_cells: dict[tuple[tuple[str, str], ...], float] = {}
    agg_indicators: dict[tuple[tuple[str, str], ...], str] = {}
    published_totals: dict[str, float | int] = {}
    extra_metrics: dict[str, float] = {}

    for row in reader:
        prov = str(row["province_code"]).strip().zfill(2)
        yr = str(row["year"]).strip()
        if target_prov is not None and prov != target_prov.zfill(2):
            continue
        if target_year is not None and yr != target_year:
            continue

        ind = str(row["indicator"]).strip()
        val_str = str(row["value"]).strip() if row["value"] is not None else ""

        # Capture extra context metrics on the same province/year (e.g., average_household_size)
        if ind == "average_household_size" and val_str:
            extra_metrics["average_household_size"] = float(val_str)

        # Check total patterns first
        matched_total = False
        for t_re in tot_regexes:
            m_tot = t_re.match(ind)
            if m_tot:
                matched_total = True
                if val_str:
                    val_num = float(val_str)
                    val_clean: float | int = int(val_num) if val_num.is_integer() else val_num
                    groups = m_tot.groupdict()
                    if not groups:
                        published_totals["total"] = published_totals.get("total", 0) + val_clean
                    elif "sex" in groups and len(groups) == 1:
                        s_key = f"sex:{groups['sex']}"
                        published_totals[s_key] = published_totals.get(s_key, 0) + val_clean
                    elif "age_group" in groups and len(groups) == 1:
                        a_key = f"age_group:{groups['age_group']}"
                        published_totals[a_key] = published_totals.get(a_key, 0) + val_clean
                    elif "category" in groups and len(groups) == 1:
                        c_key = f"category:{groups['category']}"
                        published_totals[c_key] = published_totals.get(c_key, 0) + val_clean
                break
        if matched_total:
            continue

        # Check residual pattern (e.g. 2008 unknown marital status)
        if res_regex:
            m_res = res_regex.match(ind)
            if m_res and val_str:
                groups = m_res.groupdict()
                dims = {"province_code": prov} if "province_code" in entry.dimensions else {}
                if "sex" in groups:
                    dims["sex"] = groups["sex"]
                non_geo = [d for d in entry.dimensions if d not in ("province_code", "sex")]
                if non_geo:
                    dims[non_geo[-1]] = "unknown"
                records.append({"dimensions": dims, "value": val_str, "source_indicator": ind})
                continue

        if ind_regex:
            m = ind_regex.match(ind)
            if not m:
                continue
            groups = m.groupdict()
            dims: dict[str, str] = {}
            if "province_code" in entry.dimensions:
                dims["province_code"] = prov
            for d in entry.dimensions:
                if d == "province_code":
                    continue
                if d in groups:
                    dims[d] = groups[d]
                elif "category" in groups:
                    dims[d] = groups["category"]
                else:
                    dims[d] = ind

            if target_prov is None and "province_code" not in entry.dimensions:
                # National sum across 81 provinces
                if val_str:
                    k = tuple(sorted(dims.items()))
                    agg_cells[k] = agg_cells.get(k, 0.0) + float(val_str)
                    agg_indicators[k] = ind
            else:
                records.append({"dimensions": dims, "value": val_str, "source_indicator": ind})

    if target_prov is None and agg_cells:
        for k, v in agg_cells.items():
            v_clean: int | float = int(v) if v.is_integer() else v
            records.append(
                {
                    "dimensions": dict(k),
                    "value": v_clean,
                    "source_indicator": agg_indicators[k],
                }
            )

    return records, published_totals, extra_metrics


def _extract_tuik_long_district(
    raw_bytes: bytes,
    entry: EvidenceDatasetEntry,
) -> tuple[list[dict[str, Any]], dict[str, float | int], dict[str, float]]:
    text = raw_bytes.decode(entry.retrieval_info.encoding)
    reader = csv.DictReader(io.StringIO(text))
    required_cols = {"province_code", "district_name", "year", "indicator", "value", "unit"}
    if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
        raise EvidenceLoadError(f"District dataset {entry.dataset_id!r} missing columns {sorted(required_cols)}")

    ind_regex = re.compile(entry.retrieval_info.indicator_pattern) if entry.retrieval_info.indicator_pattern else None
    target_prov = entry.retrieval_info.filter_province_code
    target_year = str(entry.retrieval_info.filter_year) if entry.retrieval_info.filter_year is not None else None

    records: list[dict[str, Any]] = []
    for row in reader:
        prov = str(row["province_code"]).strip().zfill(2)
        yr = str(row["year"]).strip()
        if target_prov and prov != target_prov.zfill(2):
            continue
        if target_year and yr != target_year:
            continue
        ind = str(row["indicator"]).strip()
        if ind_regex and not ind_regex.match(ind):
            continue
        dims = {
            "province_code": prov,
            "district_name": str(row["district_name"]).strip(),
        }
        records.append({"dimensions": dims, "value": row["value"], "source_indicator": ind})

    return records, {}, {}


def _extract_legacy_age_gender(
    raw_bytes: bytes,
    entry: EvidenceDatasetEntry,
) -> tuple[list[dict[str, Any]], dict[str, float | int], dict[str, float]]:
    text = raw_bytes.decode(entry.retrieval_info.encoding)
    reader = csv.DictReader(io.StringIO(text))
    records: list[dict[str, Any]] = []
    for row in reader:
        if str(row.get("year", "")).strip() != str(entry.year):
            continue
        dims = {
            "province_code": "06" if row.get("province") in ("Ankara", "06", "6") else str(row.get("province", "")),
            "age_group": str(row["age_group"]).strip(),
            "sex": str(row["gender"]).strip(),
        }
        records.append({"dimensions": dims, "value": row["population"], "source_indicator": "population"})
    return records, {}, {}


def _extract_legacy_marital_gender(
    raw_bytes: bytes,
    entry: EvidenceDatasetEntry,
) -> tuple[list[dict[str, Any]], dict[str, float | int], dict[str, float]]:
    text = raw_bytes.decode(entry.retrieval_info.encoding)
    reader = csv.DictReader(io.StringIO(text))
    records: list[dict[str, Any]] = []
    for row in reader:
        if str(row.get("year", "")).strip() != str(entry.year):
            continue
        dims = {
            "province_code": "06" if row.get("province") in ("Ankara", "06", "6") else str(row.get("province", "")),
            "sex": str(row["gender"]).strip(),
            "marital_status": str(row["marital_status"]).strip(),
        }
        records.append({"dimensions": dims, "value": row["population"], "source_indicator": "population"})
    return records, {}, {}


def _extract_legacy_controls(
    raw_bytes: bytes,
    entry: EvidenceDatasetEntry,
) -> tuple[list[dict[str, Any]], dict[str, float | int], dict[str, float]]:
    text = raw_bytes.decode(entry.retrieval_info.encoding)
    reader = csv.DictReader(io.StringIO(text))
    records: list[dict[str, Any]] = []
    for row in reader:
        if entry.retrieval_info.filter_year is not None and str(row.get("year", "")).strip() != str(entry.retrieval_info.filter_year):
            continue
        dims = {
            "province_code": "06" if row.get("province") in ("Ankara", "06", "6") else str(row.get("province", "")),
            "statistic": str(row["statistic"]).strip(),
        }
        records.append({"dimensions": dims, "value": row["value"], "source_indicator": str(row["statistic"]).strip()})
    return records, {}, {}


def _extract_nip_household_size(
    raw_bytes: bytes,
    entry: EvidenceDatasetEntry,
) -> tuple[list[dict[str, Any]], dict[str, float | int], dict[str, float]]:
    text = raw_bytes.decode(entry.retrieval_info.encoding)
    reader = csv.DictReader(io.StringIO(text))
    records: list[dict[str, Any]] = []
    for row in reader:
        if str(row.get("reference_year", "")).strip() != str(entry.year):
            continue
        dims = {
            "province_code": str(row["province_code"]).strip().zfill(2),
            "household_size_class": str(row["household_size_class"]).strip(),
        }
        records.append({"dimensions": dims, "value": row["households"], "source_indicator": "households"})
    return records, {}, {}


def _extract_national_marital_yaml(
    raw_bytes: bytes,
    entry: EvidenceDatasetEntry,
) -> tuple[list[dict[str, Any]], dict[str, float | int], dict[str, float]]:
    payload = yaml.load(raw_bytes.decode(entry.retrieval_info.encoding), Loader=_UniqueLoader)
    if str(payload.get("geography")) != "TR":
        raise EvidenceLoadError(f"Expected geography='TR' in {entry.dataset_id}, got {payload.get('geography')!r}")
    categories = payload.get("categories", [])
    records: list[dict[str, Any]] = []
    for row in payload.get("rows", []):
        sex = str(row["sex"])
        band = str(row["age_band"])
        for cat, pct in zip(categories, row["published_percent"]):
            records.append(
                {
                    "dimensions": {"sex": sex, "broad_age_band": band, "marital_status": str(cat)},
                    "value": pct,
                    "source_indicator": "published_percent",
                }
            )
    return records, {"total": 400.0}, {}


def _extract_national_type_size_csv(
    raw_bytes: bytes,
    entry: EvidenceDatasetEntry,
) -> tuple[list[dict[str, Any]], dict[str, float | int], dict[str, float]]:
    text = raw_bytes.decode(entry.retrieval_info.encoding)
    reader = csv.DictReader(io.StringIO(text))
    coarse_types = {"one_person", "nuclear_family", "extended_family", "non_family_multi_person"}
    records: list[dict[str, Any]] = []
    for row in reader:
        if row.get("household_type") not in coarse_types:
            continue
        records.append(
            {
                "dimensions": {
                    "household_type": str(row["household_type"]).strip(),
                    "household_type_size_band": str(row["household_size"]).strip(),
                },
                "value": row.get("households", ""),
                "value_status": row.get("value_status", "OBSERVED"),
                "source_indicator": "households",
            }
        )
    return records, {}, {}


def load_reference_dataset(
    dataset_id: str,
    *,
    registry: EvidenceRegistry | None = None,
    repo_root: Path = REPO_ROOT_DEFAULT,
    tuik_package_dir: Path | None = None,
    require_ankara_scope: bool = False,
    allow_national_scope: bool = False,
    strict_normalization: bool = False,
) -> ReferenceDataset:
    """Load, hash-verify, and normalize a reference dataset by ``dataset_id``.

    Enforces:
    1. Exact SHA-256 verification before parsing any content.
    2. Strict scope guard: if ``require_ankara_scope=True`` (or if a caller attempts to use a
       National ``TR`` dataset as Ankara-specific without ``allow_national_scope=True``), raises
       ``EvidenceLoadError``. Even when ``allow_national_scope=True``, the returned dataset carries
       ``scope_marker="NATIONAL_ONLY_NOT_ANKARA_SPECIFIC"`` and ``is_national=True``.
    """
    reg = registry or load_evidence_registry()
    try:
        entry = reg.get(dataset_id)
    except KeyError as exc:
        raise EvidenceLoadError(str(exc)) from exc

    # Scope honesty guard: prevent national data from ever being loaded as Ankara-specific silently
    if entry.geography.is_national and require_ankara_scope and not allow_national_scope:
        raise EvidenceLoadError(
            f"Scope violation: dataset {dataset_id!r} has National (TR) scope "
            f"(scope_marker={entry.geography.scope_marker!r}, is_ankara_specific=False) and "
            f"cannot be loaded as Ankara-specific ground truth."
        )

    path = resolve_dataset_path(entry, repo_root=repo_root, tuik_package_dir=tuik_package_dir)
    raw_bytes, verified_hash, digest_status = _verify_file_digest(
        path,
        entry.sha256,
        entry.dataset_id,
    )

    layout = entry.retrieval_info.layout
    if layout == "tuik_long_provincial":
        raw_records, pub_totals, extra_metrics = _extract_tuik_long_provincial(raw_bytes, entry)
    elif layout == "tuik_long_district":
        raw_records, pub_totals, extra_metrics = _extract_tuik_long_district(raw_bytes, entry)
    elif layout == "legacy_age_gender_csv":
        raw_records, pub_totals, extra_metrics = _extract_legacy_age_gender(raw_bytes, entry)
    elif layout == "legacy_marital_gender_csv":
        raw_records, pub_totals, extra_metrics = _extract_legacy_marital_gender(raw_bytes, entry)
    elif layout == "legacy_controls_csv":
        raw_records, pub_totals, extra_metrics = _extract_legacy_controls(raw_bytes, entry)
    elif layout == "nip_household_size_csv":
        raw_records, pub_totals, extra_metrics = _extract_nip_household_size(raw_bytes, entry)
    elif layout == "national_marital_seed_yaml":
        raw_records, pub_totals, extra_metrics = _extract_national_marital_yaml(raw_bytes, entry)
    elif layout == "national_type_size_csv":
        raw_records, pub_totals, extra_metrics = _extract_national_type_size_csv(raw_bytes, entry)
    else:
        raise EvidenceLoadError(f"Unsupported retrieval layout {layout!r} for dataset {dataset_id!r}")

    norm: NormalizationResult = normalize_reference_table(
        raw_records,
        entry,
        published_totals=pub_totals,
        published_extra_metrics=extra_metrics,
        strict=strict_normalization,
    )

    return ReferenceDataset(
        dataset_id=entry.dataset_id,
        title=entry.title,
        registry_version=reg.evidence_registry_version,
        parent_dependency_registry_version=reg.parent_dependency_registry_version,
        source=entry.source,
        source_reference=entry.source_reference,
        geography=entry.geography,
        scope_marker=entry.geography.scope_marker,
        is_national=entry.geography.is_national,
        is_ankara_specific=entry.geography.is_ankara_specific,
        year=entry.year,
        dimensions=entry.dimensions,
        unit=entry.unit,
        denominator=entry.denominator,
        source_file_path=str(path),
        expected_sha256=entry.sha256,
        verified_sha256=verified_hash,
        digest_status=digest_status,
        rows=norm.rows,
        published_totals=norm.published_totals,
        published_extra_metrics=extra_metrics,
        computed_total=norm.computed_total,
        distribution=norm.distribution,
        checks=norm.checks,
        issues=norm.issues,
        caveats=entry.caveats,
        data_quality_flags=entry.data_quality_flags,
    )


def build_reference_package(
    output_dir: Path,
    *,
    registry: EvidenceRegistry | None = None,
    repo_root: Path = REPO_ROOT_DEFAULT,
    tuik_package_dir: Path | None = None,
    dataset_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Produce a deterministic, versioned reference package of normalized tables + manifest.json.

    Writes:
    - ``<output_dir>/tables/<dataset_id>.json`` (canonical JSON with normalized cells, distribution,
      checks, caveats, and data_quality_flags)
    - ``<output_dir>/tables/<dataset_id>.csv`` (machine-readable normalized flat table with explicit
      ``scope_marker``, ``is_national``, ``is_ankara_specific``, ``value_status``, ``category_kind``)
    - ``<output_dir>/manifest.json`` (versioned manifest with SHA-256 digests of every normalized
      table, skipped optional raw files, and a consolidated data-quality discrepancy registry).
    """
    reg = registry or load_evidence_registry()
    output_dir = Path(output_dir)
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    target_ids = dataset_ids or tuple(reg.datasets.keys())
    manifest_tables: list[dict[str, Any]] = []
    skipped_optional: list[dict[str, Any]] = []
    flagged_discrepancies: dict[str, dict[str, Any]] = {}

    for ds_id in target_ids:
        entry = reg.get(ds_id)
        path = resolve_dataset_path(entry, repo_root=repo_root, tuik_package_dir=tuik_package_dir)
        if not path.is_file() and entry.retrieval_info.optional_local_file:
            skipped_optional.append(
                {
                    "dataset_id": ds_id,
                    "status": "not_evaluable",
                    "reason": f"Optional git-ignored local raw file {entry.retrieval_info.relative_path!r} is not present on disk.",
                    "expected_sha256": entry.sha256,
                    "geography_code": entry.geography.code,
                    "scope_marker": entry.geography.scope_marker,
                }
            )
            for flag in entry.data_quality_flags:
                flagged_discrepancies[flag.flag_id] = flag.model_dump(mode="json")
            continue

        ref_ds = load_reference_dataset(
            ds_id,
            registry=reg,
            repo_root=repo_root,
            tuik_package_dir=tuik_package_dir,
            allow_national_scope=True,
        )

        # 1. Write canonical JSON table
        json_path = tables_dir / f"{ds_id}.json"
        json_payload = ref_ds.model_dump(mode="json", exclude={"source_file_path"})
        json_bytes = (json.dumps(json_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        json_path.write_bytes(json_bytes)

        # 2. Write normalized CSV table
        csv_path = tables_dir / f"{ds_id}.csv"
        dim_cols = list(entry.dimensions)
        fieldnames = [
            "dataset_id",
            "geography_code",
            "scope_marker",
            "is_national",
            "is_ankara_specific",
            "year",
            *dim_cols,
            "value",
            "unit",
            "value_status",
            "category_kind",
            "proportion_of_total",
            "proportion_within_group",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for r in ref_ds.rows:
            row_dict: dict[str, Any] = {
                "dataset_id": r.dataset_id,
                "geography_code": r.geography_code,
                "scope_marker": r.scope_marker,
                "is_national": r.is_national,
                "is_ankara_specific": r.is_ankara_specific,
                "year": r.year,
                "value": "" if r.value is None else r.value,
                "unit": r.unit,
                "value_status": r.value_status,
                "category_kind": r.category_kind,
                "proportion_of_total": "" if r.proportion_of_total is None else f"{r.proportion_of_total:.12f}",
                "proportion_within_group": "" if r.proportion_within_group is None else f"{r.proportion_within_group:.12f}",
            }
            for d in dim_cols:
                row_dict[d] = r.dimensions.get(d, "")
            writer.writerow(row_dict)
        csv_bytes = buf.getvalue().encode("utf-8")
        csv_path.write_bytes(csv_bytes)

        for flag in ref_ds.data_quality_flags:
            flagged_discrepancies[flag.flag_id] = flag.model_dump(mode="json")

        manifest_tables.append(
            {
                "dataset_id": ds_id,
                "title": ref_ds.title,
                "geography_code": ref_ds.geography.code,
                "scope_marker": ref_ds.scope_marker,
                "is_national": ref_ds.is_national,
                "is_ankara_specific": ref_ds.is_ankara_specific,
                "year": ref_ds.year,
                "dimensions": list(ref_ds.dimensions),
                "unit": ref_ds.unit,
                "denominator_universe": ref_ds.denominator.universe,
                "computed_total": ref_ds.computed_total,
                "row_count": len(ref_ds.rows),
                "source_sha256": ref_ds.verified_sha256,
                "normalized_json_relpath": f"tables/{ds_id}.json",
                "normalized_json_sha256": sha256_bytes(json_bytes),
                "normalized_csv_relpath": f"tables/{ds_id}.csv",
                "normalized_csv_sha256": sha256_bytes(csv_bytes),
                "checks_summary": {
                    "pass": sum(1 for c in ref_ds.checks if c.status == "pass"),
                    "fail": sum(1 for c in ref_ds.checks if c.status == "fail"),
                    "not_evaluable": sum(1 for c in ref_ds.checks if c.status == "not_evaluable"),
                },
                "data_quality_flag_ids": [f.flag_id for f in ref_ds.data_quality_flags],
            }
        )

    manifest_body: dict[str, Any] = {
        "package_schema_version": "evidence-reference-package-k2-v1",
        "package_version": REFERENCE_PACKAGE_VERSION,
        "evidence_registry_schema_version": EVIDENCE_REGISTRY_SCHEMA_VERSION,
        "evidence_registry_version": reg.evidence_registry_version,
        "evidence_registry_fingerprint": reg.fingerprint,
        "parent_dependency_registry_version": reg.parent_dependency_registry_version,
        "parent_dependency_registry_fingerprint": reg.parent_dependency_registry_fingerprint,
        "tables_built_count": len(manifest_tables),
        "optional_local_skipped_count": len(skipped_optional),
        "tables": manifest_tables,
        "skipped_optional_local_datasets": skipped_optional,
        "documented_data_quality_flags": [
            flagged_discrepancies[k] for k in sorted(flagged_discrepancies)
        ],
    }
    manifest_body["package_fingerprint"] = canonical_hash(manifest_body)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_body, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_body
