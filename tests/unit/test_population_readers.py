import pytest

from societytwin.population.fixtures import (
    BASE_FIELDS,
    V2_FIELDS,
    FixtureFormatError,
    parse_age_gender,
    parse_controls,
    parse_marital_gender,
    parse_population,
)
from societytwin.population.repository import CsvPopulationRepository

V2_HEADER = "person_id,age_group,gender,marital_status,marital_status_conditioning\n"


def test_artificial_builds_load_as_two_separate_versions(settings):
    repo = CsvPopulationRepository(settings)
    builds = repo.current_builds()
    assert [b.source.variant for b in builds] == ["base", "v2"]
    assert all(b.table.row_count == 40 for b in builds)
    ids = {b.descriptor["build_id"] for b in builds}
    assert len(ids) == 2  # distinct immutable IDs; never one combined 80-row population
    v2 = builds[1].descriptor
    assert v2["is_default"] and v2["scope"] == {**v2["scope"], "province": "TESTLAND", "reference_year": 2099}
    assert v2["generator"]["configured_seed"] == 7
    assert "marital_status" not in builds[0].descriptor["available_fields"]


def test_build_id_changes_when_bytes_change(settings):
    repo = CsvPopulationRepository(settings)
    before = {b.source.variant: b.descriptor["build_id"] for b in repo.current_builds()}
    path = settings.experiment_file(settings.layout.v2_population)
    path.write_bytes(path.read_bytes().replace(b"TST2099_000040,", b"TST2099_000041,"))
    after = {b.source.variant: b.descriptor["build_id"] for b in repo.current_builds()}
    assert after["base"] == before["base"] and after["v2"] != before["v2"]


@pytest.mark.parametrize("text, message", [
    ("person_id,age_group\nA_1,0-4\n", "header"),
    (V2_HEADER + "A_1,0-4,male,not_applicable,gender_only\nA_1,5-9,male,not_applicable,gender_only\n", "duplicate"),
    (V2_HEADER + "A_1,0-4,male,,gender_only\n", "empty"),
    (V2_HEADER + "A_1,0-4,male,not_applicable,gender_only,extra\n", "malformed"),
    (V2_HEADER + "A_1,0-4,other,not_applicable,gender_only\n", "unknown gender"),
    (V2_HEADER + "A_1,1-4,male,not_applicable,gender_only\n", "unknown age_group"),
    (V2_HEADER + "A_1,30-34,male,Single,gender_only\n", "unknown marital_status"),
    (V2_HEADER + "A_1,30-34,male,Evli,age_and_gender\n", "unknown marital_status_conditioning"),
    (V2_HEADER, "no data rows"),
    (V2_HEADER + "../x,0-4,male,not_applicable,gender_only\n", "invalid person_id"),
])
def test_population_reader_rejects_bad_input(text, message):
    with pytest.raises(FixtureFormatError, match=message):
        parse_population(text.encode("utf-8"), V2_FIELDS)


def test_population_reader_rejects_non_utf8():
    with pytest.raises(FixtureFormatError, match="UTF-8"):
        parse_population(b"person_id,age_group,gender\nA_1,0-4,\xff\n", BASE_FIELDS)


def test_unicode_marital_labels_round_trip():
    data = (V2_HEADER + "A_1,30-34,female,Eşi öldü,gender_only\nA_2,30-34,male,Hiç evlenmedi,gender_only\n").encode("utf-8")
    table = parse_population(data, V2_FIELDS)
    assert [r["marital_status"] for r in table.rows] == ["Eşi öldü", "Hiç evlenmedi"]
    assert table.csv_rows == {"A_1": 2, "A_2": 3}


def _age_gender_text(settings):
    return settings.experiment_file(settings.layout.age_gender).read_text(encoding="utf-8")


def test_age_gender_reference_rejects_nonfinite_and_inconsistent(settings):
    text = _age_gender_text(settings)
    lines = text.splitlines()
    for bad in ("nan", "inf", "-0.5"):
        broken = lines[:]
        cells = broken[1].split(",")
        cells[-1] = bad
        broken[1] = ",".join(cells)
        with pytest.raises(FixtureFormatError):
            parse_age_gender(("\n".join(broken) + "\n").encode())
    with pytest.raises(FixtureFormatError, match="exactly once"):
        parse_age_gender(("\n".join(lines[:-1]) + "\n").encode())
    cells = lines[1].split(",")
    cells[4] = str(int(cells[4]) + 1)
    with pytest.raises(FixtureFormatError, match="disagrees"):
        parse_age_gender(("\n".join([lines[0], ",".join(cells), *lines[2:]]) + "\n").encode())


def test_marital_reference_requires_complete_consistent_table(settings):
    text = settings.experiment_file(settings.layout.marital_gender).read_text(encoding="utf-8")
    table = parse_marital_gender(text.encode())
    assert len(table.rows) == 8 and table.year == 2099
    with pytest.raises(FixtureFormatError, match="four marital categories"):
        parse_marital_gender(("\n".join(text.splitlines()[:-1]) + "\n").encode())


def test_controls_group_agreeing_duplicates_and_reject_conflicts(settings):
    text = settings.experiment_file(settings.layout.controls).read_text(encoding="utf-8")
    table = parse_controls(text.encode())
    assert len(table.observations) == 5 and len(table.facts) == 4
    median = next(f for f in table.facts if f.statistic == "total_median_age")
    assert len(median.observations) == 2
    conflicting = text + "2098,TESTLAND,total_median_age,40.0,years,x.xls,t2,7\n"
    with pytest.raises(FixtureFormatError, match="conflicting"):
        parse_controls(conflicting.encode())
    broken = "\n".join(l if "total_population" not in l else l.split(",")[0] + ",TESTLAND,total_population,999999,persons,a.xls,t1,5" for l in text.splitlines()) + "\n"
    with pytest.raises(FixtureFormatError, match="reconcile"):
        parse_controls(broken.encode())
