# matrAIx Türkiye (81 Provinces) & Ankara (25 Districts + EGO Public Transit) Localization Data Package

**Prepared for:** Koray, Data and Simulation Lead — matrAIx Localization Project    
**Verification Date:** `2026-10-27` (`HTTP 200 OK` verified across all 50 active official URLs; 1 legacy URL logged as `HTTP 404` in `excluded_sources.csv`)  
**Total Datasets:** **41 datasets** (**37** 81-province NUTS-3 datasets + **4** Ankara 25-district & EGO public transport datasets)  
**Total CSV Files:** **87 CSV files** (`41` tidy long `.csv` files + `41` `_wide.csv` companion files + `5` metadata/catalog CSVs)  
**Total Observations:** **458,058** deduplicated tidy long rows (`37,262` wide rows) across **679** standardized indicators

---

## 1. Executive Summary & Architecture

All files in this repository follow strict simulation-ready standards:
- **Encoding & Formatting:** UTF-8 with BOM (`utf-8-sig`), comma delimiter (`,`), dot decimal separator (`.`), `snake_case` English headers, empty string (`""`) for missing/suppressed values (never zero-filled), and zero `"Türkiye"` national summary rows inside provincial/district tables.
- **Standard Join Keys:**
  - **81-Province Files (`37` datasets):** `province_code` (`"01"` to `"81"` plate code), `province_name` (official Turkish spelling: `İstanbul`, `İzmir`, `Şanlıurfa`, `Ağrı`), `nuts3_code` (`"TR100"` to `"TRC34"`), `year`, `indicator`, `value`, `unit`.
  - **Ankara District & Transit Files (`4` datasets):** `province_code` (`"06"`), `province_name` (`"Ankara"`), `district_name` (the 25 official Ankara districts or EGO transit line/division), `year`, `indicator`, `value`, `unit`.
- **Metadata & Audit Files:**
  1. `data_catalog.csv` — Full inventory of all 41 datasets with `file_name`, `wide_file_name`, `dataset_title`, `dataset_title_tr`, `theme`, `publisher`, `source_url`, `verification_date`, `http_status`, `publication_date`, `reference_years`, `unit`, `provinces_covered`, `missing_provinces`, `source_type`, and `notes`.
  2. `coverage_report.csv` — Binary availability matrix (`1`/`0`) across all 81 provinces (`01` to `81`) × 41 datasets.
  3. `excluded_sources.csv` (and `not_province_level.csv`) — 13 rejected or non-provincial datasets/URLs with exact exclusion reasons (`not_province_level`, `dead_link`, `unverifiable_dynamic_widget`), verification date, and HTTP status.
  4. `variable_metadata.csv` — Complete indicator dictionary mapping all 679 `snake_case` indicators to their original Turkish names, English descriptions, units, and source tables/SDMX dataflows.

---

## 2. Complete Inventory of the 41 Datasets by Theme

### A. Population, Vital Statistics & Projections (8 Provincial Datasets — 81/81 Provinces)
1. `population_total_and_growth.csv` (`2007–2025`, 81/81 provinces): Total, male, and female ADNKS population, annual growth rate (`‰`), population density (`persons/km²`), and provincial land area.
2. `population_by_age_sex.csv` (`2016–2025`, 81/81 provinces): 5-year age groups (`0-4` through `90+`) × sex (`total`, `male`, `female`).
3. `population_structural_indicators.csv` (`2007–2025`, 81/81 provinces): Median age by sex, total/child/elderly dependency ratios, youth & working-age shares, sex ratio.
4. `population_urban_rural.csv` (`2007–2025`, 81/81 provinces): Provincial/district center vs. town/village population andTÜİK's newer `2022–2024` Degree of Urbanization (DEGURBA: dense urban, intermediate town, rural grid) breakdown.
5. `vital_fertility_and_birth_indicators.csv` (`2009–2025`, 81/81 provinces): Crude birth rate (`‰`), total fertility rate (TFR), age-specific fertility rates (`15-19` to `45-49`), mean age of mother at birth.
6. `vital_mortality_and_life_expectancy.csv` (`2009–2025`, 81/81 provinces): Total/male/female deaths, crude death rate, infant mortality rate, under-5 mortality rate, and life expectancy at birth ($e_0$), age 15, 30, 45, 60, and 65 by sex.
7. `deaths_by_cause.csv` (`2016–2025`, 81/81 provinces): Deaths by ICD-10 major cause group (circulatory, neoplasms, respiratory, nervous system, endocrine, external injuries, COVID-19).
8. `population_projections_2024_2030.csv` (`2024–2030`, 81/81 provinces): Official TÜİK projected provincial populations and annual growth rates through 2030.

