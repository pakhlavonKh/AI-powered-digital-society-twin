"""Deterministic record pages and backend-computed distributions."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from societytwin.population.categories import AGE_GROUPS, CONDITIONING_VALUES, GENDERS, MARITAL_STATUSES
from societytwin.population.fixtures import PopulationTable
from societytwin.sampling.filters import FilterSpec

MAX_PAGE_SIZE = 200
SORTABLE = ("person_id", "age_group", "gender", "marital_status")
GROUPABLE = ("age_group", "gender", "marital_status", "marital_status_conditioning")
CATEGORY_ORDER: dict[str, tuple[str, ...]] = {
    "age_group": AGE_GROUPS,
    "gender": GENDERS,
    "marital_status": MARITAL_STATUSES,
    "marital_status_conditioning": CONDITIONING_VALUES,
}
SortField = Literal["person_id", "age_group", "gender", "marital_status"]


class QueryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def filtered_rows(table: PopulationTable, spec: FilterSpec) -> list[dict[str, str]]:
    return [row for row in table.rows if spec.matches(row)]


def _sort_key(field: str):
    order = CATEGORY_ORDER.get(field)
    if order:
        rank = {value: i for i, value in enumerate(order)}
        return lambda row: rank[row[field]]
    return lambda row: row[field]


def page(rows: list[dict[str, str]], available_fields: list[str], sort: str, direction: str,
         offset: int, limit: int) -> list[dict[str, str]]:
    if sort not in SORTABLE or sort not in available_fields:
        raise QueryError("invalid_sort", f"Sorting by '{sort}' is not supported for this build")
    if direction not in {"asc", "desc"}:
        raise QueryError("invalid_sort", "direction must be asc or desc")
    if offset < 0 or not 1 <= limit <= MAX_PAGE_SIZE:
        raise QueryError("invalid_page", f"offset must be >= 0 and limit within 1..{MAX_PAGE_SIZE}")
    # Stable two-pass sort: person_id ascending is always the final tie-breaker.
    ordered = sorted(rows, key=lambda r: r["person_id"])
    if sort != "person_id":
        ordered = sorted(ordered, key=_sort_key(sort), reverse=direction == "desc")
    elif direction == "desc":
        ordered.reverse()
    return ordered[offset: offset + limit]


def distributions(rows: list[dict[str, str]], available_fields: list[str], group_by: list[str]) -> list[dict]:
    result = []
    denominator = len(rows)
    for field in group_by:
        if field not in GROUPABLE:
            raise QueryError("unknown_group_by", f"Cannot group by '{field}'")
        if field not in available_fields:
            raise QueryError("field_unavailable", f"Field '{field}' does not exist in this build")
        counts = Counter(row[field] for row in rows)
        categories = [
            {"value": value, "count": counts.get(value, 0),
             "share": (counts.get(value, 0) / denominator) if denominator else None}
            for value in CATEGORY_ORDER[field]
        ]
        result.append({"field": field, "denominator": denominator, "categories": categories})
    return result


def crosstab(rows: list[dict[str, str]], available_fields: list[str], row_field: str, column_field: str) -> dict:
    for field in (row_field, column_field):
        if field not in GROUPABLE or field not in available_fields:
            raise QueryError("unknown_group_by", f"Cannot cross-tabulate '{field}'")
    counts = Counter((row[row_field], row[column_field]) for row in rows)
    cells = [
        {"row": r, "column": c, "count": counts.get((r, c), 0)}
        for r in CATEGORY_ORDER[row_field] for c in CATEGORY_ORDER[column_field]
    ]
    return {"row_field": row_field, "column_field": column_field, "denominator": len(rows), "cells": cells}
