# University SQLite observations

This standalone domain stores observed university workbook data. It does not
change the Population or Scenario Engines and has no application startup hook.
Step 2 defines the schema; Step 3 adds an explicit, read-only workbook importer.
The complete executable DDL is in `src/societytwin/university/db.py` (`SCHEMA`).
See [Milestone 1 validation and research limitations](university-validation.md)
for the shareable audit summary and readiness assessment.

## Tables and relationships

| Table | Primary key | Contents and identity constraints |
| --- | --- | --- |
| `source_snapshots` | `snapshot_id` (text) | Original filename, unique lowercase SHA-256 of original file bytes, import timestamp and parser version; optional description, URL/document reference, retrieval date and notes. Verification status is `unverified`, `verified` or `rejected`. |
| `universities` | `university_id` (integer) | Original and normalized name, original institution type, optional supported city and official code. Unique `(snapshot_id, university_key)`. The key is internal, never an invented official code. |
| `programs` | `program_id` (integer) | Text official program code, original department/program name, faculty, degree level, score type, original scholarship label, nullable teaching language and sheet/row reference. Unique `(snapshot_id, program_code)`. |
| `annual_admissions` | `admission_id` (integer) | Admission year, nullable quota, placed count and last placed candidate's success rank, plus sheet/row reference. Unique `(snapshot_id, program_id, admission_year)`. |
| `annual_tuition` | `tuition_id` (integer) | Academic-year start, independently nullable full and net annual amounts in integer minor units, three-letter uppercase currency, optional original fee basis and sheet/row reference. Unique `(snapshot_id, program_id, academic_year_start)`. |
| `data_quality_issues` | `issue_id` (integer) | Issue code, severity (`info`, `warning`, `error`), message, optional program/year, sheet/row/column and raw value. Review status (`open`, `resolved`, `accepted`) and optional resolution. Unique `(snapshot_id, issue_key)` for repeatable issue reporting. |

Every domain row has a required `snapshot_id` foreign key. Each university has
many programs; each program has many annual admission and tuition observations
and optional quality issues. Composite foreign keys `(university_id, snapshot_id)`
and `(program_id, snapshot_id)` prevent references across snapshots. Referenced
entities cannot be deleted while dependent records exist; there are no cascades.
Quality issues may exist without a program, for records rejected before matching.
Their year is a contextual year, not a foreign key requiring an admitted record.

University and program identities are scoped to a snapshot: a changed file may
retain the same internal university key and official program code in a new
snapshot without overwriting earlier observations. Cross-snapshot entity matching
is future work; integer row IDs are not stable cross-file identifiers.
Different scholarship variants with different official program codes remain
different programs. There is one annual tuition observation per program/year;
additional conflicting quotes must be reviewed rather than silently overwritten.

## Missing values and observed data

SQL `NULL` means missing or unspecified; zero means an explicitly observed zero.
Quota and placed counts must be nonnegative integers when known; success ranks
must be positive integers. Counts above quota are permitted and must not be capped.
Fractional or negative integer measures are rejected. Years are integers from
1900 through 9999 (tuition starts stop at 9998). Source rows are positive,
one-based worksheet rows. Program codes use TEXT affinity: the importer must
supply strings and preserve leading zeros without numeric conversion.

Tuition uses integer minor units to avoid floating-point money rounding: for TRY,
123456 represents 1234.56 lira. Full and net amounts are separate source fields;
the importer does not calculate either from scholarship labels. Net amounts were
calculated upstream in the source workbook, as described below. Missing historical fees remain
NULL. The source meaning of fee basis, taxes, discounts, currency and academic
year must be verified during import. `academic_year_start=2025` represents
2025/2026 only when supported by the source. The inspected workbook labels fees
`2025` and `2026`, without establishing academic-year boundaries. The importer
uses these fee-year labels in `academic_year_start` and explicitly marks the
boundaries as unverified in each row's `fee_basis` JSON. Display these as source
fee years rather than asserting academic terms.