### B. Households, Marital Status & Family Dynamics (3 Provincial Datasets — 81/81 Provinces)
9. `households_size_and_types.csv` (`2008–2025`, 81/81 provinces): Average household size, total households, one-person, nuclear (couples with/without children, lone fathers, lone mothers), extended-family, and non-relative multi-person households.
10. `marital_status_by_sex.csv` (`2008–2025`, 81/81 provinces): Population aged `15+` by marital status (`never_married`, `married`, `divorced`, `widowed`) and sex.
11. `marriage_and_divorce_indicators.csv` (`2001–2025`, 81/81 provinces): Marriages, divorces, crude marriage/divorce rates, mean age at first marriage by sex, and spousal age gap.

### C. Education, Human Capital & Libraries (4 Provincial Datasets — 81/81 Provinces)
12. `education_attainment_by_sex.csv` (`2008–2024`, 81/81 provinces): Population aged `15+` by completed education level (illiterate through doctorate) and sex.
13. `education_duration_and_schooling_expectancy.csv` (`2011–2025`, 81/81 provinces): Mean years of schooling ( population `25+`), expected years of schooling, net schooling ratios (pre-primary, primary, lower-secondary, upper-secondary, higher education), students per teacher/classroom/school.
14. `literacy_and_nonformal_education.csv` (`2008–2024`, 81/81 provinces): Literacy status by sex (`6+`) plus non-formal vocational/educational courses, trainees, and graduates.
15. `education_and_public_libraries.csv` (`2024–2025`, 81/81 provinces): Formal and non-formal school libraries (public schools, private schools, private courses, enriched Z-libraries, book stocks) and public libraries (libraries, beneficiaries, registered members, materials lent, total books).

### D. Labor, Economy, GDP, Enterprises & Socioeconomic Status (4 Provincial Datasets — 81/81 Provinces)
16. `labor_force_indicators.csv` (`2021–2024`, 81/81 provinces): Labor force participation rate (`%`), employment rate (`%`), and unemployment rate (`%`) by sex (`15+`).
17. `gdp_and_economy_by_sector.csv` (`2004–2024`, 81/81 provinces): Provincial GDP in current TL, chain-linked volume index, per-capita GDP in TL and USD, Sectoral Gross Value Added (A–T NACE sections), plus foreign trade exports and imports (`2013–2025`, thousand USD).
18. `enterprises_by_sector_and_size.csv` (`2014–2024`, 81/81 provinces): Active enterprises across all 18 NACE Rev.2 sections (`A` through `S`) and 5 employee size groups (`0`, `1-9`, `10-49`, `50-249`, `250+`).
19. `socioeconomic_status_and_human_development.csv` (`2021–2023`, 81/81 provinces): TÜİK's register-based Socioeconomic Status (SES) average score, household counts and percentages across 5 socioeconomic tiers (`Upper A/A+`, `Lower-Upper B`, `Middle C1/C2`, `Lower D`, `Lowest E`), and Human Capital Index.

### E. Housing Stock, Ownership, Amenities & Real Estate (2 Provincial Datasets — 81/81 Provinces)
20. `housing_stock_and_dwelling_characteristics.csv` (`2021`, 81/81 provinces): Dwelling ownership status (`owner`, `tenant`, `lodging`, `other`), number of rooms, rooms per person, building floor count, construction period (`before 1981` to `2021+`), elevator & parking availability, piped water, toilet, bath, kitchen, heating system, and primary heating fuel.
21. `housing_sales_and_building_permits.csv` (`2009–2025`, 81/81 provinces): Total house sales, mortgaged vs. other sales, first-hand vs. second-hand sales, sales by gender, sales to foreigners, and construction permits (buildings, floor area `m²`, dwelling units).

### F. Internal & International Migration and Foreign Population (3 Provincial Datasets — 81/81 Provinces)
22. `internal_migration_and_place_of_birth.csv` (`2008–2025`, 81/81 provinces): In-migration, out-migration, net migration, net migration rate (`‰`), population by birth province status, and lifetime registry (`kütük`) province.
23. `internal_migration_by_reason.csv` (`2018–2025`, 81/81 provinces): In-migration and out-migration by 8 administrative reasons (job change/assignment, starting/finding a job, education, marriage/divorce, health/care, household dependency, buying a house/better living conditions, return to family/homeland).
24. `international_migration_and_foreign_population.csv` (`2008–2025`, 81/81 provinces): Foreign national population residing in each province by sex (`2008–2025`), foreign-born share, plus international immigration, emigration, and net migration by sex and top citizenship countries (`2016–2024`).

