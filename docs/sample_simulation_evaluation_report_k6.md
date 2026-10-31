# K6 Simulation Results Evaluation Report — `run-ankara-20pct-fare-synthetic-100`

- **Scenario ID:** `transport_fare_001`
- **Run ID:** `run-ankara-20pct-fare-synthetic-100`
- **Evaluated At:** `2026-10-30T13:45:26.393947+00:00`
- **Evaluated Personas:** `100` (Weighted Total: `5,594,554.3`)
- **Valid Responses:** `95` / `100` (95.0% Completion Rate)
- **Total Failures / Refusals:** `5`

> [!IMPORTANT]
> **Evidence Status:** SYNTHETIC SIMULATION BASELINE: All simulated response distributions represent generative agent persona outputs for software and pipeline evaluation. They CANNOT be interpreted as observed empirical human behavior, nor do they establish real-world predictive validity.

> [!NOTE]
> **Validation Gap:** VALIDATION GAP: No empirical econometric fare elasticity micro-data exists in Ankara (EGO publishes raw boardings only). Missing benchmarks are reported as 'unavailable' in accordance with project rules. Literature elasticity envelopes (-0.20 to -0.50) serve only as broad plausibility sanity checks.

---

## 1. Response Distributions (Overall & Weighted)

### Question `q1_usage_change` ($n = 95$, Weighted = 5,594,554.3)

| Option ID | Unweighted Count | Unweighted Share (%) | Weighted Share (%) | Standard Error (SE pp) |
|---|---:|---:|---:|---:|
| `maintain_usage` | 25 | 26.3% | **26.8%** | ±4.52 pp |
| `reduce_optional_trips` | 29 | 30.5% | **30.7%** | ±4.72 pp |
| `switch_to_private_car_or_taxi` | 13 | 13.7% | **13.1%** | ±3.53 pp |
| `switch_to_walking` | 28 | 29.5% | **29.5%** | ±4.68 pp |

### Question `q2_policy_support` ($n = 95$, Weighted = 5,594,554.3)

| Option ID | Unweighted Count | Unweighted Share (%) | Weighted Share (%) | Standard Error (SE pp) |
|---|---:|---:|---:|---:|
| `neutral` | 10 | 10.5% | **11.6%** | ±3.15 pp |
| `somewhat_oppose` | 41 | 43.2% | **42.6%** | ±5.08 pp |
| `somewhat_support` | 15 | 15.8% | **15.2%** | ±3.74 pp |
| `strongly_oppose` | 29 | 30.5% | **30.6%** | ±4.72 pp |

---

## 2. Demographic Subgroup Comparisons & Confidence Flags

Small subgroups ($n < 15$) are explicitly flagged as `LOW CONFIDENCE` rather than emitting misleading intervals.

