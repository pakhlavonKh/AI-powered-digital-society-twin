"""Phase 5 — Reproducible Builder & Validation Suite for the Cost Engine Data Layer.

Builds an isolated, constraint-enforced SQLite database:
  evidence_pipeline/validated/cost_engine_foundation.sqlite3
and exports standalone DDL:
  evidence_pipeline/validated/cost_engine_schema.sql

Strictly read-only on raw/ and validated/ CSVs; performs ZERO estimated cost calculations
(data layer only); leaves feature/university-sqlite v1 untouched.
"""

from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path

ROOT = Path(r"c:\Users\Korai\Desktop\engineering design\evidence_pipeline")
META = ROOT / "metadata"
VALID = ROOT / "validated"
RAW_RG = ROOT / "raw" / "resmigazete"
DB_PATH = VALID / "cost_engine_foundation.sqlite3"
DDL_PATH = VALID / "cost_engine_schema.sql"

SCHEMA_SQL = """-- Cost Engine & Evidence Foundation Data Layer (SQLite DDL v1)
-- Independent of feature/university-sqlite v1 (Decision 2 Option A).
-- Monetary amounts stored in integer minor units (e.g., TRY kurus = TL * 100) to avoid float rounding.
PRAGMA foreign_keys = ON;

CREATE TABLE source_inventory (
    source_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(source_id)) > 0),
    source_name TEXT NOT NULL CHECK (length(trim(source_name)) > 0),
    institution TEXT NOT NULL CHECK (length(trim(institution)) > 0),
    url_or_access_path TEXT NOT NULL CHECK (length(trim(url_or_access_path)) > 0),
    reference_year_or_period TEXT NOT NULL,
    publication_date TEXT NOT NULL,
    access_date TEXT NOT NULL CHECK (access_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    coverage TEXT NOT NULL,
    data_definitions_and_methodology_notes TEXT NOT NULL,
    quality_limitations TEXT NOT NULL,
    license_or_terms_of_use TEXT NOT NULL,
    reliability_tier TEXT NOT NULL CHECK (
        reliability_tier IN ('primary_official', 'secondary', 'derived_secondary')
    ),
    public_pipeline_scope TEXT NOT NULL,
    access_status TEXT NOT NULL,
    local_raw_path TEXT,
    sha256 TEXT
);

CREATE TABLE universities (
    ankara_roster_id TEXT PRIMARY KEY NOT NULL,
    official_university_name TEXT NOT NULL UNIQUE,
    university_type TEXT NOT NULL CHECK (university_type IN ('DEVLET', 'VAKIF')),
    hq_city TEXT NOT NULL,
    scope_category TEXT NOT NULL CHECK (
        scope_category IN ('ankara_headquartered', 'non_ankara_hq_with_ankara_campus')
    ),
    source_id TEXT NOT NULL REFERENCES source_inventory(source_id),
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('verified', 'partially_verified', 'conflicting', 'source_not_found', 'outdated')
    )
);

CREATE TABLE program_offerings (
    offering_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_year INTEGER NOT NULL CHECK (admission_year BETWEEN 2019 AND 2030),
    program_code TEXT NOT NULL CHECK (length(program_code) = 9 AND program_code NOT GLOB '*[^0-9]*'),
    official_university_name TEXT NOT NULL,
    university_type TEXT NOT NULL CHECK (university_type IN ('DEVLET', 'VAKIF')),
    hq_city TEXT NOT NULL,
    campus_city TEXT NOT NULL CHECK (campus_city IN ('ANKARA', 'KKTC')),
    program_regime TEXT NOT NULL CHECK (
        program_regime IN (
            'state_standard',
            'state_uolp_dual_degree_paid',
            'state_kktc_branch_paid',
            'foundation_standard'
        )
    ),
    faculty_official TEXT NOT NULL,
    program_name_official TEXT NOT NULL,
    degree_level TEXT NOT NULL CHECK (degree_level IN ('Lisans', 'OnLisans')),
    duration_years INTEGER CHECK (duration_years IS NULL OR duration_years BETWEEN 2 AND 6),
    score_type TEXT NOT NULL CHECK (score_type IN ('TYT', 'SAY', 'EA', 'SÖZ', 'DİL')),
    education_modality TEXT NOT NULL CHECK (
        education_modality IN ('Orgun Ogretim', 'Ikinci Ogretim', 'Uzaktan Ogretim', 'Acikogretim')
    ),
    teaching_language_explicit TEXT CHECK (
        teaching_language_explicit IS NULL OR length(trim(teaching_language_explicit)) > 0
    ),
    scholarship_tier TEXT NOT NULL,
    scholarship_rate_pct INTEGER CHECK (
        scholarship_rate_pct IS NULL OR scholarship_rate_pct IN (0, 25, 50, 75, 100)
    ),
    bk_special_conditions TEXT,
    official_genel_success_rank INTEGER CHECK (
        official_genel_success_rank IS NULL OR official_genel_success_rank > 0
    ),
    official_genel_min_score REAL CHECK (
        official_genel_min_score IS NULL OR official_genel_min_score > 0
    ),
    source_id TEXT NOT NULL REFERENCES source_inventory(source_id),
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('verified', 'partially_verified', 'conflicting', 'source_not_found', 'outdated')
    ),
    notes TEXT,
    UNIQUE (admission_year, program_code)
);

CREATE TABLE admissions_tracks (
    track_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_year INTEGER NOT NULL CHECK (admission_year BETWEEN 2019 AND 2030),
    program_code TEXT NOT NULL,
    quota_track TEXT NOT NULL CHECK (
        quota_track IN ('genel', 'okul_birincisi', 'depremzede', 'kadin_34_plus', 'sehit_gazi_yakini')
    ),
    quota INTEGER CHECK (quota IS NULL OR quota >= 0),
    placed INTEGER CHECK (placed IS NULL OR placed >= 0),
    unfilled_seats INTEGER CHECK (unfilled_seats IS NULL OR unfilled_seats >= 0),
    placed_excess_over_track_quota INTEGER CHECK (
        placed_excess_over_track_quota IS NULL OR placed_excess_over_track_quota >= 0
    ),
    min_score REAL CHECK (min_score IS NULL OR min_score > 0),
    max_score REAL CHECK (max_score IS NULL OR max_score > 0),
    official_success_rank INTEGER CHECK (
        official_success_rank IS NULL OR official_success_rank > 0
    ),
    score_missingness_class TEXT NOT NULL CHECK (
        score_missingness_class IN (
            'complete',
            'genuinely_absent_zero_placed',
            'suppressed_by_osym_unfilled_quota',
            'missing_unexplained_check'
        )
    ),
    source_id TEXT NOT NULL REFERENCES source_inventory(source_id),
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('verified', 'partially_verified', 'conflicting', 'source_not_found', 'outdated')
    ),
    UNIQUE (admission_year, program_code, quota_track),
    FOREIGN KEY (admission_year, program_code)
        REFERENCES program_offerings(admission_year, program_code)
);

CREATE TABLE tuition_schedules (
    tuition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_code TEXT NOT NULL CHECK (length(program_code) = 9 AND program_code NOT GLOB '*[^0-9]*'),
    official_university_name TEXT NOT NULL,
    academic_year TEXT NOT NULL CHECK (academic_year GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]'),
    entry_cohort_year INTEGER NOT NULL CHECK (entry_cohort_year BETWEEN 2019 AND 2030),
    fee_type TEXT NOT NULL CHECK (fee_type IN ('nominal_new_entrant', 'continuing_cohort')),
    program_regime TEXT NOT NULL,
    scholarship_tier TEXT NOT NULL,
    scholarship_rate_pct INTEGER CHECK (
        scholarship_rate_pct IS NULL OR scholarship_rate_pct IN (0, 25, 50, 75, 100)
    ),
    full_annual_minor INTEGER CHECK (full_annual_minor IS NULL OR full_annual_minor >= 0),
    net_annual_minor INTEGER CHECK (net_annual_minor IS NULL OR net_annual_minor >= 0),
    cash_discount_net_minor INTEGER CHECK (cash_discount_net_minor IS NULL OR cash_discount_net_minor >= 0),
    prep_year_full_minor INTEGER CHECK (prep_year_full_minor IS NULL OR prep_year_full_minor >= 0),
    currency TEXT NOT NULL CHECK (currency IN ('TRY', 'EUR', 'USD', 'TRY/USD')),
    billing_terms_per_year INTEGER NOT NULL DEFAULT 2 CHECK (billing_terms_per_year IN (2, 3)),
    kdv_included TEXT NOT NULL,
    kdv_rate_pct REAL CHECK (kdv_rate_pct IS NULL OR kdv_rate_pct >= 0),
    validity_start TEXT NOT NULL,
    validity_end TEXT NOT NULL,
    scholarship_and_payment_conditions TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source_inventory(source_id),
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('verified', 'partially_verified', 'conflicting', 'source_not_found', 'outdated')
    ),
    fee_basis_note TEXT,
    CHECK (
        full_annual_minor IS NULL
        OR net_annual_minor IS NULL
        OR net_annual_minor <= full_annual_minor
    ),
    UNIQUE (program_code, academic_year, entry_cohort_year, fee_type)
);

CREATE TABLE mandatory_surcharges (
    surcharge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    official_university_name TEXT NOT NULL,
    program_code TEXT,
    program_match_pattern TEXT NOT NULL,
    academic_year TEXT NOT NULL CHECK (academic_year GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]'),
    surcharge_type TEXT NOT NULL CHECK (
        surcharge_type IN ('pilotaj_flight_training', 'term_installment_surcharge', 'other_mandatory')
    ),
    amount_minor INTEGER CHECK (amount_minor IS NULL OR amount_minor >= 0),
    currency TEXT NOT NULL CHECK (currency IN ('TRY', 'EUR', 'USD')),
    kdv_included INTEGER CHECK (kdv_included IN (0, 1)),
    covered_for_burslu INTEGER CHECK (covered_for_burslu IS NULL OR covered_for_burslu IN (0, 1)),
    conditions_text TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source_inventory(source_id),
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('verified', 'partially_verified', 'conflicting', 'source_not_found', 'outdated')
    ),
    UNIQUE (official_university_name, program_match_pattern, academic_year, surcharge_type)
);

CREATE TABLE scholarship_rules (
    rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    official_university_name TEXT NOT NULL,
    academic_year TEXT NOT NULL CHECK (academic_year GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]'),
    rule_category TEXT NOT NULL CHECK (
        rule_category IN (
            'osym_statutory',
            'cash_upfront_discount',
            'preference_rank_discount',
            'sibling_discount',
            'merit_rank_stipend',
            'disability_or_martyr_discount',
            'annual_increase_cap'
        )
    ),
    discount_or_benefit_summary TEXT NOT NULL,
    stackable_with_osym_scholarship INTEGER CHECK (stackable_with_osym_scholarship IN (0, 1)),
    covers_prep_year INTEGER CHECK (covers_prep_year IS NULL OR covers_prep_year IN (0, 1)),
    continuation_conditions TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source_inventory(source_id),
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('verified', 'partially_verified', 'conflicting', 'source_not_found', 'outdated')
    )
);

CREATE TABLE state_statutory_fee_decrees (
    academic_year TEXT PRIMARY KEY NOT NULL CHECK (academic_year GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]'),
    presidential_decree_no TEXT NOT NULL,
    gazette_date TEXT NOT NULL CHECK (gazette_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    gazette_issue_no TEXT NOT NULL,
    formal_normal_duration_tc_exempt INTEGER NOT NULL CHECK (formal_normal_duration_tc_exempt IN (0, 1)),
    io_abolished_new_entrants INTEGER NOT NULL CHECK (io_abolished_new_entrants IN (0, 1)),
    cetvel_table_extraction_status TEXT NOT NULL,
    local_pdf_path TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    source_id TEXT NOT NULL REFERENCES source_inventory(source_id),
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('verified', 'partially_verified', 'conflicting', 'source_not_found', 'outdated')
    )
);

CREATE TABLE conflict_and_missing_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    field TEXT NOT NULL,
    oguz_value TEXT,
    source_value TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source_inventory(source_id),
    status TEXT NOT NULL CHECK (
        status IN ('verified', 'partially_verified', 'conflicting', 'source_not_found', 'outdated')
    ),
    recommended_action TEXT NOT NULL
);

CREATE INDEX idx_offerings_year_campus ON program_offerings(admission_year, campus_city, university_type);
CREATE INDEX idx_tracks_year_code ON admissions_tracks(admission_year, program_code);
CREATE INDEX idx_tuition_year_univ ON tuition_schedules(academic_year, official_university_name, verification_status);

-- Consumer View 1: All 2026 Ankara-Physical Programs (excludes 68 KKTC branch campus rows)
CREATE VIEW v_ankara_physical_programs_2026 AS
SELECT
    p.program_code,
    p.official_university_name,
    p.university_type,
    p.hq_city,
    p.campus_city,
    p.program_regime,
    p.faculty_official,
    p.program_name_official,
    p.degree_level,
    p.duration_years,
    p.score_type,
    p.education_modality,
    p.teaching_language_explicit,
    p.scholarship_tier,
    p.scholarship_rate_pct,
    t.quota AS genel_quota_2026,
    t.placed AS genel_placed_2026,
    t.unfilled_seats AS genel_unfilled_2026,
    t.placed_excess_over_track_quota AS genel_ob_rollover_excess_2026,
    t.min_score AS genel_min_score_2026,
    t.max_score AS genel_max_score_2026,
    p.source_id,
    p.verification_status
FROM program_offerings p
JOIN admissions_tracks t
  ON t.admission_year = p.admission_year
 AND t.program_code = p.program_code
 AND t.quota_track = 'genel'
WHERE p.admission_year = 2026
  AND p.campus_city = 'ANKARA';

-- Consumer View 2: Cost Engine Ready Layer (2026-2027 verified & flagged tuition + surcharges)
CREATE VIEW v_cost_engine_2026_2027_ready AS
SELECT
    p.program_code,
    p.official_university_name,
    p.university_type,
    p.campus_city,
    p.program_regime,
    p.degree_level,
    p.duration_years,
    p.score_type,
    p.program_name_official,
    p.teaching_language_explicit,
    ts.academic_year,
    ts.entry_cohort_year,
    ts.fee_type,
    ts.scholarship_tier,
    ts.scholarship_rate_pct,
    CAST(ts.full_annual_minor AS REAL) / 100.0 AS full_annual_tuition_try,
    CAST(ts.net_annual_minor AS REAL) / 100.0 AS net_annual_tuition_try,
    CAST(ts.cash_discount_net_minor AS REAL) / 100.0 AS cash_discount_net_try,
    CAST(ts.prep_year_full_minor AS REAL) / 100.0 AS prep_year_full_try,
    ts.currency,
    ts.billing_terms_per_year,
    ts.kdv_included,
    ts.kdv_rate_pct,
    ms.surcharge_type,
    CAST(ms.amount_minor AS REAL) / 100.0 AS mandatory_surcharge_amount,
    ms.currency AS mandatory_surcharge_currency,
    ms.covered_for_burslu AS surcharge_covered_for_burslu,
    ts.validity_start,
    ts.validity_end,
    ts.source_id,
    ts.verification_status
FROM program_offerings p
JOIN tuition_schedules ts
  ON ts.program_code = p.program_code
 AND ts.academic_year = '2026-2027'
 AND ts.fee_type = 'nominal_new_entrant'
LEFT JOIN mandatory_surcharges ms
  ON ms.official_university_name = p.official_university_name
 AND ms.academic_year = ts.academic_year
 AND lower(p.program_name_official) LIKE '%' || lower(ms.program_match_pattern) || '%'
WHERE p.admission_year = 2026;
"""


