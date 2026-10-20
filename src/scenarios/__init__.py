"""SocietyTwin Scenario Engine Module.

Provides comprehensive support for:
- Defining, loading, and validating public policy simulation scenarios.
- Evaluating synthetic resident eligibility with explicit missing-attribute diagnostics.
- Rendering agent prompts and validating structured responses.
"""

try:
    from .eligibility import (
        EligibilityStatus,
        PopulationFilterResult,
        ResidentEvaluation,
        evaluate_resident,
        filter_population,
    )
    from .loader import (
        ScenarioError,
        ScenarioNotFoundError,
        ScenarioParseError,
        ScenarioValidationError,
        load_scenario,
        save_scenario,
    )
    from .prompt_renderer import render_scenario_prompt
    from .response_validator import (
        AgentResponseEnvelope,
        ResponseStatus,
        validate_agent_response,
    )
    from .schema import (
        PolicyConfig,
        PolicyParameters,
        PopulationFilterConfig,
        QuestionConfig,
        QuestionOption,
        ScenarioConfig,
        ScenarioLocation,
        ScenarioMetadata,
    )
except ImportError:
    from scenarios.eligibility import (  # type: ignore
        EligibilityStatus,
        PopulationFilterResult,
        ResidentEvaluation,
        evaluate_resident,
        filter_population,
    )
    from scenarios.loader import (  # type: ignore
        ScenarioError,
        ScenarioNotFoundError,
        ScenarioParseError,
        ScenarioValidationError,
        load_scenario,
        save_scenario,
    )
    from scenarios.prompt_renderer import render_scenario_prompt  # type: ignore
    from scenarios.response_validator import (  # type: ignore
        AgentResponseEnvelope,
        ResponseStatus,
        validate_agent_response,
    )
    from scenarios.schema import (  # type: ignore
        PolicyConfig,
        PolicyParameters,
        PopulationFilterConfig,
        QuestionConfig,
        QuestionOption,
        ScenarioConfig,
        ScenarioLocation,
        ScenarioMetadata,
    )

__all__ = [
    # Schema
    "ScenarioConfig",
    "PolicyConfig",
    "PolicyParameters",
    "PopulationFilterConfig",
    "QuestionConfig",
    "QuestionOption",
    "ScenarioLocation",
    "ScenarioMetadata",
    # Loader
    "load_scenario",
    "save_scenario",
    "ScenarioError",
    "ScenarioNotFoundError",
    "ScenarioParseError",
    "ScenarioValidationError",
    # Eligibility
    "evaluate_resident",
    "filter_population",
    "EligibilityStatus",
    "ResidentEvaluation",
    "PopulationFilterResult",
    # Response Validation
    "validate_agent_response",
    "AgentResponseEnvelope",
    "ResponseStatus",
    # Prompt Rendering
    "render_scenario_prompt",
]
