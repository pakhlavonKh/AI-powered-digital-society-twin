"""Purpose-specific acceptance policies for synthetic populations and personas (Phase 4).

This module implements a dedicated policy evaluation layer that **consumes** existing
validation reports (`PopulationValidationReport`, `DependencyValidationReport`,
`CombinedQualityReport`, or their serialized dictionary forms) and persona/population
contracts **without duplicating statistical validation logic**.

Separation of Concerns
----------------------
- **Validation** answers: *Did a specific statistical check pass, fail, or remain
  not evaluable against registered evidence?* (`pass` | `fail` | `not_evaluable`)
- **Acceptance Policy** answers: *Can this validated population or persona projection
  be used for a declared downstream purpose?* (`accepted` | `restricted` | `rejected`)

Explicit Decision Semantics
---------------------------
- ``"accepted"``:
  All mandatory validation checks for the declared use have status ``"pass"``, all
  required structural/identity/linkage evidence is present and valid, and all
  advisory checks for the declared use also pass.
- ``"restricted"``:
  All mandatory validation checks for the declared use have status ``"pass"`` and all
  required structural/identity/linkage evidence is present, **but** one or more
  *optional/advisory* checks failed or are ``"not_evaluable"``, or non-blocking
  scope limitations apply that must be surfaced as explicit caveats in downstream
  reports.
  **CRITICAL INVARIANT**: A failed or ``"not_evaluable"`` **mandatory** check, or
  missing required structural/linkage evidence, can **NEVER** be downgraded to
  ``"restricted"``; it **ALWAYS** results in ``"rejected"``.
- ``"rejected"``:
  One or more mandatory validation checks failed (``"fail"``), could not be evaluated
  (``"not_evaluable"``), or are missing from the report; OR required resident
  identities, statistical universe compatibility, household membership linkage, or
  required persona projection attributes are missing or incompatible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Sequence

PolicyDecisionStatus = Literal["accepted", "restricted", "rejected"]

POLICY_ENGINE_VERSION = "1.0.0"

# Canonical check ID aliases so both internal check_ids (e.g. "margin_age")
# and human-readable check names in UI dicts map consistently.
_CHECK_ALIAS_MAP: dict[str, str] = {
    "k3:margin:age": "margin_age",
    "margin_age": "margin_age",
    "age_distribution": "margin_age",
    "age_group_5yr": "margin_age",
    "age": "margin_age",
    "k3:margin:sex": "margin_sex",
    "margin_sex": "margin_sex",
    "sex_distribution": "margin_sex",
    "sex": "margin_sex",
    "k3:margin:age_sex": "margin_age_sex",
    "margin_age_sex": "margin_age_sex",
    "age_sex_joint": "margin_age_sex",
    "age_by_sex": "margin_age_sex",
    "age_sex": "margin_age_sex",
    "k3:margin:marital_status": "margin_marital",
    "margin_marital": "margin_marital",
    "margin_marital_status": "margin_marital",
    "marital_status_distribution": "margin_marital",
    "marital_status": "margin_marital",
    "k3:margin:education": "margin_education",
    "margin_education": "margin_education",
    "education_distribution": "margin_education",
    "education_level": "margin_education",
    "education": "margin_education",
    "k3:margin:employment_status": "margin_labour_force",
    "margin_labour_force": "margin_labour_force",
    "margin_employment_status": "margin_labour_force",
    "labour_force_distribution": "margin_labour_force",
    "employment_status": "margin_labour_force",
    "k3:margin:household_size": "margin_household_size",
    "margin_household_size": "margin_household_size",
    "household_size_distribution": "margin_household_size",
    "household_size": "margin_household_size",
    "k3:margin:household_type": "margin_household_type",
    "margin_household_type": "margin_household_type",
    "household_type_distribution": "margin_household_type",
    "household_type": "margin_household_type",
    "joint_age_marital": "cond_age_marital",
    "cond_age_marital": "cond_age_marital",
    "age_by_marital": "cond_age_marital",
    "joint_sex_age_marital": "cond_sex_age_marital",
    "cond_sex_age_marital": "cond_sex_age_marital",
    "joint_age_education": "cond_age_education",
    "cond_age_education": "cond_age_education",
    "age_by_education": "cond_age_education",
    "joint_age_employment": "cond_age_employment",
    "cond_age_employment": "cond_age_employment",
    "age_by_employment": "cond_age_employment",
    "joint_household_size_type": "joint_household_size_type",
    "household_size_by_type": "joint_household_size_type",
    "district_allocation": "district_allocation",
    "district_allocation_check": "district_allocation",
}


@dataclass(frozen=True)
class PolicyDecision:
    """Structured decision record produced by an acceptance policy evaluation."""

    policy_id: str
    policy_name: str
    policy_version: str
    declared_use: str
    required_check_ids: tuple[str, ...]
    check_results: dict[str, str]
    unavailable_required_evidence: tuple[str, ...]
    decision: PolicyDecisionStatus
    reasons: tuple[str, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def acceptance_decision(self) -> PolicyDecisionStatus:
        """Alias for ``decision`` for backward compatibility with callers."""
        return self.decision

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["acceptance_decision"] = self.decision
        return payload


def _normalize_check_key(raw_key: str) -> str:
    cleaned = raw_key.strip()
    lowered = cleaned.lower().replace(" ", "_").replace("-", "_")
    if lowered in _CHECK_ALIAS_MAP:
        return _CHECK_ALIAS_MAP[lowered]
    if cleaned in _CHECK_ALIAS_MAP:
        return _CHECK_ALIAS_MAP[cleaned]
    # Heuristic matching for UI check names such as "Age Distribution (5-year)"
    if "age" in lowered and "sex" in lowered and "marital" in lowered:
        return "cond_sex_age_marital"
    if "age" in lowered and "marital" in lowered:
        return "cond_age_marital"
    if "age" in lowered and "education" in lowered:
        return "cond_age_education"
    if "age" in lowered and ("employ" in lowered or "labour" in lowered):
        return "cond_age_employment"
    if "age" in lowered and "sex" in lowered:
        return "margin_age_sex"
    if "household" in lowered and "size" in lowered and "type" in lowered:
        return "joint_household_size_type"
    if "household" in lowered and "size" in lowered:
        return "margin_household_size"
    if "household" in lowered and "type" in lowered:
        return "margin_household_type"
    if "age" in lowered:
        return "margin_age"
    if "sex" in lowered:
        return "margin_sex"
    if "marital" in lowered:
        return "margin_marital"
    if "education" in lowered:
        return "margin_education"
    if "labour" in lowered or "employ" in lowered:
        return "margin_labour_force"
    if "district" in lowered:
        return "district_allocation"
    return cleaned


def _normalize_status(item: Any) -> str:
    """Extract normalized status ('pass' | 'fail' | 'not_evaluable') from a check object or dict.

    If a serialized UI check dict explicitly sets ``passed: False``, that takes precedence
    as ``"fail"`` even if an older ``status`` field was present.
    """
    if isinstance(item, Mapping):
        if "passed" in item and item["passed"] is not None:
            passed_val = bool(item["passed"])
            raw_status = str(item.get("status", "")).strip().lower()
            if not passed_val:
                if raw_status == "not_evaluable":
                    return "not_evaluable"
                return "fail"
            return "pass"
        raw_status = str(item.get("status", "")).strip().lower()
        if raw_status in {"pass", "passed", "valid", "ok"}:
            return "pass"
        if raw_status in {"fail", "failed", "invalid", "error"}:
            return "fail"
        if raw_status in {"not_evaluable", "unavailable", "skipped"}:
            return "not_evaluable"
        return "not_evaluable"

    status_attr = getattr(item, "status", None)
    if status_attr is not None:
        raw_status = str(status_attr).strip().lower()
        if raw_status in {"pass", "passed", "valid", "ok"}:
            return "pass"
        if raw_status in {"fail", "failed", "invalid", "error"}:
            return "fail"
        return "not_evaluable"

    passed_attr = getattr(item, "passed", None)
    if passed_attr is not None:
        return "pass" if bool(passed_attr) else "fail"
    return "not_evaluable"


def _extract_checks(report: Any) -> dict[str, str]:
    """Extract canonical check_id -> status ('pass' | 'fail' | 'not_evaluable') from a report."""
    results: dict[str, str] = {}

    def _record_item(item: Any) -> None:
        if isinstance(item, Mapping):
            raw_id = str(item.get("name") or item.get("check_id") or item.get("id") or "")
            alt_id = str(item.get("check_id") or "")
        else:
            raw_id = str(getattr(item, "check_id", "") or getattr(item, "margin", "") or getattr(item, "name", "") or "")
            alt_id = str(getattr(item, "margin", "") or "")
        if not raw_id:
            return
        norm_status = _normalize_status(item)
        canonical_key = _normalize_check_key(raw_id)
        results[canonical_key] = norm_status
        results[raw_id] = norm_status
        if alt_id:
            results[_normalize_check_key(alt_id)] = norm_status

    # 1. CombinedQualityReport attributes (`population_report`, `dependency_report`, `checks`)
    pop_rep = getattr(report, "population_report", None) or getattr(report, "population_validation", None)
    if pop_rep is not None:
        for seq_name in ("checks", "marginal_checks", "conditional_checks", "household_checks"):
            for chk in getattr(pop_rep, seq_name, ()) or ():
                _record_item(chk)

    dep_rep = getattr(report, "dependency_report", None) or getattr(report, "dependency_validation", None)
    if dep_rep is not None:
        for seq_name in (
            "supported_joint_checks",
            "unverified_relationships",
            "calibrated_margins",
            "conditional_checks",
            "household_checks",
            "district_checks",
        ):
            for chk in getattr(dep_rep, seq_name, ()) or ():
                _record_item(chk)

    # 2. Direct PopulationValidationReport, DependencyValidationReport, or CombinedQualityReport.checks
    for seq_name in (
        "checks",
        "marginal_checks",
        "supported_joint_checks",
        "unverified_relationships",
        "conditional_checks",
        "household_checks",
        "district_checks",
    ):
        for chk in getattr(report, seq_name, ()) or ():
            _record_item(chk)

    # 3. Dictionary representation (e.g. to_ui_dict() or raw JSON report)
    if isinstance(report, Mapping):
        if "population_validation" in report and isinstance(report["population_validation"], Mapping):
            pv = report["population_validation"]
            for seq_name in ("marginal_checks", "conditional_checks", "household_checks"):
                for chk in pv.get(seq_name, ()) or ():
                    _record_item(chk)
        if "dependency_validation" in report and isinstance(report["dependency_validation"], Mapping):
            dv = report["dependency_validation"]
            for seq_name in ("conditional_checks", "household_checks", "district_checks"):
                for chk in dv.get(seq_name, ()) or ():
                    _record_item(chk)
        for seq_name in ("marginal_checks", "conditional_checks", "household_checks", "district_checks", "checks"):
            if seq_name in report and isinstance(report[seq_name], Sequence):
                for chk in report[seq_name]:
                    _record_item(chk)

    return results


def _extract_population_metadata(report: Any, population: Any = None) -> dict[str, Any]:
    """Extract resident identity and household linkage metadata from report and/or population."""
    meta: dict[str, Any] = {
        "population_id": "",
        "resident_count": 0,
        "has_valid_resident_identities": True,
        "has_verified_household_linkage": False,
        "limitations": [],
    }

    # Check report attributes
    if isinstance(report, Mapping):
        meta["population_id"] = str(
            report.get("population_id")
            or report.get("population_validation", {}).get("population_id", "")
            or ""
        )
        meta["resident_count"] = int(
            report.get("resident_count")
            or report.get("population_validation", {}).get("resident_count", 0)
            or 0
        )
        if "has_verified_household_linkage" in report:
            meta["has_verified_household_linkage"] = bool(report["has_verified_household_linkage"])
        if "has_valid_resident_identities" in report:
            meta["has_valid_resident_identities"] = bool(report["has_valid_resident_identities"])
        for lim in report.get("known_limitations", ()) or ():
            meta["limitations"].append(str(lim))
        pv = report.get("population_validation")
        if isinstance(pv, Mapping):
            for lim in pv.get("known_limitations", ()) or ():
                meta["limitations"].append(str(lim))
    else:
        pop_val = getattr(report, "population_validation", report)
        meta["population_id"] = str(
            getattr(report, "population_id", "")
            or getattr(pop_val, "population_id", "")
            or ""
        )
        meta["resident_count"] = int(
            getattr(pop_val, "resident_count", 0) or 0
        )
        for lim in getattr(report, "known_limitations", ()) or ():
            meta["limitations"].append(str(lim))
        if pop_val is not report:
            for lim in getattr(pop_val, "known_limitations", ()) or ():
                meta["limitations"].append(str(lim))

    # Inspect population object if provided directly
    if population is not None:
        residents = getattr(population, "residents", None)
        if residents is None and isinstance(population, Mapping):
            residents = population.get("residents")
        if residents is not None:
            meta["resident_count"] = len(residents)
            ids = [
                (r.get("resident_id") if isinstance(r, Mapping) else getattr(r, "resident_id", None))
                for r in residents
            ]
            if not ids or any(not rid or not str(rid).strip() for rid in ids) or len(set(ids)) != len(ids):
                meta["has_valid_resident_identities"] = False
            else:
                meta["has_valid_resident_identities"] = True

            # Check whether residents actually have linked household_id values matching households
            hh_ids_on_residents = [
                (r.get("household_id") if isinstance(r, Mapping) else getattr(r, "household_id", None))
                for r in residents
            ]
            households = getattr(population, "households", None)
            if households is None and isinstance(population, Mapping):
                households = population.get("households")
            known_hh_ids = set()
            if households:
                for hh in households:
                    hid = hh.get("household_id") if isinstance(hh, Mapping) else getattr(hh, "household_id", None)
                    if hid:
                        known_hh_ids.add(str(hid))
            if (
                hh_ids_on_residents
                and all(hid is not None and str(hid).strip() != "" for hid in hh_ids_on_residents)
                and (not known_hh_ids or all(str(hid) in known_hh_ids for hid in hh_ids_on_residents))
            ):
                meta["has_verified_household_linkage"] = True
            else:
                meta["has_verified_household_linkage"] = False

    if not meta["population_id"] and meta["resident_count"] <= 0:
        # Check if any checks were extracted; if report has checks, assume resident identities exist unless flagged
        pass

    return meta


def evaluate_policy_a_demographic_survey(
    report: Any,
    *,
    population: Any = None,
    mandatory_check_ids: Sequence[str] = ("margin_age", "margin_sex", "margin_age_sex"),
    advisory_check_ids: Sequence[str] = ("margin_marital", "margin_education", "margin_labour_force"),
    declared_use: str = "Basic demographic survey (individual-level age/sex/demographic marginals; household-independent)",
) -> PolicyDecision:
    """Evaluate Policy A — Basic Demographic Survey.

    Requirements:
    - Appropriate demographic distributions (mandatory: ``margin_age``, ``margin_sex``, ``margin_age_sex``).
    - Valid resident identities and relevant population evidence.
    - Missing household membership linkage MUST NOT reject an age/sex demographic survey
      that does not depend on households.
    - If all mandatory checks pass (`"pass"`), missing household linkage is recorded in
      ``limitations``, and the population is ``"accepted"`` (or ``"restricted"`` if an
      explicitly requested non-mandatory advisory check failed).
    - If any mandatory check fails or is ``"not_evaluable"``, the decision is ``"rejected"``
      (never downgraded to ``"restricted"``).
    """
    extracted = _extract_checks(report)
    meta = _extract_population_metadata(report, population=population)

    canon_mandatory = tuple(dict.fromkeys(_normalize_check_key(cid) for cid in mandatory_check_ids))
    canon_advisory = tuple(
        dict.fromkeys(
            _normalize_check_key(cid)
            for cid in advisory_check_ids
            if _normalize_check_key(cid) not in canon_mandatory
        )
    )

    check_results: dict[str, str] = {}
    unavailable_evidence: list[str] = []
    failed_mandatory: list[str] = []
    failed_advisory: list[str] = []
    reasons: list[str] = []
    limitations: list[str] = []

    if not meta["has_valid_resident_identities"]:
        reasons.append("Resident identity validation failed: missing, empty, or duplicate resident_id values.")

    for cid in canon_mandatory:
        status = extracted.get(cid, "not_evaluable")
        check_results[cid] = status
        if status == "fail":
            failed_mandatory.append(cid)
            reasons.append(f"Mandatory demographic check '{cid}' failed validation.")
        elif status != "pass":
            unavailable_evidence.append(cid)
            failed_mandatory.append(cid)
            reasons.append(
                f"Mandatory demographic check '{cid}' is '{status}' (missing or non-evaluable required evidence)."
            )

    for cid in canon_advisory:
        if cid in extracted:
            status = extracted[cid]
            check_results[cid] = status
            if status != "pass":
                failed_advisory.append(cid)
                limitations.append(
                    f"Advisory demographic check '{cid}' has status '{status}'; use caution if conditioning on '{cid}'."
                )

    # Note household independence explicitly in limitations without rejecting
    hh_size_status = extracted.get("margin_household_size", "not_evaluable")
    if hh_size_status != "pass" or not meta["has_verified_household_linkage"]:
        limitations.append(
            "Household membership linkage is unverified/unlinked on individual residents; "
            "this is permitted for Policy A (individual demographic survey) but precludes household-level analysis."
        )

    for lim in meta["limitations"]:
        if lim not in limitations:
            limitations.append(lim)

    # Decision determination (mandatory failure can NEVER be restricted)
    if not meta["has_valid_resident_identities"] or failed_mandatory or unavailable_evidence:
        decision: PolicyDecisionStatus = "rejected"
    elif failed_advisory:
        decision = "restricted"
        reasons.append(
            f"All mandatory checks ({', '.join(canon_mandatory)}) passed, but advisory checks "
            f"({', '.join(failed_advisory)}) did not pass; accepted with restrictions."
        )
    else:
        decision = "accepted"
        reasons.append(
            f"All mandatory demographic checks ({', '.join(canon_mandatory)}) and evaluated advisory checks passed; "
            "household linkage is not required for Policy A."
        )

    return PolicyDecision(
        policy_id="policy_a_demographic_survey",
        policy_name="Policy A — Basic Demographic Survey",
        policy_version=POLICY_ENGINE_VERSION,
        declared_use=declared_use,
        required_check_ids=canon_mandatory,
        check_results=check_results,
        unavailable_required_evidence=tuple(unavailable_evidence),
        decision=decision,
        reasons=tuple(reasons),
        limitations=tuple(limitations),
    )


def evaluate_policy_b_household_simulation(
    report: Any,
    *,
    population: Any = None,
    mandatory_check_ids: Sequence[str] = (
        "margin_age",
        "margin_sex",
        "margin_household_size",
        "margin_household_type",
        "joint_household_size_type",
    ),
    declared_use: str = "Household-dependent simulation requiring verified resident-to-household linkage and compatible statistical universes",
) -> PolicyDecision:
    """Evaluate Policy B — Household-Dependent Simulation.

    Requirements:
    - Validated household size and household type marginal and joint distributions
      (``margin_household_size``, ``margin_household_type``, ``joint_household_size_type``).
    - Compatible statistical universes between person-level and household-level tables.
    - Verified resident-to-household membership linkage (``household_id`` linking
      individual residents to concrete households, rather than independently generated
      unlinked household records).
    - Independently generated household records without real membership linkage -> ``"rejected"``.
    """
    extracted = _extract_checks(report)
    meta = _extract_population_metadata(report, population=population)

    canon_mandatory = tuple(dict.fromkeys(_normalize_check_key(cid) for cid in mandatory_check_ids))
    check_results: dict[str, str] = {}
    unavailable_evidence: list[str] = []
    failed_mandatory: list[str] = []
    reasons: list[str] = []
    limitations: list[str] = list(meta["limitations"])

    if not meta["has_valid_resident_identities"]:
        reasons.append("Resident identity validation failed: missing, empty, or duplicate resident_id values.")

    for cid in canon_mandatory:
        status = extracted.get(cid, "not_evaluable")
        check_results[cid] = status
        if status == "fail":
            failed_mandatory.append(cid)
            reasons.append(f"Mandatory household/demographic check '{cid}' failed validation.")
        elif status != "pass":
            unavailable_evidence.append(cid)
            failed_mandatory.append(cid)
            reasons.append(
                f"Mandatory household check '{cid}' is '{status}': required household evidence or "
                "resident-to-household membership linkage is unavailable."
            )

    if not meta["has_verified_household_linkage"]:
        if "resident_household_membership_linkage" not in unavailable_evidence:
            unavailable_evidence.append("resident_household_membership_linkage")
        reasons.append(
            "Household membership linkage is missing/unlinked: household records are generated "
            "independently without verified resident-to-household assignment (household_id is None)."
        )
        limitations.append(
            "Individual residents have household_id=None, household_size_class=None, and household_type=None; "
            "person-level ADNKS universe and ADNKS household universe are not linked at the microdata level."
        )

    if (
        not meta["has_valid_resident_identities"]
        or failed_mandatory
        or unavailable_evidence
        or not meta["has_verified_household_linkage"]
    ):
        decision: PolicyDecisionStatus = "rejected"
    else:
        decision = "accepted"
        reasons.append(
            "All mandatory household marginal/joint checks passed and resident-to-household linkage is verified."
        )

    return PolicyDecision(
        policy_id="policy_b_household_simulation",
        policy_name="Policy B — Household-Dependent Simulation",
        policy_version=POLICY_ENGINE_VERSION,
        declared_use=declared_use,
        required_check_ids=canon_mandatory,
        check_results=check_results,
        unavailable_required_evidence=tuple(unavailable_evidence),
        decision=decision,
        reasons=tuple(reasons),
        limitations=tuple(limitations),
    )


# Supported MatrAIx persona projection fields per src/societytwin/national/personas.py
_MATRAIX_SUPPORTED_FIELDS: frozenset[str] = frozenset(
    {
        "resident_id",
        "synthetic_id",
        "province_code",
        "district_code",
        "district_name",
        "urbanicity_proxy",
        "sex",
        "age_years",
        "age",
        "age_group_5yr",
        "marital_status",
        "education_level",
        "employment_status",
        "labour_status",
        "occupation_major_group",
        "population_weight",
        "analysis_weight",
    }
)

_MATRAIX_PERMITTED_SIDECAR_FIELDS: frozenset[str] = frozenset(
    {
        "degurba_class",
    }
)

_MATRAIX_FORBIDDEN_UNLINKED_HOUSEHOLD_FIELDS: frozenset[str] = frozenset(
    {
        "household_id",
        "household_size_class",
        "household_type",
    }
)

# Required core demographic groups for a valid MatrAIx persona projection
_MATRAIX_REQUIRED_FIELD_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("resident_id", ("resident_id", "synthetic_id")),
    ("age", ("age_years", "age", "age_group_5yr")),
    ("sex", ("sex",)),
    ("marital_status", ("marital_status",)),
    ("education_level", ("education_level",)),
    ("employment_status", ("employment_status", "labour_status")),
    ("province_code", ("province_code",)),
)


def evaluate_policy_c_matraix_persona_projection(
    persona_or_population: Any,
    *,
    requested_fields: Sequence[str] | None = None,
    sidecar_fields: Sequence[str] | None = None,
    validation_report: Any | None = None,
    declared_use: str = "MatrAIx persona projection for LLM agent conditioning",
) -> PolicyDecision:
    """Evaluate Policy C — MatrAIx Persona Projection.

    Requirements:
    - Valid resident identity (non-empty ``resident_id`` / ``synthetic_id``).
    - Supported core demographic fields present and non-empty (age, sex, marital_status,
      education_level, employment_status/labour_status, province_code).
    - Only permitted sidecar attributes (``degurba_class``) when sidecar attributes are included.
    - Explicit rejection when:
      1. Required demographic fields or resident identity are missing/None/empty;
      2. Unsupported or unlinked attributes (e.g. ``household_size_class``, ``household_type``,
         or arbitrary unsupported fields like ``telepathic_power``) are present on a persona
         projection or requested in ``requested_fields``;
      3. A ``PersonaProjection`` carries non-empty ``unsupported_attributes``.
    """
    required_check_ids = (
        "persona_resident_identity",
        "persona_required_demographic_fields",
        "persona_supported_attribute_whitelist",
        "persona_sidecar_compatibility",
    )
    check_results: dict[str, str] = {cid: "pass" for cid in required_check_ids}
    unavailable_evidence: list[str] = []
    reasons: list[str] = []
    limitations: list[str] = []

    # Normalize input into a list of records/dicts to inspect
    records: list[Any]
    if hasattr(persona_or_population, "residents"):
        records = list(getattr(persona_or_population, "residents"))
    elif isinstance(persona_or_population, Sequence) and not isinstance(
        persona_or_population, (str, bytes, Mapping)
    ):
        records = list(persona_or_population)
    else:
        records = [persona_or_population]

    if not records:
        check_results["persona_resident_identity"] = "fail"
        unavailable_evidence.append("persona_records")
        reasons.append("No persona or resident records provided for MatrAIx projection.")
        return PolicyDecision(
            policy_id="policy_c_matraix_persona_projection",
            policy_name="Policy C — MatrAIx Persona Projection",
            policy_version=POLICY_ENGINE_VERSION,
            declared_use=declared_use,
            required_check_ids=required_check_ids,
            check_results=check_results,
            unavailable_required_evidence=tuple(unavailable_evidence),
            decision="rejected",
            reasons=tuple(reasons),
            limitations=tuple(limitations),
        )

    missing_required_fields: set[str] = set()
    unsupported_fields_found: set[str] = set()
    invalid_identity_found = False
    unlinked_sidecar_warning = False

    # Check requested_fields if explicitly supplied
    if requested_fields is not None:
        for req_field in requested_fields:
            if req_field not in _MATRAIX_SUPPORTED_FIELDS and req_field not in _MATRAIX_PERMITTED_SIDECAR_FIELDS:
                unsupported_fields_found.add(req_field)

    if sidecar_fields is not None:
        for sc_field in sidecar_fields:
            if sc_field not in _MATRAIX_PERMITTED_SIDECAR_FIELDS:
                unsupported_fields_found.add(sc_field)

    for rec in records:
        # Case 1: PersonaProjection dataclass from societytwin.national.personas
        if hasattr(rec, "supported_attributes") and hasattr(rec, "unsupported_attributes"):
            rid = getattr(rec, "resident_id", "")
            if not rid or not str(rid).strip():
                invalid_identity_found = True
            supp = dict(getattr(rec, "supported_attributes", {}) or {})
            supp["resident_id"] = rid
            unsupp = tuple(getattr(rec, "unsupported_attributes", ()) or ())
            for u_field in unsupp:
                unsupported_fields_found.add(str(u_field))
            sidecar = dict(getattr(rec, "sidecar_attributes", {}) or {})
            for s_key in sidecar:
                if s_key not in _MATRAIX_PERMITTED_SIDECAR_FIELDS:
                    unsupported_fields_found.add(str(s_key))
            rec_map = supp
        elif isinstance(rec, Mapping):
            rec_map = dict(rec)
            # Check for any unknown/unsupported keys in the dict
            for k, v in rec_map.items():
                if k in _MATRAIX_FORBIDDEN_UNLINKED_HOUSEHOLD_FIELDS:
                    # On raw ResidentRecord dicts household fields are None; if non-None or explicitly projected, flag
                    if v is not None:
                        unsupported_fields_found.add(k)
                elif k not in _MATRAIX_SUPPORTED_FIELDS and k not in _MATRAIX_PERMITTED_SIDECAR_FIELDS:
                    unsupported_fields_found.add(k)
                elif k in _MATRAIX_PERMITTED_SIDECAR_FIELDS and v is None:
                    unlinked_sidecar_warning = True
        else:
            # ResidentRecord or custom object
            rec_map = {}
            for attr in (
                "resident_id",
                "province_code",
                "district_code",
                "district_name",
                "urbanicity_proxy",
                "sex",
                "age_years",
                "age_group_5yr",
                "marital_status",
                "education_level",
                "employment_status",
                "occupation_major_group",
            ):
                if hasattr(rec, attr):
                    rec_map[attr] = getattr(rec, attr)

        # Verify resident identity
        rid_val = rec_map.get("resident_id") or rec_map.get("synthetic_id")
        if rid_val is None or not str(rid_val).strip():
            invalid_identity_found = True

        # Verify required demographic groups
        for canonical_name, candidate_keys in _MATRAIX_REQUIRED_FIELD_GROUPS:
            has_value = any(
                (k in rec_map and rec_map[k] is not None and str(rec_map[k]).strip() != "")
                for k in candidate_keys
            )
            if not has_value:
                missing_required_fields.add(canonical_name)

        # Verify requested_fields are present and non-None on the record
        if requested_fields is not None:
            for req_field in requested_fields:
                if req_field in _MATRAIX_SUPPORTED_FIELDS:
                    val = rec_map.get(req_field)
                    if val is None or str(val).strip() == "":
                        missing_required_fields.add(req_field)

    if invalid_identity_found:
        check_results["persona_resident_identity"] = "fail"
        unavailable_evidence.append("resident_id")
        reasons.append("Persona projection is missing a valid non-empty resident_id / synthetic_id.")

    if missing_required_fields:
        check_results["persona_required_demographic_fields"] = "fail"
        sorted_missing = sorted(missing_required_fields)
        unavailable_evidence.extend(sorted_missing)
        reasons.append(
            f"Missing required MatrAIx persona projection fields: {', '.join(sorted_missing)}."
        )

    if unsupported_fields_found:
        check_results["persona_supported_attribute_whitelist"] = "fail"
        sorted_unsupp = sorted(unsupported_fields_found)
        unavailable_evidence.extend(sorted_unsupp)
        reasons.append(
            f"Incompatible or unsupported MatrAIx persona projection fields requested/present: "
            f"{', '.join(sorted_unsupp)}."
        )

    if unlinked_sidecar_warning:
        check_results["persona_sidecar_compatibility"] = "not_evaluable"
        limitations.append(
            "Sidecar attribute 'degurba_class' was present with None value; sidecar conditioning is unavailable."
        )

    # Also check underlying population report if provided
    if validation_report is not None:
        pop_decision = evaluate_policy_a_demographic_survey(validation_report)
        for cid, st in pop_decision.check_results.items():
            check_results[cid] = st
        if pop_decision.decision == "rejected":
            reasons.extend(pop_decision.reasons)
            unavailable_evidence.extend(pop_decision.unavailable_required_evidence)

    has_mandatory_failure = (
        invalid_identity_found
        or bool(missing_required_fields)
        or bool(unsupported_fields_found)
        or any(
            check_results[cid] != "pass"
            for cid in (
                "persona_resident_identity",
                "persona_required_demographic_fields",
                "persona_supported_attribute_whitelist",
            )
        )
        or (validation_report is not None and evaluate_policy_a_demographic_survey(validation_report).decision == "rejected")
    )

    if has_mandatory_failure:
        decision: PolicyDecisionStatus = "rejected"
    elif unlinked_sidecar_warning:
        decision = "restricted"
        reasons.append(
            "All mandatory persona projection fields are valid, but optional sidecar attribute value is missing."
        )
    else:
        decision = "accepted"
        reasons.append(
            "All required resident identity and MatrAIx demographic projection fields are present and supported."
        )

    limitations.append(
        "MatrAIx persona projection conditions only on supported individual-level demographic attributes "
        "(and permitted sidecar degurba_class); household-level attributes are excluded unless verified linkage exists."
    )

    return PolicyDecision(
        policy_id="policy_c_matraix_persona_projection",
        policy_name="Policy C — MatrAIx Persona Projection",
        policy_version=POLICY_ENGINE_VERSION,
        declared_use=declared_use,
        required_check_ids=required_check_ids,
        check_results=check_results,
        unavailable_required_evidence=tuple(dict.fromkeys(unavailable_evidence)),
        decision=decision,
        reasons=tuple(reasons),
        limitations=tuple(limitations),
    )


def evaluate_acceptance_policy(
    policy_id_or_name: str,
    target: Any,
    *,
    population: Any = None,
    requested_fields: Sequence[str] | None = None,
    sidecar_fields: Sequence[str] | None = None,
    validation_report: Any | None = None,
) -> PolicyDecision:
    """Dispatch evaluation to Policy A, Policy B, or Policy C by policy ID or name."""
    norm = policy_id_or_name.strip().lower()
    if norm in {
        "policy_a",
        "policy_a_demographic_survey",
        "demographic_survey",
        "basic_demographic_survey",
    }:
        return evaluate_policy_a_demographic_survey(target, population=population)
    if norm in {
        "policy_b",
        "policy_b_household_simulation",
        "household_simulation",
        "household_dependent_simulation",
    }:
        return evaluate_policy_b_household_simulation(target, population=population)
    if norm in {
        "policy_c",
        "policy_c_matraix_persona_projection",
        "matraix_persona_projection",
        "persona_projection",
    }:
        return evaluate_policy_c_matraix_persona_projection(
            target,
            requested_fields=requested_fields,
            sidecar_fields=sidecar_fields,
            validation_report=validation_report,
        )
    raise ValueError(
        f"Unknown acceptance policy '{policy_id_or_name}'. "
        "Expected 'policy_a_demographic_survey', 'policy_b_household_simulation', "
        "or 'policy_c_matraix_persona_projection'."
    )
