"""Offline DST projection tests; actual upstream loading is explicitly opt-in.

Set SOCIETYTWIN_TEST_PROJECTION_ROOT and SOCIETYTWIN_TEST_PROJECTION_PYTHON.
For a Linux runtime from Windows, also set SOCIETYTWIN_TEST_PROJECTION_WSL_DISTRO.
The external check calls schema/loader/templates only, never an agent or provider.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from societytwin.national.matraix_projection import (
    CROSSWALK, CROSSWALK_VERSION, ProjectionError, validate_catalog_dimensions,
)
from societytwin.national.personas import build_persona, matraix_persona


@pytest.fixture
def persona():
    record = {'synthetic_id': 'resident-TRACE-ONLY', 'provenance_profile': 'p1',
              'province_code': '63', 'province_name': 'Şanlıurfa', 'age': 32,
              'age_group': '30-34', 'age_top_coded': False, 'sex': 'female',
              'marital_status': 'never_married', 'education_level': 'higher_education',
              'labour_status': 'employed', 'household_size_class': None,
              'household_type': None, 'urbanicity': 'town_village', 'reference_year': 2025,
              'population_weight': 8765.4321, 'design_weight': 9123.4567}
    profile = {'fields': {'province_code': {'source_ids': ['SOURCE-CONTROL-SECRET'],
                                          'source_year': 2025, 'evidence': 'DIRECT_SOURCE'},
                          'sex': {'evidence': 'DIRECT_SOURCE'},
                          'education_level': {'limitations': ['RESEARCHER-ONLY-LIMITATION']}}}
    manifest = {'population_id': 'population-TRACE-ONLY', 'profiles': {'p1': profile},
                'generator_version': 'invented-fixture', 'seed': 42, 'reference_year': 2025}
    return build_persona(record, manifest)


def change_visible(persona, field, value, text):
    entry = next(a for a in persona['attributes'] if a['field'] == field)
    entry.update(value=value, display=text, status='visible')
    persona['model_visible'][field] = text
    persona['model_visible_fields'] = sorted(persona['model_visible'])


def test_core_projection_and_traceability(persona):
    doc = matraix_persona(persona)
    assert doc['dimensions']['dst_sex'] == 'Female'
    assert doc['dimensions']['dst_marital_status'] == 'Never married'
    assert doc['dimensions']['dst_education_level'] == "Higher education (associate or bachelor's)"
    assert doc['persona_id'] == persona['synthetic_id']
    assert doc['metadata']['resident_identity'] == {k: persona[k] for k in ('population_id', 'synthetic_id', 'persona_id')}
    assert doc['metadata']['projection']['crosswalk_version'] == CROSSWALK_VERSION
    assert doc['display_name'] == 'Resident'


@pytest.mark.parametrize('code,text', [('married', 'Married'), ('divorced', 'Divorced'), ('widowed', 'Widowed')])
def test_exact_marital_values(persona, code, text):
    change_visible(persona, 'marital_status', code, text)
    doc = matraix_persona(persona)
    assert doc['dimensions']['demo_marital_status'] == text
    decision = next(d for d in doc['metadata']['projection']['decisions'] if d['field'] == 'marital_status')
    assert decision['classification'] == 'exact'
    # A deliberately tiny synthetic catalog tests DST's validator logic, not
    # upstream compatibility. The opt-in test below checks the real schema.
    catalog = {'schemaVersion': '1.0', 'dimensions': [{'id': 'demo_marital_status', 'values': [text]}]}
    assert matraix_persona(persona, catalog=catalog)['metadata']['projection']['catalog_assessment']['status'] == 'compatible'


def test_ambiguous_and_lossy_mappings_stay_custom(persona):
    doc = matraix_persona(persona)
    assert not {'gender_identity', 'demo_marital_status', 'highest_education', 'age_bracket',
                'demo_employment_status', 'lstyle_household_size'} & doc['dimensions'].keys()
    assert doc['metadata']['projection']['lossy_transformations'] == []
    decisions = {d['field']: d for d in doc['metadata']['projection']['decisions']}
    assert decisions['sex']['classification'] == 'unsupported'
    assert decisions['marital_status']['classification'] == 'unsupported'
    assert decisions['education_level']['classification'] == 'lossy'
    assert decisions['age_group']['classification'] == 'lossy'


@pytest.mark.parametrize('value,text', [('unknown', 'Unknown'), ('future_source_code', 'Bilinmeyen / belirtilmemiş')])
def test_unknown_values_are_preserved_without_defaults(persona, value, text):
    change_visible(persona, 'education_level', value, text)
    doc = matraix_persona(persona)
    assert doc['dimensions']['dst_education_level'] == text
    assert 'highest_education' not in doc['dimensions']
    assert 'gender_identity' not in doc['dimensions']


def test_unavailable_not_applicable_and_hidden_fields_not_invented(persona):
    for field in ('sex', 'marital_status'):
        persona['model_visible'].pop(field)
        entry = next(a for a in persona['attributes'] if a['field'] == field)
        entry.update(value=None, status='unavailable')
    persona['model_visible_fields'] = sorted(persona['model_visible'])
    doc = matraix_persona(persona)
    assert not {'dst_sex', 'dst_marital_status', 'dst_age', 'dst_household_size_class'} & doc['dimensions'].keys()
    decisions = {d['field']: d for d in doc['metadata']['projection']['decisions']}
    assert decisions['sex']['status'] == 'unavailable'
    assert decisions['age']['action'] == 'omitted'


def test_unicode_yaml_roundtrip(persona):
    change_visible(persona, 'marital_status', 'never_married', 'Hiç evlenmedi')
    doc = matraix_persona(persona)
    encoded = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    assert 'Şanlıurfa' in encoded and 'Hiç evlenmedi' in encoded
    assert yaml.safe_load(encoded) == doc


def test_researcher_metadata_remains_outside_dimensions(persona):
    doc = matraix_persona(persona)
    visible_text = json.dumps(doc['dimensions'], ensure_ascii=False)
    for hidden in ('8765.4321', '9123.4567', 'SOURCE-CONTROL-SECRET', 'RESEARCHER-ONLY-LIMITATION',
                   persona['population_id'], persona['synthetic_id'], 'population_weight', 'provenance_profile'):
        assert hidden not in visible_text
    assert 'summary' not in doc and 'system_prompt' not in doc
    assert doc['metadata']['provenance']['source_ids'] == ['SOURCE-CONTROL-SECRET']


@pytest.mark.parametrize('field', ['population_weight', 'design_weight', 'provenance_profile',
                                 'calibration', 'source_ids', 'dst_unreviewed_graph_score'])
def test_no_arbitrary_field_passthrough(persona, field):
    persona['model_visible'][field] = 'SECRET'
    with pytest.raises(ProjectionError, match='Unregistered'):
        matraix_persona(persona)


def test_explicit_field_selection_is_respected(persona):
    persona['model_visible'] = {'sex': 'Female'}
    persona['model_visible_fields'] = ['sex']
    persona['field_selection'] = {'config': {'allowlist': ['sex'], 'required': ['sex'], 'optional': []},
                                  'resolution': []}
    doc = matraix_persona(persona)
    assert doc['dimensions'] == {'dst_sex': 'Female'}
    assert doc['metadata']['field_selection'] == persona['field_selection']
    persona['field_selection']['config']['allowlist'] = []
    with pytest.raises(ProjectionError, match='selection'):
        matraix_persona(persona)


@pytest.mark.parametrize('status', ['hidden', 'unavailable', 'not_applicable', 'unsupported'])
def test_conflicting_availability_fails_closed(persona, status):
    next(a for a in persona['attributes'] if a['field'] == 'sex')['status'] = status
    with pytest.raises(ProjectionError, match='availability'):
        matraix_persona(persona)


def test_sidecar_display_preserved_only_when_selected(persona):
    text = 'dense urban. Synthetic fixture; no observed individual address.'
    persona['attributes'].append({'field': 'degurba_class', 'value': 'dense_urban', 'display': text, 'status': 'assigned'})
    assert 'dst_degurba_class' not in matraix_persona(persona)['dimensions']
    persona['model_visible']['degurba_class'] = text
    persona['model_visible_fields'] = sorted(persona['model_visible'])
    assert matraix_persona(persona)['dimensions']['dst_degurba_class'] == text


def test_determinism_read_only_and_detached_metadata(persona):
    before = deepcopy(persona)
    a, b = matraix_persona(persona), matraix_persona(persona)
    assert a == b and persona == before
    reordered = deepcopy(persona)
    reordered['model_visible'] = dict(reversed(list(reordered['model_visible'].items())))
    assert a == matraix_persona(reordered)
    a['metadata']['provenance']['source_ids'].clear()
    assert persona == before


@pytest.mark.parametrize('catalog', [
    {'schemaVersion': '1.0', 'dimensions': []},
    {'schemaVersion': '1.0', 'dimensions': [{'id': 'demo_marital_status', 'values': ['Single']}]},
    {'schemaVersion': 'future', 'dimensions': [{'id': 'demo_marital_status', 'values': ['Married']}]},
])
def test_catalog_drift_fails_explicitly(persona, catalog):
    change_visible(persona, 'marital_status', 'married', 'Married')
    with pytest.raises(ProjectionError, match='Unsupported'):
        matraix_persona(persona, catalog=catalog)


def test_custom_fields_are_extensions_not_catalog_enum_claims(persona):
    doc = matraix_persona(persona)
    report = validate_catalog_dimensions(doc, {'schemaVersion': '1.0', 'dimensions': []})
    assert report['status'] == 'compatible' and not report['catalog_dimensions']
    assert set(report['custom_dimensions']) == set(doc['dimensions'])
    assert len(CROSSWALK) == len({r.field for r in CROSSWALK}) == 12


def test_relocatable_package_layout_without_checkout_or_catalog(persona, tmp_path):
    source = Path(__file__).resolve().parents[2] / 'src' / 'societytwin'
    site = tmp_path / 'site-packages'
    shutil.copytree(source, site / 'societytwin', ignore=shutil.ignore_patterns('__pycache__'))
    script = ('import sys,json; sys.stdin.reconfigure(encoding="utf-8"); '
              'sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0,sys.argv[1]); '
              'from societytwin.national.personas import matraix_persona; '
              'd=matraix_persona(json.load(sys.stdin)); '
              'assert not any(k=="matraix" or k.startswith("matraix.") for k in sys.modules); '
              'print(json.dumps(d,ensure_ascii=False))')
    run = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(site)], cwd=tmp_path,
                         input=json.dumps(persona, ensure_ascii=False), text=True, encoding='utf-8',
                         capture_output=True, timeout=30, check=True)
    assert json.loads(run.stdout) == matraix_persona(persona)


# Real upstream APIs, not stand-ins. Credential-free env, sockets denied, only
# temporary YAML writes. -I -B prevents import-path/bytecode pollution.
UPSTREAM_PROBE = r'''
import hashlib,json,os,socket,sys,tempfile
from pathlib import Path
root=Path(sys.argv[1]).resolve()
def deny(*args,**kwargs):
    raise RuntimeError('Network is forbidden in the projection contract probe')
socket.socket.connect=deny
socket.create_connection=deny
sys.path[:0]=[str(root),str(root/'src'),str(root/'environment/agents')]
os.chdir(root)
import yaml
from persona.extraction.schema import load_schema
from matraix.agents.persona.loader import load_persona
from matraix.agents.persona.templating import default_templates_dir,render_persona_template
from matraix.persona_dimension_catalog import build_dimension_narrative
catalog_path=root/'persona/schema/dimensions.json'
schema=load_schema(catalog_path)
results=[]
with tempfile.TemporaryDirectory(prefix='dst-projection-') as temporary:
    for index,doc in enumerate(json.load(sys.stdin)):
        path=Path(temporary)/f'persona-{index}.yaml'
        path.write_text(yaml.safe_dump(doc,allow_unicode=True,sort_keys=False),encoding='utf-8')
        loaded=load_persona(path)
        assert loaded.dimensions==doc['dimensions']
        native=[k for k in loaded.dimensions if not k.startswith('dst_')]
        assert all(schema.is_valid_value(k,loaded.dimensions[k]) for k in native)
        results.append({'dimensions':loaded.dimensions,'metadata':loaded.data['metadata'],
            'native_validated':native,'persona_id':loaded.persona_id,
            'system':render_persona_template(default_templates_dir()/'persona_system.md.j2',loaded),
            'instruction':render_persona_template(default_templates_dir()/'persona_instruction.md.j2',loaded,instruction='OFFLINE TEST TASK'),
            'narrative':'\n'.join(build_dimension_narrative(loaded.dimensions,catalog_path=str(catalog_path)))})
print(json.dumps({'schema_count':len(schema),'catalog_sha256':hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
                  'python':sys.version.split()[0],'results':results},ensure_ascii=False))
'''


@pytest.mark.matraix
def test_actual_upstream_schema_loading_and_intended_templates(persona):
    root = os.environ.get('SOCIETYTWIN_TEST_PROJECTION_ROOT')
    python = os.environ.get('SOCIETYTWIN_TEST_PROJECTION_PYTHON')
    distro = os.environ.get('SOCIETYTWIN_TEST_PROJECTION_WSL_DISTRO')
    if not root or not python:
        pytest.skip('Actual upstream schema/loader runtime not configured; local contract tests do not prove upstream compatibility')
    docs = [matraix_persona(persona)]
    for code, text in [('married', 'Married'), ('divorced', 'Divorced'), ('widowed', 'Widowed')]:
        selected = deepcopy(persona)
        change_visible(selected, 'marital_status', code, text)
        docs.append(matraix_persona(selected))
    unknown = deepcopy(persona)
    change_visible(unknown, 'education_level', 'unknown', 'Unknown')
    docs.append(matraix_persona(unknown))
    empty = deepcopy(persona)
    empty['model_visible'] = {}
    empty['model_visible_fields'] = []
    docs.append(matraix_persona(empty))
    # Explicit selection of one custom enrichment dimension, with no automatic
    # exposure of identity, source data or any other field.
    sidecar = deepcopy(empty)
    sidecar_text = 'kırsal / Şanlıurfa; synthetic fixture only'
    sidecar['attributes'].append({'field': 'degurba_class', 'value': 'rural',
                                  'display': sidecar_text, 'status': 'assigned'})
    sidecar['model_visible'] = {'degurba_class': sidecar_text}
    sidecar['model_visible_fields'] = ['degurba_class']
    docs.append(matraix_persona(sidecar))
    args = [python, '-I', '-B', '-c', UPSTREAM_PROBE, root]
    if distro:
        args = ['wsl', '-d', distro, '--', 'env', '-i', 'PATH=/usr/bin:/bin',
                'LANG=C.UTF-8', 'LC_ALL=C.UTF-8', *args]
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA'}}
    run = subprocess.run(args, input=json.dumps(docs, ensure_ascii=False), capture_output=True,
                         text=True, encoding='utf-8', env=env, timeout=60)
    assert run.returncode == 0, run.stderr
    output = json.loads(run.stdout)
    assert output['schema_count'] >= 1
    assert len(output['results']) == len(docs)
    for doc, loaded in zip(docs, output['results']):
        assert loaded['dimensions'] == doc['dimensions']
        assert loaded['metadata']['resident_identity'] == doc['metadata']['resident_identity']
        assert loaded['persona_id'] == doc['persona_id']
        rendered = loaded['system'] + loaded['instruction'] + loaded['narrative']
        for marker in ('8765.4321', '9123.4567', 'SOURCE-CONTROL-SECRET', 'RESEARCHER-ONLY-LIMITATION',
                       persona['population_id'], persona['synthetic_id'], 'population_weight', 'generation_seed'):
            assert marker not in rendered
        assert 'gender_identity' not in loaded['dimensions']
        if 'dst_residence_province' in doc['dimensions']:
            assert 'Şanlıurfa' in loaded['system']
        assert 'OFFLINE TEST TASK' in loaded['instruction']
    assert output['results'][4]['dimensions']['dst_education_level'] == 'Unknown'
    assert 'highest_education' not in output['results'][4]['dimensions']
    assert output['results'][5]['dimensions'] == {}
    assert sidecar_text in output['results'][6]['system']
