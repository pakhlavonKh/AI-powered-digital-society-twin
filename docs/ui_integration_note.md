# UI & API Integration Note: Validation & Quality Reports Contract

- **Author:** Koray (Data & Validation Engine)
- **To:** UI & API Owner / Frontend Team
- **Date:** 2026-10-30
- **Scope:** Consumption of Combined Quality Reports (K7) in SocietyTwin Web UI & API (`/populations/{id}/validation`, `/builds/{id}/validation`)
- **Core Principle:** Backward compatibility with zero required UI redesign.

---

## 1. Overview & Compatibility Design

The SocietyTwin Validation Layer (Phases 3 through 7) produces comprehensive, multi-layered validation reports integrating:
1. **Marginal Population Fitting (K3):** Exact weighted raking and record-sampling checks across age, sex, marital status, education, urbanicity, and household types.
2. **Multidimensional Dependency Validation (K4):** Evaluates joint distributions (`age × marital_status`, `sex × age × marital_status`, `household_size × household_type`, `age × education`) against national empirical proxies or structural zeros.
3. **Simulation Results Evaluation (K6):** Evaluates persona responses to policy interventions (such as the Ankara 20% fare increase), reporting weighted distributions, subgroup breakdowns, failure audits, and behavioral benchmark comparisons.

To connect validation reporting with the web UI and FastAPI routes (`src/societytwin/api/app.py` and `src/societytwin/api/v2.py`):
- **Integrated into `/api/v2/populations/{population_id}/validation`:** `NationalService._dependency_validation()` runs `validate_dependencies(..., include_marginal_report=False)` from [`validation/dependencies.py`](../src/societytwin/validation/dependencies.py) and returns `dependency_validation` alongside the 81-province source-fit report rendered on `/validation`. Optional module and K1–K7 reference readiness is also surfaced on `/api/v2/data-sources` (`optional_modules`).
- **Standalone full K7 helper:** [`CombinedQualityReport`](../src/societytwin/validation/reports.py) and [`CombinedQualityReport.to_ui_dict()`](../src/societytwin/validation/reports.py) produce offline multi-phase quality bundles and `/api/v1`-shaped payloads for research scripts (proposed `/populations/{id}/quality-report` and `/quality-report.md` routes are not exposed as standalone API paths).

---

## 2. API Endpoint Mapping

The table below describes how existing API endpoints can serve the new validation artifacts:

| Endpoint | Method | Response | Integration Status |
|---|---|---|---|
| `/api/v2/populations/{population_id}/validation` | `GET` | `ValidationReport` (`v2` + `dependency_validation`) | **Implemented**: returns 81-province `national/validation.py` report plus live K4 `validate_dependencies()` joint checks. |
| `/api/v2/data-sources` | `GET` | `DataSources` (`+ optional_modules`) | **Implemented**: includes K1–K7 reference bundle availability and optional module flags (`households`, `enrichment`, `marital_strategy`). |
| `/v1/builds/{build_id}/validation` | `GET` | `ValidationReport` (`v1`) | Serves historical Ankara v1 builds unchanged. |
| `/populations/{population_id}/quality-report{,.md}` | `GET` | `CombinedQualityReport` | **Proposed** offline helper (`combined_report.to_ui_dict()` / `.to_markdown()`); not mounted as separate HTTP routes. |

---

## 3. JSON Field-by-Field Mapping to Existing UI Schemas

The output of `combined_report.to_ui_dict()` maps directly to the UI's expected fields:

| Existing UI Field (`schemas.py:ValidationReport`) | Type | Populated From (`reports.py:CombinedQualityReport`) | Description |
|---|---|---|---|
| `build_id` / `population_id` | `str` | `combined_report.population_id` | Unique population identifier (e.g. `pop-06-2025-n1000-s42-e6a8e87e`). |
| `method_version` | `str` | `combined_report.evaluator_version` | Current engine version (`k7-quality-reports-1.0`). |
| `population_sha256` | `str` | `combined_report.reference_package_fingerprint` | Verified reference package fingerprint. |
| `metrics` | `list[ValidationMetric]` | Raked marginal checks (`total_variation_distance_weighted`, categories, shares). | Renders bar charts and distribution comparisons in existing UI panels. |
| `checks` | `list[Check]` | Unified checks (`marginal_*`, `joint_*`, structural zeros). | Renders pass/fail badges with human-readable detail strings. |
| `unavailable_evidence` | `list[UnavailableEvidence]` | Documented validation gaps & discrepancies (D1, D2, D3, missing EGO elasticity). | Renders yellow warning cards explaining why specific data is not evaluable. |
| `acceptance_note` | `str` | Summary statement (`PASS` vs `FAIL` tally). | High-level status header displayed at the top of the UI view. |
| `reference_tables` | `list[ReferenceTableRef]` | Table paths, SHA-256 hashes, years, and row counts. | Provenance section in the UI showing source audit trail. |
| `synthetic_label` | `str` | Mandatory synthetic data disclaimer. | Displayed in UI footer as required by project governance. |

---

## 4. UI Display Recommendations for Frontend Developers

1. **Pass / Fail / Not Evaluable Badges:**
   - Instead of binary Pass/Fail, display three distinct badge states:
     - <span style="color: green; font-weight: bold;">PASS</span>: Calibrated margins and verified joints within tolerances.
     - <span style="color: red; font-weight: bold;">FAIL</span>: Significant demographic distortions (e.g. 62% married teenagers) or structural zero violations.
     - <span style="color: orange; font-weight: bold;">NOT EVALUABLE</span>: Unobserved relationships (e.g. `age × education` empirical joint) or unavailable benchmarks.
2. **Displaying the Stated vs. Revealed Disclaimer:**
   - In simulation result cards, ensure the label reads `"Simulated Stated Preference Distribution"` rather than `"Predicted Ridership Drop"`.
3. **Small Subgroup Low-Confidence Tooltip:**
   - When rendering demographic breakdown bars where sample $n < 15$, display an inline warning icon: `"Low sample size (n < 15) — point estimate carries high variance"`.
4. **Markdown Export:**
   - The UI can provide a one-click button `"Download Complete Markdown Audit Report"` that fetches `combined_report.to_markdown()`.
