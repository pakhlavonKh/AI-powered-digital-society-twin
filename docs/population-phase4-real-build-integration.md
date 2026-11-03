# Phase 4: real-build reconciliation

Date: 2026-11-02. Phase 4 implementation and local checkpoint. No push, merge,
rebase, reset, source download, production regeneration or provider call was performed.

## Repository safety and interface comparison

- Worktree: `C:\Users\Lenovo\Desktop\Digital-Society-Twin-Population\data\results\main-evaluation-20261020\.population-hybrid-households`.
- Branch: `feature/population-hybrid-households`.
- HEAD: `6164bda3e0a225763ad32607e373db03fed9945a` (the supplied audited commit).
- Initial `git status --short`: empty. All existing Phase 1–3 files were clean.
- `git fetch origin` succeeded after escalation because shared Git metadata lives
  outside this worktree. Latest inspected `origin/main`:
  `f45b279e04b754736ba129dedf2e8488e879244c`.
- `git merge-base HEAD origin/main` equals that main commit: main is already an
  ancestor of this branch. The suspected newer Scenario Engine divergence is
  absent in the fetched references.
- Interface comparison with main: the only `src/societytwin` differences before
  this work were branch additions `households/membership.py`,
  `households/reconciliation.py`, `national/matraix_projection.py` and the
  projection integration in `national/personas.py`. National generation/store,
  build workflow and Scenario Engine interfaces otherwise match main.
- Existing worktrees, teammate branches and untracked files were preserved.

## Exact implementation

`households.reconciliation.reconcile_population(population, households)` accepts
`GeneratedPopulation` and `LoadedPopulation`, including populations written by
the unified build workflow. Generated objects supply their existing columns;
loaded Arrow tables supply only weight, province and reference-year columns via
`to_pydict()`, without rounding, filtering or rescaling. HouseholdStore and
TypeSizeStore already load the household representation accepted by `reconcile`.
Unsupported resident object types raise TypeError.

Example for a unified build directory (use its existing artifact IDs):

```python
from societytwin.national.store import PopulationStore
from societytwin.households.store import HouseholdStore
from societytwin.households.reconciliation import reconcile_population

population = PopulationStore(build_dir / 'residents').load(resident_id)
households = HouseholdStore(build_dir / 'households').load(household_id)
diagnostic = reconcile_population(population, households)
```

For type-size builds use TypeSizeStore instead. No workflow mutation, automatic
publication gate, new endpoint, membership creation or sidecar persistence was
introduced. Diagnostic provenance now also retains resident and household
`content_sha256`; existing source references, controls fingerprint and household
identity fingerprint remain detached copies. Artifact validators remain
responsible for checksum verification.

## Metadata and source evidence

The national manifest records covered provinces, record reference year,
represented population, source versions and root profile provenance. Root
`profiles[*].fields.province_code` records `geo_level`, `geo_code`, `source_year`
and `source_ids`; source observation year is distinct from requested reference
year. A mismatch remains incompatible, with no temporal transfer inferred.
`weights.definition` explicitly defines population_weight as represented persons.
Household manifests explicitly declare `weight_unit=household`, while their size
source declares unit, universe, province, reference year, version and checksum.
Type-size manifests bind the size source through `identity.size_source`.

Controls TableMeta contains `unit`, `universe_min_age` and `universe_note`.
The generic default `universe_note='All residents'`, age eligibility, table names,
source IDs and aggregate totals do not establish authoritative institutional
inclusion/exclusion. No reviewed available source field establishes a private
resident universe or an evidenced institutional subtraction for actual generated
manifests. Therefore this change deliberately adds no guessed population_universe
to generated manifests. Missing evidence remains unknown in provenance (`None`)
and yields `population_universe=not_assessable`, with no comparable private total.

Existing explicit evidence remains usable through
`population_universe.definition` and nonempty `source_ref`; all-resident evidence
also needs `institutional_population` for the same scope/year. This is a caller
evidence contract, not an independent source authentication service. Positive
tests use explicitly invented private-universe evidence, never an assertion that
official TÜİK data has that universe.

The TÜİK bot owner must supply authoritative publication/table/methodology
references explicitly defining institutional inclusion, statistical unit,
geography, observation year and any institutional count. Preserve original source
bytes/checksums and attach a reviewed machine-readable evidence binding to root
sources. Do not substitute a broad title, default note or inferred residual for
that evidence. No raw TÜİK data or institutional count was edited or invented.

## Open household sizes

Existing arithmetic is retained: sum household_weight × size_lower. Closed sizes
produce an exact aggregate; any 10+ record leaves the exact total unknown. A
comparable person total strictly below the bound is incompatible, outside the
existing `rel_tol=1e-10`, `abs_tol=1e-6`. At or above the bound the result remains
not_assessable without an upper bound or exact membership evidence. Matching a
lower bound alone never proves compatibility. Missing universe evidence also
prevents a private-member comparison. Incompatible findings take precedence over
missing evidence in the overall diagnostic.

## Native Windows projection repair

