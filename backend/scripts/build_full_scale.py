"""Build full-scale (~265,000+ scholars, ~290,000+ edges, 2,000+ verified dissertations)
columnar gzipped bundles for MathLineage.

Sources:
1. University of Freiburg QLever Wikidata SPARQL mirror (CC0):
   - All ~262,000 scholars with Mathematics Genealogy Project ID (P549)
   - All ~280,000 doctoral advisor relationships (P184)
   - University affiliations (P69) and doctoral thesis items (P1026)
2. Five authoritative open doctoral dissertation repositories (2018-2026):
   - NYU Courant (cs.nyu.edu/dynamic/reports/ + PDF title-page verification)
   - HAL / TEL (French & European Math PhD theses with advisors + PDFs)
   - theses.fr (ABES French National Doctoral Registry, defended theses)
   - DataCite (Oxford ORA, Cambridge Apollo, LMU Munich, ETH, Caltech, TU Delft)
   - MIT DSpace (Department of Mathematics Ph.D. theses + Handles)

Outputs ultra-compact gzipped columnar JSON files in `frontend/public/data/`:
  - core.json.gz   (interned universities, scholar names, MGP IDs, years, status flags)
  - edges.json.gz  (dense integer advisor/student edge arrays + edge source types)
  - theses.json.gz (official verified dissertation metadata, URLs, PDFs, DOIs, thesis titles)
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.datacite import fetch_datacite_math_dissertations
from app.connectors.hal import fetch_hal_math_theses
from app.connectors.mit_dspace import fetch_mit_math_theses
from app.connectors.nyu_courant import fetch_nyu_courant_phds
from app.connectors.theses_fr import fetch_theses_fr_math
from app.normalizer import clean_person_name, normalize_key

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
QLEVER_API = "https://qlever.cs.uni-freiburg.de/api/wikidata"
USER_AGENT = "MathLineage/2.0 (https://github.com/zlyfunction/math-lineage; open academic genealogy)"

_SKIP_SCHOOL_RE = re.compile(
    r"\b(high school|secondary school|gymnasium|middle school|elementary school|grammar school|preparatory|lycée|lyceum)\b",
    re.I,
)


def _qlever_tsv(query: str, timeout: int = 90, retries: int = 4) -> List[List[str]]:
    url = f"{QLEVER_API}?query={urllib.parse.quote(query)}"
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            rows = []
            for line in raw.splitlines()[1:]:
                if line:
                    rows.append(line.split("\t"))
            time.sleep(0.4)
            return rows
        except Exception as exc:
            last_err = exc
            if attempt < retries - 1:
                wait_s = 2.0 * (2**attempt)
                print(f"      [retry {attempt+1}/{retries-1}] QLever error ({exc}); sleeping {wait_s:.0f}s...", flush=True)
                time.sleep(wait_s)
    raise RuntimeError(f"QLever query failed after {retries} attempts: {last_err}") from last_err


def _unquote_sparql(val: str) -> str:
    if not val:
        return ""
    s = val.strip()
    if s.startswith("<") and s.endswith(">"):
        return s[1:-1].rsplit("/", 1)[-1]
    # Strip language tag like "@en" or datatype "^^<...>"
    if '"@' in s:
        s = s.rsplit('"@', 1)[0] + '"'
    elif '"^^' in s:
        s = s.rsplit('"^^', 1)[0] + '"'
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s.replace('\\"', '"').replace("\\\\", "\\").strip()


def _parse_mgp_description(desc: str) -> Tuple[str, Optional[int], str]:
    """Extract (university, year, thesis_title) when Wikidata description follows MGP format."""
    if not desc:
        return "", None, ""
    univ = ""
    year: Optional[int] = None
    thesis = ""

    # Pattern 1: 'Ph.D. from University of Wisconsin-Madison in 1969 on "Thesis Title" supervised by ...'
    m1 = re.search(
        r'(?:Ph\.?D\.?|Doctorat|Dr\.?\s*rer\.?\s*nat\.?|Sc\.?D\.?)\s+from\s+([^,]+?)\s+in\s+(1[5-9]\d{2}|20\d{2})(?:\s+on\s+"([^"]+)")?',
        desc,
        re.I,
    )
    if m1:
        univ = m1.group(1).strip(" .,;")
        year = int(m1.group(2))
        thesis = (m1.group(3) or "").strip()
        return univ, year, thesis

    # Pattern 2: 'Ph.D. California Institute of Technology 1998' or 'doctorat Université de Nanterre 1993'
    m2 = re.search(
        r'(?:Ph\.?D\.?|Doctorat|Dr\.?\s*rer\.?\s*nat\.?|Dr\.?\s*phil\.?|D\.?\s*Phil\.?|Sc\.?D\.?|Candidate of Sciences)\s+([A-ZÀ-Ÿ][^,;\d]{2,90}?)\s+(1[5-9]\d{2}|20\d{2})\b',
        desc,
        re.I,
    )
    if m2:
        univ = m2.group(1).strip(" .,;-")
        year = int(m2.group(2))
        return univ, year, ""

    # Pattern 3: 'Ph.D. 1995 University of ...'
    m3 = re.search(
        r'(?:Ph\.?D\.?|Doctorat|Dr\.?)\s+(1[5-9]\d{2}|20\d{2})\s+([A-ZÀ-Ÿ][^,;\d]{2,90})',
        desc,
        re.I,
    )
    if m3:
        year = int(m3.group(1))
        univ = m3.group(2).strip(" .,;-")
        return univ, year, ""

    return "", None, ""


def main() -> None:
    t_start = time.time()
    print("=== MathLineage Full-Scale Builder (265K+ Scholars) ===", flush=True)

    # ------------------------------------------------------------------
    # 1. Fetch ALL MGP scholars (~262,000) from QLever Wikidata mirror
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
    scholar_rows = _qlever_tsv(q_scholars)
    print(f"      Fetched {len(scholar_rows):,} scholar rows in {time.time()-t0:.1f}s", flush=True)

    # Data structures indexed by Wikidata QID first
    qid_data: Dict[str, Dict[str, Any]] = {}
    mgp_to_qid: Dict[str, str] = {}

    for row in scholar_rows:
        if len(row) < 3:
            continue
        qid = _unquote_sparql(row[0])
        mgp = _unquote_sparql(row[1])
        name = _unquote_sparql(row[2])
        desc = _unquote_sparql(row[3]) if len(row) > 3 else ""
        if not qid or not name:
            continue
        if qid in qid_data:
            continue
        univ, yr, thesis = _parse_mgp_description(desc)
        qid_data[qid] = {
            "qid": qid,
            "mgp": mgp,
            "name": name,
            "univ": univ,
            "year": yr or 0,
            "thesis": thesis,
            "flag": 2,  # 2 = historical MGP/Wikidata
            "msc": "",
        }
        if mgp:
            mgp_to_qid[mgp] = qid

    print(f"      Unique P549 scholars: {len(qid_data):,}", flush=True)

    # ------------------------------------------------------------------
    # 2. Fetch university affiliations (P69), graduation years, & thesis labels (P1026)
    # ------------------------------------------------------------------
    t0 = time.time()
    print("[2/6] Querying QLever for P69 universities, graduation years, and P1026 theses...", flush=True)
    q_univ = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?p ?univName WHERE {
  ?p wdt:P549 ?mgp ; wdt:P69 ?u .
  ?u rdfs:label ?univName . FILTER(LANG(?univName) = "en")
}"""
    try:
        for row in _qlever_tsv(q_univ):
            if len(row) < 2:
                continue
            qid = _unquote_sparql(row[0])
            uname = _unquote_sparql(row[1])
            rec = qid_data.get(qid)
            if rec and not rec["univ"] and uname and not _SKIP_SCHOOL_RE.search(uname):
                rec["univ"] = uname
    except Exception as exc:
        print(f"      WARN P69 universities skipped: {exc}", flush=True)

    q_p69_yr = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
