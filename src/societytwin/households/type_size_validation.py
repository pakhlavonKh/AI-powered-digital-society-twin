"""Validate fitted local margins and transferred association separately."""
import math
from collections import Counter
from dataclasses import asdict
from itertools import combinations

from societytwin.common import canonical_hash
from societytwin.households.model import HouseholdConfig
from societytwin.households.registry import CLASSES,HouseholdError,HouseholdRegistry
from societytwin.households.type_size import fit_targets
from societytwin.households.type_size_evidence import allowed
from societytwin.households.type_size_registry import BANDS,TYPES,MODEL_VERSION,SCHEMA_VERSION,TypeSizeRegistry


def validate_type_size(population):
    records,m=population.records,population.manifest
    ident=m['identity'];digest=canonical_hash(ident)
    config=HouseholdConfig.model_validate(ident['config'])
    registry=TypeSizeRegistry.model_validate(m['registry'])
    base=HouseholdRegistry.model_validate(m['base_registry'])
    if (not registry.enabled or not base.module.enabled or ident['registry_fingerprint']!=registry.fingerprint
            or ident['base_registry_fingerprint']!=base.fingerprint or m['identity_sha256']!=digest
            or registry.base_registry_version!=base.registry_version
            or m['household_population_id']!=f'hht-06-2025-n{config.synthetic_size}-s{config.seed}-{digest[:16]}'
            or any(x['generator_version']!=MODEL_VERSION or x['schema_version']!=SCHEMA_VERSION for x in (m,ident))):
        raise HouseholdError('type-size artifact identity/version mismatch')
    expected_sources={'national':registry.national.model_dump(mode='json'),'ankara_types':registry.ankara_types.model_dump(mode='json')}
    if (ident['size_source']!=base.source.model_dump(mode='json') or ident['type_sources']!=expected_sources
            or m['source']!=expected_sources or m['parent_dependency_registry']!=ident['parent_registry']):
        raise HouseholdError('type-size artifact provenance mismatch')
    if (m['weight_unit'],m['scope'],m['linked_to_residents'],m['member_count_exact'])!=('household','household',False,None):
        raise HouseholdError('type-size household scope/linkage mismatch')
    sizes,types=ident['size_counts'],ident['type_counts']
    fit=fit_targets(sizes,types,ident['national_counts'])
    if fit!=m['fit'] or sum(sizes)!=base.source.expected_total or m['represented_households']!=sum(sizes):
        raise HouseholdError('type-size fit/denominator mismatch')
    if len(records)!=config.synthetic_size or len(records)!=m['record_count']:
        raise HouseholdError('type-size record count mismatch')
    counts=Counter();weights={(i,j):[] for i in range(10) for j in range(4)}
    for seq,r in enumerate(records,1):
        if r.household_size_class not in CLASSES or r.household_type not in TYPES:
            raise HouseholdError('unsupported household type/size')
        i,j=CLASSES.index(r.household_size_class),TYPES.index(r.household_type)
        if not allowed(min(i,6),j):raise HouseholdError('structural-zero violation')
        exact=i+1 if i<9 else None
        if ((r.household_size,r.household_size_lower,r.household_size_upper,r.household_size_open_ended)!=(exact,i+1,exact,i==9)
                or r.household_type_size_band!=BANDS[min(i,6)] or r.provenance_profile!=MODEL_VERSION):
            raise HouseholdError('invalid type-size open-ended/coarse/provenance semantics')
        if (r.household_id!=f'SHT2025-06-{digest[:16]}-{seq:07d}' or r.province_code!='06' or r.reference_year!=2025):
            raise HouseholdError('invalid type-size record identity')
        if not math.isfinite(r.household_weight) or r.household_weight<=0:
            raise HouseholdError('invalid household weight')
        counts[i,j]+=1;weights[i,j].append(r.household_weight)
    fine=[[math.fsum(weights[i,j]) for j in range(4)] for i in range(10)]
    max_joint=0.0
    for i,row in enumerate(fit['fine_targets']):
        for j,target in enumerate(row):
            if target>0:
                if not counts[i,j] or any(not math.isclose(w,target/counts[i,j],rel_tol=1e-13) for w in weights[i,j]):
                    raise HouseholdError('missing/incorrect sampled type-size cell weight')
                max_joint=max(max_joint,abs(fine[i][j]-target)/target)
    size_errors=[abs(math.fsum(fine[i])-sizes[i])/sizes[i] for i in range(10)]
    type_errors=[abs(math.fsum(fine[i][j] for i in range(10))-types[j])/types[j] for j in range(4)]
    if max(size_errors+type_errors+[max_joint])>1e-10:
        raise HouseholdError('household type-size calibration residual too large')
    if {f'{i}:{j}':n for (i,j),n in sorted(counts.items())}!=m['allocation'] or canonical_hash([asdict(r) for r in records])!=m['content_sha256']:
        raise HouseholdError('type-size content/allocation mismatch')
    coarse=fine[:6]+[[math.fsum(fine[i][j] for i in range(6,10)) for j in range(4)]]
    odds=[]
    for a,b in combinations(range(7),2):
        for c,d in combinations(range(4),2):
            seed=ident['national_counts']
            if all(seed[i][j]>0 for i,j in ((a,c),(a,d),(b,c),(b,d))):
                original=math.log(seed[a][c])+math.log(seed[b][d])-math.log(seed[a][d])-math.log(seed[b][c])
                transferred=math.log(coarse[a][c])+math.log(coarse[b][d])-math.log(coarse[a][d])-math.log(coarse[b][c])
                odds.append(abs(original-transferred))
    if max(odds,default=0)>1e-9:raise HouseholdError('transferred association not preserved')
    total=math.fsum(r.household_weight for r in records)
    ess=total**2/math.fsum(r.household_weight**2 for r in records)
    return {'validation_version':'household-type-size-fit-1','passed':True,'weight_unit':'household',
            'records':len(records),'represented_households':total,'linked_residents':0,'exact_total_members':None,
            'size_margins':[{'class':CLASSES[i],'target':sizes[i],'weighted':math.fsum(fine[i])} for i in range(10)],
            'type_margins':[{'type':TYPES[j],'target':types[j],'weighted':math.fsum(fine[i][j] for i in range(10))} for j in range(4)],
            'max_size_relative_error':max(size_errors),'max_type_relative_error':max(type_errors),
            'max_joint_relative_error':max_joint,'coarse_weighted_joint':coarse,
            'max_transferred_log_odds_error':max(odds,default=0),'association_checks':len(odds),
            'ipf_converged':True,'ipf_iterations':fit['iterations'],'ipf_max_abs_residual':fit['max_abs_residual'],
            'structural_violations':0,'effective_sample_size':ess,
            'min_weight':min(r.household_weight for r in records),'max_weight':max(r.household_weight for r in records),
            'positive_joint_cells':len(counts),'cells_with_one_record':sum(n==1 for n in counts.values()),
            'observed_joint_resolution':'national 1-6/7+; Ankara joint is modelled',
            'tail_policy':registry.tail_policy}
