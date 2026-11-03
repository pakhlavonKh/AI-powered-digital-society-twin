# Phase 5: fixture membership persistence and persona boundaries

Implemented 2026-11-02 on `feature/population-hybrid-households` in
`C:\Users\Lenovo\Desktop\Digital-Society-Twin-Population\data\results\main-evaluation-20261020\.population-hybrid-households`.
Initial working tree was clean; HEAD and the live GitHub feature-branch hash were
both `b6817aed4e5effc47abb493c20c707002a80cf1f`. Local tracking agreed. Existing
teammate worktrees were inspected without changes. During implementation no commit, push, merge,
dependency installation, provider call or production regeneration was performed.

## Files and architecture

- `households/membership_store.py`: dedicated fixture relationship persistence,
  strict loading, deterministic replay and explicit population inspection.
- `households/membership.py`: documentation points to the dedicated store; no
  linker code, constants, seed behavior, assignment or artifact identity changed.
- `national/sidecar_persona_contracts.py`: immutable reviewed attribute contracts.
- `national/persona_selection.py`: attribute-specific rendering and approval
  checks, selection revalidation, explicit fixture-relationship rejection.
- `tests/households/test_membership_store.py`: persistence/security/integrity and
  population/persona boundary tests using invented unit fixtures.
- `tests/national/test_persona_selection.py`: additional approval and rendering
  tests, including independent MatrAIx rejection of an unregistered field.
- This report.

Membership is not categorical demographic enrichment. ExtensionStore validates
registry-driven conditional category assignments and source denominators; making
it accept household identifiers would weaken those contracts. The dedicated
MembershipStore reuses the existing immutable ResidentExtension/ExtensionRecord
shapes as a transport, but never calls the categorical enrichment validator or
treats a household ID as a demographic category. No ExtensionStore, enrichment
engine/registry, core generator/store/manifest, household generation, weighting,
sampling, Scenario Engine, frontend or teammate Validation Engine code changed.

## Versioned fixture relationship contract

For compatibility, the existing linker still emits `ext-<64 hex>` artifact IDs.
Dedicated storage uses `membership-<same 64 hex>/` so its namespace is distinct
from demographic extensions. Each immutable directory contains:

| File | Meaning |
| --- | --- |
| `manifest.json` | Exact envelope keys: `store_version`, `artifact_id`, `files` |
| `membership.json` | Exact payload keys: original `records` and original `manifest` |
| `validation.json` | Existing fixture validator's replay report |

The envelope version is `fixture-membership-store-1`; file SHA-256 values bind
both payload and validation bytes. The payload retains the existing membership
contract `household-membership-1`, model `fixture_capacity_shuffle_v1`, extension
schema version, seed/config, RNG stream version, resident population ID and
records hash, household build ID and records hash, full input fingerprints,
reconciliation hash, readiness result, provenance profiles, eligibility contract,
synthetic resident and household IDs, purpose and modeling limitations.

JSON is UTF-8, sorted, finite-only, timestamp-free and deterministic. Loads use
strict record parsing and reject duplicate object keys and nonfinite constants.
The original records/manifests and their hashes are never rewritten. Repeated
writes validate an existing artifact and reuse it without rewriting its files;
different content or a corrupt existing artifact is rejected. Publication stages
inside the output root and renames the complete directory into place.

The legacy limitation “Production weighted linkage and persistence remain
disabled” is preserved byte-for-byte for fixture artifact identity compatibility.
Phase 5 adds persistence only for explicitly authorized unit fixtures, not for
production weighted relationships.

## Explicit integration

Use the exact original input snapshot and independently supplied eligibility
contract. Stored assertions do not authorize their own use:

```python
from societytwin.households.membership import link_fixture
from societytwin.households.membership_store import MembershipStore
from societytwin.households.reconciliation import reconcile

# columns/manifest/households must describe invented, explicitly marked fixtures.
assessment = reconcile(columns, manifest, households)
membership = link_fixture(
    columns, manifest, households, reconciliation=assessment,
    contract=fixture_contract, enable_fixture_linking=True,
)
store = MembershipStore(relationship_output_root)
path = store.write(
    membership, columns, manifest, households,
    reconciliation=assessment, contract=fixture_contract,
    input_directories=(original_resident_directory, original_household_directory),
)
loaded = store.load(
    membership.manifest['artifact_id'], columns, manifest, households,
    reconciliation=assessment, contract=fixture_contract,
    input_directories=(original_resident_directory, original_household_directory),
)
```

For in-memory fixtures without input directories, omit `input_directories`.
For inspection alongside a GeneratedPopulation or LoadedPopulation:

```python
loaded = store.load_for_population(
    membership.manifest['artifact_id'], original_population, households,
    contract=fixture_contract,
)
# Inspect loaded.records and loaded.manifest; nothing is attached to a persona.
```

The object adapter recomputes reconciliation, converts the full loaded Arrow
table without rounding, and protects a LoadedPopulation's directory. Household
objects have no directory property; callers needing explicit household-directory
overlap protection must pass that directory to the low-level write/load methods.
Artifact marker checks additionally block storage under existing resident,
household, demographic extension and unified-build directories.

