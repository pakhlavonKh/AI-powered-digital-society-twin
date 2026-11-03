"""Immutable fixture relationship artifacts, independent of demographic enrichment.

Every write/load replays the existing fixture gate against caller-supplied inputs
and eligibility contract. Persisted assertions never authorize their own loading.
"""
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from societytwin.common import sha256_file
from societytwin.enrichment.model import ExtensionRecord, ResidentExtension
from societytwin.households.membership import MembershipError, validate_membership

STORE_VERSION = 'fixture-membership-store-1'
FILES = ('membership.json', 'validation.json')


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def _read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise MembershipError('Duplicate JSON key')
            result[key] = value
        return result

    def invalid(value):
        raise MembershipError('Nonfinite JSON value: ' + value)

    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=invalid)


def _plain_path(path):
    """Reject links/junctions in every existing path component before resolution."""
    path = Path(path).absolute()
    if '..' in path.parts:
        raise MembershipError('Unsafe path traversal')
    for component in (path, *path.parents):
        if component.is_symlink() or component.is_junction():
            raise MembershipError('Membership paths cannot contain symlinks or junctions')
    return path.resolve()


class MembershipStore:
    def __init__(self, root):
        self.root = Path(root)

    def _directory(self, artifact_id, input_directories):
        if not isinstance(artifact_id, str) or not re.fullmatch(r'ext-[0-9a-f]{64}', artifact_id):
            raise MembershipError('Invalid membership artifact identity')
        root = _plain_path(self.root)
        for directory in input_directories:
            protected = _plain_path(directory)
            if root.is_relative_to(protected) or protected.is_relative_to(root):
                raise MembershipError('Membership and input storage must be separate')
        # Raw in-memory callers may not have input directories. Still refuse
        # writing within an existing resident/household/enrichment artifact.
        for parent in (root, *root.parents):
            if any((parent / name).exists() for name in
                   ('records.parquet', 'households.parquet', 'attributes.parquet',
                    'build-manifest.json')):
                raise MembershipError('Membership output overlaps an existing input artifact')
        return _plain_path(root / ('membership-' + artifact_id[4:]))

    def load(self, artifact_id, columns, manifest, households, *, reconciliation,
             contract, input_directories=()):
        """Load only against the original exact records/manifests and explicit contract."""
        try:
            directory = self._directory(artifact_id, input_directories)
            if {p.name for p in directory.iterdir()} != {'manifest.json', *FILES}:
                raise MembershipError('Unexpected or missing membership files')
            for name in ('manifest.json', *FILES):
                path = _plain_path(directory / name)
                if not path.is_file():
                    raise MembershipError('Membership artifact must contain regular files')
            envelope = _read(directory / 'manifest.json')
            if (set(envelope) != {'store_version', 'artifact_id', 'files'}
                    or envelope['store_version'] != STORE_VERSION):
                raise MembershipError('Unsupported membership store schema')
            if envelope['artifact_id'] != artifact_id or set(envelope['files']) != set(FILES):
                raise MembershipError('Membership envelope identity/files mismatch')
            for name in FILES:
                if sha256_file(directory / name) != envelope['files'][name]:
                    raise MembershipError('Membership content checksum mismatch')
            payload = _read(directory / 'membership.json')
            if set(payload) != {'records', 'manifest'}:
                raise MembershipError('Malformed membership payload')
            extension = ResidentExtension(tuple(ExtensionRecord.model_validate_json(json.dumps(r), strict=True)
                                               for r in payload['records']), payload['manifest'])
            # JSON arrays map to tuple fields; validate via the JSON contract.
            checked = validate_membership(extension, columns, manifest, households,
                                          reconciliation=reconciliation, contract=contract)
            if extension.manifest['artifact_id'] != artifact_id:
                raise MembershipError('Membership build identity mismatch')
            if checked != _read(directory / 'validation.json'):
                raise MembershipError('Saved membership validation differs from replay')
            return extension
        except (OSError, KeyError, TypeError, ValueError, OverflowError) as exc:
            raise MembershipError(f'Cannot load fixture membership: {exc}') from exc

    def write(self, extension, columns, manifest, households, *, reconciliation,
              contract, input_directories=()):
        checked = validate_membership(extension, columns, manifest, households,
                                      reconciliation=reconciliation, contract=contract)
        artifact_id = extension.manifest['artifact_id']
        directory = self._directory(artifact_id, input_directories)
        options = dict(reconciliation=reconciliation, contract=contract,
                       input_directories=input_directories)
        if directory.exists():
            saved = self.load(artifact_id, columns, manifest, households, **options)
            if saved != extension:
                raise MembershipError('Membership collision; refusing overwrite')
            return directory
        directory.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='.membership-', dir=directory.parent) as temporary:
            stage = Path(temporary) / directory.name
            stage.mkdir()
            payload = {'records': [r.model_dump(mode='json') for r in extension.records],
                       'manifest': extension.manifest}
            (stage / 'membership.json').write_bytes(_json_bytes(payload))
            (stage / 'validation.json').write_bytes(_json_bytes(checked))
            envelope = {'store_version': STORE_VERSION, 'artifact_id': artifact_id,
                        'files': {name: sha256_file(stage / name) for name in FILES}}
            (stage / 'manifest.json').write_bytes(_json_bytes(envelope))
            self._directory(artifact_id, input_directories)
            try:
                stage.rename(directory)
            except FileExistsError:
                if self.load(artifact_id, columns, manifest, households, **options) != extension:
                    raise MembershipError('Concurrent membership collision')
        return directory

    def load_for_population(self, artifact_id, population, households, *, contract):
        """Explicit inspection alongside a GeneratedPopulation or LoadedPopulation.

        No persona attachment. Loaded inputs must be the same persisted snapshot
        that was fingerprinted when the fixture contract was created.
        """
        from societytwin.national.generator import GeneratedPopulation
        from societytwin.national.store import LoadedPopulation
        from societytwin.households.reconciliation import reconcile

        directories = ()
        if isinstance(population, GeneratedPopulation):
            columns = population.columns
        elif isinstance(population, LoadedPopulation):
            columns = population.table.to_pydict()
            directories = (population.directory,)
        else:
            raise MembershipError('Expected generated or loaded population')
        return self.load(artifact_id, columns, population.manifest, households,
                         reconciliation=reconcile(columns, population.manifest, households),
                         contract=contract, input_directories=directories)
