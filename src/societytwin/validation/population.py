"""Population Distribution Validator (K3) — ``src/societytwin/validation/population.py``.

Compares a generated synthetic Ankara population against the Phase 2 K2 versioned
reference package without LLM or network calls.

Core principles:
- Deterministic and reproducible: fixed seeds, verified SHA-256 hashes, zero network
  or paid LLM calls.
- Explicit three-state check results: ``pass | fail | not_evaluable`` with human-readable
  ``reason``, ``population_version``, and ``dataset_provenance`` (``dataset_id``, ``year``,
  ``geography``, ``denominator``).
- Explicit handling of sampling variability:
  * Intentionally calibrated margins -> evaluated against predefined, configurable,
    documented ``CalibrationTolerances`` (plus record-level sampling checks).
  * Uncalibrated distributions -> evaluated and reported using explicit multinomial/binomial
    sampling uncertainty for the sample size ``n`` (expected TVD for ``n``, expected max
    percentage-point standard error, Bonferroni-adjusted standardized residual threshold),
    never applying tight numerical calibration tolerances to uncalibrated draws.
- Supported margins:
  ``age``, ``sex``, ``age_sex``, ``marital_status``, ``education``,
  ``employment_status`` (only where definitions and units are comparable; otherwise
  ``not_evaluable`` with reason), ``household_size``, and ``household_type``.
"""

from __future__ import annotations

import json
import math
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
from societytwin.national.constraints import structural_zero
from societytwin.national.controls import ControlRow, ControlStore, TableMeta
from societytwin.national.dependencies import TypedModel
from societytwin.national.generator import COLUMNS, GeneratedPopulation, GenerationConfig, generate
from societytwin.national.vocab import (
    AGE_GROUPS,
    EDUCATION,
    HOUSEHOLD_SIZE,
    HOUSEHOLD_TYPE,
    LABOUR,
    MARITAL,
    NOT_APPLICABLE,
    SEX,
    TOP_CODE_AGE,
    VOCABULARIES,
    ValueStatus,
    band_bounds,
    band_of_age,
)

REPORT_SCHEMA_VERSION = "population-validation-report-k3-v1"
VALIDATOR_VERSION = "k3-population-validator-1.0"
DEFAULT_REFERENCE_PACKAGE_DIR = REPO_ROOT_DEFAULT / "data" / "reference_package_k2_v1"

CheckStatus = Literal["pass", "fail", "not_evaluable"]
MarginName = Literal[
    "age",
    "sex",
    "age_sex",
    "marital_status",
    "education",
    "employment_status",
    "household_size",
    "household_type",
]
EvaluationRegime = Literal[
    "calibrated_margin_tolerance",
    "uncalibrated_sampling_uncertainty",
    "not_evaluable",
]

SUPPORTED_MARGINS: tuple[MarginName, ...] = (
    "age",
    "sex",
    "age_sex",
    "marital_status",
    "education",
    "employment_status",
    "household_size",
    "household_type",
)


class CalibrationTolerances(TypedModel):
    """Predefined, configurable, documented tolerances for intentionally calibrated margins."""

    max_weighted_tvd: float = Field(default=1e-5, gt=0.0, le=0.05)
    max_weighted_pp_deviation: float = Field(default=1e-3, gt=0.0, le=5.0)
    max_weighted_relative_error: float = Field(default=1e-5, gt=0.0, le=0.05)
    max_stratified_record_count_error: float = Field(default=1.0, gt=0.0, le=5.0)
    familywise_alpha: float = Field(default=0.01, gt=0.0, lt=1.0)
    min_records_for_noise_test: StrictInt = Field(default=30, ge=1)

    def justification(self) -> dict[str, str]:
        return {
            "max_weighted_tvd": (
                "Raked population weights converge to <1e-10 relative error on calibrated margins; "
                "1e-5 allows floating-point summation across cells while catching any non-convergence or weight corruption."
            ),
            "max_weighted_pp_deviation": (
                "Maximum percentage-point deviation (100 * |q_w - p|) permitted on calibrated weighted shares (0.001 pp)."
            ),
            "max_weighted_relative_error": (
                "Maximum relative error (|W_k - E_k| / E_k) permitted on positive calibrated cells."
            ),
            "max_stratified_record_count_error": (
                "Root age × sex records are allocated deterministically by Hamilton largest-remainder rounding, "
                "so each cell's unweighted record count n_k is within 1.0 record of N * p_k."
            ),
            "familywise_alpha": (
                "Familywise type-I error rate (Bonferroni-adjusted across K cells) used to compute the "
                "standardized residual z threshold for Monte Carlo record draws and uncalibrated distributions."
            ),
            "min_records_for_noise_test": (
                "Minimum sample records in a conditioning group required for normal binomial z-residual approximation."
            ),
        }


class DenominatorProvenance(TypedModel):
    """Denominator metadata attached to a validation check."""

    universe: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    min_age: StrictInt | None = None
    expected_total: float | StrictInt | None = None
    reconciles_to_root_population: StrictBool = True
    expected_gap_vs_root: float | StrictInt | None = None
    inconsistency_reason: str | None = None


class DatasetProvenance(TypedModel):
    """Reference dataset provenance recorded on every margin check."""

    dataset_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    year: StrictInt | str
    geography: str = Field(min_length=1)
    geography_name: str = Field(min_length=1)
    scope_marker: str = Field(min_length=1)
    denominator: DenominatorProvenance
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_quality_flags: tuple[str, ...] = ()


class CellComparison(TypedModel):
    """Per-cell comparison metrics between synthetic population and reference distribution."""

    cell_key: str = Field(min_length=1)
    dimensions: dict[str, str]
    reference_published_count: float
    expected_population_count: float
    observed_weighted_count: float
    expected_record_count: float
    observed_record_count: StrictInt
    reference_share: float
    observed_weighted_share: float
    observed_record_share: float
    count_error_weighted: float
    abs_count_error_weighted: float
    relative_error_weighted: float | None = None
    count_error_records: float
    abs_count_error_records: float
    pp_deviation_weighted: float
    abs_pp_deviation_weighted: float
    pp_deviation_records: float
    abs_pp_deviation_records: float
    standardized_residual_z: float | None = None
    pearson_residual_records: float | None = None


class MarginMetricsSummary(TypedModel):
    """Aggregate error metrics for a single margin validation check."""

    cell_count: StrictInt = Field(ge=0)
    conditioning_groups: StrictInt = Field(ge=1)
    evaluated_records: StrictInt = Field(ge=0)
    evaluated_weighted_total: float
    reference_published_total: float
    expected_scaled_total: float
    universe_scale_factor: float = 1.0
    total_variation_distance_weighted: float = Field(ge=0.0)
    total_variation_distance_records: float = Field(ge=0.0)
    max_abs_count_error_weighted: float = Field(ge=0.0)
    mean_abs_count_error_weighted: float = Field(ge=0.0)
    max_abs_count_error_records: float = Field(ge=0.0)
    mean_abs_count_error_records: float = Field(ge=0.0)
    max_abs_pp_deviation_weighted: float = Field(ge=0.0)
    max_abs_pp_deviation_records: float = Field(ge=0.0)
    max_relative_error_weighted: float | None = None
    max_abs_standardized_residual: float | None = None
    mean_abs_standardized_residual: float | None = None


class SamplingUncertaintySummary(TypedModel):
    """Explicit sampling uncertainty quantification for sample size n (e.g., n=1000).

    Used directly to evaluate uncalibrated distributions (where calibration tolerances
    must NOT be applied) and reported alongside calibrated margins for record-level transparency.
    """

    sample_size_n: StrictInt = Field(ge=0)
    cell_count_k: StrictInt = Field(ge=1)
    familywise_alpha: float = Field(gt=0.0, lt=1.0)
    bonferroni_z_threshold: float = Field(gt=0.0)
    expected_tvd_for_n: float = Field(
        ge=0.0,
        description=(
            "Expected Total Variation Distance E[TVD] under multinomial random sampling of size n: "
            "0.5 * sum_k sqrt(2 / pi * p_k * (1 - p_k) / n)."
        ),
    )
    expected_max_cell_se_pp_for_n: float = Field(
        ge=0.0,
        description="Largest per-cell binomial standard error in percentage points: 100 * max_k sqrt(p_k*(1-p_k)/n).",
    )
    observed_tvd_records: float = Field(ge=0.0)
    observed_max_abs_pp_records: float = Field(ge=0.0)
    observed_max_abs_z: float | None = None
    noise_test_assessed: StrictBool
    within_sampling_uncertainty: StrictBool
    uncertainty_note: str = Field(min_length=1)


