from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, StrictBool, model_validator

from societytwin.national.dependencies import TypedModel, _UniqueLoader
from societytwin.national.rng import MAX_SEED

REPO_ROOT = Path(__file__).resolve().parents[3]


class BuildError(ValueError):
    pass


class Inputs(TypedModel):
    controls_directory: Path = Path('data/processed/national')
    resident_registry: Path = Path('data/dependency_registry.yaml')
    enrichment_registry: Path = Path('data/resident_extension_registry.yaml')
    household_registry: Path = Path('data/household_registry.yaml')
    household_type_registry: Path = Path('data/household_type_size_registry.yaml')


class Marital(TypedModel):
    strategy: Literal['default', 'national_age_marital_seed_v1'] = 'default'
    sensitivity: Literal['lower_quartile', 'midpoint', 'upper_quartile'] | None = None
    acknowledge_unverified_rounding: StrictBool = False

    @model_validator(mode='after')
    def contract(self):
        if self.strategy == 'default':
            if self.sensitivity is not None or self.acknowledge_unverified_rounding:
                raise ValueError('marital sensitivity/acknowledgement requires the optional strategy')
        elif self.sensitivity is None or not self.acknowledge_unverified_rounding:
            raise ValueError('optional marital strategy requires sensitivity and acknowledgement of unverified rounding')
        return self


class Households(TypedModel):
    enabled: StrictBool = False
    sample_size: int = Field(default=1000, ge=10, le=1_000_000, strict=True)
    strategy: Literal['size_only', 'national_household_type_size_seed_v1'] = 'size_only'

    @model_validator(mode='after')
    def contract(self):
        if not self.enabled and self.strategy != 'size_only':
            raise ValueError('household strategy requires households.enabled=true')
        return self


class Validation(TypedModel):
    calibration_relative: float = Field(default=1e-6, gt=0, le=0.01)
    familywise_alpha: float = Field(default=0.01, gt=0, lt=1)
    min_group_records_for_noise_test: int = Field(default=30, ge=1, strict=True)
    fail_on_constraint_violations: StrictBool = True
    fail_on_unfitted_margins: StrictBool = False


class BuildConfig(TypedModel):
    schema_version: Literal['ankara-build-config-1'] = 'ankara-build-config-1'
    province_code: Literal['06'] = '06'
    reference_year: Literal[2025] = 2025
    resident_sample_size: int = Field(default=10000, ge=100, le=1_000_000, strict=True)
    seed: int = Field(default=42, ge=0, le=MAX_SEED, strict=True)
    resident_enrichments: tuple[Literal['degurba_class'], ...] = ()
    marital: Marital = Field(default_factory=Marital)
    households: Households = Field(default_factory=Households)
    inputs: Inputs = Field(default_factory=Inputs)
    output_root: Path = Path('data/results/unified-populations')
    validation: Validation = Field(default_factory=Validation)

    @model_validator(mode='after')
    def contract(self):
        if len(self.resident_enrichments) != len(set(self.resident_enrichments)):
            raise ValueError('duplicate resident enrichment modules')
        return self


def resolve(path):
    return (REPO_ROOT / path).resolve()


def load_config(path):
    try:
        return BuildConfig.model_validate(yaml.load(Path(path).read_text(encoding='utf-8'), Loader=_UniqueLoader))
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        raise BuildError(f'Invalid unified build configuration: {exc}') from exc
