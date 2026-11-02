from copy import deepcopy
from dataclasses import replace
import json

import pytest

from societytwin.households.linkage_evidence import LinkageEvidence, load_linkage_evidence
from societytwin.households.linkage_readiness import CAPABILITIES, assess_linkage_readiness
from societytwin.households.model import GeneratedHouseholds, HouseholdRecord
from societytwin.households.reconciliation import reconcile
from tests.households.test_linkage_evidence import local_catalog  # noqa: F401


@pytest.fixture
def inputs(local_catalog):
    evidence, root = local_catalog
    columns = {'synthetic_id': [f'fixture-{i}' for i in range(16)],
               'population_weight': [1.] * 16, 'design_weight': [1.] * 16,
               'province_code': ['06'] * 16, 'reference_year': [2025] * 16}
    manifest = {'population_id': 'invented-people', 'reference_year': 2025,
                'scope': {'provinces_with_records': ['06']}, 'represented_population': 16,
                'source_versions': {'sources': [{'source_id': 'invented'}]},
                'profiles': {'invented': {'fields': {'province_code': {'source_year': 2025}}}},
                'population_universe': {'definition': 'ADNKS_private_household_residents', 'source_ref': 'invented'}}
    records = tuple(HouseholdRecord(f'fixture-hh-{n}', '06', 2025, str(n), n, n, n, False, float(count))
                    for n, count in ((1, 1), (2, 3), (3, 3)))
    households = GeneratedHouseholds(records, {'household_population_id': 'invented-households',
        'weight_unit': 'household', 'represented_households': 7,
        'source': {'province_code': '06', 'reference_year': 2025, 'unit': 'household',
                   'universe': 'ADNKS_private_households', 'source_version': 'invented'}})
    return columns, manifest, households, evidence, root


def assess(inputs, **kwargs):
    columns, manifest, hh, evidence, root = inputs
    return assess_linkage_readiness(columns, manifest, hh, evidence=evidence,
        reconciliation=reconcile(columns, manifest, hh), source_root=root, **kwargs)


def codes(report, name):
    return {r['code'] for r in report['capabilities'][name]['reasons']}


def test_distinct_aggregate_and_production_gates(inputs):
    report = assess(inputs)
    assert report['capabilities'][CAPABILITIES[0]]['status'] == 'ready'
    assert all(report['capabilities'][name]['status'] == 'blocked' for name in CAPABILITIES[1:])
    assert 'private_population_unknown' in codes(report, CAPABILITIES[1])
    assert 'weighted_representatives_not_instances' in codes(report, CAPABILITIES[2])
    assert 'relationship_evidence_missing' in codes(report, CAPABILITIES[3])
    assert report['production_assignment_enabled'] is False
    assert report['representation']['unit_weights_establish_instances'] is False


def test_unit_weights_never_establish_instances(inputs):
    columns, manifest, hh, evidence, root = inputs
    records = tuple(replace(r, household_id=f'unit-{i}-{j}', household_weight=1.)
                    for i, r in enumerate(hh.records) for j in range(int(r.household_weight)))
    hh = replace(hh, records=records)
    report = assess((columns, manifest, hh, evidence, root))
    assert report['reconciliation_status'] == 'compatible'
    assert report['representation']['residents'] == 'unit_weights_only'
    assert report['representation']['households'] == 'unit_weights_only'
    assert 'instance_semantics_unverified' in codes(report, CAPABILITIES[2])
    assert report['capabilities'][CAPABILITIES[2]]['status'] == 'blocked'


def test_missing_sources_and_missing_catalog(inputs):
    columns, manifest, hh, evidence, root = inputs
    report = assess_linkage_readiness(columns, manifest, hh, evidence=evidence,
        reconciliation=reconcile(columns, manifest, hh))
    assert report['capabilities'][CAPABILITIES[0]]['status'] == 'conditionally_ready'
    empty = evidence.model_copy(update={'composition': ()})
    report = assess((columns, manifest, hh, empty, root))
    assert 'composition_evidence_missing' in codes(report, CAPABILITIES[0])
    assert report['capabilities'][CAPABILITIES[0]]['status'] == 'blocked'


@pytest.mark.parametrize('field,value', [('geography', '34'), ('observation_year', 2024), ('reference_year', 2024)])
def test_incompatible_source_scope(inputs, field, value):
    columns, manifest, hh, evidence, root = inputs
    payload = evidence.model_dump(mode='json')
    payload['sources']['ankara_composition_2025'][field] = value
    report = assess((columns, manifest, hh, LinkageEvidence.model_validate(payload), root))
    assert 'source_scope_mismatch' in codes(report, CAPABILITIES[0])
    assert report['capabilities'][CAPABILITIES[0]]['status'] == 'blocked'


def test_unknown_institutional_population_not_inferred(inputs):
    inputs[1]['population_universe'] = {'definition': 'ADNKS_residents', 'source_ref': 'invented'}
    report = assess(inputs)
    assert 'institutional_population_unknown' in codes(report, CAPABILITIES[1])
    assert report['coverage']['institutional_persons']['value'] is None
    assert report['totals']['private_household_persons'] is None


