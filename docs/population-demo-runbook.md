# Population Engine presentation runbook

Verified 3 November 2026 on native Windows, Python 3.12.10. This is a local,
offline demonstration using preserved artifacts. Do not rebuild controls or
regenerate populations during the presentation.

## What works today

The existing engine loads TÜİK aggregate controls, generates weighted synthetic
residents, checks source fit and logical constraints, selects adult cohorts,
projects personas and executes the MatrAIx PersonaJsonSurvey agent. Population
records, persona views and agent responses are distinct objects.

The demonstration uses the existing experimental `national_age_marital_seed_v1`
strategy: national broad-age marital associations are fitted to Ankara margins.
Only this optional strategy was enabled. Household production linking,
socioeconomic enrichment and graph enrichment are not part of this demo.

## Exact environment and inputs

Open PowerShell in the feature worktree root. Configure the following environment
variables locally (absolute paths are recommended; do not commit local values):

| Local setting | Required location |
|---|---|
| `DST_DEMO_DATA_ROOT` | Data directory containing the existing `raw/` and `results/investigation/controls` inputs and default bundle |
| `DST_DEMO_PYTHON` | Existing Python 3.12 interpreter with SocietyTwin dependencies |
| `DST_DEMO_MATRAIX_ROOT` | External compatible MatrAIx checkout |
| `DST_DEMO_RUNTIME_PYTHON` | Existing interpreter with MatrAIx, Harbor and Playground dependencies |

The experimental bundle and recorded results must also be available under this
worktree's ignored `data/results` paths listed below. Raw/processed data,
environments, evidence and generated artifacts are not included in Git. Configure
their local locations before running; no source copying or symlinks are needed.
The settings below affect this shell only.

```powershell
$repoRoot = (Resolve-Path -LiteralPath '.').Path
foreach ($setting in 'DST_DEMO_DATA_ROOT','DST_DEMO_PYTHON','DST_DEMO_MATRAIX_ROOT','DST_DEMO_RUNTIME_PYTHON') {
    if (-not [Environment]::GetEnvironmentVariable($setting)) { throw "Configure $setting locally first." }
}
$dataRoot = (Resolve-Path -LiteralPath $env:DST_DEMO_DATA_ROOT).Path
$python = (Get-Item -LiteralPath $env:DST_DEMO_PYTHON).FullName
$matraixRoot = (Resolve-Path -LiteralPath $env:DST_DEMO_MATRAIX_ROOT).Path
$runtimePython = (Get-Item -LiteralPath $env:DST_DEMO_RUNTIME_PYTHON).FullName
$bundle = "$repoRoot/data/results/marital-demo-builds/build-e3e7e727a1faecd302f29292fea8c5e4253084a850f46ca66b93bc23d0c6d00e"
$pidDemo = 'pop-06-2025-n10000-s42-national_age_marital_seed_v1-78dac9da43039964'
$env:PYTHONPATH = "$repoRoot/src"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:SOCIETYTWIN_REPO_ROOT = $repoRoot
$env:SOCIETYTWIN_CONTROLS_DIR = "$dataRoot/results/investigation/controls"
$env:SOCIETYTWIN_POPULATIONS_DIR = "$bundle/residents"
$env:SOCIETYTWIN_STATE_DIR = "$repoRoot/data/results/presentation-cli-$([guid]::NewGuid().ToString('N'))/state"
$env:SOCIETYTWIN_DEPENDENCY_REGISTRY = "$repoRoot/data/dependency_registry.yaml"
$env:SOCIETYTWIN_TUIK_PACKAGE = "$dataRoot/raw/tuik_package"
$env:SOCIETYTWIN_TUIK_MAPPING = "$repoRoot/data/tuik_package_mapping.yaml"
$env:SOCIETYTWIN_START_WORKER = '0'
$env:SOCIETYTWIN_ENABLE_LIVE_EXECUTION = '0'
$env:MATRAIX_ROOT = $matraixRoot
$env:SOCIETYTWIN_RUNTIME_PYTHON = $runtimePython
git branch --show-current
git rev-parse HEAD
git status --short
```

Expected branch: `feature/population-hybrid-households`; checkpoint base:
`aa3693c1e6638626cb5dfc687ab7f0e870ebef1f`. Use the presentation checkpoint
containing the portability and warning corrections on top of this base.
No packages need installing in the configured environments.

