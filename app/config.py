"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass, field

# Entities that count as PHI by default. These map to HIPAA Safe Harbor
# identifiers (names, contact info, SSNs, record/plan/account/license numbers,
# IPs, URLs, ...). Generic DATE_TIME and LOCATION are deliberately excluded
# because they fire on almost any prose ("Monday", "2024", "Denver"); dates of
# birth are covered by the more targeted DATE_OF_BIRTH recognizer instead.
DEFAULT_PHI_ENTITIES = [
    "PERSON",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "US_SSN",
    "US_ITIN",
    "US_DRIVER_LICENSE",
    "US_PASSPORT",
    "US_BANK_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "MEDICAL_LICENSE",
    "UK_NHS",
    "MEDICAL_RECORD_NUMBER",
    "HEALTH_PLAN_ID",
    "DATE_OF_BIRTH",
]


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    spacy_model: str = field(default_factory=lambda: os.getenv("PHI_SPACY_MODEL", "en_core_web_lg"))
    score_threshold: float = field(default_factory=lambda: float(os.getenv("PHI_SCORE_THRESHOLD", "0.5")))
    entities: list[str] = field(default_factory=lambda: _env_list("PHI_ENTITIES", DEFAULT_PHI_ENTITIES))
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv("PHI_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))))


def get_settings() -> Settings:
    return Settings()
