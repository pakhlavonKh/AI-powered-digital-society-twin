"""Observed counts, disjoint partitions and explicitly justified support masks."""
import csv
import io
from dataclasses import dataclass

from societytwin.common import sha256_bytes
from societytwin.households.registry import HouseholdError
from societytwin.households.type_size_registry import BANDS,TYPES


@dataclass(frozen=True)
class TypeSizeEvidence:
    national: tuple[tuple[int,...],...]
    type_counts: tuple[int,...]
    source_hashes: tuple[str,str]


def allowed(i,j):
    return (i==0 and j==0) or (i>=1 and j in (1,3)) or (i>=2 and j==2)


def _rows(source,root,fields):
    try:
        raw=(root/source.path).read_bytes()
        if sha256_bytes(raw)!=source.sha256:
            raise HouseholdError('type-size source checksum mismatch')
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        if reader.fieldnames!=fields:
            raise HouseholdError('unsupported type-size observation columns')
        rows=list(reader)
        if any(set(r)!=set(fields) or any(v is None for v in r.values()) for r in rows):
            raise HouseholdError('missing/extra type-size observation cells')
        return rows
    except (OSError,UnicodeError,csv.Error) as exc:
        raise HouseholdError(f'type-size evidence unavailable/malformed: {exc}') from exc


def _integer(value):
    if not value or not value.isascii() or not value.isdigit():
        raise HouseholdError('missing/suppressed/noninteger household count')
    return int(value)


def load_type_size_evidence(registry,base,evidence,root):
    if registry.base_registry_version!=base.registry_version:
        raise HouseholdError('incompatible base household registry version')
    rows=_rows(registry.national,root,['year','geography','household_type','household_size','households','value_status','source_table'])
    nested=('couple_without_resident_children','couple_with_resident_children','lone_parent','lone_father','lone_mother')
    cells={}
    for r in rows:
        key=(r['household_type'],r['household_size'])
        if r['year']!='2025' or r['geography']!='TR' or key in cells or key[0] not in TYPES+nested or key[1] not in BANDS:
            raise HouseholdError('duplicate/unsupported national joint cell or year/geography')
        if r['value_status']=='NOT_APPLICABLE' and r['households']=='':
            cells[key]=None
        elif r['value_status']=='OBSERVED':
            cells[key]=_integer(r['households'])
        else:
            raise HouseholdError('missing/suppressed national joint observation')
    if len(cells)!=63:
        raise HouseholdError('incomplete national type-size joint')
    for size in BANDS:
        val=lambda t: cells[t,size] or 0
        if val('nuclear_family')!=sum(val(t) for t in nested[:3]) or val('lone_parent')!=val('lone_father')+val('lone_mother'):
            raise HouseholdError('overlapping/nested national household partition inconsistent')
    matrix=[]
    for i,size in enumerate(BANDS):
        row=[]
        for j,t in enumerate(TYPES):
            value=cells[t,size]
            if (value is None)!= (not allowed(i,j)):
                raise HouseholdError('national structural support differs from verified definitions')
            if value is not None and value<=0:
                raise HouseholdError('observed zero requires an explicit new support policy')
            row.append(value or 0)
        matrix.append(tuple(row))
    local=_rows(registry.ankara_types,root,['year','province_code','household_type','households'])
    selected={}
    for r in local:
        if r['province_code']!='06':
            raise HouseholdError('wrong Ankara household geography')
        if r['year']!='2025':continue
        if r['household_type'] not in TYPES+('total',) or r['household_type'] in selected:
            raise HouseholdError('duplicate/unsupported Ankara household type')
        selected[r['household_type']]=_integer(r['households'])
    if set(selected)!=set(TYPES+('total',)) or sum(selected[t] for t in TYPES)!=selected['total'] or selected['total']!=evidence.total:
        raise HouseholdError('incompatible household denominators or missing Ankara type margins')
    return TypeSizeEvidence(tuple(matrix),tuple(selected[t] for t in TYPES),
                            (registry.national.sha256,registry.ankara_types.sha256))
