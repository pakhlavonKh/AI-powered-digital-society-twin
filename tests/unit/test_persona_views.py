import pytest

from societytwin.errors import WorkbenchError


def v2_id(workbench):
    return next(b.descriptor["build_id"] for b in workbench.sync_builds() if b.source.variant == "v2")


def base_id(workbench):
    return next(b.descriptor["build_id"] for b in workbench.sync_builds() if b.source.variant == "base")


def test_fixture_persona_provenance(workbench):
    view = workbench.persona_view(v2_id(workbench), "TST2099_000001")
    assert view["persona_status"] == "fixture_persona"
    persona = view["personas"][0]
    assert persona["origin"] == "fixture" and persona["valid"]
    # The artificial persona has no conditioning dimension, so that source field is metadata-only too.
    assert persona["metadata_only_fields"] == ["gender", "marital_status_conditioning"]
    assert "gender" not in persona["prompt_visible_fields"]
    for forbidden in ("gender", "gender_identity", "exact_age", "preferences", "income"):
        assert forbidden not in persona["dimensions"]
    checks = {c["name"]: c["status"] for c in persona["hash_checks"]}
    assert checks["source_population"] == "line_ending_equivalent"
    assert checks["processed:testland_age_gender.csv"] == "line_ending_equivalent"
    assert checks["processed:testland_marital_gender.csv"] == "match"
    assert checks["persona_catalog"] == "unavailable"
    # The artificial YAML stores an all-zero catalog digest unquoted, which YAML reads as the integer 0.
    assert any("not strings" in w for w in persona["mapping_warnings"])
    assert persona["source_row_check"]["passed"]
    mapped = {m["dimension"]: m for m in persona["mapped_fields"]}
    assert mapped["age_bracket"]["value"] == "45-54" and mapped["age_bracket"]["source_field"] == "age_group"
    assert view["legacy_runner"]["slot"] == "A"
    assert any(e["experiment_id"] == "imp_ab_complete" for e in view["historical_prompt_evidence"])


def test_source_card_only_resident(workbench):
    build = v2_id(workbench)
    rows = workbench.load_build(build).table.rows
    never = next(r for r in rows if r["marital_status"] == "Hiç evlenmedi")
    view = workbench.persona_view(build, never["person_id"])
    assert view["persona_status"] == "source_card_only" and view["personas"] == []
    assert view["source_card"]["attributes"] == never
    assert not view["materialization"]["available"] and view["materialization"]["reasons"]
    assert "Hiç evlenmedi" in view["materialization"]["expected_omissions"][0]
    assert not view["legacy_runner"]["in_fixed_pair"]


def test_base_build_shows_no_mapped_persona(workbench):
    view = workbench.persona_view(base_id(workbench), "TST2099_000001")
    assert view["persona_status"] == "source_card_only"
    assert "marital_status" not in view["source_card"]["attributes"]
    assert any("v2" in r for r in view["materialization"]["reasons"])


def test_unknown_record(workbench):
    with pytest.raises(WorkbenchError) as info:
        workbench.persona_view(v2_id(workbench), "TST2099_999999")
    assert info.value.code == "unknown_record"


def test_changed_source_row_is_flagged(workbench, settings):
    path = settings.experiment_file(settings.layout.v2_population)
    path.write_text(path.read_text().replace("TST2099_000001,45-49,female,Evli", "TST2099_000001,45-49,female,Boşandı"))
    view = workbench.persona_view(v2_id(workbench), "TST2099_000001")
    persona = view["personas"][0]
    assert not persona["source_row_check"]["passed"]
    assert {c["name"]: c["status"] for c in persona["hash_checks"]}["source_population"] == "mismatch"
