"""Strict dissertation-verified ingestion and entity-linking pipeline."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from .connectors.datacite import fetch_datacite_math_dissertations
from .connectors.hal import fetch_hal_math_theses
from .connectors.mit_dspace import fetch_mit_math_theses
from .connectors.nyu_courant import fetch_nyu_courant_phds
from .connectors.theses_fr import fetch_theses_fr_math
from .connectors.wikidata import fetch_wikidata_ancestors_for_qids, fetch_wikidata_genealogy_backbone
from .database import get_conn, rebuild_fts, upsert_fts_row
from .normalizer import clean_person_name, normalize_key, split_name


def find_or_create_scholar(
    conn: sqlite3.Connection,
    name: str,
    *,
    name_zh: Optional[str] = None,
    mgp_id: Optional[str] = None,
    wikidata_id: Optional[str] = None,
    orcid: Optional[str] = None,
    idref_ppn: Optional[str] = None,
    degree: str = "Ph.D.",
    university: str = "",
    country: str = "",
    year: Optional[int] = None,
    thesis_title: str = "",
    thesis_title_en: str = "",
    msc_code: str = "",
    msc_label: str = "",
    verification_status: str = "verified_dissertation",
    bio_summary: str = "",
) -> Tuple[int, bool]:
    """Match an existing scholar or insert a new one. Returns (scholar_id, created)."""
    cleaned = clean_person_name(name) or name.strip()
    norm = normalize_key(cleaned)
    given, family = split_name(cleaned)

    existing = None
    if wikidata_id:
        existing = conn.execute("SELECT * FROM scholars WHERE wikidata_id = ?", (wikidata_id,)).fetchone()
    if not existing and mgp_id:
        existing = conn.execute("SELECT * FROM scholars WHERE mgp_id = ?", (mgp_id,)).fetchone()
    if not existing and orcid:
        existing = conn.execute("SELECT * FROM scholars WHERE orcid = ?", (orcid,)).fetchone()
    if not existing and norm:
        # Prefer exact normalized name match; if multiple, prefer matching university or highest verification status
        candidates = conn.execute(
            "SELECT * FROM scholars WHERE normalized_name = ? ORDER BY CASE verification_status WHEN 'verified_dissertation' THEN 0 WHEN 'historical_wikidata' THEN 1 ELSE 2 END, id ASC",
            (norm,),
        ).fetchall()
        if not candidates:
            # Middle-initial tolerant match (e.g., "denis zorin" <-> "denis n zorin")
            toks = norm.split()
            if len(toks) == 2:
                candidates = conn.execute(
                    "SELECT * FROM scholars WHERE normalized_name LIKE ? ORDER BY CASE verification_status WHEN 'verified_dissertation' THEN 0 WHEN 'historical_wikidata' THEN 1 ELSE 2 END, id ASC",
                    (f"{toks[0]} _ {toks[1]}",),
                ).fetchall()
            elif len(toks) == 3 and len(toks[1]) == 1:
                candidates = conn.execute(
                    "SELECT * FROM scholars WHERE normalized_name = ? ORDER BY CASE verification_status WHEN 'verified_dissertation' THEN 0 WHEN 'historical_wikidata' THEN 1 ELSE 2 END, id ASC",
                    (f"{toks[0]} {toks[2]}",),
                ).fetchall()
        if len(candidates) == 1:
            existing = candidates[0]
        elif len(candidates) > 1:
            for c in candidates:
                if university and c["university"] and university.lower() in c["university"].lower():
                    existing = c
                    break
            if not existing:
                existing = candidates[0]

    if existing:
        sid = existing["id"]
        # Upgrade metadata without overwriting stronger existing values
        status_rank = {"verified_dissertation": 3, "historical_wikidata": 2, "advisor_inferred": 1}
        new_status = existing["verification_status"]
        if status_rank.get(verification_status, 0) > status_rank.get(new_status, 0):
            new_status = verification_status

        conn.execute(
            """
            UPDATE scholars SET
                name_zh = COALESCE(NULLIF(name_zh, ''), ?),
                mgp_id = COALESCE(mgp_id, ?),
                wikidata_id = COALESCE(wikidata_id, ?),
                orcid = COALESCE(NULLIF(orcid, ''), ?),
                idref_ppn = COALESCE(NULLIF(idref_ppn, ''), ?),
                university = CASE WHEN university = '' THEN ? ELSE university END,
                country = CASE WHEN country = '' THEN ? ELSE country END,
                year = COALESCE(year, ?),
                thesis_title = CASE WHEN thesis_title = '' THEN ? ELSE thesis_title END,
                thesis_title_en = CASE WHEN thesis_title_en = '' THEN ? ELSE thesis_title_en END,
                msc_code = CASE WHEN msc_code = '' THEN ? ELSE msc_code END,
                msc_label = CASE WHEN msc_label = '' THEN ? ELSE msc_label END,
                bio_summary = CASE WHEN bio_summary = '' THEN ? ELSE bio_summary END,
                verification_status = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                name_zh,
                mgp_id,
                wikidata_id,
                orcid,
                idref_ppn,
                university,
                country,
                year,
                thesis_title,
                thesis_title_en,
                msc_code,
                msc_label,
                bio_summary,
                new_status,
                sid,
            ),
        )
        return sid, False

    cur = conn.execute(
        """
        INSERT INTO scholars (
            name, name_zh, normalized_name, given_name, family_name,
            mgp_id, wikidata_id, orcid, idref_ppn,
            degree, university, country, year,
            thesis_title, thesis_title_en, msc_code, msc_label,
            verification_status, bio_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cleaned,
            name_zh,
            norm,
            given,
            family,
            mgp_id,
            wikidata_id,
            orcid,
            idref_ppn,
            degree or "Ph.D.",
            university or "",
            country or "",
            year,
            thesis_title or "",
            thesis_title_en or "",
            msc_code or "",
            msc_label or "",
            verification_status,
            bio_summary or "",
        ),
    )
    return int(cur.lastrowid), True


def ingest_verified_dissertation(conn: sqlite3.Connection, rec: Dict[str, Any], update_fts: bool = True) -> Dict[str, Any]:
    """Strictly validate and commit one dissertation-verified record into SQLite.

    Hard verification rule:
      - Must have a real HTTP(S) landing_url
      - Must have a non-empty thesis_title
      - Must have a valid scholar_name AND at least one explicit advisor
    """
    landing_url = (rec.get("landing_url") or "").strip()
    thesis_title = (rec.get("thesis_title") or "").strip()
    scholar_name = clean_person_name(rec.get("scholar_name") or "")
    advisors = [clean_person_name(a) for a in (rec.get("advisors") or []) if clean_person_name(a)]
    advisors = [a for a in dict.fromkeys(advisors) if a.lower() != scholar_name.lower()]

    if not landing_url.startswith(("http://", "https://")) or not thesis_title or not scholar_name or not advisors:
        return {"accepted": False, "reason": "Missing verifiable dissertation URL, thesis title, or explicit advisor"}

    source_repo = rec.get("source_repo") or "Unknown"
    source_record_id = str(rec.get("source_record_id") or landing_url)

    # Check if this exact dissertation record is already stored
    existing_diss = conn.execute(
        "SELECT id, scholar_id FROM dissertations WHERE source_repo = ? AND source_record_id = ?",
        (source_repo, source_record_id),
    ).fetchone()
    if existing_diss:
        return {
            "accepted": True,
            "duplicate": True,
            "scholar_id": existing_diss["scholar_id"],
            "dissertation_id": existing_diss["id"],
            "new_scholars": 0,
            "new_dissertations": 0,
            "new_edges": 0,
        }

    new_scholars = 0
    new_edges = 0

    scholar_id, created = find_or_create_scholar(
        conn,
        scholar_name,
        orcid=rec.get("orcid") or None,
        idref_ppn=rec.get("idref_ppn") or None,
        degree=rec.get("degree") or "Ph.D.",
        university=rec.get("university") or "",
        country=rec.get("country") or "",
        year=rec.get("year"),
        thesis_title=thesis_title,
        thesis_title_en=rec.get("thesis_title_en") or "",
        msc_code=rec.get("msc_code") or "",
        verification_status="verified_dissertation",
    )
    if created:
        new_scholars += 1

    raw_meta = rec.get("raw_metadata")
    raw_json = raw_meta if isinstance(raw_meta, str) else json.dumps(raw_meta or {}, ensure_ascii=False)

    cur_d = conn.execute(
        """
        INSERT INTO dissertations (
            scholar_id, title, title_en, author_raw, advisors_raw,
            institution, department, degree, year,
            source_repo, source_record_id, doi, landing_url, pdf_url, raw_metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scholar_id,
            thesis_title,
            rec.get("thesis_title_en") or "",
            rec.get("scholar_name") or scholar_name,
            json.dumps(advisors, ensure_ascii=False),
            rec.get("university") or "",
            rec.get("department") or "",
            rec.get("degree") or "Ph.D.",
            rec.get("year"),
            source_repo,
            source_record_id,
            rec.get("doi") or "",
            landing_url,
            rec.get("pdf_url") or "",
            raw_json,
        ),
    )
    diss_id = int(cur_d.lastrowid)

    # Link every explicit advisor from the dissertation
    touched_ids = [scholar_id]
    for adv_name in advisors:
        adv_id, adv_created = find_or_create_scholar(
            conn,
            adv_name,
            university=rec.get("university") or "",
            country=rec.get("country") or "",
            verification_status="advisor_inferred",
        )
        if adv_created:
            new_scholars += 1
        touched_ids.append(adv_id)

        if adv_id != scholar_id:
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO advisor_edges (advisor_id, student_id, source_type, dissertation_id, confidence)
                    VALUES (?, ?, 'dissertation_verified', ?, 1.0)
                    """,
                    (adv_id, scholar_id, diss_id),
                )
                if conn.total_changes > 0:
                    new_edges += 1
            except sqlite3.IntegrityError:
                pass

    if update_fts:
        for tid in set(touched_ids):
            upsert_fts_row(conn, tid)

    return {
        "accepted": True,
        "duplicate": False,
        "scholar_id": scholar_id,
        "dissertation_id": diss_id,
        "new_scholars": new_scholars,
        "new_dissertations": 1,
        "new_edges": new_edges,
    }


def ingest_wikidata_backbone(max_scholars: int = 380) -> Dict[str, Any]:
    """Fetch and store the historical Mathematics Genealogy backbone from Wikidata."""
    scholars, edges = fetch_wikidata_genealogy_backbone(max_scholars=max_scholars)
    added_scholars = 0
    added_edges = 0

    with get_conn() as conn:
        qid_to_id: Dict[str, int] = {}
        for s in scholars:
            sid, created = find_or_create_scholar(
                conn,
                s["name"],
                name_zh=s.get("name_zh"),
                mgp_id=s.get("mgp_id"),
                wikidata_id=s.get("wikidata_id"),
                orcid=s.get("orcid"),
                university=s.get("university") or "",
                country=s.get("country") or "",
                year=s.get("year"),
                thesis_title=s.get("thesis_title") or "",
                verification_status="historical_wikidata",
                bio_summary=s.get("bio_summary") or "",
            )
            qid_to_id[s["wikidata_id"]] = sid
            if created:
                added_scholars += 1

        for adv_q, stu_q in edges:
            a_id = qid_to_id.get(adv_q)
            s_id = qid_to_id.get(stu_q)
            if a_id and s_id and a_id != s_id:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO advisor_edges (advisor_id, student_id, source_type, confidence)
                    VALUES (?, ?, 'wikidata_p184', 0.95)
                    """,
                    (a_id, s_id),
                )
                if cur.rowcount > 0:
                    added_edges += 1

        conn.execute(
            """
            INSERT INTO harvest_runs (
                source_repo, query, fetched_count, added_scholars, added_dissertations,
                added_edges, skipped_unverified, status
            ) VALUES ('Wikidata', 'MGP P549/P184 Historical Backbone', ?, ?, 0, ?, 0, 'completed')
            """,
            (len(scholars), added_scholars, added_edges),
        )
        rebuild_fts(conn)

    return {
        "source_repo": "Wikidata",
        "fetched": len(scholars),
        "added_scholars": added_scholars,
        "added_edges": added_edges,
    }


