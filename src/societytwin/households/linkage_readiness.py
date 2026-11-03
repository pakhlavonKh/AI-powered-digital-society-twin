"""Read-only readiness diagnostics. No allocator, instance linker or role generator."""
from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
import math

from societytwin.common import canonical_hash
from societytwin.households.linkage_evidence import (
    LEAVES, SIZE_CLASSES, LinkageEvidence, inspect_sources,
)
from societytwin.households.membership import input_fingerprints
from societytwin.households.reconciliation import reconcile

CAPABILITIES = ('household_aggregate_modeling', 'weighted_mass_allocation',
                'unique_instance_assignment', 'family_roles_and_kinship')


def assess_linkage_readiness(columns, manifest, households, *, evidence,
                             reconciliation, source_root=None):
    """Recheck diagnostics, bind inputs and report four distinct capability gates.

    A ready aggregate catalog never authorizes allocation. Even complete declared
    evidence can only make future weighted allocation conditionally_ready: no
    production method is implemented/approved here. Source inspection is optional,
    explicit and local; metadata declarations never authenticate their publisher.
    """
    evidence = LinkageEvidence.model_validate(
        evidence.model_dump(mode='json') if isinstance(evidence, LinkageEvidence) else evidence)
    sources = inspect_sources(evidence, source_root)
    reports = {name: {'status': 'ready', 'reasons': [], 'required_evidence': [],
                      'missing_evidence': []} for name in CAPABILITIES}

    def add(names, code, detail, *, conditional=False, required=None):
        for name in names:
            report = reports[name]
            report['reasons'].append({'code': code, 'detail': detail,
                                      'severity': 'condition' if conditional else 'blocker'})
            if not conditional:
                report['status'] = 'blocked'
            elif report['status'] == 'ready':
                report['status'] = 'conditionally_ready'
            if required and required not in report['missing_evidence']:
                report['missing_evidence'].append(required)
            if required and required not in report['required_evidence']:
                report['required_evidence'].append(required)

    aggregate = CAPABILITIES[:1]
    production = CAPABILITIES[1:]
    for name in CAPABILITIES:
        reports[name]['required_evidence'] = {
            CAPABILITIES[0]: ['same_scope_household_size_and_composition_counts'],
            CAPABILITIES[1]: ['compatible_reconciliation', 'private_person_mass',
                              'supported_household_capacity', 'reviewed_allocation_method'],
            CAPABILITIES[2]: ['private_resident_eligibility', 'joint_instance_representation',
                              'exact_instance_capacities', 'reviewed_instance_method'],
            CAPABILITIES[3]: ['relationship_observations', 'coherent_household_rosters',
                              'reviewed_role_method'],
        }[name]

    observed = reconcile(columns, manifest, households)
    try:
        if canonical_hash(reconciliation) != canonical_hash(observed):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        add(CAPABILITIES, 'reconciliation_binding_mismatch', 'Supplied diagnostic differs from fresh reconciliation of these inputs.')
    if observed['status'] != 'compatible':
        add(production, 'reconciliation_' + observed['status'],
            'Aggregate reconciliation is not compatible; matching record counts would not resolve this.',
            required='compatible_reconciliation')
    if next(f for f in observed['findings'] if f['check'] == 'statistical_units')['status'] != 'compatible':
        add(CAPABILITIES, 'statistical_units_unverified', 'Person and household expansion units must be compatible.')
    for finding in observed['findings']:
        if finding['status'] == 'incompatible':
            add(production, 'reconciliation_' + finding['check'], finding['detail'])

    fingerprints = None
    try:
        fingerprints = input_fingerprints(columns, manifest, households)
    except ValueError:
        add(CAPABILITIES, 'input_integrity', 'Cannot bind complete records and original manifests.')

    hm = households.manifest
    geos = {r.province_code for r in households.records}
    years = {r.reference_year for r in households.records}
    if geos != {evidence.geography} or years != {evidence.reference_year}:
        add(CAPABILITIES, 'household_scope_mismatch', 'Evidence scope differs from household records.')
    if (set(columns.get('province_code', ())) != {evidence.geography}
            or set(columns.get('reference_year', ())) != {evidence.reference_year}):
        add(production, 'resident_scope_mismatch', 'Evidence scope differs from resident records.')

    used_household = {c.source_id for c in (*evidence.composition, *evidence.sizes, evidence.household_total)
                      if c.source_id}
    used_person = {c.source_id for c in (evidence.coverage.private_persons,
                                        evidence.coverage.institutional_persons, evidence.tail.members)
                   if c.source_id}
    used_person.update(evidence.coverage.eligibility_source_ids)
    used_person.update(evidence.relationships.source_ids)
    if evidence.tail.upper_source_id:
        used_person.add(evidence.tail.upper_source_id)
    for key in sorted(used_household | used_person):
        source = evidence.sources[key]
        affected = CAPABILITIES if key in used_household else production
        if (source.geography != evidence.geography or source.observation_year != evidence.reference_year
                or source.reference_year != evidence.reference_year):
            add(affected, 'source_scope_mismatch', f'{key}: geography/observation/reference year differs; no transfer is inferred.')
        if key in used_household and source.universe != 'ADNKS_private_households':
            add(CAPABILITIES, 'household_universe_unknown', f'{key}: need documented private-household units.')
        status = sources[key]['status']
        if status in ('not_checked', 'unavailable'):
            add(affected, 'source_bytes_' + status, f'{key}: local source bytes are not checked/available.',
                conditional=key in used_household, required='local_source_integrity')
        elif status != 'matched':
            add(affected, 'source_integrity_failure', f'{key}: {status}.')
        if source.precision.kind != 'exact_integer_counts':
            add(affected, 'source_precision_uncertain', f'{key}: count precision is not exact.',
                conditional=key in used_household, required='source_precision')

    if (set(c.category for c in evidence.composition) != set(LEAVES)
            or any(c.status not in ('observed', 'modeled') for c in evidence.composition)):
        add(aggregate, 'composition_evidence_missing', 'Need all seven disjoint household leaves.',
            required='same_scope_household_size_and_composition_counts')
    if (set(c.category for c in evidence.sizes) != set(SIZE_CLASSES)
            or any(c.status not in ('observed', 'modeled') for c in evidence.sizes)):
        add(CAPABILITIES, 'size_evidence_missing', 'Need a complete supported size distribution.',
            required='same_scope_household_size_and_composition_counts')
    if evidence.household_total.value is None:
        add(CAPABILITIES, 'household_total_missing', 'Documented household total is unavailable.')
    elif not math.isclose(observed['totals']['households'] or 0, evidence.household_total.value,
                          rel_tol=1e-10, abs_tol=1e-6):
        add(CAPABILITIES, 'household_total_mismatch', 'Household weights differ from the evidence total.')
    if any(c.status == 'modeled' for c in (*evidence.composition, *evidence.sizes, evidence.household_total)):
        add(aggregate, 'modeled_household_evidence', 'Some household counts are modeled, not observations.', conditional=True)

    by_size = defaultdict(list)
    for row in households.records:
        by_size[row.household_size_class].append(row.household_weight)
    if any(c.value is not None and not math.isclose(math.fsum(by_size[c.category]), c.value,
                                                   rel_tol=1e-10, abs_tol=1e-6) for c in evidence.sizes):
        add(CAPABILITIES, 'household_size_mismatch', 'Weighted household size cells disagree with evidence.')

    # Aggregates and bounds do not establish an exact roster or tail distribution.
    opened = observed['totals']['open_ended_records']
    if opened:
        if evidence.tail.upper_size is None:
            add(production, 'open_tail_upper_unknown', '10+ supplies no evidenced upper size.',
                required='supported_household_capacity')
        if evidence.tail.members.status != 'observed':
            add(production, 'open_tail_members_unknown', 'Exact tail person mass is missing or modeled.',
                required='supported_household_capacity')
        add(CAPABILITIES[2:], 'open_tail_instance_sizes_unknown', 'Even a tail member total cannot identify each instance size.',
            required='exact_instance_capacities')

    private = evidence.coverage.private_persons
    if private.status != 'observed':
        add(production, 'private_population_unknown', 'Need observed same-scope private-resident mass; no mean/residual inference.',
            required='private_person_mass')
    else:
        source = evidence.sources[private.source_id]
        if source.universe != 'ADNKS_private_household_residents':
            add(production, 'private_population_universe_mismatch', 'Private person count has an incompatible/unknown universe.')
        total = observed['totals']['private_household_persons']
        if total is None or not math.isclose(total, private.value, rel_tol=1e-10, abs_tol=1e-6):
            add(production, 'private_population_binding_mismatch', 'Evidence private total differs from reconciled private person mass.')
    universe = manifest.get('population_universe', {})
    if not isinstance(universe, Mapping):
        universe = {}
    institutional = evidence.coverage.institutional_persons
    if universe.get('definition') != 'ADNKS_private_household_residents' and institutional.status != 'observed':
        add(production, 'institutional_population_unknown', 'All-resident coverage needs an observed institutional bridge, not a residual.',
            required='population_universe_bridge')
    elif institutional.status == 'observed':
        if evidence.sources[institutional.source_id].universe != 'ADNKS_institutional_residents':
            add(production, 'institutional_universe_mismatch', 'Institutional source universe is incompatible.')
        if universe.get('definition') == 'ADNKS_residents' and universe.get('institutional_population') != institutional.value:
            add(production, 'institutional_binding_mismatch', 'Manifest and evidence institutional counts differ.')

    weights = columns.get('population_weight', ())
    unit_people = bool(weights) and all(type(w) in (int, float) and w == 1 for w in weights)
    unit_households = bool(households.records) and all(r.household_weight == 1 for r in households.records)
    representation = {'residents': 'unit_weights_only' if unit_people else 'weighted_representatives',
                      'households': 'unit_weights_only' if unit_households else 'weighted_representatives',
                      'unit_weights_establish_instances': False}
    if not (unit_people and unit_households):
        add(CAPABILITIES[2:], 'weighted_representatives_not_instances', 'Expansion weights cannot be equated with individual instance counts.',
            required='joint_instance_representation')
    else:
        add(CAPABILITIES[2:], 'instance_semantics_unverified', 'Unit weights alone do not establish production instance eligibility.',
            required='joint_instance_representation')
    if evidence.coverage.eligibility_status != 'observed':
        add(CAPABILITIES[2:], 'private_eligibility_missing', 'Aggregate coverage does not identify eligible individual members.',
            required='private_resident_eligibility')
    if evidence.relationships.status != 'observed':
        add(CAPABILITIES[3:], 'relationship_evidence_missing', 'Composition marginals/codebooks do not identify spouses or parent-child pairs.',
            required='relationship_observations')
    # This phase assesses prerequisites, never licenses an executable allocator.
    add(CAPABILITIES[1:2], 'allocation_method_not_implemented', 'Future weighted conservation method still requires review.',
        conditional=True, required='reviewed_allocation_method')
    add(CAPABILITIES[2:3], 'instance_method_not_implemented', 'No production instance assignment is implemented.',
        required='reviewed_instance_method')
    add(CAPABILITIES[3:], 'role_method_not_implemented', 'No family role or kinship method is implemented.',
        required='reviewed_role_method')

    for report in reports.values():
        report['missing_evidence'].sort()
        report['required_evidence'].sort()
    assumptions = list(evidence.assumptions)
    for claim in (*evidence.composition, *evidence.sizes, evidence.household_total,
                  evidence.tail.members, evidence.coverage.private_persons,
                  evidence.coverage.institutional_persons, evidence.tail):
        if claim.assumption and claim.assumption not in assumptions:
            assumptions.append(claim.assumption)
    return {'readiness_version': 'household-linkage-readiness-1',
            'capabilities': reports, 'production_assignment_enabled': False,
            'inputs': {'population_id': manifest.get('population_id'),
                       'household_population_id': hm.get('household_population_id'),
                       'resident_content_sha256': manifest.get('content_sha256'),
                       'household_content_sha256': hm.get('content_sha256'),
                       'input_fingerprints': fingerprints, 'evidence_sha256': evidence.fingerprint,
                       'reconciliation_sha256': canonical_hash(observed)},
            'reconciliation_status': observed['status'],
            'statistical_units': deepcopy(next(f for f in observed['findings'] if f['check'] == 'statistical_units')),
            'totals': deepcopy(observed['totals']), 'representation': representation,
            'coverage': evidence.coverage.model_dump(mode='json'),
            'tail': evidence.tail.model_dump(mode='json'),
            'composition_totals': evidence.composition_totals(),
            'household_evidence': {'composition': [c.model_dump(mode='json') for c in evidence.composition],
                                   'sizes': [c.model_dump(mode='json') for c in evidence.sizes],
                                   'total': evidence.household_total.model_dump(mode='json')},
            'assumptions': assumptions,
            'sources': sources,
            'source_declarations': evidence.model_dump(mode='json')['sources'],
            'limitations': ['Matching source bytes is not independent source authentication.',
                            'Aggregate modeling readiness does not establish the unobserved Ankara type-size joint.',
                            'No assignment, household instance ID, role, family edge or persona attribute is produced.']}
