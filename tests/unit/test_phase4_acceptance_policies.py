"""Acceptance tests for Phase 4: Purpose-Specific Acceptance Policies.

Verifies:
1. Policy A (Basic Demographic Survey): A demographically valid population without household linkage
   is ACCEPTED for a demographic-only survey.
2. Policy B (Household-Dependent Simulation): The same population is REJECTED for a simulation
   requiring verified household membership.
3. Policy C (MatrAIx Persona Projection): A persona with unsupported required projection fields
   is REJECTED with explicit reporting of missing/incompatible fields.
4. Restricted decision semantics: a failed mandatory check can NEVER result in 'restricted',
   it must be 'rejected'.
"""

from __future__ import annotations

import pytest

from societytwin.validation import (
    generate_ankara_sample_population,
    generate_combined_quality_report,
    load_reference_bundle,
)
from societytwin.validation.policies import (
    evaluate_policy_a_demographic_survey,
    evaluate_policy_b_household_simulation,
    evaluate_policy_c_matraix_persona_projection,
    evaluate_acceptance_policy,
)


@pytest.fixture(scope="module")
def ankara_pop_1000():
    return generate_ankara_sample_population(1000, seed=42)


@pytest.fixture(scope="module")
def combined_report_1000(ankara_pop_1000):
    ref_bundle = load_reference_bundle()
    return generate_combined_quality_report(
        ankara_pop_1000,
        ref_bundle,
        save_to_disk=False,
    )


def test_policy_a_accepted_without_household_linkage(combined_report_1000):
    """Test 1: A demographically valid population without household linkage is ACCEPTED

    for a demographic-only survey (Policy A).
    """
    decision = evaluate_policy_a_demographic_survey(combined_report_1000)

    assert decision.policy_id == "policy_a_demographic_survey"
    assert decision.policy_name == "Policy A — Basic Demographic Survey"
    assert decision.acceptance_decision == "accepted"
    assert len(decision.required_check_ids) > 0
    # Mandatory checks (age, sex) passed
    assert any("age" in chk for chk in decision.check_results)
    assert any("sex" in chk for chk in decision.check_results)
    # Reasons/limitations are documented
    assert len(decision.reasons) > 0


def test_policy_b_rejected_without_verified_household_linkage(combined_report_1000):
    """Test 2: The same population is REJECTED for a simulation requiring verified

    household membership (Policy B).
    """
    decision = evaluate_policy_b_household_simulation(combined_report_1000)

    assert decision.policy_id == "policy_b_household_simulation"
    assert decision.policy_name == "Policy B — Household-Dependent Simulation"
    assert decision.acceptance_decision == "rejected"
    # Explicit rejection reason regarding unlinked households
    assert any("household" in r.lower() and ("link" in r.lower() or "unlinked" in r.lower()) for r in decision.reasons)
    assert len(decision.limitations) > 0


def test_policy_c_rejected_on_unsupported_projection_fields():
    """Test 3: A persona with unsupported required projection fields is REJECTED

    for MatrAIx projection (Policy C).
    """
    # Valid persona:
    valid_persona = {
        "synthetic_id": "RES_001",
        "age": 35,
        "sex": "female",
        "marital_status": "married",
        "education_level": "bachelors",
        "labour_status": "employed",
        "province_code": "06",
    }
    decision_valid = evaluate_policy_c_matraix_persona_projection(valid_persona)
    assert decision_valid.acceptance_decision == "accepted"

    # Invalid persona missing required 'age' and carrying illegal field 'telepathic_power':
    invalid_persona = {
        "synthetic_id": "RES_002",
        "sex": "female",
        "telepathic_power": "omega_level",  # illegal unsupported attribute
    }
    decision_invalid = evaluate_policy_c_matraix_persona_projection(invalid_persona)
    assert decision_invalid.acceptance_decision == "rejected"
    # Explicitly reports missing/incompatible fields
    reasons_str = " ".join(decision_invalid.reasons)
    assert "age" in reasons_str
    assert "telepathic_power" in reasons_str


def test_mandatory_check_failure_can_never_be_restricted(combined_report_1000):
    """Test 4: A failed mandatory check can NEVER be downgraded to 'restricted';

    it must be strictly 'rejected'.
    """
    # Create a synthetic report where age distribution failed
    report_dict = combined_report_1000.to_ui_dict()
    # Modify age check to failed
    for chk in report_dict["checks"]:
        if "age" in chk["name"]:
            chk["passed"] = False

    decision = evaluate_acceptance_policy("policy_a_demographic_survey", report_dict)
    assert decision.acceptance_decision == "rejected"
    assert decision.acceptance_decision != "restricted"
