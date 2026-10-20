"""Weighted aggregation of structured experiment responses.

Each final, valid response is weighted by its persona's cohort analysis weight (population weight ÷
inclusion probability) divided by the number of repetitions, so a run estimates the response
distribution of the cohort's eligible *synthetic* population. Uncertainty is shown as an approximate
95% Wilson interval on the Kish effective sample size: it covers persona sampling only, not model
stochasticity, prompt sensitivity or validity. Groups below a minimum size are suppressed.

Wording is descriptive: "within this synthetic experiment, group A selected X more often than group B".
Nothing here estimates a causal effect or a real-world share.
"""

from __future__ import annotations

import math

MIN_GROUP_PERSONAS = 10
GROUPABLE = ("province_code", "sex", "age_group", "marital_status", "education_level", "labour_status",
             "household_size_class", "household_type", "urbanicity")
INFERENCE_NOTE = ("Descriptive results of a synthetic, persona-conditioned AI experiment. Shares estimate the cohort's eligible "
                  "synthetic population under this model and prompt; they are not predictions of real behaviour and do not "
                  "identify causal effects. Intervals reflect persona sampling only.")


def wilson(p: float, n: float, z: float = 1.959964) -> tuple[float, float] | None:
    if n <= 0:
        return None
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _distribution(rows: list[dict], option_ids: list[str]) -> dict:
    total_w = math.fsum(r["weight"] for r in rows)
    sq = math.fsum(r["weight"] ** 2 for r in rows)
    n_eff = (total_w ** 2 / sq) if sq else 0.0
    out = []
    for oid in option_ids:
        chosen = [r for r in rows if r["choice"] == oid]
        w = math.fsum(r["weight"] for r in chosen)
        share = w / total_w if total_w else None
        out.append({"option_id": oid, "responses": len(chosen), "weighted_share": share,
                    "unweighted_share": len(chosen) / len(rows) if rows else None,
                    "ci95": wilson(share, n_eff) if share is not None else None})
    return {"responses": len(rows), "personas": len({r["synthetic_id"] for r in rows}), "effective_n": n_eff, "options": out}


def aggregate(final_rows: list[dict], members: dict[str, dict], option_ids: list[str], repetitions: int,
              group_by: list[str] | None = None, min_group: int = MIN_GROUP_PERSONAS) -> dict:
    valid = [r for r in final_rows if r["status"] == "ok"]
    status_counts: dict[str, int] = {}
    for r in final_rows:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    weighted = []
    for r in valid:
        m = members[r["synthetic_id"]]
        weighted.append({**r, "weight": m["analysis_weight"] / repetitions, "attributes": m})
    overall = _distribution(weighted, option_ids)
    groups = {}
    for field in group_by or []:
        if field not in GROUPABLE:
            raise ValueError(f"Cannot group by {field!r}")
        buckets: dict = {}
        for r in weighted:
            buckets.setdefault(r["attributes"].get(field), []).append(r)
        entries = []
        for value, rows in sorted(buckets.items(), key=lambda kv: (kv[0] is None, str(kv[0]))):
            personas = len({r["synthetic_id"] for r in rows})
            entry = {"value": value if value is not None else "unavailable", "personas": personas}
            if personas < min_group:
                entry.update(suppressed=True, reason=f"Fewer than {min_group} personas; not reported.")
            else:
                entry.update(suppressed=False, **_distribution(rows, option_ids))
            entries.append(entry)
        groups[field] = {"groups": entries, "min_group_personas": min_group,
                         "comparisons": _comparisons(entries, option_ids)}
    return {"overall": overall, "by": groups, "status_counts": status_counts, "valid_responses": len(valid),
            "final_responses": len(final_rows), "inference_note": INFERENCE_NOTE,
            "weighting": "analysis_weight = population weight ÷ inclusion probability, divided by repetitions per persona."}


def _comparisons(entries: list[dict], option_ids: list[str]) -> list[str]:
    reported = [e for e in entries if not e.get("suppressed")]
    if len(reported) < 2:
        return []
    out = []
    for oid in option_ids:
        shares = [(e["value"], next(o for o in e["options"] if o["option_id"] == oid)) for e in reported]
        hi = max(shares, key=lambda s: s[1]["weighted_share"] or 0)
        lo = min(shares, key=lambda s: s[1]["weighted_share"] or 0)
        if hi[0] == lo[0] or hi[1]["ci95"] is None or lo[1]["ci95"] is None:
            continue
        if hi[1]["ci95"][0] > lo[1]["ci95"][1]:
            out.append(f"Within this synthetic experiment, '{hi[0]}' selected {oid} more often than '{lo[0]}' "
                       f"({hi[1]['weighted_share']:.0%} vs {lo[1]['weighted_share']:.0%}; intervals do not overlap). "
                       "This is a descriptive difference, not a causal effect.")
    return out

