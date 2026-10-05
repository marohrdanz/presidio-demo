"""Custom Presidio recognizers for healthcare-specific identifiers."""

from presidio_analyzer import Pattern, PatternRecognizer


def medical_record_number_recognizer() -> PatternRecognizer:
    # Bare 6-10 digit numbers are everywhere, so the base score is low and
    # relies on context words ("MRN", "medical record", ...) to push it over
    # the threshold. The explicitly labelled form scores high on its own.
    return PatternRecognizer(
        supported_entity="MEDICAL_RECORD_NUMBER",
        patterns=[
            Pattern("mrn_labelled", r"(?i)\bMRN\s*[:#]?\s*[A-Z]{0,3}\d{5,12}\b", 0.9),
            Pattern("mrn_bare", r"\b[A-Z]{0,3}\d{6,10}\b", 0.2),
        ],
        context=["mrn", "medical", "record", "chart", "patient"],
    )


def health_plan_id_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="HEALTH_PLAN_ID",
        patterns=[
            Pattern(
                "member_id_labelled",
                r"(?i)\b(?:member|subscriber|policy|beneficiary|medicaid|medicare|insurance)\s*"
                r"(?:id|no\.?|number|#)\s*[:#]?\s*[A-Z0-9-]{6,20}\b",
                0.85,
            ),
            # Medicare Beneficiary Identifier (MBI) format, e.g. 1EG4-TE5-MK73.
            Pattern(
                "mbi",
                r"\b[1-9][AC-HJKMNP-RT-Yac-hjkmnp-rt-y][AC-HJKMNP-RT-Yac-hjkmnp-rt-y0-9]\d-?"
                r"[AC-HJKMNP-RT-Yac-hjkmnp-rt-y][AC-HJKMNP-RT-Yac-hjkmnp-rt-y0-9]\d-?"
                r"[AC-HJKMNP-RT-Yac-hjkmnp-rt-y]{2}\d{2}\b",
                0.4,
            ),
        ],
        context=["member", "subscriber", "policy", "insurance", "medicare", "medicaid", "beneficiary", "plan"],
    )


def date_of_birth_recognizer() -> PatternRecognizer:
    date = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4})"
    return PatternRecognizer(
        supported_entity="DATE_OF_BIRTH",
        patterns=[
            Pattern("dob_labelled", rf"(?i)\b(?:DOB|D\.O\.B\.|date of birth|birth ?date|born(?: on)?)\s*[:#]?\s*{date}", 0.9),
        ],
    )


def custom_recognizers() -> list[PatternRecognizer]:
    return [
        medical_record_number_recognizer(),
        health_plan_id_recognizer(),
        date_of_birth_recognizer(),
    ]
