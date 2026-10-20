# Optional resident enrichment

The experimental `registry_conditional_categorical_v1` module writes separate resident-ID sidecars. It is disabled by default and is not called by the resident generator, persona exporter or public API. Core columns and all weights stay unchanged.

`data/resident_extension_registry.yaml` declares a typed extension bound to the Phase 1 registry version and fingerprint. It reuses Phase 1 typed definitions and compatibility validation, then validates its own supported source dimensions, universes and assignment contract. It cannot override core attributes. Only province/sex-conditioned categorical assignment is currently executable; unsupported dimensions and methods fail. No executable configuration expressions are accepted.

The first declaration is Ankara 2025 `degurba_class`, drawn using observed province × sex × DEGURBA counts. Independence from other resident attributes within sex is a **modelling assumption**, not an observed relationship. This is a synthetic class, not an address or district. It is distinct from existing administrative `urbanicity`.

Required local input: `data/raw/ankara_degurba_sex_2025.csv`, the checksum-pinned six-cell extract of `data/raw/tuik_package/population_urban_rural.csv`. Source observations, derivation, checksums and official links are recorded in the investigation report and configuration. These evidence files are ignored local inputs; obtaining them is required on another checkout. Missing sources fail unless explicitly configured `unavailable`, which emits `unsupported` rather than drawing fabricated values.

An explicit internal invocation is:

```powershell
python -m societytwin.enrichment --enable-enrichment --population-root data/results/my-residents --population-id <population-id> --seed 42 --output-root data/results/my-extensions
```

The output directory must be separate from resident storage and under ignored `data/results`. Each immutable `ext-<sha256>` directory contains `attributes.parquet`, `manifest.json` and `validation.json`. Schema `resident-extension-schema-1` has one `synthetic_id` row per resident and a typed list of unique attribute entries: `attribute`, nullable `value`, `status`, `provenance_profile`. Readers require the original population and verify its full column/weight content hash, sidecar identity, schema, checksum, categories, IDs and deterministic seed replay. Source snapshots in manifests permit validation without a later source-file download. Deterministic bytes are verified in the pinned environment; cross-version Arrow byte identity is not guaranteed.

Statuses distinguish `assigned`, `published_unknown` (only when the source declares an unknown category), `not_reported`, `unsupported` and `outside_universe`. A partly nonreported conditional distribution is not renormalized: the whole affected group remains nonreported. Observed zero counts remain zero; missing counts never become zero. Universe eligibility is checked before missing-source status. Available group totals must match eligible core weights; incompatible denominators are rejected.

Assignment uses separate existing SHA-256 categorical streams per attribute and sex, traversing sorted IDs. No IPF or reweighting occurs: changing person weights to fit an optional class could break core controls. New weighted margins fluctuate around observed counts. Reports include conditional weighted standard errors, calculated from fixed core weights, and four-standard-error diagnostics. These are implementation/sampling checks, not evidence of realistic age, household or behavioural relationships.

Foreign-national status, birthplace relation and literacy remain deferred. This module does not resolve education coverage, add household links or modify default persona fields. Unified build orchestration and explicit evidence-aware persona selection are now implemented in their separate modules. Sidecar generation has no public API endpoint; the shared experiment request model now exposes optional persona selection and needs explicit API/snapshot review. Current status and compatibility gates are in [the handover](CURRENT_SYSTEM_HANDOVER.md); verified source/setup requirements are in [the data guide](population-data-setup.md).
