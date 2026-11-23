#!/usr/bin/env bash
# Reference Data Provisioning Shell Script for SocietyTwin Data & Validation Engine.
#
# Provisions TUIK province source data from `tuik_province_data/` into `data/raw/tuik_package/`,
# verifies cryptographic SHA-256 integrity against the Evidence Registry (K1) (failing loudly on mismatch),
# builds the normalized versioned reference package (K2), and reconstructs/verifies the reviewed
# K3 validation report artifact (`ankara_1000_validation_report_k3.json`) against the reviewed
# fingerprints in `docs/ankara_1000_validation_report_k3.md`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_DIR=""
TARGET_DIR=""
SKIP_BUILD=0
SKIP_GOLDEN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)
            SOURCE_DIR="$2"
            shift 2
            ;;
        --target)
            TARGET_DIR="$2"
            shift 2
            ;;
        --repo-root)
            REPO_ROOT="$2"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD=1
            shift
            ;;
        --skip-golden)
            SKIP_GOLDEN=1
            shift
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "${SOURCE_DIR}" ]]; then
    for candidate in \
        "${REPO_ROOT}/tuik_province_data" \
        "${REPO_ROOT}/data/tuik_province_data" \
        "${REPO_ROOT}/../repo_clone_9b8e227/tuik_province_data" \
        "${REPO_ROOT}/../AI-powered-digital-society-twin/tuik_province_data" \
        "${REPO_ROOT}/../main/tuik_province_data" \
        "${REPO_ROOT}/../tuik_province_data"; do
        if [[ -d "${candidate}" && -f "${candidate}/population_by_age_sex.csv" ]]; then
            SOURCE_DIR="$(cd "${candidate}" && pwd)"
            break
        fi
    done
fi

if [[ -z "${SOURCE_DIR}" || ! -d "${SOURCE_DIR}" ]]; then
    echo "ERROR: Source directory does not exist or could not be found." >&2
    exit 1
fi

if [[ -z "${TARGET_DIR}" ]]; then
    TARGET_DIR="${REPO_ROOT}/data/raw/tuik_package"
fi

mkdir -p "${TARGET_DIR}"

echo "INFO: Source directory: ${SOURCE_DIR}"
echo "INFO: Target directory: ${TARGET_DIR}"

