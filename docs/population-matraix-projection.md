# DST to MatrAIx projection compatibility

2026-10-28. Branch `feature/population-hybrid-households`; HEAD
`f45b279e04b754736ba129dedf2e8488e879244c`. Worktree:
`C:/Users/Lenovo/Desktop/Digital-Society-Twin-Population/data/results/main-evaluation-20261020/.population-hybrid-households`.

## Safety review

All six Phase 1/2 additions existed, were untracked and were not ignored by Git.
There were no tracked modifications at the start. Reconciliation and fixture
membership were reviewed against their models, manifest contracts, weight
semantics and current tests. No critical continuation defect was found in their
supported contracts, and none of those six files was edited. Reconciliation is
an aggregate gate, not source authentication or membership approval. Membership
adds explicit fixture labels, unit weights, eligibility and fingerprint checks;
its sidecar method remains in-memory and unsupported by the production store.

The nested worktree resolves source-relative paths to its own checkout. It does
not inherit ignored data, installed editable-package locations or generated
artifacts from other checkouts. Long Windows paths can affect fixture outputs;
tests use unique short system temporary roots. No worktree was moved, branch
changed, unrelated file changed, or commit/push/merge performed.

## Implemented files and interfaces reused

- Modified `src/societytwin/national/personas.py`: existing
  `matraix_persona(persona, *, catalog=None)` now delegates to the versioned
  projection. Existing callers and the production runner continue to use it.
- Added `src/societytwin/national/matraix_projection.py`: 12 reviewed mapping
  rules, selected-view contract checks and optional native-enum validation.
- Added `tests/integration/test_matraix_projection_contract.py`: local contract,
  relocation and actual upstream loading/rendering tests.
- Added this report, `docs/population-matraix-projection.md`.

Reused `build_persona`, `PersonaResolver`, `FieldSelection`, existing display
vocabularies, persona metadata/visibility conventions, and `canonical_hash`.
Inspected `cohorts.py` and `agents/matraix_runtime.py`; neither was changed.
The runner already serializes `matraix_persona` output as Unicode YAML.
No resident, population manifest, sampling rule, generator or core ID was changed.

## Versioned crosswalk

Crosswalk version: `dst-matraix-projection-1`. Reviewed upstream schema: `1.0`,
1,290 dimensions, commit `3633d8dab149a9482a71b024418a49ae828cc941`.
Classifications describe native-catalog mapping; every selected custom value
retains the existing DST display verbatim. No lossy transformation is approved
or implemented. The full catalog is not copied into DST.

| DST field/value | Custom dimension | Native candidate | Classification / behavior |
| --- | --- | --- | --- |
| province_name | dst_residence_province | none reviewed | Unsupported; retain province as custom |
| age_group | dst_age_group | age_bracket | Lossy; five-year bands cross upstream boundaries; no rebucketing |
| age | dst_age | age_bracket | Lossy; no rebucketing or extra precision; hidden unless explicitly selected |
| sex | dst_sex | gender_identity | Unsupported; administrative sex is not self-identified gender |
| marital_status: married/divorced/widowed | dst_marital_status | demo_marital_status | Exact; additionally emit Married/Divorced/Widowed |
| marital_status: never_married/other | dst_marital_status | demo_marital_status | Unsupported; never map to Single or infer current relationships |
| education_level | dst_education_level | highest_education | Lossy/ambiguous; preserve Turkish attainment categories without global conversion |
| labour_status | dst_labour_status | demo_employment_status | Lossy/ambiguous; no hours, retirement, student or occupation inference |
| household_size_class | dst_household_size_class | lstyle_household_size | Lossy; no coarsening or exact size for 10+ |
| household_type | dst_household_type | none reviewed | Unsupported; preserve only an already available, selected value |
| urbanicity | dst_urbanicity | none reviewed | Unsupported; administrative settlement type is not DEGURBA |
| reference_year | dst_reference_year | none reviewed | Custom context, only if selected |
| degurba_class | dst_degurba_class | none reviewed | Custom selected sidecar display, retaining its existing limitation |

The legal-marital aliases are the only emitted native catalog dimensions. Even
apparently similar education/employment labels are not automatically converted.
Future lossy transformations require explicit approval, a versioned method,
provenance and tests; this API supplies no transformation-enabling shortcut.

## Projection and visibility contract

Only registered crosswalk fields in `persona.model_visible` can be exposed.
Each must agree with its attribute availability and display. Explicit
`FieldSelection` allowlist/required/optional controls and the declared visible
field set are checked. Hidden, unavailable and not-applicable fields remain
omitted; unknown source categories remain literal custom values. No MatrAIx
default fills missing demographics. Published unknown values create no exact
native alias. Arbitrary `dst_*` names, weights, calibration data, provenance
references and unreviewed attributes fail rather than becoming dimensions.