### G. Transport, Mobility, Technology, Satisfaction & Lifestyle (6 Provincial Datasets)
25. `road_motor_vehicles_and_transfers.csv` (`2004–2025`, 81/81 provinces): Registered motor vehicles by type (`total`, `cars`, `minibuses`, `buses`, `small_trucks`, `trucks`, `motorcycles`, `special_purpose`, `tractors`) and vehicle ownership transfers (`notary handovers`).
26. `traffic_accidents_and_casualties.csv` (`2009–2024`, 81/81 provinces): Total road traffic accidents, fatal/injury accidents, deaths (at scene + 30-day follow-up), and injured persons.
27. `air_traffic_by_province.csv` (`2004–2024`, 51/81 provinces — the 30 missing provinces do not have commercial airports): Domestic, international, and total air passengers, commercial aircraft traffic, all aircraft traffic, and freight/cargo tonnage.
28. `wellbeing_and_life_satisfaction_indicators.csv` (`2013, 2015`, 81/81 provinces): 41-indicator Well-Being Index values and ranks (including `housing_monthly_rent_tl`, `income_average_daily_earnings_tl`, `income_household_monthly_consumption_tl`, `access_internet_subscriptions_per_100`, `access_public_transport_satisfaction_pct`, `environment_pm10_air_pollution_ug_m3`, `environment_forest_area_pct`, `civic_voter_turnout_local_pct`, and happiness rates by sex).
29. `municipal_and_public_services_satisfaction.csv` (`2013`, 81/81 provinces): Citizen satisfaction rates (`%`) across 10 municipal services (waste collection, sewerage, network water, public transport, green areas, disabled arrangements, social assistance, road/sidewalk construction, street lighting, street signs) and 6 national public services (SGK, health, education, judicial, public security, transportation).
30. `sports_clubs_and_media_indicators.csv` (`2007–2024`, 81/81 provinces): Cinema halls, seats, films shown, cinema spectators, theatre halls/seats/spectators, and registered sports clubs.
31. `opera_and_ballet_by_province.csv` (`2023–2025`, 6/81 provinces — only Ankara, Antalya, İstanbul, İzmir, Mersin, and Samsun have State Opera and Ballet Directorates).

### H. Health, Climate, Environment, Water, Agriculture & Justice (6 Provincial Datasets)
32. `health_infrastructure_and_personnel.csv` (`2002–2024`, 81/81 provinces): Hospitals, hospital beds, beds per 100,000 population, specialist physicians, general practitioners, medical residents, total physicians, dentists, pharmacists, nurses, and midwives.
33. `climate_temperature_and_precipitation.csv` (`1927–2025` long-term station records, 81/81 provinces): Annual mean temperature (`°C`), mean daily max/min temperature (`°C`), daily sunshine duration (`hours/day`), annual rainy days, annual total precipitation (`mm`), historical extreme max/min temperatures (`°C`), and January/July seasonal temperature and precipitation benchmarks from the General Directorate of Meteorology (MGM).
34. `municipal_water_and_waste_services.csv` (`1994–2024`, 81/81 provinces): Municipal waste collected, waste per capita (`kg/day`), drinking water abstracted/distributed, water per capita (`liters/day`), wastewater discharged/treated, and share of municipal population served by water networks, sewerage, and treatment plants.
35. `agricultural_land_by_province.csv` (`2019–2024`, 81/81 provinces): Total utilized agricultural land (`decares`), cereals/field crops, fallow land, vegetable gardens, ornamental plants, and fruit/olive/beverage orchards.
36. `agricultural_wages_by_province.csv` (`2016–2024`, 35/81 provinces — the remaining 46 provinces are suppressed by TÜİK where sample size is below publication threshold): Daily wages (`TL`) of seasonal agricultural workers (`total`, `male`, `female`) and monthly wages (`TL`) of permanent agricultural workers.
37. `prison_convicts_by_crime.csv` (`2011–2020`, 81/81 provinces): Convicts entering penitentiary institutions by province of commission across 28 crime categories.

