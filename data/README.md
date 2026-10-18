# Data

**No raw dataset, generated population, or experiment result is committed to this repository.**

SocietyTwin uses **official aggregate statistics for Türkiye**, primarily from **TÜİK** (Turkish Statistical Institute).
Sources, geographic levels, access, and licence status are described in [docs/data-strategy.md](../docs/data-strategy.md);
how the national pipeline uses them is in [docs/national-pipeline.md](../docs/national-pipeline.md).

Datasets currently in use are listed in [`manifest.yaml`](manifest.yaml): three TÜİK-derived Ankara extracts that ship
with the historical MatrAIx experiment. The team's long-format TÜİK package (reported: 33 datasets, 577 indicators) is
**not** in this repository; see "Adding the TÜİK package" below.

## Folders

| Path | Purpose | In Git? |
|---|---|---|
| `raw/` | Original downloads, exactly as published. Never edited by hand. | No (git-ignored) |
| `raw/tuik_package/` | The team's long-format TÜİK package, when added. | No (git-ignored) |
| `processed/national/` | Standard control tables built by `python -m societytwin.national build-controls` (`controls.csv`, `context.csv`, `manifest.json` with checksums). | No (git-ignored) |
| `populations/` | Generated populations: one folder per build with `records.parquet`, `manifest.json`, `validation.json`. | No (git-ignored) |
| `results/` | Workbench state: registry, run manifests and responses. | No (git-ignored) |
| `manifest.yaml` | Metadata for every dataset in use: source, title, identifier, URL, years, coverage, variables, licence, checksum, transformations, limitations. | **Yes** |
| `tuik_package_mapping.yaml` | Rules that turn package indicators into generator control tables (metadata, no data). | **Yes** |

## Adding the TÜİK package

1. Copy the package files to `data/raw/tuik_package/` (data CSVs with `province_code, province_name, nuts3_code, year,
   indicator, value, unit`, plus the metadata CSVs if available).
2. Run `PYTHONPATH=src .venv/bin/python -m societytwin.national build-controls`. Every indicator becomes province
   context, with coverage and missing-value status preserved; rejected rows are listed in the build report.
3. Add rules to `tuik_package_mapping.yaml` for the tables the generator should use (population by age group × sex
   first), rebuild, and generate. Summarise the datasets used in `manifest.yaml`.

## Rules

- **Never commit data or generated outputs.** `.gitignore` excludes everything in the folders above except placeholder and README files, plus common data formats anywhere under `data/`.
- **Commit metadata, not data.** Record every dataset in [`manifest.yaml`](manifest.yaml); unknown fields stay null.
- **Aggregate data only.** No personal or identifiable data may be added. TÜİK microdata, if ever approved, is used only under TÜİK's access rules and is never copied into this repository.
- **Missing is not zero.** Values keep their status (observed, not reported, unknown, not applicable, structurally unavailable).
- **Respect licences.** Record each dataset's licence; reuse terms that are not yet confirmed are an OPEN DECISION.
- **Keep raw data unchanged.** All cleaning and harmonisation is done in code, so processed data can be regenerated.
- **Test fixtures** must be small and clearly artificial, and live in `tests/fixtures/`, not in `data/`.
- Git history keeps deleted files: anything committed must be treated as published.
