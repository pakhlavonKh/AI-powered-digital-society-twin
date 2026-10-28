"""Unit-record, invented fixtures only; no official builds or persistence."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json

import pytest
from pydantic import ValidationError

from societytwin.enrichment.model import EnrichmentConfig, ResidentExtension
from societytwin.households.membership import (
    CONTRACT_VERSION, FIXTURE_PURPOSE, METHOD_VERSION, FixtureMembershipContract,
    MembershipError, assess_readiness, input_fingerprints, link_fixture, validate_membership,
)
from societytwin.households.model import GeneratedHouseholds, HouseholdRecord
from societytwin.households.reconciliation import reconcile


def bind(case, **overrides):
    columns, manifest, hh = case
    payload = dict(contract_version=CONTRACT_VERSION, purpose=FIXTURE_PURPOSE,
                   population_id=manifest['population_id'],
                   household_population_id=hh.manifest['household_population_id'],
                   resident_representation='unit_person_records',
                   household_representation='unit_household_records', universe_approved=True,
                   eligibility_source_ref='invented-fixture: all five residents are eligible',
                   eligible_resident_ids=tuple(columns['synthetic_id']),
                   **input_fingerprints(*case))
    payload.update(overrides)
    return FixtureMembershipContract.model_validate(payload)


@pytest.fixture
def case():
    columns = {'synthetic_id': [f'r{i}' for i in range(1, 6)],
               'province_code': ['06'] * 5, 'reference_year': [2025] * 5,
               'population_weight': [1.] * 5, 'design_weight': [1.] * 5,
               'age': [12, 24, 37, 50, 68], 'sex': ['female', 'male', 'female', 'male', 'female'],
               'marital_status': ['invented-unspecified'] * 5,
               'education': ['invented-unspecified'] * 5}
    manifest = {'population_id': 'fixture-people', 'purpose': FIXTURE_PURPOSE,
                'reference_year': 2025, 'represented_population': 5,
                'scope': {'provinces_with_records': ['06']},
                'source_versions': {'sources': [{'source_id': 'invented-unit-fixture'}]},
                'profiles': {'fixture': {'fields': {'province_code': {'source_year': 2025}}}},
                'population_universe': {'definition': 'ADNKS_private_household_residents',
                                        'source_ref': 'invented-fixture: private residents only'}}
    records = tuple(HouseholdRecord(f'h{i}', '06', 2025, str(size), size, size, size, False, 1.)
                    for i, size in [(1, 2), (2, 3)])
    hm = {'household_population_id': 'fixture-households', 'purpose': FIXTURE_PURPOSE,
          'weight_unit': 'household', 'represented_households': 2,
          'source': {'province_code': '06', 'reference_year': 2025, 'unit': 'household',
                     'universe': 'ADNKS_private_households', 'source_version': 'invented-exact-sizes'}}
    return columns, manifest, GeneratedHouseholds(records, hm)


def assess(case, contract=None, reconciliation=None):
    return assess_readiness(*case, contract=contract if contract is not None else bind(case),
                            reconciliation=reconciliation if reconciliation is not None else reconcile(*case))


def link(case, seed=42, contract=None, reconciliation=None):
    return link_fixture(*case, contract=contract if contract is not None else bind(case),
                        reconciliation=reconciliation if reconciliation is not None else reconcile(*case),
                        config=EnrichmentConfig(seed=seed), enable_fixture_linking=True)


def codes(report):
    return {r['code'] for r in report['reasons']}


def test_exact_capacity_and_existing_sidecar_contract(case):
    report = assess(case)
    assert report['status'] == 'ready' and report['ready']
    assert report['counts'] == {'residents': 5, 'households': 2, 'capacity': 5}
    extension = link(case)
    assert isinstance(extension, ResidentExtension)
    assert [r.synthetic_id for r in extension.records] == case[0]['synthetic_id']
    assert Counter(r.attributes[0].value for r in extension.records) == {'h1': 2, 'h2': 3}
    assert validate_membership(extension, *case, reconciliation=reconcile(*case), contract=bind(case))['valid']


def test_reproducibility_and_json_identity(case):
    a, b = link(case), link(case)
    assert a == b
    assert json.dumps(a.manifest, sort_keys=True, allow_nan=False) == json.dumps(b.manifest, sort_keys=True, allow_nan=False)
    assert a.manifest['artifact_id'] == b.manifest['artifact_id']


def test_seed_provenance_and_multiple_partitions(case):
    outputs = [link(case, seed) for seed in range(10)]
    assert len({tuple(r.attributes[0].value for r in o.records) for o in outputs}) > 1
    assert len({o.manifest['artifact_id'] for o in outputs}) == 10
    for seed, output in enumerate(outputs):
        assert output.manifest['config']['seed'] == seed


def test_stable_scoped_references(case):
    output = link(case)
    assert output.manifest['core']['population_id'] == case[1]['population_id']
    assert output.manifest['households']['household_population_id'] == case[2].manifest['household_population_id']
    for row in output.records:
        assert row.synthetic_id in case[0]['synthetic_id']
        assert row.attributes[0].value in {h.household_id for h in case[2].records}


def test_cross_population_id_is_not_same_identity(case):
    original = link(case)
    case[1]['population_id'] = 'another-fixture-population'
    updated = link(case)
    assert original.manifest['artifact_id'] != updated.manifest['artifact_id']
    assert original.manifest['core'] != updated.manifest['core']


def test_default_disabled_even_for_ready_fixture(case):
    with pytest.raises(MembershipError, match='disabled'):
        link_fixture(*case, reconciliation=reconcile(*case), contract=bind(case))


@pytest.mark.parametrize('side', ['resident', 'household'])
@pytest.mark.parametrize('kind', ['duplicate', 'missing', 'blank'])
def test_invalid_existing_ids(case, side, kind):
    if side == 'resident':
        case[0]['synthetic_id'][0] = {'duplicate': 'r2', 'missing': None, 'blank': ''}[kind]
    else:
        h = case[2]
        case = (*case[:2], replace(h, records=(replace(h.records[0], household_id={
            'duplicate': 'h2', 'missing': None, 'blank': ''}[kind]), h.records[1])))
    report = assess_readiness(*case, reconciliation={}, contract={})
    assert 'input_integrity' in codes(report) and not report['ready']


@pytest.mark.parametrize('size', [1, 3])
def test_insufficient_and_excess_capacity(case, size):
    h = case[2]
    hh = replace(h, records=(replace(h.records[0], household_size_class=str(size), household_size=size,
                                     household_size_lower=size, household_size_upper=size), h.records[1]))
    case = (*case[:2], hh)
    report = assess(case)
    assert 'capacity_mismatch' in codes(report) and not report['ready']
    with pytest.raises(MembershipError) as error:
        link(case)
    assert error.value.report == report


def test_open_ended_ten_plus_is_blocked(case):
    h = case[2]
    hh = replace(h, records=(replace(h.records[0], household_size_class='10+', household_size=None,
                                     household_size_lower=10, household_size_upper=None,
                                     household_size_open_ended=True), h.records[1]))
    case = (*case[:2], hh)
    assert 'exact_capacity' in codes(assess(case))
    with pytest.raises(MembershipError, match='exact_capacity'):
        link(case)


@pytest.mark.parametrize('status', ['incompatible', 'not_assessable'])
def test_supplied_bad_reconciliation_is_not_trusted(case, status):
    report = reconcile(*case)
    report['status'] = status
    assert 'reconciliation_binding' in codes(assess(case, reconciliation=report))
    with pytest.raises(MembershipError, match='reconciliation_binding'):
        link(case, reconciliation=report)


def test_genuine_incompatible_reconciliation(case):
    case[2].manifest['source']['province_code'] = '34'
    report = assess(case)
    assert 'reconciliation_incompatible' in codes(report)
    assert report['status'] == 'blocked'


def test_genuine_not_assessable_reconciliation(case):
    del case[1]['profiles']
    report = assess(case)
    assert 'reconciliation_not_assessable' in codes(report)
    assert report['status'] == 'not_assessable'


def test_forged_compatible_reconciliation_cannot_bypass_inputs(case):
    good_report = reconcile(*case)
    del case[1]['profiles']
    report = assess(case, reconciliation=good_report)
    assert {'reconciliation_binding', 'reconciliation_not_assessable'} <= codes(report)


def test_unapproved_universe(case):
    report = assess(case, contract=bind(case, universe_approved=False))
    assert 'universe_approval' in codes(report)


@pytest.mark.parametrize('definition', [None, 'unclear', 'ADNKS_residents'])
def test_unclear_or_aggregate_only_eligibility(case, definition):
    case[1]['population_universe']['definition'] = definition
    case[1]['population_universe']['institutional_population'] = 0
    report = assess(case)
    assert 'private_resident_eligibility' in codes(report) and not report['ready']


def test_weighted_production_misuse_even_when_aggregate_compatible(case):
    case[0]['population_weight'] = [2.] * 5
    case[0]['design_weight'] = [2.] * 5
    case[1]['represented_population'] = 10
    hh = replace(case[2], records=tuple(replace(r, household_weight=2.) for r in case[2].records))
    hh.manifest['represented_households'] = 4
    case = (*case[:2], hh)
    assert reconcile(*case)['status'] == 'compatible'
    assert {'resident_representation', 'household_representation'} <= codes(assess(case))
    with pytest.raises(MembershipError, match='resident_representation'):
        link(case)


@pytest.mark.parametrize('field', ['design_weight', 'population_weight'])
def test_non_unit_or_missing_person_weights(case, field):
    case[0][field][0] = 1.000000001
    assert 'resident_representation' in codes(assess(case))
    del case[0][field]
    assert 'resident_representation' in codes(assess(case))


@pytest.mark.parametrize('side', ['resident', 'household'])
def test_purpose_required_even_if_weights_are_one(case, side):
    m = case[1] if side == 'resident' else case[2].manifest
    del m['purpose']
    assert 'fixture_only' in codes(assess(case))


@pytest.mark.parametrize('ids', [('r1', 'r1', 'r3', 'r4', 'r5'), ('r1', 'r2'),
                                 ('r1', 'r2', 'r3', 'r4', 'foreign')])
def test_invalid_or_incomplete_eligibility(case, ids):
    assert 'eligibility' in codes(assess(case, contract=bind(case, eligible_resident_ids=ids)))


def test_missing_contract_and_eligibility_evidence(case):
    assert 'fixture_contract' in codes(assess_readiness(*case, reconciliation=reconcile(*case), contract=None))
    payload = bind(case).model_dump(mode='json')
    del payload['eligibility_source_ref']
    assert 'fixture_contract' in codes(assess(case, contract=payload))


def test_input_order_and_column_order_stability(case):
    contract = bind(case)
    before = link(case, contract=contract)
    columns = {k: list(reversed(v)) for k, v in reversed(list(case[0].items()))}
    reversed_case = (columns, case[1], replace(case[2], records=tuple(reversed(case[2].records))))
    assert input_fingerprints(*case) == input_fingerprints(*reversed_case)
    assert before == link(reversed_case, contract=contract)
    reversed_contract = bind(case, eligible_resident_ids=tuple(reversed(case[0]['synthetic_id'])))
    assert before == link(case, contract=reversed_contract)


def test_no_mutation_and_no_unsupported_roles_or_demographics(case):
    snapshot = deepcopy(case)
    contract = bind(case)
    assess(case, contract=contract)
    output = link(case, contract=contract)
    validate_membership(output, *case, reconciliation=reconcile(*case), contract=contract)
    assert case == snapshot
    for record in output.records:
        assert set(record.model_dump()) == {'synthetic_id', 'attributes'}
        assert [a.attribute for a in record.attributes] == ['household_id']
    # Provenance is detached from caller-owned objects.
    next(iter(output.manifest['provenance_profiles'].values()))['contract']['eligible_resident_ids'].clear()
    assert case == snapshot


def test_experimental_provenance_and_integrity(case):
    output = link(case, seed=7)
    m = output.manifest
    assert m['membership_contract_version'] == CONTRACT_VERSION
    assert m['model_version'] == METHOD_VERSION and m['purpose'] == FIXTURE_PURPOSE
    assert m['input_fingerprints'] == input_fingerprints(*case)
    assert not m['readiness']['production_linking_enabled']
    profile = next(iter(m['provenance_profiles'].values()))
    assert profile['seed'] == 7 and profile['evidence_class'] == 'synthetic_fixture'
    assert profile['limitations'] and profile['contract']['eligibility_source_ref']
    assert all(r.attributes[0].provenance_profile in m['provenance_profiles'] for r in output.records)


@pytest.mark.parametrize('kind', ['demographic', 'source', 'household'])
def test_stale_fingerprint_refuses_changed_inputs(case, kind):
    contract = bind(case)
    if kind == 'demographic':
        case[0]['age'][0] = 13
    elif kind == 'source':
        case[1]['source_versions']['sources'][0]['source_id'] = 'changed'
    else:
        case[2].manifest['source']['source_version'] = 'changed'
    assert 'input_fingerprint' in codes(assess(case, contract=contract))


def test_contract_build_ids_must_match(case):
    assert 'build_identity' in codes(assess(case, contract=bind(case, population_id='foreign')))
    assert 'build_identity' in codes(assess(case, contract=bind(case, household_population_id='foreign')))


@pytest.mark.parametrize('kind', ['missing_resident', 'duplicate_resident', 'foreign_resident', 'foreign_household', 'role'])
def test_tampered_membership_references(case, kind):
    output = link(case)
    records = list(output.records)
    if kind == 'missing_resident':
        records.pop()
    elif kind == 'duplicate_resident':
        records[0] = records[1]
    elif kind == 'foreign_resident':
        records[0] = records[0].model_copy(update={'synthetic_id': 'foreign'})
    else:
        a = records[0].attributes[0]
        a = a.model_copy(update={'value': 'foreign'} if kind == 'foreign_household' else {'attribute': 'family_role'})
        records[0] = records[0].model_copy(update={'attributes': (a,)})
    with pytest.raises(MembershipError, match='reference|attribute'):
        validate_membership(replace(output, records=tuple(records)), *case,
                            reconciliation=reconcile(*case), contract=bind(case))


@pytest.mark.parametrize('field', ['core', 'content_hash', 'purpose', 'artifact_id', 'limitations'])
def test_manifest_tampering_rejected(case, field):
    output = link(case)
    output.manifest[field] = 'tampered'
    with pytest.raises(MembershipError, match='replay'):
        validate_membership(output, *case, reconciliation=reconcile(*case), contract=bind(case))


@pytest.mark.parametrize('seed', [-1, True, 2**63, '42'])
def test_seed_validation(seed):
    with pytest.raises(ValidationError):
        EnrichmentConfig(seed=seed)