Verified with CPython 3.12.10 on native Windows, against local upstream checkout
`C:\Users\Lenovo\Desktop\MatrAIx-Persona-8B`, commit
`3633d8dab149a9482a71b024418a49ae828cc941`.

Parent `subprocess.run(encoding='utf-8')` controls only parent pipe handling.
Child `-I` ignores PYTHONUTF8, so setting that variable alone cannot fix this.
After explicit child stream configuration, reproduction exposed upstream
`load_persona` using Path.read_text() with cp1254, failing on UTF-8 bytes with
UnicodeDecodeError. Child `-X utf8` fixes default file decoding too. The probe
now explicitly configures all three standard streams; its allowlisted environment
also declares PYTHONUTF8=1. `-I -B`, credential exclusion, socket denial and
temporary YAML writes are preserved. Upstream files were not changed.

The initial interpreter lacked Jinja2. An ignored workspace-only
`data/results/phase4-runtime` venv was created without downloads; a .pth references
the existing population environment's installed dependencies, and local Jinja2
and MarkupSafe packages were copied from the existing sibling venv. No shared
environment was modified. The regression verifies real Turkish Unicode through
isolated child stdin/stdout and default file reading, UTF-8 mode and removal of
host PYTHONPATH/provider credentials.

## Validation

PowerShell commands (run from the worktree):

```powershell
$env:SOCIETYTWIN_TEST_PROJECTION_ROOT='C:\Users\Lenovo\Desktop\MatrAIx-Persona-8B'
$env:SOCIETYTWIN_TEST_PROJECTION_PYTHON=(Join-Path (Get-Location) 'data/results/phase4-runtime/Scripts/python.exe')
& $env:SOCIETYTWIN_TEST_PROJECTION_PYTHON -m pytest tests/households/test_reconciliation.py tests/integration/test_matraix_projection_contract.py -q
& $env:SOCIETYTWIN_TEST_PROJECTION_PYTHON -m pytest -q
& 'data/results/phase4-runtime/Scripts/python.exe' -m pytest tests/national tests/households tests/build tests/enrichment -q
git diff --check
```

Focused result: **77 passed**, including the configured actual upstream schema,
loader and intended-template test on Windows. One existing marker warning.
Regression coverage includes generated/stored residents and households,
universe evidence absence and explicit fixture evidence, person/household units,
exact sizes, open-tail lower bounds/tolerance, observation years, unchanged full
resident columns/weights, retained content fingerprints and deterministic output.

An earlier full run with the existing `.venv-persona` Python, without upstream
configuration, completed: **524 passed, 14 skipped, 6 failed**. Failures were
Windows symlink privilege (two), fixture digest expectations (`match` versus
`line_ending_equivalent`, two), historical completed-run consistency (one), and
a locale-dependent changed-persona fixture write/read (one). These tests do not
exercise the changed reconciliation or projection probe.

Final configured full run: **525 passed, 13 skipped, 6 failed**, with the same
six failures; actual Windows upstream projection now executes and passes.
The additional ordered subsystem invocation completed **384 passed, 2 skipped,
17 failed**. All 17 failures are existing build-workflow tests: their configured
temporary `bundles` output is rejected by the workflow guard requiring output
under repository `data/results`. The checkpoint investigation below corrects the
initial interpretation of this difference as order sensitivity. No output guard
was weakened. The broad suite is not fully green.
`git diff --check` passes (Git reports only its usual LF/CRLF conversion notices).
Test-created untracked `src/societytwin/build/__pycache__/` and
`tests/build/__pycache__/` were initially preserved after automatic approval
review rejected cleanup. The user subsequently authorized removal of those two
directories; the checkpoint verified and removed only those directories.

## Phase 4 checkpoint

Branch/worktree/HEAD were reverified against the identifiers above. Reviewed the
complete source/test diff and this entire previously untracked document. The
only staged files for the checkpoint are:

- `src/societytwin/households/reconciliation.py`
- `tests/households/test_reconciliation.py`
- `tests/integration/test_matraix_projection_contract.py`
- `docs/population-phase4-real-build-integration.md`

No generator, store, build workflow, core manifest, sampling, fixture linker,
Scenario Engine, frontend, upstream runtime or separate validation code changed.
The two cache directories resolved inside the exact authorized worktree, were
ordinary directories without reparse points (including child entries), contained
only `.cpython-312[...].pyc` files with CPython 3.12 magic bytes, and had no tracked
files. Four cache files were removed in total. No other directory was cleaned.
Subsequent tests used `-B` and `PYTHONDONTWRITEBYTECODE=1` to avoid recreating them.

### Base-commit failure comparison

Created an isolated tracked-source archive with `git archive --format=zip
6164bda3e0a225763ad32607e373db03fed9945a`, safely extracted into the new ignored
`data/results/phase4-checkpoint-base` directory. This is not another Git worktree;
no existing branch/worktree was changed. The archive contains the base source
and tracked fixtures, without any Phase 4 edits. The same runtime interpreter
was used in separate processes with each source root as the working directory.
Tracebacks confirm imports from each respective source tree.

Exact checkpoint commands (PowerShell, starting at the feature worktree):

