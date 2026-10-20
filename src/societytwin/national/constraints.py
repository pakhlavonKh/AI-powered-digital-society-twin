"""Centralised logical constraints for synthetic records.

Rules are data: each has an ID, the fields it governs, a justification and a check. The generator
asks this module for universes and structural zeros instead of carrying its own if-statements, and
validation runs every check on every build (a violation is a generator bug, so the target is zero).

Only rules with an institutional or source-defined basis are included. In particular, no
demographic rule (for example "nobody under N is married") is added beyond the universe a TÜİK
table itself defines.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from societytwin.national import geography as geo
from societytwin.national.vocab import AGE_GROUPS, NOT_APPLICABLE, TOP_CODE_AGE, VOCABULARIES, Evidence, band_bounds

ADULT_AGE = 18  # age of majority, Turkish Civil Code (Law 4721) Art. 11

# Lenient lower bounds on the age at which each attainment level can first be completed, from the
# formal structure of Turkish schooling (5-year primary before 1997, 8-year basic education 1997–2012,
# 4+4+4 since 2012 under Law 6287; school entry at about 6). They are deliberately one year below the
# theoretical completion age so that early completers are not excluded. They are applied only when
# education is NOT drawn from an age-specific official table; observed age × education cells are trusted.
EDUCATION_MIN_COMPLETION_AGE: dict[str, int] = {
    "primary": 9,
    "basic_8yr": 13,
    "lower_secondary": 13,
    "upper_secondary": 16,
    "higher_education": 18,
    "masters": 21,
    "doctorate": 24,
}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    kind: str          # universe | structural_zero | consistency | eligibility
    fields: tuple[str, ...]
    description: str
    justification: str

    def as_dict(self) -> dict:
        return dict(self.__dict__)


RULES: tuple[Rule, ...] = (
    Rule("source_universe", "universe", ("marital_status", "education_level", "labour_status", "household_size_class",
                                         "household_type", "urbanicity"),
         "An attribute is 'not_applicable' exactly when the person is younger than the minimum age of the source table's universe.",
         "Follows the population universe TÜİK defines for each table (e.g. marital status: residents aged 15+). "
         "The universe is read from the control table metadata, never hard-coded."),
    Rule("education_min_completion_age", "structural_zero", ("education_level", "age"),
         "Attainment levels require a minimum age (primary 9, 8-year basic 13, lower secondary 13, upper secondary 16, "
         "higher education 18, master's 21, doctorate 24).",
         "Lenient lower bounds from the formal structure of Turkish schooling. Used as structural zeros only when the "
         "age × education joint is not observed."),
    Rule("age_within_band", "consistency", ("age", "age_group"),
         "The single-year age lies inside its five-year band; the open 90+ band is top-coded at 90.",
         "Exact age is drawn within the observed band; top-coding the open band avoids inventing an upper age."),
    Rule("geography_consistent", "consistency", ("province_code", "province_name", "nuts1_code", "nuts2_code", "nuts3_code"),
         "Province name and İBBS codes agree with the plate code in the reference table.",
         "Province identity is the code; names and regions are derived from the reference table."),
    Rule("category_in_vocabulary", "consistency", tuple(VOCABULARIES),
         "Every categorical value is a known code, 'not_applicable', or explicitly unavailable (null).",
         "Unknown labels must fail ingestion instead of being dropped or invented."),
    Rule("weight_positive_finite", "consistency", ("population_weight",),
         "Population weights are finite and strictly positive.",
         "A synthetic record represents a positive number of residents."),
    Rule("adult_eligibility", "eligibility", ("age",),
         f"Adult-only cohorts and experiments include only records aged {ADULT_AGE} or over.",
         "Age of majority under the Turkish Civil Code (Art. 11). Children are never selected as agents for adult tasks."),
)
RULES_BY_ID = {r.rule_id: r for r in RULES}


def structural_zero(attribute: str, category: str, age: int) -> bool:
    """True when ``category`` is impossible at exact ``age`` under an institutional rule."""
    if attribute == "education_level":
        return age < EDUCATION_MIN_COMPLETION_AGE.get(category, 0)
    return False


def band_feasible(attribute: str, category: str, band: str) -> bool:
    """A band is feasible for a category if its oldest age is feasible (used to seed IPF)."""
    low, high = band_bounds(band)
    return not structural_zero(attribute, category, high if high is not None else TOP_CODE_AGE)


def in_universe(age: int, min_age: int) -> bool:
    return age >= min_age


def is_adult(age: int) -> bool:
    return age >= ADULT_AGE


def check_records(columns: dict[str, list], profiles: dict[str, dict]) -> list[dict]:
    """Run every record-level rule. Returns one entry per rule with the violation count and examples."""
    n = len(columns["synthetic_id"])
    out = {r.rule_id: {"rule_id": r.rule_id, "kind": r.kind, "description": r.description, "checked": 0, "violations": 0,
                       "examples": []} for r in RULES if r.kind != "eligibility"}

    def fail(rule_id: str, i: int, detail: str) -> None:
        entry = out[rule_id]
        entry["violations"] += 1
        if len(entry["examples"]) < 5:
            entry["examples"].append({"synthetic_id": columns["synthetic_id"][i], "detail": detail})

    for i in range(n):
        age, band = columns["age"][i], columns["age_group"][i]
        profile = profiles[columns["provenance_profile"][i]]
        out["age_within_band"]["checked"] += 1
        low, high = band_bounds(band) if band in AGE_GROUPS else (None, None)
        if low is None or age < low or (high is not None and age > high) or (high is None and age != TOP_CODE_AGE):
            fail("age_within_band", i, f"age {age} in band {band}")
        out["geography_consistent"]["checked"] += 1
        try:
            p = geo.province(columns["province_code"][i])
            if (p.name, p.nuts1, p.nuts2, p.nuts3) != (columns["province_name"][i], columns["nuts1_code"][i],
                                                       columns["nuts2_code"][i], columns["nuts3_code"][i]):
                fail("geography_consistent", i, "names or İBBS codes differ from the reference table")
        except geo.UnknownProvince:
            fail("geography_consistent", i, f"unknown province code {columns['province_code'][i]!r}")
        out["weight_positive_finite"]["checked"] += 1
        w = columns["population_weight"][i]
        if not (isinstance(w, float) and math.isfinite(w) and w > 0):
            fail("weight_positive_finite", i, f"weight {w!r}")
        for attribute, vocab in VOCABULARIES.items():
            if attribute == "sex":
                out["category_in_vocabulary"]["checked"] += 1
                if columns["sex"][i] not in vocab.codes:
                    fail("category_in_vocabulary", i, f"sex {columns['sex'][i]!r}")
                continue
            if attribute not in columns:
                continue
            value = columns[attribute][i]
            field = profile["fields"].get(attribute, {})
            out["category_in_vocabulary"]["checked"] += 1
            if value is not None and value != NOT_APPLICABLE and value not in vocab.codes:
                fail("category_in_vocabulary", i, f"{attribute} {value!r}")
            if field.get("evidence") == Evidence.UNAVAILABLE:
                if value is not None:
                    fail("source_universe", i, f"{attribute} has a value although no source is loaded")
                continue
            min_age = field.get("universe_min_age")
            if min_age is None:
                continue
            out["source_universe"]["checked"] += 1
            if (value == NOT_APPLICABLE) != (age < min_age):
                fail("source_universe", i, f"{attribute}={value!r} at age {age} (universe {min_age}+)")
            if attribute == "education_level" and field.get("structural_zeros") and value not in (None, NOT_APPLICABLE):
                out["education_min_completion_age"]["checked"] += 1
                if structural_zero(attribute, value, age):
                    fail("education_min_completion_age", i, f"{value} at age {age}")
    return list(out.values())
