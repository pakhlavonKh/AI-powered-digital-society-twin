"""Persona builder: one synthetic record -> one persona view (and an optional MatrAIx persona file).

Synthetic record -> Persona -> Active AI agent -> Experiment response are different objects. A
persona is a deterministic, template-based view of one record; it never adds facts the record does
not have. Every attribute is listed with its value, evidence and source, and with whether the model
sees it. Attributes are hidden from the model only for a stated reason, so omissions are visible
(the historical adapter dropped sex and "never married" silently).
"""

from __future__ import annotations

from societytwin.common import canonical_hash, sha256_bytes
from societytwin.national.constraints import ADULT_AGE
from societytwin.national.vocab import NOT_APPLICABLE, VOCABULARIES, Evidence

TEMPLATE_VERSION = "tr-persona-card-1"
FIELD_LABELS = {
    "province_name": "Province of residence", "age_group": "Age group", "age": "Age (single year)", "sex": "Sex",
    "marital_status": "Marital status", "education_level": "Education (completed)", "labour_status": "Labour status",
    "household_size_class": "Household size", "household_type": "Household type", "urbanicity": "Settlement type",
    "reference_year": "Reference year",
}
PERSON_FIELDS = ("province_name", "age_group", "age", "sex", "marital_status", "education_level", "labour_status",
                 "household_size_class", "household_type", "urbanicity", "reference_year")
DEFAULT_VISIBLE = ("province_name", "age_group", "sex", "marital_status", "education_level", "labour_status",
                   "household_size_class", "household_type", "urbanicity", "reference_year")
DEFAULT_HIDDEN_REASONS = {
    "age": "Hidden by default: single-year age is ASSUMED (uniform within the observed five-year band); showing it "
           "would give the model false precision.",
}
METADATA_HIDDEN = {
    "synthetic_id": "Record identifier; not a personal attribute.",
    "population_weight": "Sampling metadata (persons represented); not a personal attribute.",
    "design_weight": "Sampling metadata; not a personal attribute.",
    "provenance_profile": "Provenance reference; not a personal attribute.",
    "nuts1_code": "Statistical region code; derivable from the province and not decision-relevant.",
    "nuts2_code": "Statistical region code; derivable from the province and not decision-relevant.",
    "nuts3_code": "Statistical region code; derivable from the province and not decision-relevant.",
    "province_code": "Code form of the province, which is shown by name.",
    "age_top_coded": "Technical flag for the open 90+ band.",
}
KIND_LABEL = "Fictional synthetic resident generated from official aggregate statistics. Not a real person."


def _display(field: str, record: dict) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if field == "age_group":
        return "90 or older" if value == "90+" else value.replace("-", "–")
    if field == "age":
        return f"{value}{' (top-coded)' if record.get('age_top_coded') else ''}"
    if field in VOCABULARIES:
        return VOCABULARIES[field].display(value)
    return str(value)


def _evidence(field: str, profile: dict) -> dict:
    source_field = {"province_name": "province_code", "reference_year": "province_code"}.get(field, field)
    info = profile["fields"].get(source_field, {})
    out = {k: info.get(k) for k in ("evidence", "table_id", "source_year", "geo_level", "source_ids", "method", "conditioning",
                                    "unobserved_joint_with", "limitations", "reason") if info.get(k) is not None}
    if field == "reference_year":
        out = {"evidence": Evidence.DERIVED, "method": "Population reference year from the generation configuration."}
    return out


