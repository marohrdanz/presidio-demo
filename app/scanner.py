"""Presidio-backed PHI scanner."""

from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from app.config import Settings
from app.recognizers import custom_recognizers

# spaCy refuses texts longer than nlp.max_length (1,000,000 chars by default),
# and memory use grows with length, so large files are scanned in chunks.
CHUNK_SIZE = 100_000
CHUNK_OVERLAP = 200


@dataclass
class Finding:
    entity_type: str
    score: float
    start: int
    end: int


@dataclass
class ScanResult:
    contains_phi: bool
    findings: list[Finding]


class PhiScanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": settings.spacy_model}],
            }
        ).create_engine()
        self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
        for recognizer in custom_recognizers():
            self.analyzer.registry.add_recognizer(recognizer)

    def scan(self, text: str) -> ScanResult:
        findings: list[Finding] = []
        seen: set[tuple[str, int, int]] = set()
        for offset, chunk in _chunks(text):
            results = self.analyzer.analyze(
                text=chunk,
                language="en",
                entities=self.settings.entities,
                score_threshold=self.settings.score_threshold,
            )
            for r in results:
                key = (r.entity_type, r.start + offset, r.end + offset)
                if key in seen:  # same hit found in the overlap of two chunks
                    continue
                seen.add(key)
                findings.append(Finding(r.entity_type, round(r.score, 2), *key[1:]))
        findings.sort(key=lambda f: f.start)
        return ScanResult(contains_phi=bool(findings), findings=findings)


def _chunks(text: str):
    if len(text) <= CHUNK_SIZE:
        yield 0, text
        return
    start = 0
    while start < len(text):
        yield start, text[start : start + CHUNK_SIZE]
        start += CHUNK_SIZE - CHUNK_OVERLAP
