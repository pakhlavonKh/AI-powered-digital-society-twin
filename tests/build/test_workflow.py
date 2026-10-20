import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from societytwin.build.config import BuildConfig, BuildError, load_config
from societytwin.build.workflow import build, inspect_build, prepare
from societytwin.common import sha256_file
from societytwin.national.generator import GenerationConfig, generate
from societytwin.national.store import PopulationStore
from tests.national.conftest import national_settings, store  # noqa: F401
from tests.households.conftest import registry, evidence  # noqa: F401
from tests.households.test_type_size import optional  # noqa: F401


@pytest.fixture
def config(store,national_settings,tmp_path):
    return BuildConfig(inputs={'controls_directory':national_settings.national_controls_dir},
                       resident_sample_size=1000,output_root=tmp_path/'bundles')


def test_defaults():
    c=BuildConfig()
    assert not c.resident_enrichments and not c.households.enabled and c.marital.strategy=='default'


@pytest.mark.parametrize('payload',[
    {'province_code':'34'},{'reference_year':2024},{'seed':-1},{'seed':True},
    {'resident_sample_size':0},{'resident_sample_size':1000.5},
    {'resident_enrichments':['literacy_status']},{'resident_enrichments':['degurba_class']*2},
    {'households':{'strategy':'national_household_type_size_seed_v1'}},
    {'households':{'enabled':'yes'}},{'households':{'enabled':True,'sample_size':0}},
    {'marital':{'sensitivity':'midpoint'}},
    {'marital':{'strategy':'national_age_marital_seed_v1'}},
    {'marital':{'strategy':'national_age_marital_seed_v1','sensitivity':'midpoint','acknowledge_unverified_rounding':False}},
    {'validation':{'familywise_alpha':1.}},{'unexpected':True},
])
def test_invalid(payload):
    with pytest.raises(ValidationError):BuildConfig.model_validate(payload)


def test_yaml(tmp_path):
    p=tmp_path/'config.yaml';p.write_text('schema_version: ankara-build-config-1\nresident_sample_size: 1000\n')
    assert load_config(p).resident_sample_size==1000
    p.write_text('seed: 42\nseed: 43\n')
    with pytest.raises(BuildError):load_config(p)


def test_core_compatibility(config,store):
    direct=generate(store,GenerationConfig(synthetic_size=1000,seed=42,provinces=('06',)))
    path=build(config)
    m=inspect_build(path)
    loaded=PopulationStore(path/'residents').load(m['artifacts']['residents']['id'])
    assert loaded.columns()==direct.columns
    assert set(m['artifacts'])=={'residents'}
    hashes={p.relative_to(path):sha256_file(p) for p in path.rglob('*') if p.is_file()}
    assert build(config)==path
    assert hashes=={p.relative_to(path):sha256_file(p) for p in path.rglob('*') if p.is_file()}


def test_independent_output_roots(config):
    first=build(config)
    c=BuildConfig.model_validate(config.model_dump()|{'output_root':config.output_root.parent/'other'})
    second=build(c)
    assert first.name==second.name
    a=inspect_build(first);b=inspect_build(second)
    assert a['artifacts']==b['artifacts']
    assert a['identity']==b['identity']
    assert sha256_file(next(first.rglob('records.parquet')))==sha256_file(next(second.rglob('records.parquet')))


def test_missing_inputs(config):
    c=BuildConfig.model_validate(config.model_dump()|{'inputs':{'controls_directory':config.output_root.parent/'absent'}})
    with pytest.raises(FileNotFoundError):build(c)
    assert not config.output_root.exists()


def test_failure_after_resident_write(config,monkeypatch):
    import societytwin.build.workflow as workflow
    original=workflow._execute
    def fail(stage,c,p):
        original(stage,c,p)
        raise BuildError('injected failure after generated artifacts')
    monkeypatch.setattr(workflow,'_execute',fail)
    with pytest.raises(BuildError,match='injected'):build(config)
    assert list(config.output_root.iterdir())==[]


def test_corrupt_existing_is_not_overwritten(config):
    path=build(config)
    p=next(path.rglob('records.parquet'));p.write_bytes(b'corrupt')
    with pytest.raises(BuildError,match='checksums'):build(config)
    assert p.read_bytes()==b'corrupt'


def test_incomplete_existing_is_not_overwritten(config):
    identity=prepare(config)['build_id']
    target=config.output_root/identity;target.mkdir(parents=True)
    marker=target/'keep.txt';marker.write_text('existing')
    with pytest.raises(FileNotFoundError):build(config)
    assert marker.read_text()=='existing'


