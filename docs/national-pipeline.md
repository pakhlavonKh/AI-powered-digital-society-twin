# SocietyTwin national pipeline

Türkiye-wide synthetic population calibrated to official aggregate statistics, cohorts, personas and controlled
persona-conditioned AI experiments. Code: [`src/societytwin/national/`](../src/societytwin/national/), API `/api/v2`,
UI in [`frontend/`](../frontend/).

```text
official tables ─► standard control tables ─► dependency + constraint model ─► national generator (province = dimension)
     ─► source-fit validation ─► cohorts ─► personas ─► scenario + task + environment ─► AI runner (stub / MatrAIx)
     ─► structured responses ─► weighted aggregation ─► web UI
```

A synthetic record is not a persona, and a persona is not an AI agent. 100,000 records never means 100,000 LLM calls:
an experiment runs only the personas of a bounded, seeded cohort sample after an explicit, reviewed plan.

## 1. Status

| Area | Status |
|---|---|
| 81-province reference table (plate, NUTS-1/2/3, ISO codes), checked against the map geometry | **Implemented** |
| Standard control store; Ankara TÜİK extracts adapter; TÜİK province package reader (long + wide + metadata) with mapping rules | **Implemented**; the package is integrated locally (git-ignored, see §3) |
| One national generator, dependency model, constraint engine, controlled-rounding allocation, raked weights | **Implemented** |
| Source-fit validation with documented tolerances, constraint checks, cross-source checks | **Implemented** |
| Parquet storage with manifests; 10K / 100K (and optional 1M) builds and benchmark | **Implemented** |
| ProvinceEnvironment (context indicators with their own years; structural unavailability) | **Implemented** |
| Cohort definitions; seeded simple-random, weighted (PPS) and stratified samples | **Implemented** |
| Persona builder for any province; model-visible vs hidden attributes; MatrAIx persona export | **Implemented** |
| Experiment schema (scenario/task/environment/cohort/model/execution); reviewed plans; budget guard | **Implemented** |
| Runner: stub backend; MatrAIx PersonaJsonSurvey with arbitrary personas (fake transport verified); replay cache | **Implemented** |
| MatrAIx live provider transport | **Partially implemented**: gated, never run against a provider |
| Weighted aggregation with Kish effective n, intervals, small-group suppression | **Implemented** |
| UI: Dashboard, Population, Cohorts, Personas, New Experiment, Experiments, Results, Validation, Data Sources, Settings | **Implemented** |
| Real data for all 81 provinces: age group × sex (root), marital status, education and settlement type, 2016–2025 | **Implemented** from the TÜİK province package (2025 for every province at the default reference year) |
| Province context: 472–497 package indicators per province in 13 domains, with published periods and projections kept apart | **Implemented** |
| Labour status, household size and household type on real data | **Not available**: the package publishes labour-force *rates* and household *counts*, not persons by status or household (§3.4) |
| Socioeconomic status, income, employment status, district | **Not modelled** (no person-level source) |
| Held-out validation, behavioural validation, cost price table | **Not implemented** |

## 2. Quick start

Python 3.12 and Node.js 22+. From the repository root.

macOS / Linux:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-api.lock && .venv/bin/pip install -e . --no-deps
(cd frontend && npm ci)
PYTHONPATH=src .venv/bin/python -m societytwin.national build-controls          # normalise the available official tables
PYTHONPATH=src .venv/bin/python -m societytwin.national generate --size 10000 --seed 42
./scripts/dev.sh                                                                # UI on http://127.0.0.1:3000
```

Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements-api.lock; .\.venv\Scripts\pip install -e . --no-deps
cd frontend; npm ci; cd ..
$env:PYTHONPATH = "src"
.\.venv\Scripts\python -m societytwin.national build-controls
.\.venv\Scripts\python -m societytwin.national generate --size 10000 --seed 42
.\.venv\Scripts\python -m uvicorn --factory societytwin.api.app:app_factory --host 127.0.0.1 --port 8000
# second terminal:  cd frontend; npx next dev --hostname 127.0.0.1 --port 3000
```

The UI can do the last two steps itself (**Build control tables**, **Generate population**). Other CLI commands:
`list`, `validate POPULATION_ID`, `benchmark --sizes 10000 100000 [1000000]`. Options: `--province 06` (repeatable),
`--reference-year`, `--min-per-province`, `--no-calibrate`.

## 3. Data

### 3.1 What is loaded

| Source | Where | Use |
|---|---|---|
| **TÜİK province package** (team package, TÜİK Veri Portalı; 33 province-level datasets) | `data/raw/tuik_package/` (git-ignored; 71 files) | Control tables for all 81 provinces and all province context |
| Historical Ankara extracts shipped with the MatrAIx experiment | [`experiments/matraix_simulation/processed/`](../experiments/matraix_simulation/processed/) (read-only) | Corroboration: every value equals the package's, so the package is cited |

