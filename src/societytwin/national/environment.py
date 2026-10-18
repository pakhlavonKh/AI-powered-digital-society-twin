"""ProvinceEnvironment: province-level context, kept separate from person attributes.

Only indicators present in the control store are reported. For each indicator the value at the
reference year is the latest observation not after it; its own source year is always shown, and
nothing is interpolated or carried forward silently. Datasets that do not cover the province are
listed as STRUCTURALLY_UNAVAILABLE, which is different from a reported zero.
"""

from __future__ import annotations

from societytwin.national import geography as geo
from societytwin.national.controls import TABLE_KINDS, ControlStore
from societytwin.national.vocab import ValueStatus

DOMAINS = ("demographics", "economy", "education", "households", "housing", "health", "migration", "mobility",
           "urbanization", "environment", "justice", "other")


def province_environment(store: ControlStore, province_code: str, reference_year: int) -> dict:
    p = geo.province(province_code)
    grouped: dict[str, list] = {}
    for row in store.context_for(p):
        grouped.setdefault(row.indicator_id, []).append(row)
    domains: dict[str, list[dict]] = {d: [] for d in DOMAINS}
    for indicator_id, rows in sorted(grouped.items()):
        rows.sort(key=lambda r: r.year)
        usable = [r for r in rows if r.year <= reference_year]
        current = next((r for r in reversed(usable) if r.value_status == ValueStatus.OBSERVED), usable[-1] if usable else None)
        first = rows[0]
        entry = {
            "indicator_id": indicator_id, "label": first.label_en, "label_tr": first.label_tr or None, "unit": first.unit,
            "value": current.value if current else None,
            "value_status": current.value_status if current else "NOT_AVAILABLE_FOR_REFERENCE_YEAR",
            "source_year": current.year if current else None,
            "years_from_reference": (reference_year - current.year) if current else None,
            "geo_level": current.geo_level if current else first.geo_level,
            "source_id": (current or first).source_id, "source_ref": (current or first).source_ref,
            "history": [{"year": r.year, "value": r.value, "value_status": r.value_status} for r in rows],
            "note": None if current else f"Only years after {reference_year} exist ({[r.year for r in rows]}); not used.",
        }
        domains.setdefault(first.theme if first.theme in DOMAINS else "other", []).append(entry)
    uncovered = []
    for src in store.sources:
        coverage = src.get("province_coverage")
        if coverage is not None and p.code not in coverage:
            uncovered.append({"source_id": src["source_id"], "title": src.get("title_en"), "theme": src.get("theme"),
                              "coverage": f"{len(coverage)}/81", "value_status": ValueStatus.STRUCTURALLY_UNAVAILABLE,
                              "note": "The dataset does not cover this province. This is not a reported zero."})
    controls = []
    for table_id, meta in store.tables.items():
        sel = store.best(table_id, p, reference_year)
        controls.append({"table_id": table_id, "attribute": TABLE_KINDS[meta.kind].attribute, "title": meta.title,
                         "available": sel is not None, "source_year": sel.year if sel else None,
                         "geo_level": sel.geo_level if sel else None})
    indicator_count = sum(len(v) for v in domains.values())
    return {
        "province": p.as_dict(), "reference_year": reference_year,
        "domains": {d: v for d, v in domains.items() if v},
        "empty_domains": [d for d, v in domains.items() if not v],
        "indicator_count": indicator_count,
        "structurally_unavailable_datasets": uncovered,
        "population_controls": controls,
        "notes": ["Environment attributes describe the province, not any synthetic person.",
                  "Each value carries its own source year; the population reference year is shown separately."],
        "empty": indicator_count == 0,
    }


def coverage_summary(store: ControlStore, reference_year: int) -> list[dict]:
    """Per-province availability of the generator's tables and of context indicators (for the map and data sources)."""
    out = []
    root_cov = set(store.provinces_with("population_age_sex", reference_year))
    for p in geo.PROVINCES:
        tables = [t for t in store.tables if store.best(t, p, reference_year) is not None]
        out.append({**p.as_dict(), "has_population_controls": p.code in root_cov, "control_tables": tables,
                    "context_indicators": len({r.indicator_id for r in store.context_for(p)})})
    return out
