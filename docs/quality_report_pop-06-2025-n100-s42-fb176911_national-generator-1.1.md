# Combined Quality & Validation Report — `pop-06-2025-n100-s42-fb176911`

- **Report Schema Version:** `combined-quality-report-k7-v1`
- **Evaluator Version:** `k7-quality-reports-1.0`
- **Population ID / Version:** `pop-06-2025-n100-s42-fb176911` / `national-generator-1.1`
- **Reference Package:** `ankara-reference-package-k2-2025.1` (`fa0971ff615e7914...`)
- **Geography / Year:** `06` / `2025`
- **Sample Size ($n$):** `100` records (Weighted Total: `5,910,320.0`)
- **Seed:** `42`
- **Simulation Run ID:** `None`
- **Overall Status:** **`FAIL`** (`pass=2`, `fail=5`, `not_evaluable=6`)
- **Deterministic Report Fingerprint:** `a626128e1f651ef981a66308d896bfc29fceec02eaf7a67307509345361edf45`

> [!IMPORTANT]
> **Synthetic Label:** Synthetic population and simulation results calibrated to official aggregate statistics. Fictional residents; no real person is represented.

---

## 1. Executive Summary of All Quality Checks

Every check across marginal distributions, multidimensional dependencies, and simulation results.

| Layer | Check ID | Name | Status | Calibrated? | Dataset ID | Scope Marker | Reason / Evaluation Summary |
|---|---|---|:---:|:---:|---|---|---|
| `marginal_population` | `margin_age` | Marginal Age | **`FAIL`** | YES | `ankara_age_sex_2025` | `ANKARA_OBSERVED` | Calibrated margin 'age' failed validation: weighted TVD (0.008376) exceeds calibration tolerance (0.000010); max weighted pp deviation (0.7208 pp) exceeds calibration tolerance (0.0010 pp); max weighted relative error (1.000000) exceeds calibration tolerance (0.000010). |
| `marginal_population` | `margin_sex` | Marginal Sex | **`PASS`** | YES | `ankara_age_sex_2025` | `ANKARA_OBSERVED` | Calibrated margin 'sex' passed: weighted TVD=0.00e+00 (<= 1.0e-05), max weighted pp deviation=0.00e+00 pp; unweighted record TVD=0.0073 (expected 0.0399 for n=100), max |z|=0.15 (<= 2.81). |
| `marginal_population` | `margin_age_sex` | Marginal Age Sex | **`FAIL`** | YES | `ankara_age_sex_2025` | `ANKARA_OBSERVED` | Calibrated margin 'age_sex' failed validation: weighted TVD (0.012845) exceeds calibration tolerance (0.000010); max weighted pp deviation (0.7208 pp) exceeds calibration tolerance (0.0010 pp); max weighted relative error (1.000000) exceeds calibration tolerance (0.000010). |
| `marginal_population` | `margin_marital_status` | Marginal Marital Status | **`FAIL`** | YES | `ankara_marital_sex_2025` | `ANKARA_OBSERVED` | Calibrated margin 'marital_status' failed validation: weighted TVD (0.007002) exceeds calibration tolerance (0.000010); max weighted pp deviation (1.4004 pp) exceeds calibration tolerance (0.0010 pp); max weighted relative error (1.000000) exceeds calibration tolerance (0.000010). |
| `marginal_population` | `margin_education` | Marginal Education | **`PASS`** | NO | `ankara_education_sex_2025` | `ANKARA_OBSERVED` | Uncalibrated distribution 'education' is within expected sampling uncertainty for n=83: max |z|=2.73 <= Bonferroni threshold 3.48 (observed record TVD=0.1312 vs expected TVD=0.1481 for n=83). Calibration tolerances were not applied. |
| `marginal_population` | `margin_employment_status` | Marginal Employment Status | **`NOT_EVALUABLE`** | NO | `ankara_labour_force_rates_2025` | `ANKARA_OBSERVED` | Not evaluable: (1) ankara_labour_force_rates_2025 publishes only HLFS survey-modelled headline percentages (LFPR=53.91%, employment_rate=49.34%, unemployment_rate=8.48% of labour force) with ±1% confidence intervals for the non-institutional 15+ universe, without person counts or sex/age disaggregation (flag D7_PROVINCIAL_LABOUR_FORCE_RATES_ONLY_NO_SEX_OR_COUNTS); and (2) person-level labour_status in the core Ankara generator is UNAVAILABLE (None) rather than fabricated from non-comparable regional/rate tables. |
| `marginal_population` | `margin_household_size` | Marginal Household Size | **`NOT_EVALUABLE`** | NO | `ankara_household_size_2025` | `ANKARA_OBSERVED` | Not evaluable on resident-only population: (1) ankara_household_size_2025 is denominated in private households (expected_total=1,987,216, unit='household'), which does not reconcile to Ankara's 5,910,320 ADNKS resident population (implied private-household population = 5,690,627; unreconciled institutional/collective gap = 219,693 persons, flag D1_ANKARA_HH_VS_RESIDENT_POP_2025); (2) resident records keep household_size_class=None (UNAVAILABLE) rather than forcing an unverified person-to-household linkage; and (3) optional local raw file data/raw/ankara_household_size_2025.csv is absent in this clean checkout. |
| `marginal_population` | `margin_household_type` | Marginal Household Type | **`NOT_EVALUABLE`** | NO | `ankara_household_types_2025` | `ANKARA_OBSERVED` | Not evaluable on resident-only population: (1) ankara_household_types_2025 reports 1,987,216 private households (unit='household': one_person=407,306, nuclear_family=1,312,420, extended_family=193,972, non_family_multi_person=73,518; average_household_size=2.863618 -> 5,690,627 private-household residents), leaving an unreconciled 219,693-person gap vs Ankara's 5,910,320 ADNKS resident population (flag D1_ANKARA_HH_VS_RESIDENT_POP_2025); and (2) resident records keep household_type=None (UNAVAILABLE) because person-level household-type membership is not observed in provincial ADNKS tables. |
| `joint_dependency` | `joint_age_marital` | Age × Marital Status Joint Distribution | **`FAIL`** | NO | `—` | `national proxy, not Ankara-observed` | Demographic realism failure: Slice age_band=15-24: Significant deviation from benchmark: record TVD=0.7924 > threshold 0.1795, max |z|=11.71 > Bonferroni limit 3.02 (max PP dev=79.2 pp). | Slice age_band=25+: Significant deviation from benchmark: record TVD=0.1767 > threshold 0.1856, max |z|=3.70 > Bonferroni limit 3.02 (max PP dev=16.4 pp). | Slice age_band=15-19: Significant deviation from benchmark: record TVD=0.6943 > threshold 0.1622, max |z|=13.12 > Bonferroni limit 3.02 (max PP dev=69.4 pp). |
| `joint_dependency` | `joint_sex_age_marital` | Sex × Age × Marital Status 3-Way Joint Distribution | **`FAIL`** | NO | `—` | `national proxy, not Ankara-observed` | Sex-age conditional marital failure against National Proxy: Group (male, 15-24): Significant deviation from benchmark: record TVD=0.9520 > threshold 0.1872, max |z|=12.60 > Bonferroni limit 3.02 (max PP dev=95.2 pp). | Group (female, 15-24): Significant deviation from benchmark: record TVD=0.6143 > threshold 0.2502, max |z|=10.53 > Bonferroni limit 3.02 (max PP dev=61.4 pp). |
| `joint_dependency` | `joint_age_education` | Age × Education Joint Distribution & Structural Constraints | **`NOT_EVALUABLE`** | NO | `—` | `unverified (no empirical reference)` | Empirical age × education joint distribution is unobserved in published TÜİK tables; benchmark not invented per validation protocol. Deterministic minimum-completion-age rules and under-15 education gate verified (0 structural zero violations). |
| `joint_dependency` | `joint_age_employment` | Age × Employment Status Joint Distribution | **`NOT_EVALUABLE`** | NO | `—` | `unverified (no empirical reference)` | Empirical person-level labour force status is not modelled in baseline generator (marked UNAVAILABLE in dependency registry); TÜİK provincial labour indicators publish aggregate headline survey rates only without age-conditional joint counts. Benchmark not invented per validation protocol. |
| `joint_dependency` | `joint_household_size_type` | Household Size × Household Type Joint Distribution | **`NOT_EVALUABLE`** | NO | `—` | `unverified (no empirical reference)` | Household type × size joint distribution unlinked in resident population (D1 discrepancy: 1,987,216 private households vs 5,910,320 residents; person-to-household micro-linkage is unobserved in TÜİK tables and forbidden in baseline model). |

