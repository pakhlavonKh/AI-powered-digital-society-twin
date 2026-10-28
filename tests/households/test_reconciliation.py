"""Invented population counts only; no source downloads or generated artifacts."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from societytwin.households.model import GeneratedHouseholds, HouseholdRecord
from societytwin.households.reconciliation import reconcile


@pytest.fixture
def inputs():
    columns = {'population_weight': [4.0, 6.0], 'province_code': ['06', '06'],
               'reference_year': [2025, 2025]}
    manifest = {'population_id': 'synthetic-persons', 'reference_year': 2025,
                'scope': {'provinces_with_records': ['06']}, 'represented_population': 10,
                'source_versions': {'sources': [{'source_id': 'invented'}]},
                'profiles': {'invented': {'fields': {'province_code': {'source_year': 2025}}}},
                'population_universe': {'definition': 'ADNKS_private_household_residents',
                                        'source_ref': 'invented-private-definition'}}
    records = (HouseholdRecord('invented-hh', '06', 2025, '2', 2, 2, 2, False, 5.0),)
    hm = {'household_population_id': 'synthetic-households', 'weight_unit': 'household',
          'represented_households': 5,
          'source': {'province_code': '06', 'reference_year': 2025, 'unit': 'household',
                     'universe': 'ADNKS_private_households', 'source_version': 'invented'}}
    return columns, manifest, GeneratedHouseholds(records, hm)


def finding(result, name):
    return next(f for f in result['findings'] if f['check'] == name)['status']


def test_closed_sizes_and_different_statistical_units(inputs):
    result = reconcile(*inputs)
    assert result['status'] == 'compatible'
    assert result['totals'] == {'resident_persons': 10, 'private_household_persons': 10,
                                'households': 5, 'member_lower_bound': 10,
                                'member_exact': 10, 'open_ended_records': 0}
    assert finding(result, 'statistical_units') == 'compatible'


@pytest.mark.parametrize('persons,expected', [(50, 'not_assessable'), (60, 'not_assessable'), (49, 'incompatible')])
def test_open_tail_lower_bound(inputs, persons, expected):
    columns, manifest, hh = inputs
    columns['population_weight'] = [persons / 2, persons / 2]
    manifest['represented_population'] = persons
    hh = replace(hh, records=(replace(hh.records[0], household_size_class='10+', household_size=None,
                                     household_size_lower=10, household_size_upper=None,
                                     household_size_open_ended=True),))
    result = reconcile(columns, manifest, hh)
    assert result['status'] == expected
    assert result['totals']['member_lower_bound'] == 50
    assert result['totals']['member_exact'] is None


@pytest.mark.parametrize('column,value,check', [('province_code', '34', 'geography'),
                                               ('reference_year', 2024, 'reference_year')])
def test_mismatched_scope(inputs, column, value, check):
    columns, manifest, hh = inputs
    columns[column] = [value, value]
    if column == 'province_code':
        manifest['scope']['provinces_with_records'] = [value]
    else:
        manifest['reference_year'] = value
    result = reconcile(*inputs)
    assert result['status'] == 'incompatible'
    assert finding(result, check) == 'incompatible'


def test_institutional_only_is_incompatible(inputs):
    inputs[1]['population_universe']['definition'] = 'ADNKS_institutional_residents'
    assert reconcile(*inputs)['status'] == 'incompatible'


def test_missing_institutional_split(inputs):
    inputs[1]['population_universe']['definition'] = 'ADNKS_residents'
    result = reconcile(*inputs)
    assert result['status'] == 'not_assessable'
    assert result['totals']['private_household_persons'] is None


def test_documented_institutional_subtraction(inputs):
    inputs[0]['population_weight'] = [5, 7]
    inputs[1]['represented_population'] = 12
    inputs[1]['population_universe'].update(definition='ADNKS_residents', institutional_population=2)
    assert reconcile(*inputs)['status'] == 'compatible'


@pytest.mark.parametrize('key,value', [('reference_year', '2025'), ('scope', []),
                                     ('population_universe', None), ('source_versions', None),
                                     ('represented_population', float('nan')), ('population_id', None)])
def test_missing_or_malformed_resident_metadata(inputs, key, value):
    inputs[1][key] = value
    assert reconcile(*inputs)['status'] == 'not_assessable'


@pytest.mark.parametrize('key,value', [('source', None), ('weight_unit', None),
                                     ('represented_households', '5')])
def test_missing_or_malformed_household_metadata(inputs, key, value):
    inputs[2].manifest[key] = value
    assert reconcile(*inputs)['status'] == 'not_assessable'


@pytest.mark.parametrize('weight', [0, -1, True, float('nan'), float('inf'), '5'])
def test_invalid_weights(inputs, weight):
    columns, manifest, hh = inputs
    columns['population_weight'][0] = weight
    assert finding(reconcile(*inputs), 'resident_records') == 'not_assessable'
    hh = replace(hh, records=(replace(hh.records[0], household_weight=weight),))
    assert finding(reconcile(columns, manifest, hh), 'household_records') == 'not_assessable'


def test_totals_disagree(inputs):
    inputs[0]['population_weight'] = [6, 6]
    inputs[1]['represented_population'] = 12
    assert finding(reconcile(*inputs), 'member_totals') == 'incompatible'


def test_mislabeled_household_weights(inputs):
    inputs[2].manifest['weight_unit'] = 'person'
    assert finding(reconcile(*inputs), 'statistical_units') == 'incompatible'


def test_mislabeled_person_weights(inputs):
    inputs[1]['weight_unit'] = 'household'
    assert finding(reconcile(*inputs), 'statistical_units') == 'incompatible'


@pytest.mark.parametrize('metadata', [None, [], {}, {'source_versions': {'sources': 'invalid'}}])
def test_malformed_whole_manifest(inputs, metadata):
    assert reconcile(inputs[0], metadata, inputs[2])['status'] == 'not_assessable'


def test_malformed_universe_reference(inputs):
    inputs[1]['population_universe']['source_ref'] = ['not a reference']
    assert reconcile(*inputs)['status'] == 'not_assessable'


@pytest.mark.parametrize('year,status', [(2024, 'incompatible'), (None, 'not_assessable'), ('2025', 'not_assessable')])
def test_root_observation_year(inputs, year, status):
    inputs[1]['profiles']['invented']['fields']['province_code']['source_year'] = year
    assert finding(reconcile(*inputs), 'resident_observation_year') == status


def test_invalid_size_bounds(inputs):
    columns, manifest, hh = inputs
    hh = replace(hh, records=(replace(hh.records[0], household_size_lower=10),))
    result = reconcile(columns, manifest, hh)
    assert finding(result, 'household_records') == 'not_assessable'
    assert result['totals']['member_lower_bound'] is None


@pytest.mark.parametrize('field', ['household_size', 'household_size_upper'])
def test_closed_sizes_require_integer_metadata(inputs, field):
    columns, manifest, hh = inputs
    hh = replace(hh, records=(replace(hh.records[0], **{field: 2.0}),))
    result = reconcile(columns, manifest, hh)
    assert finding(result, 'household_records') == 'not_assessable'
    assert result['totals']['member_exact'] is None


@pytest.mark.parametrize('value', [float('nan'), float('inf'), {'non_json_set'}])
def test_malformed_provenance_remains_json_safe(inputs, value):
    inputs[1]['source_versions']['malformed'] = value
    result = reconcile(*inputs)
    assert result['status'] == 'not_assessable'
    assert finding(result, 'provenance_metadata') == 'not_assessable'
    assert result['provenance']['resident_sources'] is None
    json.dumps(result, allow_nan=False)
    assert inputs[1]['source_versions']['malformed'] is value


def test_type_size_source_binding(inputs):
    hh = inputs[2]
    size_source = deepcopy(hh.manifest['source'])
    hh.manifest['source'] = {'national': {'geography': 'TR'}}
    hh.manifest['identity'] = {'size_source': size_source}
    result = reconcile(*inputs)
    assert result['status'] == 'compatible'
    assert result['provenance']['household_source'] == size_source


def test_deterministic_read_only_and_detached_provenance(inputs):
    before = deepcopy(inputs)
    a, b = reconcile(*inputs), reconcile(*inputs)
    assert json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)
    assert inputs == before
    a['provenance']['household_source']['unit'] = 'changed'
    assert inputs == before


def test_generated_household_interface(registry, evidence):
    from societytwin.households.generator import generate
    from societytwin.households.model import HouseholdConfig
    hh = generate(evidence, HouseholdConfig(), registry)
    # Existing national manifests intentionally have no explicit universe split.
    result = reconcile({'population_weight': [2000], 'province_code': ['06'],
                        'reference_year': [2025]},
                       {'population_id': 'invented', 'reference_year': 2025,
                        'scope': {'provinces_with_records': ['06']}, 'represented_population': 2000,
                        'source_versions': {'sources': [{'source_id': 'invented'}]}}, hh)
    assert result['status'] == 'not_assessable'
    assert result['totals']['member_exact'] is None
    assert result['totals']['member_lower_bound'] == pytest.approx(2200)
