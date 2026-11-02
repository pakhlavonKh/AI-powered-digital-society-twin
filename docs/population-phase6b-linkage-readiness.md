# Phase 6B: household linkage evidence and readiness

Implemented on `feature/population-hybrid-households`, starting at
`d71d1d1a1475a5b9e96a3f938eb97106473f8d16`, with a clean worktree at
`C:\Users\Lenovo\Desktop\Digital-Society-Twin-Population\data\results\main-evaluation-20261020\.population-hybrid-households`.
This phase adds evidence/readiness only. During implementation no production assignments, resident
household IDs, family roles, graph enrichment, source downloads/regeneration,
paid calls, staging, commits, pushes or merges were performed.

## Exact new files

- `src/societytwin/households/linkage_evidence.py`
- `src/societytwin/households/linkage_readiness.py`
- `data/household_linkage_evidence.yaml`
- `tests/households/test_linkage_evidence.py`
- `tests/households/test_linkage_readiness.py`
- This document.

Existing source files are unchanged: resident/household generators, weighting,
original manifests, fixture linker, MembershipStore, categorical enrichment,
dependency registry, persona selection, MatrAIx projection, Scenario Engine,
frontend and the teammate's Validation Engine. These new modules are not wired
into the unified workflow or any automatic persona path.

## Contracts and integrity

`LinkageEvidence` is versioned as `household-linkage-evidence-1`. It reuses the
project's frozen, extra-fields-forbidden TypedModel convention and duplicate-key
YAML loader. Its sections are:

| Section/type | Contract |
| --- | --- |
| SourceEvidence | Identifier, relative path, SHA-256, title/reference/acquisition, geography, observation and reference years, statistical unit, universe, dimensions and precision |
| Precision | Exact integer counts, rounded or unknown; optional decimal places/rounding rule and explanatory note |
| CountClaim | Observed/modeled/unknown/missing/unavailable status; count and source for present evidence; explicit assumption for modeled values |
| CompositionCell | Count claim plus one of seven leaf codes, original source indicator/Turkish label and definition |
| SizeCell | Count claim for closed sizes 1–9 or open size 10+ |
| TailEvidence | Lower bound 10, optional evidenced upper bound, member-total claim and uncertainty note |
| CoverageEvidence | Private/institutional person counts, eligibility status and source references |
| RelationshipEvidence | Availability and source references, without generating any relationships |

Booleans, strings and floats cannot masquerade as integer counts/years. Unknown
counts cannot carry numeric values. Duplicate leaves, nested categories, bad
units/references/checksums/versions, contradictory complete totals, inconsistent
one-person/size-one counts and contradictory tail bounds fail validation.
Partial/missing catalogs are representable and produce missing-evidence findings.
An observed person-mass claim must name its exact source indicator.

`load_linkage_evidence(path=None)` loads the registry only, without discovering
other worktrees. `inspect_sources(evidence, source_root=None)` optionally reads
local bytes under an explicit source root. Without it, sources are `not_checked`.
Missing files are `unavailable`, not zero-valued data. Matching files are hashed;
observed composition, size, household-total and person-mass claims are checked
against exactly one CSV cell at the declared geography/year/unit. Duplicate,
absent, blank or inconsistent cells fail. Source paths reject traversal, absolute
and drive-relative paths; reads reject symlinks/junctions, including in parents.

These checks bind declarations to bytes. They do not independently authenticate
TÜİK authorship, prove a declared universe, or approve source reuse. Precision and
universe metadata remain caller/source declarations. The files must be trusted
local snapshots; this is not a hostile concurrent-filesystem sandbox.

## Available Ankara evidence and hierarchy

The feature worktree has no official raw-source copies. Phase 6A found the files
under the explicit local source root:

`C:\Users\Lenovo\Desktop\Digital-Society-Twin-Population`

The checked-in registry uses portable paths relative to that root:

