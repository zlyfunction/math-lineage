"""Politely sync complete upward advisor chains from genealogy.math.ndsu.nodak.edu
so no MGP-linked scholar is ever left with truncated or missing advisors.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.mgp import search_mgp_by_name
from app.database import get_conn
from app.ingest import ingest_mgp_sync
from app.normalizer import normalize_key


def main() -> None:
    with get_conn() as conn:
        # 1. All existing MGP scholars in DB that currently have 0 advisors
        dangling_mgp = [
            r["mgp_id"]
            for r in conn.execute(
                """
                SELECT s.mgp_id FROM scholars s
                WHERE s.mgp_id IS NOT NULL AND s.mgp_id != ''
                  AND NOT EXISTS (SELECT 1 FROM advisor_edges e WHERE e.student_id = s.id)
                """
            ).fetchall()
        ]

    print(f"[1] Found {len(dangling_mgp)} existing MGP scholars with 0 advisors.", flush=True)

    # 2. Core landmark & graphics/geometry/courant/MIT lineages to sync completely (including students)
    hub_ids = [
        "69407",   # Denis N. Zorin
        "73621",   # Peter Schröder
        "70976",   # Patrick Matthew Hanrahan
        "76722",   # Alan Howard Barr
        "275795",  # Daniele Panozzo
        "322238",  # Enrico Puppo
        "7298",    # David Hilbert
        "18231",   # Carl Friedrich Gauss
        "38586",   # Leonhard Euler
    ]

    all_seeds = list(dict.fromkeys(hub_ids + dangling_mgp))
    print(f"[2] Crawling complete upward MGP ancestry from {len(all_seeds)} direct MGP IDs...", flush=True)
    res = ingest_mgp_sync(
        all_seeds,
        include_students_for={"69407", "275795", "70976"},
        max_pages=240,
    )
    print("    Sync result:", res, flush=True)

    # Verify Pat Hanrahan, Daniele Panozzo, Denis Zorin, and Leyi Zhu!
    with get_conn() as conn:
        for nm in ["Pat Hanrahan", "Patrick Matthew Hanrahan", "Daniele Panozzo", "Denis Zorin", "Leyi Zhu"]:
            rows = conn.execute(
                "SELECT id, name, mgp_id, university, year, thesis_title FROM scholars WHERE name LIKE ?",
                (f"%{nm}%",),
            ).fetchall()
            for r in rows:
                advs = [
                    x["name"]
                    for x in conn.execute(
                        "SELECT a.name FROM advisor_edges e JOIN scholars a ON a.id = e.advisor_id WHERE e.student_id = ?",
                        (r["id"],),
                    ).fetchall()
                ]
                stus = conn.execute(
                    "SELECT COUNT(*) FROM advisor_edges WHERE advisor_id = ?", (r["id"],)
                ).fetchone()[0]
                print(f"    CHECK #{r['id']} {r['name']} (MGP #{r['mgp_id']}): advisors={advs}, students={stus}")


if __name__ == "__main__":
    main()