The package was copied into `data/raw/tuik_package/` from the extracted folder `data/raw/tuik_province_data/`, which is
kept unchanged; the SHA-256 of all 71 files is identical in both places. It contains 33 long-format dataset CSVs
(`province_code, province_name, nuts3_code, year, indicator, value, unit`), their 33 `_wide.csv` twins,
`data_catalog.csv`, `variable_metadata.csv`, `coverage_report.csv`, `not_province_level.csv` and `README.md`. No package
file is committed; [`data/tuik_package_mapping.yaml`](../data/tuik_package_mapping.yaml) (rules, no data) is.

### 3.2 Package findings, re-counted from the data

`build-controls` recounts these on every build and stores them in the control-store manifest (`audits`); the Data
Sources page shows them, and `tests/regression/test_national_tuik_package.py` asserts them. The package README and
metadata are treated as source information to check, not as proof.

| Item | Package documentation says | The data contains |
|---|---|---|
| Long-format rows | 411,132 (README) | **431,071** |
| Indicators | 577 (README and `variable_metadata.csv`) | **568** with rows. The 9 others are `transferred_vehicles_{total, car, minibus, bus, small_truck, truck, motorcycle, special_purpose, tractor}` of `road_motor_vehicles_and_transfers`, defined but never reported |
| Datasets | 33 | 33 long + 33 wide |
| Province coverage | 30 datasets 81/81; air traffic 51, agricultural wages 35, opera and ballet 6 | Same. `provinces_covered`, `missing_provinces` and `coverage_report.csv` all agree with the rows |
| Reference years, units | `data_catalog.csv` | Agree for all 33 datasets (period counts include multi-year labels) |
| Province identity | `01`–`81`, NUTS-3 `TR100`–`TRC34` | Every row has a valid plate code whose NUTS-3 code and name match the reference table |
| Duplicate province × period × indicator keys | none | None in any dataset |
| Long vs wide files | same values | 431,071 cells compared, 0 mismatches, no value only in a wide file. Wide files are verified and **not imported** |
| Blank values | `""` for suppressed (`c`) or absent (`-`) cells | **20,431** blanks (prison convicts 10,259; health 6,538; air traffic 1,702; agricultural wages 776; sports/media 772; deaths by cause 300; SES 81; mortality 3). All `NOT_REPORTED`; none is zero |
| Multi-year reference periods | – | **1,923** rows: `2013-2014` non-formal education (810); life expectancy `2013-2014`, `2015-2017`, `2018-2020`, `2021-2023` (972); opera/ballet seasons `2023-2024`, `2024-2025` (60); projected growth rate `2023-2030` (81) |
| Projections | "2023 ADNKS baseline + 2024–2030 projections" | 729 rows. The 2023 baseline equals ADNKS 2023 in all 81 provinces; the 2024 and 2025 projections differ from the observed populations in all 81 (national 2025: 86,239,196 projected vs 86,092,168 observed) |
| Negative values | – | 2,427, all in signed indicators (net migration, growth rates, annual index changes) |
| Absent rows inside covered provinces | – | Some province rows are missing (not blank): urban/rural 1,242 (town/village rows of the 30 metropolitan provinces from 2013; DEGURBA dense-urban rows of 6 provinces), air traffic 1,408, agricultural wages 804, marital status 202 (the "unknown" category exists only for 2008), prison 100, traffic 16, international migration 13. Absent rows are not created and are not zeros |
| Not province level | 10 datasets | 10 listed in `not_province_level.csv` (SILC income and poverty, household budget, ICT use, regional PPP, detailed labour force, family structure, health survey, domestic tourism, time use); shown on Data Sources, not loaded |

Province coverage of a dataset does not mean every indicator and year has a value: blanks, absent rows and
multi-year periods are reported per dataset.

### 3.3 How the package is read

[`sources.py`](../src/societytwin/national/sources.py) (`tuik_package`), configured by
[`tuik_package_mapping.yaml`](../data/tuik_package_mapping.yaml):

- **Metadata columns** are the package's actual ones: `data_catalog.csv` (`file_name`, `wide_file_name`,
  `dataset_title_tr`, `dataset_title_en`, `theme`, `source_url`, `publication_date`, `reference_year(s)`, `unit`,
  `provinces_covered`, `missing_provinces`, `retrieval_date`, `notes`), `variable_metadata.csv` (`file_name`,
  `indicator`, `original_name_tr`, `description_en`, `unit`, `source_table_or_flow`), `coverage_report.csv` (province ×
  dataset 1/0 matrix) and `not_province_level.csv`. Older aliases (`dataset_id`, `title_en`, …) still work.
