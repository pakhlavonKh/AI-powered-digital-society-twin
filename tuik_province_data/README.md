# TÜİK Province-Level (NUTS-3 / İBBS Düzey 3) Data Collection — Executive Summary

**Prepared for:** Koray, Data and Simulation Lead — matrAIx Localization Project  
**Primary Source:** TÜİK Veri Portalı (`https://veriportali.tuik.gov.tr`)  


---

## 1. Overview of Collected Datasets
We identified, extracted, cleaned, and validated **33 official province-level (`NUTS-3 / İBBS Düzey 3`) datasets** encompassing **577 distinct indicators** and **411,132 long-format data rows** (up to 25-year historical series through 2025, plus official projections to 2030).
- **Both Long & Wide Formats Provided:** Every dataset is provided in tidy long format (`<dataset>.csv`: `province_code, province_name, nuts3_code, year, indicator, value, unit`) and wide format (`<dataset>_wide.csv`: one column per indicator), encoded in **UTF-8 with BOM (`utf-8-sig`)** with comma delimiters and dot decimal separators.
- **Standardized Keys:** All files share identical join keys (`province_code` `"01"`–`"81"`, official Turkish `province_name`, and `nuts3_code` `"TR100"`–`"TRC34"`). National (`"Türkiye"`) and regional (`NUTS-1`/`NUTS-2`) summary rows have been stripped.
- **Companion Metadata Files:**
  - `data_catalog.csv` — Full inventory of the 33 datasets with Turkish/English titles, exact TÜİK portal URLs, publication dates, reference years, units, and province coverage counts.
  - `variable_metadata.csv` — Dictionary mapping all 577 `snake_case` English indicator names to their original Turkish variable names, English descriptions, units, and source tables.
  - `coverage_report.csv` — Binary (`1/0`) matrix across all 81 provinces × 33 datasets.
  - `not_province_level.csv` — Log of **10 important TÜİK datasets** excluded because TÜİK publishes them only at National, NUTS-1 (12 regions), NUTS-2 (26 subregions), or 3-major-province levels, with exact URLs and reasons.

---

## 2. Theme Coverage Summary (33 Province-Level Datasets)

| Theme | Datasets | Key Indicators & Reference Years | Coverage |
| :--- | :---: | :--- | :---: |
| **1. Population & Vital** | 8 | Total/male/female pop, growth rate & density (2007–2025); 5-yr age × sex (2016–2025); dependency ratios & median age (2007–2025); admin urban/rural & DEGURBA urban/intermediate/rural (2007–2025); TFR, CBR & age-specific fertility (2009–2025); mortality, infant/under-5 mortality, suicide & life expectancy $e_0$ (2009–2025); deaths by cause (2018–2025); projections (2023–2030). | **81/81** (all 8) |
| **2. Households & Family** | 3 | Avg household size & nuclear/one-person/extended/lone-parent composition (2008–2025); marital status by sex 15+ (2008–2025); marriages, divorces, mean age at first marriage & consanguineous marriage rate (2001–2025). | **81/81** (all 3) |
| **3. Education** | 3 | Educational attainment 15+ by sex across 8 ISCED levels (2008–2025); mean years of schooling & school life expectancy ISCED 0–8 + GPI (2011–2025); literacy 6+ by sex & non-formal courses (2008–2025). | **81/81** (all 3) |
| **4. Labor & Income** | 3 | LFPR, employment & unemployment rates + 95% CIs (2022–2025); GDP per capita (TRY/USD) & NACE Rev.2 A10 sectoral GDP (2000–2024); Household Socioeconomic Status (SES A+ to E, 2023), Provincial HDI (2018–2022) & Human Capital Index (2021–2023). | **81/81** (all 3) |
| **5. Housing & Construction** | 2 | Dwelling & building stock from 2021 Census/Survey (48 indicators: ownership, rooms, heating, fuel, building age, floors, elevator, parking); house/workplace sales by mortgage/first-vs-second-hand & building permits (2010–2025). | **81/81** (all 2) |
| **6. Migration** | 3 | Internal in/out/net migration & migration rate + lifetime birth-province retention (2008–2025); internal migration by 12 movement reasons (2018–2025); international immigration/emigration by sex & foreign resident population (2007–2025). | **81/81** (all 3) |
| **7. Mobility, Tech & Lifestyle** | 6 | Road motor vehicles & transfers by 9 vehicle types (2005–2025); traffic accidents/casualties (2015–2025); commercial air traffic (2004–2025); Provincial Well-Being Index (41 indicators + 12 dimensions, 2013/2015); sports clubs & print/online media (2007–2024); State Opera & Ballet (2023–2025). | **81/81** (4 of 6)<br>51/81 (Air)<br>6/81 (Opera) |
| **8. Health, Agri, Env & Justice** | 5 | Hospitals, beds & health personnel per capita (2002–2024); agricultural land by crop type (2020–2025); seasonal/permanent agricultural wages (2002–2025); municipal water/wastewater/waste (2020–2024); prison convicts by 20 crimes (2011–2020). | **81/81** (4 of 5)<br>35/81 (Agri wages) |

