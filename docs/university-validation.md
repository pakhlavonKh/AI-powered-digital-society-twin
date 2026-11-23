# University Database — Milestone 1 validation

Milestone 1 supplies an isolated SQLite schema, explicit initialization, a
transactional Excel importer and artificial tests. It does not implement student
agents, a preference model or a placement engine. Reproduction and local import
instructions are in [university.md](university.md).

## Coverage and evidence

The local audit examined the supplied university workbook's `Programlar`,
`Yıllık Uzun Format`, `Üniversite Özeti` and `Açıklamalar` sheets. It compared the
populated database against the unchanged source and inspected the importer,
persisted schema and source metadata. The source describes a selected set of
13 Ankara institutions, with admissions labelled 2019–2026 and fees labelled
2025 and 2026. This is not a national applicant or preference dataset.

The detailed audit remains local at
`data/processed/university/validation-report.md`; it contains source-linked
examples and analysis artifacts unsuitable for automatic publication. This
document publishes aggregate findings and research limitations, without source
records, institution/program examples, machine paths or generated database files.
No source websites were scraped or externally verified.

| Verified measure | Result |
| --- | ---: |
| Universities | 13 (3 state, 10 foundation) |
| Programs / distinct text program codes | 1,282 |
| Annual admissions | 8,715 |
| Tuition slots | 2,564 (every program × two fee years) |
| Tuition slots with amounts | 1,736 |
| Source snapshots | 1 |
| Import quality warnings | 2,720 |
| Excel-to-SQLite mismatches | 0 |
| Duplicate identities, orphan records, cross-snapshot violations | 0 |

## Verification methodology and results

The independent audit opened production SQLite using URI `mode=ro`, query-only
access and a read transaction. It read Excel with existing openpyxl in read-only
mode and did not call the production initializer or importer against the existing
database. Workbook, database and import-report hashes were unchanged after audit.

Full comparison covered every program's university assignment, faculty and
department names, score type, scholarship and exact language; every annual quota,
placed count and ranking; and both full/net fee fields in every fee-year slot.
Only documented empty-cell-to-NULL and TL-to-minor-unit transformations were
applied. The audit also compared provenance rows, stored source URLs/notes, all
populated wide annual fields and calculated university summaries. This was not
a sample. All 8,715 populated wide-sheet annual keys matched the long sheet.

`PRAGMA integrity_check` returned `ok`; `PRAGMA foreign_key_check` returned no
rows. The unique snapshot hash, snapshot-scoped program codes and annual keys,
and composite parent/snapshot foreign keys support repeatable imports without
overwriting earlier snapshots. Thirteen invalid constraint probes were rejected
on an in-memory copy; production records were never mutated.

The selected test suite passed **152 tests**: 23 schema tests, 52 importer and
parameterized checks, and 77 existing registry, population-reader and Scenario
Engine checks. One pre-existing Starlette test-client deprecation warning remains.
Tests generate artificial Excel fixtures and temporary databases, including
idempotence, revision retention, rollback, conflict quarantine, numeric parsing
and exact language preservation. They need no real dataset or provider calls.
See the regression command in [university.md](university.md).

Engineering validation establishes fidelity to this workbook. It does **not**
verify the underlying sources, official capacity, real behavior or tuition terms.

## Missing data and source preservation

| Missingness | Finding and permitted interpretation |
| --- | --- |
| Teaching language | 764 genuinely empty source cells become SQL NULL; 518 labels remain exact. NULL means unspecified, never presumed Turkish. |
| Annual coverage | 1,541 absent program/year rows in the fixed 1,282 × 8 catalogue grid. Opening/closure or inactivity cannot be inferred. |
| Quota / placed counts | No NULL fields within the 8,715 stored annual rows; absent rows remain missing observations, not zeros. |
| Success ranks | 208 NULLs: 95 coincide with zero placements; 113 accompany positive placements, all in 2026. The latter blanks have unknown causes. |
| Tuition | 828 slots have both fees NULL: 800 state-program slots and 28 foundation-program slots. No fee-year slots are missing for catalogue programs. |

The workbook explicitly omits state-university fees and labels those programs
`Devlet (Ücretsiz)`. This source convention is not proof of zero all-in costs
for every student category. Among foundation blanks, 26 in 2025 have annual
admissions and 2 in 2026 lack annual admissions; causes remain unknown. Co-absence
does not establish inactivity. There are no historical fees for 2019–2024.

Explicit language labels are preserved without translation, case normalization
or title-based inference. The actual workbook contains no explicit `Türkçe`
labels; synthetic tests verify support for that label. Missing ranks must not be
filled with zero or a previous year's rank. Known zero tuition remains distinct
from unavailable tuition.

## Placed counts above quota

All **2,720 warnings** correspond exactly to source rows where placed students
exceed the displayed quota: 31.21% of annual rows. The median positive excess is
2, the maximum 100. Across all years, excesses occur in 69.56% of state-university
rows and 12.24% of foundation-university rows.

Patterns change substantially: 2019–2024 has 2,510/6,368 cases (39.42%), compared
with 210/2,347 (8.95%) in 2025–2026. Every excess in the latter period occurs at
a state institution; foundation rows have zero excesses in both years.

The notes define placed counts as annual totals but do not establish whether
displayed quotas and placed totals share category boundaries, revisions or
allocation rounds. Additional quota categories, aggregation differences or
reporting changes are hypotheses, not documented explanations for every case.
The warnings therefore remain open.