- **Dataset identity** is the CSV file name without `.csv` (`tuik_pkg:population_by_age_sex`). Each source records its
  titles, URL, publication and retrieval dates, the TÜİK tables/flows it combines (e.g. `DF_ADNKS_T16_V1.0`), units,
  reference periods, coverage, blank and absent-row counts, the SHA-256 of the long and wide files, and its mapping
  decision. Each indicator keeps its Turkish name, English description and unit; each observation keeps `file:line`.
- **Every row is accounted for**: read = control cells + context observations + rejected + agreeing duplicates (real
  package: 76,980 + 354,091 + 0 + 0 = 431,071).
- **Row checks**: plate code 01–81, NUTS-3 code matches, name matches (a different name is a warning; the code is used),
  reference period, numeric value, unit against `variable_metadata.csv`, indicator defined, conflicting duplicate keys
  (rejected and listed).
- **Missing values**: blank → `NOT_REPORTED`; a province the dataset does not cover → `STRUCTURALLY_UNAVAILABLE`;
  absent rows are not created; nothing is zero unless the source printed 0.
- **Reference periods** are stored exactly as published (`period` = `2025` or `2021-2023`). A multi-year period has no
  single `year` (it is `null`); for selection only its last year is compared with the reference year, and the period
  label is what the environment, the API and prompts show. Control tables accept single years only.
- **Projections** are declared in the mapping (`observation_type: projection`, baseline `2023`). They are context only,
  never a current value (also for 2024 and 2025, which are ≤ the reference year), listed separately in the
  environment, and can never become control cells.

### 3.4 Mapping decisions

Control rules were written after inspecting the indicator names, the Turkish source names, units and universes. Each
rule maps detailed cells only; published aggregate rows (sex totals, all-ages totals, category totals) stay context and
are used to check that the cells add up (a total is never summed into a cell, so nothing is double-counted). Every
mapped indicator's Turkish name is checked for the mapped sex, age band and category (70 indicators, 0 mismatches).

| Dataset | Control table | Verified |
|---|---|---|
| `population_by_age_sex` (ADNKS T16, 2016–2025) | `population_age_sex` (root): 19 bands × 2 sexes | Bands sum to the sex totals, male + female = total, and the total equals `total_population` (T30) in every province and year |
| `marital_status_by_sex` (T10, 15+, 2008–2025) | `marital_status_sex`: never married, married, divorced, widowed | Categories (+ "unknown", 2008 only, 44 persons nationally) sum to the totals. The total equals the ADNKS 15+ population **exactly in 2021–2025**; in 2016–2020 it is 0.05–8.7 % smaller |
| `education_attainment_by_sex` (15+, 2008–2025) | `education_sex`: the 10 TÜİK levels incl. "unknown" (`primary_school` → İlkokul, `primary_education` → İlköğretim, …) | Categories sum to the totals. The total is **below** the ADNKS 15+ population in every province and year (2025: 0.1–6.3 % per province, 1.34 million nationally); the gap correlates 0.9998 with the foreign resident population, consistent with a universe excluding most foreign nationals (an inference; the metadata does not say) |
| `population_urban_rural` (T14) | `urbanicity_sex`: province/district centres vs towns/villages | Centres + towns/villages = the total per sex. The 30 metropolitan provinces have no town/village rows from 2013; their centres hold the whole population, so no record is assigned there |

The generator applies each table's distribution to the root population (scaled per sex); the scale per province is in
the validation report. Context only, with the reason recorded per dataset in the mapping file and on Data Sources:

- `labor_force_indicators`: labour-force participation, employment and unemployment **rates** with 95 % CIs (HLFS). No
  counts by labour status exist per province; converting survey rates to counts would invent precision, so
  `labour_status` stays unavailable.
- `households_size_and_types`: **households** by type and average size, not persons by household type or size, so
  `household_size_class` and `household_type` stay unavailable.
- `socioeconomic_status_and_human_development`: SES classes as **household** shares (3-year average) and HDI/HCI
  indices; no person-level SES.
- `population_urban_rural` DEGURBA split: a different classification from the administrative settlement type.
- `population_structural_indicators` (derived from the same ADNKS counts), `literacy_and_nonformal_education`
  (different universe, overlaps education), vital rates and life expectancy, deaths by cause, marriages and divorces,
  migration flows, GDP, housing, vehicles, traffic, air traffic, well-being (2013/2015), sports and media, opera and
  ballet, health infrastructure, agriculture, municipal services, prison convicts (sensitive; never a person field),
  population projections.

