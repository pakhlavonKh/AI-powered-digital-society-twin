"""Source adapters that normalise official tables into the standard control store.

Two adapters exist:

* ``legacy_ankara``: the processed TÜİK extracts that the historical MatrAIx experiment ships
  (Ankara, 2025 age × sex, 2025 marital status × sex, provincial context). Read-only; the experiment
  files are never modified.
* ``tuik_package``: the team's long-format TÜİK package (``province_code, province_name, nuts3_code,
  year, indicator, value, unit`` plus metadata CSVs), read from ``data/raw/tuik_package/`` when present.
  Indicators become control tables only through explicit rules in ``data/tuik_package_mapping.yaml``;
  every other indicator becomes province context for the environment, grouped by its catalog theme.

``build_controls`` merges both into one store. Conflicting duplicate cells are an error, not a choice.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from societytwin.common import sha256_bytes, sha256_file, utc_now
from societytwin.national import geography as geo
from societytwin.national.controls import TABLE_KINDS, ContextRow, ControlRow, ControlsError, ControlStore, TableMeta, validate_row
from societytwin.national.vocab import AGE_GROUPS, MARITAL, SEX, VOCABULARIES, ValueStatus, band_bounds, label_key

BUILDER_VERSION = "controls-builder-1.0"
PACKAGE_METADATA_FILES = ("data_catalog.csv", "variable_metadata.csv", "coverage_report.csv", "not_province_level.csv")
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
_ALIASES = {
    "province_code": ("province_code", "il_kodu", "plate_code"),
    "province_name": ("province_name", "il", "il_adi", "province"),
    "nuts3_code": ("nuts3_code", "nuts3", "ibbs3", "ibbs_duzey3"),
    "year": ("year", "yil"),
    "indicator": ("indicator", "gosterge", "variable"),
    "value": ("value", "deger"),
    "unit": ("unit", "birim"),
    "dataset": ("dataset_id", "dataset", "veri_seti", "table_id"),
}
_CATALOG_ALIASES = {
    "dataset": ("dataset_id", "dataset", "id", "table_id", "file"),
    "theme": ("theme", "tema", "category"),
    "title_en": ("title_en", "english_title", "title", "name", "dataset_name"),
    "title_tr": ("title_tr", "turkish_title", "baslik", "tablo_adi"),
    "url": ("url", "source_url", "link"),
    "publication_date": ("publication_date", "published", "yayim_tarihi"),
    "retrieval_date": ("retrieval_date", "download_date", "retrieved", "indirme_tarihi"),
    "identifier": ("tuik_id", "identifier", "table_code", "tablo_kodu"),
}


def _pick(record: dict[str, str], names: tuple[str, ...]) -> str | None:
    lowered = {k.lower(): v for k, v in record.items()}
    for name in names:
        if name in lowered and lowered[name] != "":
            return lowered[name]
    return None


def _column(header: list[str], names: tuple[str, ...]) -> str | None:
    lowered = {h.lower(): h for h in header}
    return next((lowered[n] for n in names if n in lowered), None)


def load_mapping(path: Path) -> dict:
    if not path.is_file():
        return {"version": 1, "controls": [], "missing_value_markers": {}}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if payload.get("version") != 1:
        raise ControlsError(f"{path.name}: unsupported mapping version {payload.get('version')!r}")
    payload.setdefault("controls", [])
    payload.setdefault("missing_value_markers", {})
    for rule in payload["controls"]:
        if rule.get("table") not in TABLE_KINDS:
            raise ControlsError(f"{path.name}: unknown control table {rule.get('table')!r}")
        if not rule.get("dataset") or not rule.get("indicator_pattern"):
            raise ControlsError(f"{path.name}: each control rule needs 'dataset' and 'indicator_pattern'")
        re.compile(rule["indicator_pattern"])
    return payload


def parse_value(raw: str, markers: dict[str, list[str]]) -> tuple[float | None, str]:
    text = raw.strip()
    lowered = text.lower()
    for status, values in markers.items():
        if lowered in {v.lower() for v in values}:
            return None, status
    cleaned = text.replace(" ", "").replace(" ", "")
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


def tuik_package(package_dir: Path, mapping_path: Path, repo_root: Path) -> AdapterResult:
    result = AdapterResult("tuik_long_format_package", "absent")
    if not package_dir.is_dir():
        result.detail = "No package directory (expected data/raw/tuik_package/)."
        return result
    data_files = sorted(p for p in package_dir.rglob("*.csv") if p.name not in PACKAGE_METADATA_FILES)
    if not data_files:
        result.detail = "The package directory holds no data CSV files."
        return result
    try:
        mapping = load_mapping(mapping_path)
    except (ControlsError, re.error, yaml.YAMLError) as exc:
        return AdapterResult(result.name, "failed", detail=f"Mapping file: {exc}")
    markers = {**DEFAULT_MARKERS, **{k: list(v) for k, v in mapping["missing_value_markers"].items()}}
    meta_rows = {name: _read_csv(package_dir / name) if (package_dir / name).is_file() else [] for name in PACKAGE_METADATA_FILES}
    catalog = {}
    for rec in meta_rows["data_catalog.csv"]:
        ds = _pick(rec, _CATALOG_ALIASES["dataset"])
        if ds:
            catalog[ds] = rec
    themes_by_indicator = {}
    for rec in meta_rows["variable_metadata.csv"]:
        ind = _pick(rec, ("indicator", "variable", "gosterge"))
        if ind:
            themes_by_indicator[ind] = _pick(rec, _CATALOG_ALIASES["theme"])
    rules = [dict(r, _re=re.compile(r["indicator_pattern"])) for r in mapping["controls"]]
    datasets: dict[str, dict] = {}
    seen_keys: dict[tuple, float | None] = {}
    errors = 0
    for path in data_files:
        result.inputs.append(_input(path, repo_root, "tuik_package_data"))
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
                try:
                    p = geo.province(rec[cols["province_code"]])
                    if cols["nuts3_code"] and rec[cols["nuts3_code"]] and rec[cols["nuts3_code"]].strip().upper() != p.nuts3:
                        raise ValueError(f"nuts3 {rec[cols['nuts3_code']]!r} does not match province {p.code}")
                    if cols["province_name"] and rec[cols["province_name"]] and geo.name_key(rec[cols["province_name"]]) not in \
                            {geo.name_key(n) for n in (p.name, *p.aliases)}:
                        result.warnings.append(f"{ref}: name {rec[cols['province_name']]!r} differs from code {p.code} ({p.name}); code used")
                    year = int(float(rec[cols["year"]]))
                    if not 1900 <= year <= 2100:
                        raise ValueError(f"year {year} out of range")
                    value, status = parse_value(rec[cols["value"]] or "", markers)
                except (ValueError, geo.UnknownProvince) as exc:
                    errors += 1
                    if errors <= 50:
                        result.warnings.append(f"{ref}: rejected ({exc})")
                    continue
                dataset = (rec[cols["dataset"]].strip() if cols["dataset"] and rec[cols["dataset"]] else path.stem)
                indicator = rec[cols["indicator"]].strip()
                unit = rec[cols["unit"]].strip() if cols["unit"] else ""
                key = (dataset, p.code, year, indicator)
                if key in seen_keys:
                    if seen_keys[key] != value:
                        errors += 1
                        result.warnings.append(f"{ref}: duplicate key {key} with a different value; first value kept")
                    continue
                seen_keys[key] = value
                info = datasets.setdefault(dataset, {"dataset": dataset, "provinces": set(), "years": set(), "indicators": set(),
                                                     "units": set(), "files": set(), "rows": 0, "status_counts": {}})
                info["provinces"].add(p.code)
                info["years"].add(year)
                info["indicators"].add(indicator)
                info["files"].add(path.name)
                info["rows"] += 1
                info["status_counts"][status] = info["status_counts"].get(status, 0) + 1
                if unit:
                    info["units"].add(unit)
                source_id = f"tuik_pkg:{dataset}"
                matched = False
                for rule in rules:
                    if rule["dataset"] != dataset:
                        continue
                    m = rule["_re"].fullmatch(indicator)
                    if not m:
                        continue
                    matched = True
                    try:
                        result.rows.append(_rule_row(rule, m, p, year, value, status, source_id, ref))
                    except ValueError as exc:
                        errors += 1
                        result.warnings.append(f"{ref}: control rule {rule['table']} could not map {indicator!r} ({exc})")
                    break
                if not matched:
                    theme = themes_by_indicator.get(indicator) or _pick(catalog.get(dataset, {}), _CATALOG_ALIASES["theme"])
                    result.context.append(ContextRow(_slug(f"{dataset}:{indicator}"), _domain(theme), indicator, "", "province", p.code,
                                                     year, value, status, unit, source_id, ref))
    for rule in mapping["controls"]:
        kind = TABLE_KINDS[rule["table"]]
        result.tables.setdefault(rule["table"], TableMeta(
            rule["table"], rule["table"], rule.get("title") or kind.description, unit=rule.get("unit", "persons"),
            universe_min_age=int(rule.get("universe_min_age", 0)), universe_note=rule.get("universe_note", "As defined by the source"),
            source_ids=[], transformations=[f"Indicators of dataset {rule['dataset']!r} matching {rule['indicator_pattern']!r} "
                                            "mapped to standard cells (data/tuik_package_mapping.yaml)."]))
        if f"tuik_pkg:{rule['dataset']}" not in result.tables[rule["table"]].source_ids:
            result.tables[rule["table"]].source_ids.append(f"tuik_pkg:{rule['dataset']}")
    coverage_notes = {(_pick(r, _CATALOG_ALIASES["dataset"]) or ""): r for r in meta_rows["coverage_report.csv"]}
    not_province = {(_pick(r, _CATALOG_ALIASES["dataset"]) or _pick(r, ("indicator",)) or "") for r in meta_rows["not_province_level.csv"]}
    for ds, info in sorted(datasets.items()):
        cat = catalog.get(ds, {})
        files = sorted(info["files"])
        result.sources.append({
            "source_id": f"tuik_pkg:{ds}", "publisher": "TÜİK (Turkish Statistical Institute), TÜİK Veri Portalı",
            "title_en": _pick(cat, _CATALOG_ALIASES["title_en"]) or ds, "title_tr": _pick(cat, _CATALOG_ALIASES["title_tr"]),
            "dataset_identifier": _pick(cat, _CATALOG_ALIASES["identifier"]) or ds, "theme": _pick(cat, _CATALOG_ALIASES["theme"]),
            "url": _pick(cat, _CATALOG_ALIASES["url"]), "publication_date": _pick(cat, _CATALOG_ALIASES["publication_date"]),
            "retrieval_date": _pick(cat, _CATALOG_ALIASES["retrieval_date"]),
            "reference_years": sorted(info["years"]), "geographic_level": "province",
            "province_coverage": sorted(info["provinces"]), "variables": sorted(info["indicators"])[:200],
            "variable_count": len(info["indicators"]), "units": sorted(info["units"]), "rows": info["rows"],
            "value_status_counts": info["status_counts"],
            "processed_file": None, "raw_files": [_input(package_dir / f, repo_root, "tuik_package_data") for f in files],
            "transformations": ["Read from the long-format package; province identified by code (names checked, never used alone)."],
            "limitations": ([f"Covers {len(info['provinces'])} of 81 provinces; uncovered provinces are STRUCTURALLY_UNAVAILABLE, not zero."]
                            if len(info["provinces"]) < 81 else []) + (["Listed in not_province_level.csv."] if ds in not_province else []),
            "catalog_record": cat or None, "coverage_record": coverage_notes.get(ds),
            "status": "used" if any(r["dataset"] == ds for r in mapping["controls"]) else "context_only",
        })
    result.datasets = [{"dataset": ds, "province_count": len(i["provinces"]), "provinces": sorted(i["provinces"]),
                        "years": sorted(i["years"]), "indicator_count": len(i["indicators"]), "rows": i["rows"]}
                       for ds, i in sorted(datasets.items())]
    result.inputs.extend(_input(package_dir / n, repo_root, "tuik_package_metadata") for n in PACKAGE_METADATA_FILES
                         if (package_dir / n).is_file())
    if errors > 50:
        result.warnings.append(f"{errors - 50} further rejected rows not listed")
    result.status = "loaded"
    result.detail = (f"{sum(i['rows'] for i in datasets.values())} rows from {len(datasets)} datasets; "
                     f"{len(mapping['controls'])} control rules; {errors} rejected rows")
    return result


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label_key(text).translate(str.maketrans("çğıöşü", "cgiosu"))).strip("_")[:120]


def _rule_row(rule: dict, match: re.Match, p: geo.Province, year: int, value, status, source_id: str, ref: str) -> ControlRow:
    kind = TABLE_KINDS[rule["table"]]
    groups = match.groupdict()
    parts = {"sex": "", "age_group": "", "category": ""}
    for dim in kind.dims:
        raw = groups.get(dim)
        if raw is None:
            raise ValueError(f"pattern has no named group {dim!r}")
        labels = rule.get(f"{dim}_labels") or {}
        if raw in labels:
            parts[dim] = labels[raw]
        elif dim == "sex":
            parts[dim] = SEX.from_source(raw)
        elif dim == "age_group":
            band = re.sub(r"\s+", "", raw).replace("–", "-")
            if band not in AGE_GROUPS:
                raise ValueError(f"age group {raw!r} is not a standard five-year band")
            parts[dim] = band
        else:
            parts[dim] = VOCABULARIES[kind.attribute].from_source(raw)
    return ControlRow(rule["table"], "province", p.code, year, parts["sex"], parts["age_group"], parts["category"],
                      value, status, source_id, ref)


# ================================================================ merge
def build_controls(settings) -> tuple[ControlStore, list[dict]]:
    adapters = [legacy_ankara(settings.experiment_root, settings.layout, settings.repo_root),
                tuik_package(settings.tuik_package_dir, settings.tuik_mapping_path, settings.repo_root)]
    tables: dict[str, TableMeta] = {}
    cells: dict[tuple, ControlRow] = {}
    context: dict[tuple, ContextRow] = {}
    sources, inputs, warnings, report = [], [], [], []
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
            key = (row.table_id, row.geo_level, row.geo_code, row.year, row.sex, row.age_group, row.category)
            if key in cells:
                if cells[key].value != row.value:
                    raise ControlsError(f"Conflicting values for {key}: {cells[key].source_id} vs {row.source_id}")
                warnings.append(f"Duplicate agreeing cell {key} from {row.source_id}; first kept")
                continue
            cells[key] = row
        for row in res.context:
            key = (row.indicator_id, row.geo_level, row.geo_code, row.year)
            if key not in context:
                context[key] = row
        sources.extend(res.sources)
        inputs.extend(res.inputs)
        warnings.extend(res.warnings)
    store = ControlStore(tables, list(cells.values()), list(context.values()), sources, utc_now(), inputs, warnings)
    return store, report


def describe_inputs(store: ControlStore) -> str:
    return sha256_bytes(repr(sorted((i["path"], i["sha256"]) for i in store.inputs)).encode())
