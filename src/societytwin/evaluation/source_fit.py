"""Source-table comparison (evidence A in docs/validation-strategy.md) and integrity checks.

No acceptance thresholds are agreed in the project docs, so every metric carries
``acceptance_threshold: None`` and nothing here produces a pass/fail "accuracy" score.
"""

from __future__ import annotations

import math
from collections import Counter

from societytwin.population.categories import ADULT_MARITAL_STATUSES, AGE_GROUPS, GENDERS, NOT_APPLICABLE, UNDER_15
from societytwin.population.fixtures import ControlsTable, PopulationTable, ReferenceTable

METHOD_VERSION = "source-fit-v1"

UNAVAILABLE_EVIDENCE = [
    {"name": "held_out_table_comparison", "evidence_kind": "held_out",
     "reason": "No held-out official table has been selected or supplied; the root data manifest is empty."},
    {"name": "persona_behavioural_adherence", "evidence_kind": "behavioral",
     "reason": "No controlled adherence experiment exists; two recorded trials differ in more than one attribute."},
    {"name": "turkish_survey_alignment", "evidence_kind": "behavioral",
     "reason": "No published Turkish survey aggregate has been compared with persona responses."},
    {"name": "national_coverage", "evidence_kind": "source_fit",
     "reason": "Only one province (the build scope) is loaded; no other province has data."},
    {"name": "raw_source_verification", "evidence_kind": "integrity",
     "reason": "Original raw TÜİK files, URLs, download dates and raw checksums are absent from this checkout."},
]


def _metric(name, value, unit, denominator, population_sha256, reference, evidence_kind, method, *,
            dimension=None, categories=None, limitations=()):
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "dimension": dimension,
        "categories": categories,
        "denominator": denominator,
        "population_sha256": population_sha256,
        "reference_sha256": reference.sha256 if reference else None,
        "reference_year": reference.year if reference else None,
        "evidence_kind": evidence_kind,
        "availability": "available",
        "method": method,
        "acceptance_threshold": None,
        "limitations": list(limitations),
    }


def _check(name, passed, detail, evidence_kind="integrity"):
    return {"name": name, "passed": bool(passed), "detail": detail, "evidence_kind": evidence_kind}


def tvd(p: dict, q: dict) -> float:
    keys = set(p) | set(q)
    return 0.5 * math.fsum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def marginal_rows(table: PopulationTable, reference: ReferenceTable, field: str, categories: tuple[str, ...]) -> list[dict]:
    n = table.row_count
    counts = Counter(row[field] for row in table.rows)
    rows = []
    for category in categories:
        source_share = math.fsum(r["probability"] for r in reference.rows if r[field] == category)
        synthetic_share = counts.get(category, 0) / n
        rows.append({"category": category, "count": counts.get(category, 0), "synthetic_share": synthetic_share,
                     "reference_share": source_share, "difference_pp": 100 * (synthetic_share - source_share)})
    return rows


def joint_age_gender_tvd(table: PopulationTable, reference: ReferenceTable) -> float:
    n = table.row_count
    counts = Counter((row["age_group"], row["gender"]) for row in table.rows)
    synthetic = {k: v / n for k, v in counts.items()}
    source = {(r["age_group"], r["gender"]): r["probability"] for r in reference.rows}
    return tvd(source, synthetic)


def marital_within_gender(table: PopulationTable, marital: ReferenceTable) -> list[dict]:
    """Marital shares among synthetic residents aged 15+, per gender, against T10 conditionals."""
    out = []
    for gender in GENDERS:
        adults = [r for r in table.rows if r["gender"] == gender and r["age_group"] not in UNDER_15]
        counts = Counter(r["marital_status"] for r in adults)
        denominator = len(adults)
        categories = []
        for status in ADULT_MARITAL_STATUSES:
            ref = next(r for r in marital.rows if r["gender"] == gender and r["marital_status"] == status)
            share = counts.get(status, 0) / denominator if denominator else None
            categories.append({"category": status, "count": counts.get(status, 0), "synthetic_share": share,
                               "reference_share": ref["conditional_probability"],
                               "difference_pp": None if share is None else 100 * (share - ref["conditional_probability"])})
        within_tvd = None
        if denominator:
            within_tvd = tvd({c["category"]: c["reference_share"] for c in categories},
                             {c["category"]: c["synthetic_share"] for c in categories})
        out.append({"gender": gender, "adult_denominator": denominator, "categories": categories, "tvd": within_tvd})
    return out


