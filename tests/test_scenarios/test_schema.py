"""Unit tests for scenario configuration schema and validation."""

import pytest
from pydantic import ValidationError

from src.scenarios.schema import (
    PolicyConfig,
    PolicyParameters,
    PopulationFilterConfig,
    QuestionConfig,
    QuestionOption,
    ScenarioConfig,
    ScenarioLocation,
    ScenarioMetadata,
)


def test_valid_scenario_config():
    scenario = ScenarioConfig(
        scenario_id="transport_fare_001",
        version="1.0.0",
        name="Ankara Fare Increase",
        description="A controlled simulation of a 20% transit fare increase in Ankara.",
        location=ScenarioLocation(province_code="06", province_name="Ankara"),
        metadata=ScenarioMetadata(hypothetical=True, reference_year=2024),
        policy=PolicyConfig(
            category="transportation",
            type="fare_increase",
            parameters=PolicyParameters(
                baseline_fare=21.0,
                new_fare=25.2,
                increase_percentage=20.0,
                currency="TL",
            ),
        ),
        target_population=PopulationFilterConfig(
            minimum_age=18,
            province_codes=["06"],
            adult_only=True,
        ),
        questions=[
            QuestionConfig(
                id="q1_usage",
                text="Would you reduce transit trips?",
                type="single_choice",
                options=[
                    QuestionOption(id="yes", label="Yes, reduce trips"),
                    QuestionOption(id="no", label="No, keep usage"),
                ],
            )
        ],
    )
    assert scenario.scenario_id == "transport_fare_001"
    assert len(scenario.questions) == 1
    assert scenario.target_population.minimum_age == 18


def test_reject_duplicate_question_ids():
    with pytest.raises(ValidationError, match="duplicate question IDs"):
        ScenarioConfig(
            scenario_id="test_dup_q",
            name="Duplicate Question Test",
            description="Testing duplicate question detection.",
            location=ScenarioLocation(province_code="06", province_name="Ankara"),
            policy=PolicyConfig(
                category="transportation",
                type="fare_increase",
                parameters=PolicyParameters(baseline_fare=20.0),
            ),
            questions=[
                QuestionConfig(
                    id="q1",
                    text="First question text?",
                    options=[
                        QuestionOption(id="opt_a", label="A"),
                        QuestionOption(id="opt_b", label="B"),
                    ],
                ),
                QuestionConfig(
                    id="q1",  # Duplicate ID
                    text="Second question text?",
                    options=[
                        QuestionOption(id="opt_a", label="A"),
                        QuestionOption(id="opt_b", label="B"),
                    ],
                ),
            ],
        )


def test_reject_duplicate_option_ids():
    with pytest.raises(ValidationError, match="duplicate option IDs"):
        QuestionConfig(
            id="q1",
            text="Question with duplicate options?",
            options=[
                QuestionOption(id="opt_yes", label="Yes"),
                QuestionOption(id="opt_yes", label="Yes indeed"),
            ],
        )


def test_reject_inconsistent_fare_parameters():
    with pytest.raises(ValidationError, match="Inconsistent fare parameters"):
        PolicyParameters(
            baseline_fare=20.0,
            increase_percentage=20.0,  # 20 * 1.20 = 24.0
            new_fare=35.0,             # Contradicts 20%
        )


def test_reject_invalid_age_bounds():
    with pytest.raises(ValidationError, match="minimum_age .* cannot exceed maximum_age"):
        PopulationFilterConfig(
            minimum_age=30,
            maximum_age=25,
            adult_only=False,
        )


def test_reject_invalid_province_codes():
    with pytest.raises(ValidationError, match="Invalid province code"):
        PopulationFilterConfig(
            province_codes=["6", "006", "ANKARA"],
        )


def test_reject_unsupported_extra_fields():
    with pytest.raises(ValidationError):
        ScenarioConfig(
            scenario_id="test_extra",
            name="Extra Field Test",
            description="Testing extra forbidden fields.",
            location=ScenarioLocation(province_code="06", province_name="Ankara"),
            policy=PolicyConfig(
                category="transportation",
                type="fare_increase",
                parameters=PolicyParameters(baseline_fare=20.0),
            ),
            questions=[
                QuestionConfig(
                    id="q1",
                    text="Sample text?",
                    options=[
                        QuestionOption(id="opt_a", label="A"),
                        QuestionOption(id="opt_b", label="B"),
                    ],
                )
            ],
            invented_rogue_field="NOT_ALLOWED",
        )
