from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.columns import check_columns
from app.main import app
from app.safe_harbor import check_values, column_kind

TODAY = date(2026, 10, 5)


def rules(kind, values):
    return {v.rule: v.count for v in check_values(kind, values, TODAY)}


@pytest.mark.parametrize(
    "heading, kind",
    [
        ("zip", "zip"), ("Zip Code", "zip"), ("patient_zip3", "zip"), ("postal_code", "zip"),
        ("age", "age"), ("age_at_admission", "age"), ("patientAge", "age"),
        ("birth_year", "birth_year"), ("YOB", "birth_year"),
        ("dob", "birth_date"), ("Date of Birth", "birth_date"),
        ("admit_date", "event_date"), ("discharge_date", "event_date"), ("DOS", "event_date"),
        ("visit_id", None), ("diagnosis", None), ("page", None),
    ],
)
def test_column_kind(heading, kind):
    assert column_kind(heading) == kind


# --- zip ------------------------------------------------------------------


def test_zip3_is_allowed():
    assert rules("zip", ["803", "100", "021", "803xx", "000"]) == {}


def test_zip5_and_zip_plus_4_are_not():
    assert rules("zip", ["80302", "80302-1234", "2134"]) == {"zip_more_than_3_digits": 3}


def test_restricted_zip3_must_be_000():
    assert rules("zip", ["036", "893", "803"]) == {"restricted_zip3": 2}


# --- age ------------------------------------------------------------------


def test_ages_up_to_89_are_allowed():
    assert rules("age", ["0", "34", "89", "89.9", "90+", ">89", "18 months"]) == {}


def test_ages_over_89_are_not():
    # "89.9" is still 89; only values over 89 break the rule.
    assert rules("age", ["90", "102", "95 yrs", "91y"]) == {"age_over_89": 4}


# --- dates ----------------------------------------------------------------


def test_year_only_dates_are_allowed():
    assert rules("event_date", ["2024", "2025", "unknown", "N/A"]) == {}


@pytest.mark.parametrize("value", ["2024-01-05", "01/05/2024", "Jan 5, 2024", "2024-01", "20240105", "45296"])
def test_anything_more_specific_than_a_year_is_not(value):
    assert rules("event_date", [value]) == {"date_more_specific_than_year": 1}


def test_birth_year_allowed_unless_it_implies_over_89():
    assert rules("birth_year", ["1971", "1937"]) == {}
    assert rules("birth_year", ["1936", "1920"]) == {"birth_year_implies_age_over_89": 2}


def test_dob_column_with_years_follows_birth_year_rule():
    assert rules("birth_date", ["1971", "1980"]) == {}
    assert rules("birth_date", ["1971-04-12", "1930"]) == {
        "date_more_specific_than_year": 1,
        "birth_year_implies_age_over_89": 1,
    }


# --- how it combines with the heading check -------------------------------


def test_compliant_clinical_file_is_accepted():
    cols = {"zip": ["803", "021"], "age": ["34", "90+"], "admit_year": ["2024"], "diagnosis": ["I10", "E11"]}
    assert check_columns(cols, TODAY) == []


def test_zip_outside_a_clinical_file_is_ignored():
    assert check_columns({"zip": ["80302"], "store": ["Boulder"]}, TODAY) == []


def test_dob_is_checked_even_outside_a_clinical_file():
    [finding] = check_columns({"dob": ["1971-04-12"], "team": ["Ops"]}, TODAY)
    assert (finding.column, finding.rule, finding.count) == ("dob", "date_more_specific_than_year", 1)


def test_birth_year_column_only_matters_in_a_clinical_file():
    assert check_columns({"birth_year": ["1920"]}, TODAY) == []
    [finding] = check_columns({"birth_year": ["1920"], "dx": ["I10"]}, TODAY)
    assert finding.rule == "birth_year_implies_age_over_89"


def test_non_value_weak_headings_still_reject_on_heading():
    [finding] = check_columns({"city": ["Boulder"], "diagnosis": ["I10"]}, TODAY)
    assert (finding.column, finding.rule) == ("city", "identifier_heading")


# --- end to end -----------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def upload(client, name, content):
    return client.post("/scan", files={"file": (name, content, "text/csv")})


def test_safe_harbor_compliant_csv_is_accepted(client):
    data = b"visit_id,zip,age,admit_year,diagnosis\nV1,803,34,2024,hypertension\nV2,021,90+,2023,asthma\n"
    resp = upload(client, "deidentified.csv", data)
    assert resp.status_code == 200, resp.json()


def test_safe_harbor_violations_are_reported_without_values(client):
    data = b"visit_id,zip,age,admit_date,diagnosis\nV1,80302,34,2024-01-05,hypertension\nV2,021,93,2023,asthma\n"
    resp = upload(client, "visits.csv", data)
    assert resp.status_code == 422
    found = {(f["column"], f["rule"], f["count"]) for f in resp.json()["findings"] if f["entity_type"] == "PHI_COLUMN"}
    assert found == {
        ("zip", "zip_more_than_3_digits", 1),
        ("age", "age_over_89", 1),
        ("admit_date", "date_more_specific_than_year", 1),
    }
    for value in ("80302", "2024-01-05"):
        assert value not in resp.text
