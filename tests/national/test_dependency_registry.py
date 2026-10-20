"""Registry contracts and pre-registry compatibility fingerprints (artificial data only)."""
import pytest
from pydantic import ValidationError

from societytwin.common import canonical_hash
from societytwin.national.dependencies import (
    DEFAULT_REGISTRY_PATH, DependencyRegistry, RegistryError, compile_compatibility, load_registry,
)
from societytwin.national.generator import GenerationConfig, GenerationError, generate
from societytwin.national.model import ATTRIBUTES, compatibility_attributes


@pytest.fixture
def payload():
    return load_registry().model_dump(mode="json")


def test_loads_typed_registry_and_preserves_legacy_adapter():
    registry = load_registry()
    assert registry.schema_version == "dependency-registry-1"
    assert registry.registry_version == "ankara-core-1"
    assert set(("province_code", "age_group", "sex", "age", "age_top_coded", "marital_status",
                "education_level", "urbanicity", "nuts2_code", "adult_eligibility")) <= registry.attributes.keys()
    assert registry.modules["linked_households"].enabled is False
    assert compatibility_attributes(registry) == ATTRIBUTES
    assert [a.attribute for a in compile_compatibility(registry)] == [
        "marital_status", "education_level", "labour_status", "household_size_class", "household_type", "urbanicity"]
    assert len(registry.fingerprint) == 64


def test_topological_order_independent_of_yaml_mapping_order(payload):
    original = DependencyRegistry.model_validate(payload)
    payload["attributes"] = dict(reversed(list(payload["attributes"].items())))
    reordered = DependencyRegistry.model_validate(payload)
    assert reordered.ordered_attributes() == original.ordered_attributes()
    order = reordered.ordered_attributes()
    for name, attr in reordered.attributes.items():
        assert all(order.index(parent) < order.index(name) for parent in attr.parents)
    assert reordered.fingerprint == original.fingerprint


def test_cycle_detection(payload):
    payload["attributes"]["age_group"]["parents"] = ["sex"]
    payload["attributes"]["sex"]["parents"] = ["age_group"]
    with pytest.raises(ValidationError, match="cyclic dependencies"):
        DependencyRegistry.model_validate(payload)


@pytest.mark.parametrize("change, message", [
    (lambda p: p["attributes"]["age"]["parents"].append("unknown_parent"), "unknown parent"),
    (lambda p: p["attributes"]["age"]["assignments"][0].update(method="neural_sampler"), "method"),
    (lambda p: p["attributes"]["age_top_coded"]["derivation"].update(operator="eval"), "operator"),
    (lambda p: p["attributes"]["marital_status"]["assignments"][0].update(source=None), "missing required observed evidence"),
    (lambda p: p["sources"]["education_sex"]["dimensions"].append("age_group"), "unsupported source dimensions"),
    (lambda p: p["sources"]["education_sex"].update(table_id="invented_table"), "unknown table"),
    (lambda p: p["attributes"]["education_level"]["assignments"][0].update(source="missing_source"), "unknown source"),
    (lambda p: p["sources"]["education_sex"].update(evidence="context_only"), "missing required observed evidence"),
    (lambda p: p["attributes"]["age"].update(scope="household"), "incompatible scope"),
    (lambda p: p["attributes"]["age"].update(scope="geography"), "incompatible scope"),
    (lambda p: p["attributes"]["marital_status"]["parents"].append("education_level"), "unsupported conditional relationship"),
    (lambda p: p["attributes"]["education_level"]["assignments"][1].update(assumption=None), "explicit assumption"),
    (lambda p: p["attributes"]["education_level"]["assignments"][1].update(evidence_class="B"), "modelled evidence"),
    (lambda p: p["attributes"]["education_level"]["assignments"][0].update(category_mapping={"primary": "doctorate"}), "invalid category mapping"),
    (lambda p: p["attributes"]["education_level"].update(vocabulary="unknown"), "unknown vocabulary"),
    (lambda p: p["attributes"]["education_level"].update(constraints=["invented_rule"]), "inapplicable constraint"),
    (lambda p: p["attributes"]["adult_eligibility"]["derivation"].update(constant=21), "invalid derivation contract"),
    (lambda p: p["attributes"]["age"].pop("provenance"), "provenance"),
    (lambda p: p["attributes"]["age"].update(module="missing_module"), "unknown module"),
    (lambda p: p["attributes"]["age"].update(assignments=[]), "missing required evidence"),
    (lambda p: p.update(schema_version="dependency-registry-999"), "schema_version"),
    (lambda p: p["attributes"]["province_code"].update(missing_source="null_with_reason"), "required evidence"),
])
def test_rejects_invalid_configuration(payload, change, message):
    change(payload)
    with pytest.raises(ValidationError, match=message):
        DependencyRegistry.model_validate(payload)


