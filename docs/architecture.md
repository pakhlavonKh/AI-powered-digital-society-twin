# Architecture Reference (v2)

> **Status:** Initial v2 architecture blueprint; core national pipeline (`src/societytwin/national/`), API (`/api/v1`, `/api/v2`), frontend workbench (`frontend/`), Scenario Engine (`src/scenarios/`), university SQLite/placement (`src/societytwin/university/`, `candidates/`), build/enrichment/households (`build/`, `enrichment/`, `households/`), and validation (`evidence/`, `validation/`) modules are implemented. See [docs/national-pipeline.md](national-pipeline.md), [docs/research-workbench.md](research-workbench.md), and [docs/scenario-engine.md](scenario-engine.md) for current implemented details.
>
> This is the **module and interface reference**. The reasoning behind each decision, the diagrams (system context, data flow, population generation, persona-to-agent activation, experiment lifecycle, deployment), and the MVP and roadmap are in the **[SocietyTwin v2 Architecture Report](societytwin-v2-architecture.md)**.
>
> The previous architecture (v1.0, a 5,000-agent demographic prototype comparing ABM, Cohort-Component / Matrix Projection, and ML models) is **SUPERSEDED** and archived in [archive/architecture-v1-demographic.md](archive/architecture-v1-demographic.md).

## 1. Layers

| Layer | Modules | Uses an LLM? |
|---|---|---|
| Data | `ingestion` | No |
| Population | `persona` (schema), `population`, `sampling` | No |
| Experiments | `scenarios`, `experiments`, `agents` | Only `agents` |
| Analysis | `evaluation`, `simulation` (optional) | No |
| Platform | `registry`, `api`, `frontend` | No |

**Dependency rule.** Population and analysis modules must not import web frameworks or LLM code, so that they can be tested and run on their own. Only `agents` talks to model providers. `api` contains no business logic: it validates requests and calls the other modules.

## 2. Target package layout

```text
src/societytwin/
├── ingestion/      data acquisition records, validation, harmonisation
├── persona/        schema definitions (versioned) and persona rendering
├── population/     dependency model, IPF fitting, generator, build writer
├── sampling/       cohort filters, sampling designs, weights
├── scenarios/      instruments and scenario conditions (versioned)
├── experiments/    experiment manager, environments (survey, scenario), trial orchestration
├── agents/         model adapters, prompt templates, activation, cache, budget
├── simulation/     optional population dynamics and Cohort-Component benchmark (STRETCH)
├── evaluation/     validation metrics, subgroup analysis, reports
├── registry/       manifests, jobs, provenance, persistence
└── api/            FastAPI application
frontend/           Next.js + TypeScript playground
configs/            schema YAML, instruments, experiment presets
tests/              unit, property, integration tests and small artificial fixtures
```

The current repository still has the research-phase placeholders under `src/`. They are **not** moved in this documentation change; see [migration-plan.md](migration-plan.md).

## 3. Module specifications

### `ingestion`
- **Purpose:** turn official downloads into validated, harmonised constraint tables.
- **Input:** files in `data/raw/`; entries in `data/manifest.yaml`.
- **Output:** harmonised marginals and cross-tabulations (Parquet) in `data/processed/`; an ingestion report.
- **Main responsibilities:** checksum and manifest checks; schema and value validation; geography mapping to İBBS codes; age-band, education, occupation, and sector harmonisation; reconciliation with ADNKS totals; marking held-out tables.
- **Dependencies:** pandas, PyArrow, Pydantic.
- **Testing:** artificial tables with known errors (missing cells, bad codes, inconsistent totals) must be reported; harmonisation mappings are round-trip tested.

### `persona`
- **Purpose:** define the versioned persona schema and construct personas from sampled records.
- **Input:** schema files in `configs/schema/`; population records.
- **Output:** schema objects (attributes, categories, parents, provenance, constraints); persona cards and unknowns statements.
- **Main responsibilities:** schema loading and validation; category encodings; hard-constraint definitions; template-based persona rendering; the synthetic-data label.
- **Dependencies:** Pydantic; a template engine.
- **Testing:** schema validation (acyclic DAG, known categories, valid constraints); rendering snapshots; no excluded attribute can appear in a card.

### `population`
- **Purpose:** generate population builds.
- **Input:** processed tables; schema version; build size N (configurable; benchmark scales 10K, 100K, 1M); seed.
- **Output:** a partitioned Parquet build and its build manifest.
- **Main responsibilities:** IPF fitting of conditionals; controlled-rounding allocation to province × sex × age cells; vectorised DAG-ordered sampling with masks; seeded streams per partition; writing builds.
- **Dependencies:** NumPy, pandas (small tables), PyArrow, `persona`, `registry`.
- **Testing:** IPF convergence on small tables; totals preserved; zero hard-constraint violations; same seed gives an identical checksum; independence from partition processing order (property-based tests).

### `sampling`
- **Purpose:** select reproducible cohorts from a build.
- **Input:** build ID; structured filter specification; sample size; sampling method; seed.
- **Output:** cohort manifest (requested and realised) with record IDs and inclusion weights.
- **Main responsibilities:** translate filters to DuckDB queries safely; simple random and stratified sampling; weight computation; realised subgroup counts.
- **Dependencies:** DuckDB, `registry`.
- **Testing:** same inputs give the same IDs; stratum sizes match the design; weights sum to the filtered population; invalid filters are rejected.

