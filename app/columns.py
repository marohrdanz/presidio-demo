"""Flag table columns whose headings name a PHI identifier.

Presidio scans a CSV as flat text, so a value like ``1971-04-12`` under a
``dob`` heading is just a bare date by the time it reaches the analyzer. This
check looks at the headings themselves (CSV/TSV, Word tables, JSON keys).

A column only counts if it actually holds values, so an empty template with
just a heading row is still accepted.
"""

import re
from collections import Counter
from dataclasses import dataclass

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


def tokens(heading: str) -> list[str]:
    heading = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", heading)  # camelCase -> camel_Case
    return [t for t in re.split(r"[^a-z0-9]+", heading.lower()) if t]


def _matches(toks: list[str], pattern: tuple[str, ...]) -> bool:
    n = len(pattern)
    for i in range(len(toks) - n + 1):
        if tuple(toks[i : i + n]) == pattern and all(t in ALLOWED_SUFFIX for t in toks[i + n :]):
            return True
    return False


def classify(heading: str) -> str | None:
    toks = tokens(heading)
    if any(_matches(toks, p) for p in STRONG):
        return "strong"
    if any(_matches(toks, p) for p in WEAK):
        return "weak"
    return None


def check_columns(columns: Counter) -> list[ColumnFinding]:
    populated = [c for c, n in columns.items() if n > 0]
    clinical = any(HEALTH_CONTEXT.intersection(tokens(c)) for c in populated)
    findings = []
    for column in populated:
        strength = classify(column)
        if strength == "strong" or (strength == "weak" and clinical):
            findings.append(ColumnFinding(column, strength))
    return findings
