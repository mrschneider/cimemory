"""SQLite backend. Stdlib only.

Demonstrates a *richer* backend than the in-memory one: it is durable,
transactional, has temporal versioning (every overwrite is kept in a history
table) and full-text search via LIKE. The plugin still calls the same ten
methods.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Optional

from ..backend import BackendCapabilities, BaseBackend

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    kind       TEXT NOT NULL,
    record_id  TEXT NOT NULL,
    payload    TEXT NOT NULL,
    ts         REAL NOT NULL,
    PRIMARY KEY (kind, record_id)
);
CREATE INDEX IF NOT EXISTS idx_records_kind_ts ON records(kind, ts);

CREATE TABLE IF NOT EXISTS history (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    record_id  TEXT NOT NULL,
    payload    TEXT NOT NULL,
    replaced_ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS journal (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    entry      TEXT NOT NULL
);
"""


class SQLiteBackend(BaseBackend):
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._path = path

    # ----- required -------------------------------------------------------

    def write(self, kind: str, record_id: str, payload: dict[str, Any]) -> None:
        ts = float(payload.get("ts", time.time()))
        with self._conn:  # transactional
            old = self._conn.execute(
                "SELECT payload FROM records WHERE kind=? AND record_id=?",
                (kind, record_id),
            ).fetchone()
            if old is not None:
                self._conn.execute(
                    "INSERT INTO history(kind, record_id, payload, replaced_ts) "
                    "VALUES (?,?,?,?)",
                    (kind, record_id, old["payload"], time.time()),
                )
            self._conn.execute(
                "INSERT INTO records(kind, record_id, payload, ts) VALUES (?,?,?,?) "
                "ON CONFLICT(kind, record_id) DO UPDATE SET payload=excluded.payload,"
                " ts=excluded.ts",
                (kind, record_id, json.dumps(payload, default=str), ts),
            )

    def read(self, kind: str, record_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT payload FROM records WHERE kind=? AND record_id=?",
            (kind, record_id),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def query(self, kind, *, where=None, order_by=None, descending=False, limit=None):
        sql = "SELECT payload FROM records WHERE kind=?"
        params: list[Any] = [kind]
        if where:
            # equality filters are applied in Python so that dict/list values
            # (breakdown lists, context dicts) compare correctly.
            pass
        order_col = "ts"
        if order_by:
            order_col = f"json_extract(payload, '$.{order_by}')"
        sql += f" ORDER BY {order_col} {'DESC' if descending else 'ASC'}"
        rows = self._conn.execute(sql, params).fetchall()
        out = [json.loads(r["payload"]) for r in rows]
        if where:
            out = [r for r in out if all(r.get(k) == v for k, v in where.items())]
        if limit is not None:
            out = out[:limit]
        return out

    def delete(self, kind: str, record_id: str) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM records WHERE kind=? AND record_id=?", (kind, record_id)
            )
        return cur.rowcount > 0

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="sqlite",
            transactional=True,
            append_only_journal=True,
            temporal_versioning=True,
            full_text_search=True,
            vector_search=False,
            durable=self._path != ":memory:",
            multi_tenant=False,
        )

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.ProgrammingError:
            pass

    # ----- optional -------------------------------------------------------

    def append(self, entry: dict[str, Any]) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO journal(ts, entry) VALUES (?,?)",
                (float(entry.get("ts", time.time())), json.dumps(entry, default=str)),
            )

    def journal(self, *, since=None, limit=None):
        sql = "SELECT ts, entry FROM journal"
        params: list[Any] = []
        if since is not None:
            sql += " WHERE ts >= ?"
            params.append(since)
        sql += " ORDER BY seq ASC"
        rows = self._conn.execute(sql, params).fetchall()
        out = [json.loads(r["entry"]) for r in rows]
        return out[:limit] if limit is not None else out

    def search_text(self, kind, text):
        rows = self._conn.execute(
            "SELECT payload FROM records WHERE kind=? AND payload LIKE ?",
            (kind, f"%{text}%"),
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    # ----- introspection --------------------------------------------------

    def history(self, kind: str, record_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT payload FROM history WHERE kind=? AND record_id=? ORDER BY seq ASC",
            (kind, record_id),
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]
