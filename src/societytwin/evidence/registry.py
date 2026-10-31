"""Evidence Registry (K1) extending the existing Population Engine DependencyRegistry.

Core rules:
- Do not create a second competing YAML registry: directly wrap and extend
  ``societytwin.national.dependencies.DependencyRegistry`` (and its bound
  ``HouseholdRegistry``, ``TypeSizeRegistry``, ``ExtensionRegistry``,
  ``data/manifest.yaml``, and ``data/tuik_package_mapping.yaml``).
- Every entry carries: ``dataset_id``, ``source``, ``geography``, ``year``,
  ``dimensions``, ``unit``, ``status``, ``source_reference``, ``retrieval_info``,
  ``denominator``, ``category_definitions``, ``sha256``, ``caveats``, and
  ``data_quality_flags``.
- Never present national data (``TR``) as Ankara-specific (``06``), or synthetic
  examples as observed evidence.
- Encode the Ankara 1,987,216 household count vs 5,910,320 resident population
  discrepancy (and all Phase 1 statistical discrepancies) as explicit, machine-readable
  ``DataQualityFlag`` records attached to the relevant datasets, never as a
  silently "fixed" number.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from societytwin.common import canonical_hash
from societytwin.enrichment.registry import (
    ExtensionRegistry,
    load_registry as load_extension_registry,
)
from societytwin.households.registry import (
    CLASSES as HOUSEHOLD_SIZE_CLASSES,
    HouseholdRegistry,
    load_registry as load_household_registry,
)
from societytwin.households.type_size_registry import (
    BANDS as HOUSEHOLD_TYPE_SIZE_BANDS,
    TYPES as HOUSEHOLD_TYPES,
    TypeSizeRegistry,
    load_type_size_registry,
)
from societytwin.national.dependencies import (
    DEFAULT_REGISTRY_PATH,
    DependencyRegistry,
    RegistryError,
    Scope,
    TypedModel,
    compile_compatibility,
    load_registry as load_dependency_registry,
)
from societytwin.national.vocab import (
    AGE_GROUPS,
    EDUCATION,
    HOUSEHOLD_SIZE,
    HOUSEHOLD_TYPE,
    LABOUR,
    MARITAL,
    SEX,
    URBANICITY,
    Vocabulary,
)

EVIDENCE_REGISTRY_SCHEMA_VERSION = "evidence-registry-k1-v1"
EVIDENCE_REGISTRY_VERSION = "ankara-evidence-k1-2025.1"

GeographyCode = Literal["06", "TR", "TR51", "81_provinces", "06_districts"]
GeographyLevel = Literal["province", "national", "nuts2", "multi_province", "district"]
DatasetStatus = Literal[
    "observed",
    "observed_with_caveats",
    "national_transfer_seed",
    "context_only",
    "projection_quarantined",
    "local_raw_optional",
    "unavailable",
]


class GeographyScope(TypedModel):
    """Explicit geographic scope with mandatory national-vs-Ankara separation."""

    code: GeographyCode
    level: GeographyLevel
    name: str = Field(min_length=1)
    province_code: str | None = None
    nuts2_code: str | None = None
    nuts3_code: str | None = None
    is_national: StrictBool = False
    is_ankara_specific: StrictBool = False
    scope_marker: Literal[
        "ANKARA_OBSERVED",
        "PROVINCE_OBSERVED_INCLUDES_ANKARA",
        "ANKARA_DISTRICT_OBSERVED",
        "NATIONAL_ONLY_NOT_ANKARA_SPECIFIC",
        "REGIONAL_OR_CONTEXT",
    ]

    @model_validator(mode="after")
    def validate_scope_honesty(self):
        if self.is_national and self.is_ankara_specific:
            raise ValueError("A dataset cannot be both national-only and Ankara-specific")
        if self.code == "TR" and (not self.is_national or self.is_ankara_specific):
            raise ValueError("National (TR) geography must set is_national=True and is_ankara_specific=False")
        if self.code == "TR" and self.scope_marker != "NATIONAL_ONLY_NOT_ANKARA_SPECIFIC":
            raise ValueError("National (TR) datasets must carry scope_marker='NATIONAL_ONLY_NOT_ANKARA_SPECIFIC'")
        if self.code == "06" and self.province_code != "06":
            raise ValueError("Ankara geography ('06') must set province_code='06'")
        return self


class SourceReference(TypedModel):
    """Official statistical publication / table provenance."""

    agency: str = Field(min_length=1)
    publication_title: str = Field(min_length=1)
    table_id: str = Field(min_length=1)
    sdmx_dataflow: str | None = None
    publication_year: StrictInt | None = None
    publication_date: str | None = None
    url: str | None = None
    parent_registry_source_id: str | None = None
    manifest_dataset_id: str | None = None


class RetrievalInfo(TypedModel):
    """Physical file location, format, and extraction filter parameters."""

    relative_path: str = Field(min_length=1)
    storage_root: Literal["repo_root", "tuik_package_dir"] = "tuik_package_dir"
    file_format: Literal["csv", "yaml"] = "csv"
    encoding: str = "utf-8-sig"
    layout: Literal[
        "tuik_long_provincial",
        "tuik_long_district",
        "legacy_age_gender_csv",
        "legacy_marital_gender_csv",
        "legacy_controls_csv",
        "nip_household_size_csv",
        "national_marital_seed_yaml",
        "national_type_size_csv",
        "ankara_household_type_csv",
        "ankara_degurba_sex_csv",
        "mobility_evidence_csv",
    ]
    filter_province_code: str | None = None
    filter_year: StrictInt | str | None = None
    indicator_pattern: str | None = None
    total_patterns: tuple[str, ...] = ()
    residual_pattern: str | None = None
    category_label_map: dict[str, str] = Field(default_factory=dict)
    verification_date: str = "2026-10-27"
    optional_local_file: StrictBool = False


class DenominatorSpec(TypedModel):
    """Explicit universe and denominator definition (never silently coerced)."""

    universe: str = Field(min_length=1)
    unit: Literal["person", "household", "percent", "rate", "try", "mixed"]
    min_age: StrictInt | None = None
    max_age: StrictInt | None = None
    expected_total: float | int | None = None
    expected_by_sex: dict[str, int | float] = Field(default_factory=dict)
    reconciles_to_root_population: StrictBool = True
    root_dataset_id: str | None = "ankara_age_sex_2025"
    expected_gap_vs_root: int | float | None = None
    inconsistency_reason: str | None = None


class CategoryDefinition(TypedModel):
    """Canonical category code, source labels, and structural properties."""

    code: str = Field(min_length=1)
    label_en: str = Field(min_length=1)
    label_tr: str | None = None
    source_aliases: tuple[str, ...] = ()
    kind: Literal["known", "published_unknown", "residual_unclassified", "open_ended_tail", "aggregate_total"] = "known"
    min_age_constraint: StrictInt | None = None
    lower_bound: StrictInt | None = None
    upper_bound: StrictInt | None = None
    is_open_ended: StrictBool = False


class DataQualityFlag(TypedModel):
    """Documented statistical discrepancy or data-quality issue (never silently fixed)."""

    flag_id: str = Field(min_length=1)
    severity: Literal["high", "medium", "info"] = "high"
    issue_type: Literal[
        "denominator_inconsistency",
        "universe_coverage_gap",
        "open_ended_tail",
        "administrative_reclassification",
        "rounding_interval_ambiguity",
        "subprovincial_unknown_residual",
        "metadata_documentation_mismatch",
        "projection_vs_realized_gap",
        "duplicate_source_rows",
        "rate_only_no_counts",
    ]
    summary: str = Field(min_length=1)
    observed_values: dict[str, int | float | str] = Field(default_factory=dict)
    root_causes: tuple[str, ...] = Field(min_length=1)
    handling_policy: Literal[
        "document_do_not_force",
        "preserve_unknown_category",
        "quarantine_projection",
        "require_explicit_transfer_marker",
        "not_evaluable_for_person_counts",
    ] = "document_do_not_force"


class EvidenceDatasetEntry(TypedModel):
    """Single K1 evidence dataset entry linked to the parent DependencyRegistry."""

    dataset_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    geography: GeographyScope
    year: StrictInt | str
    available_years: tuple[StrictInt | str, ...] = ()
    dimensions: tuple[str, ...] = Field(min_length=1)
    scope: Scope = "person"
    unit: Literal["person", "household", "percent", "rate", "try", "mixed"]
    status: DatasetStatus
    source_reference: SourceReference
    retrieval_info: RetrievalInfo
    denominator: DenominatorSpec
    category_definitions: dict[str, tuple[CategoryDefinition, ...]] = Field(default_factory=dict)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    caveats: tuple[str, ...] = ()
    data_quality_flags: tuple[DataQualityFlag, ...] = ()
    dependency_registry_attributes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_entry_consistency(self):
        if self.unit != self.denominator.unit:
            raise ValueError(f"dataset {self.dataset_id}: unit {self.unit!r} != denominator.unit {self.denominator.unit!r}")
        if self.geography.is_national and self.status not in ("national_transfer_seed", "context_only", "local_raw_optional"):
            raise ValueError(
                f"dataset {self.dataset_id}: national dataset must have status 'national_transfer_seed', "
                f"'context_only', or 'local_raw_optional' (got {self.status!r})"
            )
        return self


def _vocab_to_categories(
    vocab: Vocabulary,
    *,
    min_ages: dict[str, int] | None = None,
    open_tail_code: str | None = None,
    open_tail_lower: int | None = None,
) -> tuple[CategoryDefinition, ...]:
    out = []
    for code in vocab.codes:
        aliases = tuple(alias for alias, target in vocab.source_aliases.items() if target == code)
        kind: Literal["known", "published_unknown", "residual_unclassified", "open_ended_tail", "aggregate_total"] = "known"
        if code == "unknown":
            kind = "published_unknown"
        elif code == open_tail_code:
            kind = "open_ended_tail"
        low = open_tail_lower if code == open_tail_code else (int(code) if code.isdigit() else None)
        high = None if code == open_tail_code else (int(code) if code.isdigit() else None)
        out.append(
            CategoryDefinition(
                code=code,
                label_en=vocab.labels_en.get(code, code),
                label_tr=vocab.labels_tr.get(code),
                source_aliases=aliases,
                kind=kind,
                min_age_constraint=(min_ages or {}).get(code),
                lower_bound=low,
                upper_bound=high,
                is_open_ended=(code == open_tail_code),
            )
        )
    return tuple(out)


def _age_group_categories() -> tuple[CategoryDefinition, ...]:
    out = []
    for band in AGE_GROUPS:
        if band.endswith("+"):
            low = int(band[:-1])
            out.append(
                CategoryDefinition(
                    code=band,
                    label_en=f"{low} years and over",
                    label_tr=f"{low}+ yaş",
                    source_aliases=(f"{low}_plus", f"pop_age_{low}_plus"),
                    kind="open_ended_tail",
                    lower_bound=low,
                    upper_bound=None,
                    is_open_ended=True,
                )
            )
        else:
            low_s, high_s = band.split("-")
            low, high = int(low_s), int(high_s)
            out.append(
                CategoryDefinition(
                    code=band,
                    label_en=f"{low} to {high} years",
                    label_tr=f"{low}-{high} yaş",
                    source_aliases=(f"{low}_{high}", f"pop_age_{low}_{high}"),
                    kind="known",
                    lower_bound=low,
                    upper_bound=high,
                    is_open_ended=False,
                )
            )
    return tuple(out)


# ---------------------------------------------------------------------------
# Explicit Flagged Statistical Discrepancies (Phase 1 Audit D1–D9)
# ---------------------------------------------------------------------------

ANKARA_HOUSEHOLD_DISCREPANCY_FLAG = DataQualityFlag(
    flag_id="D1_ANKARA_HH_VS_RESIDENT_POP_2025",
    severity="high",
    issue_type="denominator_inconsistency",
    summary=(
        "Ankara 2025 private household count (1,987,216) and implied private-household population "
        "(1,987,216 × 2.86361774462363 = 5,690,627 persons; or 5,683,438 using rounded 2.86) do NOT "
        "reconcile to total ADNKS resident population (5,910,320 persons). Exact unreconciled gap: "
        "219,693 persons (3.7171% of Ankara resident population)."
    ),
    observed_values={
        "ankara_2025_adnks_resident_population": 5910320,
        "ankara_2025_private_households_total": 1987216,
        "ankara_2025_average_household_size": 2.86361774462363,
        "ankara_2025_implied_private_household_population": 5690627,
        "ankara_2025_unreconciled_institutional_and_tail_gap_persons": 219693,
        "ankara_2025_gap_share_pct": 3.7171,
        "ankara_2021_housing_census_households": 1874093,
        "ankara_2023_ses_3yr_avg_households": 1927404.6666666667,
    },
    root_causes=(
        "1. Institutional/collective population exclusion: ADNKS total resident population (5,910,320) includes "
        "institutional/collective places (KYK and private university dormitories, military barracks, prisons, "
        "nursing homes, hospitals), which are excluded by definition from ADNKS_private_households (1,987,216).",
        "2. Open-ended 10+ household size tail: In the NIP household size table (1..9, 10+), the 10+ class has "
        "only a known lower bound (10) and no published upper bound or exact mean size.",
        "3. Different reference years & multi-year averaging across household tables: 2021 Building & Dwelling "
        "Survey reports 1,874,093 households (2021 ADNKS base), while 2023 SES reports 1,927,404.67 households "
        "(2022–2024 3-year administrative register average).",
        "4. Absence of public person-to-household micro-linkage tables at Ankara (06) level.",
    ),
    handling_policy="document_do_not_force",
)

EDUCATION_UNIVERSE_GAP_FLAG = DataQualityFlag(
    flag_id="D2_ANKARA_EDUCATION_15PLUS_VS_ADNKS_15PLUS_2025",
    severity="high",
    issue_type="universe_coverage_gap",
    summary=(
        "Ankara 2025 NESD Education 15+ total (4,751,123: 2,322,692 male, 2,428,431 female) is 104,983 persons "
        "(2.1619%) smaller than Ankara 2025 ADNKS 15+ resident population (4,856,106: 2,371,482 male, "
        "2,484,624 female). Nationally in 2025, the gap is 1,340,559 persons (67,220,886 vs 68,561,445) and "
        "correlates r = 0.999766 across all 81 provinces with foreign resident population (T12)."
    ),
    observed_values={
        "ankara_2025_adnks_15plus_total": 4856106,
        "ankara_2025_adnks_15plus_male": 2371482,
        "ankara_2025_adnks_15plus_female": 2484624,
        "ankara_2025_nesd_edu_15plus_total": 4751123,
        "ankara_2025_nesd_edu_15plus_male": 2322692,
        "ankara_2025_nesd_edu_15plus_female": 2428431,
        "ankara_2025_edu_universe_gap_total": 104983,
        "ankara_2025_edu_universe_gap_male": 48790,
        "ankara_2025_edu_universe_gap_female": 56193,
        "ankara_2025_edu_unknown_total": 17626,
        "ankara_2025_foreign_resident_population_total": 128633,
        "national_2025_pearson_r_with_foreign_pop": 0.999766,
    },
    root_causes=(
        "1. NESD (Ulusal Eğitim İstatistikleri Veri Tabanı) derives diploma attainment from domestic MERNİS/MEB/YÖK "
        "registers, excluding most foreign nationals residing in Türkiye on residence permits (128,633 in Ankara 2025).",
        "2. Published 'unknown' (Bilinmeyen) category (17,626 in Ankara 2025: 7,474 male, 10,152 female) is part of "
        "the 4,751,123 NESD total and must be preserved as a distinct category, never silently dropped.",
    ),
    handling_policy="preserve_unknown_category",
)

MARITAL_HISTORICAL_GAP_FLAG = DataQualityFlag(
    flag_id="D3_MARITAL_15PLUS_HISTORICAL_UNIVERSE_AND_2008_UNKNOWN",
    severity="medium",
    issue_type="universe_coverage_gap",
    summary=(
        "Marital status 15+ (T10) matches ADNKS 15+ population with 0 discrepancy in 2021–2025 (4,856,106 in "
        "Ankara 2025), but in 2016–2020 its total is smaller than ADNKS 15+ by 57,237–128,236 in Ankara (matching "
        "the NESD Education 15+ total). In 2008 only, the 4 published categories sum to 44 less than total "
        "nationally (3 in Ankara) due to unpublished 'unknown' (Bilinmeyen) marital status."
    ),
    observed_values={
        "ankara_2025_adnks_15plus_total": 4856106,
        "ankara_2025_marital_15plus_total": 4856106,
        "ankara_2025_gap": 0,
        "ankara_2020_marital_gap_vs_adnks_15plus": 114174,
        "national_2008_unpublished_unknown_residual": 44,
        "ankara_2008_unpublished_unknown_residual": 3,
    },
    root_causes=(
        "1. Prior to 2021, provincial marital status tabulations excluded the same foreign national universe as NESD.",
        "2. In 2008, 44 persons nationally (3 in Ankara) had unknown marital status included in the published total "
        "without a separate category row in the long CSV.",
    ),
    handling_policy="document_do_not_force",
)

METROPOLITAN_URBANICITY_LAW6360_FLAG = DataQualityFlag(
    flag_id="D4_ANKARA_LAW6360_ADMIN_URBANICITY_VS_DEGURBA",
    severity="high",
    issue_type="administrative_reclassification",
    summary=(
        "From 2013 onward, Ankara (and 29 other metropolitan provinces) has no town_village rows in administrative "
        "urban/rural statistics (T14) because Law No. 6360 reclassified all villages as urban neighbourhoods "
        "(mahalle), assigning 100% of Ankara's 5,910,320 residents to province_district_centre. By contrast, "
        "2025 spatial-grid DEGURBA (T37) classifies Ankara into 5,182,618 dense_urban (87.69%), 477,753 "
        "intermediate_urban (8.08%), and 249,949 rural (4.23%)."
    ),
    observed_values={
        "ankara_2025_admin_province_district_centre": 5910320,
        "ankara_2025_degurba_dense_urban": 5182618,
        "ankara_2025_degurba_intermediate_urban": 477753,
        "ankara_2025_degurba_rural": 249949,
    },
    root_causes=(
        "1. Law No. 6360 (effective 2013) abolished legal village (köy) and town (belde) entities in 30 metropolitan "
        "provinces, making administrative urbanicity 100% province_district_centre.",
        "2. Spatial settlement morphology is measured separately by TÜİK's DEGURBA classification (T37, 2022–2025).",
    ),
    handling_policy="document_do_not_force",
)

DISTRICT_DIVORCE_UNKNOWN_FLAG = DataQualityFlag(
    flag_id="D5_ANKARA_DISTRICT_DIVORCE_BILINMEYEN_RESIDUAL",
    severity="medium",
    issue_type="subprovincial_unknown_residual",
    summary=(
        "In 2025, the sum of divorces across Ankara's 25 districts (15,843) is 182 less than Ankara's provincial "
        "divorce total (16,025; and 15,431 vs 15,601 in 2024, gap = 170), whereas marriages match exactly "
        "(36,210 in 2025; 37,292 in 2024)."
    ),
    observed_values={
        "ankara_2025_province_divorces": 16025,
        "ankara_2025_25districts_divorces_sum": 15843,
        "ankara_2025_unknown_district_divorces": 182,
        "ankara_2025_province_marriages": 36210,
        "ankara_2025_25districts_marriages_sum": 36210,
    },
    root_causes=(
        "Court divorce decrees in Ankara where the sub-provincial district of registration is coded 'Bilinmeyen' "
        "(Unknown) are counted in the province total (06) but excluded from the 25 named districts.",
    ),
    handling_policy="document_do_not_force",
)

NATIONAL_MARITAL_ROUNDING_FLAG = DataQualityFlag(
    flag_id="D6_NATIONAL_MARITAL_15_24_WIDOWED_ROUNDED_ZERO",
    severity="high",
    issue_type="rounding_interval_ambiguity",
    summary=(
        "National marital seed (İstatistiklerle Kadın 2025, Table 1.9) publishes 1-decimal percentages at National "
        "(TR) geography for broad age bands (15-24, 25+), where 'widowed' in 15-24 is printed as 0.0% (< 0.05 pp, "
        "not a structural zero)."
    ),
    observed_values={
        "geography": "TR",
        "precision_pp": 0.1,
        "male_15_24_widowed_published_pct": 0.0,
        "female_15_24_widowed_published_pct": 0.0,
    },
    root_causes=(
        "1. Published only at National (TR) level with 0.1 percentage-point precision across 2 broad age bands.",
        "2. 0.0% represents the rounding interval [0.00%, 0.05%), not an exact zero.",
    ),
    handling_policy="require_explicit_transfer_marker",
)

LABOUR_RATE_ONLY_FLAG = DataQualityFlag(
    flag_id="D7_PROVINCIAL_LABOUR_FORCE_RATES_ONLY_NO_SEX_OR_COUNTS",
    severity="high",
    issue_type="rate_only_no_counts",
    summary=(
        "Provincial labor_force_indicators.csv (2022–2025) publishes only headline 15+ model-estimated percentages "
        "(LFPR 53.91%, employment rate 49.34%, unemployment rate 8.48% in Ankara 2025) with 95% confidence intervals, "
        "without sex breakdown, age breakdown, or person counts (contrary to package README.md line 51)."
    ),
    observed_values={
        "ankara_2025_lfpr_pct": 53.91313762678153,
        "ankara_2025_employment_rate_pct": 49.34075664916479,
        "ankara_2025_unemployment_rate_pct": 8.481014422253542,
    },
    root_causes=(
        "1. Detailed Household Labour Force Survey (HLFS) tables by sex, age, and education are published only at "
        "NUTS-2 (TR51) and National (TR) levels (see not_province_level.csv).",
        "2. Converting survey model rates with ±1% CIs into exact integer person counts would fabricate precision.",
    ),
    handling_policy="not_evaluable_for_person_counts",
)

PROJECTION_VS_REALIZED_FLAG = DataQualityFlag(
    flag_id="D8_POPULATION_PROJECTIONS_VS_REALIZED_ADNKS_2024_2025",
    severity="medium",
    issue_type="projection_vs_realized_gap",
    summary=(
        "TÜİK 2024–2030 projections (2023 base) project Ankara population as 5,849,348 in 2024 and 5,886,877 in 2025, "
        "differing from realized ADNKS counts (5,864,049 in 2024; 5,910,320 in 2025) by -14,701 and -23,443 persons."
    ),
    observed_values={
        "ankara_2024_projected": 5849348,
        "ankara_2024_realized_adnks": 5864049,
        "ankara_2025_projected": 5886877,
        "ankara_2025_realized_adnks": 5910320,
    },
    root_causes=(
        "Projections were compiled on the 2023 ADNKS baseline before 2024 and 2025 ADNKS administrative registers were finalized.",
    ),
    handling_policy="quarantine_projection",
)

LEGACY_CONTROLS_DUPLICATE_FLAG = DataQualityFlag(
    flag_id="D9_LEGACY_ANKARA_CONTROLS_2024_MEDIAN_AGE_DUPLICATES",
    severity="info",
    issue_type="duplicate_source_rows",
    summary=(
        "ankara_demographic_controls.csv contains 3 duplicate rows for 2024 median age (female, male, total) "
        "extracted from both the 2024 and 2025 TÜİK Excel workbooks with identical numeric values."
    ),
    observed_values={
        "duplicate_2024_rows": 3,
        "female_median_age_2024": 36.797147871308795,
        "male_median_age_2024": 35.040515220402796,
        "total_median_age_2024": 35.93383819428382,
    },
    root_causes=(
        "Overlapping multi-year Excel workbook extraction in legacy preprocessing script.",
    ),
    handling_policy="document_do_not_force",
)


class EvidenceRegistry(TypedModel):
    """Versioned K1 Evidence Registry extending the existing DependencyRegistry.

    Wraps the unmodified ``DependencyRegistry`` (``ankara-core-1``) and companion
    household/sidecar registries without creating a competing YAML registry.
    """

    schema_version: Literal["evidence-registry-k1-v1"] = EVIDENCE_REGISTRY_SCHEMA_VERSION
    evidence_registry_version: str = EVIDENCE_REGISTRY_VERSION
    parent_dependency_registry_version: str = Field(min_length=1)
    parent_dependency_registry_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    household_registry_version: str = Field(min_length=1)
    type_size_registry_version: str = Field(min_length=1)
    extension_registry_version: str = Field(min_length=1)
    datasets: dict[str, EvidenceDatasetEntry]

    @model_validator(mode="after")
    def validate_datasets(self):
        for ds_id, entry in self.datasets.items():
            if entry.dataset_id != ds_id:
                raise ValueError(f"Dataset key {ds_id!r} does not match entry.dataset_id {entry.dataset_id!r}")
        return self

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def get(self, dataset_id: str) -> EvidenceDatasetEntry:
        if dataset_id not in self.datasets:
            raise KeyError(f"Unknown evidence dataset_id {dataset_id!r}. Available: {sorted(self.datasets)}")
        return self.datasets[dataset_id]

    def search(
        self,
        *,
        geography: str | None = None,
        year: int | str | None = None,
        dimension: str | None = None,
        status: DatasetStatus | str | None = None,
        scope: Scope | None = None,
        unit: str | None = None,
        ankara_only: bool | None = None,
        national_only: bool | None = None,
        attribute: str | None = None,
    ) -> tuple[EvidenceDatasetEntry, ...]:
        """Search evidence entries by geography, year, dimension, status, scope, unit, or attribute."""
        results: list[EvidenceDatasetEntry] = []
        for entry in self.datasets.values():
            if geography is not None:
                geo_match = (
                    entry.geography.code == geography
                    or entry.geography.province_code == geography
                    or entry.geography.level == geography
                    or entry.geography.scope_marker == geography
                )
                if not geo_match:
                    continue
            if year is not None:
                if entry.year != year and year not in entry.available_years and str(year) not in map(str, entry.available_years):
                    continue
            if dimension is not None and dimension not in entry.dimensions:
                continue
            if status is not None and entry.status != status:
                continue
            if scope is not None and entry.scope != scope:
                continue
            if unit is not None and entry.unit != unit:
                continue
            if ankara_only is True and not entry.geography.is_ankara_specific:
                continue
            if national_only is True and not entry.geography.is_national:
                continue
            if attribute is not None and attribute not in entry.dependency_registry_attributes:
                continue
            results.append(entry)
        return tuple(results)


def _build_default_entries(
    dep_reg: DependencyRegistry,
    hh_reg: HouseholdRegistry,
    ts_reg: TypeSizeRegistry,
    ext_reg: ExtensionRegistry,
) -> dict[str, EvidenceDatasetEntry]:
    sex_cats = _vocab_to_categories(SEX)
    age_cats = _age_group_categories()
    marital_cats = _vocab_to_categories(MARITAL)
    edu_cats = _vocab_to_categories(
        EDUCATION,
        min_ages={
            "primary": 11,
            "basic_8yr": 14,
            "lower_secondary": 14,
            "upper_secondary": 17,
            "higher_education": 20,
            "masters": 22,
            "doctorate": 25,
        },
    )
    urban_cats = _vocab_to_categories(URBANICITY)
    hh_size_cats = _vocab_to_categories(HOUSEHOLD_SIZE, open_tail_code="10+", open_tail_lower=10)
    hh_type_cats = _vocab_to_categories(HOUSEHOLD_TYPE)
    degurba_cats = (
        CategoryDefinition(code="dense_urban", label_en="Dense urban", label_tr="Yoğun kent", kind="known"),
        CategoryDefinition(code="intermediate_urban", label_en="Intermediate urban", label_tr="Orta yoğun kent", kind="known"),
        CategoryDefinition(code="rural", label_en="Rural", label_tr="Kır", kind="known"),
    )

    entries: list[EvidenceDatasetEntry] = [
        # 1. Ankara 2025 Age × Sex (Primary Root from TÜİK Package T16)
        EvidenceDatasetEntry(
            dataset_id="ankara_age_sex_2025",
            title="Ankara Population by 5-Year Age Group and Sex (2025, TÜİK ADNKS T16)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS DF_ADNKS_T16",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=tuple(range(2016, 2026)),
            dimensions=("province_code", "age_group", "sex"),
            scope="person",
            unit="person",
            status="observed",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="Address Based Population Registration System (ADNKS) Results, 2025",
                table_id="population_age_sex",
                sdmx_dataflow="DF_ADNKS_T16",
                publication_year=2026,
                publication_date="2026-02-06",
                url="https://veriportali.tuik.gov.tr/tr/data-table/6791?pressId=57877",
                parent_registry_source_id="population_age_sex",
                manifest_dataset_id="tuik_pkg:population_by_age_sex",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="population_by_age_sex.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_provincial",
                filter_province_code="06",
                filter_year=2025,
                indicator_pattern=r"^pop_age_(?P<age_group>\d+_\d+|90_plus)_(?P<sex>male|female)$",
                total_patterns=(
                    r"^pop_age_total_(?P<sex>male|female)$",
                    r"^pop_age_(?P<age_group>\d+_\d+|90_plus)_total$",
                    r"^pop_age_total_total$",
                ),
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_residents_all",
                unit="person",
                min_age=0,
                max_age=None,
                expected_total=5910320,
                expected_by_sex={"male": 2911853, "female": 2998467},
                reconciles_to_root_population=True,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=0,
            ),
            category_definitions={"age_group": age_cats, "sex": sex_cats},
            sha256="387c75d6fc8a5d38bf0ae7a24a61b8ec65fdd7f265aee2329a76cdf613554a0c",
            caveats=(
                "Root denominator (5,910,320) includes both private-household residents (~5,690,627) and "
                "institutional/collective residents (~219,693 in dormitories, barracks, prisons, hospitals).",
                "5-year age brackets only; single-year age within brackets is not observed in this table.",
                "90+ is an open-ended top age bracket (15,923 persons in Ankara 2025: 4,728 male, 11,195 female).",
            ),
            data_quality_flags=(ANKARA_HOUSEHOLD_DISCREPANCY_FLAG,),
            dependency_registry_attributes=("province_code", "age_group", "sex"),
        ),
        # 2. Legacy Ankara Age × Gender Extract (2025, Corroborating Source)
        EvidenceDatasetEntry(
            dataset_id="legacy_ankara_age_sex_2025",
            title="Legacy Processed Ankara Age × Sex Distribution (2025, TÜİK T16 Extract)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS T16 (Legacy Processed Extract)",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=(2025,),
            dimensions=("province_code", "age_group", "sex"),
            scope="person",
            unit="person",
            status="observed",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="ADNKS 2025 Table T16 (Processed in experiments/matraix_simulation)",
                table_id="population_age_sex",
                sdmx_dataflow="DF_ADNKS_T16",
                publication_year=2026,
                publication_date="2026-02-06",
                parent_registry_source_id="population_age_sex",
                manifest_dataset_id="legacy:tuik_t16_age_sex",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="experiments/matraix_simulation/processed/ankara_age_gender.csv",
                storage_root="repo_root",
                file_format="csv",
                encoding="utf-8",
                layout="legacy_age_gender_csv",
                filter_province_code="06",
                filter_year=2025,
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_residents_all",
                unit="person",
                min_age=0,
                expected_total=5910320,
                expected_by_sex={"male": 2911853, "female": 2998467},
                reconciles_to_root_population=True,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=0,
            ),
            category_definitions={"age_group": age_cats, "sex": sex_cats},
            sha256="c06d8834761be1ebba037f108113a332a2ab9a0bf16e87022e994d4434ad993b",
            caveats=(
                "Uses column name 'gender' in CSV for administrative sex; all 38 cells match ankara_age_sex_2025 with 0 discrepancy.",
            ),
            data_quality_flags=(),
            dependency_registry_attributes=("province_code", "age_group", "sex"),
        ),
        # 3. Ankara 2025 Marital Status × Sex (15+, TÜİK Package T10)
        EvidenceDatasetEntry(
            dataset_id="ankara_marital_sex_2025",
            title="Ankara Population Aged 15+ by Marital Status and Sex (2025, TÜİK ADNKS T10)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS DF_ADNKS_T10",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=tuple(range(2008, 2026)),
            dimensions=("province_code", "sex", "marital_status"),
            scope="person",
            unit="person",
            status="observed_with_caveats",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="ADNKS Population Aged 15+ by Marital Status and Sex, 2025",
                table_id="marital_status_sex",
                sdmx_dataflow="DF_ADNKS_T10",
                publication_year=2026,
                publication_date="2026-02-06",
                url="https://veriportali.tuik.gov.tr/tr/data-table/6785?pressId=57877",
                parent_registry_source_id="marital_status_sex",
                manifest_dataset_id="tuik_pkg:marital_status_by_sex",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="marital_status_by_sex.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_provincial",
                filter_province_code="06",
                filter_year=2025,
                indicator_pattern=r"^pop_15plus_marital_(?P<category>never_married|married|divorced|widowed)_(?P<sex>male|female)$",
                total_patterns=(
                    r"^pop_15plus_marital_total_(?P<sex>male|female)$",
                    r"^pop_15plus_marital_(?P<category>never_married|married|divorced|widowed)_total$",
                    r"^pop_15plus_marital_total_total$",
                ),
                residual_pattern=r"^pop_15plus_marital_unknown_(?P<sex>male|female)$",
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_residents_15plus",
                unit="person",
                min_age=15,
                expected_total=4856106,
                expected_by_sex={"male": 2371482, "female": 2484624},
                reconciles_to_root_population=True,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=0,
            ),
            category_definitions={"sex": sex_cats, "marital_status": marital_cats},
            sha256="3321e5c3bc8ceb859d65c6dd74be132aa680aef76cb1f82cec7398c7f0e02547",
            caveats=(
                "Marginal sex × marital_status only (universe age >= 15); joint distribution with age_group is NOT observed at province level.",
                "In 2021–2025, the 4,856,106 denominator matches Ankara ADNKS 15+ population exactly (0 gap), whereas in 2016–2020 it had a coverage gap matching the NESD education universe.",
            ),
            data_quality_flags=(MARITAL_HISTORICAL_GAP_FLAG,),
            dependency_registry_attributes=("marital_status",),
        ),
        # 4. Legacy Ankara Marital × Gender Extract (2025)
        EvidenceDatasetEntry(
            dataset_id="legacy_ankara_marital_sex_2025",
            title="Legacy Processed Ankara Marital Status × Sex (2025, TÜİK T10 Extract)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS T10 (Legacy Processed Extract)",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=(2025,),
            dimensions=("province_code", "sex", "marital_status"),
            scope="person",
            unit="person",
            status="observed",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="ADNKS 2025 Table T10 (Processed in experiments/matraix_simulation)",
                table_id="marital_status_sex",
                sdmx_dataflow="DF_ADNKS_T10",
                publication_year=2026,
                publication_date="2026-02-06",
                parent_registry_source_id="marital_status_sex",
                manifest_dataset_id="legacy:tuik_t10_marital_sex",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="experiments/matraix_simulation/processed/ankara_marital_gender.csv",
                storage_root="repo_root",
                file_format="csv",
                encoding="utf-8",
                layout="legacy_marital_gender_csv",
                filter_province_code="06",
                filter_year=2025,
                category_label_map={
                    "Hiç evlenmedi": "never_married",
                    "Evli": "married",
                    "Boşandı": "divorced",
                    "Eşi öldü": "widowed",
                },
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_residents_15plus",
                unit="person",
                min_age=15,
                expected_total=4856106,
                expected_by_sex={"male": 2371482, "female": 2484624},
                reconciles_to_root_population=True,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=0,
            ),
            category_definitions={"sex": sex_cats, "marital_status": marital_cats},
            sha256="be38d80854eac22a30c1f4bb77bf9b178857eeb8c73e048cbf1010f432958239",
            caveats=(
                "Uses Turkish marital status labels and column 'gender'; all 8 cells match ankara_marital_sex_2025 exactly.",
            ),
            data_quality_flags=(),
            dependency_registry_attributes=("marital_status",),
        ),
        # 5. Ankara 2025 Education Attainment × Sex (15+, NESD)
        EvidenceDatasetEntry(
            dataset_id="ankara_education_sex_2025",
            title="Ankara Population Aged 15+ by Attained Education Level and Sex (2025, TÜİK NESD)",
            source="Turkish Statistical Institute (TÜİK) — National Education Statistics Database (NESD)",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=tuple(range(2008, 2026)),
            dimensions=("province_code", "sex", "education_level"),
            scope="person",
            unit="person",
            status="observed_with_caveats",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="National Education Statistics Database (NESD), 2025",
                table_id="education_sex",
                sdmx_dataflow="DF_ULUSAL_EGITIM_ISTATISTIK_BED_NUFUS",
                publication_year=2026,
                publication_date="2026-05-14",
                url="https://veriportali.tuik.gov.tr/tr/data-table/6737?pressId=58104",
                parent_registry_source_id="education_sex",
                manifest_dataset_id="tuik_pkg:education_attainment_by_sex",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="education_attainment_by_sex.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_provincial",
                filter_province_code="06",
                filter_year=2025,
                indicator_pattern=(
                    r"^edu_15plus_(?P<category>illiterate|literate_no_diploma|primary_school|"
                    r"primary_education|lower_secondary_school|upper_secondary_high_school|"
                    r"higher_education_bachelor_associate|masters_degree|doctorate|unknown)_(?P<sex>male|female)$"
                ),
                total_patterns=(
                    r"^edu_15plus_total_(?P<sex>male|female)$",
                    r"^edu_15plus_(?P<category>illiterate|literate_no_diploma|primary_school|primary_education|lower_secondary_school|upper_secondary_high_school|higher_education_bachelor_associate|masters_degree|doctorate|unknown)_total$",
                    r"^edu_15plus_total_total$",
                ),
                category_label_map={
                    "primary_school": "primary",
                    "primary_education": "basic_8yr",
                    "lower_secondary_school": "lower_secondary",
                    "upper_secondary_high_school": "upper_secondary",
                    "higher_education_bachelor_associate": "higher_education",
                    "masters_degree": "masters",
                },
            ),
            denominator=DenominatorSpec(
                universe="NESD_15plus_domestic_education_register",
                unit="person",
                min_age=15,
                expected_total=4751123,
                expected_by_sex={"male": 2322692, "female": 2428431},
                reconciles_to_root_population=False,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=104983,
                inconsistency_reason=(
                    "NESD 15+ total (4,751,123) is 104,983 smaller than Ankara ADNKS 15+ population (4,856,106: "
                    "male gap 48,790, female gap 56,193). Correlates r=0.9998 across provinces with foreign resident "
                    "population (128,633 in Ankara 2025)."
                ),
            ),
            category_definitions={"sex": sex_cats, "education_level": edu_cats},
            sha256="0fab6c0180fdb0270ab3b7ae2f51616011d7390e2cd3c66c60fe749c335dec6c",
            caveats=(
                "NESD 15+ denominator (4,751,123) does not equal ADNKS 15+ denominator (4,856,106); gap = 104,983.",
                "Published 'unknown' category (17,626 persons: 7,474 male, 10,152 female) is preserved as 'unknown'.",
                "Marginal sex × education_level only; joint age_group × education_level is inferred via IPF with minimum-completion-age structural zeros.",
            ),
            data_quality_flags=(EDUCATION_UNIVERSE_GAP_FLAG,),
            dependency_registry_attributes=("education_level",),
        ),
        # 6. Ankara 2025 Administrative Urbanicity × Sex (T14)
        EvidenceDatasetEntry(
            dataset_id="ankara_urbanicity_sex_2025",
            title="Ankara Population by Administrative Urban/Rural Settlement Type and Sex (2025, TÜİK T14)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS DF_ADNKS_T14",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=tuple(range(2007, 2026)),
            dimensions=("province_code", "sex", "urbanicity"),
            scope="person",
            unit="person",
            status="observed_with_caveats",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="ADNKS Population by Province/District Centers and Towns/Villages, 2025",
                table_id="urbanicity_sex",
                sdmx_dataflow="DF_ADNKS_T14",
                publication_year=2026,
                publication_date="2026-02-06",
                url="https://veriportali.tuik.gov.tr/tr/data-table/6789?pressId=57877",
                parent_registry_source_id="urbanicity_sex",
                manifest_dataset_id="tuik_pkg:population_urban_rural",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="population_urban_rural.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_provincial",
                filter_province_code="06",
                filter_year=2025,
                indicator_pattern=r"^pop_(?P<category>province_district_centers|towns_and_villages)_(?P<sex>male|female)$",
                total_patterns=(
                    r"^pop_(?P<category>province_district_centers|towns_and_villages)_total$",
                ),
                category_label_map={
                    "province_district_centers": "province_district_centre",
                    "towns_and_villages": "town_village",
                },
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_residents_all",
                unit="person",
                min_age=0,
                expected_total=5910320,
                expected_by_sex={"male": 2911853, "female": 2998467},
                reconciles_to_root_population=True,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=0,
            ),
            category_definitions={"sex": sex_cats, "urbanicity": urban_cats},
            sha256="720324fb99816ea96db25c791aa4e9a71cff13cbcd3dae3b0685b4f547697d5a",
            caveats=(
                "Under Law No. 6360 (effective 2013), all villages in Ankara were reclassified as urban neighbourhoods; "
                "town_village rows are absent (not 0), and province_district_centre equals 100% of Ankara's population.",
            ),
            data_quality_flags=(METROPOLITAN_URBANICITY_LAW6360_FLAG,),
            dependency_registry_attributes=("urbanicity",),
        ),
        # 7. Ankara 2025 DEGURBA Spatial Urbanisation × Sex (T37)
        EvidenceDatasetEntry(
            dataset_id="ankara_degurba_sex_2025",
            title="Ankara Population by Degree of Urbanisation (DEGURBA) and Sex (2025, TÜİK T37)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS DF_ADNKS_T37",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=(2022, 2023, 2024, 2025),
            dimensions=("province_code", "sex", "degurba_class"),
            scope="person",
            unit="person",
            status="observed",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="Urban-Rural Population Statistics (DEGURBA), 2025",
                table_id="degurba_sex",
                sdmx_dataflow="DF_ADNKS_T37",
                publication_year=2026,
                publication_date="2026-02-06",
                url="https://veriportali.tuik.gov.tr/tr/data-table/6789?pressId=57877",
                parent_registry_source_id="degurba_class",
                manifest_dataset_id="tuik_pkg:population_urban_rural",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="population_urban_rural.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_provincial",
                filter_province_code="06",
                filter_year=2025,
                indicator_pattern=r"^pop_degurba_(?P<category>dense_urban|intermediate_urban|rural)_(?P<sex>male|female)$",
                total_patterns=(
                    r"^pop_degurba_(?P<category>dense_urban|intermediate_urban|rural)_total$",
                ),
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_residents_all",
                unit="person",
                min_age=0,
                expected_total=5910320,
                expected_by_sex={"male": 2911853, "female": 2998467},
                reconciles_to_root_population=True,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=0,
            ),
            category_definitions={"sex": sex_cats, "degurba_class": degurba_cats},
            sha256="720324fb99816ea96db25c791aa4e9a71cff13cbcd3dae3b0685b4f547697d5a",
            caveats=(
                "Spatial grid classification (dense_urban=5,182,618; intermediate_urban=477,753; rural=249,949); "
                "joint distribution with age_group or education_level is not observed.",
            ),
            data_quality_flags=(METROPOLITAN_URBANICITY_LAW6360_FLAG,),
            dependency_registry_attributes=(),
        ),
        # 8. Ankara 2025 Household Types & Average Size (T06 / T08 / T25)
        EvidenceDatasetEntry(
            dataset_id="ankara_household_types_2025",
            title="Ankara Private Households by Family Composition Type and Average Household Size (2025, TÜİK T06/T08/T25)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS DF_ADNKS_T06, DF_ADNKS_T08 & DF_ADNKS_T25",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=tuple(range(2014, 2026)),
            dimensions=("province_code", "household_type"),
            scope="household",
            unit="household",
            status="observed_with_caveats",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="Statistics on Family, 2025 — Households by Type and Average Size",
                table_id="household_type",
                sdmx_dataflow="DF_ADNKS_T06 / DF_ADNKS_T08 / DF_ADNKS_T25",
                publication_year=2026,
                publication_date="2026-05-08",
                url="https://veriportali.tuik.gov.tr/tr/data-table/6781?pressId=58074",
                parent_registry_source_id="household_type_persons",
                manifest_dataset_id="tuik_pkg:households_size_and_types",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="households_size_and_types.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_provincial",
                filter_province_code="06",
                filter_year=2025,
                indicator_pattern=r"^households_(?P<category>one_person|one_family|extended_family|multi_person_no_family)$",
                total_patterns=(r"^households_total$",),
                category_label_map={
                    "one_family": "nuclear_family",
                    "multi_person_no_family": "non_family_multi_person",
                },
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_private_households",
                unit="household",
                min_age=None,
                expected_total=1987216,
                reconciles_to_root_population=False,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=219693,
                inconsistency_reason=(
                    "Unit is private household (1,987,216 households in Ankara 2025; average_household_size = "
                    "2.86361774462363 -> 5,690,627 private-household residents), which excludes 219,693 institutional/"
                    "collective residents included in the 5,910,320 ADNKS resident population."
                ),
            ),
            category_definitions={"household_type": hh_type_cats},
            sha256="9748c1e993b7768976c33865e907b96bef162a6d31c2b6bacb333ad786db915f",
            caveats=(
                "Denominator is 1,987,216 private households (unit=household), NOT 5,910,320 persons.",
                "Implied private-household population (1,987,216 × 2.86361774462363 = 5,690,627) leaves an exact "
                "219,693-person gap vs total resident population (5,910,320) due to institutional/collective accommodation.",
                "Nuclear family subtypes (couple_only=292,350; couple_with_children=785,228; lone_parent=234,842 "
                "[father=50,178, mother=184,664]) partition one_family (1,312,420) and must not be double-counted.",
            ),
            data_quality_flags=(ANKARA_HOUSEHOLD_DISCREPANCY_FLAG,),
            dependency_registry_attributes=("household_type",),
        ),
        # 9. Ankara 2025 Foreign Resident Population × Sex (T12)
        EvidenceDatasetEntry(
            dataset_id="ankara_foreign_population_sex_2025",
            title="Ankara Foreign National Resident Population by Sex (2025, TÜİK ADNKS T12)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS DF_ADNKS_T12",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=tuple(range(2008, 2026)),
            dimensions=("province_code", "sex"),
            scope="person",
            unit="person",
            status="context_only",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="International Migration Statistics & ADNKS Foreign Population, 2025",
                table_id="foreign_resident_population",
                sdmx_dataflow="DF_ADNKS_T12",
                publication_year=2026,
                publication_date="2026-07-23",
                url="https://veriportali.tuik.gov.tr/tr/press-release/58086",
                manifest_dataset_id="tuik_pkg:international_migration_and_foreign_population",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="international_migration_and_foreign_population.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_provincial",
                filter_province_code="06",
                filter_year=2025,
                indicator_pattern=r"^foreign_resident_population_(?P<sex>male|female)$",
                total_patterns=(r"^foreign_resident_population_total$",),
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_foreign_national_residents",
                unit="person",
                min_age=0,
                expected_total=128633,
                expected_by_sex={"male": 60855, "female": 67778},
                reconciles_to_root_population=False,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=5781687,
                inconsistency_reason=(
                    "Subset of ADNKS total resident population (128,633 foreign nationals with valid residence "
                    "permits/international protection in Ankara 2025; excludes Syrians under Temporary Protection). "
                    "Explains the 104,983 adult (15+) gap between ADNKS 15+ and NESD Education 15+."
                ),
            ),
            category_definitions={"sex": sex_cats},
            sha256="a51c35acf602a95013425acef2fab23a1bf4211bd5c583f00ab820f58e03757a",
            caveats=(
                "Includes foreign nationals in ADNKS (residence permits / international protection); excludes Temporary Protection (Geçici Koruma).",
                "Published by sex only (no age breakdown at province level).",
            ),
            data_quality_flags=(EDUCATION_UNIVERSE_GAP_FLAG,),
            dependency_registry_attributes=(),
        ),
        # 10. Ankara 2025 Headline Labour Force Indicators (HLFS Model Rates)
        EvidenceDatasetEntry(
            dataset_id="ankara_labour_force_rates_2025",
            title="Ankara Provincial Headline Labour Force Rates & 95% CIs (2025, TÜİK HLFS)",
            source="Turkish Statistical Institute (TÜİK) — Household Labour Force Survey Provincial Model Estimates",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=(2022, 2023, 2024, 2025),
            dimensions=("province_code", "indicator"),
            scope="geography",
            unit="percent",
            status="context_only",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="Provincial Headline Labour Force Indicators, 2025",
                table_id="labor_force_indicators",
                publication_year=2026,
                publication_date="2026-03-30",
                url="https://veriportali.tuik.gov.tr/tr/press-release/58059",
                parent_registry_source_id="labour_status_sex",
                manifest_dataset_id="tuik_pkg:labor_force_indicators",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="labor_force_indicators.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_provincial",
                filter_province_code="06",
                filter_year=2025,
                indicator_pattern=r"^(?P<category>labor_force_participation_rate|employment_rate|unemployment_rate)$",
            ),
            denominator=DenominatorSpec(
                universe="HLFS_non_institutional_working_age_15plus",
                unit="percent",
                min_age=15,
                expected_total=None,
                reconciles_to_root_population=False,
                root_dataset_id="ankara_age_sex_2025",
                inconsistency_reason=(
                    "Publishes only survey-modelled percentages (LFPR=53.91%, employment=49.34%, unemployment=8.48%) "
                    "with 95% confidence intervals for the non-institutional 15+ population; person counts and "
                    "sex/age disaggregations are not published at province level."
                ),
            ),
            category_definitions={
                "indicator": (
                    CategoryDefinition(code="labor_force_participation_rate", label_en="Labour force participation rate (%)", label_tr="İşgücüne katılma oranı (%)"),
                    CategoryDefinition(code="employment_rate", label_en="Employment rate (%)", label_tr="İstihdam oranı (%)"),
                    CategoryDefinition(code="unemployment_rate", label_en="Unemployment rate (%)", label_tr="İşsizlik oranı (%)"),
                )
            },
            sha256="68e67007a3cadc7e6f34b7df8fa595bf64ae4e2277b4195527f01a19c7401da7",
            caveats=(
                "Headline rates (%) with 95% CIs only; cannot be converted to exact person counts without fabricating precision.",
                "Person-level labour_status remains UNAVAILABLE in national-v1.",
            ),
            data_quality_flags=(LABOUR_RATE_ONLY_FLAG,),
            dependency_registry_attributes=("labour_status",),
        ),
        # 11. Ankara 25 Districts Population (2025, T22)
        EvidenceDatasetEntry(
            dataset_id="ankara_district_population_2025",
            title="Ankara 25 Districts Total Population and Annual Growth Rate (2025, TÜİK ADNKS T22)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS DF_ADNKS_T22 & DF_ADNKS_T38",
            geography=GeographyScope(
                code="06_districts",
                level="district",
                name="Ankara (25 Districts / İlçe)",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_DISTRICT_OBSERVED",
            ),
            year=2025,
            available_years=(2024, 2025),
            dimensions=("province_code", "district_name"),
            scope="geography",
            unit="person",
            status="observed",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="ADNKS District Population Results, 2025",
                table_id="ankara_district_population",
                sdmx_dataflow="DF_ADNKS_T22",
                publication_year=2026,
                publication_date="2026-02-06",
                url="https://veriportali.tuik.gov.tr/tr/press-release/53899",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="ankara_district_population_and_growth.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_district",
                filter_province_code="06",
                filter_year=2025,
                indicator_pattern=r"^(?P<category>total_population)$",
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_residents_all",
                unit="person",
                min_age=0,
                expected_total=5910320,
                reconciles_to_root_population=True,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=0,
            ),
            category_definitions={},
            sha256="dce0c50e1397c173f95cfd90d84ebe58ebbda10e82111b76ec2fd069ba092319",
            caveats=(
                "Sum across all 25 Ankara districts equals 5,910,320 in 2025 (and 5,864,049 in 2024) with 0 discrepancy.",
                "District-level age × sex breakdown is not included in this file.",
            ),
            data_quality_flags=(),
            dependency_registry_attributes=(),
        ),
        # 12. National (TR) Broad-Age × Sex × Marital Status Seed (2025, NATIONAL ONLY)
        EvidenceDatasetEntry(
            dataset_id="national_age_sex_marital_2025",
            title="National (TR) Marital Status Percentages by Sex and Broad Age Band (15-24, 25+) (2025, Table 1.9)",
            source="Turkish Statistical Institute (TÜİK) — Women in Statistics 2025 (Pub No. 5466, Table 1.9)",
            geography=GeographyScope(
                code="TR",
                level="national",
                name="Türkiye (National Total — NOT Ankara-Specific)",
                province_code=None,
                is_national=True,
                is_ankara_specific=False,
                scope_marker="NATIONAL_ONLY_NOT_ANKARA_SPECIFIC",
            ),
            year=2025,
            available_years=(2025,),
            dimensions=("sex", "broad_age_band", "marital_status"),
            scope="person",
            unit="percent",
            status="national_transfer_seed",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="İstatistiklerle Kadın (Women in Statistics) 2025, Table 1.9, p. 14",
                table_id="marital_status_age_sex_national_seed",
                publication_year=2026,
                publication_date="2026-03-05",
                url="https://veriportali.tuik.gov.tr/tr/press-release/5466",
                parent_registry_source_id="marital_status_age_sex",
            ),
            retrieval_info=RetrievalInfo(
                relative_path=dep_reg.marital_strategy.source_file if dep_reg.marital_strategy else "data/raw/national_marital_seed_2025.yaml",
                storage_root="repo_root",
                file_format="yaml",
                encoding="utf-8",
                layout="national_marital_seed_yaml",
                filter_year=2025,
                optional_local_file=True,
            ),
            denominator=DenominatorSpec(
                universe="National_TR_ADNKS_residents_15plus_within_sex_broad_age",
                unit="percent",
                min_age=15,
                expected_total=100.0,
                reconciles_to_root_population=False,
                root_dataset_id="ankara_age_sex_2025",
                inconsistency_reason=(
                    "National (TR) conditional percentages within (sex, broad_age_band in {15-24, 25+}), NOT Ankara counts."
                ),
            ),
            category_definitions={
                "sex": sex_cats,
                "broad_age_band": (
                    CategoryDefinition(code="15-24", label_en="15 to 24 years", label_tr="15-24 yaş", lower_bound=15, upper_bound=24),
                    CategoryDefinition(code="25+", label_en="25 years and over", label_tr="25+ yaş", lower_bound=25, upper_bound=None, is_open_ended=True),
                ),
                "marital_status": marital_cats,
            },
            sha256=(
                dep_reg.marital_strategy.source_sha256
                if dep_reg.marital_strategy
                else "55dbc9752f4e19617cd9803dced10811a1efdb7e0cdcc906adac878141fb796d"
            ),
            caveats=(
                "NATIONAL (TR) DATA ONLY: Must never be presented as observed Ankara age × marital counts.",
                "Published at 0.1 percentage-point precision for 2 broad age bands (15-24, 25+); widowed in 15-24 is printed as 0.0%.",
                "Local opt-in raw file (data/raw/national_marital_seed_2025.yaml) is git-ignored in clean checkouts.",
            ),
            data_quality_flags=(NATIONAL_MARITAL_ROUNDING_FLAG,),
            dependency_registry_attributes=("marital_status",),
        ),
        # 13. Ankara 2025 Private Households by Size Class (1..9, 10+, NIP Local Raw)
        EvidenceDatasetEntry(
            dataset_id="ankara_household_size_2025",
            title="Ankara Private Households by Household Size Class (1..9, 10+) (2025, TÜİK NIP)",
            source="Turkish Statistical Institute (TÜİK) — Nüfus İstatistikleri Portalı (NIP)",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=(2025,),
            dimensions=("province_code", "household_size_class"),
            scope="household",
            unit="household",
            status="local_raw_optional",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="İllere ve Hanehalkı Büyüklüğüne Göre Hanehalkı Sayısı, 2025",
                table_id="household_size",
                publication_year=2026,
                url=hh_reg.source.url,
                parent_registry_source_id="household_size_persons",
            ),
            retrieval_info=RetrievalInfo(
                relative_path=hh_reg.source.source_file,
                storage_root="repo_root",
                file_format="csv",
                layout="nip_household_size_csv",
                filter_province_code="06",
                filter_year=2025,
                optional_local_file=True,
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_private_households",
                unit="household",
                expected_total=hh_reg.source.expected_total,
                reconciles_to_root_population=False,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=219693,
                inconsistency_reason=(
                    "Unit is household (1,987,216 private households), excluding 219,693 institutional residents "
                    "and right-censoring the 10+ household size tail."
                ),
            ),
            category_definitions={"household_size_class": hh_size_cats},
            sha256=hh_reg.source.sha256,
            caveats=(
                "10+ size class is open-ended (lower bound 10, exact mean and upper bound unpublished).",
                "Excludes institutional/collective populations (219,693 gap vs 5,910,320 total residents).",
                "Git-ignored local raw file in data/raw/ankara_household_size_2025.csv.",
            ),
            data_quality_flags=(ANKARA_HOUSEHOLD_DISCREPANCY_FLAG,),
            dependency_registry_attributes=("household_size_class",),
        ),
        # 14. National (TR) Household Type × Size Class (1..6, 7+) Seed (2025, NATIONAL ONLY)
        EvidenceDatasetEntry(
            dataset_id="national_household_type_size_2025",
            title="National (TR) Private Households by Type and Size Band (1..6, 7+) (2025, Table 1.4)",
            source="Turkish Statistical Institute (TÜİK) — Women in Statistics 2025, Table 1.4",
            geography=GeographyScope(
                code="TR",
                level="national",
                name="Türkiye (National Total — NOT Ankara-Specific)",
                province_code=None,
                is_national=True,
                is_ankara_specific=False,
                scope_marker="NATIONAL_ONLY_NOT_ANKARA_SPECIFIC",
            ),
            year=2025,
            available_years=(2025,),
            dimensions=("household_type", "household_type_size_band"),
            scope="household",
            unit="household",
            status="national_transfer_seed",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title=ts_reg.national.title,
                table_id="national_household_type_size",
                publication_year=2026,
                url=ts_reg.national.url,
                parent_registry_source_id="household_type_persons",
            ),
            retrieval_info=RetrievalInfo(
                relative_path=ts_reg.national.path,
                storage_root="repo_root",
                file_format="csv",
                layout="national_type_size_csv",
                filter_year=2025,
                optional_local_file=True,
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_private_households",
                unit="household",
                expected_total=None,
                reconciles_to_root_population=False,
                root_dataset_id="ankara_age_sex_2025",
                inconsistency_reason="National (TR) private households joint table (top-coded at 7+), NOT Ankara.",
            ),
            category_definitions={"household_type": hh_type_cats},
            sha256=ts_reg.national.sha256,
            caveats=(
                "NATIONAL (TR) DATA ONLY: Must never be presented as observed Ankara type × size counts.",
                "Top-coded at 7+ (collapsing 7, 8, 9, 10+).",
                "Git-ignored local raw file in data/raw/national_household_type_size_2025.csv.",
            ),
            data_quality_flags=(ANKARA_HOUSEHOLD_DISCREPANCY_FLAG,),
            dependency_registry_attributes=("household_type", "household_size_class"),
        ),
        # 15. National 81-Province Age × Sex (2025, Multi-Province / National Sum)
        EvidenceDatasetEntry(
            dataset_id="national_81provinces_age_sex_2025",
            title="Türkiye 81 Provinces Population by 5-Year Age Group and Sex (2025, TÜİK ADNKS T16)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS DF_ADNKS_T16",
            geography=GeographyScope(
                code="TR",
                level="national",
                name="Türkiye (All 81 Provinces Aggregate — NOT Ankara-Specific)",
                province_code=None,
                is_national=True,
                is_ankara_specific=False,
                scope_marker="NATIONAL_ONLY_NOT_ANKARA_SPECIFIC",
            ),
            year=2025,
            available_years=tuple(range(2016, 2026)),
            dimensions=("age_group", "sex"),
            scope="person",
            unit="person",
            status="context_only",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="Address Based Population Registration System (ADNKS) Results, 2025",
                table_id="population_age_sex",
                sdmx_dataflow="DF_ADNKS_T16",
                publication_year=2026,
                publication_date="2026-02-06",
                url="https://veriportali.tuik.gov.tr/tr/data-table/6791?pressId=57877",
                parent_registry_source_id="population_age_sex",
                manifest_dataset_id="tuik_pkg:population_by_age_sex",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="population_by_age_sex.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_provincial",
                filter_province_code=None,
                filter_year=2025,
                indicator_pattern=r"^pop_age_(?P<age_group>\d+_\d+|90_plus)_(?P<sex>male|female)$",
                total_patterns=(
                    r"^pop_age_total_(?P<sex>male|female)$",
                    r"^pop_age_(?P<age_group>\d+_\d+|90_plus)_total$",
                    r"^pop_age_total_total$",
                ),
            ),
            denominator=DenominatorSpec(
                universe="National_TR_ADNKS_residents_all",
                unit="person",
                min_age=0,
                expected_total=86092168,
                reconciles_to_root_population=False,
                root_dataset_id="ankara_age_sex_2025",
                inconsistency_reason="National (TR) 81-province sum (86,092,168), not Ankara (5,910,320).",
            ),
            category_definitions={"age_group": age_cats, "sex": sex_cats},
            sha256="387c75d6fc8a5d38bf0ae7a24a61b8ec65fdd7f265aee2329a76cdf613554a0c",
            caveats=(
                "NATIONAL (TR) 81-province aggregate (86,092,168 persons); must never be loaded as Ankara-specific without explicit scope override.",
            ),
            data_quality_flags=(),
            dependency_registry_attributes=(),
        ),
        # 16. Ankara Population Projections 2024–2030 (Quarantined Projection Series)
        EvidenceDatasetEntry(
            dataset_id="ankara_projections_2024_2030",
            title="Ankara Provincial Population Projections (2023 Baseline, 2024–2030 Projected, TÜİK)",
            source="Turkish Statistical Institute (TÜİK) — Population Projections (Press Release 53685)",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=(2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030),
            dimensions=("province_code", "indicator"),
            scope="geography",
            unit="person",
            status="projection_quarantined",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="Population Projections, 2023–2030",
                table_id="population_projections",
                publication_year=2024,
                publication_date="2024-07-31",
                url="https://veriportali.tuik.gov.tr/tr/press-release/53685",
                manifest_dataset_id="tuik_pkg:population_projections_2024_2030",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="population_projections_2024_2030.csv",
                storage_root="tuik_package_dir",
                file_format="csv",
                layout="tuik_long_provincial",
                filter_province_code="06",
                filter_year=2025,
                indicator_pattern=r"^(?P<category>projected_population)$",
            ),
            denominator=DenominatorSpec(
                universe="Projected_ADNKS_residents_2023_base",
                unit="person",
                min_age=0,
                expected_total=5886877,
                reconciles_to_root_population=False,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=23443,
                inconsistency_reason=(
                    "2025 value (5,886,877) is a demographic projection from the 2023 baseline, differing from "
                    "realized 2025 ADNKS population (5,910,320) by 23,443 persons."
                ),
            ),
            category_definitions={
                "indicator": (
                    CategoryDefinition(code="projected_population", label_en="Projected population", label_tr="Projeksiyon nüfusu"),
                )
            },
            sha256="b65670c72bd0519697d2c88f2ddfbc7f6c55ebcf3957891496d2f893dbe0b742",
            caveats=(
                "PROJECTION ONLY: Must never be used as observed 2024 or 2025 ground truth.",
            ),
            data_quality_flags=(PROJECTION_VS_REALIZED_FLAG,),
            dependency_registry_attributes=(),
        ),
        # 17. Legacy Ankara Demographic Controls (2023–2025)
        EvidenceDatasetEntry(
            dataset_id="legacy_ankara_demographic_controls_2025",
            title="Legacy Ankara Demographic Controls (Population, Median Age, Density, 2023–2025)",
            source="Turkish Statistical Institute (TÜİK) — ADNKS Tables t3 & t7 (Legacy Extract)",
            geography=GeographyScope(
                code="06",
                level="province",
                name="Ankara",
                province_code="06",
                nuts2_code="TR51",
                nuts3_code="TR510",
                is_national=False,
                is_ankara_specific=True,
                scope_marker="ANKARA_OBSERVED",
            ),
            year=2025,
            available_years=(2023, 2024, 2025),
            dimensions=("province_code", "statistic"),
            scope="geography",
            unit="mixed",
            status="context_only",
            source_reference=SourceReference(
                agency="Turkish Statistical Institute (TÜİK)",
                publication_title="ADNKS Tables t3 & t7 (Processed in experiments/matraix_simulation)",
                table_id="ankara_demographic_controls",
                publication_year=2026,
                manifest_dataset_id="legacy:tuik_ankara_controls",
            ),
            retrieval_info=RetrievalInfo(
                relative_path="experiments/matraix_simulation/processed/ankara_demographic_controls.csv",
                storage_root="repo_root",
                file_format="csv",
                encoding="utf-8",
                layout="legacy_controls_csv",
                filter_province_code="06",
                filter_year=2025,
            ),
            denominator=DenominatorSpec(
                universe="ADNKS_residents_all",
                unit="mixed",
                min_age=0,
                expected_total=5910320,
                reconciles_to_root_population=True,
                root_dataset_id="ankara_age_sex_2025",
                expected_gap_vs_root=0,
            ),
            category_definitions={},
            sha256="d6248b60a456c1decbf76418a6844f96437ea3f2d9ff6551691e0cf63532450d",
            caveats=(
                "Contains 3 duplicate rows in 2024 (female, male, and total median age repeated with identical values).",
            ),
            data_quality_flags=(LEGACY_CONTROLS_DUPLICATE_FLAG,),
            dependency_registry_attributes=(),
        ),
    ]
    return {e.dataset_id: e for e in entries}


def load_evidence_registry(
    dependency_registry_path: Path = DEFAULT_REGISTRY_PATH,
    *,
    household_registry_path: Path | None = None,
    type_size_registry_path: Path | None = None,
    extension_registry_path: Path | None = None,
) -> EvidenceRegistry:
    """Load the K1 EvidenceRegistry by composing the existing DependencyRegistry and sidecars.

    Verifies ``compile_compatibility(dep_reg)`` so the Population Engine contract is
    guaranteed intact.
    """
    dep_reg = load_dependency_registry(dependency_registry_path)
    compile_compatibility(dep_reg)
    hh_reg = load_household_registry(household_registry_path)
    ts_reg = load_type_size_registry(type_size_registry_path)
    ext_reg = load_extension_registry(extension_registry_path)

    if hh_reg.parent_registry_version != dep_reg.registry_version:
        raise RegistryError(
            f"HouseholdRegistry parent_registry_version {hh_reg.parent_registry_version!r} "
            f"!= DependencyRegistry {dep_reg.registry_version!r}"
        )
    if ext_reg.parent_registry_version != dep_reg.registry_version:
        raise RegistryError(
            f"ExtensionRegistry parent_registry_version {ext_reg.parent_registry_version!r} "
            f"!= DependencyRegistry {dep_reg.registry_version!r}"
        )

    entries = _build_default_entries(dep_reg, hh_reg, ts_reg, ext_reg)
    return EvidenceRegistry(
        parent_dependency_registry_version=dep_reg.registry_version,
        parent_dependency_registry_fingerprint=dep_reg.fingerprint,
        household_registry_version=hh_reg.registry_version,
        type_size_registry_version=ts_reg.registry_version,
        extension_registry_version=ext_reg.registry_version,
        datasets=entries,
    )
