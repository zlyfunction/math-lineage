"""FastAPI backend for MathLineage — Open & Dissertation-Verified Mathematics Genealogy."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import PROJECT_ROOT, get_conn, init_db, rebuild_fts
from .graph import compute_all_descendant_counts, count_descendants, find_shortest_path, get_lineage_subgraph
from .ingest import ingest_verified_dissertation, run_harvest
from .models import (
    HarvestRequest,
    LiveRepoSearchRequest,
    ReviewActionRequest,
    SubmissionCreateRequest,
    VerifyDissertationRequest,
)
from .verifier import search_live_repositories, verify_dissertation_identifier

init_db()

app = FastAPI(
    title="MathLineage API",
    description="Rebuilt Mathematics Genealogy platform strictly backed by verifiable doctoral dissertations.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _fts_query(raw: str) -> str:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", raw.strip())
    if not tokens:
        return ""
    return " AND ".join(f'"{t}"*' for t in tokens[:8])


@app.get("/api/stats")
def get_stats() -> Dict[str, Any]:
    with get_conn() as conn:
        total_scholars = conn.execute("SELECT COUNT(*) FROM scholars").fetchone()[0]
        verified_scholars = conn.execute(
            "SELECT COUNT(*) FROM scholars WHERE verification_status = 'verified_dissertation'"
        ).fetchone()[0]
        historical_scholars = conn.execute(
            "SELECT COUNT(*) FROM scholars WHERE verification_status = 'historical_wikidata'"
        ).fetchone()[0]
        total_dissertations = conn.execute("SELECT COUNT(*) FROM dissertations").fetchone()[0]
        total_edges = conn.execute("SELECT COUNT(*) FROM advisor_edges").fetchone()[0]
        verified_edges = conn.execute(
            "SELECT COUNT(*) FROM advisor_edges WHERE source_type = 'dissertation_verified'"
        ).fetchone()[0]
        pending_submissions = conn.execute(
            "SELECT COUNT(*) FROM submissions WHERE status = 'pending'"
        ).fetchone()[0]

        repo_breakdown = [
            {"source_repo": r["source_repo"], "count": r["cnt"]}
            for r in conn.execute(
                "SELECT source_repo, COUNT(*) AS cnt FROM dissertations GROUP BY source_repo ORDER BY cnt DESC"
            ).fetchall()
        ]
        recent_years = [
            {"year": r["year"], "count": r["cnt"]}
            for r in conn.execute(
                """
                SELECT year, COUNT(*) AS cnt FROM dissertations
                WHERE year IS NOT NULL AND year >= 2015
                GROUP BY year ORDER BY year ASC
                """
            ).fetchall()
        ]
        featured = [
            dict(r)
            for r in conn.execute(
                """
                SELECT s.id, s.name, s.name_zh, s.university, s.year, s.verification_status, s.mgp_id,
                       (SELECT COUNT(*) FROM advisor_edges e WHERE e.advisor_id = s.id) AS direct_students,
                       (SELECT d.source_repo FROM dissertations d WHERE d.scholar_id = s.id LIMIT 1) AS source_repo
                FROM scholars s
                WHERE s.wikidata_id IN ('Q6722', 'Q7604', 'Q41585', 'Q7099', 'Q81082', 'Q122992', 'Q221265', 'Q102116446')
                   OR s.name = 'Leyi Zhu'
                ORDER BY CASE WHEN s.name = 'Leyi Zhu' THEN 0 ELSE 1 END, direct_students DESC
                LIMIT 9
                """
            ).fetchall()
        ]

    return {
        "total_scholars": total_scholars,
        "verified_scholars": verified_scholars,
        "historical_scholars": historical_scholars,
        "total_dissertations": total_dissertations,
        "total_edges": total_edges,
        "verified_edges": verified_edges,
        "pending_submissions": pending_submissions,
        "repo_breakdown": repo_breakdown,
        "recent_years": recent_years,
        "featured_scholars": featured,
    }


@app.get("/api/scholars")
def search_scholars(
    q: str = Query("", description="Search name, university, thesis title, MGP ID"),
    status: str = Query("all", description="all | verified_dissertation | historical_wikidata | advisor_inferred"),
    repo: str = Query("all", description="all | MIT DSpace | HAL/TEL | theses.fr | DataCite"),
    year_from: Optional[int] = Query(None),
    year_to: Optional[int] = Query(None),
    sort: str = Query("relevance", description="relevance | year_desc | year_asc | students_desc | name_asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
) -> Dict[str, Any]:
    with get_conn() as conn:
        where_clauses: List[str] = ["1=1"]
        params: List[Any] = []
        join_fts = ""

        fts_expr = _fts_query(q)
        if fts_expr:
            join_fts = "JOIN scholars_fts f ON f.scholar_id = s.id"
            where_clauses.append("scholars_fts MATCH ?")
            params.append(fts_expr)

        if status != "all":
            where_clauses.append("s.verification_status = ?")
            params.append(status)

        if repo != "all":
            where_clauses.append(
                "EXISTS (SELECT 1 FROM dissertations d WHERE d.scholar_id = s.id AND d.source_repo = ?)"
            )
            params.append(repo)

        if year_from is not None:
            where_clauses.append("s.year >= ?")
            params.append(year_from)
        if year_to is not None:
            where_clauses.append("s.year <= ?")
            params.append(year_to)

        where_sql = " AND ".join(where_clauses)

        total = conn.execute(
            f"SELECT COUNT(*) FROM scholars s {join_fts} WHERE {where_sql}",
            params,
        ).fetchone()[0]

        if fts_expr:
            relevance_sql = (
                "CASE WHEN lower(s.name) LIKE lower(?) OR lower(COALESCE(s.name_zh,'')) LIKE lower(?) THEN 0 ELSE 1 END, "
                "bm25(scholars_fts, 0.0, 12.0, 12.0, 2.5, 1.0, 1.0, 8.0, 1.0, 1.0), "
                "CASE s.verification_status WHEN 'verified_dissertation' THEN 0 WHEN 'historical_wikidata' THEN 1 ELSE 2 END, "
                "COALESCE(s.year, 0) DESC"
            )
            like_param = f"%{q.strip()}%"
        else:
            relevance_sql = (
                "CASE s.verification_status WHEN 'verified_dissertation' THEN 0 WHEN 'historical_wikidata' THEN 1 ELSE 2 END, "
                "COALESCE(s.year, 0) DESC, s.id ASC"
            )
            like_param = None

        order_map = {
            "relevance": relevance_sql,
            "year_desc": "s.year IS NULL, s.year DESC, s.name ASC",
            "year_asc": "s.year IS NULL, s.year ASC, s.name ASC",
            "students_desc": "direct_students DESC, COALESCE(s.year, 0) DESC",
            "name_asc": "s.name ASC",
        }
        order_sql = order_map.get(sort, order_map["relevance"])

        offset = (page - 1) * page_size
        query_params = [*params]
        if sort == "relevance" and like_param is not None:
            query_params.extend([like_param, like_param])
        query_params.extend([page_size, offset])

        rows = conn.execute(
            f"""
            SELECT s.id, s.name, s.name_zh, s.degree, s.university, s.country, s.year,
                   s.thesis_title, s.thesis_title_en, s.msc_code, s.mgp_id, s.wikidata_id,
                   s.verification_status,
                   (SELECT COUNT(*) FROM advisor_edges e WHERE e.advisor_id = s.id) AS direct_students,
                   (SELECT COUNT(*) FROM advisor_edges e WHERE e.student_id = s.id) AS advisor_count,
                   (SELECT d.source_repo FROM dissertations d WHERE d.scholar_id = s.id LIMIT 1) AS source_repo,
                   (SELECT d.landing_url FROM dissertations d WHERE d.scholar_id = s.id LIMIT 1) AS dissertation_url,
                   (SELECT d.pdf_url FROM dissertations d WHERE d.scholar_id = s.id LIMIT 1) AS pdf_url,
                   (SELECT d.doi FROM dissertations d WHERE d.scholar_id = s.id LIMIT 1) AS doi
            FROM scholars s
            {join_fts}
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            query_params,
        ).fetchall()

        # Fetch advisor names for the displayed page
        scholar_ids = [r["id"] for r in rows]
        advisors_map: Dict[int, List[Dict[str, Any]]] = {sid: [] for sid in scholar_ids}
        if scholar_ids:
            ph = ",".join("?" for _ in scholar_ids)
            for ar in conn.execute(
                f"""
                SELECT e.student_id, a.id, a.name
                FROM advisor_edges e
                JOIN scholars a ON a.id = e.advisor_id
                WHERE e.student_id IN ({ph})
                """,
                scholar_ids,
            ).fetchall():
                advisors_map[ar["student_id"]].append({"id": ar["id"], "name": ar["name"]})

        items = []
        for r in rows:
            d = dict(r)
            d["advisors"] = advisors_map.get(r["id"], [])
            items.append(d)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@app.get("/api/scholars/autocomplete")
