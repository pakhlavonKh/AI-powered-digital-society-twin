"""Unit tests for placement data models, provenance validation, and non-ÖSYM disclosures."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scenarios.placement.models import (
    DEFAULT_HYPOTHETICAL_DISCLAIMER,
    PlacementRuleset,
    ProgramConditions,
    ProgramOffering,
)
from scenarios.schema import (
    PlacementScenarioConfig,
    PolicyConfig,
    PolicyParameters,
    QuestionConfig,
    QuestionOption,
    ScenarioConfig,
    ScenarioLocation,
    ScenarioMetadata,
    UniversityPolicyIntervention,
)


def test_default_ruleset_is_explicitly_hypothetical():
    ruleset = PlacementRuleset()
    assert ruleset.osym_verified is False
    assert ruleset.rule_fidelity == "hypothetical_simplified"
    assert ruleset.disclosure_banner() == DEFAULT_HYPOTHETICAL_DISCLAIMER
    assert "does NOT reproduce official ÖSYM" in ruleset.disclosure_banner()


def test_verified_osym_ruleset_requires_source_metadata():
    with pytest.raises(ValidationError, match="osym_verified=True requires rule_fidelity='verified_osym'"):
        PlacementRuleset(osym_verified=True)

    with pytest.raises(ValidationError, match="source_note"):
        PlacementRuleset(
            osym_verified=True,
            rule_fidelity="verified_osym",
            osym_kilavuz_year=2025,
            source_sha256="a" * 64,
        )

    with pytest.raises(ValidationError, match="osym_kilavuz_year"):
        PlacementRuleset(
            osym_verified=True,
            rule_fidelity="verified_osym",
            source_note="Official YKS Kilavuz",
            source_sha256="a" * 64,
        )

    with pytest.raises(ValidationError, match="source_sha256"):
        PlacementRuleset(
            osym_verified=True,
            rule_fidelity="verified_osym",
            source_note="Official YKS Kilavuz",
            osym_kilavuz_year=2025,
        )

    verified = PlacementRuleset(
        ruleset_id="osym_2025_verified",
        osym_verified=True,
        rule_fidelity="verified_osym",
        source_note="Official YKS 2025 Placement Guide",
        osym_kilavuz_year=2025,
        source_sha256="a" * 64,
    )
    assert "VERIFIED ÖSYM RULESET (2025)" in verified.disclosure_banner()


def test_program_offering_bounds_and_scholarship_net_tuition():
    prog = ProgramOffering(
        program_id="PRG_1",
        university_id="U1",
        university_name="Test Vakıf University",
        university_type="foundation",
        province_code="06",
        department_name="Law",
        score_type="EA",
        capacity=25,
        tuition_annual=200_000.0,
        scholarship_pct=50.0,
    )
    assert prog.published_net_tuition_before_aid() == 100_000.0

    with pytest.raises(ValidationError):
        ProgramOffering(
            program_id="PRG_BAD",
            university_id="U1",
            university_name="Bad",
            province_code="06",
            department_name="CS",
            score_type="SAY",
            capacity=-1,
        )

    with pytest.raises(ValidationError, match="min_age"):
        ProgramConditions(min_age=30, max_age=20)


def test_university_intervention_in_scenario_config_and_placement_scenario_config():
    params = PolicyParameters(
        currency="TL",
        custom_details={
            "simulation_mode": "university_placement",
            "university_intervention": {
                "tuition_change_pct": 20.0,
                "capacity_change_pct": -15.0,
                "affordability_filter_mode": "hard_exclude",
            },
        },
    )
    assert params.simulation_mode == "university_placement"
    uni = params.university_intervention
    assert isinstance(uni, UniversityPolicyIntervention)
    assert uni.tuition_change_pct == 20.0
    assert uni.capacity_change_pct == -15.0
    assert uni.osym_verified is False

    # Rejects osym_verified=True on hypothetical ScenarioConfig
    with pytest.raises(ValidationError, match="metadata.hypothetical=True"):
        ScenarioConfig(
            scenario_id="bad_verified_sc",
            name="Bad Verified Claim",
            description="Claims verified ÖSYM while marked hypothetical.",
            location=ScenarioLocation(province_code="06", province_name="Ankara"),
            metadata=ScenarioMetadata(hypothetical=True, source_note="Some note"),
            policy=PolicyConfig(
                category="university_placement",
                type="placement_simulation",
                parameters=PolicyParameters(
                    custom_details={
                        "simulation_mode": "university_placement",
                        "university_intervention": {
                            "rule_fidelity": "verified_osym",
                            "osym_verified": True,
                        },
                    }
                ),
            ),
            questions=[
                QuestionConfig(
                    id="q1",
                    text="Confirm?",
                    options=[QuestionOption(id="yes", label="Yes"), QuestionOption(id="no", label="No")],
                )
            ],
        )

    # PlacementScenarioConfig allows empty questions in university_placement mode
    psc = PlacementScenarioConfig(
        scenario_id="offline_placement_only",
        name="Offline Placement Only",
        description="Pure deterministic placement scenario without survey questions.",
        location=ScenarioLocation(province_code="06", province_name="Ankara"),
        policy=PolicyConfig(
            category="university_placement",
            type="quota_adjustment",
            parameters=PolicyParameters(),
        ),
        university_intervention=UniversityPolicyIntervention(capacity_change_pct=-15.0),
    )
    assert psc.questions == []
    assert psc.university_intervention.capacity_change_pct == -15.0
