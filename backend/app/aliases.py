"""The learning loop.

When a salesperson corrects a line, that correction is the single most valuable
piece of data the system will ever see: a human who knows the product told us
that *this wording* means *this SKU*. Storing it turns a one-off fix into a
capability the next quote inherits.

Kept in SQLite rather than a vector store on purpose. The lookup is exact on
normalised text, which is boring, auditable, and covers the case that actually
recurs: the same customer writing the same odd phrase every month.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

from .catalog import normalize

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "aliases.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS aliases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase_norm  TEXT NOT NULL,
    phrase_raw   TEXT NOT NULL,
    sku          TEXT NOT NULL,
    wrong_sku    TEXT,
    hits         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(phrase_norm, sku)
);
CREATE INDEX IF NOT EXISTS idx_aliases_norm ON aliases(phrase_norm);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def record_alias(phrase: str, sku: str, wrong_sku: Optional[str] = None) -> None:
    norm = normalize(phrase)
    if not norm or not sku:
        return
    with _conn() as conn:
        conn.execute(
            """INSERT INTO aliases (phrase_norm, phrase_raw, sku, wrong_sku, hits)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(phrase_norm, sku)
               DO UPDATE SET hits = hits + 1""",
            (norm, phrase, sku, wrong_sku),
        )


def lookup_alias(phrase: str) -> Optional[str]:
    norm = normalize(phrase)
    if not norm:
        return None
    with _conn() as conn:
        row = conn.execute(
            "SELECT sku FROM aliases WHERE phrase_norm = ? ORDER BY hits DESC LIMIT 1",
            (norm,),
        ).fetchone()
    return row["sku"] if row else None


def list_aliases(limit: int = 200) -> List[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT phrase_raw, sku, wrong_sku, hits, created_at "
            "FROM aliases ORDER BY hits DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def confusion_pairs(limit: int = 20) -> List[Tuple[str, str, int]]:
    """Which SKU gets mistaken for which. This is the report you take to a
    catalog owner to argue that two product descriptions need fixing."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT wrong_sku, sku, SUM(hits) AS n
               FROM aliases WHERE wrong_sku IS NOT NULL
               GROUP BY wrong_sku, sku ORDER BY n DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [(r["wrong_sku"], r["sku"], r["n"]) for r in rows]