| Path | Geography/year, units and evidence |
| --- | --- |
| `data/raw/tuik_package/households_size_and_types.csv` | Ankara 2025 household composition, selected integer cells; T06/T08; SHA-256 `cf4e83f5a2266e7e84f247d81eb8232241b7cdfa35d08f73ec816bc1f3de01ae` |
| `data/raw/ankara_household_size_2025.csv` | Ankara 2025 private-household counts, sizes 1–9/10+; SHA-256 `1aed9e3fb1b65ab6ab4a880247b5b4b662cd980b6dfee5cedd3d904dedc2471b` |
| `data/raw/tuik_package/population_by_age_sex.csv` | Ankara 2025 ADNKS all-resident age/sex counts; SHA-256 `edbde119e93691d2a9dbe28a7fe5e9989569af5611a2572cbfe29958d1bb4ace` |

The registry records portal/table references, source precision and original-label
metadata lineage (`variable_metadata.csv`). Original household-size XLSX/HTML
checksums are retained in acquisition metadata. Private-household source scope
follows the existing household registry; no new independently authenticated
resident-universe assertion is made.

The disjoint observed composition leaves are:

| Leaf | Households |
| --- | ---: |
| One-person | 400484 |
| Couple only | 292350 |
| Couple with children | 785228 |
| Lone father | 50178 |
| Lone mother | 184664 |
| Extended | 205415 |
| Multiple-person without nuclear family | 68897 |
| **Leaf total** | **1987216** |

`composition_totals()` derives nuclear = 1312420 and lone-parent = 234842.
Neither is another leaf. The schema rejects attempts to insert nested aggregates.
The four-category legacy household generator/registry is unchanged.

Children may be adults; a household without a nuclear family need not consist
entirely of unrelated people. No member ages, spouses or parent-child pointers
are inferred from category definitions. Separate size/type marginals do not
observe an Ankara joint; the existing national transfer remains a disclosed
modeling assumption, not new local observations.

## Readiness interface and meanings

```python
from societytwin.households.linkage_evidence import load_linkage_evidence
from societytwin.households.linkage_readiness import assess_linkage_readiness
from societytwin.households.reconciliation import reconcile

evidence = load_linkage_evidence()
diagnostic = reconcile(columns, manifest, households)
report = assess_linkage_readiness(
    columns, manifest, households, evidence=evidence,
    reconciliation=diagnostic,
    source_root=local_source_root,  # explicit; optional and read-only
)
```

The function revalidates evidence, recomputes reconciliation and rejects a stale
or forged diagnostic through reason codes. It reuses the existing pure
`input_fingerprints` function to bind full resident/household records and original
manifests. This reuse does not call or relax the fixture linker.

Reports have version `household-linkage-readiness-1` and contain four gates:

| Capability | Meaning of its status |
| --- | --- |
| household_aggregate_modeling | `ready` for the supported marginal catalog when source cells, counts, scope, units and precision pass; absent/unchecked bytes or modeled counts make it conditional; contradictions or missing catalog evidence block it |
| weighted_mass_allocation | Blocked by missing comparable private mass, unresolved tail/capacity, reconciliation or source problems. Even complete aggregate prerequisites can only be `conditionally_ready`, pending a reviewed future method |
| unique_instance_assignment | Always blocked in Phase 6B: weighted representatives are not instances, unit weights alone do not prove instance eligibility, and no production instance method exists |
| family_roles_and_kinship | Always blocked in Phase 6B: coherent rosters and reviewed relationship evidence/methods are not implemented |

Every gate includes required/missing evidence and stable reason codes with
blocker/condition severity. Reports include input build IDs, original content
hashes where present, full input fingerprints, evidence/reconciliation hashes,
source declarations and observed byte hashes, units, representation classification,
coverage/tail uncertainty, disjoint totals and explicit modeling assumptions.
All output is detached, deterministic JSON-safe data for supported inputs.

`production_assignment_enabled` is always false. No allocation artifact,
resident-to-household IDs, family edge or persona-visible field is produced.
Existing artifact validators remain responsible for full input artifact validity.
Aggregate `ready` does not claim a fitted joint, donor support or roster feasibility.

