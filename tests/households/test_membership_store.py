"""Invented unit fixtures only; no production sources or new dependencies."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pyarrow as pa
import pytest

from societytwin.common import sha256_file
from societytwin.households.membership import MembershipError
from societytwin.households.membership_store import MembershipStore
from societytwin.households.reconciliation import reconcile
from societytwin.national.generator import GeneratedPopulation
from societytwin.national.store import LoadedPopulation
from tests.households.test_membership import case, bind, link  # noqa: F401


def options(case):
    return dict(reconciliation=reconcile(*case), contract=bind(case))


def persist(case, tmp_path):
    extension = link(case)
    store = MembershipStore(tmp_path/'membership')
    path = store.write(extension, *case, **options(case))
    return extension, store, path


def rewrite(path, mutate):
    """Update transport checksums too, forcing semantic/replay validation."""
    document = json.loads((path/'membership.json').read_text(encoding='utf-8'))
    mutate(document)
    (path/'membership.json').write_text(json.dumps(document), encoding='utf-8')
    envelope = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    envelope['files']['membership.json'] = sha256_file(path/'membership.json')
    (path/'manifest.json').write_text(json.dumps(envelope), encoding='utf-8')


def test_round_trip_immutable_deterministic_and_input_integrity(case, tmp_path):
    before = deepcopy(case)
    extension, store, path = persist(case, tmp_path)
    snapshot = {p.name: p.read_bytes() for p in path.iterdir()}
    loaded = store.load(extension.manifest['artifact_id'], *case, **options(case))
    assert loaded == extension
    assert loaded.manifest is not extension.manifest
    assert store.write(extension, *case, **options(case)) == path
    assert snapshot == {p.name: p.read_bytes() for p in path.iterdir()}
    other = MembershipStore(tmp_path/'other').write(extension, *case, **options(case))
    assert snapshot == {p.name: p.read_bytes() for p in other.iterdir()}
    assert case == before
    for field in ('core', 'households', 'input_fingerprints', 'provenance_profiles',
                  'config', 'purpose', 'limitations', 'content_hash'):
        assert loaded.manifest[field] == extension.manifest[field]


@pytest.mark.parametrize('kind', ['duplicate', 'missing_id', 'blank_id', 'foreign_person',
                                 'foreign_household', 'schema', 'purpose', 'profile', 'seed'])
def test_semantic_tampering_even_with_updated_file_hash(case, tmp_path, kind):
    extension, store, path = persist(case, tmp_path)

    def mutate(document):
        records = document['records']
        if kind == 'duplicate':
            records[0] = records[1]
        elif kind == 'missing_id':
            del records[0]['synthetic_id']
        elif kind in ('blank_id', 'foreign_person'):
            records[0]['synthetic_id'] = '' if kind == 'blank_id' else 'foreign'
        elif kind == 'foreign_household':
            records[0]['attributes'][0]['value'] = 'foreign'
        elif kind == 'schema':
            document['manifest']['schema_version'] = 'future'
        elif kind == 'profile':
            records[0]['attributes'][0]['provenance_profile'] = 'foreign'
        elif kind == 'seed':
            document['manifest']['config']['seed'] = 900
        else:
            document['manifest']['purpose'] = 'production'

    rewrite(path, mutate)
    with pytest.raises(MembershipError):
        store.load(extension.manifest['artifact_id'], *case, **options(case))


@pytest.mark.parametrize('file', ['membership.json', 'validation.json', 'manifest.json'])
def test_corrupted_json_or_checksum(case, tmp_path, file):
    extension, store, path = persist(case, tmp_path)
    (path/file).write_bytes(b'{broken')
    with pytest.raises(MembershipError):
        store.load(extension.manifest['artifact_id'], *case, **options(case))


@pytest.mark.parametrize('mutation', [
    lambda m: m.update(store_version='future'),
    lambda m: m.update(artifact_id='ext-'+'0'*64),
    lambda m: m.update(files={'../../escape': '0'*64}),
    lambda m: m.update(unapproved=True),
])
def test_envelope_validation(case, tmp_path, mutation):
    extension, store, path = persist(case, tmp_path)
    manifest = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    mutation(manifest)
    (path/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(MembershipError):
        store.load(extension.manifest['artifact_id'], *case, **options(case))


@pytest.mark.parametrize('raw', ['{"store_version":1,"store_version":2}', '{"files":NaN}', '[]', 'null'])
def test_malformed_envelope(case, tmp_path, raw):
    extension, store, path = persist(case, tmp_path)
    (path/'manifest.json').write_text(raw, encoding='utf-8')
    with pytest.raises(MembershipError):
        store.load(extension.manifest['artifact_id'], *case, **options(case))


@pytest.mark.parametrize('side', ['population', 'households', 'weights', 'source'])
def test_cross_build_or_changed_inputs(case, tmp_path, side):
    extension, store, _ = persist(case, tmp_path)
    original = options(case)
    if side == 'population':
        case[1]['population_id'] = 'different-build'
    elif side == 'households':
        case[2].manifest['household_population_id'] = 'different-households'
    elif side == 'weights':
        case[0]['population_weight'][0] = 2.
    else:
        case[1]['source_versions']['sources'][0]['source_id'] = 'changed'
    with pytest.raises(MembershipError):
        store.load(extension.manifest['artifact_id'], *case, **original)


@pytest.mark.parametrize('artifact_id', ['../escape', 'ext-../escape', '', None, 'ext-'+'g'*64])
def test_unsafe_artifact_ids(case, tmp_path, artifact_id):
    with pytest.raises(MembershipError):
        MembershipStore(tmp_path).load(artifact_id, *case, **options(case))


def test_paths_protect_inputs_and_reject_traversal(case, tmp_path):
    extension = link(case)
    protected = tmp_path/'residents'
    for root in (protected, protected/'memberships', tmp_path):
        with pytest.raises(MembershipError, match='separate'):
            MembershipStore(root).write(extension, *case, **options(case), input_directories=(protected,))
    with pytest.raises(MembershipError, match='traversal'):
        MembershipStore(tmp_path/'..'/'escape').write(extension, *case, **options(case))
    protected.mkdir()
    (protected/'records.parquet').write_bytes(b'input sentinel')
    with pytest.raises(MembershipError, match='overlaps'):
        MembershipStore(protected/'memberships').write(extension, *case, **options(case))
    assert (protected/'records.parquet').read_bytes() == b'input sentinel'


@pytest.mark.parametrize('kind', ['root', 'ancestor', 'artifact', 'file'])
@pytest.mark.parametrize('detector', ['is_junction', 'is_symlink'])
def test_reparse_paths_are_rejected_without_windows_link_privileges(case, tmp_path, monkeypatch, kind, detector):
    extension, store, path = persist(case, tmp_path)
    target = {'root': store.root, 'ancestor': tmp_path, 'artifact': path,
              'file': path/'membership.json'}[kind]
    original = getattr(Path, detector)
    monkeypatch.setattr(Path, detector, lambda p: p == target or original(p))
    with pytest.raises(MembershipError, match='junction'):
        store.load(extension.manifest['artifact_id'], *case, **options(case))
    if kind != 'file':
        with pytest.raises(MembershipError, match='junction'):
            store.write(extension, *case, **options(case))


def test_unexpected_files_and_saved_validation(case, tmp_path):
    extension, store, path = persist(case, tmp_path)
    (path/'unexpected.txt').write_text('user file', encoding='utf-8')
    with pytest.raises(MembershipError):
        store.write(extension, *case, **options(case))
    assert (path/'unexpected.txt').read_text(encoding='utf-8') == 'user file'


def test_explicit_population_inspection(case, tmp_path):
    extension, store, _ = persist(case, tmp_path)
    population = GeneratedPopulation(case[0], case[1], case[1]['profiles'])
    assert store.load_for_population(extension.manifest['artifact_id'], population, case[2],
                                     contract=bind(case)) == extension
    loaded = LoadedPopulation(case[1], pa.table(case[0]), None, tmp_path/'original-residents')
    assert store.load_for_population(extension.manifest['artifact_id'], loaded, case[2],
                                     contract=bind(case)) == extension
    with pytest.raises(MembershipError):
        store.load_for_population(extension.manifest['artifact_id'], object(), case[2], contract=bind(case))


def test_invalid_sidecar_is_not_written(case, tmp_path):
    extension = link(case)
    bad = replace(extension, records=extension.records + extension.records[:1])
    with pytest.raises(MembershipError):
        MembershipStore(tmp_path/'out').write(bad, *case, **options(case))
    assert not (tmp_path/'out').exists()


def test_fixture_relationship_never_attached_to_persona(case, tmp_path):
    from societytwin.enrichment.registry import EnrichmentError
    from societytwin.national.persona_selection import FieldSelection, PersonaResolver
    from societytwin.national.personas import matraix_persona

    columns, manifest, households = case
    columns['province_name'] = ['Ankara'] * 5
    columns['provenance_profile'] = ['fixture'] * 5
    manifest.update(generator_version='invented-unit-fixture', seed=42)
    extension, store, _ = persist(case, tmp_path)
    core = LoadedPopulation(manifest, pa.table(columns), None, tmp_path/'residents')
    loaded = store.load_for_population(extension.manifest['artifact_id'], core, households, contract=bind(case))
    s = FieldSelection(allowlist=['sex'], required=['sex'])
    resolver = PersonaResolver(core, s)
    p = resolver.build('r1')
    assert p['model_visible'] == {'sex': 'Female'}
    assert 'household_id' not in {a['field'] for a in p['attributes']}
    assert matraix_persona(p)['dimensions'] == {'dst_sex': 'Female'}
    with pytest.raises(EnrichmentError, match='Fixture relationships'):
        PersonaResolver(core, s, loaded)


def test_saved_validation_requires_semantic_match(case, tmp_path):
    extension, store, path = persist(case, tmp_path)
    (path/'validation.json').write_text('{"valid":true}', encoding='utf-8')
    envelope = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    envelope['files']['validation.json'] = sha256_file(path/'validation.json')
    (path/'manifest.json').write_text(json.dumps(envelope), encoding='utf-8')
    with pytest.raises(MembershipError, match='validation differs'):
        store.load(extension.manifest['artifact_id'], *case, **options(case))


def test_original_persisted_population_bytes_and_weights_unchanged(case, tmp_path):
    from societytwin.common import canonical_hash
    from societytwin.national.generator import COLUMNS
    from societytwin.national.store import PopulationStore

    # Complete the intentionally invented fixture's storage schema. No official
    # record is transformed into a fixture or linked in this test.
    columns = {name: case[0].get(name, [None] * 5) for name in COLUMNS}
    columns.update(province_name=['Ankara'] * 5, provenance_profile=['fixture'] * 5)
    manifest = {**case[1], 'population_id': 'pop-fixture', 'content_sha256': canonical_hash(columns)}
    population = GeneratedPopulation(columns, manifest, manifest['profiles'])
    residents = PopulationStore(tmp_path/'residents')
    saved, _ = residents.write(population, {})
    core = residents.load(saved['population_id'])
    source_snapshot = {p.name: p.read_bytes() for p in core.directory.iterdir()}
    persisted_case = (core.table.to_pydict(), core.manifest, case[2])
    contract = bind(persisted_case)
    extension = link(persisted_case, contract=contract)
    store = MembershipStore(tmp_path/'relationships')
    store.write(extension, *persisted_case, reconciliation=reconcile(*persisted_case),
                contract=contract, input_directories=(core.directory,))
    assert store.load_for_population(extension.manifest['artifact_id'], core, case[2], contract=contract) == extension
    assert source_snapshot == {p.name: p.read_bytes() for p in core.directory.iterdir()}
    assert core.table.to_pydict() == columns
    assert population.manifest == manifest
