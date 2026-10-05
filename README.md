# presidio-demo: PHI upload scanner

:warning: **Warning**: This is just a quick, untested, ai-generated mockup of ideas :warning:

A small FastAPI service that scans uploaded files for **protected health information (PHI)** using [Microsoft Presidio](https://microsoft.github.io/presidio/) and **rejects** any file that contains suspected PHI.

## How it works

1. A client `POST`s a file to `/scan` (multipart form field `file`).
2. Text is extracted from the file (plain text formats, PDF, DOCX).
3. Presidio's `AnalyzerEngine` (spaCy NER + pattern recognizers) scans the text for PHI entities.
4. For tabular files, the column headings are checked too (see [Column heading check](#column-heading-check)).
5. If anything scores at or above the threshold, or a column heading names a PHI field, the file is rejected with **HTTP 422**. Otherwise it's accepted with **HTTP 200**.

The response lists the entity types, confidence scores and character offsets that were found. **The matched text is never echoed back**, so the scanner's response doesn't leak PHI into client logs.

### What counts as PHI

The default entity list is aimed at HIPAA Safe Harbor identifiers:

| Source | Entities |
| --- | --- |
| Presidio built-ins | `PERSON`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `US_SSN`, `US_ITIN`, `US_DRIVER_LICENSE`, `US_PASSPORT`, `US_BANK_NUMBER`, `CREDIT_CARD`, `IBAN_CODE`, `IP_ADDRESS`, `MEDICAL_LICENSE`, `UK_NHS` |
| Custom (`app/recognizers.py`) | `MEDICAL_RECORD_NUMBER`, `HEALTH_PLAN_ID` (member/policy IDs, Medicare MBI), `DATE_OF_BIRTH` |

Presidio's generic `DATE_TIME` and `LOCATION` entities are **off by default**: they fire on almost any prose ("Monday", "2024", "Denver") and would reject nearly every file. Dates of birth are caught by the targeted `DATE_OF_BIRTH` recognizer instead. You can turn them back on with `PHI_ENTITIES` if you want a stricter gate.

### Column heading check

Presidio scans a CSV as flat text, so a value like `1971-04-12` under a `dob` heading is just a bare date by the time it reaches the analyzer. A CSV of birth dates with no other identifiers would otherwise be accepted. To close that gap, `app/columns.py` also looks at the headings of CSV/TSV files, Word tables, and JSON keys:

- **Strong headings** name a direct identifier (`dob`, `ssn`, `mrn`, `patient_name`, `last_name`, `member_id`, `phone`, `email`, ...). Any populated column with one of these headings causes a rejection.
- **Weak headings** are only identifying in a health context (`name`, `patient`, `address`, `city`, ...). They cause a rejection only if the file also has a populated clinical column (`diagnosis`, `icd10`, `medication`, `allergies`, ...). So `name,sku,price` passes, but `name,diagnosis` doesn't.
- **Zip, age and date columns** are checked value by value against the Safe Harbor rules below, rather than rejected on their heading.
- **Empty columns don't count**, so a template with just a heading row is accepted.

Headings are matched on normalised tokens (`patientDOB`, `Patient DOB` and `patient_dob` all match `dob`). A match may only be followed by suffixes like `number`, `id` or `no`, so `phone_number` matches but `phone_model` doesn't.

Column findings appear in the response with `"entity_type": "PHI_COLUMN"`, the heading in `column`, the reason in `rule` (`identifier_heading` or one of the Safe Harbor rules below) and the number of affected values in `count`. Headings are labels, not values, so echoing them doesn't leak PHI. Edit the lists in `app/columns.py` to match your own schemas, or turn the check off with `PHI_CHECK_COLUMNS=false`.

### Safe Harbor value rules

HIPAA's Safe Harbor method doesn't ban zip codes, ages or dates outright; it bans them above a certain precision. `app/safe_harbor.py` checks the values in columns recognised by heading:

| Column kind | Example headings | Allowed | Rejected (`rule`) |
| --- | --- | --- | --- |
| Zip code | `zip`, `zip_code`, `postal_code`, `zip3` | First 3 digits (`803`, `803xx`) | 4+ digits (`zip_more_than_3_digits`); a 3-digit prefix covering 20,000 or fewer people, which must be `000` (`restricted_zip3`) |
| Age | `age`, `age_at_admission` | 0-89, or a grouped value like `90+` | Over 89 (`age_over_89`) |
| Birth year | `birth_year`, `yob` | Years implying age 89 or under | Years implying age over 89 (`birth_year_implies_age_over_89`) |
| Birth date | `dob`, `date_of_birth` | Year only, same age rule as birth year | Anything more specific than a year (`date_more_specific_than_year`) |
| Event date | `admit_date`, `discharge_date`, `dos`, `visit_date`, `date_of_death` | Year only | Anything more specific than a year (`date_more_specific_than_year`) |

How these rules apply:

- **Date checks are conservative.** Any value with digits that isn't a bare 4-digit year counts as too specific, including `2024-01`, `20240105` and Excel serial dates. Values with no digits (`unknown`, `N/A`) pass.
- **Birth dates are checked in every file.** Zip, age, birth-year and event-date columns are checked only in clinical files, the same rule as weak headings.
- **Restricted zip prefixes:** the list in `RESTRICTED_ZIP3` is HHS's list based on 2000 Census data. Review it against current Census figures before relying on it.
- **Free text isn't covered.** These rules apply to table columns only. Dates and zips in free text aren't checked.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m spacy download en_core_web_lg
uvicorn app.main:app --reload
```

Interactive API docs are at http://localhost:8000/docs.

### With Docker

```bash
docker build -t phi-scanner .
docker run -p 8000:8000 phi-scanner
```

## Usage

```bash
$ curl -F file=@note.txt http://localhost:8000/scan
{"filename":"note.txt","status":"rejected","contains_phi":true,
 "entity_counts":{"PERSON":1,"DATE_OF_BIRTH":1,"MEDICAL_RECORD_NUMBER":1},
 "findings":[{"entity_type":"PERSON","score":0.85,"start":9,"end":23}, ...]}
# HTTP 422

$ curl -F file=@retro.txt http://localhost:8000/scan
{"filename":"retro.txt","status":"accepted","contains_phi":false,"entity_counts":{},"findings":[]}
# HTTP 200
```

| Status | Meaning |
| --- | --- |
| 200 | Accepted, no suspected PHI |
| 422 | Rejected, suspected PHI found (body lists findings) |
| 400 | File couldn't be read (corrupt, or an image-only PDF with no text layer) |
| 413 | File larger than `PHI_MAX_UPLOAD_BYTES` |
| 415 | Unsupported file extension |

Supported extensions: `.txt .csv .tsv .json .md .xml .html .htm .log .hl7 .yaml .yml .pdf .docx`

## Configuration

| Env var | Default | Description |
| --- | --- | --- |
| `PHI_SCORE_THRESHOLD` | `0.5` | Minimum Presidio confidence for a finding to count. Lower is stricter. |
| `PHI_ENTITIES` | see above | Comma-separated entity types that cause rejection. |
| `PHI_CHECK_COLUMNS` | `true` | Also reject tabular files whose column headings name PHI fields. |
| `PHI_SPACY_MODEL` | `en_core_web_lg` | spaCy model used for NER (must be installed). |
| `PHI_MAX_UPLOAD_BYTES` | `10485760` | Max upload size (10 MiB). |

## Tests

```bash
pytest
```

## Limitations

This is a screening tool, not a compliance guarantee. Automated detection has both false negatives and false positives:

- **No OCR.** Image-only PDFs and images are refused (400/415) rather than scanned.
- **English only.**
- **Free-text names** are found by spaCy NER, which can miss unusual names or flag non-patient names (e.g. a doctor's or author's name).
- **Format-specific identifiers** (MRNs, member IDs) vary by organization. Tune the patterns in `app/recognizers.py` to match your own systems.
- Other formats (XLSX, HL7 parsing, DICOM metadata, images) are not handled.
- **No uniqueness check.** A file can follow every Safe Harbor value rule and still single people out, e.g. one row in a small dataset with a rare diagnosis. A k-anonymity check on quasi-identifier columns is not implemented yet.
