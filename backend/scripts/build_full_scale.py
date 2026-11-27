"""Build ultra-scale v4 (~465,000+ scholars, ~500,000+ edges, ~60,000+ verified dissertations,
~85,000+ total thesis titles) compact gzipped columnar bundles for MathLineage.

Gap-closing sources:
1. University of Freiburg QLever Wikidata SPARQL mirror (CC0):
   - ALL ~262,000 MGP scholars (wdt:P549) + ALL ~404,000 global academics (P549 U P184 U P185)
   - University affiliations (P69) + exact graduation years (pq:P582 & p:P512/pq:P585)
   - ALL ~26,300 historical doctoral thesis titles (P1026)
   - Verified MGP historical hub fixes (including Leonhard Euler -> Joseph-Louis Lagrange!)
2. Seven authoritative open doctoral dissertation repositories (parallel bulk harvest):
   - HAL / TEL: ALL ~35,300 Math, Applied Math, Statistics, Math-Physics & CS PhD theses + PDFs
   - UC eScholarship (ALL 9 UC Campuses: UCLA, UC Berkeley, UCSD, UCSB, UCD, UCI, UCSC, UCR, UCM):
     Math/CS/Stats/Physics PhDs + any PhD whose advisor is in the 400K academic graph (~15,000+ US PhDs + PDFs!)
   - DataCite: 16,000+ Math/CS/Stats/Physics dissertations with official Supervisor metadata
     (Oxford ORA, Cambridge Apollo, ETH Zurich, EPFL, Caltech, LMU Munich, TU Delft, Imperial, UCL, etc.)
   - theses.fr: Defended 2018-2026 French Math, Applied Math, Statistics & CS PhDs (fast non-wildcard queries)
   - MIT DSpace: Department of Mathematics Ph.D. theses + Handles (~600 theses)
   - Cornell eCommons: Math & CS Ph.D. dissertations with dc.contributor.chair/advisor
   - NYU Courant: 2016-2026 CS Ph.D. archive + PDF Page-1 title-page advisor verification (incl. Leyi Zhu 2026)
"""

from __future__ import annotations

import concurrent.futures
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.mit_dspace import fetch_mit_math_theses
from app.connectors.nyu_courant import fetch_nyu_courant_phds
from app.normalizer import clean_person_name, normalize_key

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
CACHE_DIR = PROJECT_ROOT / "data" / "qlever_cache"
QLEVER_API = "https://qlever.cs.uni-freiburg.de/api/wikidata"
HAL_API = "https://api.archives-ouvertes.fr/search/"
THESES_FR_API = "https://theses.fr/api/v1/theses/recherche/"
DATACITE_API = "https://api.datacite.org/dois"
UC_ESCHOLARSHIP_GQL = "https://escholarship.org/graphql"
CORNELL_DSPACE_API = "https://ecommons.cornell.edu/server/api/discover/search/objects"
USER_AGENT = "MathLineage/4.0 (https://github.com/zlyfunction/math-lineage; open academic genealogy)"

REPO_LIST = [
    "MGP",
    "HAL/TEL",
    "theses.fr",
    "DataCite",
    "MIT DSpace",
    "NYU Courant",
    "UC eScholarship",
    "Cornell eCommons",
]
REPO_TO_ID = {name: i for i, name in enumerate(REPO_LIST)}

UC_CAMPUSES = [
    ("ucla_etd", "University of California, Los Angeles", 16000),
    ("ucb_etd", "University of California, Berkeley", 15000),
    ("ucsd_etd", "University of California, San Diego", 15000),
    ("uci_etd", "University of California, Irvine", 8000),
    ("ucr_etd", "University of California, Riverside", 6500),
    ("ucsb_etd", "University of California, Santa Barbara", 5000),
    ("ucd_etd", "University of California, Davis", 4500),
    ("ucsc_etd", "University of California, Santa Cruz", 4000),
    ("ucm_etd", "University of California, Merced", 2000),
]

_UC_STEM_RE = re.compile(
    r"\b(math|applied math|computer science|computing|statistics|biostatistics|probability|"
    r"physics|theoretical physics|astrophysics|operations research|data science|machine learning|"
    r"artificial intelligence|cryptography|combinatorics|geometry|topology|algebra|numerical|"
    r"electrical engineering|computer engineering|logic)\b",
    re.I,
)

_SKIP_SCHOOL_RE = re.compile(
    r"\b(high school|secondary school|gymnasium|middle school|elementary school|grammar school|preparatory|lycée|lyceum)\b",
    re.I,
)


def _http_get_text(
    url: str,
    headers: Dict[str, str],
    *,
    data: Optional[bytes] = None,
    timeout: int = 90,
    retries: int = 5,
) -> str:
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_err = exc
            if attempt < retries - 1:
                if exc.code == 429:
                    wait_s = 12.0 * (attempt + 1)
                elif exc.code >= 500:
                    wait_s = 4.0 * (2**attempt)
                else:
                    raise
                print(f"      [retry {attempt+1}/{retries-1}] HTTP {exc.code}; sleeping {wait_s:.0f}s...", flush=True)
                time.sleep(wait_s)
        except Exception as exc:
            last_err = exc
            if attempt < retries - 1:
                wait_s = 3.0 * (2**attempt)
                print(f"      [retry {attempt+1}/{retries-1}] {exc}; sleeping {wait_s:.0f}s...", flush=True)
                time.sleep(wait_s)
    raise RuntimeError(f"HTTP request failed after {retries} attempts: {last_err}") from last_err


def _qlever_tsv(cache_key: str, query: str, timeout: int = 120) -> List[List[str]]:
    use_cache = os.environ.get("MATHLINEAGE_USE_CACHE", "0") == "1"
    cache_path = CACHE_DIR / f"{cache_key}.tsv.gz"
    if use_cache and cache_path.exists():
        raw = gzip.open(cache_path, "rt", encoding="utf-8", errors="replace").read()
        print(f"      (loaded {cache_key} from local cache)", flush=True)
    else:
        url = f"{QLEVER_API}?query={urllib.parse.quote(query)}"
        raw = _http_get_text(
            url,
            {"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"},
            timeout=timeout,
            retries=5,
        )
        if use_cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with gzip.open(cache_path, "wt", encoding="utf-8", compresslevel=5) as fh:
                fh.write(raw)
        time.sleep(3.5)

    rows: List[List[str]] = []
    for line in raw.splitlines()[1:]:
        if line:
            rows.append(line.split("\t"))
    return rows


