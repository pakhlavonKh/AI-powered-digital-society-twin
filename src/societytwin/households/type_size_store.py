"""Distinct schema/store for optional type-size artifacts; legacy schema unchanged."""
import pyarrow as pa

from societytwin.households.store import HouseholdStore,SCHEMA as SIZE_SCHEMA
from societytwin.households.type_size import TypedHouseholdRecord
from societytwin.households.type_size_registry import SCHEMA_VERSION
from societytwin.households.type_size_validation import validate_type_size

SCHEMA=pa.schema(list(SIZE_SCHEMA)+[
    pa.field('household_type',pa.string(),nullable=False),
    pa.field('household_type_size_band',pa.string(),nullable=False),
    pa.field('provenance_profile',pa.string(),nullable=False),
],metadata={b'societytwin.schema_version':SCHEMA_VERSION.encode(),b'societytwin.unit':b'household'})


class TypeSizeStore(HouseholdStore):
    schema=SCHEMA
    record_type=TypedHouseholdRecord
    check=staticmethod(validate_type_size)
    id_pattern=r'hht-06-2025-n[0-9]+-s[0-9]+-[0-9a-f]{16}'