### `scenarios`
- **Purpose:** define versioned instruments and scenario conditions.
- **Input:** instrument files in `configs/instruments/`.
- **Output:** validated instrument objects with answer schemas; condition definitions (baseline and treatments).
- **Main responsibilities:** instrument validation; answer JSON schemas; random assignment of conditions with a seed; carrying the v1 demographic scenario parameters for the optional dynamics engine.
- **Dependencies:** Pydantic.
- **Testing:** instrument validation; condition assignment is balanced and reproducible.

### `experiments`
- **Purpose:** run experiments from configuration to results.
- **Input:** cohort; instrument and conditions; environment; model configuration; seeds; budget.
- **Output:** experiment manifest; trial records; lifecycle state.
- **Main responsibilities:** configuration validation and cost estimate; lifecycle (draft → validated → queued → running → completed / failed / stopped → analysed); SURVEY and SCENARIO environments (CHAT is STRETCH); trial orchestration through `agents`.
- **Dependencies:** `sampling`, `scenarios`, `agents`, `persona`, `registry`.
- **Testing:** end-to-end runs with the stub model; lifecycle transitions; budget stop; cancellation.

### `agents`
- **Purpose:** instantiate personas as AI agents for single trials.
- **Input:** persona card; instrument item and answer schema; prompt template version; model configuration.
- **Output:** a validated structured answer with usage information.
- **Main responsibilities:** provider-independent adapter interface; stub model; prompt templates (versioned); structured-output validation with bounded retries; asynchronous (and optionally batched) execution with concurrency limits; response cache; token and cost accounting; budget guard; recording model, version, temperature and other parameters, schema and template versions, and response metadata for every call ([report §14.1](societytwin-v2-architecture.md#141-metadata-recorded-for-every-ai-call)). Agents are used only for sampled personas; population records never reach this module.
- **Dependencies:** provider SDKs or HTTP client (behind the adapter), Pydantic, `registry`.
- **Testing:** stub model only in CI; cache-key determinism; retry and invalid-output handling; no credentials in logs.

### `simulation` (optional, STRETCH)
- **Purpose:** population dynamics over records (aging, births, deaths, migration) and the Cohort-Component / Matrix Projection benchmark carried over from v1.
- **Input:** a build; TÜİK vital statistics and life tables; scenario parameters.
- **Output:** time-shifted builds; aggregate time series in the Common Result Schema.
- **Main responsibilities:** vectorised yearly transitions; accounting identity checks; docking against the cohort-component benchmark.
- **Dependencies:** NumPy, SciPy (optional), `population`.
- **Testing:** accounting identity (final = initial + births − deaths + net migration); determinism with seeds.

### `evaluation`
- **Purpose:** validation and subgroup analysis.
- **Input:** builds; processed and held-out tables; trial records.
- **Output:** validation reports; Common Result Schema aggregates; performance and cost summaries.
- **Main responsibilities:** TVD, JSD, MAE, RMSE, SRMSE, Cramér's V difference, constraint violation rate, rare-cell recall; persona-consistency and experiment-validity metrics; weighted subgroup estimates with intervals ([validation-strategy.md](validation-strategy.md)).
- **Dependencies:** NumPy, SciPy, DuckDB.
- **Testing:** metrics against hand-computed examples; edge cases (zero cells, single category).

### `registry`
- **Purpose:** provenance and job state.
- **Input:** manifests and status updates from other modules.
- **Output:** persisted build, cohort, and experiment records; job queue.
- **Main responsibilities:** manifest storage; job table with safe concurrent claiming; trial index; experiment history.
- **Dependencies:** PostgreSQL (SQLite for local development and tests).
- **Testing:** transactions; concurrent job claiming; migrations.

### `api`
- **Purpose:** expose the platform to the frontend.
- **Input:** HTTP requests.
- **Output:** JSON responses; job submissions; exports.
- **Main responsibilities:** the endpoints in [report §21](societytwin-v2-architecture.md#21-api-architecture); request validation; roles (if enabled); synthetic-data labels in responses.
- **Dependencies:** FastAPI, all modules above.
- **Testing:** contract tests with the FastAPI test client.

### `frontend`
- **Purpose:** the Experiment Playground ([experiment-system.md §7](experiment-system.md#7-playground-pages-proposed)).
- **Input:** API responses.
- **Output:** pages for populations, cohorts, experiments, monitoring, results, and registry.
- **Main responsibilities:** display only; never computes statistics; shows the synthetic-data label on every page with persona output.
- **Dependencies:** Next.js, TypeScript, Recharts.
- **Testing:** Vitest component tests; typed API client.

## 4. Data contracts

| Contract | Defined in |
|---|---|
| Persona schema and provenance classes | [persona-schema.md](persona-schema.md) |
| Data manifest | [`data/manifest.yaml`](../data/manifest.yaml), [data-strategy.md](data-strategy.md) |
| Build, cohort, and experiment manifests | [report §20](societytwin-v2-architecture.md#20-reproducibility) |
| Trial record and Common Result Schema | [experiment-system.md §6](experiment-system.md#6-telemetry-and-result-model) |
| Validation report | [validation-strategy.md](validation-strategy.md) |
