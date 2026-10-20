import math

from societytwin.evaluation.source_fit import integrity_checks, joint_age_gender_tvd, marginal_rows, tvd, validation_report
from societytwin.population.fixtures import V2_FIELDS, parse_population
from societytwin.population.repository import CsvPopulationRepository


def test_tvd_hand_computed():
    assert tvd({"a": 0.5, "b": 0.5}, {"a": 0.25, "b": 0.75}) == 0.25
    assert tvd({"a": 1.0}, {"b": 1.0}) == 1.0
    assert tvd({"a": 0.2, "b": 0.8}, {"a": 0.2, "b": 0.8}) == 0.0


def test_report_on_artificial_build(settings):
    repo = CsvPopulationRepository(settings)
    v2 = repo.current_builds()[1]
    report = validation_report(v2.table, "v2", repo.age_gender(), repo.marital_gender(), repo.controls())
    names = [m["name"] for m in report["metrics"]]
    assert names == ["gender_marginal_share_difference", "age_group_marginal_share_difference", "joint_age_gender_tvd",
                     "marital_within_male_15plus_tvd", "marital_within_female_15plus_tvd"]
    assert all(m["acceptance_threshold"] is None for m in report["metrics"])
    assert report["acceptance_status"] is None
    joint = next(m for m in report["metrics"] if m["name"] == "joint_age_gender_tvd")
    assert 0 <= joint["value"] <= 1 and joint["value"] == joint_age_gender_tvd(v2.table, repo.age_gender())
    gender = report["metrics"][0]["categories"]
    assert sum(c["count"] for c in gender) == 40
    assert math.isclose(sum(c["synthetic_share"] for c in gender), 1.0)
    assert all(c["passed"] for c in report["checks"])
    kinds = {e["evidence_kind"] for e in report["unavailable_evidence"]}
    assert {"held_out", "behavioral"} <= kinds


def test_marginal_rows_hand_computed(settings):
    repo = CsvPopulationRepository(settings)
    table = parse_population(b"person_id,age_group,gender\nA,0-4,male\nB,0-4,female\nC,5-9,female\nD,90+,female\n",
                             ("person_id", "age_group", "gender"))
    rows = marginal_rows(table, repo.age_gender(), "gender", ("male", "female"))
    assert rows[0]["count"] == 1 and rows[0]["synthetic_share"] == 0.25
    ref_male = sum(r["probability"] for r in repo.age_gender().rows if r["gender"] == "male")
    assert math.isclose(rows[0]["difference_pp"], 100 * (0.25 - ref_male))


def test_integrity_checks_flag_child_with_applicable_status(settings):
    repo = CsvPopulationRepository(settings)
    table = parse_population(
        ("person_id,age_group,gender,marital_status,marital_status_conditioning\n"
         "A,5-9,male,Evli,gender_only\nB,30-34,female,not_applicable,gender_only\n").encode(), V2_FIELDS)
    checks = {c["name"]: c for c in integrity_checks(table, repo.age_gender(), repo.marital_gender(), repo.controls(), "v2")}
    assert not checks["under_15_not_applicable"]["passed"]
    assert "1 with an applicable status" in checks["under_15_not_applicable"]["detail"]
    assert checks["reference_totals_reconcile_with_controls"]["passed"]