def ingest_wikidata_ancestors(start_qids: List[str], max_depth: int = 12) -> Dict[str, Any]:
    """Trace upward Wikidata P184 doctoral ancestry chains and merge into SQLite."""
    scholars, edges = fetch_wikidata_ancestors_for_qids(start_qids, max_depth=max_depth)
    added_scholars = 0
    added_edges = 0
    with get_conn() as conn:
        qid_to_id: Dict[str, int] = {}
        for s in scholars:
            sid, created = find_or_create_scholar(
                conn,
                s["name"],
                name_zh=s.get("name_zh"),
                mgp_id=s.get("mgp_id"),
                wikidata_id=s.get("wikidata_id"),
                orcid=s.get("orcid"),
                university=s.get("university") or "",
                country=s.get("country") or "",
                year=s.get("year"),
                thesis_title=s.get("thesis_title") or "",
                verification_status="historical_wikidata",
                bio_summary=s.get("bio_summary") or "",
            )
            qid_to_id[s["wikidata_id"]] = sid
            if created:
                added_scholars += 1

        for adv_q, stu_q in edges:
            a_id = qid_to_id.get(adv_q)
            s_id = qid_to_id.get(stu_q)
            if a_id and s_id and a_id != s_id:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO advisor_edges (advisor_id, student_id, source_type, confidence)
                    VALUES (?, ?, 'wikidata_p184', 0.95)
                    """,
                    (a_id, s_id),
                )
                if cur.rowcount > 0:
                    added_edges += 1
        rebuild_fts(conn)
    return {"fetched": len(scholars), "added_scholars": added_scholars, "added_edges": added_edges}


def run_harvest(source: str, query: str = "", limit: int = 35, page: int = 0) -> Dict[str, Any]:
    """Execute a live dissertation harvest from an authoritative repository."""
    repo_label_map = {
        "hal": "HAL/TEL",
        "theses_fr": "theses.fr",
        "mit_dspace": "MIT DSpace",
        "datacite": "DataCite",
        "nyu_courant": "NYU Courant",
    }
    repo_label = repo_label_map.get(source, source)

    try:
        if source == "hal":
            records = fetch_hal_math_theses(query=query, limit=limit, start=page * limit)
        elif source == "theses_fr":
            records = fetch_theses_fr_math(query=query, limit=limit, page=page + 1)
        elif source == "mit_dspace":
            records = fetch_mit_math_theses(query=query, limit=limit, page=page)
        elif source == "datacite":
            records = fetch_datacite_math_dissertations(query=query, limit=limit, page=page + 1)
        elif source == "nyu_courant":
            records = fetch_nyu_courant_phds(query=query, limit=limit)
        else:
            raise ValueError(f"Unsupported source: {source}")
    except Exception as exc:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO harvest_runs (source_repo, query, status, error_message)
                VALUES (?, ?, 'failed', ?)
                """,
                (repo_label, query, str(exc)),
            )
        raise

    added_scholars = 0
    added_diss = 0
    added_edges = 0
    skipped = 0

    with get_conn() as conn:
        for rec in records:
            res = ingest_verified_dissertation(conn, rec, update_fts=False)
            if not res.get("accepted"):
                skipped += 1
            else:
                added_scholars += res.get("new_scholars", 0)
                added_diss += res.get("new_dissertations", 0)
                added_edges += res.get("new_edges", 0)

        conn.execute(
            """
            INSERT INTO harvest_runs (
                source_repo, query, fetched_count, added_scholars, added_dissertations,
                added_edges, skipped_unverified, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed')
            """,
            (repo_label, query or "mathematics", len(records), added_scholars, added_diss, added_edges, skipped),
        )
        rebuild_fts(conn)

    return {
        "source_repo": repo_label,
        "query": query or "mathematics",
        "fetched_count": len(records),
        "added_scholars": added_scholars,
        "added_dissertations": added_diss,
        "added_edges": added_edges,
        "skipped_unverified": skipped,
    }
