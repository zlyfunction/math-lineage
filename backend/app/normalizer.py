"""Name normalization and scholar matching utilities.

Handles bibliographic author/advisor strings from institutional repositories such as:
- MIT DSpace: "Bradley, Philip H. (Philip Harlan), 1973-" -> "Philip H. Bradley"
- DataCite: "Spalding, CA" -> "CA Spalding"
- HAL / theses.fr: "Aurélien Garivier" -> "Aurélien Garivier"
"""

from __future__ import annotations

import re
import unicodedata
from typing import Tuple


_HONORIFICS = {
    "prof", "prof.", "dr", "dr.", "professor", "mr", "mr.", "ms", "ms.",
    "mrs", "mrs.", "sir", "hd", "hdr", "phd", "ph.d.", "m.", "mme", "mlle",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def clean_person_name(raw: str) -> str:
    """Clean raw repository author/advisor string into canonical 'Given Family' form."""
    if not raw:
        return ""
    s = raw.strip()
    # Remove trailing periods, semicolons, colons
    s = re.sub(r"[\s.;:]+$", "", s)
    # Remove MARC / library birth-death year suffixes like ", 1973-" or ", 1945-2020"
    s = re.sub(r",?\s*\b\d{4}\s*-\s*(\d{4})?\b", "", s)
    # Remove parenthetical expansions like "(Philip Harlan)" or "(Supervisor)"
    s = re.sub(r"\([^)]*\)", "", s)
    # Remove role annotations like "thesis advisor" or "advisor:"
    s = re.sub(r"\b(thesis\s+supervisor|thesis\s+advisor|supervisor|advisor|directeur|directrice)\b[:\s-]*", "", s, flags=re.I)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip(" ,.;:")

    # Convert "Family, Given Middle" -> "Given Middle Family"
    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if len(parts) == 2:
            family, given = parts[0], parts[1]
            # Guard against suffixes like "Jr." or "III"
            if given.lower().rstrip(".") not in {"jr", "sr", "ii", "iii", "iv"}:
                s = f"{given} {family}"
            else:
                s = f"{family} {given}"
        elif len(parts) >= 3:
            s = f"{parts[1]} {parts[0]}"

    # Strip leading honorifics
    tokens = s.split()
    while tokens and tokens[0].lower() in _HONORIFICS:
        tokens.pop(0)
    s = " ".join(tokens).strip(" ,.;:")
    return s


def normalize_key(name: str) -> str:
    """Produce accent-free, punctuation-free lowercase key for exact matching."""
    cleaned = clean_person_name(name)
    ascii_name = strip_accents(cleaned).lower()
    ascii_name = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", ascii_name)
    return re.sub(r"\s+", " ", ascii_name).strip()


def split_name(name: str) -> Tuple[str, str]:
    """Return (given_name, family_name) heuristic split."""
    cleaned = clean_person_name(name)
    parts = cleaned.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def loose_match_key(name: str) -> str:
    """Generate 'first_initial family' key for cautious cross-source disambiguation."""
    norm = normalize_key(name)
    parts = norm.split()
    if len(parts) < 2:
        return norm
    return f"{parts[0][0]} {parts[-1]}"
