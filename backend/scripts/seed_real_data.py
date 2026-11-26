"""Bootstrap SQLite database with 100% real data from Wikidata + 4 open dissertation repositories."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import get_conn, init_db
from app.ingest import ingest_wikidata_backbone, run_harvest


def main() -> None:
    db_path = init_db()
    print(f"[1/6] Initialized SQLite database at {db_path}")

    print("[2/6] Fetching historical Mathematics Genealogy backbone from Wikidata (P549/P184/P185)...")
    wd_res = ingest_wikidata_backbone(max_scholars=360)
    print("     ", wd_res)

    # Harvest real, verified PhD dissertations from 4 distinct institutional/national APIs
    harvest_jobs = [
        ("hal", "", 60, 0),
        ("hal", "Villani OR Lions OR Brezis OR Tao OR geometry OR PDE", 30, 0),
        ("theses_fr", "", 50, 0),
        ("mit_dspace", "", 40, 0),
        ("mit_dspace", "Strang OR Berger OR Sipser OR Mrowka OR Edelman", 25, 0),
        ("datacite", "mathematics", 50, 0),
        ("datacite", "topology OR algebra OR probability OR geometry", 35, 0),
    ]

    for idx, (src, q, lim, pg) in enumerate(harvest_jobs, start=3):
        label = f"{src} ({q or 'recent math'})"
        print(f"[{idx}/9] Harvesting verified dissertations from {label}...")
        try:
            res = run_harvest(src, query=q, limit=lim, page=pg)
            print("     ", res)
        except Exception as exc:
            print(f"     WARNING: {label} error: {exc}")

    # Summary stats
    with get_conn() as conn:
        scholars = conn.execute("SELECT COUNT(*) FROM scholars").fetchone()[0]
        verified = conn.execute("SELECT COUNT(*) FROM scholars WHERE verification_status = 'verified_dissertation'").fetchone()[0]
        diss = conn.execute("SELECT COUNT(*) FROM dissertations").fetchone()[0]
        edges = conn.execute("SELECT COUNT(*) FROM advisor_edges").fetchone()[0]
        by_repo = conn.execute("SELECT source_repo, COUNT(*) FROM dissertations GROUP BY source_repo").fetchall()
        print("\n=== FINAL DATABASE SUMMARY ===")
        print(f"Total Scholars: {scholars}")
        print(f"Dissertation-Verified Scholars: {verified}")
        print(f"Verified Dissertations: {diss}")
        print(f"Advisor-Student Edges: {edges}")
        for repo, cnt in by_repo:
            print(f"  - {repo}: {cnt} dissertations")


if __name__ == "__main__":
    main()
