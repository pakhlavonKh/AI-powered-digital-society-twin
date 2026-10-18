# SocietyTwin Research Workbench

> **Status:** working local release. The main pages serve the **national pipeline** (`/api/v2`); see
> [national-pipeline.md](national-pipeline.md) for what it implements. This document covers setup and configuration of
> the whole workbench, and the **historical Ankara workbench** (`/api/v1`), which the UI keeps under **Historical**
> (`/historical/...`). Live provider execution is implemented but **disabled by default** and has not been exercised
> against a provider.

The historical workbench is a web UI and API over the Ankara proof-of-concept in
[`experiments/matraix_simulation/`](../experiments/matraix_simulation/), with the workflow
**Overview → Population Explorer → Cohorts → Persona Explorer → New Experiment → Results → Validation / Data Sources**
under `/historical`.

Everything it shows is computed from the actual fixture files and recorded run folders. It never calls a model to
create population records or to fill persona fields, and it keeps population records, personas and active LLM agents
separate, as in [persona-schema.md](persona-schema.md).

## What works and what is gated (historical workbench)

| Area | Status | Notes |
|---|---|---|
| Builds | Works offline | The base and v2 CSVs are two versions of the same 1,000 residents with separate content-derived IDs; v2 is the default. A changed file gets a new ID; the old ID stays registered as "source changed". |
| Population Explorer | Works offline | Server-side filters (exact ID, age band, administrative sex, marital status in v2 only), deterministic sort and paging, backend distributions. |
| Cohorts | Works offline | Filter → preview count → seeded simple random sample without replacement → saved manifest with the exact realized IDs. Stratified sampling is disabled. |
| Persona Explorer | Works offline | A read-only source card for every resident; stored persona YAMLs with model-visible fields, metadata-only fields, unassigned fields and provenance digest checks. |
| Persona materialization | Needs runtime | Runs the existing adapter in a subprocess into managed state. It never overwrites a fixture. |
| New Experiment | Drafts work offline | Scenario, task and environment are separate. Unsupported drafts are saved with exact blockers. |
| A/B preflight | Needs runtime | Runs the existing A/B runner in prepare-only mode: zero provider calls, immutable reviewed plan. |
| Fake smoke run | Needs runtime | Runs the real survey agent once with the deterministic fake transport through a durable local job. Zero provider calls. |
| Live two-persona A/B | **Disabled by default** | Exactly the existing runner with `--execute` (two calls, zero retries), behind an explicit start, idempotency key and fresh output directory. Tested only with a fake runtime. |
| Results | Works offline | Imported run folders and managed runs; side-by-side answers, usage marked as estimated, recorded prompts, consistency checks, artifacts, events, CSV/JSON export. |
| Validation / Data Sources | Works offline | Integrity checks and source-table fit (marginal shares, joint age × sex TVD, marital-within-sex TVD). No thresholds or scores. |
| Cohort execution, scenario execution, new environments, cache replay, stratified sampling, national generation | Not in `/api/v1` | Implemented in the national pipeline (`/api/v2`). In v1 they stay unavailable; `POST /api/v1/experiments/{id}/reproduce` returns 501. |
| Held-out or behavioural validation | Not implemented | Neither API implements it. |

## Quick start

Prerequisites: Python 3.12, Node.js 22 or later. Commands run from the repository root.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-api.lock
.venv/bin/pip install -e . --no-deps
(cd frontend && npm ci)
PYTHONPATH=src .venv/bin/python -m societytwin.national build-controls    # optional: the UI offers the same buttons
PYTHONPATH=src .venv/bin/python -m societytwin.national generate --size 10000 --seed 42
./scripts/dev.sh            # API on 127.0.0.1:8000, UI on http://127.0.0.1:3000
```

Windows commands are in [national-pipeline.md](national-pipeline.md#2-quick-start).

If the workbench is already running, the script prints its address and exits instead of starting a second copy.
Otherwise it takes the first free port from 8000 for the API and from 3000 for the UI, and prints the address. Ports set
with `SOCIETYTWIN_API_PORT` or `SOCIETYTWIN_WEB_PORT` must be free. It never stops other processes. Next.js allows only
one dev server per project, so stop a running copy before starting another.

On macOS, Python may skip the editable install's `.pth` file because `.venv` carries the hidden flag. The scripts and
pytest set `PYTHONPATH=src`, so this does not matter for them.

Historical results appear when run folders exist under `experiments/matraix_simulation/runs/` (git-ignored). This
checkout does not contain them; copy them from the archive that holds run3, or point `SOCIETYTWIN_IMPORT_RUNS_DIR`
at a folder that does. They are read, never modified.

### Optional: the MatrAIx runtime

Preflight, smoke and materialization run the existing experiment scripts in a separate interpreter that has MatrAIx
installed. It must not be the API's environment.

```bash
python3.12 -m venv ../matraix-runtime
../matraix-runtime/bin/pip install -r experiments/matraix_simulation/requirements.txt \
  -e ../MatrAIx-Persona-8B -e ../MatrAIx-Persona-8B/packages/playground
