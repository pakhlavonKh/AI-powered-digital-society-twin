# Phase 2: fixture household membership foundation

Date: 2026-10-28. Branch: `feature/population-hybrid-households`.
Worktree: `C:/Users/Lenovo/Desktop/Digital-Society-Twin-Population/data/results/main-evaluation-20261020/.population-hybrid-households`.
HEAD remains `f45b279e04b754736ba129dedf2e8488e879244c`.
Phase 1's three uncommitted files matched the reported implementation and were
preserved without edits. Existing worktrees were preserved. No checkout, merge,
rebase, reset, commit or push was performed during this phase.

## Files and reuse

This phase adds only:

- `src/societytwin/households/membership.py`
- `tests/households/test_membership.py`
- `docs/population-household-membership.md`

The implementation reuses Phase 1 `reconcile`, existing `GeneratedHouseholds`
and household record fields, `ResidentExtension`, `ExtensionRecord`,
`AttributeValue`, frozen `TypedModel`, `EnrichmentConfig`, `canonical_hash`, and
the versioned SHA-256 `Stream`. No immutable demographics are copied into the
membership output. No existing generator, validator, registry, store, frontend,
Scenario Engine or MatrAIx runtime was modified.

## Narrow sidecar contract

Version: `household-membership-1`. Method: `fixture_capacity_shuffle_v1`.
The output is an in-memory **existing `ResidentExtension`**. Each record has
the existing resident `synthetic_id` and exactly one assigned `household_id`
attribute with a provenance profile reference. The manifest binds:

- `core.population_id` and the sorted resident records hash;
- `households.household_population_id` and the sorted household records hash;
- full input fingerprints, including all input columns and both manifests;
- method version, sidecar schema version, seed and stream version;
- explicit fixture eligibility/universe assertions, reconciliation digest,
  readiness assessment, provenance profile and experimental limitations;
- sidecar content hash and content-derived `ext-` artifact identity.

A resident reference is `(core.population_id, synthetic_id)`. A household
reference is `(households.household_population_id, household_id)`. Bare IDs
must not be joined across builds. Profile and manifest bindings apply to every
assignment, without repeating build IDs or demographics in each record.

The existing `ExtensionStore` is registry-driven and validates the existing
categorical enrichment method. It does **not** accept this experimental method.
There is no alternate store or automatic disk write in this phase. Do not call
that store with fixture membership output. A reviewed future integration can
extend existing dispatch rather than introduce competing sidecar storage.

## Explicit fixture contract and readiness

Both input manifests must explicitly contain
`purpose='synthetic_fixture_only'`. This is a declaration for invented test data,
not permission to relabel official or representative population records.

`FixtureMembershipContract` additionally requires exact build identities,
`resident_representation='unit_person_records'`,
`household_representation='unit_household_records'`,
`universe_approved=True`, an eligibility source reference, a complete list of
eligible resident IDs and the full input fingerprints. There are no inferred
approval or eligibility defaults. The reference documents a synthetic test
assertion; it does not purport to be official TÜİK evidence.

```python
from societytwin.households.membership import (
    FixtureMembershipContract, assess_readiness, input_fingerprints, link_fixture,
)
from societytwin.households.reconciliation import reconcile
from societytwin.enrichment.model import EnrichmentConfig

# columns, resident_manifest and households are explicitly constructed fixtures.
contract = FixtureMembershipContract(
    contract_version='household-membership-1',
    purpose='synthetic_fixture_only',
    population_id=resident_manifest['population_id'],
    household_population_id=households.manifest['household_population_id'],
    resident_representation='unit_person_records',
    household_representation='unit_household_records',
    universe_approved=True,
    eligibility_source_ref='test-fixture: every listed resident is eligible',
    eligible_resident_ids=tuple(columns['synthetic_id']),
    **input_fingerprints(columns, resident_manifest, households),
)
reconciliation = reconcile(columns, resident_manifest, households)
readiness = assess_readiness(
    columns, resident_manifest, households,
    reconciliation=reconciliation, contract=contract,
)
extension = link_fixture(
    columns, resident_manifest, households,
    reconciliation=reconciliation, contract=contract,
    config=EnrichmentConfig(seed=42), enable_fixture_linking=True,
)
```

Readiness returns `status` (`ready`, `blocked`, `not_assessable`), `ready`,
ordered reasons (`code`, `status`, `detail`), counts, fingerprints and
`production_linking_enabled=False`. A definitive blocker takes precedence
over missing evidence. A failed linking call raises `MembershipError` with the
readiness result in `.report`; it produces no partial sidecar.

The gate recomputes reconciliation and requires the supplied result to match
exactly and to be compatible. A status string alone cannot bypass the gate.
Phase 1's geographic, reference/observation year, universe and total checks remain
in force. All resident and household IDs must be nonempty and unique within
their respective builds. The explicit contract must match the actual inputs.

Both `population_weight` and `design_weight` must be explicitly one for every
resident. Every `household_weight` must be one. Missing design weights are not
treated as one. No rounded-weight tolerance, rescaling, expansion into virtual
people, or weight conversion is supported. Distinct statistical units remain
valid in reconciliation, but aggregate representatives cannot be consumed as
individual records by this fixture method.

