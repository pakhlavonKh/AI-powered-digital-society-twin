"""Dependency model: which official table each person attribute is drawn from, and how.

The root of every record is the joint cell province × five-year age group × sex from the ADNKS
table (DIRECT_SOURCE). Every other attribute is drawn conditionally on (age group, sex) within its
province, from the strongest table loaded for that province, in this order of preference:

1. ``conditional_age_sex``: a table cross-classified by age group, sex and the attribute
   -> CONDITIONAL_SOURCE (the full joint with the parents is observed);
2. ``ipf_sex``: a table by sex and the attribute only -> a two-way IPF per sex fits the age-group
   margin (from the root) and the attribute margin, with structural zeros from the constraint engine.
   Without structural zeros IPF reduces exactly to conditioning on sex alone, i.e. assuming
   independence from age within sex -> MARGINAL_INFERENCE (the age relationship is NOT observed);
3. ``marginal``: a table by the attribute only -> independence from age and sex is assumed
   -> MARGINAL_INFERENCE.

Attributes with no table for a province stay null with evidence UNAVAILABLE. Nothing is imputed
from another province.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceOption:
    table_id: str
    method: str  # conditional_age_sex | ipf_sex | marginal


@dataclass(frozen=True)
class AttributeSpec:
    attribute: str
    options: tuple[SourceOption, ...]
    structural_zeros: bool = False
    description: str = ""


ATTRIBUTES: tuple[AttributeSpec, ...] = (
    AttributeSpec("marital_status", (SourceOption("marital_status_age_sex", "conditional_age_sex"),
                                     SourceOption("marital_status_sex", "ipf_sex")),
                  description="Legal marital status (civil registration)."),
    AttributeSpec("education_level", (SourceOption("education_age_sex", "conditional_age_sex"),
                                      SourceOption("education_sex", "ipf_sex")), structural_zeros=True,
                  description="Completed educational attainment."),
    AttributeSpec("labour_status", (SourceOption("labour_status_age_sex", "conditional_age_sex"),
                                    SourceOption("labour_status_sex", "ipf_sex")),
                  description="ILO labour status (HLFS; often regional, applied to every province in the region)."),
    AttributeSpec("household_size_class", (SourceOption("household_size_persons", "marginal"),),
                  description="Size of the person's household."),
    AttributeSpec("household_type", (SourceOption("household_type_persons", "marginal"),), description="Household type."),
    AttributeSpec("urbanicity", (SourceOption("urbanicity_sex", "ipf_sex"), SourceOption("urbanicity", "marginal")),
                  description="Settlement type of the registered address."),
)
ATTRIBUTE_NAMES = tuple(a.attribute for a in ATTRIBUTES)

# Fields the project schema names but that no loaded official table supports at person level.
NOT_MODELLED: dict[str, str] = {
    "socioeconomic_status": "No person-level socioeconomic-status distribution exists. The TÜİK package publishes SES classes "
                            "as household shares (A+ to E, 3-year average) and HDI/HCI indices by province; they are "
                            "environment context, not personal attributes.",
    "employment_status": "Status in employment (employee, employer, own-account…) needs an HLFS table conditional on being "
                         "employed; it is published only at NUTS-2 (not_province_level.csv), so none is loaded.",
    "income": "SILC income is published at NUTS-2 or above without the joint distributions needed for person-level draws; "
              "provincial GDP per capita is environment context.",
    "district": "District-level tables are not loaded; records are placed at province level only.",
}

METHOD_TEXT = {
    "conditional_age_sex": "Drawn from the official age group × sex × category table of the province (conditional sampling).",
    "ipf_sex": "Two-way IPF per sex of the age margin (root table) and the sex × category margin, then drawn conditionally "
               "on age and sex. Where a structural-zero rule applies the fit runs over single years of age (band "
               "population spread uniformly, as for the exact-age draw) with the zeros in the seed; otherwise over age "
               "groups, which equals conditioning on sex only.",
    "marginal": "Drawn from the province's category distribution; independence from age and sex is assumed.",
}


def dependency_graph() -> dict:
    nodes = [{"id": "province", "kind": "root", "evidence": "DIRECT_SOURCE"},
             {"id": "age_group", "kind": "root", "evidence": "DIRECT_SOURCE"},
             {"id": "sex", "kind": "root", "evidence": "DIRECT_SOURCE"},
             {"id": "age", "kind": "derived", "evidence": "ASSUMED"}]
    edges = [{"from": "province", "to": "age_group", "basis": "population_age_sex (joint)"},
             {"from": "province", "to": "sex", "basis": "population_age_sex (joint)"},
             {"from": "age_group", "to": "age", "basis": "uniform within band (assumed); 90+ top-coded"}]
    for spec in ATTRIBUTES:
        nodes.append({"id": spec.attribute, "kind": "attribute", "options": [o.__dict__ for o in spec.options],
                      "structural_zeros": spec.structural_zeros})
        edges.append({"from": "province", "to": spec.attribute, "basis": "province-specific table"})
        if any(o.method in ("conditional_age_sex", "ipf_sex") for o in spec.options):
            edges.append({"from": "sex", "to": spec.attribute, "basis": "observed when a sex breakdown exists"})
            edges.append({"from": "age_group", "to": spec.attribute,
                          "basis": "observed only with an age × sex table; otherwise inferred (IPF) or assumed independent"})
    return {"nodes": nodes, "edges": edges, "not_modelled": NOT_MODELLED, "methods": METHOD_TEXT}
