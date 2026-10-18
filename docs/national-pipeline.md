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
| Standard control store; Ankara TÜİK extracts adapter; long-format package reader with mapping rules | **Implemented** (the package itself is not in this checkout; see §3) |
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
| Real data for 80 of 81 provinces | **Not available**: the team's TÜİK package is not in this checkout |
| Education, labour, household, settlement-type attributes on real data | **Not available** (code paths exist and are tested on artificial data; no real table loaded) |
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

**What this checkout contains.** The only official statistics present are the TÜİK-derived Ankara extracts that ship
with the historical MatrAIx experiment ([`experiments/matraix_simulation/processed/`](../experiments/matraix_simulation/processed/)):
2025 population by five-year age group × sex, 2025 marital status × sex (ages 15+), and 2023–2025 totals, density and
median ages. They are read, never modified, and recorded in [`data/manifest.yaml`](../data/manifest.yaml). The marital
table's universe was verified arithmetically: for each sex its total equals the 15+ population of the age × sex table.

**What is missing.** The team reports a long-format package of 33 province-level datasets, 577 indicators and 411,132
rows (`province_code, province_name, nuts3_code, year, indicator, value, unit` plus `data_catalog.csv`,
`variable_metadata.csv`, `coverage_report.csv`, `not_province_level.csv`). It is not in this repository, the archive or
any branch. Consequently 80 provinces have no source data, and the UI says so.

**Adding the package.** Copy it to `data/raw/tuik_package/` (git-ignored), then:

1. `build-controls` loads every package indicator as **province context** (environment), grouped by catalog theme, with
   its own year and missing-value status. Province identity is the code; names are only checked; NUTS-3 mismatches,
   invalid codes, unparseable values and conflicting duplicates are rejected and listed.
2. To make an indicator a **generator control table**, add a rule to
   [`data/tuik_package_mapping.yaml`](../data/tuik_package_mapping.yaml): table, dataset, a regex with named groups
   (`sex`, `age_group`, `category`) and the table's universe (minimum age). Labels map to codes through
   [`vocab.py`](../src/societytwin/national/vocab.py); an unknown label is an error, never a dropped value.
3. Rebuild the controls and generate. Provinces with the root table (age group × sex) become part of the national
   population automatically; no province needs its own code.

**Standard control tables** ([`controls.py`](../src/societytwin/national/controls.py)): `population_age_sex` (root),
`marital_status_age_sex`, `marital_status_sex`, `education_age_sex`, `education_sex`, `labour_status_age_sex`,
`labour_status_sex`, `household_size_persons`, `household_type_persons`, `urbanicity_sex`, `urbanicity`. Each cell
has `geo_level` (province, nuts2, nuts1, country), year, value and **value status**.

**Missing values are never zero.** `OBSERVED` (a published number, 0 included), `NOT_REPORTED` (row present, no number:
`-`, `..`, empty), `UNKNOWN`, `NOT_APPLICABLE`, `STRUCTURALLY_UNAVAILABLE` (the dataset does not cover the province,
e.g. 51/81 for air traffic). Coverage is shown as k/81 on Data Sources and in the environment.

## 4. Reference-year strategy

The population reference year defaults to **2025**. For every table and province the generator uses the latest year
**not after** the reference year; later years (e.g. projections) are never used, and nothing is interpolated or
carried forward silently. Each field's source year is stored in the provenance profile and shown next to the
population reference year (Population Explorer, persona detail, run manifest). A source year that differs from the
reference year adds an explicit limitation.

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
                 ├─► education     same options; IPF seeded with structural zeros from the constraint engine
                 ├─► labour        same options; regional (NUTS-2/1) tables applied to each province and flagged
                 └─► household size / type, settlement type   province (×sex) table → MARGINAL_INFERENCE
```

Why IPF: when only `sex × category` is published, the two-way IPF of the root's age-group margin and the category
margin, per sex, is the maximum-entropy joint consistent with both. Without structural zeros it reduces exactly to
conditioning on sex alone, which is what the Ankara data supports. With structural zeros (education) it moves mass
away from impossible combinations while still matching both margins. It is not used where a joint table exists.

**Not supported by the loaded data (and therefore not claimed):** province × age × sex × marital status (only
province × sex × marital exists for Ankara); any relationship between education, labour status and household; district
geography; income or socioeconomic status at person level.

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
   redistributed within the same parent group.

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

Also: constraint results, and cross-source checks (Ankara: the age × sex total equals the separate workbook's total,
female and male populations exactly). **Source-fit validation does not show that AI responses resemble human
behaviour.** Held-out tables and behavioural validation are not implemented.

Real-data result (Ankara, 10K and 100K, seed 42): weighted age × sex and marital × sex reproduce TÜİK exactly (e.g.
633,169 never-married women, 33,210 widowed men); record shares within sampling noise (max |z| 2.26 at 10K, threshold
3.23); 0 constraint violations; cross-source totals agree.

## 10. Environment, cohorts and personas

- **Environment** (`GET /api/v2/environments/{code}`): every context indicator for the province by domain, the value at
  or before the reference year with its own year and status, the history, the generator tables available, and the
  datasets that do not cover the province.
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
flow. `tests/regression/test_national_ankara_extracts.py` checks the real Ankara controls are reproduced exactly and
the historical files are untouched. `tests/integration/test_matraix_national.py` runs arbitrary personas through
MatrAIx (opt-in). Frontend: Vitest component tests and Playwright (`frontend/e2e/national.spec.ts`).

Benchmark on this machine (Apple silicon, Python 3.12, one province, `benchmark` command):

| Records | Generate | Validate | Write | Filter + 3 distributions | PPS sample of 100 | Parquet |
|---|---|---|---|---|---|---|
| 10,000 | 0.03 s | 0.02 s | 0.006 s | 0.001 s | 0.002 s | 45 KB |
| 100,000 | 0.28 s | 0.21 s | 0.04 s | 0.004 s | 0.02 s | 268 KB |
| 1,000,000 (optional) | 2.8 s | 2.1 s | 0.3 s | 0.03 s | 0.24 s | 1.7 MB |

Peak memory at 1M was about 1.2 GB (generation holds Python lists). With 81 provinces, per-province IPF and raking add
overhead not measured here, because only one province has data.

## 15. Limitations and claims to avoid

- One real province. The national code path is exercised on artificial data only.
- Marital status is conditioned on sex only (age relationship assumed independent within sex); single-year age is
  assumed uniform within bands; the 90+ band is top-coded.
- Regional tables (e.g. HLFS at NUTS-2) would be applied unchanged to every province in the region.
- Raw TÜİK files, URLs, publication and retrieval dates are not recorded for the Ankara extracts; reuse terms are an
  OPEN DECISION.
- No model has been called: stub and MatrAIx fake-transport runs test the pipeline only.

SocietyTwin is a synthetic population calibrated to official aggregate statistics, made of fictional synthetic
residents, used for controlled persona-conditioned AI experiments and population-level exploratory simulation. It does
not simulate every person in Türkiye, does not reconstruct citizens, and does not predict what Turkish citizens will
do. Demographic fit (source-fit validation) does not establish behavioural realism, and MatrAIx does not validate
Turkish society; behavioural validation remains a separate research question.
