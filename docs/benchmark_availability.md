# Behavioral Benchmark Availability Assessment (K5)

- **Scenario:** Hypothetical 20% Increase in Ankara Public Transport Fares (`transport_fare_001`)
- **Author:** Koray (Data & Validation Engine)
- **Branch:** `feature/data-validation`
- **Date:** 2026-10-27
- **Target Interface:** [`src/societytwin/validation/behavioral.py`]
- **Core Principle:** Explicit validation instead of unverified claims of realism. Never fabricate ground truth. If no usable data exists, state the validation gap honestly.

---

## 1. Executive Summary & The Validation Gap

When simulating the behavioral response of synthetic personas to a policy intervention—such as a hypothetical 20% increase in standard public transit fares in Ankara (from 21.00 TL to 25.20 TL under the August 2024 UKOME baseline, or 40.00 TL to 48.00 TL under 2026 tariffs)—there is an unavoidable temptation in agentic simulation projects to compare generative agent responses directly against an invented "empirical ground truth".

**This document explicitly rejects that approach.**

### The Core Validation Gap
1. **No Controlled Empirical Micro-Data Exists in Ankara:**
   While the Ankara Metropolitan Municipality (ABB) and EGO General Directorate collect millions of daily electronic smartcard validations via the *Ankarakart* automated fare collection (AFC) system, **no econometric fare elasticity model, panel survey, or micro-level ridership dataset isolating price sensitivity has ever been published by EGO or municipal authorities**.
2. **Extreme Macroeconomic Confounding in Türkiye:**
   In Türkiye, annual consumer price inflation (CPI) exceeded 60–80% between 2022 and 2025. Municipal transit tariff hikes in Ankara (typically enacted once or twice a year by UKOME decisions) frequently represent **real price reductions** relative to general inflation, or lag behind sharp increases in diesel fuel prices. Consequently, time-series ridership changes around tariff adjustments reflect seasonal shifts (academic semesters, summer holidays), fuel-price cross-elasticity, and post-pandemic recovery rather than an isolated pure fare shock.
3. **Statutory Demographic Concessions Eliminate the Shock for Major Cohorts:**
   Under Turkish law (Law No. 4736), citizens aged 65 and older receive **100% free public transit** nationwide. Furthermore, Ankara students hold heavily subsidized flat-rate monthly subscription passes (*Öğrenci Abonman* at 200–650 TL for unlimited monthly rides). As a result, the standard 20% single-ride tariff increase applies primarily to working-age adults (ages 18–64) paying standard fares (*Tam Bilet*), while seniors and student subscribers experience **zero marginal price shock**.
4. **Stated Intention is NOT Equivalent to Observed Ridership Decrease:**
   In stated-preference (SP) surveys and synthetic agent simulations, individuals routinely state that they will "cut trips", "walk more", or "protest" a tariff hike. In revealed-preference (RP) reality, urban transit in Ankara is a captive, non-discretionary service for lower- and middle-income workers with fixed work locations, long commute distances (e.g., Sincan, Keçiören, Mamak to Kızılay/Çankaya), and steep topography. Stated intention systematically over-reports elasticity due to **hypothetical bias, protest sentiment, and neglect of physical asset constraints**.

---

## 2. Evidence Typology & Classification Standard

Every candidate benchmark source evaluated by the validation layer is classified into **exactly one** of four strictly defined evidence types:

| Evidence Type | Definition | Epistemic Status in Validation | Example in Transit Scenario |
|---|---|---|---|
| **`observed_behavior`** | Objective, physical, revealed-preference actions recorded without subjective filtering (turnstile taps, ticket sales, vehicle GPS). | **Gold standard for physical reality**, but rarely provides demographic breakdown or causal isolation. | EGO daily turnstile tap counts; annual boarding totals. |
| **`survey_response`** | Self-reported declarations gathered from human subjects via structured questionnaires (travel diaries, stated preferences, budget records). | **Subjective and cross-sectional**. Stated intentions reflect aspirations or protest, not guaranteed physical action. | TÜİK Household Budget Survey (HBA); AUAP household travel survey. |
| **`literature_estimate`** | Econometric parameters synthesized from peer-reviewed academic meta-analyses or external empirical studies. | **Theoretical benchmark / reference envelope**, but not ground truth for a specific city at a specific moment. | Litman (2023) / TRRL 920 global transit elasticity ($e_p \approx -0.33 \pm 0.15$). |
| **`hypothetical_assumption`** | Explicit operational assumptions or parameter choices used to specify a scenario or prompt an LLM agent. | **Model design construct only**. Under no circumstances can it be presented as empirical evidence. | SocietyTwin `transport_fare_001.yaml` choice distribution (`maintain_usage`, `reduce_optional_trips`, etc.). |

