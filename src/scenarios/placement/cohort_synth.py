"""TÜİK-anchored synthetic candidate cohort builder and offline program/fixture loaders.

Demographics (province_code, age, sex, education_level, population_weight) are drawn
from a saved national LoadedPopulation without modifying records.parquet. Synthesized
exam scores, ranks, preferences, and financial attributes are explicitly tagged ASSUMED.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

try:
    from .models import (
        CandidateCohort,
        CandidateRecord,
        PlacementRuleset,
        ProgramOffering,
        ScoreType,
    )
except ImportError:
    from scenarios.placement.models import (  # type: ignore
        CandidateCohort,
        CandidateRecord,
        PlacementRuleset,
        ProgramOffering,
        ScoreType,
    )

from societytwin.national.cohorts import simple_random, weighted_pps
from societytwin.national.rng import Stream
from societytwin.national.store import LoadedPopulation, PopulationFilter
from societytwin.national.vocab import Evidence


def build_standalone_demo_programs() -> list[ProgramOffering]:
    """Create a compact, explicitly hypothetical multi-province program catalog for offline tests/demos."""
    return [
        ProgramOffering(
            program_id="PRG_ANK_MED_STATE",
            university_id="UNI_ANK_STATE",
            university_name="Ankara State University (Hypothetical)",
            university_type="state",
            province_code="06",
            department_name="Medicine",
            degree_level="bachelor",
            score_type="SAY",
            baraj_group="medicine",
            capacity=12,
            tuition_annual=0.0,
        ),
        ProgramOffering(
            program_id="PRG_ANK_CS_STATE",
            university_id="UNI_ANK_STATE",
            university_name="Ankara State University (Hypothetical)",
            university_type="state",
            province_code="06",
            department_name="Computer Engineering",
            degree_level="bachelor",
            score_type="SAY",
            baraj_group="engineering",
            capacity=20,
            tuition_annual=0.0,
        ),
        ProgramOffering(
            program_id="PRG_ANK_CS_FOUND_100",
            university_id="UNI_ANK_FOUND",
            university_name="Ankara Foundation University (Hypothetical)",
            university_type="foundation",
            province_code="06",
            department_name="Computer Engineering (%100 Burslu)",
            degree_level="bachelor",
            score_type="SAY",
            baraj_group="engineering",
            capacity=8,
            tuition_annual=240_000.0,
            scholarship_pct=100.0,
        ),
        ProgramOffering(
            program_id="PRG_ANK_CS_FOUND_50",
            university_id="UNI_ANK_FOUND",
            university_name="Ankara Foundation University (Hypothetical)",
            university_type="foundation",
            province_code="06",
            department_name="Computer Engineering (%50 İndirimli)",
            degree_level="bachelor",
            score_type="SAY",
            baraj_group="engineering",
            capacity=16,
            tuition_annual=240_000.0,
            scholarship_pct=50.0,
        ),
        ProgramOffering(
            program_id="PRG_ANK_CS_FOUND_PAID",
            university_id="UNI_ANK_FOUND",
            university_name="Ankara Foundation University (Hypothetical)",
            university_type="foundation",
            province_code="06",
            department_name="Computer Engineering (Ücretli)",
            degree_level="bachelor",
            score_type="SAY",
            baraj_group="engineering",
            capacity=16,
            tuition_annual=240_000.0,
            scholarship_pct=0.0,
        ),
        ProgramOffering(
            program_id="PRG_IST_LAW_STATE",
            university_id="UNI_IST_STATE",
            university_name="Istanbul State University (Hypothetical)",
            university_type="state",
            province_code="34",
            department_name="Law",
            degree_level="bachelor",
            score_type="EA",
            baraj_group="law",
            capacity=20,
            tuition_annual=0.0,
        ),
        ProgramOffering(
            program_id="PRG_IST_ECON_FOUND_50",
            university_id="UNI_IST_FOUND",
            university_name="Istanbul Foundation University (Hypothetical)",
            university_type="foundation",
            province_code="34",
            department_name="Economics (%50 İndirimli)",
            degree_level="bachelor",
            score_type="EA",
            baraj_group=None,
            capacity=20,
            tuition_annual=200_000.0,
            scholarship_pct=50.0,
        ),
        ProgramOffering(
            program_id="PRG_IZM_TEACH_STATE",
            university_id="UNI_IZM_STATE",
            university_name="Izmir State University (Hypothetical)",
            university_type="state",
            province_code="35",
            department_name="Turkish Language Teaching",
            degree_level="bachelor",
            score_type="SÖZ",
            baraj_group="teaching",
            capacity=20,
            tuition_annual=0.0,
        ),
        ProgramOffering(
            program_id="PRG_ANK_TRANS_STATE",
            university_id="UNI_ANK_STATE",
            university_name="Ankara State University (Hypothetical)",
            university_type="state",
            province_code="06",
            department_name="English Translation",
            degree_level="bachelor",
            score_type="DİL",
            baraj_group=None,
            capacity=14,
            tuition_annual=0.0,
        ),
        ProgramOffering(
            program_id="PRG_ANK_TECH_ASSOC",
            university_id="UNI_ANK_STATE",
            university_name="Ankara State University (Hypothetical)",
            university_type="state",
            province_code="06",
            department_name="Computer Programming (Associate)",
            degree_level="associate",
            score_type="TYT",
            baraj_group=None,
            capacity=24,
            tuition_annual=0.0,
        ),
    ]


def _synthesize_candidate_from_resident(
    resident: dict[str, Any],
    candidate_id: str,
    programs: list[ProgramOffering],
    stream: Stream,
    inherited_provenance: dict[str, str],
    source_population_id: str | None = None,
    max_preferences: int = 10,
) -> CandidateRecord:
    """Attach strictly ASSUMED synthetic scores, preferences, and financials to a demographic anchor."""
    # Draw primary academic track deterministically
    track_roll = stream.random()
    if track_roll < 0.45:
        primary_track: ScoreType = "SAY"
    elif track_roll < 0.75:
        primary_track = "EA"
    elif track_roll < 0.90:
        primary_track = "SÖZ"
    else:
        primary_track = "DİL"

    # Triangular-like centered score distribution in [210, 505]
    u = (stream.random() + stream.random() + stream.random()) / 3.0
    raw_tyt = round(180.0 + u * 270.0, 3)
    raw_primary = round(190.0 + u * 285.0, 3)
    obp = round(30.0 + stream.random() * 28.0, 3)

    scores: dict[ScoreType, float | None] = {
        "TYT": round(raw_tyt + obp, 3),
        primary_track: round(raw_primary + obp, 3),
    }
    raw_scores: dict[ScoreType, float | None] = {
        "TYT": raw_tyt,
        primary_track: raw_primary,
    }

    income_roll = stream.random()
    if income_roll < 0.40:
        income_band = "low"
        liquid_budget = round(15_000.0 + stream.random() * 35_000.0, 2)
        max_affordable = round(liquid_budget * 1.4, 2)
    elif income_roll < 0.80:
        income_band = "middle"
        liquid_budget = round(65_000.0 + stream.random() * 90_000.0, 2)
        max_affordable = round(liquid_budget * 1.5, 2)
    else:
        income_band = "high"
        liquid_budget = round(200_000.0 + stream.random() * 250_000.0, 2)
        max_affordable = round(liquid_budget * 2.0, 2)

    prov = resident.get("province_code")
    matching = [p for p in programs if p.status == "open" and p.score_type in scores]
    if not matching:
        matching = [p for p in programs if p.status == "open"]

    # Sort programs with slight stochastic jitter + home-province preference + scholarship preference
    scored_prefs: list[tuple[float, str]] = []
    for prog in matching:
        score = stream.random() * 2.0
        if prov and prog.province_code == prov:
            score -= 0.75
        if prog.tuition_annual == 0 or prog.scholarship_pct >= 50.0:
            score -= 0.4
        if prog.score_type == primary_track:
            score -= 0.5
        scored_prefs.append((score, prog.program_id))

    scored_prefs.sort(key=lambda item: (item[0], item[1]))
    pref_count = min(max_preferences, max(2, 3 + stream.below(max(1, min(6, len(scored_prefs))))))
    preferences = [pid for _, pid in scored_prefs[:pref_count]]

    prov_map = dict(inherited_provenance)
    for assumed_field in (
        "scores",
        "raw_scores",
        "obp_contribution",
        "diploma_eligible",
        "preferences",
        "income_band",
        "liquid_budget",
        "max_affordable_tuition",
    ):
        prov_map[assumed_field] = Evidence.ASSUMED

    return CandidateRecord(
        candidate_id=candidate_id,
        source_synthetic_id=resident.get("synthetic_id"),
        source_population_id=source_population_id,
        province_code=prov,
        age=resident.get("age"),
        sex=resident.get("sex"),
        education_level=resident.get("education_level"),
        population_weight=resident.get("population_weight"),
        diploma_eligible=True,
        scores=scores,
        raw_scores=raw_scores,
        ranks={},
        obp_contribution=obp,
        previously_placed_penalty=False,
        preferences=preferences,
        income_band=income_band,  # type: ignore[arg-type]
        liquid_budget=liquid_budget,
        max_affordable_tuition=max_affordable,
        need_aid_grant=0.0,
        field_provenance=prov_map,
    )


def build_tuik_anchored_candidates(
    loaded_population: LoadedPopulation,
    programs: list[ProgramOffering] | None = None,
    *,
    sample_size: int = 200,
    seed: int = 42,
    age_min: int = 17,
    age_max: int = 25,
    province_codes: list[str] | None = None,
    sampling_method: str = "simple_random",
    max_preferences: int = 10,
) -> CandidateCohort:
    """Build a TÜİK-anchored synthetic CandidateCohort without mutating records.parquet."""
    prog_list = programs or build_standalone_demo_programs()
    pop_filter = PopulationFilter(province_codes=province_codes, age_min=age_min, age_max=age_max)
    filtered = loaded_population.filtered(pop_filter)
    if filtered.num_rows == 0:
        raise ValueError(
            f"Population '{loaded_population.population_id}' has 0 records matching age {age_min}..{age_max} "
            f"and provinces {province_codes}."
        )

    actual_size = min(sample_size, filtered.num_rows)
    ids = filtered["synthetic_id"].to_pylist()
    weights = filtered["population_weight"].to_pylist()
    members = (
        weighted_pps(ids, weights, actual_size, seed)
        if sampling_method == "weighted"
        else simple_random(ids, weights, actual_size, seed)
    )

    records_by_id = {row["synthetic_id"]: row for row in filtered.to_pylist()}
    profiles = loaded_population.manifest.get("profiles", {})
    stream = Stream("placement:tuik_anchored_synth", seed)

    candidates: list[CandidateRecord] = []
    for idx, member in enumerate(sorted(members, key=lambda m: m.synthetic_id), start=1):
        rec = records_by_id[member.synthetic_id]
        prof_fields = profiles.get(rec.get("provenance_profile", ""), {}).get("fields", {})
        inherited_prov = {
            "province_code": prof_fields.get("province_code", {}).get("evidence", Evidence.DIRECT_SOURCE),
            "age": prof_fields.get("age", {}).get("evidence", Evidence.DERIVED),
            "sex": prof_fields.get("sex", {}).get("evidence", Evidence.DIRECT_SOURCE),
            "education_level": prof_fields.get("education_level", {}).get("evidence", Evidence.MARGINAL_INFERENCE),
        }
        candidates.append(
            _synthesize_candidate_from_resident(
                resident=rec,
                candidate_id=f"CAND_{idx:05d}",
                programs=prog_list,
                stream=stream,
                inherited_provenance=inherited_prov,
                source_population_id=loaded_population.population_id,
                max_preferences=max_preferences,
            )
        )

    field_provenance = {
        "province_code": {"source": "tuik_population", "evidence": "inherited_from_population_profile"},
        "age": {"source": "tuik_population", "evidence": "inherited_from_population_profile"},
        "sex": {"source": "tuik_population", "evidence": "inherited_from_population_profile"},
        "education_level": {"source": "tuik_population", "evidence": "inherited_from_population_profile"},
        "scores": {"source": "synthetic_generator", "evidence": Evidence.ASSUMED, "note": "Hypothetical YKS-style scores"},
        "preferences": {"source": "synthetic_generator", "evidence": Evidence.ASSUMED, "note": "Hypothetical preference order"},
        "liquid_budget": {"source": "synthetic_generator", "evidence": Evidence.ASSUMED, "note": "Hypothetical liquid budget"},
    }

    return CandidateCohort(
        cohort_id=f"cand_{loaded_population.population_id}_s{seed}_n{len(candidates)}",
        demographic_source="tuik_population",
        source_population_id=loaded_population.population_id,
        population_content_sha256=loaded_population.manifest.get("content_sha256"),
        seed=seed,
        field_provenance=field_provenance,
        candidates=candidates,
    )


def build_standalone_test_cohort(
    programs: list[ProgramOffering] | None = None,
    *,
    size: int = 120,
    seed: int = 42,
    max_preferences: int = 10,
) -> CandidateCohort:
    """Create a standalone synthetic CandidateCohort for offline unit tests and CLI demos."""
    prog_list = programs or build_standalone_demo_programs()
    stream = Stream("placement:standalone_fixture", seed)
    provinces = ("06", "34", "35")
    sexes = ("female", "male")

    candidates: list[CandidateRecord] = []
    for idx in range(1, size + 1):
        resident = {
            "synthetic_id": None,
            "province_code": provinces[stream.below(len(provinces))],
            "age": 18 + stream.below(6),
            "sex": sexes[stream.below(2)],
            "education_level": "upper_secondary",
            "population_weight": 1.0,
        }
        inherited_prov = {k: Evidence.ASSUMED for k in ("province_code", "age", "sex", "education_level")}
        candidates.append(
            _synthesize_candidate_from_resident(
                resident=resident,
                candidate_id=f"CAND_{idx:05d}",
                programs=prog_list,
                stream=stream,
                inherited_provenance=inherited_prov,
                source_population_id=None,
                max_preferences=max_preferences,
            )
        )

    return CandidateCohort(
        cohort_id=f"cand_standalone_s{seed}_n{size}",
        demographic_source="standalone_test_fixture",
        seed=seed,
        field_provenance={
            "all_attributes": {
                "source": "standalone_test_fixture",
                "evidence": Evidence.ASSUMED,
                "note": "Synthetic standalone test fixture; not drawn from official TÜİK or ÖSYM records.",
            }
        },
        candidates=candidates,
    )


def _read_structured_file(path: str | Path) -> Any:
    target = Path(path).resolve()
    text = target.read_text(encoding="utf-8")
    if target.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def load_candidates_file(path: str | Path) -> CandidateCohort:
    """Load a CandidateCohort or list of CandidateRecord dicts from JSON/YAML."""
    data = _read_structured_file(path)
    if isinstance(data, list):
        return CandidateCohort(
            cohort_id=Path(path).stem,
            demographic_source="standalone_test_fixture",
            candidates=[CandidateRecord.model_validate(item) for item in data],
        )
    return CandidateCohort.model_validate(data)


def load_programs_file(path: str | Path) -> list[ProgramOffering]:
    """Load a list of ProgramOffering models from JSON/YAML."""
    data = _read_structured_file(path)
    items = data.get("programs", data) if isinstance(data, dict) else data
    return [ProgramOffering.model_validate(item) for item in items]


def load_ruleset_file(path: str | Path) -> PlacementRuleset:
    """Load a PlacementRuleset from JSON/YAML."""
    data = _read_structured_file(path)
    return PlacementRuleset.model_validate(data)
