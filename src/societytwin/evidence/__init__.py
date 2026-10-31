"""Evidence Registry (K1) and Statistical Normalization & Reference Loaders (K2).

Extends the existing ``DependencyRegistry`` (and companion household/enrichment
registries) without creating a competing registry or mutating ``national-v1``
compatibility contracts.
"""

from __future__ import annotations

from societytwin.evidence.loaders import (
    EvidenceLoadError,
    ReferenceCell,
    ReferenceDataset,
    build_reference_package,
    load_reference_dataset,
    resolve_dataset_path,
)
from societytwin.evidence.normalization import (
    DataQualityIssue,
    DistributionSummary,
    NormalizationError,
    NormalizationResult,
    ValidationCheckResult,
    compute_distribution,
    detect_denominator_inconsistency,
    normalize_category,
    normalize_reference_table,
    validate_category_totals,
)
from societytwin.evidence.registry import (
     EVIDENCE_REGISTRY_SCHEMA_VERSION,
    EVIDENCE_REGISTRY_VERSION,
    CategoryDefinition,
    DataQualityFlag,
    DatasetStatus,
    DenominatorSpec,
    EvidenceDatasetEntry,
    EvidenceRegistry,
    GeographyScope,
    RetrievalInfo,
    SourceReference,
    load_evidence_registry,
)

__all__ = [
    "EVIDENCE_REGISTRY_SCHEMA_VERSION",
    "EVIDENCE_REGISTRY_VERSION",
    "CategoryDefinition",
    "DataQualityFlag",
    "DataQualityIssue",
    "DatasetStatus",
    "DenominatorSpec",
    "DistributionSummary",
    "EvidenceDatasetEntry",
    "EvidenceLoadError",
    "EvidenceRegistry",
    "GeographyScope",
    "NormalizationError",
    "NormalizationResult",
    "ReferenceCell",
    "ReferenceDataset",
    "RetrievalInfo",
    "SourceReference",
    "ValidationCheckResult",
    "build_reference_package",
    "compute_distribution",
    "detect_denominator_inconsistency",
    "load_evidence_registry",
    "load_reference_dataset",
    "normalize_category",
    "normalize_reference_table",
    "resolve_dataset_path",
    "validate_category_totals",
]
