# Data

**No raw dataset, generated population, or experiment result is committed to this repository.**

SocietyTwin uses **official aggregate statistics for Türkiye**, primarily from **TÜİK** (Turkish Statistical Institute).
Sources, geographic levels, access, and licence status are described in [docs/data-strategy.md](../docs/data-strategy.md);
how the national pipeline uses them is in [docs/national-pipeline.md](../docs/national-pipeline.md).

Datasets in use are recorded in [`manifest.yaml`](manifest.yaml): the team's TÜİK province package (33 datasets, all
81 provinces; integrated locally, git-ignored) and three TÜİK-derived Ankara extracts that ship with the historical
MatrAIx experiment (now corroborating: every value equals the package's).

## Folders

| Path | Purpose | In Git? |
|---|---|---|
| `raw/` | Original downloads, exactly as published. Never edited by hand. | No (git-ignored) |
| `raw/tuik_package/` | The team's TÜİK province package, files directly in this folder: 33 `<dataset>.csv` (long), 33 `<dataset>_wide.csv`, `data_catalog.csv`, `variable_metadata.csv`, `coverage_report.csv`, `not_province_level.csv`, `README.md` (71 files). | No (git-ignored) |
| `raw/tuik_province_data/` | The extracted folder the package arrived in, kept unchanged (same 71 files, identical SHA-256). Not read by the pipeline. | No (git-ignored) |
| `processed/national/` | Standard control tables built by `python -m societytwin.national build-controls` (`controls.csv`, `context.csv`, `manifest.json` with checksums, sources, the indicator dictionary and the package audit). | No (git-ignored) |
| `populations/` | Generated populations: one folder per build with `records.parquet`, `manifest.json`, `validation.json`. | No (git-ignored) |
| `results/` | Workbench state: registry, run manifests and responses. | No (git-ignored) |
| `manifest.yaml` | Metadata for every dataset in use: source, title, identifier, URL, years, coverage, variables, licence, checksum, transformations, limitations. | **Yes** |
| `tuik_package_mapping.yaml` | Rules that turn package indicators into generator control tables, and the domain, use and reason for every package dataset (metadata, no data). | **Yes** |

## Setting up the data package locally (teammates)

The package is not in this branch. Its 71 files are on the team branch `data-turkey` (folder `tuik_province_data/`,
added by Koray); the copy integrated here was checked to be byte-identical (SHA-256) on 2026-10-19. Copy the files out
of that branch; **do not merge `data-turkey` into a code branch** (it commits raw data, which code branches never do).

macOS / Linux, from the repository root:

```bash
git fetch origin data-turkey
mkdir -p data/raw/tuik_package
git archive origin/data-turkey tuik_province_data | tar -x -C data/raw/tuik_package --strip-components=1
ls data/raw/tuik_package | wc -l                                   # 71 files, directly in the folder
PYTHONPATH=src .venv/bin/python -m societytwin.national build-controls
PYTHONPATH=src .venv/bin/python -m societytwin.national generate --size 100000 --seed 42
.venv/bin/python -m pytest -m tuik_package -q                       # asserts the package findings
```

Windows (PowerShell):

```powershell
git fetch origin data-turkey
New-Item -ItemType Directory -Force data\raw\tuik_package | Out-Null
git archive --format=tar -o tuik_package.tar origin/data-turkey tuik_province_data
tar -x -f tuik_package.tar -C data\raw\tuik_package --strip-components=1
Remove-Item tuik_package.tar
$env:PYTHONPATH = "src"
.\.venv\Scripts\python -m societytwin.national build-controls
.\.venv\Scripts\python -m societytwin.national generate --size 100000 --seed 42
```

If you received the package another way (e.g. a zip), put its files **directly** in `data/raw/tuik_package/`, not in a
nested folder, and do not edit them. In the UI, **Data Sources → Build control tables** does the build step.

- Rebuild the controls after pulling: the control-store format changed (`controls-store-2`); an older build is
  reported as "unsupported control store version" until it is rebuilt.
- Use 100,000 records (or `--min-per-province`) for 81-province work: at 10,000 records small provinces get about
  10 records and many province margins cannot be imposed (they are reported on the Validation page).
- Without the package, only the historical Ankara extracts load (1 of 81 provinces), and the UI says so.

## What the build does with the package

1. Every long-format row becomes a control cell (through a rule in `tuik_package_mapping.yaml`), a province context
   observation with its published reference period and value status, or a rejected row with a reason. The wide files
   are checked cell by cell against the long files and not imported.
2. The build report and Data Sources page list the package audit: counts, discrepancies with the package
   documentation, coverage, blanks, multi-year periods, projections and per-table checks.
3. For a new package version: review the audit, then run `.venv/bin/python -m pytest -m tuik_package` and update the
   regression deliberately where counts change. Details and the verified findings:
   [docs/national-pipeline.md §3](../docs/national-pipeline.md#3-data).

## Rules

- **Never commit data or generated outputs.** `.gitignore` excludes everything in the folders above except placeholder and README files, plus common data formats anywhere under `data/`.
- **Commit metadata, not data.** Record every dataset in [`manifest.yaml`](manifest.yaml); unknown fields stay null.
- **Aggregate data only.** No personal or identifiable data may be added. TÜİK microdata, if ever approved, is used only under TÜİK's access rules and is never copied into this repository.
- **Missing is not zero.** Values keep their status (observed, not reported, unknown, not applicable, structurally unavailable).
- **Respect licences.** Record each dataset's licence; reuse terms that are not yet confirmed are an OPEN DECISION.
- **Keep raw data unchanged.** All cleaning and harmonisation is done in code, so processed data can be regenerated.
- **Test fixtures** must be small and clearly artificial, and live in `tests/fixtures/`, not in `data/`.
- Git history keeps deleted files: anything committed must be treated as published.
