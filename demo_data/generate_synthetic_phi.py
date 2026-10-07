#!/usr/bin/env python3
"""
generate_synthetic_phi.py

Generate synthetic CSV files containing FAKE PHI for testing PHI-detection
pipelines (e.g. Presidio + column profiling), plus a ground-truth manifest
(manifest.json) so you can measure what your detector catches and misses.

Files produced (in --out-dir):
  labeled.csv           Obvious PHI with descriptive headers (baseline).
  obfuscated.csv        Same kinds of PHI under generic/misleading headers,
                        shuffled column order, digits-only IDs and phones.
  formats.csv           PHI in many formats (dates, phones, SSNs, names, ZIP+4,
                        prefixed MRNs) and ages over 89.
  freetext.csv          Clinical-style notes; some contain embedded PHI.
                        Character-level spans recorded in the manifest.
  sparse.csv            Clean structured data plus a mostly blank comments
                        column with PHI in only a few rows (tests sampling).
  negative_control.csv  Safe Harbor-style de-identified data with traps for
                        false positives (eponymous diagnoses, name-like words).
  quasi_identifiers.csv No direct identifiers, but combinations of columns
                        single out some people (tests k-anonymity checks).
  manifest.json         Ground truth for every file.

Safety: everything is randomly generated. Reserved ranges are used where they
exist, so these values cannot belong to real people or systems:
  - phone numbers: 555-0100..555-0199 (reserved for fictional use)
  - emails / URLs: example.com / .org / .net (RFC 2606)
  - IP addresses: documentation ranges (RFC 5737)
  - SSNs: area numbers 900-999, never issued as SSNs (see --realistic-ssn)
Names, street addresses, and ZIP codes are random combinations and may
coincidentally resemble real ones; they are not drawn from any real data.

Standard library only. Python 3.8+.

Usage:
  python generate_synthetic_phi.py
  python generate_synthetic_phi.py --rows 1000 --seed 7 --out-dir ./phi_test
  python generate_synthetic_phi.py --mrn-format "AB######"
"""

import argparse
import csv
import json
import random
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

# --------------------------------------------------------------------------
# Source vocabularies
# --------------------------------------------------------------------------

# Includes names that are also ordinary words or places (Grace, Hope, Jordan,
# April, Will, Paris...) and non-ASCII names, both common detector weak spots.
FIRST_NAMES = [
    "James", "Maria", "Robert", "Linda", "Michael", "Aisha", "David", "Mei",
    "Carlos", "Priya", "John", "Fatima", "Wei", "Olga", "Kwame", "Sofia",
    "Grace", "Hope", "Jordan", "April", "Will", "Paris", "Florence", "Rose",
    "Chase", "Austin", "José", "Zoë", "Siobhán", "Dmitri", "Ngozi", "Hiroshi",
]
LAST_NAMES = [
    "Smith", "Johnson", "Garcia", "Nguyen", "Patel", "Okafor", "Kowalski",
    "Haddad", "Tanaka", "Begum", "O'Brien", "Müller", "Hernández", "Kim",
    "Brown", "King", "Young", "Wood", "Rivers", "Banks", "Strong", "Fox",
    "Ivanova", "Mensah", "Rossi", "Chen", "Singh", "Delacroix",
]
STREET_NAMES = ["Oak", "Maple", "Cedar", "Elm", "Washington", "Lake", "Hill",
                "Park", "Pine", "Sunset", "River", "Main", "Church", "Meadow"]
STREET_TYPES = ["St", "Ave", "Rd", "Blvd", "Ln", "Dr", "Ct", "Way"]
# (city, state, ZIP3). Includes ZIP3s with leading zeros.
CITIES = [
    ("Springfield", "IL", "627"), ("Riverside", "CA", "925"),
    ("Franklin", "TN", "370"), ("Greenville", "SC", "296"),
    ("Fairview", "TX", "750"), ("Madison", "WI", "537"),
    ("Clinton", "MA", "015"), ("Salem", "OR", "973"),
    ("Georgetown", "KY", "403"), ("Burlington", "VT", "054"),
]
AREA_CODES = ["212", "312", "415", "617", "713", "206", "404", "305", "503"]
EMPLOYERS = ["Lakeside Elementary School", "Northgate Logistics",
             "Bluebonnet Diner", "Harbor Point Credit Union",
             "Summit Ridge Construction", "Tri-County Transit"]
