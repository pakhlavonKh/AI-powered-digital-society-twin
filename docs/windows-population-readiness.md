# Native Windows population execution

Local presentation setup verified on 2026-11-03, Python 3.12.10. Execute from
the root of the `feature/population-hybrid-households` worktree.
No installation, source copying, symlinks or default configuration changes are needed.

## Existing population: help, list and validation

Run in PowerShell from the feature worktree. Configure `DST_DEMO_DATA_ROOT`
locally to the directory containing the existing `raw/` and `results/` inputs,
and `DST_DEMO_PYTHON` to an existing Python 3.12 interpreter with this project's
dependencies. These locations are not supplied by Git. The data directory may
belong to a separate checkout; do not select that checkout's source code.
These settings affect this shell only.

```powershell
$repoRoot = (Resolve-Path -LiteralPath '.').Path
if (-not $env:DST_DEMO_DATA_ROOT -or -not $env:DST_DEMO_PYTHON) {
    throw 'Configure DST_DEMO_DATA_ROOT and DST_DEMO_PYTHON locally first.'
}
$dataRoot = (Resolve-Path -LiteralPath $env:DST_DEMO_DATA_ROOT).Path
$python = (Get-Item -LiteralPath $env:DST_DEMO_PYTHON).FullName
$env:PYTHONPATH = "$repoRoot/src"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:SOCIETYTWIN_REPO_ROOT = $repoRoot
$env:SOCIETYTWIN_CONTROLS_DIR = "$dataRoot/results/investigation/controls"
$env:SOCIETYTWIN_POPULATIONS_DIR = "$dataRoot/results/unified-build/repeat-bundles/build-cc7bd130a2fa29d9615b6682df51d10f8f7279202a36beec9116954852474aed/residents"
$env:SOCIETYTWIN_STATE_DIR = "$repoRoot/data/results/windows-readiness-$([guid]::NewGuid().ToString('N'))/state"
$env:SOCIETYTWIN_TUIK_PACKAGE = "$dataRoot/raw/tuik_package"
$env:SOCIETYTWIN_TUIK_MAPPING = "$repoRoot/data/tuik_package_mapping.yaml"
$env:SOCIETYTWIN_DEPENDENCY_REGISTRY = "$repoRoot/data/dependency_registry.yaml"
$env:SOCIETYTWIN_START_WORKER = '0'
$env:SOCIETYTWIN_ENABLE_LIVE_EXECUTION = '0'
& $python -B -m societytwin.national --help
& $python -B -m societytwin.national list
& $python -B -m societytwin.national validate pop-06-2025-n10000-s42-e901eaa4
```

The list/validate commands initialize SQLite in the isolated state directory;
they do not change the population or controls. CLI validation displays the saved
report when one exists. For a fresh source-fit check without writing a report:

```powershell
@'
from societytwin.config import load_settings
from societytwin.national.controls import read_store
from societytwin.national.store import PopulationStore
from societytwin.national.validation import validate, summarize
settings = load_settings()
controls = read_store(settings.national_controls_dir)
population = PopulationStore(settings.populations_dir).load('pop-06-2025-n10000-s42-e901eaa4')
assert controls.fingerprint == population.manifest['source_versions']['controls_fingerprint']
print(summarize(validate(population.columns(), population.manifest, controls)))
'@ | & $python -B -
```

Expected: 10,000 records; content SHA-256
`e901eaa4839b9a8feb347cc9212bcf9466a9a689129b52dbaa7eb1f254b02428`;
controls fingerprint
`2c0c5052a3df5b3dbdb0327956d28b60c7aa889f54bda964c31c1ea7b5cd0de5`.
Readers retain their existing checksum checks. Source-fit success does not
validate the age relationships of the demographic attributes.

`resource` supplies benchmark peak-RSS telemetry only. Unix retains its existing
`getrusage(RUSAGE_SELF)` measurement and units. When the module is unavailable,
benchmark JSON reports null RSS and unit plus an explicit explanation. No
resource-limit enforcement is removed. Benchmark and generation write artifacts;
neither is required for inspecting this saved population.

## Existing external runtime (not required for population commands)

Configure `DST_DEMO_MATRAIX_ROOT` to the external MatrAIx checkout and
`DST_DEMO_RUNTIME_PYTHON` to its existing compatible Python environment.
Neither the checkout nor its environment is included in Git. The presentation
runbook maps these settings to `MATRAIX_ROOT` and `SOCIETYTWIN_RUNTIME_PYTHON`.
The existing runner bootstrap imports successfully. No provider or smoke run is
part of Windows population readiness.

## Optional isolated experimental marital build (reference only)

The preserved presentation build is already complete; do not rerun this recipe
for the demo. This reference recipe uses
the existing strategy and checksum verification, with no household or settlement
modules enabled. Do not use the broader `ankara-optional.yaml` for this bounded
demo. National 15-24/25+ transfer and unverified rounding remain experimental.

For a separately authorized future build, use the shell setup above, then:

```powershell
@'
from pathlib import Path
import os
import yaml
from societytwin.build.config import BuildConfig, Inputs, Marital, Validation
from societytwin.national.dependencies import load_registry, DependencyRegistry

repo = Path(os.environ['SOCIETYTWIN_REPO_ROOT']).resolve()
data = Path(os.environ['DST_DEMO_DATA_ROOT']).resolve()
assert Path.cwd().resolve() == repo
inputs = repo / 'data/results/marital-demo-inputs'
output = repo / 'data/results/marital-demo-builds'
if inputs.exists() or output.exists():
    raise SystemExit('Choose fresh demo input/output directories; preserve existing artifacts.')
payload = load_registry().model_dump(mode='json')
# Keep the registry default disabled; only the unified demo config activates it.
assert payload['marital_strategy']['enabled'] is False
payload['marital_strategy']['source_file'] = str(data / 'raw/national_marital_seed_2025.yaml')
DependencyRegistry.model_validate(payload)
config = BuildConfig(
    resident_sample_size=10000, seed=42,
    marital=Marital(strategy='national_age_marital_seed_v1', sensitivity='midpoint',
                    acknowledge_unverified_rounding=True),
    inputs=Inputs(controls_directory=data / 'results/investigation/controls',
                  resident_registry=inputs / 'resident-registry.yaml'),
    output_root=output,
    validation=Validation(fail_on_unfitted_margins=True),
)
inputs.mkdir(parents=True, exist_ok=False)
with (inputs / 'resident-registry.yaml').open('x', encoding='utf-8') as handle:
    yaml.safe_dump(payload, handle, sort_keys=False)
with (inputs / 'marital-demo.yaml').open('x', encoding='utf-8') as handle:
    yaml.safe_dump(config.model_dump(mode='json'), handle, sort_keys=False)
print(inputs / 'marital-demo.yaml')
'@ | & $python -B -
if ($LASTEXITCODE -ne 0) { throw 'Demo preparation failed; do not build.' }
& $python -B -m societytwin.build run --config "$repoRoot/data/results/marital-demo-inputs/marital-demo.yaml"
```

The unified workflow reads `inputs.controls_directory` from its configuration;
it does not use `SOCIETYTWIN_CONTROLS_DIR`. Its existing preflight verifies the
seed checksum before generation. This recipe does not redirect the ordinary
national CLI to the experimental registry, alter source hashes or overwrite the
saved population. Inspect and independently audit the resulting bundle before
presenting it. No claim of production eligibility follows from this recipe.