Fingerprinting includes the complete original manifests. PopulationStore adds
file and operational metadata when persisting: therefore bind the fixture
contract **after** loading its final input snapshot if that snapshot will be used
later. A contract bound before persistence is intentionally rejected against a
changed loaded manifest. No fingerprint normalization silently bridges snapshots.

## PersonaResolver

Reviewed metadata is in `APPROVED_SIDECAR_ATTRIBUTES`, a read-only mapping of
frozen SidecarPersonaContract objects. A contract specifies its own label,
display limitation, categories, assignment method, evidence class and assumption.
The only production-approved entry remains `degurba_class`. Its text, status
handling, missingness behavior, evidence, card format and selected projection
remain unchanged. The previous SUPPORTED and LIMITATION exports are preserved.

The resolver validates the selection again, validates the demographic sidecar
with existing code, and checks selected attributes against their approved
contracts. Adding an attribute to an enrichment registry does not approve its
persona exposure. Future approved categorical attributes can add their own
contract without being labeled DEGURBA. Other kinds of sidecar, including
relationships, do not go through this renderer. Household IDs, family roles and
arbitrary attributes remain unsupported selection fields. Passing fixture
membership as the resolver's demographic extension raises EnrichmentError even
when only a core field was selected. There is no membership resolver argument,
automatic lookup, production persona attachment, endpoint or frontend change.

MatrAIx's crosswalk is unchanged. Persona exposure approval and projection
approval remain independent: a test-only additional persona contract renders its
own label, but its MatrAIx projection fails as unregistered. No real additional
demographic field is approved by that test.

## Security and integrity

- Full existing fixture readiness/reconciliation/replay validation runs on every
  write and load, with an explicit caller contract. Unit person/design/household
  weights, complete eligibility, exact capacities and fixture purpose remain
  mandatory; production weights and open-ended households are not linked.
- Duplicate/missing/blank/foreign residents, foreign households, cross-build
  identities, changed records/weights/source metadata, malformed records,
  unsupported versions, altered provenance/seed, and checksum corruption fail.
- Recomputed transport checksums cannot bypass deterministic semantic replay.
  Saved validation must match fresh validation, not merely have a valid hash.
- Only fixed filenames and strict artifact identifiers are used. Traversal,
  symlinks, Windows junctions and linked path components are rejected before
  resolution. Output roots may not overlap explicitly supplied input roots.
  Unexpected files in an existing membership directory cause rejection and are
  preserved. No existing artifact is overwritten or repaired automatically.
- File hashes detect corruption, not authorship. Caller contracts must come from
  trusted fixture preparation; these checks do not authenticate official sources.
- The implementation checks paths before access/publication; it does not claim
  protection against a hostile concurrent process swapping filesystem components
  between checks. Run against trusted local input/output directories.

Tests include byte-for-byte preservation of an original PopulationStore artifact,
its source fingerprints, full columns and weights across membership write/load.
Link/junction rejection tests inject path predicates to work without Windows
symlink privileges; genuine OS-level hostile link races are not tested.

## Tests and environment

Native Windows CPython 3.12.10, using the existing ignored workspace runtime
`data/results/phase4-runtime/Scripts/python.exe`; pytest 8.4.2, pyarrow 25.0.1,
pydantic 2.12.5, FastAPI 0.135.3, Starlette 1.8.0, httpx 0.28.1, PyYAML 6.0.3.
No dependency was added. As documented in Phase 4, this runtime uses an explicit
`.pth` referencing the existing `.venv-persona` packages and locally copied
Jinja2/MarkupSafe; it is machine-specific and not hermetically reconstructed from
a lockfile. Base and changed code used the same interpreter in separate processes.

Exact commands from the feature worktree (PowerShell):

```powershell
$phase5Root = (Get-Location).Path
$phase5Python = Join-Path $phase5Root 'data/results/phase4-runtime/Scripts/python.exe'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:SOCIETYTWIN_TEST_PROJECTION_ROOT='C:\Users\Lenovo\Desktop\MatrAIx-Persona-8B'
$env:SOCIETYTWIN_TEST_PROJECTION_PYTHON=$phase5Python
& $phase5Python -B -m pytest tests/households/test_membership_store.py tests/households/test_membership.py tests/households/test_reconciliation.py tests/national/test_persona_selection.py tests/integration/test_matraix_projection_contract.py -q --tb=short -p no:cacheprovider
& $phase5Python -B -m pytest tests/national tests/households tests/enrichment tests/build -q --tb=short -p no:cacheprovider
Push-Location (Join-Path $phase5Root 'data/results/phase5-base')
try {
  & $phase5Python -B -m pytest tests/build -q --tb=short -p no:cacheprovider
} finally { Pop-Location }
git diff --check
```

Results:

- Final focused suite: **195 passed, 2 skipped**. Includes real upstream native
  Windows projection against the same local MatrAIx checkout used in Phase 4.
  Skips are optional pre-existing disposable real-data sidecar exports, absent
  locally. Existing marker and Starlette/httpx warnings remain.
