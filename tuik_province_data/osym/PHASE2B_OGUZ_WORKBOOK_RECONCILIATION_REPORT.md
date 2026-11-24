# Phase 2B — Direct Record-by-Record Verification of Oğuz's Workbook Against Official Primary Data (2019–2026)

**Prepared for:** Koray (Data Engineering, Evidence & Cost Foundation Workstream)  
**Verification Date:** 2026-11-24  
**Verified File:** [Universite_Bolum_Kontenjan_Yerlesen_Sira_Burs_Ucret.xlsx](file:///c:/Users/Korai/Desktop/engineering%20design/evidence_pipeline/raw/oguz/Universite_Bolum_Kontenjan_Yerlesen_Sira_Burs_Ucret.xlsx) (`575,658` bytes)  
**Verified SHA-256:** `03c4ac4216b1b2e97caa9699e3b25971f296f5864952e04f16ad64db91a8326d` (**100% byte-identical** to the expected SHA-256 recorded in `feature/university-sqlite`)  
**Reproducible Audit Script:** [reconcile_oguz_vs_official.py](file:///c:/Users/Korai/Desktop/engineering%20design/evidence_pipeline/scripts/reconcile_oguz_vs_official.py)  
**Primary Official Benchmark:** [cost_engine_foundation.sqlite3](file:///c:/Users/Korai/Desktop/engineering%20design/evidence_pipeline/validated/cost_engine_foundation.sqlite3) (`13,939` verified program-year rows across all `8/8` years `2019–2026`, `22,648` multi-track rows, `100%` 2026–2027 verified foundation tuition).

---

## 1. Executive Reconciliation Scorecard

| Audit Dimension | Oğuz Workbook Scope | Verified Exact Match | Conflicting / Missing / Hazard | Key Forensic Root Cause |
| :--- | :--- | :--- | :--- | :--- |
| **2026 Institutional & Program Coverage** | `13` univs (`1,124` active 2026 progs; `1,282` union `2019–2026`) | `1,124 / 1,882` (`59.7%`) | **`758` active 2026 progs missing** (`534` in `9` omitted Ankara insts + **`224` missing within Oğuz's own 13 univs**: `129` Lisans Ankara, `87` Ön Lisans Ankara, `8` ODTÜ KKTC) | Oğuz's `Sınav İzcisi` extract missed dozens of active programs inside his own 13 universities (e.g., `62` Ankara Medipol, `35` Başkent, `31` Ankara Ü., `22` TEDÜ, `20` Ankara Bilim). |
| **Program Identity & Attributes (`1,282` rows)** | `1,282` unique `Program Kodu` rows | `1,208` `verified`, `4` `partially_verified` | **`70` `conflicting`** — incl. **`30` ÖSYM reused program codes** (`29` Ankara Medipol + `1` Atılım `200290250`) & `40` paid State KKTC/UOLP rows (`33` KKTC + `7` UOLP) | **CRITICAL SCHEMA HAZARD:** ÖSYM reassigned 30 9-digit program codes across years to completely different degrees, score types, and scholarship tiers (e.g., `209210292`: `2024` *Diş Hekimliği %25 SAY* → `2025–2026` *İlk ve Acil Yardım EN Burslu TYT*). Keying on `program_code` alone silently corrupts these 30 histories. |
| **Annual Quotas & Placements (`8,715` rows, `2019–2026`)** | `8,715` `(year, code)` observations | **`8,715 / 8,715` (`100.0%`)** `Kontenjan` = `Genel Kontenjan`; `5,795` exact `Yerleşen` | **`1,914` rows** put **`ALL_TRACKS_SUM_PLACED`** into `Yerleşen` while keeping `Genel Kontenjan` in `Kontenjan` (+ `3` off by `+1/+2`) | **EXACT DECOMPOSITION OF ALL `2,720` `placed > quota` WARNINGS:** `1,669` (`61.4%`) `Sınav İzcisi` track-mixing (`Genel` quota vs all-tracks placed), `803` (`29.5%`) pure State 1:1 OB rollover, `245` (`9.0%`) combined OB rollover + special tracks, `3` (`0.1%`) `+1/+2`. |
| **Annual Success Ranks (`8,715` rows)** | `8,715` rows (`2019–2026`) | **`2,938 / 2,941` (`99.90%`)** exact match in `2019, 2022, 2023`; **`113 / 113` (`100%`)** 2026 NULLs = `Dolmadı` | `2020`: `793` rounded to `100/1,000` in official `2021` Kılavuz; `2025`: `968` offset (median `-486` vs official `2026` Kılavuz); `78` other diffs | `2020` diffs are official rounding; `2025` diffs reflect official final `2026` Kılavuz baseline vs `Sınav İzcisi`'s `2025` scrape; `113/113` 2026 NULL ranks are confirmed ÖSYM unfilled-quota suppressions. |
| **Tuition & Scholarship (`1,282` rows: `2026` & `2025`)** | `1,124` active 2026 + `158` discontinued pre-2026 | **`1,035 / 1,124` (`92.1%`)** active 2026 exact (`719` Vakıf + `316` State `0 TL`); **`60 / 60` (`100%`)** `2025` TOBB ETÜ exact | **`32` 2026 TRY mismatches** (`17` EN fee errors + `15` reused-code collisions) + **`30` State KKTC/UOLP mislabeled `0 TL`** + `23` State Uzaktan/AÖF + `4` Pilotaj missing EUR | `10` OSTİM English programs understated by `40k–55k TL`; `7` Ankara Medipol English med/dental/pharm/nursing programs overstated by `100k–160k TL`; Atılım `200290250` labeled `%50` (`600k`) instead of `%25` (`900k`, `300k TL` error). |

---

## 2. Critical Finding for Engineering Teams: ÖSYM Program-Code Reuse Hazard (`30` Codes)

Between `2022–2024` and `2025–2026`, ÖSYM reused **30 exact 9-digit program codes** at Ankara Medipol (`29` codes) and Atılım (`1` code: `200290250`) for completely different programs, degrees, score types, and scholarship tiers. Examples verified directly from official ÖSYM TABLO-3/4:
- **`209210292` (Ankara Medipol):** `2024` = *Diş Hekimliği (İngilizce) (%25 İndirimli)* (`Lisans`, `SAY`) → `2025–2026` = *İlk ve Acil Yardım (İngilizce) (Burslu)* (`Ön Lisans`, `TYT`, `240,000 TL` full / `0 TL` net). Oğuz kept the 2024 label and assigned `1,150,000 TL` full / `862,500 TL` net!
- **`209210306` (Ankara Medipol):** `2024` = *Eczacılık (İngilizce) (%25 İndirimli)* (`Lisans`, `SAY`) → `2025–2026` = *Tıbbi Laboratuvar Teknikleri (İngilizce) (Burslu)* (`Ön Lisans`, `TYT`, `240,000 TL` full / `0 TL` net).
- **`200290250` (Atılım):** `2022` = *Uçak Gövde ve Motor Bakımı (İngilizce) (%50 İndirimli)* → `2023–2026` = *Uçak Elektrik ve Elektroniği (İngilizce) (%25 İndirimli)* (`900,000 TL` net vs Oğuz's `600,000 TL` net).

**Architectural Verdict:** Any schema keyed by `program_code` alone (including Oğuz's Excel and `feature/university-sqlite` v1 `programs` table) silently corrupts longitudinal histories and tuition joins on reused codes. Our validated Cost Engine database [cost_engine_foundation.sqlite3](file:///c:/Users/Korai/Desktop/engineering%20design/evidence_pipeline/validated/cost_engine_foundation.sqlite3) enforces **`UNIQUE (admission_year, program_code)`** in `program_offerings` and is 100% immune.

---

## 3. Generated Machine-Readable Reconciliation Outputs
All 4 audit tables live in `evidence_pipeline/validated/oguz_reconciliation/`:
1. [oguz_programs_verification_1282.csv](file:///c:/Users/Korai/Desktop/engineering%20design/evidence_pipeline/validated/oguz_reconciliation/oguz_programs_verification_1282.csv) — Program-level status (`1,208 verified`, `4 partially_verified`, `70 conflicting`).
2. [oguz_annual_admissions_verification_8715.csv](file:///c:/Users/Korai/Desktop/engineering%20design/evidence_pipeline/validated/oguz_reconciliation/oguz_annual_admissions_verification_8715.csv) — Every `(year, program_code)` row checked against official `genel` & `all_tracks` quota/placed + official Kılavuz ranks (`2,157 verified`, `3,620 partially_verified`, `2,938 conflicting`).
3. [oguz_tuition_verification_1282.csv](file:///c:/Users/Korai/Desktop/engineering%20design/evidence_pipeline/validated/oguz_reconciliation/oguz_tuition_verification_1282.csv) — Every program's `2026` & `2025` tuition compared against verified `tuition_schedules` & `mandatory_surcharges`.
4. [oguz_vs_official_conflict_log.csv](file:///c:/Users/Korai/Desktop/engineering%20design/evidence_pipeline/validated/oguz_reconciliation/oguz_vs_official_conflict_log.csv) — `38` structured conflict log rows (`record_id, field, oguz_value, source_value, source_id, status, recommended_action`).
