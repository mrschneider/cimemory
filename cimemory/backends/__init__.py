"""Backend implementations and factory.

Register a new backend with ``register_backend`` and it becomes selectable by
name everywhere — including from config/YAML — with no change to the plugin.
"""

from __future__ import annotations

from typing import Any, Callable

from .jsonl import JsonlBackend
from .memory import InMemoryBackend
from .sqlite import SQLiteBackend

_FACTORIES: dict[str, Callable[..., Any]] = {
    "memory": InMemoryBackend,
    "sqlite": SQLiteBackend,
    "jsonl": JsonlBackend,
}


def register_backend(name: str, factory: Callable[..., Any]) -> None:
    _FACTORIES[name] = factory


def available_backends() -> list[str]:
    return sorted(_FACTORIES)


def get_backend(name: str = "memory", **kwargs) -> Any:
    """Instantiate a backend by name. e.g. get_backend("sqlite", path="ev.db")"""
    try:
        factory = _FACTORIES[name]
    except KeyError as exc:
        raise KeyError(
            f"unknown backend {name!r}; available: {available_backends()}"
        ) from exc
    return factory(**kwargs)


__all__ = [
    "InMemoryBackend",
    "SQLiteBackend",
    "JsonlBackend",
    "get_backend",
    "register_backend",
    "available_backends",
]
