"""Write the ARTIFICIAL long-format package used by the national tests and the browser flow.

Province codes are the real plate codes (the reference table is classification metadata), but every
number is invented by the formulas below. Nothing here is a TÜİK statistic.

    python tests/fixtures/build_artificial_tuik_package.py
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "artificial_tuik_package"
MAPPING = ROOT / "artificial_tuik_package_mapping.yaml"
BANDS = [f"{a}-{a + 4}" for a in range(0, 90, 5)] + ["90+"]
PROVINCES = {"01": ("Adana", "TR621", 1000), "06": ("Ankara", "TR510", 2000), "69": ("Bayburt", "TRA13", 30)}
SEX_TR = {"male": "Erkek", "female": "Kadın"}
HEADER = ["dataset_id", "province_code", "province_name", "nuts3_code", "year", "indicator", "value", "unit"]


def population(scale: int, band_index: int, sex: str, year: int) -> int:
    shape = 100 - 4 * band_index
    return round(scale * shape / 100 * (1.03 if sex == "female" and band_index > 12 else 1.0) * (0.98 if year == 2024 else 1.0))


def split(total: int, shares: list[float]) -> list[int]:
    parts = [int(total * s) for s in shares[:-1]]
    return parts + [total - sum(parts)]


def main() -> None:
    PACKAGE.mkdir(exist_ok=True)
    rows = {"population_by_age_sex": [], "marital_status_by_sex": [], "education_by_sex": [], "air_traffic": [],
            "gdp_per_capita": [], "quality_checks": []}
    adult = {}
    for code, (name, nuts3, scale) in PROVINCES.items():
        for year in ((2024, 2025) if code == "01" else (2025,)):
            for i, band in enumerate(BANDS):
                for sex in ("male", "female"):
                    value = population(scale, i, sex, year)
                    rows["population_by_age_sex"].append(["population_by_age_sex", code, name, nuts3, year,
                                                          f"Nüfus | {SEX_TR[sex]} | {band}", value, "kişi"])
                    if year == 2025 and i >= 3:
                        adult[(code, sex)] = adult.get((code, sex), 0) + value
    marital = {"female": [0.30, 0.55, 0.06, 0.09], "male": [0.35, 0.58, 0.05, 0.02]}
    labels = ["Hiç evlenmedi", "Evli", "Boşandı", "Eşi öldü"]
    education = [0.03, 0.04, 0.20, 0.10, 0.08, 0.30, 0.20, 0.04, 0.01]
    edu_labels = ["Okuma yazma bilmeyen", "Okuma yazma bilen fakat bir okul bitirmeyen", "İlkokul", "İlköğretim",
                  "Ortaokul veya dengi meslek ortaokul", "Lise veya dengi meslek okulu", "Yüksekokul veya fakülte",
                  "Yüksek lisans", "Doktora"]
    for code, (name, nuts3, _) in PROVINCES.items():
        for sex in ("male", "female"):
            for label, value in zip(labels, split(adult[(code, sex)], marital[sex])):
                rows["marital_status_by_sex"].append(["marital_status_by_sex", code, name, nuts3, 2025,
                                                      f"Medeni durum | {SEX_TR[sex]} | {label}", value, "kişi"])
            # Bayburt has education only as a 2026 projection: it must not be used for a 2025 population.
            year = 2026 if code == "69" else 2025
            for label, value in zip(edu_labels, split(adult[(code, sex)], education)):
                rows["education_by_sex"].append(["education_by_sex", code, name, nuts3, year,
                                                 f"Eğitim | {SEX_TR[sex]} | {label}", value, "kişi"])
    rows["air_traffic"] += [["air_traffic", "06", "Ankara", "TR510", 2024, "Yolcu sayısı (bin)", "12345.6", "bin kişi"],
                            ["air_traffic", "06", "Ankara", "TR510", 2025, "Yolcu sayısı (bin)", "-", "bin kişi"]]
    rows["gdp_per_capita"] += [["gdp_per_capita", "01", "Adana", "TR621", 2023, "Kişi başına GSYH", "150000", "TL"],
                               ["gdp_per_capita", "06", "Ankara", "TR510", 2023, "Kişi başına GSYH", "250000", "TL"],
                               ["gdp_per_capita", "69", "Bayburt", "TRA13", 2023, "Kişi başına GSYH", "", "TL"]]
    rows["quality_checks"] += [["quality_checks", "99", "Nowhere", "TR999", 2025, "Kontrol", "1", "adet"],
                               ["quality_checks", "06", "Ankara", "TR100", 2025, "Kontrol", "1", "adet"],
                               ["quality_checks", "06", "Ankara", "TR510", 2025, "Kontrol", "2", "adet"],
                               ["quality_checks", "06", "Ankara", "TR510", 2025, "Kontrol", "3", "adet"],
                               ["quality_checks", "06", "Ankara", "TR510", 2025, "Sıfır", "0", "adet"]]
    for dataset, data in rows.items():
        with (PACKAGE / f"{dataset}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(HEADER)
            writer.writerows(data)
    catalog = [["dataset_id", "theme", "title_en", "title_tr", "source_url", "publication_date", "retrieval_date"],
               ["population_by_age_sex", "Population & Vital", "ARTIFICIAL population by age and sex", "YAPAY yaş ve cinsiyete göre nüfus", "", "", ""],
               ["marital_status_by_sex", "Households & Family", "ARTIFICIAL marital status by sex", "", "", "", ""],
               ["education_by_sex", "Education", "ARTIFICIAL educational attainment by sex", "", "", "", ""],
               ["air_traffic", "Mobility, Tech & Lifestyle", "ARTIFICIAL air passengers", "", "", "", ""],
               ["gdp_per_capita", "Labor & Income", "ARTIFICIAL GDP per capita", "", "", "", ""],
               ["quality_checks", "Other", "ARTIFICIAL malformed rows for ingestion tests", "", "", "", ""]]
    for name, data in {"data_catalog.csv": catalog,
                       "variable_metadata.csv": [["indicator", "theme", "unit"], ["Kişi başına GSYH", "Labor & Income", "TL"]],
                       "coverage_report.csv": [["dataset_id", "province_count", "note"], ["air_traffic", "1", "Artificial partial coverage"]],
                       "not_province_level.csv": [["dataset_id", "note"]]}.items():
        with (PACKAGE / name).open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows(data)
    (PACKAGE / "README.md").write_text(
        "# Artificial long-format package\n\nEvery value in this folder is **artificial** (see "
        "`../build_artificial_tuik_package.py`). Province codes are real plate codes; the numbers are not TÜİK statistics.\n",
        encoding="utf-8")
    MAPPING.write_text("""# Mapping for the ARTIFICIAL test package (same format as data/tuik_package_mapping.yaml).
version: 1
controls:
  - table: population_age_sex
    dataset: population_by_age_sex
    indicator_pattern: '^Nüfus \\| (?P<sex>Erkek|Kadın) \\| (?P<age_group>\\d+-\\d+|90\\+)$'
    universe_min_age: 0
    universe_note: All residents (artificial)
  - table: marital_status_sex
    dataset: marital_status_by_sex
    indicator_pattern: '^Medeni durum \\| (?P<sex>Erkek|Kadın) \\| (?P<category>.+)$'
    universe_min_age: 15
    universe_note: Residents aged 15+ (artificial)
  - table: education_sex
    dataset: education_by_sex
    indicator_pattern: '^Eğitim \\| (?P<sex>Erkek|Kadın) \\| (?P<category>.+)$'
    universe_min_age: 15
    universe_note: Residents aged 15+ (artificial)
""", encoding="utf-8")


if __name__ == "__main__":
    main()
