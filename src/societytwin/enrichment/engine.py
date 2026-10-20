"""Optional conditional assignments; core records and weights are read only."""
import math
from collections import Counter

from societytwin.common import canonical_hash
from societytwin.enrichment import MODEL_VERSION, SCHEMA_VERSION
from societytwin.enrichment.evidence import load_evidence
from societytwin.enrichment.model import AttributeValue, ExtensionRecord, ResidentExtension, EnrichmentConfig
from societytwin.enrichment.registry import EnrichmentError, REPO_ROOT, parent_binding
from societytwin.national.rng import Stream, cumulative, STREAM_VERSION


def core_binding(core):
    rows=sorted(core.table.to_pylist(),key=lambda r:r['synthetic_id'])
    ids=[r['synthetic_id'] for r in rows]
    if not ids or any(not isinstance(i,str) or not i for i in ids) or len(ids)!=len(set(ids)):
        raise EnrichmentError('core requires nonempty unique resident IDs')
    for row in rows:
        if not math.isfinite(row['population_weight']) or row['population_weight']<=0:
            raise EnrichmentError('invalid core population weight')
    return rows,{'population_id':core.manifest['population_id'],'records_hash':canonical_hash(rows)}


def eligible(row, attribute):
    return row['age']>=attribute.min_age and (attribute.max_age is None or row['age']<=attribute.max_age)


def generate(core, registry, config=None, root=REPO_ROOT):
    config=config or EnrichmentConfig()
    parent=parent_binding(registry)
    active={n:a for n,a in sorted(registry.attributes.items()) if registry.modules[a.module].enabled}
    if not active:raise EnrichmentError('optional resident module disabled; explicit opt-in required')
    rows,binding=core_binding(core)
    evidence={};profiles={};streams={}
    for name,a in active.items():
        if any(r['province_code']!=a.source.province_code or r['reference_year']!=a.source.reference_year or r['sex'] not in ('male','female') for r in rows):
            raise EnrichmentError('source geography/year/sex incompatible with core residents')
        evidence[name]=load_evidence(a,root)
        profiles[name]=canonical_hash({'attribute':a.model_dump(mode='json'),'evidence':evidence[name]})
        for sex,g in evidence[name]['groups'].items():
            weight=math.fsum(r['population_weight'] for r in rows if r['sex']==sex and eligible(r,a))
            if g['status']=='available' and not math.isclose(weight,g['total'],rel_tol=1e-8,abs_tol=1e-6):
                raise EnrichmentError(f'{name}/{sex}: source universe denominator differs from eligible resident weights')
        streams[name]={sex:Stream(f'enrichment:{MODEL_VERSION}:{name}:{a.source.province_code}:{a.source.reference_year}:{sex}',config.seed) for sex in ('male','female')}
    records=[]
    for r in rows:
        values=[]
        for name,a in active.items():
            value=None
            if not eligible(r,a):status='outside_universe'
            elif evidence[name]['status']=='unsupported':status='unsupported'
            else:
                group=evidence[name]['groups'][r['sex']]
                if group['status']=='not_reported':status='not_reported'
                else:
                    category=a.categories[streams[name][r['sex']].weighted_index(cumulative(group['probabilities']))]
                    value=category.code
                    status='published_unknown' if category.kind=='published_unknown' else 'assigned'
            values.append(AttributeValue(attribute=name,value=value,status=status,provenance_profile=profiles[name]))
        records.append(ExtensionRecord(synthetic_id=r['synthetic_id'],attributes=tuple(values)))
    payload=[r.model_dump(mode='json') for r in records]
    manifest={'schema_version':SCHEMA_VERSION,'model_version':MODEL_VERSION,'stream_version':STREAM_VERSION,
              'config':config.model_dump(mode='json'),'registry':registry.model_dump(mode='json'),
              'registry_fingerprint':registry.fingerprint,'parent_registry':parent,'core':binding,
              'evidence':evidence,'provenance_profiles':profiles,'content_hash':canonical_hash(payload),
              'assignment_policy':'conditional categorical draws; no weight changes or exact marginal fitting'}
    manifest['artifact_id']='ext-'+canonical_hash(manifest)
    return ResidentExtension(tuple(records),manifest)


