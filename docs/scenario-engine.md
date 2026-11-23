# Scenario Engine Architecture & Workflow Guide

The **Scenario Engine** is the policy modeling, natural language compilation, and demographic simulation bridge of the **AI-Powered Digital Society Twin**. It transforms conversational policy questions and municipal interventions into calibrated, demographic-aware experiments executed by synthetic citizen personas.

---

## 1. System Overview & Purpose

Policy analysts, researchers, municipal planners, and entrepreneurs rarely formulate policy in terms of low-level JSON configuration files or database schemas. Instead, they ask questions such as:

> *"What if bus and subway fares in Ankara increase by 30%? Will people switch to walking or driving?"*  
> *"What is the best location to open a cafe in Ankara?"*  
> *"Simulate an 18% electricity tariff increase in Bursa for residential households."*  
> *"How would university students in Istanbul respond to a 50% discount on transit passes?"*

The **Scenario Engine** bridges the gap between natural language questions and persona-conditioned agent experiments. It automatically:
1. **Extracts Geographic Context**: Identifies provinces across all 81 Turkish provinces (handling Turkish diacritics and apostrophized suffixes like *Ankara'da*, *Bursa'da*, *İstanbul'da*).
2. **Classifies Policy Domains**: Identifies domain types (`transportation`, `university_placement`, `university_policy`, `housing`, `energy`, `economic`, `education`, `public_policy`).
3. **Calibrates Economic & Policy Parameters**: Infers baseline tariffs, proposed tariffs, percentage shifts, currency units, or business feasibility constraints.
4. **Determines Target Demographics**: Infers age ranges, income strata, or household types eligible for the scenario.
5. **Synthesizes Question Formats**:
   - **Single Choice**: Calibrated, balanced, non-leading multiple-choice options.
   - **Free-Text (Qualitative)**: Open-ended questions eliciting rich citizen perspectives in their own words.
6. **Screens Persona Eligibility**: Evaluates synthetic citizens against policy rules before prompting models.
7. **Validates AI Citizen Responses**: Strictly verifies agent choices against declared schemas, rejecting hallucinations.
8. **Synthesizes Executive Summaries**: Automatically generates comprehensive executive reports and qualitative takeaways using LLM intelligence or deterministic rule-based analysis.

---

## 2. End-to-End Workflow Diagram

```mermaid
flowchart TD
    A["Natural Language Prompt / Scenario Template"] --> B["Scenario Compiler\n(src/scenarios/compiler.py)"]
    
    subgraph Compilation["1. Compilation & Autofill"]
        B --> B1["Location Extraction\n(81 Turkish Provinces)"]
        B --> B2["Domain Classification\n(Transport, Energy, Housing, University, Public Policy...)"]
        B --> B3["Parameter Calibration\n(Tariffs, Percentages, Attributes)"]
        B --> B4["Target Population Rules\n(Age, Province, Adults)"]
        B --> B5["Question Synthesis\n(Single Choice or Free-Text Mode)"]
    end
    
    Compilation --> C["Validated ScenarioConfig\n(src/scenarios/schema.py)"]
    
    C --> D["Scenario Adapter\n(src/scenarios/adapter.py)"]
    D --> E["Experiment Definition\n(ExperimentDefinition)"]
    
    subgraph Execution["2. Simulation & Agent Execution"]
        E --> F["Eligibility Engine\n(src/scenarios/eligibility.py)"]
        F --> G["Representative Cohort Sample\n(Synthetic Turkish Personas)"]
        G --> H["Prompt Renderer\n(src/scenarios/prompt_renderer.py)"]
        H --> I["Execution Engine\n(Live Cloud LLM, Zero-Cost Simulation, or Pipeline Test)"]
        I --> J["Response Validator\n(src/scenarios/response_validator.py)"]
    end
    
    subgraph Synthesis["3. Analytics & Executive Summary"]
        J --> K["Aggregate Engine\n(src/societytwin/national/results.py)"]
        J --> L["Result Text Summarizer\n(src/scenarios/summary.py)"]
        L --> M["Executive Result Summary & Qualitative Quotes\n(/results/[id])"]
    end
```

---

## 3. Core Modules (`src/scenarios/`)

The Scenario Engine core is implemented in [`src/scenarios/`](../src/scenarios):

### 3.1 `schema.py` — Strict Data Modeling
Defines validated Pydantic models for policy configurations:
- **`ScenarioConfig`**: Top-level model containing metadata, location, target population, policy parameters, and questionnaire.
- **`PolicyParameters`**: Holds calibrated economic figures (`baseline_fare`, `new_fare`, `increase_percentage`, `currency`, `policy_summary`, `custom_details`). Non-transit scenarios cleanly set transport attributes (`fare_category`) to `None`.
- **`PopulationFilterConfig`**: Demographic screening bounds (`province_codes`, `minimum_age`, `maximum_age`, `sexes`, `marital_statuses`, `education_levels`, `adult_only`, `required_attributes`).
- **`QuestionConfig`**:
  - `type="single_choice"`: Structured choice questions with balanced options.
  - `type="free_text"`: Open-ended qualitative questions with `options=[]` and length bounds (`min_length`, `max_length`).

### 3.2 `compiler.py` — Zero-Shot NLP & Parameter Calibration
Transforms raw text prompts into a complete `ScenarioConfig`:
- **`extract_location(text)`**: Turkish diacritic-aware normalization matching all 81 provinces (handles *İçel/Mersin*, *Afyonkarahisar*, and apostrophized suffixes such as *Bursa'da*).
- **`detect_domain_and_category(...)`**: Classifies prompts into domains (`transportation`, `university_placement`, `university_policy`, `housing`, `energy`, `economic`, `education`, `public_policy`).
- **`calculate_tariff_change(...)`**: Automatically computes relative percentages, absolute new tariffs, or baseline values from partial prompt mentions.
- **`detect_target_population(...)`**: Detects demographic filters (e.g., student filters `minimum_age=18, maximum_age=26`, elderly discounts `minimum_age=65`).
- **`synthesize_questions(...)`**: Produces either calibrated single-choice questions or open-ended free-text questions based on prompt intent.
- **LLM + Heuristic Fallback**: Uses OpenAI completion only when `SOCIETYTWIN_ENABLE_LIVE_SCENARIO_LLM=1` and `OPENAI_API_KEY` (with optional `openai` extra installed) are set, otherwise falling back seamlessly to deterministic rule-based heuristic extraction.

### 3.3 `adapter.py` — Pipeline Transformation & Catalog
Connects scenarios to the workbench experiment system:
- **`scenario_to_experiment_definition(scenario, cohort_id, ...)`**: Maps a `ScenarioConfig` into an executable `ExperimentDefinition`. Supports both `single_choice` and `free_text` response types.
- **`save_custom_scenario(scenario)`**: Persists custom scenarios as YAML files; API routes store runtime-created scenarios under `SOCIETYTWIN_STATE_DIR/scenarios/` so source directories stay clean, while built-in templates are read from `src/scenarios/builtin_scenarios/` (`uni_placement_quota_001`, `uni_tuition_hike_001`) and `experiments/policy_scenarios/scenarios/` (`transport_fare_001`, `energy_subsidy_001`).
- **`get_scenario(scenario_id)`**: Retrieves built-in or saved custom scenarios from the catalog.
- **`scenarios.placement` & `scenarios.university`**: Counterfactual university admission placement engine (`python -m scenarios.placement`) and multi-semester policy/financial ledger engine (`python -m scenarios.university`), integrated into `/api/v2/placement/*` and `/api/v2/university/*`.

### 3.4 `eligibility.py` — Deterministic Resident Screening
Evaluates whether a synthetic persona qualifies for a scenario:
- Evaluates constraints: province codes, age thresholds, household parameters.
- Returns ternary screening status:
  - `ELIGIBLE`: Persona meets all criteria.
  - `EXCLUDED`: Persona fails one or more criteria (with human-readable diagnostic reason).
  - `CANNOT_EVALUATE`: Missing persona attribute (fails closed to prevent corrupt experiments).

### 3.5 `prompt_renderer.py` — Standalone Scenario Prompt Helper
Standalone template helper for scenario cards (the national pipeline executes via `societytwin.national.experiments.render_prompts` and `societytwin.national.runner`):
- Renders persona summary fields alongside scenario description and options/free-text JSON format instructions without leaking synthetic IDs or seeds.

### 3.6 `response_validator.py` — Standalone Schema Validator
Strict standalone response validation contract (parallel to `societytwin.national.experiments.parse_response` used by the runner):
- Strips markdown code fences (````json ... ````).
- Validates `single_choice`, `multiple_choice`, and `free_text` (with `min_length`/`max_length` bounds) and captures rationale fields when enabled.

### 3.7 `summary.py` — Executive Result Text Summarizer
Generates comprehensive narrative result summaries and executive briefings from simulation data:
- **LLM Executive Synthesis**: When an experiment used `transport == "live"`, `backend != "stub"`, `OPENAI_API_KEY` is present, and `SOCIETYTWIN_ALLOW_LLM_SUMMARY=1` (or `allow_llm=True`), calls OpenAI to synthesize qualitative responses, key trends, representative quotes, and policy recommendations.
- **Deterministic Rule-Based Fallback**: Generates structured reports with plurality/consensus percentages, response depth metrics, and verbatim quotes when offline or running fake/stub tests.
- **Failure Diagnostics**: Provides clear diagnostic banners if agent calls fail (e.g. HTTP 401 invalid API key), avoiding confusing 0% graphs.

---

## 4. Execution Engines & Pipelining

The simulation runner supports three distinct execution backends:

| Engine | Backend / Transport | AI Behavior | External API Calls / Cost | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **AI Citizen Agents (Live LLM provider)** | `matraix:live` | Full LLM cognitive reasoning (GPT-4o, Claude 3.5 Sonnet, Gemini) | **Yes** (Consumes API tokens; requires valid API key in `.env`) | Actual research, behavioral prediction, paper and thesis data collection. |
| **AI Citizen Agents (Zero-cost simulation)** | `matraix:fake` | Offline mock execution mode via MatrAIx batch runner | **Zero cost** (Runs 100% offline, zero network calls) | Testing prompt templates, verifying survey flow, and UI demonstrations without spending API credits. |
| **Pipeline Test (No AI / Offline)** | `stub:fake` | Deterministic mathematical hash runner | **Zero cost** (In-memory execution in milliseconds) | CI/CD automated test suites, verifying database persistence, stratification, and isolating data layer bugs. |

### Why Pipeline Testing is Essential
While **Pipeline Test** has zero AI intelligence by design, it is critical in scientific software:
1. **CI/CD Automated Testing**: Runs 80+ integration tests automatically without paid API keys or network latency.
2. **Isolation of Failures**: If a statistical aggregation fails, running a stub pipeline test immediately isolates whether the issue is in the demographic data pipeline vs. external LLM API rate limits.
3. **Pre-flight Budget Guard**: Allows researchers to verify cohort filters and questionnaire schema on a 1-second stub run before spending money on a 1,000-agent live LLM run.

---

## 5. REST API Endpoints (`src/societytwin/api/v2.py`)

The scenario engine exposes REST endpoints registered under `/api/v2`:

| Method | Endpoint | Description | Request / Query | Response |
|---|---|---|---|---|
| `POST` | `/api/v2/scenarios/from-prompt` | Zero-shot prompt compilation into validated scenario | `ScenarioPromptRequest` (`prompt`, `save`, `model`) | `ScenarioConfig` |
| `GET` | `/api/v2/scenarios` | Lists built-in and saved custom scenarios | Query: `category`, `province` | `ScenarioList` |
| `GET` | `/api/v2/scenarios/{id}` | Fetches full scenario YAML specification | None | `ScenarioConfig` |
| `GET` | `/api/v2/scenarios/{id}/experiment-definition` | Converts scenario to runnable experiment definition | Query: `cohort_id`, `question_id`, `seed` | `ExperimentDefinition` |
| `POST` | `/api/v2/scenarios` | Registers new custom scenario template | `ScenarioConfig` (JSON) | `ScenarioConfig` |
| `GET` | `/api/v2/runs/{run_id}/text-summary` | Generates or fetches executive result text summary | None | `ResultTextSummary` |

---

## 6. Frontend User Experience (`frontend/src/app/experiments/new/page.tsx`)

### Prompt-First Builder + Reviewed Execution Plan
- **Prompt Compilation & Auto-Selection**: Enter a natural language policy question and click **`Compile & review plan`** (or **`Preview & Edit Question ↓`** to inspect/edit before creating a plan). Selecting a template in `#scenario-select` immediately populates the scenario, question, and parameters.
- **Graceful Backend Default & Model Controls**: Automatically selects `stub:fake` when MatrAIx runtime is unavailable, and exposes a live `provider/model` selector (`openai/*`, `anthropic/*`, `gemini/*`) when `matraix:live` is chosen.
- **Cohort, Parameters & Budget Controls**: Supports choosing a saved cohort (`#cohort-select`, including URL `?cohort=` handoff from `/cohorts`) or auto-creating a matching adult cohort, editing scenario parameters, sampling method/seed, temperature, call cap, and cost cap inside the customization drawer.
- **Explicit Plan Review & Confirmation Gate**: Clicking **`Compile & review plan`** or **`Save and review plan`** runs `POST /api/v2/experiments` and `POST /api/v2/experiments/{id}/plan`, displaying active personas, estimated calls/tokens/cost, blockers, warnings, and an example prompt before enabling **`Run experiment`** behind the confirmation checkbox.

### Results Dashboard (`frontend/src/app/results/[id]/page.tsx`)
- **Executive Result Summary Card**: Displays an executive headline, bulleted key behavioral findings, a copy-to-clipboard button, and an expandable full analytical Markdown report.
- **Citizen Free-Text Responses (Qualitative Findings)**: When open-ended free-text mode is selected, displays quote cards showing verbatim citizen feedback and synthetic IDs.
- **Weighted Response Distribution**: Renders statistical choice distribution bars with 95% Wilson score confidence intervals and Kish effective sample sizes.

---

## 7. How to Run Tests

### Backend Unit & Integration Tests:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scenarios/ tests/national/test_scenario_pipeline.py tests/national/test_api_v2.py tests/national/test_university_api_v2.py -v
```
*Executes the scenario engine, university placement API, and national pipeline test suites, verifying location extraction, tariff math, domain classification, free-text schemas, deterministic/LLM summaries, demographic screening, and API endpoints.*

### Frontend Typecheck:
```powershell
cd frontend
npx tsc --noEmit
```
*Verifies 0 TypeScript compilation errors across all pages, components, and API client interfaces.*