Quotas must be described as **reported quota indicators**, not verified official
placement capacities. Preserve source counts and allow descriptive occupancy
ratios above 100%. Exact placement replay requires dated category-complete
capacity definitions and allocation rules; do not infer hidden capacity from
realized placements or clamp historical counts.

## Tuition interpretation

All known source fees are native Excel integers, with grouping used only for
display. Every SQLite amount equals the original TL value multiplied by 100;
currency is TRY. No negative fees, noninteger minor units or net-above-full cases
were found. Artificial tests additionally exercise Turkish-formatted text amounts.

All 1,736 known full/net pairs match the source-described scholarship arithmetic.
Net fees were calculated upstream; the importer retains and labels them as
source-derived rather than recomputing them or treating them as independent
observations. Arithmetic agreement does not verify the source's fee matching.

The audit identified **six explicitly English-language medicine/pharmacy rows**
where numeric full fees differ from amounts named in attached English-program
notes. Six more rows with NULL language carry the same notes, with applicability
unknown. These are unresolved source-internal interpretation tensions, not
import mismatches. Neither amount was selected as authoritative or corrected.

The notes call tuition annual, but the 2025/2026 fee labels do not establish
calendar-year versus academic-year or entry-cohort boundaries. The schema's
`academic_year_start` name does not resolve that ambiguity; row metadata marks
boundaries unverified. Additional pilot-training charges are explicitly mentioned
without complete amounts. Tax inclusion, payment conditions, scholarship
continuation/eligibility, preparation-year coverage and living costs are not
fully specified. Scholarship category alone cannot represent actual student cost.

## Historical leakage precautions

The workbook reports source retrieval in 2026, not contemporaneous 2025 field
availability. Current program characteristics are a static snapshot; they are not
a proven historical catalogue. A year label does not establish publication time.

For a 2025 preference simulation:

- Establish the explicit decision date and dated offering catalogue. Require
  publication/effective-date evidence for quotas, fees and characteristics.
- Previous-year rankings are potentially candidate-visible only after their
  availability is established; preserve score-type and year distinctions.
- Final 2025 placed counts, rankings and occupancy are outcomes for evaluation,
  never pre-placement candidate inputs. Exclude 2026 information from inputs,
  prompts, preprocessing and model selection for the 2025 experiment.
- Freeze source/snapshot/parser/code identities, inclusion rules, missingness
  policies and chronological splits. A proposed aggregate prediction split is
  training targets 2020–2022, validation 2023 and locked test 2024, with lagged
  inputs, followed by a separately frozen 2025 retrospective evaluation.
- Do not call the retrospectively assembled data a prospective study. The split
  cannot validate individual preferences without separate behavioral evidence.
- Label synthetic candidates and LLM decisions as synthetic. LLM pretraining can
  introduce hindsight even when prompts omit later outcomes; control and audit
  model versions, evidence access, prompts and experimental records.

Unknown publication dates remain unresolved rather than automatically eligible.
These precautions are requirements for later work, not implemented new features.

## Readiness for future modules

| Module | Readiness | Main condition / missing evidence |
| --- | --- | --- |
| University Program Registry | READY for descriptive snapshot browsing | Preserve unknowns and provenance; a historical 2025 offering catalogue remains PARTIAL. |
| Education Cost Engine | PARTIAL | Resolve note/amount tensions, fee dates/cohorts, extra costs and scholarship conditions. |
| Candidate Population Engine | BLOCKED | No individual candidates, score/rank distributions, budgets, demographics or validated joint structure. |
| Statistical Preference Model | BLOCKED for empirical calibration | No observed preference lists, choice sets or representative behavioral observations. |
| MatrAIx/LLM student agents | PARTIAL for explicitly synthetic experiments | Need candidate profiles, a dated information set, controlled protocol and human benchmarks. |
| Placement Engine | BLOCKED for exact replay | Need category-complete capacities, candidate priorities/preferences, eligibility, tie and round rules. |
| Scenario Engine | PARTIAL for descriptive scenario design | Counterfactual responses and causal effects are not identified by year-to-year aggregates. |
| Scientific validation | PARTIAL; engineering checks READY | Need independent source/temporal confirmation, behavioral ground truth and appropriate generalization claims. |

## Unresolved research requirements

**P0 scientific-use gates:** establish a decision-time evidence contract before
claiming historical 2025 fidelity; obtain candidate/preference evidence before
empirical behavioral claims; verify capacities and allocation rules before exact
placement claims. No P0 database-corruption or import-fidelity defect was found.

**P1:** investigate the quota-pattern break; resolve the six explicit-language
fee tensions and six applicability cases; clarify fee-year and cost semantics;
retain unknown-language/ranking/tuition and absent-row missingness; verify source
publication history and catalogue scope. Static catalogue selection, repeated
program-years and score-type differences limit generalization and stationarity.

Milestone verdict: **CONDITIONAL GO** for a descriptive registry and preparation
of the research evidence contract. It is **NO-GO** for validated preference,
complete affordability, causal scenario or exact official-placement claims until
the relevant evidence gaps are resolved or the work is explicitly scoped as a
hypothetical experiment. Publication shares engineering work and its limitations;
it does not resolve these research requirements or start the next implementation.
