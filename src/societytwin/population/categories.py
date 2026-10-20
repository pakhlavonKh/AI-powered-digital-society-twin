"""Category vocabularies used by the supplied fixtures. Source labels are kept verbatim."""

from __future__ import annotations

AGE_GROUPS: tuple[str, ...] = tuple(f"{age}-{age + 4}" for age in range(0, 90, 5)) + ("90+",)
UNDER_15: frozenset[str] = frozenset({"0-4", "5-9", "10-14"})
GENDERS: tuple[str, ...] = ("male", "female")
ADULT_MARITAL_STATUSES: tuple[str, ...] = ("Hiç evlenmedi", "Evli", "Boşandı", "Eşi öldü")
NOT_APPLICABLE = "not_applicable"
MARITAL_STATUSES: tuple[str, ...] = ADULT_MARITAL_STATUSES + (NOT_APPLICABLE,)
CONDITIONING_VALUES: tuple[str, ...] = ("gender_only",)

# Optional display translations. They are presentation aids only; the stored and filtered
# values remain the source labels above. "Hiç evlenmedi" is translated literally and is not
# equated with the persona catalog's "Single".
MARITAL_DISPLAY_EN: dict[str, str] = {
    "Hiç evlenmedi": "Never married",
    "Evli": "Married",
    "Boşandı": "Divorced",
    "Eşi öldü": "Widowed",
    NOT_APPLICABLE: "Not applicable (under 15)",
}

GENDER_FIELD_NOTE = (
    "The `gender` column holds TÜİK's administrative sex category (male/female) as recorded in the "
    "source tables. It is not a statement about gender identity, which is not modelled."
)