The output retains `persona_id=synthetic_id` for existing callers. Research
metadata records `(population_id, synthetic_id, persona_id)` explicitly, together
with crosswalk decisions, dimension content fingerprint, hidden fields, evidence
limitations, selection policy and provenance. Metadata is detached from caller
objects. Projection is deterministic and changes no inputs.

The new neutral `display_name='Resident'` prevents MatrAIx's loader from deriving
an agent-visible display name from the technical resident ID. No personal name,
summary or system prompt is invented. Weights and researcher/source metadata
are never copied into dimensions, summary or system prompt. Both bundled
upstream templates were tested for leaks; arbitrary custom templates could
deliberately render metadata and remain outside this guarantee.

`matraix_persona(persona, catalog=raw_dimensions_json)` optionally checks emitted
native values against a caller-supplied catalog. It rejects version/enum drift.
`validate_catalog_dimensions(document, catalog)` returns a compatible/incompatible
assessment and separates native enum checks from registered custom extensions.
Custom dimensions are not falsely described as native catalog enums. There is
no implicit catalog search, upstream import, default application or network use.

## Actual upstream exercise

Read and exercised the actual local checkout at
`/home/lenovobejan/MatrAIx-Persona-8B` in Ubuntu WSL:

- `persona/extraction/schema.py`: `load_schema` and `is_valid_value`.
- `persona/schema/dimensions.json`: all 1,290 dimensions loaded in the probe;
  SHA-256 `cbf4db9d887dec057431aff409e1d28d83f345e7a31e29a4275a607212ecfca5`.
- `environment/agents/matraix/agents/persona/loader.py`: `load_persona`.
- `src/matraix/persona_dimension_catalog.py`: `build_dimension_narrative`,
  also called by the actual templating integration.
- `environment/agents/matraix/agents/persona/templating.py` and bundled
  `persona_system.md.j2`, `persona_instruction.md.j2`, `persona_macros.md.j2`.

The real upstream test loads seven documents: ordinary custom DST attributes,
each of the three exact marital aliases, unknown education, an empty selection,
and an explicitly selected custom enrichment field. It validates native enums,
preserves loaded custom dimensions, checks Turkish Unicode and identity metadata,
and renders both intended templates with source/weight/identifier leak checks.
Unknown education remains `Unknown` in YAML; upstream intentionally suppresses
unknown/nullish narrative values instead of replacing them with demographics.

No agent, survey, model, provider or paid endpoint was executed. The child has a
credential-free environment, denied sockets, isolated imports and disabled
bytecode writes. Only disposable synthetic YAML files are written under a
temporary directory. Upstream Git status was clean after inspection/testing.
This proves schema/loader/bundled-template compatibility, not end-to-end agent
execution or demographic validity.

## Offline commands and portability

Host tests use existing Windows Python 3.12.10:
`C:/Users/Lenovo/Desktop/Digital-Society-Twin-Population/.venv-persona/Scripts/python.exe`.
The available upstream interpreter is its existing WSL `.venv/bin/python`,
Python **3.14.4**, not 3.12. No dependencies were installed. The local catalog
and renderer import directly from source; the source-root path is explicitly
included for `persona.extraction`, which is not exposed by the installed package.

Run from the feature worktree in PowerShell:

```powershell
$python = 'C:/Users/Lenovo/Desktop/Digital-Society-Twin-Population/.venv-persona/Scripts/python.exe'
$env:SOCIETYTWIN_TEST_PROJECTION_ROOT = '/home/lenovobejan/MatrAIx-Persona-8B'
$env:SOCIETYTWIN_TEST_PROJECTION_PYTHON = '/home/lenovobejan/MatrAIx-Persona-8B/.venv/bin/python'
$env:SOCIETYTWIN_TEST_PROJECTION_WSL_DISTRO = 'Ubuntu'
$testRun = Join-Path $env:TEMP ('dst-upstream-projection-' + [guid]::NewGuid().ToString('N'))
& $python -m pytest -c pyproject.toml tests/integration/test_matraix_projection_contract.py -q -p no:cacheprovider --basetemp=$testRun
$testRun = Join-Path $env:TEMP ('dst-projection-regression-' + [guid]::NewGuid().ToString('N'))
& $python -m pytest -c pyproject.toml tests/integration/test_matraix_projection_contract.py tests/households tests/national tests/enrichment -q -p no:cacheprovider --basetemp=$testRun
```

Without upstream configuration, the actual-upstream test explicitly skips;
local synthetic enum-validator tests do not claim upstream compatibility.
For a native Linux/macOS runtime, omit the WSL distribution variable and supply
native root/interpreter paths. WSL requires OS permission outside this session's
filesystem sandbox. These tests need no API key or live-runtime flags.

Results with the actual WSL runtime configured: **29 focused tests passed** in
12.30 s; **387 regression tests passed, 2 skipped** in 59.20 s. The regression
count includes the focused projection suite, all 39 reconciliation tests and
all 54 membership tests. Both skips require unavailable local disposable
real-data bundles. One existing FastAPI/Starlette TestClient deprecation warning
about httpx remains; no dependency change was made. Local-only verification also
passed 28 tests with the actual-upstream test explicitly skipped. Final tracked
diff and new-file whitespace checks passed.

