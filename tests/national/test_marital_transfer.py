"""Rounding scenarios, fail-closed transfer, and default/opt-in isolation."""
import dataclasses
import math
from collections import Counter

import pytest
from pydantic import ValidationError

from societytwin.national import geography as geo
from societytwin.national.controls import ControlRow, ControlStore, TableMeta
from societytwin.national.dependencies import DependencyRegistry, RegistryError, load_registry
from societytwin.national.generator import GenerationConfig, GenerationError, generate
from societytwin.national.marital import CATEGORIES, MaritalEvidence, broad_band, load_evidence, reconstruct, transferred_conditionals
from societytwin.national.validation import validate
from societytwin.national.vocab import AGE_GROUPS


@pytest.fixture(autouse=True)
def artificial_evidence(tmp_path, monkeypatch):
    """Unit/API tests use invented evidence, never depend on ignored real data."""
    import hashlib
    import sys
    import yaml
    original_registry = load_registry()
    payload = {
        'schema_version': 'national-marital-percentages-1', 'source_version': 'ARTIFICIAL-test-only-1',
        'title': 'ARTIFICIAL test evidence, not official observations', 'publication_number': 'ARTIFICIAL',
        'publication_date': 'ARTIFICIAL', 'isbn': 'ARTIFICIAL', 'table': '1.9', 'printed_page': 14, 'pdf_page': 36,
        'url': 'https://example.invalid/artificial', 'methodology_url': 'https://example.invalid/artificial',
        'reference_year': 2025, 'geography': 'TR', 'unit': 'percent', 'denominator': 'Artificial 15+',
        'precision_pp': .1, 'categories': list(CATEGORIES), 'rounding_rule_confirmed': False,
        'zero_interpretation': 'Artificial uncertain zeros', 'acquisition': 'Invented fixture', 'reuse': 'Test only',
        'rows': [{'sex': s, 'age_band': b, 'published_percent': p} for s, b, p in (
            ('male', '15-24', [95., 4.8, .2, 0.]), ('male', '25+', [20., 70., 7., 3.]),
            ('female', '15-24', [90., 9.5, .5, 0.]), ('female', '25+', [12., 68., 8., 12.]))]}
    path = tmp_path / 'artificial-evidence.yaml'
    raw = yaml.safe_dump(payload).encode('utf-8')
    path.write_bytes(raw)
    config = original_registry.model_dump(mode='json')
    config['marital_strategy'].update(source_file=str(path), source_sha256=hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(sys.modules[__name__], 'load_registry', lambda: DependencyRegistry.model_validate(config))


def registry(variant='midpoint', enabled=True):
    payload = load_registry().model_dump(mode='json')
    payload['marital_strategy'].update(enabled=enabled, zero_variant=variant)
    return DependencyRegistry.model_validate(payload)


@pytest.fixture
def local_store():
    """Explicit ARTIFICIAL full-age controls; no downloaded dependencies in CI."""
    tables = {'population_age_sex': TableMeta('population_age_sex', 'population_age_sex', 'Artificial root'),
              'marital_status_sex': TableMeta('marital_status_sex', 'marital_status_sex', 'Artificial marital',
                                               universe_min_age=15, universe_note='Artificial 15+')}
    rows = [ControlRow('population_age_sex', 'province', '06', 2025, s, b, '', 1000, 'OBSERVED', 'test', 'artificial')
            for b in AGE_GROUPS for s in ('male', 'female')]
    rows += [ControlRow('marital_status_sex', 'province', '06', 2025, s, '', c, v, 'OBSERVED', 'test', 'artificial')
             for s in ('male', 'female') for c, v in zip(CATEGORIES, (5000, 9000, 1000, 1000))]
    return ControlStore(tables, rows, [], [], fingerprint='artificial-marital-test')


@pytest.mark.parametrize('variant, pp', [('lower_quartile', .0125), ('midpoint', .025), ('upper_quartile', .0375)])
def test_scenarios_keep_published_intervals_and_positive_support(variant, pp):
    evidence = load_evidence(registry().marital_strategy)
    probabilities, audit = reconstruct(evidence, variant)
    for row in audit:
        p = probabilities[(row['sex'], row['age_band'])]
        assert math.fsum(p) == pytest.approx(1)
        assert all(math.isfinite(v) and v > 0 for v in p)
        assert all(lo <= v < hi for lo, v, hi in zip(row['assumed_lower_pp'], row['scenario_percent'],
                                                     row['assumed_upper_pp_exclusive']))
        if row['age_band'] == '15-24':
            assert row['published_percent'][3] == 0
            assert row['scenario_percent'][3] == pp
    assert not evidence.rounding_rule_confirmed


@pytest.mark.parametrize('change', [
    lambda p: p.update(unit='persons'),
    lambda p: p.update(geography='06'),
    lambda p: p.update(rounding_rule_confirmed=True),
    lambda p: p['rows'].pop(),
    lambda p: p['rows'].append(p['rows'][0]),
    lambda p: p['rows'][0].update(age_band='15-19'),
    lambda p: p['rows'][0]['published_percent'].__setitem__(0, float('nan')),
    lambda p: p['rows'][0]['published_percent'].__setitem__(3, -.01),
    lambda p: p['rows'][0]['published_percent'].__setitem__(0, 96.7),
])
def test_bad_evidence_rejected(change):
    payload = load_evidence(registry().marital_strategy).model_dump(mode='json')
    change(payload)
    with pytest.raises(ValidationError):
        MaritalEvidence.model_validate(payload)


@pytest.mark.parametrize('change', [
    {'policy_version': 'silently_invent_epsilon'}, {'zero_variant': 'exact_zero'},
    {'acknowledge_unverified_rounding': False}, {'province_code': '34'}, {'reference_year': 2024},
    {'source_sha256': 'missing'},
])
def test_invalid_strategy_rejected(change):
    payload = load_registry().model_dump(mode='json')
    payload['marital_strategy'].update(change)
    with pytest.raises(ValidationError):
        DependencyRegistry.model_validate(payload)


def test_source_missing_or_changed_fails_closed(tmp_path):
    strategy = registry().marital_strategy
    with pytest.raises(RegistryError, match='Invalid national marital evidence'):
        load_evidence(strategy.model_copy(update={'source_file': str(tmp_path / 'missing.yaml')}))
    with pytest.raises(RegistryError, match='checksum mismatch'):
        load_evidence(strategy.model_copy(update={'source_sha256': '0' * 64}))


def test_fitted_broad_rows_match_targets_and_have_no_fine_age_gradient(local_store):
    root = local_store.best('population_age_sex', geo.province('06'), 2025)
    info = transferred_conditionals(local_store, geo.province('06'), root, 2025, registry().marital_strategy)
    for sex, fit in info['provenance']['diagnostics']['ipf'].items():
        for row, target in zip(fit['fitted_counts'], fit['row_targets']):
            assert math.fsum(row) == pytest.approx(target, rel=1e-8)
        for j, target in enumerate(fit['column_targets']):
            assert math.fsum(row[j] for row in fit['fitted_counts']) == pytest.approx(target, rel=1e-8)
        # IPF preserves each positive-support broad-age/category odds ratio;
        # Ankara percentages themselves need not equal national percentages.
        for j in range(1, len(CATEGORIES)):
            def odds(table):
                return table[0][j] * table[1][0] / (table[0][0] * table[1][j])
            assert odds(fit['fitted_probabilities']) == pytest.approx(odds(fit['seed_probabilities']), rel=1e-8)
        assert info['conditionals'][('15-19', sex)] == info['conditionals'][('20-24', sex)]
        assert info['conditionals'][('25-29', sex)] == info['conditionals'][('90+', sex)]
        assert info['conditionals'][('15-19', sex)][3] > 0
    assert info['provenance']['structural_zeros'] is False


@pytest.mark.parametrize('config', [GenerationConfig(provinces=None), GenerationConfig(provinces=('34',)),
    GenerationConfig(provinces=('06',), reference_year=2024), GenerationConfig(provinces=('06',), calibrate=False),
    GenerationConfig(provinces=('06',), synthetic_size=10)])
def test_outside_bounded_execution_contract_fails(local_store, config):
    with pytest.raises(GenerationError):
        generate(local_store, config, registry=registry())


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'unknown', 'mismatch', 'negative'])
def test_invalid_controls_not_silently_scaled_or_filled(local_store, mutation):
    rows = list(local_store.rows)
    i = next(i for i, r in enumerate(rows) if r.table_id == 'marital_status_sex')
    if mutation == 'missing':
        rows.pop(i)
    elif mutation == 'duplicate':
        rows.append(rows[i])
    elif mutation == 'unknown':
        rows[i] = dataclasses.replace(rows[i], value=None, value_status='NOT_AVAILABLE')
    else:
        rows[i] = dataclasses.replace(rows[i], value=rows[i].value + 1 if mutation == 'mismatch' else -1)
    store = ControlStore(local_store.tables, rows, [], [])
    with pytest.raises(GenerationError):
        generate(store, GenerationConfig(provinces=('06',)), registry=registry())


