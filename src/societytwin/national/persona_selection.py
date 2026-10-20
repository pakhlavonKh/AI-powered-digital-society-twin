"""Explicit, versioned persona exposure policy; no generation or model calls."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from societytwin.common import canonical_hash, sha256_bytes
from societytwin.enrichment.engine import validate
from societytwin.enrichment.registry import EnrichmentError
from societytwin.enrichment.store import ExtensionStore
from societytwin.national.personas import PERSON_FIELDS, build_persona

SUPPORTED = frozenset(PERSON_FIELDS) - {'household_size_class', 'household_type'} | {'degurba_class'}
LIMITATION = ('Synthetic DEGURBA class sampled from province/sex aggregate counts; independence from other '
              'resident attributes within sex is assumed. Not an observed individual location, address or district.')


class FieldSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['persona-field-selection-1'] = 'persona-field-selection-1'
    allowlist: list[str]
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    max_attributes: int = Field(default=6, ge=1, le=12, strict=True)
    missingness: Literal['omit', 'error'] = 'omit'
    sidecar_root: str | None = None
    sidecar_id: str | None = None

    @model_validator(mode='after')
    def contract(self):
        selected = self.required + self.optional
        for fields in (self.allowlist, selected):
            if len(fields) != len(set(fields)):
                raise ValueError('Duplicate persona fields')
            if set(fields) - SUPPORTED:
                raise ValueError(f'Unsupported persona fields: {sorted(set(fields) - SUPPORTED)}')
        if not set(selected) <= set(self.allowlist):
            raise ValueError('Selected fields must belong to the experiment allowlist')
        if len(selected) > self.max_attributes:
            raise ValueError('Persona selection exceeds max_attributes')
        if bool(self.sidecar_root) != bool(self.sidecar_id):
            raise ValueError('Both sidecar_root and sidecar_id are required')
        return self


class PersonaResolver:
    """Validate once per sample, then resolve exact resident IDs without altering membership."""
    def __init__(self, core, selection: FieldSelection, extension=None):
        self.core, self.selection = core, selection
        self.rows = {r['synthetic_id']: r for r in core.table.to_pylist()}
        if len(self.rows) != core.table.num_rows or any(not i for i in self.rows):
            raise EnrichmentError('Missing/duplicate core synthetic IDs')
        if extension is None and selection.sidecar_id:
            extension = ExtensionStore(selection.sidecar_root).load(selection.sidecar_id, core)
        self.extension = extension
        self.values = {}
        if extension is not None:
            validate(extension, core)
            m = extension.manifest
            for name, a in m['registry']['attributes'].items():
                e = m['evidence'].get(name)
                if e is not None and e['status'] != 'unsupported' and e['source_sha256'] != a['source']['sha256']:
                    raise EnrichmentError('Sidecar source version mismatch')
                if e is not None and canonical_hash({'attribute': a, 'evidence': e}) != m['provenance_profiles'][name]:
                    raise EnrichmentError('Sidecar provenance/source version mismatch')
            self.values = {r.synthetic_id: {v.attribute: v for v in r.attributes} for r in extension.records}

    def build(self, synthetic_id):
        record = self.rows[synthetic_id]
        s = self.selection
        selected = s.required + s.optional
        persona = build_persona(record, self.core.manifest, [f for f in selected if f in PERSON_FIELDS])
        resolution = []
        for field in selected:
            if field in PERSON_FIELDS:
                entry = next(a for a in persona['attributes'] if a['field'] == field)
            else:
                value = self.values.get(synthetic_id, {}).get(field)
                status = value.status if value else 'unavailable'
                evidence = {}
                if value:
                    m = self.extension.manifest
                    a = m['registry']['attributes'][field]
                    evidence = {'evidence_class': a['evidence_class'], 'assumption': a['assumption'],
                                'source': a['source'], 'provenance': a['provenance'],
                                'registry_version': m['registry']['registry_version'],
                                'artifact_id': m['artifact_id'], 'provenance_profile': value.provenance_profile}
                available = status in ('assigned', 'published_unknown')
                text = f'{value.value.replace("_", " ")}. {LIMITATION}' if available else None
                entry = {'field': field, 'label': 'DEGURBA class', 'value': value.value if value else None,
                         'display': text, 'status': status, 'evidence': evidence}
                persona['attributes'].append(entry)
                if available:
                    persona['model_visible'][field] = text
                    persona['persona_card'] += f'\n- DEGURBA class: {text}'
                    persona['limitations'].append(LIMITATION)
            available = entry['status'] in ('visible', 'assigned', 'published_unknown')
            if not available and (field in s.required or s.missingness == 'error'):
                raise EnrichmentError(f'{field}: required selected attribute unavailable ({entry["status"]})')
            resolution.append({'field': field, 'status': entry['status'], 'evidence': entry['evidence']})
        persona['model_visible_fields'] = sorted(persona['model_visible'])
        persona['persona_card_sha256'] = sha256_bytes(persona['persona_card'].encode())
        persona['field_selection'] = {'config': s.model_dump(), 'resolution': resolution}
        persona['persona_id'] = 'per-' + canonical_hash({'base': persona['persona_id'],
            'selection': persona['field_selection'], 'card': persona['persona_card_sha256']})[:16]
        return persona


def experiment_persona_builder(core, policy):
    if policy.field_selection is None:
        return lambda synthetic_id: build_persona(core.record(synthetic_id), core.manifest, policy.visible_fields)
    return PersonaResolver(core, policy.field_selection).build
