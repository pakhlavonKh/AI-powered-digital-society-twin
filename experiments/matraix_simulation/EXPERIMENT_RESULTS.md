# SocietyTwin / MatrAIx Live Simulation Experiment Report

- **Date:** 2026-10-15
- **Branch:** `matraix-simulation`
- **Experiment Type:** Two-Persona Conditioned A/B Survey Simulation
- **Survey Task:** `application/tasks/example-survey_product-feedback`
- **Output Directory:** `experiments/matraix_simulation/runs/matraix_ab_live`

---

## 1. Executive Summary & Verdict

> **Verdict: Technical Success with 100% Behavioral Divergence Under Demographic Conditioning.**
>
> 1. **Engineering Pipeline Execution:** Fully validated. The end-to-end stack—from TÜİK demographic baseline extraction, through synthetic population generation, persona adaptation, and the MatrAIx survey runtime to live OpenAI `gpt-4o` completion—ran cleanly with zero errors, zero retries, and strict compliance with the two-call safety limit.
> 2. **Behavioral Divergence:** **9 out of 9 answers differed** between Persona A and Persona B. Demographic context alone was sufficient for the model to produce distinct, coherent consumer profiles.
> 3. **Sociological Realism vs. Model Priors:** Persona A (45–49, married) acted as an ROI-focused, pragmatic software adopter. Persona B (80–84, widowed) exhibited strong tech reluctance and total subscription rejection. Because economic and digital literacy dimensions were not explicitly specified in the minimal schema, the LLM bridged the gap using its pre-trained societal priors.

---

## 2. Experiment Configuration & Execution Metrics

| Parameter | Configuration / Metric |
|---|---|
| **Model** | `openai/gpt-4o` |
| **Sampling Temperature** | `0.0` (deterministic greedy decoding) |
| **Provider** | OpenAI Direct API |
| **Runtime Duration** | 34.33 seconds |
| **Total Calls Made** | 2 (Trial A: 1 call, Trial B: 1 call) |
| **Max Output Tokens** | Uncapped (`null`), actual used: 450 tokens |
| **Total Input Tokens** | 3,913 tokens (Trial A: 1,956, Trial B: 1,957) |
| **Total Output Tokens** | 450 tokens (Trial A: 256, Trial B: 194) |
| **Total Cost (USD)** | **$0.01428** |
| **Private Metadata Leakage** | 0 leaks (SHA256 hashes and seeds blocked from model prompt) |

---

## 3. Persona Profiles & Demographic Lineage

Both personas were sampled deterministically from the Ankara 2025 synthetic population fixture (`ankara_population_1000_v2.csv`, seed 42) calibrated against official TÜİK statistics.

```mermaid
flowchart TD
    TUIK["TÜİK 2025 Statistics (Ankara)"] --> Pop["Synthetic Population (1,000 residents)"]
    Pop --> PA["Persona A (ANK2025_000001)"]
    Pop --> PB["Persona B (ANK2025_000183)"]
    PA --> LiveA["Live Survey Trial A (gpt-4o)"]
    PB --> LiveB["Live Survey Trial B (gpt-4o)"]
    LiveA --> Comp["Structured Comparison (9/9 differing)"]
    LiveB --> Comp
```

### Persona A (`ANK2025_000001`)
- **Province:** Ankara, Türkiye
- **Age Group:** 45–49 (MatrAIx bracket: `45-54`)
- **Gender:** Female
- **Marital Status:** Married (`Evli`)
- **Conditioning Mode:** Gender-only baseline

### Persona B (`ANK2025_000183`)
- **Province:** Ankara, Türkiye
- **Age Group:** 80–84 (MatrAIx bracket: `75-84`)
- **Gender:** Female
- **Marital Status:** Widowed (`Eşi öldü`)
- **Conditioning Mode:** Gender-only baseline

---

## 4. Full Question-by-Question Comparison