def test_calibration_failure_cannot_drop_marital_margin(local_store, monkeypatch):
    from societytwin.national.fitting import RakeReport
    monkeypatch.setattr('societytwin.national.generator.rake',
                        lambda *a, **k: RakeReport(converged=False, iterations=1, max_relative_error=.1))
    with pytest.raises(GenerationError, match='cannot be dropped'):
        generate(local_store, GenerationConfig(synthetic_size=1000, provinces=('06',)), registry=registry())


def test_nonconvergent_seed_fit_is_rejected(local_store, monkeypatch):
    from societytwin.national import marital
    original = marital.ipf_2d
    def unconverged(*args, **kwargs):
        result = original(*args, **kwargs)
        result.converged = False
        return result
    monkeypatch.setattr(marital, 'ipf_2d', unconverged)
    with pytest.raises(GenerationError, match='IPF failed'):
        generate(local_store, GenerationConfig(synthetic_size=1000, provinces=('06',)), registry=registry())


def test_missing_record_support_cannot_redistribute_targets():
    from societytwin.national.generator import _attribute_margin
    from types import SimpleNamespace
    info = {'option': SimpleNamespace(table_id='marital_status_sex'), 'min_age': 15, 'strict_targets': True,
            'selection': SimpleNamespace(counts=lambda: {('male', c): 1.0 for c in CATEGORIES})}
    columns = {'age': [30], 'age_group': ['30-34'], 'sex': ['male'], 'marital_status': ['married']}
    with pytest.raises(GenerationError, match='forbids target redistribution'):
        _attribute_margin('marital_status', info, columns, range(1), {('30-34', 'male'): 4})


