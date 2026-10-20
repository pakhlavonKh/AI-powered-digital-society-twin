"""Households are weighted household representatives, never resident records."""
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from societytwin.households.registry import Typed
from societytwin.national.rng import MAX_SEED


class HouseholdConfig(Typed):
    synthetic_size: int = Field(default=1000, ge=10, le=1_000_000, strict=True)
    seed: int = Field(default=42, ge=0, le=MAX_SEED, strict=True)
    province_code: Literal["06"] = "06"
    reference_year: Literal[2025] = 2025


@dataclass(frozen=True)
class HouseholdRecord:
    household_id: str
    province_code: str
    reference_year: int
    household_size_class: str
    household_size: int | None
    household_size_lower: int
    household_size_upper: int | None
    household_size_open_ended: bool
    household_weight: float


@dataclass(frozen=True)
class GeneratedHouseholds:
    records: tuple[HouseholdRecord, ...]
    manifest: dict