def autocomplete_scholars(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=20)) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        fts_expr = _fts_query(q)
        if not fts_expr:
            return []
        rows = conn.execute(
            """
            SELECT s.id, s.name, s.name_zh, s.university, s.year, s.verification_status,
                   (SELECT COUNT(*) FROM advisor_edges e WHERE e.advisor_id = s.id OR e.student_id = s.id) AS degree_links
            FROM scholars s
            JOIN scholars_fts f ON f.scholar_id = s.id
            WHERE scholars_fts MATCH ?
            ORDER BY degree_links DESC, s.year DESC
            LIMIT ?
            """,
            (fts_expr, limit),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/scholars/{scholar_id}")
def get_scholar_detail(scholar_id: int) -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM scholars WHERE id = ?", (scholar_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Scholar not found")

        scholar = dict(row)

        # Dissertations (provenance evidence)
        dissertations = []
        for dr in conn.execute(
            "SELECT * FROM dissertations WHERE scholar_id = ? ORDER BY verified_at DESC",
            (scholar_id,),
        ).fetchall():
            dd = dict(dr)
            try:
                dd["advisors_raw"] = json.loads(dd["advisors_raw"] or "[]")
            except Exception:
                dd["advisors_raw"] = []
            try:
                dd["raw_metadata"] = json.loads(dd["raw_metadata_json"] or "{}")
            except Exception:
                dd["raw_metadata"] = {}
            dissertations.append(dd)

        # Advisors
        advisors = [
            dict(r)
            for r in conn.execute(
                """
                SELECT s.id, s.name, s.name_zh, s.university, s.year, s.verification_status, s.mgp_id,
                       e.source_type, e.dissertation_id
                FROM advisor_edges e
                JOIN scholars s ON s.id = e.advisor_id
                WHERE e.student_id = ?
                ORDER BY s.year ASC, s.name ASC
                """,
                (scholar_id,),
            ).fetchall()
        ]

        # Students + each student's descendant count
        desc_counts = compute_all_descendant_counts(conn)
        students_rows = conn.execute(
            """
            SELECT s.id, s.name, s.name_zh, s.university, s.country, s.year, s.thesis_title,
                   s.verification_status, s.mgp_id, e.source_type,
                   (SELECT d.landing_url FROM dissertations d WHERE d.scholar_id = s.id LIMIT 1) AS dissertation_url,
                   (SELECT d.source_repo FROM dissertations d WHERE d.scholar_id = s.id LIMIT 1) AS source_repo
            FROM advisor_edges e
            JOIN scholars s ON s.id = e.student_id
            WHERE e.advisor_id = ?
            ORDER BY s.year IS NULL, s.year DESC, s.name ASC
            """,
            (scholar_id,),
        ).fetchall()
        students = []
        for sr in students_rows:
            sd = dict(sr)
            st_direct, st_total = desc_counts.get(sr["id"], (0, 0))
            sd["direct_students"] = st_direct
            sd["total_descendants"] = st_total
            students.append(sd)

        direct_cnt, total_desc_cnt = desc_counts.get(scholar_id, (0, 0))

    return {
        "scholar": scholar,
        "dissertations": dissertations,
        "advisors": advisors,
        "students": students,
        "direct_students_count": direct_cnt,
        "total_descendants_count": total_desc_cnt,
    }


