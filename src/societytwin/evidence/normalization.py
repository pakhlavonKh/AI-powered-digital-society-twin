"""Statistical normalization, schema validation, and discrepancy checks (K2).

Core rules:
- Deterministic and reproducible: no network calls, no paid LLM calls, no RNG.
- Never silently coerce, drop, or "fix" inconsistent data. Flag and document it.
- Preserve published ``unknown`` / ``unclassified`` categories as explicit records.
- Missing values (``""``, ``"-"``, ``".."``, ``"c"``) are preserved with explicit
  ``ValueStatus`` (``NOT_REPORTED``, ``NOT_APPLICABLE``, ``UNKNOWN``), never silently
  converted to ``0``.
- Every check result uses one of three statuses: ``pass`` | ``fail`` | ``not_evaluable``,
  with a reason.
- National (``TR``) vs Ankara-specific (``06``) tagging is preserved on every cell
  and summary object.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from societytwin.evidence.registry import (
    ANKARA_HOUSEHOLD_DISCREPANCY_FLAG,
    CategoryDefinition,
    DataQualityFlag,
    EvidenceDatasetEntry,
    GeographyScope,
)
from societytwin.national.dependencies import TypedModel
from societytwin.national.vocab import VOCABULARIES, ValueStatus, label_key

CheckStatus = Literal["pass", "fail", "not_evaluable"]

MISSING_MARKERS: frozenset[str] = frozenset({"", "-", "..", "...", "c", "n/a", "na", "null", "none"})


class NormalizationError(ValueError):
    """Raised when a reference table violates schema, category, or scope rules in strict mode."""


class ValidationCheckResult(TypedModel):
    """Standardized 3-status check result (pass | fail | not_evaluable) with reason."""

    check_id: str = Field(min_length=1)
    status: CheckStatus
    reason: str = Field(min_length=1)
    dataset_id: str | None = None
    geography_code: str | None = None
    scope_marker: str | None = None
    year: StrictInt | str | None = None
    expected: Any = None
    observed: Any = None
    discrepancy_flag_id: str | None = None


class DataQualityIssue(TypedModel):
    """Detected or documented data-quality / statistical discrepancy record."""

    issue_id: str = Field(min_length=1)
    severity: Literal["error", "warning", "info"] = "warning"
    category: Literal[
        "schema_violation",
        "unknown_category_unmapped",
        "published_unknown_preserved",
        "missing_value_preserved",
        "category_total_mismatch",
        "denominator_inconsistency",
        "household_vs_resident_discrepancy",
        "scope_mismatch",
        "duplicate_row",
        "open_ended_tail",
    ]
    dataset_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class NormalizedRow(TypedModel):
    """Single canonical normalized cell in a reference dataset."""

    dataset_id: str = Field(min_length=1)
    geography_code: str = Field(min_length=1)
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
    dimensions: dict[str, str]
    value: float | int | None
    unit: str = Field(min_length=1)
    value_status: Literal[
        "OBSERVED",
        "NOT_REPORTED",
        "UNKNOWN",
        "NOT_APPLICABLE",
        "STRUCTURALLY_UNAVAILABLE",
    ] = "OBSERVED"
    category_kind: Literal[
        "known",
        "published_unknown",
        "residual_unclassified",
        "open_ended_tail",
        "aggregate_total",
    ] = "known"
    proportion_of_total: float | None = None
    proportion_within_group: float | None = None
    source_indicator: str | None = None

    @model_validator(mode="after")
    def check_status_and_value(self):
        if self.value_status == ValueStatus.OBSERVED:
            if self.value is None or not math.isfinite(float(self.value)) or float(self.value) < 0:
                raise ValueError("OBSERVED cell requires a finite non-negative numeric value")
        else:
            if self.value is not None:
                raise ValueError(f"Non-OBSERVED cell ({self.value_status}) must have value=None, never 0")
        if self.is_national and self.is_ankara_specific:
            raise ValueError("NormalizedRow cannot be both is_national and is_ankara_specific")
        return self


class DistributionSummary(TypedModel):
    """Normalized probability distribution over observed cells."""

    dataset_id: str = Field(min_length=1)
    geography_code: str = Field(min_length=1)
    scope_marker: str = Field(min_length=1)
    year: StrictInt | str
    grouping_dimensions: tuple[str, ...] = ()
    target_dimension: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    total_observed_mass: float
    includes_published_unknown: StrictBool = False
    published_unknown_mass: float = 0.0
    missing_cell_count: StrictInt = 0
    cell_probabilities: dict[str, float] = Field(default_factory=dict)
    conditional_probabilities: dict[str, dict[str, float]] = Field(default_factory=dict)


class NormalizationResult(TypedModel):
    """Complete output of K2 normalization, total checks, and denominator checks."""

    dataset_id: str = Field(min_length=1)
    geography: GeographyScope
    year: StrictInt | str
    unit: str = Field(min_length=1)
    denominator_universe: str = Field(min_length=1)
    rows: tuple[NormalizedRow, ...]
    published_totals: dict[str, float | int] = Field(default_factory=dict)
    computed_total: float = 0.0
    distribution: DistributionSummary | None = None
    checks: tuple[ValidationCheckResult, ...] = ()
    issues: tuple[DataQualityIssue, ...] = ()
    data_quality_flags: tuple[DataQualityFlag, ...] = ()

    @property
    def passed_all_checks(self) -> bool:
        return all(c.status != "fail" for c in self.checks)


def parse_cell_value(
    raw_value: Any,
    *,
    explicit_status: str | None = None,
    require_integer: bool = False,
) -> tuple[int | float | None, str]:
    """Parse a raw cell value without ever coercing missing/suppressed markers to zero."""
    if explicit_status is not None and explicit_status != ValueStatus.OBSERVED:
        if explicit_status not in ValueStatus.ALL:
            raise NormalizationError(f"Unsupported value_status {explicit_status!r}")
        if raw_value not in (None, "") and str(raw_value).strip().lower() not in MISSING_MARKERS:
            raise NormalizationError(
                f"Cell marked {explicit_status!r} must not carry numeric value {raw_value!r}"
            )
        return None, explicit_status

    if raw_value is None:
        return None, ValueStatus.NOT_REPORTED

    if isinstance(raw_value, bool):
        raise NormalizationError(f"Boolean value {raw_value!r} is not a valid statistical observation")

    text = str(raw_value).strip()
    if text.lower() in MISSING_MARKERS:
        return None, ValueStatus.NOT_REPORTED

    try:
        num = float(text)
    except ValueError as exc:
        raise NormalizationError(f"Non-numeric observation value {raw_value!r}") from exc

    if not math.isfinite(num) or num < 0:
        raise NormalizationError(f"Observation value must be finite and non-negative (got {raw_value!r})")

    if require_integer:
        if not num.is_integer() or ("." in text and not text.endswith(".0")):
            raise NormalizationError(f"Expected exact integer count, got {raw_value!r}")
        return int(num), ValueStatus.OBSERVED

    if num.is_integer() and "." not in text:
        return int(num), ValueStatus.OBSERVED
    return num, ValueStatus.OBSERVED


def normalize_category(
    dimension: str,
    raw_label: str,
    entry: EvidenceDatasetEntry,
) -> tuple[str, Literal["known", "published_unknown", "residual_unclassified", "open_ended_tail", "aggregate_total"]]:
    """Map a source category label to its canonical code, preserving 'unknown' and failing on unmapped labels."""
    cleaned = str(raw_label).strip()
    if not cleaned:
        raise NormalizationError(f"Empty category label for dimension {dimension!r} in {entry.dataset_id}")

    # 1. Explicit retrieval category_label_map
    label_map = entry.retrieval_info.category_label_map
    if cleaned in label_map:
        cleaned = label_map[cleaned]

    # 2. Age group underscore normalization (e.g. '0_4' -> '0-4', '90_plus' -> '90+')
    if dimension == "age_group":
        if cleaned == "90_plus":
            cleaned = "90+"
        elif "_" in cleaned and all(p.isdigit() for p in cleaned.split("_", 1)):
            cleaned = cleaned.replace("_", "-", 1)

    # 3. Check entry.category_definitions if defined for this dimension
    cat_defs = entry.category_definitions.get(dimension)
    if cat_defs:
        key = label_key(cleaned)
        for cdef in cat_defs:
            candidate_keys = {label_key(cdef.code), label_key(cdef.label_en)}
            if cdef.label_tr:
                candidate_keys.add(label_key(cdef.label_tr))
            candidate_keys.update(label_key(a) for a in cdef.source_aliases)
            if key in candidate_keys:
                return cdef.code, cdef.kind
        raise NormalizationError(
            f"Unmapped category {raw_label!r} for dimension {dimension!r} in dataset {entry.dataset_id!r}. "
            f"Allowed codes: {[c.code for c in cat_defs]}"
        )

    # 4. Fallback to canonical VOCABULARIES if dimension is a standard vocabulary
    if dimension in VOCABULARIES:
        try:
            code = VOCABULARIES[dimension].from_source(cleaned)
        except ValueError as exc:
            raise NormalizationError(
                f"Unmapped vocabulary label {raw_label!r} for {dimension!r} in {entry.dataset_id!r}"
            ) from exc
        kind: Literal["known", "published_unknown", "residual_unclassified", "open_ended_tail", "aggregate_total"] = "known"
        if code == "unknown":
            kind = "published_unknown"
        elif code in ("10+", "90+"):
            kind = "open_ended_tail"
        return code, kind

    # 5. Free-form known dimensions (e.g., district_name, statistic)
    return cleaned, "known"


def compute_distribution(
    rows: tuple[NormalizedRow, ...],
    entry: EvidenceDatasetEntry,
    *,
    target_dimension: str | None = None,
    grouping_dimensions: tuple[str, ...] | None = None,
) -> tuple[ tuple[NormalizedRow, ...], DistributionSummary ]:
    """Compute marginal and conditional distributions while preserving published_unknown cells."""
    non_geo_dims = tuple(d for d in entry.dimensions if d != "province_code")
    if target_dimension is None:
        target_dimension = non_geo_dims[-1] if non_geo_dims else entry.dimensions[-1]
    if grouping_dimensions is None:
        grouping_dimensions = tuple(d for d in non_geo_dims if d != target_dimension)

    observed_rows = [r for r in rows if r.value_status == ValueStatus.OBSERVED and r.value is not None]
    missing_count = sum(1 for r in rows if r.value_status != ValueStatus.OBSERVED)
    total_mass = math.fsum(float(r.value) for r in observed_rows)

    unknown_mass = math.fsum(
        float(r.value)
        for r in observed_rows
        if r.category_kind in ("published_unknown", "residual_unclassified")
        or r.dimensions.get(target_dimension) == "unknown"
    )
    includes_unknown = unknown_mass > 0 or any(
        r.category_kind in ("published_unknown", "residual_unclassified") for r in rows
    )

    # Group totals for conditional probabilities
    group_totals: dict[str, float] = {}
    for r in observed_rows:
        g_key = "|".join(f"{d}={r.dimensions.get(d, '')}" for d in grouping_dimensions) if grouping_dimensions else "__all__"
        group_totals[g_key] = group_totals.get(g_key, 0.0) + float(r.value)

    updated_rows: list[NormalizedRow] = []
    cell_probs: dict[str, float] = {}
    cond_probs: dict[str, dict[str, float]] = {}

    for r in rows:
        if r.value_status == ValueStatus.OBSERVED and r.value is not None and total_mass > 0:
            p_tot = float(r.value) / total_mass
            g_key = "|".join(f"{d}={r.dimensions.get(d, '')}" for d in grouping_dimensions) if grouping_dimensions else "__all__"
            g_tot = group_totals.get(g_key, 0.0)
            p_grp = (float(r.value) / g_tot) if g_tot > 0 else None
            cell_label = "|".join(f"{d}={v}" for d, v in r.dimensions.items() if d != "province_code")
            cell_probs[cell_label] = cell_probs.get(cell_label, 0.0) + p_tot
            if grouping_dimensions and p_grp is not None:
                tgt_val = r.dimensions.get(target_dimension, "")
                cond_probs.setdefault(g_key, {})[tgt_val] = p_grp
            updated_rows.append(
                r.model_copy(update={"proportion_of_total": p_tot, "proportion_within_group": p_grp})
            )
        else:
            updated_rows.append(r)

    summary = DistributionSummary(
        dataset_id=entry.dataset_id,
        geography_code=entry.geography.code,
        scope_marker=entry.geography.scope_marker,
        year=entry.year,
        grouping_dimensions=grouping_dimensions,
        target_dimension=target_dimension,
        unit=entry.unit,
        total_observed_mass=total_mass,
        includes_published_unknown=includes_unknown,
        published_unknown_mass=unknown_mass,
        missing_cell_count=missing_count,
        cell_probabilities=cell_probs,
        conditional_probabilities=cond_probs,
    )
    return tuple(updated_rows), summary


def validate_category_totals(
    rows: tuple[NormalizedRow, ...],
    entry: EvidenceDatasetEntry,
    *,
    published_totals: dict[str, float | int] | None = None,
    rel_tol: float = 1e-9,
    abs_tol: float = 1e-6,
) -> tuple[list[ValidationCheckResult], list[DataQualityIssue]]:
    """Verify that normalized category cells sum to published totals and expected_total."""
    checks: list[ValidationCheckResult] = []
    issues: list[DataQualityIssue] = []
    published_totals = published_totals or {}

    observed_rows = [r for r in rows if r.value_status == ValueStatus.OBSERVED and r.value is not None]
    computed_total = math.fsum(float(r.value) for r in observed_rows)

    # 1. Check against entry.denominator.expected_total (when unit is person or household)
    expected_total = entry.denominator.expected_total
    if expected_total is not None and entry.unit in ("person", "household"):
        if math.isclose(computed_total, float(expected_total), rel_tol=rel_tol, abs_tol=abs_tol):
            checks.append(
                ValidationCheckResult(
                    check_id=f"{entry.dataset_id}:expected_total_match",
                    status="pass",
                    reason=f"Category sum ({computed_total:,.0f}) matches expected denominator total ({expected_total:,.0f}).",
                    dataset_id=entry.dataset_id,
                    geography_code=entry.geography.code,
                    scope_marker=entry.geography.scope_marker,
                    year=entry.year,
                    expected=expected_total,
                    observed=computed_total,
                )
            )
        else:
            diff = computed_total - float(expected_total)
            checks.append(
                ValidationCheckResult(
                    check_id=f"{entry.dataset_id}:expected_total_match",
                    status="fail",
                    reason=(
                        f"Category sum ({computed_total:,.2f}) does NOT equal expected denominator total "
                        f"({expected_total:,.2f}); discrepancy = {diff:+,.2f}."
                    ),
                    dataset_id=entry.dataset_id,
                    geography_code=entry.geography.code,
                    scope_marker=entry.geography.scope_marker,
                    year=entry.year,
                    expected=expected_total,
                    observed=computed_total,
                )
            )
            issues.append(
                DataQualityIssue(
                    issue_id=f"{entry.dataset_id}:category_sum_vs_expected_total",
                    severity="error",
                    category="category_total_mismatch",
                    dataset_id=entry.dataset_id,
                    message=f"Category sum {computed_total} != expected_total {expected_total} (diff={diff})",
                    details={"expected_total": expected_total, "computed_total": computed_total, "diff": diff},
                )
            )

    # 2. Check against published_totals["total"] if present in source table
    if "total" in published_totals:
        pub_tot = float(published_totals["total"])
        if math.isclose(computed_total, pub_tot, rel_tol=rel_tol, abs_tol=abs_tol):
            checks.append(
                ValidationCheckResult(
                    check_id=f"{entry.dataset_id}:published_total_match",
                    status="pass",
                    reason=f"Category cells sum ({computed_total:,.0f}) equals published table total ({pub_tot:,.0f}).",
                    dataset_id=entry.dataset_id,
                    geography_code=entry.geography.code,
                    scope_marker=entry.geography.scope_marker,
                    year=entry.year,
                    expected=pub_tot,
                    observed=computed_total,
                )
            )
        else:
            diff = computed_total - pub_tot
            checks.append(
                ValidationCheckResult(
                    check_id=f"{entry.dataset_id}:published_total_match",
                    status="fail",
                    reason=(
                        f"Category cells sum ({computed_total:,.2f}) does NOT equal published table total "
                        f"({pub_tot:,.2f}); discrepancy = {diff:+,.2f}."
                    ),
                    dataset_id=entry.dataset_id,
                    geography_code=entry.geography.code,
                    scope_marker=entry.geography.scope_marker,
                    year=entry.year,
                    expected=pub_tot,
                    observed=computed_total,
                )
            )
            issues.append(
                DataQualityIssue(
                    issue_id=f"{entry.dataset_id}:category_sum_vs_published_total",
                    severity="error",
                    category="category_total_mismatch",
                    dataset_id=entry.dataset_id,
                    message=f"Category cells sum {computed_total} != published total {pub_tot} (diff={diff})",
                    details={"published_total": pub_tot, "computed_total": computed_total, "diff": diff},
                )
            )

    # 3. Check sex-specific totals if expected_by_sex or published sex totals exist
    for sex_code in ("male", "female"):
        sex_rows = [r for r in observed_rows if r.dimensions.get("sex") == sex_code]
        if not sex_rows:
            continue
        sex_sum = math.fsum(float(r.value) for r in sex_rows)
        exp_sex = entry.denominator.expected_by_sex.get(sex_code)
        pub_sex = published_totals.get(f"sex:{sex_code}")
        target_sex = pub_sex if pub_sex is not None else exp_sex
        if target_sex is not None:
            if math.isclose(sex_sum, float(target_sex), rel_tol=rel_tol, abs_tol=abs_tol):
                checks.append(
                    ValidationCheckResult(
                        check_id=f"{entry.dataset_id}:sex_total_match:{sex_code}",
                        status="pass",
                        reason=f"Category sum for sex={sex_code} ({sex_sum:,.0f}) matches target ({float(target_sex):,.0f}).",
                        dataset_id=entry.dataset_id,
                        geography_code=entry.geography.code,
                        scope_marker=entry.geography.scope_marker,
                        year=entry.year,
                        expected=target_sex,
                        observed=sex_sum,
                    )
                )
            else:
                diff = sex_sum - float(target_sex)
                checks.append(
                    ValidationCheckResult(
                        check_id=f"{entry.dataset_id}:sex_total_match:{sex_code}",
                        status="fail",
                        reason=f"Category sum for sex={sex_code} ({sex_sum:,.2f}) != target ({float(target_sex):,.2f}); diff={diff:+,.2f}.",
                        dataset_id=entry.dataset_id,
                        geography_code=entry.geography.code,
                        scope_marker=entry.geography.scope_marker,
                        year=entry.year,
                        expected=target_sex,
                        observed=sex_sum,
                    )
                )
                issues.append(
                    DataQualityIssue(
                        issue_id=f"{entry.dataset_id}:sex_total_mismatch:{sex_code}",
                        severity="error",
                        category="category_total_mismatch",
                        dataset_id=entry.dataset_id,
                        message=f"Sex={sex_code} sum {sex_sum} != target {target_sex}",
                        details={"sex": sex_code, "expected": target_sex, "observed": sex_sum, "diff": diff},
                    )
                )

    return checks, issues


def detect_denominator_inconsistency(
    rows: tuple[NormalizedRow, ...],
    entry: EvidenceDatasetEntry,
    *,
    root_population_total: int | float = 5910320,
    root_population_15plus: int | float = 4856106,
    published_extra_metrics: dict[str, float] | None = None,
) -> tuple[list[ValidationCheckResult], list[DataQualityIssue]]:
    """Detect and document denominator/universe differences vs the Ankara ADNKS root population.

    Never forces inconsistent denominators to match; flags them explicitly with their
    exact empirical gap and root-cause explanation.
    """
    checks: list[ValidationCheckResult] = []
    issues: list[DataQualityIssue] = []
    published_extra_metrics = published_extra_metrics or {}

    observed_rows = [r for r in rows if r.value_status == ValueStatus.OBSERVED and r.value is not None]
    computed_total = math.fsum(float(r.value) for r in observed_rows)

    # Case A: Household-unit datasets in Ankara (1,987,216 households vs 5,910,320 residents)
    if entry.unit == "household" and entry.geography.code == "06":
        avg_hh_size = published_extra_metrics.get("average_household_size", 2.86361774462363)
        implied_private_pop = round(computed_total * avg_hh_size)
        gap_vs_residents = int(root_population_total) - implied_private_pop
        checks.append(
            ValidationCheckResult(
                check_id=f"{entry.dataset_id}:household_vs_resident_population_reconciliation",
                status="not_evaluable",
                reason=(
                    f"Dataset {entry.dataset_id!r} has unit='household' (observed={computed_total:,.0f} private "
                    f"households; implied private-household population = {implied_private_pop:,.0f} at average size "
                    f"{avg_hh_size:.6f}), which does not reconcile to total ADNKS resident population "
                    f"({root_population_total:,.0f} persons; unreconciled gap = {gap_vs_residents:,.0f} persons / "
                    f"{gap_vs_residents / root_population_total * 100:.2f}%) due to institutional/collective "
                    f"households and the open-ended 10+ tail. Documented per D1; never forced to match."
                ),
                dataset_id=entry.dataset_id,
                geography_code=entry.geography.code,
                scope_marker=entry.geography.scope_marker,
                year=entry.year,
                expected={"resident_population": root_population_total, "private_households": 1987216},
                observed={
                    "private_households": computed_total,
                    "average_household_size": avg_hh_size,
                    "implied_private_household_population": implied_private_pop,
                    "unreconciled_gap_persons": gap_vs_residents,
                },
                discrepancy_flag_id=ANKARA_HOUSEHOLD_DISCREPANCY_FLAG.flag_id,
            )
        )
        issues.append(
            DataQualityIssue(
                issue_id=f"{entry.dataset_id}:D1_ankara_household_vs_resident_gap",
                severity="warning",
                category="household_vs_resident_discrepancy",
                dataset_id=entry.dataset_id,
                message=ANKARA_HOUSEHOLD_DISCREPANCY_FLAG.summary,
                details={
                    "private_households": int(computed_total),
                    "average_household_size": avg_hh_size,
                    "implied_private_household_population": implied_private_pop,
                    "adnks_resident_population": int(root_population_total),
                    "gap_persons": gap_vs_residents,
                },
            )
        )
        return checks, issues

    # Case B: National (TR) datasets cannot be compared to Ankara's denominator
    if entry.geography.is_national:
        checks.append(
            ValidationCheckResult(
                check_id=f"{entry.dataset_id}:root_denominator_reconciliation",
                status="not_evaluable",
                reason=(
                    f"Dataset {entry.dataset_id!r} has National (TR) scope "
                    f"({entry.geography.scope_marker}); its denominator ({entry.denominator.universe}) "
                    f"is national and cannot be reconciled to Ankara (06) resident totals."
                ),
                dataset_id=entry.dataset_id,
                geography_code=entry.geography.code,
                scope_marker=entry.geography.scope_marker,
                year=entry.year,
            )
        )
        return checks, issues

    # Case C: Person-unit Ankara datasets
    if entry.unit == "person" and entry.geography.code in ("06", "06_districts"):
        target_root = root_population_15plus if entry.denominator.min_age == 15 else root_population_total
        root_label = "ADNKS 15+ population" if entry.denominator.min_age == 15 else "ADNKS total resident population"
        diff = float(target_root) - computed_total

        if math.isclose(computed_total, float(target_root), rel_tol=1e-9, abs_tol=1e-6):
            checks.append(
                ValidationCheckResult(
                    check_id=f"{entry.dataset_id}:root_denominator_reconciliation",
                    status="pass",
                    reason=f"Dataset denominator ({computed_total:,.0f}) reconciles exactly to Ankara {root_label} ({target_root:,.0f}).",
                    dataset_id=entry.dataset_id,
                    geography_code=entry.geography.code,
                    scope_marker=entry.geography.scope_marker,
                    year=entry.year,
                    expected=target_root,
                    observed=computed_total,
                )
            )
        elif not entry.denominator.reconciles_to_root_population and entry.denominator.expected_gap_vs_root is not None:
            # Known documented universe gap (e.g., NESD education 15+ gap = 104,983; foreign residents; projections)
            exp_gap = float(entry.denominator.expected_gap_vs_root)
            if math.isclose(abs(diff), exp_gap, rel_tol=1e-6, abs_tol=1.0):
                flag_id = entry.data_quality_flags[0].flag_id if entry.data_quality_flags else None
                checks.append(
                    ValidationCheckResult(
                        check_id=f"{entry.dataset_id}:root_denominator_reconciliation",
                        status="not_evaluable",
                        reason=(
                            f"Documented universe difference: {entry.dataset_id} total ({computed_total:,.0f}) "
                            f"differs from Ankara {root_label} ({target_root:,.0f}) by {diff:,.0f} persons. "
                            f"Reason: {entry.denominator.inconsistency_reason}"
                        ),
                        dataset_id=entry.dataset_id,
                        geography_code=entry.geography.code,
                        scope_marker=entry.geography.scope_marker,
                        year=entry.year,
                        expected=target_root,
                        observed=computed_total,
                        discrepancy_flag_id=flag_id,
                    )
                )
                issues.append(
                    DataQualityIssue(
                        issue_id=f"{entry.dataset_id}:documented_denominator_gap",
                        severity="warning",
                        category="denominator_inconsistency",
                        dataset_id=entry.dataset_id,
                        message=(
                            f"Denominator ({computed_total:,.0f}) differs from {root_label} ({target_root:,.0f}) "
                            f"by {diff:,.0f} persons: {entry.denominator.inconsistency_reason}"
                        ),
                        details={
                            "dataset_total": computed_total,
                            "root_target": target_root,
                            "gap": diff,
                            "universe": entry.denominator.universe,
                        },
                    )
                )
            else:
                checks.append(
                    ValidationCheckResult(
                        check_id=f"{entry.dataset_id}:root_denominator_reconciliation",
                        status="fail",
                        reason=(
                            f"Unexpected denominator discrepancy: {entry.dataset_id} total ({computed_total:,.0f}) "
                            f"differs from Ankara {root_label} ({target_root:,.0f}) by {diff:,.0f} "
                            f"(expected documented gap was {exp_gap:,.0f})."
                        ),
                        dataset_id=entry.dataset_id,
                        geography_code=entry.geography.code,
                        scope_marker=entry.geography.scope_marker,
                        year=entry.year,
                        expected=target_root - exp_gap,
                        observed=computed_total,
                    )
                )
                issues.append(
                    DataQualityIssue(
                        issue_id=f"{entry.dataset_id}:unexpected_denominator_mismatch",
                        severity="error",
                        category="denominator_inconsistency",
                        dataset_id=entry.dataset_id,
                        message=f"Unexpected denominator gap {diff} (expected {exp_gap})",
                        details={"dataset_total": computed_total, "root_target": target_root, "gap": diff},
                    )
                )
        else:
            checks.append(
                ValidationCheckResult(
                    check_id=f"{entry.dataset_id}:root_denominator_reconciliation",
                    status="fail",
                    reason=(
                        f"Undocumented denominator mismatch: {entry.dataset_id} total ({computed_total:,.0f}) "
                        f"does not match Ankara {root_label} ({target_root:,.0f}); gap = {diff:+,.0f}."
                    ),
                    dataset_id=entry.dataset_id,
                    geography_code=entry.geography.code,
                    scope_marker=entry.geography.scope_marker,
                    year=entry.year,
                    expected=target_root,
                    observed=computed_total,
                )
            )
            issues.append(
                DataQualityIssue(
                    issue_id=f"{entry.dataset_id}:undocumented_denominator_mismatch",
                    severity="error",
                    category="denominator_inconsistency",
                    dataset_id=entry.dataset_id,
                    message=f"Denominator {computed_total} != {root_label} {target_root} (gap={diff})",
                    details={"dataset_total": computed_total, "root_target": target_root, "gap": diff},
                )
            )

    return checks, issues


def normalize_reference_table(
    raw_records: list[dict[str, Any]],
    entry: EvidenceDatasetEntry,
    *,
    published_totals: dict[str, float | int] | None = None,
    published_extra_metrics: dict[str, float] | None = None,
    root_population_total: int | float = 5910320,
    root_population_15plus: int | float = 4856106,
    strict: bool = False,
) -> NormalizationResult:
    """Normalize raw extracted records into canonical NormalizedRows and run all K2 checks.

    Each raw record in ``raw_records`` is expected to contain:
    - ``dimensions``: ``dict[str, str]`` mapping each dimension name in ``entry.dimensions`` to its raw label
    - ``value``: raw value (number or string)
    - ``value_status`` (optional): explicit status string
    - ``source_indicator`` (optional): original indicator name
    """
    checks: list[ValidationCheckResult] = []
    issues: list[DataQualityIssue] = []
    normalized_rows: list[NormalizedRow] = []
    seen_keys: dict[tuple[tuple[str, str], ...], float | int | None] = {}

    require_int = entry.unit in ("person", "household")

    for idx, rec in enumerate(raw_records):
        raw_dims = rec.get("dimensions")
        if not isinstance(raw_dims, dict):
            msg = f"Row {idx} in {entry.dataset_id} is missing a 'dimensions' mapping"
            if strict:
                raise NormalizationError(msg)
            issues.append(
                DataQualityIssue(
                    issue_id=f"{entry.dataset_id}:schema_row_{idx}",
                    severity="error",
                    category="schema_violation",
                    dataset_id=entry.dataset_id,
                    message=msg,
                )
            )
            continue

        if set(raw_dims.keys()) != set(entry.dimensions):
            msg = (
                f"Row {idx} in {entry.dataset_id} has dimensions {sorted(raw_dims.keys())}, "
                f"expected {list(entry.dimensions)}"
            )
            if strict:
                raise NormalizationError(msg)
            issues.append(
                DataQualityIssue(
                    issue_id=f"{entry.dataset_id}:dimension_mismatch_row_{idx}",
                    severity="error",
                    category="schema_violation",
                    dataset_id=entry.dataset_id,
                    message=msg,
                    details={"observed_dimensions": sorted(raw_dims.keys()), "expected_dimensions": list(entry.dimensions)},
                )
            )
            checks.append(
                ValidationCheckResult(
                    check_id=f"{entry.dataset_id}:schema_dimensions",
                    status="fail",
                    reason=msg,
                    dataset_id=entry.dataset_id,
                    geography_code=entry.geography.code,
                    scope_marker=entry.geography.scope_marker,
                    year=entry.year,
                )
            )
            continue

        # Normalize each dimension's category code
        canon_dims: dict[str, str] = {}
        row_kind: Literal["known", "published_unknown", "residual_unclassified", "open_ended_tail", "aggregate_total"] = "known"
        category_failed = False

        for dim_name in entry.dimensions:
            raw_label = str(raw_dims[dim_name])
            if dim_name == "province_code":
                if entry.geography.province_code and raw_label.zfill(2) != entry.geography.province_code:
                    msg = (
                        f"Row {idx} in {entry.dataset_id} has province_code={raw_label!r}, "
                        f"expected {entry.geography.province_code!r}"
                    )
                    if strict:
                        raise NormalizationError(msg)
                    issues.append(
                        DataQualityIssue(
                            issue_id=f"{entry.dataset_id}:wrong_province_row_{idx}",
                            severity="error",
                            category="scope_mismatch",
                            dataset_id=entry.dataset_id,
                            message=msg,
                        )
                    )
                    checks.append(
                        ValidationCheckResult(
                            check_id=f"{entry.dataset_id}:geography_scope_match",
                            status="fail",
                            reason=msg,
                            dataset_id=entry.dataset_id,
                            geography_code=entry.geography.code,
                            scope_marker=entry.geography.scope_marker,
                            year=entry.year,
                        )
                    )
                    category_failed = True
                    break
                canon_dims[dim_name] = raw_label.zfill(2)
                continue

            try:
                code, kind = normalize_category(dim_name, raw_label, entry)
            except NormalizationError as exc:
                if strict:
                    raise
                issues.append(
                    DataQualityIssue(
                        issue_id=f"{entry.dataset_id}:unmapped_category_row_{idx}",
                        severity="error",
                        category="unknown_category_unmapped",
                        dataset_id=entry.dataset_id,
                        message=str(exc),
                        details={"dimension": dim_name, "raw_label": raw_label},
                    )
                )
                checks.append(
                    ValidationCheckResult(
                        check_id=f"{entry.dataset_id}:category_vocabulary:{dim_name}",
                        status="fail",
                        reason=str(exc),
                        dataset_id=entry.dataset_id,
                        geography_code=entry.geography.code,
                        scope_marker=entry.geography.scope_marker,
                        year=entry.year,
                    )
                )
                category_failed = True
                break

            canon_dims[dim_name] = code
            if kind in ("published_unknown", "residual_unclassified"):
                row_kind = kind
            elif kind == "open_ended_tail" and row_kind == "known":
                row_kind = "open_ended_tail"

        if category_failed:
            continue

        # Parse numeric value / missing marker
        try:
            val, v_status = parse_cell_value(
                rec.get("value"),
                explicit_status=rec.get("value_status"),
                require_integer=require_int,
            )
        except NormalizationError as exc:
            if strict:
                raise
            issues.append(
                DataQualityIssue(
                    issue_id=f"{entry.dataset_id}:invalid_value_row_{idx}",
                    severity="error",
                    category="schema_violation",
                    dataset_id=entry.dataset_id,
                    message=str(exc),
                )
            )
            checks.append(
                ValidationCheckResult(
                    check_id=f"{entry.dataset_id}:numeric_values_valid",
                    status="fail",
                    reason=str(exc),
                    dataset_id=entry.dataset_id,
                    geography_code=entry.geography.code,
                    scope_marker=entry.geography.scope_marker,
                    year=entry.year,
                )
            )
            continue

        key_tuple = tuple(sorted(canon_dims.items()))
        if key_tuple in seen_keys:
            prev_val = seen_keys[key_tuple]
            if prev_val == val:
                issues.append(
                    DataQualityIssue(
                        issue_id=f"{entry.dataset_id}:identical_duplicate_{len(issues)}",
                        severity="info",
                        category="duplicate_row",
                        dataset_id=entry.dataset_id,
                        message=f"Duplicate identical cell {dict(key_tuple)} with value={val} deduplicated.",
                        details={"dimensions": dict(key_tuple), "value": val},
                    )
                )
                continue
            else:
                msg = f"Conflicting duplicate cell {dict(key_tuple)}: {prev_val} vs {val}"
                if strict:
                    raise NormalizationError(msg)
                issues.append(
                    DataQualityIssue(
                        issue_id=f"{entry.dataset_id}:conflicting_duplicate_{len(issues)}",
                        severity="error",
                        category="duplicate_row",
                        dataset_id=entry.dataset_id,
                        message=msg,
                        details={"dimensions": dict(key_tuple), "first_value": prev_val, "second_value": val},
                    )
                )
                checks.append(
                    ValidationCheckResult(
                        check_id=f"{entry.dataset_id}:no_conflicting_duplicates",
                        status="fail",
                        reason=msg,
                        dataset_id=entry.dataset_id,
                        geography_code=entry.geography.code,
                        scope_marker=entry.geography.scope_marker,
                        year=entry.year,
                    )
                )
                continue

        seen_keys[key_tuple] = val

        if row_kind in ("published_unknown", "residual_unclassified"):
            issues.append(
                DataQualityIssue(
                    issue_id=f"{entry.dataset_id}:preserved_unknown_{len(issues)}",
                    severity="info",
                    category="published_unknown_preserved",
                    dataset_id=entry.dataset_id,
                    message=f"Preserved published unknown/unclassified cell {canon_dims} with value={val}.",
                    details={"dimensions": canon_dims, "value": val, "kind": row_kind},
                )
            )

        if v_status != ValueStatus.OBSERVED:
            issues.append(
                DataQualityIssue(
                    issue_id=f"{entry.dataset_id}:missing_value_{len(issues)}",
                    severity="warning",
                    category="missing_value_preserved",
                    dataset_id=entry.dataset_id,
                    message=f"Cell {canon_dims} has non-observed status {v_status} (preserved as None, not 0).",
                    details={"dimensions": canon_dims, "value_status": v_status},
                )
            )

        normalized_rows.append(
            NormalizedRow(
                dataset_id=entry.dataset_id,
                geography_code=entry.geography.code,
                scope_marker=entry.geography.scope_marker,
                is_national=entry.geography.is_national,
                is_ankara_specific=entry.geography.is_ankara_specific,
                year=entry.year,
                dimensions=canon_dims,
                value=val,
                unit=entry.unit,
                value_status=v_status,
                category_kind=row_kind,
                source_indicator=rec.get("source_indicator"),
            )
        )

    rows_tuple = tuple(normalized_rows)
    rows_with_dist, dist_summary = compute_distribution(rows_tuple, entry)

    if not any(c.check_id.startswith(f"{entry.dataset_id}:category_vocabulary") and c.status == "fail" for c in checks):
        checks.append(
            ValidationCheckResult(
                check_id=f"{entry.dataset_id}:schema_and_vocabulary",
                status="pass",
                reason=f"All {len(rows_with_dist)} normalized cells match schema, geography ({entry.geography.code}), and category vocabularies.",
                dataset_id=entry.dataset_id,
                geography_code=entry.geography.code,
                scope_marker=entry.geography.scope_marker,
                year=entry.year,
            )
        )

    tot_checks, tot_issues = validate_category_totals(
        rows_with_dist,
        entry,
        published_totals=published_totals,
    )
    checks.extend(tot_checks)
    issues.extend(tot_issues)

    denom_checks, denom_issues = detect_denominator_inconsistency(
        rows_with_dist,
        entry,
        root_population_total=root_population_total,
        root_population_15plus=root_population_15plus,
        published_extra_metrics=published_extra_metrics,
    )
    checks.extend(denom_checks)
    issues.extend(denom_issues)

    return NormalizationResult(
        dataset_id=entry.dataset_id,
        geography=entry.geography,
        year=entry.year,
        unit=entry.unit,
        denominator_universe=entry.denominator.universe,
        rows=rows_with_dist,
        published_totals=published_totals or {},
        computed_total=dist_summary.total_observed_mass,
        distribution=dist_summary,
        checks=tuple(checks),
        issues=tuple(issues),
        data_quality_flags=entry.data_quality_flags,
    )