# 1. Copy all source CSV/metadata files to target directory
FILE_COUNT=0
for src_file in "${SOURCE_DIR}"/*; do
    if [[ -f "${src_file}" ]]; then
        cp -p "${src_file}" "${TARGET_DIR}/"
        FILE_COUNT=$((FILE_COUNT + 1))
    fi
done
echo "INFO: Transferred ${FILE_COUNT} files to ${TARGET_DIR}"

# 2. Verify ankara_district_population_and_growth.csv exists
DISTRICT_FILE="${TARGET_DIR}/ankara_district_population_and_growth.csv"
if [[ ! -f "${DISTRICT_FILE}" ]]; then
    echo "ERROR: ankara_district_population_and_growth.csv missing in ${TARGET_DIR}!" >&2
    exit 1
fi

# Locate Python interpreter
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
    for py_cand in \
        "${REPO_ROOT}/.venv/Scripts/python.exe" \
        "${REPO_ROOT}/.venv/bin/python" \
        "${REPO_ROOT}/../main/.venv/Scripts/python.exe" \
        "${REPO_ROOT}/../.venv/Scripts/python.exe" \
        "$(command -v python3 2>/dev/null || true)" \
        "$(command -v python 2>/dev/null || true)"; do
        if [[ -n "${py_cand}" && -x "${py_cand}" ]]; then
            if "${py_cand}" -c "import yaml, pydantic" >/dev/null 2>&1; then
                PYTHON_BIN="${py_cand}"
                break
            fi
        fi
    done
fi

if [[ -z "${PYTHON_BIN}" ]]; then
    echo "ERROR: Could not find a Python interpreter with required packages (pyyaml, pydantic)." >&2
    exit 1
fi

export PYTHONPATH="${REPO_ROOT}/src:${PYTHONPATH:-}"

# 3. Verify SHA-256 digests against EvidenceRegistry (K1), build K2 reference package, and reconstruct K3 golden report
"${PYTHON_BIN}" - "${REPO_ROOT}" "${TARGET_DIR}" "${SKIP_BUILD}" "${SKIP_GOLDEN}" <<'PYEOF'
import json
import sys
from pathlib import Path

from societytwin.common import sha256_bytes
from societytwin.evidence import build_reference_package, load_evidence_registry
from societytwin.validation.population import (
    generate_ankara_sample_population,
    load_reference_bundle,
    validate_population,
)

repo_root = Path(sys.argv[1]).resolve()
target_dir = Path(sys.argv[2]).resolve()
skip_build = sys.argv[3] == "1"
skip_golden = sys.argv[4] == "1"

reg = load_evidence_registry()


def ensure_exact_line_endings(file_path: Path, expected_sha256: str, label: str) -> str:
    raw = file_path.read_bytes()
    actual_sha = sha256_bytes(raw)
    if actual_sha == expected_sha256:
        return actual_sha
    lf_bytes = raw.replace(b"\r\n", b"\n")
    if sha256_bytes(lf_bytes) == expected_sha256:
        file_path.write_bytes(lf_bytes)
        print(f"INFO: Restored LF line endings for {label} ({expected_sha256[:12]})")
        return expected_sha256
    crlf_bytes = lf_bytes.replace(b"\n", b"\r\n")
    if sha256_bytes(crlf_bytes) == expected_sha256:
        file_path.write_bytes(crlf_bytes)
        print(f"INFO: Restored CRLF line endings for {label} ({expected_sha256[:12]})")
        return expected_sha256
    raise ValueError(
        f"SHA-256 mismatch for {label} ({file_path.name}): "
        f"expected {expected_sha256}, got {actual_sha}"
    )


print("INFO: Verifying SHA-256 digests against Evidence Registry...")
for entry in reg.datasets.values():
    if entry.retrieval_info.storage_root == "tuik_package_dir":
        dest_file = target_dir / entry.retrieval_info.relative_path
        if not dest_file.is_file():
            raise FileNotFoundError(
                f"Required dataset file {entry.retrieval_info.relative_path} missing in {target_dir}"
            )
        verified_sha = ensure_exact_line_endings(dest_file, entry.sha256, entry.dataset_id)
        print(f"INFO: Verified {entry.dataset_id}: exact match ({verified_sha[:12]})")
    elif entry.retrieval_info.storage_root == "repo_root" and not entry.retrieval_info.optional_local_file:
        repo_file = repo_root / entry.retrieval_info.relative_path
        if repo_file.is_file():
            verified_sha = ensure_exact_line_endings(repo_file, entry.sha256, entry.dataset_id)
            print(f"INFO: Verified {entry.dataset_id}: exact match ({verified_sha[:12]})")

ankara_district_entry = reg.get("ankara_district_population_2025")
ankara_district_path = target_dir / ankara_district_entry.retrieval_info.relative_path
ensure_exact_line_endings(ankara_district_path, ankara_district_entry.sha256, "ankara_district_population_2025")
print("INFO: Verified: ankara_district_population_and_growth.csv matches ankara_district_population_2025.")

ref_pkg_dir = repo_root / "data" / "reference_package_k2_v1"
if not skip_build:
    print(f"INFO: Building reference package into {ref_pkg_dir}...")
    manifest = build_reference_package(
        ref_pkg_dir,
        registry=reg,
        repo_root=repo_root,
        tuik_package_dir=target_dir,
    )
    print(
        f"INFO: Reference package build complete: {manifest['tables_built_count']} tables built, "
        f"{manifest['optional_local_skipped_count']} optional skipped (total registered={len(reg.datasets)}). "
        f"Fingerprint: {manifest['package_fingerprint'][:16]}"
    )

if not skip_golden and ref_pkg_dir.is_dir():
    print("INFO: Reconstructing and verifying reviewed golden validation report (K3)...")
    bundle, _, _, _ = load_reference_bundle(ref_pkg_dir)
    sample_pop = generate_ankara_sample_population(
        synthetic_size=1000,
        seed=42,
        calibrate=True,
        reference_bundle=bundle,
    )
    k3_report = validate_population(sample_pop, bundle)

    expected_pop_id = "pop-06-2025-n1000-s42-e6a8e87e"
    expected_pkg_fp_prefix = "fa0971ff615e7914"
    if k3_report.population_id != expected_pop_id:
        raise ValueError(
            f"Reconstructed K3 report population_id {k3_report.population_id!r} does not match "
            f"reviewed population_id {expected_pop_id!r}"
        )
    if not k3_report.reference_package_fingerprint.startswith(expected_pkg_fp_prefix):
        raise ValueError(
            f"Reconstructed K3 report reference_package_fingerprint {k3_report.reference_package_fingerprint!r} "
            f"does not start with reviewed prefix {expected_pkg_fp_prefix!r}"
        )
    if k3_report.status_counts != {"pass": 5, "fail": 0, "not_evaluable": 3}:
        raise ValueError(
            f"Reconstructed K3 report status_counts {k3_report.status_counts} do not match "
            "reviewed expected counts {'pass': 5, 'fail': 0, 'not_evaluable': 3}"
        )

    json_path = ref_pkg_dir / "ankara_1000_validation_report_k3.json"
    md_path = repo_root / "docs" / "ankara_1000_validation_report_k3.md"
    if md_path.is_file():
        committed_md = md_path.read_text(encoding="utf-8").strip()
        generated_md = k3_report.to_markdown().strip()
        if committed_md != generated_md:
            raise ValueError(
                "Reconstructed K3 report Markdown does not match reviewed docs/ankara_1000_validation_report_k3.md"
            )

    json_path.write_text(
        json.dumps(k3_report.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"INFO: Verified and wrote golden K3 report to {json_path}")
PYEOF

echo "INFO: Reference data provisioning completed successfully!"
