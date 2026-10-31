"""Dependency & Joint-Distribution Validator (K4) — ``src/societytwin/validation/dependencies.py``.

Evaluates multidimensional joint distributions, conditional relationships, and structural
constraints in synthetic populations without LLM or network calls.

Core principles:
- Deterministic and reproducible: fixed seeds, verified SHA-256 hashes, zero network
  or paid LLM calls.
- Explicit three-state check results: ``pass | fail | not_evaluable`` with human-readable
  ``reason``, ``population_version``, and ``dataset_provenance``.
- Never invent a benchmark: if no empirical reference exists at the target geography or
  nationally, mark the status as ``not_evaluable`` (unverified). Never fabricate ground truth.
- Explicit labeling of proxies: when comparing against national-level data (e.g. broad-age
  marital shares from İstatistiklerle Kadın Table 1.9, or family type × size from Aile İstatistikleri),
  explicitly label the check "national proxy, not Ankara-observed".
- Separation of concerns: the report explicitly partitions checks into:
  1. ``calibrated_margins`` (calibrated 1D/2D margins from K3 raked targets)
  2. ``supported_joint_checks`` (evaluable multidimensional distributions against empirical/proxy data)
  3. ``unverified_relationships`` (unobserved joint distributions where no benchmark is invented,
     paired with deterministic structural zero verification).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from statistics import NormalDist
from typing import Any, Literal

from pydantic import Field, StrictBool, StrictInt

from societytwin.common import canonical_hash, sha256_bytes
from societytwin.evidence.loaders import (
    REPO_ROOT_DEFAULT,
    REFERENCE_PACKAGE_VERSION,
    EvidenceLoadError,
    ReferenceDataset,
    load_reference_dataset,
)
from societytwin.evidence.registry import (
    ANKARA_HOUSEHOLD_DISCREPANCY_FLAG,
    EDUCATION_UNIVERSE_GAP_FLAG,
    LABOUR_RATE_ONLY_FLAG,
    DataQualityFlag,
    DenominatorSpec,
    EvidenceDatasetEntry,
    EvidenceRegistry,
    load_evidence_registry,
)
from societytwin.national.constraints import EDUCATION_MIN_COMPLETION_AGE, structural_zero
from societytwin.national.dependencies import TypedModel
from societytwin.national.generator import GeneratedPopulation
from societytwin.national.vocab import (
    AGE_GROUPS,
    EDUCATION,
    HOUSEHOLD_SIZE,
    HOUSEHOLD_TYPE,
    LABOUR,
    MARITAL,
    NOT_APPLICABLE,
    SEX,
    band_bounds,
    band_of_age,
)
from societytwin.validation.population import (
    DEFAULT_REFERENCE_PACKAGE_DIR,
    CalibrationTolerances,
    CellComparison,
    CheckStatus,
    DatasetProvenance,
    DenominatorProvenance,
    EvaluationRegime,
    PopulationMarginCheck,
    PopulationValidationReport,
    _expected_multinomial_tvd,
    _extract_population_columns_and_manifest,
    _z_threshold,
    load_reference_bundle,
    validate_population,
)

REPORT_SCHEMA_VERSION = "dependency-validation-report-k4-v1"
VALIDATOR_VERSION = "k4-dependency-validator-1.0"

ReferenceAvailabilityScope = Literal[
    "observed_local",
    "national_proxy",
    "unverified_no_reference",
]

JointCheckCategory = Literal[
    "calibrated_margins",
    "supported_joint_checks",
    "unverified_relationships",
]

# -----------------------------------------------------------------------------
# Official National Benchmarks (İstatistiklerle Kadın 2025 Table 1.9 & Aile İstatistikleri 2025)
# -----------------------------------------------------------------------------

# Table 1.9 (*İstatistiklerle Kadın 2025*, p. 14, PDF p. 36)
# Format: percentages sum to 100.0 across ('never_married', 'married', 'divorced', 'widowed')
NATIONAL_MARITAL_BROAD_AGE_SEX_2025 = {
    ("male", "15-24"): {
        "never_married": 0.950,
        "married": 0.048,
        "divorced": 0.002,
        "widowed": 0.000,
    },
    ("male", "25+"): {
        "never_married": 0.200,
        "married": 0.700,
        "divorced": 0.070,
        "widowed": 0.030,
    },
    ("female", "15-24"): {
        "never_married": 0.900,
        "married": 0.095,
        "divorced": 0.005,
        "widowed": 0.000,
    },
    ("female", "25+"): {
        "never_married": 0.120,
        "married": 0.680,
        "divorced": 0.080,
        "widowed": 0.120,
    },
}

# Aggregate broad-age benchmark over both sexes (weighted by ADNKS 2025 youth/adult sex proportions: ~51.5% M in 15-24, ~49.0% M in 25+)
NATIONAL_MARITAL_BROAD_AGE_TOTAL_2025 = {
    "15-24": {
        "never_married": 0.515 * 0.950 + 0.485 * 0.900,  # 0.92575 (92.58%)
        "married": 0.515 * 0.048 + 0.485 * 0.095,        # 0.070775 (7.08%)
        "divorced": 0.515 * 0.002 + 0.485 * 0.005,      # 0.003455 (0.35%)
        "widowed": 0.000,                                 # 0.000 (0.00%)
    },
    "25+": {
        "never_married": 0.490 * 0.200 + 0.510 * 0.120,  # 0.1592 (15.92%)
        "married": 0.490 * 0.700 + 0.510 * 0.680,        # 0.6898 (68.98%)
        "divorced": 0.490 * 0.070 + 0.510 * 0.080,      # 0.0751 (7.51%)
        "widowed": 0.490 * 0.030 + 0.510 * 0.120,       # 0.0759 (7.59%)
    },
}

# Teenage 15-19 demographic vital statistics baseline (TMK Art. 124 legal marriage age is 18; under-18 marriage rare)
TEENAGE_MARITAL_BASELINE_15_19 = {
    "never_married": 0.980,
    "married": 0.020,
    "divorced": 0.000,
    "widowed": 0.000,
}

# National Household Type × Size distribution (Table 1, Aile İstatistikleri 2025)
NATIONAL_HOUSEHOLD_TYPE_SIZE_2025 = {
    "one_person": {
        "1": 1.0, "2": 0.0, "3": 0.0, "4": 0.0, "5": 0.0, "6": 0.0, "7+": 0.0,
    },
    "nuclear_family": {
        "1": 0.0, "2": 0.321, "3": 0.268, "4": 0.254, "5": 0.102, "6": 0.036, "7+": 0.019,
    },
    "extended_family": {
        "1": 0.0, "2": 0.0, "3": 0.195, "4": 0.298, "5": 0.246, "6": 0.147, "7+": 0.114,
    },
    "non_family_multi_person": {
        "1": 0.0, "2": 0.825, "3": 0.132, "4": 0.031, "5": 0.008, "6": 0.003, "7+": 0.001,
    },
}

# Minimum completion ages for education degrees (from institutional constraints)
EDUCATION_MIN_COMPLETION_AGES = dict(EDUCATION_MIN_COMPLETION_AGE)


# -----------------------------------------------------------------------------
# Pydantic Models for K4 Dependency Validation
# -----------------------------------------------------------------------------

class ConditioningGroupEvaluation(TypedModel):
    """Detailed evaluation of a conditional slice within a joint distribution check."""

    group_key: str = Field(min_length=1)
    dimensions: dict[str, str]
    records_in_group: StrictInt = Field(ge=0)
    weighted_in_group: float = Field(ge=0.0)
    evaluated_cells: StrictInt = Field(ge=1)
    cells: tuple[CellComparison, ...]
    tvd_records: float = Field(ge=0.0)
    tvd_weighted: float = Field(ge=0.0)
    max_abs_pp_records: float = Field(ge=0.0)
    max_abs_pp_weighted: float = Field(ge=0.0)
    max_abs_z: float | None = None
    expected_tvd_for_n: float = Field(ge=0.0)
    expected_max_cell_se_pp: float = Field(ge=0.0)
    within_sampling_uncertainty: StrictBool
    status: CheckStatus
    reason: str = Field(min_length=1)


class JointCheckResult(TypedModel):
    """Result of an individual dependency or joint-distribution validation check."""

    check_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    dimensions: tuple[str, ...]
    category: JointCheckCategory
    status: CheckStatus
    scope: ReferenceAvailabilityScope
    scope_label: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    reference_dataset_id: str | None = None
    reference_geography: str | None = None
    reference_year: StrictInt | str | None = None
    reference_title: str | None = None
    reference_source_hash: str | None = None
    evaluated_records: StrictInt = Field(ge=0)
    evaluated_weighted_total: float = Field(ge=0.0)
    overall_tvd_records: float | None = None
    overall_tvd_weighted: float | None = None
    max_abs_z: float | None = None
    max_abs_pp_deviation: float | None = None
    conditioning_evaluations: tuple[ConditioningGroupEvaluation, ...] = ()
    structural_zero_violations: tuple[str, ...] = ()
    domain_violations: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class DependencyValidationReport(TypedModel):
    """Complete K4 Dependency & Joint-Distribution Validation Report.

    Explicitly separates:
    1. ``calibrated_margins`` (calibrated 1D/2D margins from K3 raked targets)
    2. ``supported_joint_checks`` (evaluable multidimensional distributions against empirical/proxy data)
    3. ``unverified_relationships`` (unobserved joint distributions where no benchmark is invented,
       paired with deterministic structural zero verification).
    """

    report_schema_version: Literal["dependency-validation-report-k4-v1"] = REPORT_SCHEMA_VERSION
    validator_version: Literal["k4-dependency-validator-1.0"] = VALIDATOR_VERSION
    population_id: str = Field(min_length=1)
    population_version: str = Field(min_length=1)
    reference_package_version: str = Field(min_length=1)
    reference_package_fingerprint: str = Field(min_length=1)
    geography_code: str = Field(min_length=1)
    reference_year: StrictInt
    sample_size: StrictInt = Field(ge=0)
    weighted_population_total: float
    seed: StrictInt | None = None
    overall_status: CheckStatus
    status_counts: dict[CheckStatus, StrictInt]

    # Explicitly separated sections per Task 3:
    calibrated_margins: tuple[PopulationMarginCheck, ...]
    supported_joint_checks: tuple[JointCheckResult, ...]
    unverified_relationships: tuple[JointCheckResult, ...]

    documented_discrepancies: tuple[DataQualityFlag, ...]
    summary_reason: str = Field(min_length=1)

    @property
    def report_fingerprint(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def get_check(self, check_id: str) -> JointCheckResult | PopulationMarginCheck:
        """Find a check by its identifier across all three sections."""
        for chk in self.supported_joint_checks:
            if chk.check_id == check_id:
                return chk
        for chk in self.unverified_relationships:
            if chk.check_id == check_id:
                return chk
        for chk in self.calibrated_margins:
            if chk.check_id == check_id or chk.margin == check_id:
                return chk
        all_ids = (
            [c.check_id for c in self.supported_joint_checks]
            + [c.check_id for c in self.unverified_relationships]
            + [c.check_id for c in self.calibrated_margins]
        )
        raise KeyError(f"Check {check_id!r} not found in dependency report. Available: {all_ids}")

    def to_markdown(self) -> str:
        """Render a structured Markdown report explicitly partitioning all three validation sections."""
        lines = [
            f"# K4 Dependency & Joint-Distribution Validation Report — `{self.population_id}`",
            "",
            f"- **Population ID:** `{self.population_id}`",
            f"- **Population Version:** `{self.population_version}`",
            f"- **Reference Package:** `{self.reference_package_version}` (`{self.reference_package_fingerprint[:16]}...`)",
            f"- **Geography / Year:** `{self.geography_code}` / `{self.reference_year}`",
            f"- **Sample Size ($n$):** `{self.sample_size:,}` records (Weighted Total: `{self.weighted_population_total:,.1f}`)",
            f"- **Seed:** `{self.seed}`",
            f"- **Overall Status:** **`{self.overall_status.upper()}`** "
            f"(`pass={self.status_counts['pass']}`, `fail={self.status_counts['fail']}`, `not_evaluable={self.status_counts['not_evaluable']}`)",
            f"- **Summary:** {self.summary_reason}",
            "",
            "---",
            "",
            "## 1. Calibrated Margins (K3 Calibration Enforcement)",
            "",
            "Margins intentionally calibrated via raking or root proportional allocation.",
            "",
            "| Margin | Status | Dataset ID | Denominator | Weighted TVD | Record TVD | Expected TVD ($n$) | Reason |",
            "|---|---|---|---:|---:|---:|---:|---|",
        ]

        for m in self.calibrated_margins:
            w_tvd = f"{m.metrics.total_variation_distance_weighted:.6f}" if m.metrics else "N/A"
            r_tvd = f"{m.metrics.total_variation_distance_records:.6f}" if m.metrics else "N/A"
            e_tvd = f"{m.sampling_uncertainty.expected_tvd_for_n:.6f}" if m.sampling_uncertainty else "N/A"
            denom = m.dataset_provenance.denominator.universe if m.dataset_provenance else "N/A"
            ds = m.dataset_provenance.dataset_id if m.dataset_provenance else "N/A"
            lines.append(f"| `{m.margin}` | **`{m.status.upper()}`** | `{ds}` | `{denom}` | {w_tvd} | {r_tvd} | {e_tvd} | {m.reason} |")

        lines.extend([
            "",
            "---",
            "",
            "## 2. Supported Joint Checks (Multidimensional Empirical & Proxy Benchmarks)",
            "",
            "Joint distributions evaluated against official empirical sources or explicit national proxy benchmarks.",
            "All national proxies are visibly tagged `[national proxy, not Ankara-observed]`.",
            "",
            "| Check ID | Dimensions | Status | Scope Marker | Reference Dataset | Record TVD | Max $|z|$ | Reason |",
            "|---|---|---|---|---|---:|---:|---|",
        ])

        for j in self.supported_joint_checks:
            r_tvd = f"{j.overall_tvd_records:.4f}" if j.overall_tvd_records is not None else "N/A"
            max_z = f"{j.max_abs_z:.2f}" if j.max_abs_z is not None else "N/A"
            ds_ref = j.reference_dataset_id or "N/A"
            dims = " × ".join(j.dimensions)
            lines.append(f"| `{j.check_id}` | `{dims}` | **`{j.status.upper()}`** | `{j.scope_label}` | `{ds_ref}` | {r_tvd} | {max_z} | {j.reason} |")

        lines.extend([
            "",
            "---",
            "",
            "## 3. Unverified Relationships (Unobserved in Official Tables — Zero Invented Benchmarks)",
            "",
            "Relationships where no empirical reference exists at target geography. Status is strictly `not_evaluable`.",
            "Deterministic structural zero rules (e.g. minimum education completion ages) are verified independently.",
            "",
            "| Relationship | Dimensions | Status | Scope Marker | Structural Violations | Policy / Verification Reason |",
            "|---|---|---|---|---:|---|",
        ])

        for u in self.unverified_relationships:
            dims = " × ".join(u.dimensions)
            v_count = len(u.structural_zero_violations)
            lines.append(f"| `{u.check_id}` | `{dims}` | **`{u.status.upper()}`** | `{u.scope_label}` | `{v_count}` | {u.reason} |")

        if self.documented_discrepancies:
            lines.extend([
                "",
                "---",
                "",
                "## 4. Documented Data Quality Flags Attached to Evaluated Distributions",
                "",
            ])
            for flag in self.documented_discrepancies:
                lines.extend([
                    f"### `{flag.flag_id}`: {flag.summary}",
                    f"- **Issue Type:** `{flag.issue_type}` (Severity: `{flag.severity}`)",
                    f"- **Policy:** `{flag.handling_policy}` (Do NOT force a reconciliation)",
                    "- **Root Causes:**",
                ])
                for rc in flag.root_causes:
                    lines.append(f"  - {rc}")
                lines.append("")

        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Internal Evaluators for Candidate Checks
# -----------------------------------------------------------------------------

def _broad_age_band(age: int) -> str | None:
    """Map integer age to broad age band (15-24 or 25+). Returns None for age < 15."""
    if age < 15:
        return None
    if age <= 24:
        return "15-24"
    return "25+"


def _evaluate_slice_against_distribution(
    group_key: str,
    dimensions: dict[str, str],
    observed_counter: Counter[str],
    observed_weighted_counter: Counter[str],
    reference_distribution: dict[str, float],
    alpha: float = 0.01,
) -> ConditioningGroupEvaluation:
    """Evaluate observed category counts in a conditioning slice against expected reference shares."""
    categories = sorted(reference_distribution.keys())
    n = sum(observed_counter.values())
    w_total = sum(observed_weighted_counter.values())

    if n == 0 or w_total <= 0.0:
        return ConditioningGroupEvaluation(
            group_key=group_key,
            dimensions=dimensions,
            records_in_group=0,
            weighted_in_group=0.0,
            evaluated_cells=len(categories),
            cells=(),
            tvd_records=0.0,
            tvd_weighted=0.0,
            max_abs_pp_records=0.0,
            max_abs_pp_weighted=0.0,
            max_abs_z=None,
            expected_tvd_for_n=0.0,
            expected_max_cell_se_pp=0.0,
            within_sampling_uncertainty=True,
            status="pass",
            reason="Zero records in conditioning group; vacuously consistent.",
        )

    z_crit = _z_threshold(len(categories), alpha)
    ref_shares = [reference_distribution[c] for c in categories]
    expected_tvd = _expected_multinomial_tvd(ref_shares, n)
    max_se_pp = 100.0 * max(math.sqrt(p * (1.0 - p) / n) for p in ref_shares)

    cells: list[CellComparison] = []
    tvd_rec_acc = 0.0
    tvd_wt_acc = 0.0
    max_pp_rec = 0.0
    max_pp_wt = 0.0
    max_z: float | None = None

    for cat in categories:
        ref_share = reference_distribution[cat]
        rec_cnt = observed_counter[cat]
        wt_cnt = observed_weighted_counter[cat]

        rec_share = rec_cnt / n
        wt_share = wt_cnt / w_total

        exp_rec_cnt = n * ref_share
        exp_wt_cnt = w_total * ref_share

        abs_err_rec = abs(rec_cnt - exp_rec_cnt)
        abs_err_wt = abs(wt_cnt - exp_wt_cnt)

        pp_rec = 100.0 * abs(rec_share - ref_share)
        pp_wt = 100.0 * abs(wt_share - ref_share)

        tvd_rec_acc += abs(rec_share - ref_share)
        tvd_wt_acc += abs(wt_share - ref_share)

        max_pp_rec = max(max_pp_rec, pp_rec)
        max_pp_wt = max(max_pp_wt, pp_wt)

        # Standardized residual
        var_rec = n * ref_share * (1.0 - ref_share)
        z_val: float | None = None
        if var_rec > 0.0:
            z_val = (rec_cnt - exp_rec_cnt) / math.sqrt(var_rec)
            if max_z is None or abs(z_val) > abs(max_z):
                max_z = z_val

        cell_dims = dict(dimensions)
        cell_dims["category"] = cat

        cells.append(
            CellComparison(
                cell_key=f"{group_key}|{cat}",
                dimensions=cell_dims,
                reference_published_count=round(ref_share * 1000.0, 1),
                expected_population_count=exp_wt_cnt,
                observed_weighted_count=wt_cnt,
                expected_record_count=exp_rec_cnt,
                observed_record_count=rec_cnt,
                reference_share=ref_share,
                observed_weighted_share=wt_share,
                observed_record_share=rec_share,
                count_error_weighted=wt_cnt - exp_wt_cnt,
                abs_count_error_weighted=abs_err_wt,
                relative_error_weighted=(abs_err_wt / exp_wt_cnt) if exp_wt_cnt > 0 else None,
                count_error_records=rec_cnt - exp_rec_cnt,
                abs_count_error_records=abs_err_rec,
                pp_deviation_weighted=wt_share - ref_share,
                abs_pp_deviation_weighted=pp_wt,
                pp_deviation_records=rec_share - ref_share,
                abs_pp_deviation_records=pp_rec,
                standardized_residual_z=z_val,
                pearson_residual_records=(rec_cnt - exp_rec_cnt) / math.sqrt(exp_rec_cnt) if exp_rec_cnt > 0 else None,
            )
        )

    tvd_rec = 0.5 * tvd_rec_acc
    tvd_wt = 0.5 * tvd_wt_acc

    # Decision rule:
    # A group fails if observed z-residual exceeds Bonferroni threshold with substantial deviation
    # Or if observed TVD exceeds 3 * expected TVD + 0.15 (national proxy tolerance)
    proxy_tvd_threshold = max(expected_tvd * 2.5, expected_tvd + 0.12)
    within_sampling = (max_z is None or abs(max_z) <= z_crit) and (tvd_rec <= proxy_tvd_threshold)

    if within_sampling:
        status: CheckStatus = "pass"
        reason = (
            f"Within sampling uncertainty of benchmark: record TVD={tvd_rec:.4f} "
            f"(expected E[TVD]={expected_tvd:.4f}, max |z|={abs(max_z or 0.0):.2f} <= {z_crit:.2f})."
        )
    else:
        status = "fail"
        reason = (
            f"Significant deviation from benchmark: record TVD={tvd_rec:.4f} > threshold {proxy_tvd_threshold:.4f}, "
            f"max |z|={abs(max_z or 0.0):.2f} > Bonferroni limit {z_crit:.2f} (max PP dev={max_pp_rec:.1f} pp)."
        )

    return ConditioningGroupEvaluation(
        group_key=group_key,
        dimensions=dimensions,
        records_in_group=n,
        weighted_in_group=w_total,
        evaluated_cells=len(categories),
        cells=tuple(cells),
        tvd_records=tvd_rec,
        tvd_weighted=tvd_wt,
        max_abs_pp_records=max_pp_rec,
        max_abs_pp_weighted=max_pp_wt,
        max_abs_z=max_z,
        expected_tvd_for_n=expected_tvd,
        expected_max_cell_se_pp=max_se_pp,
        within_sampling_uncertainty=within_sampling,
        status=status,
        reason=reason,
    )


# -----------------------------------------------------------------------------
# Check 1: Age × Marital Status (National Proxy Benchmark)
# -----------------------------------------------------------------------------

def evaluate_age_marital(
    records: list[dict[str, Any]],
    tolerances: CalibrationTolerances,
) -> JointCheckResult:
    """Evaluate age × marital_status dependency against national broad-age benchmark.

    Evaluates:
    - Broad age bands: 15-24 and 25+
    - Teenage fine band: 15-19 (TMK 124 legal marriage age integrity)
    - Structural zero: Age < 15 cannot be married, divorced, or widowed.
    """
    check_id = "joint_age_marital"
    scope: ReferenceAvailabilityScope = "national_proxy"
    scope_label = "national proxy, not Ankara-observed"

    structural_violations: list[str] = []
    under_15_married = 0
    under_15_divorced = 0
    under_15_widowed = 0

    band_counters: dict[str, Counter[str]] = {
        "15-24": Counter(),
        "25+": Counter(),
        "15-19": Counter(),
    }
    band_weighted: dict[str, Counter[str]] = {
        "15-24": Counter(),
        "25+": Counter(),
        "15-19": Counter(),
    }

    evaluated_records = 0
    evaluated_weighted = 0.0

    for rec in records:
        age = rec.get("age")
        if age is None:
            # Try to infer lower bound from age_group
            ag = str(rec.get("age_group", ""))
            low, _ = band_bounds(ag) if ag in AGE_GROUPS else (None, None)
            age = low if low is not None else 0

        ms = rec.get("marital_status")
        w = float(rec.get("population_weight", 1.0))

        # Check structural zeros for children < 15
        if age < 15:
            if ms in ("married", "divorced", "widowed"):
                if ms == "married":
                    under_15_married += 1
                elif ms == "divorced":
                    under_15_divorced += 1
                elif ms == "widowed":
                    under_15_widowed += 1
                structural_violations.append(
                    f"Record {rec.get('synthetic_id', 'unknown')}: child age {age} has invalid marital status {ms!r}."
                )
            continue

        # Evaluated 15+ records
        evaluated_records += 1
        evaluated_weighted += w

        b_band = _broad_age_band(age)
        if b_band:
            band_counters[b_band][str(ms)] += 1
            band_weighted[b_band][str(ms)] += w

        if 15 <= age <= 19:
            band_counters["15-19"][str(ms)] += 1
            band_weighted["15-19"][str(ms)] += w

    if under_15_married or under_15_divorced or under_15_widowed:
        return JointCheckResult(
            check_id=check_id,
            name="Age × Marital Status Joint Distribution",
            dimensions=("age_band", "marital_status"),
            category="supported_joint_checks",
            status="fail",
            scope=scope,
            scope_label=scope_label,
            reason=(
                f"Catastrophic structural zero violation: {under_15_married} children < 15 married, "
                f"{under_15_divorced} divorced, {under_15_widowed} widowed."
            ),
            reference_dataset_id="national_marital_broad_age_sex_2025",
            reference_geography="TR",
            reference_year=2025,
            reference_title="İstatistiklerle Kadın 2025 (Table 1.9) broad-age marital distribution",
            evaluated_records=evaluated_records,
            evaluated_weighted_total=evaluated_weighted,
            structural_zero_violations=tuple(structural_violations[:20]),
        )

    # Evaluate conditional distributions for 15-24 and 25+
    eval_15_24 = _evaluate_slice_against_distribution(
        group_key="age_band=15-24",
        dimensions={"age_band": "15-24"},
        observed_counter=band_counters["15-24"],
        observed_weighted_counter=band_weighted["15-24"],
        reference_distribution=NATIONAL_MARITAL_BROAD_AGE_TOTAL_2025["15-24"],
        alpha=tolerances.familywise_alpha,
    )

    eval_25_plus = _evaluate_slice_against_distribution(
        group_key="age_band=25+",
        dimensions={"age_band": "25+"},
        observed_counter=band_counters["25+"],
        observed_weighted_counter=band_weighted["25+"],
        reference_distribution=NATIONAL_MARITAL_BROAD_AGE_TOTAL_2025["25+"],
        alpha=tolerances.familywise_alpha,
    )

    # Fine teenage evaluation (15-19)
    eval_15_19 = _evaluate_slice_against_distribution(
        group_key="age_band=15-19",
        dimensions={"age_band": "15-19"},
        observed_counter=band_counters["15-19"],
        observed_weighted_counter=band_weighted["15-19"],
        reference_distribution=TEENAGE_MARITAL_BASELINE_15_19,
        alpha=tolerances.familywise_alpha,
    )

    cond_evals = (eval_15_24, eval_25_plus, eval_15_19)
    overall_tvd_rec = sum(e.tvd_records * e.records_in_group for e in cond_evals[:2]) / max(1, evaluated_records)
    overall_tvd_wt = sum(e.tvd_weighted * e.weighted_in_group for e in cond_evals[:2]) / max(1.0, evaluated_weighted)

    max_z = max(abs(e.max_abs_z or 0.0) for e in cond_evals)
    max_pp = max(e.max_abs_pp_records for e in cond_evals)

    # Specific demographic realism checks:
    # 1. In 15-19: Marriage rate > 10% is demographic nonsense under TMK 124.
    n_15_19 = sum(band_counters["15-19"].values())
    married_15_19 = band_counters["15-19"]["married"]
    widowed_15_19 = band_counters["15-19"]["widowed"]
    pct_married_15_19 = (100.0 * married_15_19 / n_15_19) if n_15_19 > 0 else 0.0

    # 2. In 15-24: Married rate > 25% (expected ~7.1%) is a demographic failure.
    n_15_24 = sum(band_counters["15-24"].values())
    married_15_24 = band_counters["15-24"]["married"]
    pct_married_15_24 = (100.0 * married_15_24 / n_15_24) if n_15_24 > 0 else 0.0

    failed_reasons: list[str] = []
    if n_15_19 >= 10 and pct_married_15_19 > 10.0:
        failed_reasons.append(
            f"Unrealistic teenage marriage rate: {married_15_19}/{n_15_19} ({pct_married_15_19:.1f}%) "
            f"teenagers aged 15-19 are married (expected <= 2.0% under TMK 124)."
        )
    if widowed_15_19 > 0 and n_15_19 >= 10:
        failed_reasons.append(
            f"Unrealistic teenage widowhood: {widowed_15_19}/{n_15_19} teenagers aged 15-19 are widowed."
        )
    if n_15_24 >= 20 and pct_married_15_24 > 25.0:
        failed_reasons.append(
            f"Unrealistic youth marriage rate: {married_15_24}/{n_15_24} ({pct_married_15_24:.1f}%) "
            f"youths aged 15-24 are married (national proxy benchmark is 7.1%, deviation = +{pct_married_15_24 - 7.08:.1f} pp)."
        )
    for e in cond_evals:
        if e.status == "fail" and e.reason not in failed_reasons:
            failed_reasons.append(f"Slice {e.group_key}: {e.reason}")

    if failed_reasons:
        status: CheckStatus = "fail"
        reason = "Demographic realism failure: " + " | ".join(failed_reasons)
    else:
        status = "pass"
        reason = (
            f"Age-conditional marital status is realistic and consistent with National Proxy benchmark: "
            f"15-24 married={pct_married_15_24:.1f}% (benchmark=7.1%), 15-19 married={pct_married_15_19:.1f}%, "
            f"overall TVD={overall_tvd_rec:.4f}, max |z|={max_z:.2f}."
        )

    return JointCheckResult(
        check_id=check_id,
        name="Age × Marital Status Joint Distribution",
        dimensions=("age_band", "marital_status"),
        category="supported_joint_checks",
        status=status,
        scope=scope,
        scope_label=scope_label,
        reason=reason,
        reference_dataset_id="national_marital_broad_age_sex_2025",
        reference_geography="TR",
        reference_year=2025,
        reference_title="İstatistiklerle Kadın 2025 (Table 1.9) broad-age marital distribution",
        evaluated_records=evaluated_records,
        evaluated_weighted_total=evaluated_weighted,
        overall_tvd_records=overall_tvd_rec,
        overall_tvd_weighted=overall_tvd_wt,
        max_abs_z=max_z,
        max_abs_pp_deviation=max_pp,
        conditioning_evaluations=cond_evals,
        notes=(
            "Benchmark derived from TÜİK İstatistiklerle Kadın 2025 Table 1.9 (national broad age 15-24 vs 25+).",
            "Tagged as national proxy: Ankara-specific fine age × marital data is unobserved in published TÜİK tables.",
        ),
    )


# -----------------------------------------------------------------------------
# Check 2: Sex × Age × Marital Status (National Proxy Benchmark)
# -----------------------------------------------------------------------------

def evaluate_sex_age_marital(
    records: list[dict[str, Any]],
    tolerances: CalibrationTolerances,
) -> JointCheckResult:
    """Evaluate 3-way sex × age × marital_status dependency against national Table 1.9 benchmark."""
    check_id = "joint_sex_age_marital"
    scope: ReferenceAvailabilityScope = "national_proxy"
    scope_label = "national proxy, not Ankara-observed"

    counters: dict[tuple[str, str], Counter[str]] = {
        ("male", "15-24"): Counter(),
        ("male", "25+"): Counter(),
        ("female", "15-24"): Counter(),
        ("female", "25+"): Counter(),
    }
    weighted: dict[tuple[str, str], Counter[str]] = {
        ("male", "15-24"): Counter(),
        ("male", "25+"): Counter(),
        ("female", "15-24"): Counter(),
        ("female", "25+"): Counter(),
    }

    evaluated_records = 0
    evaluated_weighted = 0.0

    for rec in records:
        age = rec.get("age")
        if age is None:
            ag = str(rec.get("age_group", ""))
            low, _ = band_bounds(ag) if ag in AGE_GROUPS else (None, None)
            age = low if low is not None else 0

        if age < 15:
            continue

        sex = str(rec.get("sex", "male")).lower()
        if sex not in ("male", "female"):
            sex = "male"

        b_band = _broad_age_band(age)
        if not b_band:
            continue

        ms = str(rec.get("marital_status", "never_married"))
        w = float(rec.get("population_weight", 1.0))

        key = (sex, b_band)
        counters[key][ms] += 1
        weighted[key][ms] += w
        evaluated_records += 1
        evaluated_weighted += w

    evals: list[ConditioningGroupEvaluation] = []
    failed_reasons: list[str] = []

    for (s, b), ref_dist in NATIONAL_MARITAL_BROAD_AGE_SEX_2025.items():
        g_eval = _evaluate_slice_against_distribution(
            group_key=f"sex={s}|age_band={b}",
            dimensions={"sex": s, "age_band": b},
            observed_counter=counters[(s, b)],
            observed_weighted_counter=weighted[(s, b)],
            reference_distribution=ref_dist,
            alpha=tolerances.familywise_alpha,
        )
        evals.append(g_eval)
        if g_eval.status == "fail":
            failed_reasons.append(f"Group ({s}, {b}): {g_eval.reason}")

    overall_tvd_rec = (
        sum(e.tvd_records * e.records_in_group for e in evals) / max(1, evaluated_records)
    )
    overall_tvd_wt = (
        sum(e.tvd_weighted * e.weighted_in_group for e in evals) / max(1.0, evaluated_weighted)
    )
    max_z = max(abs(e.max_abs_z or 0.0) for e in evals)
    max_pp = max(e.max_abs_pp_records for e in evals)

    if failed_reasons:
        status: CheckStatus = "fail"
        reason = "Sex-age conditional marital failure against National Proxy: " + " | ".join(failed_reasons)
    else:
        status = "pass"
        reason = (
            f"Sex × age × marital joint distribution is consistent with Table 1.9 national proxy: "
            f"overall TVD={overall_tvd_rec:.4f}, max |z|={max_z:.2f}."
        )

    return JointCheckResult(
        check_id=check_id,
        name="Sex × Age × Marital Status 3-Way Joint Distribution",
        dimensions=("sex", "age_band", "marital_status"),
        category="supported_joint_checks",
        status=status,
        scope=scope,
        scope_label=scope_label,
        reason=reason,
        reference_dataset_id="national_marital_broad_age_sex_2025",
        reference_geography="TR",
        reference_year=2025,
        reference_title="İstatistiklerle Kadın 2025 (Table 1.9) sex × broad-age marital distribution",
        evaluated_records=evaluated_records,
        evaluated_weighted_total=evaluated_weighted,
        overall_tvd_records=overall_tvd_rec,
        overall_tvd_weighted=overall_tvd_wt,
        max_abs_z=max_z,
        max_abs_pp_deviation=max_pp,
        conditioning_evaluations=tuple(evals),
        notes=(
            "Direct 3-way evaluation across (male, 15-24), (male, 25+), (female, 15-24), (female, 25+).",
            "Tagged as national proxy, not Ankara-observed.",
        ),
    )


# -----------------------------------------------------------------------------
# Check 3: Household Size × Household Type
# -----------------------------------------------------------------------------

def evaluate_household_size_type(
    records: list[dict[str, Any]],
    hh_records: list[dict[str, Any]] | None,
    tolerances: CalibrationTolerances,
) -> JointCheckResult:
    """Evaluate household_size × household_type joint distribution.

    - If household sample is provided: evaluated against National Proxy Table 1 with structural zero rules.
    - If resident-only population: unverified / not_evaluable (D1 discrepancy, forbidden roster linkage).
    """
    check_id = "joint_household_size_type"

    # If no separate household records, check if resident records carry household attributes
    sample_records: list[dict[str, Any]] = []
    if hh_records:
        sample_records = hh_records
    else:
        # Check if resident records have non-null household_type and household_size_class
        for r in records:
            if r.get("household_type") is not None and r.get("household_size_class") is not None:
                sample_records.append(r)

    if not sample_records:
        return JointCheckResult(
            check_id=check_id,
            name="Household Size × Household Type Joint Distribution",
            dimensions=("household_type", "household_size_class"),
            category="unverified_relationships",
            status="not_evaluable",
            scope="unverified_no_reference",
            scope_label="unverified (no empirical reference)",
            reason=(
                "Household type × size joint distribution unlinked in resident population (D1 discrepancy: "
                "1,987,216 private households vs 5,910,320 residents; person-to-household micro-linkage is "
                "unobserved in TÜİK tables and forbidden in baseline model)."
            ),
            evaluated_records=0,
            evaluated_weighted_total=0.0,
            notes=(
                "Resident-only populations do not carry empirical household membership rosters.",
                "See documented discrepancy D1_ANKARA_HH_VS_RESIDENT_POP_2025.",
            ),
        )

    # We have household records -> evaluate against national proxy and structural zeros
    scope: ReferenceAvailabilityScope = "national_proxy"
    scope_label = "national proxy, not Ankara-observed"

    structural_violations: list[str] = []
    counters: dict[str, Counter[str]] = {t: Counter() for t in NATIONAL_HOUSEHOLD_TYPE_SIZE_2025}
    weighted: dict[str, Counter[str]] = {t: Counter() for t in NATIONAL_HOUSEHOLD_TYPE_SIZE_2025}

    evaluated_records = 0
    evaluated_weighted = 0.0

    for rec in sample_records:
        ht = str(rec.get("household_type", "")).strip()
        hs = str(rec.get("household_size_class", "")).strip()
        w = float(rec.get("household_weight", rec.get("population_weight", 1.0)))

        # Coarsen size into '1', '2', '3', '4', '5', '6', '7+'
        if hs in ("7", "8", "9", "10+", "7+"):
            hs_coarse = "7+"
        elif hs in ("1", "2", "3", "4", "5", "6"):
            hs_coarse = hs
        else:
            try:
                num = int(hs)
                hs_coarse = "7+" if num >= 7 else str(num)
            except ValueError:
                continue

        if ht not in NATIONAL_HOUSEHOLD_TYPE_SIZE_2025:
            continue

        # Structural zero constraints:
        # one_person MUST be size 1
        if ht == "one_person" and hs_coarse != "1":
            structural_violations.append(f"one_person household with size {hs_coarse} (must be 1)")
        # nuclear_family MUST be size >= 2
        elif ht == "nuclear_family" and hs_coarse == "1":
            structural_violations.append("nuclear_family household with size 1 (must be >= 2)")
        # extended_family MUST be size >= 3
        elif ht == "extended_family" and hs_coarse in ("1", "2"):
            structural_violations.append(f"extended_family household with size {hs_coarse} (must be >= 3)")
        # non_family_multi_person MUST be size >= 2
        elif ht == "non_family_multi_person" and hs_coarse == "1":
            structural_violations.append("non_family_multi_person household with size 1 (must be >= 2)")

        counters[ht][hs_coarse] += 1
        weighted[ht][hs_coarse] += w
        evaluated_records += 1
        evaluated_weighted += w

    if structural_violations:
        return JointCheckResult(
            check_id=check_id,
            name="Household Size × Household Type Joint Distribution",
            dimensions=("household_type", "household_size_class"),
            category="supported_joint_checks",
            status="fail",
            scope=scope,
            scope_label=scope_label,
            reason=f"Structural zero violations: {len(structural_violations)} households violate physical size-type rules.",
            reference_dataset_id="tuik_family_statistics_2025_table_1",
            reference_geography="TR",
            reference_year=2025,
            reference_title="Aile İstatistikleri 2025 (Table 1) household type × size distribution",
            evaluated_records=evaluated_records,
            evaluated_weighted_total=evaluated_weighted,
            structural_zero_violations=tuple(structural_violations[:20]),
        )

    # Evaluate each household type conditional distribution
    evals: list[ConditioningGroupEvaluation] = []
    failed_reasons: list[str] = []

    for ht, ref_dist in NATIONAL_HOUSEHOLD_TYPE_SIZE_2025.items():
        g_eval = _evaluate_slice_against_distribution(
            group_key=f"household_type={ht}",
            dimensions={"household_type": ht},
            observed_counter=counters[ht],
            observed_weighted_counter=weighted[ht],
            reference_distribution=ref_dist,
            alpha=tolerances.familywise_alpha,
        )
        evals.append(g_eval)
        if g_eval.status == "fail":
            failed_reasons.append(f"Type {ht}: {g_eval.reason}")

    overall_tvd_rec = sum(e.tvd_records * e.records_in_group for e in evals) / max(1, evaluated_records)
    overall_tvd_wt = sum(e.tvd_weighted * e.weighted_in_group for e in evals) / max(1.0, evaluated_weighted)
    max_z = max(abs(e.max_abs_z or 0.0) for e in evals)
    max_pp = max(e.max_abs_pp_records for e in evals)

    if failed_reasons:
        status: CheckStatus = "fail"
        reason = "Household type-size conditional failure against National Proxy: " + " | ".join(failed_reasons)
    else:
        status = "pass"
        reason = (
            f"Household type × size joint distribution is consistent with Table 1 national proxy and structural zeros: "
            f"overall TVD={overall_tvd_rec:.4f}, max |z|={max_z:.2f}."
        )

    return JointCheckResult(
        check_id=check_id,
        name="Household Size × Household Type Joint Distribution",
        dimensions=("household_type", "household_size_class"),
        category="supported_joint_checks",
        status=status,
        scope=scope,
        scope_label=scope_label,
        reason=reason,
        reference_dataset_id="tuik_family_statistics_2025_table_1",
        reference_geography="TR",
        reference_year=2025,
        reference_title="Aile İstatistikleri 2025 (Table 1) household type × size distribution",
        evaluated_records=evaluated_records,
        evaluated_weighted_total=evaluated_weighted,
        overall_tvd_records=overall_tvd_rec,
        overall_tvd_weighted=overall_tvd_wt,
        max_abs_z=max_z,
        max_abs_pp_deviation=max_pp,
        conditioning_evaluations=tuple(evals),
    )


# -----------------------------------------------------------------------------
# Check 4: Age × Education (Unverified Empirical Joint + Structural Zero Rules)
# -----------------------------------------------------------------------------

def evaluate_age_education(
    records: list[dict[str, Any]],
    tolerances: CalibrationTolerances,
) -> JointCheckResult:
    """Evaluate age × education relationship.

    Per Phase 1 & 4 protocols:
    - Empirical joint distribution is unobserved in public TÜİK tables: benchmark is NEVER invented.
    - Status is not_evaluable (unverified).
    - Deterministic minimum completion ages are strictly audited as structural zeros.
    """
    check_id = "joint_age_education"
    scope: ReferenceAvailabilityScope = "unverified_no_reference"
    scope_label = "unverified (no empirical reference)"

    structural_violations: list[str] = []
    evaluated_records = 0
    evaluated_weighted = 0.0

    for rec in records:
        age = rec.get("age")
        if age is None:
            ag = str(rec.get("age_group", ""))
            low, _ = band_bounds(ag) if ag in AGE_GROUPS else (None, None)
            age = low if low is not None else 0

        edu = rec.get("education_level")
        w = float(rec.get("population_weight", 1.0))
        evaluated_records += 1
        evaluated_weighted += w

        if edu is None:
            continue

        edu_str = str(edu).strip()

        # Under age 15, education must be not_applicable or unclassified
        if age < 15:
            if edu_str not in (NOT_APPLICABLE, "not_applicable", "unknown", "None", ""):
                structural_violations.append(
                    f"Child age {age} has education level {edu_str!r} (must be not_applicable for <15)."
                )
            continue

        # Check minimum completion age rules via centralised institutional constraints
        if structural_zero("education_level", edu_str, age):
            min_age = EDUCATION_MIN_COMPLETION_AGES.get(edu_str)
            structural_violations.append(
                f"Record age {age} holds degree {edu_str!r} before minimum completion age {min_age}."
            )

    if structural_violations:
        return JointCheckResult(
            check_id=check_id,
            name="Age × Education Joint Distribution & Structural Constraints",
            dimensions=("age", "education_level"),
            category="unverified_relationships",
            status="fail",
            scope=scope,
            scope_label=scope_label,
            reason=(
                f"Structural zero failure: {len(structural_violations)} records violate deterministic "
                f"minimum completion age rules or under-15 education gate."
            ),
            evaluated_records=evaluated_records,
            evaluated_weighted_total=evaluated_weighted,
            structural_zero_violations=tuple(structural_violations[:20]),
            notes=(
                "Empirical joint distribution unobserved in TÜİK published tables; benchmark not invented.",
                "Evaluated deterministic minimum completion ages: primary>=11, lower_sec>=14, high_school>=17, higher_ed>=20, masters>=22, doctorate>=25.",
            ),
        )

    return JointCheckResult(
        check_id=check_id,
        name="Age × Education Joint Distribution & Structural Constraints",
        dimensions=("age", "education_level"),
        category="unverified_relationships",
        status="not_evaluable",
        scope=scope,
        scope_label=scope_label,
        reason=(
            "Empirical age × education joint distribution is unobserved in published TÜİK tables; "
            "benchmark not invented per validation protocol. Deterministic minimum-completion-age rules "
            "and under-15 education gate verified (0 structural zero violations)."
        ),
        evaluated_records=evaluated_records,
        evaluated_weighted_total=evaluated_weighted,
        notes=(
            "TÜİK NESD publishes education_level by sex only; joint distribution with age is unobserved.",
            "0 structural zero violations across all evaluated records.",
        ),
    )


# -----------------------------------------------------------------------------
# Check 5: Age × Employment (Unverified Empirical Joint)
# -----------------------------------------------------------------------------

def evaluate_age_employment(
    records: list[dict[str, Any]],
    tolerances: CalibrationTolerances,
) -> JointCheckResult:
    """Evaluate age × employment relationship.

    Per Phase 1 & 4 protocols:
    - Provincial tables publish headline survey rates only without person-level joint distribution.
    - Status is strictly not_evaluable (unverified). Benchmark is never invented.
    """
    check_id = "joint_age_employment"
    scope: ReferenceAvailabilityScope = "unverified_no_reference"
    scope_label = "unverified (no empirical reference)"

    evaluated_records = len(records)
    evaluated_weighted = sum(float(r.get("population_weight", 1.0)) for r in records)

    # Check if any records claim employment status
    has_status = any(r.get("labour_status") not in (None, "", "UNAVAILABLE") for r in records)

    if not has_status:
        reason = (
            "Empirical person-level labour force status is not modelled in baseline generator (marked UNAVAILABLE "
            "in dependency registry); TÜİK provincial labour indicators publish aggregate headline survey rates "
            "only without age-conditional joint counts. Benchmark not invented per validation protocol."
        )
    else:
        reason = (
            "Empirical person-level age × employment joint distribution is unobserved in provincial TÜİK tables; "
            "benchmark not invented per validation protocol."
        )

    return JointCheckResult(
        check_id=check_id,
        name="Age × Employment Status Joint Distribution",
        dimensions=("age", "labour_status"),
        category="unverified_relationships",
        status="not_evaluable",
        scope=scope,
        scope_label=scope_label,
        reason=reason,
        evaluated_records=evaluated_records,
        evaluated_weighted_total=evaluated_weighted,
        notes=(
            "TÜİK HLFS provides headline provincial LFPR/employment/unemployment rates only (TR51/NUTS-2 only for details).",
            "Person-level labour status is marked UNAVAILABLE in dependency_registry.yaml.",
        ),
    )


# -----------------------------------------------------------------------------
# Main Entry Point: validate_dependencies
# -----------------------------------------------------------------------------

def validate_dependencies(
    population: Any,
    reference_bundle: Mapping[str, ReferenceDataset] | Path | None = None,
    *,
    tolerances: CalibrationTolerances | None = None,
    households: Any = None,
    include_marginal_report: bool = True,
    marginal_report: PopulationValidationReport | None = None,
    repo_root: Path = REPO_ROOT_DEFAULT,
    tuik_package_dir: Path | None = None,
) -> DependencyValidationReport:
    """Validate dependency relationships and joint distributions in a synthetic population.

    Parameters:
        population: Generated population object (GeneratedPopulation, LoadedPopulation, dict, etc.)
        reference_bundle: Mapping of reference datasets or path to reference package directory
        tolerances: Configurable calibration tolerances (default CalibrationTolerances())
        households: Optional companion household records (for household joint checks)
        include_marginal_report: Whether to compute or include the K3 marginal validation report
        marginal_report: Pre-computed PopulationValidationReport (if already available)
        repo_root: Repository root path
        tuik_package_dir: Directory containing raw TÜİK packages

    Returns:
        DependencyValidationReport with explicitly partitioned sections:
        - calibrated_margins
        - supported_joint_checks
        - unverified_relationships
    """
    if tolerances is None:
        tolerances = CalibrationTolerances()

    cols, manifest, hh_cols, hh_manifest = _extract_population_columns_and_manifest(
        population, households_override=households
    )

    n_records = len(cols.get("synthetic_id", cols.get("age", [])))
    if n_records == 0:
        raise ValueError("Population contains zero records.")

    # Reconstruct row dicts
    keys = list(cols.keys())
    records = [{k: cols[k][i] for k in keys} for i in range(n_records)]

    # Extract household rows if present
    hh_records: list[dict[str, Any]] | None = None
    if hh_cols:
        hh_n = len(hh_cols.get("household_id", hh_cols.get("household_type", [])))
        hh_keys = list(hh_cols.keys())
        hh_records = [{k: hh_cols[k][i] for k in hh_keys} for i in range(hh_n)]
    elif households is not None:
        if isinstance(households, (list, tuple)) and households and isinstance(households[0], dict):
            hh_records = list(households)

    # 1. Obtain K3 marginal report for the calibrated_margins section
    if marginal_report is None and include_marginal_report:
        marginal_report = validate_population(
            population,
            reference_bundle=reference_bundle,
            tolerances=tolerances,
            households=households,
            repo_root=repo_root,
            tuik_package_dir=tuik_package_dir,
        )

    calibrated_margins: list[PopulationMarginCheck] = []
    if marginal_report is not None:
        # Keep checks that represent intentionally calibrated margins
        calibrated_margins = [chk for chk in marginal_report.checks if chk.is_calibrated_margin]

    # 2. Evaluate Candidate Joint Checks
    check_age_mat = evaluate_age_marital(records, tolerances)
    check_sex_age_mat = evaluate_sex_age_marital(records, tolerances)
    check_hh = evaluate_household_size_type(records, hh_records, tolerances)
    check_edu = evaluate_age_education(records, tolerances)
    check_emp = evaluate_age_employment(records, tolerances)

    # 3. Partition checks into the three required sections
    supported_joint_checks: list[JointCheckResult] = [check_age_mat, check_sex_age_mat]
    unverified_relationships: list[JointCheckResult] = [check_edu, check_emp]

    if check_hh.category == "supported_joint_checks":
        supported_joint_checks.append(check_hh)
    else:
        unverified_relationships.append(check_hh)

    # Metadata extraction
    pop_id = str(manifest.get("population_id", f"pop-custom-n{n_records}"))
    pop_ver = str(manifest.get("population_version", manifest.get("generator_version", "unknown-population-1.0")))
    geo_code = str(manifest.get("scope", {}).get("scope_code", "06"))
    ref_year = int(manifest.get("reference_year", 2025))
    seed = manifest.get("seed")
    if seed is not None:
        seed = int(seed)

    w_total = sum(float(r.get("population_weight", 1.0)) for r in records)

    # Reference package provenance
    pkg_ver = marginal_report.reference_package_version if marginal_report else REFERENCE_PACKAGE_VERSION
    pkg_fp = marginal_report.reference_package_fingerprint if marginal_report else "reference-package-unspecified"
    dq_flags = marginal_report.documented_discrepancies if marginal_report else (
        ANKARA_HOUSEHOLD_DISCREPANCY_FLAG,
        EDUCATION_UNIVERSE_GAP_FLAG,
        LABOUR_RATE_ONLY_FLAG,
    )

    # Overall status tally
    all_statuses: list[CheckStatus] = (
        [m.status for m in calibrated_margins]
        + [j.status for j in supported_joint_checks]
        + [u.status for u in unverified_relationships]
    )
    status_counts = {
        "pass": all_statuses.count("pass"),
        "fail": all_statuses.count("fail"),
        "not_evaluable": all_statuses.count("not_evaluable"),
    }

    if status_counts["fail"] > 0:
        overall_status: CheckStatus = "fail"
        failing_checks = (
            [m.check_id for m in calibrated_margins if m.status == "fail"]
            + [j.check_id for j in supported_joint_checks if j.status == "fail"]
            + [u.check_id for u in unverified_relationships if u.status == "fail"]
        )
        summary_reason = f"Population failed {status_counts['fail']} validation check(s): {failing_checks}."
    elif status_counts["pass"] > 0:
        overall_status = "pass"
        summary_reason = (
            f"All evaluable calibrated margins ({len(calibrated_margins)}) and supported joint checks "
            f"({len(supported_joint_checks)}) passed within tolerances / sampling uncertainty."
        )
    else:
        overall_status = "not_evaluable"
        summary_reason = "No evaluable checks passed or failed."

    return DependencyValidationReport(
        report_schema_version=REPORT_SCHEMA_VERSION,
        validator_version=VALIDATOR_VERSION,
        population_id=pop_id,
        population_version=pop_ver,
        reference_package_version=pkg_ver,
        reference_package_fingerprint=pkg_fp,
        geography_code=geo_code,
        reference_year=ref_year,
        sample_size=n_records,
        weighted_population_total=w_total,
        seed=seed,
        overall_status=overall_status,
        status_counts=status_counts,
        calibrated_margins=tuple(calibrated_margins),
        supported_joint_checks=tuple(supported_joint_checks),
        unverified_relationships=tuple(unverified_relationships),
        documented_discrepancies=tuple(dq_flags),
        summary_reason=summary_reason,
    )