Fill rates, scholarship-adjusted estimates, trends and summary indicators are
not stored here. Future analysis can calculate them separately and label them
as derived. University `name_normalized` and internal `university_key` are
matching metadata; the original name remains intact. Parser v1 matches exact
university names, copies the name unchanged into `name_normalized`, and builds
`university_key` from SHA-256 of the UTF-8 name. It does not merge labels or infer
official codes, degree levels or cities. Conflicting institution types quarantine
affected programs.

## Teaching language

`programs.teaching_language` preserves the exact supplied label, including
capitalization and spacing: `İngilizce`, `Türkçe`, or any other source label.
An empty source cell must become SQL NULL. NULL means **the source did not
explicitly specify a teaching language**; it does not identify Turkish instruction.
There is no default, normalized-language field, translation, category conversion
or inference from department names. The database rejects an empty string but
does not rewrite labels. The importer maps empty cells to None. Storage and
artificial-workbook tests verify exact Turkish and arbitrary labels, whitespace,
NULLs and absence of inference at both storage and importer boundaries.

## Provenance and repeatability

Archive the unchanged original workbook outside Git according to `docs/data-strategy.md`.
`source_reference` can identify that archived document or its source URL; the
database stores metadata and hash, not workbook bytes. Hash the original bytes
before parsing. The importer uses the stable identifier `sha256:<hash>`.
The unique file hash prevents duplicate snapshots of byte-identical input;
reprocessing with a different parser requires an explicit migration rather than duplicate rows.
Import timestamps use UTC ISO-8601. The source-reported retrieval date 2026-09-20
is captured from `Açıklamalar` in `retrieved_at`, with its origin recorded in
snapshot notes. Unknown retrieval dates stay NULL; import time never replaces
them. Verification remains `unverified`; reading the file is not source verification.

Imports use versioned matching rules and stable issue keys based on worksheet,
row, column, issue code and year. Each data import runs in one transaction.
Identical hashes with parser `university-xlsx-v1` reuse the existing snapshot,
preserving all rows and timestamps. Changed bytes produce a new snapshot;
a different parser version raises an error. Initialization precedes the data
transaction, so an empty schema may remain after failure but no partial data.

## Initialization and versioning

