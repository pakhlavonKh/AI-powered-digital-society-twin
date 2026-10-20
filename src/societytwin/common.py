"""Small dependency-free helpers shared by every layer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def crlf_variant_sha256(data: bytes) -> str:
    """Digest of the same text with every line ending written as CRLF."""
    normalized = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return sha256_bytes(normalized)


def lf_variant_sha256(data: bytes) -> str:
    return sha256_bytes(data.replace(b"\r\n", b"\n"))


def compare_recorded_digest(recorded: str | None, current_bytes: bytes | None) -> str:
    """Classify a recorded digest against current bytes.

    Returns ``match`` (byte identical), ``line_ending_equivalent`` (matches only after
    LF/CRLF conversion: explained drift, not byte identity), ``mismatch``, or
    ``unavailable`` when either side is missing.
    """
    if not recorded or current_bytes is None:
        return "unavailable"
    if sha256_bytes(current_bytes) == recorded:
        return "match"
    if recorded in {crlf_variant_sha256(current_bytes), lf_variant_sha256(current_bytes)}:
        return "line_ending_equivalent"
    return "mismatch"


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canonical_hash(payload: object) -> str:
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_HOME = str(Path.home())
_ABS_PATH = re.compile(r"(?:[A-Za-z]:\\|/)(?:Users|home|private|var|tmp|opt|Volumes|mnt)[^\s'\"<>|]*")
_SECRETISH = re.compile(r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)\s*=\s*\S+")


def redact(text: str | None, *, max_length: int = 2000) -> str:
    """Remove host paths and anything that looks like an assigned secret from user-facing text."""
    if not text:
        return ""
    cleaned = text.replace(_HOME, "~")
    cleaned = _ABS_PATH.sub("<path>", cleaned)
    cleaned = _SECRETISH.sub(lambda m: f"{m.group(1)}=<redacted>", cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[-max_length:]
    return cleaned


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def has_symlink_component(path: Path, root: Path) -> bool:
    """True when any component from root (exclusive) to path (inclusive) is a symlink."""
    root = root.absolute()
    current = path.absolute()
    while True:
        if current == root:
            return False
        if os.path.islink(current):
            return True
        if current.parent == current:
            return False
        current = current.parent
