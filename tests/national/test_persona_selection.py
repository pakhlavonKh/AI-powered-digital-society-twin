from dataclasses import replace
from copy import deepcopy
from pathlib import Path

import pyarrow as pa
import pytest
import yaml
from pydantic import ValidationError

from societytwin.common import canonical_hash
from societytwin.enrichment.engine import generate
from societytwin.enrichment.registry import load_registry, EnrichmentError
from societytwin.national.experiments import PersonaPolicy, ExperimentDefinition, example_fare_definition
from societytwin.national.persona_selection import FieldSelection, PersonaResolver, experiment_persona_builder
from societytwin.national.personas import build_persona, matraix_persona
from societytwin.national.store import LoadedPopulation
from societytwin.national.generator import COLUMNS


def selection(**kwargs):
    return FieldSelection(allowlist=['sex', 'degurba_class'], required=['sex'], optional=['degurba_class'], **kwargs)


@pytest.fixture
def core(generated, tmp_path):
    return LoadedPopulation(generated.manifest, pa.table({c: generated.columns[c] for c in COLUMNS}), None, tmp_path)


def test_default_exact(core):
    policy = PersonaPolicy()
    assert policy.model_dump() == {'visible_fields': None}
    for row in core.table.to_pylist()[:20]:
        assert experiment_persona_builder(core, policy)(row['synthetic_id']) == build_persona(row, core.manifest)
    d = ExperimentDefinition(**example_fare_definition('cohort'))
    assert d.model_dump()['persona'] == {'visible_fields': None}


@pytest.mark.parametrize('payload', [
    dict(allowlist=['income']), dict(allowlist=['household_type']),
    dict(allowlist=['sex'], required=['age']),
    dict(allowlist=['sex'], required=['sex'], optional=['sex']),
    dict(allowlist=['sex', 'age'], required=['sex', 'age'], max_attributes=1),
    dict(allowlist=[], schema_version='future'), dict(allowlist=[], sidecar_id='ext-bad')])
def test_policy_rejection(payload):
    with pytest.raises(ValidationError):
        FieldSelection(**payload)


def test_missing_and_required(core):
    p = PersonaResolver(core, selection()).build(core.table['synthetic_id'][0].as_py())
    assert 'degurba_class' not in p['model_visible']
    assert p['field_selection']['resolution'][-1]['status'] == 'unavailable'
    with pytest.raises(EnrichmentError, match='unavailable'):
        PersonaResolver(core, selection(missingness='error')).build(p['synthetic_id'])
    s = FieldSelection(allowlist=['degurba_class'], required=['degurba_class'])
    with pytest.raises(EnrichmentError):
        PersonaResolver(core, s).build(p['synthetic_id'])
    with pytest.raises(ValidationError):
        PersonaPolicy(visible_fields=[], field_selection=s)


def test_duplicate_core(core):
    duplicate = replace(core, table=pa.concat_tables([core.table, core.table.slice(0, 1)]))
    with pytest.raises(EnrichmentError, match='duplicate'):
        PersonaResolver(duplicate, selection())


def test_unavailable_and_outside_universe(core, tmp_path):
    import pyarrow.compute as pc
    from societytwin.enrichment.registry import ExtensionRegistry
    core = replace(core, table=core.table.filter(pc.equal(core.table['province_code'], '06')))
    payload = load_registry().activated().model_dump(mode='json')
    attribute = payload['attributes']['degurba_class']
    attribute['source']['path'] = 'absent.csv'
    attribute['missing_source'] = 'unavailable'
    attribute['min_age'] = 18
    extension = generate(core, ExtensionRegistry.model_validate(payload), root=tmp_path)
    resolver = PersonaResolver(core, selection(), extension)
    statuses = set()
    for row in core.table.to_pylist():
        p = resolver.build(row['synthetic_id'])
        statuses.add(p['field_selection']['resolution'][-1]['status'])
        assert 'degurba_class' not in p['model_visible']
    assert statuses == {'unsupported', 'outside_universe'}


