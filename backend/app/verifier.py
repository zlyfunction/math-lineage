"""Real-time dissertation verification against authoritative institutional APIs."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional

from .connectors.datacite import fetch_datacite_by_doi, fetch_datacite_math_dissertations
from .connectors.hal import fetch_hal_by_id, fetch_hal_math_theses
from .connectors.mit_dspace import fetch_mit_by_handle, fetch_mit_math_theses
from .connectors.nyu_courant import fetch_nyu_courant_phds, parse_dissertation_pdf_url
from .connectors.theses_fr import fetch_theses_fr_by_id, fetch_theses_fr_math
from .normalizer import normalize_key


def _enrich_with_db_matches(conn: sqlite3.Connection, candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Check whether the dissertation's author or advisors already exist in our genealogy DB."""
    notes: List[str] = []
    norm_author = normalize_key(candidate.get("scholar_name", ""))
    existing_scholar = None
    if norm_author:
        row = conn.execute(
            "SELECT id, name, university, year, verification_status, mgp_id FROM scholars WHERE normalized_name = ? LIMIT 1",
            (norm_author,),
        ).fetchone()
        if row:
            existing_scholar = dict(row)
            notes.append(f"Author matches existing scholar #{row['id']} ({row['name']}); approving will attach dissertation proof.")

    matched_advisors: List[Dict[str, Any]] = []
    for adv in candidate.get("advisors", []):
        norm_adv = normalize_key(adv)
        row = None
        if norm_adv:
            row = conn.execute(
                "SELECT id, name, university, year, mgp_id, verification_status FROM scholars WHERE normalized_name = ? LIMIT 1",
                (norm_adv,),
            ).fetchone()
            if not row and len(norm_adv.split()) == 2:
                toks = norm_adv.split()
                row = conn.execute(
                    "SELECT id, name, university, year, mgp_id, verification_status FROM scholars WHERE normalized_name LIKE ? LIMIT 1",
                    (f"{toks[0]} _ {toks[1]}",),
                ).fetchone()
        if row:
            matched_advisors.append({"raw_name": adv, "matched": True, "scholar": dict(row)})
            notes.append(f"Advisor '{adv}' linked to existing lineage node #{row['id']} ({row['name']}).")
        else:
            matched_advisors.append({"raw_name": adv, "matched": False, "scholar": None})

    # Check if exact dissertation already in DB
    dup = conn.execute(
        "SELECT id, scholar_id FROM dissertations WHERE source_repo = ? AND source_record_id = ?",
        (candidate["source_repo"], candidate["source_record_id"]),
    ).fetchone()
    if dup:
        notes.append(f"This exact dissertation record is already verified in the database (scholar #{dup['scholar_id']}).")

    if not candidate.get("advisors"):
        notes.append("WARNING: Repository metadata did not include a structured advisor/supervisor field.")

    candidate["existing_scholar_match"] = existing_scholar
    candidate["matched_advisors"] = matched_advisors
    candidate["verification_notes"] = notes
    candidate["already_ingested"] = dup is not None
    return candidate


def verify_dissertation_identifier(
    conn: sqlite3.Connection,
    identifier: str,
    source_hint: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve and verify a dissertation identifier (DOI, HAL ID, theses.fr ID, MIT Handle, or direct official .pdf URL) live."""
    raw = identifier.strip()
    result = None

    # Direct official university dissertation PDF URL verification!
    if raw.lower().startswith(("http://", "https://")) and raw.lower().split("?")[0].endswith(".pdf"):
        parsed_pdf = parse_dissertation_pdf_url(raw, max_pages=3)
        if parsed_pdf.get("thesis_title") and parsed_pdf.get("scholar_name"):
            repo_name = "NYU Courant" if "nyu.edu" in raw.lower() else "Direct Thesis PDF"
            rec_id = raw.split("/")[-1].split("?")[0]
            result = {
                "scholar_name": parsed_pdf["scholar_name"],
                "advisors": parsed_pdf["advisors"],
                "university": parsed_pdf["university"],
                "country": "United States" if ".edu" in raw.lower() else "",
                "department": "",
                "degree": "Ph.D.",
                "year": parsed_pdf["year"],
                "thesis_title": parsed_pdf["thesis_title"],
                "thesis_title_en": "",
                "source_repo": repo_name,
                "source_record_id": rec_id,
                "doi": "",
                "landing_url": raw,
                "pdf_url": raw,
                "raw_metadata": {
                    "pdf_url": raw,
                    "verification_method": "Official Dissertation PDF Title-Page Extraction",
                    "pdf_title_page_excerpt": parsed_pdf.get("page1_excerpt", ""),
                },
            }
    elif source_hint == "mit_dspace" or "1721.1/" in raw or "dspace.mit.edu" in raw:
        result = fetch_mit_by_handle(raw)
    elif source_hint == "hal" or re.search(r"\b(tel|hal)-\d+", raw, re.I) or "hal.science" in raw:
        result = fetch_hal_by_id(raw)
    elif source_hint == "theses_fr" or "theses.fr" in raw or re.match(r"^(s\d{5,}|\d{4}[A-Z]{2,}\w+)$", raw):
        result = fetch_theses_fr_by_id(raw)
    elif source_hint == "datacite" or re.search(r"10\.\d{4,9}/", raw):
        result = fetch_datacite_by_doi(raw)
    else:
        for fn in (fetch_datacite_by_doi, fetch_hal_by_id, fetch_theses_fr_by_id, fetch_mit_by_handle):
            try:
                result = fn(raw)
                if result:
                    break
            except Exception:
                continue

    if not result:
        return None
    return _enrich_with_db_matches(conn, result)


def search_live_repositories(
    conn: sqlite3.Connection,
    query: str,
    source: str = "all",
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """Search authoritative dissertation repositories live and return verifiable candidates."""
    sources = ["nyu_courant", "hal", "theses_fr", "mit_dspace", "datacite"] if source == "all" else [source]
    per_src = max(3, limit // len(sources) + 1)
    candidates: List[Dict[str, Any]] = []

    for src in sources:
        try:
            if src == "nyu_courant":
                recs = fetch_nyu_courant_phds(query=query, limit=per_src)
            elif src == "hal":
                recs = fetch_hal_math_theses(query=query, limit=per_src)
            elif src == "theses_fr":
                recs = fetch_theses_fr_math(query=query, limit=per_src)
            elif src == "mit_dspace":
                recs = fetch_mit_math_theses(query=query, limit=per_src)
            elif src == "datacite":
                recs = fetch_datacite_math_dissertations(query=query, limit=per_src)
            else:
                recs = []
            for r in recs:
                candidates.append(_enrich_with_db_matches(conn, r))
        except Exception:
            continue

    return candidates[:limit]
