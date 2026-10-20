"""Opt-in national broad-age marital seed with explicit rounding sensitivity.

Published percentages and reconstructed scenario probabilities remain separate.
Nearest-tenth rounding is a model assumption, not a verified TÜİK algorithm.
No observation is labelled an Ankara age-specific count.
"""
from __future__ import annotations

import hashlib
import math
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import model_validator

from societytwin.national.dependencies import MaritalStrategy, RegistryError, TypedModel, _UniqueLoader
from societytwin.national.fitting import ipf_2d
from societytwin.national.model import SourceOption
from societytwin.national.vocab import AGE_GROUPS, VOCABULARIES, band_bounds

REPO_ROOT = Path(__file__).resolve().parents[3]
FRACTIONS = {'lower_quartile': Decimal('0.25'), 'midpoint': Decimal('0.5'), 'upper_quartile': Decimal('0.75')}
BANDS = ('15-24', '25+')
CATEGORIES = VOCABULARIES['marital_status'].codes
SEXES = VOCABULARIES['sex'].codes


class PublishedRow(TypedModel):
    sex: Literal['male', 'female']
    age_band: Literal['15-24', '25+']
    published_percent: tuple[float, float, float, float]


class MaritalEvidence(TypedModel):
    schema_version: Literal['national-marital-percentages-1']
    source_version: str
    title: str
    publication_number: str
    publication_date: str
    isbn: str
    table: Literal['1.9']
    printed_page: Literal[14]
    pdf_page: Literal[36]
    url: str
    methodology_url: str
    reference_year: Literal[2025]
    geography: Literal['TR']
    unit: Literal['percent']
    denominator: str
    precision_pp: Literal[0.1]
    categories: tuple[str, ...]
    rounding_rule_confirmed: Literal[False]
    zero_interpretation: str
    acquisition: str
    reuse: str
    rows: tuple[PublishedRow, ...]

    @model_validator(mode='after')
    def check_cells(self):
        if self.categories != CATEGORIES:
            raise ValueError('marital evidence category order must match the canonical vocabulary')
        keys = [(r.sex, r.age_band) for r in self.rows]
        if len(keys) != 4 or set(keys) != {(s, b) for s in SEXES for b in BANDS}:
            raise ValueError('marital evidence needs exactly four unique sex/broad-age rows')
        for row in self.rows:
            values = [Decimal(str(v)) for v in row.published_percent]
            if any(not v.is_finite() or not 0 <= v <= 100 or v % Decimal('0.1') for v in values):
                raise ValueError('marital evidence requires finite nonnegative one-decimal percentages')
            if sum(values) != 100:
                raise ValueError('marital evidence percentage rows must sum to 100')
            # This version reconstructs only the two known rounded-zero cells.
            zeros = [i for i, v in enumerate(values) if v == 0]
            if zeros != ([CATEGORIES.index('widowed')] if row.age_band == '15-24' else []):
                raise ValueError('unexpected zero/missing-cell pattern for this source version')
        return self


def load_evidence(strategy: MaritalStrategy) -> MaritalEvidence:
    try:
        raw = (REPO_ROOT / strategy.source_file).read_bytes()
        if hashlib.sha256(raw).hexdigest() != strategy.source_sha256:
            raise ValueError('marital source checksum mismatch')
        return MaritalEvidence.model_validate(yaml.load(raw.decode('utf-8-sig'), Loader=_UniqueLoader))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise RegistryError(f'Invalid national marital evidence: {exc}') from exc


def reconstruct(evidence: MaritalEvidence, variant: str) -> tuple[dict, list[dict]]:
    """Choose named interior points of the assumed rounding interval, not estimates.

    For a printed zero the assumed nearest-tenth interval is [0, 0.05) pp.
    Use its quartiles and subtract that mass from never-married. This minimal
    paired adjustment preserves normalization and all displayed rounding cells.
    These three scenarios are neither a prior nor an exhaustive uncertainty set.
    """
    if variant not in FRACTIONS:
        raise RegistryError(f'Unknown marital zero-cell sensitivity variant: {variant}')
    half = Decimal(str(evidence.precision_pp)) / 2
    out, audit = {}, []
    for row in evidence.rows:
        printed = [Decimal(str(v)) for v in row.published_percent]
        lower = [max(Decimal(0), v - half) for v in printed]
        upper = [min(Decimal(100), v + half) for v in printed]
        scenario = list(printed)
        if row.age_band == '15-24':
            mass = half * FRACTIONS[variant]
            scenario[CATEGORIES.index('widowed')] = mass
            scenario[CATEGORIES.index('never_married')] -= mass
        if sum(scenario) != 100 or any(not lo <= v < hi for lo, v, hi in zip(lower, scenario, upper)):
            raise RegistryError('Marital reconstruction is infeasible within assumed rounding intervals')
        out[(row.sex, row.age_band)] = [float(v / 100) for v in scenario]
        audit.append({'sex': row.sex, 'age_band': row.age_band, 'published_percent': list(row.published_percent),
                      'assumed_lower_pp': list(map(float, lower)), 'assumed_upper_pp_exclusive': list(map(float, upper)),
                      'scenario_percent': list(map(float, scenario))})
    return out, audit


def broad_band(band: str) -> str | None:
    low, high = band_bounds(band)
    if high is not None and high < 15:
        return None
    if low >= 25:
        return '25+'
    if low >= 15 and high is not None and high <= 24:
        return '15-24'
    raise RegistryError(f'Age band {band} crosses a national marital source boundary')


