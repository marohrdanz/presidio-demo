"""HIPAA Safe Harbor rules for the values in quasi-identifier columns.

Safe Harbor (45 CFR 164.514(b)(2)) doesn't ban zip codes, ages or dates
outright; it bans them above a certain precision:

- Zip codes: at most the first 3 digits, and "000" for 3-digit areas with
  20,000 or fewer people.
- Ages over 89, and any date element (including year) that implies one,
  must be grouped into a single 90-or-older category.
- Dates directly related to an individual (birth, admission, discharge,
  service, death): year only.

These checks look at the values under columns recognised by heading, so a
file of 3-digit zips or birth years passes while one of 5-digit zips or full
dates doesn't. Values are never echoed back, only how many broke each rule.
"""

import re
from dataclasses import dataclass
from datetime import date

from app.headings import contains, tokens

# 3-digit zip prefixes covering 20,000 or fewer people, which Safe Harbor
# requires be replaced with "000". This is the HHS list based on 2000 Census
# data; review it against current Census figures for production use.
RESTRICTED_ZIP3 = frozenset(
    {"036", "059", "063", "102", "203", "556", "692", "790", "821", "823", "830", "831", "878", "879", "884", "890", "893"}
)

# Column kinds, matched on heading tokens. Unlike the identifier headings in
# columns.py these allow any trailing tokens ("age_at_admission",
# "zip_code_patient"), since the values decide whether anything is wrong.
KINDS = {
    "birth_year": [("birth", "year"), ("year", "of", "birth"), ("yob",), ("birthyear",)],
    "birth_date": [("dob",), ("date", "of", "birth"), ("birth", "date"), ("birthdate",), ("birthday",)],
    "event_date": [
        ("admit", "date"), ("admission", "date"), ("discharge", "date"), ("date", "of", "service"),
        ("service", "date"), ("dos",), ("date", "of", "death"), ("death", "date"), ("dod",),
        ("visit", "date"), ("encounter", "date"), ("procedure", "date"), ("surgery", "date"),
    ],
    "age": [("age",)],
    "zip": [("zip",), ("zipcode",), ("zip", "code"), ("postal", "code"), ("postcode",), ("zip3",), ("zip5",)],
}

YEAR = re.compile(r"\d{4}")
AGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:y|yo|yr|yrs|years?)?", re.IGNORECASE)


@dataclass
class Violation:
    rule: str
    count: int


def column_kind(heading: str) -> str | None:
    toks = tokens(heading)
    for kind, patterns in KINDS.items():
        if any(contains(toks, p) for p in patterns):
            return kind
    return None


def check_values(kind: str, values: list[str], today: date | None = None) -> list[Violation]:
    current_year = (today or date.today()).year
    counts: dict[str, int] = {}

    def hit(rule: str) -> None:
        counts[rule] = counts.get(rule, 0) + 1

    for value in values:
        if kind in ("birth_date", "event_date"):
            # Conservative: anything with digits that isn't a bare year is
            # treated as a full or partial date. "unknown"/"N/A" pass.
            if YEAR.fullmatch(value):
                if kind == "birth_date" and current_year - int(value) > 89:
                    hit("birth_year_implies_age_over_89")
            elif any(c.isdigit() for c in value):
                hit("date_more_specific_than_year")
        elif kind == "birth_year":
            if YEAR.fullmatch(value) and current_year - int(value) > 89:
                hit("birth_year_implies_age_over_89")
        elif kind == "age":
            m = AGE.fullmatch(value)
            if m and int(float(m.group(1))) > 89:  # completed years, so 89.9 is 89
                hit("age_over_89")
        elif kind == "zip":
            digits = re.sub(r"\D", "", value)
            if len(digits) > 3:
                hit("zip_more_than_3_digits")
            elif len(digits) == 3 and digits in RESTRICTED_ZIP3:
                hit("restricted_zip3")
    return [Violation(rule, n) for rule, n in counts.items()]