All household capacities must be positive exact integers with matching closed
class/lower/upper fields and `household_size_open_ended=False`. Any 10+ record
is blocked, even if somebody supplies an assumed exact size. Every input resident
must be explicitly eligible, without duplicate or foreign eligibility references.
Partial eligibility subsets are outside this narrow contract. Exact capacity
must equal eligible record count globally and within each province/year.
The resident universe must explicitly be private-household residents; an
institutional count subtraction establishes no individual eligibility and is
not sufficient here.

Fingerprints bind canonical ID-sorted rows, including demographics and weights,
and full manifests. Reordering resident rows, household rows or column keys does
not change the binding. Manifest lists retain their declared order. Hashes detect
input drift relative to the explicit fixture contract; they do not authenticate
external sources, replace artifact validators or constitute approval.

## Deterministic behavior and synthetic example

Within each province/year, the existing SHA-256 stream shuffles resident IDs
from canonical ID order. The namespace binds the method, both build identities,
province and year. Canonically ordered household IDs consume their exact slot
counts. Output records are sorted by resident ID. The method changes no resident
or household, and creates no parent/spouse/child, family-role or household-type
attributes. It makes no demographic realism claim.

For the five invented residents and two households (capacities two and three)
in `test_membership.py`, seed 42 produces these selected output fields:

```json
{
  "population_id": "fixture-people",
  "household_population_id": "fixture-households",
  "method_version": "fixture_capacity_shuffle_v1",
  "seed": 42,
  "memberships": [
    {"synthetic_id": "r1", "household_id": "h2"},
    {"synthetic_id": "r2", "household_id": "h1"},
    {"synthetic_id": "r3", "household_id": "h2"},
    {"synthetic_id": "r4", "household_id": "h1"},
    {"synthetic_id": "r5", "household_id": "h2"}
  ]
}
```

`validate_membership(extension, columns, manifest, households,
reconciliation=..., contract=...)` checks referential integrity and replays the
same method, requiring exact record and manifest agreement. It rejects missing,
duplicate or foreign references, extra role attributes, altered capacities or
inputs, and modified provenance/content. This is a narrow module validator in
the existing style, not a second general validation framework.

## Production guard and ownership

`link_fixture` is disabled by default and is not wired into production services,
APIs, CLIs, generation or the enrichment store. Explicit opt-in does not bypass
readiness. Existing production expansion/design/household weights, missing
private-resident eligibility, unknown tail capacities and unsupported source
evidence block this method. Aggregate compatibility alone remains insufficient.
Representative Ankara linking needs a separately approved weighted method and
evidence; fixture labels must not be applied to production data to bypass this.

The Validation Engine owner can consume the versioned readiness reasons, Phase 1
findings, sidecar bindings, input fingerprints and replay validator. They retain
ownership of broader validation of conditional demographics, consistency,
provenance and source/content integrity. Persistence or registry integration
requires a separate reviewed change to existing sidecar dispatch.

The TÜİK bot owner still needs to provide matching universe definitions and
dates, geography coverage, citizenship/age/residency restrictions, institutional
versus private-resident evidence, source IDs/table-cell references and hashes,
and observed exact tail membership evidence. A private-resident aggregate alone
does not identify individual eligibility. Exact household sizes and a defensible
weighted representation/linkage method are prerequisites for representative
linking; no institutional counts or tail sizes are invented here.

Recommended next slice: agree and validate a provenance-bearing eligibility and
record-representation sidecar contract using evidence supplied by the data owner,
then review how the existing sidecar dispatcher should support membership.
Keep weighted production assignment, family roles and graph enrichment disabled
until their evidence, method and approvals are explicit.

## Tests

Python 3.12.10 from the existing `.venv-persona` environment; no dependencies
installed. Exact commands, run from the feature worktree:

```powershell
$python = 'C:/Users/Lenovo/Desktop/Digital-Society-Twin-Population/.venv-persona/Scripts/python.exe'
$testRun = Join-Path $env:TEMP ('hh-membership-' + [guid]::NewGuid().ToString('N'))
& $python -m pytest tests/households/test_membership.py -q -p no:cacheprovider --basetemp=$testRun
$testRun = Join-Path $env:TEMP ('hh-phase2-regression-' + [guid]::NewGuid().ToString('N'))
& $python -m pytest tests/households tests/national tests/enrichment -q -p no:cacheprovider --basetemp=$testRun
```

The focused suite covers exact capacities, reproducibility, scoped references,
duplicate/missing/foreign IDs, insufficient/excess capacity, open tails,
incompatible/unknown/forged reconciliation, approval and eligibility, weighted
record misuse even with compatible aggregates, record ordering, mutation
prevention, absent role generation, provenance, stale fingerprints and tampering.
Regression suites use existing local synthetic fixtures and stub backends.
No paid calls, source downloads or official data regeneration were performed.

Results: **54 focused tests passed** in 0.37 s; **358 regression tests passed,
2 skipped** in 59.26 s (including the focused suite). Both skips are the existing
persona-selection tests requiring unavailable local disposable real-data bundles.
The regression run reported one existing FastAPI/Starlette TestClient deprecation
warning about httpx. No dependency change was made. `git diff --check` passed,
and final status contains only the three preserved Phase 1 additions and the
three Phase 2 additions listed above, all uncommitted.
