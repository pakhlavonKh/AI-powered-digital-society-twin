"""Immutable versioned household artifacts; never read/write resident Parquet."""
import json
import re
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from societytwin.common import sha256_file
from societytwin.households import SCHEMA_VERSION
from societytwin.households.model import GeneratedHouseholds, HouseholdRecord
from societytwin.households.registry import HouseholdError
from societytwin.households.validation import validate

SCHEMA = pa.schema([
    pa.field("household_id",pa.string(),nullable=False),
    pa.field("province_code",pa.string(),nullable=False),
    pa.field("reference_year",pa.int16(),nullable=False),
    pa.field("household_size_class",pa.string(),nullable=False),
    pa.field("household_size",pa.int16()),
    pa.field("household_size_lower",pa.int16(),nullable=False),
    pa.field("household_size_upper",pa.int16()),
    pa.field("household_size_open_ended",pa.bool_(),nullable=False),
    pa.field("household_weight",pa.float64(),nullable=False),
], metadata={b"societytwin.schema_version":SCHEMA_VERSION.encode(),b"societytwin.unit":b"household"})


def _json(path, payload):
    path.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")


class HouseholdStore:
    schema = SCHEMA
    record_type = HouseholdRecord
    check = staticmethod(validate)
    id_pattern = r"hh-06-2025-n[0-9]+-s[0-9]+-[0-9a-f]{16}"

    def __init__(self, root: Path):
        self.root = Path(root)

    def _directory(self, build_id):
        if not re.fullmatch(self.id_pattern,build_id):
            raise HouseholdError("invalid household build ID")
        directory = self.root / build_id
        if directory.is_symlink():
            raise HouseholdError("household artifact directory cannot be a symlink")
        return directory

    def load(self, build_id: str) -> GeneratedHouseholds:
        directory = self._directory(build_id)
        try:
            manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
            if manifest["household_population_id"] != build_id:
                raise HouseholdError("household build ID mismatch")
            for name in ["households.parquet","validation.json"]:
                path = directory/name
                if path.is_symlink() or sha256_file(path) != manifest["files"][name]["sha256"]:
                    raise HouseholdError(f"household artifact checksum mismatch: {name}")
            table = pq.read_table(directory/"households.parquet")
            if not table.schema.equals(self.schema,check_metadata=True):
                raise HouseholdError("unsupported household Parquet schema")
            population = GeneratedHouseholds(tuple(self.record_type(**r) for r in table.to_pylist()),manifest)
            checked = self.check(population)
            saved = json.loads((directory/"validation.json").read_text(encoding="utf-8"))
            if checked != saved:
                raise HouseholdError("saved household validation differs from recomputed results")
            return population
        except (OSError,KeyError,TypeError,ValueError) as exc:
            raise HouseholdError(f"Cannot load household population {build_id}: {exc}") from exc

    def write(self, population: GeneratedHouseholds) -> Path:
        checked = self.check(population)
        build_id = population.manifest["household_population_id"]
        directory = self._directory(build_id)
        if directory.exists():
            saved = self.load(build_id)
            if (saved.manifest["identity_sha256"],saved.manifest["content_sha256"]) != (
                    population.manifest["identity_sha256"],population.manifest["content_sha256"]):
                raise HouseholdError("existing household artifact differs; refusing overwrite")
            return directory
        self.root.mkdir(parents=True,exist_ok=True)
        # Stage inside this output root; publishing never rewrites an existing build.
        with TemporaryDirectory(prefix=".household-staging-",dir=self.root) as temporary:
            stage = Path(temporary)/build_id
            stage.mkdir()
            pq.write_table(pa.Table.from_pylist([asdict(r) for r in population.records],schema=self.schema),stage/"households.parquet")
            _json(stage/"validation.json",checked)
            manifest = population.manifest | {"files":{name:{"sha256":sha256_file(stage/name)}
                         for name in ["households.parquet","validation.json"]}}
            _json(stage/"manifest.json",manifest)
            try:
                stage.rename(directory)
            except FileExistsError:
                saved = self.load(build_id)
                if saved.manifest["content_sha256"] != population.manifest["content_sha256"]:
                    raise HouseholdError("concurrent household build collision")
        return directory