def test_default_exact_and_opt_in_identity_separation(local_store):
    cfg = GenerationConfig(synthetic_size=1000, provinces=('06',))
    default = generate(local_store, cfg)
    disabled = generate(local_store, cfg, registry=registry('upper_quartile', enabled=False))
    assert default.columns == disabled.columns
    assert default.profiles == disabled.profiles
    assert default.manifest['population_id'] == disabled.manifest['population_id']
    ids = set()
    for variant in ('lower_quartile', 'midpoint', 'upper_quartile'):
        pop = generate(local_store, cfg, registry=registry(variant))
        again = generate(local_store, cfg, registry=registry(variant))
        assert pop.columns == again.columns
        assert pop.manifest['population_id'] == again.manifest['population_id']
        for key in default.columns.keys() - {'marital_status', 'population_weight'}:
            assert pop.columns[key] == default.columns[key]
        assert pop.columns['marital_status'] != default.columns['marital_status']
        assert validate(pop.columns, pop.manifest, local_store)['constraint_violations'] == 0
        sums = Counter()
        for i, age in enumerate(pop.columns['age']):
            if age >= 15:
                sums[(pop.columns['sex'][i], pop.columns['marital_status'][i])] += pop.columns['population_weight'][i]
        for r in local_store.rows:
            if r.table_id == 'marital_status_sex':
                assert sums[(r.sex, r.category)] == pytest.approx(r.value, rel=1e-6)
        ids.add(pop.manifest['population_id'])
    assert len(ids) == 3 and default.manifest['population_id'] not in ids


def test_existing_source_units_and_bands_not_extended():
    assert broad_band('0-4') is None
    assert broad_band('15-19') == broad_band('20-24') == '15-24'
    assert broad_band('25-29') == broad_band('90+') == '25+'


def test_opt_in_uses_existing_api_persona_and_cohort_contracts(national_settings, local_store, tmp_path):
    import yaml
    from tests.conftest import make_client
    from societytwin.national.controls import write_store
    path = tmp_path / 'opt-in-registry.yaml'
    path.write_text(yaml.safe_dump(registry().model_dump(mode='json')), encoding='utf-8')
    settings = national_settings.with_overrides(dependency_registry_path=path)
    write_store(settings.national_controls_dir, local_store)
    with make_client(settings) as client:
        request = {'synthetic_size': 1000, 'seed': 42, 'province_codes': ['06']}
        response = client.post('/api/v2/populations', json=request)
        assert response.status_code == 201, response.text
        pid = response.json()['population']['population_id']
        assert client.post('/api/v2/populations', json=request).json()['created'] is False
        page = client.get(f'/api/v2/populations/{pid}/records', params={'adult_only': True, 'limit': 1}).json()
        rec = page['items'][0]
        detail = client.get(f"/api/v2/populations/{pid}/records/{rec['synthetic_id']}")
        assert detail.status_code == 200 and 'model_visible' in detail.json()['persona']
        response = client.post('/api/v2/cohorts', json={'name': 'Opt-in test', 'population_id': pid,
                                                       'filters': {'adult_only': True}})
        assert response.status_code == 201, response.text
        cid = response.json()['cohort_id']
        sample = client.post(f'/api/v2/cohorts/{cid}/samples', json={'size': 10, 'method': 'weighted', 'seed': 4})
        assert sample.status_code == 201, sample.text
        assert sample.json()['selected'] == 10