class PopulationMarginCheck(TypedModel):
    """Result of validating one demographic or household margin."""

    check_id: str = Field(min_length=1)
    margin: MarginName
    status: CheckStatus
    reason: str = Field(min_length=1)
    population_id: str = Field(min_length=1)
    population_version: str = Field(min_length=1)
    dataset_provenance: DatasetProvenance
    is_calibrated_margin: StrictBool
    evaluation_regime: EvaluationRegime
    calibration_tolerance_applied: StrictBool
    metrics: MarginMetricsSummary | None = None
    sampling_uncertainty: SamplingUncertaintySummary | None = None
    cells: tuple[CellComparison, ...] = ()
    domain_violations: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class PopulationValidationReport(TypedModel):
    """Complete K3 Population Distribution Validation Report."""

    report_schema_version: Literal["population-validation-report-k3-v1"] = REPORT_SCHEMA_VERSION
    validator_version: Literal["k3-population-validator-1.0"] = VALIDATOR_VERSION
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
    calibration_tolerances: CalibrationTolerances
    tolerance_justification: dict[str, str]
    checks: tuple[PopulationMarginCheck, ...]
    documented_discrepancies: tuple[DataQualityFlag, ...]
    summary_reason: str = Field(min_length=1)

    @property
    def report_fingerprint(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def get_check(self, margin: MarginName | str) -> PopulationMarginCheck:
        for chk in self.checks:
            if chk.margin == margin or chk.check_id == margin:
                return chk
        raise KeyError(f"Margin check {margin!r} not found in report. Available: {[c.margin for c in self.checks]}")

    def to_markdown(self) -> str:
        """Render a human-readable Markdown summary of the validation report."""
        lines = [
            f"# K3 Population Validation Report — `{self.population_id}`",
            "",
            f"- **Population ID:** `{self.population_id}`",
            f"- **Population Version:** `{self.population_version}`",
            f"- **Reference Package Version:** `{self.reference_package_version}` (`{self.reference_package_fingerprint[:16]}...`)",
            f"- **Geography / Year:** `{self.geography_code}` / `{self.reference_year}`",
            f"- **Sample Size ($n$):** `{self.sample_size:,}` records (Weighted Total: `{self.weighted_population_total:,.1f}`)",
            f"- **Seed:** `{self.seed}`",
            f"- **Overall Status:** **`{self.overall_status.upper()}`** "
            f"(`pass={self.status_counts['pass']}`, `fail={self.status_counts['fail']}`, "
            f"`not_evaluable={self.status_counts['not_evaluable']}`)",
            f"- **Summary:** {self.summary_reason}",
            "",
            "## Margin Check Results",
            "",
            "| Margin | Status | Calibrated | Regime | Dataset ID | Denominator | Weighted TVD | Record TVD | Expected TVD ($n$) | Max $|z|$ | Reason |",
            "|---|---|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
        for c in self.checks:
            denom = (
                f"{c.dataset_provenance.denominator.expected_total:,} ({c.dataset_provenance.denominator.unit})"
                if isinstance(c.dataset_provenance.denominator.expected_total, (int, float))
                else f"N/A ({c.dataset_provenance.denominator.unit})"
            )
            w_tvd = f"{c.metrics.total_variation_distance_weighted:.6f}" if c.metrics else "—"
            r_tvd = f"{c.metrics.total_variation_distance_records:.4f}" if c.metrics else "—"
            e_tvd = f"{c.sampling_uncertainty.expected_tvd_for_n:.4f}" if c.sampling_uncertainty else "—"
            max_z = (
                f"{c.metrics.max_abs_standardized_residual:.2f}"
                if c.metrics and c.metrics.max_abs_standardized_residual is not None
                else "—"
            )
            lines.append(
                f"| `{c.margin}` | **`{c.status}`** | `{c.is_calibrated_margin}` | `{c.evaluation_regime}` | "
                f"`{c.dataset_provenance.dataset_id}` | {denom} | {w_tvd} | {r_tvd} | {e_tvd} | {max_z} | {c.reason} |"
            )
        lines.extend(["", "## Documented Data-Quality Flags", ""])
        for flag in self.documented_discrepancies:
            lines.append(f"- **`{flag.flag_id}`** (`{flag.severity}`, policy: `{flag.handling_policy}`): {flag.summary}")
        return "\n".join(lines) + "\n"


def _z_threshold(cells: int, alpha: float) -> float:
    return NormalDist().inv_cdf(1.0 - alpha / (2.0 * max(cells, 1)))


def _expected_multinomial_tvd(shares: list[float], n: int) -> float:
    """Analytical expected Total Variation Distance for a multinomial sample of size n.

    Under normal approximation for cell counts n_k ~ Binomial(n, p_k),
    E[|q_k - p_k|] = sqrt(2 / pi) * sqrt(p_k * (1 - p_k) / n),
    so E[TVD] = 0.5 * sum_k E[|q_k - p_k|].
    """
    if n <= 0:
        return 0.0
    factor = math.sqrt(2.0 / math.pi)
    return 0.5 * math.fsum(
        factor * math.sqrt(max(0.0, p * (1.0 - p)) / n)
        for p in shares
        if 0.0 < p < 1.0
    )


def _provenance_from_dataset(ds: ReferenceDataset) -> DatasetProvenance:
    return DatasetProvenance(
        dataset_id=ds.dataset_id,
        title=ds.title,
        source=ds.source,
        year=ds.year,
        geography=ds.geography.code,
        geography_name=ds.geography.name,
        scope_marker=ds.scope_marker,
        denominator=DenominatorProvenance(
            universe=ds.denominator.universe,
            unit=ds.denominator.unit,
            min_age=ds.denominator.min_age,
            expected_total=ds.denominator.expected_total,
            reconciles_to_root_population=ds.denominator.reconciles_to_root_population,
            expected_gap_vs_root=ds.denominator.expected_gap_vs_root,
            inconsistency_reason=ds.denominator.inconsistency_reason,
        ),
        source_sha256=ds.verified_sha256,
        data_quality_flags=tuple(f.flag_id for f in ds.data_quality_flags),
    )


def _provenance_from_entry(entry: EvidenceDatasetEntry) -> DatasetProvenance:
    return DatasetProvenance(
        dataset_id=entry.dataset_id,
        title=entry.title,
        source=entry.source,
        year=entry.year,
        geography=entry.geography.code,
        geography_name=entry.geography.name,
        scope_marker=entry.geography.scope_marker,
        denominator=DenominatorProvenance(
            universe=entry.denominator.universe,
            unit=entry.denominator.unit,
            min_age=entry.denominator.min_age,
            expected_total=entry.denominator.expected_total,
            reconciles_to_root_population=entry.denominator.reconciles_to_root_population,
            expected_gap_vs_root=entry.denominator.expected_gap_vs_root,
            inconsistency_reason=entry.denominator.inconsistency_reason,
        ),
        source_sha256=entry.sha256,
        data_quality_flags=tuple(f.flag_id for f in entry.data_quality_flags),
    )


def load_reference_bundle(
    reference_bundle: Path | str | EvidenceRegistry | Mapping[str, ReferenceDataset] | None = None,
    *,
    repo_root: Path = REPO_ROOT_DEFAULT,
    tuik_package_dir: Path | None = None,
) -> tuple[dict[str, ReferenceDataset], EvidenceRegistry, str, str]:
    """Load and verify the Phase 2 K2 reference bundle.

    Returns ``(datasets_dict, evidence_registry, package_version, package_fingerprint)``.
    If a built reference package directory (e.g. ``data/reference_package_k2_v1``) exists,
    verifies every normalized JSON table against its SHA-256 recorded in ``manifest.json``.
    """
    ev_reg = reference_bundle if isinstance(reference_bundle, EvidenceRegistry) else load_evidence_registry()

    if isinstance(reference_bundle, Mapping):
        datasets = dict(reference_bundle)
        if (DEFAULT_REFERENCE_PACKAGE_DIR / "manifest.json").is_file():
            manifest = json.loads((DEFAULT_REFERENCE_PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
            table_ids = {t["dataset_id"] for t in manifest.get("tables", [])}
            if set(datasets.keys()) == table_ids:
                return (
                    datasets,
                    ev_reg,
                    manifest.get("package_version", REFERENCE_PACKAGE_VERSION),
                    manifest.get("package_fingerprint", ev_reg.fingerprint),
                )
        fp = canonical_hash({k: v.content_sha256 for k, v in sorted(datasets.items())})
        return datasets, ev_reg, REFERENCE_PACKAGE_VERSION, fp

    pkg_dir: Path | None = None
    if isinstance(reference_bundle, (Path, str)):
        candidate = Path(reference_bundle)
        if candidate.name == "manifest.json":
            pkg_dir = candidate.parent
        elif candidate.is_dir():
            pkg_dir = candidate
    elif reference_bundle is None and (DEFAULT_REFERENCE_PACKAGE_DIR / "manifest.json").is_file():
        pkg_dir = DEFAULT_REFERENCE_PACKAGE_DIR

    datasets: dict[str, ReferenceDataset] = {}
    if pkg_dir is not None and (pkg_dir / "manifest.json").is_file():
        manifest = json.loads((pkg_dir / "manifest.json").read_text(encoding="utf-8"))
        pkg_version = manifest.get("package_version", REFERENCE_PACKAGE_VERSION)
        pkg_fp = manifest.get("package_fingerprint", ev_reg.fingerprint)
        for t_info in manifest.get("tables", []):
            ds_id = t_info["dataset_id"]
            json_path = pkg_dir / t_info["normalized_json_relpath"]
            raw_bytes = json_path.read_bytes()
            if sha256_bytes(raw_bytes) != t_info["normalized_json_sha256"]:
                raise EvidenceLoadError(
                    f"Reference package table {ds_id!r} failed SHA-256 verification against manifest.json"
                )
            payload = json.loads(raw_bytes.decode("utf-8"))
            if "source_file_path" not in payload:
                payload["source_file_path"] = ev_reg.get(ds_id).retrieval_info.relative_path
            datasets[ds_id] = ReferenceDataset.model_validate(payload)
        return datasets, ev_reg, pkg_version, pkg_fp

    # Fallback: load required Ankara datasets directly through K2 loader
    for ds_id in (
        "ankara_age_sex_2025",
        "ankara_marital_sex_2025",
        "ankara_education_sex_2025",
        "ankara_urbanicity_sex_2025",
        "ankara_household_types_2025",
        "ankara_labour_force_rates_2025",
    ):
        datasets[ds_id] = load_reference_dataset(
            ds_id,
            registry=ev_reg,
            repo_root=repo_root,
            tuik_package_dir=tuik_package_dir,
        )
    fp = canonical_hash({k: v.content_sha256 for k, v in sorted(datasets.items())})
    return datasets, ev_reg, REFERENCE_PACKAGE_VERSION, fp


def build_ankara_control_store_from_bundle(
    reference_bundle: Path | str | EvidenceRegistry | Mapping[str, ReferenceDataset] | None = None,
    *,
    repo_root: Path = REPO_ROOT_DEFAULT,
    tuik_package_dir: Path | None = None,
) -> ControlStore:
    """Build an in-memory ``ControlStore`` for Ankara (06, 2025) from the verified Phase 2 reference bundle.

    Produces bit-for-bit identical Ankara populations to the full 71-file ``build_controls`` store.
    """
    datasets, _, pkg_version, pkg_fp = load_reference_bundle(
        reference_bundle, repo_root=repo_root, tuik_package_dir=tuik_package_dir
    )
    tables: dict[str, TableMeta] = {}
    rows: list[ControlRow] = []
    sources: list[dict[str, Any]] = []

    spec_list = (
        ("ankara_age_sex_2025", "population_age_sex", "population_age_sex", 0, None),
        ("ankara_marital_sex_2025", "marital_status_sex", "marital_status_sex", 15, "marital_status"),
        ("ankara_education_sex_2025", "education_sex", "education_sex", 15, "education_level"),
        ("ankara_urbanicity_sex_2025", "urbanicity_sex", "urbanicity_sex", 0, "urbanicity"),
    )
    for ds_id, table_id, kind, min_age, cat_dim in spec_list:
        ds = datasets[ds_id]
        source_id = ds.source_reference.manifest_dataset_id or ds_id
        sources.append(
            {
                "source_id": source_id,
                "title_en": ds.title,
                "dataset_identifier": ds.source_reference.sdmx_dataflow or ds.dataset_id,
                "reference_years": [2025],
                "geographic_level": "province",
                "province_coverage": ["06"],
                "units": [ds.unit],
                "status": "used",
            }
        )
        tables[table_id] = TableMeta(
            table_id=table_id,
            kind=kind,
            title=ds.title,
            unit="persons",
            universe_min_age=min_age,
            universe_note=ds.denominator.universe,
            source_ids=[source_id],
            limitations=list(ds.caveats),
        )
        for r in ds.rows:
            d = r.dimensions
            rows.append(
                ControlRow(
                    table_id=table_id,
                    geo_level="province",
                    geo_code=d.get("province_code", "06"),
                    year=int(ds.year),
                    sex=d.get("sex", ""),
                    age_group=d.get("age_group", ""),
                    category=d.get(cat_dim, "") if cat_dim else "",
                    value=r.value,
                    value_status=r.value_status,
                    source_id=source_id,
                    source_ref=ds.source_file_path,
                )
            )
    return ControlStore(
        tables=tables,
        rows=rows,
        context=[],
        sources=sources,
        built_at=pkg_version,
        fingerprint=pkg_fp,
    )


def generate_ankara_sample_population(
    synthetic_size: int = 1000,
    seed: int = 42,
    *,
    calibrate: bool = True,
    reference_bundle: Path | str | EvidenceRegistry | Mapping[str, ReferenceDataset] | None = None,
    repo_root: Path = REPO_ROOT_DEFAULT,
    tuik_package_dir: Path | None = None,
) -> GeneratedPopulation:
    """Use the existing Population Engine sampler to generate an Ankara 2025 synthetic population.

    With ``synthetic_size=1000, seed=42, calibrate=True``, this deterministically produces
    ``pop-06-2025-n1000-s42-e6a8e87e`` (identical to running against the full TÜİK store).
    """
    store = build_ankara_control_store_from_bundle(
        reference_bundle, repo_root=repo_root, tuik_package_dir=tuik_package_dir
    )
    config = GenerationConfig(
        reference_year=2025,
        synthetic_size=synthetic_size,
        seed=seed,
        provinces=("06",),
        calibrate=calibrate,
    )
    return generate(store, config)


def _extract_population_columns_and_manifest(
    population: Any,
    households_override: Any = None,
) -> tuple[dict[str, list[Any]], dict[str, Any], dict[str, list[Any]] | None, dict[str, Any] | None]:
    """Normalize supported population containers into ``(columns, manifest, hh_columns, hh_manifest)``."""
    hh_cols: dict[str, list[Any]] | None = None
    hh_manifest: dict[str, Any] | None = None

    if isinstance(population, dict) and "residents" in population:
        res_obj = population["residents"]
        if households_override is None and "households" in population:
            households_override = population["households"]
        population = res_obj

    if households_override is not None:
        if hasattr(households_override, "records") and hasattr(households_override, "manifest"):
            recs = households_override.records
            hh_manifest = dict(households_override.manifest)
            hh_cols = {
                "household_id": [getattr(r, "household_id", None) for r in recs],
                "province_code": [getattr(r, "province_code", "06") for r in recs],
                "reference_year": [getattr(r, "reference_year", 2025) for r in recs],
                "household_size_class": [getattr(r, "household_size_class", None) for r in recs],
                "household_type": [getattr(r, "household_type", None) for r in recs],
                "household_weight": [float(getattr(r, "household_weight", 1.0)) for r in recs],
            }
        elif isinstance(households_override, dict):
            hh_cols = {k: list(v) for k, v in households_override.get("columns", households_override).items() if isinstance(v, (list, tuple))}
            hh_manifest = dict(households_override.get("manifest", {}))
        elif isinstance(households_override, (list, tuple)) and households_override and isinstance(households_override[0], dict):
            keys = set().union(*(r.keys() for r in households_override))
            hh_cols = {k: [r.get(k) for r in households_override] for k in keys}
            hh_manifest = {}

    # GeneratedPopulation
    if hasattr(population, "columns") and hasattr(population, "manifest") and not callable(population.columns):
        cols = {k: list(v) for k, v in population.columns.items()}
        manifest = dict(population.manifest)
        return cols, manifest, hh_cols, hh_manifest

    # LoadedPopulation
    if hasattr(population, "columns") and callable(population.columns) and hasattr(population, "manifest"):
        cols = {k: list(v) for k, v in population.columns().items()}
        manifest = dict(population.manifest)
        return cols, manifest, hh_cols, hh_manifest

    # PyArrow Table
    if hasattr(population, "to_pydict") and callable(population.to_pydict):
        cols = {k: list(v) for k, v in population.to_pydict().items()}
        return cols, {}, hh_cols, hh_manifest

    # Dict of columns or {"columns": ..., "manifest": ...}
    if isinstance(population, dict):
        if "columns" in population and isinstance(population["columns"], dict):
            cols = {k: list(v) for k, v in population["columns"].items()}
            manifest = dict(population.get("manifest", {}))
            return cols, manifest, hh_cols, hh_manifest
        cols = {k: list(v) for k, v in population.items() if isinstance(v, (list, tuple))}
        return cols, {}, hh_cols, hh_manifest

    # List of row dicts
    if isinstance(population, (list, tuple)) and population and isinstance(population[0], dict):
        keys = set().union(*(r.keys() for r in population))
        cols = {k: [r.get(k) for r in population] for k in keys}
        return cols, {}, hh_cols, hh_manifest

    raise TypeError(f"Unsupported population object of type {type(population).__name__!r}")


def _evaluate_cells_and_metrics(
    *,
    cell_keys: list[tuple[str, ...]],
    dim_names: tuple[str, ...],
    group_dim_indices: tuple[int, ...],
    ref_published_counts: dict[tuple[str, ...], float],
    obs_weighted_counts: dict[tuple[str, ...], float],
    obs_record_counts: dict[tuple[str, ...], int],
    scale_by_group: dict[tuple[str, ...], float],
    overall_scale: float,
    tolerances: CalibrationTolerances,
) -> tuple[tuple[CellComparison, ...], MarginMetricsSummary, SamplingUncertaintySummary]:
    """Compute cell-level and summary metrics plus sampling uncertainty for a margin."""

    def group_of(k: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(k[i] for i in group_dim_indices)

    ref_group_totals: dict[tuple[str, ...], float] = {}
    exp_group_totals: dict[tuple[str, ...], float] = {}
    obs_w_group_totals: dict[tuple[str, ...], float] = {}
    obs_n_group_totals: dict[tuple[str, ...], int] = {}

    for k in cell_keys:
        g = group_of(k)
        s_Factor = scale_by_group.get(g, overall_scale)
        pub_c = ref_published_counts.get(k, 0.0)
        exp_c = pub_c * s_Factor
        w_c = obs_weighted_counts.get(k, 0.0)
        n_c = obs_record_counts.get(k, 0)

        ref_group_totals[g] = ref_group_totals.get(g, 0.0) + pub_c
        exp_group_totals[g] = exp_group_totals.get(g, 0.0) + exp_c
        obs_w_group_totals[g] = obs_w_group_totals.get(g, 0.0) + w_c
        obs_n_group_totals[g] = obs_n_group_totals.get(g, 0) + n_c

    z_thresh = _z_threshold(len(cell_keys), tolerances.familywise_alpha)
    cells_out: list[CellComparison] = []
    abs_err_w_list: list[float] = []
    abs_err_n_list: list[float] = []
    abs_pp_w_list: list[float] = []
    abs_pp_n_list: list[float] = []
    rel_err_w_list: list[float] = []
    abs_z_list: list[float] = []
    tvd_w_by_group: dict[tuple[str, ...], float] = {}
    tvd_n_by_group: dict[tuple[str, ...], float] = {}
    noise_assessed = True
    max_cell_se_pp = 0.0
    expected_tvd_groups: list[float] = []

    for g, g_ref_tot in ref_group_totals.items():
        g_n = obs_n_group_totals.get(g, 0)
        if g_n < tolerances.min_records_for_noise_test:
            noise_assessed = False
        g_shares = [
            ref_published_counts.get(k, 0.0) / g_ref_tot
            for k in cell_keys
            if group_of(k) == g and g_ref_tot > 0
        ]
        expected_tvd_groups.append(_expected_multinomial_tvd(g_shares, g_n))

    for k in cell_keys:
        g = group_of(k)
        s_factor = scale_by_group.get(g, overall_scale)
        pub_c = ref_published_counts.get(k, 0.0)
        exp_c = pub_c * s_factor
        w_c = obs_weighted_counts.get(k, 0.0)
        n_c = obs_record_counts.get(k, 0)

        g_exp_tot = exp_group_totals.get(g, 0.0)
        g_w_tot = obs_w_group_totals.get(g, 0.0)
        g_n_tot = obs_n_group_totals.get(g, 0)

        p_share = exp_c / g_exp_tot if g_exp_tot > 0 else 0.0
        q_w_share = w_c / g_w_tot if g_w_tot > 0 else 0.0
        q_n_share = n_c / g_n_tot if g_n_tot > 0 else 0.0

        exp_n = g_n_tot * p_share
        err_w = w_c - exp_c
        abs_err_w = abs(err_w)
        rel_w = abs_err_w / exp_c if exp_c > 0 else (0.0 if w_c == 0.0 else None)

        err_n = n_c - exp_n
        abs_err_n = abs(err_n)

        pp_w = 100.0 * (q_w_share - p_share)
        abs_pp_w = abs(pp_w)
        pp_n = 100.0 * (q_n_share - p_share)
        abs_pp_n = abs(pp_n)

        z_val: float | None = None
        pearson_val: float | None = None
        if g_n_tot > 0 and 0.0 < p_share < 1.0:
            se_p = math.sqrt(p_share * (1.0 - p_share) / g_n_tot)
            max_cell_se_pp = max(max_cell_se_pp, 100.0 * se_p)
            if g_n_tot >= tolerances.min_records_for_noise_test:
                z_val = (q_n_share - p_share) / se_p
                abs_z_list.append(abs(z_val))
        if exp_n > 0:
            pearson_val = (n_c - exp_n) / math.sqrt(exp_n)

        abs_err_w_list.append(abs_err_w)
        abs_err_n_list.append(abs_err_n)
        abs_pp_w_list.append(abs_pp_w)
        abs_pp_n_list.append(abs_pp_n)
        if rel_w is not None and math.isfinite(rel_w):
            rel_err_w_list.append(rel_w)

        tvd_w_by_group[g] = tvd_w_by_group.get(g, 0.0) + 0.5 * abs(q_w_share - p_share)
        tvd_n_by_group[g] = tvd_n_by_group.get(g, 0.0) + 0.5 * abs(q_n_share - p_share)

        cells_out.append(
            CellComparison(
                cell_key="|".join(k),
                dimensions=dict(zip(dim_names, k)),
                reference_published_count=pub_c,
                expected_population_count=exp_c,
                observed_weighted_count=w_c,
                expected_record_count=exp_n,
                observed_record_count=n_c,
                reference_share=p_share,
                observed_weighted_share=q_w_share,
                observed_record_share=q_n_share,
                count_error_weighted=err_w,
                abs_count_error_weighted=abs_err_w,
                relative_error_weighted=rel_w,
                count_error_records=err_n,
                abs_count_error_records=abs_err_n,
                pp_deviation_weighted=pp_w,
                abs_pp_deviation_weighted=abs_pp_w,
                pp_deviation_records=pp_n,
                abs_pp_deviation_records=abs_pp_n,
                standardized_residual_z=z_val,
                pearson_residual_records=pearson_val,
            )
        )

    num_groups = max(len(ref_group_totals), 1)
    tvd_w = math.fsum(tvd_w_by_group.values()) / num_groups
    tvd_n = math.fsum(tvd_n_by_group.values()) / num_groups
    exp_tvd = math.fsum(expected_tvd_groups) / max(len(expected_tvd_groups), 1)
    total_n = sum(obs_n_group_totals.values())
    total_w = math.fsum(obs_w_group_totals.values())
    total_pub = math.fsum(ref_published_counts.values())
    total_exp = math.fsum(exp_group_totals.values())

    max_z = max(abs_z_list) if abs_z_list else None
    mean_z = (math.fsum(abs_z_list) / len(abs_z_list)) if abs_z_list else None
    within_noise = (max_z <= z_thresh) if max_z is not None else False

    metrics = MarginMetricsSummary(
        cell_count=len(cell_keys),
        conditioning_groups=num_groups,
        evaluated_records=total_n,
        evaluated_weighted_total=total_w,
        reference_published_total=total_pub,
        expected_scaled_total=total_exp,
        universe_scale_factor=overall_scale,
        total_variation_distance_weighted=tvd_w,
        total_variation_distance_records=tvd_n,
        max_abs_count_error_weighted=max(abs_err_w_list, default=0.0),
        mean_abs_count_error_weighted=(math.fsum(abs_err_w_list) / len(abs_err_w_list)) if abs_err_w_list else 0.0,
        max_abs_count_error_records=max(abs_err_n_list, default=0.0),
        mean_abs_count_error_records=(math.fsum(abs_err_n_list) / len(abs_err_n_list)) if abs_err_n_list else 0.0,
        max_abs_pp_deviation_weighted=max(abs_pp_w_list, default=0.0),
        max_abs_pp_deviation_records=max(abs_pp_n_list, default=0.0),
        max_relative_error_weighted=max(rel_err_w_list) if rel_err_w_list else None,
        max_abs_standardized_residual=max_z,
        mean_abs_standardized_residual=mean_z,
    )

    sampling_uncertainty = SamplingUncertaintySummary(
        sample_size_n=total_n,
        cell_count_k=max(len(cell_keys), 1),
        familywise_alpha=tolerances.familywise_alpha,
        bonferroni_z_threshold=z_thresh,
        expected_tvd_for_n=exp_tvd,
        expected_max_cell_se_pp_for_n=max_cell_se_pp,
        observed_tvd_records=tvd_n,
        observed_max_abs_pp_records=metrics.max_abs_pp_deviation_records,
        observed_max_abs_z=max_z,
        noise_test_assessed=noise_assessed and (max_z is not None),
        within_sampling_uncertainty=within_noise,
        uncertainty_note=(
            f"For n={total_n} records across {len(cell_keys)} cell(s), expected multinomial TVD is "
            f"{exp_tvd:.4f} (observed record TVD={tvd_n:.4f}), max cell binomial SE is "
            f"{max_cell_se_pp:.2f} pp (observed max record deviation={metrics.max_abs_pp_deviation_records:.2f} pp), "
            f"and Bonferroni z-threshold at alpha={tolerances.familywise_alpha} is {z_thresh:.3f} "
            f"(observed max |z|={f'{max_z:.3f}' if max_z is not None else 'N/A'})."
        ),
    )
    return tuple(cells_out), metrics, sampling_uncertainty


def _decide_check_status(
    *,
    margin: MarginName,
    is_calibrated: bool,
    is_stratified_root: bool,
    domain_violations: list[str],
    metrics: MarginMetricsSummary,
    uncertainty: SamplingUncertaintySummary,
    tolerances: CalibrationTolerances,
) -> tuple[CheckStatus, EvaluationRegime, bool, str]:
    """Determine (status, regime, calibration_tolerance_applied, reason)."""
    if domain_violations:
        return (
            "fail",
            "calibrated_margin_tolerance" if is_calibrated else "uncalibrated_sampling_uncertainty",
            is_calibrated,
            f"Domain/structural integrity failure on {margin}: {'; '.join(domain_violations[:3])}",
        )

    if is_calibrated:
        regime: EvaluationRegime = "calibrated_margin_tolerance"
        failures: list[str] = []
        if metrics.total_variation_distance_weighted > tolerances.max_weighted_tvd:
            failures.append(
                f"weighted TVD ({metrics.total_variation_distance_weighted:.6f}) exceeds calibration tolerance "
                f"({tolerances.max_weighted_tvd:.6f})"
            )
        if metrics.max_abs_pp_deviation_weighted > tolerances.max_weighted_pp_deviation:
            failures.append(
                f"max weighted pp deviation ({metrics.max_abs_pp_deviation_weighted:.4f} pp) exceeds calibration tolerance "
                f"({tolerances.max_weighted_pp_deviation:.4f} pp)"
            )
        if (
            metrics.max_relative_error_weighted is not None
            and metrics.max_relative_error_weighted > tolerances.max_weighted_relative_error
        ):
            failures.append(
                f"max weighted relative error ({metrics.max_relative_error_weighted:.6f}) exceeds calibration tolerance "
                f"({tolerances.max_weighted_relative_error:.6f})"
            )
        if is_stratified_root and metrics.max_abs_count_error_records > tolerances.max_stratified_record_count_error:
            failures.append(
                f"stratified record count error ({metrics.max_abs_count_error_records:.2f} records) exceeds Hamilton "
                f"rounding bound ({tolerances.max_stratified_record_count_error:.2f})"
            )
        if uncertainty.noise_test_assessed and not uncertainty.within_sampling_uncertainty:
            failures.append(
                f"unweighted record distribution exceeds sampling noise bound (max |z|="
                f"{uncertainty.observed_max_abs_z:.3f} > Bonferroni threshold {uncertainty.bonferroni_z_threshold:.3f}; "
                f"record TVD={uncertainty.observed_tvd_records:.4f} vs expected {uncertainty.expected_tvd_for_n:.4f})"
            )
        if failures:
            return (
                "fail",
                regime,
                True,
                f"Calibrated margin {margin!r} failed validation: {'; '.join(failures)}.",
            )
        return (
            "pass",
            regime,
            True,
            (
                f"Calibrated margin {margin!r} passed: weighted TVD={metrics.total_variation_distance_weighted:.2e} "
                f"(<= {tolerances.max_weighted_tvd:.1e}), max weighted pp deviation="
                f"{metrics.max_abs_pp_deviation_weighted:.2e} pp; unweighted record TVD="
                f"{metrics.total_variation_distance_records:.4f} (expected {uncertainty.expected_tvd_for_n:.4f} for "
                f"n={metrics.evaluated_records}), max |z|="
                f"{f'{uncertainty.observed_max_abs_z:.2f}' if uncertainty.observed_max_abs_z is not None else 'N/A'} "
                f"(<= {uncertainty.bonferroni_z_threshold:.2f})."
            ),
        )

    # Uncalibrated distribution: NEVER apply calibration tolerances! Evaluate against sampling uncertainty for n.
    regime = "uncalibrated_sampling_uncertainty"
    if not uncertainty.noise_test_assessed:
        return (
            "not_evaluable",
            regime,
            False,
            (
                f"Uncalibrated distribution {margin!r} has too few records (n={metrics.evaluated_records} < "
                f"{tolerances.min_records_for_noise_test}) to assess multinomial sampling uncertainty reliably."
            ),
        )
    if not uncertainty.within_sampling_uncertainty:
        return (
            "fail",
            regime,
            False,
            (
                f"Uncalibrated distribution {margin!r} deviates beyond sampling uncertainty for n={metrics.evaluated_records}: "
                f"max |z|={uncertainty.observed_max_abs_z:.3f} > Bonferroni threshold {uncertainty.bonferroni_z_threshold:.3f} "
                f"(observed record TVD={uncertainty.observed_tvd_records:.4f} vs expected TVD={uncertainty.expected_tvd_for_n:.4f} "
                f"for n={metrics.evaluated_records}; max pp deviation={metrics.max_abs_pp_deviation_records:.2f} pp). "
                f"Calibration tolerances were not applied."
            ),
        )
    return (
        "pass",
        regime,
        False,
        (
            f"Uncalibrated distribution {margin!r} is within expected sampling uncertainty for n={metrics.evaluated_records}: "
            f"max |z|={uncertainty.observed_max_abs_z:.2f} <= Bonferroni threshold {uncertainty.bonferroni_z_threshold:.2f} "
            f"(observed record TVD={uncertainty.observed_tvd_records:.4f} vs expected TVD={uncertainty.expected_tvd_for_n:.4f} "
            f"for n={metrics.evaluated_records}). Calibration tolerances were not applied."
        ),
    )


def validate_population(
    population: Any,
    reference_bundle: Path | str | EvidenceRegistry | Mapping[str, ReferenceDataset] | None = None,
    *,
    tolerances: CalibrationTolerances | None = None,
    households: Any = None,
    repo_root: Path = REPO_ROOT_DEFAULT,
    tuik_package_dir: Path | None = None,
) -> PopulationValidationReport:
    """Validate a synthetic Ankara population against the Phase 2 K2 reference bundle.

    Parameters
    ----------
    population:
        A ``GeneratedPopulation``, ``LoadedPopulation``, column dictionary, record list,
        PyArrow table, or bundle dict ``{"residents": ..., "households": ...}``.
    reference_bundle:
        Path to Phase 2 reference package (default ``data/reference_package_k2_v1``),
        ``EvidenceRegistry``, or mapping of ``dataset_id -> ReferenceDataset``.
    tolerances:
        Configurable ``CalibrationTolerances`` for calibrated margins and familywise alpha.
    households:
        Optional ``GeneratedHouseholds`` or household column dict when validating an unlinked
        Ankara household sample alongside the resident population.
    """
    tol = tolerances or CalibrationTolerances()
    datasets, ev_reg, pkg_version, pkg_fp = load_reference_bundle(
        reference_bundle, repo_root=repo_root, tuik_package_dir=tuik_package_dir
    )
    cols, manifest, hh_cols, hh_manifest = _extract_population_columns_and_manifest(
        population, households_override=households
    )

    pop_id = str(manifest.get("population_id", "pop-06-2025-unlabelled"))
    pop_version = str(
        manifest.get("population_version")
        or manifest.get("generator_version")
        or "unversioned"
    )
    ref_year = int(manifest.get("reference_year", 2025))
    seed = manifest.get("seed")
    if seed is None and isinstance(manifest.get("config"), dict):
        seed = manifest["config"].get("seed")

    n_records = len(cols.get("sex", cols.get("age_group", [])))
    weights = [
        float(w)
        for w in cols.get(
            "population_weight",
            [5910320.0 / max(n_records, 1)] * n_records,
        )
    ]
    weighted_total = math.fsum(weights)

    # Determine which margins were calibrated in the manifest
    calibrated_tables: set[str] = set()
    if "calibration" in manifest and isinstance(manifest["calibration"], list):
        for cal_entry in manifest["calibration"]:
            if cal_entry.get("province_code") in ("06", None):
                if cal_entry.get("calibrated"):
                    calibrated_tables.update(cal_entry.get("margins", []))
                elif "population_age_sex" in cal_entry.get("margins", []):
                    calibrated_tables.add("population_age_sex")
    elif "population_weight" in cols:
        # Default assumption when population_weight is present from national generator
        calibrated_tables = {"population_age_sex", "marital_status_sex", "education_sex", "urbanicity_sex"}

    has_explicit_weights = "population_weight" in cols
    age_sex_calibrated = has_explicit_weights and ("population_age_sex" in calibrated_tables)
    marital_calibrated = has_explicit_weights and ("marital_status_sex" in calibrated_tables)
    education_calibrated = has_explicit_weights and ("education_sex" in calibrated_tables)

    ages = cols.get("age", [])
    age_groups = cols.get("age_group", [])
    sexes = cols.get("sex", [])

    # Common domain check on weights, ages, age_groups, sexes
    base_age_violations: list[str] = []
    base_sex_violations: list[str] = []
    for i in range(n_records):
        w = weights[i]
        if not math.isfinite(w) or w <= 0:
            base_age_violations.append(f"Record {i} has non-positive or non-finite population_weight={w!r}")
            base_sex_violations.append(f"Record {i} has non-positive or non-finite population_weight={w!r}")
        ag = age_groups[i] if i < len(age_groups) else None
        if ag not in AGE_GROUPS:
            base_age_violations.append(f"Record {i} has invalid age_group={ag!r}")
        if i < len(ages) and ages[i] is not None:
            a_val = ages[i]
            if not isinstance(a_val, int) or a_val < 0 or a_val > TOP_CODE_AGE:
                base_age_violations.append(f"Record {i} has out-of-range exact age={a_val!r}")
            elif ag in AGE_GROUPS and band_of_age(a_val) != ag:
                base_age_violations.append(
                    f"Record {i} has exact age={a_val} inconsistent with age_group={ag!r} (expected {band_of_age(a_val)!r})"
                )
        sx = sexes[i] if i < len(sexes) else None
        if sx not in SEX.codes:
            base_sex_violations.append(f"Record {i} has invalid sex={sx!r}")

    checks: list[PopulationMarginCheck] = []

    # =========================================================================
    # 1. AGE MARGIN (ankara_age_sex_2025 marginalized over sex)
    # =========================================================================
    ds_age_sex = datasets["ankara_age_sex_2025"]
    prov_age_sex = _provenance_from_dataset(ds_age_sex)

    ref_age_counts: dict[tuple[str, ...], float] = {
        (ag,): 0.0 for ag in AGE_GROUPS
    }
    ref_sex_counts: dict[tuple[str, ...], float] = {
        (sx,): 0.0 for sx in SEX.codes
    }
    ref_joint_age_sex: dict[tuple[str, ...], float] = {
        (ag, sx): 0.0 for ag in AGE_GROUPS for sx in SEX.codes
    }
    for r in ds_age_sex.rows:
        if r.value is not None:
            ag = r.dimensions["age_group"]
            sx = r.dimensions["sex"]
            ref_age_counts[(ag,)] = ref_age_counts.get((ag,), 0.0) + float(r.value)
            ref_sex_counts[(sx,)] = ref_sex_counts.get((sx,), 0.0) + float(r.value)
            ref_joint_age_sex[(ag, sx)] = float(r.value)

    obs_age_w: dict[tuple[str, ...], float] = {(ag,): 0.0 for ag in AGE_GROUPS}
    obs_age_n: dict[tuple[str, ...], int] = {(ag,): 0 for ag in AGE_GROUPS}
    obs_sex_w: dict[tuple[str, ...], float] = {(sx,): 0.0 for sx in SEX.codes}
    obs_sex_n: dict[tuple[str, ...], int] = {(sx,): 0 for sx in SEX.codes}
    obs_joint_w: dict[tuple[str, ...], float] = {(ag, sx): 0.0 for ag in AGE_GROUPS for sx in SEX.codes}
    obs_joint_n: dict[tuple[str, ...], int] = {(ag, sx): 0 for ag in AGE_GROUPS for sx in SEX.codes}

    for i in range(n_records):
        ag = age_groups[i] if i < len(age_groups) else None
        sx = sexes[i] if i < len(sexes) else None
        w = weights[i] if math.isfinite(weights[i]) and weights[i] > 0 else 0.0
        if ag in AGE_GROUPS:
            obs_age_w[(ag,)] += w
            obs_age_n[(ag,)] += 1
        if sx in SEX.codes:
            obs_sex_w[(sx,)] += w
            obs_sex_n[(sx,)] += 1
        if ag in AGE_GROUPS and sx in SEX.codes:
            obs_joint_w[(ag, sx)] += w
            obs_joint_n[(ag, sx)] += 1

    age_cells, age_metrics, age_unc = _evaluate_cells_and_metrics(
        cell_keys=[(ag,) for ag in AGE_GROUPS],
        dim_names=("age_group",),
        group_dim_indices=(),
        ref_published_counts=ref_age_counts,
        obs_weighted_counts=obs_age_w,
        obs_record_counts=obs_age_n,
        scale_by_group={},
        overall_scale=1.0,
        tolerances=tol,
    )
    age_status, age_regime, age_cal_applied, age_reason = _decide_check_status(
        margin="age",
        is_calibrated=age_sex_calibrated,
        is_stratified_root=age_sex_calibrated,
        domain_violations=base_age_violations,
        metrics=age_metrics,
        uncertainty=age_unc,
        tolerances=tol,
    )
    checks.append(
        PopulationMarginCheck(
            check_id="margin_age",
            margin="age",
            status=age_status,
            reason=age_reason,
            population_id=pop_id,
            population_version=pop_version,
            dataset_provenance=prov_age_sex,
            is_calibrated_margin=age_sex_calibrated,
            evaluation_regime=age_regime,
            calibration_tolerance_applied=age_cal_applied,
            metrics=age_metrics,
            sampling_uncertainty=age_unc,
            cells=age_cells,
            domain_violations=tuple(base_age_violations),
            notes=(
                "Evaluated over 19 five-year age groups (0-4 .. 90+) marginalized from ankara_age_sex_2025.",
                "Single-year age (0..90) is also checked for exact membership in each record's five-year band.",
            ),
        )
    )

    # =========================================================================
    # 2. SEX MARGIN (ankara_age_sex_2025 marginalized over age_group)
    # =========================================================================
    sex_cells, sex_metrics, sex_unc = _evaluate_cells_and_metrics(
        cell_keys=[(sx,) for sx in SEX.codes],
        dim_names=("sex",),
        group_dim_indices=(),
        ref_published_counts=ref_sex_counts,
        obs_weighted_counts=obs_sex_w,
        obs_record_counts=obs_sex_n,
        scale_by_group={},
        overall_scale=1.0,
        tolerances=tol,
    )
    sex_status, sex_regime, sex_cal_applied, sex_reason = _decide_check_status(
        margin="sex",
        is_calibrated=age_sex_calibrated,
        is_stratified_root=age_sex_calibrated,
        domain_violations=base_sex_violations,
        metrics=sex_metrics,
        uncertainty=sex_unc,
        tolerances=tol,
    )
    checks.append(
        PopulationMarginCheck(
            check_id="margin_sex",
            margin="sex",
            status=sex_status,
            reason=sex_reason,
            population_id=pop_id,
            population_version=pop_version,
            dataset_provenance=prov_age_sex,
            is_calibrated_margin=age_sex_calibrated,
            evaluation_regime=sex_regime,
            calibration_tolerance_applied=sex_cal_applied,
            metrics=sex_metrics,
            sampling_uncertainty=sex_unc,
            cells=sex_cells,
            domain_violations=tuple(base_sex_violations),
            notes=("Evaluated over male (2,911,853) and female (2,998,467) totals in ankara_age_sex_2025 (5,910,320).",),
        )
    )

    # =========================================================================
    # 3. AGE × SEX JOINT MARGIN (ankara_age_sex_2025, 38 cells)
    # =========================================================================
    joint_violations = list(dict.fromkeys(base_age_violations + base_sex_violations))
    joint_cells, joint_metrics, joint_unc = _evaluate_cells_and_metrics(
        cell_keys=[(ag, sx) for ag in AGE_GROUPS for sx in SEX.codes],
        dim_names=("age_group", "sex"),
        group_dim_indices=(),
        ref_published_counts=ref_joint_age_sex,
        obs_weighted_counts=obs_joint_w,
        obs_record_counts=obs_joint_n,
        scale_by_group={},
        overall_scale=1.0,
        tolerances=tol,
    )
    joint_status, joint_regime, joint_cal_applied, joint_reason = _decide_check_status(
        margin="age_sex",
        is_calibrated=age_sex_calibrated,
        is_stratified_root=age_sex_calibrated,
        domain_violations=joint_violations,
        metrics=joint_metrics,
        uncertainty=joint_unc,
        tolerances=tol,
    )
    checks.append(
        PopulationMarginCheck(
            check_id="margin_age_sex",
            margin="age_sex",
            status=joint_status,
            reason=joint_reason,
            population_id=pop_id,
            population_version=pop_version,
            dataset_provenance=prov_age_sex,
            is_calibrated_margin=age_sex_calibrated,
            evaluation_regime=joint_regime,
            calibration_tolerance_applied=joint_cal_applied,
            metrics=joint_metrics,
            sampling_uncertainty=joint_unc,
            cells=joint_cells,
            domain_violations=tuple(joint_violations),
            notes=("Root joint table (38 cells: 19 five-year age bands × 2 sexes) from ADNKS T16.",),
        )
    )

    # =========================================================================
    # 4. MARITAL STATUS MARGIN (ankara_marital_sex_2025, 15+ universe)
    # =========================================================================
    ds_marital = datasets["ankara_marital_sex_2025"]
    prov_marital = _provenance_from_dataset(ds_marital)
    marital_vals = cols.get("marital_status", [None] * n_records)

    marital_violations: list[str] = []
    ref_marital: dict[tuple[str, ...], float] = {
        (sx, m): 0.0 for sx in SEX.codes for m in MARITAL.codes
    }
    for r in ds_marital.rows:
        if r.value is not None:
            ref_marital[(r.dimensions["sex"], r.dimensions["marital_status"])] = float(r.value)

    obs_marital_w: dict[tuple[str, ...], float] = {k: 0.0 for k in ref_marital}
    obs_marital_n: dict[tuple[str, ...], int] = {k: 0 for k in ref_marital}

    for i in range(n_records):
        ag = age_groups[i] if i < len(age_groups) else "0-4"
        a_val = ages[i] if i < len(ages) and isinstance(ages[i], int) else (band_bounds(ag)[0] if ag in AGE_GROUPS else 0)
        sx = sexes[i] if i < len(sexes) else None
        m_val = marital_vals[i] if i < len(marital_vals) else None
        w = weights[i] if math.isfinite(weights[i]) and weights[i] > 0 else 0.0

        if a_val < 15:
            if m_val not in (NOT_APPLICABLE, None):
                marital_violations.append(
                    f"Record {i} is under 15 (age={a_val}, band={ag}) but has legal marital_status={m_val!r} "
                    f"(expected {NOT_APPLICABLE!r})"
                )
        else:
            if m_val == NOT_APPLICABLE or m_val is None:
                marital_violations.append(
                    f"Record {i} is aged 15+ (age={a_val}) but has marital_status={m_val!r}"
                )
            elif m_val not in MARITAL.codes:
                marital_violations.append(
                    f"Record {i} has impossible/unknown marital_status={m_val!r} (allowed: {MARITAL.codes})"
                )
            elif sx in SEX.codes:
                obs_marital_w[(sx, m_val)] += w
                obs_marital_n[(sx, m_val)] += 1

    # Compute per-sex scale vs reference 15+ (exact 1.0 in 2025 Ankara)
    ref_marital_by_sex = {
        (sx,): math.fsum(v for (s, _), v in ref_marital.items() if s == sx)
        for sx in SEX.codes
    }
    obs_15plus_w_by_sex = {
        (sx,): math.fsum(v for (s, _), v in obs_marital_w.items() if s == sx)
        for sx in SEX.codes
    }
    marital_scale_by_sex = {
        (sx,): (obs_15plus_w_by_sex[(sx,)] / ref_marital_by_sex[(sx,)] if ref_marital_by_sex[(sx,)] > 0 else 1.0)
        for sx in SEX.codes
    }
    overall_marital_scale = (
        math.fsum(obs_15plus_w_by_sex.values()) / math.fsum(ref_marital_by_sex.values())
        if math.fsum(ref_marital_by_sex.values()) > 0
        else 1.0
    )

    marital_cells, marital_metrics, marital_unc = _evaluate_cells_and_metrics(
        cell_keys=[(sx, m) for sx in SEX.codes for m in MARITAL.codes],
        dim_names=("sex", "marital_status"),
        group_dim_indices=(0,),
        ref_published_counts=ref_marital,
        obs_weighted_counts=obs_marital_w,
        obs_record_counts=obs_marital_n,
        scale_by_group=marital_scale_by_sex,
        overall_scale=overall_marital_scale,
        tolerances=tol,
    )
    marital_status, marital_regime, marital_cal_applied, marital_reason = _decide_check_status(
        margin="marital_status",
        is_calibrated=marital_calibrated,
        is_stratified_root=False,
        domain_violations=marital_violations,
        metrics=marital_metrics,
        uncertainty=marital_unc,
        tolerances=tol,
    )
    checks.append(
        PopulationMarginCheck(
            check_id="margin_marital_status",
            margin="marital_status",
            status=marital_status,
            reason=marital_reason,
            population_id=pop_id,
            population_version=pop_version,
            dataset_provenance=prov_marital,
            is_calibrated_margin=marital_calibrated,
            evaluation_regime=marital_regime,
            calibration_tolerance_applied=marital_cal_applied,
            metrics=marital_metrics,
            sampling_uncertainty=marital_unc,
            cells=marital_cells,
            domain_violations=tuple(marital_violations),
            notes=(
                "Evaluated on the 15+ resident universe (4,856,106 in Ankara 2025) conditioned within sex.",
                "Records aged < 15 are verified to carry 'not_applicable'.",
            ),
        )
    )

    # =========================================================================
    # 5. EDUCATION MARGIN (ankara_education_sex_2025, 15+ NESD universe)
    # =========================================================================
    ds_edu = datasets["ankara_education_sex_2025"]
    prov_edu = _provenance_from_dataset(ds_edu)
    edu_vals = cols.get("education_level", [None] * n_records)

    edu_violations: list[str] = []
    ref_edu: dict[tuple[str, ...], float] = {
        (sx, e): 0.0 for sx in SEX.codes for e in EDUCATION.codes
    }
    for r in ds_edu.rows:
        if r.value is not None:
            ref_edu[(r.dimensions["sex"], r.dimensions["education_level"])] = float(r.value)

    obs_edu_w: dict[tuple[str, ...], float] = {k: 0.0 for k in ref_edu}
    obs_edu_n: dict[tuple[str, ...], int] = {k: 0 for k in ref_edu}

    for i in range(n_records):
        ag = age_groups[i] if i < len(age_groups) else "0-4"
        a_val = ages[i] if i < len(ages) and isinstance(ages[i], int) else (band_bounds(ag)[0] if ag in AGE_GROUPS else 0)
        sx = sexes[i] if i < len(sexes) else None
        e_val = edu_vals[i] if i < len(edu_vals) else None
        w = weights[i] if math.isfinite(weights[i]) and weights[i] > 0 else 0.0

        if a_val < 15:
            if e_val not in (NOT_APPLICABLE, None):
                edu_violations.append(
                    f"Record {i} is under 15 (age={a_val}) but has education_level={e_val!r} "
                    f"(expected {NOT_APPLICABLE!r} for 15+ NESD education table)"
                )
        else:
            if e_val == NOT_APPLICABLE or e_val is None:
                edu_violations.append(
                    f"Record {i} is aged 15+ (age={a_val}) but has education_level={e_val!r}"
                )
            elif e_val not in EDUCATION.codes:
                edu_violations.append(
                    f"Record {i} has invalid education_level={e_val!r} (allowed: {EDUCATION.codes})"
                )
            else:
                if structural_zero("education_level", e_val, a_val):
                    edu_violations.append(
                        f"Record {i} violates minimum-completion-age structural zero: age={a_val} with education_level={e_val!r}"
                    )
                if sx in SEX.codes:
                    obs_edu_w[(sx, e_val)] += w
                    obs_edu_n[(sx, e_val)] += 1

    # NESD 15+ total (4,751,123) is 104,983 smaller than ADNKS 15+ (4,856,106);
    # generator scales NESD target counts per sex to match the root 15+ population per sex.
    ref_edu_by_sex = {
        (sx,): math.fsum(v for (s, _), v in ref_edu.items() if s == sx)
        for sx in SEX.codes
    }
    obs_edu_w_by_sex = {
        (sx,): math.fsum(v for (s, _), v in obs_edu_w.items() if s == sx)
        for sx in SEX.codes
    }
    edu_scale_by_sex = {
        (sx,): (obs_edu_w_by_sex[(sx,)] / ref_edu_by_sex[(sx,)] if ref_edu_by_sex[(sx,)] > 0 else 1.0)
        for sx in SEX.codes
    }
    overall_edu_scale = (
        math.fsum(obs_edu_w_by_sex.values()) / math.fsum(ref_edu_by_sex.values())
        if math.fsum(ref_edu_by_sex.values()) > 0
        else 1.0
    )

    edu_cells, edu_metrics, edu_unc = _evaluate_cells_and_metrics(
        cell_keys=[(sx, e) for sx in SEX.codes for e in EDUCATION.codes],
        dim_names=("sex", "education_level"),
        group_dim_indices=(0,),
        ref_published_counts=ref_edu,
        obs_weighted_counts=obs_edu_w,
        obs_record_counts=obs_edu_n,
        scale_by_group=edu_scale_by_sex,
        overall_scale=overall_edu_scale,
        tolerances=tol,
    )
    edu_status, edu_regime, edu_cal_applied, edu_reason = _decide_check_status(
        margin="education",
        is_calibrated=education_calibrated,
        is_stratified_root=False,
        domain_violations=edu_violations,
        metrics=edu_metrics,
        uncertainty=edu_unc,
        tolerances=tol,
    )
    checks.append(
        PopulationMarginCheck(
            check_id="margin_education",
            margin="education",
            status=edu_status,
            reason=edu_reason,
            population_id=pop_id,
            population_version=pop_version,
            dataset_provenance=prov_edu,
            is_calibrated_margin=education_calibrated,
            evaluation_regime=edu_regime,
            calibration_tolerance_applied=edu_cal_applied,
            metrics=edu_metrics,
            sampling_uncertainty=edu_unc,
            cells=edu_cells,
            domain_violations=tuple(edu_violations),
            notes=(
                "NESD 15+ denominator (4,751,123) is 104,983 smaller than ADNKS 15+ population (4,856,106) "
                "(flag D2_ANKARA_EDUCATION_15PLUS_VS_ADNKS_15PLUS_2025); within-sex shares are compared "
                f"with per-sex universe scaling (male={edu_scale_by_sex[('male',)]:.6f}, female={edu_scale_by_sex[('female',)]:.6f}).",
                "Published 'unknown' category (17,626 in Ankara 2025: 7,474 male, 10,152 female) is preserved and validated.",
                "Minimum-completion-age structural zeros (e.g. higher_education >= 20, masters >= 22, doctorate >= 25) are enforced.",
            ),
        )
    )

    # =========================================================================
    # 6. EMPLOYMENT / LABOUR STATUS MARGIN (ankara_labour_force_rates_2025)
    # =========================================================================
    ds_labour = datasets.get("ankara_labour_force_rates_2025")
    prov_labour = (
        _provenance_from_dataset(ds_labour)
        if ds_labour is not None
        else _provenance_from_entry(ev_reg.get("ankara_labour_force_rates_2025"))
    )
    labour_vals = cols.get("labour_status", [None] * n_records)
    non_null_labour = [v for v in labour_vals if v is not None and v != NOT_APPLICABLE]
    invalid_labour = [v for v in non_null_labour if v not in LABOUR.codes]

    if invalid_labour:
        checks.append(
            PopulationMarginCheck(
                check_id="margin_employment_status",
                margin="employment_status",
                status="fail",
                reason=(
                    f"Population contains invalid labour_status values {sorted(set(invalid_labour))[:3]!r} "
                    f"outside allowed vocabulary {LABOUR.codes}."
                ),
                population_id=pop_id,
                population_version=pop_version,
                dataset_provenance=prov_labour,
                is_calibrated_margin=False,
                evaluation_regime="uncalibrated_sampling_uncertainty",
                calibration_tolerance_applied=False,
                domain_violations=(f"Invalid labour_status categories: {sorted(set(invalid_labour))}",),
            )
        )
    elif ds_labour is not None and ds_labour.unit == "person" and non_null_labour:
        # If caller explicitly supplied a comparable person-count reference dataset and populated labour_status
        ref_lab: dict[tuple[str, ...], float] = {(c,): 0.0 for c in LABOUR.codes}
        for r in ds_labour.rows:
            cat = r.dimensions.get("labour_status") or r.dimensions.get("indicator")
            if cat in LABOUR.codes and r.value is not None:
                ref_lab[(cat,)] += float(r.value)
        obs_lab_w: dict[tuple[str, ...], float] = {(c,): 0.0 for c in LABOUR.codes}
        obs_lab_n: dict[tuple[str, ...], int] = {(c,): 0 for c in LABOUR.codes}
        for i in range(n_records):
            lv = labour_vals[i]
            if lv in LABOUR.codes:
                obs_lab_w[(lv,)] += weights[i]
                obs_lab_n[(lv,)] += 1
        lab_cells, lab_metrics, lab_unc = _evaluate_cells_and_metrics(
            cell_keys=[(c,) for c in LABOUR.codes],
            dim_names=("labour_status",),
            group_dim_indices=(),
            ref_published_counts=ref_lab,
            obs_weighted_counts=obs_lab_w,
            obs_record_counts=obs_lab_n,
            scale_by_group={},
            overall_scale=1.0,
            tolerances=tol,
        )
        lab_status, lab_regime, lab_cal, lab_reason = _decide_check_status(
            margin="employment_status",
            is_calibrated=False,
            is_stratified_root=False,
            domain_violations=[],
            metrics=lab_metrics,
            uncertainty=lab_unc,
            tolerances=tol,
        )
        checks.append(
            PopulationMarginCheck(
                check_id="margin_employment_status",
                margin="employment_status",
                status=lab_status,
                reason=lab_reason,
                population_id=pop_id,
                population_version=pop_version,
                dataset_provenance=prov_labour,
                is_calibrated_margin=False,
                evaluation_regime=lab_regime,
                calibration_tolerance_applied=lab_cal,
                metrics=lab_metrics,
                sampling_uncertainty=lab_unc,
                cells=lab_cells,
            )
        )
    else:
        checks.append(
            PopulationMarginCheck(
                check_id="margin_employment_status",
                margin="employment_status",
                status="not_evaluable",
                reason=(
                    "Not evaluable: (1) ankara_labour_force_rates_2025 publishes only HLFS survey-modelled headline "
                    "percentages (LFPR=53.91%, employment_rate=49.34%, unemployment_rate=8.48% of labour force) with "
                    "±1% confidence intervals for the non-institutional 15+ universe, without person counts or sex/age "
                    "disaggregation (flag D7_PROVINCIAL_LABOUR_FORCE_RATES_ONLY_NO_SEX_OR_COUNTS); and "
                    "(2) person-level labour_status in the core Ankara generator is UNAVAILABLE (None) rather than "
                    "fabricated from non-comparable regional/rate tables."
                ),
                population_id=pop_id,
                population_version=pop_version,
                dataset_provenance=prov_labour,
                is_calibrated_margin=False,
                evaluation_regime="not_evaluable",
                calibration_tolerance_applied=False,
                notes=(
                    "Definitions are not comparable: HLFS excludes institutional residents and reports unemployment "
                    "as a percentage of the labour force rather than ADNKS 15+ resident counts.",
                ),
            )
        )

    # =========================================================================
    # 7. HOUSEHOLD SIZE MARGIN (ankara_household_size_2025, 1,987,216 households)
    # =========================================================================
    ds_hh_size = datasets.get("ankara_household_size_2025")
    prov_hh_size = (
        _provenance_from_dataset(ds_hh_size)
        if ds_hh_size is not None
        else _provenance_from_entry(ev_reg.get("ankara_household_size_2025"))
    )

    res_hh_size_vals = cols.get("household_size_class", [None] * n_records)
    invalid_res_hh_size = [
        v for v in res_hh_size_vals if v is not None and v != NOT_APPLICABLE and v not in HOUSEHOLD_SIZE.codes
    ]
    if invalid_res_hh_size:
        checks.append(
            PopulationMarginCheck(
                check_id="margin_household_size",
                margin="household_size",
                status="fail",
                reason=(
                    f"Population contains invalid household_size_class values {sorted(set(invalid_res_hh_size))[:3]!r} "
                    f"outside allowed vocabulary {HOUSEHOLD_SIZE.codes}."
                ),
                population_id=pop_id,
                population_version=pop_version,
                dataset_provenance=prov_hh_size,
                is_calibrated_margin=False,
                evaluation_regime="uncalibrated_sampling_uncertainty",
                calibration_tolerance_applied=False,
                domain_violations=(f"Invalid household_size_class categories: {sorted(set(invalid_res_hh_size))}",),
            )
        )
    elif hh_cols is not None and ds_hh_size is not None and any(v is not None for v in hh_cols.get("household_size_class", [])):
        hh_size_vals = hh_cols["household_size_class"]
        hh_weights = [float(w) for w in hh_cols.get("household_weight", [1.0] * len(hh_size_vals))]
        hh_size_violations = [
            f"Household record {i} has invalid household_size_class={v!r}"
            for i, v in enumerate(hh_size_vals)
            if v not in HOUSEHOLD_SIZE.codes
        ]
        ref_hh_s: dict[tuple[str, ...], float] = {(c,): 0.0 for c in HOUSEHOLD_SIZE.codes}
        for r in ds_hh_size.rows:
            if r.value is not None:
                ref_hh_s[(r.dimensions["household_size_class"],)] = float(r.value)
        obs_hh_sw: dict[tuple[str, ...], float] = {(c,): 0.0 for c in HOUSEHOLD_SIZE.codes}
        obs_hh_sn: dict[tuple[str, ...], int] = {(c,): 0 for c in HOUSEHOLD_SIZE.codes}
        for v, w in zip(hh_size_vals, hh_weights):
            if v in HOUSEHOLD_SIZE.codes:
                obs_hh_sw[(v,)] += w
                obs_hh_sn[(v,)] += 1
        hhs_cells, hhs_metrics, hhs_unc = _evaluate_cells_and_metrics(
            cell_keys=[(c,) for c in HOUSEHOLD_SIZE.codes],
            dim_names=("household_size_class",),
            group_dim_indices=(),
            ref_published_counts=ref_hh_s,
            obs_weighted_counts=obs_hh_sw,
            obs_record_counts=obs_hh_sn,
            scale_by_group={},
            overall_scale=1.0,
            tolerances=tol,
        )
        hhs_status, hhs_regime, hhs_cal, hhs_reason = _decide_check_status(
            margin="household_size",
            is_calibrated=True,
            is_stratified_root=True,
            domain_violations=hh_size_violations,
            metrics=hhs_metrics,
            uncertainty=hhs_unc,
            tolerances=tol,
        )
        checks.append(
            PopulationMarginCheck(
                check_id="margin_household_size",
                margin="household_size",
                status=hhs_status,
                reason=hhs_reason,
                population_id=pop_id,
                population_version=pop_version,
                dataset_provenance=prov_hh_size,
                is_calibrated_margin=True,
                evaluation_regime=hhs_regime,
                calibration_tolerance_applied=hhs_cal,
                metrics=hhs_metrics,
                sampling_uncertainty=hhs_unc,
                cells=hhs_cells,
                domain_violations=tuple(hh_size_violations),
                notes=(
                    "Evaluated on unlinked household sample against 1,987,216 private households (flag D1_ANKARA_HH_VS_RESIDENT_POP_2025: "
                    "219,693 resident gap vs 5,910,320 total ADNKS population is documented, never forced).",
                ),
            )
        )
    else:
        checks.append(
            PopulationMarginCheck(
                check_id="margin_household_size",
                margin="household_size",
                status="not_evaluable",
                reason=(
                    "Not evaluable on resident-only population: (1) ankara_household_size_2025 is denominated in private "
                    "households (expected_total=1,987,216, unit='household'), which does not reconcile to Ankara's "
                    "5,910,320 ADNKS resident population (implied private-household population = 5,690,627; unreconciled "
                    "institutional/collective gap = 219,693 persons, flag D1_ANKARA_HH_VS_RESIDENT_POP_2025); "
                    "(2) resident records keep household_size_class=None (UNAVAILABLE) rather than forcing an unverified "
                    "person-to-household linkage; and (3) optional local raw file data/raw/ankara_household_size_2025.csv "
                    f"is {'loaded' if ds_hh_size is not None else 'absent in this clean checkout'}."
                ),
                population_id=pop_id,
                population_version=pop_version,
                dataset_provenance=prov_hh_size,
                is_calibrated_margin=False,
                evaluation_regime="not_evaluable",
                calibration_tolerance_applied=False,
                notes=(
                    "Discrepancy D1_ANKARA_HH_VS_RESIDENT_POP_2025 is preserved as a documented data-quality flag.",
                ),
            )
        )

    # =========================================================================
    # 8. HOUSEHOLD TYPE MARGIN (ankara_household_types_2025, 1,987,216 households)
    # =========================================================================
    ds_hh_type = datasets["ankara_household_types_2025"]
    prov_hh_type = _provenance_from_dataset(ds_hh_type)

    res_hh_type_vals = cols.get("household_type", [None] * n_records)
    invalid_res_hh_type = [
        v for v in res_hh_type_vals if v is not None and v != NOT_APPLICABLE and v not in HOUSEHOLD_TYPE.codes
    ]
    if invalid_res_hh_type:
        checks.append(
            PopulationMarginCheck(
                check_id="margin_household_type",
                margin="household_type",
                status="fail",
                reason=(
                    f"Population contains invalid household_type values {sorted(set(invalid_res_hh_type))[:3]!r} "
                    f"outside allowed vocabulary {HOUSEHOLD_TYPE.codes}."
                ),
                population_id=pop_id,
                population_version=pop_version,
                dataset_provenance=prov_hh_type,
                is_calibrated_margin=False,
                evaluation_regime="uncalibrated_sampling_uncertainty",
                calibration_tolerance_applied=False,
                domain_violations=(f"Invalid household_type categories: {sorted(set(invalid_res_hh_type))}",),
            )
        )
    elif hh_cols is not None and any(v is not None for v in hh_cols.get("household_type", [])):
        hh_type_vals = hh_cols["household_type"]
        hh_weights = [float(w) for w in hh_cols.get("household_weight", [1.0] * len(hh_type_vals))]
        hh_type_violations = [
            f"Household record {i} has invalid household_type={v!r}"
            for i, v in enumerate(hh_type_vals)
            if v not in HOUSEHOLD_TYPE.codes
        ]
        ref_hh_t: dict[tuple[str, ...], float] = {(c,): 0.0 for c in HOUSEHOLD_TYPE.codes}
        for r in ds_hh_type.rows:
            if r.value is not None:
                ref_hh_t[(r.dimensions["household_type"],)] = float(r.value)
        obs_hh_tw: dict[tuple[str, ...], float] = {(c,): 0.0 for c in HOUSEHOLD_TYPE.codes}
        obs_hh_tn: dict[tuple[str, ...], int] = {(c,): 0 for c in HOUSEHOLD_TYPE.codes}
        for v, w in zip(hh_type_vals, hh_weights):
            if v in HOUSEHOLD_TYPE.codes:
                obs_hh_tw[(v,)] += w
                obs_hh_tn[(v,)] += 1
        hh_type_calibrated = bool(hh_manifest and "fit" in hh_manifest)
        hht_cells, hht_metrics, hht_unc = _evaluate_cells_and_metrics(
            cell_keys=[(c,) for c in HOUSEHOLD_TYPE.codes],
            dim_names=("household_type",),
            group_dim_indices=(),
            ref_published_counts=ref_hh_t,
            obs_weighted_counts=obs_hh_tw,
            obs_record_counts=obs_hh_tn,
            scale_by_group={},
            overall_scale=1.0,
            tolerances=tol,
        )
        hht_status, hht_regime, hht_cal, hht_reason = _decide_check_status(
            margin="household_type",
            is_calibrated=hh_type_calibrated,
            is_stratified_root=False,
            domain_violations=hh_type_violations,
            metrics=hht_metrics,
            uncertainty=hht_unc,
            tolerances=tol,
        )
        checks.append(
            PopulationMarginCheck(
                check_id="margin_household_type",
                margin="household_type",
                status=hht_status,
                reason=hht_reason,
                population_id=pop_id,
                population_version=pop_version,
                dataset_provenance=prov_hh_type,
                is_calibrated_margin=hh_type_calibrated,
                evaluation_regime=hht_regime,
                calibration_tolerance_applied=hht_cal,
                metrics=hht_metrics,
                sampling_uncertainty=hht_unc,
                cells=hht_cells,
                domain_violations=tuple(hh_type_violations),
                notes=(
                    "Evaluated on unlinked household sample against ankara_household_types_2025 (1,987,216 private households; "
                    "flag D1_ANKARA_HH_VS_RESIDENT_POP_2025).",
                ),
            )
        )
    else:
        checks.append(
            PopulationMarginCheck(
                check_id="margin_household_type",
                margin="household_type",
                status="not_evaluable",
                reason=(
                    "Not evaluable on resident-only population: (1) ankara_household_types_2025 reports 1,987,216 private "
                    "households (unit='household': one_person=407,306, nuclear_family=1,312,420, extended_family=193,972, "
                    "non_family_multi_person=73,518; average_household_size=2.863618 -> 5,690,627 private-household residents), "
                    "leaving an unreconciled 219,693-person gap vs Ankara's 5,910,320 ADNKS resident population "
                    "(flag D1_ANKARA_HH_VS_RESIDENT_POP_2025); and (2) resident records keep household_type=None (UNAVAILABLE) "
                    "because person-level household-type membership is not observed in provincial ADNKS tables."
                ),
                population_id=pop_id,
                population_version=pop_version,
                dataset_provenance=prov_hh_type,
                is_calibrated_margin=False,
                evaluation_regime="not_evaluable",
                calibration_tolerance_applied=False,
                notes=(
                    "Pass an unlinked household sample via `households=...` to evaluate household_type against "
                    "ankara_household_types_2025 (1,987,216 households).",
                ),
            )
        )

    # Aggregate status counts and overall status
    status_counts: dict[CheckStatus, int] = {"pass": 0, "fail": 0, "not_evaluable": 0}
    for chk in checks:
        status_counts[chk.status] += 1

    if status_counts["fail"] > 0:
        overall_status: CheckStatus = "fail"
        failed_names = [c.margin for c in checks if c.status == "fail"]
        summary_reason = (
            f"Validation FAILED on {len(failed_names)} margin(s) ({', '.join(failed_names)}); "
            f"{status_counts['pass']} passed and {status_counts['not_evaluable']} not_evaluable."
        )
    elif status_counts["pass"] > 0:
        overall_status = "pass"
        passed_names = [c.margin for c in checks if c.status == "pass"]
        ne_names = [c.margin for c in checks if c.status == "not_evaluable"]
        summary_reason = (
            f"All {len(passed_names)} evaluable margin(s) PASSED ({', '.join(passed_names)}); "
            f"{len(ne_names)} margin(s) marked not_evaluable ({', '.join(ne_names)}) due to documented "
            f"unit/denominator incompatibilities (D1 household vs resident population, D7 rate-only HLFS)."
        )
    else:
        overall_status = "not_evaluable"
        summary_reason = "All checks returned not_evaluable."

    return PopulationValidationReport(
        population_id=pop_id,
        population_version=pop_version,
        reference_package_version=pkg_version,
        reference_package_fingerprint=pkg_fp,
        geography_code="06",
        reference_year=ref_year,
        sample_size=n_records,
        weighted_population_total=weighted_total,
        seed=seed,
        overall_status=overall_status,
        status_counts=status_counts,
        calibration_tolerances=tol,
        tolerance_justification=tol.justification(),
        checks=tuple(checks),
        documented_discrepancies=(
            ANKARA_HOUSEHOLD_DISCREPANCY_FLAG,
            EDUCATION_UNIVERSE_GAP_FLAG,
            LABOUR_RATE_ONLY_FLAG,
        ),
        summary_reason=summary_reason,
    )
