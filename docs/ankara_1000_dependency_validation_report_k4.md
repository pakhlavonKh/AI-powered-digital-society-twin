# K4 Dependency & Joint-Distribution Validation Report — `pop-06-2025-n1000-s42-e6a8e87e`

- **Population ID:** `pop-06-2025-n1000-s42-e6a8e87e`
- **Population Version:** `national-generator-1.1`
- **Reference Package:** `ankara-reference-package-k2-2025.1` (`fa0971ff615e7914...`)
- **Geography / Year:** `06` / `2025`
- **Sample Size ($n$):** `1,000` records (Weighted Total: `5,910,320.0`)
- **Seed:** `42`
- **Overall Status:** **`FAIL`** (`pass=5`, `fail=2`, `not_evaluable=3`)
- **Summary:** Population failed 2 validation check(s): ['joint_age_marital', 'joint_sex_age_marital'].

---

## 1. Calibrated Margins (K3 Calibration Enforcement)

Margins intentionally calibrated via raking or root proportional allocation.

| Margin | Status | Dataset ID | Denominator | Weighted TVD | Record TVD | Expected TVD ($n$) | Reason |
|---|---|---|---:|---:|---:|---:|---|
| `age` | **`PASS`** | `ankara_age_sex_2025` | `ADNKS_residents_all` | 0.000000 | 0.003559 | 0.050611 | Calibrated margin 'age' passed: weighted TVD=5.35e-14 (<= 1.0e-05), max weighted pp deviation=2.56e-12 pp; unweighted record TVD=0.0036 (expected 0.0506 for n=1000), max |z|=0.19 (<= 3.47). |
| `sex` | **`PASS`** | `ankara_age_sex_2025` | `ADNKS_residents_all` | 0.000000 | 0.000673 | 0.012614 | Calibrated margin 'sex' passed: weighted TVD=3.61e-16 (<= 1.0e-05), max weighted pp deviation=3.89e-14 pp; unweighted record TVD=0.0007 (expected 0.0126 for n=1000), max |z|=0.04 (<= 2.81). |
| `age_sex` | **`PASS`** | `ankara_age_sex_2025` | `ADNKS_residents_all` | 0.000000 | 0.004950 | 0.072667 | Calibrated margin 'age_sex' passed: weighted TVD=7.22e-14 (<= 1.0e-05), max weighted pp deviation=2.36e-12 pp; unweighted record TVD=0.0049 (expected 0.0727 for n=1000), max |z|=0.22 (<= 3.65). |
| `marital_status` | **`PASS`** | `ankara_marital_sex_2025` | `ADNKS_residents_15plus` | 0.000000 | 0.019052 | 0.027250 | Calibrated margin 'marital_status' passed: weighted TVD=1.19e-14 (<= 1.0e-05), max weighted pp deviation=1.88e-12 pp; unweighted record TVD=0.0191 (expected 0.0272 for n=822), max |z|=1.20 (<= 3.23). |
| `education` | **`PASS`** | `ankara_education_sex_2025` | `NESD_15plus_domestic_education_register` | 0.000000 | 0.043820 | 0.047059 | Calibrated margin 'education' passed: weighted TVD=1.63e-16 (<= 1.0e-05), max weighted pp deviation=2.22e-14 pp; unweighted record TVD=0.0438 (expected 0.0471 for n=822), max |z|=2.19 (<= 3.48). |

---

## 2. Supported Joint Checks (Multidimensional Empirical & Proxy Benchmarks)

Joint distributions evaluated against official empirical sources or explicit national proxy benchmarks.
All national proxies are visibly tagged `[national proxy, not Ankara-observed]`.

| Check ID | Dimensions | Status | Scope Marker | Reference Dataset | Record TVD | Max $|z|$ | Reason |
|---|---|---|---|---|---:|---:|---|
| `joint_age_marital` | `age_band × marital_status` | **`FAIL`** | `national proxy, not Ankara-observed` | `national_marital_broad_age_sex_2025` | 0.2280 | 42.88 | Demographic realism failure: Unrealistic teenage marriage rate: 44/71 (62.0%) teenagers aged 15-19 are married (expected <= 2.0% under TMK 124). | Unrealistic teenage widowhood: 4/71 teenagers aged 15-19 are widowed. | Unrealistic youth marriage rate: 83/145 (57.2%) youths aged 15-24 are married (national proxy benchmark is 7.1%, deviation = +50.2 pp). | Slice age_band=15-24: Significant deviation from benchmark: record TVD=0.6361 > threshold 0.1391, max |z|=29.22 > Bonferroni limit 3.02 (max PP dev=63.6 pp). | Slice age_band=25+: Significant deviation from benchmark: record TVD=0.1407 > threshold 0.1408, max |z|=10.00 > Bonferroni limit 3.02 (max PP dev=14.1 pp). | Slice age_band=15-19: Significant deviation from benchmark: record TVD=0.7124 > threshold 0.1333, max |z|=42.88 > Bonferroni limit 3.02 (max PP dev=71.2 pp). |
| `joint_sex_age_marital` | `sex × age_band × marital_status` | **`FAIL`** | `national proxy, not Ankara-observed` | `national_marital_broad_age_sex_2025` | 0.2285 | 25.76 | Sex-age conditional marital failure against National Proxy: Group (male, 15-24): Significant deviation from benchmark: record TVD=0.6527 > threshold 0.1421, max |z|=25.76 > Bonferroni limit 3.02 (max PP dev=65.3 pp). | Group (male, 25+): Significant deviation from benchmark: record TVD=0.1425 > threshold 0.1483, max |z|=6.44 > Bonferroni limit 3.02 (max PP dev=14.3 pp). | Group (female, 15-24): Significant deviation from benchmark: record TVD=0.6183 > threshold 0.1514, max |z|=17.37 > Bonferroni limit 3.02 (max PP dev=61.8 pp). | Group (female, 25+): Significant deviation from benchmark: record TVD=0.1400 > threshold 0.1496, max |z|=8.06 > Bonferroni limit 3.02 (max PP dev=14.0 pp). |

