"""In-memory backend. Zero dependencies. Used by tests and experiments."""

from __future__ import annotations

import copy
from typing import Any, Optional

from ..backend import BackendCapabilities, BaseBackend


class InMemoryBackend(BaseBackend):
    def __init__(self, name: str = "memory") -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._journal: list[dict[str, Any]] = []
        self._name = name
        self._closed = False

    # ----- required -------------------------------------------------------

    def write(self, kind: str, record_id: str, payload: dict[str, Any]) -> None:
        self._data.setdefault(kind, {})[record_id] = copy.deepcopy(payload)

    def read(self, kind: str, record_id: str) -> Optional[dict[str, Any]]:
        rec = self._data.get(kind, {}).get(record_id)
        return copy.deepcopy(rec) if rec is not None else None

    def query(self, kind, *, where=None, order_by=None, descending=False, limit=None):
        rows = [copy.deepcopy(r) for r in self._data.get(kind, {}).values()]
        if where:
            rows = [
                r for r in rows
                if all(r.get(k) == v for k, v in where.items())
            ]
        if order_by:
            rows.sort(key=lambda r: (r.get(order_by) is None, r.get(order_by)),
                      reverse=descending)
        if limit is not None:
            rows = rows[:limit]
        return rows

    def delete(self, kind: str, record_id: str) -> bool:
        return self._data.get(kind, {}).pop(record_id, None) is not None

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name=self._name,
            transactional=True,
            append_only_journal=True,
            temporal_versioning=False,
            full_text_search=True,
            vector_search=False,
            durable=False,
            multi_tenant=False,
        )

    def close(self) -> None:
        self._closed = True
        self._data.clear()
        self._journal.clear()

    # ----- optional -------------------------------------------------------

    def append(self, entry: dict[str, Any]) -> None:
        self._journal.append(copy.deepcopy(entry))

    def journal(self, *, since=None, limit=None):
        entries = [copy.deepcopy(e) for e in self._journal]
        if since is not None:
            entries = [e for e in entries if e.get("ts", 0) >= since]
        if limit is not None:
            entries = entries[:limit]
        return entries

    def search_text(self, kind, text):
        needle = text.lower()
        out = []
        for r in self._data.get(kind, {}).values():
            blob = " ".join(str(v) for v in r.values()).lower()
            if needle in blob:
                out.append(copy.deepcopy(r))
        return out

    # ----- introspection --------------------------------------------------

    def all_kinds(self) -> list[str]:
        return sorted(self._data)

    def count(self, kind: str) -> int:
        return len(self._data.get(kind, {}))
