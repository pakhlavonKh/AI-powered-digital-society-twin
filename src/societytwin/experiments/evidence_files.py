"""Contained, read-only access to files inside one run directory."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from societytwin.common import has_symlink_component, is_within, sha256_bytes

MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_RUN = 2000
MAX_DEPTH = 8
ARTIFACT_MEDIA_TYPES = {
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".md": "text/markdown; charset=utf-8",
    ".pdf": "application/pdf",
    ".yaml": "text/plain; charset=utf-8",
}
SAFE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")


@dataclass
class FileEvidence:
    relpath: str
    status: str  # present | absent | malformed | unreadable | too_large | unsafe
    size: int | None = None
    sha256: str | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class RunFiles:
    """Reads files relative to a run directory. Absolute paths found inside artifacts are never followed."""

    def __init__(self, root: Path):
        self.root = root
        self.evidence: dict[str, FileEvidence] = {}
        self.skipped: list[str] = []

    def _path(self, rel: str) -> Path | None:
        parts = Path(rel).parts
        if Path(rel).is_absolute() or ".." in parts or not parts or not all(SAFE_NAME.fullmatch(p) for p in parts):
            return None
        path = self.root / rel
        if not is_within(path, self.root) or has_symlink_component(path, self.root):
            return None
        return path

    def read_bytes(self, rel: str, limit: int = MAX_JSON_BYTES) -> bytes | None:
        path = self._path(rel)
        if path is None:
            self.evidence[rel] = FileEvidence(rel, "unsafe", error="path rejected by containment checks")
            return None
        if not path.is_file():
            self.evidence.setdefault(rel, FileEvidence(rel, "absent"))
            return None
        try:
            size = path.stat().st_size
            if size > limit:
                self.evidence[rel] = FileEvidence(rel, "too_large", size=size)
                return None
            data = path.read_bytes()
        except OSError as exc:
            self.evidence[rel] = FileEvidence(rel, "unreadable", error=type(exc).__name__)
            return None
        self.evidence[rel] = FileEvidence(rel, "present", size=len(data), sha256=sha256_bytes(data))
        return data

    def read_json(self, rel: str):
        data = self.read_bytes(rel)
        if data is None:
            return None
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.evidence[rel].status = "malformed"
            self.evidence[rel].error = type(exc).__name__
            return None
        return value

    def read_text(self, rel: str) -> str | None:
        data = self.read_bytes(rel)
        if data is None:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            self.evidence[rel].status = "malformed"
            self.evidence[rel].error = "UnicodeDecodeError"
            return None

    def read_jsonl(self, rel: str) -> tuple[list[dict] | None, int]:
        text = self.read_text(rel)
        if text is None:
            return None, 0
        events, malformed = [], 0
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(value, dict):
                events.append(value)
            else:
                malformed += 1
        if malformed:
            self.evidence[rel].error = f"{malformed} malformed line(s)"
        return events, malformed

    def listing(self) -> list[tuple[str, int, int]]:
        """(relpath, size, mtime_ns) for regular files; symlinks and unsafe names are skipped."""
        found = []
        root_depth = len(self.root.parts)
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            current = Path(dirpath)
            if len(current.parts) - root_depth >= MAX_DEPTH:
                dirnames[:] = []
            kept = []
            for d in dirnames:
                if os.path.islink(current / d) or not SAFE_NAME.fullmatch(d):
                    self.skipped.append(str((current / d).relative_to(self.root)))
                else:
                    kept.append(d)
            dirnames[:] = sorted(kept)
            for name in sorted(filenames):
                path = current / name
                rel = path.relative_to(self.root).as_posix()
                if name == ".DS_Store":
                    continue
                if os.path.islink(path) or not SAFE_NAME.fullmatch(name):
                    self.skipped.append(rel)
                    continue
                stat = path.stat()
                found.append((rel, stat.st_size, stat.st_mtime_ns))
                if len(found) >= MAX_FILES_PER_RUN:
                    return found
        return found