SELECT ?p ?yr WHERE {
  ?p wdt:P549 ?mgp ; p:P69 ?st .
  ?st pq:P582 ?yr .
}"""
    try:
        p69_max_yr: Dict[str, int] = {}
        for row in _qlever_tsv(q_p69_yr):
            if len(row) < 2:
                continue
            qid = _unquote_sparql(row[0])
            raw_yr = _unquote_sparql(row[1])
            if len(raw_yr) >= 4 and raw_yr[:4].isdigit():
                y = int(raw_yr[:4])
                if 1500 <= y <= 2026:
                    if y > p69_max_yr.get(qid, 0):
                        p69_max_yr[qid] = y
        for qid, y in p69_max_yr.items():
            rec = qid_data.get(qid)
            if rec and not rec["year"]:
                rec["year"] = y
    except Exception as exc:
        print(f"      WARN P69 end years skipped: {exc}", flush=True)

    q_theses = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?p ?tLabel WHERE {
  ?p wdt:P549 ?mgp ; wdt:P1026 ?t .
  ?t rdfs:label ?tLabel . FILTER(LANG(?tLabel) = "en")
}"""
    try:
        for row in _qlever_tsv(q_theses):
            if len(row) < 2:
                continue
            qid = _unquote_sparql(row[0])
            tlabel = _unquote_sparql(row[1])
            rec = qid_data.get(qid)
            if rec and not rec["thesis"] and tlabel:
                rec["thesis"] = tlabel
    except Exception as exc:
        print(f"      WARN P1026 theses skipped: {exc}", flush=True)
    print(f"      Enriched universities, years & theses in {time.time()-t0:.1f}s", flush=True)

    # ------------------------------------------------------------------
    # 3. Fetch ALL ~280,000 doctoral advisor edges (P184) + missing advisor labels
    # ------------------------------------------------------------------
    t0 = time.time()
    print("[3/6] Querying QLever for all P184 advisor-student edges...", flush=True)
    q_edges = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?s ?a WHERE {
  ?s wdt:P549 ?m1 ; wdt:P184 ?a .
}"""
    raw_edges: List[Tuple[str, str]] = []
    missing_adv_qids: Set[str] = set()
    for row in _qlever_tsv(q_edges):
        if len(row) < 2:
            continue
        sq = _unquote_sparql(row[0])
        aq = _unquote_sparql(row[1])
        if sq in qid_data and aq and aq != sq:
            raw_edges.append((aq, sq))
            if aq not in qid_data:
                missing_adv_qids.add(aq)

    # Also fetch English labels for non-P549 advisors referenced in P184 edges!
    q_non_mgp_advs = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?a ?name WHERE {
  ?s wdt:P549 ?m1 ; wdt:P184 ?a .
  FILTER NOT EXISTS { ?a wdt:P549 ?m2 }
  ?a rdfs:label ?name . FILTER(LANG(?name) = "en")
}"""
    try:
        for row in _qlever_tsv(q_non_mgp_advs):
            if len(row) < 2:
                continue
            aq = _unquote_sparql(row[0])
            aname = _unquote_sparql(row[1])
            if aq in missing_adv_qids and aname and aq not in qid_data:
                qid_data[aq] = {
                    "qid": aq,
                    "mgp": "",
                    "name": aname,
                    "univ": "",
                    "year": 0,
                    "thesis": "",
                    "flag": 2,
                    "msc": "",
                }
    except Exception as exc:
        print(f"      WARN non-MGP advisor labels skipped: {exc}", flush=True)

    print(f"      Fetched {len(raw_edges):,} raw P184 edges ({len(qid_data):,} total nodes) in {time.time()-t0:.1f}s", flush=True)

    # ------------------------------------------------------------------
    # 4. Build dense 0-based index & exact MGP-verified enrichments
    # ------------------------------------------------------------------
    scholars: List[Dict[str, Any]] = []
    qid_to_idx: Dict[str, int] = {}
    mgp_to_idx: Dict[str, int] = {}
    norm_to_indices: Dict[str, List[int]] = {}
    first_last_mid1_to_indices: Dict[Tuple[str, str], List[int]] = {}
    edge_set: Dict[Tuple[int, int], int] = {}  # (adv_idx, stu_idx) -> type (1=thesis, 2=mgp, 0=wikidata)
    theses_map: Dict[str, Dict[str, Any]] = {}  # str(scholar_idx) -> dissertation provenance object

    # Count outgoing student degree per QID so name disambiguation prefers established advisors
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
        msc: str = "",
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
            "msc": msc,
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
            theses_map[str(idx)] = {
                "t": thesis,
                "r": "MGP / Wikidata",
                "id": mgp or qid,
                "url": f"https://www.genealogy.math.ndsu.nodak.edu/id.php?id={mgp}" if mgp else "",
                "pdf": "",
                "doi": "",
                "advs": [],
                "yr": year or None,
                "inst": univ,
                "msc": msc,
                "verified": False,
            }
        return idx

    # Insert all QLever scholars sorted by out-degree desc so famous mathematicians get lower IDs
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
            msc=d["msc"],
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
        msc: str = "",
        prefer_existing_advisor: bool = False,
    ) -> int:
        if mgp and mgp in mgp_to_idx:
            idx = mgp_to_idx[mgp]
            sc = scholars[idx]
            if univ and not sc["univ"]:
                sc["univ"] = univ
            if year and not sc["year"]:
                sc["year"] = year
            if msc and not sc["msc"]:
                sc["msc"] = msc
            if flag == 1:
                sc["flag"] = 1
            return idx

        nk = normalize_key(name)
        cands = norm_to_indices.get(nk, [])
        # O(1) middle-initial tolerant match (e.g., "denis zorin" <-> "denis n zorin")
        if not cands and nk:
            toks = nk.split()
            if len(toks) == 2:
                cands = first_last_mid1_to_indices.get((toks[0], toks[1]), [])
            elif len(toks) == 3 and len(toks[1]) == 1:
                cands = norm_to_indices.get(f"{toks[0]} {toks[2]}", [])
        if cands:
            # Prefer exact university match, else first (highest out-degree because of sorting!)
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

        return add_scholar(name, mgp=mgp, univ=univ, year=year, flag=flag, msc=msc)

    # Apply exact verified MGP reference metadata for key modern lineages (including Pat Hanrahan, Denis Zorin, Daniele Panozzo)
    print("[4/6] Applying verified MGP metadata enrichments...", flush=True)
    mgp_fixes = [
        ("70976", "Pat Hanrahan", "University of Wisconsin-Madison", 1985, "Topological Shape Models", "92 — Biology and other natural sciences", [("35097", "Antony O. W. Stretton"), ("82321", "Leonard Merrick Uhr")]),
        ("69407", "Denis N. Zorin", "California Institute of Technology", 1998, "Stationary Subdivision and Multiresolution Surface Representations", "", [("73621", "Peter Schröder"), ("76722", "Alan Howard Barr")]),
        ("73621", "Peter Schröder", "Princeton University", 1994, "Wavelet Algorithms for Illumination Computations", "", [("70976", "Pat Hanrahan")]),
        ("76722", "Alan Howard Barr", "Rensselaer Polytechnic Institute", 1983, "Geometric Modeling and Fluid Dynamic Analysis of Swimming Spermatozoa", "", [("97349", "Garrett Mitchell Odell")]),
        ("322238", "Enrico Puppo", "Università di Genova", 1986, "", "", []),
        ("275795", "Daniele Panozzo", "Università di Genova", 2012, "From Irregular Meshes to Structured Models", "", [("322238", "Enrico Puppo")]),
        ("168211", "Yotam Gingold", "New York University", 2009, "", "", [("69407", "Denis N. Zorin")]),
        ("69417", "Aaron Hertzmann", "New York University", 2001, "", "", [("69407", "Denis N. Zorin")]),
        ("111539", "Lexing Ying", "New York University", 2004, "", "", [("69407", "Denis N. Zorin")]),
        ("275772", "Hans-Christian Ebke", "RWTH Aachen University", 2017, "", "", [("275795", "Daniele Panozzo")]),
        ("294752", "Zachary Ferguson", "New York University", 2023, "", "", [("275795", "Daniele Panozzo")]),
        ("43967", "Terence Tao", "Princeton University", 1996, "Three Regularity Results in Harmonic Analysis", "", []),
        ("18231", "Carl Friedrich Gauss", "University of Helmstedt", 1799, "Demonstratio nova theorematis omnem functionem algebraicam rationalem integram unius variabilis in factores reales primi vel secundi gradus resolvi posse", "", []),
        ("38586", "Leonhard Euler", "University of Basel", 1726, "Dissertatio physica de sono", "", []),
        ("7298", "David Hilbert", "University of Königsberg", 1885, "Über invariante Eigenschaften spezieller binärer Formen, insbesondere der Kugelfunktionen", "", []),
        ("6967", "Emmy Noether", "University of Erlangen-Nuremberg", 1907, "Über die Bildung des Formensystems der ternären biquadratischen Form", "", []),
    ]
    for mid, nm, univ, yr, th, msc, advs in mgp_fixes:
        si = match_or_create(nm, mgp=mid, univ=univ, year=yr, flag=2, msc=msc)
        scholars[si]["univ"] = univ
        scholars[si]["year"] = yr
        if msc:
            scholars[si]["msc"] = msc
        if th:
            theses_map[str(si)] = {
                "t": th,
                "r": "MGP",
                "id": mid,
                "url": f"https://www.genealogy.math.ndsu.nodak.edu/id.php?id={mid}",
                "pdf": "",
                "doi": "",
                "advs": [a[1] for a in advs],
                "yr": yr,
                "inst": univ,
                "msc": msc,
                "verified": False,
            }
        for amid, anm in advs:
            ai = match_or_create(anm, mgp=amid, flag=2)
            if ai != si:
                edge_set[(ai, si)] = 2

    # ------------------------------------------------------------------
    # 5. Harvest recent 2018-2026 official verified dissertations from 5 repos
    # ------------------------------------------------------------------
    print("[5/6] Harvesting recent verified doctoral dissertations from 5 official archives...", flush=True)
    harvested_theses: List[Dict[str, Any]] = []

    def safe_collect(label: str, fn) -> None:
        t_h = time.time()
        try:
            recs = fn()
            harvested_theses.extend(recs)
            print(f"      {label}: {len(recs)} verified dissertations ({time.time()-t_h:.1f}s)", flush=True)
        except Exception as exc:
            print(f"      {label}: WARN {exc}", flush=True)

    # NYU Courant 2023-2026 (with PDF title-page verification for Leyi Zhu 2026 etc.) + 2018-2022
    safe_collect("NYU Courant (2023-2026)", lambda: fetch_nyu_courant_phds("", limit=80, years=[2026, 2025, 2024, 2023], parse_pdf_when_missing_advisor=True))
    safe_collect("NYU Courant (2018-2022)", lambda: fetch_nyu_courant_phds("", limit=120, years=[2022, 2021, 2020, 2019, 2018], parse_pdf_when_missing_advisor=False))

    # HAL / TEL recent Math PhD theses with advisors + PDFs (up to 600!)
    for pg in range(6):
        safe_collect(f"HAL/TEL (page {pg+1})", lambda p=pg: fetch_hal_math_theses("", limit=100, start=p * 100))

    # theses.fr defended 2018-2026 Math PhDs (up to 400!)
    for pg in range(1, 5):
        safe_collect(f"theses.fr (page {pg})", lambda p=pg: fetch_theses_fr_math("", limit=100, page=p))

    # MIT DSpace Dept. of Mathematics PhDs (up to 150!)
    for pg in range(3):
        safe_collect(f"MIT DSpace (page {pg+1})", lambda p=pg: fetch_mit_math_theses("", limit=50, page=p))

    # DataCite Math Dissertations with Supervisors (Oxford, Cambridge, LMU, ETH, Caltech, TU Delft)
    for pg in range(1, 5):
        safe_collect(f"DataCite (page {pg})", lambda p=pg: fetch_datacite_math_dissertations("mathematics", limit=60, page=p))
    safe_collect("DataCite (geometry/topology/PDE)", lambda: fetch_datacite_math_dissertations("geometry OR topology OR algebra OR numerical", limit=60, page=1))

    # Merge harvested verified dissertations into the 262K+ global graph!
    seen_diss_keys: Set[Tuple[str, str]] = set()
    verified_count = 0
    linked_to_existing_mgp_advisor = 0
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
        # Upgrade existing scholar to verified_dissertation!
        scholars[si]["flag"] = 1
        if rec.get("university"):
            scholars[si]["univ"] = rec["university"]
        if rec.get("year"):
            scholars[si]["year"] = rec["year"]

        theses_map[str(si)] = {
            "t": title,
            "te": rec.get("thesis_title_en") or "",
            "r": repo,
            "id": rid,
            "url": url,
            "pdf": rec.get("pdf_url") or "",
            "doi": rec.get("doi") or "",
            "advs": advisors,
            "yr": rec.get("year") or None,
            "inst": rec.get("university") or "",
            "verified": True,
        }
        verified_count += 1
        repo_counts[repo] = repo_counts.get(repo, 0) + 1

        for adv_name in advisors:
            existed_before = normalize_key(adv_name) in norm_to_indices
            ai = match_or_create(
                adv_name,
                univ="",
                year=0,
                flag=0,
                prefer_existing_advisor=True,
            )
            if existed_before and scholars[ai]["mgp"]:
                linked_to_existing_mgp_advisor += 1
            if ai != si:
                edge_set[(ai, si)] = 1  # 1 = dissertation_verified

    print(
        f"      Merged {verified_count:,} verified dissertations "
        f"({linked_to_existing_mgp_advisor:,} advisor links directly connected into the 262K MGP graph!)",
        flush=True,
    )

    # ------------------------------------------------------------------
    # 6. Export ultra-compact gzipped columnar v2 bundles
    # ------------------------------------------------------------------
    print("[6/6] Exporting ultra-compact gzipped columnar bundles...", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Intern university strings
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

    # Featured landmark indices
    featured_targets = [
        ("Leyi Zhu", None),
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
        idx = None
        if fmgp and fmgp in mgp_to_idx:
            idx = mgp_to_idx[fmgp]
        else:
            c = norm_to_indices.get(normalize_key(fname), [])
            if c:
                idx = c[0]
        if idx is not None and idx not in feat_indices:
            feat_indices.append(idx)

    # Flatten edges
    e_adv: List[int] = []
    e_stu: List[int] = []
    e_typ: List[int] = []
    for (ai, si), typ in edge_set.items():
        e_adv.append(ai)
        e_stu.append(si)
        e_typ.append(typ)

    stats_summary = {
        "total_scholars": len(scholars),
        "verified_scholars": sum(1 for sc in scholars if sc["flag"] == 1),
        "total_dissertations": verified_count,
        "total_edges": len(edge_set),
        "verified_edges": sum(1 for typ in e_typ if typ == 1),
        "repo_breakdown": [
            {"source_repo": r, "count": c}
            for r, c in sorted(repo_counts.items(), key=lambda x: -x[1])
        ],
    }

    core_payload = {
        "v": 2,
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
    theses_payload = theses_map

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
    print(f"Total Scholars:            {stats_summary['total_scholars']:,}", flush=True)
    print(f"Total Advisor-Student Edges: {stats_summary['total_edges']:,}", flush=True)
    print(f"Verified Official Theses:  {stats_summary['total_dissertations']:,}", flush=True)
    print(f"Total Gzipped Payload:     {total_mb:.2f} MB", flush=True)
    for rb in stats_summary["repo_breakdown"]:
        print(f"  - {rb['source_repo']}: {rb['count']:,}", flush=True)

    # Sanity check Leyi Zhu, Pat Hanrahan, Daniele Panozzo, Denis Zorin, Gauss!
    for label, key, mgp in [
        ("Leyi Zhu", "leyi zhu", None),
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