def test_output_guards(config):
    bad=BuildConfig.model_validate(config.model_dump()|{'output_root':Path('src/forbidden')})
    with pytest.raises(BuildError,match='ignored'):prepare(bad)
    overlap=BuildConfig.model_validate(config.model_dump()|{'output_root':config.inputs.controls_directory})
    with pytest.raises(BuildError,match='overlaps'):prepare(overlap)


def test_validation_settings_in_identity(config):
    strict=BuildConfig.model_validate(config.model_dump()|{'validation':{'fail_on_unfitted_margins':True}})
    assert prepare(strict)['build_id']!=prepare(config)['build_id']


@pytest.fixture
def extension_registry(config,store,tmp_path):
    from societytwin.enrichment.registry import load_registry, ExtensionRegistry
    from societytwin.national import geography
    root=store.best('population_age_sex',geography.province('06'),2025)
    counts={s:int(sum(r.value for r in root.rows if r.sex==s)) for s in ('male','female')}
    lines=['province_code,year,sex,category,count,value_status']
    for sex,total in counts.items():
        a=total*7//10;b=total//5
        for category,n in zip(('dense_urban','intermediate_urban','rural'),(a,b,total-a-b)):
            lines.append(f'06,2025,{sex},{category},{n},OBSERVED')
    p=tmp_path/'artificial-extension.csv';p.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    payload=load_registry().model_dump(mode='json')
    payload['attributes']['degurba_class']['source'].update(path=str(p),sha256=sha256_file(p),title='ARTIFICIAL test counts')
    return ExtensionRegistry.model_validate(payload)


@pytest.mark.parametrize('hh_strategy',['disabled','size_only','national_household_type_size_seed_v1'])
@pytest.mark.parametrize('with_extension',[False,True])
def test_optional_combinations(config,registry,optional,extension_registry,hh_strategy,with_extension,tmp_path):
    paths={}
    for name,obj in [('household_registry',registry),('household_type_registry',optional),('enrichment_registry',extension_registry)]:
        p=tmp_path/f'{name}.yaml';p.write_text(yaml.safe_dump(obj.model_dump(mode='json')),encoding='utf-8');paths[name]=p
    payload=config.model_dump()
    payload['inputs'].update(paths)
    payload['resident_enrichments']=['degurba_class'] if with_extension else []
    payload['households']={'enabled':hh_strategy!='disabled','strategy':hh_strategy if hh_strategy!='disabled' else 'size_only'}
    c=BuildConfig.model_validate(payload)
    base=build(config);baseline=inspect_build(base)
    built=build(c);m=inspect_build(built)
    assert m['artifacts']['residents']==baseline['artifacts']['residents']
    assert ('households' in m['artifacts'])==(hh_strategy!='disabled')
    assert ('enrichments' in m['artifacts'])==with_extension
    assert m['household_person_linkage'] is False
    if hh_strategy!='disabled':
        assert m['validation']['households']['linked_residents']==0
    assert build(c)==built


def test_selected_source_missing_preflight(config,extension_registry,tmp_path):
    payload=extension_registry.model_dump(mode='json')
    payload['attributes']['degurba_class']['source']['path']=str(tmp_path/'missing.csv')
    p=tmp_path/'registry.yaml';p.write_text(yaml.safe_dump(payload))
    data=config.model_dump();data['inputs']['enrichment_registry']=p;data['resident_enrichments']=['degurba_class']
    with pytest.raises(ValueError,match='unavailable'):build(BuildConfig.model_validate(data))
    assert not config.output_root.exists()


def test_constraint_failure_is_not_published(config,monkeypatch):
    import societytwin.build.workflow as workflow
    original=workflow.validate
    def failure(*args,**kwargs):
        report=original(*args,**kwargs);report['constraint_violations']=1
        return report
    monkeypatch.setattr(workflow,'validate',failure)
    with pytest.raises(BuildError,match='constraint'):build(config)
    assert list(config.output_root.iterdir())==[]


def test_cli(config,tmp_path):
    import os
    import subprocess
    import sys
    p=tmp_path/'build.yaml';p.write_text(yaml.safe_dump(config.model_dump(mode='json')))
    environment={**os.environ,'PYTHONPATH':'src','PYTHONDONTWRITEBYTECODE':'1'}
    run=subprocess.run([sys.executable,'-B','-m','societytwin.build','run','--config',str(p)],env=environment,capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    inspect=subprocess.run([sys.executable,'-B','-m','societytwin.build','inspect',run.stdout.strip()],env=environment,capture_output=True,text=True)
    assert inspect.returncode==0,inspect.stderr
    assert set(json.loads(inspect.stdout)['artifacts'])=={'residents'}
    p.write_text('province_code: bad')
    invalid=subprocess.run([sys.executable,'-B','-m','societytwin.build','run','--config',str(p)],env=environment,capture_output=True,text=True)
    assert invalid.returncode==2 and 'Invalid unified build configuration' in invalid.stderr