def build_persona(record: dict, manifest: dict, visible_fields: list[str] | None = None) -> dict:
    profile = manifest["profiles"][record["provenance_profile"]]
    requested = list(visible_fields) if visible_fields is not None else list(DEFAULT_VISIBLE)
    unknown = [f for f in requested if f not in PERSON_FIELDS]
    if unknown:
        raise ValueError(f"Unknown persona fields: {unknown}")
    attributes, model_visible, hidden = [], {}, []
    for field in PERSON_FIELDS:
        value = record.get(field)
        display = _display(field, record)
        evidence = _evidence(field, profile)
        if value is None:
            status, reason = "unavailable", evidence.get("reason") or "No source table is loaded for this field and province."
        elif value == NOT_APPLICABLE:
            status, reason = "not_applicable", "Outside the source table's universe for this age."
        elif field in requested:
            status, reason = "visible", None
            model_visible[field] = display
        else:
            status = "hidden"
            reason = DEFAULT_HIDDEN_REASONS.get(field, "Excluded by this experiment's persona field policy.")
            hidden.append({"field": field, "reason": reason})
        attributes.append({"field": field, "label": FIELD_LABELS[field], "value": value, "display": display or "Not available",
                           "status": status, "reason": reason, "evidence": evidence})
    for field, reason in METADATA_HIDDEN.items():
        hidden.append({"field": field, "reason": reason})
    limitations = []
    for field in model_visible:
        for text in _evidence(field, profile).get("limitations", []) or []:
            if text not in limitations:
                limitations.append(text)
    adult = record["age"] >= ADULT_AGE
    card = render_card(model_visible, record)
    persona_id = "per-" + canonical_hash({"population": manifest["population_id"], "record": record["synthetic_id"],
                                          "template": TEMPLATE_VERSION, "visible": sorted(model_visible)})[:16]
    return {
        "persona_id": persona_id, "kind": "persona", "kind_label": KIND_LABEL, "template_version": TEMPLATE_VERSION,
        "synthetic_id": record["synthetic_id"], "population_id": manifest["population_id"],
        "province_code": record["province_code"], "province_name": record["province_name"],
        "attributes": attributes, "model_visible": model_visible, "hidden": hidden,
        "model_visible_fields": sorted(model_visible), "persona_card": card, "persona_card_sha256": sha256_bytes(card.encode()),
        "eligibility": {"adult": adult, "age": record["age"], "rule": f"Adult-only tasks require age ≥ {ADULT_AGE}."},
        "limitations": limitations,
        "provenance": {"population_id": manifest["population_id"], "synthetic_id": record["synthetic_id"],
                       "provenance_profile": record["provenance_profile"], "generator_version": manifest["generator_version"],
                       "generation_seed": manifest["seed"], "reference_year": manifest["reference_year"],
                       "source_years": profile.get("source_years", {}),
                       "source_ids": sorted({sid for f in profile["fields"].values() for sid in f.get("source_ids", [])})},
        "population_weight": record["population_weight"],
    }


def render_card(model_visible: dict, record: dict) -> str:
    lines = [
        "You are taking part in a controlled research experiment as a fictional synthetic resident of Türkiye.",
        "This person does not exist. The profile below was generated from official aggregate statistics and is all that is known.",
        "",
        f"Profile (reference year {record['reference_year']}):",
    ]
    for field in PERSON_FIELDS:
        if field in model_visible and field != "reference_year":
            lines.append(f"- {FIELD_LABELS[field]}: {model_visible[field]}")
    lines += [
        "",
        "Answer as this person plausibly would, given only these attributes and the situation described. Do not invent "
        "specific personal facts (names, employers, exact incomes) beyond the profile.",
    ]
    return "\n".join(lines)


def matraix_persona(persona: dict) -> dict:
    """MatrAIx persona document. Custom ``dst_`` dimensions carry the model-visible SocietyTwin attributes verbatim;
    catalog dimensions are added only where the meaning is identical (never 'Single' for 'never married', never
    gender identity for administrative sex). Evidence limitations go to metadata (for researchers), not to the prompt."""
    visible = persona["model_visible"]
    dims = {}
    for field, text in visible.items():
        dims[f"dst_{'residence_province' if field == 'province_name' else field}"] = text
    status = next((a["value"] for a in persona["attributes"] if a["field"] == "marital_status"), None)
    catalog_marital = {"married": "Married", "divorced": "Divorced", "widowed": "Widowed"}
    if "marital_status" in visible and status in catalog_marital:
        dims["demo_marital_status"] = catalog_marital[status]
    return {"persona_id": persona["synthetic_id"], "version": "1.0", "source": "synthetic", "dimensions": dims,
            "metadata": {"societytwin_persona_id": persona["persona_id"], "template_version": persona["template_version"],
                         "population_id": persona["population_id"], "prompt_visible_fields": sorted(dims),
                         "hidden_fields": persona["hidden"], "evidence_limitations": persona["limitations"],
                         "provenance": persona["provenance"]}}
