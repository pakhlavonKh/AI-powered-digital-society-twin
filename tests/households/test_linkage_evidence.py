from copy import deepcopy
import csv

import pytest
from pydantic import ValidationError

from societytwin.common import sha256_file
from societytwin.households.linkage_evidence import (
    LEAVES, LinkageEvidence, LinkageEvidenceError, inspect_sources, load_linkage_evidence,
)


def test_ankara_catalog_partition_and_preserved_provenance():
    evidence = load_linkage_evidence()
    assert tuple(c.category for c in evidence.composition) == LEAVES
    assert [c.value for c in evidence.composition] == [400484, 292350, 785228, 50178, 184664, 205415, 68897]
    assert evidence.composition_totals() == {'leaf_total': 1987216, 'nuclear': 1312420, 'lone_parent': 234842}
    assert sum(c.value for c in evidence.composition) == evidence.household_total.value
    assert sum(c.value for c in evidence.sizes) == 1987216
    assert all(c.source_label and c.definition and c.source_indicator for c in evidence.composition)
    source = evidence.sources['ankara_size_2025']
    assert source.sha256 == '1aed9e3fb1b65ab6ab4a880247b5b4b662cd980b6dfee5cedd3d904dedc2471b'
    assert evidence.coverage.private_persons.value is None
    assert evidence.coverage.institutional_persons.value is None
    assert evidence.tail.upper_size is None and evidence.tail.members.value is None


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(schema_version='future'),
    lambda p: p['composition'].append(deepcopy(p['composition'][0])),
    lambda p: p['composition'][0].update(category='nuclear'),
    lambda p: p['composition'][0].update(value=400485),
    lambda p: p['composition'][0].update(value=True),
    lambda p: p['composition'][0].update(value='400484'),
    lambda p: p['composition'][0].update(source_id='missing'),
    lambda p: p['composition'][0].update(status='missing'),
    lambda p: p['composition'][0].update(status='modeled'),
    lambda p: p['sources']['ankara_composition_2025'].update(unit='person'),
    lambda p: p['sources']['ankara_composition_2025'].update(sha256='bad'),
    lambda p: p['sources']['ankara_composition_2025'].update(source_id='wrong'),
    lambda p: p['sources']['ankara_composition_2025'].update(observation_year='2025'),
    lambda p: p['sources']['ankara_composition_2025'].update(universe='invented-universe'),
    lambda p: p['sources']['ankara_composition_2025']['precision'].update(decimal_places=2),
    lambda p: p['sizes'][0].update(category='11'),
    lambda p: p['tail'].update(upper_size=20),
    lambda p: p['tail']['members'].update(status='observed', value=35000),
    lambda p: p['relationships'].update(status='observed'),
])
def test_invalid_contracts_fail(mutation):
    payload = load_linkage_evidence().model_dump(mode='json')
    mutation(payload)
    with pytest.raises(ValidationError):
        LinkageEvidence.model_validate(payload)


@pytest.mark.parametrize('path', ['../escape.csv', '/absolute.csv', 'C:/outside.csv',
                                  'C:relative.csv', 'a\\..\\escape.csv', 'a:b.csv'])
def test_unsafe_source_paths(path):
    payload = load_linkage_evidence().model_dump(mode='json')
    payload['sources']['ankara_size_2025']['path'] = path
    with pytest.raises(ValidationError, match='relative paths'):
        LinkageEvidence.model_validate(payload)


def test_absent_sources_are_not_authenticated(tmp_path):
    evidence = load_linkage_evidence()
    assert {r['status'] for r in inspect_sources(evidence).values()} == {'not_checked'}
    before = evidence.model_dump(mode='json')
    assert {r['status'] for r in inspect_sources(evidence, tmp_path).values()} == {'unavailable'}
    assert evidence.model_dump(mode='json') == before