### I. Ankara-Specific Deep-Dive: 25 Districts (`İlçe`) & EGO Public Transit (4 Datasets)
38. `ankara_district_population_and_growth.csv` (`2024–2025`, all 25 Ankara districts): Total population, urban center population, town/village population, and annual population growth rate (`‰`) for all 25 districts (`Akyurt`, `Altındağ`, `Ayaş`, `Bala`, `Beypazarı`, `Çamlıdere`, `Çankaya`, `Çubuk`, `Elmadağ`, `Etimesgut`, `Evren`, `Gölbaşı`, `Güdül`, `Haymana`, `Kahramankazan`, `Kalecik`, `Keçiören`, `Kızılcahamam`, `Mamak`, `Nallıhan`, `Polatlı`, `Pursaklar`, `Sincan`, `Şereflikoçhisar`, `Yenimahalle`).
39. `ankara_district_vital_and_marital.csv` (`2014–2025`, all 25 Ankara districts): 12-year time series of live births (`total`, `male`, `female`), marriages, and divorces for each of the 25 districts.
40. `ankara_district_socioeconomic_and_housing.csv` (`2013–2025`, all 25 Ankara districts): `2023` average Socioeconomic Status (SES) score and 5-tier household class distribution (`%` in `A/A+`, `B`, `C1/C2`, `D`, `E`) for all 25 districts, plus `2013–2025` house and commercial property sales to foreigners by district.
41. `ankara_public_transport_ego_and_rail.csv` (`2021–2026`, 27 Ankara transit divisions/lines): EGO Bus Total (`2021–2025`), EGO Bus 5 Regional Divisions (`1. Bölge` through `5. Bölge` with district coverage, dispatch hubs, routes, active/inactive fleet, drivers, trips, and km operated), `Ankaray (A1 AŞTİ-Dikimevi)`, `Metro M1 (Kızılay-Batıkent)`, `Metro M2 (Kızılay-Çayyolu)`, `Metro M3 (Batıkent-OSB/Törekent)`, `Metro M4 (Keçiören-Kızılay)`, `EGO Rail Total`, `Teleferik (Yenimahalle-Şentepe)`, `TCDD Başkentray (Kayaş-Sincan)`, `Private Public Buses (ÖHO & ÖTA)`, and 10 outer-district commuter corridors (`Çubuk`, `Akyurt`, `Elmadağ`, `Kahramankazan`, `Hasanoğlan`, `Polatlı`, `Lalahan`, `Kalecik`, `Beypazarı`), including `2026 Jan–Aug` fare-type breakdowns (`full_fare`, `discounted`, `student_subscription`, `mobile_nfc_qr`, `free_pass`), trips, km, energy (`kWh`), and energy expenditure (`TL`).

---

## 3. Cross-Checks & Ankara Highlights

