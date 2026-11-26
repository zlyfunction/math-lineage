"""Graph algorithms for academic lineage trees, descendant counts, and shortest paths."""

from __future__ import annotations

import sqlite3
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple


def _load_edge_maps(conn: sqlite3.Connection) -> Tuple[Dict[int, List[Tuple[int, str, Optional[int]]]], Dict[int, List[Tuple[int, str, Optional[int]]]]]:
    """Return (advisor_to_students, student_to_advisors) adjacency lists."""
    adv_to_stu: Dict[int, List[Tuple[int, str, Optional[int]]]] = {}
    stu_to_adv: Dict[int, List[Tuple[int, str, Optional[int]]]] = {}
    for row in conn.execute("SELECT advisor_id, student_id, source_type, dissertation_id FROM advisor_edges"):
        a, s, st, did = row["advisor_id"], row["student_id"], row["source_type"], row["dissertation_id"]
        adv_to_stu.setdefault(a, []).append((s, st, did))
        stu_to_adv.setdefault(s, []).append((a, st, did))
    return adv_to_stu, stu_to_adv


def count_descendants(conn: sqlite3.Connection, scholar_id: int) -> Tuple[int, int]:
    """Return (direct_students_count, total_descendants_count) with cycle safety."""
    adv_to_stu, _ = _load_edge_maps(conn)
    direct = [s for s, _, _ in adv_to_stu.get(scholar_id, [])]
    visited: Set[int] = {scholar_id}
    queue: deque[int] = deque()
    for s in direct:
        if s not in visited:
            visited.add(s)
            queue.append(s)
    while queue:
        cur = queue.popleft()
        for nxt, _, _ in adv_to_stu.get(cur, []):
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)
    return len(direct), len(visited) - 1


def compute_all_descendant_counts(conn: sqlite3.Connection) -> Dict[int, Tuple[int, int]]:
    """Compute (direct_students, total_descendants) for all scholars in the DB."""
    adv_to_stu, _ = _load_edge_maps(conn)
    all_ids = [r["id"] for r in conn.execute("SELECT id FROM scholars")]
    result: Dict[int, Tuple[int, int]] = {}
    for sid in all_ids:
        direct = [s for s, _, _ in adv_to_stu.get(sid, [])]
        if not direct:
            result[sid] = (0, 0)
            continue
        visited: Set[int] = {sid}
        q: deque[int] = deque(direct)
        visited.update(direct)
        while q:
            cur = q.popleft()
            for nxt, _, _ in adv_to_stu.get(cur, []):
                if nxt not in visited:
                    visited.add(nxt)
                    q.append(nxt)
        result[sid] = (len(direct), len(visited) - 1)
    return result


def get_lineage_subgraph(
    conn: sqlite3.Connection,
    scholar_id: int,
    ancestor_depth: int = 5,
    descendant_depth: int = 3,
    max_nodes: int = 120,
) -> Dict[str, Any]:
    """Extract a layered ancestor + descendant subgraph centered on scholar_id."""
    adv_to_stu, stu_to_adv = _load_edge_maps(conn)

    # Track level relative to focus scholar: ancestors have negative levels, descendants positive
    levels: Dict[int, int] = {scholar_id: 0}
    edges_seen: Set[Tuple[int, int]] = set()
    edges: List[Dict[str, Any]] = []

    # BFS upward (ancestors)
    q_up: deque[Tuple[int, int]] = deque([(scholar_id, 0)])
    while q_up and len(levels) < max_nodes:
        cur, lvl = q_up.popleft()
        if abs(lvl) >= ancestor_depth:
            continue
        for adv, stype, did in stu_to_adv.get(cur, []):
            if (adv, cur) not in edges_seen:
                edges_seen.add((adv, cur))
                edges.append({
                    "source": adv,
                    "target": cur,
                    "source_type": stype,
                    "dissertation_id": did,
                })
            if adv not in levels and len(levels) < max_nodes:
                levels[adv] = lvl - 1
                q_up.append((adv, lvl - 1))

    # BFS downward (descendants)
    q_down: deque[Tuple[int, int]] = deque([(scholar_id, 0)])
    while q_down and len(levels) < max_nodes:
        cur, lvl = q_down.popleft()
        if lvl >= descendant_depth:
            continue
        # Cap branching per level if huge so visualization stays readable
        children = adv_to_stu.get(cur, [])[:35]
        for stu, stype, did in children:
            if len(levels) >= max_nodes and stu not in levels:
                continue
            if (cur, stu) not in edges_seen:
                edges_seen.add((cur, stu))
                edges.append({
                    "source": cur,
                    "target": stu,
                    "source_type": stype,
                    "dissertation_id": did,
                })
            if stu not in levels:
                levels[stu] = lvl + 1
                q_down.append((stu, lvl + 1))

    node_ids = list(levels.keys())
    if not node_ids:
        return {"focus_id": scholar_id, "nodes": [], "edges": []}

    placeholders = ",".join("?" for _ in node_ids)
    rows = conn.execute(
        f"""
        SELECT s.id, s.name, s.name_zh, s.university, s.country, s.year,
               s.degree, s.thesis_title, s.verification_status, s.mgp_id,
               (SELECT COUNT(*) FROM dissertations d WHERE d.scholar_id = s.id) AS diss_count
        FROM scholars s
        WHERE s.id IN ({placeholders})
        """,
        node_ids,
    ).fetchall()

    # Keep only edges whose endpoints are both in node_ids
    valid_set = set(node_ids)
    filtered_edges = [e for e in edges if e["source"] in valid_set and e["target"] in valid_set]

    nodes = []
    for r in rows:
        sid = r["id"]
        nodes.append({
            "id": sid,
            "name": r["name"],
            "name_zh": r["name_zh"],
            "university": r["university"],
            "country": r["country"],
            "year": r["year"],
            "degree": r["degree"],
            "thesis_title": r["thesis_title"],
            "verification_status": r["verification_status"],
            "mgp_id": r["mgp_id"],
            "has_dissertation_proof": r["diss_count"] > 0,
            "level": levels[sid],
            "is_focus": sid == scholar_id,
            "student_count": len(adv_to_stu.get(sid, [])),
            "advisor_count": len(stu_to_adv.get(sid, [])),
        })

    return {
        "focus_id": scholar_id,
        "nodes": nodes,
        "edges": filtered_edges,
    }


