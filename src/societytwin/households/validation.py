"""Household-unit source fit and open-tail checks; no person calibration."""
import math
from collections import Counter
from dataclasses import asdict

from societytwin.common import canonical_hash
from societytwin.households import GENERATOR_VERSION, SCHEMA_VERSION
from societytwin.households.model import GeneratedHouseholds, HouseholdConfig
from societytwin.households.registry import CLASSES, HouseholdError, HouseholdRegistry


def validate(population: GeneratedHouseholds) -> dict:
    records, manifest = population.records, population.manifest
    failures = []
    identity = manifest["identity"]
    digest = canonical_hash(identity)
    config = HouseholdConfig.model_validate(identity["config"])
    registry = HouseholdRegistry.model_validate(manifest["registry"])
    expected_id = f"hh-06-2025-n{config.synthetic_size}-s{config.seed}-{digest[:16]}"
    if (manifest["identity_sha256"] != digest or manifest["household_population_id"] != expected_id
            or identity["registry_fingerprint"] != registry.fingerprint or not registry.module.enabled
            or manifest["source"] != registry.source.model_dump(mode="json")
            or identity["source_sha256"] != registry.source.sha256
            or identity["source_version"] != registry.source.source_version
            or identity["parent_registry"] != manifest["parent_dependency_registry"]):
        failures.append("identity/provenance mismatch")
    if any(obj["schema_version"] != SCHEMA_VERSION or obj["generator_version"] != GENERATOR_VERSION
           for obj in [identity,manifest]):
        failures.append("unsupported version")
    if manifest["weight_unit"] != "household" or manifest["scope"] != "household" or manifest["linked_to_residents"] is not False:
        failures.append("household/person scope mismatch or linkage")
    if manifest["member_count_exact"] is not None:
        failures.append("unsupported exact household member count")
    targets = identity["counts"]
    if set(targets) != set(CLASSES) or any(type(v) is not int or v <= 0 for v in targets.values()):
        raise HouseholdError("invalid observed household targets")
    if sum(targets.values()) != registry.source.expected_total or manifest["represented_households"] != sum(targets.values()):
        failures.append("household total mismatch")
    if len(records) != config.synthetic_size or len(records) != manifest["record_count"]:
        failures.append("record count mismatch")
    counts = Counter()
    weights = {c:[] for c in CLASSES}
    for seq,r in enumerate(records,1):
        if r.household_id != f"SH2025-06-{digest[:16]}-{seq:07d}" or r.province_code != "06" or r.reference_year != 2025:
            failures.append("invalid household identity/location/year")
        if r.household_size_class not in CLASSES:
            failures.append("unknown size class")
            continue
        counts[r.household_size_class] += 1
        weights[r.household_size_class].append(r.household_weight)
        is_open = r.household_size_class == "10+"
        lower = 10 if is_open else int(r.household_size_class)
        exact = None if is_open else lower
        if (r.household_size, r.household_size_lower, r.household_size_upper, r.household_size_open_ended) != (exact,lower,exact,is_open):
            failures.append("invalid exact/open-ended size semantics")
        if not math.isfinite(r.household_weight) or r.household_weight <= 0:
            failures.append("nonpositive/nonfinite household weight")
    margins = []
    for c in CLASSES:
        weighted = math.fsum(weights[c])
        relative_error = abs(weighted-targets[c])/targets[c]
        record_deviation = abs(counts[c]-len(records)*targets[c]/sum(targets.values()))
        if relative_error > 1e-12 or record_deviation >= 1.0000001:
            failures.append(f"household size margin mismatch: {c}")
        if any(not math.isclose(w, targets[c]/counts[c], rel_tol=1e-14) for w in weights[c]):
            failures.append(f"incorrect household expansion weight: {c}")
        margins.append({"household_size_class":c,"records":counts[c],"target_households":targets[c],
                        "weighted_households":weighted,"relative_error":relative_error,
                        "record_allocation_deviation":record_deviation})
    if dict(counts) != manifest["allocation"] or canonical_hash([asdict(r) for r in records]) != manifest["content_sha256"]:
        failures.append("record content/allocation differs from manifest")
    if failures:
        raise HouseholdError("Household validation failed: " + "; ".join(sorted(set(failures))))
    return {"validation_version":"household-source-fit-1", "passed":True,"weight_unit":"household",
            "records":len(records), "represented_households":math.fsum(r.household_weight for r in records),
            "margins":margins,"linked_residents":0,"exact_total_members":None,
            "open_ended_records":counts["10+"],
            "represented_members_lower_bound":math.fsum(r.household_weight*r.household_size_lower for r in records),
            "limitations":"Fit validates household margins only; no rosters, type joint or member population is validated."}
