"""HAL / TEL (French & European Open Thesis Archive) connector.

Official API: https://api.archives-ouvertes.fr/search/
Strictly fetches doctoral theses (docType_s:THESE) in Mathematics (domain_s:0.math)
that contain an explicit thesis advisor (director_s) and a verifiable landing URL / PDF.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from ..normalizer import clean_person_name

USER_AGENT = "MathLineage/1.0 (Open Verifiable Mathematics Genealogy)"
HAL_API = "https://api.archives-ouvertes.fr/search/"

HAL_FIELDS = ",".join([
    "halId_s",
    "title_s",
    "en_title_s",
    "fr_title_s",
    "authFullName_s",
    "director_s",
    "producedDateY_i",
    "defenseDateY_i",
    "authorityInstitution_s",
    "uri_s",
    "fileMain_s",
    "doiId_s",
    "domain_s",
])


def _http_get_json(url: str, timeout: int = 18) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_hal_doc(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    hal_id = doc.get("halId_s")
    uri = doc.get("uri_s") or (f"https://theses.hal.science/{hal_id}" if hal_id else "")
    authors = doc.get("authFullName_s") or []
    directors = doc.get("director_s") or []
    titles = doc.get("title_s") or []

    if not hal_id or not uri or not authors or not directors or not titles:
        return None

    scholar_name = clean_person_name(authors[0])
    advisors = [clean_person_name(d) for d in directors if clean_person_name(d)]
    # Avoid self-advising artifacts
    advisors = [a for a in advisors if a.lower() != scholar_name.lower()]
    if not scholar_name or not advisors:
        return None

    en_titles = doc.get("en_title_s") or []
    fr_titles = doc.get("fr_title_s") or []
    title_primary = titles[0].strip()
    title_en = en_titles[0].strip() if en_titles else (titles[1].strip() if len(titles) > 1 else "")
    if not title_en and fr_titles and len(titles) > 1:
        for t in titles:
            if t != fr_titles[0]:
                title_en = t.strip()
                break

    insts = doc.get("authorityInstitution_s") or []
    university = insts[0].strip() if insts else ""
    year = doc.get("defenseDateY_i") or doc.get("producedDateY_i")
    try:
        year = int(year) if year else None
    except (ValueError, TypeError):
        year = None

    return {
        "scholar_name": scholar_name,
        "advisors": advisors,
        "university": university,
        "country": "France",
        "department": "Mathematics",
        "degree": "Ph.D.",
        "year": year,
        "thesis_title": title_primary,
        "thesis_title_en": title_en if title_en != title_primary else "",
        "source_repo": "HAL/TEL",
        "source_record_id": hal_id,
        "doi": doc.get("doiId_s") or "",
        "landing_url": uri,
        "pdf_url": doc.get("fileMain_s") or "",
        "raw_metadata": doc,
    }


def fetch_hal_math_theses(query: str = "", limit: int = 40, start: int = 0) -> List[Dict[str, Any]]:
    """Fetch recent verified Mathematics PhD theses with advisors from HAL/TEL."""
    base_q = "docType_s:THESE AND domain_s:0.math AND director_s:*"
    if query.strip():
        safe = query.strip().replace('"', "")
        base_q = f'({base_q}) AND ({safe})'

    params = urllib.parse.urlencode({
        "q": base_q,
        "fl": HAL_FIELDS,
        "rows": limit,
        "start": start,
        "sort": "producedDateY_i desc",
        "wt": "json",
    })
    data = _http_get_json(f"{HAL_API}?{params}")
    docs = data.get("response", {}).get("docs", [])
    results = []
    for d in docs:
        parsed = _parse_hal_doc(d)
        if parsed:
            results.append(parsed)
    return results


def fetch_hal_by_id(hal_id: str) -> Optional[Dict[str, Any]]:
    """Verify and fetch a single dissertation by HAL/TEL ID (e.g. tel-05583740)."""
    clean_id = hal_id.strip().rstrip("/")
    if "/" in clean_id:
        clean_id = clean_id.split("/")[-1]
    # Strip trailing version suffix like v1
    if len(clean_id) > 3 and clean_id[-2] == "v" and clean_id[-1].isdigit():
        clean_id = clean_id[:-2]

    params = urllib.parse.urlencode({
        "q": f'halId_s:"{clean_id}"',
        "fl": HAL_FIELDS,
        "rows": 1,
        "wt": "json",
    })
    data = _http_get_json(f"{HAL_API}?{params}")
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        return None
    return _parse_hal_doc(docs[0])