def _unquote_sparql(val: str) -> str:
    if not val:
        return ""
    s = val.strip()
    if s.startswith("<") and s.endswith(">"):
        return s[1:-1].rsplit("/", 1)[-1]
    if '"@' in s:
        s = s.rsplit('"@', 1)[0] + '"'
    elif '"^^' in s:
        s = s.rsplit('"^^', 1)[0] + '"'
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s.replace('\\"', '"').replace("\\\\", "\\").strip()


def _parse_mgp_description(desc: str) -> Tuple[str, Optional[int], str]:
    if not desc:
        return "", None, ""
    m1 = re.search(
        r'(?:Ph\.?D\.?|Doctorat|Dr\.?\s*rer\.?\s*nat\.?|Sc\.?D\.?)\s+from\s+([^,]+?)\s+in\s+(1[5-9]\d{2}|20\d{2})(?:\s+on\s+"([^"]+)")?',
        desc,
        re.I,
    )
    if m1:
        return m1.group(1).strip(" .,;"), int(m1.group(2)), (m1.group(3) or "").strip()

    m2 = re.search(
        r'(?:Ph\.?D\.?|Doctorat|Dr\.?\s*rer\.?\s*nat\.?|Dr\.?\s*phil\.?|D\.?\s*Phil\.?|Sc\.?D\.?|Candidate of Sciences)\s+([A-ZÀ-Ÿ][^,;\d]{2,90}?)\s+(1[5-9]\d{2}|20\d{2})\b',
        desc,
        re.I,
    )
    if m2:
        return m2.group(1).strip(" .,;-"), int(m2.group(2)), ""

    m3 = re.search(
        r'(?:Ph\.?D\.?|Doctorat|Dr\.?)\s+(1[5-9]\d{2}|20\d{2})\s+([A-ZÀ-Ÿ][^,;\d]{2,90})',
        desc,
        re.I,
    )
    if m3:
        return m3.group(2).strip(" .,;-"), int(m3.group(1)), ""

    return "", None, ""


def _harvest_hal_bulk(max_docs: int = 40000) -> List[Dict[str, Any]]:
    """Harvest ALL Math, Applied Math, Statistics, Math-Physics & CS PhD theses with advisors from HAL/TEL via cursorMark."""
    fq = "docType_s:THESE AND (domain_s:0.math OR domain_s:0.info OR domain_s:0.stat OR domain_s:0.phys.mphy) AND director_s:*"
    fl = "halId_s,title_s,en_title_s,authFullName_s,director_s,authorityInstitution_s,defenseDateY_i,uri_s,fileMain_s"
    cursor = "*"
    batch_size = 2500
    results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    while len(results) < max_docs:
        params = urllib.parse.urlencode({
            "q": "*:*",
            "fq": fq,
            "fl": fl,
            "rows": str(batch_size),
            "sort": "docid asc",
            "cursorMark": cursor,
            "wt": "json",
        })
        raw = _http_get_text(f"{HAL_API}?{params}", {"User-Agent": USER_AGENT}, timeout=45, retries=4)
        payload = json.loads(raw)
        docs = payload.get("response", {}).get("docs", [])
        if not docs:
            break
        for doc in docs:
            hal_id = (doc.get("halId_s") or "").strip()
            if not hal_id or hal_id in seen_ids:
                continue
            authors = doc.get("authFullName_s") or []
            directors = doc.get("director_s") or []
            titles = doc.get("en_title_s") or doc.get("title_s") or []
            if not authors or not directors or not titles:
                continue
            scholar = clean_person_name(authors[0])
            advisors = [clean_person_name(d) for d in directors if clean_person_name(d)]
            title = str(titles[0]).strip()
            if not scholar or not advisors or not title:
                continue
            seen_ids.add(hal_id)
            insts = doc.get("authorityInstitution_s") or []
            univ = str(insts[0]).strip() if insts else ""
            yr = doc.get("defenseDateY_i")
            year = int(yr) if isinstance(yr, int) and 1900 <= yr <= 2027 else 0
            uri = (doc.get("uri_s") or f"https://theses.hal.science/{hal_id}").strip()
            pdf = (doc.get("fileMain_s") or "").strip()
            results.append({
                "scholar_name": scholar,
                "university": univ,
                "year": year,
                "thesis_title": title,
                "advisors": advisors,
                "source_repo": "HAL/TEL",
                "source_record_id": hal_id,
                "landing_url": uri,
                "pdf_url": pdf,
                "doi": "",
            })
        next_cursor = payload.get("nextCursorMark")
        if not next_cursor or next_cursor == cursor or len(docs) < batch_size:
            break
        cursor = next_cursor
    return results


def _harvest_theses_fr_fast() -> List[Dict[str, Any]]:
    """Harvest defended French Math, Applied Math, Statistics & CS PhDs using fast non-wildcard queries."""
    queries = [
        ('status:soutenue AND dateSoutenance:[2016-01-01 TO 2026-12-31] AND discipline:"Mathématiques"', 2500),
        ('status:soutenue AND dateSoutenance:[2016-01-01 TO 2026-12-31] AND discipline:"Mathématiques appliquées"', 2000),
        ('status:soutenue AND dateSoutenance:[2018-01-01 TO 2026-12-31] AND discipline:"Informatique"', 4500),
        ('status:soutenue AND dateSoutenance:[2016-01-01 TO 2026-12-31] AND discipline:"Statistiques"', 1000),
        ('status:soutenue AND dateSoutenance:[2018-01-01 TO 2026-12-31] AND discipline:"Mathématiques et applications"', 1500),
    ]
    results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    batch = 100

    for q, cap in queries:
        debut = 0
        while debut < cap:
            params = urllib.parse.urlencode({"q": q, "nombre": str(batch), "debut": str(debut)})
            try:
                raw = _http_get_text(f"{THESES_FR_API}?{params}", {"User-Agent": USER_AGENT}, timeout=20, retries=2)
                payload = json.loads(raw)
            except Exception as exc:
                print(f"      theses.fr query stopped at offset {debut}: {exc}", flush=True)
                break
            theses = payload.get("theses") or []
            if not theses:
                break
            for item in theses:
                tid = str(item.get("id") or "").strip()
                if not tid or tid in seen_ids:
                    continue
                auteurs = item.get("auteurs") or []
                directeurs = item.get("directeurs") or []
                title = (item.get("titrePrincipal") or "").strip()
                if not auteurs or not directeurs or not title:
                    continue
                a0 = auteurs[0]
                scholar = clean_person_name(f"{a0.get('prenom', '')} {a0.get('nom', '')}".strip())
                advisors = []
                for d in directeurs:
                    dn = clean_person_name(f"{d.get('prenom', '')} {d.get('nom', '')}".strip())
                    if dn and dn not in advisors:
                        advisors.append(dn)
                if not scholar or not advisors:
                    continue
                seen_ids.add(tid)
                univ = (item.get("etabSoutenanceN") or "").strip()
                ds = str(item.get("dateSoutenance") or "")
                year = 0
                m = re.search(r"(19|20)\d{2}", ds)
                if m:
                    year = int(m.group(0))
                results.append({
                    "scholar_name": scholar,
                    "university": univ,
                    "year": year,
                    "thesis_title": title,
                    "advisors": advisors,
                    "source_repo": "theses.fr",
                    "source_record_id": tid,
                    "landing_url": f"https://theses.fr/{tid}",
                    "pdf_url": "",
                    "doi": "",
                })
            if len(theses) < batch:
                break
            debut += batch
    return results


