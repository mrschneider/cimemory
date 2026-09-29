"""JSONL backend — the minimal viable adapter.

One append-only file, one JSON object per line. No transactions, no native
index, no versioning. It exists to prove the plugin's contract is genuinely
thin: if a backend as dumb as this one works, a real database will too.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

from ..backend import BackendCapabilities, BaseBackend


class JsonlBackend(BaseBackend):
    def __init__(self, path: str = "cimemory.jsonl") -> None:
        self._path = path
        self._records: dict[str, dict[str, dict[str, Any]]] = {}
        self._journal: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind, record_id, payload = row["kind"], row["record_id"], row["payload"]
                if kind == "__journal__":
                    self._journal.append(payload)
                else:
                    self._records.setdefault(kind, {})[record_id] = payload

    def _append_line(self, kind: str, record_id: str, payload: dict[str, Any]) -> None:
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(
                {"kind": kind, "record_id": record_id, "payload": payload},
                default=str,
            ) + "\n")

    def _rewrite(self) -> None:
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for kind, bucket in self._records.items():
                for record_id, payload in bucket.items():
                    fh.write(json.dumps(
                        {"kind": kind, "record_id": record_id, "payload": payload},
                        default=str,
                    ) + "\n")
            for entry in self._journal:
                fh.write(json.dumps(
                    {"kind": "__journal__", "record_id": "", "payload": entry},
                    default=str,
                ) + "\n")
        os.replace(tmp, self._path)

    # ----- required -------------------------------------------------------

    def write(self, kind: str, record_id: str, payload: dict[str, Any]) -> None:
        self._records.setdefault(kind, {})[record_id] = payload
        self._append_line(kind, record_id, payload)

    def read(self, kind: str, record_id: str) -> Optional[dict[str, Any]]:
        return self._records.get(kind, {}).get(record_id)

    def query(self, kind, *, where=None, order_by=None, descending=False, limit=None):
        rows = list(self._records.get(kind, {}).values())
        if where:
            rows = [r for r in rows if all(r.get(k) == v for k, v in where.items())]
        if order_by:
            rows.sort(key=lambda r: (r.get(order_by) is None, r.get(order_by)),
                      reverse=descending)
        if limit is not None:
            rows = rows[:limit]
        return rows

    def delete(self, kind: str, record_id: str) -> bool:
        removed = self._records.get(kind, {}).pop(record_id, None) is not None
        if removed:
            self._rewrite()
        return removed

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="jsonl",
            transactional=False,
            append_only_journal=True,
            temporal_versioning=False,
            full_text_search=True,
            vector_search=False,
            durable=True,
            multi_tenant=False,
        )

    def close(self) -> None:
        self._rewrite()

    # ----- optional -------------------------------------------------------

    def append(self, entry: dict[str, Any]) -> None:
        self._journal.append(entry)
        self._append_line("__journal__", "", entry)

    def journal(self, *, since=None, limit=None):
        entries = list(self._journal)
        if since is not None:
            entries = [e for e in entries if e.get("ts", 0) >= since]
        return entries[:limit] if limit is not None else entries

    def search_text(self, kind, text):
        needle = text.lower()
        return [
            r for r in self._records.get(kind, {}).values()
            if needle in json.dumps(r, default=str).lower()
        ]
