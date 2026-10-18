"""Source-fit validation of a generated population (evidence type A in docs/validation-strategy.md).

This compares the synthetic population with the official tables it was generated from. It is an
implementation check of the generator and the weights. It says nothing about whether AI responses
resemble human behaviour (behavioural validation is a separate question, never inferred from this).

Two different comparisons are reported for every table, because they answer different questions:

* **Weighted counts** (the default for population estimates). Tables used as raking margins should
  match by construction; their tolerance is numerical (``calibration_relative``). A miss means unreachable
  cells (no record at this size) or non-convergence, and is reported as such.
* **Record shares** (unweighted). These show how faithfully the records themselves (which become
  personas) follow the source. The tolerance is the sampling noise of a sample of that size: a cell
  fails when its share deviates by more than ``z`` binomial standard errors, with ``z`` chosen so that
  the probability of any false failure across the table's cells is ``familywise_alpha`` (Bonferroni).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import NormalDist

from societytwin.national import geography as geo
from societytwin.national.constraints import check_records
from societytwin.national.controls import TABLE_KINDS, ControlStore
from societytwin.national.vocab import NOT_APPLICABLE, VOCABULARIES, ValueStatus

METHOD_VERSION = "national-source-fit-1.0"


@dataclass(frozen=True)
class ValidationTolerances:
    calibration_relative: float = 1e-6
    familywise_alpha: float = 0.01
    min_group_records_for_noise_test: int = 30

    def justification(self) -> dict:
        return {
            "calibration_relative": "Raked margins are matched numerically (the raking stops at 1e-10); 1e-6 allows for "
                                    "floating-point summation. A larger gap means unreachable cells or non-convergence.",
            "familywise_alpha": "Record-share deviations are judged against binomial sampling noise. The per-cell z threshold "
                                "is Bonferroni-adjusted over the table's cells so that a correct generator fails a table with "
                                "probability at most this value.",
            "min_group_records_for_noise_test": "Below this many records in a group the normal approximation is unreliable; "
                                                "the noise test is reported as not assessed rather than passed.",
        }


def _z_threshold(cells: int, alpha: float) -> float:
    return NormalDist().inv_cdf(1 - alpha / (2 * max(cells, 1)))


def _jsd(p: list[float], q: list[float]) -> float:
    def kl(a, b):
        return math.fsum(x * math.log2(x / y) for x, y in zip(a, b) if x > 0)
    m = [(x + y) / 2 for x, y in zip(p, q)]
    return max(0.0, 0.5 * kl(p, m) + 0.5 * kl(q, m))


def _compare(table_id: str, source: dict, synth_w: dict, synth_n: dict, group_dims: list[int], calibrated: bool,
             tol: ValidationTolerances, scale: float = 1.0) -> dict:
    """Compare per cell. Shares are within the parent group (e.g. marital status within sex)."""
    keys = sorted(set(source) | set(synth_w))
    def group(k):
        return tuple(k[i] for i in group_dims)
    src_tot, w_tot, n_tot = {}, {}, {}
    for k in keys:
        g = group(k)
        src_tot[g] = src_tot.get(g, 0.0) + source.get(k, 0.0)
        w_tot[g] = w_tot.get(g, 0.0) + synth_w.get(k, 0.0)
        n_tot[g] = n_tot.get(g, 0) + synth_n.get(k, 0)
    z = _z_threshold(len(keys), tol.familywise_alpha)
    cells, worst_rel, worst_pp_w, worst_pp_n, worst_z = [], 0.0, 0.0, 0.0, 0.0
    tvd_w, tvd_n, sq = 0.0, 0.0, 0.0
    noise_assessed = True
    for k in keys:
        g = group(k)
        s = source.get(k, 0.0) * scale
        w = synth_w.get(k, 0.0)
        n = synth_n.get(k, 0)
        p = source.get(k, 0.0) / src_tot[g] if src_tot[g] else None
        qw = w / w_tot[g] if w_tot[g] else None
        qn = n / n_tot[g] if n_tot[g] else None
        rel = (w - s) / s if s else (None if w == 0 else math.inf)
        pp_w = 100 * (qw - p) if p is not None and qw is not None else None
        pp_n = 100 * (qn - p) if p is not None and qn is not None else None
        cell_z = None
        if p is not None and qn is not None and n_tot[g] >= tol.min_group_records_for_noise_test and 0 < p < 1:
            cell_z = (qn - p) / math.sqrt(p * (1 - p) / n_tot[g])
            worst_z = max(worst_z, abs(cell_z))
        elif n_tot[g] < tol.min_group_records_for_noise_test:
            noise_assessed = False
        if rel is not None and math.isfinite(rel):
            worst_rel = max(worst_rel, abs(rel))
        elif rel is not None:
            worst_rel = math.inf
        if pp_w is not None:
            worst_pp_w = max(worst_pp_w, abs(pp_w))
            tvd_w += abs(pp_w) / 100
        if pp_n is not None:
            worst_pp_n = max(worst_pp_n, abs(pp_n))
            tvd_n += abs(pp_n) / 100
        sq += (w - s) ** 2
        cells.append({"cell": list(k), "source_count": s, "synthetic_weighted_count": w, "synthetic_records": n,
                      "source_share": p, "synthetic_share": qw, "record_share": qn,
                      "absolute_error": w - s, "relative_error": rel, "pp_error": pp_w, "record_pp_error": pp_n,
                      "record_z": cell_z})
    groups = max(len(src_tot), 1)
    mean_cell = math.fsum(source.get(k, 0.0) * scale for k in keys) / max(len(keys), 1)
    srmse = math.sqrt(sq / max(len(keys), 1)) / mean_cell if mean_cell else None
    p_all = [source.get(k, 0.0) for k in keys]
    q_all = [synth_w.get(k, 0.0) for k in keys]
    ps, qs = math.fsum(p_all), math.fsum(q_all)
    jsd = _jsd([x / ps for x in p_all], [x / qs for x in q_all]) if ps and qs else None
    if calibrated:
        weighted_status = "fit_by_construction" if worst_rel <= tol.calibration_relative else "calibration_gap"
    else:
        weighted_status = "not_calibrated"
    if not noise_assessed and worst_z == 0.0:
        record_status = "not_assessed_small_sample"
    else:
        record_status = "within_sampling_noise" if worst_z <= z else "outside_sampling_noise"
    return {
        "table_id": table_id, "cells": cells, "cell_count": len(keys), "groups": groups,
        "summary": {"max_relative_error": worst_rel if math.isfinite(worst_rel) else None,
                    "max_abs_pp_error_weighted": worst_pp_w, "max_abs_pp_error_records": worst_pp_n,
                    "tvd_weighted": tvd_w / groups, "tvd_records": tvd_n / groups, "jsd_weighted": jsd, "srmse_weighted": srmse,
                    "max_abs_record_z": worst_z, "record_z_threshold": z},
        "calibrated": calibrated, "weighted_status": weighted_status, "record_status": record_status,
    }


def validate(columns: dict, manifest: dict, store: ControlStore, tol: ValidationTolerances | None = None) -> dict:
    tol = tol or ValidationTolerances()
    profiles = manifest["profiles"]
    # Design weights alone reproduce the root table; raking adds every other margin it was given.
    calibrated_tables = {c["province_code"]: set(c["margins"]) if c.get("calibrated") else {"population_age_sex"}
                         for c in manifest["calibration"]}
    by_province: dict[str, list[int]] = {}
    for i, code in enumerate(columns["province_code"]):
        by_province.setdefault(code, []).append(i)
    scopes, national_acc = [], {}
    for code, idx in sorted(by_province.items()):
        p = geo.province(code)
        prof = profiles[f"prov-{code}"]
        tables = []
        root_sel = store.best("population_age_sex", p, manifest["reference_year"])
        tables.append(_table_fit("population_age_sex", root_sel, columns, idx, None,
                                 "population_age_sex" in calibrated_tables.get(code, set()), tol,
                                 national_acc, prof))
        for field_name, field in prof["fields"].items():
            tid = field.get("table_id")
            if not tid or tid == "population_age_sex" or field.get("evidence") == "UNAVAILABLE":
                continue
            sel = store.best(tid, p, manifest["reference_year"])
            if sel is None:
                continue
            if sel.geo_level != "province":
                tables.append({"table_id": tid, "attribute": field_name, "status": "not_validated_regional_source",
                               "detail": f"Source is published for {sel.geo_level} {sel.geo_code}; no province-level control exists."})
                continue
            tables.append(_table_fit(tid, sel, columns, idx, field_name, tid in calibrated_tables.get(code, set()), tol,
                                     national_acc, prof))
        unavailable = [{"field": f, "reason": v.get("reason")} for f, v in prof["fields"].items() if v.get("evidence") == "UNAVAILABLE"]
        consistency = _cross_source(store, p, manifest["reference_year"], root_sel)
        scopes.append({"scope": "province", "province_code": code, "province_name": p.name, "records": len(idx),
                       "tables": tables, "fields_without_source": unavailable, "cross_source_checks": consistency})
    national = []
    for tid, acc in sorted(national_acc.items()):
        fit = _compare(tid, acc["source"], acc["w"], acc["n"], acc["group_dims"], acc["calibrated"], tol)
        fit.update(attribute=acc["attribute"], provinces=sorted(acc["provinces"]),
                   note=f"Sum over the {len(acc['provinces'])} province(s) that have this table at province level.")
        national.append(fit)
    constraint_results = check_records(columns, profiles)
    return {
        "method_version": METHOD_VERSION,
        "population_id": manifest["population_id"],
        "evidence_type": "source_fit",
        "statement": "Source-fit validation: does the synthetic population reproduce the official tables it was built from? "
                     "Passing it does not show that AI personas behave like real people; behavioural validation is separate.",
        "tolerances": asdict(tol), "tolerance_justification": tol.justification(),
        "national": {"scope": "covered_provinces", "province_count": len(by_province),
                     "province_reference_count": len(geo.PROVINCES), "tables": national},
        "provinces": scopes,
        "constraints": constraint_results,
        "constraint_violations": sum(c["violations"] for c in constraint_results),
        "weights": manifest["weights"],
        "calibration": manifest["calibration"],
        "not_validated": ["Held-out tables (none is selected or loaded).",
                          "Behavioural realism of AI responses (outside source-fit validation)."],
    }


def _table_fit(tid, sel, columns, idx, attribute, calibrated, tol, national_acc, profile) -> dict:
    kind = TABLE_KINDS[sel.meta.kind]
    dims = kind.dims
    min_age = sel.meta.universe_min_age
    source = sel.counts()
    synth_w, synth_n = {}, {}
    excluded_unavailable = 0
    for i in idx:
        if columns["age"][i] < min_age:
            continue
        value = columns[attribute][i] if attribute else None
        if attribute and value in (None, NOT_APPLICABLE):
            excluded_unavailable += 1
            continue
        parts = {"age_group": columns["age_group"][i], "sex": columns["sex"][i], "category": value}
        key = tuple(parts[d] for d in dims)
        synth_w[key] = synth_w.get(key, 0.0) + columns["population_weight"][i]
        synth_n[key] = synth_n.get(key, 0) + 1
    group_dims = [j for j, d in enumerate(dims) if d != "category"] if attribute else []
    # The source universe may start inside a band (e.g. 6+): weighted synthetic counts are compared with the table
    # scaled to the root's universe population, as in calibration; the scale is reported.
    scale = 1.0
    if attribute:
        root_universe = math.fsum(columns["population_weight"][i] for i in idx if columns["age"][i] >= min_age)
        total = math.fsum(source.values())
        scale = root_universe / total if total else 1.0
    fit = _compare(tid, source, synth_w, synth_n, group_dims, calibrated, tol, scale)
    fit.update(attribute=attribute, source={"geo_level": sel.geo_level, "geo_code": sel.geo_code, "year": sel.year,
                                            "source_ids": sel.meta.source_ids, "universe_min_age": min_age,
                                            "universe_note": sel.meta.universe_note},
               source_to_population_scale=scale, records_without_value=excluded_unavailable,
               non_observed_cells=[{"cell": [r.sex, r.age_group, r.category], "value_status": r.value_status}
                                   for r in sel.rows if r.value_status != ValueStatus.OBSERVED])
    if attribute:
        fit["evidence"] = profile["fields"][attribute]["evidence"]
    acc = national_acc.setdefault(tid, {"source": {}, "w": {}, "n": {}, "group_dims": group_dims, "calibrated": True,
                                        "attribute": attribute, "provinces": set()})
    acc["calibrated"] = acc["calibrated"] and calibrated
    acc["provinces"].add(sel.geo_code)
    for k, v in source.items():
        acc["source"][k] = acc["source"].get(k, 0.0) + v * scale
    for k, v in synth_w.items():
        acc["w"][k] = acc["w"].get(k, 0.0) + v
    for k, v in synth_n.items():
        acc["n"][k] = acc["n"].get(k, 0) + v
    return fit


def _cross_source(store: ControlStore, p: geo.Province, year: int, root_sel) -> list[dict]:
    checks = []
    if root_sel is None:
        return checks
    root_total = math.fsum(root_sel.counts().values())
    by_sex = {s: math.fsum(v for k, v in root_sel.counts().items() if k[1] == s) for s in VOCABULARIES["sex"].codes}
    for row in store.context_for(p):
        if row.geo_level != "province" or row.year != root_sel.year or row.value is None:
            continue
        expected = {"total_population": root_total, "female_population": by_sex["female"], "male_population": by_sex["male"]}.get(row.indicator_id)
        if expected is None:
            continue
        checks.append({"name": f"root_vs_{row.indicator_id}", "year": row.year, "root_table": expected, "context": row.value,
                       "difference": expected - row.value, "passed": abs(expected - row.value) < 0.5,
                       "detail": f"Age × sex table total vs {row.label_en} from {row.source_ref}"})
    return checks


def summarize(report: dict) -> dict:
    """Small summary for listings and the dashboard."""
    statuses = {}
    for scope in report["provinces"]:
        for t in scope["tables"]:
            for key in ("weighted_status", "record_status", "status"):
                if key in t:
                    statuses[t[key]] = statuses.get(t[key], 0) + 1
    return {"constraint_violations": report["constraint_violations"], "status_counts": statuses,
            "provinces": len(report["provinces"])}
