# `src/scenarios` (Scenario Engine Core)

This package contains the core implementation of the **SocietyTwin Scenario Engine**:
- `schema.py`: Pydantic data models for scenarios, policy parameters, questions, and population filters.
- `loader.py`: Safe YAML/JSON loader with diagnostic syntax and validation error reporting.
- `eligibility.py`: Single resident evaluation and batch population filtering with explicit missing-attribute diagnostics (`CANNOT_EVALUATE`).
- `response_validator.py`: Strict structured response validator preventing hallucinated answer choices (e.g. rejects "maybe").
- `prompt_renderer.py`: Transforms validated scenarios and persona context into reproducible agent prompts without leaking generator seeds.

For full research notes, mobility evidence registers, and reference scenario files, see [`experiments/policy_scenarios/`](../../experiments/policy_scenarios/).

### Running Tests:
```powershell
.\.venv\Scripts\pytest tests/test_scenarios/ -v
```
