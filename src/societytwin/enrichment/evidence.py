"""Reusable observed conditional-count adapter, with explicit nonreporting semantics."""
import csv
import io

from societytwin.common import sha256_bytes
from societytwin.enrichment.registry import EnrichmentError


def load_evidence(attribute,root):
    source=attribute.source
    try:
        raw=(root/source.path).read_bytes()
    except FileNotFoundError as exc:
        if attribute.missing_source=='unavailable':
            return {'status':'unsupported','reason':'source_file_unavailable','groups':{},'source_sha256':None}
        raise EnrichmentError('required optional source file unavailable') from exc
    except OSError as exc:
        raise EnrichmentError(f'cannot read optional source: {exc}') from exc
    if sha256_bytes(raw)!=source.sha256:
        raise EnrichmentError('optional source checksum mismatch')
    try:
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        fields=['province_code','year','sex','category','count','value_status']
        if reader.fieldnames!=fields:raise EnrichmentError('unsupported optional source columns')
        categories={c.code for c in attribute.categories}
        groups={'male':{},'female':{}}
        for row in reader:
            if set(row)!=set(fields) or any(v is None for v in row.values()):
                raise EnrichmentError('incomplete/extra optional observation cells')
            if row['province_code']!=source.province_code or row['year']!=str(source.reference_year) or row['sex'] not in groups:
                raise EnrichmentError('wrong optional source geography/year/conditioning category')
            category=row['category'];group=groups[row['sex']]
            if category not in categories or category in group:
                raise EnrichmentError('duplicate or unknown optional category')
            value=row['count'];status=row['value_status']
            if status=='OBSERVED' and value and value.isascii() and value.isdigit():
                group[category]={'count':int(value),'status':'OBSERVED'}
            elif status=='NOT_REPORTED' and value=='':
                group[category]={'count':None,'status':'NOT_REPORTED'}
            else:
                raise EnrichmentError('invalid/missing count or unsupported observation status')
        for sex,cells in groups.items():
            if set(cells)!=categories:raise EnrichmentError('missing optional source cells; no silent category substitution')
            if any(c['status']=='NOT_REPORTED' for c in cells.values()):
                groups[sex]={'status':'not_reported','cells':cells,'probabilities':None}
            else:
                total=sum(c['count'] for c in cells.values())
                if total<=0:raise EnrichmentError('optional conditional distribution has no observed mass')
                groups[sex]={'status':'available','cells':cells,'total':total,
                             'probabilities':[cells[c.code]['count']/total for c in attribute.categories]}
        return {'status':'available','groups':groups,'source_sha256':source.sha256}
    except (UnicodeError,csv.Error) as exc:
        raise EnrichmentError(f'malformed optional observations: {exc}') from exc
