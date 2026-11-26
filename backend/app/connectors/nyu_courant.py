"""NYU Courant Institute of Mathematical Sciences (CS Dept) Ph.D. Theses connector
& official dissertation PDF title-page metadata extractor.

Official archive: https://cs.nyu.edu/dynamic/reports/?type=PhD&year=<YYYY>
Extracts Title, Candidate, Year, Advisor(s), and official PDF URL.
When the HTML listing omits Advisor(s), downloads the official university PDF and
extracts the advisor line(s) directly from Page 1 (title/signature page) via pypdf.
"""

from __future__ import annotations

import html as html_lib
import os
import re
import tempfile
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from pypdf import PdfReader

from ..normalizer import clean_person_name

USER_AGENT = "MathLineage/1.0 (Open Verifiable Mathematics Genealogy)"
NYU_REPORTS_BASE = "https://cs.nyu.edu/dynamic/reports/"
NYU_HOST = "https://cs.nyu.edu"


def _fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_dissertation_pdf_url(pdf_url: str, max_pages: int = 4) -> Dict[str, Any]:
    """Download an official dissertation PDF and extract title-page provenance via pypdf."""
    req = urllib.request.Request(pdf_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=35) as resp:
        data = resp.read()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(data)
        tmp_path = f.name

    try:
        reader = PdfReader(tmp_path)
        pages_text = []
        for i in range(min(max_pages, len(reader.pages))):
            txt = (reader.pages[i].extract_text() or "").strip()
            if txt:
                pages_text.append(txt)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    page1 = pages_text[0] if pages_text else ""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in page1.splitlines() if ln.strip()]

    # Extract advisor lines from Page 1 (e.g., "Professor Denis Zorin", "Advisor: ...", "Supervised by ...")
    advisors: List[str] = []
    for ln in lines:
        m_prof = re.match(r"^(?:Professor|Prof\.?|Dr\.?)\s+([A-Z][A-Za-zÀ-ÿ\.\-\s]{3,50})$", ln)
        if m_prof:
            cand = clean_person_name(m_prof.group(1))
            if cand and len(cand.split()) >= 2:
                advisors.append(cand)
            continue
        m_adv = re.search(
            r"(?:Thesis\s+Advisor|Dissertation\s+Advisor|Advisor(?:s)?|Supervisor(?:s)?|Directed\s+by|Advised\s+by)\s*[:\-]\s*(.+)$",
            ln,
            re.I,
        )
        if m_adv:
            raw_part = m_adv.group(1)
            for piece in re.split(r"\s*,\s*|\s+and\s+|\s*;\s*", raw_part):
                cand = clean_person_name(piece)
                if cand and len(cand.split()) >= 2:
                    advisors.append(cand)

    # Extract year
    m_yr = re.search(r"\b(19\d{2}|20\d{2})\b", page1)
    year = int(m_yr.group(1)) if m_yr else None

    # Extract author ("by\nAuthor Name" or "by Author Name")
    author = ""
    for idx, ln in enumerate(lines):
        if ln.lower() == "by" and idx + 1 < len(lines):
            author = clean_person_name(lines[idx + 1])
            break
        m_by = re.match(r"^by\s+([A-Z][A-Za-zÀ-ÿ\.\-\s]{2,60})$", ln, re.I)
        if m_by:
            author = clean_person_name(m_by.group(1))
            break

    # Extract title (lines before "by")
    title = ""
    for idx, ln in enumerate(lines):
        if ln.lower() == "by" or re.match(r"^by\s+", ln, re.I):
            title = " ".join(lines[:idx]).strip()
            break
    if not title and lines:
        title = lines[0]

    # Extract university heuristic
    university = ""
    for ln in lines:
        if re.search(r"(University|Institute|College|École|ETH|MIT)", ln, re.I) and not re.search(r"dissertation|fulfillment|degree", ln, re.I):
            university = ln
            break

    advisors = [a for a in dict.fromkeys(advisors) if a.lower() != author.lower()]

    return {
        "scholar_name": author,
        "advisors": advisors,
        "university": university,
        "year": year,
        "thesis_title": title,
        "page1_excerpt": page1[:1500],
        "page_count": len(pages_text),
    }


