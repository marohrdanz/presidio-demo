"""Shared helpers for matching column headings."""

import re


def tokens(heading: str) -> list[str]:
    """Split a heading into lowercase words: "patientDOB" and "Patient DOB" -> ["patient", "dob"]."""
    heading = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", heading)  # camelCase -> camel_Case
    return [t for t in re.split(r"[^a-z0-9]+", heading.lower()) if t]


def contains(toks: list[str], pattern: tuple[str, ...], allowed_suffix: set[str] | None = None) -> bool:
    """True if ``pattern`` appears contiguously in ``toks``.

    With ``allowed_suffix``, only those tokens may follow the match.
    """
    n = len(pattern)
    for i in range(len(toks) - n + 1):
        if tuple(toks[i : i + n]) == pattern and (
            allowed_suffix is None or all(t in allowed_suffix for t in toks[i + n :])
        ):
            return True
    return False