### Existing stored build check

Read, without modifying or regenerating, the existing parent-checkout bundle:

`data/results/unified-build/bundles/build-26e88537630b4b8ef54abc709bf9ac7399b260a7f2228f8af799d65d1bd72a6c`

All three source hashes matched; composition and size claims matched their cells.
Result: aggregate modeling **ready**; weighted allocation, unique assignment and
kinship **blocked**. Its 10000 resident representatives expand to about 5910320
persons; 10000 household representatives expand to 1987216 households. The member
lower bound is about 5686300, with unknown exact tail/person totals. The report
retains this distinction between representative records and expansion units.

## Why linking remains blocked / data-bot request

- The root population has no explicit private-household universe binding.
- Private-resident and institutional totals and individual eligibility remain
  unknown. Mean household size times household count suggests about 5690627
  persons, but its precision/numerator evidence is unresolved. The 219693 residual
  from the root is not labeled an institutional observation.
- The 3000 observed 10+ households have no upper size or exact tail member total.
  The schema stores bounds/uncertainty; no mean-based sizes are invented.
- An exact tail member total would still not identify each household's size.
- Current household/person weights do not establish a coherent instance roster.
- A codebook mentioning spouse/parent pointers is not acquired relationship data.

The TÜİK bot teammate must supply same-scope/date authoritative universe and
coverage definitions, private/institutional counts (preferably private age/sex
controls), tail sizes or supported bounds/member totals with precision rules,
Ankara composition/size/member joints or approved donor evidence, and actual
relationship observations if roles are to be modeled. Each needs original-file
hashes, provenance, units, dimensions, missing/suppression rules, sampling/weight
semantics and permitted-use documentation. Missing evidence stays explicit.

## Future weighted artifact contract — specified, not implemented

An aggregate allocation would carry a separate schema/version, both input build
IDs and full fingerprints, method/version/seed, source and assumption references,
and rows `(resident_representative_id, household_representative_id,
allocated_person_mass)`. These would reference existing representative IDs,
not create or imply household instances. Mass must be finite and nonnegative.

For supported exact capacities, require:

```
sum_h mass[i,h] = independently supported private person mass for i
sum_i mass[i,h] = household_weight[h] * supported household_size[h]
```

Any institutional/unresolved mass must be separately accounted for. Interval or
modeled capacities require explicit uncertainty semantics; a lower bound is not
an exact capacity. Preserve all original weights and artifacts. Fractional mass
may split a representative across households and cannot be presented as a unique
resident membership or a simulation roster. A separate jointly integerized or
otherwise reviewed instance representation would be needed for actual rosters.
This phase implements neither artifact rows nor an allocator.

## Validation Engine handoff and acceptance

The separate teammate can consume the evidence registry fingerprint, local-source
inspection findings, fresh reconciliation and four readiness reports. Preserve
evidence availability/classification separately from method approval and source
authentication. Important reason codes include `source_integrity_failure`,
`source_scope_mismatch`, `statistical_units_unverified`,
`reconciliation_binding_mismatch`, `private_population_unknown`,
`institutional_population_unknown`, `open_tail_upper_unknown`,
`open_tail_members_unknown`, `weighted_representatives_not_instances`,
`instance_semantics_unverified` and `relationship_evidence_missing`.

Acceptance coverage includes seven-category partition/nesting, exact and missing
claims, wrong scope/year/units, source corruption and false count declarations,
precision and tail contradictions, source path rejection, deterministic hashes,
no input mutation, persona/projection invariance, and unchanged reconciliation,
fixture membership and persistence behavior. No broader Validation Engine code
or acceptance policy is replaced.

## Test commands, results and limits

Native Windows CPython 3.12.10, using the existing ignored workspace runtime.
No dependencies were installed. The runtime retains the Phase 4 limitation: an
explicit .pth references the sibling `.venv-persona` packages, with local copied
Jinja2/MarkupSafe. It is machine-specific, not a hermetic lockfile reconstruction.

