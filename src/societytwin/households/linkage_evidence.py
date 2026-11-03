"""Versioned evidence declarations and optional local-byte checks; no assignment.

Source declarations and matching checksums are integrity bindings, not independent
authentication of the source or approval to link people.
"""
import csv
import io
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from pydantic import Field, model_validator
import yaml

from societytwin.common import canonical_hash, sha256_bytes
from societytwin.national.dependencies import TypedModel, _UniqueLoader

EvidenceStatus = Literal['observed', 'modeled', 'unknown', 'missing', 'unavailable']
Unit = Literal['person', 'household', 'persons_per_household']
Universe = Literal['ADNKS_residents', 'ADNKS_private_households',
                   'ADNKS_private_household_residents', 'ADNKS_institutional_residents', 'unknown']
LEAVES = ('one_person', 'couple_only', 'couple_with_children', 'lone_father',
          'lone_mother', 'extended', 'without_nuclear_family')
SIZE_CLASSES = tuple(str(n) for n in range(1, 10)) + ('10+',)
REPO_ROOT = Path(__file__).resolve().parents[3]


class LinkageEvidenceError(ValueError):
    pass


class Precision(TypedModel):
    kind: Literal['exact_integer_counts', 'rounded', 'unknown']
    decimal_places: int | None = Field(default=None, ge=0, strict=True)
    rounding_rule: str | None = None
    note: str = Field(min_length=1)

    @model_validator(mode='after')
    def integer_precision(self):
        if self.kind == 'exact_integer_counts' and self.decimal_places not in (None, 0):
            raise ValueError('Exact integer counts cannot declare fractional decimal precision')
        return self


class SourceEvidence(TypedModel):
    source_id: str = Field(min_length=1, pattern=r'^\S.*\S$|^\S$')
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    title: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    acquisition: str = Field(min_length=1)
    geography: str = Field(pattern=r'^(TR|0[1-9]|[1-7][0-9]|8[01])$')
    observation_year: int = Field(ge=1900, le=2200, strict=True)
    reference_year: int = Field(ge=1900, le=2200, strict=True)
    unit: Unit
    universe: Universe
    universe_note: str = Field(min_length=1)
    dimensions: tuple[str, ...] = Field(min_length=1)
    precision: Precision

    @model_validator(mode='after')
    def relative_path(self):
        posix, windows = PurePosixPath(self.path), PureWindowsPath(self.path)
        if (posix.is_absolute() or windows.is_absolute() or windows.drive
                or '\\' in self.path or ':' in self.path or '..' in posix.parts):
            raise ValueError('Evidence paths must be portable relative paths without traversal')
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError('Duplicate source dimensions')
        return self


class CountClaim(TypedModel):
    status: EvidenceStatus
    source_id: str | None = None
    source_indicator: str | None = None
    value: int | None = Field(default=None, ge=0, strict=True)
    assumption: str | None = None
    note: str = Field(min_length=1)

    @model_validator(mode='after')
    def evidence_binding(self):
        present = self.status in ('observed', 'modeled')
        if present != (self.value is not None) or (present and not self.source_id):
            raise ValueError('Present counts require a source and value; missing evidence cannot carry a count')
        if self.status == 'modeled' and (not self.assumption or not self.assumption.strip()):
            raise ValueError('Modeled evidence requires an explicit assumption')
        return self


class CompositionCell(CountClaim):
    category: Literal['one_person', 'couple_only', 'couple_with_children', 'lone_father',
                      'lone_mother', 'extended', 'without_nuclear_family']
    source_indicator: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    definition: str = Field(min_length=1)


class SizeCell(CountClaim):
    category: str


class TailEvidence(TypedModel):
    category: Literal['10+'] = '10+'
    lower_size: Literal[10] = 10
    upper_size: int | None = Field(default=None, ge=10, strict=True)
    upper_status: EvidenceStatus = 'unknown'
    upper_source_id: str | None = None
    assumption: str | None = None
    members: CountClaim
    note: str = Field(min_length=1)

    @model_validator(mode='after')
    def bounds(self):
        if (self.upper_status in ('observed', 'modeled')) != (self.upper_size is not None):
            raise ValueError('Tail upper bound must have an evidence status')
        if self.upper_size is not None and not self.upper_source_id:
            raise ValueError('Tail upper bound requires a source')
        if self.upper_status == 'modeled' and not self.assumption:
            raise ValueError('Modeled tail upper bound requires an assumption')
        return self


class CoverageEvidence(TypedModel):
    private_persons: CountClaim
    institutional_persons: CountClaim
    eligibility_status: EvidenceStatus
    eligibility_source_ids: tuple[str, ...] = ()
    note: str = Field(min_length=1)

    @model_validator(mode='after')
    def references(self):
        if self.eligibility_status in ('observed', 'modeled') and not self.eligibility_source_ids:
            raise ValueError('Eligibility declarations require sources')
        return self


class RelationshipEvidence(TypedModel):
    status: EvidenceStatus
    source_ids: tuple[str, ...] = ()
    note: str = Field(min_length=1)

    @model_validator(mode='after')
    def references(self):
        if self.status in ('observed', 'modeled') and not self.source_ids:
            raise ValueError('Relationship evidence requires sources')
        return self


