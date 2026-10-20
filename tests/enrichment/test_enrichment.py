from dataclasses import replace

import pyarrow as pa
import pytest
from pydantic import ValidationError

from societytwin.common import sha256_bytes, sha256_file
from societytwin.enrichment.engine import generate, validate
from societytwin.enrichment.model import EnrichmentConfig, ResidentExtension
from societytwin.enrichment.registry import load_registry, ExtensionRegistry, EnrichmentError
from societytwin.enrichment.store import ExtensionStore
from societytwin.enrichment.service import build
from societytwin.national.store import LoadedPopulation


@pytest.fixture
def setup(tmp_path):
    rows=[{'synthetic_id':f'resident-{i:03}','sex':sex,'age':age,'province_code':'06','reference_year':2025,
           'population_weight':1.,'design_weight':1.} for i,(sex,age) in enumerate((s,a) for s in ('male','female') for a in range(10))]
    core=LoadedPopulation({'population_id':'pop-test'},pa.Table.from_pylist(rows),None,tmp_path/'core')
    raw=b'province_code,year,sex,category,count,value_status\n'
    for sex in ('male','female'):
        for c,n in [('dense_urban',7),('intermediate_urban',2),('rural',1)]:
            raw+=f'06,2025,{sex},{c},{n},OBSERVED\n'.encode()
    (tmp_path/'source.csv').write_bytes(raw)
    payload=load_registry().activated().model_dump(mode='json')
    payload['attributes']['degurba_class']['source'].update(path='source.csv',sha256=sha256_bytes(raw))
    registry=ExtensionRegistry.model_validate(payload)
    return core,registry,tmp_path


def test_disabled():
    with pytest.raises(EnrichmentError,match='disabled'):build('missing','missing')
    assert not any(m.enabled for m in load_registry().modules.values())


def test_repeat_storage_core_unchanged(setup):
    core,r,root=setup;before=core.table.to_pylist()
    a=generate(core,r,root=root);b=generate(core,r,root=root)
    assert a==b
    assert validate(a,core)['statuses']=={'assigned':20}
    stores=[ExtensionStore(root/x) for x in ('a','b')]
    paths=[s.write(a,core) for s in stores]
    for filename in ('attributes.parquet','manifest.json','validation.json'):
        assert sha256_file(paths[0]/filename)==sha256_file(paths[1]/filename)
    assert stores[0].load(a.manifest['artifact_id'],core).records==a.records
    assert stores[0].write(a,core)==paths[0]
    assert core.table.to_pylist()==before
    assert all('weight' not in field for field in stores[0].load(a.manifest['artifact_id'],core).records[0].model_dump())


def test_seed_and_order(setup):
    core,r,root=setup
    a=generate(core,r,root=root)
    reversed_core=replace(core,table=core.table.take(pa.array(list(reversed(range(20))))))
    b=generate(reversed_core,r,root=root)
    assert a==b
    assert a.records!=generate(core,r,EnrichmentConfig(seed=43),root=root).records


@pytest.mark.parametrize('field,value',[('method','arbitrary'),('parents',['age']),('scope','household'),
    ('assumption','unjustified'),('evidence_class','A'),('max_age',-1)])
def test_invalid_attribute(setup,field,value):
    _,r,_=setup;d=r.model_dump(mode='json');d['attributes']['degurba_class'][field]=value
    with pytest.raises(ValidationError):ExtensionRegistry.model_validate(d)


@pytest.mark.parametrize('field,value',[('dimensions',['province_code','category']),('universe','citizens'),
    ('unit','household'),('reference_year',2024),('province_code','34'),('evidence','modelled')])
def test_invalid_source(setup,field,value):
    _,r,_=setup;d=r.model_dump(mode='json');d['attributes']['degurba_class']['source'][field]=value
    with pytest.raises(ValidationError):ExtensionRegistry.model_validate(d)


def change_source(r,root,old,new):
    raw=(root/'source.csv').read_bytes().replace(old,new)
    (root/'source.csv').write_bytes(raw)
    d=r.model_dump(mode='json');d['attributes']['degurba_class']['source']['sha256']=sha256_bytes(raw)
    return ExtensionRegistry.model_validate(d)


def test_missing_source(setup):
    core,r,root=setup;(root/'source.csv').unlink()
    with pytest.raises(EnrichmentError,match='unavailable'):generate(core,r,root=root)
    d=r.model_dump(mode='json');d['attributes']['degurba_class']['missing_source']='unavailable'
    result=generate(core,ExtensionRegistry.model_validate(d),root=root)
    assert validate(result,core)['statuses']=={'unsupported':20}


def test_nonreported_distinct_from_unknown(setup):
    core,r,root=setup
    r=change_source(r,root,b'male,rural,1,OBSERVED',b'male,rural,,NOT_REPORTED')
    e=generate(core,r,root=root)
    # Both sexes match this byte replacement: no partial-distribution renormalization.
    assert validate(e,core)['statuses']=={'not_reported':20}


