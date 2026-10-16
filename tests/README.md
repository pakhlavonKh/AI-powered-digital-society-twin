# Tests

**Status:** Tests exist for the research workbench (`src/societytwin/`, `frontend/`); the rest of the v2 strategy below is still planned.

| Suite | Command | Data |
|---|---|---|
| Unit and API (`tests/unit`, `tests/api`) | `.venv/bin/python -m pytest -m "not local_fixture and not matraix"` | Artificial fixture in `tests/fixtures/artificial_experiment/` |
| Supplied-fixture regression (`tests/regression`) | `.venv/bin/python -m pytest -m local_fixture` | The tracked Ankara fixtures and, if present, the git-ignored run folders |
| MatrAIx integration (`tests/integration`) | set `SOCIETYTWIN_TEST_MATRAIX_ROOT` and `SOCIETYTWIN_TEST_RUNTIME_PYTHON` | External MatrAIx checkout; no provider keys |
| Frontend | `cd frontend && npx vitest run`, `./scripts/e2e.sh` | Mocked API / artificial fixture |

Details: [docs/research-workbench.md](../docs/research-workbench.md#tests).

The PROPOSED v2 testing strategy is in [report §28](../docs/societytwin-v2-architecture.md#28-testing-strategy). In summary:

| Level | Examples |
|---|---|
| Unit | IPF convergence on small tables; allocation preserves totals; masks respected; metrics match hand-computed values |
| Property-based (Hypothesis) | Totals preserved, zero hard-constraint violations, same seed gives identical output, independence from partition processing order |
| Schema and configuration | Schema, instrument, and experiment configurations validate; invalid ones are rejected |
| Integration | Artificial data → 10K build → validation → cohort → SURVEY experiment with the stub model → results |
| API and frontend | FastAPI contract tests; Vitest component tests |
| Performance | 10K / 100K / 1M benchmarks (manual or scheduled, not in every CI run) |

Rules: no real LLM calls and no real TÜİK data in CI. Small, clearly artificial fixtures live in `tests/fixtures/`.
