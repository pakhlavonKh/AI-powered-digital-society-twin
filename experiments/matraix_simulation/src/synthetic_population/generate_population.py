"""Sample 1,000 Ankara residents from observed age-group/sex probabilities."""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from src.data_processing.process_tuik_demographics import AGE_GROUPS, validate_ankara_2025
from src.data_processing.process_tuik_marital import read_distribution as read_marital_distribution
from src.data_processing.process_tuik_marital import OUTPUT_PATH as MARITAL_PATH

INPUT_PATH = PROJECT_ROOT / "processed" / "ankara_age_gender.csv"
OUTPUT_PATH = PROJECT_ROOT / "synthetic" / "ankara_population_1000.csv"
V2_OUTPUT_PATH = PROJECT_ROOT / "synthetic" / "ankara_population_1000_v2.csv"
SEED = 42
SAMPLE_SIZE = 1000


def read_distribution(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["year", "province", "age_group", "gender", "population", "probability"]:
            raise ValueError("Unexpected processed dataset schema")
        rows = list(reader)
    for row in rows:
        row["year"] = int(row["year"])
        row["population"] = int(row["population"])
        row["probability"] = float(row["probability"])
    validated = validate_ankara_2025(rows)
    for raw, expected in zip(sorted(rows, key=lambda r: (r["age_group"], r["gender"])),
                             sorted(validated, key=lambda r: (r["age_group"], r["gender"]))):
        if not math.isfinite(raw["probability"]) or not math.isclose(raw["probability"], expected["probability"], rel_tol=0, abs_tol=1e-12):
            raise ValueError("Stored probability disagrees with population")
    if not math.isclose(math.fsum(r["probability"] for r in rows), 1, rel_tol=0, abs_tol=1e-9):
        raise ValueError("Probability sum is not one")
    return validated


def generate_population(distribution, seed=SEED):
    draws = random.Random(seed).choices(distribution, weights=[r["probability"] for r in distribution], k=SAMPLE_SIZE)
    return [dict(person_id=f"ANK2025_{i:06d}", age_group=r["age_group"], gender=r["gender"])
            for i, r in enumerate(draws, start=1)]


def compare_proportions(distribution, sample):
    allowed = {(r["age_group"], r["gender"]) for r in distribution}
    if len(sample) != SAMPLE_SIZE or len({r["person_id"] for r in sample}) != SAMPLE_SIZE:
        raise ValueError("Sample size or person IDs invalid")
    if any((r["age_group"], r["gender"]) not in allowed for r in sample):
        raise ValueError("Sample contains an unknown age/gender pair")
    comparisons = []
    for dimension, categories in [("gender", ("male", "female")), ("age_group", AGE_GROUPS)]:
        observed = Counter(r[dimension] for r in sample)
        for category in categories:
            probability = math.fsum(r["probability"] for r in distribution if r[dimension] == category)
            proportion = observed[category] / len(sample)
            comparisons.append(dict(dimension=dimension, category=category, count=observed[category],
                                    source=probability, sample=proportion,
                                    error_pp=100 * (proportion - probability)))
    joint = Counter((r["age_group"], r["gender"]) for r in sample)
    joint_tv = 0.5 * sum(abs(joint[r["age_group"], r["gender"]] / len(sample) - r["probability"])
                         for r in distribution)
    return comparisons, joint_tv


def is_under_15(age_group):
    if age_group not in AGE_GROUPS:
        raise ValueError(f"Unknown age group: {age_group}")
    return age_group in {"0-4", "5-9", "10-14"}


def enrich_marital_status(sample, distribution, seed=SEED):
    rng = random.Random(seed)
    by_gender = {g: [r for r in distribution if r["gender"] == g] for g in ("male", "female")}
    enriched = []
    for person in sample:
        if is_under_15(person["age_group"]):
            status = "not_applicable"
        else:
            rows = by_gender[person["gender"]]
            status = rng.choices(rows, weights=[r["conditional_probability"] for r in rows], k=1)[0]["marital_status"]
        enriched.append(dict(person, marital_status=status, marital_status_conditioning="gender_only"))
    return enriched


def compare_marital_proportions(distribution, sample):
    comparisons = []
    for person in sample:
        if person["marital_status_conditioning"] != "gender_only":
            raise ValueError("Missing gender-only conditioning metadata")
        if is_under_15(person["age_group"]):
            if person["marital_status"] != "not_applicable":
                raise ValueError("Child has an applicable marital status")
        elif person["marital_status"] not in {r["marital_status"] for r in distribution if r["gender"] == person["gender"]}:
            raise ValueError("Invalid adult marital status")
    for gender in ("male", "female"):
        adults = [p for p in sample if p["gender"] == gender and not is_under_15(p["age_group"])]
        if not adults:
            raise ValueError(f"No sampled adults for {gender}")
        counts = Counter(p["marital_status"] for p in adults)
        for row in distribution:
            if row["gender"] == gender:
                fraction = counts[row["marital_status"]] / len(adults)
                comparisons.append(dict(gender=gender, marital_status=row["marital_status"],
                                        adult_denominator=len(adults), count=counts[row["marital_status"]],
                                        source=row["conditional_probability"], sample=fraction,
                                        error_pp=100 * (fraction - row["conditional_probability"])))
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output", type=Path, default=V2_OUTPUT_PATH)
    parser.add_argument("--base-population", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--marital-input", type=Path, default=MARITAL_PATH)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    distribution = read_distribution(args.input)
    with args.base_population.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["person_id", "age_group", "gender"]:
            raise ValueError("Unexpected base population schema")
        sample = list(reader)
    comparisons, joint_tv = compare_proportions(distribution, sample)
    marital = read_marital_distribution(args.marital_input)
    sample = enrich_marital_status(sample, marital, args.seed)
    marital_comparisons = compare_marital_proportions(marital, sample)
    if args.output.resolve() in {args.base_population.resolve(), args.input.resolve(), args.marital_input.resolve()}:
        raise ValueError("Enriched output must not overwrite an input file")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["person_id", "age_group", "gender", "marital_status", "marital_status_conditioning"])
        writer.writeheader()
        writer.writerows(sample)
    print(f"PASS: {len(sample)} people; unique IDs; valid age/gender pairs; seed={args.seed}")
    print("dimension,category,count,source_percent,sample_percent,error_percentage_points")
    for r in comparisons:
        print(f"{r['dimension']},{r['category']},{r['count']},{100*r['source']:.6f},{100*r['sample']:.6f},{r['error_pp']:+.6f}")
    print(f"Joint age/gender total variation distance: {joint_tv:.6f}")
    print("gender,marital_status,adult_denominator,count,source_percent,sample_percent,error_percentage_points")
    for r in marital_comparisons:
        print(f"{r['gender']},{r['marital_status']},{r['adult_denominator']},{r['count']},{100*r['source']:.6f},{100*r['sample']:.6f},{r['error_pp']:+.6f}")
    print(f"Under 15: {sum(is_under_15(r['age_group']) for r in sample)}; all not_applicable")
    print("Conditioning: gender_only; true age x marital-status relationship is not preserved")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
