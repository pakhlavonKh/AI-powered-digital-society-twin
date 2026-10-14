"""Deterministically adapt one existing resident; never synthesize missing attributes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "synthetic" / "ankara_population_1000_v2.csv"
DEFAULT_OUTPUT = ROOT / "personas" / "test_persona.yaml"
DEFAULT_MATRAIX = Path(os.environ.get("MATRAIX_ROOT", ROOT.parents[2] / "MatrAIx-Persona-8B")).expanduser()
SOURCE_FIELDS = ["person_id", "age_group", "gender", "marital_status", "marital_status_conditioning"]
PROMPT_VISIBLE_ALLOWLIST = frozenset({
    "age_bracket", "demo_marital_status", "dst_residence_province", "dst_age_group",
    "dst_reference_year", "dst_marital_status_conditioning", "dst_evidence_limit",
})
MARITAL_MAPPING = {"Evli": "Married", "Bo\u015fand\u0131": "Divorced", "E\u015fi \u00f6ld\u00fc": "Widowed"}
EVIDENCE_LIMIT = "Marital status was sampled by gender only; no age-specific relationship is established."


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_resident(path, person_id):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SOURCE_FIELDS:
            raise ValueError("Unexpected source population schema")
        matches = [(line, row) for line, row in enumerate(reader, 2) if row["person_id"] == person_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one resident {person_id}; found {len(matches)}")
    line, resident = matches[0]
    if None in resident or any(v is None or v == "" for v in resident.values()):
        raise ValueError("Malformed resident")
    if resident["gender"] not in {"male", "female"} or resident["marital_status_conditioning"] != "gender_only":
        raise ValueError("Unexpected recorded gender or conditioning")
    if resident["marital_status"] not in {*MARITAL_MAPPING, "Hi\u00e7 evlenmedi", "not_applicable"}:
        raise ValueError("Unknown source marital category")
    return resident, line


def bounds(label):
    if label == "Under 5":
        return 0, 4
    match = re.fullmatch(r"(\d+)-(\d+)", label)
    if match:
        lower, upper = map(int, match.groups())
        if lower > upper:
            raise ValueError("Invalid age interval")
        return lower, upper
    match = re.fullmatch(r"(\d+)\+", label)
    if match:
        return int(match[1]), float("inf")
    raise ValueError(f"Unrecognized age label {label!r}")


def fitting_age_bracket(age_group, catalog):
    lower, upper = bounds(age_group)
    fitting = [label for label in catalog["age_bracket"]["values"]
               if bounds(label)[0] <= lower and upper <= bounds(label)[1]]
    if len(fitting) > 1:
        raise ValueError("Ambiguous catalog age mapping")
    return fitting[0] if fitting else None


def load_catalog(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {row["id"]: row for row in payload["dimensions"]}


def display_path(path, base=ROOT):
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def generation_context(root, resident):
    # These facts are joined from processed inputs, not inferred from the ID.
    with (root / "processed" / "ankara_age_gender.csv").open(encoding="utf-8", newline="") as handle:
        matches = [r for r in csv.DictReader(handle)
                   if r["age_group"] == resident["age_group"] and r["gender"] == resident["gender"]]
    if len(matches) != 1 or matches[0]["year"] != "2025" or matches[0]["province"] != "Ankara":
        raise ValueError("Cannot establish resident year/province from processed source")
    # Read the configured seed without executing the generator or making new draws.
    import ast
    tree = ast.parse((root / "src" / "synthetic_population" / "generate_population.py").read_text(encoding="utf-8"))
    seeds = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "SEED" for t in node.targets)]
    if seeds != [42]:
        raise ValueError("Generation configuration changed; provenance must be reviewed")
    return matches[0], seeds[0]


def build_persona(resident, source, source_row, catalog_path, root=ROOT):
    catalog = load_catalog(catalog_path)
    context, seed = generation_context(root, resident)
    dimensions = {"dst_residence_province": context["province"], "dst_age_group": resident["age_group"],
                  "dst_reference_year": context["year"],
                  "dst_marital_status_conditioning": resident["marital_status_conditioning"],
                  "dst_evidence_limit": EVIDENCE_LIMIT}
    bracket = fitting_age_bracket(resident["age_group"], catalog)
    if bracket:
        dimensions["age_bracket"] = bracket
    mapped_status = MARITAL_MAPPING.get(resident["marital_status"])
    if mapped_status:
        if mapped_status not in catalog["demo_marital_status"]["values"]:
            raise ValueError("Marital mapping not supported by the catalog")
        dimensions["demo_marital_status"] = mapped_status
    provenance = {}
    def evidence(source_field, dataset, method):
        return dict(source_field=source_field, source_value=(resident.get(source_field) or context.get(source_field)),
                    source_type="statistically_inferred" if dataset == "T10" else "sampled_observed_distribution",
                    dataset=dataset, reference_year=2025, method=method)
    provenance["persona_id"] = dict(source_field="person_id", source_value=resident["person_id"], source_type="synthetic_identifier", method="identity")
    for key, field in [("dst_age_group", "age_group"), ("dst_residence_province", "province"), ("dst_reference_year", "year")]:
        provenance[key] = evidence(field, "T16", "identity; geography/year joined from processed input")
    if bracket:
        provenance["age_bracket"] = evidence("age_group", "T16", "fully contained interval; original band retained")
    if mapped_status:
        provenance["demo_marital_status"] = evidence("marital_status", "T10", "direct label translation; source assignment conditioned on gender only")
    provenance["dst_marital_status_conditioning"] = dict(source_field="marital_status_conditioning", source_value="gender_only", source_type="method_metadata", method="identity")
    provenance["dst_evidence_limit"] = dict(source_type="method_metadata", source_field="marital_status_conditioning", source_value="gender_only", method="explicit limitation")
    return dict(persona_id=resident["person_id"], version="1.0", source="synthetic", dimensions=dimensions,
                metadata=dict(source_population=display_path(source), source_sha256=digest(source), source_csv_row=source_row,
                              source_attributes=dict(resident), reference_year=2025, province="Ankara",
                              generation_seed=seed, seed_provenance="Configured seed 42; confirmed generation history in this project, not stored per resident",
                              catalog_path="MatrAIx-Persona-8B/persona/schema/dimensions.json", catalog_sha256=digest(catalog_path),
                              processed_sources={name: dict(path=display_path(root / "processed" / name), sha256=digest(root / "processed" / name))
                                                 for name in ("ankara_age_gender.csv", "ankara_marital_gender.csv")},
                              field_provenance=provenance, prompt_visible_fields=sorted(dimensions),
                              unassigned_fields=["gender_identity", "region", "primary_language", "education", "employment",
                                                 "personality", "values", "preferences", "communication_style", "exact_age"]))


def validate_persona(persona, resident, source, source_row, catalog_path):
    if set(persona) != {"persona_id", "version", "source", "dimensions", "metadata"}:
        raise ValueError("Missing/unsupported MatrAIx envelope fields")
    if persona["persona_id"] != resident["person_id"] or persona["version"] != "1.0" or persona["source"] != "synthetic":
        raise ValueError("Invalid persona envelope")
    dimensions = persona["dimensions"]
    if not set(dimensions) <= PROMPT_VISIBLE_ALLOWLIST:
        raise ValueError("Unsupported prompt-visible fields")
    expected = build_persona(resident, source, source_row, catalog_path)
    if persona != expected:
        raise ValueError("Persona differs from deterministic supported mappings/provenance")
    if not set(dimensions) <= persona["metadata"]["field_provenance"].keys():
        raise ValueError("Mapped field is missing provenance")
    if yaml.safe_load(yaml.safe_dump(persona, allow_unicode=True, sort_keys=False)) != persona:
        raise ValueError("YAML round-trip failed")


def matraix_load_test(output, matraix_root, persona):
    sys.path.insert(0, str(matraix_root / "src"))
    from matraix.application_job import _persona_entry_from_path
    from matraix.persona_dimension_catalog import build_dimension_narrative
    loaded = _persona_entry_from_path(output.resolve(), repo_root=output.resolve().parent)
    if loaded["persona_id"] != persona["persona_id"] or loaded["dimensions"] != persona["dimensions"] or loaded["metadata"] != persona["metadata"]:
        raise ValueError("MatrAIx loader changed persona attributes")
    profile = build_dimension_narrative(loaded["dimensions"], catalog_path=str(matraix_root / "persona" / "schema" / "dimensions.json"))
    if not profile or not any("Ankara" in block and persona["dimensions"]["dst_age_group"] in block for block in profile):
        raise ValueError("MatrAIx renderer failed to include custom demographics")
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--matraix-root", type=Path, default=DEFAULT_MATRAIX)
    args = parser.parse_args()
    if args.output.suffix.lower() not in {".yaml", ".yml"} or args.output.resolve() == args.source.resolve():
        parser.error("Output must be a YAML file distinct from the input")
    catalog = args.matraix_root / "persona" / "schema" / "dimensions.json"
    source_checksum = digest(args.source)
    resident, line = read_resident(args.source, args.person_id)
    persona = build_persona(resident, args.source, line, catalog)
    validate_persona(persona, resident, args.source, line, catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(persona, allow_unicode=True, sort_keys=False), encoding="utf-8")
    loaded = yaml.safe_load(args.output.read_text(encoding="utf-8"))
    validate_persona(loaded, resident, args.source, line, catalog)
    profile = matraix_load_test(args.output, args.matraix_root, loaded)
    if digest(args.source) != source_checksum:
        raise ValueError("Source population changed")
    print(f"PASS: one persona {args.person_id}; mappings/provenance/allowlist/YAML round-trip validated")
    print("PASS: actual MatrAIx loader and renderer; source unchanged")
    print("\n".join(profile))
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
