# Household population reconciliation

Implementation slice: read-only universe diagnostics, 2026-10-28.

## Development setup

Branch: `feature/population-hybrid-households`.
Worktree: `.population-hybrid-households` under the original evaluation checkout.
Fetched integration baseline: `origin/main`,
`f45b279e04b754736ba129dedf2e8488e879244c`.
The original checkout had clean status at `0e23d1829ddc3b5c6554d521a3e776cc57a9a852`.
Fetch also advanced the scenario remote-tracking branch and discovered the MatrAIx
runtime branch; neither affects this baseline. Existing worktrees and branches
were preserved. No pull, merge, reset, rebase, commit or push was performed.

Changed files are this note, `src/societytwin/households/reconciliation.py`, and
`tests/households/test_reconciliation.py`. No generation, frontend, scenario,
existing validation or source-data files were changed.

## Existing contracts

The diagnostic accepts the national generator's column mapping and manifest,
and the existing `GeneratedHouseholds` wrapper / `HouseholdRecord` fields.
It reuses `CLASSES` from the household registry. The optional type-size manifest
is supported through `identity.size_source`; national transfer tables are not
used to assert local household universe coverage.

`households.validation.validate` already calculates weighted household counts
and member lower bounds. Reconciliation follows those semantics but does not
invoke the validator: the existing validator enforces complete build identity,
all ten observed strata and generator invariants, while this diagnostic also
needs to explain incomplete metadata and closed-size synthetic fixtures.
`national.validation.validate` remains unchanged. These artifact validators
should run separately; reconciliation does not authenticate hashes or sources.

The inspected saved manifests in the original evaluation checkout included
ARTIFICIAL resident and household test builds. They confirmed person expansion
weights, household expansion weights, `ADNKS_private_households`,
`linked_to_residents=false`, and `member_count_exact=null`. These test counts
are not official population estimates. The household registry explicitly excludes
collective accommodation. Current national manifests do not supply the explicit
resident/private-household universe split required by this gate.

## Validation Engine interface

```python
from societytwin.households.reconciliation import reconcile

report = reconcile(residents.columns, residents.manifest, households)
```

This function performs no I/O, writes no attributes, and mutates no inputs.
The return value contains `reconciliation_version`, overall `status`, an ordered
`findings` list of `{check, status, detail}`, `totals`, copied `provenance`, and
`limitations`. Status values are `compatible`, `incompatible`, `not_assessable`.
An incompatible finding takes precedence; otherwise missing evidence prevents
compatibility. There are no timestamps or randomness in the result.

The additive input contract below can be supplied in a caller-owned manifest
copy. This implementation does not add it to generated artifacts or sidecars.
Only evidenced definitions should be supplied; adding a string is not evidence.

```python
population_universe = {
    "definition": "ADNKS_private_household_residents",
    "source_ref": "documented-source-and-definition-reference",
}
```

Alternatively `ADNKS_residents` requires an evidenced, nonnegative
`institutional_population` count for the same geography, year and coverage;
the private total is the resident weighted total minus that count.
`ADNKS_institutional_residents` is explicitly incompatible with private
households. Unsupported definitions and missing evidence are not assessable.
No institutional count, nationality restriction or age restriction is inferred.

Geography and year are compared across complete record sets and checked against
manifest metadata. Root population observation years from the national manifest's
`profiles[*].fields.province_code.source_year` must also match record years;
missing observation years are not assessable. No implicit province subset or
source-year transfer is made.
Resident totals use `sum(population_weight)`; household totals use
`sum(household_weight)`. Member totals use `sum(household_weight * size)`;
for 10+ the size is only a lower bound of ten. Distinct statistical units are
expected and compatible. Explicit contradictory unit declarations are rejected.
Positive finite weights and the existing size-bound semantics are required.
Manifest represented totals must agree with record totals.
Totals use `math.fsum`; comparison tolerance is relative `1e-10`, absolute `1e-6`.

