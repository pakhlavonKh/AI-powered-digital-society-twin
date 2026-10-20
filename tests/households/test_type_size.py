"""Artificial evidence only. Real acquired observations remain ignored research inputs."""
import csv
import dataclasses
import json
import math

import pytest
from pydantic import ValidationError

from societytwin.common import sha256_file
from societytwin.households.generator import generate as size_only
from societytwin.households.model import HouseholdConfig
from societytwin.households.registry import HouseholdError
from societytwin.households.store import HouseholdStore,SCHEMA as SIZE_SCHEMA
from societytwin.households.type_size import fit_targets,generate_type_size
from societytwin.households.type_size_evidence import allowed,load_type_size_evidence
from societytwin.households.type_size_registry import BANDS,TYPES,TypeSizeRegistry,load_type_size_registry
from societytwin.households.type_size_store import TypeSizeStore,SCHEMA
from societytwin.households.type_size_validation import validate_type_size


@pytest.fixture
def optional(registry,tmp_path):
    types=TYPES+('couple_without_resident_children','couple_with_resident_children','lone_parent','lone_father','lone_mother')
    rows=[]
    for i,band in enumerate(BANDS):
        nuclear=200+i*100 if i else 0
        lone=nuclear//2 if i==1 else nuclear//5
        vals={'one_person':1000 if i==0 else None,'nuclear_family':nuclear if i else None,
              'extended_family':i*100 if i>=2 else None,'non_family_multi_person':120-i*10 if i else None,
              'couple_without_resident_children':nuclear-lone if i==1 else None,
              'couple_with_resident_children':nuclear-lone if i>=2 else None,
              'lone_parent':lone if i else None,'lone_father':lone//2 if i else None,
              'lone_mother':lone-lone//2 if i else None}
        for t in types:
            v=vals[t]
            rows.append([2025,'TR',t,band,'' if v is None else v,'NOT_APPLICABLE' if v is None else 'OBSERVED','ARTIFICIAL'])
    national=tmp_path/'national.csv'
    with national.open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['year','geography','household_type','household_size','households','value_status','source_table']);writer.writerows(rows)
    local=tmp_path/'types.csv'
    with local.open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['year','province_code','household_type','households'])
        writer.writerows([2025,'06',t,v] for t,v in zip(TYPES+('total',),(100,300,80,70,550)))
    payload=load_type_size_registry().model_dump(mode='json')
    payload['national'].update(path=str(national),sha256=sha256_file(national),title='ARTIFICIAL joint')
    payload['ankara_types'].update(path=str(local),sha256=sha256_file(local),title='ARTIFICIAL margins')
    return TypeSizeRegistry.model_validate(payload).activated()


@pytest.fixture
def joint(optional,registry,evidence,tmp_path):
    return load_type_size_evidence(optional,registry,evidence,tmp_path)


@pytest.mark.parametrize('n',[1000,10000])
def test_fitted_margins_association_tail_and_ess(optional,registry,evidence,joint,n):
    pop=generate_type_size(evidence,joint,HouseholdConfig(synthetic_size=n),registry,optional)
    result=validate_type_size(pop)
    assert result['max_size_relative_error']<1e-10 and result['max_type_relative_error']<1e-10
    assert result['max_transferred_log_odds_error']<1e-9 and result['association_checks']>0
    assert result['structural_violations']==0 and result['linked_residents']==0
    assert 0<result['effective_sample_size']<=n
    assert math.isclose(result['represented_households'],550,rel_tol=1e-12)
    assert all(r.household_weight>0 and math.isfinite(r.household_weight) for r in pop.records)
    assert all(r.household_size is None and r.household_size_upper is None for r in pop.records if r.household_size_class=='10+')
    assert all(r.household_type_size_band=='7+' for r in pop.records if r.household_size_class in ('7','8','9','10+'))
    assert pop.manifest['fit']['tail_policy']=='exchangeable_within_observed_7plus_v1'
    assert set(dataclasses.asdict(pop.records[0])).isdisjoint({'resident_id','population_weight','income','members'})


def test_repeat_identity_and_distinct_legacy_schema(optional,registry,evidence,joint,tmp_path):
    config=HouseholdConfig()
    before=size_only(evidence,config,registry)
    a=generate_type_size(evidence,joint,config,registry,optional)
    b=generate_type_size(evidence,joint,config,registry,optional)
    assert a==b
    changed=generate_type_size(evidence,joint,HouseholdConfig(seed=43),registry,optional)
    assert changed.records!=a.records and changed.manifest['identity_sha256']!=a.manifest['identity_sha256']
    assert before==size_only(evidence,config,registry)
    assert 'household_type' not in SIZE_SCHEMA.names and 'household_type' in SCHEMA.names
    dirs=[]
    for name in ['a','b']:
        store=TypeSizeStore(tmp_path/name);p=store.write(a);dirs.append(p)
        assert store.load(p.name).records==a.records
        hashes={f.name:sha256_file(f) for f in p.iterdir()}
        assert store.write(a)==p and hashes=={f.name:sha256_file(f) for f in p.iterdir()}
    assert {p.name:sha256_file(p) for p in dirs[0].iterdir()}=={p.name:sha256_file(p) for p in dirs[1].iterdir()}
    with pytest.raises(HouseholdError):HouseholdStore(dirs[0].parent).load(dirs[0].name)


def test_default_disabled(optional,registry,evidence,joint):
    assert load_type_size_registry().enabled is False
    disabled=TypeSizeRegistry.model_validate(optional.model_dump(mode='json')|{'enabled':False})
    with pytest.raises(HouseholdError,match='disabled'):
        generate_type_size(evidence,joint,HouseholdConfig(),registry,disabled)


