# University Simulation UI & Results Explorer

> **Status:** working frontend on **fixture data**. No university registry, candidate or placement API exists yet
> (`frontend/openapi.json` has no such paths), so every page runs against a deterministic synthetic fixture behind a
> data-source adapter. The API adapter is a placeholder that reports *pending backend integration*; it never guesses an
> endpoint. Fixture results come from an **illustrative fixture allocation**, not from a placement engine.

Owner: Sam (frontend). Registry schema and candidate handoff: Bejan (`feature/university-sqlite`). Placement engine,
eligibility and allocation rules: Pakhlavon (per `docs/candidate-population.md` on that branch).

## 1. Routes and modules

| Route | Module | What it shows |
|---|---|---|
| `/university` | — | Redirects to `/university/programs`. |
| `/university/programs` | University & Program Explorer | Registry rows (program × admission year): filters, search, sort, pagination, program details, data quality. |
| `/university/candidates` | Synthetic Candidate Explorer | Synthetic applicants, ranked preferences, placement outcome from a selected run, cohort provenance and quality. |
| `/university/scenarios` | Scenario Setup | Presets A–E, validated configuration form, serialized request body, execution status. |
| `/university/results` | Placement Results | Summary metrics, six charts, unplaced candidates, run provenance and result validation. |
| `/university/compare` | Scenario Comparison | Compatibility gate, B − A differences, comparison charts, program and candidate-level changes. |

The sidebar group **University Simulation** links all five pages. On `/university/*` the top bar shows the registry
snapshot, the data origin (fixture/API) and the execution mode. Provenance, missing-data and validation panels appear
on every page that shows data.

URL state: `snapshot` (registry snapshot; absent = newest), and per page —
programs: `year` (absent = latest, `all`), `score`, `scholarship`, `university`, `type`, `lang` (repeatable), `q`,
`sort`, `dir`, `page`, `program`; candidates: `run` (absent = first run, `none`), `cohort`, `q`, `score`, `min`, `max`,
`status`, `sort`, `dir`, `page`, `candidate`; scenarios: `preset`; results: `run`; compare: `a`, `b`.

## 2. Architecture

```
app/university/*/page.tsx          pages: read URL state, gate on a snapshot, compose components
components/university/*            UI only (explorers, details, charts, panels); no data access logic
lib/university/
  types.ts                         normalized types (registry, candidates, provisional simulation contract)
  source.ts                        UniversityDataSource interface — the only thing components depend on
  context.tsx                      provider + hooks (useUniversitySource, useSelectedSnapshot, useCatalogue, useRuns, useRun)
  config.ts                        UNIVERSITY_DATA_SOURCE = "fixture" | "api"
  fixtureSource.ts                 fixture implementation of the interface
  apiSource.ts                     placeholder API implementation (every call → 501 pending_backend_integration)
  programs.ts, candidates.ts       pure query logic: filter, Turkish-aware search, deterministic sort, paging, URL state
  scenario.ts                      presets, validation, canonical serialization, fingerprint
  metrics.ts                       run summaries, integrity checks, compatibility, comparison
  quality.ts                       importer-issue pass-through and dashboard checks
  urlState.ts                      URL params as state without lag or lost updates
  fixtures/registry.ts             synthetic registry shaped like the SQLite schema
  fixtures/candidates.ts           synthetic cohort mirroring candidate-development-v1
  fixtures/allocator.ts            ILLUSTRATIVE fixture allocation (not the placement engine)
```

Reused from the existing workbench: `useApi` (keyed fetching, stale-while-loading, retry), `PageHeader`, `StatTile`,
`KeyValues`, `Badge`, `CopyId`, `ErrorState`/`Loading`/`EmptyState`/`UnavailableState`, `BarChartCard` and
`DivergingBars` (Recharts with table views; each gained one optional, backward-compatible prop: `valueAxisLabel`,
`rowHeight`), the `.explorer2`/`.filters2` explorer layout from the Population Explorer, and the CSS design tokens.
No new dependency was added.

## 3. Data contracts

### Registry (mirrors `src/societytwin/university/db.py`, schema v1)

