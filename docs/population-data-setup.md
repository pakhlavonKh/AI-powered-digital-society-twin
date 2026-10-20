# Ankara population data setup and portability

Reviewed 20 October 2026 for `feature/ankara-population-realism`. This guide records
the locally verified input contracts. It does not grant permission to redistribute
TÜİK observations or claim the official download endpoints were rechecked today.
Keep raw data and generated artifacts ignored. A code clone alone is insufficient
for all optional real-data builds.

## Environment and locations

Use the feature checkout, Python 3.12 and `requirements-api.lock`. The tested Windows
environment used Python 3.12.10; the lock header describes a different tested host.
Standalone wheel installation without the repository `data/` metadata is unsupported.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-api.lock
.\.venv\Scripts\python -m pip install -e . --no-deps
$env:PYTHONPATH = 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
```

Commands below assume `python` is that interpreter; alternatively replace it with
`.\.venv\Scripts\python`. Do not commit `.venv-persona/`, the local validation
environment, or any other virtual environment. Existing environments need not be moved.

## Input inventory

| Input | Purpose / required option | Git and acquisition status |
|---|---|---|
| `experiments/matraix_simulation/processed/ankara_*.csv` | Historical Ankara controls; fallback default coverage | Existing tracked fixtures; original downloads absent; limited attributes |
| `data/raw/tuik_package/` | Province age/sex, marital, education, settlement controls and context | Ignored here; 71 files in separate team `data-turkey` history; copy-only, never merge raw-data branch |
| `data/raw/ankara_household_size_2025.csv` | Size-only and type × size households | Ignored official-table transcription; checksum pinned in household registry |
| `data/raw/national_marital_seed_2025.yaml` | Optional broad-age marital strategy | Ignored publication transcription; checksum pinned in dependency registry and data manifest |
| `data/raw/national_household_type_size_2025.csv` | National joint seed for type × size households | Ignored table transcription, including nested validation rows |
| `data/raw/ankara_household_type_2025_source.csv` | Ankara type margins for type × size households | Ignored portal extract; historical years retained, only 2025 selected |
| `data/raw/ankara_degurba_sex_2025.csv` | Optional resident sidecar | Ignored deterministic six-cell derivative of the package |
| `data/processed/national/` | Normalized controls read by unified builds | Locally generated and ignored; default destination must first be populated |
| `data/*registry.yaml`, `data/build_configs/*.yaml` | Metadata, contracts and opt-in configuration | Code-publication candidates; several are currently untracked, so must be included in a later reviewed commit |
| `ext-...`, `pop-...`, `hh-...`, `hht-...`, `build-...` artifacts | Residents, sidecars and separate households | Locally generated and ignored; not delivered by GitHub |

All five raw feature-input files are available and pass their actual checksum/schema
loaders on this machine. This does not mean a fresh clone contains them.

## Team package: a pinned local source

The verified package commit is `683c85180834189c3d357bfb15e078b9dfa58454`, directory
`tuik_province_data`, Git tree `a5240bab58989398a7e0ecbf375cb4c5b83fb19c`.
All 71 local files were compared byte-for-byte with that commit during Prompt 6.
The catalog, variable metadata, coverage files and README accompany 33 long and
33 wide CSVs. Official source URLs and identifiers are recorded in `data/manifest.yaml`,
`data/tuik_package_mapping.yaml` and the package catalog. The Git branch is a team
distribution mechanism, not the statistical authority or proof of redistribution rights.

After confirming that your team access/use is permitted, obtain that exact commit
through the approved team repository. These commands are a future setup procedure;
the readiness review did not fetch or publish anything:

```powershell
git fetch origin data-turkey
git cat-file -e 683c85180834189c3d357bfb15e078b9dfa58454
if (Test-Path -LiteralPath 'data/raw/tuik_package') { throw 'Use a new checkout or review the existing input; do not overwrite it.' }
New-Item -ItemType Directory -Path data/raw/tuik_package | Out-Null
New-Item -ItemType Directory -Force -Path data/results/package-setup | Out-Null
git archive --format=tar -o data/results/package-setup/package.tar 683c85180834189c3d357bfb15e078b9dfa58454 tuik_province_data
tar -x -f data/results/package-setup/package.tar -C data/raw/tuik_package --strip-components=1
(Get-ChildItem data/raw/tuik_package -File | Measure-Object).Count # 71
```

Use a fresh archive filename if this setup was run before. Keep the archive ignored.
Do not change file encodings or line endings. Verify file hashes against the pinned
Git objects/catalog before building; compare package-wide audit and source checksums
in the generated control manifest. A newer `data-turkey` commit is a source revision
requiring review, not an automatic substitute.

## Required feature inputs: authority, hashes and acquisition

The following SHA-256 values refer to the normalized local input bytes, **not**
to the official webpage or downloaded PDF. All have a final newline. Size, marital
and DEGURBA inputs use UTF-8 without BOM; the two household-type CSVs retain the
acquired UTF-8 BOM. Check the byte-format details below before investigating a hash mismatch.

| Input | SHA-256 | Authority / contract |
|---|---|---|
| Household size | `1aed9e3fb1b65ab6ab4a880247b5b4b662cd980b6dfee5cedd3d904dedc2471b` | [TÜİK NIP household size](https://nip.tuik.gov.tr/?value=HanehalkiBuyukluguneGoreHs), Ankara 2025; `data/household_registry.yaml` |
| Marital seed | `55dbc9752f4e19617cd9803dced10811a1efdb7e0cdcc906adac878141fb796d` | TÜİK *Youth in Statistics 2025*, publication 4821, table 1.9, printed p14 / PDF p36; full official publication URL in `data/manifest.yaml` and `data/dependency_registry.yaml` |
| National household joint | `649901d6122c1d5bba92e5209946c3d33c65cd9e1bb46baf3b1dcd16c6f6472b` | TÜİK *Women in Statistics 2025*, table 1.4, printed p4 / PDF p28; official download URL in `data/household_type_size_registry.yaml` |
| Ankara household types | `d2d4e0b67e3670d7a26293c004b346b6c759024b2876aebbf651cb8baa66fd93` | [TÜİK NIP household types](https://nip.tuik.gov.tr/?value=HanehalkiTipi), Ankara 2025; same registry |
| DEGURBA derivative | `10e3181955fb52ddbf797f8b497b535bde308951647f9d31e1f30a45e260e8f0` | [TÜİK DF_ADNKS_T37, version 1.1](https://veriportali.tuik.gov.tr/en/databrowser/tuik/TR%2CDF_ADNKS_T37%2C1.1), Ankara sex × class 2025; `data/resident_extension_registry.yaml` |

### Household size

Open the NIP table, choose **Tablo → Düzey Seçiniz: İl → ANKARA**, then the 2025
row. Transcribe classes `1` through `9`, `10+` in order; strip thousands separators,
retain integer household counts and do not infer members. Header:
`province_code,reference_year,household_size_class,households`. Use `06`, `2025`,
CRLF line endings. Validate ten classes and total 1,987,216 households, then checksum.
The detailed acquisition history remains in the handover and local Phase 2A report.

### National marital percentages

Inspect the specified official publication table. Transcribe the four sex × broad-age
rows, category order `never_married, married, divorced, widowed`, into the full
`MaritalEvidence` contract in `national/marital.py`: publication metadata, source/version,
reference geography/year, percentages/unit, precision, denominator, source/methodology
URLs, acquisition/reuse limitations and rows. Preserve LF line endings, one-decimal
published precision, and `rounding_rule_confirmed: false`. Printed zeros do not become
structural zeros or exact probabilities. The executable sensitivity scenario is selected
in build configuration, never written back as a source observation.

The exact YAML serialization includes comments and metadata. Merely emitting equivalent
YAML with `safe_dump` will not reproduce its byte checksum. The original PDF binary was
not archived and earlier download attempts returned 403; a response body from a failed
download is not evidence. Reacquire the publication legitimately and review its contents.

### Household type × size

From the specified *Women in Statistics* table, create the CSV header
`year,geography,household_type,household_size,households,value_status,source_table`.
Preserve the four broad types plus the five nested validation types expected by
`households/type_size_evidence.py`, seven classes `1`–`6`,`7+`, 63 cells, semantic
`NOT_APPLICABLE` cells with empty counts, source-table label, 2025/TR, UTF-8 BOM and CRLF endings.
Do not replace missing observations with zero or add parent and child rows together.

For Ankara types, select the NIP **İl / ANKARA** table and export/transcribe the original
year rows with header `year,province_code,household_type,households`. Preserve the
acquired historical-row ordering, UTF-8 BOM and CRLF endings; 2025 alone is selected by the loader.
Four disjoint type counts must sum to the same private-household total as the size input.
Source extraction endpoints and provenance were archived locally under Phase 2A;
they are not required runtime inputs and are not shipped with the code.

**Portability gate for these transcriptions:** this repository does not contain a
byte-exact, independently regenerating acquisition/serialization utility for all three
transcribed sources (marital, national household joint, Ankara household types).
Rows, labels, comments and historical ordering affect their pinned hashes. The steps
above specify source and schema, but do not establish byte-exact regeneration from a
new publication download. Obtain an authorized exact copy through an approved private
handoff, or implement/review a deterministic acquisition utility and a versioned source
revision after official verification. Do not relax checksum checks or edit registry
pins to accept arbitrary equivalent-looking files. Full fresh-clone optional-data
portability remains blocked until this is resolved. No data copy is supplied here.

### DEGURBA: deterministic derivation from the package

First verify `population_urban_rural.csv` SHA-256:
`7f223faf84c77bf91842f0903618528218967dffe4db3ac928ec073f86e5f6c1`.
Filter province `06`, year `2025`, unit `person`, the six indicators
`pop_degurba_{dense_urban,intermediate_urban,rural}_{male,female}`; each must occur
exactly once with an observed integer value. Do not include total-sex indicators.
Write `province_code,year,sex,category,count,value_status`, sex order male then female,
category order dense_urban, intermediate_urban, rural, and `OBSERVED` status. Use CRLF
endings, integer counts, no BOM and a final newline. Verify the pinned derivative hash.
This is a source normalization procedure, not a statistical algorithm change.

The following serializer was independently executed into a new private output and
reproduced the existing 314-byte derivative and its registry hash exactly. For future
setup it refuses an existing destination:

```powershell
@'
import csv, hashlib, io
from decimal import Decimal
from pathlib import Path
source = Path('data/raw/tuik_package/population_urban_rural.csv')
assert hashlib.sha256(source.read_bytes()).hexdigest() == '7f223faf84c77bf91842f0903618528218967dffe4db3ac928ec073f86e5f6c1'
with source.open(encoding='utf-8-sig', newline='') as f:
    rows = [r for r in csv.DictReader(f) if r['province_code'] == '06' and r['year'] == '2025']
output = io.StringIO(newline='')
writer = csv.writer(output, lineterminator='\r\n')
writer.writerow(['province_code', 'year', 'sex', 'category', 'count', 'value_status'])
for sex in ('male', 'female'):
    for category in ('dense_urban', 'intermediate_urban', 'rural'):
        cells = [r for r in rows if r['indicator'] == f'pop_degurba_{category}_{sex}']
        assert len(cells) == 1 and cells[0]['unit'] == 'person'
        value = Decimal(cells[0]['value'])
        assert value.is_finite() and value >= 0 and value == value.to_integral_value()
        writer.writerow(['06', '2025', sex, category, str(int(value)), 'OBSERVED'])
raw = output.getvalue().encode('utf-8')
assert hashlib.sha256(raw).hexdigest() == '10e3181955fb52ddbf797f8b497b535bde308951647f9d31e1f30a45e260e8f0'
with Path('data/raw/ankara_degurba_sex_2025.csv').open('xb') as f:
    f.write(raw)
'@ | python -B -
```

## Verify sources before generating

Use `Get-FileHash <path> -Algorithm SHA256` for each of the five files and compare with
the actual registry pins, then run the real readers (all read-only):

```powershell
@'
from pathlib import Path
from societytwin.national.dependencies import load_registry as deps
from societytwin.national.marital import load_evidence as marital
from societytwin.households.registry import load_registry as households
from societytwin.households.evidence import load_evidence as sizes
from societytwin.households.type_size_registry import load_type_size_registry
from societytwin.households.type_size_evidence import load_type_size_evidence
from societytwin.enrichment.registry import load_registry as extensions
from societytwin.enrichment.evidence import load_evidence as extension_evidence
root = Path.cwd()
base = households()
evidence = sizes(base, root)
load_type_size_evidence(load_type_size_registry(), base, evidence, root)
marital(deps().marital_strategy)
extension_evidence(extensions().attributes['degurba_class'], root)
print('All five source contracts passed')
'@ | python -B -
```

These calls were verified in Prompt 6. A missing source or checksum/schema mismatch
must fail. No optional feature is activated by installing a raw input.

## Build controls and unified artifacts

On Windows, the existing `python -m societytwin.national` CLI fails before parsing
arguments because it imports Unix-only `resource`. The same failure is present in
the original `ui_design` worktree. Do not describe that CLI as verified on Windows.
Its cross-platform repair is a separate task. The existing source functions provide
a verified Windows-compatible setup path without changing generator algorithms:

```powershell
@'
from pathlib import Path
from societytwin.config import load_settings
from societytwin.national.sources import build_controls
from societytwin.national.controls import write_store, read_store
target = Path('data/processed/national')
if target.exists() and any(target.iterdir()):
    raise RuntimeError('Select a fresh control directory; do not overwrite existing controls')
store, adapters = build_controls(load_settings())
write_store(target, store)
read_store(target)
print('Control store built and verified')
'@ | python -B -
python -B -m societytwin.build run --config data/build_configs/ankara-core.yaml
python -B -m societytwin.build run --config data/build_configs/ankara-optional.yaml
python -B -m societytwin.build inspect data/results/unified-populations/<build-id>
```

The function path was executed into a **new private** Prompt 6 control directory;
the normal `data/processed/national` directory was not overwritten. The two example
YAMLs parse successfully, but actual builds require their selected input files.
Unified/household/enrichment CLI help and unified CLI execution are covered by tests.
Prompt 5 already verified 64 full builds; those research outputs were not regenerated
or overwritten for this handover.

## Optional persona selection and sharing policy

Default persona output needs no DEGURBA sidecar. Explicit selection uses
`FieldSelection` and `PersonaResolver` in Python, or the current shared experiment
model's `persona.field_selection`. Resolve an existing sidecar against the exact
resident artifact; supply its `sidecar_root` and `sidecar_id` together. Those paths
are local and must be relocated on another machine; an ID alone does not download
the sidecar. Do not load household artifacts as person attributes.

Public experiment-schema exposure requires the API/snapshot review described in
`CURRENT_SYSTEM_HANDOVER.md`; do not regenerate the frontend contract automatically.
External MatrAIx integration still needs a separately configured checkout/interpreter.
No paid calls are needed to build, verify, sample or export these artifacts.

All source reuse/redistribution permissions above remain **OPEN DECISION** in the
project records. Downloadability or existing presence on `data-turkey` does not settle
permission. Koray owns acquisition provenance and checksums; Bejan approves statistical
contracts; Pakhlavon verifies setup in integration. Publish metadata and code only.
