"""Cohorts: reproducible, filtered selections from a synthetic population.

A cohort *definition* (population + filters) is stored separately from any *sample* drawn from it
(size, method, seed, members). Three seeded designs are implemented, each recording every member's
inclusion probability and the resulting analysis weight (Horvitz–Thompson: population weight ÷
inclusion probability), so cohort results can be weighted back to the eligible population:

* ``simple_random``: equal-probability sampling without replacement over eligible records;
* ``weighted``: probability proportional to the population weight (systematic PPS on a seeded random
  order; records whose expected inclusion would exceed 1 are taken with certainty);
* ``stratified``: proportional allocation of the sample over the categories of one field by weighted
  population (largest remainder), then simple random sampling within each stratum.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from societytwin.common import canonical_hash
from societytwin.national.fitting import largest_remainder
from societytwin.national.rng import MAX_SEED, Stream
from societytwin.national.store import PopulationFilter

SAMPLING_VERSION = "cohort-sampling-1.0"
MAX_SAMPLE = 10_000
STRATIFIABLE = ("province_code", "sex", "age_group", "marital_status", "education_level", "labour_status", "urbanicity")


class CohortDefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    population_id: str = Field(min_length=1, max_length=160)
    filters: PopulationFilter = Field(default_factory=PopulationFilter)


class CohortSampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: int = Field(ge=1, le=MAX_SAMPLE)
    method: str = Field(default="weighted", pattern="^(simple_random|weighted|stratified)$")
    seed: int = Field(ge=0, le=MAX_SEED)
    strata_field: str | None = Field(default=None, pattern="^(" + "|".join(STRATIFIABLE) + ")$")


class SamplingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Member:
    synthetic_id: str
    inclusion_probability: float
    population_weight: float

    @property
    def analysis_weight(self) -> float:
        return self.population_weight / self.inclusion_probability

    def as_dict(self) -> dict:
        return {"synthetic_id": self.synthetic_id, "inclusion_probability": self.inclusion_probability,
                "population_weight": self.population_weight, "analysis_weight": self.analysis_weight}


def definition_hash(population_id: str, filters: PopulationFilter) -> str:
    return canonical_hash({"population_id": population_id, "filters": filters.normalized()})


def simple_random(ids: list[str], weights: list[float], size: int, seed: int) -> list[Member]:
    order = sorted(range(len(ids)), key=lambda i: ids[i])
    stream = Stream(f"cohort:srs:{size}", seed)
    pool = list(order)
    for i in range(size):
        j = i + stream.below(len(pool) - i)
        pool[i], pool[j] = pool[j], pool[i]
    pi = size / len(ids)
    return [Member(ids[k], pi, weights[k]) for k in pool[:size]]


def weighted_pps(ids: list[str], weights: list[float], size: int, seed: int) -> list[Member]:
    stream = Stream(f"cohort:pps:{size}", seed)
    order = stream.shuffle(sorted(range(len(ids)), key=lambda i: ids[i]))
    certain: list[int] = []
    rest = list(order)
    n = size
    while n > 0:
        total = math.fsum(weights[i] for i in rest)
        big = {i for i in rest if n * weights[i] / total >= 1}
        if not big:
            break
        certain.extend(i for i in rest if i in big)
        rest = [i for i in rest if i not in big]
        n = size - len(certain)
    members = [Member(ids[i], 1.0, weights[i]) for i in certain]
    if n > 0:
        total = math.fsum(weights[i] for i in rest)
        step = total / n
        start = stream.random() * step
        acc, j = 0.0, 0
        chosen = set()
        for i in rest:
            acc += weights[i]
            # Every remaining unit has weight below one step, so it can be hit by at most one point.
            if j < n and start + j * step < acc:
                members.append(Member(ids[i], n * weights[i] / total, weights[i]))
                chosen.add(i)
                j += 1
        for i in reversed(rest):  # floating-point guard: the last point can fall past the summed total by rounding
            if j >= n:
                break
            if i not in chosen:
                members.append(Member(ids[i], n * weights[i] / total, weights[i]))
                j += 1
    return members


def stratified(ids: list[str], weights: list[float], strata: list, size: int, seed: int) -> tuple[list[Member], list[dict]]:
    groups: dict = {}
    for i, s in enumerate(strata):
        groups.setdefault("∅" if s is None else s, []).append(i)
    shares = {k: math.fsum(weights[i] for i in v) for k, v in groups.items()}
    alloc = largest_remainder(shares, size)
    members, report = [], []
    for key in sorted(groups):
        members_idx = groups[key]
        n_h = min(alloc[key], len(members_idx))
        report.append({"stratum": key, "eligible": len(members_idx), "weighted": shares[key], "allocated": alloc[key], "drawn": n_h})
        if n_h == 0:
            continue
        sub_ids = [ids[i] for i in members_idx]
        sub_w = [weights[i] for i in members_idx]
        members.extend(simple_random(sub_ids, sub_w, n_h, seed ^ (hash_key(str(key)) & MAX_SEED)))
    return members, report


def hash_key(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def draw(ids: list[str], weights: list[float], request: CohortSampleRequest, strata: list | None = None) -> dict:
    if not ids:
        raise SamplingError("empty_frame", "No records match this cohort's filters.")
    if request.size > len(ids):
        raise SamplingError("oversample", f"Requested {request.size} but only {len(ids)} records are eligible (sampling is without replacement).")
    report = None
    if request.method == "simple_random":
        members = simple_random(ids, weights, request.size, request.seed)
    elif request.method == "weighted":
        members = weighted_pps(ids, weights, request.size, request.seed)
    else:
        if not request.strata_field or strata is None:
            raise SamplingError("strata_required", "Stratified sampling needs strata_field.")
        members, report = stratified(ids, weights, strata, request.size, request.seed)
    eligible_weight = math.fsum(weights)
    return {
        "members": [m.as_dict() for m in members],
        "eligible_records": len(ids), "eligible_weighted_population": eligible_weight,
        "selected": len(members), "strata": report,
        "sum_analysis_weights": math.fsum(m.analysis_weight for m in members),
        "algorithm_version": SAMPLING_VERSION,
        "frame_ordering": "Eligible synthetic IDs sorted ascending before any seeded shuffle or draw.",
        "weight_note": "analysis_weight = population_weight ÷ inclusion probability; weighted cohort results estimate the "
                       "eligible synthetic population, not real residents.",
    }