def test_published_unknown(setup):
    core,r,root=setup;d=r.model_dump(mode='json')
    d['attributes']['degurba_class']['categories'][0]['kind']='published_unknown'
    e=generate(core,ExtensionRegistry.model_validate(d),root=root)
    assert validate(e,core)['statuses']['published_unknown']>0


def test_outside_universe(setup):
    core,r,root=setup
    d=r.model_dump(mode='json');d['attributes']['degurba_class']['min_age']=5
    r=change_source(ExtensionRegistry.model_validate(d),root,b'dense_urban,7',b'dense_urban,2')
    e=generate(core,r,root=root)
    assert validate(e,core)['statuses']['outside_universe']==10
    assert all(v.value is None for rec in e.records for v in rec.attributes if v.status=='outside_universe')


@pytest.mark.parametrize('mutation',['hash','denominator','missing_cell','duplicate_cell','zero_total'])
def test_invalid_observations(setup,mutation):
    core,r,root=setup
    if mutation=='hash':(root/'source.csv').write_bytes(b'bad')
    elif mutation=='denominator':r=change_source(r,root,b'dense_urban,7',b'dense_urban,8')
    elif mutation=='missing_cell':r=change_source(r,root,b'06,2025,male,rural,1,OBSERVED\n',b'')
    elif mutation=='duplicate_cell':r=change_source(r,root,b'06,2025,male,rural,1,OBSERVED\n',b'06,2025,male,rural,1,OBSERVED\n'*2)
    else:
        for old in (b',7,',b',2,',b',1,'):r=change_source(r,root,old,b',0,')
    with pytest.raises(EnrichmentError):generate(core,r,root=root)


@pytest.mark.parametrize('mutation',['ids','weight','year','province'])
def test_invalid_core(setup,mutation):
    core,r,root=setup;rows=core.table.to_pylist()
    if mutation=='ids':rows[0]['synthetic_id']=rows[1]['synthetic_id']
    elif mutation=='weight':rows[0]['population_weight']=float('nan')
    elif mutation=='year':rows[0]['reference_year']=2024
    else:rows[0]['province_code']='34'
    with pytest.raises(EnrichmentError):generate(replace(core,table=pa.Table.from_pylist(rows)),r,root=root)


def test_binding_integrity(setup):
    core,r,root=setup;e=generate(core,r,root=root)
    with pytest.raises(EnrichmentError):validate(ResidentExtension(e.records[:-1],e.manifest),core)
    rows=core.table.to_pylist();rows[0]['population_weight']=2.
    with pytest.raises(EnrichmentError,match='binding'):validate(e,replace(core,table=pa.Table.from_pylist(rows)))
    store=ExtensionStore(root/'extensions');path=store.write(e,core)
    with (path/'attributes.parquet').open('ab') as f:f.write(b'corrupt')
    with pytest.raises(EnrichmentError,match='checksum'):store.load(e.manifest['artifact_id'],core)
    with pytest.raises(EnrichmentError):store.write(e,core)


def test_independent_generic_attributes(setup):
    core,r,root=setup
    original=generate(core,r,root=root)
    d=r.model_dump(mode='json')
    d['attributes']['another_class']=d['attributes']['degurba_class'].copy()
    combined=generate(core,ExtensionRegistry.model_validate(d),root=root)
    assert validate(combined,core)['statuses']=={'assigned':40}
    assert [next(v for v in rec.attributes if v.attribute=='degurba_class') for rec in combined.records]==[rec.attributes[0] for rec in original.records]


@pytest.mark.parametrize('mutation',['parent','override','categories','module'])
def test_registry_bindings(setup,mutation):
    core,r,root=setup;d=r.model_dump(mode='json')
    if mutation=='parent':d['parent_registry_version']='future'
    elif mutation=='override':d['attributes']['sex']=d['attributes'].pop('degurba_class')
    elif mutation=='categories':d['attributes']['degurba_class']['categories'][1]=d['attributes']['degurba_class']['categories'][0]
    else:d['attributes']['degurba_class']['module']='missing'
    with pytest.raises((EnrichmentError,ValidationError)):
        generate(core,ExtensionRegistry.model_validate(d),root=root)


def test_observed_zero_not_missing(setup):
    core,r,root=setup
    r=change_source(r,root,b'rural,1',b'rural,0')
    r=change_source(r,root,b'dense_urban,7',b'dense_urban,8')
    e=generate(core,r,root=root)
    assert validate(e,core)['statuses']=={'assigned':20}
    assert all(v.value!='rural' for rec in e.records for v in rec.attributes)


def test_storage_is_separate(setup):
    core,r,root=setup;e=generate(core,r,root=root)
    with pytest.raises(EnrichmentError,match='separate'):ExtensionStore(core.directory).write(e,core)


def test_disabled_engine(setup):
    core,r,root=setup;d=r.model_dump(mode='json');d['modules']['optional_resident']['enabled']=False
    with pytest.raises(EnrichmentError,match='disabled'):generate(core,ExtensionRegistry.model_validate(d),root=root)