Other preserved input locations:

| Input | Location |
|---|---|
| Official local package | `$dataRoot/raw/tuik_package` |
| National marital transcription | `$dataRoot/raw/national_marital_seed_2025.yaml` |
| Default population bundle | `$dataRoot/results/unified-build/repeat-bundles/build-cc7bd130a2fa29d9615b6682df51d10f8f7279202a36beec9116954852474aed` |
| Experimental replay bundle | `$repoRoot/data/results/marital-demo-replay/build-e3e7e727a1faecd302f29292fea8c5e4253084a850f46ca66b93bc23d0c6d00e` |

The seed is a manual transcription of TurkStat *Youth in Statistics 2025*,
publication 4821, table 1.9, printed page 14 / PDF page 36. It contains national
percentages, not Ankara age-specific counts. Original PDF binary is not archived
locally. Midpoint reconstruction acknowledges unverified nearest-tenth rounding.
Seed SHA-256:
`55dbc9752f4e19617cd9803dced10811a1efdb7e0cdcc906adac878141fb796d`.

## Inspect and validate the preserved population

```powershell
& $python -B -m societytwin.national --help
& $python -B -m societytwin.national list
& $python -B -m societytwin.national validate $pidDemo
```

Expected: 10,000 records, Ankara, 5,910,320 represented residents, zero logical
constraint violations, four `fit_by_construction` and four
`within_sampling_noise` statuses, no unfitted margins. CLI list/validate initialize
SQLite only in the configured CLI state directory. The validation CLI displays
the saved report when available. For a fresh in-memory check against the original
controls, with no report or population writes:

```powershell
@'
from societytwin.config import load_settings
from societytwin.national.controls import read_store
from societytwin.national.store import PopulationStore
from societytwin.national.validation import validate, summarize
settings = load_settings()
controls = read_store(settings.national_controls_dir)
population = PopulationStore(settings.populations_dir).load('pop-06-2025-n10000-s42-national_age_marital_seed_v1-78dac9da43039964')
assert len(population.table) == 10000
assert controls.fingerprint == population.manifest['source_versions']['controls_fingerprint']
print(population.manifest['population_id'])
print(population.manifest['content_sha256'])
print(summarize(validate(population.columns(), population.manifest, controls)))
'@ | & $python -B -
```

Expected content fingerprints:

| Artifact | SHA-256 |
|---|---|
| Default population content | `e901eaa4839b9a8feb347cc9212bcf9466a9a689129b52dbaa7eb1f254b02428` |
| Experimental population content | `78dac9da4303996444ab89e296f69b2c081b937bcab477ac8737d12a5982158d` |
| Experimental Parquet file | `f2752dfb90e479fe143ee8efd0c487fc06c057d2336304a0f386e783701c37d2` |
| Shared control-store fingerprint | `2c0c5052a3df5b3dbdb0327956d28b60c7aa889f54bda964c31c1ea7b5cd0de5` |

Age/sex, marital/sex, education/sex and urbanicity/sex margins remain fitted in
both builds. Maximum experimental weighted marital error is about
`5.1e-12` percentage points. Existing logical constraints pass. Age, age group,
sex, education, urbanicity and design-weight record values are unchanged from
the baseline; final calibrated weights are the existing generator's output.

Teenagers aged 15–19: 712 records. R = record percentage; W = population-weighted
percentage, each within this age group.

| Status | Default count | Default R% / W% | Experimental count | Experimental R% / W% |
|---|---:|---:|---:|---:|
| Never married | 197 | 27.669 / 28.076 | 654 | 91.854 / 92.067 |
| Married | 430 | 60.393 / 60.596 | 55 | 7.725 / 7.551 |
| Divorced | 50 | 7.022 / 6.361 | 3 | 0.421 / 0.382 |
| Widowed | 35 | 4.916 / 4.967 | 0 | 0 / 0 |

The near-60% teenage-marriage artifact is removed, but 7.551% is a model output,
not a verified Ankara rate. Official marital calibration uses the **15+** source
universe; the adult agent cohort uses **18+**. Do not conflate them.

## Personas and exact offline demo command

