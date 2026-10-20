import unicodedata

import pytest
from pydantic import ValidationError

from societytwin.population.fixtures import V2_FIELDS, parse_population
from societytwin.sampling.filters import FieldUnavailable, FilterSpec
from societytwin.sampling.query import GROUPABLE, SORTABLE, QueryError, crosstab, distributions, filtered_rows, page

ROWS = (
    "person_id,age_group,gender,marital_status,marital_status_conditioning\n"
    "P_03,30-34,female,Evli,gender_only\n"
    "P_01,30-34,male,Evli,gender_only\n"
    "P_02,0-4,female,not_applicable,gender_only\n"
    "P_04,85-89,female,Eşi öldü,gender_only\n"
    "P_05,30-34,female,Boşandı,gender_only\n"
)
TABLE = parse_population(ROWS.encode(), V2_FIELDS)


def ids(rows):
    return [r["person_id"] for r in rows]


def test_and_across_fields_or_within_field():
    spec = FilterSpec(genders=["female"], marital_statuses=["Evli", "Eşi öldü"])
    assert sorted(ids(filtered_rows(TABLE, spec))) == ["P_03", "P_04"]
    assert len(filtered_rows(TABLE, FilterSpec())) == 5


@pytest.mark.parametrize("payload", [{"genders": []}, {"age_groups": []}, {"unknown": ["x"]}, {"genders": ["other"]},
                                     {"age_groups": ["31"]}, {"person_ids": ["a b"]}, {"person_ids": []}])
def test_invalid_filters_are_rejected(payload):
    with pytest.raises(ValidationError):
        FilterSpec(**payload)


def test_decomposed_unicode_is_normalized():
    nfd = unicodedata.normalize("NFD", "Eşi öldü")
    assert nfd != "Eşi öldü"
    spec = FilterSpec(marital_statuses=[nfd])
    assert ids(filtered_rows(TABLE, spec)) == ["P_04"]


def test_marital_filter_on_build_without_column_is_rejected():
    with pytest.raises(FieldUnavailable):
        FilterSpec(marital_statuses=["Evli"]).check_available(["person_id", "age_group", "gender"], "base-build")


def test_normalized_form_is_canonical():
    spec = FilterSpec(age_groups=["85-89", "0-4", "0-4"], genders=["female"])
    assert spec.normalized() == {"age_groups": ["0-4", "85-89"], "genders": ["female"]}


def test_pagination_and_sort_are_deterministic():
    fields = list(V2_FIELDS)
    rows = list(TABLE.rows)
    assert ids(page(rows, fields, "person_id", "asc", 0, 10)) == ["P_01", "P_02", "P_03", "P_04", "P_05"]
    assert ids(page(rows, fields, "person_id", "desc", 1, 2)) == ["P_04", "P_03"]
    # Ties on age group fall back to person_id ascending, in either direction.
    assert ids(page(rows, fields, "age_group", "asc", 0, 10)) == ["P_02", "P_01", "P_03", "P_05", "P_04"]
    assert ids(page(rows, fields, "age_group", "desc", 0, 10)) == ["P_04", "P_01", "P_03", "P_05", "P_02"]
    assert ids(page(list(reversed(rows)), fields, "age_group", "asc", 0, 10)) == ["P_02", "P_01", "P_03", "P_05", "P_04"]
    with pytest.raises(QueryError):
        page(rows, fields, "age", "asc", 0, 10)
    with pytest.raises(QueryError):
        page(rows, fields, "person_id", "asc", 0, 0)
    with pytest.raises(QueryError):
        page(rows, ["person_id", "age_group", "gender"], "marital_status", "asc", 0, 5)


def test_no_exact_age_or_unsupported_fields_are_queryable():
    for field in ("age", "exact_age", "income", "education", "district"):
        assert field not in SORTABLE and field not in GROUPABLE


def test_distributions_sum_to_denominator_and_keep_zero_categories():
    rows = filtered_rows(TABLE, FilterSpec(genders=["female"]))
    for dist in distributions(rows, list(V2_FIELDS), ["age_group", "marital_status"]):
        assert dist["denominator"] == 4
        assert sum(c["count"] for c in dist["categories"]) == 4
        assert abs(sum(c["share"] for c in dist["categories"]) - 1) < 1e-12
    age = distributions(rows, list(V2_FIELDS), ["age_group"])[0]
    assert len(age["categories"]) == 19 and age["categories"][1]["count"] == 0
    assert distributions([], list(V2_FIELDS), ["gender"])[0]["categories"][0]["share"] is None
    table = crosstab(rows, list(V2_FIELDS), "age_group", "gender")
    assert sum(c["count"] for c in table["cells"]) == table["denominator"] == 4
    with pytest.raises(QueryError):
        distributions(rows, list(V2_FIELDS), ["person_id"])