The historical Ankara extracts are loaded after the package: their 38 age × sex cells, 8 marital cells and 17 context
values (totals, density, median ages for 2023–2025) equal the package's, so they are marked `corroborating`, the
package is cited, and they are not listed as coverage gaps.

### 3.5 Adding or updating the package

Teammates: the package files are on the team branch `data-turkey` (`tuik_province_data/`); copy them out with the
commands in [data/README.md](../data/README.md#setting-up-the-data-package-locally-teammates) rather than merging that
branch.

1. Put all files directly in `data/raw/tuik_package/` (no nested folder).
2. `PYTHONPATH=src .venv/bin/python -m societytwin.national build-controls`, then read the audit on Data Sources (or
   `data/processed/national/manifest.json` → `audits`): counts, documentation discrepancies, wide-file check, rejected
   rows, per-table checks.
3. A changed indicator name, unit or label makes the rule's rows fail loudly (rejected with a reason), never silently
   remapped. New control rules go into the mapping file; `use`, `domain` and `reason` are recorded per dataset.
4. Run `.venv/bin/python -m pytest -m tuik_package` (the regression asserts the counts above; update it deliberately
   when a new package version changes them).

**Standard control tables** ([`controls.py`](../src/societytwin/national/controls.py)): `population_age_sex` (root),
`marital_status_age_sex`, `marital_status_sex`, `education_age_sex`, `education_sex`, `labour_status_age_sex`,
`labour_status_sex`, `household_size_persons`, `household_type_persons`, `urbanicity_sex`, `urbanicity`. Each cell
has `geo_level` (province, nuts2, nuts1, country), year, value and **value status**. Loaded from the package:
`population_age_sex`, `marital_status_sex`, `education_sex`, `urbanicity_sex`, each for all 81 provinces.

**Missing values are never zero.** `OBSERVED` (a published number, 0 included), `NOT_REPORTED` (row present, no number:
blank, `-`, `..`), `UNKNOWN`, `NOT_APPLICABLE`, `STRUCTURALLY_UNAVAILABLE` (the dataset does not cover the province,
e.g. 51/81 for air traffic). Coverage is shown as k/81 on Data Sources and in the environment.

## 4. Reference-year strategy

The population reference year defaults to **2025**. For every table and province the generator uses the latest year
**not after** the reference year; later years (e.g. projections) are never used, and nothing is interpolated or
carried forward silently. Each field's source year is stored in the provenance profile and shown next to the
population reference year (Population Explorer, persona detail, run manifest). A source year that differs from the
reference year adds an explicit limitation. With the package, every province's four tables come from 2025.

Province context follows the same rule with the published reference **period**: the current value of an indicator is
the latest observed value whose period ends no later than the reference year (life expectancy at reference year 2025:
`2021-2023`, shown as such). Official projections are never current values, even for 2024 and 2025. When a province's
series stops before the dataset's latest period (e.g. town/village population of a metropolitan province, last row
2012), the value is shown with its own year and a note that later rows are absent, not zero.

## 5. Person schema and evidence

Columns (`records.parquet`): `synthetic_id` (`ST2025-06-0000123`), `province_code`, `province_name`, `nuts1_code`,
`nuts2_code`, `nuts3_code`, `age`, `age_group`, `age_top_coded`, `sex`, `marital_status`, `education_level`,
`labour_status`, `household_size_class`, `household_type`, `urbanicity`, `population_weight`, `design_weight`,
`provenance_profile`, `reference_year`. Values are codes; `not_applicable` means outside the source universe; null
means no source for that province. Provenance is normalised: one profile per province in the manifest, referenced by
`provenance_profile`, never copied into every row. Province context lives in the environment, not in person rows.

| Evidence | Meaning |
|---|---|
| `DIRECT_SOURCE` | The record's cell is a published cell (province × age group × sex) |
| `CONDITIONAL_SOURCE` | Drawn from an official conditional with every parent observed jointly (e.g. marital \| age, sex) |
| `MARGINAL_INFERENCE` | Drawn from a fit to official marginals; the joint with some parents is not observed |
| `RULE_CONSTRAINED` | Set by a documented rule (e.g. `not_applicable` below the universe age) |
| `DERIVED` | Computed from other fields or reference tables (NUTS codes, weights) |
| `ASSUMED` | Drawn from an assumed distribution (single-year age, uniform within the band) |
| `CONTEXTUAL` | Province context in the environment |
| `UNAVAILABLE` | No source; the value is null and the reason is recorded |

## 6. Dependency model

