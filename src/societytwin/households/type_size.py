"""Opt-in national association fit to Ankara margins, with an explicit 7+ tail policy."""
import math
from dataclasses import asdict,dataclass
from itertools import combinations

from societytwin.common import canonical_hash
from societytwin.households.model import GeneratedHouseholds,HouseholdConfig,HouseholdRecord
from societytwin.households.registry import CLASSES,HouseholdError,parent_binding
from societytwin.households.type_size_evidence import TypeSizeEvidence,allowed
from societytwin.households.type_size_registry import BANDS,TYPES,MODEL_VERSION,SCHEMA_VERSION
from societytwin.national.fitting import ipf_2d,largest_remainder
from societytwin.national.rng import STREAM_VERSION,Stream


@dataclass(frozen=True)
class TypedHouseholdRecord(HouseholdRecord):
    household_type: str
    household_type_size_band: str
    provenance_profile: str


def fit_targets(size_counts,type_counts,seed,*,max_iter=10000):
    """Fit only at observed resolution. Never silently rescale conflicting totals."""
    if len(size_counts)!=10 or len(type_counts)!=4 or any(type(v) is not int or v<=0 for v in (*size_counts,*type_counts)):
        raise HouseholdError('invalid/nonpositive household margins')
    rows=list(size_counts[:6])+[sum(size_counts[6:])]
    if sum(rows)!=sum(type_counts) or rows[0]!=type_counts[0]:
        raise HouseholdError('incompatible household totals or one-person/size1 constraint')
    if len(seed)!=7 or any(len(row)!=4 for row in seed):
        raise HouseholdError('unsupported source joint dimensions')
    if any(not math.isfinite(v) or (v<=0 if allowed(i,j) else v!=0)
           for i,row in enumerate(seed) for j,v in enumerate(row)):
        raise HouseholdError('invalid national seed or structural support')
    # Transportation feasibility (Hall capacity inequalities) for all column subsets.
    for n in range(1,5):
        for subset in combinations(range(4),n):
            capacity=sum(rows[i] for i in range(7) if any(allowed(i,j) for j in subset))
            if sum(type_counts[j] for j in subset)>capacity:
                raise HouseholdError('infeasible household margins under structural support')
    fitted=ipf_2d(rows,list(type_counts),[list(r) for r in seed],tol=1e-14,max_iter=max_iter)
    if not fitted.converged or fitted.column_scale!=1.0:
        raise HouseholdError('household type-size IPF did not converge without rescaling')
    fine=[]
    for i,count in enumerate(size_counts):
        coarse=min(i,6)
        fine.append([v*count/rows[coarse] for v in fitted.table[coarse]])
    return {'coarse_targets':fitted.table,'fine_targets':fine,'row_targets':rows,
            'iterations':fitted.iterations,'converged':fitted.converged,
            'max_abs_residual':fitted.max_abs_residual,'column_scale':fitted.column_scale,
            'tail_policy':'exchangeable_within_observed_7plus_v1'}


def generate_type_size(evidence,type_evidence,config,base,registry):
    if not registry.enabled or not base.module.enabled:
        raise HouseholdError('household type-size strategy is disabled; explicit opt-in required')
    # Revalidate all typed caller-owned declarations before dispatch.
    registry=type(registry).model_validate(registry.model_dump(mode='json'))
    base=type(base).model_validate(base.model_dump(mode='json'))
    config=HouseholdConfig.model_validate(config.model_dump(mode='json'))
    if (registry.base_registry_version!=base.registry_version or evidence.source!=base.source
            or type_evidence.source_hashes!=(registry.national.sha256,registry.ankara_types.sha256)
            or evidence.total!=base.source.expected_total):
        raise HouseholdError('household source/registry binding mismatch')
    fit=fit_targets(evidence.counts,type_evidence.type_counts,type_evidence.national)
    shares={(i,j):v for i,row in enumerate(fit['fine_targets']) for j,v in enumerate(row) if v>0}
    if config.synthetic_size<len(shares):
        raise HouseholdError('sample too small to support all positive type-size cells')
    allocation=largest_remainder(shares,config.synthetic_size,{k:1 for k in shares})
    parent=parent_binding(base)
    identity={'generator_version':MODEL_VERSION,'schema_version':SCHEMA_VERSION,
              'config':config.model_dump(mode='json'),'base_registry_fingerprint':base.fingerprint,
              'registry_fingerprint':registry.fingerprint,'parent_registry':parent,
              'size_source':evidence.source.model_dump(mode='json'),
              'type_sources':{'national':registry.national.model_dump(mode='json'),
                              'ankara_types':registry.ankara_types.model_dump(mode='json')},
              'size_counts':list(evidence.counts),'type_counts':list(type_evidence.type_counts),
              'national_counts':[list(row) for row in type_evidence.national]}
    digest=canonical_hash(identity)
    build_id=f'hht-06-2025-n{config.synthetic_size}-s{config.seed}-{digest[:16]}'
    namespace=f'households:{MODEL_VERSION}:06:2025:type-size-order'
    cells=Stream(namespace,config.seed).shuffle([k for k,n in sorted(allocation.items()) for _ in range(n)])
    records=tuple(TypedHouseholdRecord(
        household_id=f'SHT2025-06-{digest[:16]}-{seq:07d}',province_code='06',reference_year=2025,
        household_size_class=CLASSES[i],household_size=i+1 if i<9 else None,
        household_size_lower=i+1,household_size_upper=i+1 if i<9 else None,household_size_open_ended=i==9,
        household_weight=shares[i,j]/allocation[i,j],household_type=TYPES[j],
        household_type_size_band=BANDS[min(i,6)],provenance_profile=MODEL_VERSION)
        for seq,(i,j) in enumerate(cells,1))
    manifest={'household_population_id':build_id,'identity':identity,'identity_sha256':digest,
              'schema_version':SCHEMA_VERSION,'generator_version':MODEL_VERSION,
              'registry':registry.model_dump(mode='json'),'base_registry':base.model_dump(mode='json'),
              'parent_dependency_registry':parent,'source':identity['type_sources'],
              'record_count':len(records),'represented_households':evidence.total,
              'weight_unit':'household','scope':'household','linked_to_residents':False,'member_count_exact':None,
              'fit':fit,'allocation':{f'{i}:{j}':n for (i,j),n in sorted(allocation.items())},
              'random_stream':{'version':STREAM_VERSION,'namespace':namespace,'seed':config.seed},
              'provenance_profile':{'id':MODEL_VERSION,'evidence_class':'D','runtime_evidence':'MARGINAL_INFERENCE',
                  'observed':'National 2025 joint at sizes 1-6/7+; Ankara 2025 separate type and size margins.',
                  'assumptions':[registry.transfer_policy,registry.tail_policy],
                  'limitations':'Not an observed Ankara joint. No observed type gradient within 7+. No members or family links.'},
              'method':'Coarse national seed IPF; explicit within-7+ exchangeability; cell-stratified Hamilton allocation with one-record support floor; fitted cell / sample cell expansion weights.',
              'content_sha256':canonical_hash([asdict(r) for r in records])}
    return GeneratedHouseholds(records,manifest)
