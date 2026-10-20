"""Explicit household registry extension. The size-only registry/hash is unchanged."""
from typing import Literal

import yaml
from pydantic import Field, StrictBool, model_validator

from societytwin.common import canonical_hash
from societytwin.households.registry import REPO_ROOT, HouseholdError, Typed, UniqueLoader

TYPES = ('one_person','nuclear_family','extended_family','non_family_multi_person')
BANDS = ('1','2','3','4','5','6','7+')
MODEL_VERSION = 'national_household_type_size_seed_v1'
SCHEMA_VERSION = 'household-type-size-schema-1'


class TableSource(Typed):
    path: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    geography: Literal['TR','06']
    reference_year: Literal[2025]
    unit: Literal['household']
    universe: Literal['ADNKS_private_households']
    evidence: Literal['observed_joint_counts','observed_marginal_counts']
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    acquisition: str = Field(min_length=1)


class TypeAttribute(Typed):
    scope: Literal['household']
    dtype: Literal['categorical']
    method: Literal['fitted_national_type_size','coarsen_size_1to6_7plus']
    parents: tuple[str,...]
    evidence_class: Literal['C','D']


class TypeSizeRegistry(Typed):
    schema_version: Literal['household-type-size-registry-1']
    registry_version: str = Field(min_length=1)
    model_version: Literal['national_household_type_size_seed_v1']
    schema_output_version: Literal['household-type-size-schema-1']
    enabled: StrictBool = False
    scope: Literal['household']
    base_registry_version: str
    transfer_policy: Literal['national_2025_association_fitted_to_ankara_2025_v1']
    tail_policy: Literal['exchangeable_within_observed_7plus_v1']
    types: tuple[str,...]
    source_size_classes: tuple[str,...]
    national: TableSource
    ankara_types: TableSource
    structural_support: Literal['one_person_iff_size1_extended_min3_others_min2_v1']
    reuse: str = Field(min_length=1)
    attributes: dict[str,TypeAttribute]

    @model_validator(mode='after')
    def contract(self):
        if self.types != TYPES or self.source_size_classes != BANDS:
            raise ValueError('unsupported type/size categories')
        if (self.national.geography,self.national.evidence,self.ankara_types.geography,self.ankara_types.evidence) != (
                'TR','observed_joint_counts','06','observed_marginal_counts'):
            raise ValueError('incompatible source geography/evidence')
        expected={'household_type':('fitted_national_type_size',('province_code','household_type_size_band'),'D'),
                  'household_type_size_band':('coarsen_size_1to6_7plus',('household_size_class',),'C')}
        if set(self.attributes) != set(expected) or any(
                (a.method,a.parents,a.evidence_class)!=expected[n] for n,a in self.attributes.items()):
            raise ValueError('unsupported household type dependency binding')
        return self

    @property
    def fingerprint(self):
        return canonical_hash(self.model_dump(mode='json'))

    def activated(self):
        return type(self).model_validate(self.model_dump(mode='json') | {'enabled':True})


def load_type_size_registry(path=None):
    try:
        path=path or REPO_ROOT/'data/household_type_size_registry.yaml'
        return TypeSizeRegistry.model_validate(yaml.load(path.read_text(encoding='utf-8'),Loader=UniqueLoader))
    except (OSError,ValueError,TypeError,yaml.YAMLError) as exc:
        raise HouseholdError(f'Invalid household type-size registry: {exc}') from exc