---

## 3. Unverified Relationships (Unobserved in Official Tables — Zero Invented Benchmarks)

Relationships where no empirical reference exists at target geography. Status is strictly `not_evaluable`.
Deterministic structural zero rules (e.g. minimum education completion ages) are verified independently.

| Relationship | Dimensions | Status | Scope Marker | Structural Violations | Policy / Verification Reason |
|---|---|---|---|---:|---|
| `joint_age_education` | `age × education_level` | **`NOT_EVALUABLE`** | `unverified (no empirical reference)` | `0` | Empirical age × education joint distribution is unobserved in published TÜİK tables; benchmark not invented per validation protocol. Deterministic minimum-completion-age rules and under-15 education gate verified (0 structural zero violations). |
| `joint_age_employment` | `age × labour_status` | **`NOT_EVALUABLE`** | `unverified (no empirical reference)` | `0` | Empirical person-level labour force status is not modelled in baseline generator (marked UNAVAILABLE in dependency registry); TÜİK provincial labour indicators publish aggregate headline survey rates only without age-conditional joint counts. Benchmark not invented per validation protocol. |
| `joint_household_size_type` | `household_type × household_size_class` | **`NOT_EVALUABLE`** | `unverified (no empirical reference)` | `0` | Household type × size joint distribution unlinked in resident population (D1 discrepancy: 1,987,216 private households vs 5,910,320 residents; person-to-household micro-linkage is unobserved in TÜİK tables and forbidden in baseline model). |

---

## 4. Documented Data Quality Flags Attached to Evaluated Distributions

### `D1_ANKARA_HH_VS_RESIDENT_POP_2025`: Ankara 2025 private household count (1,987,216) and implied private-household population (1,987,216 × 2.86361774462363 = 5,690,627 persons; or 5,683,438 using rounded 2.86) do NOT reconcile to total ADNKS resident population (5,910,320 persons). Exact unreconciled gap: 219,693 persons (3.7171% of Ankara resident population).
- **Issue Type:** `denominator_inconsistency` (Severity: `high`)
- **Policy:** `document_do_not_force` (Do NOT force a reconciliation)
- **Root Causes:**
  - 1. Institutional/collective population exclusion: ADNKS total resident population (5,910,320) includes institutional/collective places (KYK and private university dormitories, military barracks, prisons, nursing homes, hospitals), which are excluded by definition from ADNKS_private_households (1,987,216).
  - 2. Open-ended 10+ household size tail: In the NIP household size table (1..9, 10+), the 10+ class has only a known lower bound (10) and no published upper bound or exact mean size.
  - 3. Different reference years & multi-year averaging across household tables: 2021 Building & Dwelling Survey reports 1,874,093 households (2021 ADNKS base), while 2023 SES reports 1,927,404.67 households (2022–2024 3-year administrative register average).
  - 4. Absence of public person-to-household micro-linkage tables at Ankara (06) level.

### `D2_ANKARA_EDUCATION_15PLUS_VS_ADNKS_15PLUS_2025`: Ankara 2025 NESD Education 15+ total (4,751,123: 2,322,692 male, 2,428,431 female) is 104,983 persons (2.1619%) smaller than Ankara 2025 ADNKS 15+ resident population (4,856,106: 2,371,482 male, 2,484,624 female). Nationally in 2025, the gap is 1,340,559 persons (67,220,886 vs 68,561,445) and correlates r = 0.999766 across all 81 provinces with foreign resident population (T12).
- **Issue Type:** `universe_coverage_gap` (Severity: `high`)
- **Policy:** `preserve_unknown_category` (Do NOT force a reconciliation)
- **Root Causes:**
  - 1. NESD (Ulusal Eğitim İstatistikleri Veri Tabanı) derives diploma attainment from domestic MERNİS/MEB/YÖK registers, excluding most foreign nationals residing in Türkiye on residence permits (128,633 in Ankara 2025).
  - 2. Published 'unknown' (Bilinmeyen) category (17,626 in Ankara 2025: 7,474 male, 10,152 female) is part of the 4,751,123 NESD total and must be preserved as a distinct category, never silently dropped.

### `D7_PROVINCIAL_LABOUR_FORCE_RATES_ONLY_NO_SEX_OR_COUNTS`: Provincial labor_force_indicators.csv (2022–2025) publishes only headline 15+ model-estimated percentages (LFPR 53.91%, employment rate 49.34%, unemployment rate 8.48% in Ankara 2025) with 95% confidence intervals, without sex breakdown, age breakdown, or person counts (contrary to package README.md line 51).
- **Issue Type:** `rate_only_no_counts` (Severity: `high`)
- **Policy:** `not_evaluable_for_person_counts` (Do NOT force a reconciliation)
- **Root Causes:**
  - 1. Detailed Household Labour Force Survey (HLFS) tables by sex, age, and education are published only at NUTS-2 (TR51) and National (TR) levels (see not_province_level.csv).
  - 2. Converting survey model rates with ±1% CIs into exact integer person counts would fabricate precision.