> [!IMPORTANT]
> **Non-Equivalence Rule:** A survey where 40% of people say *"I will reduce transit trips"* is classified as `survey_response`, NOT `observed_behavior`. An agent simulation predicting 45% trip reduction cannot claim "empirical validation" against that survey, nor can it claim that actual EGO ridership will drop by 45%.

---

## 3. Candidate Source Inventory & Benchmark Evaluation

The table below catalogs every candidate source identified for the Ankara 20% public transport fare increase scenario, its evidence classification, geographic resolution, measurement definition, and availability status.

| Candidate Source & Citation | Evidence Type | Geography | Year | Measurement Definition & Target Variable | Observed Value / Benchmark Range | Ground Truth? | Availability Status in Repo |
|---|---|---|---|---|---:|:---:|:---:|
| **Ankara EGO Boarding Statistics**<br>EGO Genel Müdürlüğü 2024 Faaliyet Raporu ([ego.gov.tr](https://www.ego.gov.tr/tr/kategori/17/raporlar-ve-istatistikler)) | `observed_behavior` | `06` (Ankara) | 2020–2025 | Total passenger boardings across Bus, Metro, and Ankaray via smartcard validations. | ~1.2M–1.4M daily boardings (Aggregate totals only) | **YES** (for volume); **NO** (for elasticity) | **`UNAVAILABLE`**<br>(No econometric elasticity model published) |
| **Global Transit Fare Elasticity Meta-Analysis**<br>Todd Litman (VTPI, 2023) / TRRL 920 ([vtpi.org](https://www.vtpi.org/tranelas.pdf)) | `literature_estimate` | `GLOBAL` | 2023 (1980–2023 meta) | Short-run price elasticity of transit demand: $e_p = \frac{\% \Delta Q}{\% \Delta P}$ (Simpson-Curtin rule). | **$e_p \in [-0.50, -0.20]$**<br>(Central estimate: $-0.33$) | **NO** (External literature proxy) | **`AVAILABLE`**<br>(Reference range for reasonableness) |
| **Ankara Pre-Policy Stated Preference Survey**<br>Hypothetical UKOME Survey ([N/A](#)) | `survey_response` | `06` (Ankara) | None | Stated transit usage adjustment following a 20% fare increase. | *None published* | **NO** (Stated intention) | **`UNAVAILABLE`**<br>(No representative survey archived) |
| **TÜİK Household Budget Survey (HBA)**<br>TÜİK Haber Bülteni Sayı: 49635 ([tuik.gov.tr](https://data.tuik.gov.tr/Bulten/Index?p=Hanehalki-Tuketim-Harcamasi-(Bolgesel)-2022-2024-49635)) | `survey_response` | `TR51` (Ankara) | 2022–2024 | Share of total household consumption expenditure allocated to COICOP 07 (Transportation). | **$23.6\%$** of household expenditure (2nd highest in Türkiye) | **NO** (Expenditure share, not trip elasticity) | **`AVAILABLE`**<br>(Demonstrates high price sensitivity) |
| **Ankara Transportation Master Plan (AUAP / SKUP)**<br>EGO & Gazi University AUAP 2038 / SKUP Ankara 2050 ([ego.gov.tr](https://www.ego.gov.tr)) | `survey_response` | `06` (Ankara) | 2015–2024 | Baseline modal split across all mechanized and non-motorized urban trips. | **~$32\%$** public transit share ($30–35\%$ range) | **NO** (Cross-sectional modal baseline) | **`AVAILABLE`**<br>(Structural modal split baseline) |
| **SocietyTwin Scenario Design Specification**<br>Pakhlavon / SocietyTwin Module ([transport_fare_001.yaml]) | `hypothetical_assumption` | `06` (Ankara) | 2024 | Categorical option distribution across five prompt responses. | Discrete options (maintain, reduce, walk, car/taxi, unsure) | **NO** (Simulation construct) | **`AVAILABLE`**<br>(Scenario specification parameter) |

---

## 4. In-Depth Analysis of Candidate Sources

### 4.1 Ankara EGO Boarding Statistics (`observed_behavior`)
- **What it Measures:** Total electronic smartcard boardings per day and per year disaggregated by transport mode (EGO bus, Metro, Ankaray, ÖHO/ÖTA private buses) and ticket category (full adult, discounted student/teacher, free concessions).
- **Geography:** Ankara Metropolitan Area (`06`).
- **Year:** Annual (2020–2025; e.g. EGO 2024 Administrative Activity Report).
- **Sample / Denominator:** Complete census of electronic validations (approx. 1.2–1.4 million validations per day).
- **Method:** Automated Fare Collection (AFC) turnstile transaction logging.
- **Limitations:**
  1. Confounded by Macro Inflation: When UKOME increased standard fares from 15.00 TL to 21.00 TL in August 2024 (+40%), general annual inflation was 62%. In real terms, the transit fare was cheaper than in 2022.
  2. Aggregate-Only: EGO does not publish panel data tracking whether individual riders reduced trips.
  3. No Econometric Model: No published elasticity coefficient ($e_p$) exists for Ankara. Inserting an ad-hoc number would violate the project's non-fabrication rule.
- **Validation Role:** **Unavailable as an elasticity benchmark**. Serves as environmental context for overall transit ridership volume.

### 4.2 Literature Meta-Estimates: Litman / TRRL (`literature_estimate`)
- **What it Measures:** Short-run and long-run price elasticity of public transit demand ($e_p = \frac{\Delta Q / Q}{\Delta P / P}$).
- **Geography:** Global meta-analyses covering North American, European, and Asian transit systems.
- **Year:** 1980–2023 syntheses (Litman, 2023; TRRL Report 920; Balcombe et al., 2004).
- **Sample / Denominator:** Meta-analysis of over 100 empirical transit studies.
- **Method:** Econometric time-series regressions and log-log demand models.
- **Baseline Expectations:**
  - Standard Simpson-Curtin rule: $e_p \approx -0.33 \pm 0.15$.
  - Short-run transit elasticity: $-0.20$ to $-0.50$.
  - Peak/commute trips: highly inelastic ($-0.10$ to $-0.20$).
  - Off-peak/discretionary trips: moderately elastic ($-0.40$ to $-0.60$).
- **Implication for 20% Fare Increase:**
  Under standard literature assumptions, a 20% nominal fare increase in a stable currency typically produces a **$-4.0\%$ to $-8.0\%$ drop in overall ridership**.
- **Limitations:**
  1. Developed in countries with stable price levels (2–5% inflation).
  2. Does not account for Türkiye's specific structural concessions (65+ statutory free transit, student monthly flat passes).
- **Validation Role:** **Available as a literature reference envelope**. Provides a plausibility sanity check for aggregate agent behavior, but cannot be treated as observed Ankara ground truth.

### 4.3 Stated Intentions vs. Revealed Preferences (`survey_response`)
- **What it Measures:** Self-reported hypothetical answers to: *"If fares increase by 20%, how will you change your usage?"*
- **Geography:** Ankara (`06`).
- **Validation Gap:** No representative pre-policy stated preference survey was commissioned or publicly archived for the specific 2024 UKOME fare revision.
- **The Stated vs. Revealed Gap:**
  - In stated preference surveys, respondents consistently exhibit **protest bias** and **hypothetical bias**. When faced with a hypothetical price hike, 40–50% of survey respondents often claim they will "boycott", "walk", or "reduce trips".
  - When the tariff actually takes effect, revealed boarding drops are typically under 5–8% because:
    1. Working adults cannot cut commute trips to their jobs.
    2. Ankara's terrain and distances make walking 10–15 km impossible for daily commutes.
    3. Private car ownership requires major capital assets and fuel expenses that low-income transit riders do not possess.
- **Validation Role:** **Marked as unavailable**. The validation engine strictly prevents treating hypothetical stated responses as physical ridership loss.

### 4.4 TÜİK Regional Household Consumption Expenditure (`survey_response`)
- **What it Measures:** Percentage of total household consumption expenditure spent on transportation (COICOP 07) across NUTS-2 regions.
- **Geography:** NUTS-2 TR51 (Ankara Province).
- **Year:** 2022–2024 (TÜİK Press Release No. 49635, published June 2024).
- **Sample / Denominator:** Representative sample of Ankara private households keeping monthly expenditure diaries.
- **Observed Value:** **23.6%** of total household expenditure in Ankara goes to transportation (second highest in Türkiye, surpassed only by TR42 at 25.0%).
- **Limitations:** Conflates vehicle purchases, fuel, repairs, and public transit fares. Cannot isolate public bus/metro tickets.
- **Validation Role:** **Available as economic context**. Validates that Ankara households operate under high transportation budget constraints, explaining high sensitivity to tariff adjustments.

### 4.5 Ankara Transportation Master Plan (AUAP / SKUP) Modal Split (`survey_response`)
- **What it Measures:** Proportional distribution of daily urban trips across transport modes (EGO bus, Metro/Ankaray, dolmuş, private car, service shuttle, walking).
- **Geography:** Ankara Metropolitan Area (`06`).
- **Year:** Baseline surveys 2013–2015 (AUAP 2038) and 2022–2024 updates (SKUP Ankara 2050).
- **Observed Value:** Public transit accounts for approximately **30–35%** (midpoint ~32%) of total daily mechanized/active trips.
- **Limitations:** Represents cross-sectional baseline habits under pre-existing fare structures, not marginal elasticity to tariff shocks.
- **Validation Role:** **Available as structural baseline**. Used to verify that synthetic personas assigned to public transit match Ankara's real modal share.

---

## 5. Interface Specification in `src/societytwin/validation/behavioral.py`

To enforce these principles in code without fabricating ground truth, [`src/societytwin/validation/behavioral.py`] implements an **interface-only design**:

1. **[`BenchmarkSpec`]:**
   - Captures `benchmark_id`, `name`, `scenario_id`, `status` (`available | unavailable | insufficient_metadata`), `evidence_type` (`observed_behavior | survey_response | literature_estimate | hypothetical_assumption`), `provenance` ([`BenchmarkProvenance`]), `measurement` ([`MeasurementDefinition`]), and `comparability` ([`ComparabilityNotes`]).
   - Supports `observed_value: float | None`, `observed_range: tuple[float, float] | None`, and mandatory `unavailability_reason: str | None`.
2. **[`BenchmarkBundle`]:**
   - Bundles benchmarks for a scenario, providing query methods (`available_benchmarks()`, `unavailable_benchmarks()`, `by_evidence_type()`) and Markdown reporting (`to_markdown()`).
3. **Canonical Ankara Fare Bundle ([`get_ankara_transit_fare_bundle()`]):**
   - Instantiates the 6 candidate benchmarks evaluated above.
   - Accurately reports `ankara_ego_observed_elasticity` and `ankara_stated_travel_intention` as **`unavailable`** with explicit reasons.
   - Reports `literature_transit_fare_elasticity`, `tuik_tr51_household_transport_expenditure_share`, and `auap_ankara_transit_modal_split` as **`available`** with verified citations.

---

## 6. Recommendations for Scenario (Pakhlavon) & Runtime (Sam) Agents

1. **Do NOT Claim Empirical Validation of Stated Intentions:**
   When runtime agents answer the `transport_fare_001` questionnaire, their aggregated responses (e.g. 35% maintain usage, 40% reduce trips, 20% walk) must be reported as **simulated stated preference distributions**, NOT observed transit ridership decreases.
2. **Check Persona Plausibility Against Structural Constraints:**
   - Persona aged 65+ stating *"I will stop traveling because fares increased by 20%"* is a **hallucination/model defect**, because statutory free transit for 65+ under Law No. 4736 means their fare remains 0.00 TL.
   - Persona with high household income and car ownership stating *"I will walk 15 km in winter to save 4.20 TL"* violates economic rationality and physical feasibility.
3. **Use Literature Envelopes as Plausibility Bounds:**
   While literature estimates ($-0.20 \le e_p \le -0.50$) cannot serve as Ankara ground truth, an agent simulation implying an elasticity of $-3.5$ (e.g. 70% ridership drop for a 20% fare hike) is wildly implausible and should trigger a validation warning.