---

## 3. Coverage Gaps & Methodological Notes
1. **Province Coverage within the 33 Included Datasets:**
   - **30 of 33 datasets have 100% coverage (81/81 provinces).**
   - **3 datasets have structural/survey coverage $<81$ provinces** (missing provinces are explicitly listed in `data_catalog.csv` and `coverage_report.csv`):
     - `air_traffic_by_province.csv` (**51/81 provinces**): The remaining 30 provinces do not have commercial civil airports reported by DHMİ.
     - `agricultural_wages_by_province.csv` (**35/81 provinces**): TÜİK's Agricultural Holdings Labour Wage Structure Survey reports province-level wage estimates only for the 35 major agricultural employment provinces meeting sample precision thresholds; cells suppressed by TÜİK for confidentiality (`"c"`) or absence (`"-"`) are preserved as empty `""`.
     - `opera_and_ballet_by_province.csv` (**6/81 provinces**): State Opera and Ballet General Directorate halls exist only in Ankara, Antalya, İstanbul, İzmir, Mersin, and Samsun.
2. **Themes Published Only at NUTS-1 / NUTS-2 (Logged in `not_province_level.csv`):**
   - Because TÜİK conducts sample household surveys at the **NUTS-2 (26 subregions)** or **NUTS-1 (12 regions)** design level, the following are **not published at the 81-province level**: Household Budget/Consumption Expenditure (`NUTS-2`), Survey of Income and Living Conditions / Gini / Poverty (`NUTS-2`), Household ICT Usage (`NUTS-1`), Youth NEET & Employment by Sector (`NUTS-2`), and House Price Index (`NUTS-2` / 3 major provinces).
   - **How We Bridged These Gaps at the 81-Province Level:** We captured TÜİK's administrative-register **Socioeconomic Status (SES) Score & Household Class Distribution (`A+` to `E`)** (`socioeconomic_status_and_human_development.csv`, all 81 provinces) to replace NUTS-2 income quintiles, **broadband internet satisfaction** in `wellbeing_and_life_satisfaction_indicators.csv` (all 81 provinces) for ICT access, and **Provincial GDP by NACE sector** (`gdp_and_economy_by_sector.csv`, all 81 provinces) for economic structure.

---

## 4. Top 5 Recommendations for matrAIx Simulation Calibration
1. **Joint Synthetic Population Marginals (Iterative Proportional Fitting / IPF):** Combine `population_by_age_sex.csv` (2025), `marital_status_by_sex.csv` (2025), and `education_attainment_by_sex.csv` (2025) as your core 1D/2D provincial marginal controls, and pair them with `households_size_and_types.csv` (2025) to group synthetic agents into realistic nuclear, lone-parent, one-person, and extended households.
2. **Household Wealth & Purchasing Power Assignment:** Use `socioeconomic_status_and_human_development.csv` (specifically the 2023 administrative-register `A+`, `A`, `B`, `C1`, `C2`, `D`, `E` household shares across all 81 provinces) alongside `gdp_and_economy_by_sector.csv` (`gdp_per_capita_try` / `gdp_per_capita_usd`) to assign household socioeconomic tiers without relying on coarse NUTS-2 income survey averages.
3. **Dwelling & Physical Environment Calibration:** Use `housing_stock_and_dwelling_characteristics.csv` (2021 Census 48 indicators: tenure/ownership, room count, building age, floor count, central vs. stove heating, natural gas vs. coal/wood fuel) together with `population_urban_rural.csv` (2025 DEGURBA dense urban / intermediate / rural grid shares) to assign physical housing attributes.
4. **Agent Mobility & Dynamic Relocation:** Calibrate inter-provincial agent flows using `internal_migration_and_place_of_birth.csv` and parameterize agent decision triggers (job change, education, marriage, family dependency, retirement, housing purchase) directly from `internal_migration_by_reason.csv` (2018–2025).
5. **Forward Simulation Validation (2025 $\to$ 2030):** Use `vital_fertility_and_birth_indicators.csv`, `vital_mortality_and_life_expectancy.csv`, and `population_projections_2024_2030.csv` as benchmark trajectories to validate your synthetic population's aging, birth, and mortality dynamics through 2030.
