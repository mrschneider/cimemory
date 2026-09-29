"""The DB-agnostic storage contract.

The plugin never imports a database driver. It talks to a ``MemoryBackend``,
which is any object satisfying this protocol. Adding Postgres, Redis, S3,
Neo4j or a vector store means writing one adapter — nothing else changes.

The contract is deliberately **small**. Ten methods, five of them optional to
implement (they raise ``NotImplementedError`` by default and are advertised
truthfully through ``capabilities()``).

Full requirements, and why each one exists, are in
``docs/requirements/generic-memory-requirements.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Protocol, runtime_checkable


@dataclass
class BackendCapabilities:
    """What a backend can actually do.

    The plugin asks before it relies on anything. A backend that cannot do
    vector search says so, and the plugin falls back to keyword scan instead of
    crashing or silently returning nothing.
    """

    name: str
    transactional: bool = False           # multi-record writes are atomic
    append_only_journal: bool = False     # an ordered, immutable event log
    temporal_versioning: bool = False     # previous versions are retrievable
    full_text_search: bool = False
    vector_search: bool = False
    durable: bool = False                 # survives process restart
    multi_tenant: bool = False            # scoped/isolation support
    max_record_bytes: Optional[int] = None

    def supports(self, feature: str) -> bool:
        return bool(getattr(self, feature, False))


class BackendError(RuntimeError):
    """Raised for genuine storage failures (not for 'unsupported feature')."""


@runtime_checkable
class MemoryBackend(Protocol):
    """Minimal contract every storage adapter must satisfy.

    Records are addressed by ``(kind, record_id)`` and are opaque dicts. The
    backend does not need to know the semantic meaning of a field; it needs to
    store it faithfully, return it faithfully, and be able to hand back every
    record of a kind in a stable order.
    """

    # ----- required -------------------------------------------------------

    def write(self, kind: str, record_id: str, payload: dict[str, Any]) -> None:
        """Insert or fully replace a record. Idempotent on record_id."""
        ...

    def read(self, kind: str, record_id: str) -> Optional[dict[str, Any]]:
        """Return the record, or None. Must not raise for a missing id."""
        ...

    def query(
        self,
        kind: str,
        *,
        where: Optional[dict[str, Any]] = None,
        order_by: Optional[str] = None,
        descending: bool = False,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Return records of ``kind``.

        ``where`` is an equality filter only — deliberately dumb, so every
        backend can honour it. Complex predicates belong in the plugin.
        """
        ...

    def delete(self, kind: str, record_id: str) -> bool:
        """Remove a record. Returns True if something was removed."""
        ...

    def capabilities(self) -> BackendCapabilities:
        """Truthful self-description. Never optimistic."""
        ...

    def close(self) -> None:
        """Flush and release resources. Safe to call twice."""
        ...

    # ----- optional (see capabilities) ------------------------------------

    def update(
        self, kind: str, record_id: str, patch: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Partial update. Backends without native support merge + write."""
        ...

    def append(self, entry: dict[str, Any]) -> None:
        """Append one immutable entry to the journal (the andon/timeline log).

        Required for the evolution loop: the loop must be able to reconstruct
        what it saw, in order, even if a record was later mutated.
        """
        ...

    def journal(
        self, *, since: Optional[float] = None, limit: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Read the append-only journal, oldest first."""
        ...

    def search_text(self, kind: str, text: str) -> list[dict[str, Any]]:
        """Keyword/substring search. Optional."""
        ...

    def search_vector(
        self, kind: str, embedding: Iterable[float], k: int = 5
    ) -> list[tuple[dict[str, Any], float]]:
        """Nearest-neighbour search. Optional."""
        ...


class BaseBackend:
    """Convenience base: provides the optional methods as honest no-ops.

    Subclasses override only what they genuinely support, and must override
    ``capabilities()`` to match.
    """

    def write(self, kind: str, record_id: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def read(self, kind: str, record_id: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    def query(self, kind, *, where=None, order_by=None, descending=False, limit=None):
        raise NotImplementedError

    def delete(self, kind: str, record_id: str) -> bool:
        raise NotImplementedError

    def capabilities(self) -> BackendCapabilities:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def update(self, kind, record_id, patch):
        existing = self.read(kind, record_id)
        if existing is None:
            return None
        merged = {**existing, **patch}
        self.write(kind, record_id, merged)
        return merged

    def append(self, entry: dict[str, Any]) -> None:
        raise NotImplementedError("this backend has no append-only journal")

    def journal(self, *, since=None, limit=None):
        raise NotImplementedError("this backend has no append-only journal")

    def search_text(self, kind, text):
        raise NotImplementedError("this backend has no full-text search")

    def search_vector(self, kind, embedding, k=5):
        raise NotImplementedError("this backend has no vector search")