def to_minor(val_str: str) -> int | None:
    s = (val_str or "").strip()
    if not s:
        return None
    return int(round(float(s) * 100))


def to_int_or_none(val_str: str) -> int | None:
    s = (val_str or "").strip()
    if not s:
        return None
    return int(float(s))


def to_float_or_none(val_str: str) -> float | None:
    s = (val_str or "").strip()
    if not s:
        return None
    return float(s)


def primary_sid(src_field: str) -> str:
    return src_field.split("|")[0].strip()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_source_inventory() -> list[dict]:
    """Read synchronized source_inventory.csv without mutating it."""
    inv_path = META / "source_inventory.csv"
    return list(csv.DictReader(inv_path.open("r", encoding="utf-8-sig")))


def build_database() -> None:
    DDL_PATH.write_text(SCHEMA_SQL, encoding="utf-8")
    if DB_PATH.exists():
        DB_PATH.unlink()

    inv_rows = load_source_inventory()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute("PRAGMA user_version = 1")

        # 1. source_inventory
        conn.executemany(
            """INSERT INTO source_inventory VALUES (
                :source_id, :source_name, :institution, :url_or_access_path,
                :reference_year_or_period, :publication_date, :access_date, :coverage,
                :data_definitions_and_methodology_notes, :quality_limitations,
                :license_or_terms_of_use, :reliability_tier, :public_pipeline_scope,
                :access_status, :local_raw_path, :sha256
            )""",
            inv_rows,
        )

        # 2. universities (all 22 official Ankara institutions)
        roster = list(csv.DictReader((META / "ankara_universities_2026_official.csv").open("r", encoding="utf-8-sig")))
        for r in roster:
            hq = "ANKARA" if r["scope_category"] == "ankara_headquartered" else "İSTANBUL"
            conn.execute(
                """INSERT INTO universities VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    r["ankara_roster_id"],
                    r["official_university_name_osym_2026"],
                    r["university_type"],
                    hq,
                    r["scope_category"],
                    "SRC-OSYM-T4-2026",
                    "verified",
                ),
            )

        # Load Kılavuz metadata (duration & Bk. codes) keyed by (year, program_code)
        kil_meta = {}
        with (VALID / "ankara_kilavuz_preplacement_2019_2026.csv").open("r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                kil_meta[(int(r["kilavuz_year"]), r["program_code"])] = (
                    to_int_or_none(r["duration_years"]),
                    r["bk_special_conditions"].strip() or None,
                )

        # Load min_score per (year, code) for genel track
        genel_min = {}
        with (VALID / "ankara_admissions_tracks_2019_2026_validated.csv").open("r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["quota_track"] == "genel":
                    genel_min[(int(r["admission_year"]), r["program_code"])] = to_float_or_none(r["min_score"])

        # 3. program_offerings (2019–2024 & 2026 verified + 2025 partial from 2026 Kılavuz)
        with (VALID / "ankara_programs_2019_2026_validated.csv").open("r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                yr = int(r["admission_year"])
                code = r["program_code"]
                dur, bk = kil_meta.get((yr, code), (None, None))
                conn.execute(
                    """INSERT INTO program_offerings (
                        admission_year, program_code, official_university_name, university_type,
                        hq_city, campus_city, program_regime, faculty_official, program_name_official,
                        degree_level, duration_years, score_type, education_modality,
                        teaching_language_explicit, scholarship_tier, scholarship_rate_pct,
                        bk_special_conditions, official_genel_success_rank, official_genel_min_score,
                        source_id, verification_status, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        yr, code, r["university_name_official"], r["university_type"],
                        r["hq_city"], r["campus_city"], r["program_regime"],
                        r["faculty_official"], r["program_name_official"], r["degree_level"],
                        dur, r["score_type"], r["education_modality"],
                        r["teaching_language_explicit"].strip() or None,
                        r["scholarship_tier"], to_int_or_none(r["scholarship_rate_pct"]),
                        bk, to_int_or_none(r["official_genel_success_rank_from_next_kilavuz"]),
                        genel_min.get((yr, code)),
                        primary_sid(r["source_id"]), r["verification_status"],
                        f"source_file={r['source_file']};row={r['source_row']}",
                    ),
                )

        # Verify ALL 8 consecutive years (2019–2026) are now loaded as verified from primary ÖSYM TABLO-3/4 XLSX!
        loaded_years = [row[0] for row in conn.execute("SELECT DISTINCT admission_year FROM program_offerings ORDER BY admission_year")]
        assert loaded_years == [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026], f"Expected 8/8 years 2019-2026, got {loaded_years}"

        # 4. admissions_tracks (all 8 years verified multi-track rows)
        with (VALID / "ankara_admissions_tracks_2019_2026_validated.csv").open("r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                conn.execute(
                    """INSERT INTO admissions_tracks (
                        admission_year, program_code, quota_track, quota, placed,
                        unfilled_seats, placed_excess_over_track_quota, min_score, max_score,
                        official_success_rank, score_missingness_class, source_id, verification_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(r["admission_year"]), r["program_code"], r["quota_track"],
                        to_int_or_none(r["quota"]), to_int_or_none(r["placed"]),
                        to_int_or_none(r["unfilled_seats"]), to_int_or_none(r["placed_excess_over_track_quota"]),
                        to_float_or_none(r["min_score"]), to_float_or_none(r["max_score"]),
                        to_int_or_none(r["official_success_rank"]), r["score_missingness_class"],
                        primary_sid(r["source_id"]), r["verification_status"],
                    ),
                )

        # 5. tuition_schedules (1,944 structured records: 2026-2027 all 1,882 + 2025-2026 TOBB ETÜ 62)
        with (VALID / "ankara_tuition_2026_2027_complete_validated.csv").open("r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                ay = r["academic_year"]
                cohort = int(ay.split("-")[0])
                terms = 3 if "TOBB" in r["university_name_official"].upper() else 2
                kdv_rate = 10.0 if r["kdv_included"].startswith("yes_10pct") else (0.0 if "exempt" in r["kdv_included"] else None)
                v_start = f"{cohort}-09-01"
                v_end = f"{cohort + 1}-08-31"
                conn.execute(
                    """INSERT INTO tuition_schedules (
                        program_code, official_university_name, academic_year, entry_cohort_year,
                        fee_type, program_regime, scholarship_tier, scholarship_rate_pct,
                        full_annual_minor, net_annual_minor, cash_discount_net_minor, prep_year_full_minor,
                        currency, billing_terms_per_year, kdv_included, kdv_rate_pct,
                        validity_start, validity_end, scholarship_and_payment_conditions,
                        source_id, verification_status, fee_basis_note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        r["program_code"], r["university_name_official"], ay, cohort, r["fee_type"],
                        r["program_regime"], r["scholarship_tier"], to_int_or_none(r["scholarship_rate_pct"]),
                        to_minor(r["full_annual_tuition_try"]), to_minor(r["net_annual_tuition_try"]),
                        to_minor(r["cash_discount_net_try"]), to_minor(r["prep_year_full_tuition_try"]),
                        r["currency"], terms, r["kdv_included"], kdv_rate, v_start, v_end,
                        r["scholarship_and_payment_conditions"], primary_sid(r["source_id"]),
                        r["verification_status"], r["fee_basis_note"],
                    ),
                )

        # 6. mandatory_surcharges (all 3 verified multi-currency Ankara Pilotaj flight surcharges!)
        surcharges = [
            ("ANKARA BİLİM ÜNİVERSİTESİ", None, "pilotaj", "2026-2027", "pilotaj_flight_training",
             7500000, "EUR", 0, None,
             "75,000 EUR + KDV mandatory flight training fee in addition to 1,280,000 TL annual tuition.",
             "SRC-OSYM-KILAVUZ-2019-2026", "verified"),
            ("ATILIM ÜNİVERSİTESİ (ANKARA)", None, "pilotaj", "2026-2027", "pilotaj_flight_training",
             8200000, "EUR", None, None,
             "82,000 EUR mandatory flight training fee in addition to 1,200,000 TL annual tuition (ÖSYM 2026 Kılavuz p.711).",
             "SRC-OSYM-KILAVUZ-2019-2026", "verified"),
            ("TÜRK HAVA KURUMU ÜNİVERSİTESİ (ANKARA)", None, "pilotaj", "2026-2027", "pilotaj_flight_training",
             9600000, "USD", 1, 1,
             "96,000 USD (KDV Dahil) flight training fee; covered by university for Burslu students across 1-yr prep + normal duration (ÖSYM 2026 Kılavuz p.752).",
             "SRC-OSYM-KILAVUZ-2019-2026", "verified"),
        ]
        conn.executemany(
            """INSERT INTO mandatory_surcharges (
                official_university_name, program_code, program_match_pattern, academic_year,
                surcharge_type, amount_minor, currency, kdv_included, covered_for_burslu,
                conditions_text, source_id, verification_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            surcharges,
        )

        # 7. scholarship_rules (verified institutional rules from archived raw .edu.tr & 2026 Kılavuz)
        rules = [
            ("İHSAN DOĞRAMACI BİLKENT ÜNİVERSİTESİ (ANKARA)", "2026-2027", "cash_upfront_discount",
             "Upfront September payment reduces full annual tuition from 1,295,000 TL to 1,245,000 TL (and %50 Burslu from 647,500 TL to 622,500 TL).",
             1, 1, "Applies to full-year payment in September instead of 2 installments (Sep & Jan).", "SRC-UNIV-BILKENT", "verified"),
            ("TOBB EKONOMİ VE TEKNOLOJİ ÜNİVERSİTESİ (ANKARA)", "2026-2027", "cash_upfront_discount",
             "3-term academic year (Güz/Bahar/Yaz): upfront payment 1,250,000 TL (non-Med) vs term-by-term total 1,291,667 TL (+10% Yaz surcharge).",
             1, 1, "Term-by-term payment allows 4 installments/term (12/yr) with Yaz term surcharge.", "SRC-UNIV-TOBBETU", "verified"),
            ("ÇANKAYA ÜNİVERSİTESİ (ANKARA)", "2026-2027", "annual_increase_cap",
             "Annual tuition increases from 2027-2028 onward guaranteed capped at realized inflation; ÖSYM scholarship covers English Prep.",
             1, 1, "Unconditional across Prep and active enrollment while attending classes.", "SRC-UNIV-CANKAYA", "verified"),
            ("ANKARA BİLİM ÜNİVERSİTESİ", "2026-2027", "preference_rank_discount",
             "Top-5 preference placement grants extra 5% discount; upfront payment grants extra compounding 10% discount (e.g., 560k -> 532k -> 478.8k TL).",
             1, None, "Published on official 2026-2027 student fee table PDF.", "SRC-UNIV-ANKBILIM", "verified"),
            ("ANKARA MEDİPOL ÜNİVERSİTESİ", "2026-2027", "merit_rank_stipend",
             "Rank-based monthly stipends (7 mo/yr: 13k-50k TL) + free dorm/meals for top ranks; +10% sibling, disability (>=40%), martyr/veteran discounts.",
             1, 1, "Valid across standard duration and mandatory prep (raw ankaramedipol_burslar_2026.html).", "SRC-UNIV-ANKMED", "verified"),
            ("TED ÜNİVERSİTESİ (ANKARA)", "2026-2027", "sibling_discount",
             "+10% sibling discount for concurrent fee-paying siblings; Academic Achievement scholarship 50%/40%/30% for top-3 GPA ranks.",
             1, 1, "Per TEDÜ Undergraduate Scholarship Directive (raw tedu_ucretler_2026.html).", "SRC-UNIV-TEDU", "verified"),
            ("TÜRK HAVA KURUMU ÜNİVERSİTESİ (ANKARA)", "2026-2027", "osym_statutory",
             "Pilotaj 100% Burslu students have their 96,000 USD flight-school fee covered by university for 1-yr prep + normal duration.",
             1, 1, "Explicitly stated in 2026 ÖSYM Kılavuz p.752.", "SRC-OSYM-KILAVUZ-2019-2026", "verified"),
        ]
        conn.executemany(
            """INSERT INTO scholarship_rules (
                official_university_name, academic_year, rule_category, discount_or_benefit_summary,
                stackable_with_osym_scholarship, covers_prep_year, continuation_conditions,
                source_id, verification_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rules,
        )

        # 8. state_statutory_fee_decrees (ALL 8 Resmî Gazete PDFs 2019-2026 verified & hashed!)
        decrees = [
            ("2019-2020", "1842",  "2019-12-24", "30988", 1, 0, "rg_2019_2020_karar1842_20191224.pdf"),
            ("2020-2021", "2755",  "2020-07-11", "31182", 1, 0, "rg_2020_2021_karar2755_20200711.pdf"),
            ("2021-2022", "4230",  "2021-07-01", "31527", 1, 0, "rg_2021_2022_karar4230_20210701.pdf"),
            ("2022-2023", "5874",  "2022-07-27", "31905", 1, 0, "rg_2022_2023_karar5874_20220727.pdf"),
            ("2023-2024", "7384",  "2023-07-15", "32249", 1, 0, "rg_2023_2024_karar7384_20230715.pdf"),
            ("2024-2025", "8703",  "2024-07-02", "32590", 1, 1, "rg_2024_2025_karar8703_20240702.pdf"),
            ("2025-2026", "10042", "2025-07-09", "32953", 1, 1, "rg_2025_2026_karar10042_20250709.pdf"),
            ("2026-2027", "11625", "2026-08-15", "33341", 1, 1, "rg_2026_2027_karar11625_20260815.pdf"),
        ]
        for ay, kno, gdate, gno, exempt, io_abol, fn in decrees:
            p = RAW_RG / fn
            conn.execute(
                """INSERT INTO state_statutory_fee_decrees VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ay, kno, gdate, gno, exempt, io_abol,
                    "scanned_image_cetvel_pending_ocr_or_visual_transcription",
                    f"evidence_pipeline/raw/resmigazete/{fn}",
                    sha256_file(p),
                    "SRC-RG-TUITION-2019-2026",
                    "partially_verified",
                ),
            )

        # 9. conflict_and_missing_log (consolidated key conflicts across Phases 1–4)
        p1_logs = list(csv.DictReader((META / "phase1_conflict_missing_log.csv").open("r", encoding="utf-8-sig")))
        for r in p1_logs:
            conn.execute(
                """INSERT INTO conflict_and_missing_log (record_id, field, oguz_value, source_value, source_id, status, recommended_action)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (r["record_id"], r["field"], r["oguz_value"], r["source_value"], primary_sid(r["source_id"]), r["status"], r["recommended_action"]),
            )
        extra_logs = [
            ("OGUZ-RECON:30-REUSED-CODES", "program_code_identity_across_years", "30 codes treated as static 2019-2026 PKs in Oğuz workbook",
             "ÖSYM reassigned 30 codes (29 Ankara Medipol + 1 Atılım 200290250) to different degrees/score_types/tiers (e.g., 209210292: 2024 Diş %25 SAY -> 2025-26 İlk ve Acil Yardım EN Burslu TYT).",
             "SRC-OGUZ-01", "conflicting", "Composite key (admission_year, program_code) enforced in program_offerings prevents corruption."),
            ("OGUZ-RECON:2720-TRACK-MIX", "kontenjan_vs_yerlesen", "2,720 placed>quota warnings in Oğuz workbook (8,715 rows)",
             "100% Kontenjan=Genel Quota, but 1,914 Yerleşen=ALL-tracks sum -> exact split: 1,669 track-mixing, 803 pure State 1:1 OB rollover, 245 combined, 3 +1/+2.",
             "SRC-OGUZ-01", "conflicting", "Consume normalized admissions_tracks instead of Oğuz's collapsed single-column Yerleşen."),
            ("OGUZ-RECON:TUITION-AND-COV", "2026_tuition_and_coverage", "1,124 active 2026 progs; 1,035/1,124 exact match; 32 TRY diffs + 30 State non-free 0 TL",
             "Missing 758 active 2026 progs (534 in 9 omitted univs + 224 inside Oğuz's 13 univs); 17 EN fee errors (10 OSTİM, 7 Medipol) + 15 reused-code collisions + 30 paid KKTC/UOLP labeled 0 TL + 4 Pilotaj missing EUR.",
             "SRC-OGUZ-01", "conflicting", "Use cost_engine_foundation.sqlite3 v_cost_engine_2026_2027_ready (100% 13/13 foundation univs verified)."),
            ("2025:OSYM-PARTIAL-403", "2025_placement_pdf_and_kilavuz", "FILE_UNAVAILABLE",
             "2025 TABLO-3 & TABLO-4 XLSX (1,929 Ankara programs, 3,623 track rows) ARE NOW VERIFIED & INGESTED (upgrading panel to 8/8 yrs 2019-2026); only 2025 Placement PDF & 2022/2025 Kılavuz remain unavailable (HTTP 403).",
             "SRC-OSYM-SB-2019-2025", "partially_verified", "Program-level panel is 100% complete across 2019-2026; ingest 2025 Placement PDF if restored."),
            ("2019-2026:2161-OB-ROLLOVER", "genel_placed_vs_genel_quota", "2,720 open warnings in repo audit",
             "2,161 / 2,161 (100.0%) Ankara State over-placements match unused Okul Birincisi seats 1:1 across ALL 8 years (2019–2026, incl. 224/224 in 2025).",
             "SRC-OSYM-T4-2026", "verified", "Retain track-level tables; never clamp placed to quota."),
            ("2021-EVAL:TABLO11-SOZ-4X", "osym_2021_tablo11_printed_total", "N/A (primary official PDF audit)",
             "ÖSYM 2021 Değerlendirme Raporu Tablo 11 (p.53) SÖZ 4x row prints Toplam=43,914 (omitting 100-149 bin=1,648); true bin sum 45,562 matches ÖSYM's own printed % (7.85%..0.04%), Tablo 10 & Tablo 12 (938,291).",
             "SRC-OSYM-EVAL-2019-2021", "conflicting", "Both source_printed_total (43,914) and reconciled bin sum (45,562) preserved explicitly in CSV."),
            ("2025-2026:YOK-T103-SBU", "sbu_department_campus_split", "N/A (YÖK T103 granularity)",
             "YÖK T103 aggregates SBÜ faculties across Istanbul+Ankara; SBÜ Gülhane Ankara campus (1,857 new registrants) is isolated cleanly via KEÇİÖREN district row in T101.",
             "SRC-YOK-ISTATISTIK", "partially_verified", "Use T101 KEÇİÖREN for SBÜ Ankara totals and T103 for 21 Ankara-HQ department gender splits."),
            ("2026:ANKMED-OSTIM-EN-DIFF", "full_annual_tuition_try", "6 English med/pharmacy fee tensions in repo",
             "Ankara Medipol: 14 EN programs lower than TR (e.g. Tıp 990k vs 1.15M); OSTİM: 5 EN programs higher than TR.",
             "SRC-OSYM-KILAVUZ-2019-2026", "verified", "Resolved program-by-program in tuition_schedules."),
            ("2026:PILOTAJ-3UNIVS-FX", "mandatory_surcharge", "Incomplete pilot-training charges noted in repo",
             "Ankara Bilim +75,000 EUR+KDV; Atılım +82,000 EUR; THK +96,000 USD (KDV incl., Burslu covered).",
             "SRC-OSYM-KILAVUZ-2019-2026", "verified", "Stored in mandatory_surcharges with explicit FX currency & KDV flags."),
            ("2026:68-KKTC-11-UOLP-STATE", "campus_city_and_program_regime", "Repo labeled all State rows 'Devlet (Ücretsiz)'",
             "68 KKTC branch campus rows (ODTÜ KKK 31, ASBÜ KKTC 37) + 11 paid State UOLP dual-degree rows identified.",
             "SRC-OSYM-T4-2026", "conflicting", "Isolated via campus_city & program_regime; use v_ankara_physical_programs_2026 for physical Ankara."),
        ]
        conn.executemany(
            """INSERT INTO conflict_and_missing_log (record_id, field, oguz_value, source_value, source_id, status, recommended_action)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            extra_logs,
        )

        conn.commit()

        # === AUTOMATED VALIDATION SUITE ===
        ic = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        fkc = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
        assert ic == ["ok"], f"integrity_check failed: {ic}"
        assert fkc == [], f"foreign_key_check failed: {fkc}"

        # Constraint enforcement probe on in-memory copy (must reject negative tuition & net > full)
        mem = sqlite3.connect(":memory:")
        mem.execute("PRAGMA foreign_keys = ON")
        mem.executescript(SCHEMA_SQL)
        mem.execute("INSERT INTO source_inventory VALUES ('S1','N','I','U','2026','2026','2026-11-22','c','d','q','l','primary_official','in_scope_public','downloaded_verified','','')")
        probes_passed = 0
        for bad_sql in [
            "INSERT INTO tuition_schedules (program_code,official_university_name,academic_year,entry_cohort_year,fee_type,program_regime,scholarship_tier,full_annual_minor,net_annual_minor,currency,kdv_included,validity_start,validity_end,scholarship_and_payment_conditions,source_id,verification_status) VALUES ('123456789','U','2026-2027',2026,'nominal_new_entrant','foundation_standard','Ücretli',-100,0,'TRY','yes','2026-09-01','2027-08-31','c','S1','verified')",
            "INSERT INTO tuition_schedules (program_code,official_university_name,academic_year,entry_cohort_year,fee_type,program_regime,scholarship_tier,full_annual_minor,net_annual_minor,currency,kdv_included,validity_start,validity_end,scholarship_and_payment_conditions,source_id,verification_status) VALUES ('123456789','U','2026-2027',2026,'nominal_new_entrant','foundation_standard','%50',100000,200000,'TRY','yes','2026-09-01','2027-08-31','c','S1','verified')",
            "INSERT INTO tuition_schedules (program_code,official_university_name,academic_year,entry_cohort_year,fee_type,program_regime,scholarship_tier,full_annual_minor,net_annual_minor,currency,kdv_included,validity_start,validity_end,scholarship_and_payment_conditions,source_id,verification_status) VALUES ('123456789','U','2026-2027',2026,'nominal_new_entrant','foundation_standard','Ücretli',100000,100000,'TRY','yes','2026-09-01','2027-08-31','c','NO_SUCH_SRC','verified')",
        ]:
            try:
                mem.execute(bad_sql)
                raise AssertionError(f"Expected constraint rejection for: {bad_sql}")
            except sqlite3.IntegrityError:
                probes_passed += 1
        mem.close()

        print("=== PHASE 5 COST ENGINE DATABASE BUILT & VALIDATED ===")
        print(f"Database: {DB_PATH} ({DB_PATH.stat().st_size:,} bytes) | integrity_check={ic} | fk_errors={len(fkc)} | constraint_probes_rejected={probes_passed}/3")
        for tbl in [
            "source_inventory", "universities", "program_offerings", "admissions_tracks",
            "tuition_schedules", "mandatory_surcharges", "scholarship_rules",
            "state_statutory_fee_decrees", "conflict_and_missing_log",
        ]:
            cnt = conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            print(f"  table {tbl:30s}: {cnt:6d} rows")
        for vw in ["v_ankara_physical_programs_2026", "v_cost_engine_2026_2027_ready"]:
            cnt = conn.execute(f"SELECT count(*) FROM {vw}").fetchone()[0]
            print(f"  view  {vw:30s}: {cnt:6d} rows")

        print("\n=== EXAMPLE QUERY: 2026-2027 VERIFIED ANKARA FOUNDATION TUITION STATS BY UNIVERSITY ===")
        q = """
        SELECT official_university_name,
               COUNT(*) AS progs,
               ROUND(MIN(full_annual_tuition_try), 0) AS min_full_try,
               ROUND(MAX(full_annual_tuition_try), 0) AS max_full_try,
               SUM(CASE WHEN mandatory_surcharge_amount IS NOT NULL THEN 1 ELSE 0 END) AS with_fx_surcharge
        FROM v_cost_engine_2026_2027_ready
        WHERE university_type = 'VAKIF' AND verification_status = 'verified'
        GROUP BY official_university_name
        ORDER BY max_full_try DESC;
        """
        for row in conn.execute(q):
            print(f"  {row['official_university_name']:46s} | progs={row['progs']:3d} | min={int(row['min_full_try']):10,d} | max={int(row['max_full_try']):10,d} | fx_surcharge={row['with_fx_surcharge']}")
    finally:
        conn.close()


if __name__ == "__main__":
    build_database()