PowerShell commands from the feature worktree:

```powershell
$phase6bPython = Join-Path (Get-Location) 'data/results/phase4-runtime/Scripts/python.exe'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:SOCIETYTWIN_TEST_PROJECTION_ROOT='C:\Users\Lenovo\Desktop\MatrAIx-Persona-8B'
$env:SOCIETYTWIN_TEST_PROJECTION_PYTHON=$phase6bPython
& $phase6bPython -B -m pytest tests/households/test_linkage_evidence.py tests/households/test_linkage_readiness.py tests/households/test_reconciliation.py tests/households/test_membership.py tests/households/test_membership_store.py tests/national/test_persona_selection.py tests/integration/test_matraix_projection_contract.py -q --tb=short -p no:cacheprovider
& $phase6bPython -B -m pytest tests/national tests/households tests/enrichment tests/build -q --tb=short -p no:cacheprovider
git diff --check
```

The relevant broad run completed **481 passed, 2 skipped, 17 failed**, before
the final precision/tail/visibility test additions. The 17 failing IDs were
programmatically compared with `data/results/phase5-publish-regression.txt` and
match exactly. They are the unchanged explicit-build output-root guard failures:
tests select temporary bundles outside repository `data/results`. No unrelated
baseline failure was fixed or guard weakened. Default pytest discovery excludes
`tests/build`, which was explicitly selected here. Broad output is retained in
ignored `data/results/phase6b-regression.txt`.

The focused suite includes optional real-upstream Windows projection and the
existing persona, reconciliation and fixture-membership/store checks. The two
optional disposable real-data exports are unavailable and skipped; unknown marker
and Starlette/httpx deprecation warnings are pre-existing. Final focused result:
**246 passed, 2 skipped**, including the final precision, tail-bound and persona
visibility additions. No new blocking regression was identified. `git diff
--check` passed. Because all six implementation files are new/untracked, an
additional explicit UTF-8/trailing-whitespace and Python AST check inspected
every new file; all passed. `git diff --exit-code` confirmed no existing tracked
file changed. At implementation handoff HEAD remained the expected Phase 5 commit;
only the six documented new files were present, with nothing staged or published.

## Publication review

The subsequent user-authorized review verified the exact feature worktree and
Phase 5 base HEAD, configured Git identity `ovgubejan <taburoglubejan@gmail.com>`,
and live GitHub feature-branch hash. Only the six intended new source, evidence
registry, test and documentation files were present; no existing tracked files,
teammate code, generated datasets or dependencies changed. The reviewed file set
was checked for credential patterns and unintended assignment calls.

Re-ran the focused command above: **246 passed, 2 skipped**. Re-ran the relevant
regressions including explicit `tests/build`: **486 passed, 2 skipped, 17 failed**.
Programmatic failed-ID comparison with the established Phase 5 publication log
confirmed exactly the same 17 failures; the output-root guard error is unchanged.
No new regression was identified, and no unrelated baseline failure was fixed.
The ignored review log is `data/results/phase6b-publish-regression.txt`.

Reviewed that production allocation is always disabled, weighted allocation can
at most be conditional, and instance/kinship methods remain blocked. Fixture
membership, MembershipStore, original demographics/weights/manifests, personas,
MatrAIx, Scenario Engine and frontend are unchanged. Whitespace checks passed;
the exact staged set is inspected before the authorized commit. Publication is
limited to a normal fast-forward push of `feature/population-hybrid-households`
after fetching origin. Commit identity and remote-hash verification are reported
in the accompanying publication response. No main/teammate merge or Phase 7 work
is included.

## Next slice

Obtain/review the missing universe and tail evidence first. Extend source-bound
tests and prerequisite diagnostics for any new official format before designing
a separate weighted conservation method. Do not relax fixture-only contracts or
turn an aggregate-ready catalog into permission for assignment. Roles, instance
expansion, graph enrichment, persona exposure and production activation each
require separate evidence/method review.
