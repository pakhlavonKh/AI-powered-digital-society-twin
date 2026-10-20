"""Immutable, versioned optional sidecars, separate from resident Parquet files."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from societytwin.common import sha256_file
from societytwin.enrichment import SCHEMA_VERSION
from societytwin.enrichment.engine import validate
from societytwin.enrichment.model import ResidentExtension, ExtensionRecord
from societytwin.enrichment.registry import EnrichmentError

VALUE=pa.struct([pa.field('attribute',pa.string(),nullable=False),pa.field('value',pa.string()),
                 pa.field('status',pa.string(),nullable=False),pa.field('provenance_profile',pa.string(),nullable=False)])
SCHEMA=pa.schema([pa.field('synthetic_id',pa.string(),nullable=False),pa.field('attributes',pa.list_(pa.field('element',VALUE)),nullable=False)],
                 metadata={b'schema_version':SCHEMA_VERSION.encode()})


class ExtensionStore:
    def __init__(self,root):self.root=Path(root)

    def _separate(self,core):
        root=self.root.resolve();resident=core.directory.resolve()
        if root.is_relative_to(resident) or resident.is_relative_to(root):
            raise EnrichmentError('resident and sidecar storage roots must be separate')

    def load(self,artifact_id,core):
        self._separate(core)
        if not artifact_id.startswith('ext-') or len(artifact_id)!=68 or any(c not in '0123456789abcdef' for c in artifact_id[4:]):
            raise EnrichmentError('invalid sidecar identity')
        directory=self.root/artifact_id
        m=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        if m['artifact_id']!=artifact_id or sha256_file(directory/'attributes.parquet')!=m['parquet_sha256']:
            raise EnrichmentError('sidecar checksum/identity mismatch')
        table=pq.read_table(directory/'attributes.parquet')
        if not table.schema.equals(SCHEMA,check_metadata=True):raise EnrichmentError('sidecar schema mismatch')
        extension=ResidentExtension(tuple(ExtensionRecord.model_validate(r) for r in table.to_pylist()),m)
        validate(extension,core)
        return extension

    def write(self,extension,core):
        self._separate(core)
        report=validate(extension,core)
        destination=self.root/extension.manifest['artifact_id']
        if destination.exists():
            existing=self.load(destination.name,core)
            if existing.records!=extension.records:raise EnrichmentError('sidecar collision')
            return destination
        self.root.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(prefix='.extension-',dir=self.root) as temporary:
            stage=Path(temporary)/'artifact';stage.mkdir()
            table=pa.Table.from_pylist([r.model_dump(mode='json') for r in extension.records],schema=SCHEMA)
            pq.write_table(table,stage/'attributes.parquet',compression='zstd')
            manifest={**extension.manifest,'parquet_sha256':sha256_file(stage/'attributes.parquet')}
            for name,value in [('manifest',manifest),('validation',report)]:
                (stage/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
            stage.rename(destination)
        return destination
