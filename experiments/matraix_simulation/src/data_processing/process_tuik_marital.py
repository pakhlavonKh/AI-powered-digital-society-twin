"""Extract observed Ankara 2025 marital-status distributions for each gender, ages 15+."""

import argparse
import csv
import hashlib
import math
import re
from pathlib import Path

try:
    from .process_tuik_demographics import PROJECT_ROOT, RAW_DIR, normalize, write_csv
except ImportError:
    from process_tuik_demographics import PROJECT_ROOT, RAW_DIR, normalize, write_csv

OUTPUT_PATH = PROJECT_ROOT / "processed" / "ankara_marital_gender.csv"
STATUSES = ("Hi\u00e7 evlenmedi", "Evli", "Bo\u015fand\u0131", "E\u015fi \u00f6ld\u00fc")
TOTALS = {"male": 2371482, "female": 2484624}
FIELDS = ["year", "province", "gender", "marital_status", "population", "conditional_probability"]


def validate_distribution(rows):
    expected = {(g, s) for g in TOTALS for s in STATUSES}
    keys = [(r["gender"], r["marital_status"]) for r in rows]
    if len(rows) != 8 or set(keys) != expected or len(set(keys)) != len(keys):
        raise ValueError("Expected exactly four distinct T10 statuses for each gender")
    for row in rows:
        if row["year"] != 2025 or row["province"] != "Ankara":
            raise ValueError("Wrong year or province")
        if type(row["population"]) is not int or row["population"] < 0:
            raise ValueError("Population must be a nonnegative integer")
        probability = row["conditional_probability"]
        expected_probability = row["population"] / TOTALS[row["gender"]]
        if not math.isfinite(probability) or not math.isclose(probability, expected_probability, rel_tol=0, abs_tol=1e-12):
            raise ValueError("Conditional probability disagrees with the gender denominator")
    for gender, total in TOTALS.items():
        subset = [r for r in rows if r["gender"] == gender]
        if sum(r["population"] for r in subset) != total:
            raise ValueError(f"{gender} categories do not sum to T10 total")
        if not math.isclose(math.fsum(r["conditional_probability"] for r in subset), 1, rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"{gender} conditional probabilities do not sum to one")
    return sorted(rows, key=lambda r: (r["gender"], STATUSES.index(r["marital_status"])))


def extract_t10(path):
    headers = ["cografi kapsam", "gozlem sikligi", "istatistiksel gosterge", "ikamet edilen yer",
               "cinsiyet", "medeni durum", "adnks gosterge", "zaman", "gozlem", "gozlem durumu",
               "zaman formati", "ondalik basamak sayisi", "olcu birimi", "birim carpani"]
    observations = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if [normalize(h) for h in (reader.fieldnames or [])] != headers:
            raise ValueError("CSV does not match the inspected T10 schema")
        for line, raw in enumerate(reader, 2):
            if None in raw or any(v is None for v in raw.values()):
                raise ValueError(f"Malformed CSV row {line}")
            r = dict(zip(headers, raw.values()))
            if r["ikamet edilen yer"] != "Ankara" or r["zaman"] != "2025":
                continue
            if normalize(r["adnks gosterge"]) != "15 ve daha yukari yastaki nufus" or normalize(r["gozlem sikligi"]) != "yillik":
                raise ValueError("Unexpected T10 measure or frequency")
            if any(r[k] for k in ("gozlem durumu", "olcu birimi", "birim carpani")):
                raise ValueError("Unexpected T10 observation metadata")
            gender = {"erkek": "male", "kadin": "female", "toplam": "total"}.get(normalize(r["cinsiyet"]))
            status = r["medeni durum"]
            if gender is None or status not in (*STATUSES, "Toplam"):
                raise ValueError(f"Unrecognized Ankara 2025 category: {r}")
            if not re.fullmatch(r"\d+", r["gozlem"]):
                raise ValueError("Expected a nonnegative integer population")
            key = (gender, status)
            if key in observations:
                raise ValueError(f"Duplicate source observation: {key}")
            observations[key] = int(r["gozlem"])
    expected = {(g, s) for g in ("male", "female", "total") for s in (*STATUSES, "Toplam")}
    if set(observations) != expected:
        raise ValueError("Incomplete Ankara 2025 T10 observations")
    for gender in ("male", "female", "total"):
        if sum(observations[gender, s] for s in STATUSES) != observations[gender, "Toplam"]:
            raise ValueError("Source status totals do not reconcile")
    for status in (*STATUSES, "Toplam"):
        if observations["male", status] + observations["female", status] != observations["total", status]:
            raise ValueError("Source gender totals do not reconcile")
    rows = []
    for gender, total in TOTALS.items():
        if observations[gender, "Toplam"] != total:
            raise ValueError("Unexpected T10 gender denominator")
        for status in STATUSES:
            population = observations[gender, status]
            rows.append(dict(year=2025, province="Ankara", gender=gender, marital_status=status,
                             population=population, conditional_probability=population / total))
    return validate_distribution(rows)


def read_distribution(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS:
            raise ValueError("Unexpected marital dataset schema")
        rows = list(reader)
    for row in rows:
        row["year"] = int(row["year"])
        row["population"] = int(row["population"])
        row["conditional_probability"] = float(row["conditional_probability"])
    return validate_distribution(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    candidates = [args.source] if args.source else sorted(RAW_DIR.rglob("*DF_ADNKS_T10,1.1*.csv"))
    if len(candidates) != 1:
        parser.error("Expected one T10 CSV; specify --source")
    source = candidates[0]
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = extract_t10(source)
    if hashlib.sha256(source.read_bytes()).hexdigest() != checksum:
        raise ValueError("Raw checksum changed during extraction")
    write_csv(rows, args.output)
    print(f"PASS: 8 rows; gender denominators {TOTALS}; categories/totals reconcile; each probability sum=1")
    print(f"Raw SHA256 unchanged: {checksum}")
    print(f"Source: {source}; wrote {args.output}")


if __name__ == "__main__":
    main()
