# MatrAIx Simulation Experiment

This folder contains the clean SocietyTwin/MatrAIx simulation that was tested locally. It keeps MatrAIx as an external framework dependency and tracks only the SocietyTwin-specific scripts, small derived fixtures, and two deterministic Ankara personas needed to reproduce the smoke and A/B runs.

## Setup

Use Python 3.12. Install SocietyTwin experiment dependencies and the dependencies required by your local MatrAIx checkout:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r experiments\matraix_simulation\requirements.txt
$env:MATRAIX_ROOT = (Resolve-Path ..\MatrAIx-Persona-8B).Path
.\.venv\Scripts\python -m pip install -e "$env:MATRAIX_ROOT" -e "$env:MATRAIX_ROOT\packages\playground"
.\.venv\Scripts\python -m pip check
```

MatrAIx is not vendored here. Clone or place the MatrAIx framework somewhere local, then either put it next to this repository as `../MatrAIx-Persona-8B` or pass `--matraix-root` to the scripts.
Use editable installation: the framework's regular wheel omits the persona `.md.j2`
templates, which prevents the existing survey runner from rendering persona context.

## API Keys

The zero-cost smoke run does not need an API key. Live A/B execution requires a provider key. Copy `.env.example` to `.env` inside this folder and fill in only your provider's key, or export the key in your shell. `.env` is ignored by git.

## Model Selection

For live execution, choose an explicit provider/model with `--model`, for example:

```powershell
.\.venv\Scripts\python experiments\matraix_simulation\src\runtime\run_matraix_ab.py --model anthropic/claude-sonnet-4-5
```

If `--model` is omitted, the script asks MatrAIx to resolve the persona model from its normal environment configuration.
Use `MATRIX_PERSONA_MODEL` in the ignored `.env` or shell environment. Run all commands
from the SocietyTwin repository root, using `.\.venv\Scripts\python` rather than the
global Python interpreter. The A/B runner reads its `.env` before resolving defaults;
the smoke runner uses shell `MATRAIX_ROOT` or `--matraix-root`.

## Run

Validate the actual MatrAIx survey agent wiring without making provider calls:

```powershell
.\.venv\Scripts\python experiments\matraix_simulation\src\runtime\run_matraix_smoke.py --matraix-root "$env:MATRAIX_ROOT"
```

Prepare a two-persona A/B run without live calls:

```powershell
.\.venv\Scripts\python experiments\matraix_simulation\src\runtime\run_matraix_ab.py --matraix-root "$env:MATRAIX_ROOT" --model anthropic/claude-sonnet-4-5
```

Execute exactly two live model calls:

```powershell
.\.venv\Scripts\python experiments\matraix_simulation\src\runtime\run_matraix_ab.py --matraix-root "$env:MATRAIX_ROOT" --model anthropic/claude-sonnet-4-5 --execute --output-dir experiments\matraix_simulation\runs\matraix_ab_live
```

Generated run outputs go under `runs/` and are ignored.

## First One-Persona API Test

Put your own `ANTHROPIC_API_KEY` in the ignored experiment `.env`, and select an
available model with `MATRIX_PERSONA_MODEL=anthropic/claude-sonnet-4-5` (or another
supported provider/model and its matching key). The following command uses the
existing agent and artifact adapter for just `test_persona.yaml`. It loads both
personas during preflight, but runs only persona A. SDK retries are disabled and
Anthropic output is capped at 2048 tokens, matching the A/B runner. Use a fresh
output directory for each deliberate live test. This command makes a paid call.

```powershell
@'
import asyncio, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path('experiments/matraix_simulation').resolve()))
from src.runtime import run_matraix_ab as ab
ab.load_env_file(ab.ROOT / '.env')
repo = ab.default_matraix_root().resolve()
ab.setup_imports(repo)
from playground.persona_model import resolve_persona_model
from playground.model_client import build_json_client
from playground.inprocess import survey_eval
from matraix.agents.persona.json_survey import PersonaJsonSurvey
from harbor.models.agent.context import AgentContext
output = ab.ROOT / 'runs' / 'first_persona_api'
assert not output.exists(), 'Choose a fresh output directory'
plan, instrument = ab.prepare(repo, output, resolve_persona_model(), 0)
assert plan['credentials_present'], 'Set your provider key in the ignored .env'
client = build_json_client(plan['model'], temperature=0)
if plan['provider'] == 'anthropic':
    client.max_tokens = 2048
elif hasattr(client, '_client'):
    client._client = client._client.with_options(max_retries=0)
trial = output / 'trial_A'
logs = trial / 'agent'
logs.mkdir(parents=True)
agent = PersonaJsonSurvey(logs_dir=logs, persona_path=str(ab.PERSONAS[0]), survey_task_path=str(repo / ab.TASK), model_name=plan['model'])
async def run():
    environment = ab.ArtifactEnvironment(trial)
    await agent.setup(environment)
    with patch.object(survey_eval, 'build_json_client', lambda model: client):
        await agent.run(instruction='', environment=environment, context=AgentContext())
asyncio.run(run())
print(trial / 'artifacts/app/output/survey_result.json')
'@ | .\.venv\Scripts\python -
```

## Clean Environment Verification

Verified on Windows with Python 3.12.10, Pydantic 2.14.1, pydantic-core 2.50.1,
and the local MatrAIx checkout at revision
`3633d8dab149a9482a71b024418a49ae828cc941`. Both frameworks were installed
editable into an isolated `.venv` with system site-packages disabled.
`pip check`, all simulation module imports, both persona YAMLs and templates,
the survey configuration, the one-persona smoke (nine answers), and two-persona
preflight passed. The one-persona API command above was also checked using the
deterministic mock transport. External connections were blocked during the mock
runs; no provider calls were made. Live credentials/model availability remain
untested. Dependency lower bounds are not a frozen environment lock.

## What Is What

MatrAIx provides the external framework: the survey agent, persona loader/renderer, task content loader, model client, and the existing `application/tasks/example-survey_product-feedback` task.

SocietyTwin work in this folder includes:

- `src/data_processing/`: deterministic extraction/validation code for Ankara TÜİK-derived controls.
- `src/synthetic_population/`: deterministic Ankara synthetic population sampler and marital-status enrichment.
- `src/persona_adapter/`: conversion from a SocietyTwin synthetic resident to a MatrAIx persona YAML.
- `src/runtime/`: smoke and A/B runners that verify prompt conditioning and optionally execute live model calls.
- `processed/`, `synthetic/`, `personas/`: small reproducibility fixtures used by the tested simulation.

Raw TÜİK downloads, `.env`, provider keys, caches, virtual environments, and generated run outputs are intentionally excluded.