```text
province ──► (age group × sex)   DIRECT_SOURCE, joint ADNKS cell
                 │
                 ├─► age           ASSUMED: uniform within band, 90+ top-coded at 90
                 ├─► marital       age×sex×marital table → CONDITIONAL_SOURCE
                 │                 else sex×marital table → IPF per sex → MARGINAL_INFERENCE (age joint not observed)
                 ├─► education     same options; IPF over single years of age with structural zeros (constraint engine)
                 ├─► labour        same options; regional (NUTS-2/1) tables applied to each province and flagged
                 ├─► settlement    sex × settlement table → IPF per sex → MARGINAL_INFERENCE
                 └─► household size / type   province table → MARGINAL_INFERENCE (no table loaded: UNAVAILABLE)
```

Why IPF: when only `sex × category` is published, the two-way IPF of the root's age-group margin and the category
margin, per sex, is the maximum-entropy joint consistent with both. Without structural zeros it reduces exactly to
conditioning on sex alone, which is what the marital and settlement tables support. With structural zeros (education)
the fit runs over single years of age (each band's population spread uniformly over its ages, the same assumption as
the exact-age draw), so a zero at an exact age inside a band, such as higher education below 18 in the 15–19 band, is
part of the fit. (An earlier band-level seed let the draw remove fitted mass at those ages; on the 81-province data that
under-drew higher education by 1.2 percentage points, |z| ≈ 6. The single-age fit removes the bias: national |z| 1.87.)
It is not used where a joint table exists.

**Not supported by the loaded data (and therefore not claimed):** province × age × sex × marital status or education
(only province × sex × category is published); any relationship between marital status, education and settlement type
beyond age and sex; labour status and household attributes (no person-level table); district geography; income or
socioeconomic status at person level.

## 7. Constraints

Centralised in [`constraints.py`](../src/societytwin/national/constraints.py) and run on every record of every build
(target: zero violations):

- `source_universe`: an attribute is `not_applicable` exactly below the minimum age of its source table's universe
  (read from the table metadata; marital status 15+).
- `education_min_completion_age`: lenient minimum ages per attainment level from the formal school structure
  (primary 9, 8-year basic 13, lower secondary 13, upper secondary 16, higher 18, master's 21, doctorate 24). Used as
  structural zeros only where age × education is not observed.
- `age_within_band`, `geography_consistent`, `category_in_vocabulary`, `weight_positive_finite`.
- `adult_eligibility`: adult-only cohorts and experiments require age ≥ 18 (Turkish Civil Code Art. 11). A plan whose
  sample contains a minor for an adult task is blocked.

No demographic rule beyond a source's own universe is added (e.g. no invented minimum marriage age).

## 8. Allocation and weights

1. Each covered province gets records proportional to its population (largest remainder), at least one when the size
   allows, or at least `--min-per-province` (oversampling small provinces for province-level analysis).
2. Within the province, records are allocated to age × sex cells by largest remainder. Cells that receive no record are
   collapsed into the nearest allocated band of the same sex (logged in the manifest), so no population is lost.
3. Design weight = cell population ÷ records in the cell (stratified sample with proportional allocation).
4. Raking (iterative proportional fitting of the weights) to every province-level control table used, until the
   largest relative deviation is ≤ 1e-10. Unreachable cells (no record at this size) are reported and their mass is
   redistributed within the same parent group. Margins are added in priority order (marital status, education,
   settlement type) and kept only if raking with them converges (up to 5,000 iterations) **and** every final weight
   stays within ×0.05–×20 of its design weight (`WEIGHT_RATIO_BOUNDS`). With few records in a province the margins
   can be jointly unattainable: raking then drives some weights towards zero, or meets the margin only by nearly
   deleting a record. Such a margin is **not imposed**; raking for it is abandoned once a weight falls 1,000× below the
   lower bound. It is listed in the manifest (`calibration[].margins_not_calibrated`, with the reason), recorded in
   the attribute's provenance (`calibration.imposed = false` and a limitation shown on persona detail), and reported
   by validation (§9). More records per province (`--min-per-province`) avoid it. Generator version
   `national-generator-1.1` introduced these rules and the single-age education IPF.

`population_weight` is the number of residents a record represents. Weighted analysis is the default for population
estimates; record shares are shown alongside. Diagnostics: weight CV, Kish design effect, raking iterations, and the
ratio of final to design weights.

## 9. Source-fit validation

[`validation.py`](../src/societytwin/national/validation.py), stored per build as `validation.json` and shown on the
Validation page, for all covered provinces combined and per province. Per cell: source count, weighted synthetic count,
source share, synthetic share, absolute, relative and percentage-point error, record count, record share and the
record share's z score. Per table: TVD (weighted and records), JSD, SRMSE, maximum errors.

| Tolerance | Value | Justification |
|---|---|---|
| `calibration_relative` | 1e-6 | Raked margins match numerically; anything larger means unreachable cells or non-convergence |
| `familywise_alpha` | 0.01 | Record shares are judged against binomial sampling noise with a Bonferroni-adjusted z over the table's cells |
| `min_group_records_for_noise_test` | 30 | Below this, the normal approximation is unreliable; reported as "not assessed", not as passed |

Each table also carries plain-language **notes** (shown under the table on the Validation page): a margin not imposed
in that province and why; cells that received no record at this size (population redistributed within the parent group;
root table: merged into the nearest age band); and, when the source universe differs from the root population
(education), the size of the difference per sex and the fact that the source is scaled to the root population per sex,
so the table checks shares within sex rather than the source's absolute counts. The national table status is
`partially_calibrated` when a margin was imposed in some provinces only, and its notes name those provinces. The
summary counts margins not imposed (Validation tile, dashboard pipeline status). With a per-province floor, a national
note says record shares are not expected to follow the source.

Also: constraint results, and cross-source checks (Ankara: the age × sex total equals the separate workbook's total,
female and male populations exactly). **Source-fit validation does not show that AI responses resemble human
behaviour.** Held-out tables and behavioural validation are not implemented.

Cross-source checks per province also compare the root table with the package's own published totals (T30 total
population and the T16 sex totals); all 327 agree for the national builds below.

