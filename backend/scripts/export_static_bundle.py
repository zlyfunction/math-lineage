"""Export SQLite genealogy database into a compact JSON bundle for GitHub Pages / static deployment."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import PROJECT_ROOT, get_conn, init_db


def export_bundle(output_path: Path | None = None) -> Path:
    init_db()
    out = output_path or (PROJECT_ROOT / "frontend" / "public" / "data" / "genealogy-bundle.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    with get_conn() as conn:
        scholars = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, name, name_zh, normalized_name, degree, university, country, year,
                       thesis_title, thesis_title_en, msc_code, mgp_id, wikidata_id, orcid,
                       verification_status, bio_summary
                FROM scholars
                ORDER BY id ASC
                """
            ).fetchall()
        ]

        dissertations = []
        for r in conn.execute(
            """
            SELECT id, scholar_id, title, title_en, author_raw, advisors_raw,
                   institution, department, degree, year, source_repo, source_record_id,
                   doi, landing_url, pdf_url, raw_metadata_json, verified_at
            FROM dissertations
            ORDER BY id ASC
            """
        ).fetchall():
            d = dict(r)
            try:
                d["advisors_raw"] = json.loads(d["advisors_raw"] or "[]")
            except Exception:
                d["advisors_raw"] = []
            # Keep compact metadata excerpt for transparency without bloating bundle size
            try:
                raw_obj = json.loads(d.pop("raw_metadata_json", "{}") or "{}")
                compact_raw = {}
                for k in (
                    "doi", "handle", "halId_s", "id", "publisher", "registry_url", "pdf_url",
                    "verification_method", "pdf_title_page_excerpt", "publicationYear",
                    "etabSoutenanceN", "dateSoutenance", "director_s", "advisor",
                ):
                    if k in raw_obj and raw_obj[k]:
                        val = raw_obj[k]
                        compact_raw[k] = val[:700] if isinstance(val, str) else val
                d["raw_metadata"] = compact_raw
            except Exception:
                d["raw_metadata"] = {}
            dissertations.append(d)

        edges = [
            dict(r)
            for r in conn.execute(
                "SELECT advisor_id, student_id, source_type, dissertation_id FROM advisor_edges ORDER BY id ASC"
            ).fetchall()
        ]

        harvest_runs = [
            dict(r)
            for r in conn.execute(
                """
                SELECT id, source_repo, query, fetched_count, added_scholars,
                       added_dissertations, added_edges, skipped_unverified, status, finished_at
                FROM harvest_runs
                ORDER BY id DESC LIMIT 30
                """
            ).fetchall()
        ]

    bundle = {
        "version": 1,
        "scholars": scholars,
        "dissertations": dissertations,
        "edges": edges,
        "harvest_runs": harvest_runs,
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = out.stat().st_size / 1024
    print(
        f"Exported static bundle to {out} ({size_kb:.1f} KB): "
        f"{len(scholars)} scholars, {len(dissertations)} dissertations, {len(edges)} edges"
    )
    return out


if __name__ == "__main__":
    export_bundle()