def test_duplicate_keys_and_missing_files_fail_clearly(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text("schema_version: dependency-registry-1\nschema_version: other\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="duplicate registry key"):
        load_registry(path)
    with pytest.raises(RegistryError, match="Invalid dependency registry"):
        load_registry(tmp_path / "missing.yaml")


def test_missing_required_runtime_evidence_is_rejected(store):
    from societytwin.national.controls import ControlStore
    empty = ControlStore(store.tables, [], [], [])
    with pytest.raises(GenerationError, match="missing required evidence"):
        generate(empty, GenerationConfig(synthetic_size=10))


def test_compatibility_profile_blocks_semantic_changes(payload):
    payload["assignment_order"][0:2] = reversed(payload["assignment_order"][0:2])
    registry = DependencyRegistry.model_validate(payload)
    with pytest.raises(RegistryError, match="calibration order"):
        compile_compatibility(registry)
    payload = load_registry().model_dump(mode="json")
    payload["attributes"]["education_level"]["constraints"] = ["source_universe"]
    with pytest.raises(RegistryError, match="structural zeros"):
        compile_compatibility(DependencyRegistry.model_validate(payload))


def test_disabled_modules_cannot_be_activated_in_phase_one(payload):
    payload["modules"]["linked_households"]["enabled"] = True
    with pytest.raises(RegistryError, match="new execution modules"):
        compile_compatibility(DependencyRegistry.model_validate(payload))


def test_metadata_edits_are_loaded_without_changing_adapter(tmp_path, payload):
    import yaml
    path = tmp_path / "registry.yaml"
    payload["registry_version"] = "ankara-core-1-review"
    payload["attributes"]["marital_status"]["provenance"]["note"] = "Reviewed metadata"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    reviewed = load_registry(path)
    assert reviewed.registry_version == "ankara-core-1-review"
    assert reviewed.fingerprint != load_registry().fingerprint
    assert compile_compatibility(reviewed) == compile_compatibility(load_registry())


def test_optional_source_absence_preserves_null_and_evidence(store):
    # The artificial package has no person-household controls. Keeping these
    # legacy slots is necessary for the fixed schema and provenance contract.
    pop = generate(store, GenerationConfig(synthetic_size=500, seed=42))
    for name in ("household_size_class", "household_type"):
        assert set(pop.columns[name]) == {None}
        assert all(p["fields"][name]["evidence"] == "UNAVAILABLE" for p in pop.profiles.values())


def test_invalid_registry_is_rejected_by_existing_api(national_settings, tmp_path):
    from tests.conftest import make_client
    path = tmp_path / "invalid-registry.yaml"
    path.write_text("schema_version: invalid\n", encoding="utf-8")
    with make_client(national_settings.with_overrides(dependency_registry_path=path)) as client:
        assert client.post("/api/v2/controls/build").status_code == 200
        result = client.post("/api/v2/populations", json={"synthetic_size": 100, "seed": 42})
        assert result.status_code == 422
        assert "Invalid dependency registry" in result.text


@pytest.mark.parametrize("seed, columns_hash, cohorts_hash, personas_hash", [
    (42, "76a1301cdf847a841dd9fc62fb2aa0178c91e49fe1cd80f81943b993cc068081",
     "73a341d85398fc1347e7bb32273cc7988c65c1e55e4c248a250778ef3aaa321a",
     "9398a3b36a8ca5371ea2d25551b8d5dcbd581e2db02cbd9399f2af2fa317514f"),
    (43, "423512f1cbb1335aaf5621b701c604237c5a95f61adf7cbfaa7c421039b8966a",
     "46207470c2d4e5beb42b2ab3d086d7ce7407e54c29979fb9b899aa17d607feba",
     "6e30dd63eb40a3243bf187e2bf2e1897297cbd7489413ce94fb60b62733091d1"),
])
def test_pre_registry_artificial_snapshot(store, seed, columns_hash, cohorts_hash, personas_hash):
    # Filled from ignored before.json, captured before the adapter was edited.
    # Hash all columns, including exact float weights, rather than rounded IDs.
    from societytwin.national.cohorts import CohortSampleRequest, draw
    from societytwin.national.personas import build_persona
    pop = generate(store, GenerationConfig(synthetic_size=5000, seed=seed))
    c = pop.columns
    assert canonical_hash(c) == columns_hash
    eligible = [i for i,age in enumerate(c["age"]) if age >= 18]
    ids = [c["synthetic_id"][i] for i in eligible]
    weights = [c["population_weight"][i] for i in eligible]
    cohorts = {method: draw(ids, weights, CohortSampleRequest(size=40, seed=123, method=method,
                strata_field="sex" if method == "stratified" else None), [c["sex"][i] for i in eligible])
               for method in ("simple_random", "weighted", "stratified")}
    personas = [build_persona({k:v[i] for k,v in c.items()}, pop.manifest)
                for i in eligible[::max(1,len(eligible)//20)][:20]]
    assert canonical_hash(cohorts) == cohorts_hash
    assert canonical_hash(personas) == personas_hash
