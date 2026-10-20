# Unified Ankara build workflow

`python -m societytwin.build` coordinates the existing resident, enrichment and household generators. It introduces no statistical method, API, frontend, persona change or person–household link. Configuration schema is `ankara-build-config-1`; unknown fields and unsupported options fail validation.

Use a Python environment with this project's dependencies and `src` on `PYTHONPATH` (or an installed package). Read-only existing controls must already have been built using the existing `python -m societytwin.national build-controls` workflow. Unified builds do not rebuild or overwrite controls. Supply their directory in `inputs.controls_directory`; relative paths resolve against the repository, not the YAML file's directory.

```powershell
$env:PYTHONPATH='src'
python -m societytwin.build run --config data/build_configs/ankara-core.yaml
python -m societytwin.build run --config data/build_configs/ankara-optional.yaml
python -m societytwin.build inspect data/results/unified-populations/<build-id>
```

The core example uses 10,000 Ankara 2025 residents, seed 42, with all optional features off. The optional example explicitly enables DEGURBA, the midpoint marital sensitivity policy and 10,000 separate type × size household records. **It accepts experimental assumptions** documented in the component reports, including unverified nearest-tenth marital rounding, national-to-Ankara transfers and household 7+ tail exchangeability. It does not establish observed Ankara individual joints. The 10,000-resident marital pilot remains experimental; 1,000-record builds are diagnostic and may retain unfitted margins.

Configurable fields:

|Field|Supported values/default|
|---|---|
|`province_code`, `reference_year`|Only `'06'`, `2025` in this bounded workflow|
|`resident_sample_size`, `seed`|100–1,000,000; nonnegative integer seed, default 10,000 / 42|
|`resident_enrichments`|Default empty; supported entry `degurba_class`|
|`marital.strategy`|`default` or `national_age_marital_seed_v1`|
|`marital.sensitivity`|Required only for opt-in strategy: `lower_quartile`, `midpoint`, `upper_quartile`|
|`marital.acknowledge_unverified_rounding`|Must be true for opt-in strategy; default false|
|`households.enabled`, `sample_size`|Default false / 1,000; household sample size is independent of resident count|
|`households.strategy`|`size_only` default, or enabled-only `national_household_type_size_seed_v1`|
|`inputs`|Existing control directory and optional paths to the four component registry YAMLs; see typed defaults in `build/config.py`|
|`output_root`|Default `data/results/unified-populations`; must be under feature-worktree ignored `data/results`, separate from inputs and existing artifacts|
|`validation`|Existing calibration tolerance, familywise alpha, minimum noise-test group size; constraint failures block publication by default; `fail_on_unfitted_margins` defaults false|

Numeric limits do not guarantee adequate sampled support. Existing generators reject infeasible small household samples and report core margin drops. Validation always runs; it cannot be disabled. Use `validation.fail_on_unfitted_margins: true` to require all requested resident calibration margins. Sampling deviations and inherited universe scaling remain visible in component validations. No weight is changed by orchestration.

Selected sources are checksum-verified in preflight using the existing readers. Optional source requirements are in `docs/resident-enrichment.md`, `docs/unlinked-households.md` and their registries; ignored local evidence must be acquired separately on a new checkout. Required missing data fails before generating artifacts. Declared enrichment `unavailable` policy remains supported and produces explicit unsupported values; it never invents observations. The unified identity records that evidence state.

Outputs:

```text
<output_root>/build-<sha256>/
  build-manifest.json
  validation.json
  residents/pop-.../{records.parquet,manifest.json,validation.json}
  enrichments/ext-.../{attributes.parquet,manifest.json,validation.json}  # optional
  households/hh-.../{households.parquet,manifest.json,validation.json}   # optional size-only
  households/hht-.../{households.parquet,manifest.json,validation.json}  # optional type × size instead
```

Historical component readers still work against these component roots. The unified manifest records strategy/sensitivity settings, complete selected registry snapshots (including source/version/assumption metadata), verified control-file hashes and provenance, code-content fingerprint, runtime versions, child IDs/content hashes, file checksums and validation summaries. It declares `household_person_linkage: false`. Household weights represent households; resident weights represent persons; neither is rescaled to the other's denominator. Exact household member counts remain unknown for 10+.

Build identity excludes output location and input path selection, using selected contents/configuration instead. It includes code and runtime versions so local uncommitted implementation changes cannot silently reuse an older bundle. Repeated requests reuse an existing verified complete bundle without rewriting it. Independent fresh builds reproduce records, IDs, weights, Parquet data and optional component artifacts in the same environment. Existing resident generation/writing timestamps and timings remain operational metadata, so their manifests and the unified file-checksum lists can differ across fresh roots. Cross-version Arrow byte identity is not promised.

Everything is generated in a private staging directory beneath the output root, checked, then published by a single same-filesystem directory rename. Ordinary failures clean staging and publish no output set; corrupt or incomplete existing destinations are refused. Abrupt process termination may leave hidden staging debris, never a published partial bundle. This is local filesystem publication, not a distributed transaction. The workflow does not alter external controls or global population registries.

`inspect` verifies the bundle inventory and all component readers/checksums, sidecar referential integrity and child schema/size/content identities. It requires compatible installed component/parent-registry readers. The workflow does not add enrichment to default persona representations. Evidence-aware, explicitly requested persona enrichment is now implemented separately in `national/persona_selection.py`; the shared HTTP experiment schema still needs the API/snapshot review recorded in [the current handover](CURRENT_SYSTEM_HANDOVER.md). See [data setup](population-data-setup.md) for current input contracts and the verified Windows control-build workaround.