def _harvest_datacite_bulk(max_pages: int = 32, page_size: int = 500) -> List[Dict[str, Any]]:
    """Harvest up to 16,000 Math/CS/Stats/Physics doctoral dissertations with official Supervisor metadata via DataCite."""
    q_dc = (
        'types.resourceTypeGeneral:Dissertation AND contributors.contributorType:Supervisor AND '
        '(mathematics OR mathematical OR algebra OR geometry OR topology OR "computer science" '
        'OR algorithm OR "partial differential" OR probability OR statistics OR stochastic '
        'OR optimization OR "machine learning" OR cryptography OR combinatorics '
        'OR physics OR quantum OR "numerical analysis" OR "graph theory")'
    )
    next_url: Optional[str] = (
        f"{DATACITE_API}?query={urllib.parse.quote(q_dc)}&page[cursor]=1&page[size]={page_size}"
    )
    results: List[Dict[str, Any]] = []
    seen_dois: Set[str] = set()

    for page_idx in range(max_pages):
        if not next_url:
            break
        try:
            raw = _http_get_text(next_url, {"User-Agent": USER_AGENT}, timeout=45, retries=3)
            payload = json.loads(raw)
        except Exception as exc:
            print(f"      DataCite stopped at page {page_idx+1}: {exc}", flush=True)
            break
        items = payload.get("data") or []
        if not items:
            break
        for item in items:
            attrs = item.get("attributes") or {}
            doi = (attrs.get("doi") or item.get("id") or "").strip()
            if not doi or doi in seen_dois:
                continue
            creators = attrs.get("creators") or []
            contribs = attrs.get("contributors") or []
            titles = attrs.get("titles") or []
            if not creators or not contribs or not titles:
                continue
            c0 = creators[0]
            raw_author = c0.get("name") or f"{c0.get('givenName', '')} {c0.get('familyName', '')}".strip()
            scholar = clean_person_name(raw_author)
            advisors = []
            for c in contribs:
                if (c.get("contributorType") or "").lower() == "supervisor":
                    rn = c.get("name") or f"{c.get('givenName', '')} {c.get('familyName', '')}".strip()
                    cn = clean_person_name(rn)
                    if cn and cn not in advisors:
                        advisors.append(cn)
            title = (titles[0].get("title") or "").strip()
            if not scholar or not advisors or not title:
                continue
            seen_dois.add(doi)
            univ = (attrs.get("publisher") or "").strip()
            if isinstance(univ, dict):
                univ = (univ.get("name") or "").strip()
            yr = attrs.get("publicationYear")
            year = int(yr) if isinstance(yr, int) and 1900 <= yr <= 2027 else 0
            url = (attrs.get("url") or f"https://doi.org/{doi}").strip()
            results.append({
                "scholar_name": scholar,
                "university": univ,
                "year": year,
                "thesis_title": title,
                "advisors": advisors,
                "source_repo": "DataCite",
                "source_record_id": doi,
                "landing_url": url,
                "pdf_url": "",
                "doi": doi,
            })
        next_url = (payload.get("links") or {}).get("next")
    return results


def _harvest_one_uc_campus(
    unit_id: str,
    univ_name: str,
    max_scan: int,
    known_advisor_keys: Set[str],
) -> List[Dict[str, Any]]:
    """Scan one UC campus ETD unit on eScholarship GraphQL; keep Math/CS/Stats/Physics ETDs
    plus ANY ETD whose official ADVISOR matches our 400K academic genealogy graph!"""
    results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    more: Optional[str] = None
    scanned = 0
    batch = 500

    while scanned < max_scan:
        after_arg = f', more: "{more}"' if more else ""
        q = (
            f'{{ unit(id: "{unit_id}") {{ items(first: {batch}{after_arg}) {{ '
            'more nodes { id title published subjects '
            'authors { nodes { name } } '
            'contributors { nodes { name role } } '
            'permalink contentLink } } } }'
        )
        try:
            raw = _http_get_text(
                UC_ESCHOLARSHIP_GQL,
                {"User-Agent": USER_AGENT, "Content-Type": "application/json"},
                data=json.dumps({"query": q}).encode("utf-8"),
                timeout=35,
                retries=3,
            )
            payload = json.loads(raw)
        except Exception as exc:
            print(f"      UC {unit_id} stopped at {scanned}: {exc}", flush=True)
            break

        items_obj = (payload.get("data") or {}).get("unit") or {}
        items_obj = items_obj.get("items") or {}
        nodes = items_obj.get("nodes") or []
        if not nodes:
            break
        scanned += len(nodes)

        for n in nodes:
            raw_id = (n.get("id") or "").strip()
            short_id = raw_id.rsplit("/qt", 1)[-1] if "/qt" in raw_id else raw_id
            if not short_id or short_id in seen_ids:
                continue
            authors = (n.get("authors") or {}).get("nodes") or []
            contribs = (n.get("contributors") or {}).get("nodes") or []
            title = (n.get("title") or "").strip()
            if not authors or not contribs or not title:
                continue
            advisors = []
            for c in contribs:
                if (c.get("role") or "").upper() == "ADVISOR":
                    cn = clean_person_name(c.get("name") or "")
                    if cn and cn not in advisors:
                        advisors.append(cn)
            if not advisors:
                continue

            subjs_str = " ".join(n.get("subjects") or [])
            is_stem = bool(_UC_STEM_RE.search(subjs_str))
            advisor_in_graph = any(normalize_key(a) in known_advisor_keys for a in advisors)
            if not is_stem and not advisor_in_graph:
                continue

            scholar = clean_person_name(authors[0].get("name") or "")
            if not scholar:
                continue
            seen_ids.add(short_id)

            pub = str(n.get("published") or "")
            year = int(pub[:4]) if len(pub) >= 4 and pub[:4].isdigit() else 0
            permalink = (n.get("permalink") or f"https://escholarship.org/uc/item/{short_id}").strip()
            pdf = (n.get("contentLink") or "").strip()
            results.append({
                "scholar_name": scholar,
                "university": univ_name,
                "year": year,
                "thesis_title": title,
                "advisors": advisors,
                "source_repo": "UC eScholarship",
                "source_record_id": short_id,
                "landing_url": permalink,
                "pdf_url": pdf,
                "doi": "",
            })

        more = items_obj.get("more")
        if not more or len(nodes) < batch:
            break

    return results