- Relevant regressions with build tests explicitly selected: **430 passed,
  2 skipped, 17 failed**. This run preceded five added path/integrity test cases;
  all five passed in the final focused suite. Failures are exclusively the known
  build output guard issue, not membership or resolver failures.
- Base-commit explicit build run: **18 passed, 17 failed**, with exactly the same
  failing test IDs and guard errors. Baseline source was safely extracted from
  `git archive --format=zip b6817aed4e5effc47abb493c20c707002a80cf1f` into the new
  ignored `data/results/phase5-base` directory. Main and teammate worktrees were
  not changed. Build fixtures choose temporary `bundles` paths outside repository
  `data/results`, which the unchanged workflow guard rejects. No guard was weakened.
- `git diff --check`: passed. No new blocking regression identified.
- A final compatibility-export type adjustment was followed by the targeted
  relationship-selection and additional-contract tests: **5 passed**. Command:
  `& $phase5Python -B -m pytest tests/national/test_persona_selection.py::test_relationship_and_unapproved_selection_rejected tests/national/test_persona_selection.py::test_attribute_specific_approved_contract_and_independent_projection_gate -q --tb=short -p no:cacheprovider`.

The default full suite was not repeated in this phase: its six historical
Windows/fixture failures were reproduced at baseline during the Phase 4 checkpoint
and lie outside changed code. Those six are not newly reclassified by this run.
Build tests must continue to be selected explicitly because default pytest
discovery excludes directories named `build`.

Ignored regression logs are in `data/results/phase5-regression.txt` and
`data/results/phase5-base-build.txt`. The runtime, archive and logs are left intact;
only source/tests/documentation are intended for publication. During implementation
no staging, commit, push or merge was performed; the user subsequently authorized
the publication checkpoint below.

## Publication checkpoint review

Reviewed the complete tracked diff and all four untracked files before staging.
Verified the exact feature worktree, Phase 4 HEAD and tracking branch; configured
Git identity is `ovgubejan <taburoglubejan@gmail.com>`. Only the seven listed
Phase 5 source/test/documentation files are included. No generated data, runtime,
logs, dependency additions, credentials, source observations, core manifests or
unrelated files are intended for the commit.

The persistence review confirmed fixed filenames, strict artifact IDs, link and
junction checks, separate input/output roots, complete cross-build fingerprint
bindings, file checksums and deterministic semantic replay with explicit caller
eligibility. The fixture-only and unit-weight gates are unchanged. The documented
trusted-directory/concurrent-filesystem limitation remains; this is not a hostile
filesystem sandbox. Persona review confirmed separate demographic approval and
projection approval, unchanged DEGURBA wording and default behavior, and explicit
rejection of fixture relationships. A direct comparison with the Phase 4 resolver
returned identical complete persona dictionaries for assigned and missing DEGURBA
on male and female invented unit fixtures.

Re-ran the exact focused and relevant regression commands above using the same
native Windows Python 3.12 environment:

- Focused: **195 passed, 2 skipped** (real upstream Windows projection included).
- Relevant population/household/enrichment regressions with `tests/build`
  explicitly selected: **435 passed, 2 skipped, 17 failed**.
- Phase 4 archive explicit `tests/build` rerun: **18 passed, 17 failed**.
- Compared the failed test IDs programmatically: all 17 match exactly. Baseline
  build config/workflow, build tests and persona resolver files were checked
  against `git show b6817ae:<path>` after CRLF/LF normalization (the archive has
  Windows line endings). The failures are the unchanged
  output-root guard problem, not new regressions. No unrelated failure was fixed.
- `git diff --check` passed; the exact staged file set is reviewed before commit.

Review verdict: **PASS for Phase 5 publication**, subject to the known baseline
failures and environment limits already documented. Publication is authorized
only for `feature/population-hybrid-households`, using a normal fast-forward
push after fetching origin. No main/teammate merge, force-push, Phase 6 or graph
implementation is part of this checkpoint. Publication commit identity and remote
hash verification are reported in the accompanying checkpoint response.

Checkpoint regression logs (ignored):
`data/results/phase5-publish-regression.txt` and
`data/results/phase5-publish-base-build.txt`.

## Validation Engine handoff and remaining limits

The teammate can use `validate_membership` (existing narrow replay validator),
`MembershipStore.load`/`load_for_population`, and the original
`input_fingerprints` function. Reports retain contract version, valid flag,
record/household counts, purpose and `production_linking_enabled=False`.
The storage envelope adds its own version and file hashes without modifying the
input manifests. Consumers should retain the caller's eligibility contract,
resident/household snapshots, reconciliation and provenance, and distinguish
fixture readiness from official demographic validity. This does not replace or
extend the teammate's broader Validation Engine.

Representative household linking still needs authoritative private-resident and
institutional-universe evidence, suitable record/household weight semantics,
compatible exact/bounded capacity evidence, and an independently reviewed linking
method. No roles, family relationships, production linking or graph sampling are
implemented. Optional graph enrichment would require its own typed contract,
evidence and provenance, opt-in controls, integrity validation and separate
persona/projection approvals before any agent exposure.
