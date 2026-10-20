"""Strict observed household-count ingestion; no population or mean-size rescaling."""
import csv
import io
from dataclasses import dataclass
from pathlib import Path

from societytwin.common import sha256_bytes
from societytwin.households.registry import CLASSES, HouseholdError, HouseholdRegistry, Source


@dataclass(frozen=True)
class HouseholdEvidence:
    source: Source
    counts: tuple[int, ...]

    @property
    def total(self):
        return sum(self.counts)


def load_evidence(registry: HouseholdRegistry, repo_root: Path) -> HouseholdEvidence:
    source = registry.source
    path = repo_root / source.source_file
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise HouseholdError(f"Household observations unavailable: {path}") from exc
    if sha256_bytes(raw) != source.sha256:
        raise HouseholdError("household observations checksum mismatch")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if reader.fieldnames != ["province_code", "reference_year", "household_size_class", "households"]:
            raise HouseholdError("unsupported household observation columns")
        counts = {}
        for row in reader:
            if set(row) != set(reader.fieldnames) or any(value is None for value in row.values()):
                raise HouseholdError("incomplete or extra household observation cells")
            if row["province_code"] != source.province_code or row["reference_year"] != str(source.reference_year):
                raise HouseholdError("household observations have wrong province/year")
            category = row["household_size_class"]
            if category not in CLASSES or category in counts:
                raise HouseholdError("duplicate or unsupported household-size class")
            value = row["households"]
            if not value or not value.isascii() or not value.isdigit() or int(value) <= 0:
                raise HouseholdError("household counts must be positive observed integers")
            counts[category] = int(value)
        if set(counts) != set(CLASSES) or sum(counts.values()) != source.expected_total:
            raise HouseholdError("household source categories/total are incomplete or inconsistent")
        return HouseholdEvidence(source, tuple(counts[c] for c in CLASSES))
    except (UnicodeError, csv.Error, TypeError, KeyError) as exc:
        raise HouseholdError(f"Malformed household observations: {exc}") from exc
