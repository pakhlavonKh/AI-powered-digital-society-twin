"""One national generator; province is a dimension.

``generate(store, config)`` builds a synthetic population for every requested province that has the
root table (province × age group × sex) for a year not after the reference year. Steps per province:

1. **Allocation** (controlled rounding). The province's record count is fixed first (proportional to
   its population, optionally with a floor so small provinces can be analysed), then split over its
   age × sex cells by the largest-remainder method. Allocation is deterministic; it does not depend on
   the seed. Cells that receive no record are collapsed into the nearest allocated band of the same
   sex for weighting, and every collapse is recorded.
2. **Exact age**: uniform within the five-year band (ASSUMED); the open 90+ band is top-coded at 90.
3. **Attributes**, in dependency order, from ``model.ATTRIBUTES`` (see that module for evidence levels).
4. **Weights**: design weight = cell population ÷ cell records; then raking to every province-level
   control table used, so weighted estimates reproduce the controls up to the reported tolerance.

Randomness comes from independent SHA-256 streams per (province, attribute), so adding a province or
an attribute never changes the draws of another.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from societytwin.common import canonical_hash, utc_now
from societytwin.national import GENERATOR_VERSION
from societytwin.national import geography as geo
from societytwin.national.constraints import RULES, structural_zero
from societytwin.national.controls import TABLE_KINDS, ControlStore, Selection
from societytwin.national.dependencies import DependencyRegistry, RegistryError, load_registry
from societytwin.national.fitting import Margin, ipf_2d, largest_remainder, rake
from societytwin.national.model import METHOD_TEXT, NOT_MODELLED, compatibility_attributes, dependency_graph
from societytwin.national.marital import transferred_conditionals
from societytwin.national.rng import STREAM_VERSION, Stream, cumulative
from societytwin.national.vocab import AGE_GROUPS, NOT_APPLICABLE, TOP_CODE_AGE, VOCABULARIES, Evidence, band_bounds

COLUMNS = ("synthetic_id", "province_code", "province_name", "nuts1_code", "nuts2_code", "nuts3_code", "age", "age_group",
           "age_top_coded", "sex", "marital_status", "education_level", "labour_status", "household_size_class",
           "household_type", "urbanicity", "population_weight", "design_weight", "provenance_profile", "reference_year")
SEXES = VOCABULARIES["sex"].codes
MAX_SIZE = 1_000_000
# An attribute margin is imposed only if raking converges with every final weight within these multiples of its design
# weight. A margin that can only be met by shrinking a record almost to nothing (or inflating it far beyond its cell)
# is effectively unattainable at that sample size; it is reported instead of forced.
WEIGHT_RATIO_BOUNDS = (0.05, 20.0)
RAKE_MAX_ITER = 5000


class GenerationError(ValueError):
    pass


@dataclass(frozen=True)
class GenerationConfig:
    reference_year: int = 2025
    synthetic_size: int = 10_000
    seed: int = 42
    provinces: tuple[str, ...] | None = None          # plate codes; None = every province with root coverage
    min_records_per_province: int = 0                 # oversampling floor; weights correct for it
    calibrate: bool = True

    def normalized(self) -> dict:
        return {"reference_year": self.reference_year, "synthetic_size": self.synthetic_size, "seed": self.seed,
                "provinces": sorted(self.provinces) if self.provinces else None,
                "min_records_per_province": self.min_records_per_province, "calibrate": self.calibrate}


@dataclass
class GeneratedPopulation:
    columns: dict[str, list]
    manifest: dict
    profiles: dict[str, dict]
    timings: dict = field(default_factory=dict)


def _universe_fraction(band: str, min_age: int) -> float:
    low, high = band_bounds(band)
    if high is None:
        return 1.0 if TOP_CODE_AGE >= min_age else 0.0
    if high < min_age:
        return 0.0
    if low >= min_age:
        return 1.0
    return (high - min_age + 1) / (high - low + 1)  # uniform-within-band, consistent with the exact-age assumption


def _band_ages(band: str) -> list[int]:
    low, high = band_bounds(band)
    return [TOP_CODE_AGE] if high is None else list(range(low, high + 1))


def _root(store: ControlStore, p: geo.Province, year: int) -> Selection | None:
    sel = store.best("population_age_sex", p, year)
    return sel if sel and sel.geo_level == "province" else None


def _conditionals(spec, store: ControlStore, p: geo.Province, year: int, root_counts: dict) -> dict:
    """For one attribute and province: chosen source, per (age_group, sex) category weights, and provenance."""
    vocab = VOCABULARIES[spec.attribute]
    for option in spec.options:
        sel = store.best(option.table_id, p, year)
        if sel is None:
            continue
        meta = sel.meta
        min_age = meta.universe_min_age
        counts = sel.counts()
        cond: dict[tuple[str, str], list[float]] = {}
        diagnostics: dict = {}
        if option.method == "conditional_age_sex":
            for band in AGE_GROUPS:
                for sex in SEXES:
                    if _universe_fraction(band, min_age) > 0:
                        cond[(band, sex)] = [counts.get((band, sex, c), 0.0) for c in vocab.codes]
            evidence = Evidence.CONDITIONAL_SOURCE
            conditioning, unobserved = ["age_group", "sex"], []
        elif option.method == "ipf_sex":
            bands = [b for b in AGE_GROUPS if _universe_fraction(b, min_age) > 0]
            diagnostics["ipf"] = {}
            # With structural zeros the fit runs over single years of age (band population spread uniformly over its
            # ages, the same assumption as the exact-age draw), so that a zero at an exact age inside a band (e.g. higher
            # education below 18 in the 15–19 band) is part of the fit instead of removing fitted mass at draw time.
            if spec.structural_zeros:
                units = [(b, a) for b in bands for a in _band_ages(b) if a >= min_age]
            else:
                units = [(b, None) for b in bands]
            for sex in SEXES:
                rows = [root_counts.get((b, sex), 0.0) * (_universe_fraction(b, min_age) if a is None else 1 / len(_band_ages(b)))
                        for b, a in units]
                cols = [counts.get((sex, c), 0.0) for c in vocab.codes]
                if sum(rows) <= 0 or sum(cols) <= 0:
                    continue
                seed = [[(0.0 if spec.structural_zeros and structural_zero(spec.attribute, c, a) else 1.0)
                         for c in vocab.codes] for b, a in units]
                fit = ipf_2d(rows, cols, seed)
                diagnostics["ipf"][sex] = {"converged": fit.converged, "iterations": fit.iterations,
                                           "max_abs_residual": fit.max_abs_residual, "column_scale": fit.column_scale,
                                           "rows": "single_year_age" if spec.structural_zeros else "age_group"}
                for (b, a), row in zip(units, fit.table):
                    cond[(b, sex) if a is None else (b, sex, a)] = row
            evidence = Evidence.MARGINAL_INFERENCE
            conditioning, unobserved = ["sex"], ["age_group"]
        else:
            weights = [counts.get((c,), 0.0) for c in vocab.codes]
            for band in AGE_GROUPS:
                for sex in SEXES:
                    if _universe_fraction(band, min_age) > 0:
                        cond[(band, sex)] = list(weights)
            evidence = Evidence.MARGINAL_INFERENCE
            conditioning, unobserved = [], ["age_group", "sex"]
        limitations = list(meta.limitations)
        if unobserved:
            readable = {"age_group": "age", "sex": "sex"}
            limitations.append(f"The joint distribution of {spec.attribute.replace('_', ' ')} with "
                               f"{' and '.join(readable[u] for u in unobserved)} is not observed; "
                               f"it is {'fitted under structural zeros' if spec.structural_zeros and option.method == 'ipf_sex' else 'assumed independent'} "
                               f"within {'sex' if conditioning else 'the province'}.")
        if sel.geo_level != "province":
            limitations.append(f"Source is published for {sel.geo_level} {sel.geo_code}; the regional distribution is applied "
                               "unchanged to every province in it.")
        if sel.year != year:
            limitations.append(f"Source year {sel.year} differs from the reference year {year}; no interpolation was applied.")
        return {
            "selection": sel, "option": option, "conditionals": cond, "min_age": min_age, "codes": vocab.codes,
            "provenance": {"evidence": evidence, "table_id": option.table_id, "method": option.method,
                           "method_text": METHOD_TEXT[option.method], "geo_level": sel.geo_level, "geo_code": sel.geo_code,
                           "source_year": sel.year, "source_ids": sel.source_ids, "conditioning": conditioning,
                           "unobserved_joint_with": unobserved, "universe_min_age": min_age, "universe_note": meta.universe_note,
                           "outside_universe": f"'{NOT_APPLICABLE}' below age {min_age} ({Evidence.RULE_CONSTRAINED})" if min_age else None,
                           "structural_zeros": spec.structural_zeros and option.method == "ipf_sex",
                           "limitations": limitations, "diagnostics": diagnostics},
        }
    later = sorted({y for o in spec.options for y in store.later_years_only(o.table_id, p, year)})
    reason = (f"Only years after the reference year exist ({later}); none is used." if later
              else f"No {spec.attribute} control table is loaded for this province; related official data, if any, is "
                   "province context only (see Data Sources for the reason).")
    return {"selection": None, "provenance": {"evidence": Evidence.UNAVAILABLE, "reason": reason, "universe_min_age": None}}


def _allocate_provinces(store: ControlStore, config: GenerationConfig) -> tuple[dict, dict, list[dict]]:
    requested = config.provinces or tuple(p.code for p in geo.PROVINCES)
    roots, excluded = {}, []
    for code in requested:
        p = geo.province(code)
        sel = _root(store, p, config.reference_year)
        if sel is None:
            later = store.later_years_only("population_age_sex", p, config.reference_year)
            excluded.append({"province_code": p.code, "province_name": p.name,
                             "reason": "no root table (age × sex) for a year ≤ reference year" + (f"; only {later}" if later else "")})
            continue
        roots[p.code] = sel
    if not roots:
        raise GenerationError("No requested province has a population × age × sex control table; nothing can be generated.")
    populations = {code: math.fsum(sel.counts().values()) for code, sel in roots.items()}
    # Every covered province gets at least one record when the size allows it, so no province with source data
    # silently drops out of the represented population; the weights correct for the oversampling.
    minimum = max(config.min_records_per_province, 1 if config.synthetic_size >= len(roots) else 0)
    if minimum * len(roots) > config.synthetic_size:
        raise GenerationError("The per-province floor exceeds the requested size.")
    counts = largest_remainder(populations, config.synthetic_size, {c: minimum for c in roots} if minimum else None)
    return roots, counts, excluded


def _cell_allocation(root_counts: dict, n: int) -> tuple[dict, list[dict], dict]:
    cells = {k: v for k, v in root_counts.items() if v > 0}
    alloc = largest_remainder(cells, n)
    targets = {k: cells[k] for k in cells if alloc[k] > 0}
    collapsed = []
    for key in sorted(cells, key=lambda k: (k[1], AGE_GROUPS.index(k[0]))):
        if alloc[key] > 0:
            continue
        band, sex = key
        i = AGE_GROUPS.index(band)
        candidates = sorted((abs(AGE_GROUPS.index(b) - i), AGE_GROUPS.index(b), (b, s)) for (b, s) in targets if s == sex)
        if not candidates:  # no record of this sex at all (tiny sizes): keep the population in the nearest cell of either sex
            candidates = sorted((abs(AGE_GROUPS.index(b) - i), AGE_GROUPS.index(b), s, (b, s)) for (b, s) in targets)
            candidates = [(c[0], c[1], c[3]) for c in candidates]
        if not candidates:
            collapsed.append({"cell": list(key), "population": cells[key], "into": None})
            continue
        into = candidates[0][2]
        targets[into] += cells[key]
        collapsed.append({"cell": list(key), "population": cells[key], "into": list(into)})
    return alloc, collapsed, targets


def generate(store: ControlStore, config: GenerationConfig, *, registry: DependencyRegistry | None = None) -> GeneratedPopulation:
    if not 1 <= config.synthetic_size <= MAX_SIZE:
        raise GenerationError(f"synthetic_size must be within 1..{MAX_SIZE}")
    try:
        registry = registry if registry is not None else load_registry()
        attributes = compatibility_attributes(registry)
        registry.validate_controls(store)
        strategy = registry.marital_strategy
        strategy = strategy if strategy and strategy.enabled else None
        if strategy and (config.provinces != ('06',) or config.reference_year != 2025 or not config.calibrate):
            raise RegistryError('national_age_marital_seed_v1 requires provinces=(06,), reference_year=2025 and calibration enabled')
    except RegistryError as exc:
        raise GenerationError(str(exc)) from exc
    started = time.perf_counter()
    roots, province_counts, excluded = _allocate_provinces(store, config)
    columns: dict[str, list] = {c: [] for c in COLUMNS}
    profiles: dict[str, dict] = {}
    allocation_report, calibration_report = [], []
    for code in sorted(roots):
        p = geo.province(code)
        n = province_counts[code]
        if n == 0:
            allocation_report.append({"province_code": code, "province_name": p.name, "records": 0,
                                      "population": math.fsum(roots[code].counts().values()),
                                      "note": "No record at this size (fewer records than covered provinces); its population is "
                                              "not represented."})
            continue
        root = roots[code]
        root_counts = root.counts()
        alloc, collapsed, root_targets = _cell_allocation(root_counts, n)
        if strategy and collapsed:
            raise GenerationError('Opt-in marital model requires every age/sex root cell to have records; increase population size')
        try:
            attr = {spec.attribute: (transferred_conditionals(store, p, root, config.reference_year, strategy)
                                    if strategy and spec.attribute == 'marital_status' else
                                    _conditionals(spec, store, p, config.reference_year, root_counts)) for spec in attributes}
        except RegistryError as exc:
            raise GenerationError(str(exc)) from exc
        profile_id = f"prov-{code}"
        profiles[profile_id] = _profile(profile_id, p, root, attr, config)
        age_stream = Stream(f"pop:{code}:age", config.seed)
        attr_streams = {a: Stream(f"pop:{code}:{a}", config.seed) for a in attr}
        attr_cum: dict[str, dict] = {}
        start = len(columns["synthetic_id"])
        seq = 0
        for band in AGE_GROUPS:
            for sex in SEXES:
                k = alloc.get((band, sex), 0)
                low, high = band_bounds(band)
                for _ in range(k):
                    seq += 1
                    age = TOP_CODE_AGE if high is None else low + age_stream.below(high - low + 1)
                    columns["synthetic_id"].append(f"ST{config.reference_year}-{code}-{seq:07d}")
                    columns["province_code"].append(code)
                    columns["province_name"].append(p.name)
                    columns["nuts1_code"].append(p.nuts1)
                    columns["nuts2_code"].append(p.nuts2)
                    columns["nuts3_code"].append(p.nuts3)
                    columns["age"].append(age)
                    columns["age_group"].append(band)
                    columns["age_top_coded"].append(high is None)
                    columns["sex"].append(sex)
                    columns["reference_year"].append(config.reference_year)
                    columns["provenance_profile"].append(profile_id)
                    for name, info in attr.items():
                        columns[name].append(_draw(name, info, band, sex, age, attr_streams[name], attr_cum))
                    columns["design_weight"].append(0.0)
                    columns["population_weight"].append(0.0)
        end = len(columns["synthetic_id"])
        cal = _weights(columns, start, end, root_targets, attr, config, code)
        calibration_report.append(cal)
        allocation_report.append({"province_code": code, "province_name": p.name, "records": n,
                                  "population": math.fsum(root_counts.values()), "root_year": root.year,
                                  "cells": len([k for k in alloc if alloc[k] > 0]), "collapsed_cells": collapsed})
    timings = {"generation_seconds": round(time.perf_counter() - started, 3)}
    manifest = _manifest(store, config, columns, profiles, allocation_report, calibration_report, excluded)
    if strategy:
        identity = {'strategy': strategy.model_dump(mode='json'), 'registry_version': registry.registry_version,
                    'registry_sha256': registry.fingerprint}
        manifest['statistical_strategy'] = identity
        manifest['config'] = dict(manifest['config'], marital_strategy=identity)
        manifest['source_versions']['marital_seed'] = {'sha256': strategy.source_sha256,
                                                       'file': strategy.source_file, 'geography': 'TR', 'year': 2025}
        manifest['generator_version'] = manifest['population_version'] = f'{GENERATOR_VERSION}+{strategy.model_version}'
        manifest['content_sha256'] = canonical_hash({'record_content_sha256': manifest['content_sha256'],
                                                    'statistical_strategy': identity})
        manifest['population_id'] = (f'pop-06-2025-n{config.synthetic_size}-s{config.seed}-'
                                     f'{strategy.model_version}-{manifest["content_sha256"][:16]}')
        graph = manifest['dependency_model']
        for node in graph['nodes']:
            if node['id'] == 'marital_status':
                node['options'] = [{'table_id': 'marital_status_sex', 'method': strategy.model_version}]
                node['evidence'] = 'MARGINAL_INFERENCE'
        for edge in graph['edges']:
            if edge['to'] == 'marital_status':
                edge['basis'] = ('Transferred national 15-24/25+ association; no observed Ankara age joint'
                                 if edge['from'] == 'age_group' else 'Observed Ankara 2025 calibration margin')
        graph['methods'] = dict(graph['methods'], **{strategy.model_version:
            'Rounding-sensitivity national broad-age seed, fitted by IPF to observed Ankara margins.'})
    return GeneratedPopulation(columns, manifest, profiles, timings)


def _draw(name: str, info: dict, band: str, sex: str, age: int, stream: Stream, cache: dict):
    if info["selection"] is None:
        return None
    if age < info["min_age"]:
        return NOT_APPLICABLE
    structural = info["provenance"]["structural_zeros"]
    weights = info["conditionals"].get((band, sex, age) if structural else (band, sex))
    if not weights:
        return None
    codes = info["codes"]
    key = (name, band, sex, age if structural else None)
    cum = cache.get(key)
    if cum is None:
        w = [0.0 if structural and structural_zero(name, c, age) else weights[i] for i, c in enumerate(codes)]
        cum = cumulative(w) if math.fsum(w) > 0 else None
        cache[key] = cum
    if cum is None:
        return None
    return codes[stream.weighted_index(cum)]


def _weights(columns: dict, start: int, end: int, root_targets: dict, attr: dict, config: GenerationConfig, code: str) -> dict:
    idx = range(start, end)
    cells = sorted(root_targets, key=lambda k: (AGE_GROUPS.index(k[0]), k[1]))
    cell_index = {k: i for i, k in enumerate(cells)}
    root_membership = [cell_index[(columns["age_group"][i], columns["sex"][i])] for i in idx]
    counts = [0] * len(cells)
    for c in root_membership:
        counts[c] += 1
    design = [root_targets[cells[c]] / counts[c] for c in root_membership]
    for j, i in enumerate(idx):
        columns["design_weight"][i] = design[j]
    weights = list(design)
    margins = [Margin("population_age_sex", cells, [root_targets[k] for k in cells], root_membership)]
    used, info_of = [], {}
    for name, info in attr.items():
        sel = info.get("selection")
        if sel is None or sel.geo_level != "province":
            continue
        margin = _attribute_margin(name, info, columns, idx, root_targets)
        if margin is not None:
            margins.append(margin)
            used.append(info["option"].table_id)
            info_of[margin.name] = info
    report = {"province_code": code, "calibrated": False, "margins": ["population_age_sex", *used], "margins_not_calibrated": [],
              "weight_ratio_bounds": list(WEIGHT_RATIO_BOUNDS)}
    if config.calibrate and len(margins) > 1:
        # Margins are added in the dependency model's priority order and kept only if raking with them converges.
        # With few records in a province the margins can be jointly unattainable; raking would then oscillate and drive
        # weights towards zero. A dropped margin is reported (validation shows it as not calibrated), never forced.
        kept, best, best_rr = [margins[0]], list(weights), None
        lo_bound, hi_bound = WEIGHT_RATIO_BOUNDS
        hopeless = [d * lo_bound / 1000 for d in design]  # 1000× below the accepted range: raking for this margin is abandoned
        for margin in margins[1:]:
            trial = list(best)
            rr = rake(trial, kept + [margin], max_iter=RAKE_MAX_ITER, abandon_below=hopeless)
            provenance = info_of[margin.name]["provenance"]
            finite = all(w > 0 and math.isfinite(w) for w in trial)
            ratios = [w / d for w, d in zip(trial, design)] if finite else []
            if rr.converged and finite and lo_bound <= min(ratios) and max(ratios) <= hi_bound:
                kept.append(margin)
                best, best_rr = trial, rr
                provenance["calibration"] = {"imposed": True}
                continue
            if info_of[margin.name].get('strict_targets'):
                raise GenerationError(f'{margin.name}: opt-in calibration failed or weight bounds exceeded; target cannot be dropped')
            n = end - start
            if not (rr.converged and finite):
                why = f"raking with this margin did not converge with {n} records in the province"
            else:
                why = (f"matching it with {n} records would need weights from ×{min(ratios):.3g} to ×{max(ratios):.3g} of the "
                       f"design weights (accepted range ×{lo_bound:g}–×{hi_bound:g})")
            reason = (f"Not imposed on the weights: {why}. More records per province (e.g. --min-per-province) help.")
            report["margins_not_calibrated"].append({"margin": margin.name, "max_relative_error": rr.max_relative_error,
                                                     "records": n, "converged": rr.converged, "reason": reason})
            provenance["calibration"] = {"imposed": False, "reason": reason}
            provenance["limitations"].append(
                f"Population weights in this province are not calibrated to {margin.name} ({why}); weighted counts of this "
                "attribute follow the drawn records only.")
        weights = best
        report["margins"] = [m.name for m in kept]
        if best_rr is None:
            report.update(calibrated=False, converged=True, iterations=0, max_relative_error=0.0, unreachable_cells=[],
                          note="No attribute margin could be matched; design weights reproduce the root table exactly.")
        else:
            report.update(calibrated=True, converged=best_rr.converged, iterations=best_rr.iterations,
                          max_relative_error=best_rr.max_relative_error, unreachable_cells=best_rr.unreachable_cells)
    else:
        report.update(converged=True, iterations=0, max_relative_error=0.0, unreachable_cells=[],
                      note="Only the root table applies; design weights reproduce it exactly." if len(margins) == 1 else "Calibration disabled.")
    ratios = [w / d for w, d in zip(weights, design)]
    report["weight_ratio_min"] = min(ratios)
    report["weight_ratio_max"] = max(ratios)
    for j, i in enumerate(idx):
        columns["population_weight"][i] = weights[j]
    return report


def _attribute_margin(name: str, info: dict, columns: dict, idx: range, root_targets: dict) -> Margin | None:
    dims = TABLE_KINDS[info["option"].table_id].dims
    counts = info["selection"].counts()
    min_age = info["min_age"]
    keys = sorted(counts)
    position = {k: i for i, k in enumerate(keys)}
    membership = []
    for i in idx:
        value = columns[name][i]
        if value in (None, NOT_APPLICABLE) or columns["age"][i] < min_age:
            membership.append(None)
            continue
        parts = {"age_group": columns["age_group"][i], "sex": columns["sex"][i], "category": value}
        membership.append(position.get(tuple(parts[d] for d in dims)))
    # Scale the table to the root's universe population (per sex where the table has a sex dimension), so that
    # margins from different tables are consistent; the scale is reported in the provenance diagnostics.
    universe = {}
    for (band, sex), pop in root_targets.items():
        f = _universe_fraction(band, min_age)
        group = (sex,) if "sex" in dims else ()
        universe[group] = universe.get(group, 0.0) + pop * f
    totals = {}
    for k, v in counts.items():
        group = (k[dims.index("sex")],) if "sex" in dims else ()
        totals[group] = totals.get(group, 0.0) + v
    targets = []
    for k in keys:
        group = (k[dims.index("sex")],) if "sex" in dims else ()
        targets.append(counts[k] * universe.get(group, 0.0) / totals[group] if totals[group] > 0 else 0.0)
    # Redistribute target mass of cells that received no record over the reachable cells of the same group.
    present = [False] * len(keys)
    for c in membership:
        if c is not None:
            present[c] = True
    if info.get('strict_targets') and any(t > 0 and not ok for t, ok in zip(targets, present)):
        raise GenerationError(f'{name}: positive Ankara target has no records; opt-in model forbids target redistribution')
    groups: dict[tuple, list[int]] = {}
    for i, k in enumerate(keys):
        group = tuple(k[j] for j, d in enumerate(dims) if d != "category")
        groups.setdefault(group, []).append(i)
    redistributed = []
    for group, members in groups.items():
        lost = math.fsum(targets[i] for i in members if not present[i])
        kept = math.fsum(targets[i] for i in members if present[i])
        if lost > 0 and kept > 0:
            for i in members:
                targets[i] = targets[i] * (1 + lost / kept) if present[i] else 0.0
            redistributed.append({"group": list(group), "population": lost})
    info["provenance"]["diagnostics"]["calibration_redistributed"] = redistributed
    return Margin(info["option"].table_id, keys, targets, membership)


def _profile(profile_id: str, p: geo.Province, root: Selection, attr: dict, config: GenerationConfig) -> dict:
    root_prov = {"evidence": Evidence.DIRECT_SOURCE, "table_id": "population_age_sex", "geo_level": root.geo_level,
                 "geo_code": root.geo_code, "source_year": root.year, "source_ids": root.source_ids,
                 "method": "Controlled rounding of the record count over the province's age × sex cells."}
    fields = {
        "province_code": dict(root_prov),
        "age_group": dict(root_prov),
        "sex": dict(root_prov, note=VOCABULARIES["sex"].note),
        "age": {"evidence": Evidence.ASSUMED, "method": "Uniform within the five-year band; the open 90+ band is top-coded at 90.",
                "limitations": ["Single-year age is not observed; only the five-year band is."]},
        "nuts1_code": {"evidence": Evidence.DERIVED, "method": "From the province reference table."},
        "nuts2_code": {"evidence": Evidence.DERIVED, "method": "From the province reference table."},
        "nuts3_code": {"evidence": Evidence.DERIVED, "method": "From the province reference table."},
        "population_weight": {"evidence": Evidence.DERIVED,
                              "method": "Design weight (cell population ÷ cell records) raked to every province-level control used."},
    }
    for name, info in attr.items():
        fields[name] = info["provenance"]
    return {"profile_id": profile_id, "province_code": p.code, "province_name": p.name, "reference_year": config.reference_year,
            "fields": fields,
            "source_years": {k: v.get("source_year") for k, v in fields.items() if v.get("source_year") is not None}}


def _manifest(store: ControlStore, config: GenerationConfig, columns: dict, profiles: dict, allocation: list, calibration: list,
              excluded: list) -> dict:
    n = len(columns["synthetic_id"])
    weights = columns["population_weight"]
    mean = math.fsum(weights) / n
    cv = math.sqrt(math.fsum((w - mean) ** 2 for w in weights) / n) / mean
    content_hash = canonical_hash({c: columns[c] for c in COLUMNS if c not in ("population_weight", "design_weight")}
                                  | {"weights": [round(w, 6) for w in weights]})
    scope_code = config.provinces[0] if config.provinces and len(config.provinces) == 1 else "TR"
    population_id = f"pop-{scope_code}-{config.reference_year}-n{config.synthetic_size}-s{config.seed}-{content_hash[:8]}"
    covered = sorted({c for c in columns["province_code"]})
    used_sources = sorted({sid for prof in profiles.values() for f in prof["fields"].values() for sid in f.get("source_ids", [])})
    return {
        "population_id": population_id,
        "population_version": GENERATOR_VERSION,
        "generator_version": GENERATOR_VERSION,
        "rng_stream": STREAM_VERSION,
        "generated_at": utc_now(),
        "reference_year": config.reference_year,
        "seed": config.seed,
        "synthetic_size": n,
        "config": config.normalized(),
        "scope": {"label": (f"Türkiye — {len(covered)} of {len(geo.PROVINCES)} provinces with source data" if scope_code == "TR"
                            else geo.province(scope_code).name), "scope_code": scope_code,
                  "requested_provinces": sorted(config.provinces) if config.provinces else "all",
                  "provinces_with_records": covered, "province_count": len(covered), "province_reference_count": len(geo.PROVINCES),
                  "excluded": excluded},
        "represented_population": math.fsum(weights),
        "unrepresented_provinces": [a for a in allocation if a["records"] == 0],
        "allocation": {"method": "largest_remainder", "min_records_per_province": config.min_records_per_province,
                       "rule": "Proportional to province population; at least one record per covered province when the size allows.",
                       "provinces": allocation},
        "calibration": calibration,
        "weights": {"sum": math.fsum(weights), "mean": mean, "min": min(weights), "max": max(weights), "cv": cv,
                    "kish_design_effect": 1 + cv ** 2,
                    "definition": "population_weight = persons represented by the record. Design weight = cell population ÷ "
                                  "records in the cell (stratified, proportional allocation), then raked to the controls."},
        "source_versions": {"controls_fingerprint": store.fingerprint, "controls_built_at": store.built_at,
                            "sources": [s for s in store.sources if s["source_id"] in used_sources]},
        "dependency_model": dependency_graph(),
        "constraint_rules": [r.as_dict() for r in RULES],
        "profiles": profiles,
        "fields_not_modelled": NOT_MODELLED,
        "columns": list(COLUMNS),
        "content_sha256": content_hash,
        "label": "Synthetic population calibrated to official aggregate statistics. Fictional residents; no real person is represented.",
    }
