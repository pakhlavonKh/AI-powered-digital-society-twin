import dataclasses
import json
import math
from collections import Counter

import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from societytwin.common import sha256_file
from societytwin.households import SCHEMA_VERSION
from societytwin.households.evidence import load_evidence
from societytwin.households.generator import generate
from societytwin.households.model import HouseholdConfig
from societytwin.households.registry import HouseholdError,HouseholdRegistry,load_registry,parent_binding
from societytwin.households.service import build
from societytwin.households.store import HouseholdStore,SCHEMA
from societytwin.households.validation import validate


def test_default_disabled_and_household_scope(tmp_path):
    registry=load_registry()
    assert registry.module.enabled is False
    assert all(a.scope=='household' for a in registry.attributes.values())
    assert parent_binding(registry)['registry_version']==registry.parent_registry_version
    with pytest.raises(HouseholdError,match='disabled by default'):
        build(HouseholdConfig(),output_root=tmp_path/'untouched')
    assert not (tmp_path/'untouched').exists()


def test_generator_rejects_disabled_registry(evidence):
    with pytest.raises(HouseholdError,match='disabled'):
        generate(evidence,HouseholdConfig(),load_registry())


@pytest.mark.parametrize('size',[1000,10000])
def test_records_distribution_fit_tail_and_units(registry,evidence,size):
    population=generate(evidence,HouseholdConfig(synthetic_size=size),registry)
    report=validate(population)
    assert len(population.records)==len({r.household_id for r in population.records})==size
    assert math.isclose(report['represented_households'],550,rel_tol=1e-14)
    assert report['weight_unit']=='household' and report['exact_total_members'] is None
    assert report['linked_residents']==0
    assert all(m['relative_error']<1e-12 and m['record_allocation_deviation']<1 for m in report['margins'])
    assert all(r.household_weight>0 and math.isfinite(r.household_weight) for r in population.records)
    tail=[r for r in population.records if r.household_size_class=='10+']
    assert tail and all(r.household_size is None and r.household_size_upper is None and
                        r.household_size_lower==10 and r.household_size_open_ended for r in tail)
    forbidden={'synthetic_id','resident_id','population_weight','design_weight','members','household_type','income','ses'}
    assert not forbidden.intersection(dataclasses.asdict(population.records[0]))
    assert report['represented_members_lower_bound']>report['represented_households']


def test_deterministic_records_id_versions_and_seed(registry,evidence):
    a=generate(evidence,HouseholdConfig(seed=42),registry)
    b=generate(evidence,HouseholdConfig(seed=42),registry)
    other=generate(evidence,HouseholdConfig(seed=43),registry)
    assert a==b and a.records!=other.records
    assert Counter(r.household_size_class for r in a.records)==Counter(r.household_size_class for r in other.records)
    assert a.manifest['schema_version']==SCHEMA_VERSION
    assert a.manifest['source']['sha256']==registry.source.sha256
    assert a.manifest['parent_dependency_registry']==parent_binding(registry)
    payload=registry.model_dump(mode='json');payload['registry_version']='test-household-size-2'
    changed=generate(evidence,HouseholdConfig(),HouseholdRegistry.model_validate(payload))
    assert changed.manifest['household_population_id']!=a.manifest['household_population_id']
    assert len({r.household_id for r in a.records}&{r.household_id for r in changed.records})==0


@pytest.mark.parametrize('change',[
    lambda p:p['source'].update(scope='person'),
    lambda p:p['source'].update(unit='person'),
    lambda p:p['source'].update(evidence='context_only'),
    lambda p:p['source'].update(dimensions=['province_code','sex']),
    lambda p:p['source'].update(universe='all_residents'),
    lambda p:p['attributes']['household_weight'].update(method='resident_raking'),
    lambda p:p['attributes']['household_size'].update(parents=['age']),
    lambda p:p.update(size_classes=['1','2','10']),
])
def test_invalid_registry_rejected(registry,change):
    payload=registry.model_dump(mode='json');change(payload)
    with pytest.raises(ValidationError):HouseholdRegistry.model_validate(payload)


def test_wrong_parent_registry_rejected(registry):
    payload=registry.model_dump(mode='json');payload['parent_registry_version']='unknown'
    with pytest.raises(HouseholdError,match='compatible parent'):
        parent_binding(HouseholdRegistry.model_validate(payload))


def test_duplicate_yaml_rejected(tmp_path):
    path=tmp_path/'bad.yaml';path.write_text('module: {}\nmodule: {}\n')
    with pytest.raises(HouseholdError,match='duplicate'):
        load_registry(path)


def test_missing_and_changed_observations_rejected(registry,tmp_path):
    path=tmp_path/'artificial-households.csv'
    path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(HouseholdError,match='checksum'):
        load_evidence(registry,tmp_path)
    path.unlink()
    with pytest.raises(HouseholdError,match='unavailable'):
        load_evidence(registry,tmp_path)


def test_extra_observation_cells_rejected(registry,tmp_path):
    path=tmp_path/'artificial-households.csv'
    path.write_text(path.read_text().replace('06,2025,1,100','06,2025,1,100,extra'),encoding='utf-8')
    payload=registry.model_dump(mode='json');payload['source']['sha256']=sha256_file(path)
    with pytest.raises(HouseholdError,match='extra household observation'):
        load_evidence(HouseholdRegistry.model_validate(payload),tmp_path)