class LinkageEvidence(TypedModel):
    schema_version: Literal['household-linkage-evidence-1']
    registry_version: str = Field(min_length=1)
    geography: str = Field(pattern=r'^(0[1-9]|[1-7][0-9]|8[01])$')
    reference_year: int = Field(ge=1900, le=2200, strict=True)
    sources: dict[str, SourceEvidence]
    composition: tuple[CompositionCell, ...] = ()
    household_total: CountClaim
    sizes: tuple[SizeCell, ...] = ()
    tail: TailEvidence
    coverage: CoverageEvidence
    relationships: RelationshipEvidence
    assumptions: tuple[str, ...] = ()

    @model_validator(mode='after')
    def contract(self):
        if any(key != s.source_id for key, s in self.sources.items()):
            raise ValueError('Source mapping keys must match source identifiers')
        categories = [c.category for c in self.composition]
        if len(set(categories)) != len(categories):
            raise ValueError('Duplicate composition leaves')
        sizes = [c.category for c in self.sizes]
        if len(set(sizes)) != len(sizes) or set(sizes) - set(SIZE_CLASSES):
            raise ValueError('Duplicate or unsupported household size category')
        claims = [(c, 'household') for c in (*self.composition, *self.sizes, self.household_total)]
        claims += [(c, 'person') for c in (self.tail.members, self.coverage.private_persons,
                                          self.coverage.institutional_persons)]
        for claim, unit in claims:
            if claim.source_id and (claim.source_id not in self.sources
                                    or self.sources[claim.source_id].unit != unit):
                raise ValueError('Missing source reference or incompatible statistical unit')
            if unit == 'person' and claim.status == 'observed' and not claim.source_indicator:
                raise ValueError('Observed person mass requires its source indicator')
        refs = (*self.relationships.source_ids, *self.coverage.eligibility_source_ids)
        if self.tail.upper_source_id:
            refs += (self.tail.upper_source_id,)
        if any(ref not in self.sources for ref in refs):
            raise ValueError('Unknown evidence source reference')
        complete = len(categories) == 7 and all(c.value is not None for c in self.composition)
        if complete and self.household_total.value is not None:
            if sum(c.value for c in self.composition) != self.household_total.value:
                raise ValueError('Disjoint composition leaves do not sum to household total')
        if len(sizes) == 10 and all(c.value is not None for c in self.sizes):
            if self.household_total.value is not None and sum(c.value for c in self.sizes) != self.household_total.value:
                raise ValueError('Size counts do not sum to household total')
        size_values = {c.category: c.value for c in self.sizes}
        composition_values = {c.category: c.value for c in self.composition}
        if (size_values.get('1') is not None and composition_values.get('one_person') is not None
                and size_values['1'] != composition_values['one_person']):
            raise ValueError('One-person composition and size-one counts differ')
        count, members = size_values.get('10+'), self.tail.members.value
        if count is not None and members is not None:
            if members < 10 * count or (self.tail.upper_size is not None and members > self.tail.upper_size * count):
                raise ValueError('Tail member count contradicts household size bounds')
        return self

    @property
    def fingerprint(self):
        return canonical_hash(self.model_dump(mode='json'))

    def composition_totals(self):
        """Derived hierarchy only; never add nested aggregates to the partition."""
        values = {c.category: c.value for c in self.composition}
        def total(keys):
            return sum(values[k] for k in keys) if all(values.get(k) is not None for k in keys) else None
        return {'leaf_total': total(LEAVES),
                'nuclear': total(('couple_only', 'couple_with_children', 'lone_father', 'lone_mother')),
                'lone_parent': total(('lone_father', 'lone_mother'))}


def load_linkage_evidence(path=None):
    try:
        payload = yaml.load(Path(path or REPO_ROOT/'data/household_linkage_evidence.yaml').read_text(
            encoding='utf-8'), Loader=_UniqueLoader)
        return LinkageEvidence.model_validate(payload)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        raise LinkageEvidenceError(f'Invalid linkage evidence: {exc}') from exc


def inspect_sources(evidence, source_root=None):
    """Read local bytes only. Matching hash does not authenticate their publisher.

    No parent-worktree discovery, downloads, file writes or source regeneration.
    Known composition and size claims are also compared with the hashed CSV rows.
    """
    results = {}
    for key, source in sorted(evidence.sources.items()):
        result = {'source_id': key, 'path': source.path, 'expected_sha256': source.sha256,
                  'actual_sha256': None, 'status': 'not_checked'}
        results[key] = result
        if source_root is None:
            continue
        declared_root = Path(source_root).absolute()
        path = declared_root/source.path
        if (any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))
                or not path.resolve().is_relative_to(declared_root.resolve())):
            result['status'] = 'unsafe_path'
            continue
        try:
            raw = path.read_bytes()
            result['actual_sha256'] = sha256_bytes(raw)
            if result['actual_sha256'] != source.sha256:
                result['status'] = 'checksum_mismatch'
                continue
            expected = [c for c in (*evidence.composition, *evidence.sizes, evidence.household_total,
                                    evidence.coverage.private_persons, evidence.coverage.institutional_persons,
                                    evidence.tail.members)
                        if c.source_id == key and c.status == 'observed']
            if expected:
                rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
                for claim in expected:
                    if isinstance(claim, SizeCell):
                        matched = [r for r in rows if r.get('household_size_class') == claim.category
                                   and r.get('province_code') == source.geography
                                   and r.get('reference_year') == str(source.observation_year)]
                        values = [r['households'] for r in matched]
                    else:
                        indicator = claim.source_indicator or 'households_total'
                        matched = [r for r in rows if r.get('indicator') == indicator
                                   and r.get('province_code') == source.geography
                                   and r.get('year') == str(source.observation_year)
                                   and r.get('unit') == source.unit]
                        values = [r['value'] for r in matched]
                    if len(values) != 1 or not values[0].isascii() or not values[0].isdigit() or int(values[0]) != claim.value:
                        raise ValueError('Declared observed count differs from CSV')
            result['status'] = 'matched'
        except FileNotFoundError:
            result['status'] = 'unavailable'
        except (OSError, ValueError, KeyError, UnicodeError, csv.Error):
            result['status'] = 'malformed_or_claim_mismatch'
    return results
