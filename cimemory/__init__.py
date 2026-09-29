"""cimemory — a continuous-improvement memory plugin for agent evolution.

Built on the Toyota Production System: kaizen, PDCA / Toyota Business Practices,
jidoka, andon, hansei, yokoten, and standard work.

Quick start
-----------
    from cimemory import EvolutionMemory, KaizenLoop, KaizenSpec, get_backend

    mem = EvolutionMemory(get_backend("sqlite", path="evolution.db"), agent="argus")
    loop = KaizenLoop(mem)
    outcome = loop.run(KaizenSpec(...))

The plugin is DB-agnostic: swap ``get_backend("sqlite")`` for
``get_backend("memory")``, ``get_backend("jsonl", path="...")``, or any object
implementing ``MemoryBackend``.
"""

from .backend import (
    BackendCapabilities,
    BackendError,
    BaseBackend,
    MemoryBackend,
)
from .backends import (
    InMemoryBackend,
    JsonlBackend,
    SQLiteBackend,
    available_backends,
    get_backend,
    register_backend,
)
from .loop import (
    ChangeScope,
    CountermeasureSpec,
    CycleOutcome,
    KaizenLoop,
    KaikakuNotApproved,
    KaizenSpec,
)
from .models import (
    Andon,
    Check,
    Countermeasure,
    CountermeasureStrength,
    Experiment,
    ExperimentStatus,
    Hansei,
    Observation,
    Problem,
    ProblemStatus,
    RootCause,
    Spread,
    Standard,
    Target,
    Why,
)
from .plugin import DisciplineError, EvolutionMemory

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # plugin
    "EvolutionMemory",
    "DisciplineError",
    # loop
    "KaizenLoop",
    "KaizenSpec",
    "CountermeasureSpec",
    "CycleOutcome",
    "ChangeScope",
    "KaikakuNotApproved",
    # backends
    "MemoryBackend",
    "BaseBackend",
    "BackendCapabilities",
    "BackendError",
    "InMemoryBackend",
    "SQLiteBackend",
    "JsonlBackend",
    "get_backend",
    "register_backend",
    "available_backends",
    # models
    "Observation",
    "Problem",
    "ProblemStatus",
    "Target",
    "Why",
    "RootCause",
    "Countermeasure",
    "CountermeasureStrength",
    "Check",
    "Experiment",
    "ExperimentStatus",
    "Standard",
    "Spread",
    "Hansei",
    "Andon",
]