Real-data result, all 81 provinces, seed 42, generator 1.1 (`pop-TR-2025-n100000-s42-99ece554` and
`pop-TR-2025-n10000-s42-8751f71f`):

| | 100,000 records | 10,000 records |
|---|---|---|
| Represented population | 86,092,168 = the sum of the 81 provincial ADNKS 2025 totals | same |
| Constraint violations | 0 | 0 |
| Margins not imposed | 5 of 243: marital status in Bilecik (no convergence, 267 records) and Muş (weights outside ×0.05–×20); education in Tunceli and Bayburt (outside the range) and Ardahan (no convergence) | 145 of 243 in 65 provinces (education 62, marital 45, settlement 38): small provinces get about 10–100 records |
| Root table | 31 provinces with collapsed cells (44 cells), so their weighted age × sex cells differ from TÜİK; national max error 0.009 pp | 80 provinces with collapsed cells; national max error 0.13 pp |
| National weighted status and max error (education / marital / settlement) | partially calibrated 0.065 pp / partially calibrated 0.047 pp / exact | all partially calibrated: 0.77 / 0.47 / 0.25 pp |
| National record shares | within sampling noise for all four tables (max \|z\| 1.86, 1.22, 0.18, 0.92; thresholds 3.48, 3.23, 3.65, 3.02) | within sampling noise |
| Province tables fit exactly (weighted) | age × sex 50, marital 71, education 19, settlement 81 of 81 | age × sex 1, marital 17, education 1, settlement 43 |
| Province tables outside record sampling noise | 5 of 324 (about 3 expected at α = 0.01 per table) | 3; 145 not assessed (fewer than 30 records) |
| Weights | CV 0.15, Kish deff 1.02 | CV 0.28, deff 1.08 |

At province level the weighted fit is exact (`fit_by_construction`) wherever the margin was imposed and every cell
received a record. The other province tables have cells with no record at that size (e.g. doctorate or "unknown"
education in smaller provinces; all 59 remaining education gaps at 100K are of this kind), whose population is
redistributed within sex and reported, or a margin that was not imposed. Ankara reproduces TÜİK 2025 exactly in all four tables (e.g.
633,169 never-married women, 33,210 widowed men). Tables whose universe differs from the root (education) are compared
after scaling to the root's 15+ population per sex, as in calibration; the scales are in the report (Ankara education:
×1.0210 male, ×1.0231 female). For province-level analysis of small provinces use a per-province floor; with a floor, national record shares are not
expected to follow the source (the validation report says so) and the weighted counts are the national check.

## 10. Environment, cohorts and personas

- **Environment** (`GET /api/v2/environments/{code}`): every context indicator for the province by domain (demographics,
  economy, education, households, housing, health, migration, mobility, urbanization, wellbeing, culture, environment,
  justice), the value at or before the reference year with its own published period (`source_period`; `source_year` is
  null for multi-year periods) and status, a note when the province's series ends early, the history, official
  projections in a separate list, the generator tables available, and the datasets that do not cover the province.
  Experiment prompts quote the indicator with its period, never a projection.
- **Cohorts**: a definition (population + filters on province, age range, adults only, sex, marital status, education,
  labour, household, settlement type) is stored separately from samples. Samples are seeded and deduplicated by
  configuration: `simple_random`, `weighted` (systematic PPS on a seeded order, certainty units for large weights) or
  `stratified` (proportional allocation by weighted population). Each member keeps its inclusion probability and
  analysis weight (population weight ÷ inclusion probability).
