# Combined Quality & Validation Report — `pop-06-2025-n1000-s42-e6a8e87e`

- **Report Schema Version:** `combined-quality-report-k7-v1`
- **Evaluator Version:** `k7-quality-reports-1.0`
- **Population ID / Version:** `pop-06-2025-n1000-s42-e6a8e87e` / `national-generator-1.1`
- **Reference Package:** `ankara-reference-package-k2-2025.1` (`fa0971ff615e7914...`)
- **Geography / Year:** `06` / `2025`
- **Sample Size ($n$):** `1,000` records (Weighted Total: `5,910,320.0`)
- **Seed:** `42`
- **Simulation Run ID:** `run-ankara-20pct-fare-synthetic-1000`
- **Overall Status:** **`FAIL`** (`pass=5`, `fail=2`, `not_evaluable=6`)
- **Deterministic Report Fingerprint:** `2766b66bfa53358d3ea2414d9ac37242fa7091a2cbcc6dc44802cff9c4ad9573`

> [!IMPORTANT]
> **Synthetic Label:** Synthetic population and simulation results calibrated to official aggregate statistics. Fictional residents; no real person is represented.

---

## 1. Executive Summary of All Quality Checks

Every check across marginal distributions, multidimensional dependencies, and simulation results.

| Layer | Check ID | Name | Status | Calibrated? | Dataset ID | Scope Marker | Reason / Evaluation Summary |
|---|---|---|:---:|:---:|---|---|---|
| `marginal_population` | `margin_age` | Marginal Age | **`PASS`** | YES | `ankara_age_sex_2025` | `ANKARA_OBSERVED` | Calibrated margin 'age' passed: weighted TVD=5.35e-14 (<= 1.0e-05), max weighted pp deviation=2.56e-12 pp; unweighted record TVD=0.0036 (expected 0.0506 for n=1000), max |z|=0.19 (<= 3.47). |
| `marginal_population` | `margin_sex` | Marginal Sex | **`PASS`** | YES | `ankara_age_sex_2025` | `ANKARA_OBSERVED` | Calibrated margin 'sex' passed: weighted TVD=3.61e-16 (<= 1.0e-05), max weighted pp deviation=3.89e-14 pp; unweighted record TVD=0.0007 (expected 0.0126 for n=1000), max |z|=0.04 (<= 2.81). |
| `marginal_population` | `margin_age_sex` | Marginal Age Sex | **`PASS`** | YES | `ankara_age_sex_2025` | `ANKARA_OBSERVED` | Calibrated margin 'age_sex' passed: weighted TVD=7.22e-14 (<= 1.0e-05), max weighted pp deviation=2.36e-12 pp; unweighted record TVD=0.0049 (expected 0.0727 for n=1000), max |z|=0.22 (<= 3.65). |
| `marginal_population` | `margin_marital_status` | Marginal Marital Status | **`PASS`** | YES | `ankara_marital_sex_2025` | `ANKARA_OBSERVED` | Calibrated margin 'marital_status' passed: weighted TVD=1.19e-14 (<= 1.0e-05), max weighted pp deviation=1.88e-12 pp; unweighted record TVD=0.0191 (expected 0.0272 for n=822), max |z|=1.20 (<= 3.23). |
| `marginal_population` | `margin_education` | Marginal Education | **`PASS`** | YES | `ankara_education_sex_2025` | `ANKARA_OBSERVED` | Calibrated margin 'education' passed: weighted TVD=1.63e-16 (<= 1.0e-05), max weighted pp deviation=2.22e-14 pp; unweighted record TVD=0.0438 (expected 0.0471 for n=822), max |z|=2.19 (<= 3.48). |
| `marginal_population` | `margin_employment_status` | Marginal Employment Status | **`NOT_EVALUABLE`** | NO | `ankara_labour_force_rates_2025` | `ANKARA_OBSERVED` | Not evaluable: (1) ankara_labour_force_rates_2025 publishes only HLFS survey-modelled headline percentages (LFPR=53.91%, employment_rate=49.34%, unemployment_rate=8.48% of labour force) with ±1% confidence intervals for the non-institutional 15+ universe, without person counts or sex/age disaggregation (flag D7_PROVINCIAL_LABOUR_FORCE_RATES_ONLY_NO_SEX_OR_COUNTS); and (2) person-level labour_status in the core Ankara generator is UNAVAILABLE (None) rather than fabricated from non-comparable regional/rate tables. |
| `marginal_population` | `margin_household_size` | Marginal Household Size | **`NOT_EVALUABLE`** | NO | `ankara_household_size_2025` | `ANKARA_OBSERVED` | Not evaluable on resident-only population: (1) ankara_household_size_2025 is denominated in private households (expected_total=1,987,216, unit='household'), which does not reconcile to Ankara's 5,910,320 ADNKS resident population (implied private-household population = 5,690,627; unreconciled institutional/collective gap = 219,693 persons, flag D1_ANKARA_HH_VS_RESIDENT_POP_2025); (2) resident records keep household_size_class=None (UNAVAILABLE) rather than forcing an unverified person-to-household linkage; and (3) optional local raw file data/raw/ankara_household_size_2025.csv is absent in this clean checkout. |
| `marginal_population` | `margin_household_type` | Marginal Household Type | **`NOT_EVALUABLE`** | NO | `ankara_household_types_2025` | `ANKARA_OBSERVED` | Not evaluable on resident-only population: (1) ankara_household_types_2025 reports 1,987,216 private households (unit='household': one_person=407,306, nuclear_family=1,312,420, extended_family=193,972, non_family_multi_person=73,518; average_household_size=2.863618 -> 5,690,627 private-household residents), leaving an unreconciled 219,693-person gap vs Ankara's 5,910,320 ADNKS resident population (flag D1_ANKARA_HH_VS_RESIDENT_POP_2025); and (2) resident records keep household_type=None (UNAVAILABLE) because person-level household-type membership is not observed in provincial ADNKS tables. |
| `joint_dependency` | `joint_age_marital` | Age × Marital Status Joint Distribution | **`FAIL`** | NO | `—` | `national proxy, not Ankara-observed` | Demographic realism failure: Unrealistic teenage marriage rate: 44/71 (62.0%) teenagers aged 15-19 are married (expected <= 2.0% under TMK 124). | Unrealistic teenage widowhood: 4/71 teenagers aged 15-19 are widowed. | Unrealistic youth marriage rate: 83/145 (57.2%) youths aged 15-24 are married (national proxy benchmark is 7.1%, deviation = +50.2 pp). | Slice age_band=15-24: Significant deviation from benchmark: record TVD=0.6361 > threshold 0.1391, max |z|=29.22 > Bonferroni limit 3.02 (max PP dev=63.6 pp). | Slice age_band=25+: Significant deviation from benchmark: record TVD=0.1407 > threshold 0.1408, max |z|=10.00 > Bonferroni limit 3.02 (max PP dev=14.1 pp). | Slice age_band=15-19: Significant deviation from benchmark: record TVD=0.7124 > threshold 0.1333, max |z|=42.88 > Bonferroni limit 3.02 (max PP dev=71.2 pp). |
| `joint_dependency` | `joint_sex_age_marital` | Sex × Age × Marital Status 3-Way Joint Distribution | **`FAIL`** | NO | `—` | `national proxy, not Ankara-observed` | Sex-age conditional marital failure against National Proxy: Group (male, 15-24): Significant deviation from benchmark: record TVD=0.6527 > threshold 0.1421, max |z|=25.76 > Bonferroni limit 3.02 (max PP dev=65.3 pp). | Group (male, 25+): Significant deviation from benchmark: record TVD=0.1425 > threshold 0.1483, max |z|=6.44 > Bonferroni limit 3.02 (max PP dev=14.3 pp). | Group (female, 15-24): Significant deviation from benchmark: record TVD=0.6183 > threshold 0.1514, max |z|=17.37 > Bonferroni limit 3.02 (max PP dev=61.8 pp). | Group (female, 25+): Significant deviation from benchmark: record TVD=0.1400 > threshold 0.1496, max |z|=8.06 > Bonferroni limit 3.02 (max PP dev=14.0 pp). |
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

---

## 4. Simulation Results Evaluation Summary

- **Evaluated Personas:** `1,000`
- **Valid Completion Rate:** `99.5%` (995 valid, 5 failed)
- **Evidence Disclaimer:** SYNTHETIC SIMULATION BASELINE: All simulated response distributions represent generative agent persona outputs for software and pipeline evaluation. They CANNOT be interpreted as observed empirical human behavior, nor do they establish real-world predictive validity.

### Primary Question Response Distribution

| Option ID | Unweighted Share (%) | Weighted Share (%) | Standard Error (SE) |
|---|---:|---:|---:|
| `maintain_usage` | 25.4% | **25.2%** | ±1.38 pp |
| `reduce_optional_trips` | 30.3% | **30.2%** | ±1.46 pp |
| `switch_to_private_car_or_taxi` | 14.2% | **14.5%** | ±1.11 pp |
| `switch_to_walking` | 30.2% | **30.2%** | ±1.45 pp |