@app.get("/api/scholars/{scholar_id}/lineage")
def get_scholar_lineage(
    scholar_id: int,
    ancestor_depth: int = Query(5, ge=1, le=12),
    descendant_depth: int = Query(3, ge=1, le=8),
) -> Dict[str, Any]:
    with get_conn() as conn:
        exists = conn.execute("SELECT id FROM scholars WHERE id = ?", (scholar_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Scholar not found")
        return get_lineage_subgraph(
            conn,
            scholar_id,
            ancestor_depth=ancestor_depth,
            descendant_depth=descendant_depth,
        )


@app.get("/api/path")
def get_shortest_path(from_id: int = Query(...), to_id: int = Query(...)) -> Dict[str, Any]:
    with get_conn() as conn:
        return find_shortest_path(conn, from_id, to_id)


@app.post("/api/verify-dissertation")
async def api_verify_dissertation(req: VerifyDissertationRequest) -> Dict[str, Any]:
    def _run() -> Optional[Dict[str, Any]]:
        with get_conn() as conn:
            return verify_dissertation_identifier(conn, req.identifier, req.source_hint)

    res = await asyncio.to_thread(_run)
    if not res:
        raise HTTPException(
            status_code=404,
            detail="Could not verify this identifier in DataCite, HAL/TEL, theses.fr, or MIT DSpace. Please check the DOI / HAL ID / theses.fr ID / MIT Handle.",
        )
    return res


@app.post("/api/verify-dissertation/search")
async def api_search_live_repos(req: LiveRepoSearchRequest) -> Dict[str, Any]:
    def _run() -> List[Dict[str, Any]]:
        with get_conn() as conn:
            return search_live_repositories(conn, req.query, req.source, req.limit)

    items = await asyncio.to_thread(_run)
    return {"query": req.query, "source": req.source, "count": len(items), "items": items}


@app.get("/api/submissions")
def list_submissions(status: str = Query("all", pattern="^(all|pending|approved|rejected)$")) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        if status == "all":
            rows = conn.execute("SELECT * FROM submissions ORDER BY created_at DESC, id DESC LIMIT 100").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM submissions WHERE status = ? ORDER BY created_at DESC, id DESC LIMIT 100",
                (status,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["advisors"] = json.loads(d["advisors_json"] or "[]")
            except Exception:
                d["advisors"] = []
            out.append(d)
        return out


@app.post("/api/submissions")
def create_submission(req: SubmissionCreateRequest) -> Dict[str, Any]:
    if not req.landing_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="A verifiable http(s) dissertation URL is mandatory.")
    if not req.advisors:
        raise HTTPException(status_code=400, detail="At least one dissertation advisor is mandatory.")

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO submissions (
                status, scholar_name, advisors_json, university, country, degree, year,
                thesis_title, thesis_title_en, msc_code,
                source_repo, source_record_id, doi, landing_url, pdf_url,
                raw_metadata_json, submitter_note
            ) VALUES ('pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.scholar_name.strip(),
                json.dumps([a.strip() for a in req.advisors if a.strip()], ensure_ascii=False),
                req.university.strip(),
                req.country.strip(),
                req.degree.strip() or "Ph.D.",
                req.year,
                req.thesis_title.strip(),
                req.thesis_title_en.strip(),
                req.msc_code.strip(),
                req.source_repo.strip(),
                req.source_record_id.strip(),
                req.doi.strip(),
                req.landing_url.strip(),
                req.pdf_url.strip(),
                req.raw_metadata_json,
                req.submitter_note.strip(),
            ),
        )
        sub_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,)).fetchone()
        d = dict(row)
        d["advisors"] = json.loads(d["advisors_json"] or "[]")
        return d


