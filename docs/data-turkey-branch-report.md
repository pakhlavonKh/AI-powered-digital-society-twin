# `origin/data-turkey` Branch Audit & Integration Assessment

**Date:** 2026-11-24  
**Inspected Branch:** `origin/data-turkey` (`de2692e`)  
**Common Ancestor with `main` & `university-simulation`:** `760e79f` (*docs: add v2.1 architecture, MatrAIx findings and experiment results; update Sam's role*, `2026-10-16`)  
**Target Comparison Branch:** `university-simulation` (`b294e37`, built on `ebed8be` — `Merge branch 'fix/post-merge-alignment'`)

---

## 1. Executive Verdict

**Recommendation: Do NOT run a blanket `git merge origin/data-turkey` into `university-simulation`.**

1. **Zero automatic runtime integration:** Every change on `origin/data-turkey` lives strictly inside `tuik_province_data/` (`117` files, `45,632,425` bytes / `43.52 MB`). Nothing in `src/`, `frontend/`, or `tests/` reads `tuik_province_data/osym/` yet, so merging the branch changes zero simulation behavior on `/university`.
2. **PR bloat vs. repo architecture:** `main` and `university-simulation` intentionally keep bulk TÜİK CSVs outside Git (via [.gitignore](../.gitignore#L7), `scripts/provision_reference_data.sh`, and [src/societytwin/evidence/loaders.py](../src/societytwin/evidence/loaders.py#L99-L109)). Merging adds `552k+` insertions of static CSVs—mostly 81-province TÜİK tables—into an application/simulator PR.
3. **High-value higher-education assets can be adopted selectively:** Commit `de2692e` (`29` files under `tuik_province_data/osym/`, `10.45 MB`) delivers clean official 2019–2026 Ankara ÖSYM/tuition datasets, empirical IPF calibration priors, and a forensic reconciliation report directly exposing errors in our `.xlsx` workbook. Those should be integrated via a small targeted adapter rather than merging the whole branch.

---

## 2. Branch Lineage & Commit History

`origin/data-turkey` contains **3 commits** on top of `760e79f` (all authored by `ikoraycaglar`):

| Commit | Date | Message | Scope | Volume |
|---|---|---|---|---|
| `683c851` | 2026-10-18 22:04 +0300 | `feat(data-turkey): add Turkey dataset` | Initial 81-province TÜİK NUTS-3 tables (long + wide CSVs) and catalog/coverage/variable metadata under `tuik_province_data/` | `71` files (`+467,315` lines) |
| `320cafa` | 2026-10-31 16:42 +0300 | `feat(data-turkey): add new datasets from ankara` | Expanded `tuik_province_data/` to `41` datasets (`37` 81-province + `4` Ankara 25-district & EGO public transit), adding climate, enterprises, municipal satisfaction, opera/ballet, etc. Total across `README.md`: `458,058` tidy long rows, `679` indicators (`87` CSVs) | `+46` modified/added files |
| `de2692e` | 2026-11-24 16:37 +0300 | `feat(data): add validated 2019-2026 Ankara higher-ed evidence, data` | Complete 22-institution Ankara ÖSYM admissions/tuition panels (`2019–2026`), Phase 2B reconciliation audit of our `.xlsx` workbook, Phase 4B demographic/mobility evidence pack, and Phase 5 SQLite Cost Engine DDL/script under `tuik_province_data/osym/` | `29` files (`+55,778` lines + handover PDF, `10.45 MB`) |

Cross-branch overlap check against `760e79f..HEAD`:
- Files changed outside `tuik_province_data/` on `origin/data-turkey`: **`0`**.
- Files changed inside `tuik_province_data/` on `university-simulation`: **`0`**.
- The two branches are path-disjoint (merging would not conflict mechanically, only add `43.52 MB` of files under `tuik_province_data/`).

---

## 3. Detailed Breakdown of Commit `de2692e` (`tuik_province_data/osym/`)

### 3.1 Official Multi-Year Ankara Higher-Education Datasets (`2019–2026`)

| File | Bytes | Contents |
|---|---:|---|
| `ankara_programs_2019_2026_validated.csv` | `3,797,724` | `13,939` program-year rows covering **all `22` Ankara institutions** (`2019–2026`, incl. `68` KKTC branch rows distinguished via `campus_city`) |
| `ankara_admissions_tracks_2019_2026_validated.csv` | `2,743,016` | `22,648` track-level rows separating `genel`, `okul_birincisi`, `depremzede`, `kadin_34_plus`, and `sehit_gazi_yakini` |
| `ankara_kilavuz_preplacement_2019_2026.csv` | `2,299,794` | `10,301` pre-placement Kılavuz reference rows (quotas, special conditions, prior-year ranks/scores) |
| `ankara_tuition_2026_2027_complete_validated.csv` | `1,045,268` | `1,944` validated 2026–2027 tuition schedules cross-verified against ÖSYM Kılavuz and university PDFs (incl. payment terms, conditional discounts, and EUR surcharges) |
| `multiyear_overplacement_audit_2019_2026.csv` | `266,808` | Multi-year audit tracing `placed > quota` instances across years |

### 3.2 Forensic Reconciliation Against Our `.xlsx` Workbook (`PHASE2B_OGUZ_WORKBOOK_RECONCILIATION_REPORT.md`)

Commit `de2692e` audited the exact Excel workbook currently imported on `university-simulation` ([Universite_Bolum_Kontenjan_Yerlesen_Sira_Burs_Ucret.xlsx](../data/raw/university/Universite_Bolum_Kontenjan_Yerlesen_Sira_Burs_Ucret.xlsx), `575,658` bytes, SHA-256 `03c4ac4216b1b2e97caa9699e3b25971f296f5864952e04f16ad64db91a8326d`) against official ÖSYM/university primary data:

| Audit Dimension | Workbook Scope (`university.sqlite3`) | Official Benchmark Finding (`data-turkey`) | Impact on `university-simulation` |
|---|---|---|---|
| **2026 Program Coverage** | `13` universities (`1,124` active 2026 programs; `1,282` union `2019–2026`) | **`758` active 2026 programs missing** (`534` across `9` omitted Ankara institutions + `224` missed inside the `13` included universities, e.g. `62` Medipol, `35` Başkent, `31` Ankara Ü., `22` TEDÜ, `20` Ankara Bilim) | Simulations currently omit 9 Ankara institutions and partial offerings in the 13 included ones. |
| **Program-Code Reuse (`30` codes)** | Keys `programs` by `program_code` (`feature/university-sqlite` v1 schema) | ÖSYM reassigned **`30` exact 9-digit `program_code`s** between `2022–2024` and `2025–2026` (`29` at Ankara Medipol, `1` at Atılım `200290250`), changing degree/score-type/scholarship tier (e.g., `209210292`: 2024 Dentistry `%25 SAY` -> 2025–2026 First Aid `Burslu TYT`) | Keying only by `program_code` mixes historical admissions/tuition across incompatible degrees for these 30 codes. |
| **`2,720` `placed > quota` Warnings** | Flagged in [import-report.json](../data/processed/university/import-report.json) | Root-caused `100%`: `1,914` rows store `ALL_TRACKS_SUM_PLACED` against `Genel Kontenjan` (`1,669` scrape mixing + `245` combined), `803` are 1:1 State `okul_birincisi` rollover, and `3` are off by `+1/+2` | Explains every single `placed_above_quota` warning reported by `importer.py`. |
| **2026–2027 Fee Mismatches** | `1,035 / 1,124` (`92.1%`) exact match (`60/60` exact for 2025 TOBB ETÜ) | **`32` TRY mismatches** (`10` OSTİM English fees understated by `40k–55k` TL; `7` Medipol English med/dental/pharm/nursing fees overstated by `100k–160k` TL; `15` reused-code collisions) + `30` paid State KKTC/UOLP marked `0` TL + `4` Pilotaj missing EUR fees | Affects precision of baseline fee levels on affected OSTİM, Medipol, Atılım (`200290250`), and State KKTC/UOLP programs. |

### 3.3 Empirical Evidence Pack (`tuik_province_data/osym/evidence/`, `20` files)

Summarized in `PHASE4B_DEMOGRAPHICS_AND_MOBILITY_EVIDENCE.md` and `evidence_availability_and_gaps_matrix.csv`:

- **National Exam & Score Distributions (`2019–2026`):** `osym_national_applicants_2019_2026.csv`, `osym_cumulative_score_distributions_2019_2026.csv` (`336` rows across 20-pt bins & 5 score types), `osym_preference_rank_shares_2024_2026.csv`, `osym_graduation_status_placements_2021_2026.csv`, `osym_highschool_type_placements_2021_2026.csv`.
- **Structural Priors (`2021-YKS`, flagged `pre_2022_baraj_regime_flag=1`):** `osym_2021_gender_by_score_bin.csv`, `osym_2021_retake_count_by_score_bin.csv`, `osym_2021_education_status_mean_scores.csv`, `yok_2021_foundation_scholarship_shares.csv` (`59.0%` %50-discounted, `22.6%` Burslu, `9.6%` Ücretli, `8.8%` %25), `yok_2021_preference_rank_by_degree.csv`, `yok_2021_province_mobility_and_rank.csv` (81 provinces), `yok_2021_regional_od_matrix.csv`, `yok_2021_ankara_od_flows.csv` (`89` OD pairs).
- **Entrant Demographics & High-School Cohorts:** `yok_entrant_age_gender_2025_2026.csv` (`663` rows), `yok_university_new_entrants_2023_2026.csv` (`412` rows incl. SBÜ Keçiören), `yok_ankara_department_gender_2025_2026.csv` (`1,073` rows), `meb_province_hs_graduates_2024_2025.csv` (`81` provinces), `meb_province_12th_grade_cohorts_2025_2026.csv` (`81` provinces).
- **Documented Data Gaps:** `evidence_availability_and_gaps_matrix.csv` confirms individual candidate 24-choice preference lists and household-income-to-YKS linkages are **not publicly available**—validating that our utility/budget elasticities must stay clearly flagged (`coefficients_calibrated=false`).

### 3.4 Phase 5 Cost Engine Schema & Script (`cost_engine_schema.sql`, `build_phase5_cost_engine_db.py`)

- Defines a 9-table + 2-view SQLite DDL (`source_inventory`, `universities`, `program_offerings`, `admissions_tracks`, `tuition_schedules`, `mandatory_surcharges`, `scholarship_rules`, `state_statutory_fee_decrees`, `conflict_and_missing_log`; views `v_ankara_physical_programs_2026`, `v_cost_engine_2026_2027_ready`).
- Uses `UNIQUE (admission_year, program_code)` in `program_offerings`, solving the 30 reused ÖSYM codes.
- **Portability caveat:** `build_phase5_cost_engine_db.py` hardcodes `ROOT = Path(r"c:\Users\Korai\Desktop\engineering design\evidence_pipeline")` and expects additional local metadata/raw files not committed in `tuik_province_data/osym/`, so it cannot execute as-is in this checkout.

---

## 4. Recommended Next Steps

1. **Merge `university-simulation` (`b294e37`) into `main` cleanly without merging `origin/data-turkey`.**
   - Keeps the PR scoped to the working simulator, UI cleanup, tests, and imported `university.sqlite3` snapshot.
2. **In a focused follow-up branch, selectively consume `origin/data-turkey`'s `osym/` data:**
   - **Data upgrade:** Build an importer adapter reading `ankara_programs_2019_2026_validated.csv`, `ankara_admissions_tracks_2019_2026_validated.csv`, and `ankara_tuition_2026_2027_complete_validated.csv` keyed by `(admission_year, program_code)` to expand coverage from `13` to all `22` Ankara institutions and fix the `32` fee mismatches and `30` reused codes.
   - **Synthetic cohort anchoring:** Use `osym_cumulative_score_distributions_2019_2026.csv`, `yok_entrant_age_gender_2025_2026.csv`, `yok_2021_ankara_od_flows.csv`, and `osym_preference_rank_shares_2024_2026.csv` inside [cohort_synth.py](../src/scenarios/placement/cohort_synth.py) while keeping price/elasticity sensitivities flagged `coefficients_calibrated=false`.
   - **Provincial TÜİK CSVs:** Keep consuming the non-ÖSYM provincial CSVs via `scripts/provision_reference_data.sh` / git-ignored `data/raw/tuik_package/` rather than committing `43.5 MB` under `tuik_province_data/`.
