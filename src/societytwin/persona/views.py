"""Build persona views for one resident of one build."""

from __future__ import annotations

from pathlib import Path

from societytwin import FIXTURE_ATTRIBUTION_NOTE, SYNTHETIC_RESPONSE_LABEL
from societytwin.common import compare_recorded_digest, sha256_bytes
from societytwin.config import Settings
from societytwin.persona.static_constants import read_constants
from societytwin.population.categories import GENDER_FIELD_NOTE

PROMPT_IDENTITY_FIELD = "person_id"


def adapter_constants(settings: Settings) -> dict:
    consts = read_constants(settings.experiment_file(settings.layout.adapter_source))
    return {
        "marital_mapping": consts.get("MARITAL_MAPPING") if isinstance(consts.get("MARITAL_MAPPING"), dict) else None,
        "prompt_visible_allowlist": sorted(consts["PROMPT_VISIBLE_ALLOWLIST"]) if isinstance(consts.get("PROMPT_VISIBLE_ALLOWLIST"), (set, frozenset)) else None,
        "source_fields": list(consts["SOURCE_FIELDS"]) if isinstance(consts.get("SOURCE_FIELDS"), list) else None,
    }


def runner_constants(settings: Settings) -> dict:
    consts = read_constants(settings.experiment_file(settings.layout.ab_runner))
    keys = consts.get("KEYS") if isinstance(consts.get("KEYS"), dict) else None
    expected = consts.get("EXPECTED_IDS") if isinstance(consts.get("EXPECTED_IDS"), tuple) else None
    return {
        "expected_ids": list(expected) if expected else None,
        "provider_prefixes": sorted(keys) if keys else None,
        "provider_env": {k: list(v) for k, v in keys.items()} if keys else None,
    }


def _load_yaml(data: bytes):
    import yaml

    return yaml.safe_load(data.decode("utf-8"))