@app.post("/api/submissions/{submission_id}/review")
def review_submission(submission_id: int, req: ReviewActionRequest) -> Dict[str, Any]:
    with get_conn() as conn:
        sub = conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")
        if sub["status"] != "pending":
            raise HTTPException(status_code=400, detail=f"Submission already {sub['status']}")

        if req.action == "reject":
            conn.execute(
                """
                UPDATE submissions SET status = 'rejected', review_note = ?, reviewed_at = datetime('now')
                WHERE id = ?
                """,
                (req.review_note, submission_id),
            )
            return {"id": submission_id, "status": "rejected"}

        # Approve: commit into scholars + dissertations + advisor_edges!
        advisors = json.loads(sub["advisors_json"] or "[]")
        ingest_res = ingest_verified_dissertation(
            conn,
            {
                "scholar_name": sub["scholar_name"],
                "advisors": advisors,
                "university": sub["university"],
                "country": sub["country"],
                "degree": sub["degree"],
                "year": sub["year"],
                "thesis_title": sub["thesis_title"],
                "thesis_title_en": sub["thesis_title_en"],
                "msc_code": sub["msc_code"],
                "source_repo": sub["source_repo"],
                "source_record_id": sub["source_record_id"],
                "doi": sub["doi"],
                "landing_url": sub["landing_url"],
                "pdf_url": sub["pdf_url"],
                "raw_metadata": sub["raw_metadata_json"],
            },
            update_fts=True,
        )
        if not ingest_res.get("accepted"):
            raise HTTPException(status_code=400, detail=ingest_res.get("reason", "Validation failed"))

        conn.execute(
            """
            UPDATE submissions
            SET status = 'approved', review_note = ?, matched_scholar_id = ?, reviewed_at = datetime('now')
            WHERE id = ?
            """,
            (req.review_note, ingest_res["scholar_id"], submission_id),
        )
        return {
            "id": submission_id,
            "status": "approved",
            "scholar_id": ingest_res["scholar_id"],
            "dissertation_id": ingest_res["dissertation_id"],
        }


@app.get("/api/harvest/runs")
def list_harvest_runs() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM harvest_runs ORDER BY id DESC LIMIT 40").fetchall()
        return [dict(r) for r in rows]


@app.post("/api/harvest")
async def trigger_harvest(req: HarvestRequest) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(run_harvest, req.source, req.query, req.limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Harvest from {req.source} failed: {exc}")


# Serve built Vite SPA if present
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
