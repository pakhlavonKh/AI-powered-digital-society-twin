"""Versioned, dependency-light projection of an already selected persona view.

No generation, sampling, defaults, field selection or lossy transformations.
The small crosswalk was reviewed against MatrAIx's 1.0 dimension catalog at
3633d8dab149a9482a71b024418a49ae828cc941. An optional caller-supplied catalog
can validate emitted native values; no checkout or upstream import is required.
"""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass

from societytwin.common import canonical_hash

CROSSWALK_VERSION = 'dst-matraix-projection-1'
REVIEWED_UPSTREAM_COMMIT = '3633d8dab149a9482a71b024418a49ae828cc941'
UPSTREAM_SCHEMA_VERSION = '1.0'


class ProjectionError(ValueError):
    pass


@dataclass(frozen=True)
class MappingRule:
    field: str
    custom_dimension: str
    classification: str
    upstream_candidate: str | None
    reason: str
    exact_values: tuple[tuple[str, str], ...] = ()


# Classifications describe native-catalog mapping, not the fidelity of custom
# dimensions: selected custom display values are always preserved verbatim.
# Lossy candidates are documentation only; this version approves none of them.
CROSSWALK = (
    MappingRule('province_name', 'dst_residence_province', 'unsupported', None,
                'Province of residence has no reviewed exact catalog equivalent.'),
    MappingRule('age_group', 'dst_age_group', 'lossy', 'age_bracket',
                'Five-year ADNKS bands cross upstream life-age bucket boundaries.'),
    MappingRule('age', 'dst_age', 'lossy', 'age_bracket',
                'Bucketing loses precision; DST exact age may be assumed or top-coded.'),
    MappingRule('sex', 'dst_sex', 'unsupported', 'gender_identity',
                'Administrative sex does not establish self-identified gender.'),
    MappingRule('marital_status', 'dst_marital_status', 'unsupported', 'demo_marital_status',
                'Only married/divorced/widowed are equivalent; never married does not mean Single.',
                (('married', 'Married'), ('divorced', 'Divorced'), ('widowed', 'Widowed'))),
    MappingRule('education_level', 'dst_education_level', 'lossy', 'highest_education',
                'Turkish attainment definitions and combined associate/bachelor category do not align with the global buckets.'),
    MappingRule('labour_status', 'dst_labour_status', 'lossy', 'demo_employment_status',
                'ILO labour-force status cannot establish work hours, occupation or retirement/student status.'),
    MappingRule('household_size_class', 'dst_household_size_class', 'lossy', 'lstyle_household_size',
                'Upstream household buckets coarsen closed sizes and cannot resolve an open tail.'),
    MappingRule('household_type', 'dst_household_type', 'unsupported', None,
                'No reviewed exact household-type equivalent; membership supplies no type.'),
    MappingRule('urbanicity', 'dst_urbanicity', 'unsupported', None,
                'Administrative settlement type is not degree of urbanisation.'),
    MappingRule('reference_year', 'dst_reference_year', 'unsupported', None,
                'Reference year is context only and has no reviewed native equivalent.'),
    MappingRule('degurba_class', 'dst_degurba_class', 'unsupported', None,
                'Selected sidecar display and its existing limitation are preserved, without inferring an address.'),
)


def validate_catalog_dimensions(document, catalog):
    """Check native enums against raw upstream dimensions.json, without defaults.

    Custom DST keys are explicitly registered extensions, not claims of catalog
    membership. This is a projection check, not population validation.
    """
    if not isinstance(catalog, Mapping) or not isinstance(catalog.get('dimensions'), list):
        raise ProjectionError('Catalog must contain the upstream dimensions list.')
    indexed = {}
    for row in catalog['dimensions']:
        if not isinstance(row, Mapping) or not isinstance(row.get('id'), str) or row['id'] in indexed:
            raise ProjectionError('Catalog has malformed or duplicate dimension identifiers.')
        indexed[row['id']] = row
    custom_keys = {r.custom_dimension for r in CROSSWALK}
    findings, native, custom = [], [], []
    if str(catalog.get('schemaVersion')) != UPSTREAM_SCHEMA_VERSION:
        findings.append('Unsupported upstream schema version.')
    for key, value in document['dimensions'].items():
        if key in custom_keys:
            custom.append(key)
            continue
        native.append(key)
        row = indexed.get(key)
        if row is None or not isinstance(row.get('values'), list) or value not in row['values']:
            findings.append(f'Unsupported catalog dimension/value: {key}.')
    return {'status': 'incompatible' if findings else 'compatible',
            'catalog_dimensions': sorted(native), 'custom_dimensions': sorted(custom),
            'findings': findings}


