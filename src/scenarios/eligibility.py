"""Population eligibility evaluation and diagnostic filtering for policy scenarios.

Evaluates synthetic resident records against scenario filter criteria,
providing explicit diagnostics for exclusions and missing attributes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Union

try:
    from .schema import PopulationFilterConfig, ScenarioConfig
except ImportError:
    from scenarios.schema import PopulationFilterConfig, ScenarioConfig  # type: ignore


class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"
    CANNOT_EVALUATE = "cannot_evaluate"


@dataclass
class ResidentEvaluation:
    """Diagnostic result of evaluating a single resident against eligibility criteria."""
    resident_id: str
    status: EligibilityStatus
    passed_criteria: list[str] = field(default_factory=list)
    failed_criteria: list[str] = field(default_factory=list)
    missing_attributes: list[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "resident_id": self.resident_id,
            "status": self.status.value,
            "passed_criteria": self.passed_criteria,
            "failed_criteria": self.failed_criteria,
            "missing_attributes": self.missing_attributes,
            "explanation": self.explanation,
        }


@dataclass
class PopulationFilterResult:
    """Aggregated results of filtering a collection of synthetic residents."""
    eligible_records: list[dict[str, Any]] = field(default_factory=list)
    excluded_records: list[dict[str, Any]] = field(default_factory=list)
    cannot_evaluate_records: list[dict[str, Any]] = field(default_factory=list)
    evaluations: list[ResidentEvaluation] = field(default_factory=list)
    total_evaluated: int = 0

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_records)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_records)

    @property
    def cannot_evaluate_count(self) -> int:
        return len(self.cannot_evaluate_records)

    def summary(self) -> dict[str, Any]:
        exclusion_reasons: dict[str, int] = {}
        missing_attrs: dict[str, int] = {}

        for ev in self.evaluations:
            for reason in ev.failed_criteria:
                exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1
            for attr in ev.missing_attributes:
                missing_attrs[attr] = missing_attrs.get(attr, 0) + 1

        return {
            "total_evaluated": self.total_evaluated,
            "eligible_count": self.eligible_count,
            "excluded_count": self.excluded_count,
            "cannot_evaluate_count": self.cannot_evaluate_count,
            "eligibility_rate": (self.eligible_count / self.total_evaluated) if self.total_evaluated > 0 else 0.0,
            "exclusion_reasons_breakdown": exclusion_reasons,
            "missing_attributes_breakdown": missing_attrs,
        }


def evaluate_resident(
    resident: dict[str, Any],
    filter_config: PopulationFilterConfig,
    id_field: str = "resident_id",
) -> ResidentEvaluation:
    """Evaluate one synthetic resident record against a PopulationFilterConfig.

    Handles missing attributes explicitly without inventing synthetic assumptions.
    """
    resident_id = str(resident.get(id_field) or resident.get("synthetic_id") or "UNKNOWN_RESIDENT")
    passed: list[str] = []
    failed: list[str] = []
    missing: list[str] = []

    # 1. Check required attributes existence
    for req in filter_config.required_attributes:
        val = resident.get(req)
        if val is None and req == "sex":
            val = resident.get("gender")
        elif val is None and req == "gender":
            val = resident.get("sex")
        if val is None or val == "" or val == "unavailable":
            missing.append(req)

    if missing:
        return ResidentEvaluation(
            resident_id=resident_id,
            status=EligibilityStatus.CANNOT_EVALUATE,
            missing_attributes=missing,
            explanation=f"Cannot evaluate eligibility: required attribute(s) missing or null: {missing}",
        )

    # 2. Check Province
    if filter_config.province_codes is not None:
        p_code = resident.get("province_code")
        if p_code is None:
            missing.append("province_code")
        else:
            p_code_str = f"{int(p_code):02d}" if isinstance(p_code, int) else str(p_code)
            if p_code_str in filter_config.province_codes:
                passed.append(f"province_code in {filter_config.province_codes}")
            else:
                failed.append(f"province_code '{p_code_str}' not in target provinces {filter_config.province_codes}")

    # 3. Check Age Bounds
    age = resident.get("age")
    if age is None:
        missing.append("age")
    else:
        try:
            age_int = int(age)
            if filter_config.minimum_age is not None:
                if age_int >= filter_config.minimum_age:
                    passed.append(f"age >= {filter_config.minimum_age}")
                else:
                    failed.append(f"age {age_int} is below minimum age {filter_config.minimum_age}")

            if filter_config.maximum_age is not None:
                if age_int <= filter_config.maximum_age:
                    passed.append(f"age <= {filter_config.maximum_age}")
                else:
                    failed.append(f"age {age_int} exceeds maximum age {filter_config.maximum_age}")
        except (ValueError, TypeError):
            failed.append(f"Invalid non-integer age value: '{age}'")

    # 4. Check Sex / Gender
    if filter_config.sexes is not None:
        sex = resident.get("sex") or resident.get("gender")
        if sex is None:
            missing.append("sex")
        else:
            if str(sex).lower() in [s.lower() for s in filter_config.sexes]:
                passed.append(f"sex in {filter_config.sexes}")
            else:
                failed.append(f"sex '{sex}' not in allowed sexes {filter_config.sexes}")

    # 5. Check Marital Status
    if filter_config.marital_statuses is not None:
        ms = resident.get("marital_status")
        if ms is None:
            missing.append("marital_status")
        else:
            if str(ms).lower() in [s.lower() for s in filter_config.marital_statuses]:
                passed.append(f"marital_status in {filter_config.marital_statuses}")
            else:
                failed.append(f"marital_status '{ms}' not in allowed {filter_config.marital_statuses}")

    # 6. Check Education Level
    if filter_config.education_levels is not None:
        ed = resident.get("education_level")
        if ed is None:
            missing.append("education_level")
        else:
            if str(ed).lower() in [s.lower() for s in filter_config.education_levels]:
                passed.append(f"education_level in {filter_config.education_levels}")
            else:
                failed.append(f"education_level '{ed}' not in allowed {filter_config.education_levels}")

    # Final verdict
    if missing:
        return ResidentEvaluation(
            resident_id=resident_id,
            status=EligibilityStatus.CANNOT_EVALUATE,
            passed_criteria=passed,
            missing_attributes=missing,
            explanation=f"Cannot evaluate eligibility: attributes missing or unobserved: {missing}",
        )

    if failed:
        return ResidentEvaluation(
            resident_id=resident_id,
            status=EligibilityStatus.EXCLUDED,
            passed_criteria=passed,
            failed_criteria=failed,
            explanation=f"Excluded from scenario: {'; '.join(failed)}",
        )

    return ResidentEvaluation(
        resident_id=resident_id,
        status=EligibilityStatus.ELIGIBLE,
        passed_criteria=passed,
        explanation="Resident satisfies all scenario eligibility criteria.",
    )


def filter_population(
    residents: list[dict[str, Any]],
    filter_or_scenario: Union[PopulationFilterConfig, ScenarioConfig],
    id_field: str = "resident_id",
) -> PopulationFilterResult:
    """Filter a collection of synthetic resident records according to scenario criteria."""
    filter_config: PopulationFilterConfig
    if isinstance(filter_or_scenario, ScenarioConfig):
        filter_config = filter_or_scenario.target_population
    else:
        filter_config = filter_or_scenario

    result = PopulationFilterResult(total_evaluated=len(residents))

    for rec in residents:
        ev = evaluate_resident(rec, filter_config, id_field=id_field)
        result.evaluations.append(ev)

        if ev.status == EligibilityStatus.ELIGIBLE:
            result.eligible_records.append(rec)
        elif ev.status == EligibilityStatus.EXCLUDED:
            result.excluded_records.append(rec)
        else:
            result.cannot_evaluate_records.append(rec)

    return result