def transferred_conditionals(store, province, root, year: int, strategy: MaritalStrategy) -> dict:
    evidence = load_evidence(strategy)
    if province.code != strategy.province_code or year != 2025 or root.year != year:
        raise RegistryError('national_age_marital_seed_v1 requires Ankara and matching 2025 root/targets')
    target = store.best('marital_status_sex', province, year)
    if target is None or (target.geo_level, target.geo_code, target.year) != ('province', province.code, year):
        raise RegistryError('national marital transfer requires observed Ankara 2025 marital_status_sex targets')
    if target.meta.universe_min_age != 15 or root.meta.universe_min_age != 0:
        raise RegistryError('national marital transfer requires matching root and age-15+ marital universes')
    for selection, expected in ((root, {(b, s) for b in AGE_GROUPS for s in SEXES}),
                                (target, {(s, c) for s in SEXES for c in CATEGORIES})):
        dims = ('age_group', 'sex') if selection is root else ('sex', 'category')
        keys = [r.key(dims) for r in selection.rows]
        if (len(keys) != len(expected) or set(keys) != expected or
            any(r.value_status != 'OBSERVED' or r.value is None or not math.isfinite(r.value) or r.value < 0
                for r in selection.rows)):
            raise RegistryError('national marital transfer rejects missing, duplicate or non-observed target/root cells')
    probabilities, reconstruction = reconstruct(evidence, strategy.zero_variant)
    root_counts, target_counts = root.counts(), target.counts()
    cond, diagnostics = {}, {}
    for sex in SEXES:
        rows = [math.fsum(v for (b, s), v in root_counts.items() if s == sex and broad_band(b) == broad)
                for broad in BANDS]
        cols = [target_counts[(sex, c)] for c in CATEGORIES]
        if any(v <= 0 for v in rows) or abs(math.fsum(rows) - math.fsum(cols)) > 1e-8:
            raise RegistryError('Ankara age-15+ and marital target totals conflict; no automatic rescaling allowed')
        seed = [probabilities[(sex, broad)] for broad in BANDS]
        fit = ipf_2d(rows, cols, seed, tol=1e-12)
        relative = max([abs(math.fsum(row) / t - 1) for row, t in zip(fit.table, rows)] +
                       [abs(math.fsum(row[j] for row in fit.table) / t - 1) if t else
                        abs(math.fsum(row[j] for row in fit.table)) for j, t in enumerate(cols)])
        if not fit.converged or relative > 1e-8 or any(not math.isfinite(v) or v < 0 for row in fit.table for v in row):
            raise RegistryError('National marital seed IPF failed or targets are infeasible')
        fitted = [[v / math.fsum(row) for v in row] for row in fit.table]
        for band in AGE_GROUPS:
            broad = broad_band(band)
            if broad is not None:
                cond[(band, sex)] = fitted[BANDS.index(broad)]
        diagnostics[sex] = {'converged': fit.converged, 'iterations': fit.iterations,
                            'max_abs_residual': fit.max_abs_residual, 'max_relative_residual': relative,
                            'column_scale': fit.column_scale, 'broad_age_bands': list(BANDS),
                            'row_targets': rows, 'column_targets': cols, 'fitted_counts': fit.table,
                            'fitted_probabilities': fitted, 'seed_probabilities': seed}
    return {'selection': target, 'option': SourceOption('marital_status_sex', strategy.model_version),
            'conditionals': cond, 'min_age': 15, 'codes': CATEGORIES, 'strict_targets': True,
            'provenance': {'evidence': 'MARGINAL_INFERENCE', 'evidence_class': 'D', 'table_id': 'marital_status_sex',
                'method': strategy.model_version, 'method_text': 'National broad-age seed fitted to Ankara age/sex and marital/sex counts using IPF.',
                'geo_level': 'province', 'geo_code': province.code, 'source_year': year, 'source_ids': target.source_ids,
                'conditioning': ['broad_age_band', 'sex'], 'unobserved_joint_with': ['Ankara age_group'],
                'universe_min_age': 15, 'universe_note': target.meta.universe_note,
                'outside_universe': "'not_applicable' below age 15 (RULE_CONSTRAINED)", 'structural_zeros': False,
                'transfer': {'source_geography': 'TR', 'source_year': 2025, 'source_version': evidence.source_version,
                             'source_url': evidence.url, 'source_sha256': strategy.source_sha256,
                             'publication': evidence.title, 'table': evidence.table, 'printed_page': evidence.printed_page,
                             'unit': evidence.unit, 'denominator': evidence.denominator, 'precision_pp': evidence.precision_pp,
                             'acquisition': evidence.acquisition, 'categories': list(CATEGORIES),
                             'model_version': strategy.model_version, 'policy_version': strategy.policy_version,
                             'zero_variant': strategy.zero_variant, 'rounding_rule_confirmed': False,
                             'reconstruction': reconstruction},
                'limitations': ['National age association is transferred/modelled, not observed for Ankara.',
                    'Nearest-tenth rounding is assumed; no table-specific rule or unrounded cells were acquired.',
                    'Positive zero-cell scenarios are sensitivity choices, not estimated probabilities or exact counts.',
                    'Conditional probabilities are constant within 15-24 and 25+ before record calibration; no elderly gradient is observed.',
                    'Local calibration can change the national percentages. No independent or behavioural validation.'],
                'diagnostics': {'ipf': diagnostics}}}
