"""Typed dependency metadata and the compatibility-first registry compiler.

The registry describes evidence; it never creates it. Phase 1 dispatches only to
the existing generator. Topological order is diagnostic: the legacy stochastic
and calibration order remains explicit and unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, model_validator

from societytwin.common import canonical_hash
from societytwin.national.constraints import ADULT_AGE, RULES_BY_ID
from societytwin.national.controls import TABLE_KINDS, ControlStore
from societytwin.national.vocab import AGE_GROUPS, VOCABULARIES

_CHECKOUT_REGISTRY_PATH = Path(__file__).resolve().parents[3] / "data" / "dependency_registry.yaml"
_PACKAGED_REGISTRY_PATH = Path(__file__).resolve().parent / "dependency_registry.yaml"
DEFAULT_REGISTRY_PATH = _CHECKOUT_REGISTRY_PATH if _CHECKOUT_REGISTRY_PATH.is_file() else _PACKAGED_REGISTRY_PATH
Scope = Literal["person", "household", "geography"]
Method = Literal["joint_allocation", "uniform_within_band", "conditional_age_sex", "ipf_sex", "marginal", "derived"]
EvidenceClass = Literal["A", "B", "C", "D", "E", "F"]


class RegistryError(ValueError):
    """Invalid registry or a declaration outside the Phase 1 execution contract."""


class TypedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provenance(TypedModel):
    reference: str = Field(min_length=1)
    version: str = Field(min_length=1)
    note: str = ""


class ModuleDefinition(TypedModel):
    enabled: StrictBool
    description: str


class SourceDefinition(TypedModel):
    table_id: str
    dimensions: tuple[str, ...]
    scope: Scope = "person"
    evidence: Literal["observed_distribution", "context_only"] = "observed_distribution"
    provenance: Provenance


class Derivation(TypedModel):
    operator: Literal["band_is_open", "province_nuts2", "greater_equal"]
    constant: StrictInt | None = None


class Assignment(TypedModel):
    method: Method
    source: str | None = None
    evidence_class: EvidenceClass
    runtime_evidence: Literal["DIRECT_SOURCE", "CONDITIONAL_SOURCE", "MARGINAL_INFERENCE", "ASSUMED", "DERIVED"]
    assumption: str | None = None
    category_mapping: dict[str, str] = Field(default_factory=dict)


class AttributeDefinition(TypedModel):
    scope: Scope
    dtype: Literal["categorical", "string", "integer", "boolean"]
    vocabulary: str | None = None
    parents: tuple[str, ...] = ()
    module: str = "core"
    required: bool = False
    missing_source: Literal["error", "null_with_reason"] = "null_with_reason"
    missing_parent: Literal["propagate_null", "error"] = "propagate_null"
    constraints: tuple[str, ...] = ()
    assignments: tuple[Assignment, ...]
    derivation: Derivation | None = None
    description: str
    provenance: Provenance


class MaritalStrategy(TypedModel):
    """Bounded opt-in transfer; rounding interpretation is an acknowledged assumption."""
    enabled: StrictBool = False
    model_version: Literal["national_age_marital_seed_v1"] = "national_age_marital_seed_v1"
    policy_version: Literal["assumed_nearest_tenth_sensitivity_v1"]
    acknowledge_unverified_rounding: Literal[True]
    zero_variant: Literal["lower_quartile", "midpoint", "upper_quartile"]
    source_file: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    province_code: Literal["06"] = "06"
    reference_year: Literal[2025] = 2025


class DependencyRegistry(TypedModel):
    schema_version: Literal["dependency-registry-1"]
    registry_version: str = Field(min_length=1)
    compatibility_profile: Literal["national-v1"]
    reference_year_policy: Literal["latest_not_after_build"]
    modules: dict[str, ModuleDefinition]
    sources: dict[str, SourceDefinition]
    attributes: dict[str, AttributeDefinition]
    assignment_order: tuple[str, ...]
    marital_strategy: MaritalStrategy | None = None

    @model_validator(mode="after")
    def validate_dependencies(self):
        # Resolve graph references before looking through another node's module.
        for name,attr in self.attributes.items():
            if attr.module not in self.modules:
                raise ValueError(f"attribute {name}: unknown module {attr.module!r}")
            for parent in attr.parents:
                if parent not in self.attributes:
                    raise ValueError(f"attribute {name}: unknown parent {parent!r}")
        for name, source in self.sources.items():
            kind = TABLE_KINDS.get(source.table_id)
            if kind is None:
                raise ValueError(f"source {name}: unknown table {source.table_id!r}")
            # The table contract, not a claimed YAML dimension, is authoritative.
            dimensions = ("province_code",) + tuple(kind.attribute if d == "category" else d for d in kind.dims)
            if source.dimensions != dimensions:
                raise ValueError(f"source {name}: unsupported source dimensions; expected {dimensions}")
            if source.scope != "person":
                raise ValueError(f"source {name}: table {source.table_id} has person scope")
        for name, attr in self.attributes.items():
            if attr.module not in self.modules:
                raise ValueError(f"attribute {name}: unknown module {attr.module!r}")
            if len(set(attr.parents)) != len(attr.parents):
                raise ValueError(f"attribute {name}: duplicate parents")
            for parent in attr.parents:
                if parent not in self.attributes:
                    raise ValueError(f"attribute {name}: unknown parent {parent!r}")
                other = self.attributes[parent]
                if other.scope != attr.scope:
                    raise ValueError(f"attribute {name}: incompatible scope dependency on {parent}; explicit links are not supported")
                if self.enabled(name) and not self.enabled(parent):
                    raise ValueError(f"attribute {name}: enabled attribute has disabled parent {parent}")
            vocabulary = self.categories(name)
            if attr.dtype == "categorical" and not vocabulary:
                raise ValueError(f"attribute {name}: categorical attributes need a known vocabulary")
            if attr.vocabulary is not None and attr.dtype != "categorical":
                raise ValueError(f"attribute {name}: vocabulary requires categorical dtype")
            for rule in attr.constraints:
                if rule not in RULES_BY_ID or name not in RULES_BY_ID[rule].fields:
                    raise ValueError(f"attribute {name}: unknown or inapplicable constraint {rule!r}")
            if not attr.assignments:
                raise ValueError(f"attribute {name}: missing required evidence/assignment")
            if attr.required and attr.missing_source != "error":
                raise ValueError(f"attribute {name}: required evidence must use missing_source: error")
            for assignment in attr.assignments:
                self._validate_assignment(name, attr, assignment, vocabulary)
            derived = any(a.method == "derived" for a in attr.assignments)
            if derived != (attr.derivation is not None) or (derived and len(attr.assignments) != 1):
                raise ValueError(f"attribute {name}: derived assignment requires exactly one derivation")
            if derived:
                self._validate_derivation(name, attr)
        self.ordered_attributes()  # Includes disabled declarations: dormant cycles are invalid too.
        if len(set(self.assignment_order)) != len(self.assignment_order):
            raise ValueError("assignment_order contains duplicates")
        expected = {n for n,a in self.attributes.items() if self.enabled(n) and any(x.method in
                    ("conditional_age_sex", "ipf_sex", "marginal") for x in a.assignments)}
        if set(self.assignment_order) != expected:
            raise ValueError(f"assignment_order must contain exactly enabled stochastic attributes: {sorted(expected)}")
        positions = {n:i for i,n in enumerate(self.assignment_order)}
        for n in self.assignment_order:
            if any(p in positions and positions[p] >= positions[n] for p in self.attributes[n].parents):
                raise ValueError(f"assignment_order violates dependency of {n}")
        return self

    def enabled(self, name: str) -> bool:
        return self.modules[self.attributes[name].module].enabled

    def categories(self, name: str) -> tuple[str, ...]:
        vocab = self.attributes[name].vocabulary
        if vocab is None:
            return ()
        if vocab == "age_group":
            return AGE_GROUPS
        if vocab not in VOCABULARIES:
            raise ValueError(f"attribute {name}: unknown vocabulary {vocab!r}")
        return VOCABULARIES[vocab].codes

    def _validate_assignment(self, name: str, attr: AttributeDefinition, assignment: Assignment,
                             vocabulary: tuple[str, ...]) -> None:
        method = assignment.method
        source = self.sources.get(assignment.source) if assignment.source else None
        if assignment.source and source is None:
            raise ValueError(f"attribute {name}: unknown source {assignment.source!r}")
        if method in ("joint_allocation", "conditional_age_sex", "ipf_sex", "marginal"):
            if source is None or source.evidence != "observed_distribution":
                raise ValueError(f"attribute {name}: missing required observed evidence for {method}")
            if source.scope != attr.scope:
                raise ValueError(f"attribute {name}: incompatible source scope")
            kind = TABLE_KINDS[source.table_id]
            if method == "joint_allocation":
                if source.table_id != "population_age_sex" or name not in source.dimensions:
                    raise ValueError(f"attribute {name}: unsupported root source")
                allowed_parents = set(source.dimensions) - {name}
            else:
                dims = {"conditional_age_sex": ("age_group", "sex", "category"),
                        "ipf_sex": ("sex", "category"), "marginal": ("category",)}[method]
                if kind.dims != dims or kind.attribute != name:
                    raise ValueError(f"attribute {name}: unsupported source dimensions/attribute for {method}")
                # A marginal fallback explicitly models independence of both age
                # and sex, including when a stronger strategy was requested.
                allowed_parents = {"province_code", "age_group", "sex"}
            if not set(attr.parents) <= allowed_parents:
                raise ValueError(f"attribute {name}: unsupported conditional relationship with parents {attr.parents}")
            if method in ("ipf_sex", "marginal"):
                if not assignment.assumption or assignment.evidence_class != "D" or assignment.runtime_evidence != "MARGINAL_INFERENCE":
                    raise ValueError(f"attribute {name}: inferred relationship needs explicit assumption and modelled evidence D")
            elif assignment.evidence_class not in ("A", "B") or assignment.runtime_evidence != (
                    "DIRECT_SOURCE" if method == "joint_allocation" else "CONDITIONAL_SOURCE"):
                raise ValueError(f"attribute {name}: observed assignment has incompatible evidence classification")
        elif method == "uniform_within_band":
            if name != "age" or attr.parents != ("age_group",) or attr.dtype != "integer" or not assignment.assumption:
                raise ValueError(f"attribute {name}: unsupported uniform age declaration")
            if assignment.evidence_class != "D" or assignment.runtime_evidence != "ASSUMED":
                raise ValueError("uniform age must be labelled ASSUMED / D")
        elif assignment.evidence_class != "C" or assignment.runtime_evidence != "DERIVED":
            raise ValueError(f"attribute {name}: derivation requires C / DERIVED evidence")
        if method in ("derived", "uniform_within_band") and assignment.source is not None:
            raise ValueError(f"attribute {name}: this method does not read a source table")
        if assignment.category_mapping:
            # Internal controls already use canonical codes. A remap here would alter
            # probabilities or require a new ingestion contract, so only identity is legal.
            if any(k not in vocabulary or v != k for k,v in assignment.category_mapping.items()):
                raise ValueError(f"attribute {name}: invalid category mapping; Phase 1 accepts canonical identity mappings only")

    def _validate_derivation(self, name: str, attr: AttributeDefinition) -> None:
        contracts = {"band_is_open": ("age_top_coded", ("age_group",), "boolean", None),
                     "province_nuts2": ("nuts2_code", ("province_code",), "string", None),
                     "greater_equal": ("adult_eligibility", ("age",), "boolean", ADULT_AGE)}
        if (name, attr.parents, attr.dtype, attr.derivation.constant) != contracts[attr.derivation.operator]:
            raise ValueError(f"attribute {name}: invalid derivation contract for {attr.derivation.operator}")

    def ordered_attributes(self, *, enabled_only: bool = False) -> tuple[str, ...]:
        """Deterministic Kahn ordering, independent of YAML mapping order."""
        pending = {n:set(a.parents) for n,a in self.attributes.items()}
        ordered = []
        while pending:
            ready = sorted(n for n,parents in pending.items() if not parents)
            if not ready:
                raise ValueError(f"cyclic dependencies: {', '.join(sorted(pending))}")
            for name in ready:
                ordered.append(name)
                del pending[name]
            for parents in pending.values():
                parents.difference_update(ready)
        return tuple(n for n in ordered if not enabled_only or self.enabled(n))

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def validate_controls(self, store: ControlStore) -> None:
        """Required sources must actually have observations; optional sources may be absent.

        Existing root selection still enforces province/year availability at generation.
        """
        for name,attr in self.attributes.items():
            if not self.enabled(name) or not attr.required:
                continue
            tables = {self.sources[a.source].table_id for a in attr.assignments if a.source}
            if tables and not any(r.table_id in tables and r.value is not None and r.value_status == "OBSERVED" for r in store.rows):
                raise RegistryError(f"attribute {name}: missing required evidence in control store ({sorted(tables)})")


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise RegistryError(f"duplicate registry key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> DependencyRegistry:
    try:
        payload = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueLoader)
        return DependencyRegistry.model_validate(payload)
    except ValidationError as exc:
        # Keep the field paths and reasons visible through the API's existing
        # bounded error messages; do not dump whole input documents or URLs.
        reasons = "; ".join(f"{'.'.join(map(str,e['loc'])) or 'registry'}: {e['msg']}"
                            for e in exc.errors()[:3])
        raise RegistryError(f"Invalid dependency registry {path}: {reasons}") from exc
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
        raise RegistryError(f"Invalid dependency registry {path}: {exc}") from exc


@dataclass(frozen=True)
class CompiledAttribute:
    attribute: str
    options: tuple[tuple[str, str], ...]
    structural_zeros: bool
    description: str


def compile_compatibility(registry: DependencyRegistry) -> tuple[CompiledAttribute, ...]:
    """Bridge declarations to legacy AttributeSpecs without changing numerical code.

    This profile deliberately rejects new execution semantics. The signatures are
    a compatibility gate, not another source of assignment configuration.
    """
    signatures = {
        "marital_status": (("marital_status_age_sex", "conditional_age_sex"), ("marital_status_sex", "ipf_sex")),
        "education_level": (("education_age_sex", "conditional_age_sex"), ("education_sex", "ipf_sex")),
        "labour_status": (("labour_status_age_sex", "conditional_age_sex"), ("labour_status_sex", "ipf_sex")),
        "household_size_class": (("household_size_persons", "marginal"),),
        "household_type": (("household_type_persons", "marginal"),),
        "urbanicity": (("urbanicity_sex", "ipf_sex"), ("urbanicity", "marginal")),
    }
    core = {"province_code", "age_group", "sex", "age", "age_top_coded", "nuts2_code", "adult_eligibility"}
    if set(registry.ordered_attributes(enabled_only=True)) != core | set(signatures):
        raise RegistryError("national-v1 requires exactly the existing core and six legacy assignment attributes")
    if registry.assignment_order != tuple(signatures):
        raise RegistryError("national-v1 must preserve legacy assignment/calibration order")
    if any(m.enabled and n not in ("core", "legacy_optional") for n,m in registry.modules.items()):
        raise RegistryError("national-v1 cannot enable new execution modules")
    core_contracts = {
        "province_code": ("string", (), "joint_allocation"),
        "age_group": ("categorical", ("province_code",), "joint_allocation"),
        "sex": ("categorical", ("province_code",), "joint_allocation"),
        "age": ("integer", ("age_group",), "uniform_within_band"),
        "age_top_coded": ("boolean", ("age_group",), "derived"),
        "nuts2_code": ("string", ("province_code",), "derived"),
        "adult_eligibility": ("boolean", ("age",), "derived"),
    }
    for name,(dtype,parents,method) in core_contracts.items():
        attr = registry.attributes[name]
        if attr.scope != "person" or (attr.dtype,attr.parents,tuple(a.method for a in attr.assignments)) != (dtype,parents,(method,)):
            raise RegistryError(f"national-v1 must preserve core binding for {name}")
        root = name in ("province_code", "age_group", "sex")
        if attr.vocabulary != (name if name in ("age_group", "sex") else None) or attr.constraints or attr.required != root or attr.missing_source != ("error" if root else "null_with_reason"):
            raise RegistryError(f"national-v1 must preserve core vocabulary, constraints and evidence policy for {name}")
    compiled = []
    for name in registry.assignment_order:
        attr = registry.attributes[name]
        options = tuple((registry.sources[a.source].table_id,a.method) for a in attr.assignments)
        zeros = "education_min_completion_age" in attr.constraints
        if options != signatures[name] or zeros != (name == "education_level"):
            raise RegistryError(f"national-v1 must preserve source selection and structural zeros for {name}")
        if attr.missing_source != "null_with_reason" or attr.required:
            raise RegistryError(f"national-v1 must preserve optional source policy for {name}")
        expected_parents = ("province_code",) if name in ("household_type", "household_size_class") else ("province_code", "age_group", "sex")
        expected_constraints = ("source_universe", "education_min_completion_age") if zeros else ("source_universe",)
        if attr.scope != "person" or attr.dtype != "categorical" or attr.vocabulary != name or attr.parents != expected_parents or attr.constraints != expected_constraints:
            raise RegistryError(f"national-v1 must preserve attribute binding for {name}")
        compiled.append(CompiledAttribute(name,options,zeros,attr.description))
    return tuple(compiled)