| Subgroup Dimension | Segment | Sample $n$ | Weighted Total | Confidence Flag | Top Choice (Weighted %) | Second Choice (Weighted %) |
|---|---|---:|---:|:---:|---|---|
| `age_bracket` | `18-29 (young adult)` | 19 | 1,073,804.9 | **`ADEQUATE`** | `switch_to_walking` (45.2%) | `reduce_optional_trips` (33.1%) |
| `age_bracket` | `30-44 (middle age)` | 23 | 1,322,951.7 | **`ADEQUATE`** | `switch_to_private_car_or_taxi` (28.1%) | `switch_to_walking` (26.9%) |
| `age_bracket` | `45-64 (older adult)` | 25 | 1,444,365.8 | **`ADEQUATE`** | `reduce_optional_trips` (30.1%) | `maintain_usage` (29.4%) |
| `age_bracket` | `65+ (senior)` | 10 | 648,434.0 | **`LOW CONFIDENCE`** | `maintain_usage` (100.0%) | — |
| `age_bracket` | `<18 (minor)` | 18 | 1,104,997.9 | **`ADEQUATE`** | `reduce_optional_trips` (56.3%) | `switch_to_walking` (43.7%) |
| `sex` | `female` | 48 | 2,861,280.6 | **`ADEQUATE`** | `switch_to_walking` (31.9%) | `reduce_optional_trips` (29.4%) |
| `sex` | `male` | 47 | 2,733,273.8 | **`ADEQUATE`** | `reduce_optional_trips` (32.0%) | `switch_to_walking` (27.0%) |
| `marital_status` | `divorced` | 5 | 249,456.0 | **`LOW CONFIDENCE`** | `reduce_optional_trips` (53.8%) | `switch_to_private_car_or_taxi` (26.7%) |
| `marital_status` | `married` | 46 | 2,824,991.2 | **`ADEQUATE`** | `maintain_usage` (39.5%) | `reduce_optional_trips` (25.6%) |
| `marital_status` | `never_married` | 23 | 1,366,660.2 | **`ADEQUATE`** | `switch_to_walking` (41.2%) | `reduce_optional_trips` (22.3%) |
| `marital_status` | `not_applicable` | 15 | 938,549.0 | **`ADEQUATE`** | `reduce_optional_trips` (54.3%) | `switch_to_walking` (45.7%) |
| `marital_status` | `widowed` | 6 | 214,898.0 | **`LOW CONFIDENCE`** | `maintain_usage` (47.2%) | `switch_to_private_car_or_taxi` (32.9%) |
| `education_level` | `basic_8yr` | 8 | 448,703.2 | **`LOW CONFIDENCE`** | `maintain_usage` (40.3%) | `reduce_optional_trips` (34.1%) |
| `education_level` | `higher_education` | 21 | 1,269,634.0 | **`ADEQUATE`** | `switch_to_walking` (42.1%) | `reduce_optional_trips` (21.2%) |
| `education_level` | `illiterate` | 1 | 73,346.3 | **`LOW CONFIDENCE`** | `switch_to_private_car_or_taxi` (100.0%) | — |
| `education_level` | `literate_no_diploma` | 1 | 58,364.2 | **`LOW CONFIDENCE`** | `switch_to_walking` (100.0%) | — |
| `education_level` | `lower_secondary` | 8 | 419,167.2 | **`LOW CONFIDENCE`** | `switch_to_walking` (37.9%) | `maintain_usage` (34.2%) |
| `education_level` | `masters` | 5 | 284,054.0 | **`LOW CONFIDENCE`** | `switch_to_walking` (68.2%) | `switch_to_private_car_or_taxi` (16.5%) |
| `education_level` | `not_applicable` | 15 | 938,549.0 | **`ADEQUATE`** | `reduce_optional_trips` (54.3%) | `switch_to_walking` (45.7%) |
| `education_level` | `primary` | 12 | 730,739.6 | **`LOW CONFIDENCE`** | `maintain_usage` (52.4%) | `reduce_optional_trips` (41.0%) |
| `education_level` | `unknown` | 1 | 48,850.7 | **`LOW CONFIDENCE`** | `reduce_optional_trips` (100.0%) | — |
| `education_level` | `upper_secondary` | 23 | 1,323,146.1 | **`ADEQUATE`** | `maintain_usage` (39.6%) | `reduce_optional_trips` (25.2%) |
| `statutory_concession` | `senior_free_concession_law4736` | 10 | 648,434.0 | **`LOW CONFIDENCE`** | `maintain_usage` (100.0%) | — |
| `statutory_concession` | `standard_fare_passenger` | 85 | 4,946,120.3 | **`ADEQUATE`** | `reduce_optional_trips` (34.7%) | `switch_to_walking` (33.4%) |

---

## 3. Behavioral Benchmark Comparisons & Ground Truth Reality

| Benchmark ID | Evidence Type | Status | Benchmark Value | Simulated Value | Difference (pp) | Within Envelope? |
|---|---|:---:|---:|---:|---:|:---:|
| `ankara_ego_observed_elasticity` | `observed_behavior` | **`UNAVAILABLE`** | Unavailable | — | — | N/A |
| `literature_transit_fare_elasticity` | `literature_estimate` | **`AVAILABLE`** | -0.33 | 30.7 | +24.1 pp | NO |
| `ankara_stated_travel_intention` | `survey_response` | **`UNAVAILABLE`** | Unavailable | — | — | N/A |
| `tuik_tr51_household_transport_expenditure_share` | `survey_response` | **`AVAILABLE`** | 23.6 | — | — | YES |
| `auap_ankara_transit_modal_split` | `survey_response` | **`AVAILABLE`** | 0.32 | — | — | N/A |
| `hypothetical_agent_fare_reduction_assumption` | `hypothetical_assumption` | **`AVAILABLE`** | Unavailable | — | — | N/A |

---

## 4. Baseline-vs-Intervention Synthetic Comparison

> [!WARNING]
> **Disclaimer:** All deltas below compare two synthetic simulation runs (e.g. status-quo baseline vs. 20% fare increase). They evaluate pipeline responsiveness and persona logic, NOT predictive accuracy.

| Metric / Option | Baseline Share (%) | Intervention Share (%) | Delta (pp) | Relative Change (%) |
|---|---:|---:|---:|---:|
| `q1_usage_change:maintain_usage` | 100.0% | 26.3% | **-73.7 pp** | -73.7% |
| `q1_usage_change:reduce_optional_trips` | 0.0% | 30.5% | **+30.5 pp** | +0.0% |
| `q1_usage_change:switch_to_private_car_or_taxi` | 0.0% | 13.7% | **+13.7 pp** | +0.0% |
| `q1_usage_change:switch_to_walking` | 0.0% | 29.5% | **+29.5 pp** | +0.0% |

---

## 5. Failure & Non-Response Audit Summary

- **Total Personas Dispatched:** `100`
- **Successful Valid Responses:** `95`
- **Total Non-Valid / Refused:** `5`
- **Failure Breakdown by Status:**
  - `valid`: 95
  - `invalid`: 2
  - `failed`: 1
  - `refused`: 1
  - `timeout`: 1
- **Sample Error Messages:**
  - `HTTP 500 error`
  - `Invalid choice`
  - `Missing q1 answer`
  - `Timeout after 60s`
  - `User refused`