def validate(extension,core):
    """Reconstruct deterministic assignments and report weighted sampling deviations."""
    from societytwin.enrichment.registry import ExtensionRegistry
    m=extension.manifest
    registry=ExtensionRegistry.model_validate(m['registry'])
    rows,binding=core_binding(core)
    if binding!=m['core']:raise EnrichmentError('sidecar core binding mismatch')
    if m['schema_version']!=SCHEMA_VERSION or m['model_version']!=MODEL_VERSION:
        raise EnrichmentError('unsupported sidecar version')
    payload=[r.model_dump(mode='json') for r in extension.records]
    if canonical_hash(payload)!=m['content_hash']:raise EnrichmentError('sidecar content hash mismatch')
    identity={k:v for k,v in m.items() if k not in ('artifact_id','parquet_sha256')}
    if 'ext-'+canonical_hash(identity)!=m['artifact_id']:raise EnrichmentError('sidecar artifact identity mismatch')
    if [r.synthetic_id for r in extension.records]!=[r['synthetic_id'] for r in rows]:
        raise EnrichmentError('sidecar referential integrity failure')
    active={n:a for n,a in sorted(registry.attributes.items()) if registry.modules[a.module].enabled}
    if not active or registry.fingerprint!=m['registry_fingerprint'] or parent_binding(registry)!=m['parent_registry']:
        raise EnrichmentError('invalid registry binding')
    config=EnrichmentConfig.model_validate(m['config'])
    streams={name:{sex:Stream(f'enrichment:{MODEL_VERSION}:{name}:{a.source.province_code}:{a.source.reference_year}:{sex}',config.seed)
                   for sex in ('male','female')} for name,a in active.items()}
    diagnostics=[];statuses=Counter()
    for record,row in zip(extension.records,rows):
        if [v.attribute for v in record.attributes]!=list(active):raise EnrichmentError('missing/duplicate sidecar attributes')
        for v in record.attributes:
            a=active[v.attribute];e=m['evidence'][v.attribute]
            expected=('outside_universe' if not eligible(row,a) else 'unsupported' if e['status']=='unsupported' else 'not_reported' if e['groups'][row['sex']]['status']=='not_reported' else None)
            if v.provenance_profile!=m['provenance_profiles'][v.attribute]:raise EnrichmentError('provenance mismatch')
            if expected:
                if v.status!=expected or v.value is not None:raise EnrichmentError('invalid unavailable/universe status')
            else:
                kinds={c.code:c.kind for c in a.categories}
                if v.value not in kinds or v.status!=('published_unknown' if kinds[v.value]=='published_unknown' else 'assigned'):
                    raise EnrichmentError('invalid assigned category/status')
                group=e['groups'][row['sex']]
                drawn=a.categories[streams[v.attribute][row['sex']].weighted_index(cumulative(group['probabilities']))].code
                if v.value!=drawn:raise EnrichmentError('assignment differs from deterministic seed replay')
            statuses[v.status]+=1
    for name,a in active.items():
        for sex,g in m['evidence'][name]['groups'].items():
            if g['status']!='available':continue
            selected=[(r,v) for r,rec in zip(rows,extension.records) for v in rec.attributes if v.attribute==name and r['sex']==sex and eligible(r,a)]
            weights=[r['population_weight'] for r,v in selected]
            for c,p in zip(a.categories,g['probabilities']):
                actual=math.fsum(r['population_weight'] for r,v in selected if v.value==c.code)
                expected=math.fsum(weights)*p
                se=math.sqrt(p*(1-p)*math.fsum(w*w for w in weights))
                diagnostics.append({'attribute':name,'sex':sex,'category':c.code,'observed_source_count':g['cells'][c.code]['count'],
                                    'expected_weight':expected,'actual_weight':actual,'sampling_standard_error':se,
                                    'z':(actual-expected)/se if se else 0.,'within_4se':abs(actual-expected)<=4*se+1e-6})
    return {'valid':True,'records':len(rows),'statuses':dict(statuses),'margins':diagnostics,
            'note':'Observed province/sex counts are expectations, not exactly fitted new margins. Four-SE checks are diagnostic.'}