`RegistrySnapshot`, `University`, `Program`, `AnnualAdmission`, `AnnualTuition` and `QualityIssue` copy the SQLite
columns. `null` means missing; observed zeros stay `0`. Program codes are text (leading zeros kept) and are the durable
identifier within a snapshot. Placed counts above quota are shown unchanged. Teaching language `null` means "not
specified in source", never Turkish. Filters offer only values present in the snapshot; the city filter is hidden because
the importer records no cities.

### Candidates (mirrors `src/societytwin/candidates/__init__.py`)

`Candidate` and `Preference` match the handoff (`candidate_id`, `age`, `score_type`, `achievement` proxy 0–10000,
null location/interests/budget; `program_id` = registry `program_code`, contiguous `position` from 1). "Cohort rank" is
derived in the UI from the proxy and labelled as such; it is not a YKS rank. Fields the contract lacks (eligibility
constraints, scholarship preferences, official scores) are shown as **Not in schema**.

Score-type labels are kept as written. For matching only, `SÖZ`/`SOZ` and `DİL`/`DIL` are folded together (the registry
uses Turkish letters, the generator ASCII). Registry labels outside SAY/EA/SOZ/DIL (e.g. `TYT`) are reported as
*unknown score type*. **This folding is a UI assumption that needs an agreed vocabulary.**

### Scenario configuration (PROVISIONAL — `university-scenario-ui-v1`)

```json
{
  "contract_version": "university-scenario-ui-v1",
  "name": "Scenario B — Quotas +20%",
  "preset": "quota_increase",
  "admission_year": 2025,
  "registry_snapshot_id": "sha256:…",
  "cohort": { "cohort_id": "…", "generator_version": "candidate-development-v1", "seed": 42, "size": 1000 },
  "seed": 7,
  "quota_adjustment_pct": 20,
  "program_quota_overrides": { "102210277": 40 },
  "included_university_keys": null
}
```

`serializeScenario` produces this with sorted keys; `scenarioFingerprint` hashes everything except `name` and `preset`
and is used to refuse duplicate runs. Validation (blocking errors vs warnings) is in `scenario.ts`; the fixture source
re-validates on submit (422 on blocking errors).

Supported: presets A (baseline), B (quota increase), C (quota decrease) and custom. **Not supported**, shown disabled
with the reason: D (scholarship availability — no mechanism; the registry stores scholarship labels only) and
E (preference change — no preference model).

### Results (PROVISIONAL)

A `SimulationRun` carries `status` (`pending | running | completed | failed`), `origin`, the `config`, `provenance`
(engine, engine version, seed, snapshot, cohort, config hash, created at), one `Assignment` per candidate
(`placed | unplaced | ineligible`, `program_code`, `preference_position`, optional `reason_code`/`reason`, optional
per-preference `evaluated` outcomes) and `capacities` per program (`base_quota`, `capacity`, `placed`).
All summaries are computed in `metrics.ts` from assignments, so a backend only has to return assignment-level output.

Formulas (shown on the pages):

- Placement rate (%) = placed ÷ eligible × 100, **eligible = placed + unplaced**; ineligible candidates are excluded and counted separately.
- Capacity utilization (%) = occupied seats ÷ available seats × 100, over programs with a **known** capacity.
- Placement rate difference = B − A, in **percentage points**; relative change = (B − A) ÷ A × 100, in **%** (always shown separately).
- Unplaced candidate difference = B unplaced − A unplaced.

Comparison is blocked for different registry snapshots, admission years, cohorts (generator or seed) or origins, and
for unfinished runs. Cohort size, seed, engine and institution differences are warnings; candidate-level changes are
matched by synthetic ID within one cohort.

## 4. Validation, provenance and missing data

- Missing values render as explicit states — *Missing from source*, *Not available*, *Not applicable*,
  *Not calculated*, *Pending backend integration*, *Not in schema* — never as 0.
- Importer issues (`placed_above_quota`, `invalid_annual`, `duplicate_program`, …) pass through unchanged with their
  sheet/row/raw value. Dashboard checks add: missing quota, missing/unknown score type, missing university identifier,
  duplicate program record, invalid preference reference, candidates with no (valid) preferences, placements exceeding
  capacity, unreconciled totals, missing simulation provenance, incompatible scenarios.
- Every finding is counted; groups can collapse but nothing is dropped. Blocking errors disable the related action
  (running a scenario, comparing runs); warnings stay visible.
- The reusable `DataQualityPanel` shows records loaded, incomplete records, warnings, errors, data source and version;
  `ProvenancePanel` lists snapshot, file hash, importer version, import/retrieval times, verification status, run ID,
  seed, engine and version.