export MATRAIX_ROOT=../MatrAIx-Persona-8B
export SOCIETYTWIN_RUNTIME_PYTHON=../matraix-runtime/bin/python
```

Then use **Check runtime** (`POST /api/v1/runtime/probe`) or start a preflight. The child processes get a minimal
environment, run with `python -I -B`, write only into fresh managed directories, and have HTTP proxies pointed at a
closed local port unless live mode is used.

### Live execution (not enabled here)

Live mode needs `SOCIETYTWIN_ENABLE_LIVE_EXECUTION=1`, the provider key in the **API server's** environment, a reviewed
preflight for the two-persona fixture, and an explicit start with a confirmation. One plan can create at most one job.
If the worker stops mid-run the job becomes `unknown_after_interruption` and is never retried. Review the runner code
and the provider's terms before enabling it; it has not been run against a provider in this release.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SOCIETYTWIN_EXPERIMENT_ROOT` | `experiments/matraix_simulation` | Fixture folder (a `layout.json` there may rename files; used by the test fixture) |
| `SOCIETYTWIN_IMPORT_RUNS_DIR` | `<experiment root>/runs` | Read-only historical run folders |
| `SOCIETYTWIN_STATE_DIR` | `data/results/societytwin_local` | SQLite registry, managed outputs, materialized personas and logs (git-ignored) |
| `SOCIETYTWIN_DATA_MANIFEST` | `data/manifest.yaml` | Root dataset manifest |
| `MATRAIX_ROOT` | sibling `../MatrAIx-Persona-8B` | External MatrAIx checkout |
| `SOCIETYTWIN_RUNTIME_PYTHON` | unset | Interpreter with MatrAIx installed |
| `SOCIETYTWIN_ENABLE_LIVE_EXECUTION` | off | Allows the live A/B mode |
| `SOCIETYTWIN_LOCAL_MUTATIONS` | on | POST endpoints, accepted from loopback clients only |
| `SOCIETYTWIN_FRONTEND_ORIGINS` | `http://127.0.0.1:3000,http://localhost:3000` | CORS allowlist |
| `SOCIETYTWIN_API_ORIGIN` (frontend) | `http://127.0.0.1:8000` | Where Next forwards `/api/v1` and `/api/v2`; server-side only, set at build time for `next build` |
| `SOCIETYTWIN_TUIK_PACKAGE` | `data/raw/tuik_package` | Long-format TÜİK package (national pipeline) |
| `SOCIETYTWIN_TUIK_MAPPING` | `data/tuik_package_mapping.yaml` | Rules mapping package indicators to control tables |
| `SOCIETYTWIN_CONTROLS_DIR` | `data/processed/national` | Built control store |
| `SOCIETYTWIN_POPULATIONS_DIR` | `data/populations` | Generated populations |
| `SOCIETYTWIN_MAX_AGENTS` | `200` | Maximum active personas per national run |
| `SOCIETYTWIN_MODEL_PRICES` | unset | Optional YAML price table (`models: {provider/model: {input_per_mtok, output_per_mtok, source, as_of}}`); without it cost is unknown |

This is a local development service. It has no authentication and must not be exposed beyond the machine.

## Architecture

```text
frontend/ (Next.js, TypeScript, Recharts)  ── /api/v1 rewrite ──►  src/societytwin/api (FastAPI)
                                                                        │
            ┌──────────────┬──────────────┬─────────────┬───────────────┼──────────────┬───────────────┐
       population/     sampling/      evaluation/     persona/     experiments/     registry/       agents/
   readers, builds   filters, SRS    source fit,    source cards,  imported runs,  SQLite, jobs,  subprocess adapter
                                     integrity      YAML views     drafts, plans   migrations     to MatrAIx runners
```

- Population, sampling and evaluation import neither web frameworks nor model SDKs. Only `agents` starts the
  external runtime, and never in-process: the experiment scripts mutate `sys.path` and import a package named
  `src`, which would collide with the repository's own `src`.
- Mapping rules and fixed IDs are read from the adapter and runner sources with `ast` (no import), so the workbench
  does not duplicate persona mapping.
- The typed client in `frontend/src/lib/api/schema.d.ts` is generated from `frontend/openapi.json` by
  `scripts/export_openapi.sh`; a backend test fails when they drift.
- The CSV repository sits behind a small interface for a later DuckDB/Parquet store; the SQLite registry uses
  ordered migrations and portable SQL for the proposed PostgreSQL path. Neither migration has happened.