1. **Exact Population Reconciliation (`0` Discrepancy):**
   - **2024 Ankara Population:** `population_total_and_growth.csv` = **`5,864,049`** | Sum of 25 districts in `ankara_district_population_and_growth.csv` = **`5,864,049`** (`100.000%` exact match).
   - **2025 Ankara Population:** `population_total_and_growth.csv` = **`5,910,320`** | Sum of 25 districts in `ankara_district_population_and_growth.csv` = **`5,910,320`** (`100.000%` exact match).
   - **Top 7 Urban Core Districts (2025):** `Çankaya` (`952,198`), `Keçiören` (`931,722`), `Yenimahalle` (`721,531`), `Mamak` (`690,329`), `Etimesgut` (`632,458`), `Sincan` (`605,366`), and `Altındağ` (`418,072`) account for **`4,951,676`** residents (**`83.78%`** of Ankara's total population).
2. **Exact Marriage & Divorce Reconciliation:**
   - **Marriages (2024 & 2025):** Province total (`37,292` in 2024; `36,210` in 2025) matches the 25-district sum (`37,292` in 2024; `36,210` in 2025) with **zero discrepancy**.
   - **Divorces (2024 & 2025):** Province total is `15,601` (2024) and `16,025` (2025) vs. 25-district sum of `15,431` (2024) and `15,843` (2025); the `170` (`1.09%`) and `182` (`1.14%`) difference represents court divorce decrees where the sub-provincial district of residence is coded `"Bilinmeyen"` (Unknown) by TÜİK.
3. **Ankara Intra-Provincial Socioeconomic Gradient (`2023` SES):**
   - Provincial average SES score: **`149.66`** (`#1` among all 81 provinces, ahead of İstanbul at `147.82`).
   - Within Ankara (`ankara_district_socioeconomic_and_housing.csv`), the SES score spans an **81.26-point gap** across the 25 districts:
     - **Highest SES Districts:** `Çankaya` (`178.11`, with `36.95%` of households in `Upper A/A+` and `20.61%` in `B`), `Etimesgut` (`167.92`, `27.13%` in `A/A+`), `Gölbaşı` (`162.00`, `25.47%` in `A/A+`), `Yenimahalle` (`161.91`, `25.82%` in `A/A+`), `Pursaklar` (`141.30`), `Keçiören` (`140.41`), `Kahramankazan` (`136.97`), `Mamak` (`135.22`), `Sincan` (`134.97`).
     - **Lowest SES Rural Peripheral Districts:** `Şereflikoçhisar` (`107.48`), `Haymana` (`102.77`), `Çamlıdere` (`101.77`), `Güdül` (`98.92`), and `Evren` (`96.85`, where `59.62%` of households are in `Lower D` or `Lowest E`).
4. **Ankara Urban Mobility & Public Transit Ecosystem (`2025–2026`):**
   - **Total 2025 Ridership Across All Modes:** **`558.76 million`** passenger boardings (`264.58M` EGO municipal buses across 417 routes and 10,785 stops + `173.17M` EGO Rail [Ankaray + Metro M1–M4] + `68.73M` Private Public Buses [ÖHO] + `26.10M` TCDD Başkentray commuter rail + `18.21M` Private Public Transit [ÖTA] + `7.95M` outer-district transit corridors).
   - **2026 (Jan–Aug) Rail Fare Structure (`109.40M` boardings):** `34.81%` Full Fare (`38.08M`), `25.34%` Student Monthly Subscription (`27.72M`), `19.93%` Discounted Student/Teacher (`21.81M`), `12.70%` Free Pass (`65+`/Disabled, `13.90M`), and `7.21%` Contactless Bank Card / NFC / QR (`7.89M`).

---

## 4. Top 6 Recommendations for matrAIx Simulation & Localization Models

1. **Synthetic Population & Household Initialization (`population_by_age_sex.csv` + `households_size_and_types.csv` + `ankara_district_population_and_growth.csv`):**
   Use Iterative Proportional Fitting (IPF) anchored on the 25 Ankara district totals (`ankara_district_population_and_growth.csv`) and the 81-province age × sex (`population_by_age_sex.csv`), marital status (`marital_status_by_sex.csv`), and household typology distributions (`households_size_and_types.csv`).
2. **Spatial Purchasing Power & Agent Class Assignment (`socioeconomic_status_and_human_development.csv` + `ankara_district_socioeconomic_and_housing.csv`):**
   Because TÜİK's Income and Living Conditions Survey (GYKA) is only published at NUTS-2 (`26 subregions`), TÜİK's administrative register-based **Socioeconomic Status (SES)** dataset is the gold-standard predictor for agent wealth, consumption propensity, and social class (`A/A+`, `B`, `C1/C2`, `D`, `E`) across all 81 provinces and all 25 Ankara districts.
3. **Origin–Destination Commuting & Mode Choice Calibration (`ankara_public_transport_ego_and_rail.csv` + `road_motor_vehicles_and_transfers.csv`):**
   Calibrate Ankara transit vs. private car mode choice using the 5 EGO Bus regional division capacities/kilometers, the station-to-station corridor ridership of `M1` (`53.39M`), `M2` (`39.35M`), `Ankaray` (`38.02M`), `TCDD Başkentray` (`26.10M`), `M3` (`24.51M`), and `M4` (`17.90M`), and the 2026 card-type shares to model student vs. worker vs. retiree travel behavior.
4. **Firm Location & Employment Demand Generation (`enterprises_by_sector_and_size.csv` + `gdp_and_economy_by_sector.csv` + `labor_force_indicators.csv`):**
   Generate workplace agents and sectoral employment demand across all 81 provinces using the 11-year (`2014–2024`) active enterprise matrix by 18 NACE Rev.2 sections and 5 employee size tiers (`0`, `1-9`, `10-49`, `50-249`, `250+`), weighted by provincial sectoral GVA (`gdp_and_economy_by_sector.csv`).
5. **Agent Relocation & Demographic Microsimulation (`internal_migration_by_reason.csv` + `vital_fertility_and_birth_indicators.csv` + `ankara_district_vital_and_marital.csv`):**
   Drive annual agent life-course transitions using provincial age-specific fertility and life expectancy tables, district-level birth/marriage/divorce rates in Ankara, and the 8-reason internal migration matrices (`education`, `job_change`, `marriage_divorce`, `housing_living_conditions`) to capture Ankara's university and civil-service inflows.
6. **Environmental, Housing & Infrastructure Stress Testing (`climate_temperature_and_precipitation.csv` + `municipal_water_and_waste_services.csv` + `housing_stock_and_dwelling_characteristics.csv`):**
   Couple MGM's 81-province temperature/precipitation normals and extremes with provincial heating fuel mix, building age cohorts, and per-capita municipal water abstraction (`liters/person-day`) to simulate seasonal energy demand and urban water stress.
