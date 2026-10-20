from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from societytwin.national.dependencies import TypedModel
from societytwin.national.rng import MAX_SEED

Status=Literal['assigned','published_unknown','not_reported','unsupported','outside_universe']


class EnrichmentConfig(TypedModel):
    seed: int = Field(default=42,ge=0,le=MAX_SEED,strict=True)


class AttributeValue(TypedModel):
    attribute: str
    value: str | None
    status: Status
    provenance_profile: str


class ExtensionRecord(TypedModel):
    synthetic_id: str
    attributes: tuple[AttributeValue,...]


@dataclass(frozen=True)
class ResidentExtension:
    records: tuple[ExtensionRecord,...]
    manifest: dict