| Question ID | Question Prompt | Persona A Answer (`ANK2025_000001`) | Persona B Answer (`ANK2025_000183`) | Value Differs? | Behavioral Difference Analysis |
|---|---|---|---|:---:|---|
| **overall_interest** | *Overall interest in this product.* | **`4` (High)** | **`1` (Minimal/None)** | **YES** | Persona A finds active value in organizational tools; Persona B finds zero relevance. |
| **would_try_beta** | *Would you try a beta version?* | **`"true"` (Yes)** | **`"false"` (No)** | **YES** | Persona A is receptive to early technology; Persona B avoids unproven software. |
| **q0** | *After trying the free version, your realistic plan is...* | `"q0_pay_when_roi_clear"` | `"q0_not_interested"` | **YES** | Persona A evaluates return on investment; Persona B drops out immediately. |
| **q1** | *Plus vs Pro ($5 more per month)...* | `"q1_plus_after_sustained_use"` | `"q1_reject_both_tiers"` | **YES** | Persona A adopts entry tier after habit formation; Persona B rejects all subscriptions. |
| **q2** | *Annual vs monthly billing...* | `"q2_annual_after_long_use"` | `"q2_monthly_cancel_anytime"` | **YES** | Persona A optimizes for long-term savings; Persona B avoids financial lock-in. |
| **q3** | *A limited $1 first-month Plus promo...* | `"q3_one_dollar_try_cancel"` | `"q3_skip_even_one_dollar"` | **YES** | Persona A exploits low-risk promotion; Persona B rejects even nominal spend. |
| **q4** | *A friend uses a paid organizer app...* | `"q4_compare_pay_if_wins"` | `"q4_seek_free_alternative"` | **YES** | Persona A benchmarks alternatives by merit; Persona B defaults to free-only solutions. |
| **q5** | *Ads on free vs paying to remove them...* | `"q5_ads_pay_if_plus_useful"` | `"q5_ads_not_worth_paying"` | **YES** | Persona A views ad removal as valuable convenience; Persona B tolerates ads rather than paying. |
| **q6** | *Overall, the product's pricing feels...* | `"q6_fair_if_use_justifies"` | `"q6_too_expensive_stay_free"` | **YES** | Persona A gauges fairness by utility; Persona B perceives digital tools as overpriced. |

---

## 5. Behavioral & Psychological Findings

### Persona A: Pragmatic Working-Age Household Manager
1. **Utility-Driven:** Answers demonstrate calculated economic decision-making. She is willing to convert to a paid tier once the software proves indispensable (`q0_pay_when_roi_clear`, `q1_plus_after_sustained_use`).
2. **Promotional Responsiveness:** Takes advantage of trial promotions (`q3_one_dollar_try_cancel`) while actively planning to cancel if expectations are unmet.
3. **Openness to Innovation:** Rates product interest at 4/5 and agrees to participate in beta testing.

### Persona B: Digitally Reluctant Senior Resident
1. **Extreme Subscription Aversion:** Rejects both tiers outright (`q1_reject_both_tiers`) and states no willingness to pay under any condition.
2. **Friction Avoidance:** Even a $1 first-month trial is bypassed (`q3_skip_even_one_dollar`), reflecting aversion to entering payment details for digital services.
3. **Disinterest in Digital Productivity Tools:** Rates interest at 1/5 and declines beta testing, closely mirroring official TÜİK survey findings on digital tool adoption in the 75+ demographic.

---

## 6. Key Scientific Limitations & SocietyTwin v2 Roadmap

1. **Stereotype Imputation by the Base Model:**
   - The minimal persona schema for this experiment only provided `province`, `age_group`, `gender`, and `marital_status`.
   - The LLM automatically filled in unmentioned variables (education, income, digital familiarity). While the results aligned with general demographics, they reflect model pretraining biases rather than grounded statistical facts.
   - **Remedy:** Integrate TÜİK Education (T18) and Employment/Income tables into the synthetic population to constrain these variables deterministically.
2. **Sample Size ($N=2$):**
   - This experiment serves as an architectural proof-of-concept and wiring verification.
   - **Remedy:** Scale up to cohort testing ($N=100$ or $N=500$) with stratified sampling to measure population-level statistical distribution.
3. **Sampling Independence:**
   - In this initial run, marital status was sampled conditioned only on gender, rather than jointly conditioned on `(age_group × gender)`.
   - **Remedy:** Implement Iterative Proportional Fitting (IPF) across joint demographic matrices as specified in the v2 architecture.

---

## 7. Artifact References

> Run outputs under `runs/` are git-ignored, so these files exist only on the machine that executed the run. Re-run `src/runtime/run_matraix_ab.py --execute` to regenerate them.

- **Summary Comparison JSON:** `experiments/matraix_simulation/runs/matraix_ab_live/comparison.json`
- **Preflight Configuration:** `experiments/matraix_simulation/runs/matraix_ab_live/preflight.json`
- **Trial A Raw Artifacts:** `experiments/matraix_simulation/runs/matraix_ab_live/trial_A/artifacts/app/output/survey_result.json`
- **Trial B Raw Artifacts:** `experiments/matraix_simulation/runs/matraix_ab_live/trial_B/artifacts/app/output/survey_result.json`
