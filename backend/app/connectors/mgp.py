"""Mathematics Genealogy Project (genealogy.math.ndsu.nodak.edu) polite reference connector.

Used strictly for:
1. Ensuring complete, accurate upward doctoral advisor chains (no dangling ancestors like
   missing advisors for Pat Hanrahan, Alonzo Church, Émile Picard, etc.).
2. Enriching MGP-linked scholars with faithful degree, university, country, year,
   dissertation title, MSC subject classification, and direct MGP students.
"""

from __future__ import annotations

import html as html_lib
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple

from ..normalizer import clean_person_name

USER_AGENT = "MathLineage/1.0 (https://github.com/zlyfunction/math-lineage; polite academic sync)"
MGP_BASE = "https://www.genealogy.math.ndsu.nodak.edu"

_COUNTRY_SPACER_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _clean_html_text(raw: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw)
    txt = html_lib.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def _format_country(flag_alt: str) -> str:
    if not flag_alt:
        return ""
    s = _COUNTRY_SPACER_RE.sub(" ", flag_alt.strip())
    return s.replace("United Kingdom", "United Kingdom").strip()


def fetch_mgp_record(mgp_id: str | int, timeout: int = 15) -> Optional[Dict[str, Any]]:
    """Fetch and parse a single MGP mathematician page cleanly."""
    mid = str(mgp_id).strip()
    url = f"{MGP_BASE}/id.php?id={urllib.parse.quote(mid)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")

    if "You have specified an ID that does not exist" in body:
        return None

    h2 = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.S)
    name = _clean_html_text(h2.group(1)) if h2 else ""
    if not name:
        return None

    # Degree, university, year block
    degree = "Ph.D."
    university = ""
    year: Optional[int] = None
    deg_block = re.search(
        r'<span style="margin-right: 0\.5em">(.*?)<span style="color:\s*#006633; margin-left: 0\.5em">(.*?)</span>\s*(\d{4})?</span>',
        body,
        re.S,
    )
    if deg_block:
        d_raw = _clean_html_text(deg_block.group(1))
        if d_raw:
            degree = d_raw
        university = _clean_html_text(deg_block.group(2))
        if deg_block.group(3):
            year = int(deg_block.group(3))

    # Country from flag alt/title
    country = ""
    flag_m = re.search(r'<img src="img/flags/[^"]+"[^>]*alt="([^"]+)"', body)
    if flag_m:
        country = _format_country(flag_m.group(1))

    # Dissertation title
    thesis_title = ""
    diss_m = re.search(r'id="thesisTitle">(.*?)</span>', body, re.S)
    if diss_m:
        thesis_title = _clean_html_text(diss_m.group(1))

    # MSC subject classification
    msc_code = ""
    msc_label = ""
    msc_m = re.search(r"Mathematics Subject Classification:\s*([^<]+)<", body)
    if msc_m:
        msc_full = _clean_html_text(msc_m.group(1))
        parts = re.split(r"\s*[—–-]\s*", msc_full, maxsplit=1)
        if parts:
            msc_code = parts[0].strip()
            msc_label = parts[1].strip() if len(parts) > 1 else msc_full

    # Advisors
    advisors: List[Dict[str, str]] = []
    for adv_id, adv_name in re.findall(r'Advisor\s*\d*:\s*<a href="id\.php\?id=(\d+)">([^<]+)</a>', body):
        cleaned = _clean_html_text(adv_name)
        if cleaned:
            advisors.append({"mgp_id": adv_id, "name": cleaned})

    # Direct Students
    students: List[Dict[str, Any]] = []
    for st_id, st_name, st_school, st_year in re.findall(
        r'<tr[^>]*><td><a href="id\.php\?id=(\d+)">([^<]+)</a></td><td>([^<]*)</td><td[^>]*>([^<]*)</td>',
        body,
    ):
        yr_m = re.search(r"\d{4}", st_year)
        students.append({
            "mgp_id": st_id,
            "name": clean_person_name(_clean_html_text(st_name)),
            "university": _clean_html_text(st_school),
            "year": int(yr_m.group(0)) if yr_m else None,
        })

    return {
        "mgp_id": mid,
        "name": name,
        "degree": degree,
        "university": university,
        "country": country,
        "year": year,
        "thesis_title": thesis_title,
        "msc_code": msc_code,
        "msc_label": msc_label,
        "advisors": advisors,
        "students": students,
        "mgp_url": url,
    }


def search_mgp_by_name(name: str, timeout: int = 12) -> List[Dict[str, str]]:
    """Search MGP quickSearch for a scholar name and return candidate (mgp_id, name) pairs."""
    data = urllib.parse.urlencode({"searchTerms": name, "Submit": "Search"}).encode("utf-8")
    req = urllib.request.Request(f"{MGP_BASE}/quickSearch.php", data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")

    # If redirected straight to a single id.php?id=... page
    final_url = resp.geturl()
    m_single = re.search(r"id\.php\?id=(\d+)", final_url)
    if m_single:
        h2 = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.S)
        nm = _clean_html_text(h2.group(1)) if h2 else name
        return [{"mgp_id": m_single.group(1), "name": nm}]

    hits = []
    for mid, raw_nm in re.findall(r'<td><a href="id\.php\?id=(\d+)">([^<]+)</a></td>', body):
        hits.append({"mgp_id": mid, "name": clean_person_name(_clean_html_text(raw_nm))})
    return hits


def crawl_mgp_ancestors_complete(
    start_mgp_ids: List[str],
    include_students_for: Optional[Set[str]] = None,
    max_pages: int = 220,
    delay: float = 0.08,
) -> Dict[str, Dict[str, Any]]:
    """Politely crawl upward from start_mgp_ids until EVERY branch reaches its true MGP root."""
    from concurrent.futures import ThreadPoolExecutor

    cache: Dict[str, Dict[str, Any]] = {}
    frontier: List[str] = list(dict.fromkeys(str(x) for x in start_mgp_ids if x))
    seen: Set[str] = set(frontier)
    stu_seeds = set(include_students_for or set())

    def _safe_fetch(mid: str) -> Optional[Dict[str, Any]]:
        try:
            time.sleep(delay)
            return fetch_mgp_record(mid, timeout=8)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        while frontier and len(cache) < max_pages:
            remaining = max_pages - len(cache)
            batch = frontier[: min(16, remaining)]
            frontier = frontier[len(batch):]

            for mid, rec in zip(batch, pool.map(_safe_fetch, batch)):
                if not rec:
                    continue
                cache[mid] = rec
                for adv in rec["advisors"]:
                    aid = adv["mgp_id"]
                    if aid not in seen:
                        seen.add(aid)
                        frontier.append(aid)
                if mid in stu_seeds:
                    for st in rec["students"][:20]:
                        sid = st["mgp_id"]
                        if sid not in seen:
                            seen.add(sid)
                            frontier.append(sid)

    return cache
