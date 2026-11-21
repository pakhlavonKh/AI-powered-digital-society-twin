"""Offline multi-semester university policy simulation package (Milestone 2)."""

from __future__ import annotations

try:
    from .cohort import (
        build_demo_course_catalog,
        build_synthetic_university_cohort,
        student_cohort_from_placement_handoff,
    )
    from .decision_engine import choose_student_action, feasible_choices_for_student
    from .experiments import run_replicated_university_experiment, run_tuition_sensitivity_sweep
    from .financial_ledger import apply_university_economic_policy, compute_semester_ledger
    from .models import (
        ALL_CHOICE_ACTIONS,
        DEFAULT_UNIVERSITY_DISCLAIMER,
        UNIVERSITY_ENGINE_VERSION,
        AgentDecisionRecord,
        ChoiceAction,
        CourseOffering,
        SemesterFinancialLedger,
        SemesterSnapshot,
        StudentAgentRecord,
        StudentState,
        UniversityComparisonReport,
        UniversityRuleset,
        UniversitySimulationManifest,
        UniversitySimulationResult,
        UtilityWeights,
    )
    from .semester_engine import run_university_simulation
except ImportError:
    from scenarios.university.cohort import (  # type: ignore
        build_demo_course_catalog,
        build_synthetic_university_cohort,
        student_cohort_from_placement_handoff,
    )
    from scenarios.university.decision_engine import (  # type: ignore
        choose_student_action,
        feasible_choices_for_student,
    )
    from scenarios.university.experiments import (  # type: ignore
        run_replicated_university_experiment,
        run_tuition_sensitivity_sweep,
    )
    from scenarios.university.financial_ledger import (  # type: ignore
        apply_university_economic_policy,
        compute_semester_ledger,
    )
    from scenarios.university.models import (  # type: ignore
        ALL_CHOICE_ACTIONS,
        DEFAULT_UNIVERSITY_DISCLAIMER,
        UNIVERSITY_ENGINE_VERSION,
        AgentDecisionRecord,
        ChoiceAction,
        CourseOffering,
        SemesterFinancialLedger,
        SemesterSnapshot,
        StudentAgentRecord,
        StudentState,
        UniversityComparisonReport,
        UniversityRuleset,
        UniversitySimulationManifest,
        UniversitySimulationResult,
        UtilityWeights,
    )
    from scenarios.university.semester_engine import run_university_simulation  # type: ignore

__all__ = [
    "ALL_CHOICE_ACTIONS",
    "DEFAULT_UNIVERSITY_DISCLAIMER",
    "UNIVERSITY_ENGINE_VERSION",
    "AgentDecisionRecord",
    "ChoiceAction",
    "CourseOffering",
    "SemesterFinancialLedger",
    "SemesterSnapshot",
    "StudentAgentRecord",
    "StudentState",
    "UniversityComparisonReport",
    "UniversityRuleset",
    "UniversitySimulationManifest",
    "UniversitySimulationResult",
    "UtilityWeights",
    "apply_university_economic_policy",
    "build_demo_course_catalog",
    "build_synthetic_university_cohort",
    "choose_student_action",
    "compute_semester_ledger",
    "feasible_choices_for_student",
    "run_replicated_university_experiment",
    "run_tuition_sensitivity_sweep",
    "run_university_simulation",
    "student_cohort_from_placement_handoff",
]
