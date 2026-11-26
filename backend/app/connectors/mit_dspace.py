"""MIT DSpace 7 REST API connector.

Official API: https://dspace.mit.edu/server/api/discover/search/objects
Strictly fetches MIT Ph.D. dissertations in Mathematics that include:
- dc.contributor.author
- dc.contributor.advisor (explicit thesis supervisor!)
- dc.identifier.uri (permanent MIT Handle URL)
- dc.title & dc.date.issued
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from ..normalizer import clean_person_name

USER_AGENT = "MathLineage/1.0 (Open Verifiable Mathematics Genealogy)"
MIT_SEARCH_API = "https://dspace.mit.edu/server/api/discover/search/objects"


def _http_get_json(url: str, timeout: int = 18) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _first_val(md: Dict[str, Any], key: str) -> str:
    vals = md.get(key) or []
    return vals[0].get("value", "").strip() if vals else ""


def _all_vals(md: Dict[str, Any], key: str) -> List[str]:
    return [v.get("value", "").strip() for v in (md.get(key) or []) if v.get("value")]


def _parse_mit_item(item: Dict[str, Any], require_phd_math: bool = True) -> Optional[Dict[str, Any]]:
    md = item.get("metadata") or {}
    dc_types = [t.lower() for t in _all_vals(md, "dc.type")]
    if "thesis" not in dc_types:
        return None

    degrees = _all_vals(md, "dc.description.degree")
    degree_text = " ".join(degrees)
    is_phd = bool(re.search(r"\b(ph\.?\s*d\.?|sc\.?\s*d\.?|doctor)\b", degree_text, re.I))
    if require_phd_math and degrees and not is_phd:
        return None

    depts = _all_vals(md, "dc.contributor.other") + _all_vals(md, "dc.contributor.department")
    dept_text = " | ".join(depts)
    if require_phd_math and dept_text and "mathematics" not in dept_text.lower():
        return None

    authors = _all_vals(md, "dc.contributor.author")
    advisors_raw = _all_vals(md, "dc.contributor.advisor")
    title = _first_val(md, "dc.title")
    uris = _all_vals(md, "dc.identifier.uri")
    handle = item.get("handle") or ""

    if not authors or not advisors_raw or not title:
        return None

    scholar_name = clean_person_name(authors[0])
    # Advisors may be concatenated with "and" or ";"
    advisors: List[str] = []
    for raw_adv in advisors_raw:
        # Remove leading notes like "Thesis supervisor:"
        parts = re.split(r"\s*;\s*|\s+and\s+", raw_adv)
        for p in parts:
            cleaned = clean_person_name(p)
            if cleaned and cleaned.lower() != scholar_name.lower() and len(cleaned.split()) >= 2:
                advisors.append(cleaned)
    # Deduplicate preserving order
    advisors = list(dict.fromkeys(advisors))
    if not scholar_name or not advisors:
        return None

    landing_url = ""
    for u in uris:
        if "hdl.handle.net" in u or "dspace.mit.edu" in u:
            landing_url = u.replace("http://hdl.handle.net/", "https://hdl.handle.net/")
            break
    if not landing_url and handle:
        landing_url = f"https://hdl.handle.net/{handle}"
    if not landing_url:
        return None

    issued = _first_val(md, "dc.date.issued") or _first_val(md, "dc.date.copyright")
    m_year = re.search(r"\b(19\d{2}|20\d{2})\b", issued)
    year = int(m_year.group(1)) if m_year else None

    record_id = handle or item.get("uuid") or landing_url
    return {
        "scholar_name": scholar_name,
        "advisors": advisors,
        "university": "Massachusetts Institute of Technology",
        "country": "United States",
        "department": depts[0] if depts else "Department of Mathematics",
        "degree": "Ph.D." if is_phd or not degree_text else degree_text,
        "year": year,
        "thesis_title": title,
        "thesis_title_en": "",
        "source_repo": "MIT DSpace",
        "source_record_id": record_id,
        "doi": "",
        "landing_url": landing_url,
        "pdf_url": "",
        "raw_metadata": {
            "uuid": item.get("uuid"),
            "handle": handle,
            "title": title,
            "author": authors,
            "advisor": advisors_raw,
            "degree": degrees,
            "department": depts,
            "issued": issued,
            "uri": uris,
        },
    }


def fetch_mit_math_theses(query: str = "", limit: int = 35, page: int = 0) -> List[Dict[str, Any]]:
    """Fetch MIT Mathematics Ph.D. dissertations with explicit advisor metadata."""
    q = '"Dept. of Mathematics" Ph.D. Thesis'
    if query.strip():
        q = f'{query.strip()} "Dept. of Mathematics" Thesis'
    params = urllib.parse.urlencode({
        "query": q,
        "dsoType": "item",
        "size": min(limit * 2, 60),
        "page": page,
        "sort": "dc.date.issued,DESC",
    })
    data = _http_get_json(f"{MIT_SEARCH_API}?{params}")
    objs = data.get("_embedded", {}).get("searchResult", {}).get("_embedded", {}).get("objects", [])
    results = []
    for o in objs:
        item = o.get("_embedded", {}).get("indexableObject")
        if not item:
            continue
        parsed = _parse_mit_item(item, require_phd_math=True)
        if parsed:
            results.append(parsed)
        if len(results) >= limit:
            break
    return results


def fetch_mit_by_handle(handle_or_url: str) -> Optional[Dict[str, Any]]:
    """Verify and fetch a single MIT DSpace thesis by Handle (e.g., 1721.1/8641) or URL."""
    s = handle_or_url.strip()
    m = re.search(r"(1721\.1/\d+)", s)
    if not m:
        return None
    handle = m.group(1)
    # Direct DSpace 7 PID resolver!
    url = f"https://dspace.mit.edu/server/api/pid/find?id={urllib.parse.quote(handle)}"
    try:
        item = _http_get_json(url)
        return _parse_mit_item(item, require_phd_math=False)
    except Exception:
        # Fallback to search
        params = urllib.parse.urlencode({"query": handle, "dsoType": "item", "size": 3})
        data = _http_get_json(f"{MIT_SEARCH_API}?{params}")
        objs = data.get("_embedded", {}).get("searchResult", {}).get("_embedded", {}).get("objects", [])
        for o in objs:
            item = o.get("_embedded", {}).get("indexableObject")
            if item and item.get("handle") == handle:
                return _parse_mit_item(item, require_phd_math=False)
    return None