## Evidence rules the UI follows

- **Run states come from files, not folder names.** `completed` needs a completed comparison and a saved result for
  every planned trial. A trial with `request_started` and no response is `outcome unknown`: not failed, not running.
  `preflight.status = prepared` is kept as a raw status even in completed runs.
- **Comparisons are recomputed** from the trial results and checked against `comparison.json`.
- **Unknown stays unknown.** Null tokens and costs are shown as unknown, never zero. Recorded costs are estimates from
  the framework's price table; no billed amount is recorded.
- **Labels only from snapshots.** Answer labels come from the questionnaire snapshot saved in each trial folder;
  otherwise the raw code is shown.
- **No host paths.** Absolute paths embedded in historical artifacts are never followed or shown; files are served by
  server-owned artifact IDs with containment and symlink checks.
- **Reports are descriptive.** The run3 Markdown/PDF reports are offered with a caveat: their date is a file
  modification time and their free-tier statement is not established by usage data. JSON is the numerical authority.
- **No scores.** Source-fit metrics carry no threshold; the docs set none.

## Reconciliation notes (archive versus `main`)

The brief was written against `AI-powered-digital-society-twin-matraix-simulation.zip`
(SHA-256 `d711a8eb…ccffed37`). This branch starts from `origin/main` at `760e79f`, which is newer for documentation.

| Finding | Handling |
|---|---|
| The archive has `src/reporting/build_persona_report.py`; `main` does not | Not ported. The UI reads JSON directly and serves existing report files. |
| The archive's `run_matraix_ab.py` adds lossless JSON-boolean coercion; `main`'s runner lacks it | Not changed. Recorded coercions are displayed from `model_boundary.json`. A live run from `main`'s runner would reject boolean answers instead of coercing them. |
| Run folders exist only in the archive (git-ignored) | Imported read-only; byte-identical to the zip. |
| `EXPERIMENT_RESULTS.md` describes a completed gpt-4o run in `runs/matraix_ab_live` | The archive's folder of that name holds only an Anthropic `request_started` boundary. The UI shows the local evidence only. |
| Persona fixtures record CSV digests that match only the CRLF form of today's files | Shown as "line-ending drift", not byte identity. Historical YAML is unchanged; materializing again creates a new artifact with new digests. |
| The v1 migration plan says to remove `experiments/` once empty | Not applied: the folder is a populated working experiment. |

## Tests

```bash
.venv/bin/python -m pytest                       # backend: artificial fixtures + local Ankara/run3 regression
.venv/bin/python -m pytest -m "not local_fixture and not matraix"   # what CI runs
SOCIETYTWIN_TEST_MATRAIX_ROOT=... SOCIETYTWIN_TEST_RUNTIME_PYTHON=... .venv/bin/python -m pytest tests/integration
(cd frontend && npx tsc --noEmit && npx vitest run)
./scripts/e2e.sh                                 # production build + Playwright (historical + national) on artificial fixtures
./scripts/check_bundle.sh                        # after a build: no server configuration in the client bundle
```

- CI fixtures in `tests/fixtures/artificial_experiment/` are invented (TESTLAND, 2099, `TST2099_*`) and regenerated by
  `tests/fixtures/build_artificial_fixtures.py`. The national tests use `tests/fixtures/artificial_tuik_package/`
  (real plate codes, invented values), regenerated by `tests/fixtures/build_artificial_tuik_package.py`.
- Every pytest test blocks non-loopback sockets and strips provider keys. The integration suite passes no keys to its
  subprocesses and asserts afterwards that the experiment folder is byte-identical.
- `tests/regression/` re-runs the experiment's own seed-42 sampling in an isolated process and compares the rows.

## Known limitations and risks

- Two recorded trials cannot support population percentages, causal effects, significance tests or confidence
  intervals; the UI says so wherever answers appear.
- The supplied population is one province, sampled at random (no IPF or controlled rounding), with marital status
  conditioned on sex only.
- Raw TÜİK files, URLs, download dates, licences and raw checksums are not in the checkout, so raw-source verification
  is unavailable.
- The MatrAIx checkout used for verification had no git metadata; its persona catalog matched the fixtures' recorded
  catalog digest, but its revision could not be compared with the README's tested revision.
- One worker per state directory. On macOS and Linux an advisory lock stops a second API process from running or
  recovering jobs; on Windows that lock is unavailable and only one API process should use a state directory.
- Live execution is untested against a provider.

## Remaining work

- Decide whether to port the archive's boolean-coercion runner change and report script into `main`.
- Add the team's TÜİK package and its mapping rules (national pipeline, see national-pipeline.md).
- Held-out validation tables, persona-adherence experiments and agreed thresholds.
- Authentication and a non-local deployment, if the workbench is ever shared.