The existing adult-only cohort sampler selects five residents, stratified by
marital status, seed 42. Membership is deterministic; no hand-assigned attributes.

| Synthetic ID | Age group shown | Audit-only exact age | Sex | Marital status | Completed education |
|---|---|---:|---|---|---|
| ST2025-06-0009106 | 65–69 | 66 | Female | Divorced | Upper secondary |
| ST2025-06-0003294 | 25–29 | 29 | Male | Married | Higher education |
| ST2025-06-0008016 | 55–59 | 55 | Male | Married | Upper secondary |
| ST2025-06-0005452 | 35–39 | 39 | Female | Married | Upper secondary |
| ST2025-06-0002829 | 20–24 | 20 | Male | Never married | Higher education |

Existing `build_persona()` / `matraix_persona()` preserve source-supported values.
The actual MatrAIx schema/loader accepts all five documents. Native enum fields
are checked; `dst_*` fields are custom extensions, not native schema claims.
Assumed exact ages stay hidden; age groups are shown. Labour and both household
fields remain null for 100% of population records and are unavailable/omitted
in agent prompts. Resident IDs, weights and source provenance do not leak into
captured prompts; traceability metadata remains in stored files.

The completed demo can be shown directly from recorded results. To execute the
same existing integration again, select a fresh directory automatically:

```powershell
$freshDemo = "$repoRoot/data/results/presentation-matraix-$([guid]::NewGuid().ToString('N'))"
@'
import json, sys
from pathlib import Path
from societytwin.config import load_settings
from societytwin.registry.store import Registry
from societytwin.agents.matraix_runtime import MatraixRuntime
from societytwin.national.service import NationalService
from societytwin.national.cohorts import CohortDefinitionRequest, CohortSampleRequest
from societytwin.national.store import PopulationFilter
from societytwin.national.personas import build_persona, matraix_persona
from societytwin.national.experiments import ExperimentDefinition, example_fare_definition

output = Path(sys.argv[1]).resolve()
settings = load_settings()
assert output.is_relative_to((settings.repo_root / 'data/results').resolve())
output.mkdir(parents=True, exist_ok=False)
settings = settings.with_overrides(state_dir=output / 'state', start_worker=False, live_execution_enabled=False)
settings.state_dir.mkdir()
registry = Registry(settings.registry_path)
service = NationalService(settings, registry, MatraixRuntime(settings))
try:
    pid = 'pop-06-2025-n10000-s42-national_age_marital_seed_v1-78dac9da43039964'
    population = service.populations.load(pid)
    assert len(population.table) == 10000 and population.validation['constraint_violations'] == 0
    assert population.manifest['content_sha256'] == '78dac9da4303996444ab89e296f69b2c081b937bcab477ac8737d12a5982158d'
    assert service.store().fingerprint == population.manifest['source_versions']['controls_fingerprint']
    cohort = service.create_cohort(CohortDefinitionRequest(name='Presentation adults', population_id=pid,
                                  filters=PopulationFilter(adult_only=True)))
    sample = service.draw_sample(cohort['cohort_id'], CohortSampleRequest(
        size=5, method='stratified', strata_field='marital_status', seed=42))
    catalog = json.loads((settings.matraix_root / 'persona/schema/dimensions.json').read_text(encoding='utf-8'))
    projected = [matraix_persona(build_persona(population.record(m['synthetic_id']), population.manifest), catalog=catalog)
                 for m in sample['members']]
    definition = example_fare_definition(cohort['cohort_id'], seed=42)
    definition['cohort'].update(sample_size=5, sampling_method='stratified', strata_field='marital_status')
    definition['environment'] = {'province_code':'06', 'context_indicators':[]}
    definition['model'].update(backend='matraix', transport='fake', temperature=0)
    definition['execution'].update(max_calls=5)
    exp = service.create_experiment(ExperimentDefinition.model_validate(definition))
    plan = service.plan(exp['experiment_id'])
    assert plan['executable'], plan['blockers']
    run = service.start_run(exp['experiment_id'], plan['plan_hash'], 'presentation-offline')['run']
    assert service.claim_and_run('presentation')
    view = service.run(run['run_id'])
    assert view['run']['state'] == 'completed', view['run']
    assert view['run']['valid_responses'] == 5 and view['run']['provider_calls'] == 0
    responses = service.run_responses(run['run_id'], True, 0, 100)
    for name, payload in [('summary.json', view), ('responses.json', responses),
                          ('selected.json', sample), ('projected.json', projected)]:
        with (output / name).open('x', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(view['run'], indent=2))
finally:
    registry.close()
'@ | & $python -B - $freshDemo
if ($LASTEXITCODE -ne 0) { throw 'Offline demo failed; inspect the retained logs.' }
Get-Content -LiteralPath "$freshDemo/summary.json" -Raw -Encoding UTF8 | ConvertFrom-Json | Select-Object -ExpandProperty run
```

