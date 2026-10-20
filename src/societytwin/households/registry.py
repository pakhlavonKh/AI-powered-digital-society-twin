"""Typed household-scope extension bound to the unchanged Phase 1 registry."""
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from societytwin.common import canonical_hash
from societytwin.national.dependencies import compile_compatibility, load_registry as load_parent

REPO_ROOT = Path(__file__).resolve().parents[3]
CLASSES = tuple(str(i) for i in range(1, 10)) + ("10+",)


class HouseholdError(ValueError):
    pass


class Typed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Module(Typed):
    name: Literal["unlinked_households"]
    scope: Literal["household"]
    enabled: StrictBool = False


class OriginalObservation(Typed):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Source(Typed):
    source_version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    source_file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    province_code: Literal["06"]
    reference_year: Literal[2025]
    reference_date: Literal["2025-12-31"]
    scope: Literal["household"]
    dimensions: tuple[Literal["province_code", "household_size_class"], ...]
    unit: Literal["household"]
    universe: Literal["ADNKS_private_households"]
    coverage: str = Field(min_length=1)
    evidence: Literal["observed_distribution"]
    expected_total: int = Field(gt=0, strict=True)
    acquisition: str = Field(min_length=1)
    original_observations: tuple[OriginalObservation, ...] = Field(min_length=1)
    reuse: str = Field(min_length=1)
    limitation: str = Field(min_length=1)


class Attribute(Typed):
    scope: Literal["household"]
    dtype: Literal["string", "integer", "boolean", "float"]
    method: Literal["stable_id", "constant", "stratified_size_allocation", "size_bounds", "stratum_weight"]
    parents: tuple[str, ...]


CONTRACT = {
    "household_id": ("string", "stable_id", ()),
    "province_code": ("string", "constant", ()),
    "reference_year": ("integer", "constant", ()),
    "household_size_class": ("string", "stratified_size_allocation", ("province_code",)),
    "household_size": ("integer", "size_bounds", ("household_size_class",)),
    "household_size_lower": ("integer", "size_bounds", ("household_size_class",)),
    "household_size_upper": ("integer", "size_bounds", ("household_size_class",)),
    "household_size_open_ended": ("boolean", "size_bounds", ("household_size_class",)),
    "household_weight": ("float", "stratum_weight", ("household_size_class",)),
}


class HouseholdRegistry(Typed):
    schema_version: Literal["household-registry-1"]
    registry_version: str = Field(min_length=1)
    parent_schema_version: Literal["dependency-registry-1"]
    parent_registry_version: str
    module: Module
    source: Source
    size_classes: tuple[str, ...]
    attributes: dict[str, Attribute]

    @model_validator(mode="after")
    def contract(self):
        if self.source.dimensions != ("province_code", "household_size_class"):
            raise ValueError("unsupported household source dimensions")
        if self.size_classes != CLASSES or set(self.attributes) != set(CONTRACT):
            raise ValueError("household schema/categories differ from supported v1 contract")
        for name, attr in self.attributes.items():
            if (attr.dtype, attr.method, attr.parents) != CONTRACT[name]:
                raise ValueError(f"unsupported household attribute binding: {name}")
        return self

    @property
    def fingerprint(self):
        return canonical_hash(self.model_dump(mode="json"))

    def activated(self):
        """Explicit request-local activation; never edits the on-disk default."""
        payload = self.model_dump(mode="json")
        payload["module"]["enabled"] = True
        return type(self).model_validate(payload)


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise HouseholdError(f"duplicate household registry key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_registry(path: Path | None = None) -> HouseholdRegistry:
    try:
        return HouseholdRegistry.model_validate(yaml.load(
            (path or REPO_ROOT / "data/household_registry.yaml").read_text(encoding="utf-8"), Loader=UniqueLoader))
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        raise HouseholdError(f"Invalid household registry: {exc}") from exc


def parent_binding(registry: HouseholdRegistry, path: Path | None = None) -> dict:
    parent = load_parent(path) if path else load_parent()
    compile_compatibility(parent)
    if (parent.schema_version, parent.registry_version) != (registry.parent_schema_version, registry.parent_registry_version):
        raise HouseholdError("household registry requires a compatible parent dependency registry")
    return {"schema_version": parent.schema_version, "registry_version": parent.registry_version,
            "fingerprint": parent.fingerprint}