def persona_artifact_view(data: bytes, *, artifact_id: str, origin: str, relpath: str, row: dict | None,
                          csv_row: int | None, current_files: dict[str, bytes | None], catalog_bytes: bytes | None) -> dict:
    sha = sha256_bytes(data)
    base = {"persona_artifact_id": artifact_id, "origin": origin, "relpath": relpath, "sha256": sha}
    try:
        payload = _load_yaml(data)
    except Exception:  # noqa: BLE001 - any YAML error makes the artifact invalid, nothing is guessed
        return dict(base, valid=False, error="YAML could not be parsed")
    if not isinstance(payload, dict) or set(payload) != {"persona_id", "version", "source", "dimensions", "metadata"}:
        return dict(base, valid=False, error="Not a MatrAIx persona envelope (persona_id, version, source, dimensions, metadata)")
    dims = payload["dimensions"] if isinstance(payload["dimensions"], dict) else {}
    meta = payload["metadata"] if isinstance(payload["metadata"], dict) else {}
    provenance = meta.get("field_provenance") if isinstance(meta.get("field_provenance"), dict) else {}
    source_attributes = meta.get("source_attributes") if isinstance(meta.get("source_attributes"), dict) else {}

    visible_sources = {p.get("source_field") for k, p in provenance.items() if k in dims and isinstance(p, dict)}
    metadata_only = [f for f in source_attributes if f != PROMPT_IDENTITY_FIELD and f not in visible_sources]
    mapped = []
    for key in sorted(dims):
        prov = provenance.get(key) if isinstance(provenance.get(key), dict) else {}
        mapped.append({"dimension": key, "value": str(dims[key]), "source_field": prov.get("source_field"),
                       "source_value": None if prov.get("source_value") is None else str(prov.get("source_value")),
                       "source_type": prov.get("source_type"), "dataset": prov.get("dataset"), "method": prov.get("method")})

    warnings = []
    declared_visible = meta.get("prompt_visible_fields")
    if isinstance(declared_visible, list) and sorted(declared_visible) != sorted(dims):
        warnings.append("metadata.prompt_visible_fields differs from the actual dimensions; the dimensions are what the renderer uses.")
    if "marital_status" in metadata_only:
        warnings.append(f"Source marital status {source_attributes.get('marital_status')!r} has no catalog mapping and is not shown to the model.")
    if "age_bracket" not in dims and "age_group" in source_attributes:
        warnings.append("No catalog age bracket wholly contains the source age band; only dst_age_group carries age.")
    if "gender" in metadata_only:
        warnings.append("Source sex is kept in metadata only; it is not a prompt dimension.")

    hash_checks = []
    non_string = []

    def recorded(value, name):
        # YAML can parse an all-digit digest as a number; such a value cannot be compared reliably.
        if value is None or isinstance(value, str):
            return value
        non_string.append(name)
        return None

    recorded_source = recorded(meta.get("source_sha256"), "source_population")
    hash_checks.append({"name": "source_population", "path": meta.get("source_population"), "recorded_sha256": recorded_source,
                        "status": compare_recorded_digest(recorded_source, current_files.get("source_population"))})
    processed = meta.get("processed_sources") if isinstance(meta.get("processed_sources"), dict) else {}
    for name, entry in sorted(processed.items()):
        digest = recorded(entry.get("sha256") if isinstance(entry, dict) else None, f"processed:{name}")
        hash_checks.append({"name": f"processed:{name}", "path": entry.get("path") if isinstance(entry, dict) else None,
                            "recorded_sha256": digest, "status": compare_recorded_digest(digest, current_files.get(f"processed:{name}"))})
    catalog_digest = recorded(meta.get("catalog_sha256"), "persona_catalog")
    hash_checks.append({"name": "persona_catalog", "path": meta.get("catalog_path"), "recorded_sha256": catalog_digest,
                        "status": compare_recorded_digest(catalog_digest, catalog_bytes)})
    if non_string:
        warnings.append("Recorded digest(s) for " + ", ".join(non_string) + " are not strings in the YAML and cannot be compared.")
    if any(c["status"] == "line_ending_equivalent" for c in hash_checks):
        warnings.append("Some recorded digests match current files only after LF/CRLF conversion: explained line-ending drift, "
                        "not verified byte identity. Historical hashes are preserved unchanged.")

    row_check = None
    if row is not None:
        attrs_match = {k: str(v) for k, v in source_attributes.items()} == {k: str(v) for k, v in row.items()}
        row_match = meta.get("source_csv_row") == csv_row
        row_check = {"passed": attrs_match and row_match,
                     "detail": (f"Recorded CSV row {meta.get('source_csv_row')} and attributes match the current build row {csv_row}."
                                if attrs_match and row_match else
                                f"Recorded row {meta.get('source_csv_row')} / attributes differ from current row {csv_row}.")}
    return dict(
        base, valid=True, error=None,
        persona_id=payload.get("persona_id"), version=str(payload.get("version")), source=payload.get("source"),
        dimensions={k: str(v) for k, v in dims.items()},
        prompt_visible_fields=sorted(dims), metadata_only_fields=metadata_only,
        unassigned_fields=[str(x) for x in meta.get("unassigned_fields", [])] if isinstance(meta.get("unassigned_fields"), list) else [],
        mapped_fields=mapped,
        provenance_source_types=sorted({p.get("source_type") for p in provenance.values() if isinstance(p, dict) and p.get("source_type")}),
        metadata={k: meta.get(k) for k in ("source_population", "source_csv_row", "source_attributes", "reference_year", "province",
                                           "generation_seed", "seed_provenance", "catalog_path", "catalog_sha256")},
        hash_checks=hash_checks, source_row_check=row_check, mapping_warnings=warnings,
        attribution_note=FIXTURE_ATTRIBUTION_NOTE if origin == "fixture" else None,
    )


def fixture_persona_files(settings: Settings) -> list[Path]:
    directory = settings.experiment_file(settings.layout.personas_dir)
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.suffix in {".yaml", ".yml"} and p.is_file() and not p.is_symlink())


def fixture_persona_index(settings: Settings) -> dict[str, list[Path]]:
    """persona_id -> fixture files, read with safe_load (no framework import)."""
    index: dict[str, list[Path]] = {}
    for path in fixture_persona_files(settings):
        try:
            payload = _load_yaml(path.read_bytes())
        except Exception:  # noqa: BLE001
            continue
        if isinstance(payload, dict) and isinstance(payload.get("persona_id"), str):
            index.setdefault(payload["persona_id"], []).append(path)
    return index


def build_context_notes() -> dict:
    return {"gender_field": GENDER_FIELD_NOTE, "synthetic_label": SYNTHETIC_RESPONSE_LABEL}