def test_assigned_sidecar_and_integrity_without_local_data(core, tmp_path):
    from collections import Counter
    from societytwin.common import sha256_bytes
    from societytwin.enrichment.registry import ExtensionRegistry
    rows = [dict(r, population_weight=1.) for r in core.table.to_pylist() if r['province_code'] == '06']
    core = replace(core, table=pa.Table.from_pylist(rows))
    counts = Counter(r['sex'] for r in rows)
    raw = 'province_code,year,sex,category,count,value_status\n'
    for sex, count in counts.items():
        for category, n in [('dense_urban', count), ('intermediate_urban', 0), ('rural', 0)]:
            raw += f'06,2025,{sex},{category},{n},OBSERVED\n'
    (tmp_path / 'source.csv').write_bytes(raw.encode())
    payload = load_registry().activated().model_dump(mode='json')
    payload['attributes']['degurba_class']['source'].update(path='source.csv', sha256=sha256_bytes(raw.encode()))
    extension = generate(core, ExtensionRegistry.model_validate(payload), root=tmp_path)
    resolver = PersonaResolver(core, selection(), extension)
    p = resolver.build(rows[0]['synthetic_id'])
    doc = matraix_persona(p)
    assert 'dense urban' in doc['dimensions']['dst_degurba_class']
    assert 'assumed' in doc['dimensions']['dst_degurba_class']
    assert doc['metadata']['field_selection']['resolution'][-1]['evidence']['evidence_class'] == 'D'
    for records in (extension.records[:-1], extension.records + extension.records[:1]):
        with pytest.raises(EnrichmentError):
            PersonaResolver(core, selection(), replace(extension, records=records))
    bad = deepcopy(extension)
    bad.manifest['registry']['registry_version'] = 'changed'
    with pytest.raises(EnrichmentError):
        PersonaResolver(core, selection(), bad)


def test_selected_experiment_plan_and_run(national_client, population_id):
    c = national_client
    cid = c.post('/api/v2/cohorts', json={'name': 'selected adults', 'population_id': population_id,
                                        'filters': {'adult_only': True}}).json()['cohort_id']
    definition = example_fare_definition(cid)
    definition['persona'] = {'field_selection': selection().model_dump()}
    exp = c.post('/api/v2/experiments', json=definition).json()
    plan = c.post(f"/api/v2/experiments/{exp['experiment_id']}/plan").json()
    assert plan['executable']
    assert plan['visible_fields_policy'] == ['sex', 'degurba_class']
    assert all(p['model_visible_fields'] == ['sex'] for p in plan['personas'])
    run = c.post(f"/api/v2/experiments/{exp['experiment_id']}/runs", json={
        'plan_hash': plan['plan_hash'], 'idempotency_key': 'selected-policy-01', 'confirm': True}).json()['run']
    assert run['state'] == 'completed' and run['provider_calls'] == 0


@pytest.mark.parametrize('size', [1000, 10000])
def test_real_sidecar_exports(size, tmp_path):
    """Read existing disposable real-data bundles; create fresh sidecars and exports."""
    import json
    from societytwin.national.store import PopulationStore
    from societytwin.enrichment.store import ExtensionStore
    from societytwin.national.cohorts import draw, CohortSampleRequest
    matrix_path = Path('data/results/unified-build/matrix-results.json')
    if not matrix_path.exists():
        pytest.skip('Local disposable real-data bundles unavailable')
    case = next(c for c in json.loads(matrix_path.read_text()) if c['size'] == size and c['seed'] == 42 and c['mode'] == 'degurba_size')
    bundle = matrix_path.parent / 'bundles' / case['build_id']
    core = PopulationStore(bundle / 'residents').load(case['artifacts']['residents']['id'])
    old = ExtensionStore(bundle / 'enrichments').load(case['artifacts']['enrichments']['id'], core)
    from societytwin.enrichment.registry import ExtensionRegistry
    registry = ExtensionRegistry.model_validate(old.manifest['registry'])
    extension = generate(core, registry)
    output = tmp_path / 'extensions'
    ExtensionStore(output).write(extension, core)
    s = selection(sidecar_root=str(output), sidecar_id=extension.manifest['artifact_id'])
    resolver = PersonaResolver(core, s)
    rows = core.table.to_pylist()
    ids = [r['synthetic_id'] for r in rows]
    weights = [r['population_weight'] for r in rows]
    before = draw(ids, weights, CohortSampleRequest(size=20, seed=7))
    docs = []
    for member in before['members']:
        sid = member['synthetic_id']
        p = resolver.build(sid)
        assert p == resolver.build(sid)
        doc = matraix_persona(p)
        assert doc['persona_id'] == sid
        assert 'assumed' in doc['dimensions']['dst_degurba_class']
        assert yaml.safe_load(yaml.safe_dump(doc)) == doc
        docs.append(doc)
    assert before == draw(ids, weights, CohortSampleRequest(size=20, seed=7))
    assert len(docs) == 20
    bad = deepcopy(extension)
    bad.manifest['core']['population_id'] = 'wrong'
    with pytest.raises(EnrichmentError, match='binding'):
        PersonaResolver(core, s, bad)
    bad = deepcopy(extension)
    bad.manifest['schema_version'] = 'future'
    with pytest.raises(EnrichmentError, match='version'):
        PersonaResolver(core, s, bad)