Use the repository's Python 3.12 environment. Runtime dependencies live in
`pyproject.toml`, tested pins in `requirements-api.lock`; the legacy
`requirements.txt` describes the proposed research stack. Schema handling uses
the standard library. Excel import adds `openpyxl>=3.1.5,<4`, pinned to 3.1.5
with `et_xmlfile==2.0.0` in the existing lockfile. No other dependencies changed.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-api.lock
python -m pip install -e . --no-deps
```

On POSIX systems, create the environment with `python3.12 -m venv .venv` and
activate it with `source .venv/bin/activate`, then use the same installation
commands. The existing lockfile is the project's pinned API/test environment;
this milestone only adds the Excel reader and its dependency.

From the repository root in PowerShell (or use the installed package):

```powershell
$env:PYTHONPATH = 'src'
python -c "from societytwin.university import initialize_database; initialize_database('data/processed/university/university.sqlite3')"
```

The Python API is `initialize_database(path: str | pathlib.Path) -> None`.
It creates parent directories and uses `BEGIN IMMEDIATE` for atomic schema and
version creation. Version 1 is stored in `PRAGMA user_version`, preserving exactly
six logical tables. Repeated initialization preserves data and validates the
schema definitions. Unsupported versions, nonempty unversioned databases,
missing tables and changed DDL raise `SchemaVersionError` without dropping or
repairing anything. No migrations are implemented yet. Formatting changes to
persisted DDL or added indexes also fail the exact definition check; schema
changes require an explicit versioned migration policy.

Use `societytwin.university.connect(path)` for subsequent access. It enables
foreign keys on every connection and returns `sqlite3.Row` results. Callers own
the connection, transactions and closing. A plain external `sqlite3.connect`
must explicitly set `PRAGMA foreign_keys=ON`; SQLite does not persist that setting.
Neither package import nor connection opening initializes tables automatically.
Choose a dedicated file, never the existing DST registry database.

Run the artificial temporary-database tests with:

```powershell
python -m pytest tests/university -q
```

All 75 university tests use artificial records and generate small Excel workbooks
in temporary directories. They run without the real workbook, populated database,
provider credentials or network access. The broader regression command below
also uses artificial fixtures. Source-data reconciliation requires a separately
authorized local workbook and is distinct from these automated tests.

## Import command and table mapping

The importer reads the file bytes once, hashes those bytes and parses them with
openpyxl in read-only mode. It never saves the workbook. Header validation accepts
the inspected program/annual column sets in any order and rejects missing,
unknown or duplicate headers. Formula cells are rejected rather than treating
missing cached results as missing source data. The actual workbook has no formulas.

From the repository root, with the package installed:

If authorized to use the dataset, place an unchanged local copy at
`data/raw/university/Universite_Bolum_Kontenjan_Yerlesen_Sira_Burs_Ucret.xlsx`,
creating the directory if needed. The workbook is not downloaded by this command.
Raw data, generated SQLite files, detailed JSON/Markdown audit reports, caches
and virtual environments are excluded from Git under the repository data policy.
The schema/importer, artificial tests and aggregate validation summary are shared;
teammates must obtain an authorized source copy separately. No populated database
is included in the repository.

```powershell
python -m societytwin.university.importer `
  --workbook data/raw/university/Universite_Bolum_Kontenjan_Yerlesen_Sira_Burs_Ucret.xlsx `
  --database data/processed/university/university.sqlite3 `
  --report data/processed/university/import-report.json
```

These paths are the defaults. The API is
`import_workbook(workbook_path, database_path) -> dict`. The CLI prints a compact
summary and writes a complete JSON report with every source-linked quality issue.
An existing report file is replaced; report paths matching the workbook or
database are rejected. Workbook, database and generated report are ignored by Git.

| Source | Destination and authority |
| --- | --- |
| `Programlar` | University/program identity, institution type, faculty, score type, scholarship, exact language and tuition. Wide annual fields cross-check the long sheet. |
| `Yıllık Uzun Format` | Annual admissions; university/name/scholarship and all measures must agree with `Programlar`. |
| `Üniversite Özeti` | Calculated program-count and annual-sum cross-check only; never an observations source. |
| `Açıklamalar` | Exact source notes and source-reported retrieval date in snapshot metadata. |

`source_snapshots.notes` stores deterministic JSON containing source notes, raw
row counts, per-program row references, original Sınav İzcisi URLs, other labels
and fee notes. The schema has no per-program URL/extra-label fields; JSON preserves
these without adding tables or columns. `source_reference` retains the workbook
path. No source URLs were visited.

Tuition uses explicit TL headers for TRY and Decimal arithmetic to multiply by
100. Each accepted program has a row for each fee year 2025 and 2026, including
NULL/NULL where no fee is supplied. Full and net fees are parsed independently;
no fees are inferred for state universities or missing years. The workbook notes
define net tuition as full fee multiplied by payment rate. Supplied net values
are retained as **source-derived**, marked in `fee_basis`, without recomputation.
Full fees may reflect the source's program/faculty/general fee matching; the
original caveat is preserved. These are source quotations, not verified invoices.

Numeric cells are parsed directly, so numeric `1234.56` is 123456 minor units.
Text supports Turkish grouping (`1.234`, `1.234.567,89`), decimal comma (`1234,56`)
and decimal dot with one/two following digits (`1234.56`). A dot before a group
of three digits means thousands. Unsupported formats, nonfinite numbers, Boolean
values, overflow, fractional integer measures and negatives are rejected. Ranks
must be positive integers. Empty cells stay NULL; explicit zeros stay zero.
Program codes must already be digit strings: numeric code cells are quarantined
instead of guessing leading zeros or display formats. All actual codes are text.

