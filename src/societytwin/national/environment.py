"""ProvinceEnvironment: province-level context, kept separate from person attributes.

Only indicators present in the control store are reported. For each indicator the value at the
reference year is the latest observed value whose reference period ends no later than it; its own
reference period is always shown as published (a calendar year, or a multi-year period such as
``2021-2023`` that is never reduced to one year), and nothing is interpolated or carried forward
silently. Official projections are listed separately and are never the current value, even for
years up to the reference year. Datasets that do not cover the province are listed as
STRUCTURALLY_UNAVAILABLE, which is different from a reported zero; a province series that stops
before the dataset's latest period is flagged, because absent rows are not zeros either.
"""

from __future__ import annotations

from societytwin.national import geography as geo
from societytwin.national.controls import TABLE_KINDS, ContextRow, ControlStore
from societytwin.national.vocab import ValueStatus

DOMAINS = ("demographics", "economy", "education", "households", "housing", "health", "migration", "mobility",
           "urbanization", "wellbeing", "culture", "environment", "justice", "other")


def _order(r: ContextRow) -> tuple[int, int]:
    return r.period_end, r.period_start


def _point(r: ContextRow) -> dict:
    return {"period": r.period, "year": r.year, "value": r.value, "value_status": r.value_status,
            "observation_type": r.observation_type}


def province_environment(store: ControlStore, province_code: str, reference_year: int) -> dict:
    p = geo.province(province_code)
    grouped: dict[str, list] = {}
    for row in store.context_for(p):
        grouped.setdefault(row.indicator_id, []).append(row)
    last_end = store.indicator_last_period_end()
    domains: dict[str, list[dict]] = {d: [] for d in DOMAINS}
    projections: list[dict] = []
    for indicator_id, rows in sorted(grouped.items()):
        rows.sort(key=_order)
        first = rows[0]
        observed = [r for r in rows if not r.is_projection]
        projected = [r for r in rows if r.is_projection]
        if not observed:
            projections.append({"indicator_id": indicator_id, "label": first.label_en, "label_tr": first.label_tr or None,
                                "unit": first.unit, "source_id": first.source_id, "theme": first.theme,
                                "points": [_point(r) for r in projected],
                                "note": "Official projection: not an observation, never used as a current value."})
            continue
        usable = [r for r in observed if r.period_end <= reference_year]
        current = next((r for r in reversed(usable) if r.value_status == ValueStatus.OBSERVED), usable[-1] if usable else None)
        note = None
        if current is None:
            note = f"Only periods after {reference_year} exist ({[r.period for r in observed]}); not used."
        else:
            dataset_end = min(last_end.get(indicator_id, current.period_end), reference_year)
            later_blank = [r.period for r in usable if _order(r) > _order(current)]
            if current.value_status != ValueStatus.OBSERVED:
                note = "No row up to the reference year carries a number; nothing is substituted."
            elif later_blank:
                note = (f"Later row(s) {', '.join(later_blank)} carry no number ({usable[-1].value_status}); the latest reported "
                        f"value ({current.period}) is shown, not a zero.")
            elif current.period_end < dataset_end:
                note = (f"No row after {current.period} for this province, although the dataset reports this indicator up to "
                        f"{dataset_end} elsewhere; absent rows are not zero.")
        entry = {
            "indicator_id": indicator_id, "label": first.label_en, "label_tr": first.label_tr or None, "unit": first.unit,
            "value": current.value if current else None,
            "value_status": current.value_status if current else "NOT_AVAILABLE_FOR_REFERENCE_YEAR",
            "source_year": current.year if current else None,
            "source_period": current.period if current else None,
            "multi_year_period": bool(current and current.is_multi_year),
            "years_from_reference": (reference_year - current.period_end) if current else None,
            "geo_level": current.geo_level if current else first.geo_level,
            "source_id": (current or first).source_id, "source_ref": (current or first).source_ref,
            "history": [_point(r) for r in observed],
            "projections": [_point(r) for r in projected],
            "note": note,
        }
        domains.setdefault(first.theme if first.theme in DOMAINS else "other", []).append(entry)
    uncovered = []
    for src in store.sources:
        coverage = src.get("province_coverage")
        if src.get("status") == "corroborating":
            continue  # its values repeat another loaded source; not a coverage gap
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
        "projections": projections,
        "structurally_unavailable_datasets": uncovered,
        "population_controls": controls,
        "notes": ["Environment attributes describe the province, not any synthetic person.",
                  "Each value carries its own reference period (a year or a published multi-year period); the population "
                  "reference year is shown separately.",
                  "Official projections are listed separately and are never used as current observations."],
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
