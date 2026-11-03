"""SocietyTwin Scenario Engine Module.

Provides comprehensive support for:
- Defining, loading, and validating public policy simulation scenarios.
- Evaluating synthetic resident eligibility with explicit missing-attribute diagnostics.
- Rendering agent prompts and validating structured responses.
"""

try:
    from .adapter import (
        ScenarioConflictError,
        UnsupportedQuestionTypeError,
        get_scenario,
        list_available_scenarios,
        save_custom_scenario,
        scenario_to_experiment_definition,
    )
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
    from .compiler import compile_scenario_from_prompt
    from .prompt_renderer import render_scenario_prompt
    from .response_validator import (
        AgentResponseEnvelope,
        ResponseStatus,
        validate_agent_response,
    )
    from .schema import (
        TEMPLATE_FIELDS,
        PolicyConfig,
        PolicyParameters,
        PopulationFilterConfig,
        QuestionConfig,
        QuestionOption,
        ScenarioConfig,
        ScenarioLocation,
        ScenarioMetadata,
        UnknownQuestionError,
        template_fields,
    )
except ImportError:
    from scenarios.adapter import (  # type: ignore
        ScenarioConflictError,
        UnsupportedQuestionTypeError,
        get_scenario,
        list_available_scenarios,
        save_custom_scenario,
        scenario_to_experiment_definition,
    )
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
    from scenarios.compiler import compile_scenario_from_prompt  # type: ignore
    from scenarios.prompt_renderer import render_scenario_prompt  # type: ignore
    from scenarios.response_validator import (  # type: ignore
        AgentResponseEnvelope,
        ResponseStatus,
        validate_agent_response,
    )
    from scenarios.schema import (  # type: ignore
        TEMPLATE_FIELDS,
        PolicyConfig,
        PolicyParameters,
        PopulationFilterConfig,
        QuestionConfig,
        QuestionOption,
        ScenarioConfig,
        ScenarioLocation,
        ScenarioMetadata,
        UnknownQuestionError,
        template_fields,
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
    "UnknownQuestionError",
    "template_fields",
    "TEMPLATE_FIELDS",
    # Loader
    "load_scenario",
    "save_scenario",
    "ScenarioError",
    "ScenarioNotFoundError",
    "ScenarioParseError",
    "ScenarioValidationError",
    # Adapter
    "list_available_scenarios",
    "get_scenario",
    "save_custom_scenario",
    "scenario_to_experiment_definition",
    "UnsupportedQuestionTypeError",
    "ScenarioConflictError",
    # Compiler
    "compile_scenario_from_prompt",
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