Closed sizes can establish equality or a contradiction. An open-ended lower
bound above the available private population establishes a contradiction;
otherwise exact equality remains not assessable, including when the bound
equals the available population. No exact tail value or upper bound is invented.
Compatibility is only an aggregate universe gate: it does not establish
individual membership, conditional demographic fit, family roles, or approval
to link residents. With an institutional subtraction, individual eligibility
remains unknown even if aggregate totals reconcile.

## Synthetic example

The tests use two resident representatives with person weights 4 and 6, and one
size-two household representative with household weight 5. Both cover province
06, 2025, with documented private-household coverage. Selected report fields:

```json
{
  "reconciliation_version": "household-universe-1",
  "status": "compatible",
  "totals": {
    "resident_persons": 10.0,
    "private_household_persons": 10.0,
    "households": 5.0,
    "member_lower_bound": 10.0,
    "member_exact": 10.0,
    "open_ended_records": 0
  }
}
```

With a 10+ household representative of weight 5, the member bound becomes 50
and `member_exact` is null. Fifty or sixty private residents produce
`not_assessable`; forty-nine produce `incompatible`. Removing the universe
evidence also produces `not_assessable`.

## Verification

Existing supported environment (no dependencies installed):
`C:/Users/Lenovo/Desktop/Digital-Society-Twin-Population/.venv-persona/Scripts/python.exe`,
Python 3.12.10. Run from the new worktree in PowerShell:

```powershell
$python = 'C:/Users/Lenovo/Desktop/Digital-Society-Twin-Population/.venv-persona/Scripts/python.exe'
$testRun = Join-Path $env:TEMP ('hh-reconcile-' + [guid]::NewGuid().ToString('N'))
& $python -m pytest tests/households/test_reconciliation.py -q -p no:cacheprovider --basetemp=$testRun
$testRun = Join-Path $env:TEMP ('hh-regression-' + [guid]::NewGuid().ToString('N'))
& $python -m pytest tests/households tests/national/test_generator_and_validation.py -q -p no:cacheprovider --basetemp=$testRun
```

All fixtures are synthetic. Existing household regressions cover storage,
validation, disabled-by-default behavior and the optional type-size interface;
national regressions cover generation, weights, constraints and validation.
No downloads, paid calls, source regeneration or dependency installation occurred.

Final results: focused reconciliation suite **39 passed** in 0.23 s;
household plus national generator/validation regression suite **127 passed**
in 15.74 s (including those 39 focused tests). `git diff --check` passed.
The first focused attempt had a missing parent directory for its custom pytest
temporary path; rerunning with a unique directory in the system temporary root
resolved that setup error. Neither initial Python nor the UI checkout's virtual
environment had pytest; the existing `.venv-persona` environment above did.

## Remaining evidence and ownership

The TÜİK bot owner needs to provide authoritative source identifiers, URLs,
table/cell references, reference dates/years, geography codes, coverage definitions
(citizenship, age and residence restrictions), institutional versus private
household inclusion, and matching private-resident or institutional counts with
provenance. Definitions must establish that subtraction exhausts the difference
between these universes. Missing observations must remain missing, not zero.

Exact 10+ member counts or an observed tail-size distribution are required to
resolve exact represented membership; a mean size or assumed size ten does not
supply that evidence. An observed tail distribution would require a separately
approved subsequent implementation. Source dates and root control provenance
must also confirm actual observation years rather than target build years alone.

Before linking, the population owner also needs a defensible private-resident
eligibility mechanism, compatible roster/household evidence and approved family
role constraints. The broader Validation Engine owner can consume the versioned
findings and totals without changing existing validators, and should separately
verify source/content integrity, observation periods, conditional relationships,
consistency and provenance. Compatibility is not a household assignment plan.
No household linking, graph enrichment or inference was implemented here;
offline MatrAIx testing remains outside this slice.

Integration checkpoint: closed exact sizes/upper bounds now require integer
types, matching the membership readiness contract. Malformed copied provenance
(including nonfinite numbers or non-JSON objects) yields `not_assessable` with
the affected output provenance section set to null, keeping the diagnostic
strict-JSON serializable without changing the inputs. Five focused regression
cases cover these boundary corrections; the Phase 1 suite now has 44 tests.
