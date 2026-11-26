"""SQLite database initialization, schema, and FTS5 search helpers."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = Path(os.environ.get("MATH_GENEALOGY_DB", DATA_DIR / "genealogy.db"))


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS scholars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_zh TEXT,
    normalized_name TEXT NOT NULL,
    given_name TEXT DEFAULT '',
    family_name TEXT DEFAULT '',
    mgp_id TEXT UNIQUE,
    wikidata_id TEXT UNIQUE,
    orcid TEXT,
    idref_ppn TEXT,
    degree TEXT DEFAULT 'Ph.D.',
    university TEXT DEFAULT '',
    country TEXT DEFAULT '',
    year INTEGER,
    thesis_title TEXT DEFAULT '',
    thesis_title_en TEXT DEFAULT '',
    msc_code TEXT DEFAULT '',
    msc_label TEXT DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT 'historical_wikidata',
    -- 'verified_dissertation' | 'historical_wikidata' | 'advisor_inferred'
    bio_summary TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scholars_norm ON scholars(normalized_name);
CREATE INDEX IF NOT EXISTS idx_scholars_year ON scholars(year);
CREATE INDEX IF NOT EXISTS idx_scholars_univ ON scholars(university);
CREATE INDEX IF NOT EXISTS idx_scholars_status ON scholars(verification_status);
CREATE INDEX IF NOT EXISTS idx_scholars_mgp ON scholars(mgp_id);
CREATE INDEX IF NOT EXISTS idx_scholars_wd ON scholars(wikidata_id);

CREATE TABLE IF NOT EXISTS dissertations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scholar_id INTEGER NOT NULL REFERENCES scholars(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    title_en TEXT DEFAULT '',
    author_raw TEXT NOT NULL,
    advisors_raw TEXT NOT NULL DEFAULT '[]', -- JSON list of raw advisor strings
    institution TEXT DEFAULT '',
    department TEXT DEFAULT '',
    degree TEXT DEFAULT 'Ph.D.',
    year INTEGER,
    source_repo TEXT NOT NULL,               -- 'MIT DSpace' | 'HAL/TEL' | 'theses.fr' | 'DataCite' | 'Wikidata'
    source_record_id TEXT NOT NULL,
    doi TEXT DEFAULT '',
    landing_url TEXT NOT NULL,
    pdf_url TEXT DEFAULT '',
    raw_metadata_json TEXT NOT NULL DEFAULT '{}',
    verified_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_repo, source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_diss_scholar ON dissertations(scholar_id);
CREATE INDEX IF NOT EXISTS idx_diss_repo ON dissertations(source_repo);
CREATE INDEX IF NOT EXISTS idx_diss_doi ON dissertations(doi);

CREATE TABLE IF NOT EXISTS advisor_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    advisor_id INTEGER NOT NULL REFERENCES scholars(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES scholars(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL DEFAULT 'dissertation_verified',
    -- 'dissertation_verified' | 'wikidata_p184'
    dissertation_id INTEGER REFERENCES dissertations(id) ON DELETE SET NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(advisor_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_edges_advisor ON advisor_edges(advisor_id);
CREATE INDEX IF NOT EXISTS idx_edges_student ON advisor_edges(student_id);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'approved' | 'rejected'
    scholar_name TEXT NOT NULL,
    advisors_json TEXT NOT NULL DEFAULT '[]',
    university TEXT DEFAULT '',
    country TEXT DEFAULT '',
    degree TEXT DEFAULT 'Ph.D.',
    year INTEGER,
    thesis_title TEXT NOT NULL,
    thesis_title_en TEXT DEFAULT '',
    msc_code TEXT DEFAULT '',
    source_repo TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    doi TEXT DEFAULT '',
    landing_url TEXT NOT NULL,
    pdf_url TEXT DEFAULT '',
    raw_metadata_json TEXT NOT NULL DEFAULT '{}',
    submitter_note TEXT DEFAULT '',
    review_note TEXT DEFAULT '',
    matched_scholar_id INTEGER REFERENCES scholars(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);

CREATE TABLE IF NOT EXISTS harvest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_repo TEXT NOT NULL,
    query TEXT DEFAULT '',
    fetched_count INTEGER NOT NULL DEFAULT 0,
    added_scholars INTEGER NOT NULL DEFAULT 0,
    added_dissertations INTEGER NOT NULL DEFAULT 0,
    added_edges INTEGER NOT NULL DEFAULT 0,
    skipped_unverified INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    error_message TEXT DEFAULT '',
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS scholars_fts USING fts5(
    scholar_id UNINDEXED,
    name,
    name_zh,
    university,
    thesis_title,
    thesis_title_en,
    mgp_id,
    country,
    msc_label,
    tokenize='unicode61 remove_diacritics 2'
);
"""


def init_db(db_path: Path | None = None) -> Path:
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    return path


@contextmanager
def get_conn(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS5 search index from the scholars table."""
    conn.execute("DELETE FROM scholars_fts;")
    conn.execute(
        """
        INSERT INTO scholars_fts(
            scholar_id, name, name_zh, university, thesis_title,
            thesis_title_en, mgp_id, country, msc_label
        )
        SELECT
            id,
            COALESCE(name, ''),
            COALESCE(name_zh, ''),
            COALESCE(university, ''),
            COALESCE(thesis_title, ''),
            COALESCE(thesis_title_en, ''),
            COALESCE(mgp_id, ''),
            COALESCE(country, ''),
            COALESCE(msc_label, '')
        FROM scholars;
        """
    )


def upsert_fts_row(conn: sqlite3.Connection, scholar_id: int) -> None:
    conn.execute("DELETE FROM scholars_fts WHERE scholar_id = ?;", (scholar_id,))
    conn.execute(
        """
        INSERT INTO scholars_fts(
            scholar_id, name, name_zh, university, thesis_title,
            thesis_title_en, mgp_id, country, msc_label
        )
        SELECT
            id,
            COALESCE(name, ''),
            COALESCE(name_zh, ''),
            COALESCE(university, ''),
            COALESCE(thesis_title, ''),
            COALESCE(thesis_title_en, ''),
            COALESCE(mgp_id, ''),
            COALESCE(country, ''),
            COALESCE(msc_label, '')
        FROM scholars WHERE id = ?;
        """,
        (scholar_id,),
    )