This inline recipe calls existing APIs and uses only the configured variables;
it does not depend on ignored machine-specific helper scripts. It loads the
existing population (never regenerates it), creates a fresh local registry,
projects personas against the actual catalog, and executes the existing agent
and upstream loader with fake transport only. It refuses existing output
directories. The original fare scenario source is
unchanged: hypothetical 40 TL → 48 TL, one single-choice question per persona.

Expected: five completed trials, five valid responses, zero provider calls.
Each fake answer is `continue_public_transport` with an explicit synthetic smoke
rationale. Matching fake answers are intentional, not evidence of consensus.
New runs store the run view in `summary.json`, sample membership in `selected.json`,
and responses/projections alongside them. Actual prompts and upstream survey
outputs are under `state/national_runs/<run-id>/matraix_batch_1/trial_*`.

## Recorded outputs and reports

Paths below are relative to the feature worktree. All are ignored local artifacts.

| Evidence | Location |
|---|---|
| Population comparison report and detailed CSVs | `data/results/marital-demo-evaluation-20261103/report.md` |
| Offline integration report | `data/results/matraix-demo-20261103/report.md` |
| Original successful offline run | `data/results/matraix-demo-20261103/offline-success` (`run_828e6e49f660`) |
| Independent offline replay | `data/results/matraix-demo-20261103/determinism-replay` (`run_441f6b27df2e`) |
| Final verification with corrected warning | `data/results/final-demo-audit-20261103/offline-verification` (`run_1a84317ac477`) |
| Fresh population/coverage/checksum audit | `data/results/final-demo-audit-20261103/verification.json` |
| Full final test results | `data/results/final-demo-audit-20261103/tests-complete.xml` |

Inside an offline run directory, open `selected.json`, `schema-validation.json`,
`summary.json`, `captured-prompts.json`, `responses.json` and `run.json`.
Agent files are under `state/national_runs/<run-id>/matraix_batch_1/`: `batch.log`,
`batch_report.json`, and `trial_0000` through `trial_0004`, each containing
`persona.yaml`, `trial_result.json` and the survey output under
`artifacts/app/output/survey_result.json`. Selection, projected persona documents,
transport-boundary prompts and answers match across all three recorded runs.

The older offline report and its immutable saved plan retain the original stale
sex-only warning. New plans now correctly disclose the experimental national
broad-age transfer, assumed rounding and unverified Ankara joint realism. This
is a wording-only correction in `NationalService.plan()`; old evidence was not
rewritten.

## Tests and preservation

Final suite: **238 passed, 2 skipped**, including all **35 tests/build** cases,
national generator/validation/API/cohort tests, Windows CLI tests, persona
contracts, actual MatrAIx schema/template checks, national and historical offline
runtime tests, and Windows launcher portability tests. The two skips require
unavailable disposable sidecar fixtures; the actual demo population and external
runtime were exercised. Four existing warnings concern unregistered pytest
markers and Starlette/httpx deprecation. No unresolved product failures.

An initial test invocation failed because its chosen temporary parent directory
did not exist. That execution mistake was corrected without product changes;
the successful full suite is recorded separately. No baseline code failure was
observed in the completed suite. `git diff --check` passed.

To repeat the suite without reusing a prior pytest directory:

