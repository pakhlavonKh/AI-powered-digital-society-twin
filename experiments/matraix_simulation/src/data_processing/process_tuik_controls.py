"""Extract Ankara controls with workbook, sheet, row, year and unit provenance."""

import argparse
import math
from pathlib import Path

try:
    from .process_tuik_demographics import RAW_DIR, PROJECT_ROOT, iter_workbook_sheets, normalize, title_year, to_number, write_csv
except ImportError:
    from process_tuik_demographics import RAW_DIR, PROJECT_ROOT, iter_workbook_sheets, normalize, title_year, to_number, write_csv

OUTPUT_PATH = PROJECT_ROOT / "processed" / "ankara_demographic_controls.csv"


def extract_controls(raw_dir):
    records = []
    for sheet in iter_workbook_sheets(raw_dir):
        rows = sheet.rows
        title = " ".join(normalize(v) for r in rows[:2] for v in r)
        population = "population density" in title
        median = "median age" in title
        if not (population or median):
            continue
        if len(rows) < 4:
            raise ValueError(f"Missing headers: {sheet.path}")
        starts = [1] if population else [i for i, v in enumerate(rows[2]) if isinstance(v, (int, float)) and 1900 <= v <= 2100]
        for start in starts:
            expected = ["toplam total", "erkek male", "kadin female"]
            if [normalize(v) for v in rows[3][start:start + 3]] != expected:
                raise ValueError(f"Unrecognized control headers: {sheet.path}")
        if population and (normalize(rows[2][1]) != "toplam total" or "population density" not in normalize(rows[2][-1])):
            raise ValueError(f"Unrecognized population layout: {sheet.path}")
        hits = [(i, r) for i, r in enumerate(rows) if r and normalize(r[0]) == "ankara"]
        if len(hits) != 1:
            raise ValueError(f"Expected exactly one Ankara row: {sheet.path}")
        index, row = hits[0]
        for start in starts:
            year = title_year(rows[:2]) if population else to_number(rows[2][start])
            names = ["total_population", "male_population", "female_population"] if population else ["total_median_age", "male_median_age", "female_median_age"]
            values = [(name, row[start + j], "persons" if population else "years") for j, name in enumerate(names)]
            if population:
                values.append(("population_density", row[-1], "persons/km2"))
            for statistic, value, unit in values:
                value = to_number(value) if unit == "persons" else float(value)
                if not math.isfinite(value) or value <= 0 or (unit == "years" and value > 120):
                    raise ValueError(f"Invalid {statistic}: {value}")
                records.append(dict(year=year, province="Ankara", statistic=statistic, value=value,
                                    unit=unit, source_workbook=sheet.path.relative_to(raw_dir).as_posix(),
                                    source_sheet=sheet.sheet_name, source_row=index + 1))
    if not records:
        raise ValueError("No Ankara controls found")
    observations = {}
    for record in records:
        key = (record["year"], record["statistic"])
        if key in observations and not math.isclose(observations[key], record["value"], rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"Conflicting source values: {key}")
        observations[key] = record["value"]
    for year in {r["year"] for r in records}:
        counts = [observations.get((year, name)) for name in ("total_population", "male_population", "female_population")]
        if any(v is not None for v in counts) and (any(v is None for v in counts) or counts[0] != counts[1] + counts[2]):
            raise ValueError(f"Population totals do not reconcile for {year}")
    return sorted(records, key=lambda r: (r["year"], r["statistic"], r["source_workbook"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    rows = extract_controls(args.raw_dir)
    write_csv(rows, args.output)
    for row in rows:
        print(f"{row['year']} {row['statistic']}={row['value']} ({row['unit']}): {row['source_workbook']} / {row['source_sheet']} / row {row['source_row']}")
    print(f"Wrote {len(rows)} source observations to {args.output}")


if __name__ == "__main__":
    main()