def test_open_tail_blocks_assignment(inputs):
    columns, manifest, hh, _, root = inputs
    evidence = load_linkage_evidence()
    hh = replace(hh, records=(HouseholdRecord('tail', '06', 2025, '10+', None, 10, None, True, 7.),))
    report = assess((columns, manifest, hh, evidence, root))
    assert report['totals']['member_lower_bound'] == 70
    assert report['totals']['member_exact'] is None
    assert 'open_tail_upper_unknown' in codes(report, CAPABILITIES[1])
    assert 'open_tail_instance_sizes_unknown' in codes(report, CAPABILITIES[2])
    assert report['capabilities'][CAPABILITIES[1]]['status'] == 'blocked'


def test_forged_reconciliation_cannot_authorize(inputs):
    columns, manifest, hh, evidence, root = inputs
    diagnostic = reconcile(columns, manifest, hh)
    diagnostic['totals']['households'] = 999
    report = assess_linkage_readiness(columns, manifest, hh, evidence=evidence,
        reconciliation=diagnostic, source_root=root)
    assert all('reconciliation_binding_mismatch' in codes(report, name) for name in CAPABILITIES)


def test_wrong_units(inputs):
    inputs[2].manifest['weight_unit'] = 'person'
    report = assess(inputs)
    assert all('statistical_units_unverified' in codes(report, name) for name in CAPABILITIES)


def test_checksum_failure_blocks_aggregate_modeling(inputs):
    evidence, root = inputs[3:]
    path = root/evidence.sources['ankara_size_2025'].path
    path.write_bytes(b'tampered')
    assert 'source_integrity_failure' in codes(assess(inputs), CAPABILITIES[0])


def test_deterministic_detached_and_no_persona_mutation(inputs):
    before = deepcopy(inputs[:4])
    a, b = assess(inputs), assess(inputs)
    assert json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)
    assert inputs[:4] == before
    assert a['inputs']['input_fingerprints']['resident_input_sha256']
    assert a['inputs']['population_id'] == inputs[1]['population_id']
    assert a['sources']['ankara_size_2025']['expected_sha256'] == inputs[3].sources['ankara_size_2025'].sha256
    a['source_declarations']['ankara_size_2025']['sha256'] = 'changed'
    a['coverage']['private_persons']['value'] = 1
    assert inputs[:4] == before
    assert 'household_id' not in inputs[0]
    assert 'model_visible' not in inputs[1]


def test_local_unavailable_and_precision_uncertainty(inputs, tmp_path):
    columns, manifest, hh, evidence, _ = inputs
    report = assess((columns, manifest, hh, evidence, tmp_path/'absent'))
    assert report['capabilities'][CAPABILITIES[0]]['status'] == 'conditionally_ready'
    payload = evidence.model_dump(mode='json')
    payload['sources']['ankara_size_2025']['precision']['kind'] = 'unknown'
    report = assess((columns, manifest, hh, LinkageEvidence.model_validate(payload), tmp_path/'absent'))
    assert 'source_precision_uncertain' in codes(report, CAPABILITIES[0])


def test_complete_aggregate_evidence_never_enables_allocator(inputs):
    from societytwin.common import sha256_file
    columns, manifest, hh, evidence, root = inputs
    payload = evidence.model_dump(mode='json')
    path = root/'private.csv'
    path.write_text('province_code,year,indicator,value,unit\n06,2025,private_persons,16,person\n', encoding='utf-8')
    source = {**payload['sources']['ankara_composition_2025'], 'source_id': 'private', 'path': 'private.csv',
              'sha256': sha256_file(path), 'unit': 'person', 'universe': 'ADNKS_private_household_residents'}
    payload['sources']['private'] = source
    payload['coverage']['private_persons'].update(status='observed', source_id='private',
                                                 source_indicator='private_persons', value=16)
    report = assess((columns, manifest, hh, LinkageEvidence.model_validate(payload), root))
    assert report['capabilities'][CAPABILITIES[1]]['status'] == 'conditionally_ready'
    assert report['production_assignment_enabled'] is False
    assert report['capabilities'][CAPABILITIES[2]]['status'] == 'blocked'
    # A hash-bound CSV carrying a different declared person count is still rejected.
    payload['coverage']['private_persons']['value'] = 15
    report = assess((columns, manifest, hh, LinkageEvidence.model_validate(payload), root))
    assert 'source_integrity_failure' in codes(report, CAPABILITIES[1])


def test_modeled_composition_is_disclosed(inputs):
    columns, manifest, hh, evidence, root = inputs
    payload = evidence.model_dump(mode='json')
    payload['composition'][0].update(status='modeled', assumption='Invented modeled cell assumption')
    report = assess((columns, manifest, hh, LinkageEvidence.model_validate(payload), root))
    assert report['capabilities'][CAPABILITIES[0]]['status'] == 'conditionally_ready'
    assert 'Invented modeled cell assumption' in report['assumptions']


def test_persona_visibility_is_identical_before_and_after(inputs):
    from societytwin.national.personas import build_persona, matraix_persona
    row = {key: values[0] for key, values in inputs[0].items()}
    row.update(age=32, province_name='Ankara', provenance_profile='invented')
    manifest = {**inputs[1], 'generator_version': 'invented', 'seed': 42}
    before = build_persona(row, manifest)
    before_projection = matraix_persona(before)
    assess(inputs)
    assert build_persona(row, manifest) == before
    assert matraix_persona(build_persona(row, manifest)) == before_projection
    assert 'household_id' not in before['model_visible']