- **Personas** ([`personas.py`](../src/societytwin/national/personas.py), template `tr-persona-card-1`): every
  attribute with value, evidence, source year and status (`visible`, `hidden` with a reason, `unavailable`,
  `not_applicable`). Default model-visible fields: province, age group, sex, marital status and any available education,
  labour, household and settlement fields, plus the reference year. Single-year age is hidden by default (assumed).
  Sex is visible and "Hiç evlenmedi" maps to "Never married"; both were missing in the historical adapter.
  Limitations are for researchers, not part of the prompt. The MatrAIx export uses custom `dst_*` dimensions and adds a
  catalog dimension only where the meaning is identical (never "Single" for never married, never gender identity for
  administrative sex).

## 11. Experiments and execution

Definition parts: **scenario** (title, description, parameters, `hypothetical` true unless a source note is given),
**task** (instruction, 2–12 controlled options, optional free text for `other`, rationale, adult-only), **environment**
(a context province or each persona's own province, selected indicators), **cohort** (cohort, sample size, method,
seed), **model** (backend, transport, model, temperature, seed, max output tokens), **execution** (repetitions, attempts,
call cap, optional cost cap), **persona** policy (visible fields).

`POST /experiments/{id}/plan` draws the sample, builds every persona and prompt, and returns eligible records, the
represented population, active personas, minors, planned and maximum calls, the call cap, provider calls expected, a
characters ÷ 4 input-token estimate, a cost estimate (only with a configured price table, otherwise unknown), warnings
(missing fields, inferred attributes, stub/placeholder backends) and blockers. Running needs the plan hash, an
idempotency key and `confirm: true`; a plan executes once.

Backends:

- **stub**: deterministic placeholder choices from a hash of the prompt; offline; labelled as a pipeline test
  everywhere, never as results.
- **matraix**: MatrAIx's PersonaJsonSurvey under the external runtime interpreter, one trial per persona, with a
  generated SocietyTwin task (context = environment + scenario; one single-choice question). Transport `fake` uses
  MatrAIx's zero-cost smoke client (schema-valid placeholders, identical for everyone). Transport `live` needs
  `SOCIETYTWIN_ENABLE_LIVE_EXECUTION`, a provider key in the API environment and the runtime; SDK retries are disabled.
  Prompts are captured at the transport boundary. MatrAIx runs are queued for the local worker.
- **replay**: serves cached responses of an earlier run for identical prompts; exact reproduction without calls.

Budget guard: every attempted call counts, retries included; the run stops at the call cap (and at the cost cap when a
price table makes cost known). Invalid structured output (not JSON, choice not an option id) is never guessed; it is
recorded as `invalid_output` and retried only if attempts remain.

## 12. Results and reproducibility

Every attempt is stored (`national_responses`) and the final attempt per persona and repetition is flagged. Aggregates
weight each valid response by analysis weight ÷ repetitions, report the Kish effective n and approximate 95% Wilson
intervals (persona sampling only), suppress groups below a minimum number of personas (default 10), and phrase
differences only as "within this synthetic experiment, group A selected X more often than group B" when intervals do
not overlap.

Each run writes `manifest.json` and `responses.jsonl` under the state directory: code commit (uncommitted changes are
not detected), population ID, content hash, seed and generator version, cohort definition, sample configuration and
member hash, persona and prompt template versions, the experiment definition and its hash, model configuration,
backend, controls fingerprint and sources, reference and source years, and a summary. Populations carry their own
manifest (config, scope, allocation, calibration, weights, profiles, dependency model, constraint rules, sources,
content and file checksums). Same seed, controls and size reproduce the same population ID and content.

## 13. API (`/api/v2`)

`GET overview`, `capabilities`, `geography/provinces`, `environments/{code}`, `controls`, `data-sources`;
`POST controls/build`; `GET|POST populations`; `GET populations/{id}`, `/summary`, `/records`, `/records/{sid}`,
`/validation`; `POST cohorts/preview`; `GET|POST cohorts`; `GET cohorts/{id}`; `POST cohorts/{id}/samples`;
`GET samples/{id}`, `/personas`; `GET examples/fare-experiment`; `GET|POST experiments`; `GET experiments/{id}`;
`POST experiments/{id}/plan`, `/runs`; `GET runs`, `runs/{id}`, `/responses`, `/aggregate`; `POST runs/{id}/replay`.
Filters are query parameters (`province_codes`, `age_min`, `age_max`, `sexes`, `marital_statuses`, `adult_only`, …);
records are paged server-side (≤ 200). Mutations are accepted from loopback clients only. `/api/v1` is unchanged and
serves the historical Ankara workbench under `/historical` in the UI.

