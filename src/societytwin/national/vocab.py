"""Category vocabularies for national person attributes.

Every attribute has internal codes; the TÜİK source label of each code is kept for display and
provenance. Ingestion maps source labels to codes explicitly. An unmapped label is an error, never a
silently dropped value (the historical persona adapter lost "Hiç evlenmedi" exactly that way).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

NOT_APPLICABLE = "not_applicable"

AGE_GROUPS: tuple[str, ...] = tuple(f"{a}-{a + 4}" for a in range(0, 90, 5)) + ("90+",)
TOP_CODE_AGE = 90  # the open-ended 90+ band is top-coded at 90 (standard practice for census microdata)


def band_bounds(band: str) -> tuple[int, int | None]:
    """Inclusive bounds; the open top band has no upper bound."""
    if band.endswith("+"):
        return int(band[:-1]), None
    low, high = band.split("-")
    return int(low), int(high)


def band_of_age(age: int) -> str:
    return "90+" if age >= 90 else f"{age // 5 * 5}-{age // 5 * 5 + 4}"


def label_key(text: str) -> str:
    """Matching key for source labels: NFC, Turkish i-dots folded, case and spacing ignored."""
    value = unicodedata.normalize("NFC", str(text)).strip().replace("İ", "i").replace("I", "ı").lower()
    value = re.sub(r"[\s_\-–/]+", " ", value)
    return value


@dataclass(frozen=True)
class Vocabulary:
    attribute: str
    codes: tuple[str, ...]
    labels_en: dict[str, str]
    labels_tr: dict[str, str]
    source_aliases: dict[str, str] = field(default_factory=dict)  # extra accepted source labels -> code
    note: str = ""

    def from_source(self, label: str) -> str:
        key = label_key(label)
        for code in self.codes:
            if key in {label_key(code), label_key(self.labels_tr.get(code, "")), label_key(self.labels_en.get(code, ""))}:
                return code
        for alias, code in self.source_aliases.items():
            if key == label_key(alias):
                return code
        raise ValueError(f"Unmapped {self.attribute} label {label!r}; add it to the vocabulary instead of dropping it")

    def display(self, code: str | None) -> str:
        if code is None:
            return "Not available"
        if code == NOT_APPLICABLE:
            return "Not applicable"
        return self.labels_en.get(code, code)

    def as_dict(self) -> dict:
        return {"attribute": self.attribute, "note": self.note,
                "categories": [{"code": c, "label_en": self.labels_en.get(c, c), "label_tr": self.labels_tr.get(c)} for c in self.codes]}


SEX = Vocabulary(
    "sex", ("male", "female"), {"male": "Male", "female": "Female"}, {"male": "Erkek", "female": "Kadın"},
    {"Erkek Male": "male", "Kadın Female": "female", "Kadin": "female"},
    note="TÜİK's administrative sex category as registered in ADNKS. Not a statement about gender identity, which is not modelled.",
)

MARITAL = Vocabulary(
    "marital_status", ("never_married", "married", "divorced", "widowed"),
    {"never_married": "Never married", "married": "Married", "divorced": "Divorced", "widowed": "Widowed"},
    {"never_married": "Hiç evlenmedi", "married": "Evli", "divorced": "Boşandı", "widowed": "Eşi öldü"},
    {"Hiç evlenmemiş": "never_married", "Bekar": "never_married", "Boşanmış": "divorced", "Eşi ölmüş": "widowed"},
    note="Legal marital status from civil registration. 'Never married' is kept literal and is not equated with 'single'.",
)

EDUCATION = Vocabulary(
    "education_level",
    ("illiterate", "literate_no_diploma", "primary", "basic_8yr", "lower_secondary", "upper_secondary",
     "higher_education", "masters", "doctorate", "unknown"),
    {"illiterate": "Illiterate", "literate_no_diploma": "Literate, no diploma", "primary": "Primary school (5-year)",
     "basic_8yr": "Primary education (8-year)", "lower_secondary": "Lower secondary", "upper_secondary": "Upper secondary (high school)",
     "higher_education": "Higher education (associate or bachelor's)", "masters": "Master's", "doctorate": "Doctorate",
     "unknown": "Unknown"},
    {"illiterate": "Okuma yazma bilmeyen", "literate_no_diploma": "Okuma yazma bilen fakat bir okul bitirmeyen",
     "primary": "İlkokul", "basic_8yr": "İlköğretim", "lower_secondary": "Ortaokul veya dengi meslek ortaokul",
     "upper_secondary": "Lise veya dengi meslek okulu", "higher_education": "Yüksekokul veya fakülte",
     "masters": "Yüksek lisans", "doctorate": "Doktora", "unknown": "Bilinmeyen"},
    {"Yüksek lisans (5 veya 6 yıllık fakülteler dahil)": "masters", "Ortaokul": "lower_secondary", "Lise": "upper_secondary"},
    note="Completed educational attainment in TÜİK's categories. 'Unknown' is a source category, kept as reported.",
)

LABOUR = Vocabulary(
    "labour_status", ("employed", "unemployed", "not_in_labour_force"),
    {"employed": "Employed", "unemployed": "Unemployed", "not_in_labour_force": "Not in labour force"},
    {"employed": "İstihdam", "unemployed": "İşsiz", "not_in_labour_force": "İşgücüne dahil olmayan"},
    {"İstihdam edilen": "employed", "İşgücüne dahil olmayanlar": "not_in_labour_force"},
    note="ILO labour status from the Household Labour Force Survey (sample survey; regional detail only).",
)

HOUSEHOLD_SIZE = Vocabulary(
    "household_size_class", ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10+"),
    {**{str(i): f"{i} person{'s' if i > 1 else ''}" for i in range(1, 10)}, "10+": "10 or more persons"},
    {**{str(i): f"{i} kişi" for i in range(1, 10)}, "10+": "10 ve daha fazla kişi"},
    {"10 ve üzeri": "10+", "10 kişi ve üzeri": "10+"},
    note="Size of the household the person lives in (person-level; derived from household counts when only households are published).",
)

HOUSEHOLD_TYPE = Vocabulary(
    "household_type", ("one_person", "nuclear_family", "extended_family", "non_family_multi_person"),
    {"one_person": "One-person household", "nuclear_family": "Nuclear family household",
     "extended_family": "Extended family household", "non_family_multi_person": "Multi-person household without a family nucleus"},
    {"one_person": "Tek kişilik hanehalkı", "nuclear_family": "Bir çekirdek aileden oluşan hanehalkı",
     "extended_family": "Geniş aile hanehalkı", "non_family_multi_person": "Çekirdek aile bulunmayan birden fazla kişiden oluşan hanehalkı"},
    {"Tek kişilik": "one_person", "Çekirdek aile": "nuclear_family", "Geniş aile": "extended_family"},
)

URBANICITY = Vocabulary(
    "urbanicity", ("province_district_centre", "town_village"),
    {"province_district_centre": "Province or district centre", "town_village": "Town (belde) or village"},
    {"province_district_centre": "İl ve ilçe merkezleri", "town_village": "Belde ve köyler"},
    {"İl/ilçe merkezi": "province_district_centre", "Belde/köy": "town_village", "Belde köy": "town_village"},
    note="ADNKS settlement type of the registered address. This is not the degree-of-urbanisation classification.",
)

VOCABULARIES: dict[str, Vocabulary] = {v.attribute: v for v in (SEX, MARITAL, EDUCATION, LABOUR, HOUSEHOLD_SIZE, HOUSEHOLD_TYPE, URBANICITY)}


class ValueStatus:
    """Status of one statistical cell. Missingness is never encoded as zero."""

    OBSERVED = "OBSERVED"                                 # a number published by the source (0 included)
    NOT_REPORTED = "NOT_REPORTED"                         # the source row exists but carries no number (e.g. '-', '..')
    UNKNOWN = "UNKNOWN"                                   # the source marks the value as unknown
    NOT_APPLICABLE = "NOT_APPLICABLE"                     # the indicator does not apply to this unit
    STRUCTURALLY_UNAVAILABLE = "STRUCTURALLY_UNAVAILABLE" # the dataset does not cover this province at all

    ALL = (OBSERVED, NOT_REPORTED, UNKNOWN, NOT_APPLICABLE, STRUCTURALLY_UNAVAILABLE)


class Evidence:
    """How a person attribute was obtained. Recorded per field in each provenance profile."""

    DIRECT_SOURCE = "DIRECT_SOURCE"            # the record's cell is a cell of an official table
    CONDITIONAL_SOURCE = "CONDITIONAL_SOURCE"  # drawn from an official conditional with all parents observed jointly
    MARGINAL_INFERENCE = "MARGINAL_INFERENCE"  # drawn from a fit to official marginals; the joint was not observed
    RULE_CONSTRAINED = "RULE_CONSTRAINED"      # set by a documented rule (e.g. outside the source universe)
    DERIVED = "DERIVED"                        # computed deterministically from other fields
    ASSUMED = "ASSUMED"                        # drawn from an assumed, unobserved distribution
    CONTEXTUAL = "CONTEXTUAL"                  # province-level context; belongs to the environment, not the person
    UNAVAILABLE = "UNAVAILABLE"                # no source; the value is explicitly unknown

    DESCRIPTIONS = {
        DIRECT_SOURCE: "The record's cell is a published cell of an official table.",
        CONDITIONAL_SOURCE: "Drawn from an official conditional distribution in which every parent attribute was observed jointly.",
        MARGINAL_INFERENCE: "Drawn from a fit to official marginal tables; the joint relationship with some parents was not observed.",
        RULE_CONSTRAINED: "Assigned by a documented rule, for example 'not applicable' outside the source table's universe.",
        DERIVED: "Computed deterministically from other fields or reference tables.",
        ASSUMED: "Drawn from an assumed distribution that no source observes (stated in the method).",
        CONTEXTUAL: "Province-level context held in the environment, not a personal attribute.",
        UNAVAILABLE: "No source table is loaded for this field and province; the value is explicitly unknown.",
    }
