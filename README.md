# presidio-demo: PHI upload scanner

A small FastAPI service that scans uploaded files for **protected health information (PHI)** using [Microsoft Presidio](https://microsoft.github.io/presidio/) and **rejects** any file that contains suspected PHI.

## How it works

1. A client `POST`s a file to `/scan` (multipart form field `file`).
2. Text is extracted from the file (plain text formats, PDF, DOCX).
3. Presidio's `AnalyzerEngine` (spaCy NER + pattern recognizers) scans the text for PHI entities.
4. If anything scores at or above the threshold, the file is rejected with **HTTP 422**. Otherwise it's accepted with **HTTP 200**.

The response lists the entity types, confidence scores and character offsets that were found. **The matched text is never echoed back**, so the scanner's response doesn't leak PHI into client logs.

### What counts as PHI

The default entity list is aimed at HIPAA Safe Harbor identifiers:

| Source | Entities |
| --- | --- |
| Presidio built-ins | `PERSON`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `US_SSN`, `US_ITIN`, `US_DRIVER_LICENSE`, `US_PASSPORT`, `US_BANK_NUMBER`, `CREDIT_CARD`, `IBAN_CODE`, `IP_ADDRESS`, `MEDICAL_LICENSE`, `UK_NHS` |
| Custom (`app/recognizers.py`) | `MEDICAL_RECORD_NUMBER`, `HEALTH_PLAN_ID` (member/policy IDs, Medicare MBI), `DATE_OF_BIRTH` |

Presidio's generic `DATE_TIME` and `LOCATION` entities are **off by default**: they fire on almost any prose ("Monday", "2024", "Denver") and would reject nearly every file. Dates of birth are caught by the targeted `DATE_OF_BIRTH` recognizer instead. You can turn them back on with `PHI_ENTITIES` if you want a stricter gate.

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
