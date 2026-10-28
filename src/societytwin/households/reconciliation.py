"""Read-only population-universe gate; compatibility does not authorize linkage.

``reconcile(columns, manifest, households)`` accepts the national column mapping
and a GeneratedHouseholds (including the optional type-size variant). It performs
no I/O. Existing validators remain responsible for full artifact integrity.

Resident universe metadata is optional, explicit ``manifest['population_universe']``:
``{'definition': 'ADNKS_private_household_residents' | 'ADNKS_residents',
'source_ref': <nonempty evidence reference>, 'institutional_population': <number>}``.
The institutional count is required only for all-resident universes, and must
cover the same geography/year. Unknown definitions are never inferred from prose.
This is an input contract, not a change to generated manifests.
"""
from collections.abc import Mapping
from copy import deepcopy
import json
import math

from societytwin.households.registry import CLASSES


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _number(value, *, positive=False):
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and (value > 0 if positive else value >= 0))
    except OverflowError:
        return False


def reconcile(columns, manifest, households):
    """Return JSON-safe deterministic findings without changing caller objects.

    Incompatible findings take precedence over missing evidence. Open tails can
    disprove compatibility if their lower bound exceeds available persons, but
    cannot prove it. Totals use a fixed 1e-10 relative / 1e-6 absolute tolerance.
    No province filtering, rescaling, or institutional allocation is inferred.
    """
    columns, manifest = _mapping(columns), _mapping(manifest)
    hm = _mapping(households.manifest)
    source = _mapping(hm.get('source'))
    # Type-size manifests store the size-source binding separately from transfers.
    if 'national' in source:
        source = _mapping(_mapping(hm.get('identity')).get('size_source'))
    findings = []
    totals = {'resident_persons': None, 'private_household_persons': None,
              'households': None, 'member_lower_bound': None,
              'member_exact': None, 'open_ended_records': None}

    def add(check, status, detail):
        findings.append({'check': check, 'status': status, 'detail': detail})

    def close(a, b):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-6)

    provenance = {'population_id': manifest.get('population_id'),
                  'household_population_id': hm.get('household_population_id'),
                  'resident_sources': deepcopy(manifest.get('source_versions')),
                  'household_source': deepcopy(source),
                  'household_identity_sha256': hm.get('identity_sha256'),
                  'parent_dependency_registry': deepcopy(hm.get('parent_dependency_registry')),
                  'population_universe': deepcopy(manifest.get('population_universe'))}
    for name, value in provenance.items():
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError, OverflowError):
            # Keep the diagnostic serializable even when evidence itself is
            # malformed. Never rewrite or coerce caller-owned source metadata.
            provenance[name] = None
            add('provenance_metadata', 'not_assessable', f'Malformed JSON provenance: {name}.')
    resident_sources = _mapping(provenance['resident_sources']).get('sources')
    if (not all(isinstance(v, str) and v for v in
                (provenance['population_id'], provenance['household_population_id']))
            or not isinstance(resident_sources, list) or not resident_sources
            or not all(isinstance(_mapping(s).get('source_id'), str)
                       and _mapping(s).get('source_id') for s in resident_sources)
            or not isinstance(source.get('source_version'), str) or not source.get('source_version')):
        add('provenance', 'not_assessable', 'Missing manifest identifiers or source provenance.')
    else:
        add('provenance', 'compatible', 'Manifest identifiers and source references retained; checksums are not revalidated here.')

    try:
        weights = columns['population_weight']
        geos, years = columns['province_code'], columns['reference_year']
        if not weights or not (len(weights) == len(geos) == len(years)):
            raise ValueError
        if (not all(_number(w, positive=True) for w in weights)
                or not all(isinstance(g, str) and g for g in geos)
                or not all(type(y) is int for y in years)):
            raise ValueError
        resident_total = math.fsum(weights)
        if not math.isfinite(resident_total):
            raise ValueError
        totals['resident_persons'] = resident_total
        rg, ry = set(geos), set(years)
        declared = _mapping(manifest.get('scope')).get('provinces_with_records')
        if not isinstance(declared, list) or not declared or not all(isinstance(g, str) for g in declared):
            add('resident_geography_metadata', 'not_assessable', 'Missing/malformed covered provinces.')
        elif set(declared) != rg:
            add('resident_geography_metadata', 'incompatible', 'Manifest coverage differs from records.')
        if type(manifest.get('reference_year')) is not int:
            add('resident_year_metadata', 'not_assessable', 'Missing/malformed reference year.')
        elif ry != {manifest['reference_year']}:
            add('resident_year_metadata', 'incompatible', 'Manifest year differs from records.')
        profiles = _mapping(manifest.get('profiles'))
        root_years = [_mapping(_mapping(_mapping(p).get('fields')).get('province_code')).get('source_year')
                      for p in profiles.values()]
        if not root_years or not all(type(y) is int for y in root_years):
            add('resident_observation_year', 'not_assessable', 'Missing/malformed root population observation years in profiles.')
        else:
            add('resident_observation_year', 'compatible' if set(root_years) == ry else 'incompatible',
                'Root observation years must match record reference years; no temporal transfer is inferred.')
        declared_total = manifest.get('represented_population')
        if not _number(declared_total):
            add('resident_total_metadata', 'not_assessable', 'Missing/malformed represented population.')
        elif not close(resident_total, declared_total):
            add('resident_total_metadata', 'incompatible', 'Weights disagree with represented population.')
    except (KeyError, TypeError, ValueError, OverflowError):
        rg, ry = None, None
        add('resident_records', 'not_assessable', 'Missing/malformed person weights, geography or year columns.')

    try:
        records = households.records
        if not records:
            raise ValueError
        hw, members, hg, hy, opened = [], [], set(), set(), 0
        for r in records:
            if r.household_size_class not in CLASSES or not _number(r.household_weight, positive=True):
                raise ValueError
            tail = r.household_size_class == '10+'
            lower = 10 if tail else int(r.household_size_class)
            exact = None if tail else lower
            if (type(r.household_size_lower) is not int
                    or type(r.household_size_open_ended) is not bool
                    or (not tail and (type(r.household_size) is not int
                                      or type(r.household_size_upper) is not int))
                    or (r.household_size, r.household_size_lower, r.household_size_upper,
                        r.household_size_open_ended) != (exact, lower, exact, tail)
                    or not isinstance(r.province_code, str) or not r.province_code
                    or type(r.reference_year) is not int):
                raise ValueError
            hw.append(r.household_weight)
            members.append(r.household_weight * lower)
            hg.add(r.province_code)
            hy.add(r.reference_year)
            opened += tail
        household_total, bound = math.fsum(hw), math.fsum(members)
        if not math.isfinite(household_total) or not math.isfinite(bound):
            raise ValueError
        totals.update(households=household_total, member_lower_bound=bound,
                      member_exact=None if opened else bound, open_ended_records=opened)
        for name, observed, expected in [('geography', hg, source.get('province_code')),
                                          ('year', hy, source.get('reference_year'))]:
            valid = isinstance(expected, str) and bool(expected) if name == 'geography' else type(expected) is int
            add('household_' + name + '_metadata',
                'not_assessable' if not valid else 'compatible' if observed == {expected} else 'incompatible',
                'Size-source geography/year must agree with all household records.')
        if not _number(hm.get('represented_households')):
            add('household_total_metadata', 'not_assessable', 'Missing/malformed represented households.')
        elif not close(household_total, hm['represented_households']):
            add('household_total_metadata', 'incompatible', 'Household weights disagree with manifest total.')
        if rg is not None:
            add('geography', 'compatible' if rg == hg else 'incompatible', 'Compared complete province sets; no implicit subsetting.')
            add('reference_year', 'compatible' if ry == hy else 'incompatible', 'Compared record reference years.')
    except (AttributeError, TypeError, ValueError, OverflowError):
        add('household_records', 'not_assessable', 'Missing/malformed household weights or size bounds.')

    units = (hm.get('weight_unit'), source.get('unit'))
    resident_unit = manifest.get('weight_unit', _mapping(manifest.get('weights')).get('unit', 'person'))
    if any(u is None for u in units):
        add('statistical_units', 'not_assessable', 'Household weight/source unit is missing.')
    elif units != ('household', 'household') or resident_unit != 'person':
        add('statistical_units', 'incompatible', 'population_weight must expand persons and household_weight must expand households.')
    else:
        add('statistical_units', 'compatible', 'population_weight expands persons; household_weight expands households. Multiply household weights by size to compare members.')

    universe = _mapping(manifest.get('population_universe'))
    definition = universe.get('definition')
    if (source.get('universe') != 'ADNKS_private_households'
            or not isinstance(universe.get('source_ref'), str) or not universe.get('source_ref')):
        add('population_universe', 'not_assessable', 'Need documented private-household universe and resident universe evidence.')
    elif definition == 'ADNKS_private_household_residents':
        totals['private_household_persons'] = totals['resident_persons']
        add('population_universe', 'compatible', 'Residents explicitly exclude institutional populations.')
    elif definition == 'ADNKS_residents':
        institutional = universe.get('institutional_population')
        if not _number(institutional) or totals['resident_persons'] is None:
            add('population_universe', 'not_assessable', 'All residents require an evidenced same-scope institutional count; no count is inferred.')
        elif institutional > totals['resident_persons']:
            add('population_universe', 'incompatible', 'Institutional count exceeds all resident persons.')
        else:
            totals['private_household_persons'] = totals['resident_persons'] - institutional
            add('population_universe', 'compatible', 'Private-household total derived by subtracting documented institutional count; individual eligibility remains unknown.')
    elif definition == 'ADNKS_institutional_residents':
        add('population_universe', 'incompatible', 'Institutional-only residents cannot populate private households.')
    else:
        add('population_universe', 'not_assessable', 'Missing or unsupported resident universe definition.')

    persons, bound = totals['private_household_persons'], totals['member_lower_bound']
    if persons is None or bound is None:
        add('member_totals', 'not_assessable', 'Comparable member/person totals are unavailable.')
    elif bound > persons and not close(bound, persons):
        add('member_totals', 'incompatible', 'Household member lower bound exceeds available private-household persons.')
    elif totals['member_exact'] is None:
        add('member_totals', 'not_assessable', 'Open-ended sizes provide a lower bound only; exact member total is unknown.')
    else:
        add('member_totals', 'compatible' if close(bound, persons) else 'incompatible', 'Compared exact weighted members with private-household persons.')
    statuses = {f['status'] for f in findings}
    status = 'incompatible' if 'incompatible' in statuses else 'not_assessable' if 'not_assessable' in statuses else 'compatible'
    return {'reconciliation_version': 'household-universe-1', 'status': status,
            'findings': findings, 'totals': totals, 'provenance': provenance,
            'limitations': ['Aggregate gate only; no resident membership or family roles are established.',
                            'Existing artifact validators must independently verify source and content integrity.']}
