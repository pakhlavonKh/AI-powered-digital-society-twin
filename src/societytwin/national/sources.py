"""Source adapters that normalise official tables into the standard control store.

Two adapters exist:

* ``legacy_ankara``: the processed TÜİK extracts that the historical MatrAIx experiment ships
  (Ankara, 2025 age × sex, 2025 marital status × sex, provincial context). Read-only; the experiment
  files are never modified.
* ``tuik_package``: the team's long-format TÜİK package, read from ``data/raw/tuik_package/`` when present:
  ``<dataset>.csv`` files (``province_code, province_name, nuts3_code, year, indicator, value, unit``), their
  ``<dataset>_wide.csv`` twins (verified cell by cell against the long file, never imported, so nothing is
  counted twice), ``data_catalog.csv``, ``variable_metadata.csv``, ``coverage_report.csv``,
  ``not_province_level.csv`` and the README (whose counts are re-checked, not trusted). Every long-format row is
  accounted for: it becomes a control cell (through an explicit rule in ``data/tuik_package_mapping.yaml``),
  a province context observation with its published reference period (``2025`` or ``2021-2023``) and
  observation type (official projections are never current observations), or a rejected row with a reason.

``build_controls`` merges both into one store (package first; the legacy extract corroborates it). Conflicting
duplicate cells are an error, not a choice.
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from societytwin.common import sha256_bytes, sha256_file, utc_now
from societytwin.national import geography as geo
from societytwin.national.controls import (TABLE_KINDS, ContextRow, ControlRow, ControlsError, ControlStore, TableMeta, parse_period,
                                          validate_row)
from societytwin.national.vocab import AGE_GROUPS, MARITAL, SEX, VOCABULARIES, ValueStatus, band_bounds, label_key

BUILDER_VERSION = "controls-builder-2.0"
PACKAGE_METADATA_FILES = ("data_catalog.csv", "variable_metadata.csv", "coverage_report.csv", "not_province_level.csv")
WIDE_SUFFIX = "_wide"  # <dataset>_wide.csv: the same values, one column per indicator (verified, never imported)
DEFAULT_MARKERS = {
    ValueStatus.NOT_REPORTED: ["", "-", "–", "..", "...", "na", "n/a", "nan"],
    ValueStatus.UNKNOWN: ["?", "unknown", "bilinmiyor", "bilinmeyen"],
    ValueStatus.NOT_APPLICABLE: ["not applicable", "uygulanamaz"],
}
THEME_DOMAINS = {  # package theme keywords -> environment domain
    "population": "demographics", "vital": "demographics", "nüfus": "demographics",
    "household": "households", "family": "households", "hanehalkı": "households",
    "education": "education", "eğitim": "education",
    "labour": "economy", "labor": "economy", "income": "economy", "economy": "economy", "gdp": "economy", "işgücü": "economy",
    "housing": "housing", "construction": "housing", "konut": "housing",
    "migration": "migration", "göç": "migration",
    "mobility": "mobility", "transport": "mobility", "tech": "mobility", "lifestyle": "mobility", "ulaştırma": "mobility",
    "health": "health", "sağlık": "health",
    "agriculture": "environment", "environment": "environment", "justice": "justice", "tarım": "environment",
}


@dataclass
class AdapterResult:
    name: str
    status: str                        # loaded | absent | failed
    tables: dict[str, TableMeta] = field(default_factory=dict)
    rows: list[ControlRow] = field(default_factory=list)
    context: list[ContextRow] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    inputs: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detail: str = ""
    datasets: list[dict] = field(default_factory=list)
    audit: dict | None = None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def _input(path: Path, root: Path, role: str) -> dict:
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.name
    return {"path": rel, "role": role, "sha256": sha256_file(path), "bytes": path.stat().st_size}


# ================================================================ legacy Ankara extracts
def legacy_ankara(experiment_root: Path, layout, repo_root: Path) -> AdapterResult:
    result = AdapterResult("legacy_ankara_extracts", "absent")
    age_path = experiment_root / layout.age_gender
    marital_path = experiment_root / layout.marital_gender
    controls_path = experiment_root / layout.controls
    if not age_path.is_file():
        result.detail = f"{layout.age_gender} is not present"
        return result
    try:
        _legacy_age_sex(age_path, result, repo_root)
        if marital_path.is_file():
            _legacy_marital(marital_path, result, repo_root)
        if controls_path.is_file():
            _legacy_context(controls_path, result, repo_root)
    except (ValueError, KeyError, geo.UnknownProvince) as exc:
        return AdapterResult("legacy_ankara_extracts", "failed", detail=str(exc))
    result.status = "loaded"
    return result


def _legacy_source(source_id: str, title: str, dataset_ref: str, path: Path, repo_root: Path, years, variables,
                   transformations: list[str], extra_limitations: list[str]) -> dict:
    return {
        "source_id": source_id, "publisher": "TÜİK (Turkish Statistical Institute)", "title_en": title, "title_tr": None,
        "dataset_identifier": dataset_ref, "url": None, "publication_date": None, "retrieval_date": None,
        "reference_years": sorted(set(years)), "geographic_level": "province", "province_coverage": ["06"],
        "variables": variables, "units": ["persons"], "processed_file": _input(path, repo_root, "processed_extract"),
        "raw_file_checksum": None, "transformations": transformations,
        "limitations": ["The original TÜİK download is not in this checkout; attribution is as recorded by the project's "
                        "processing code, so raw-source verification is unavailable.",
                        "URL, publication date and retrieval date were not recorded.",
                        "Reuse terms for TÜİK portal tables are an OPEN DECISION (docs/data-strategy.md).", *extra_limitations],
        "status": "used",
    }


def _legacy_age_sex(path: Path, result: AdapterResult, repo_root: Path) -> None:
    rows = _read_csv(path)
    if not rows or set(rows[0]) < {"year", "province", "age_group", "gender", "population"}:
        raise ValueError(f"{path.name}: unexpected columns")
    years = set()
    for rec in rows:
        p = geo.resolve(rec["province"])
        if rec["age_group"] not in AGE_GROUPS:
            raise ValueError(f"{path.name}: unknown age group {rec['age_group']!r}")
        years.add(int(rec["year"]))
        result.rows.append(ControlRow("population_age_sex", "province", p.code, int(rec["year"]), SEX.from_source(rec["gender"]),
                                      rec["age_group"], "", float(int(rec["population"])), ValueStatus.OBSERVED,
                                      "legacy:tuik_t16_age_sex", f"{path.name}"))
    result.tables["population_age_sex"] = TableMeta(
        "population_age_sex", "population_age_sex", "Resident population by age group and sex", universe_min_age=0,
        universe_note="All registered residents (ADNKS)", source_ids=["legacy:tuik_t16_age_sex"],
        transformations=["Processed extract read verbatim; sex labels mapped to codes; one row per province × age group × sex."])
    result.sources.append(_legacy_source(
        "legacy:tuik_t16_age_sex", "ADNKS population by province, five-year age group and sex",
        "T16 (identifier as named in the project's processing code)", path, repo_root, years, ["age_group", "sex", "population"],
        ["Extracted from the raw TÜİK file by experiments/matraix_simulation/src/data_processing/process_tuik_demographics.py",
         "Normalised into standard control rows by societytwin.national.sources.legacy_ankara"], ["Ankara only."]))
    result.inputs.append(_input(path, repo_root, "legacy_extract"))


def _legacy_marital(path: Path, result: AdapterResult, repo_root: Path) -> None:
    rows = _read_csv(path)
    if not rows or set(rows[0]) < {"year", "province", "gender", "marital_status", "population"}:
        raise ValueError(f"{path.name}: unexpected columns")
    years, totals = set(), {}
    for rec in rows:
        p = geo.resolve(rec["province"])
        year = int(rec["year"])
        years.add(year)
        sex = SEX.from_source(rec["gender"])
        value = float(int(rec["population"]))
        totals[(p.code, year, sex)] = totals.get((p.code, year, sex), 0.0) + value
        result.rows.append(ControlRow("marital_status_sex", "province", p.code, year, sex, "", MARITAL.from_source(rec["marital_status"]),
                                      value, ValueStatus.OBSERVED, "legacy:tuik_t10_marital_sex", path.name))
    checks = []
    for (code, year, sex), total in sorted(totals.items()):
        aged = sum(r.value for r in result.rows if r.table_id == "population_age_sex" and r.geo_code == code and r.year == year
                   and r.sex == sex and band_bounds(r.age_group)[0] >= 15)
        checks.append({"name": "universe_is_population_15_plus", "geo_code": code, "year": year, "sex": sex,
                       "marital_total": total, "population_15_plus": aged, "passed": aged == total,
                       "detail": "Sum over marital categories equals the population aged 15+ of the age × sex table."})
    meta = TableMeta(
        "marital_status_sex", "marital_status_sex", "Population aged 15+ by marital status and sex", universe_min_age=15,
        universe_note="Residents aged 15 and over (TÜİK marital-status statistics universe)",
        source_ids=["legacy:tuik_t10_marital_sex"], checks=checks,
        transformations=["Processed extract read verbatim; TÜİK labels mapped to codes (Hiç evlenmedi → never_married, "
                         "Evli → married, Boşandı → divorced, Eşi öldü → widowed)."],
        limitations=["Marital status is published here by sex only: the joint distribution with age is not observed."])
    if not all(c["passed"] for c in checks):
        meta.limitations.append("The marital total differs from the 15+ population of the age × sex table; see checks.")
    result.tables["marital_status_sex"] = meta
    result.sources.append(_legacy_source(
        "legacy:tuik_t10_marital_sex", "Population aged 15+ by province, marital status and sex",
        "T10 (identifier as named in the project's processing code)", path, repo_root, years,
        ["sex", "marital_status", "population"],
        ["Extracted by experiments/matraix_simulation/src/data_processing/process_tuik_marital.py",
         "Normalised into standard control rows by societytwin.national.sources.legacy_ankara"],
        ["Ankara only.", "No age breakdown."]))
    result.inputs.append(_input(path, repo_root, "legacy_extract"))


LEGACY_CONTEXT = {
    "total_population": ("demographics", "Total population", "Toplam nüfus"),
    "female_population": ("demographics", "Female population", "Kadın nüfus"),
    "male_population": ("demographics", "Male population", "Erkek nüfus"),
    "population_density": ("urbanization", "Population density", "Nüfus yoğunluğu"),
    "total_median_age": ("demographics", "Median age (total)", "Ortanca yaş"),
    "female_median_age": ("demographics", "Median age (female)", "Ortanca yaş (kadın)"),
    "male_median_age": ("demographics", "Median age (male)", "Ortanca yaş (erkek)"),
}


def _legacy_context(path: Path, result: AdapterResult, repo_root: Path) -> None:
    rows = _read_csv(path)
    seen: dict[tuple[str, str, int], ContextRow] = {}
    workbooks, years = set(), set()
    for rec in rows:
        if rec["statistic"] not in LEGACY_CONTEXT:
            result.warnings.append(f"{path.name}: statistic {rec['statistic']!r} has no context mapping and was not loaded")
            continue
        p = geo.resolve(rec["province"])
        theme, en, tr = LEGACY_CONTEXT[rec["statistic"]]
        year = int(rec["year"])
        ref = f"{rec['source_workbook']} / sheet {rec['source_sheet']} / row {rec['source_row']}"
        workbooks.add(rec["source_workbook"])
        years.add(year)
        key = (rec["statistic"], p.code, year)
        row = ContextRow(rec["statistic"], theme, en, tr, "province", p.code, year, float(rec["value"]), ValueStatus.OBSERVED,
                         rec["unit"], "legacy:tuik_province_workbooks", ref)
        if key in seen:
            if seen[key].value != row.value:
                raise ValueError(f"{path.name}: conflicting values for {key}")
            seen[key] = replace(seen[key], source_ref=f"{seen[key].source_ref} ; {ref}")
            continue
        seen[key] = row
    result.context.extend(seen.values())
    src = _legacy_source("legacy:tuik_province_workbooks", "TÜİK provincial workbooks: population, density and median age",
                         "; ".join(sorted(workbooks)), path, repo_root, years, sorted(LEGACY_CONTEXT),
                         ["Extracted by experiments/matraix_simulation/src/data_processing/process_tuik_controls.py "
                          "(workbook, sheet and row recorded per observation)",
                          "Agreeing duplicate observations merged; every workbook reference kept"], ["Ankara only."])
    src["units"] = sorted({c.unit for c in seen.values()})
    result.sources.append(src)
    result.inputs.append(_input(path, repo_root, "legacy_extract"))


# ================================================================ long-format TÜİK package
# Column names accepted for each field. The first group of each tuple is the team package's actual header
# (data_catalog.csv: file_name, dataset_title_en, source_url, reference_year(s), …; variable_metadata.csv:
# file_name, indicator, original_name_tr, description_en, unit, source_table_or_flow).
_ALIASES = {
    "province_code": ("province_code", "il_kodu", "plate_code"),
    "province_name": ("province_name", "il", "il_adi", "province"),
    "nuts3_code": ("nuts3_code", "nuts3", "ibbs3", "ibbs_duzey3"),
    "year": ("year", "yil", "period", "reference_period"),
    "indicator": ("indicator", "gosterge", "variable"),
    "value": ("value", "deger"),
    "unit": ("unit", "birim"),
    "dataset": ("dataset_id", "dataset", "veri_seti", "table_id"),
}
_CATALOG_ALIASES = {
    "dataset": ("file_name", "dataset_id", "dataset", "id", "table_id", "file"),
    "wide_file": ("wide_file_name", "wide_file"),
    "theme": ("theme", "tema", "category"),
    "title_en": ("dataset_title_en", "title_en", "english_title", "title", "name", "dataset_name"),
    "title_tr": ("dataset_title_tr", "title_tr", "turkish_title", "baslik", "tablo_adi"),
    "url": ("source_url", "url", "link"),
    "publication_date": ("publication_date", "published", "yayim_tarihi"),
    "retrieval_date": ("retrieval_date", "download_date", "retrieved", "indirme_tarihi"),
    "identifier": ("tuik_id", "identifier", "table_code", "tablo_kodu"),
    "reference_years": ("reference_year(s)", "reference_years", "years"),
    "unit": ("unit", "units", "birim"),
    "provinces_covered": ("provinces_covered",),
    "missing_provinces": ("missing_provinces",),
    "notes": ("notes", "note"),
}
_VARIABLE_ALIASES = {
    "dataset": ("file_name", "dataset_id", "dataset"),
    "indicator": ("indicator", "variable", "gosterge"),
    "label_tr": ("original_name_tr", "label_tr", "name_tr"),
    "label_en": ("description_en", "label_en", "description"),
    "unit": ("unit", "birim"),
    "source_table": ("source_table_or_flow", "source_table", "dataflow"),
    "theme": ("theme", "tema"),
}
# Claims in the package README that are re-counted from the data (documentation is evidence to check, not proof).
_README_CLAIMS = {
    "datasets": r"(\d[\d,]*)\s+official province-level",
    "indicators": r"(\d[\d,]*)\s+distinct indicators",
    "long_rows": r"(\d[\d,]*)\s+long-format data rows",
    "datasets_with_full_coverage": r"(\d+)\s+of\s+\d+\s+datasets have 100% coverage",
    "not_province_level_datasets": r"Log of\s+(\d+)",
}
RULE_KEYS = {"table", "dataset", "indicator_pattern", "total_patterns", "residual_pattern", "universe_min_age", "universe_note",
             "universe_check", "title", "unit", "source_units", "limitations", "verify_labels", "sex_labels", "age_group_labels",
             "category_labels"}
DATASET_USES = ("controls", "context")


def _pick(record: dict[str, str], names: tuple[str, ...]) -> str | None:
    lowered = {k.lower(): v for k, v in record.items()}
    for name in names:
        if name in lowered and lowered[name] != "":
            return lowered[name]
    return None


def _column(header: list[str], names: tuple[str, ...]) -> str | None:
    lowered = {h.lower(): h for h in header}
    return next((lowered[n] for n in names if n in lowered), None)


def _dataset_id(name: str) -> str:
    name = name.strip()
    return name[:-4] if name.lower().endswith(".csv") else name


def load_mapping(path: Path) -> dict:
    if not path.is_file():
        return {"version": 1, "controls": [], "datasets": {}, "missing_value_markers": {}}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if payload.get("version") != 1:
        raise ControlsError(f"{path.name}: unsupported mapping version {payload.get('version')!r}")
    payload["controls"] = payload.get("controls") or []
    payload["datasets"] = payload.get("datasets") or {}
    payload["missing_value_markers"] = payload.get("missing_value_markers") or {}
    for rule in payload["controls"]:
        if rule.get("table") not in TABLE_KINDS:
            raise ControlsError(f"{path.name}: unknown control table {rule.get('table')!r}")
        if not rule.get("dataset") or not rule.get("indicator_pattern"):
            raise ControlsError(f"{path.name}: each control rule needs 'dataset' and 'indicator_pattern'")
        unknown = set(rule) - RULE_KEYS
        if unknown:
            raise ControlsError(f"{path.name}: rule for {rule['table']} has unknown keys {sorted(unknown)}")
        if rule.get("universe_check") not in (None, "root_universe"):
            raise ControlsError(f"{path.name}: universe_check must be 'root_universe' or absent")
        for pattern in [rule["indicator_pattern"], *(rule.get("total_patterns") or []),
                        *([rule["residual_pattern"]] if rule.get("residual_pattern") else [])]:
            re.compile(pattern)
    from societytwin.national.environment import DOMAINS  # local import: environment depends on controls only

    for ds, spec in payload["datasets"].items():
        if not isinstance(spec, dict):
            raise ControlsError(f"{path.name}: dataset entry {ds!r} must be a mapping")
        if spec.get("use", "context") not in DATASET_USES:
            raise ControlsError(f"{path.name}: dataset {ds!r}: 'use' must be one of {DATASET_USES}")
        if spec.get("domain") and spec["domain"] not in DOMAINS:
            raise ControlsError(f"{path.name}: dataset {ds!r}: unknown domain {spec['domain']!r}")
        if spec.get("observation_type", "observed") not in ("observed", "projection"):
            raise ControlsError(f"{path.name}: dataset {ds!r}: observation_type must be 'observed' or 'projection'")
        if spec.get("use") == "controls" and not any(r["dataset"] == ds for r in payload["controls"]):
            raise ControlsError(f"{path.name}: dataset {ds!r} is marked use: controls but no control rule names it")
        if spec.get("observation_type") == "projection" and any(r["dataset"] == ds for r in payload["controls"]):
            raise ControlsError(f"{path.name}: projections ({ds!r}) can never become control tables")
    return payload


def parse_value(raw: str, markers: dict[str, list[str]]) -> tuple[float | None, str]:
    text = raw.strip()
    lowered = text.lower()
    for status, values in markers.items():
        if lowered in {v.lower() for v in values}:
            return None, status
    cleaned = text.replace(" ", "").replace(" ", "")
    if re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", cleaned):
        return float(cleaned), ValueStatus.OBSERVED
    raise ValueError(f"unparseable value {raw!r}")


def _domain(theme: str | None) -> str:
    if not theme:
        return "other"
    key = label_key(theme)
    for word, domain in THEME_DOMAINS.items():
        if word in key:
            return domain
    return "other"


def _codes_in(text: str | None) -> set[str] | None:
    """Province codes listed in a catalog cell such as '03 (Afyonkarahisar); 08 (Artvin)'. None when absent."""
    if text is None:
        return None
    if text.strip().lower() in ("", "none", "-", "yok"):
        return set()
    return {geo.normalize_code(c) for c in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", text)}


def _claimed_periods(text: str | None) -> dict | None:
    """Parse a catalog 'reference_year(s)' cell: '2007-2025 (19 periods)', '2022, 2023' or '2023-2024, 2024-2025'."""
    if not text:
        return None
    t = text.strip()
    m = re.fullmatch(r"(\d{4})\s*-\s*(\d{4})\s*\((\d+)\s+periods?\)", t)
    if m:
        return {"text": t, "first": int(m[1]), "last": int(m[2]), "count": int(m[3])}
    try:
        parsed = [parse_period(x.strip()) for x in t.split(",") if x.strip()]
    except ValueError:
        return {"text": t, "parsed": False}
    return {"text": t, "first": min(p[1] for p in parsed), "last": max(p[2] for p in parsed), "count": len(parsed),
            "labels": sorted(p[0] for p in parsed)}


def _readme_claims(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace").replace("*", "")
    out = {}
    for key, pattern in _README_CLAIMS.items():
        m = re.search(pattern, text)
        out[key] = int(m.group(1).replace(",", "")) if m else None
    return out


def _period_key(label: str) -> tuple[int, int]:
    _, start, end = parse_period(label)
    return end, start


class _Check:
    """Summary of one build-time consistency check over many province × year cells."""

    def __init__(self, name: str, detail: str):
        self.name, self.detail = name, detail
        self.checked = self.failed = 0
        self.failures: list[dict] = []
        self.years: dict[int, list[int]] = {}
        self.gaps: list[float] = []

    def add(self, ok: bool, year: int, example: dict, relative_gap: float | None = None) -> None:
        self.checked += 1
        counts = self.years.setdefault(year, [0, 0])
        counts[0] += 1
        if not ok:
            self.failed += 1
            counts[1] += 1
            if relative_gap is not None:
                self.gaps.append(relative_gap)
            if len(self.failures) < 20:
                self.failures.append(example)

    def as_dict(self) -> dict:
        out = {"name": self.name, "detail": self.detail, "summary": True, "checked": self.checked, "failed": self.failed,
               "passed": self.checked > 0 and self.failed == 0,
               "years_passed": sorted(y for y, (_, f) in self.years.items() if f == 0),
               "years_failed": sorted(y for y, (_, f) in self.years.items() if f), "failures": self.failures}
        if self.gaps:
            out["relative_gap_range"] = [min(self.gaps), max(self.gaps)]
        return out


@dataclass
class _DatasetInfo:
    dataset: str
    files: set = field(default_factory=set)
    provinces: set = field(default_factory=set)
    periods: set = field(default_factory=set)
    indicators: set = field(default_factory=set)
    units: set = field(default_factory=set)
    read: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicates_agreeing: int = 0
    control_rows: int = 0
    context_rows: int = 0
    blank_values: int = 0
    multi_year_rows: int = 0
    projection_rows: int = 0
    status_counts: dict = field(default_factory=dict)
    multi_year_periods: dict = field(default_factory=dict)
    unit_mismatches: dict = field(default_factory=dict)
    undefined_indicators: set = field(default_factory=set)
    cells: dict = field(default_factory=dict)          # (indicator, period) -> provinces with a row
    wide: list = field(default_factory=list)


def tuik_package(package_dir: Path, mapping_path: Path, repo_root: Path) -> AdapterResult:
    result = AdapterResult("tuik_long_format_package", "absent")
    if not package_dir.is_dir():
        result.detail = "No package directory (expected data/raw/tuik_package/)."
        return result
    files = sorted(p for p in package_dir.rglob("*") if p.is_file() and not p.name.startswith("."))
    csvs = [p for p in files if p.suffix.lower() == ".csv"]
    wide_files = {p.name: p for p in csvs if p.stem.endswith(WIDE_SUFFIX)}
    data_files = [p for p in csvs if p.name not in PACKAGE_METADATA_FILES and p.name not in wide_files]
    documents = [p for p in files if p.suffix.lower() != ".csv"]
    if not data_files:
        result.detail = "The package directory holds no data CSV files."
        return result
    try:
        mapping = load_mapping(mapping_path)
    except (ControlsError, re.error, yaml.YAMLError) as exc:
        return AdapterResult(result.name, "failed", detail=f"Mapping file: {exc}")
    markers = {**DEFAULT_MARKERS, **{k: list(v) for k, v in mapping["missing_value_markers"].items()}}
    meta_rows = {name: _read_csv(package_dir / name) if (package_dir / name).is_file() else [] for name in PACKAGE_METADATA_FILES}
    catalog: dict[str, dict] = {}
    for rec in meta_rows["data_catalog.csv"]:
        ds = _pick(rec, _CATALOG_ALIASES["dataset"])
        if ds:
            catalog[_dataset_id(ds)] = rec
    variables: dict[tuple[str | None, str], dict] = {}
    for rec in meta_rows["variable_metadata.csv"]:
        ind = _pick(rec, _VARIABLE_ALIASES["indicator"])
        if ind:
            ds = _pick(rec, _VARIABLE_ALIASES["dataset"])
            variables[(_dataset_id(ds) if ds else None, ind)] = {k: _pick(rec, v) for k, v in _VARIABLE_ALIASES.items()}

    def var_meta(dataset: str, indicator: str) -> dict:
        return variables.get((dataset, indicator)) or variables.get((None, indicator)) or {}

    ds_specs = mapping["datasets"]
    rules = []
    for r in mapping["controls"]:
        rules.append(dict(r, _re=re.compile(r["indicator_pattern"]), _totals=[re.compile(p) for p in r.get("total_patterns") or []],
                          _residual=re.compile(r["residual_pattern"]) if r.get("residual_pattern") else None))
    rule_by_dataset: dict[str, list[dict]] = {}
    for r in rules:
        rule_by_dataset.setdefault(r["dataset"], []).append(r)
    totals: dict[tuple, dict] = {}      # (table, dataset, pattern index) -> {(province, year, group…): value}
    residuals: dict[tuple, dict] = {}   # (table, dataset) -> {(province, year, sex): value}
    label_checks: dict[tuple, _Check] = {}
    verified_labels: dict[tuple, str | None] = {}
    datasets: dict[str, _DatasetInfo] = {}
    seen_keys: dict[tuple, float | None] = {}
    errors = conflicting = 0

    def reject(info: _DatasetInfo | None, ref: str, why: str) -> None:
        nonlocal errors
        errors += 1
        if info is not None:
            info.rejected += 1
        if errors <= 50:
            result.warnings.append(f"{ref}: rejected ({why})")

    for path in data_files:
        result.inputs.append(_input(path, repo_root, "tuik_package_data"))
        file_keys: dict[tuple, float | None] = {}
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            cols = {k: _column(header, v) for k, v in _ALIASES.items()}
            missing = [k for k in ("province_code", "year", "indicator", "value") if cols[k] is None]
            if missing:
                result.warnings.append(f"{path.name}: skipped, missing columns {missing}")
                continue
            for line, rec in enumerate(reader, start=2):
                ref = f"{path.name}:{line}"
                dataset = (rec[cols["dataset"]].strip() if cols["dataset"] and rec[cols["dataset"]] else path.stem)
                info = datasets.setdefault(dataset, _DatasetInfo(dataset))
                info.files.add(path.name)
                info.read += 1
                try:
                    p = geo.province(rec[cols["province_code"]])
                    if cols["nuts3_code"] and rec[cols["nuts3_code"]] and rec[cols["nuts3_code"]].strip().upper() != p.nuts3:
                        raise ValueError(f"nuts3 {rec[cols['nuts3_code']]!r} does not match province {p.code}")
                    if cols["province_name"] and rec[cols["province_name"]] and geo.name_key(rec[cols["province_name"]]) not in \
                            {geo.name_key(n) for n in (p.name, *p.aliases)}:
                        result.warnings.append(f"{ref}: name {rec[cols['province_name']]!r} differs from code {p.code} ({p.name}); code used")
                    period, start, end = parse_period(rec[cols["year"]])
                    value, status = parse_value(rec[cols["value"]] or "", markers)
                except (ValueError, geo.UnknownProvince) as exc:
                    reject(info, ref, str(exc))
                    continue
                indicator = rec[cols["indicator"]].strip()
                if not indicator:
                    reject(info, ref, "empty indicator")
                    continue
                unit = rec[cols["unit"]].strip() if cols["unit"] else ""
                key = (dataset, p.code, period, indicator)
                if key in seen_keys:
                    if seen_keys[key] != value:
                        conflicting += 1
                        reject(info, ref, f"duplicate key {key} with a different value; first value kept")
                    else:
                        info.duplicates_agreeing += 1
                    continue
                vm = var_meta(dataset, indicator)
                spec = ds_specs.get(dataset, {})
                if spec.get("observation_type") == "projection":
                    baseline = str(spec.get("projection_baseline_period") or "")
                    obs_type = "projection_baseline" if baseline and period == baseline else "projection"
                else:
                    obs_type = "observed"
                source_id = f"tuik_pkg:{dataset}"
                year = start if start == end else None
                control_row = None
                try:
                    for rule in rule_by_dataset.get(dataset, []):
                        m = rule["_re"].fullmatch(indicator)
                        if m:
                            if year is None:
                                raise ValueError(f"control tables need a single reference year, not the period {period!r}")
                            if obs_type != "observed":
                                raise ValueError("projections cannot become control cells")
                            allowed = rule.get("source_units") or ["person", "persons", "kişi"]
                            if unit and unit not in allowed:
                                raise ValueError(f"unit {unit!r} is not a person count ({allowed})")
                            control_row = _rule_row(rule, m, p, year, value, status, source_id, ref)
                            problem = _verify_labels(rule, control_row, dataset, indicator, vm, verified_labels, label_checks)
                            if problem:
                                raise ValueError(problem)
                            break
                        if year is None or status != ValueStatus.OBSERVED:
                            continue
                        for i, pattern in enumerate(rule["_totals"]):
                            t = pattern.fullmatch(indicator)
                            if t:
                                totals.setdefault((rule["table"], dataset, i), {})[(p.code, year, *_group_codes(rule, t.groupdict()))] = value
                        res = rule["_residual"].fullmatch(indicator) if rule["_residual"] is not None else None
                        if res:
                            bucket = residuals.setdefault((rule["table"], dataset), {})
                            k = (p.code, year, *_group_codes(rule, res.groupdict()))
                            bucket[k] = bucket.get(k, 0.0) + value
                except ValueError as exc:
                    reject(info, ref, f"control rule {rule['table']} could not map {indicator!r}: {exc}")
                    continue
                seen_keys[key] = value
                file_keys[(p.code, period, indicator)] = value
                if variables and not vm:
                    info.undefined_indicators.add(indicator)
                if vm.get("unit") and unit and vm["unit"] != unit:
                    info.unit_mismatches[indicator] = (vm["unit"], unit)
                info.accepted += 1
                info.provinces.add(p.code)
                info.periods.add(period)
                info.indicators.add(indicator)
                info.cells.setdefault((indicator, period), set()).add(p.code)
                info.status_counts[status] = info.status_counts.get(status, 0) + 1
                if rec[cols["value"]].strip() == "":
                    info.blank_values += 1
                if start != end:
                    info.multi_year_rows += 1
                    info.multi_year_periods[period] = info.multi_year_periods.get(period, 0) + 1
                if obs_type != "observed":
                    info.projection_rows += 1
                if unit:
                    info.units.add(unit)
                if control_row is not None:
                    result.rows.append(control_row)
                    info.control_rows += 1
                    continue
                theme = spec.get("domain") or _domain(vm.get("theme") or _pick(catalog.get(dataset, {}), _CATALOG_ALIASES["theme"]))
                result.context.append(ContextRow(_slug(f"{dataset}:{indicator}"), theme, vm.get("label_en") or indicator,
                                                 vm.get("label_tr") or "", "province", p.code, year, value, status, unit,
                                                 source_id, ref, period, obs_type))
                info.context_rows += 1
        wide_name = _pick(catalog.get(path.stem, {}), _CATALOG_ALIASES["wide_file"]) or f"{path.stem}{WIDE_SUFFIX}.csv"
        if wide_name in wide_files:
            info = datasets.get(path.stem)
            if info is not None:
                info.wide.append(_verify_wide(wide_files[wide_name], file_keys, markers, repo_root))
    for dataset, info in datasets.items():
        if info.read != info.accepted + info.rejected + info.duplicates_agreeing:
            raise ControlsError(f"{dataset}: row accounting failed ({info.read} read)")  # an internal error, never a data choice

    # ------------------------------------------------------------ control table metadata and checks
    root_cells: dict[tuple, float] = {}
    for row in result.rows:
        if row.table_id == "population_age_sex" and row.value_status == ValueStatus.OBSERVED:
            root_cells[(row.geo_code, row.year, row.sex, row.age_group)] = row.value
    for rule in rules:
        kind = TABLE_KINDS[rule["table"]]
        min_age = int(rule.get("universe_min_age", 0))
        meta = result.tables.setdefault(rule["table"], TableMeta(
            rule["table"], rule["table"], rule.get("title") or kind.description, unit=rule.get("unit", "persons"),
            universe_min_age=min_age, universe_note=rule.get("universe_note", "As defined by the source"), source_ids=[]))
        if f"tuik_pkg:{rule['dataset']}" not in meta.source_ids:
            meta.source_ids.append(f"tuik_pkg:{rule['dataset']}")
        meta.transformations.append(
            f"Indicators of dataset {rule['dataset']!r} matching {rule['indicator_pattern']!r} mapped to standard cells "
            "(data/tuik_package_mapping.yaml). Published aggregate rows (totals) are kept as context and used only for checks, "
            "never summed into cells.")
        meta.limitations += [x for x in rule.get("limitations") or [] if x not in meta.limitations]
        cells = [r for r in result.rows if r.table_id == rule["table"] and r.source_id == f"tuik_pkg:{rule['dataset']}"
                 and r.value_status == ValueStatus.OBSERVED]
        resid = residuals.get((rule["table"], rule["dataset"]), {})
        for i, pattern in enumerate(rule["_totals"]):
            dims = [d for d in ("age_group", "sex", "category") if d in pattern.groupindex]
            sums: dict[tuple, float] = {}
            for r in cells:
                k = (r.geo_code, r.year, *(getattr(r, d) for d in dims))
                sums[k] = sums.get(k, 0.0) + r.value
            check = _Check(f"cells_sum_to_published_total[{i}]",
                           f"Sum of the mapped cells{' and the residual category' if resid else ''} equals the published "
                           f"aggregate row ({pattern.pattern}) per province and year"
                           f"{' and ' + ', '.join(dims) if dims else ''}.")
            for k, total in sorted(totals.get((rule["table"], rule["dataset"], i), {}).items()):
                got = sums.get(k, 0.0) + (sum(v for rk, v in resid.items() if rk[:2] == k[:2] and (not dims or rk[2:] == k[2:]))
                                          if resid else 0.0)
                check.add(abs(got - total) < 0.5, k[1], {"geo_code": k[0], "year": k[1], "group": list(k[2:]), "cells": got,
                                                         "published_total": total})
            if check.checked:
                meta.checks.append(check.as_dict())
        if rule.get("universe_check") == "root_universe" and rule["table"] != "population_age_sex":
            bands = [b for b in AGE_GROUPS if band_bounds(b)[0] >= min_age]
            if any(lo < min_age <= (hi if hi is not None else 10 ** 6) for lo, hi in map(band_bounds, AGE_GROUPS)):
                result.warnings.append(f"{rule['table']}: universe {min_age}+ starts inside an age band; not checked against the root")
            else:
                by_sex: dict[tuple, float] = {}
                for r in cells:
                    k = (r.geo_code, r.year, r.sex)
                    by_sex[k] = by_sex.get(k, 0.0) + r.value
                for rk, v in resid.items():
                    if len(rk) == 3 and rk in by_sex:
                        by_sex[rk] += v
                check = _Check("universe_equals_root_population",
                               f"Table total per sex equals the population aged {min_age}+ of the age × sex table "
                               "(same province and year).")
                for (code, year, sex), total in sorted(by_sex.items()):
                    if not any((code, year, sex, b) in root_cells for b in AGE_GROUPS):
                        continue
                    root = math.fsum(root_cells.get((code, year, sex, b), 0.0) for b in bands)
                    gap = (total - root) / root if root else None
                    check.add(abs(total - root) < 0.5, year, {"geo_code": code, "year": year, "sex": sex, "table_total": total,
                                                              "root_population": root, "relative_gap": gap}, gap)
                if check.checked:
                    meta.checks.append(check.as_dict())
                    d = check.as_dict()
                    if d["years_failed"]:
                        lo, hi = d.get("relative_gap_range", [0, 0])
                        meta.limitations.append(
                            f"The table total differs from the age × sex table's {min_age}+ population in "
                            f"{_years_text(d['years_failed'])} (relative gap {100 * lo:+.2f}% to {100 * hi:+.2f}% where it differs)"
                            + (f"; it matches exactly in {_years_text(d['years_passed'])}" if d["years_passed"] else "")
                            + ". The generator applies the table's distribution to the root population (scaled per sex; the "
                              "scale is reported in validation).")
    for (table, dataset), check in label_checks.items():
        if table in result.tables:
            result.tables[table].checks.append(check.as_dict())

    # ------------------------------------------------------------ sources and package audit
    coverage_matrix: dict[str, set[str]] = {}
    coverage_notes: dict[str, dict] = {}
    for rec in meta_rows["coverage_report.csv"]:
        code = _pick(rec, ("province_code",))
        if code:  # the team package: one row per province, one 1/0 column per dataset file
            for col, flag in rec.items():
                if col.lower().endswith(".csv") and flag.strip() == "1":
                    coverage_matrix.setdefault(_dataset_id(col), set()).add(geo.normalize_code(code))
                elif col.lower().endswith(".csv"):
                    coverage_matrix.setdefault(_dataset_id(col), set())
        else:
            ds = _pick(rec, _CATALOG_ALIASES["dataset"])
            if ds:
                coverage_notes[_dataset_id(ds)] = rec
    not_province = [{"title_en": _pick(r, ("dataset_title_en", "title_en")), "title_tr": _pick(r, ("dataset_title_tr", "title_tr")),
                     "theme": _pick(r, ("theme",)), "geographic_level": _pick(r, ("geographic_level_available", "geographic_level")),
                     "reason": _pick(r, ("reason_excluded", "reason", "note")), "url": _pick(r, ("source_url", "url"))}
                    for r in meta_rows["not_province_level.csv"]]
    discrepancies: list[dict] = []

    def discrepancy(dataset: str | None, field_name: str, claimed, actual, note: str = "") -> None:
        discrepancies.append({"dataset": dataset, "field": field_name, "claimed": claimed, "actual": actual, "note": note})

    for ds in sorted(set(catalog) - set(datasets)):
        discrepancy(ds, "data_file", "listed in data_catalog.csv", "no long-format rows found")
    for ds, info in sorted(datasets.items()):
        cat = catalog.get(ds, {})
        if catalog and not cat:
            discrepancy(ds, "data_catalog", "not listed", f"{info.accepted} rows")
        claimed_count = _pick(cat, _CATALOG_ALIASES["provinces_covered"])
        if claimed_count is not None and claimed_count.isdigit() and int(claimed_count) != len(info.provinces):
            discrepancy(ds, "provinces_covered", int(claimed_count), len(info.provinces))
        has_missing_column = any(k.lower() in _CATALOG_ALIASES["missing_provinces"] for k in cat)
        claimed_missing = _codes_in(_pick(cat, _CATALOG_ALIASES["missing_provinces"]) or "None") if has_missing_column else None
        actual_missing = {p.code for p in geo.PROVINCES} - info.provinces
        if claimed_missing is not None and claimed_missing != actual_missing:
            discrepancy(ds, "missing_provinces", sorted(claimed_missing), sorted(actual_missing))
        if ds in coverage_matrix and coverage_matrix[ds] != info.provinces:
            discrepancy(ds, "coverage_report", sorted(coverage_matrix[ds]), sorted(info.provinces))
        claim = _claimed_periods(_pick(cat, _CATALOG_ALIASES["reference_years"]))
        ends = [_period_key(x) for x in info.periods]
        if claim and claim.get("parsed", True):
            actual = {"first": min(s for _, s in ends), "last": max(e for e, _ in ends), "count": len(info.periods)}
            if any(claim[k] != actual[k] for k in ("first", "last", "count")) or \
                    ("labels" in claim and claim["labels"] != sorted(info.periods)):
                discrepancy(ds, "reference_year(s)", claim["text"], f"{actual['first']}–{actual['last']}, {actual['count']} periods: "
                            + ", ".join(sorted(info.periods, key=_period_key)))
        claimed_units = {u.strip() for u in (_pick(cat, _CATALOG_ALIASES["unit"]) or "").split(";") if u.strip()}
        if claimed_units and claimed_units != info.units:
            discrepancy(ds, "unit", sorted(claimed_units), sorted(info.units))
        defined = {ind for (vds, ind) in variables if vds == ds}
        if defined - info.indicators:
            discrepancy(ds, "variable_metadata", f"{len(defined)} indicators defined", f"{len(info.indicators)} indicators with rows",
                        "Defined but absent from the data: " + ", ".join(sorted(defined - info.indicators)))
        if info.undefined_indicators:
            discrepancy(ds, "variable_metadata", "no definition", sorted(info.undefined_indicators))
        for ind, (declared, used) in sorted(info.unit_mismatches.items()):
            discrepancy(ds, "unit", f"{ind}: {declared}", used, "Unit in the data differs from variable_metadata.csv")
    total_rows = sum(i.accepted for i in datasets.values())
    total_indicators = sum(len(i.indicators) for i in datasets.values())
    readme = next((p for p in documents if p.name.lower() == "readme.md"), None)
    claims = _readme_claims(readme) if readme else {}
    actual_counts = {"datasets": len(datasets), "indicators": total_indicators, "long_rows": total_rows,
                     "datasets_with_full_coverage": sum(1 for i in datasets.values() if len(i.provinces) == len(geo.PROVINCES)),
                     "not_province_level_datasets": len(not_province)}
    for key, claimed in claims.items():
        if claimed is not None and claimed != actual_counts[key]:
            discrepancy(None, f"README.{key}", claimed, actual_counts[key])
    if variables and len(variables) != total_indicators:
        discrepancy(None, "variable_metadata.rows", len(variables), total_indicators,
                    "variable_metadata.csv defines more indicators than the data contains")
    wide_checks = [w for i in datasets.values() for w in i.wide]
    for w in wide_checks:
        if w["mismatches"] or w["wide_only_values"] or w["long_only_keys"]:
            discrepancy(_dataset_id(w["file"]).removesuffix(WIDE_SUFFIX), "wide_file", "same values as the long file",
                        {k: w[k] for k in ("mismatches", "wide_only_values", "long_only_keys")})
    unused_wide = sorted(set(wide_files) - {w["file"] for w in wide_checks})

    for ds, info in sorted(datasets.items()):
        cat = catalog.get(ds, {})
        spec = ds_specs.get(ds, {})
        used = any(r["dataset"] == ds for r in rules) and info.control_rows > 0
        source_tables = sorted({var_meta(ds, i).get("source_table") for i in info.indicators} - {None})
        absent_rows = sum(len(info.provinces) - len(v) for v in info.cells.values())
        limitations = []
        if len(info.provinces) < len(geo.PROVINCES):
            limitations.append(f"Covers {len(info.provinces)} of 81 provinces; uncovered provinces are STRUCTURALLY_UNAVAILABLE, not zero.")
        if info.blank_values:
            limitations.append(f"{info.blank_values} blank value(s) are NOT_REPORTED (never zero). The package does not distinguish "
                               "confidentiality suppression from absence.")
        if absent_rows:
            limitations.append(f"{absent_rows} province row(s) are absent within indicator-periods that other covered provinces report; "
                               "absent rows are not created and are not zero.")
        if info.multi_year_rows:
            limitations.append(f"{info.multi_year_rows} observation(s) refer to multi-year periods "
                               f"({', '.join(sorted(info.multi_year_periods, key=_period_key))}); the period is kept as published.")
        if spec.get("observation_type") == "projection":
            limitations.append("Official projections: never used as current observations"
                               + (f" (period {spec['projection_baseline_period']} is the projection baseline)."
                                  if spec.get("projection_baseline_period") else "."))
        if spec.get("reason"):
            limitations.append(spec["reason"])
        ds_discrepancies = [d for d in discrepancies if d["dataset"] == ds]
        result.sources.append({
            "source_id": f"tuik_pkg:{ds}", "publisher": "TÜİK (Turkish Statistical Institute), TÜİK Veri Portalı",
            "title_en": _pick(cat, _CATALOG_ALIASES["title_en"]) or ds, "title_tr": _pick(cat, _CATALOG_ALIASES["title_tr"]),
            "dataset_identifier": _pick(cat, _CATALOG_ALIASES["identifier"]) or ("; ".join(source_tables) if source_tables else ds),
            "source_tables": source_tables, "theme": _pick(cat, _CATALOG_ALIASES["theme"]),
            "domain": spec.get("domain") or _domain(_pick(cat, _CATALOG_ALIASES["theme"])),
            "url": _pick(cat, _CATALOG_ALIASES["url"]), "publication_date": _pick(cat, _CATALOG_ALIASES["publication_date"]),
            "retrieval_date": _pick(cat, _CATALOG_ALIASES["retrieval_date"]),
            "reference_years": sorted({parse_period(x)[1] for x in info.periods if parse_period(x)[1] == parse_period(x)[2]}),
            "reference_periods": sorted(info.periods, key=_period_key),
            "catalog_reference_years": _pick(cat, _CATALOG_ALIASES["reference_years"]),
            "geographic_level": "province",
            "province_coverage": sorted(info.provinces), "missing_provinces": sorted({p.code for p in geo.PROVINCES} - info.provinces),
            "variables": sorted(info.indicators)[:200], "variable_count": len(info.indicators),
            "variable_metadata": {i: {k: var_meta(ds, i).get(k) for k in ("label_tr", "label_en", "unit", "source_table")}
                                  for i in sorted(info.indicators)},
            "units": sorted(info.units), "rows": info.accepted, "value_status_counts": info.status_counts,
            "blank_values": info.blank_values, "multi_year_rows": info.multi_year_rows, "multi_year_periods": info.multi_year_periods,
            "projection_rows": info.projection_rows, "absent_province_rows": absent_rows,
            "observation_type": spec.get("observation_type", "observed"),
            "accounting": {"read": info.read, "control_cells": info.control_rows, "context_observations": info.context_rows,
                           "rejected": info.rejected, "duplicates_agreeing": info.duplicates_agreeing},
            "mapping": {"use": "controls" if used else "context",
                        "tables": sorted({r["table"] for r in rules if r["dataset"] == ds}),
                        "reason": spec.get("reason") or spec.get("note")},
            "processed_file": None,
            "raw_files": [_input(package_dir / f, repo_root, "tuik_package_data") for f in sorted(info.files)],
            "wide_files": [{k: w[k] for k in ("file", "sha256", "cells_compared", "mismatches", "wide_only_values", "long_only_keys")}
                           for w in info.wide],
            "transformations": ["Read from the long-format package; province identified by code (NUTS-3 code and name checked, "
                                "never used alone); reference periods kept as published.",
                                "The matching _wide.csv file is verified cell by cell against the long file and not imported, "
                                "so no value is counted twice."],
            "limitations": limitations, "discrepancies": ds_discrepancies,
            "catalog_record": cat or None, "coverage_record": coverage_notes.get(ds),
            "status": "used" if used else "context_only",
        })
    result.datasets = [{"dataset": ds, "province_count": len(i.provinces), "provinces": sorted(i.provinces),
                        "years": sorted({parse_period(x)[2] for x in i.periods}), "periods": sorted(i.periods, key=_period_key),
                        "indicator_count": len(i.indicators), "rows": i.accepted, "rejected": i.rejected,
                        "control_cells": i.control_rows, "context_observations": i.context_rows}
                       for ds, i in sorted(datasets.items())]
    result.inputs.extend(_input(package_dir / n, repo_root, "tuik_package_metadata") for n in PACKAGE_METADATA_FILES
                         if (package_dir / n).is_file())
    result.inputs.extend(_input(wide_files[n], repo_root, "tuik_package_wide_verified_not_imported") for n in sorted(wide_files))
    result.inputs.extend(_input(p, repo_root, "tuik_package_documentation") for p in documents)
    if unused_wide:
        result.warnings.append(f"Wide files without a matching long file (not imported): {unused_wide}")
    if errors > 50:
        result.warnings.append(f"{errors - 50} further rejected rows not listed")
    result.audit = {
        "adapter": result.name, "package_dir": _rel(package_dir, repo_root),
        "files": {"total": len(files), "long_format": len(data_files), "wide": len(wide_files),
                  "metadata": [n for n in PACKAGE_METADATA_FILES if (package_dir / n).is_file()],
                  "documentation": [p.name for p in documents]},
        "counts": {**actual_counts, "rejected_rows": errors,
                   "blank_values": sum(i.blank_values for i in datasets.values()),
                   "multi_year_rows": sum(i.multi_year_rows for i in datasets.values()),
                   "projection_rows": sum(i.projection_rows for i in datasets.values()),
                   "control_cells": sum(i.control_rows for i in datasets.values()),
                   "context_observations": sum(i.context_rows for i in datasets.values()),
                   "duplicate_keys_conflicting": conflicting,
                   "variable_metadata_indicators": len(variables),
                   "province_coverage_distribution": dict(sorted(Counter(len(i.provinces) for i in datasets.values()).items(),
                                                                 reverse=True))},
        "documentation_claims": {"source": readme.name if readme else None, "claims": claims,
                                 "note": "Counts claimed by the package documentation, re-counted from the data. The "
                                         "documentation is treated as source information, not as proof."},
        "wide_files": {"verified": len(wide_checks), "cells_compared": sum(w["cells_compared"] for w in wide_checks),
                       "mismatches": sum(w["mismatches"] for w in wide_checks), "unmatched_files": unused_wide},
        "discrepancies": discrepancies,
        "not_province_level": not_province,
        "mapping_file": _rel(mapping_path, repo_root),
    }
    result.status = "loaded"
    result.detail = (f"{total_rows} rows from {len(datasets)} datasets ({len(result.rows)} control cells, {len(result.context)} context "
                     f"observations); {len(rules)} control rules; {errors} rejected rows; {len(discrepancies)} documentation "
                     "discrepancies")
    return result


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _years_text(years: list[int]) -> str:
    if not years:
        return "no year"
    runs, start, prev = [], years[0], years[0]
    for y in years[1:] + [None]:
        if y is not None and y == prev + 1:
            prev = y
            continue
        runs.append(str(start) if start == prev else f"{start}–{prev}")
        if y is not None:
            start = prev = y
    return ", ".join(runs)


def _verify_wide(path: Path, long_values: dict[tuple, float | None], markers: dict, repo_root: Path) -> dict:
    """Compare a wide file with its long twin, cell by cell. The wide file is evidence, never a second import."""
    compared = mismatches = wide_only = 0
    examples = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        id_cols = {"province_code", "province_name", "nuts3_code", "year"}
        for rec in reader:
            try:
                code = geo.normalize_code(rec["province_code"])
                period = parse_period(rec["year"])[0]
            except (ValueError, KeyError, geo.UnknownProvince):
                mismatches += 1
                continue
            for col, raw in rec.items():
                if col in id_cols or col is None:
                    continue
                key = (code, period, col)
                try:
                    value, _ = parse_value(raw or "", markers)
                except ValueError:
                    value = raw
                if key not in long_values:
                    if (raw or "").strip():
                        wide_only += 1
                    continue
                seen.add(key)
                compared += 1
                expected = long_values[key]
                same = (expected is None and value is None) or (
                    isinstance(expected, float) and isinstance(value, float) and abs(expected - value) <= 1e-9 * max(1.0, abs(expected)))
                if not same:
                    mismatches += 1
                    if len(examples) < 5:
                        examples.append({"key": list(key), "long": expected, "wide": value})
    return {**_input(path, repo_root, "tuik_package_wide_verified_not_imported"), "file": path.name, "cells_compared": compared,
            "mismatches": mismatches, "wide_only_values": wide_only, "long_only_keys": len(set(long_values) - seen),
            "examples": examples}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label_key(text).translate(str.maketrans("çğıöşü", "cgiosu"))).strip("_")[:120]


def _age_band(raw: str) -> str:
    band = re.sub(r"\s+", "", raw).replace("–", "-").replace("_plus", "+").replace("plus", "+").replace("_", "-")
    if band not in AGE_GROUPS:
        raise ValueError(f"age group {raw!r} is not a standard five-year band")
    return band


def _dim_code(rule: dict, dim: str, raw: str, attribute: str | None) -> str:
    labels = rule.get(f"{dim}_labels") or {}
    if raw in labels:
        return labels[raw]
    if dim == "sex":
        return SEX.from_source(raw)
    if dim == "age_group":
        return _age_band(raw)
    return VOCABULARIES[attribute].from_source(raw)


def _group_codes(rule: dict, groups: dict) -> tuple[str, ...]:
    """Codes of the named groups of a total/residual pattern, in the fixed order age_group, sex, category."""
    attribute = TABLE_KINDS[rule["table"]].attribute
    return tuple(_dim_code(rule, d, groups[d], attribute) for d in ("age_group", "sex", "category") if groups.get(d) is not None)


def _rule_row(rule: dict, match: re.Match, p: geo.Province, year: int, value, status, source_id: str, ref: str) -> ControlRow:
    kind = TABLE_KINDS[rule["table"]]
    groups = match.groupdict()
    parts = {"sex": "", "age_group": "", "category": ""}
    for dim in kind.dims:
        raw = groups.get(dim)
        if raw is None:
            raise ValueError(f"pattern has no named group {dim!r}")
        parts[dim] = _dim_code(rule, dim, raw, kind.attribute)
    return ControlRow(rule["table"], "province", p.code, year, parts["sex"], parts["age_group"], parts["category"],
                      value, status, source_id, ref)


def _word_in(needle: str, haystack: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(needle)}(?![\w])", haystack) is not None


def _verify_labels(rule: dict, row: ControlRow, dataset: str, indicator: str, vm: dict, cache: dict, checks: dict) -> str | None:
    """Check a mapped cell against the indicator's original Turkish name in variable_metadata.csv.

    The indicator id (e.g. pop_age_0_4_male) is the package's own English naming; the Turkish name is closer to the
    TÜİK table. Each mapped code must be recognisable in it: the sex label, the age band, and the category's TÜİK label
    (or a declared alias). Done once per indicator. Rules may set verify_labels: false when no Turkish names exist.
    """
    original = vm.get("label_tr")
    if rule.get("verify_labels") is False or not original:
        return None
    key = (rule["table"], dataset, indicator)
    if key in cache:
        return cache[key]
    text = label_key(original)
    problems = []
    if row.sex and not _word_in(label_key(SEX.labels_tr[row.sex]), text):
        problems.append(f"sex {row.sex!r}")
    if row.age_group:
        low, high = band_bounds(row.age_group)
        band = f"{low}+" if high is None else f"{low} {high}"
        if not _word_in(band, text) and not (high is None and f"{low}+" in text):
            problems.append(f"age group {row.age_group!r}")
    if row.category:
        vocab = VOCABULARIES[TABLE_KINDS[rule["table"]].attribute]
        names = [vocab.labels_tr.get(row.category, "")] + [a for a, c in vocab.source_aliases.items() if c == row.category]
        if not any(n and label_key(n) in text for n in names):
            problems.append(f"category {row.category!r}")
    out = (f"mapped cell ({', '.join(problems)}) is not recognisable in the source name {original!r}") if problems else None
    cache[key] = out
    check = checks.setdefault((rule["table"], dataset), _Check(
        "labels_match_source_names", f"Every mapped indicator of {dataset} names the mapped sex, age band and category in its "
                                     "original Turkish label (variable_metadata.csv)."))
    check.add(out is None, row.year, {"indicator": indicator, "original_name_tr": original, "problem": out})
    return out


# ================================================================ merge
LEGACY_EQUIVALENTS = {  # legacy Ankara context id -> package context id with the same definition (cross-source check)
    "total_population": "population_total_and_growth_total_population",
    "female_population": "population_by_age_sex_pop_age_total_female",
    "male_population": "population_by_age_sex_pop_age_total_male",
    "population_density": "population_total_and_growth_population_density",
    "total_median_age": "population_structural_indicators_median_age_total",
    "female_median_age": "population_structural_indicators_median_age_female",
    "male_median_age": "population_structural_indicators_median_age_male",
}


def build_controls(settings) -> tuple[ControlStore, list[dict]]:
    # The package goes first: it carries URLs, dates and raw-file checksums, so a cell present in both is attributed to
    # it; the legacy extract then corroborates it. Disagreeing cells are an error, not a choice.
    adapters = [tuik_package(settings.tuik_package_dir, settings.tuik_mapping_path, settings.repo_root),
                legacy_ankara(settings.experiment_root, settings.layout, settings.repo_root)]
    tables: dict[str, TableMeta] = {}
    cells: dict[tuple, ControlRow] = {}
    context: dict[tuple, ContextRow] = {}
    sources, inputs, warnings, report, audits = [], [], [], [], []
    corroborated: dict[tuple[str, str], int] = {}
    cells_by_source: dict[str, int] = {}
    for res in adapters:
        report.append({"adapter": res.name, "status": res.status, "detail": res.detail, "warnings": res.warnings[:100],
                       "datasets": res.datasets})
        if res.status != "loaded":
            continue
        for tid, meta in res.tables.items():
            if tid in tables:
                existing = tables[tid]
                if existing.universe_min_age != meta.universe_min_age:
                    raise ControlsError(f"{tid}: sources disagree on the universe ({existing.universe_min_age}+ vs {meta.universe_min_age}+)")
                existing.source_ids = sorted(set(existing.source_ids) | set(meta.source_ids))
                existing.transformations += [t for t in meta.transformations if t not in existing.transformations]
                existing.checks += meta.checks
                existing.limitations += [x for x in meta.limitations if x not in existing.limitations]
            else:
                tables[tid] = meta
        for row in res.rows:
            validate_row(row, tables[row.table_id])
            cells_by_source[row.source_id] = cells_by_source.get(row.source_id, 0) + 1
            key = (row.table_id, row.geo_level, row.geo_code, row.year, row.sex, row.age_group, row.category)
            if key in cells:
                if cells[key].value != row.value or cells[key].value_status != row.value_status:
                    raise ControlsError(f"Conflicting values for {key}: {cells[key].source_id} vs {row.source_id}")
                pair = (cells[key].source_id, row.source_id)
                if pair[0] == pair[1]:
                    warnings.append(f"Duplicate agreeing cell {key} from {row.source_id}; first kept")
                corroborated[pair] = corroborated.get(pair, 0) + 1
                continue
            cells[key] = row
        for row in res.context:
            key = (row.indicator_id, row.geo_level, row.geo_code, row.period)
            if key not in context:
                context[key] = row
        sources.extend(res.sources)
        inputs.extend(res.inputs)
        warnings.extend(res.warnings)
        if res.audit:
            audits.append(res.audit)
    cross = []
    for (kept, other), n in sorted(corroborated.items()):
        if kept != other:
            cross.append({"check": "agreeing_cells", "kept_source": kept, "corroborating_source": other, "cells": n, "conflicts": 0,
                          "detail": f"{n} cells of {other} equal the cells already loaded from {kept}; the first source is cited."})
    for (ind, level, code, period), row in sorted(context.items()):
        twin = LEGACY_EQUIVALENTS.get(ind)
        other = context.get((twin, level, code, period)) if twin else None
        if other is not None and row.value is not None and other.value is not None:
            ok = math.isclose(row.value, other.value, rel_tol=1e-9, abs_tol=1e-6)
            cross.append({"check": "legacy_context_equals_package", "indicator": ind, "package_indicator": twin, "geo_code": code,
                          "period": period, "legacy": row.value, "package": other.value, "passed": ok})
    # A source whose every cell (or context value) repeats an already-loaded source is corroborating evidence: it is
    # kept and cited in the checks, but it is not a coverage gap for the provinces it does not cover.
    agreeing = {c["corroborating_source"]: c["cells"] for c in cross if c["check"] == "agreeing_cells"}
    context_checks: dict[str, list[bool]] = {}
    for c in cross:
        if c["check"] == "legacy_context_equals_package":
            sid = context[(c["indicator"], "province", c["geo_code"], c["period"])].source_id
            context_checks.setdefault(sid, []).append(c["passed"])
    context_counts = Counter(row.source_id for row in context.values())
    for src in sources:
        sid = src["source_id"]
        rows_ok = cells_by_source.get(sid, 0) > 0 and agreeing.get(sid) == cells_by_source[sid]
        context_ok = context_counts.get(sid, 0) > 0 and len(context_checks.get(sid, [])) == context_counts[sid] and all(context_checks[sid])
        if rows_ok or context_ok:
            src["status"] = "corroborating"
            src["limitations"] = [*src["limitations"], "Every value equals the TÜİK package's; the package is cited for these cells and "
                                                       "this source is kept as corroborating evidence only."]
    if cross:
        audits.append({"adapter": "cross_source", "checks": cross})
    store = ControlStore(tables, list(cells.values()), list(context.values()), sources, utc_now(), inputs, warnings, audits=audits)
    return store, report


def describe_inputs(store: ControlStore) -> str:
    return sha256_bytes(repr(sorted((i["path"], i["sha256"]) for i in store.inputs)).encode())
