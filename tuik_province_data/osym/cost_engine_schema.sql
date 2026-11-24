-- Cost Engine & Evidence Foundation Data Layer (SQLite DDL v1)
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