```powershell
$checkpointRoot = (Get-Location).Path
$checkpointPython = Join-Path $checkpointRoot 'data/results/phase4-runtime/Scripts/python.exe'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:SOCIETYTWIN_TEST_PROJECTION_ROOT='C:\Users\Lenovo\Desktop\MatrAIx-Persona-8B'
$env:SOCIETYTWIN_TEST_PROJECTION_PYTHON=$checkpointPython
& $checkpointPython -B -m pytest tests/households/test_reconciliation.py tests/integration/test_matraix_projection_contract.py -q -p no:cacheprovider
$failureSelection = @(
  'tests/api/test_security.py::test_symlink_escape_never_listed',
  'tests/regression/test_supplied_fixtures.py::test_persona_digests_are_line_ending_equivalent',
  'tests/unit/test_historical_runs.py::test_completed_ab_run',
  'tests/unit/test_historical_runs.py::test_symlinks_and_unsafe_paths_are_ignored',
  'tests/unit/test_persona_views.py::test_fixture_persona_provenance',
  'tests/unit/test_persona_views.py::test_changed_source_row_is_flagged',
  'tests/build'
)
& $checkpointPython -B -m pytest @failureSelection -q --tb=no -p no:cacheprovider
Push-Location (Join-Path $checkpointRoot 'data/results/phase4-checkpoint-base')
try {
  & $checkpointPython -B -m pytest @failureSelection -q --tb=short -p no:cacheprovider
  & $checkpointPython -B -m pytest tests/integration/test_matraix_projection_contract.py::test_actual_upstream_schema_loading_and_intended_templates -q --tb=short -p no:cacheprovider
} finally { Pop-Location }
& $checkpointPython -B -m pytest --collect-only -q -p no:cacheprovider
git diff --check
```

Results:

- Focused Phase 4 rerun: **77 passed** (native Windows upstream test included).
- Base failure selection: **23 failed, 18 passed**.
- Current failure selection: **23 failed, 18 passed**, same failing test IDs.
- All six originally reported full-suite failures reproduce at base with the
  same errors/assertions. All 17 build failures reproduce at base with the same
  output-directory guard errors (including downstream expected-error mismatches).
  These are confirmed pre-existing in this Windows environment.
- Base native upstream test: **1 failed**, dimension equality assertion after
  child decoding; the same configured test passes with Phase 4. The earlier
  partial-fix reproduction also exposed cp1254 default file decoding upstream.
- Default collection: **544 tests**; zero `tests/build` cases. Pytest's default
  `norecursedirs` includes `build`. Explicit directory selection collects the
  build tests. Thus the prior apparent order sensitivity is a discovery gap,
  not demonstrated order-dependent behavior. Default full-suite results must
  not be presented as build-workflow validation.
- `git diff --check`: passed. No new blocking regression identified. Checkpoint
  verdict: **PASS for Phase 4**, with the pre-existing failures and discovery
  limitation above; the repository-wide suite is not green.

### Environment and reproducibility limits

Native Windows CPython 3.12.10; pytest 8.4.2, pyarrow 25.0.1, pydantic 2.12.5,
FastAPI 0.135.3, Starlette 1.8.0, httpx 0.28.1, PyYAML 6.0.3. Unknown marker and
Starlette/httpx deprecation warnings remain. The runtime venv has
`include-system-site-packages=false`, but its explicit `.pth` points to the
existing `.venv-persona/Lib/site-packages`. Jinja2 and MarkupSafe were copied from
the sibling venv without their distribution metadata. Consequently this is a
machine-specific, non-hermetic verification environment, not a lockfile-built
runtime; dependency metadata alone cannot fully reconstruct its contents.
Changes or removal of the referenced environment could change these results.
The isolated subprocess still loads its own configured interpreter's installed
packages; `-I` does not remove installed `.pth` configuration. Tests establish
Windows behavior in this environment, not universal runtime compatibility.

The base archive is a tracked-source snapshot, not a bit-identical copy of all
ignored local data or platform checkout conversions. Same failure IDs and
messages reproduced nonetheless. The ignored runtime and base archive are left
intact and excluded from the checkpoint commit. A future independent verification
should use a fully pinned environment with Jinja2/MarkupSafe recorded and select
`tests/build` explicitly; no environment or discovery-policy change is included
in this Phase 4 checkpoint.

## Output impact, restrictions and Phase 5

Core generated records, IDs, weights, sampling, manifest schemas and content
fingerprints are unchanged. The diagnostic has two additive provenance fields
and a new object adapter. Existing low-level reconcile calls remain valid.
The fixture linker and its unit-weight restriction are unchanged; aggregate
compatibility does not authorize representative household membership or roles.
Sidecar persistence and PersonaResolver integration remain outside this phase.

Recommended Phase 5 interfaces: a versioned reviewed source-universe evidence
binding with scope/year/source checksum; explicit unknown evidence status;
separate institutional count provenance; optional bounded tail evidence; and an
explicit read-only build-diagnostic entry point after artifact validation.
Retain the aggregate gate separately from any future eligibility/linkage design.
