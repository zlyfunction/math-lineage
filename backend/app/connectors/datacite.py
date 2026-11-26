"""DataCite Dissertations API connector.

Official API: https://api.datacite.org/dois
Covers authoritative institutional repositories minting DOIs for dissertations with
explicit `contributors.contributorType == "Supervisor"`, including:
- University of Oxford (ORA, 10.5287/ora-...)
- University of Cambridge (Apollo, 10.17863/cam....)
- ETH Zurich Research Collection (10.3929/ethz-...)
- Ludwig-Maximilians-Universität München (10.5282/edoc....)
- CaltechTHESIS (10.7907/...)
- TU Delft, Imperial College London, etc.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from ..normalizer import clean_person_name

USER_AGENT = "MathLineage/1.0 (Open Verifiable Mathematics Genealogy)"
DATACITE_API = "https://api.datacite.org/dois"


def _http_get_json(url: str, timeout: int = 18) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.api+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _infer_institution_and_country(publisher: str, doi: str) -> tuple[str, str]:
    pub = (publisher or "").strip()
    low = pub.lower()
    if "oxford" in low or doi.startswith("10.5287/"):
        return "University of Oxford", "United Kingdom"
    if "cambridge" in low or "apollo" in low or doi.startswith("10.17863/"):
        return "University of Cambridge", "United Kingdom"
    if "eth zurich" in low or "ethz" in low or doi.startswith("10.3929/"):
        return "ETH Zürich", "Switzerland"
    if "caltech" in low or doi.startswith("10.7907/"):
        return "California Institute of Technology", "United States"
    if "münchen" in low or "munich" in low or doi.startswith("10.5282/"):
        return "Ludwig-Maximilians-Universität München", "Germany"
    if "delft" in low or doi.startswith("10.4233/"):
        return "Delft University of Technology", "Netherlands"
    if "imperial" in low:
        return "Imperial College London", "United Kingdom"
    if "edinburgh" in low:
        return "University of Edinburgh", "United Kingdom"
    if "warwick" in low:
        return "University of Warwick", "United Kingdom"
    if "bonn" in low or "heidelberg" in low or "göttingen" in low or "berlin" in low or "universität" in low:
        return pub, "Germany"
    if "university" in low and ("london" in low or "manchester" in low or "bristol" in low or "leeds" in low):
        return pub, "United Kingdom"
    return pub or "Unknown Institution", ""


def _parse_datacite_record(rec: Dict[str, Any], require_supervisor: bool = True) -> Optional[Dict[str, Any]]:
    attrs = rec.get("attributes") or {}
    doi = (attrs.get("doi") or rec.get("id") or "").strip()
    if not doi:
        return None

    creators = attrs.get("creators") or []
    titles = attrs.get("titles") or []
    contributors = attrs.get("contributors") or []
    supervisors = [
        clean_person_name(c.get("name", ""))
        for c in contributors
        if c.get("contributorType") == "Supervisor" and clean_person_name(c.get("name", ""))
    ]

    if not creators or not titles:
        return None
    if require_supervisor and not supervisors:
        return None

    creator_raw = creators[0].get("name") or f"{creators[0].get('givenName', '')} {creators[0].get('familyName', '')}"
    scholar_name = clean_person_name(creator_raw)
    supervisors = [s for s in dict.fromkeys(supervisors) if s.lower() != scholar_name.lower()]
    if not scholar_name or (require_supervisor and not supervisors):
        return None

    title = (titles[0].get("title") or "").strip()
    if not title:
        return None

    publisher = attrs.get("publisher") or ""
    university, country = _infer_institution_and_country(publisher, doi)
    year = attrs.get("publicationYear")
    try:
        year = int(year) if year else None
    except (ValueError, TypeError):
        year = None

    landing_url = attrs.get("url") or f"https://doi.org/{doi}"

    # Extract ORCID if present on creator
    orcid = ""
    for nid in creators[0].get("nameIdentifiers") or []:
        if "orcid" in (nid.get("nameIdentifierScheme") or "").lower():
            orcid = nid.get("nameIdentifier", "").replace("https://orcid.org/", "")
            break

    return {
        "scholar_name": scholar_name,
        "advisors": supervisors,
        "university": university,
        "country": country,
        "department": "Mathematics",
        "degree": "Ph.D.",
        "year": year,
        "thesis_title": title,
        "thesis_title_en": "",
        "source_repo": "DataCite",
        "source_record_id": doi,
        "doi": doi,
        "orcid": orcid,
        "landing_url": landing_url,
        "pdf_url": "",
        "raw_metadata": {
            "doi": doi,
            "publisher": publisher,
            "publicationYear": year,
            "titles": titles,
            "creators": creators,
            "contributors": contributors,
            "types": attrs.get("types"),
            "url": landing_url,
        },
    }


def fetch_datacite_math_dissertations(query: str = "", limit: int = 35, page: int = 1) -> List[Dict[str, Any]]:
    """Fetch verified mathematics dissertations with explicit Supervisor metadata from DataCite."""
    q = "mathematics AND contributors.contributorType:Supervisor"
    if query.strip():
        safe = query.strip().replace('"', "")
        q = f"({safe}) AND contributors.contributorType:Supervisor"
    params = urllib.parse.urlencode({
        "resource-type-id": "dissertation",
        "query": q,
        "page[size]": min(limit * 2, 60),
        "page[number]": page,
        "sort": "-published",
    })
    data = _http_get_json(f"{DATACITE_API}?{params}")
    results = []
    for rec in data.get("data", []):
        parsed = _parse_datacite_record(rec, require_supervisor=True)
        if parsed:
            results.append(parsed)
        if len(results) >= limit:
            break
    return results


def fetch_datacite_by_doi(doi_or_url: str) -> Optional[Dict[str, Any]]:
    """Verify and fetch a single dissertation by exact DOI."""
    s = doi_or_url.strip()
    m = re.search(r"(10\.\d{4,9}/[^\s]+)", s)
    if not m:
        return None
    doi = m.group(1).rstrip(".,;)")
    url = f"{DATACITE_API}/{urllib.parse.quote(doi, safe='')}"
    try:
        data = _http_get_json(url)
        rec = data.get("data")
        if not rec:
            return None
        return _parse_datacite_record(rec, require_supervisor=False)
    except Exception:
        return None
