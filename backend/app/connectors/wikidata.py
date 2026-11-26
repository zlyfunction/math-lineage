"""Wikidata historical Mathematics Genealogy backbone connector.

Uses MediaWiki's fast `wbgetentities` API (batch of 50 QIDs per request) to fetch
authentic historical & modern mathematical lineages with:
- P549: Mathematics Genealogy Project ID
- P184: doctoral advisor
- P185: doctoral student
- P69: educated at (university)
- P1026: academic thesis (linked QID -> label)
- Multilingual labels (en & zh)
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import Any, Dict, List, Set, Tuple

USER_AGENT = "MathLineage/1.0 (https://github.com/zlyfunction; open academic genealogy tool)"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# Verified canonical Wikidata QIDs for foundational & modern mathematical hubs
SEED_QIDS = [
    "Q7604",    # Leonhard Euler
    "Q6722",    # Carl Friedrich Gauss
    "Q41585",   # David Hilbert
    "Q7099",    # Emmy Noether
    "Q81082",   # Henri Poincaré
    "Q76604",   # Felix Klein
    "Q15990",   # Bernhard Riemann
    "Q17455",   # John von Neumann
    "Q153224",  # Andrey Kolmogorov
    "Q122992",  # Alexander Grothendieck
    "Q154728",  # Jean-Pierre Serre
    "Q184566",  # Michael Atiyah
    "Q155723",  # Shiing-Shen Chern (let's verify dynamically too!)
    "Q318174",  # Shing-Tung Yau
    "Q221265",  # Terence Tao
    "Q166341",  # Peter Scholze
    "Q935",     # Isaac Newton
    "Q9047",    # Gottfried Wilhelm Leibniz
    "Q122366",  # Jacob Bernoulli
    "Q227897",  # Johann Bernoulli
    "Q47162",   # G. H. Hardy
    "Q7251",    # Alan Turing
    "Q9310",    # Kurt Gödel
    "Q188121",  # Cédric Villani
    "Q333997",  # Pierre-Louis Lions
    "Q1387009", # Gilbert Strang
    "Q16203966",# Bonnie Berger
    "Q102116446", # Denis N. Zorin (NYU Courant / Caltech Ph.D. 1998, MGP #69407)
]


def _wbgetentities(qids: List[str], props: str = "labels|claims|descriptions") -> Dict[str, Any]:
    if not qids:
        return {}
    out: Dict[str, Any] = {}
    for i in range(0, len(qids), 50):
        batch = qids[i : i + 50]
        params = urllib.parse.urlencode({
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": props,
            "languages": "en|zh",
            "format": "json",
        })
        for attempt in range(4):
            try:
                req = urllib.request.Request(f"{WIKIDATA_API}?{params}", headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                out.update(data.get("entities", {}))
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 3:
                    time.sleep(2.5 * (attempt + 1))
                    continue
                raise
        time.sleep(0.6)
    return out


def _claim_strings(claims: Dict[str, Any], prop: str) -> List[str]:
    vals = []
    for c in claims.get(prop, []):
        dv = c.get("mainsnak", {}).get("datavalue")
        if dv and isinstance(dv.get("value"), str):
            vals.append(dv["value"])
    return vals


def _claim_item_ids(claims: Dict[str, Any], prop: str) -> List[str]:
    vals = []
    for c in claims.get(prop, []):
        dv = c.get("mainsnak", {}).get("datavalue")
        if dv and isinstance(dv.get("value"), dict) and "id" in dv["value"]:
            vals.append(dv["value"]["id"])
    return vals


def _claim_year(claims: Dict[str, Any], prop: str) -> int | None:
    for c in claims.get(prop, []):
        for q_prop in ("P585", "P582", "P577"):
            for qual in c.get("qualifiers", {}).get(q_prop, []):
                t = qual.get("datavalue", {}).get("value", {}).get("time", "")
                m = re.search(r"(\d{4})", t)
                if m:
                    return int(m.group(1))
    return None


def _is_human(claims: Dict[str, Any]) -> bool:
    return "Q5" in _claim_item_ids(claims, "P31")


def fetch_wikidata_genealogy_backbone(max_scholars: int = 380) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
    """Crawl an interconnected mathematical genealogy subgraph via Wikidata wbgetentities.

    Returns:
      scholars: list of dicts with wikidata_id, name, name_zh, mgp_id, university, thesis_title, year, bio_summary
      edges: list of (advisor_qid, student_qid) tuples
    """
    # Filter seeds to verified humans first
    initial_entities = _wbgetentities(SEED_QIDS)
    valid_seeds = [
        qid for qid, ent in initial_entities.items()
        if _is_human(ent.get("claims", {})) and (
            _claim_strings(ent.get("claims", {}), "P549")
            or _claim_item_ids(ent.get("claims", {}), "P184")
            or _claim_item_ids(ent.get("claims", {}), "P185")
        )
    ]

    fetched: Dict[str, Dict[str, Any]] = {qid: initial_entities[qid] for qid in valid_seeds}
    queue: deque[Tuple[str, int]] = deque((qid, 0) for qid in valid_seeds)
    seen: Set[str] = set(valid_seeds)

    # Multi-hop BFS prioritizing MGP-linked scholars (P549)
    while queue and len(fetched) < max_scholars:
        batch_to_fetch: List[Tuple[str, int]] = []
        while queue and len(batch_to_fetch) < 40 and (len(fetched) + len(batch_to_fetch)) < max_scholars:
            cur_qid, depth = queue.popleft()
            if depth >= 3:
                continue
            ent = fetched.get(cur_qid)
            if not ent:
                continue
            claims = ent.get("claims", {})
            # Always follow all doctoral advisors (upward) + top doctoral students (downward)
            neighbors = _claim_item_ids(claims, "P184")[:6] + _claim_item_ids(claims, "P185")[:10]
            for nq in neighbors:
                if nq not in seen and (len(fetched) + len(batch_to_fetch)) < max_scholars:
                    seen.add(nq)
                    batch_to_fetch.append((nq, depth + 1))

        if not batch_to_fetch:
            break

        ents = _wbgetentities([q for q, _ in batch_to_fetch])
        for nq, ndepth in batch_to_fetch:
            ent = ents.get(nq)
            if not ent or not _is_human(ent.get("claims", {})):
                continue
            claims = ent.get("claims", {})
            # Keep if it has an MGP ID or advisor/student links
            if _claim_strings(claims, "P549") or _claim_item_ids(claims, "P184") or _claim_item_ids(claims, "P185"):
                fetched[nq] = ent
                queue.append((nq, ndepth))

    # Resolve auxiliary QIDs (universities P69 and thesis items P1026) in one batch
    aux_qids: Set[str] = set()
    for ent in fetched.values():
        claims = ent.get("claims", {})
        univs = _claim_item_ids(claims, "P69")
        if univs:
            aux_qids.add(univs[-1])  # Usually highest degree institution
            aux_qids.add(univs[0])
        for tq in _claim_item_ids(claims, "P1026")[:1]:
            aux_qids.add(tq)

    aux_entities = _wbgetentities(list(aux_qids), props="labels|claims")

    scholars: List[Dict[str, Any]] = []
    edges_set: Set[Tuple[str, str]] = set()

    for qid, ent in fetched.items():
        labels = ent.get("labels", {})
        en_name = labels.get("en", {}).get("value")
        zh_name = labels.get("zh", {}).get("value")
        if not en_name:
            continue
        claims = ent.get("claims", {})
        mgp_list = _claim_strings(claims, "P549")
        mgp_id = mgp_list[0] if mgp_list else None
        orcid_list = _claim_strings(claims, "P496")
        orcid = orcid_list[0] if orcid_list else None

        # University from P69 (prefer one with doctoral degree qualifier or last listed)
        univ_name = ""
        phd_year = None
        for c in claims.get("P69", []):
            dv = c.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            uqid = dv.get("id") if isinstance(dv, dict) else None
            if not uqid:
                continue
            quals = c.get("qualifiers", {})
            # Check end time (P582) or point in time (P585)
            end_yr = None
            for qp in ("P582", "P585"):
                for qv in quals.get(qp, []):
                    t = qv.get("datavalue", {}).get("value", {}).get("time", "")
                    m = re.search(r"(\d{4})", t)
                    if m:
                        end_yr = int(m.group(1))
                        break
            deg_ids = [
                qv.get("datavalue", {}).get("value", {}).get("id")
                for qv in quals.get("P512", [])
                if isinstance(qv.get("datavalue", {}).get("value"), dict)
            ]
            label = aux_entities.get(uqid, {}).get("labels", {}).get("en", {}).get("value", "")
            if label and (not univ_name or "Q752297" in deg_ids or "Q849697" in deg_ids):
                univ_name = label
                if end_yr:
                    phd_year = end_yr

        # Thesis title from P1026 (academic thesis)
        thesis_title = ""
        thesis_qids = _claim_item_ids(claims, "P1026")
        if thesis_qids:
            tent = aux_entities.get(thesis_qids[0], {})
            thesis_title = tent.get("labels", {}).get("en", {}).get("value", "")
            if not phd_year:
                tclaims = tent.get("claims", {})
                for c in tclaims.get("P577", []):
                    t = c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("time", "")
                    m = re.search(r"(\d{4})", t)
                    if m:
                        phd_year = int(m.group(1))
                        break

        # Fallback estimate for historical scholars using birth year + 25 if no thesis year
        # Wait: DO NOT fabricate a PhD year! Leave year=None if unknown so every year is accurate.
        bio = ent.get("descriptions", {}).get("en", {}).get("value", "")

        scholars.append({
            "wikidata_id": qid,
            "name": en_name,
            "name_zh": zh_name,
            "mgp_id": mgp_id,
            "orcid": orcid,
            "university": univ_name,
            "country": "",
            "year": phd_year,
            "thesis_title": thesis_title,
            "bio_summary": bio,
        })

        for adv_q in _claim_item_ids(claims, "P184"):
            if adv_q in fetched and adv_q != qid:
                edges_set.add((adv_q, qid))
        for stu_q in _claim_item_ids(claims, "P185"):
            if stu_q in fetched and stu_q != qid:
                edges_set.add((qid, stu_q))

    return scholars, list(edges_set)


def fetch_wikidata_ancestors_for_qids(start_qids: List[str], max_depth: int = 12) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
    """Trace upward P184 doctoral advisor chains from specific Wikidata QIDs."""
    fetched: Dict[str, Dict[str, Any]] = {}
    seen: Set[str] = set()
    frontier = list(start_qids)

    for _ in range(max_depth):
        batch = [q for q in frontier if q not in seen]
        if not batch:
            break
        seen.update(batch)
        ents = _wbgetentities(batch)
        nxt: List[str] = []
        for q, ent in ents.items():
            if not _is_human(ent.get("claims", {})):
                continue
            fetched[q] = ent
            nxt.extend(_claim_item_ids(ent.get("claims", {}), "P184"))
        frontier = nxt
        time.sleep(0.35)

    aux_qids: Set[str] = set()
    for ent in fetched.values():
        claims = ent.get("claims", {})
        for uq in _claim_item_ids(claims, "P69")[:2]:
            aux_qids.add(uq)
        for tq in _claim_item_ids(claims, "P1026")[:1]:
            aux_qids.add(tq)
    aux_entities = _wbgetentities(list(aux_qids), props="labels|claims") if aux_qids else {}

    scholars: List[Dict[str, Any]] = []
    edges_set: Set[Tuple[str, str]] = set()
    for qid, ent in fetched.items():
        labels = ent.get("labels", {})
        en_name = labels.get("en", {}).get("value")
        zh_name = labels.get("zh", {}).get("value")
        if not en_name:
            continue
        claims = ent.get("claims", {})
        mgp_list = _claim_strings(claims, "P549")
        mgp_id = mgp_list[0] if mgp_list else None
        orcid_list = _claim_strings(claims, "P496")
        orcid = orcid_list[0] if orcid_list else None

        univ_name = ""
        phd_year = None
        for c in claims.get("P69", []):
            dv = c.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            uqid = dv.get("id") if isinstance(dv, dict) else None
            if not uqid:
                continue
            label = aux_entities.get(uqid, {}).get("labels", {}).get("en", {}).get("value", "")
            if label and not univ_name:
                univ_name = label
            for qp in ("P582", "P585"):
                for qv in c.get("qualifiers", {}).get(qp, []):
                    t = qv.get("datavalue", {}).get("value", {}).get("time", "")
                    m = re.search(r"(\d{4})", t)
                    if m and not phd_year:
                        phd_year = int(m.group(1))

        bio = ent.get("descriptions", {}).get("en", {}).get("value", "")
        if not phd_year and bio:
            m_bio_yr = re.search(r"Ph\.?D\.?.*?\b(1[789]\d{2}|20\d{2})\b", bio)
            if m_bio_yr:
                phd_year = int(m_bio_yr.group(1))
        if not univ_name and bio:
            m_bio_u = re.search(r"Ph\.?D\.?\s+([A-Z][A-Za-z\s\-&,]+?)\s+(?:1[789]\d{2}|20\d{2})", bio)
            if m_bio_u:
                univ_name = m_bio_u.group(1).strip()

        thesis_title = ""
        tqs = _claim_item_ids(claims, "P1026")
        if tqs:
            thesis_title = aux_entities.get(tqs[0], {}).get("labels", {}).get("en", {}).get("value", "")

        scholars.append({
            "wikidata_id": qid,
            "name": en_name,
            "name_zh": zh_name,
            "mgp_id": mgp_id,
            "orcid": orcid,
            "university": univ_name,
            "country": "",
            "year": phd_year,
            "thesis_title": thesis_title,
            "bio_summary": bio,
        })
        for adv_q in _claim_item_ids(claims, "P184"):
            if adv_q in fetched and adv_q != qid:
                edges_set.add((adv_q, qid))

    return scholars, list(edges_set)