DIAGNOSES = ["Type 2 diabetes mellitus", "Essential hypertension", "Asthma",
             "Major depressive disorder", "Chronic kidney disease stage 3",
             "Atrial fibrillation", "Osteoarthritis of knee", "COPD",
             "Hypothyroidism", "Migraine"]
# Eponymous diagnoses contain surnames but are NOT PHI: false-positive traps.
EPONYM_DX = ["Crohn's disease", "Hodgkin lymphoma", "Graves' disease",
             "Alzheimer's disease", "Parkinson's disease", "Bell's palsy",
             "Hashimoto's thyroiditis", "Down syndrome", "Addison's disease",
             "Cushing's syndrome"]
RARE_DX = ["Erdheim-Chester disease", "Fibrodysplasia ossificans progressiva",
           "Castleman disease", "Alkaptonuria"]
# Large-population ZIP3s for the de-identified negative control.
SAFE_ZIP3 = ["100", "606", "900", "770", "941", "191", "021", "303", "981"]
LAB_NAMES = ["HbA1c", "Creatinine", "TSH", "LDL", "Hemoglobin", "Sodium"]
SPECIALTIES = ["Cardiology", "Endocrinology", "Family Medicine",
               "Nephrology", "Neurology", "Pulmonology"]

# --------------------------------------------------------------------------
# Value generators
# --------------------------------------------------------------------------


def ascii_slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def rand_date(rng, start, end):
    return start + timedelta(days=rng.randint(0, (end - start).days))


def age_on(dob, d):
    return d.year - dob.year - ((d.month, d.day) < (dob.month, dob.day))


def age_band(age):
    if age >= 90:
        return "90+"
    lo = age // 10 * 10
    return f"{lo}-{lo + 9}"


def fmt_date(d, style):
    if style == "iso":
        return d.isoformat()                       # 2024-03-07
    if style == "us":
        return f"{d.month:02d}/{d.day:02d}/{d.year}"   # 03/07/2024
    if style == "us_short":
        return f"{d.month}/{d.day}/{d.year % 100:02d}"  # 3/7/24
    if style == "long":
        return f"{d:%B} {d.day}, {d.year}"         # March 7, 2024
    if style == "dmy":
        return f"{d.day:02d}-{d:%b}-{d.year}"      # 07-Mar-2024
    raise ValueError(style)


DATE_STYLES = ["iso", "us", "us_short", "long", "dmy"]


def make_phone(rng, style="dashed"):
    area = rng.choice(AREA_CODES)
    line = f"01{rng.randint(0, 99):02d}"           # 555-0100..555-0199
    return {
        "dashed": f"{area}-555-{line}",
        "paren": f"({area}) 555-{line}",
        "dots": f"{area}.555.{line}",
        "intl": f"+1 {area} 555 {line}",
        "digits": f"{area}555{line}",
    }[style]


PHONE_STYLES = ["dashed", "paren", "dots", "intl", "digits"]


def make_ssn(rng, realistic, style="dashed"):
    if realistic:
        area = rng.choice([a for a in range(1, 900) if a != 666])
    else:
        area = rng.randint(900, 999)               # never issued as SSNs
    group, serial = rng.randint(1, 99), rng.randint(1, 9999)
    sep = {"dashed": "-", "plain": "", "spaced": " "}[style]
    return f"{area:03d}{sep}{group:02d}{sep}{serial:04d}"