---

## 2. Validation Gaps & Unresolved Empirical Discrepancies

Documented data quality issues, unverified relationships where no benchmark was invented, and unavailable behavioral data.

### `D1_ANKARA_HH_VS_RESIDENT_POP_2025` (data_discrepancy)
- **Summary:** Ankara 2025 private household count (1,987,216) and implied private-household population (1,987,216 × 2.86361774462363 = 5,690,627 persons; or 5,683,438 using rounded 2.86) do NOT reconcile to total ADNKS resident population (5,910,320 persons). Exact unreconciled gap: 219,693 persons (3.7171% of Ankara resident population).
- **Policy Action:** `document_do_not_force`
- **Details & Root Causes:**
  - 1. Institutional/collective population exclusion: ADNKS total resident population (5,910,320) includes institutional/collective places (KYK and private university dormitories, military barracks, prisons, nursing homes, hospitals), which are excluded by definition from ADNKS_private_households (1,987,216).
  - 2. Open-ended 10+ household size tail: In the NIP household size table (1..9, 10+), the 10+ class has only a known lower bound (10) and no published upper bound or exact mean size.
  - 3. Different reference years & multi-year averaging across household tables: 2021 Building & Dwelling Survey reports 1,874,093 households (2021 ADNKS base), while 2023 SES reports 1,927,404.67 households (2022–2024 3-year administrative register average).
  - 4. Absence of public person-to-household micro-linkage tables at Ankara (06) level.