## 14. Tests and performance

`tests/national/` (artificial three-province package in `tests/fixtures/artificial_tuik_package/`, invented values):
geography and codes, ingestion and missing values, store integrity, generator size, determinism, coverage, weights,
universes, structural zeros, collapsing, floors, validation, constraint detection, cohort filters and designs, persona
mapping, experiment schema, structured-output parsing, budget guard, retries, failures, cache and replay, and the API
flow. `tests/national/test_tuik_package_format.py` writes a tiny artificial package in the team package's exact layout
and covers its metadata columns, wide-file verification, multi-year periods, projections, blanks, totals and label
checks. `tests/regression/test_national_ankara_extracts.py` checks the real Ankara controls are reproduced exactly and
the historical files are untouched. `tests/regression/test_national_tuik_package.py` (marker `tuik_package`, skipped
without the package) asserts the package findings of §3.2, the 81-province control tables and checks, the
environment's periods and projections, and a 20,000-record national build (about 11 s).
`tests/integration/test_matraix_national.py` runs arbitrary personas through MatrAIx (opt-in). Frontend: Vitest
component tests and Playwright (`frontend/e2e/national.spec.ts`).

`build-controls` on the real package takes about 7 s (431,071 rows, 33 wide files compared) and writes a 53 MB
`context.csv`; reading the store takes about 1 s. Generating all 81 provinces (seed 42): 10,000 records 2.9 s,
100,000 records 1.2 s (the smaller build is slower because raking trials fail in provinces with about 10 records),
validation 0.15 s and 0.4 s, Parquet about 124 KB and 710 KB, peak memory about 0.5 GB.

Earlier benchmark (one province, before the package was added):

| Records | Generate | Validate | Write | Filter + 3 distributions | PPS sample of 100 | Parquet |
|---|---|---|---|---|---|---|
| 10,000 | 0.03 s | 0.02 s | 0.006 s | 0.001 s | 0.002 s | 45 KB |
| 100,000 | 0.28 s | 0.21 s | 0.04 s | 0.004 s | 0.02 s | 268 KB |
| 1,000,000 (optional) | 2.8 s | 2.1 s | 0.3 s | 0.03 s | 0.24 s | 1.7 MB |

Peak memory at 1M was about 1.2 GB (generation holds Python lists). A 1,000,000-record national build has not been
benchmarked.

## 15. Limitations and claims to avoid

- Person attributes from official tables: age group, sex, marital status, education and settlement type. Labour status,
  household size and household type stay null (no person-level province table); socioeconomic status, income,
  employment status and district are not modelled.
- Marital status and education are published by sex only: their relationship with age is inferred by IPF (education
  under minimum-completion-age zeros), not observed; single-year age is assumed uniform within bands; 90+ is top-coded.
  No joint relationship between marital status, education and settlement type beyond age and sex is observed.
- The education table's universe is smaller than the ADNKS 15+ population (likely excluding most foreign nationals;
  an inference); its distribution is applied to the whole 15+ population, scaled per sex, which assumes the residents
  outside that universe have the same education distribution within age and sex. Marital totals match ADNKS exactly
  only from 2021.
- Small provinces cannot carry every margin at small sizes: 5 of 243 province margins are not imposed at 100K and 145
  at 10K; their weighted counts follow the drawn records only. Each is reported (manifest, provenance, validation).
  Rare categories (doctorate, "unknown" education) receive no record in many provinces, so those province tables are
  not exact even when calibrated. Use `--min-per-province` (and weighted national figures) for province analysis.
- Context indicators are province-level: the newest well-being data is from 2015, prison data from 2020, housing
  characteristics from the 2021 census; each shows its own period. Air traffic (51), agricultural wages (35) and opera
  and ballet (6) do not cover every province.
- The package documentation overstates its row and indicator counts (§3.2); the data is what is used.
- Regional tables (e.g. HLFS at NUTS-2) would be applied unchanged to every province in the region.
- Reuse terms for TÜİK portal tables are an OPEN DECISION. The package records URLs and dates per dataset; the
  historical Ankara extracts do not.
- No model has been called: stub and MatrAIx fake-transport runs test the pipeline only.

SocietyTwin is a synthetic population calibrated to official aggregate statistics, made of fictional synthetic
residents, used for controlled persona-conditioned AI experiments and population-level exploratory simulation. It does
not simulate every person in Türkiye, does not reconstruct citizens, and does not predict what Turkish citizens will
do. Demographic fit (source-fit validation) does not establish behavioural realism, and MatrAIx does not validate
Turkish society; behavioural validation remains a separate research question.
