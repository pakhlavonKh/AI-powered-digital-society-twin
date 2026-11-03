"""Reviewed persona exposure contracts, separate from sidecar storage schemas.

Adding a stored attribute does not authorize persona exposure. A new contract
needs field-specific semantics, reviewed categories and tests; MatrAIx approval
is independent. Relationships and experimental fixtures are never categories.
"""
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class SidecarPersonaContract:
    label: str
    limitation: str
    categories: frozenset[str]
    method: str = 'conditional_categorical_v1'
    evidence_class: str = 'D'
    assumption: str = 'independent_of_other_core_attributes_within_province_sex_v1'

    def accepts(self, attribute):
        return (attribute['scope'] == 'person' and attribute['method'] == self.method
                and attribute['evidence_class'] == self.evidence_class
                and attribute['assumption'] == self.assumption
                and {c['code'] for c in attribute['categories']} == self.categories)

    def display(self, value):
        if value not in self.categories:
            raise ValueError('Unapproved persona category')
        return f'{value.replace("_", " ")}. {self.limitation}'


APPROVED_SIDECAR_ATTRIBUTES = MappingProxyType({
    'degurba_class': SidecarPersonaContract(
        label='DEGURBA class',
        limitation=('Synthetic DEGURBA class sampled from province/sex aggregate counts; independence from other '
                    'resident attributes within sex is assumed. Not an observed individual location, address or district.'),
        categories=frozenset({'dense_urban', 'intermediate_urban', 'rural'})),
})