def make_mrn(rng, fmt):
    """'#' -> digit, 'A' -> uppercase letter, anything else kept literally."""
    out = []
    for ch in fmt:
        if ch == "#":
            out.append(str(rng.randint(0, 9)))
        elif ch == "A":
            out.append(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"))
        else:
            out.append(ch)
    return "".join(out)


def make_ip(rng):
    return f"{rng.choice(['192.0.2', '198.51.100', '203.0.113'])}.{rng.randint(1, 254)}"


def make_url(rng):
    return f"https://portal.example.com/patient/{rng.randint(10000, 99999)}/photos"


def make_person(rng, args):
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    dob = rand_date(rng, date(1925, 1, 1), date(2020, 12, 31))
    admit = rand_date(rng, date(2022, 1, 1), date(2025, 12, 31))
    if admit < dob:
        admit = dob + timedelta(days=30)
    city, state, zip3 = rng.choice(CITIES)
    return {
        "first": first, "last": last, "name": f"{first} {last}",
        "middle_initial": rng.choice("ABCDEFGHJKLMNPRSTW"),
        "dob": dob, "admit": admit,
        "discharge": admit + timedelta(days=rng.randint(0, 14)),
        "age": age_on(dob, admit),
        "sex": rng.choice(["F", "M"]),
        "mrn": make_mrn(rng, args.mrn_format),
        "mrn_plain": str(rng.randint(10_000_000, 99_999_999)),
        "ssn_digits": make_ssn(rng, args.realistic_ssn, "plain"),
        "street": f"{rng.randint(1, 9999)} {rng.choice(STREET_NAMES)} "
                  f"{rng.choice(STREET_TYPES)}",
        "city": city, "state": state, "zip3": zip3,
        "zip5": f"{zip3}{rng.randint(0, 99):02d}",
        "phone": make_phone(rng),
        "email": f"{ascii_slug(first)}.{ascii_slug(last)}{rng.randint(1, 99)}"
                 f"@example.{rng.choice(['com', 'org', 'net'])}",
        "employer": rng.choice(EMPLOYERS),
        "dx": rng.choice(DIAGNOSES),
        "lab": f"{rng.uniform(4.5, 11.0):.1f}",
    }


def ssn_style(p, style):
    d = p["ssn_digits"]
    sep = {"dashed": "-", "plain": "", "spaced": " "}[style]
    return f"{d[:3]}{sep}{d[3:5]}{sep}{d[5:]}"

# --------------------------------------------------------------------------
# Free-text notes with recorded spans
# --------------------------------------------------------------------------


PHI_TEMPLATES = [
    "Patient {PERSON} (MRN {MRN}) presented on {DATE} with worsening {DX}.",
    "Spoke with daughter {RELATIVE} at {PHONE} re: discharge plan. Pt agrees.",
    "Pt lives at {ADDRESS} with spouse {RELATIVE}.",
    "Requests records be sent to {EMAIL}. Consent form signed {DATE}.",
    "Pt is a {AGE_OVER_89} y/o with h/o {DX_EPONYM}, accompanied by son {RELATIVE}.",
    "Works as custodian at {EMPLOYER}; has missed shifts since {DATE}.",
    "Uploaded wound photos via {URL} from IP {IP}.",
    "Insurance verification: SSN {SSN}, callback number {PHONE}.",
    "{PERSON} called to reschedule; last seen by Dr. {PROVIDER} on {DATE}.",
    "Pt reports she moved to {CITY} last spring and needs a new PCP.",
]
# Clean notes include name-like words (Grace, Hope, May, April) and provider
# names: things a detector may flag that are not patient identifiers.
CLEAN_TEMPLATES = [
    "Pt reports improved sleep. Continue current regimen.",
    "BP well controlled on current meds. No acute distress.",
    "Discussed {DX_EPONYM} management; patient agrees with plan.",
    "Labs reviewed with Dr. {PROVIDER}; repeat in 3 months.",
    "{AGE}-year-old with {DX}. Follow up in 6 weeks.",
    "Grace period for prior auth extended; no changes to plan.",
    "Hope to taper steroids by next visit. May start PT in April.",
]
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def note_value(key, p, rng, args):
    """Return (value, entity_or_None, is_phi)."""
    if key == "PERSON":
        return p["name"], "PERSON", True
    if key == "RELATIVE":
        return f"{rng.choice(FIRST_NAMES)} {p['last']}", "PERSON", True
    if key == "PROVIDER":
        # Provider names are not Safe Harbor identifiers of the patient, but
        # most detectors will flag them. Recorded so you can set a policy.
        return rng.choice(LAST_NAMES), "PERSON_PROVIDER", False
    if key == "MRN":
        return p["mrn"], "MRN", True
    if key == "DATE":
        d = p["admit"] + timedelta(days=rng.randint(-30, 30))
        return fmt_date(d, rng.choice(DATE_STYLES)), "DATE", True
    if key == "PHONE":
        return make_phone(rng, rng.choice(PHONE_STYLES)), "PHONE_NUMBER", True
    if key == "ADDRESS":
        return (f"{p['street']}, {p['city']}, {p['state']} {p['zip5']}",
                "ADDRESS", True)
    if key == "CITY":
        return p["city"], "LOCATION", True
    if key == "EMAIL":
        return p["email"], "EMAIL_ADDRESS", True
    if key == "EMPLOYER":
        return p["employer"], "EMPLOYER", True
    if key == "URL":
        return make_url(rng), "URL", True
    if key == "IP":
        return make_ip(rng), "IP_ADDRESS", True
    if key == "SSN":
        return make_ssn(rng, args.realistic_ssn,
                        rng.choice(["dashed", "plain"])), "US_SSN", True
    if key == "AGE_OVER_89":
        return str(rng.randint(90, 104)), "AGE_OVER_89", True
    if key == "AGE":
        return str(rng.randint(18, 89)), None, False
    if key == "DX":
        return p["dx"], None, False
    if key == "DX_EPONYM":
        return rng.choice(EPONYM_DX), None, False
    raise KeyError(key)


def render_note(template, p, rng, args, row_idx, column):
    out, spans, pos, last = [], [], 0, 0
    for m in PLACEHOLDER.finditer(template):
        literal = template[last:m.start()]
        out.append(literal)
        pos += len(literal)
        value, entity, is_phi = note_value(m.group(1), p, rng, args)
        if entity:
            spans.append({"row": row_idx, "column": column, "start": pos,
                          "end": pos + len(value), "entity": entity,
                          "phi": is_phi, "value": value})
        out.append(value)
        pos += len(value)
        last = m.end()
    out.append(template[last:])
    return "".join(out), spans

# --------------------------------------------------------------------------
# File builders: each returns (header, rows, manifest_entry)
# --------------------------------------------------------------------------


def col(entity, phi, note=None):
    d = {"entity": entity, "phi": phi}
    if note:
        d["note"] = note
    return d


AGE_NOTE = "Identifying only when > 89 (Safe Harbor requires aggregating to 90+)."


def build_labeled(people, rng, args):
    spec = [
        ("patient_name", lambda p: p["name"], col("PERSON", True)),
        ("dob", lambda p: p["dob"].isoformat(), col("DATE", True)),
        ("mrn", lambda p: p["mrn"], col("MRN", True)),
        ("ssn", lambda p: ssn_style(p, "dashed"), col("US_SSN", True)),
        ("street_address", lambda p: p["street"], col("ADDRESS", True)),
        ("city", lambda p: p["city"], col("LOCATION", True)),
        ("state", lambda p: p["state"], col("US_STATE", False)),
        ("zip", lambda p: p["zip5"], col("ZIP_CODE", True)),
        ("phone", lambda p: p["phone"], col("PHONE_NUMBER", True)),
        ("email", lambda p: p["email"], col("EMAIL_ADDRESS", True)),
        ("admit_date", lambda p: p["admit"].isoformat(), col("DATE", True)),
        ("discharge_date", lambda p: p["discharge"].isoformat(), col("DATE", True)),
        ("age", lambda p: str(p["age"]), col("AGE", "conditional", AGE_NOTE)),
        ("sex", lambda p: p["sex"], col(None, False)),
        ("diagnosis", lambda p: p["dx"], col(None, False)),
        ("hba1c", lambda p: p["lab"], col(None, False)),
    ]
    return from_spec(spec, people, "Descriptive headers; baseline detection test.")


def build_obfuscated(people, rng, args):
    spec = [
        ("col_a", lambda p: p["name"], col("PERSON", True)),
        ("d1", lambda p: fmt_date(p["dob"], "us"), col("DATE", True)),
        ("code", lambda p: p["mrn_plain"], col("MRN", True,
         "Plain 8-digit integers; needs uniqueness profiling or a custom recognizer.")),
        ("ref", lambda p: ssn_style(p, "plain"), col("US_SSN", True,
         "SSNs without dashes.")),
        ("line1", lambda p: p["street"], col("ADDRESS", True)),
        ("loc", lambda p: p["city"], col("LOCATION", True)),
        ("pc", lambda p: p["zip5"], col("ZIP_CODE", True,
         "Some values have leading zeros; read with dtype=str.")),
        ("contact", lambda p: make_phone(rng, "digits"), col("PHONE_NUMBER", True)),
        ("user", lambda p: p["email"], col("EMAIL_ADDRESS", True)),
        ("d2", lambda p: p["admit"].isoformat(), col("DATE", True)),
        ("category", lambda p: p["dx"], col(None, False)),
        ("value", lambda p: p["lab"], col(None, False)),
    ]
    rng.shuffle(spec)
    return from_spec(spec, people,
                     "Generic/misleading headers, shuffled columns; tests value-based detection.")


def build_formats(people, rng, args):
    def name(p):
        return rng.choice([
            p["name"], f"{p['last']}, {p['first']}", p["name"].upper(),
            f"{p['first']} {p['middle_initial']}. {p['last']}"])

    def zipc(p):
        return p["zip5"] if rng.random() < 0.6 else f"{p['zip5']}-{rng.randint(0, 9999):04d}"

    def mrn(p):
        return rng.choice([p["mrn"], f"MRN-{p['mrn']}", f"#{p['mrn']}"])

    spec = [
        ("patient", name, col("PERSON", True, "Mixed name orders and casing.")),
        ("birth_date", lambda p: fmt_date(p["dob"], rng.choice(DATE_STYLES)),
         col("DATE", True, "Five date formats mixed within the column.")),
        ("record_no", mrn, col("MRN", True)),
        ("ssn", lambda p: ssn_style(p, rng.choice(["dashed", "plain", "spaced"])),
         col("US_SSN", True)),
        ("zip", zipc, col("ZIP_CODE", True, "Mix of ZIP5 and ZIP+4.")),
        ("phone", lambda p: make_phone(rng, rng.choice(PHONE_STYLES)),
         col("PHONE_NUMBER", True)),
        ("admitted", lambda p: fmt_date(p["admit"], rng.choice(DATE_STYLES)),
         col("DATE", True)),
        ("age", lambda p: str(p["age"]), col("AGE", "conditional", AGE_NOTE)),
    ]
    return from_spec(spec, people, "Format variety within each column.")


def from_spec(spec, people, description):
    header = [h for h, _, _ in spec]
    rows = [[fn(p) for _, fn, _ in spec] for p in people]
    columns = {h: meta for h, _, meta in spec}
    if "age" in columns:
        columns["age"]["rows_over_89"] = sum(1 for p in people if p["age"] > 89)
    return header, rows, {"description": description, "columns": columns}


def build_freetext(people, rng, args):
    header = ["row_id", "visit_year", "note"]
    rows, spans = [], []
    for i, p in enumerate(people):
        tmpl = rng.choice(PHI_TEMPLATES if rng.random() < args.phi_rate
                          else CLEAN_TEMPLATES)
        text, s = render_note(tmpl, p, rng, args, i, "note")
        rows.append([str(i + 1), str(p["admit"].year), text])
        spans.extend(s)
    return header, rows, {
        "description": "Clinical-style notes; spans give exact PHI locations. "
                       "'row' is the 0-based data row index (excluding header).",
        "columns": {"row_id": col(None, False), "visit_year": col(None, False),
                    "note": col("FREE_TEXT", "conditional")},
        "rows_with_phi": len({s["row"] for s in spans if s["phi"]}),
        "spans": spans,
    }


def build_sparse(people, rng, args):
    header = ["row_id", "visit_year", "age_band", "sex", "diagnosis",
              "lab_value", "comments"]
    hit_rows = set(rng.sample(range(len(people)), min(args.sparse_hits, len(people))))
    rows, spans = [], []
    for i, p in enumerate(people):
        comment = ""
        if i in hit_rows:
            comment, s = render_note(rng.choice(PHI_TEMPLATES), p, rng, args, i, "comments")
            spans.extend(s)
        elif rng.random() < 0.05:
            comment = rng.choice(["see chart", "no issues", "pt declined flu shot"])
        rows.append([str(i + 1), str(p["admit"].year), age_band(p["age"]),
                     p["sex"], p["dx"], p["lab"], comment])
    return header, rows, {
        "description": f"PHI in only {len(hit_rows)} comment(s); row-sampling scans may miss it.",
        "columns": {**{h: col(None, False) for h in header[:-1]},
                    "comments": col("FREE_TEXT", "conditional")},
        "rows_with_phi": sorted(hit_rows),
        "spans": spans,
    }


def build_negative_control(people, rng, args):
    header = ["row_id", "birth_year", "age_band", "sex", "zip3", "visit_year",
              "diagnosis", "lab_name", "lab_value", "specialty"]
    rows = []
    for i, p in enumerate(people):
        old = p["age"] >= 90
        rows.append([
            str(i + 1),
            "" if old else str(p["dob"].year),   # suppressed for 90+
            age_band(p["age"]), p["sex"], rng.choice(SAFE_ZIP3),
            str(p["admit"].year),
            rng.choice(EPONYM_DX if rng.random() < 0.4 else DIAGNOSES),
            rng.choice(LAB_NAMES), f"{rng.uniform(0.5, 150):.1f}",
            rng.choice(SPECIALTIES),
        ])
    return header, rows, {
        "description": "Safe Harbor-style de-identified data. Expect NO PHI: any "
                       "detection is a false positive. Eponymous diagnoses "
                       "(e.g. Parkinson's, Crohn's) are common PERSON false positives. "
                       "birth_year is blank for patients aged 90+.",
        "columns": {h: col(None, False) for h in header},
    }


def build_quasi(people, rng, args):
    # Most rows are drawn from a small pool of common profiles so they share
    # their quasi-identifier combination with many others (high k). About 3%
    # are outliers with a rare diagnosis, which makes them unique (k = 1).
    header = ["row_id", "age_band", "sex", "zip3", "admit_year", "diagnosis"]
    pool = set()
    while len(pool) < 12:
        pool.add((rng.choice(["30-39", "40-49", "50-59", "60-69"]),
                  rng.choice(["F", "M"]), rng.choice(["627", "370", "537"]),
                  rng.choice(["2024", "2025"]),
                  rng.choice(["Essential hypertension", "Type 2 diabetes mellitus"])))
    pool = sorted(pool)
    rows = []
    for i in range(len(people)):
        profile = list(rng.choice(pool))
        if rng.random() < 0.03:
            profile[0] = rng.choice(["70-79", "80-89", "90+"])
            profile[4] = rng.choice(RARE_DX)
        rows.append([str(i + 1)] + profile)
    combos = Counter(tuple(r[1:]) for r in rows)
    unique_rows = [i for i, r in enumerate(rows) if combos[tuple(r[1:])] == 1]
    return header, rows, {
        "description": "No direct identifiers, but some rows are unique on "
                       "(age_band, sex, zip3, admit_year, diagnosis). Tests "
                       "k-anonymity / quasi-identifier checks, not entity detection.",
        "columns": {h: col(None, False) for h in header},
        "quasi_identifier_columns": header[1:],
        "unique_rows": unique_rows,
        "min_k": min(combos.values()) if combos else None,
    }

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


BUILDERS = {
    "labeled.csv": build_labeled,
    "obfuscated.csv": build_obfuscated,
    "formats.csv": build_formats,
    "freetext.csv": build_freetext,
    "sparse.csv": build_sparse,
    "negative_control.csv": build_negative_control,
    "quasi_identifiers.csv": build_quasi,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rows", type=int, default=10, help="rows per file (default 200)")
    ap.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    ap.add_argument("--out-dir", default="synthetic_phi", help="output directory")
    ap.add_argument("--mrn-format", default="########",
                    help="MRN pattern: '#'=digit, 'A'=letter, other chars literal "
                         "(default '########'). Match your institution's format.")
    ap.add_argument("--phi-rate", type=float, default=0.5,
                    help="fraction of freetext notes containing PHI (default 0.5)")
    ap.add_argument("--sparse-hits", type=int, default=3,
                    help="number of PHI comments in sparse.csv (default 3)")
    ap.add_argument("--realistic-ssn", action="store_true",
                    help="use SSN area numbers 001-899 instead of the never-issued "
                         "900-999 range. Some detectors reject 9xx as invalid; this "
                         "makes them testable but values could match real SSNs.")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    people = [make_person(rng, args) for _ in range(args.rows)]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "generator": "generate_synthetic_phi.py",
        "seed": args.seed, "rows_per_file": args.rows,
        "mrn_format": args.mrn_format, "realistic_ssn": args.realistic_ssn,
        "phi_semantics": "phi=true: HIPAA Safe Harbor identifier; "
                         "'conditional': identifying only for some values; "
                         "false: not a patient identifier.",
        "files": {},
    }
    for fname, builder in BUILDERS.items():
        header, rows, meta = builder(people, rng, args)
        with open(out / fname, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        manifest["files"][fname] = meta
        print(f"wrote {out / fname} ({len(rows)} rows)")

    with open(out / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"wrote {out / 'manifest.json'}")


if __name__ == "__main__":
    main()
