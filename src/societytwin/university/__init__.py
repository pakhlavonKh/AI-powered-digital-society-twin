"""University observations; importing this package performs no database I/O."""

from .db import SCHEMA_VERSION, SchemaVersionError, connect, initialize_database

__all__ = ["SCHEMA_VERSION", "SchemaVersionError", "connect", "initialize_database"]