def project_persona(persona, *, catalog=None):
    """Project only supported, explicitly visible fields from production builders.

    Unregistered keys and inconsistent selection/status metadata fail closed.
    Research metadata remains under metadata and never becomes a dimension,
    summary or system prompt. No arbitrary dst_* passthrough is supported.
    """
    visible = persona['model_visible']
    if not isinstance(visible, Mapping):
        raise ProjectionError('model_visible must be a field mapping.')
    rules = {r.field: r for r in CROSSWALK}
    if set(visible) - rules.keys():
        raise ProjectionError('Unregistered visible persona fields; add a reviewed crosswalk rule before exposure.')
    if set(persona.get('model_visible_fields', visible)) != set(visible):
        raise ProjectionError('Persona visible-field declarations disagree.')
    attrs = persona['attributes']
    indexed = {}
    for entry in attrs:
        field = entry['field']
        if field in indexed:
            raise ProjectionError('Duplicate persona attribute declarations.')
        indexed[field] = entry
    if 'field_selection' in persona:
        policy = persona['field_selection']['config']
        selected = set(policy['required']) | set(policy['optional'])
        if not set(visible) <= selected & set(policy['allowlist']):
            raise ProjectionError('Visible fields violate the explicit selection policy.')
    dims, decisions = {}, []
    for rule in CROSSWALK:
        entry = indexed.get(rule.field)
        if rule.field not in visible:
            if entry is not None:
                decisions.append({'field': rule.field, 'action': 'omitted',
                                  'status': entry['status'], 'classification': rule.classification})
            continue
        text = visible[rule.field]
        if (entry is None or entry['status'] not in ('visible', 'assigned', 'published_unknown')
                or entry.get('value') is None or entry.get('value') == 'not_applicable'
                or not isinstance(text, str) or not text.strip() or text != entry.get('display')):
            raise ProjectionError(f'{rule.field}: visible value conflicts with attribute availability/display.')
        dims[rule.custom_dimension] = text
        mapped = dict(rule.exact_values).get(entry['value']) if isinstance(entry['value'], str) else None
        if mapped is not None and entry['status'] != 'published_unknown':
            dims[rule.upstream_candidate] = mapped
        else:
            mapped = None
        decisions.append({'field': rule.field, 'action': 'custom_and_exact' if mapped else 'custom_only',
                          'status': entry['status'], 'custom_dimension': rule.custom_dimension,
                          'classification': 'exact' if mapped else rule.classification,
                          'upstream_candidate': rule.upstream_candidate,
                          'upstream_value': mapped, 'reason': rule.reason})
    identity = {key: persona[key] for key in ('population_id', 'synthetic_id', 'persona_id')}
    if any(not isinstance(value, str) or not value.strip() for value in identity.values()):
        raise ProjectionError('Population, resident and persona identities are required.')
    projection = {'crosswalk_version': CROSSWALK_VERSION, 'upstream_schema_version': UPSTREAM_SCHEMA_VERSION,
                  'reviewed_upstream_commit': REVIEWED_UPSTREAM_COMMIT, 'decisions': decisions,
                  'lossy_transformations': [], 'dimension_content_sha256': canonical_hash(dims)}
    result = {'persona_id': persona['synthetic_id'], 'version': '1.0', 'source': 'synthetic',
              # Upstream otherwise manufactures display_name from persona_id,
              # which leaks the technical resident identifier into its templates.
              'display_name': 'Resident', 'dimensions': dims,
              'metadata': {'societytwin_persona_id': persona['persona_id'],
                           'template_version': persona['template_version'],
                           'population_id': persona['population_id'], 'resident_identity': identity,
                           'prompt_visible_fields': sorted(dims), 'projection': projection,
                           'hidden_fields': deepcopy(persona['hidden']),
                           'evidence_limitations': deepcopy(persona['limitations']),
                           'provenance': deepcopy(persona['provenance'])}}
    if 'field_selection' in persona:
        result['metadata']['field_selection'] = deepcopy(persona['field_selection'])
    if catalog is not None:
        assessment = validate_catalog_dimensions(result, catalog)
        if assessment['status'] != 'compatible':
            raise ProjectionError('; '.join(assessment['findings']))
        result['metadata']['projection']['catalog_assessment'] = assessment
    return result