def _strip_tags(s: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", s)
    txt = html_lib.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def fetch_nyu_courant_phds(
    query: str = "",
    limit: int = 35,
    years: Optional[List[int]] = None,
    parse_pdf_when_missing_advisor: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch verified NYU Courant Ph.D. dissertations from cs.nyu.edu/dynamic/reports/."""
    target_years = years or [2026, 2025, 2024, 2023]
    q_low = query.strip().lower()
    results: List[Dict[str, Any]] = []

    for yr in target_years:
        if len(results) >= limit:
            break
        page_url = f"{NYU_REPORTS_BASE}?type=PhD&year={yr}"
        try:
            page_html = _fetch_text(page_url)
        except Exception:
            continue

        row_blocks = re.findall(r'<li class="row">(.*?)</li>', page_html, re.S)
        for block in row_blocks:
            if len(results) >= limit:
                break
            if "Ph.D. Thesis" not in block:
                continue

            # Extract columns
            title_m = re.search(r'class="col-xs-12 col-sm-4 col-sm-push-1">(.*?)</span>', block, re.S)
            cand_m = re.search(r'class="col-xs-12 col-sm-3 col-sm-push-1">(.*?)</span>', block, re.S)
            year_m = re.search(r'class="col-xs-2 col-sm-1 col-sm-push-9">(.*?)</span>', block, re.S)
            pdf_m = re.search(r'<a href="(/media/publications/[^"]+\.pdf)"', block, re.I)

            title = _strip_tags(title_m.group(1)) if title_m else ""
            cand_raw = _strip_tags(cand_m.group(1)) if cand_m else ""
            year_val = int(re.search(r"\d{4}", _strip_tags(year_m.group(1))).group(0)) if (year_m and re.search(r"\d{4}", _strip_tags(year_m.group(1)))) else yr
            pdf_url = f"{NYU_HOST}{pdf_m.group(1)}" if pdf_m else ""

            scholar_name = clean_person_name(cand_raw)
            if not scholar_name or not title:
                continue

            # Extract Advisor(s) from HTML abstract collapse block
            advisors: List[str] = []
            adv_m = re.search(r"<strong>Advisor\(s\):</strong>(.*?)</p>", block, re.S | re.I)
            if adv_m:
                adv_text = _strip_tags(adv_m.group(1))
                for part in re.split(r"\s*,\s*|\s+and\s+|\s*;\s*", adv_text):
                    cleaned = clean_person_name(part)
                    if cleaned and len(cleaned.split()) >= 2 and cleaned.lower() != scholar_name.lower():
                        advisors.append(cleaned)

            # Query filter BEFORE any PDF download to stay fast
            if q_low:
                haystack = f"{scholar_name} {title} {' '.join(advisors)} {year_val}".lower()
                if q_low not in haystack:
                    continue

            page1_excerpt = ""
            verification_method = "NYU Courant Official HTML Registry"
            # If HTML omitted Advisor(s) (common for newly posted theses) and official PDF is present, parse Page 1!
            if not advisors and pdf_url and parse_pdf_when_missing_advisor:
                try:
                    pdf_info = parse_dissertation_pdf_url(pdf_url, max_pages=2)
                    advisors = pdf_info.get("advisors") or []
                    page1_excerpt = pdf_info.get("page1_excerpt") or ""
                    verification_method = "NYU Courant Official Registry + Title Page PDF Verification"
                except Exception:
                    continue

            advisors = list(dict.fromkeys(advisors))
            if not advisors:
                continue

            # Stable record ID
            slug = re.sub(r"[^a-z0-9]+", "-", f"{year_val}-{scholar_name.lower()}").strip("-")
            record_id = pdf_m.group(1).split("/")[-1] if pdf_m else slug

            results.append({
                "scholar_name": scholar_name,
                "advisors": advisors,
                "university": "New York University",
                "country": "United States",
                "department": "Courant Institute of Mathematical Sciences (Computer Science)",
                "degree": "Ph.D.",
                "year": year_val,
                "thesis_title": title,
                "thesis_title_en": "",
                "source_repo": "NYU Courant",
                "source_record_id": record_id,
                "doi": "",
                "landing_url": pdf_url or page_url,
                "pdf_url": pdf_url,
                "raw_metadata": {
                    "registry_url": page_url,
                    "pdf_url": pdf_url,
                    "candidate_raw": cand_raw,
                    "advisors_extracted": advisors,
                    "verification_method": verification_method,
                    "pdf_title_page_excerpt": page1_excerpt,
                },
            })

    return results