def find_shortest_path(conn: sqlite3.Connection, from_id: int, to_id: int) -> Dict[str, Any]:
    """Find shortest undirected academic lineage path between two scholars."""
    if from_id == to_id:
        row = conn.execute("SELECT * FROM scholars WHERE id = ?", (from_id,)).fetchone()
        return {
            "found": row is not None,
            "distance": 0,
            "nodes": [dict(row)] if row else [],
            "steps": [],
        }

    adv_to_stu, stu_to_adv = _load_edge_maps(conn)
    # Undirected adjacency with direction metadata
    adj: Dict[int, List[Tuple[int, str, str, Optional[int]]]] = {}
    for a, lst in adv_to_stu.items():
        for s, stype, did in lst:
            adj.setdefault(a, []).append((s, "advised", stype, did))
            adj.setdefault(s, []).append((a, "advised_by", stype, did))

    visited: Set[int] = {from_id}
    parent: Dict[int, Tuple[int, str, str, Optional[int]]] = {}
    q: deque[int] = deque([from_id])
    found = False

    while q:
        cur = q.popleft()
        if cur == to_id:
            found = True
            break
        for nxt, direction, stype, did in adj.get(cur, []):
            if nxt not in visited:
                visited.add(nxt)
                parent[nxt] = (cur, direction, stype, did)
                if nxt == to_id:
                    found = True
                    q.clear()
                    break
                q.append(nxt)

    if not found:
        return {"found": False, "distance": None, "nodes": [], "steps": []}

    # Reconstruct path
    path_ids: List[int] = []
    steps_rev: List[Dict[str, Any]] = []
    cur = to_id
    while cur != from_id:
        path_ids.append(cur)
        prev, direction, stype, did = parent[cur]
        steps_rev.append({
            "from_id": prev,
            "to_id": cur,
            "relation": direction,  # 'advised' or 'advised_by'
            "source_type": stype,
            "dissertation_id": did,
        })
        cur = prev
    path_ids.append(from_id)
    path_ids.reverse()
    steps = list(reversed(steps_rev))

    placeholders = ",".join("?" for _ in path_ids)
    rows = {
        r["id"]: dict(r)
        for r in conn.execute(
            f"""
            SELECT s.id, s.name, s.name_zh, s.university, s.country, s.year,
                   s.degree, s.thesis_title, s.verification_status, s.mgp_id,
                   (SELECT d.landing_url FROM dissertations d WHERE d.scholar_id = s.id LIMIT 1) AS dissertation_url
            FROM scholars s WHERE s.id IN ({placeholders})
            """,
            path_ids,
        ).fetchall()
    }

    # Enrich dissertation link on each step if available
    diss_ids = [st["dissertation_id"] for st in steps if st["dissertation_id"]]
    diss_map: Dict[int, Dict[str, Any]] = {}
    if diss_ids:
        d_ph = ",".join("?" for _ in diss_ids)
        for dr in conn.execute(
            f"SELECT id, title, source_repo, landing_url, pdf_url, doi FROM dissertations WHERE id IN ({d_ph})",
            diss_ids,
        ).fetchall():
            diss_map[dr["id"]] = dict(dr)

    for st in steps:
        if st["dissertation_id"] and st["dissertation_id"] in diss_map:
            st["dissertation"] = diss_map[st["dissertation_id"]]
        else:
            st["dissertation"] = None

    return {
        "found": True,
        "distance": len(steps),
        "nodes": [rows[pid] for pid in path_ids if pid in rows],
        "steps": steps,
    }