@pytest.fixture
def local_catalog(tmp_path):
    """Small invented CSVs exercise source binding without official production generation."""
    payload = load_linkage_evidence().model_dump(mode='json')
    payload['sources'].pop('ankara_residents_2025')
    for source in payload['sources'].values():
        source['title'] = 'Invented fixture observations'
        source['acquisition'] = 'Test-generated fixture, not official observations'
    for cell in payload['composition']:
        cell['value'] = 1
    payload['household_total']['value'] = 7
    for cell in payload['sizes']:
        cell['value'] = 1 if cell['category'] == '1' else 3 if cell['category'] in ('2', '3') else 0
    for key, source in payload['sources'].items():
        path = tmp_path/source['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            if key == 'ankara_size_2025':
                writer.writerow(['province_code', 'reference_year', 'household_size_class', 'households'])
                writer.writerows(('06', 2025, c['category'], c['value']) for c in payload['sizes'])
            else:
                writer.writerow(['province_code', 'year', 'indicator', 'value', 'unit'])
                writer.writerow(['06', 2025, 'households_total', 7, 'household'])
                writer.writerows(('06', 2025, c['source_indicator'], c['value'], 'household') for c in payload['composition'])
        source['sha256'] = sha256_file(path)
    return LinkageEvidence.model_validate(payload), tmp_path


def test_local_checksums_and_cells(local_catalog):
    evidence, root = local_catalog
    snapshot = evidence.model_dump(mode='json')
    assert {r['status'] for r in inspect_sources(evidence, root).values()} == {'matched'}
    path = root/evidence.sources['ankara_size_2025'].path
    path.write_bytes(path.read_bytes() + b'changed')
    assert inspect_sources(evidence, root)['ankara_size_2025']['status'] == 'checksum_mismatch'
    assert evidence.model_dump(mode='json') == snapshot


def test_matching_hash_does_not_validate_false_claims(local_catalog):
    evidence, root = local_catalog
    payload = evidence.model_dump(mode='json')
    payload['composition'][1]['value'] = 0
    payload['composition'][2]['value'] = 2
    result = inspect_sources(LinkageEvidence.model_validate(payload), root)
    assert result['ankara_composition_2025']['status'] == 'malformed_or_claim_mismatch'


def test_duplicate_yaml_keys_and_bad_file_rejected(tmp_path):
    path = tmp_path/'evidence.yaml'
    path.write_text('schema_version: a\nschema_version: b\n', encoding='utf-8')
    with pytest.raises(LinkageEvidenceError):
        load_linkage_evidence(path)
    with pytest.raises(LinkageEvidenceError):
        load_linkage_evidence(tmp_path/'absent.yaml')


def test_modeled_claims_need_and_retain_assumptions():
    payload = load_linkage_evidence().model_dump(mode='json')
    payload['composition'][0].update(status='modeled', assumption='Explicit invented modeling assumption')
    evidence = LinkageEvidence.model_validate(payload)
    assert evidence.composition[0].status == 'modeled'
    assert evidence.composition[0].assumption == 'Explicit invented modeling assumption'


def test_source_reparse_points_rejected(local_catalog, monkeypatch):
    from pathlib import Path
    evidence, root = local_catalog
    target = root/evidence.sources['ankara_size_2025'].path
    original = Path.is_junction
    monkeypatch.setattr(Path, 'is_junction', lambda p: p == target or original(p))
    assert inspect_sources(evidence, root)['ankara_size_2025']['status'] == 'unsafe_path'


@pytest.mark.parametrize('members,upper', [(29999, None), (30001, 10)])
def test_tail_member_counts_must_respect_bounds(members, upper):
    payload = load_linkage_evidence().model_dump(mode='json')
    payload['tail']['members'].update(status='observed', source_id='ankara_residents_2025',
                                      source_indicator='invented_tail_members', value=members)
    if upper is not None:
        payload['tail'].update(upper_size=upper, upper_status='observed', upper_source_id='ankara_size_2025')
    with pytest.raises(ValidationError, match='Tail member count'):
        LinkageEvidence.model_validate(payload)


def test_one_person_identity_is_checked(local_catalog):
    evidence, _ = local_catalog
    payload = evidence.model_dump(mode='json')
    payload['composition'][0]['value'] = 0
    payload['composition'][1]['value'] = 2
    with pytest.raises(ValidationError, match='One-person'):
        LinkageEvidence.model_validate(payload)
