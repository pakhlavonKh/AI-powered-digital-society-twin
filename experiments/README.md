# Experiments

**Status:** Active experiment tracks alongside the `configs/` & `data/results/` architecture notes:

- `experiments/matraix_simulation/`: Historical recorded Ankara MatrAIx A/B and smoke runs (served read-only under `/api/v1` and `/historical`).
- `experiments/policy_scenarios/`: YAML scenario catalog & mobility evidence notes (`src/scenarios/`; custom API runs persist outside git under `SOCIETYTWIN_STATE_DIR/scenarios`).

Generated trial outputs under `experiments/outputs/`, `experiments/results/`, and `experiments/policy_scenarios/scenarios/prompt_*.yaml` remain git-ignored.
