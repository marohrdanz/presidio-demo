import io
import json

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.columns import check_columns, classify
from app.extract import extract
from app.main import app


@pytest.mark.parametrize(
    "heading",
    ["dob", "DOB", "patient_dob", "Date of Birth", "birthDate", "SSN", "mrn", "Medical Record Number",
     "patientName", "Last Name", "member_id", "Medicare ID", "phone_number", "Home Phone", "email", "E-mail"],
)
def test_strong_headings(heading):
    assert classify(heading) == "strong"


@pytest.mark.parametrize("heading", ["name", "Patient", "address", "zip", "admit_date", "age"])
def test_weak_headings(heading):
    assert classify(heading) == "weak"


@pytest.mark.parametrize(
    "heading",
    ["visit_id", "diagnosis", "revenue", "phone_model", "email_template", "mobile_app_version",
     "page", "percentage", "dosage", "product_code"],
)
def test_unrelated_headings(heading):
    assert classify(heading) is None


def test_empty_column_is_ignored():
    assert check_columns({"dob": [], "visit_id": ["V1", "V2", "V3"]}) == []


def test_weak_column_needs_health_context():
    assert check_columns({"name": ["Widget"], "price": ["9.99"]}) == []
    flagged = check_columns({"name": ["Maria"], "diagnosis": ["I10"]})
    assert [f.column for f in flagged] == ["name"]


def test_health_context_column_must_be_populated():
    assert check_columns({"name": ["Maria"], "diagnosis": []}) == []


def test_csv_collects_values_per_heading():
    data = b"visit_id,dob,notes\nV1,1971-04-10,\nV2,,\n"
    assert extract("x.csv", data).columns == {"visit_id": ["V1", "V2"], "dob": ["1971-04-10"], "notes": []}


def test_tsv_uses_tab_delimiter():
    assert extract("x.tsv", b"mrn\tdx\n7712093\tI10\n").columns == {"mrn": ["7712093"], "dx": ["I10"]}


def test_json_keys_are_columns():
    doc = {"patients": [{"dob": "1971-04-10", "notes": None}, {"dob": "1980-01-01", "tags": ["a"]}]}
    cols = extract("x.json", json.dumps(doc).encode()).columns
    assert sorted(cols["dob"]) == ["1971-04-10", "1980-01-01"]
    assert cols["notes"] == []
    assert cols["tags"] == ["a"]


def test_invalid_json_has_no_columns():
    assert extract("x.json", b"{not json").columns == {}


# --- end to end -----------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def upload(client, name, content):
    return client.post("/scan", files={"file": (name, content, "application/octet-stream")})


def test_csv_with_only_header_labelled_dobs_is_rejected(client):
    # Presidio alone accepts this file: the dates are bare once the CSV is
    # flattened to text, and nothing else in it looks like PHI.
    rows = "\n".join(f"V{i},1971-04-{10 + i:02d},8020{i},hypertension" for i in range(5))
    resp = upload(client, "visits.csv", f"visit_id,dob,zip,diagnosis\n{rows}\n".encode())
    assert resp.status_code == 422
    body = resp.json()
    flagged = {f["column"] for f in body["findings"] if f["entity_type"] == "PHI_COLUMN"}
    # zip is weak, but diagnosis makes this a clinical file.
    assert flagged == {"dob", "zip"}
    assert body["entity_counts"]["PHI_COLUMN"] == 2


def test_csv_mrn_column_is_flagged_beyond_first_row(client):
    rows = "\n".join(f"{7712093 + i},1971-04-{10 + i:02d},hypertension" for i in range(5))
    resp = upload(client, "visits.csv", f"mrn,dob,diagnosis\n{rows}\n".encode())
    assert resp.status_code == 422
    flagged = {f["column"] for f in resp.json()["findings"] if f["entity_type"] == "PHI_COLUMN"}
    assert flagged == {"mrn", "dob"}


def test_empty_template_is_accepted(client):
    resp = upload(client, "template.csv", b"mrn,dob,diagnosis\n")
    assert resp.status_code == 200


def test_non_clinical_csv_with_name_column_is_accepted(client):
    data = b"name,sku,price\nWidget,W-100,9.99\nGadget,G-200,19.99\n"
    assert upload(client, "catalog.csv", data).status_code == 200


def test_json_records_are_rejected(client):
    doc = [{"visit": "V1", "birthDate": "1971-04-10"}, {"visit": "V2", "birthDate": "1980-01-01"}]
    resp = upload(client, "export.json", json.dumps(doc).encode())
    assert resp.status_code == 422
    assert any(f.get("column") == "birthDate" for f in resp.json()["findings"])


def test_docx_table_headings_are_checked(client):
    doc = Document()
    table = doc.add_table(rows=3, cols=2)
    for row, (a, b) in zip(table.rows, [("Visit", "DOB"), ("V1", "1971-04-10"), ("V2", "1980-01-01")]):
        row.cells[0].text, row.cells[1].text = a, b
    buf = io.BytesIO()
    doc.save(buf)
    resp = upload(client, "visits.docx", buf.getvalue())
    assert resp.status_code == 422
    assert any(f.get("column") == "DOB" for f in resp.json()["findings"])


def test_column_check_can_be_disabled(client, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(client.app.state, "settings", replace(client.app.state.settings, check_columns=False))
    rows = "\n".join(f"V{i},1971-04-{10 + i:02d}" for i in range(5))
    assert upload(client, "visits.csv", f"visit_id,dob\n{rows}\n".encode()).status_code == 200
