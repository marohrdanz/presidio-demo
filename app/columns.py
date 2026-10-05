"""Flag table columns whose headings name a PHI identifier.

Presidio scans a CSV as flat text, so a value like ``1971-04-12`` under a
``dob`` heading is just a bare date by the time it reaches the analyzer. This
check looks at the headings themselves (CSV/TSV, Word tables, JSON keys).

A column only counts if it actually holds values, so an empty template with
just a heading row is still accepted. Zip, age and date columns are checked
value by value against the Safe Harbor rules in safe_harbor.py instead of
being rejected on their heading alone.
"""

from dataclasses import dataclass
from datetime import date

from app.extract import Columns
from app.headings import contains, tokens
from app.safe_harbor import check_values, column_kind

# Headings that name a direct identifier. Each entry is a run of tokens that
# must appear contiguously in the normalised heading ("patient_dob" and
# "DOB" both contain ("dob",)).
STRONG = [
    ("ssn",), ("social", "security"),
    ("mrn",), ("medical", "record"), ("chart", "number"),
    ("dob",), ("date", "of", "birth"), ("birth", "date"), ("birthdate",), ("birthday",),
    ("patient", "name"), ("first", "name"), ("last", "name"), ("middle", "name"), ("full", "name"),
    ("given", "name"), ("family", "name"), ("surname",), ("firstname",), ("lastname",), ("fname",), ("lname",),
    ("member", "id"), ("subscriber", "id"), ("policy", "number"), ("medicare",), ("medicaid",), ("mbi",),
    ("phone",), ("telephone",), ("mobile",), ("fax",), ("email",), ("e", "mail"),
    ("drivers", "license"), ("driver", "license"), ("passport",),
    ("ip", "address"),
]

# Headings that are only identifying in a health context ("name" in a product
# catalogue is harmless; "name" next to "diagnosis" is not).
WEAK = [
    ("name",), ("patient",), ("address",), ("street",), ("city",), ("zip",), ("zipcode",), ("postal", "code"),
    ("admit", "date"), ("admission", "date"), ("discharge", "date"), ("date", "of", "service"), ("dos",),
    ("date", "of", "death"), ("death", "date"), ("age",),
]

# Tokens that make a file clinical when they appear in any populated heading.
HEALTH_CONTEXT = {
    "diagnosis", "diagnoses", "dx", "icd", "icd9", "icd10", "cpt", "procedure", "medication", "medications",
    "meds", "rx", "prescription", "drug", "dosage", "allergy", "allergies", "condition", "symptom", "symptoms",
    "treatment", "lab", "labs", "vitals", "npi", "encounter", "admission", "discharge", "clinical", "therapy",
}

# A pattern may be followed only by these tokens, so "phone_number" and
# "member_id_no" match but "phone_model" and "email_template" don't.
ALLOWED_SUFFIX = {"number", "num", "no", "nbr", "id", "code", "value", "address", "addr", "1", "2", "3"}


@dataclass
class ColumnFinding:
    column: str
    strength: str  # "strong" | "weak"
    rule: str  # "identifier_heading", or the Safe Harbor value rule broken
    count: int  # number of values in the column (or breaking the rule)


def classify(heading: str) -> str | None:
    toks = tokens(heading)
    if any(contains(toks, p, ALLOWED_SUFFIX) for p in STRONG):
        return "strong"
    if any(contains(toks, p, ALLOWED_SUFFIX) for p in WEAK):
        return "weak"
    return None


def check_columns(columns: Columns, today: date | None = None) -> list[ColumnFinding]:
    populated = {c: v for c, v in columns.items() if v}
    clinical = any(HEALTH_CONTEXT.intersection(tokens(c)) for c in populated)
    findings = []
    for column, values in populated.items():
        strength = classify(column)
        kind = column_kind(column)
        if kind and (strength == "strong" or clinical):
            # Zip, age and date columns are allowed at Safe Harbor precision,
            # so their values decide rather than the heading alone.
            findings += [
                ColumnFinding(column, strength or "weak", v.rule, v.count)
                for v in check_values(kind, values, today)
            ]
        elif strength == "strong" or (strength == "weak" and clinical):
            findings.append(ColumnFinding(column, strength, "identifier_heading", len(values)))
    return findings
