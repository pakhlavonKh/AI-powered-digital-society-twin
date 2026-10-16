"""Domain errors with a stable machine code. The API maps ``kind`` to an HTTP status."""

from __future__ import annotations


class WorkbenchError(Exception):
    KINDS = {"not_found", "invalid", "conflict", "unavailable", "not_implemented", "forbidden"}

    def __init__(self, kind: str, code: str, message: str, details: dict | list | None = None):
        if kind not in self.KINDS:
            raise ValueError(kind)
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.message = message
        self.details = details


def not_found(code: str, message: str, details=None) -> WorkbenchError:
    return WorkbenchError("not_found", code, message, details)


def invalid(code: str, message: str, details=None) -> WorkbenchError:
    return WorkbenchError("invalid", code, message, details)


def conflict(code: str, message: str, details=None) -> WorkbenchError:
    return WorkbenchError("conflict", code, message, details)


def unavailable(code: str, message: str, details=None) -> WorkbenchError:
    return WorkbenchError("unavailable", code, message, details)
