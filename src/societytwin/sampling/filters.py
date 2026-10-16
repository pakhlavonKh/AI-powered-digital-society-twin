"""Structured filter specification. Filters are data: no SQL, expressions or regular expressions are executed."""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from societytwin.population.categories import AGE_GROUPS, GENDERS, MARITAL_STATUSES
from societytwin.population.fixtures import ID_PATTERN

AgeGroup = Literal[AGE_GROUPS]  # type: ignore[valid-type]
Gender = Literal[GENDERS]  # type: ignore[valid-type]
MaritalStatus = Literal[MARITAL_STATUSES]  # type: ignore[valid-type]
PersonId = Annotated[str, StringConstraints(pattern=ID_PATTERN.pattern)]

FIELD_FOR_FILTER = {
    "person_ids": "person_id",
    "age_groups": "age_group",
    "genders": "gender",
    "marital_statuses": "marital_status",
}


class FieldUnavailable(ValueError):
    code = "field_unavailable"

    def __init__(self, field: str, build_id: str):
        super().__init__(f"Field '{field}' does not exist in build {build_id}")
        self.field = field
        self.build_id = build_id


class FilterSpec(BaseModel):
    """AND across fields, OR within a field; an omitted field means no restriction."""

    model_config = ConfigDict(extra="forbid")

    person_ids: list[PersonId] | None = Field(default=None, min_length=1, max_length=1000,
                                              description="Exact resident IDs (no pattern matching).")
    age_groups: list[AgeGroup] | None = Field(default=None, min_length=1)
    genders: list[Gender] | None = Field(default=None, min_length=1,
                                         description="Administrative sex category as recorded by TÜİK.")
    marital_statuses: list[MaritalStatus] | None = Field(default=None, min_length=1,
                                                         description="Source TÜİK labels; available in v2 builds only.")

    @field_validator("marital_statuses", mode="before")
    @classmethod
    def _nfc(cls, value):
        if isinstance(value, list):
            return [unicodedata.normalize("NFC", v) if isinstance(v, str) else v for v in value]
        return value

    def normalized(self) -> dict[str, list[str]]:
        """Canonical form used for persistence and hashing: omitted fields dropped, values unique and ordered."""
        out: dict[str, list[str]] = {}
        orders = {"age_groups": AGE_GROUPS, "genders": GENDERS, "marital_statuses": MARITAL_STATUSES}
        for name in FIELD_FOR_FILTER:
            values = getattr(self, name)
            if values is None:
                continue
            unique = set(values)
            order = orders.get(name)
            out[name] = [v for v in order if v in unique] if order else sorted(unique)
        return out

    def check_available(self, available_fields: list[str], build_id: str) -> None:
        for name, column in FIELD_FOR_FILTER.items():
            if getattr(self, name) is not None and column not in available_fields:
                raise FieldUnavailable(column, build_id)

    def matches(self, row: dict[str, str]) -> bool:
        for name, column in FIELD_FOR_FILTER.items():
            values = getattr(self, name)
            if values is not None and row.get(column) not in values:
                return False
        return True
