"""Build descriptors for the supplied population fixtures.

A build descriptor describes an existing file; registering it never generates anything.
The base and v2 files are two versions of the same residents, so they get distinct IDs and
are never concatenated.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from societytwin import SYNTHETIC_POPULATION_LABEL
from societytwin.common import canonical_hash
from societytwin.config import ExperimentLayout
from societytwin.population.fixtures import BASE_FIELDS, V2_FIELDS, PopulationTable, ReferenceTable

UNAVAILABLE_FIELDS: dict[str, str] = {
    "exact_age": "Rows hold five-year age bands only; exact ages were never generated.",
    "income": "No income table was used; the field does not exist in these rows.",
    "education": "No education table was used; the field does not exist in these rows.",
    "occupation": "No labour or occupation table was used; the field does not exist in these rows.",
    "household": "Households are not linked or generated in these rows.",
    "district": "Rows carry no district; the build scope is a single province.",
    "nuts_region": "No NUTS mapping exists for these rows.",
    "personality": "No personality, values or preferences are modelled.",
}


@dataclass(frozen=True)
class BuildSource:
    variant: str
    relative_path: str
    fields: tuple[str, ...]
    schema_version: str
    method: str
    is_default: bool


def build_sources(layout: ExperimentLayout) -> tuple[BuildSource, ...]:
    return (
        BuildSource(
            variant="base",
            relative_path=layout.base_population,
            fields=BASE_FIELDS,
            schema_version="fixture-base-columns-1",
            method=(
                "Weighted random draws with replacement (Python random.choices) from the joint "
                "age-group × sex cells of the processed age/sex reference table; IDs assigned in draw order."
            ),
            is_default=False,
        ),
        BuildSource(
            variant="v2",
            relative_path=layout.v2_population,
            fields=V2_FIELDS,
            schema_version="fixture-v2-columns-1",
            method=(
                "The base rows plus marital status: for ages 15+, one weighted draw from the marital-status "
                "distribution conditioned on sex only (gender_only); under-15 rows are set to not_applicable. "
                "Age and marital status are not sampled jointly."
            ),
            is_default=True,
        ),
    )


def read_configured_seed(generator_source: Path) -> tuple[int | None, str]:
    """Read the SEED constant without executing the generator (mirrors the persona adapter)."""
    if not generator_source.is_file():
        return None, "Generator source is not present in this fixture directory; no seed evidence."
    try:
        tree = ast.parse(generator_source.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None, "Generator source could not be parsed; no seed evidence."
    seeds = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "SEED" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    if len(seeds) != 1 or not isinstance(seeds[0], int):
        return None, "No single integer SEED constant found in the generator source."
    return seeds[0], (
        "Configured constant SEED read statically from the generator source (not executed). Seeds are not "
        "stored per row. In the generator CLI, --seed controls only the marital enrichment stage; the base "
        "rows are read from the existing base file."
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "build"


def make_build_id(source: BuildSource, table: PopulationTable, scope_province: str) -> str:
    digest = canonical_hash({"schema_version": source.schema_version, "fields": list(source.fields),
                             "source_sha256": table.sha256})
    return f"{_slug(scope_province)}-{table.row_count}-{source.variant}-{digest[:12]}"


def describe_build(
    source: BuildSource,
    table: PopulationTable,
    reference: ReferenceTable,
    seed: int | None,
    seed_evidence: str,
    fixture_kind: str,
) -> dict:
    missing_cells = {(r["age_group"], r["gender"]) for r in table.rows} - {
        (r["age_group"], r["gender"]) for r in reference.rows
    }
    if missing_cells:
        raise ValueError("Population contains age/sex cells absent from the reference table; scope cannot be joined")
    available = list(source.fields)
    filterable = ["person_id", "age_group", "gender"] + (["marital_status"] if "marital_status" in available else [])
    gaps = [
        "Original raw TÜİK files are absent from this checkout; raw-source verification is unavailable.",
        "The CSV carries no generation log, commit or timestamp; reproducibility is checked by offline re-execution in the regression tests, not by stored evidence.",
        "Rows have no geography or year columns; the scope below is joined from the reference table, not parsed from person IDs.",
    ]
    if source.variant == "v2":
        gaps.append("Marital status was conditioned on sex only; the age × marital-status relationship is not preserved.")
    return {
        "build_id": make_build_id(source, table, reference.province),
        "variant": source.variant,
        "schema_version": source.schema_version,
        "schema_note": "Adapter schema for this fixture file; not the proposed tr-persona-1 schema.",
        "source_path": source.relative_path,
        "source_sha256": table.sha256,
        "source_bytes": table.byte_size,
        "row_count": table.row_count,
        "available_fields": available,
        "filterable_fields": filterable,
        "unavailable_fields": [{"field": k, "reason": v} for k, v in UNAVAILABLE_FIELDS.items()],
        "scope": {
            "province": reference.province,
            "reference_year": reference.year,
            "evidence": (
                f"Joined from the processed reference table {reference.name} (sha256 {reference.sha256[:12]}…), "
                "whose year and province columns describe the cells the generator sampled from."
            ),
        },
        "generator": {"method": source.method, "configured_seed": seed, "seed_evidence": seed_evidence},
        "origin": fixture_kind,
        "is_default": source.is_default,
        "evidence_gaps": gaps,
        "synthetic_label": SYNTHETIC_POPULATION_LABEL,
    }