- Unplaced reasons are shown only when the run supplies them; otherwise the cell says *Not available*.

## 5. Fixture conventions

- **Registry** `fixture:university-ui-v1`: 6 synthetic institutions ("Synthetic State University A", …), 76 programs,
  admission years 2022–2026, fee years 2025–2026. Codes are 9-digit strings with leading zeros (`001010101`).
  Deliberately incomplete records: institution F has no type; one program has no score type; vocational programs use
  `TYT`; one 2025 row (`002060101`) has a NULL quota; some 2026 ranks are NULL; one 2023 row is quarantined by an
  `invalid_annual` error; placed-above-quota rows carry warnings like the real importer.
- **Cohort** `fixture-cohort-s{seed}-n{size}` (default seed 42, size 1000): distributions of
  `candidate-development-v1`, but a mulberry32 PRNG — reproducible in the UI, **not byte-identical** to the Python
  generator. Candidate N depends only on seed and N. Preferences are artificial (popularity-weighted, without
  replacement); about 8% of draws ignore score type and a few reference the unknown code `009999901`.
- **Runs**: three built-in runs (A baseline, B +20%, C −30%; year 2025; seed 7) plus previews made in the browser
  session (configurations kept in `sessionStorage`; results recomputed deterministically).
- **Fixture allocation** (`fixtures/allocator.ts`): candidates in descending proxy order (seeded tie-break); each takes
  the first preference that exists, is included, matches score type, has a known capacity and a free seat. It exists
  only so fixture results are internally consistent. **It is not the SocietyTwin placement engine and not ÖSYM rules,
  and must not be wired up as one.**
- Every fixture object carries `origin: "fixture"`; pages show a fixture notice and badges.

## 6. Switching to real data

1. Agree endpoints with the API owner and add them to the FastAPI app; regenerate `frontend/openapi.json` and the
   typed client as usual.
2. Implement the methods of `UniversityDataSource` in `apiSource.ts` (map responses into `types.ts`; `queryPrograms`
   can call a server-side query or reuse `queryProgramRows` over `getCatalogue`).
3. Set `UNIVERSITY_DATA_SOURCE = "api"` in `lib/university/config.ts`. No component changes are needed.
4. Return `capabilities()` honestly: `execution.mode`, supported/unsupported presets, limits.

Tests can inject any source with `<UniversitySourceProvider source={…}>`.

## 7. Local development and tests

```bash
cd frontend && npm ci
npm run dev                     # http://127.0.0.1:3000/university (no API needed for these pages)
npx tsc --noEmit                # typecheck
npx vitest run                  # unit/component tests (src/test/university-*.test.ts[x])
cd .. && ./scripts/e2e.sh university narrow   # browser tests (needs the Python .venv; see research-workbench.md)
```

The root layout still asks the API for populations; without the API the console shows proxy errors, which do not
affect the university pages.

## 8. Known limitations

- All data is synthetic fixture data; nothing has been checked against the real workbook through the UI.
- The fixture allocation is illustrative; eligibility, ties, rounds and category quotas are not modelled.
- Fixture cohorts are not byte-identical to `python -m societytwin.candidates` output.
- Fixture previews live only in the browser session.
- Program search, filtering and paging run in the browser over the whole catalogue (fine for ~1,300 programs).
- Score-type folding (SÖZ/SOZ, DİL/DIL) is a UI assumption.

## 9. Backend dependencies still open

| Dependency | Needed for | Owner (per team docs) |
|---|---|---|
| Read-only registry API (snapshots, catalogue or paged programs, program detail, quality issues) | Program Explorer on real data | Pakhlavon (API) with Bejan (registry) |
| Candidate cohort API or file handoff, including **ranked preferences** | Candidate Explorer on real data | Bejan / open decision |
| Placement engine and scenario execution API (submit, status, assignment-level results, reasons) | Scenario execution, Results, Comparison | Pakhlavon |
| Agreed score-type vocabulary between registry and candidates | Matching and eligibility | Bejan / Pakhlavon |
| Acceptance or replacement of the provisional scenario and result contracts above | Removing the provisional labels | Pakhlavon, reviewed by Sam |
| Scholarship-availability and preference-change mechanisms | Presets D and E | Not assigned |