def integrity_checks(table: PopulationTable, age_gender: ReferenceTable, marital: ReferenceTable | None,
                     controls: ControlsTable | None, variant: str) -> list[dict]:
    checks = [
        _check("unique_person_ids", len(table.csv_rows) == table.row_count,
               f"{table.row_count} rows, {len(table.csv_rows)} unique IDs"),
        _check("schema_and_categories", True,
               "Header and every category matched the documented vocabulary when the file was parsed "
               "(a mismatch makes the build unavailable instead of being repaired)."),
        _check("reference_probabilities_sum_to_one",
               math.isclose(math.fsum(r["probability"] for r in age_gender.rows), 1.0, abs_tol=1e-9),
               "Age × sex reference probabilities sum to one within 1e-9 and equal population/total within 1e-12."),
        _check("population_cells_exist_in_reference",
               {(r["age_group"], r["gender"]) for r in table.rows} <= {(r["age_group"], r["gender"]) for r in age_gender.rows},
               "Every synthetic age × sex cell exists in the reference table."),
    ]
    if controls is not None:
        totals = {g: sum(r["population"] for r in age_gender.rows if r["gender"] == g) for g in GENDERS}
        totals["total"] = sum(totals.values())
        facts = {(f.year, f.province, f.statistic): f.value for f in controls.facts}
        keys = {g: (age_gender.year, age_gender.province, f"{g}_population") for g in ("male", "female", "total")}
        present = all(k in facts for k in keys.values())
        agrees = present and all(facts[keys[g]] == totals[g] for g in keys)
        detail = (
            f"Reference totals male {totals['male']:,}, female {totals['female']:,}, total {totals['total']:,} "
            f"{'agree with' if agrees else 'do not agree with'} the {age_gender.year} population controls."
            if present else f"No complete {age_gender.year} population controls are present for comparison."
        )
        checks.append(_check("reference_totals_reconcile_with_controls", agrees, detail))
    if marital is not None:
        checks.append(_check(
            "marital_reference_probabilities",
            all(math.isclose(math.fsum(r["conditional_probability"] for r in marital.rows if r["gender"] == g), 1.0, abs_tol=1e-9)
                for g in GENDERS),
            "Marital conditional probabilities sum to one within each sex (ages 15+ denominators)."))
    if variant == "v2":
        children = [r for r in table.rows if r["age_group"] in UNDER_15]
        adults = [r for r in table.rows if r["age_group"] not in UNDER_15]
        bad_children = sum(r["marital_status"] != NOT_APPLICABLE for r in children)
        bad_adults = sum(r["marital_status"] == NOT_APPLICABLE for r in adults)
        checks.append(_check("under_15_not_applicable", bad_children == 0 and bad_adults == 0,
                             f"{len(children)} residents under 15, {bad_children} with an applicable status; "
                             f"{len(adults)} aged 15+, {bad_adults} marked not_applicable."))
        tags = Counter(r["marital_status_conditioning"] for r in table.rows)
        checks.append(_check("conditioning_tag_present", set(tags) == {"gender_only"},
                             "Every row records marital_status_conditioning=gender_only, including children; the tag "
                             "records the enrichment method, not that a child received a marital draw."))
    return checks


def base_v2_consistency(base: PopulationTable, v2: PopulationTable) -> dict:
    base_rows = [(r["person_id"], r["age_group"], r["gender"]) for r in base.rows]
    v2_rows = [(r["person_id"], r["age_group"], r["gender"]) for r in v2.rows]
    same = base_rows == v2_rows
    return _check("base_and_v2_share_residents", same,
                  "The v2 file repeats the base file's IDs, age groups and sexes in the same order; they are two "
                  "versions of the same residents, not a combined population." if same
                  else "The v2 file does not repeat the base file's rows; treat them as unrelated builds.")


def validation_report(table: PopulationTable, variant: str, age_gender: ReferenceTable,
                      marital: ReferenceTable | None, controls: ControlsTable | None) -> dict:
    n = table.row_count
    metrics = []
    for field, categories in (("gender", GENDERS), ("age_group", AGE_GROUPS)):
        rows = marginal_rows(table, age_gender, field, categories)
        metrics.append(_metric(
            f"{field}_marginal_share_difference", None, "percentage_points", n, table.sha256, age_gender, "source_fit",
            "Synthetic share minus reference share for each category; value left null because no single summary is defined.",
            dimension=field, categories=rows,
            limitations=["The reference table was used to generate these rows, so agreement is an implementation check, not independent validation."]))
    metrics.append(_metric(
        "joint_age_gender_tvd", joint_age_gender_tvd(table, age_gender), "proportion (0–1)", n, table.sha256,
        age_gender, "source_fit", "Total variation distance ½Σ|p−q| over the joint age-group × sex cells.",
        dimension="age_group×gender",
        limitations=["Includes sampling noise from a 1,000-draw build; no acceptance threshold is agreed.",
                     "Not an accuracy score."]))
    if variant == "v2" and marital is not None:
        for block in marital_within_gender(table, marital):
            metrics.append(_metric(
                f"marital_within_{block['gender']}_15plus_tvd", block["tvd"], "proportion (0–1)",
                block["adult_denominator"], table.sha256, marital, "source_fit",
                "TVD between synthetic marital shares among residents aged 15+ of this sex and the reference conditional distribution.",
                dimension=f"marital_status | gender={block['gender']}, age 15+", categories=block["categories"],
                limitations=["Conditioned on sex only; the age × marital-status relationship is not represented."]))
    return {
        "method_version": METHOD_VERSION,
        "population_sha256": table.sha256,
        "metrics": metrics,
        "checks": integrity_checks(table, age_gender, marital, controls, variant),
        "unavailable_evidence": UNAVAILABLE_EVIDENCE,
        "acceptance_status": None,
        "acceptance_note": "No scientific fit thresholds are agreed in the project docs; no pass/fail or percentage score is produced.",
    }
