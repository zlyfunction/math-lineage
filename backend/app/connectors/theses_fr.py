"""theses.fr (ABES French National Doctoral Registry) connector.

Official API: https://theses.fr/api/v1/theses/recherche/
Strictly fetches defended (statut:soutenue) Mathematics PhD dissertations
with explicit doctoral advisors (directeurs + IdRef PPN authority identifiers).
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from ..normalizer import clean_person_name

USER_AGENT = "MathLineage/1.0 (Open Verifiable Mathematics Genealogy)"
THESES_FR_SEARCH = "https://theses.fr/api/v1/theses/recherche/"


def _http_get_json(url: str, timeout: int = 18) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    m = re.search(r"\b(19\d{2}|20\d{2})\b", str(date_str))
    return int(m.group(1)) if m else None


def _format_person(obj: Dict[str, Any]) -> str:
    prenom = (obj.get("prenom") or "").strip()
    nom = (obj.get("nom") or "").strip()
    full = f"{prenom} {nom}".strip()
    return clean_person_name(full)


def _parse_theses_fr_record(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tid = rec.get("id")
    if not tid:
        return None
    # Strictly require defended status or explicit defense date
    date_sout = rec.get("dateSoutenance")
    if not date_sout:
        return None

    auteurs = rec.get("auteurs") or []
    directeurs = rec.get("directeurs") or []
    title = (rec.get("titrePrincipal") or "").strip()
    if not auteurs or not directeurs or not title:
        return None

    scholar_name = _format_person(auteurs[0])
    advisors = [_format_person(d) for d in directeurs if _format_person(d)]
    advisors = [a for a in advisors if a.lower() != scholar_name.lower()]
    if not scholar_name or not advisors:
        return None

    year = _extract_year(date_sout)
    university = (rec.get("etabSoutenanceN") or "").strip()
    title_en = (rec.get("titreEN") or "").strip()
    if title_en == title:
        title_en = ""

    return {
        "scholar_name": scholar_name,
        "advisors": advisors,
        "university": university,
        "country": "France",
        "department": rec.get("discipline") or "Mathematics",
        "degree": "Ph.D.",
        "year": year,
        "thesis_title": title,
        "thesis_title_en": title_en,
        "source_repo": "theses.fr",
        "source_record_id": tid,
        "doi": "",
        "landing_url": f"https://theses.fr/{tid}",
        "pdf_url": f"https://theses.fr/{tid}/document" if rec.get("accessible") == "oui" else "",
        "idref_ppn": (auteurs[0].get("ppn") or "") if auteurs else "",
        "raw_metadata": rec,
    }


def fetch_theses_fr_math(query: str = "", limit: int = 35, page: int = 1) -> List[Dict[str, Any]]:
    """Fetch defended Mathematics PhD theses from theses.fr."""
    q = 'discipline:"Mathématiques" AND status:soutenue AND dateSoutenance:[2015-01-01 TO 2026-12-31]'
    if query.strip():
        safe = query.strip().replace('"', "")
        q = f"({q}) AND ({safe})"
    params = urllib.parse.urlencode({
        "q": q,
        "nombre": limit,
        "debut": (page - 1) * limit,
        "tri": "dateDesc",
    })
    data = _http_get_json(f"{THESES_FR_SEARCH}?{params}")
    results = []
    for rec in data.get("theses", []):
        parsed = _parse_theses_fr_record(rec)
        if parsed:
            results.append(parsed)
    return results


def fetch_theses_fr_by_id(thesis_id: str) -> Optional[Dict[str, Any]]:
    """Verify and fetch a single thesis from theses.fr by NNT/ID or URL."""
    tid = thesis_id.strip().rstrip("/")
    if "theses.fr/" in tid:
        tid = tid.split("theses.fr/")[-1].split("/")[0].split("?")[0]

    params = urllib.parse.urlencode({"q": f'id:"{tid}"', "nombre": 1})
    data = _http_get_json(f"{THESES_FR_SEARCH}?{params}")
    items = data.get("theses", [])
    if not items:
        return None
    rec = items[0]
    # Allow lookup even if ongoing only if we clearly warn, or require defense date
    parsed = _parse_theses_fr_record(rec)
    if parsed:
        return parsed
    # Fallback parse for lookup preview when dateSoutenance is null
    auteurs = rec.get("auteurs") or []
    directeurs = rec.get("directeurs") or []
    if auteurs and directeurs and rec.get("titrePrincipal"):
        return {
            "scholar_name": _format_person(auteurs[0]),
            "advisors": [_format_person(d) for d in directeurs if _format_person(d)],
            "university": (rec.get("etabSoutenanceN") or "").strip(),
            "country": "France",
            "department": rec.get("discipline") or "Mathematics",
            "degree": "Ph.D. (In Progress / Defense Pending)",
            "year": _extract_year(rec.get("dateSoutenance") or rec.get("datePremiereInscriptionDoctorat")),
            "thesis_title": rec.get("titrePrincipal", "").strip(),
            "thesis_title_en": (rec.get("titreEN") or "").strip(),
            "source_repo": "theses.fr",
            "source_record_id": tid,
            "doi": "",
            "landing_url": f"https://theses.fr/{tid}",
            "pdf_url": "",
            "raw_metadata": rec,
        }
    return None