The repository's `pytest.ini` takes precedence over its richer pyproject pytest
configuration, including the `matraix` marker. Commands explicitly use
`-c pyproject.toml` to enable the intended strict marker configuration without
editing unrelated configuration. The isolated relocation test explicitly sets
UTF-8 for Windows pipes. It copies the package into a temporary site-packages
layout with no repository data/catalog and proves projection works there without
importing MatrAIx. An actual wheel build/install was not performed. Production
generation gains no mandatory heavyweight MatrAIx dependency.

## Future population interfaces and remaining requirements

Future household/graph attributes must first enter a reviewed existing sidecar
contract and pass that method's validator. Current fixture membership does not
establish family roles or representative resident household attributes, and
`PersonaResolver` does not consume its experimental sidecar method.

The production exposure path remains:
`FieldSelection` / `persona_selection.SUPPORTED` -> `PersonaResolver.build` ->
selected `attributes` + `model_visible` -> `personas.matraix_persona` ->
`matraix_projection.CROSSWALK`. Add a reviewed rule and an explicit visibility
policy/resolver change for each new attribute; an arbitrary sidecar field or
`dst_*` key does not auto-expose itself. New rules need availability, evidence,
semantic and upstream-rendering tests. Do not duplicate attributes into the core.

The Validation Engine owner can inspect versioned projection decisions and the
dimension fingerprint, and invoke catalog checks without replacing population
validation. The data owner still needs to provide documented private-household
eligibility, matching universes/dates, institutional distinctions, exact tail
membership evidence and source provenance before representative linking.
No new demographic inference or data-collection requirement was invented here.

Recommended next slice: agree a provenance-bearing eligibility/representation
sidecar contract with the data and Validation Engine owners, keeping production
linking blocked until evidence and a weighted method are approved. Extend persona
visibility only after a new attribute's meaning and evidence are reviewed.

Only `national/personas.py` is modified among tracked files. The six Phase 1/2
additions remain intact, alongside this phase's three new files. There are no
unintended tracked diffs. Scenario Engine, frontend, national generator,
cohort sampling, core records and MatrAIx source were not changed.

## Integration checkpoint (2026-10-28)

Verdict: **PASS**, after two narrowly scoped reconciliation boundary corrections.
Closed exact sizes/upper bounds now require integer types, consistently with
membership readiness. Non-JSON or nonfinite copied provenance now produces
`not_assessable` and a null affected output section, without changing inputs.
Five added regression cases reproduced both defects before correction.

Final checkpoint command is the regression command above, with a unique
`population-checkpoint-<uuid>` temporary root. Result: **392 passed, 2 skipped**
in 61.65 s, including all **29 projection tests** against the actual upstream
schema/loader/templates, **44 reconciliation tests** and **54 membership tests**.
The two skips still require unavailable disposable real-data bundles. The same
existing TestClient deprecation warning remains. A focused household run also
passed all 98 reconciliation/membership tests. No dependencies were installed.

Reviewed all ten intended files, including the nine initially untracked ones.
Git does not ignore them. Only the production projection entry point changes
among previously tracked files. No Scenario Engine, frontend, generator,
sampling, weight or teammate-branch changes are included. The existing configured
Git author/committer is `ovgubejan <taburoglubejan@gmail.com>`.

Reconciliation, fixture membership and projection have consistent boundaries:
aggregate compatibility is insufficient for one-to-one membership; experimental
membership does not enter production sidecar persistence/resolution; projection
only exposes already available, explicitly selected reviewed attributes. The
unchanged one-argument projection call remains supported for production-built
personas. New rejection of arbitrary fields/inconsistent views and neutral
display-name handling are intentional safety changes, not byte-identical prompt
compatibility. Identity remains scoped by population/build metadata.

Default-off behavior, deterministic replay, provenance, missing-data handling,
Unicode and relocated-package imports pass. A distribution wheel was not built:
the existing test environment has no setuptools, and no build dependency was
installed for this checkpoint. Package discovery already includes the new
modules under `src/societytwin`; no checkout-relative catalog is required by the
projection. Existing household registry/data lookups remain source-tree-oriented.

The intended commits are Phase 1's three reconciliation files (including these
corrections), Phase 2's three membership files, then Phase 3's four projection
files (including this checkpoint report). Review found no generated/source data,
unrelated content or credential-pattern matches. Staged whitespace checks are
required before each commit. Sections above retain the earlier implementation
snapshots and their historical test counts/uncommitted state.

The initial remote check found no existing feature branch. Publication must
recheck remote state, use only this feature branch's explicit refspec without
force, and verify the resulting remote hash. A conflicting/divergent remote
update must stop publication; no teammate branch or main may be updated.