@pytest.mark.parametrize('old,new,message',[
    ('06,2025,1,100','01,2025,1,100','province/year'),
    ('06,2025,1,100','06,2024,1,100','province/year'),
    ('06,2025,1,100','06,2025,1,','positive observed integers'),
    ('06,2025,1,100','06,2025,1,-100','positive observed integers'),
    ('06,2025,1,100','06,2025,1,NaN','positive observed integers'),
    ('06,2025,1,100','06,2025,1,100.0','positive observed integers'),
    ('06,2025,10+,10','06,2025,10,10','unsupported'),
    ('06,2025,2,90','06,2025,1,90','duplicate'),
    ('06,2025,1,100','06,2025,1,101','total'),
])
def test_malformed_cells_fail_even_with_matching_file_hash(registry,tmp_path,old,new,message):
    path=tmp_path/'artificial-households.csv'
    path.write_text(path.read_text().replace(old,new),encoding='utf-8')
    payload=registry.model_dump(mode='json');payload['source']['sha256']=sha256_file(path)
    with pytest.raises(HouseholdError,match=message):
        load_evidence(HouseholdRegistry.model_validate(payload),tmp_path)


def test_insufficient_sample_support_fails(registry,evidence):
    with pytest.raises(HouseholdError,match='sample too small'):
        generate(evidence,HouseholdConfig(synthetic_size=10),registry)


@pytest.mark.parametrize('bad',[
    {'synthetic_size':True},{'synthetic_size':1000.5},{'seed':-1},{'province_code':'01'},
    {'reference_year':2024},{'population_weight':1},{'resident_build_id':'invented'},
])
def test_config_rejects_invalid_requests(bad):
    with pytest.raises(ValidationError):HouseholdConfig(**bad)


@pytest.mark.parametrize('weight',[0,-1,float('nan'),float('inf')])
def test_weight_corruption_rejected(registry,evidence,weight):
    population=generate(evidence,HouseholdConfig(),registry)
    broken=dataclasses.replace(population,records=(dataclasses.replace(population.records[0],household_weight=weight),)+population.records[1:])
    with pytest.raises((HouseholdError,ValueError)):
        validate(broken)


def test_false_exact_tail_rejected(registry,evidence):
    population=generate(evidence,HouseholdConfig(),registry)
    records=tuple(dataclasses.replace(r,household_size=10) if r.household_size_class=='10+' else r for r in population.records)
    with pytest.raises(HouseholdError,match='open-ended'):
        validate(dataclasses.replace(population,records=records))


def test_store_round_trip_schema_idempotence_and_tampering(registry,evidence,tmp_path):
    population=generate(evidence,HouseholdConfig(),registry)
    store=HouseholdStore(tmp_path/'households')
    directory=store.write(population)
    hashes={p.name:sha256_file(p) for p in directory.iterdir()}
    assert store.write(population)==directory
    assert hashes=={p.name:sha256_file(p) for p in directory.iterdir()}
    saved=store.load(population.manifest['household_population_id'])
    assert saved.records==population.records
    assert pq.read_schema(directory/'households.parquet').equals(SCHEMA,check_metadata=True)
    assert not (directory/'records.parquet').exists()
    (directory/'households.parquet').write_bytes(b'corrupt')
    with pytest.raises(HouseholdError,match='checksum'):
        store.write(population)
    assert (directory/'households.parquet').read_bytes()==b'corrupt'


def test_output_isolation(registry,tmp_path):
    for output in [tmp_path/'data/populations',tmp_path/'src']:
        with pytest.raises(HouseholdError,match='outputs must be separate'):
            build(HouseholdConfig(),enable_households=True,repo_root=tmp_path,output_root=output)
        assert not output.exists()


def test_service_activates_only_request_local_registry(registry,tmp_path):
    import yaml
    path=tmp_path/'registry.yaml'
    payload=registry.model_dump(mode='json');payload['module']['enabled']=False
    path.write_text(yaml.safe_dump(payload),encoding='utf-8')
    before=path.read_bytes()
    output=tmp_path/'data/results/disposable-households'
    directory=build(HouseholdConfig(),enable_households=True,registry_path=path,repo_root=tmp_path,output_root=output)
    assert path.read_bytes()==before
    manifest=json.loads((directory/'manifest.json').read_text())
    assert manifest['registry']['module']['enabled'] is True
    assert manifest['linked_to_residents'] is False
    assert not list(output.rglob('records.parquet'))
    assert not list(output.rglob('membership.parquet'))


def test_cli_requires_explicit_opt_in(monkeypatch,capsys):
    from societytwin.households.__main__ import main
    monkeypatch.setattr('sys.argv',['households'])
    with pytest.raises(SystemExit) as exc:main()
    assert exc.value.code==2
    assert 'disabled by default' in capsys.readouterr().err


def test_households_do_not_change_resident_generation(store,registry,evidence):
    from societytwin.national.generator import GenerationConfig,generate as residents
    from societytwin.national.dependencies import load_registry as resident_registry
    from societytwin.national.store import SCHEMA as resident_schema
    before=resident_registry().fingerprint
    baseline=residents(store,GenerationConfig(synthetic_size=1000,seed=42))
    generate(evidence,HouseholdConfig(),registry)
    again=residents(store,GenerationConfig(synthetic_size=1000,seed=42))
    assert baseline.columns==again.columns
    assert baseline.manifest['population_id']==again.manifest['population_id']
    assert resident_registry().fingerprint==before
    assert 'household_id' not in resident_schema.names
    assert all(v is None for v in again.columns['household_size_class'])
