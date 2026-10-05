from app import scanner as scanner_module
from app.config import Settings
from app.scanner import PhiScanner


def test_phi_split_across_chunk_boundary_is_found(monkeypatch):
    monkeypatch.setattr(scanner_module, "CHUNK_SIZE", 1000)
    monkeypatch.setattr(scanner_module, "CHUNK_OVERLAP", 100)
    s = PhiScanner(Settings())
    filler = "lorem ipsum dolor sit amet " * 37  # ~999 chars
    text = filler[:990] + " SSN 536-22-8726 " + filler
    result = s.scan(text)
    ssn_hits = [f for f in result.findings if f.entity_type == "US_SSN"]
    assert len(ssn_hits) == 1
    assert text[ssn_hits[0].start : ssn_hits[0].end] == "536-22-8726"