def test_service_explicit_activation_and_schema(optional,registry,tmp_path):
    import yaml
    from societytwin.households.service import build
    base_path=tmp_path/'base.yaml';type_path=tmp_path/'type.yaml'
    bp=registry.model_dump(mode='json');bp['module']['enabled']=False
    tp=optional.model_dump(mode='json');tp['enabled']=False
    base_path.write_text(yaml.safe_dump(bp),encoding='utf-8');type_path.write_text(yaml.safe_dump(tp),encoding='utf-8')
    before=(base_path.read_bytes(),type_path.read_bytes())
    output=tmp_path/'data/results/type-test'
    with pytest.raises(HouseholdError,match='disabled'):
        build(HouseholdConfig(),type_size=True,repo_root=tmp_path,output_root=output)
    assert not output.exists()
    path=build(HouseholdConfig(),enable_households=True,type_size=True,registry_path=base_path,
               type_size_registry_path=type_path,repo_root=tmp_path,output_root=output)
    assert TypeSizeStore(output).load(path.name).manifest['schema_version']=='household-type-size-schema-1'
    assert (base_path.read_bytes(),type_path.read_bytes())==before


@pytest.mark.parametrize('counts,message',[
    ((100,300,80,71),'incompatible'),((99,301,80,70),'one-person'),
    ((100,10,400,40),'infeasible'),((100,300,150,0),'nonpositive')])
def test_incompatible_infeasible_margins(evidence,joint,counts,message):
    with pytest.raises(HouseholdError,match=message):fit_targets(evidence.counts,counts,joint.national)


def test_seed_support_and_convergence_guards(evidence,joint):
    bad=[list(r) for r in joint.national];bad[0][1]=1
    with pytest.raises(HouseholdError,match='support'):fit_targets(evidence.counts,joint.type_counts,bad)
    with pytest.raises(HouseholdError,match='converge'):fit_targets(evidence.counts,joint.type_counts,joint.national,max_iter=1)


def test_small_sample_fails_without_dropping_cells(optional,registry,evidence,joint):
    with pytest.raises(HouseholdError,match='too small'):
        generate_type_size(evidence,joint,HouseholdConfig(synthetic_size=10),registry,optional)


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(tail_policy='invent_fine_tail'),
    lambda p:p.update(types=['one_person','lone_parent','nuclear_family']),
    lambda p:p.update(scope='person'),
    lambda p:p['national'].update(unit='person'),
    lambda p:p['national'].update(reference_year=2024),
    lambda p:p['national'].update(evidence='observed_marginal_counts'),
    lambda p:p['attributes']['household_type'].update(parents=['age']),
])
def test_invalid_registry(optional,mutation):
    payload=optional.model_dump(mode='json');mutation(payload)
    with pytest.raises(ValidationError):TypeSizeRegistry.model_validate(payload)


@pytest.mark.parametrize('old,new,message',[
    ('2025,TR,','2024,TR,','year/geography'),
    ('one_person,2,,NOT_APPLICABLE','one_person,2,,UNKNOWN','suppressed'),
    ('one_person,2,,NOT_APPLICABLE','one_person,2,1,OBSERVED','support'),
    ('one_person,1,1000,OBSERVED','one_person,1,0,OBSERVED','zero'),
    ('nuclear_family,2,300,OBSERVED','nuclear_family,2,301,OBSERVED','partition'),
])
def test_invalid_source_observations(optional,registry,evidence,tmp_path,old,new,message):
    path=tmp_path/'national.csv';text=path.read_text();assert old in text
    path.write_text(text.replace(old,new),encoding='utf-8')
    payload=optional.model_dump(mode='json');payload['national']['sha256']=sha256_file(path)
    with pytest.raises(HouseholdError,match=message):
        load_type_size_evidence(TypeSizeRegistry.model_validate(payload),registry,evidence,tmp_path)


def test_source_checksum_and_denominator_guards(optional,registry,evidence,tmp_path):
    local=tmp_path/'types.csv';local.write_bytes(local.read_bytes()+b'\n')
    with pytest.raises(HouseholdError,match='checksum'):load_type_size_evidence(optional,registry,evidence,tmp_path)
    local.write_text(local.read_text().replace('total,550','total,551'),encoding='utf-8')
    payload=optional.model_dump(mode='json');payload['ankara_types']['sha256']=sha256_file(local)
    with pytest.raises(HouseholdError,match='denominators'):
        load_type_size_evidence(TypeSizeRegistry.model_validate(payload),registry,evidence,tmp_path)


@pytest.mark.parametrize('kind',['structural','tail','weight','provenance'])
def test_record_corruption_rejected(optional,registry,evidence,joint,kind):
    pop=generate_type_size(evidence,joint,HouseholdConfig(),registry,optional)
    r=next(r for r in pop.records if r.household_size_class=='10+')
    updates={'structural':{'household_type':'one_person'},'tail':{'household_size':10},
             'weight':{'household_weight':float('nan')},'provenance':{'provenance_profile':'invented'}}[kind]
    records=tuple(dataclasses.replace(x,**updates) if x.household_id==r.household_id else x for x in pop.records)
    with pytest.raises(HouseholdError):validate_type_size(dataclasses.replace(pop,records=records))


def test_independence_sensitivity_differs(evidence,joint):
    observed=fit_targets(evidence.counts,joint.type_counts,joint.national)
    flat=[[1 if allowed(i,j) else 0 for j in range(4)] for i in range(7)]
    sensitivity=fit_targets(evidence.counts,joint.type_counts,flat)
    assert observed['coarse_targets']!=sensitivity['coarse_targets']