```powershell
$env:SOCIETYTWIN_TEST_MATRAIX_ROOT = $env:MATRAIX_ROOT
$env:SOCIETYTWIN_TEST_RUNTIME_PYTHON = $env:SOCIETYTWIN_RUNTIME_PYTHON
$env:SOCIETYTWIN_TEST_PROJECTION_ROOT = $env:MATRAIX_ROOT
$env:SOCIETYTWIN_TEST_PROJECTION_PYTHON = $env:SOCIETYTWIN_RUNTIME_PYTHON
$testRun = "$repoRoot/data/results/presentation-tests-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $testRun -ErrorAction Stop | Out-Null
& $python -B -m pytest -p no:cacheprovider -ra tests/build tests/national tests/integration/test_matraix_national.py tests/integration/test_matraix_runtime.py tests/integration/test_matraix_projection_contract.py tests/integration/test_runtime_portability.py --basetemp="$testRun/temp" --junitxml="$testRun/results.xml"
git diff --check
```

Tests generate artificial temporary fixture artifacts, not replacements for the
preserved Ankara demo. Prior checksum records (189 and 303 protected paths)
were rechecked: only the authorized source edits differ; original raw inputs,
controls, manifests, populations and evidence remain unchanged. No generation
algorithm, weight, registry default, crosswalk or household guard changed.

## Two-to-three-minute presentation sequence

1. **0:00–0:30:** Explain synthetic records → adult cohort → persona → active
   survey agent. Show the preserved 10k listing and experimental label.
2. **0:30–1:00:** Run the saved validation command. Explain that source-fit and
   zero declared constraints are narrower than demographic realism. Show the
   teenage comparison and the national-transfer limitation.
3. **1:00–1:40:** Show one projected persona and the five-person selection.
   Point out preserved age group/sex/marital attributes, missing labour/household
   fields, and provenance outside the model prompt.
4. **1:40–2:30:** Show the completed run summary and one captured prompt/response,
   or execute the fresh offline command. Confirm five valid responses and zero
   provider calls. Explain that fake answers prove wiring, not human behavior.

## Limits and claims to avoid

| Assessment | Evidence and boundary |
|---|---|
| Source fit | Available official margins match; these are fitting targets, not held-out validation. |
| Conditional plausibility | Teenage anomaly is reduced; national 15–24/25+ transfer does not observe Ankara five-year-age joints or an elderly gradient. Rounding remains assumed. |
| Runtime integration | Actual schema, persona loader, agent, prompt capture and structured response persistence work offline. |
| Real-world behavior | Not validated. No live model or causal/behavioral prediction was tested. |

Do not claim a fully realistic population, known Ankara teenage rates,
behaviorally predictive responses, household membership, family relationships,
individual employment/income, or a production-approved experimental model.
Education still uses sex margins and existing permissive minimum completion
ages. Zero sampled teenage widows is not a structural population zero.

## Windows troubleshooting and handoff

- **Wrong branch/defaults:** check `Get-Location`, branch and HEAD. Set the
  absolute `PYTHONPATH` and `SOCIETYTWIN_REPO_ROOT` above; never switch the parent
  checkout. The default registry stays disabled for future generation; loading
  this saved experimental population does not require enabling it.
- **Missing controls/population:** the feature defaults are not the shared input
  locations. Reapply this shell setup. Do not run `build-controls` to repair a
  path mistake. Existing readers must continue verifying checksums.
- **Missing dependencies:** use the two explicit interpreters; system Python
  lacks the project dependencies. Paths containing spaces need quotes and `&`.
- **`resource` import crash:** use the checkpoint containing the CLI portability fix.
  Windows benchmark RSS is explicitly unavailable; no safety limit is removed.
- **Unicode corruption, WinError 10106 or missing home:** preserve the runtime
  launcher fix: isolated `-X utf8`, UTF-8 capture, Windows `SystemRoot`, and managed
  `USERPROFILE`/temporary paths. Do not remove isolation or pass provider keys.
- **Existing output directory:** choose a fresh path. Retain failed logs and
  preserve successful artifacts. Never overwrite either population.
- **Live model requested:** stop; use `backend=matraix`, `transport=fake`. No
  provider credentials are required. The adapter strips inherited credentials
  and points offline proxies at a closed port.

This checkpoint publishes code, tests and documentation for the bounded,
honestly labelled demonstration. Official data, local evidence, environments,
ignored helpers and recorded outputs are not included in Git. A repository
publication alone is not a data/artifact handoff; configure the local prerequisites
above. The inline execution recipe works without the ignored helpers.
