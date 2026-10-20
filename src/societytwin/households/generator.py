"""Size-stratified unlinked household generation with exact count expansion weights."""
from dataclasses import asdict

from societytwin.common import canonical_hash
from societytwin.households import GENERATOR_VERSION, SCHEMA_VERSION
from societytwin.households.evidence import HouseholdEvidence
from societytwin.households.model import GeneratedHouseholds, HouseholdConfig, HouseholdRecord
from societytwin.households.registry import CLASSES, HouseholdError, HouseholdRegistry, parent_binding
from societytwin.national.fitting import largest_remainder
from societytwin.national.rng import STREAM_VERSION, Stream


def generate(evidence: HouseholdEvidence, config: HouseholdConfig, registry: HouseholdRegistry) -> GeneratedHouseholds:
    if not registry.module.enabled:
        raise HouseholdError("unlinked_households module is disabled; explicit opt-in is required")
    # Revalidate caller-owned objects, including nested dictionaries, before execution.
    registry = HouseholdRegistry.model_validate(registry.model_dump(mode="json"))
    config = HouseholdConfig.model_validate(config.model_dump(mode="json"))
    if evidence.source != registry.source or len(evidence.counts) != len(CLASSES) or any(
            type(v) is not int or v <= 0 for v in evidence.counts) or evidence.total != registry.source.expected_total:
        raise HouseholdError("household evidence does not match registry")
    parent = parent_binding(registry)
    identity = {"generator_version": GENERATOR_VERSION, "schema_version": SCHEMA_VERSION,
                "config": config.model_dump(mode="json"), "registry_fingerprint": registry.fingerprint,
                "parent_registry": parent, "source_sha256": evidence.source.sha256,
                "source_version": evidence.source.source_version, "counts": dict(zip(CLASSES, evidence.counts))}
    digest = canonical_hash(identity)
    build_id = f"hh-06-2025-n{config.synthetic_size}-s{config.seed}-{digest[:16]}"
    # Numeric keys fix Hamilton tie-breaking in natural size order (not lexical 10+,1,...).
    allocation = largest_remainder(dict(enumerate(evidence.counts)), config.synthetic_size)
    if any(n <= 0 for n in allocation.values()):
        raise HouseholdError("sample too small to support all observed household margins; increase synthetic_size")
    namespace = f"households:{GENERATOR_VERSION}:06:2025:size-order"
    classes = Stream(namespace, config.seed).shuffle([i for i in range(len(CLASSES)) for _ in range(allocation[i])])
    records = tuple(HouseholdRecord(
        household_id=f"SH2025-06-{digest[:16]}-{seq:07d}", province_code="06", reference_year=2025,
        household_size_class=CLASSES[i], household_size=i+1 if i < 9 else None,
        household_size_lower=i+1, household_size_upper=i+1 if i < 9 else None,
        household_size_open_ended=i == 9, household_weight=evidence.counts[i]/allocation[i])
        for seq,i in enumerate(classes,1))
    manifest = {"household_population_id": build_id, "identity_sha256": digest, "identity": identity,
        "schema_version": SCHEMA_VERSION, "generator_version": GENERATOR_VERSION,
        "registry": registry.model_dump(mode="json"), "parent_dependency_registry": parent,
        "source": evidence.source.model_dump(mode="json"), "record_count": len(records),
        "represented_households": evidence.total, "weight_unit": "household", "scope": "household",
        "linked_to_residents": False, "member_count_exact": None,
        "allocation": {CLASSES[i]:allocation[i] for i in allocation},
        "random_stream": {"version": STREAM_VERSION, "namespace": namespace, "seed": config.seed},
        "method": "Hamilton proportional size allocation; source count / stratum records; seeded order shuffle",
        "limitations": ["Unlinked household representatives, not families or resident rosters.",
                        "10+ has no assigned exact size or upper bound.",
                        "No type, roles, housing, income, SES or institutional-population estimate."],
        "content_sha256": canonical_hash([asdict(r) for r in records])}
    return GeneratedHouseholds(records, manifest)