Identical duplicates collapse with quality issues. All rows for conflicting
program codes or annual keys are quarantined; there is no first-row winner.
Invalid measures, missing parents, identity mismatches and wide/long disagreements
produce issues containing original records. Wide observations missing from the
long sheet are reported but not synthesized. Placed counts above quota remain
unchanged and are flagged. Structural errors or unexpected failures roll back
the entire data import; row quarantine allows other valid records to import.

## Actual workbook validation

Original file SHA-256:

```text
03c4ac4216b1b2e97caa9699e3b25971f296f5864952e04f16ad64db91a8326d
```

| Measure | Result |
| --- | ---: |
| Universities / summary universities | 13 / 13 |
| Programs / source program rows | 1,282 / 1,282 |
| Admissions / source long-format rows | 8,715 / 8,715 |
| Tuition rows (all programs × 2 fee years) | 2,564 |
| Tuition rows with amounts | 1,736 |
| 2025 fee rows with amounts / missing both amounts | 856 / 426 |
| 2026 fee rows with amounts / missing both amounts | 880 / 402 |
| Missing teaching language | 764 |
| Missing success rankings among annual rows | 208 |
| Placed-above-quota warnings | 2,720 |
| Duplicates, conflicts, cross-sheet disagreements, quarantined rows | 0 |

Admissions by year: 2019: 785; 2020: 970; 2021: 1,051; 2022: 1,118;
2023: 1,162; 2024: 1,282; 2025: 1,223; 2026: 1,124.
All 8,715 populated wide program/year observations match the long sheet exactly.
University summary counts and totals agree. Missing fee slots explain the tuition
counts above; no amounts were invented. `PRAGMA integrity_check` returns `ok`,
and `PRAGMA foreign_key_check` returns no rows. The full issue audit is in
`data/processed/university/import-report.json` and `data_quality_issues`.

Source verification, academic-year fee boundaries and cross-snapshot university
matching remain unresolved. No schema migration was required.

The final run passed 75 university tests (23 schema and 52 importer/parameterized
checks) and 77 existing registry, population-reader and scenario checks: 152
passed. One existing Starlette test-client deprecation warning remains.
Every actual program, admission and tuition value was also compared back to its
source cell. Re-importing the actual file preserved an identical logical SQL
dump and one source snapshot. The original workbook hash remained unchanged.

```powershell
python -m pytest tests/university tests/unit/test_registry_jobs.py tests/unit/test_population_readers.py tests/test_scenarios tests/national/test_scenario_pipeline.py -q
```

## Query examples

```python
from contextlib import closing
from societytwin.university import connect

with closing(connect("data/processed/university/university.sqlite3")) as conn:
    snapshots = conn.execute(
        "SELECT snapshot_id, file_sha256, importer_version FROM source_snapshots"
    ).fetchall()
    snapshot_id = snapshots[0]["snapshot_id"]  # Select the desired snapshot explicitly.
    programs = conn.execute("""
        SELECT p.program_code, u.name_original AS university,
               p.name_original AS department, p.teaching_language,
               a.admission_year, a.quota, a.placed_students, a.success_rank
        FROM programs p
        JOIN universities u ON u.university_id = p.university_id
        JOIN annual_admissions a ON a.program_id = p.program_id
        WHERE p.snapshot_id = ? AND a.admission_year = ?
        ORDER BY p.program_code
    """, (snapshot_id, 2026)).fetchall()
    issues = conn.execute("""
        SELECT issue_code, source_sheet, source_row, related_year, message
        FROM data_quality_issues WHERE snapshot_id = ? ORDER BY issue_key
    """, (snapshot_id,)).fetchall()
```
