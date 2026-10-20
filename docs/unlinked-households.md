# Unlinked Ankara household populations (Phase 2D-2)

The default size-only module generates household representatives, not families or residents.
Its v1 schema has no resident links, roles, member ages, household type, housing, income or SES.
An additional experimental type × size strategy is documented below and remains disabled by default.
The resident generator, dependency registry, public APIs and frontend are unchanged.

## Verified source

`data/household_registry.yaml` describes the Ankara 2025 NIP private-household size
observations and pins `data/raw/ankara_household_size_2025.csv` by SHA-256. Data
remain ignored. The normalized CSV was extracted from the Phase 2A observations,
whose archived HTML and XLSX were rechecked before implementation. The ten classes
are 1–9 and 10+; counts sum to 1,987,216 households. The separate Ankara household
type total corroborates this denominator. This is a household count, never the
5,910,320-person all-resident root. Public statistical reuse requires attribution.

The registry retains URLs, reference date, scope, geography, source version,
coverage, acquisition notes and original observation hashes. Original research
archives are provenance references; only the pinned normalized source is needed
at runtime. Do not substitute national proportions, a mean, or a population
residual for the observed size counts. Missing files, wrong checksums, categories,
years, geography, units, scope or totals cause an explicit error.

The underlying TÜİK table is available at
<https://nip.tuik.gov.tr/?value=HanehalkiBuyukluguneGoreHs>. Select **Tablo**, set
**Düzey Seçiniz** to **İl**, select **ANKARA**, and transcribe the 2025 row for
classes 1–9 and 10+ into the registry's four-column CSV contract. Strip Turkish
thousands separators; retain integer counts. Verify all ten classes, province 06,
year 2025, positive counts, total 1,987,216, and the pinned SHA-256. The exact
normalization format, local verification commands, source attribution, and
licensing caution are in [the current system handover](CURRENT_SYSTEM_HANDOVER.md#data-setup-and-portability).
The reuse licence is **OPEN DECISION** in the project data strategy. Do not
redistribute the transcription until TÜİK's applicable terms are confirmed.

## Explicit opt-in

The separate household-scope registry is disabled by default. It binds to the
existing `dependency-registry-1` / `ankara-core-1` parent registry and validates
its compatibility profile without editing it. The Phase 1 compiler remains
person-only, and its `linked_households` module remains disabled. This is an
explicit typed extension, not activation of linked household support.

Run from the repository with the project Python environment and `src` importable:

```powershell
$env:PYTHONPATH = 'src'
python -m societytwin.households --enable-households --size 1000 --seed 42
python -m societytwin.households --enable-households --size 10000 --seed 42
```

Without `--enable-households` the command fails before reading source observations
or creating output directories. Activation is request-local and versioned in the
manifest; the on-disk registry remains disabled. Internal callers use
`households.service.build(HouseholdConfig(...), enable_households=True)`.
There is no national service, UI or API integration.

`--output-root data/results/<disposable-directory>` supports isolated testing.
The normal output root is `data/households/`. The service permits only these two
output namespaces under its repository root, and rejects resident directories.

## Sampling and weights

Existing deterministic Hamilton largest-remainder allocation chooses the number
of records per size class proportional to observed household counts. Every class
must have record support: too-small requests fail rather than discard a margin.
For 1,000 and 10,000 records all ten classes have support. A separate namespaced
SHA-256 counter stream shuffles class order; it does not touch resident streams.
Record allocation differs from each proportional quota by less than one record.
This is a stratified synthetic sample, not an iid draw or an observed joint.

Each record's `household_weight` is its official size-cell household count divided
by the number of records allocated to that cell. Weighted class totals therefore
reproduce the observed margins; their total is 1,987,216 households. No IPF, person
raking, mean-size fitting or random model calls are required.

## Versioned household schema

Parquet metadata declares `household-size-schema-1` and unit `household`.

|Field|Type|Meaning|
|---|---|---|
|household_id|string|Deterministic synthetic ID, build namespace plus sequence|
|province_code|string|06, Ankara|
|reference_year|int16|2025|
|household_size_class|string|Observed 1–9 or 10+ class|
|household_size|nullable int16|Exact class size for 1–9; null for 10+|
|household_size_lower|int16|Exact size for 1–9; 10 for 10+|
|household_size_upper|nullable int16|Exact size for 1–9; null for 10+|
|household_size_open_ended|bool|True only for 10+|
|household_weight|float64|Number of households represented, not persons|

There is no `population_weight`, person ID, resident build reference, membership
table or household type. The manifest reports `linked_to_residents=false` and
`member_count_exact=null`. Weighted minimum membership is a lower bound, not a
measured person count. In particular, 10+ does not become exactly 10, and the
population-minus-household estimate is not an assigned institutional population.

## Identity and persistence

`data/households/<household_population_id>/` contains `households.parquet`,
`manifest.json` and `validation.json`. Build identity includes generator/schema
versions, settings, seed, source hash/counts, household registry fingerprint and
parent dependency registry fingerprint. IDs change with semantic inputs; repeated
identical requests reproduce records, weights and manifests. Manifests deliberately
omit wall-clock timestamps from these deterministic artifacts.

The store validates before writing, stages a complete artifact inside its output
root, and reuses an existing identical validated build. It refuses inconsistent
or corrupt builds rather than overwriting them. Loading checks file checksums,
the exact household schema, content identity, validation results and margins.
Resident Parquet schemas and stored research populations are never rewritten.

## Limits and next gate

This validates household margins by construction, not realistic families. The
10+ tail has no exact sizes, and these records cannot be interpreted as rosters.
The separate Phase 2D-3 strategy below uses national type × size evidence at
1–6/7+, preserving Ankara household marginals. It cannot identify observed
type variation within 7+ or member composition and does not add fields to the v1 schema. Linked membership
still requires private-household age/sex coverage, roster evidence and coherent
joint household/person weights.

## Experimental type × size strategy (Phase 2D-3)

`national_household_type_size_seed_v1` is **disabled by default**, separately
declared in `data/household_type_size_registry.yaml`. Neither this file nor its
source metadata changes the size-only registry fingerprint or default artifacts.

```powershell
python -m societytwin.households --enable-households --type-size --size 10000 --seed 42 --output-root data/results/my-type-size-test
```

`--type-size` explicitly accepts the named national transfer and tail assumptions.
Both `--enable-households` and `--type-size` are required at the CLI; there is no
public API option. Internal callers pass `type_size=True` to the existing household
`build` entry point. The optional registry is activated only in memory.

Required ignored sources are the existing pinned size CSV plus byte copies of the
acquired Phase 2A sources: `data/raw/national_household_type_size_2025.csv` and
`data/raw/ankara_household_type_2025_source.csv`. The latter contains historical
rows but only 2025 Ankara rows are selected. The registry retains file hashes,
official URLs, geography/year, units, private-household universe and acquisition
limitations. The national CSV is a transcription of inspected official counts,
not a downloaded original PDF binary; redistribution terms remain an open decision.

Four **disjoint broad types** are used: `one_person`, `nuclear_family`,
`extended_family`, `non_family_multi_person`. Nuclear subtypes are reconciled in
source validation and are never counted in addition to their parent row. “Child”
in family composition can be an adult; no children or relationships are assigned.

Existing IPF fits a national 2025 **7 × 4** count seed to Ankara 2025 size (1–6/7+)
and type margins. Source not-applicable cells are excluded using verified semantic
support: one-person iff size 1; nuclear/no-family minimum 2; extended minimum 3.
Missing or suppressed observations are rejected. Mismatched totals, infeasible
support and nonconvergence fail explicitly; no silent column rescaling is allowed.

To retain Ankara's ten size margins, the model then applies the explicit policy
`exchangeable_within_observed_7plus_v1`: **the same type proportions are used for
sizes 7, 8, 9 and 10+**. This is a modelling assumption, not observed fine-size
evidence. The fitted coarse association remains the nationally transferred one;
no observed Ankara joint is claimed.

The sample has at least one record per positive fitted fine type/size cell; too
small requests fail. Remaining records are allocated proportionally using the
existing Hamilton routine and a separate deterministic random stream shuffles
them. Weights equal fitted cell households / cell sample records. Weighted size
and type margins match within strict numerical tolerance; raw record proportions
need not match the earlier size-only sample allocation. Sparse cells and effective
sample size are reported. No resident weights or records are used.

Optional outputs have schema `household-type-size-schema-1`, all v1 household
fields plus `household_type`, `household_type_size_band` and `provenance_profile`.
The band field records the source-compatible 1–6/7+ group, while size class retains
1–9/10+. Exact 10+ size and upper bound remain null. Artifacts use `hht-...` build
IDs and `SHT2025-...` household IDs, and the separate `TypeSizeStore` rejects schema
confusion with the v1 store. Model/registry/source versions, transferred geography,
both assumptions, fitted tables and IPF diagnostics are retained in the manifest.

Validation checks both Ankara marginals, fitted joint-cell expansion weights,
structural support, 35 transferable coarse log-odds contrasts for the real source,
positive finite weights, effective sample size, identity and absence of links.
Matching margins and association demonstrates implementation consistency, not
independent validation of Ankara household realism. At present the strategy is
appropriate only for controlled opt-in research; no household-resident linkage,
family relationships, housing, income or SES are enabled.