def _harvest_uc_all(known_advisor_keys: Set[str]) -> List[Dict[str, Any]]:
    all_uc: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = {
            pool.submit(_harvest_one_uc_campus, uid, uname, cap, known_advisor_keys): uid
            for uid, uname, cap in UC_CAMPUSES
        }
        for fut in concurrent.futures.as_completed(futs):
            uid = futs[fut]
            try:
                recs = fut.result()
                all_uc.extend(recs)
                print(f"        - UC {uid}: {len(recs):,} Math/CS/graph-linked PhDs", flush=True)
            except Exception as exc:
                print(f"        - UC {uid}: WARN {exc}", flush=True)
    return all_uc


def _harvest_cornell_ecommons(max_pages: int = 12, page_size: int = 50) -> List[Dict[str, Any]]:
    """Harvest Cornell University Math/CS/Stats Ph.D. dissertations from eCommons DSpace 7 REST API."""
    results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    queries = [
        "dissertation mathematics",
        "dissertation computer science",
        "dissertation statistics OR applied mathematics",
    ]
    per_q_pages = max(1, max_pages // len(queries))
    for q in queries:
        for pg in range(per_q_pages):
            params = urllib.parse.urlencode({"query": q, "size": str(page_size), "page": str(pg)})
            try:
                raw = _http_get_text(f"{CORNELL_DSPACE_API}?{params}", {"User-Agent": USER_AGENT}, timeout=25, retries=2)
                payload = json.loads(raw)
            except Exception:
                break
            objs = (
                payload.get("_embedded", {})
                .get("searchResult", {})
                .get("_embedded", {})
                .get("objects", [])
            )
            if not objs:
                break
            for o in objs:
                item = (o.get("_embedded") or {}).get("indexableObject") or {}
                md = item.get("metadata") or {}
                types = [x.get("value", "").lower() for x in md.get("dc.type", [])]
                if not any("dissertation" in t or "thesis" in t for t in types):
                    continue
                handle = (item.get("handle") or item.get("uuid") or "").strip()
                if not handle or handle in seen_ids:
                    continue
                authors = [x.get("value", "") for x in md.get("dc.contributor.author", [])]
                chairs = [x.get("value", "") for x in md.get("dc.contributor.chair", [])]
                adv_raw = chairs or [x.get("value", "") for x in md.get("dc.contributor.advisor", [])]
                titles = [x.get("value", "") for x in md.get("dc.title", [])]
                if not authors or not adv_raw or not titles:
                    continue
                scholar = clean_person_name(authors[0])
                advisors = [clean_person_name(a) for a in adv_raw if clean_person_name(a)]
                title = titles[0].strip()
                if not scholar or not advisors or not title:
                    continue
                seen_ids.add(handle)
                dates = [x.get("value", "") for x in md.get("dc.date.issued", [])]
                year = 0
                if dates:
                    m = re.search(r"(19|20)\d{2}", dates[0])
                    if m:
                        year = int(m.group(0))
                landing = f"https://hdl.handle.net/{handle}" if "/" in handle else f"https://ecommons.cornell.edu/items/{handle}"
                results.append({
                    "scholar_name": scholar,
                    "university": "Cornell University",
                    "year": year,
                    "thesis_title": title,
                    "advisors": advisors,
                    "source_repo": "Cornell eCommons",
                    "source_record_id": handle,
                    "landing_url": landing,
                    "pdf_url": "",
                    "doi": "",
                })
    return results


def _pack_thesis_tuple(
    title: str,
    repo: str,
    rid: str,
    url: str,
    pdf: str,
    doi: str,
    verified: bool,
) -> List[Any]:
    """Encode thesis metadata into ultra-compact v3/v4 7-tuple:
    [title, repoIdx, recordId, customUrl, customPdf, doi, flags]
    """
    r_idx = REPO_TO_ID.get(repo, 0)
    custom_url = url
    custom_pdf = pdf
    if repo == "HAL/TEL" and rid:
        if url in (f"https://theses.hal.science/{rid}", f"https://theses.hal.science/{rid}v1", f"https://hal.science/{rid}"):
            custom_url = ""
        if pdf == f"https://theses.hal.science/{rid}/document":
            custom_pdf = "1"
    elif repo == "UC eScholarship" and rid:
        if url == f"https://escholarship.org/uc/item/{rid}":
            custom_url = ""
        if pdf == f"https://escholarship.org/content/qt{rid}/qt{rid}.pdf":
            custom_pdf = "1"
    elif repo == "theses.fr" and rid and url == f"https://theses.fr/{rid}":
        custom_url = ""
    elif repo == "DataCite" and rid and url == f"https://doi.org/{rid}":
        custom_url = ""
    elif repo == "Cornell eCommons" and rid and url == f"https://hdl.handle.net/{rid}":
        custom_url = ""
    elif repo == "MGP" and rid and url == f"https://www.genealogy.math.ndsu.nodak.edu/id.php?id={rid}":
        custom_url = ""
    flags = 1 if verified else 0
    return [title, r_idx, rid, custom_url, custom_pdf, doi, flags]


def main() -> None:
    t_start = time.time()
    print("=== MathLineage Ultra-Scale v4 Builder (465K+ Scholars, 60K+ Verified Theses) ===", flush=True)

    # ------------------------------------------------------------------
    # 1. Fetch ALL MGP scholars (P549) from QLever
    # ------------------------------------------------------------------
    t0 = time.time()
    print("[1/6] Querying QLever for all Wikidata P549 (MGP) scholars...", flush=True)
    q_scholars = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
SELECT ?p ?mgp ?name ?desc WHERE {
  ?p wdt:P549 ?mgp .
  ?p rdfs:label ?name . FILTER(LANG(?name) = "en")
  OPTIONAL { ?p schema:description ?desc . FILTER(LANG(?desc) = "en") }
}"""
    scholar_rows = _qlever_tsv("p549_scholars", q_scholars)
    print(f"      Fetched {len(scholar_rows):,} P549 rows in {time.time()-t0:.1f}s", flush=True)

    qid_data: Dict[str, Dict[str, Any]] = {}
    for row in scholar_rows:
        if len(row) < 3:
            continue
        qid = _unquote_sparql(row[0])
        mgp = _unquote_sparql(row[1])
        name = _unquote_sparql(row[2])
        desc = _unquote_sparql(row[3]) if len(row) > 3 else ""
        if not qid or not name or qid in qid_data:
            continue
        univ, yr, thesis = _parse_mgp_description(desc)
        qid_data[qid] = {
            "qid": qid,
            "mgp": mgp,
            "name": name,
            "univ": univ,
            "year": yr or 0,
            "thesis": thesis,
            "flag": 2,
        }
    print(f"      Unique P549 scholars: {len(qid_data):,}", flush=True)

    # ------------------------------------------------------------------
    # 2. Fetch ALL global doctoral advisor/student edges (P184 U P185) + non-P549 labels
    # ------------------------------------------------------------------
    t0 = time.time()
    print("[2/6] Querying QLever for FULL global P184 U P185 doctoral graph...", flush=True)
    q_edges = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT DISTINCT ?s ?a WHERE {
  { ?s wdt:P184 ?a } UNION { ?a wdt:P185 ?s }
}"""
    raw_edges: List[Tuple[str, str]] = []
    needed_qids: Set[str] = set()
    for row in _qlever_tsv("all_p184_p185_edges", q_edges):
        if len(row) < 2:
            continue
        sq = _unquote_sparql(row[0])
        aq = _unquote_sparql(row[1])
        if sq and aq and sq != aq:
            raw_edges.append((aq, sq))
            if sq not in qid_data:
                needed_qids.add(sq)
            if aq not in qid_data:
                needed_qids.add(aq)
    print(f"      Fetched {len(raw_edges):,} global P184/P185 edges ({len(needed_qids):,} non-P549 QIDs) in {time.time()-t0:.1f}s", flush=True)

    t0 = time.time()
    q_extra_labels = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?p ?name WHERE {
  { ?p wdt:P184 ?x } UNION { ?y wdt:P184 ?p } UNION { ?p wdt:P185 ?z } UNION { ?w wdt:P185 ?p }
  FILTER NOT EXISTS { ?p wdt:P549 ?m }
  ?p rdfs:label ?name . FILTER(LANG(?name) = "en")
}"""
    try:
        added_extra = 0
        for row in _qlever_tsv("non_p549_labels", q_extra_labels):
            if len(row) < 2:
                continue
            qid = _unquote_sparql(row[0])
            name = _unquote_sparql(row[1])
            if qid in needed_qids and name and qid not in qid_data:
                qid_data[qid] = {
                    "qid": qid,
                    "mgp": "",
                    "name": name,
                    "univ": "",
                    "year": 0,
                    "thesis": "",
                    "flag": 2,
                }
                added_extra += 1
        print(f"      Added {added_extra:,} non-P549 global academics (total QLever nodes: {len(qid_data):,}) in {time.time()-t0:.1f}s", flush=True)
    except Exception as exc:
        print(f"      WARN non-P549 labels skipped: {exc}", flush=True)

    # ------------------------------------------------------------------
    # 3. Enrich universities (P69), Ph.D. degree years (P512/P585 + P69/P582), & thesis titles (P1026)
    # ------------------------------------------------------------------
    t0 = time.time()
    print("[3/6] Querying QLever for P69 universities, P512/P69 years, and P1026 thesis titles...", flush=True)
    q_univ = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?p ?univName WHERE {
  { ?p wdt:P549 ?m } UNION { ?p wdt:P184 ?a }
  ?p wdt:P69 ?u .
  ?u rdfs:label ?univName . FILTER(LANG(?univName) = "en")
}"""
    try:
        for row in _qlever_tsv("p69_univs", q_univ):
            if len(row) < 2:
                continue
            qid = _unquote_sparql(row[0])
            uname = _unquote_sparql(row[1])
            rec = qid_data.get(qid)
            if rec and not rec["univ"] and uname and not _SKIP_SCHOOL_RE.search(uname):
                rec["univ"] = uname
    except Exception as exc:
        print(f"      WARN P69 universities skipped: {exc}", flush=True)

    # Exact Ph.D. degree point-in-time (p:P512 / pq:P585) + university end year (p:P69 / pq:P582)
    q_years = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
SELECT ?p ?yr WHERE {
  { ?p wdt:P549 ?m } UNION { ?p wdt:P184 ?a }
  { ?p p:P512 ?st . ?st pq:P585 ?yr . }
  UNION
  { ?p p:P69 ?st2 . ?st2 pq:P582 ?yr . }
}"""
    try:
        max_yr: Dict[str, int] = {}
        for row in _qlever_tsv("p512_p69_years", q_years):
            if len(row) < 2:
                continue
            qid = _unquote_sparql(row[0])
            raw_yr = _unquote_sparql(row[1])
            if len(raw_yr) >= 4 and raw_yr[:4].isdigit():
                y = int(raw_yr[:4])
                if 1500 <= y <= 2026 and y > max_yr.get(qid, 0):
                    max_yr[qid] = y
        yr_added = 0
        for qid, y in max_yr.items():
            rec = qid_data.get(qid)
            if rec and not rec["year"]:
                rec["year"] = y
                yr_added += 1
        print(f"      Added {yr_added:,} graduation years from P512/P69", flush=True)
    except Exception as exc:
        print(f"      WARN P512/P69 years skipped: {exc}", flush=True)

    # Historical doctoral thesis titles (wdt:P1026 -> rdfs:label) across ALL P549 U P184 scholars (~26K!)
    q_theses = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?p ?tLabel WHERE {
  { ?p wdt:P549 ?m } UNION { ?p wdt:P184 ?a }
  ?p wdt:P1026 ?t .
  ?t rdfs:label ?tLabel . FILTER(LANG(?tLabel) IN ("en", "fr", "de", "la", "mul"))
}"""
    try:
        th_added = 0
        for row in _qlever_tsv("p1026_theses", q_theses):
            if len(row) < 2:
                continue
            qid = _unquote_sparql(row[0])
            tlabel = _unquote_sparql(row[1])
            rec = qid_data.get(qid)
            if rec and not rec["thesis"] and tlabel:
                rec["thesis"] = tlabel
                th_added += 1
        print(f"      Added {th_added:,} historical thesis titles from Wikidata P1026 in {time.time()-t0:.1f}s", flush=True)
    except Exception as exc:
        print(f"      WARN P1026 theses skipped: {exc}", flush=True)

    # ------------------------------------------------------------------
    # 4. Build dense 0-based index & verified MGP historical hub fixes
    # ------------------------------------------------------------------
    print("[4/6] Indexing global graph and applying verified MGP hub metadata...", flush=True)
    scholars: List[Dict[str, Any]] = []
    qid_to_idx: Dict[str, int] = {}
    mgp_to_idx: Dict[str, int] = {}
    norm_to_indices: Dict[str, List[int]] = {}
    first_last_mid1_to_indices: Dict[Tuple[str, str], List[int]] = {}
    edge_set: Dict[Tuple[int, int], int] = {}
    theses_map: Dict[str, List[Any]] = {}

    qid_out_deg: Dict[str, int] = {}
    for aq, sq in raw_edges:
        if aq in qid_data and sq in qid_data:
            qid_out_deg[aq] = qid_out_deg.get(aq, 0) + 1

    def add_scholar(
        name: str,
        *,
        mgp: str = "",
        univ: str = "",
        year: int = 0,
        flag: int = 2,
        thesis: str = "",
        qid: str = "",
    ) -> int:
        idx = len(scholars)
        cleaned = clean_person_name(name) or name.strip()
        scholars.append({
            "name": cleaned,
            "mgp": mgp,
            "univ": univ,
            "year": year or 0,
            "flag": flag,
        })
        if qid:
            qid_to_idx[qid] = idx
        if mgp:
            mgp_to_idx[mgp] = idx
        nk = normalize_key(cleaned)
        if nk:
            norm_to_indices.setdefault(nk, []).append(idx)
            toks = nk.split()
            if len(toks) == 3 and len(toks[1]) == 1:
                first_last_mid1_to_indices.setdefault((toks[0], toks[2]), []).append(idx)
        if thesis:
            theses_map[str(idx)] = _pack_thesis_tuple(
                thesis, "MGP", mgp or qid,
                f"https://www.genealogy.math.ndsu.nodak.edu/id.php?id={mgp}" if mgp else "",
                "", "", False,
            )
        return idx

    sorted_qids = sorted(qid_data.keys(), key=lambda q: (-qid_out_deg.get(q, 0), qid_data[q]["name"]))
    for q in sorted_qids:
        d = qid_data[q]
        add_scholar(
            d["name"],
            mgp=d["mgp"],
            univ=d["univ"],
            year=d["year"],
            flag=d["flag"],
            thesis=d["thesis"],
            qid=q,
        )

    for aq, sq in raw_edges:
        ai = qid_to_idx.get(aq)
        si = qid_to_idx.get(sq)
        if ai is not None and si is not None and ai != si:
            edge_set[(ai, si)] = 0

    def match_or_create(
        name: str,
        *,
        mgp: str = "",
        univ: str = "",
        year: int = 0,
        flag: int = 0,
    ) -> int:
        if mgp and mgp in mgp_to_idx:
            idx = mgp_to_idx[mgp]
            sc = scholars[idx]
            if univ and not sc["univ"]:
                sc["univ"] = univ
            if year and not sc["year"]:
                sc["year"] = year
            if flag == 1:
                sc["flag"] = 1
            return idx

        nk = normalize_key(name)
        cands = norm_to_indices.get(nk, [])
        if not cands and nk:
            toks = nk.split()
            if len(toks) == 2:
                cands = first_last_mid1_to_indices.get((toks[0], toks[1]), [])
            elif len(toks) == 3 and len(toks[1]) == 1:
                cands = norm_to_indices.get(f"{toks[0]} {toks[2]}", [])
        if cands:
            chosen = cands[0]
            if univ and len(cands) > 1:
                ulow = univ.lower()
                for ci in cands:
                    if scholars[ci]["univ"] and ulow in scholars[ci]["univ"].lower():
                        chosen = ci
                        break
            if flag == 1:
                scholars[chosen]["flag"] = 1
                if univ:
                    scholars[chosen]["univ"] = univ
                if year:
                    scholars[chosen]["year"] = year
            return chosen

        return add_scholar(name, mgp=mgp, univ=univ, year=year, flag=flag)

    # Verified MGP hub fixes (including Leonhard Euler -> Joseph-Louis Lagrange, restoring 105K+ descendants!)
    mgp_fixes = [
        ("17864", "Joseph-Louis Lagrange", "University of Turin", 0, "", [("38586", "Leonhard Euler")]),
        ("38586", "Leonhard Euler", "University of Basel", 1726, "Dissertatio physica de sono", [("53410", "Johann Bernoulli")]),
        ("18231", "Carl Friedrich Gauss", "University of Helmstedt", 1799, "Demonstratio nova theorematis omnem functionem algebraicam rationalem integram unius variabilis in factores reales primi vel secundi gradus resolvi posse", [("18230", "Johann Friedrich Pfaff")]),
        ("7298", "David Hilbert", "University of Königsberg", 1885, "Über invariante Eigenschaften spezieller binärer Formen, insbesondere der Kugelfunktionen", [("7404", "Ferdinand von Lindemann"), ("16915", "Heinrich Martin Weber")]),
        ("6967", "Emmy Noether", "University of Erlangen-Nuremberg", 1907, "Über die Bildung des Formensystems der ternären biquadratischen Form", []),
        ("43967", "Terence Tao", "Princeton University", 1996, "Three Regularity Results in Harmonic Analysis", []),
        ("55821", "Yves Capdeboscq", "Université Pierre-et-Marie-Curie - Paris VI", 1999, "Homogénéisation des modèles de diffusion en neutronique", []),
        ("70976", "Pat Hanrahan", "University of Wisconsin-Madison", 1985, "Topological Shape Models", [("35097", "Antony O. W. Stretton"), ("82321", "Leonard Merrick Uhr")]),
        ("69407", "Denis N. Zorin", "California Institute of Technology", 1998, "Stationary Subdivision and Multiresolution Surface Representations", [("73621", "Peter Schröder"), ("76722", "Alan Howard Barr")]),
        ("73621", "Peter Schröder", "Princeton University", 1994, "Wavelet Algorithms for Illumination Computations", [("70976", "Pat Hanrahan")]),
        ("76722", "Alan Howard Barr", "Rensselaer Polytechnic Institute", 1983, "Geometric Modeling and Fluid Dynamic Analysis of Swimming Spermatozoa", [("97349", "Garrett Mitchell Odell")]),
        ("322238", "Enrico Puppo", "Università di Genova", 1986, "", []),
        ("275795", "Daniele Panozzo", "Università di Genova", 2012, "From Irregular Meshes to Structured Models", [("322238", "Enrico Puppo")]),
        ("168211", "Yotam Gingold", "New York University", 2009, "", [("69407", "Denis N. Zorin")]),
        ("69417", "Aaron Hertzmann", "New York University", 2001, "", [("69407", "Denis N. Zorin")]),
        ("111539", "Lexing Ying", "New York University", 2004, "", [("69407", "Denis N. Zorin")]),
        ("275772", "Hans-Christian Ebke", "RWTH Aachen University", 2017, "", [("275795", "Daniele Panozzo")]),
        ("294752", "Zachary Ferguson", "New York University", 2023, "", [("275795", "Daniele Panozzo")]),
    ]
    for mid, nm, univ, yr, th, advs in mgp_fixes:
        si = match_or_create(nm, mgp=mid, univ=univ, year=yr, flag=2)
        if univ:
            scholars[si]["univ"] = univ
        if yr:
            scholars[si]["year"] = yr
        if th:
            theses_map[str(si)] = _pack_thesis_tuple(
                th, "MGP", mid, f"https://www.genealogy.math.ndsu.nodak.edu/id.php?id={mid}", "", "", False
            )
        for amid, anm in advs:
            ai = match_or_create(anm, mgp=amid, flag=2)
            if ai != si:
                edge_set[(ai, si)] = 2

    # Snapshot normalized keys of existing 400K scholars so UC eScholarship can auto-match ANY advisor in our graph!
    known_advisor_keys: Set[str] = set(norm_to_indices.keys())

    # ------------------------------------------------------------------
    # 5. Parallel bulk harvest across 7 official doctoral dissertation repositories!
    # ------------------------------------------------------------------
    print("[5/6] Parallel bulk harvesting official doctoral dissertations from 7 repositories...", flush=True)
    harvested_theses: List[Dict[str, Any]] = []

    def _run_mit_all() -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for pg in range(12):
            try:
                recs = fetch_mit_math_theses("", limit=50, page=pg)
                if not recs:
                    break
                out.extend(recs)
            except Exception:
                break
        return out

    def _run_nyu_all() -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        out.extend(fetch_nyu_courant_phds("", limit=100, years=[2026, 2025, 2024, 2023], parse_pdf_when_missing_advisor=True))
        out.extend(fetch_nyu_courant_phds("", limit=200, years=[2022, 2021, 2020, 2019, 2018, 2017, 2016], parse_pdf_when_missing_advisor=False))
        return out

    tasks = {
        "NYU Courant (2016-2026)": _run_nyu_all,
        "HAL/TEL (ALL Math+CS+Stat)": lambda: _harvest_hal_bulk(max_docs=40000),
        "UC eScholarship (ALL 9 Campuses)": lambda: _harvest_uc_all(known_advisor_keys),
        "DataCite (16K Math+CS Supervisors)": lambda: _harvest_datacite_bulk(max_pages=32, page_size=500),
        "theses.fr (2016-2026 Math+CS)": _harvest_theses_fr_fast,
        "MIT DSpace (Math PhDs)": _run_mit_all,
        "Cornell eCommons (Math+CS PhDs)": lambda: _harvest_cornell_ecommons(max_pages=12, page_size=50),
    }

    t_harv = time.time()
    results_by_task: Dict[str, List[Dict[str, Any]]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        future_map = {pool.submit(fn): label for label, fn in tasks.items()}
        for fut in concurrent.futures.as_completed(future_map):
            label = future_map[fut]
            try:
                recs = fut.result()
                results_by_task[label] = recs
                print(f"      {label}: {len(recs):,} verified dissertations (elapsed {time.time()-t_harv:.1f}s)", flush=True)
            except Exception as exc:
                results_by_task[label] = []
                print(f"      {label}: WARN {exc}", flush=True)

    # Merge in priority order (PDF-rich repos first so PDF links win on duplicates!)
    merge_order = [
        "NYU Courant (2016-2026)",
        "HAL/TEL (ALL Math+CS+Stat)",
        "UC eScholarship (ALL 9 Campuses)",
        "MIT DSpace (Math PhDs)",
        "Cornell eCommons (Math+CS PhDs)",
        "DataCite (16K Math+CS Supervisors)",
        "theses.fr (2016-2026 Math+CS)",
    ]
    for label in merge_order:
        harvested_theses.extend(results_by_task.get(label, []))

    seen_diss_keys: Set[Tuple[str, str]] = set()
    verified_scholar_indices: Set[int] = set()
    verified_count = 0
    linked_to_existing_advisor = 0
    repo_counts: Dict[str, int] = {}

    for rec in harvested_theses:
        repo = rec.get("source_repo") or "Unknown"
        rid = str(rec.get("source_record_id") or "")
        url = (rec.get("landing_url") or "").strip()
        title = (rec.get("thesis_title") or "").strip()
        advisors = rec.get("advisors") or []
        if not url.startswith(("http://", "https://")) or not title or not advisors:
            continue
        if (repo, rid) in seen_diss_keys:
            continue
        seen_diss_keys.add((repo, rid))

        si = match_or_create(
            rec["scholar_name"],
            univ=rec.get("university") or "",
            year=rec.get("year") or 0,
            flag=1,
        )
        scholars[si]["flag"] = 1
        if rec.get("university"):
            scholars[si]["univ"] = rec["university"]
        if rec.get("year"):
            scholars[si]["year"] = rec["year"]

        existing_th = theses_map.get(str(si))
        already_has_verified_pdf = bool(existing_th and (existing_th[6] & 1) and existing_th[4])
        if not already_has_verified_pdf or rec.get("pdf_url"):
            theses_map[str(si)] = _pack_thesis_tuple(
                title,
                repo,
                rid,
                url,
                rec.get("pdf_url") or "",
                rec.get("doi") or "",
                True,
            )
            if si not in verified_scholar_indices:
                verified_scholar_indices.add(si)
                verified_count += 1
                repo_counts[repo] = repo_counts.get(repo, 0) + 1

        for adv_name in advisors:
            existed_before = normalize_key(adv_name) in norm_to_indices
            ai = match_or_create(adv_name, univ="", year=0, flag=0)
            if existed_before:
                linked_to_existing_advisor += 1
            if ai != si:
                edge_set[(ai, si)] = 1

    print(
        f"      Merged {verified_count:,} unique verified dissertations "
        f"({linked_to_existing_advisor:,} advisor links connected into existing graph!)",
        flush=True,
    )

    # ------------------------------------------------------------------
    # 6. Export ultra-compact v3/v4 gzipped columnar bundles
    # ------------------------------------------------------------------
    print("[6/6] Exporting ultra-compact gzipped columnar bundles...", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    univ_to_id: Dict[str, int] = {}
    univ_list: List[str] = []
    ui_arr: List[int] = []
    n_arr: List[str] = []
    m_arr: List[str] = []
    y_arr: List[int] = []
    f_arr: List[int] = []

    for sc in scholars:
        n_arr.append(sc["name"])
        m_arr.append(sc["mgp"])
        y_arr.append(sc["year"])
        f_arr.append(sc["flag"])
        u = sc["univ"]
        if not u:
            ui_arr.append(-1)
        else:
            uid = univ_to_id.get(u)
            if uid is None:
                uid = len(univ_list)
                univ_to_id[u] = uid
                univ_list.append(u)
            ui_arr.append(uid)

    featured_targets = [
        ("Leyi Zhu", None),
        ("Tianrui Dai", None),
        ("Carl Friedrich Gauss", "18231"),
        ("Leonhard Euler", "38586"),
        ("David Hilbert", "7298"),
        ("Emmy Noether", "6967"),
        ("Denis N. Zorin", "69407"),
        ("Pat Hanrahan", "70976"),
        ("Terence Tao", "43967"),
    ]
    feat_indices: List[int] = []
    for fname, fmgp in featured_targets:
        idx = mgp_to_idx.get(fmgp) if fmgp else None
        if idx is None:
            c = norm_to_indices.get(normalize_key(fname), [])
            if c:
                idx = c[0]
        if idx is not None and idx not in feat_indices:
            feat_indices.append(idx)

    e_adv: List[int] = []
    e_stu: List[int] = []
    e_typ: List[int] = []
    for (ai, si), typ in edge_set.items():
        e_adv.append(ai)
        e_stu.append(si)
        e_typ.append(typ)

    stats_summary = {
        "total_scholars": len(scholars),
        "verified_scholars": len(verified_scholar_indices),
        "total_dissertations": verified_count,
        "total_edges": len(edge_set),
        "verified_edges": sum(1 for typ in e_typ if typ == 1),
        "repo_breakdown": [
            {"source_repo": r, "count": c}
            for r, c in sorted(repo_counts.items(), key=lambda x: -x[1])
        ],
    }

    core_payload = {
        "v": 3,
        "u": univ_list,
        "n": n_arr,
        "m": m_arr,
        "ui": ui_arr,
        "y": y_arr,
        "f": f_arr,
        "feat": feat_indices,
        "stats": stats_summary,
    }
    edges_payload = {"a": e_adv, "s": e_stu, "t": e_typ}
    theses_payload = {"v": 3, "r": REPO_LIST, "d": theses_map}

    def write_gz(filename: str, obj: Any) -> float:
        p = OUT_DIR / filename
        raw_bytes = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with gzip.open(p, "wb", compresslevel=9) as gz:
            gz.write(raw_bytes)
        mb = p.stat().st_size / (1024 * 1024)
        print(f"      Wrote {p.name}: {mb:.2f} MB gzipped ({len(raw_bytes)/(1024*1024):.2f} MB raw)", flush=True)
        return mb

    total_mb = (
        write_gz("core.json.gz", core_payload)
        + write_gz("edges.json.gz", edges_payload)
        + write_gz("theses.json.gz", theses_payload)
    )

    print(f"\n=== BUILD COMPLETE in {time.time()-t_start:.1f}s ===", flush=True)
    print(f"Total Scholars:              {stats_summary['total_scholars']:,}", flush=True)
    print(f"Total Advisor-Student Edges: {stats_summary['total_edges']:,}", flush=True)
    print(f"Verified Official Theses:    {stats_summary['total_dissertations']:,}", flush=True)
    print(f"Total Thesis Titles (All):   {len(theses_map):,}", flush=True)
    print(f"Total Gzipped Payload:       {total_mb:.2f} MB", flush=True)
    for rb in stats_summary["repo_breakdown"]:
        print(f"  - {rb['source_repo']}: {rb['count']:,}", flush=True)

    # Sanity checks!
    for label, key, mgp in [
        ("Leyi Zhu", "leyi zhu", None),
        ("Tianrui Dai", "tianrui dai", None),
        ("Yves Capdeboscq", "yves capdeboscq", "55821"),
        ("Terence Tao", "terence tao", "43967"),
        ("Leonhard Euler", "leonhard euler", "38586"),
        ("Pat Hanrahan", "pat hanrahan", "70976"),
        ("Denis N. Zorin", "denis n zorin", "69407"),
        ("Daniele Panozzo", "daniele panozzo", "275795"),
        ("Carl Friedrich Gauss", "carl friedrich gauss", "18231"),
    ]:
        idx = mgp_to_idx.get(mgp) if mgp else (norm_to_indices.get(key) or [None])[0]
        if idx is None:
            print(f"  [WARN] {label} not found!")
            continue
        adv_names = [n_arr[a] for (a, s) in edge_set if s == idx]
        stu_cnt = sum(1 for (a, s) in edge_set if a == idx)
        print(f"  [OK] #{idx} {n_arr[idx]} ({univ_list[ui_arr[idx]] if ui_arr[idx]>=0 else '—'}, {y_arr[idx] or '—'}) | advisors={adv_names[:4]} | students={stu_cnt}")


if __name__ == "__main__":
    main()
