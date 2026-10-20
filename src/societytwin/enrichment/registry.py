"""Typed sidecar extension reusing Phase 1 types, evidence rules and parent validation."""
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field,StrictInt,model_validator

from societytwin.common import canonical_hash
from societytwin.national.dependencies import (
    TypedModel,Provenance,ModuleDefinition,_UniqueLoader,load_registry as load_parent,compile_compatibility,
)

REPO_ROOT=Path(__file__).resolve().parents[3]


class EnrichmentError(ValueError):
    pass


class Category(TypedModel):
    code: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    kind: Literal['known','published_unknown'] = 'known'


class Source(TypedModel):
    path: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    dimensions: tuple[str,...]
    scope: Literal['person']
    unit: Literal['person']
    universe: Literal['ADNKS_residents']
    province_code: Literal['06']
    reference_year: Literal[2025]
    evidence: Literal['observed_distribution']
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    acquisition: str = Field(min_length=1)
    coverage: str = Field(min_length=1)
    reuse: str = Field(min_length=1)


class Attribute(TypedModel):
    scope: Literal['person']
    module: str
    method: Literal['conditional_categorical_v1']
    parents: tuple[str,...]
    evidence_class: Literal['D']
    assumption: Literal['independent_of_other_core_attributes_within_province_sex_v1']
    missing_source: Literal['error','unavailable']
    min_age: int = Field(ge=0,strict=True)
    max_age: int | None = Field(default=None,ge=0,strict=True)
    categories: tuple[Category,...] = Field(min_length=2)
    provenance: Provenance
    source: Source


class ExtensionRegistry(TypedModel):
    schema_version: Literal['resident-extension-registry-1']
    registry_version: str = Field(min_length=1)
    model_version: Literal['registry_conditional_categorical_v1']
    parent_registry_version: str
    modules: dict[str,ModuleDefinition]
    attributes: dict[str,Attribute]

    @model_validator(mode='after')
    def contract(self):
        if not self.attributes:
            raise ValueError('no optional attribute declarations')
        for name,a in self.attributes.items():
            if not name.isidentifier() or a.module not in self.modules:
                raise ValueError(f'{name}: invalid name or unknown module')
            if a.parents!=('province_code','sex') or a.source.dimensions!=('province_code','sex','category'):
                raise ValueError(f'{name}: unsupported conditioning dimensions/parents')
            codes=[c.code for c in a.categories]
            if len(codes)!=len(set(codes)) or (a.max_age is not None and a.max_age<a.min_age):
                raise ValueError(f'{name}: duplicate categories or invalid universe age bounds')
        return self

    @property
    def fingerprint(self):
        return canonical_hash(self.model_dump(mode='json'))

    def activated(self):
        payload=self.model_dump(mode='json')
        for m in payload['modules'].values():m['enabled']=True
        return type(self).model_validate(payload)


def parent_binding(registry):
    parent=load_parent();compile_compatibility(parent)
    if parent.registry_version!=registry.parent_registry_version:
        raise EnrichmentError('incompatible parent dependency registry')
    for name,a in registry.attributes.items():
        if name in parent.attributes:
            raise EnrichmentError(f'{name}: optional sidecar cannot override a core attribute')
        if any(p not in parent.attributes or parent.attributes[p].scope!='person' for p in a.parents):
            raise EnrichmentError(f'{name}: missing or incompatible parent dependency')
    return {'registry_version':parent.registry_version,'schema_version':parent.schema_version,'fingerprint':parent.fingerprint}


def load_registry(path: Path | None = None):
    try:
        result=ExtensionRegistry.model_validate(yaml.load(
            (path or REPO_ROOT/'data/resident_extension_registry.yaml').read_text(encoding='utf-8'),Loader=_UniqueLoader))
        parent_binding(result)
        return result
    except (OSError,ValueError,TypeError,yaml.YAMLError) as exc:
        raise EnrichmentError(f'Invalid optional resident registry: {exc}') from exc