### `D2_ANKARA_EDUCATION_15PLUS_VS_ADNKS_15PLUS_2025` (data_discrepancy)
- **Summary:** Ankara 2025 NESD Education 15+ total (4,751,123: 2,322,692 male, 2,428,431 female) is 104,983 persons (2.1619%) smaller than Ankara 2025 ADNKS 15+ resident population (4,856,106: 2,371,482 male, 2,484,624 female). Nationally in 2025, the gap is 1,340,559 persons (67,220,886 vs 68,561,445) and correlates r = 0.999766 across all 81 provinces with foreign resident population (T12).
- **Policy Action:** `preserve_unknown_category`
- **Details & Root Causes:**
  - 1. NESD (Ulusal Eğitim İstatistikleri Veri Tabanı) derives diploma attainment from domestic MERNİS/MEB/YÖK registers, excluding most foreign nationals residing in Türkiye on residence permits (128,633 in Ankara 2025).
  - 2. Published 'unknown' (Bilinmeyen) category (17,626 in Ankara 2025: 7,474 male, 10,152 female) is part of the 4,751,123 NESD total and must be preserved as a distinct category, never silently dropped.

### `D7_PROVINCIAL_LABOUR_FORCE_RATES_ONLY_NO_SEX_OR_COUNTS` (data_discrepancy)
- **Summary:** Provincial labor_force_indicators.csv (2022–2025) publishes only headline 15+ model-estimated percentages (LFPR 53.91%, employment rate 49.34%, unemployment rate 8.48% in Ankara 2025) with 95% confidence intervals, without sex breakdown, age breakdown, or person counts (contrary to package README.md line 51).
- **Policy Action:** `not_evaluable_for_person_counts`
- **Details & Root Causes:**
  - 1. Detailed Household Labour Force Survey (HLFS) tables by sex, age, and education are published only at NUTS-2 (TR51) and National (TR) levels (see not_province_level.csv).
  - 2. Converting survey model rates with ±1% CIs into exact integer person counts would fabricate precision.

### `UNVERIFIED_AGE_EDUCATION_JOINT` (unverified_relationship)
- **Summary:** Empirical age × education joint distribution is unobserved in public TÜİK tables.
- **Policy Action:** `Never invent synthetic benchmark; verify deterministic structural zeros only.`
- **Details & Root Causes:**
  - TÜİK NESD publishes sex-only marginals; age-conditional tables are unobserved at province level.

### `UNAVAILABLE_ANKARA_FARE_ELASTICITY` (unavailable_benchmark)
- **Summary:** Ankara EGO General Directorate publishes aggregate boardings only; no econometric fare elasticity is available.
- **Policy Action:** `Report status as 'unavailable'; use international literature meta-estimates as sanity envelope only.`
- **Details & Root Causes:**
  - Macroeconomic inflation (>60%) and statutory 65+ free transit confound simple time-series differencing.

---

## 3. Structural Limitations & Methodological Constraints

- 1. Calibrated Margins vs. Joint Realism: Exact marginal convergence (K3) does not guarantee realistic multivariate associations (K4).
- 2. National Proxy Scope: Age-conditional marital benchmarks derive from national broad-age tables (Table 1.9), labeled 'national proxy, not Ankara-observed'.
- 3. Stated Intention Non-Equivalence: Stated survey responses systematically over-report trip reduction due to protest and hypothetical bias; they cannot be equated to observed turnstile ridership drops.
- 4. Unlinked Resident Population: Resident personas do not carry empirical household membership links (D1 discrepancy: 1,987,216 private households vs 5,910,320 residents).