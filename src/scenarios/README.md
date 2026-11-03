# `src/scenarios` (Scenario Engine Core)

This package contains the core implementation of the **SocietyTwin Scenario Engine**:
- `compiler.py`: Zero-shot NLP prompt compiler (81-province extraction, tariff calculation, question synthesis, LLM/heuristic extraction).
- `schema.py`: Pydantic data models for scenarios, policy parameters, questions, and population filters.
- `adapter.py`: Bridge between policy scenarios and the experiment execution pipeline.
- `loader.py`: Safe YAML/JSON loader with diagnostic syntax and validation error reporting.
- `eligibility.py`: Single resident evaluation and batch population filtering with explicit missing-attribute diagnostics (`CANNOT_EVALUATE`).
- `response_validator.py`: Strict structured response validator preventing hallucinated answer choices (e.g. rejects "maybe").
- `prompt_renderer.py`: Transforms validated scenarios and persona context into reproducible agent prompts without leaking generator seeds.

For the comprehensive guide, see [docs/scenario-engine.md](../../docs/scenario-engine.md).
For mobility evidence registers and reference scenario files, see [`experiments/policy_scenarios/`](../../experiments/policy_scenarios/).

### Running Tests:
```powershell
.\.venv\Scripts\pytest tests/test_scenarios/ -v
```
