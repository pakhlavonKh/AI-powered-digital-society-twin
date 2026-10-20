# Ankara Public Transportation Simulation: Data Evidence & Notes

## 1. Purpose & Scope
This document records the empirical evidence, data sources, and explicit limitations supporting public policy simulations of transit fare interventions in Ankara (Province code `06`), specifically for reference scenario `transport_fare_001`.

The synthetic population developed in SocietyTwin is grounded in official demographic statistics from the Turkish Statistical Institute (TÜİK - ADNKS 2025). However, demographics alone (age, sex, marital status, education) do not directly measure transportation behavior. To prevent scientific overclaiming, this note classifies all mobility attributes into three categories:
- **Observed:** Directly extracted from official government registers or municipal decrees.
- **Derived:** Calculated from published aggregate tables or benchmark studies.
- **Missing / Unobserved:** Not available in official person-level tables; must be handled with explicit diagnostic warnings rather than synthetic fabrication.

---

## 2. Municipal Transit Structure & Tariffs (Ankara EGO)

Public transport in Ankara is coordinated by the **EGO General Directorate (Ankara Büyükşehir Belediyesi EGO Genel Müdürlüğü)** and regulated by UKOME (Ulaşım Koordinasyon Merkezi).

### 2.1 Tariff Categories (Observed)
As of the August 2024 UKOME tariff update for electronic smart cards (Ankarakart):
1. **Full Fare (Tam Bilet):** 21.00 TL (Single boarding on EGO buses, Ankaray, and Metro).
2. **Discounted Student Fare (İndirimli Öğrenci):** 10.50 TL.
3. **Monthly Student Subscription (Öğrenci Abonman):** 300 TL / month (225 boardings).
4. **Statutory Free Concession (65 Yaş ve Üzeri):** 0 TL.
   - Mandated by Law No. 4736 (T.C. Aile ve Sosyal Hizmetler Bakanlığı regulation).
   - Turkish citizens aged 65 or older board urban public transit free of charge.
5. **Transfer (Aktarma):** 9.00 TL (full) / 4.50 TL (student) within a 75-minute window.

### 2.2 Crucial Policy Modeling Rules
- **No Blanket Adult Assumptions:** Standard full adult fare adjustments (e.g., +20% from 21.00 TL to 25.20 TL) must **never** be silently applied to synthetic residents who qualify for statutory exemptions (e.g., age 65+) or student discounts without an explicit municipal policy decree.
- **Hypothetical Intervention vs. Baseline:** The baseline is defined as 21.00 TL. The policy intervention (+20% -> 25.20 TL) is a controlled hypothetical parameter.

---

## 3. Supported vs. Unavailable Population Attributes

| Attribute | Status in Synthetic Population | Simulation Strategy |
|---|---|---|
| **Age** | Observed (TÜİK ADNKS 2025) | Used for eligibility: filter min_age >= 18; identify 65+ concession recipients. |
| **Province / Geography** | Observed (Province 06 Ankara) | Used for eligibility: verify resident resides in Ankara. |
| **Sex** | Observed (TÜİK) | Disaggregation dimension for analyzing subgroup response variance. |
| **Education Level** | Inferred conditional on sex/age (TÜİK 2025) | Context for socioeconomic standing. |
| **Student Status** | Not in standard person table | Must be inferred from age or flagged as missing; university students aged 18-25 require careful qualification. |
| **Labour / Employment Status** | Unavailable in 2025 person tables | Flagged as `unavailable` in current population build; scenarios must not filter strictly on employment without fallback. |
| **Individual Trip Frequency** | **MISSING** | TÜİK does not record person-level transit tap data. Scenario prompts must ask conditional behavioral responses without inventing false trip histories. |
| **Personal Car Access** | **MISSING** | While province-level car ownership per 1,000 residents is known (~300 cars/1k in Ankara), individual access is unobserved. Agents are asked about mode shift hypothetically. |
| **Household Income** | **MISSING** at person level | TÜİK HBA reports national/regional income quintiles. The scenario must not assert exact TRY incomes for synthetic records. |

---

## 4. Benchmark Price Elasticity of Demand

In urban transportation economics, short-run price elasticity of transit demand typically ranges from **-0.2 to -0.4** (Simpson, 1992; Litman, 2023; Eski et al., 2023 for Turkish cities):
- A 20% fare increase in the real world is expected to produce a 4% to 8% reduction in ridership among discretionary riders, with near-inelastic behavior among captive commuters.
- **Role in SocietyTwin:** These empirical figures serve as a benchmark against which aggregated AI persona outputs can be compared during validation, without confusing AI outputs with empirical observations.
