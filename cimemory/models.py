"""Data model for the continuous-improvement memory.

Every record here maps to a Toyota concept. The mapping is deliberate and is
documented in docs/architecture/kaizen-evolution-loop.md:

    Observation        -> genchi genbutsu / gemba observation
    Problem            -> TBP step 1 (clarify) + step 2 (break down)
    Target             -> TBP step 3
    RootCause / Why    -> TBP step 4 (5-Why + Therefore Test)
    Countermeasure     -> TBP step 5 (taisho / taisaku / mizen-boushi)
    Experiment         -> TBP step 6 (Do) + step 7 (Check)
    Standard           -> TBP step 8 (Act: standardise, reset the baseline)
    Spread (Yokoten)   -> TBP step 8 (Act: share horizontally)
    Hansei             -> TBP step 8 (reflection) / Principle 14
    Andon              -> Principle 5 (stop the line / jidoka)

All records are plain dataclasses that serialise to JSON-serialisable dicts.
Nothing here knows about a database.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _now() -> float:
    return time.time()


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _plain(obj: Any) -> Any:
    """Recursively convert Enums (and tuples) to plain JSON-safe values."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


class Record:
    """Mixin: every record is a dataclass that can become a plain dict.

    ``kind`` is what the backend stores it under, so a DB-agnostic backend only
    ever needs ``save(kind, id, dict)`` / ``load(kind, id)``.
    """

    _kind: str = "record"
    _id_field: str = ""

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def record_id(self) -> str:
        """The id this record is stored under. Convention, not hard-coding."""
        value = getattr(self, self._id_field, None)
        if value is None:
            raise NotImplementedError(
                f"{type(self).__name__} does not declare _id_field"
            )
        return str(value)

    def to_dict(self) -> dict[str, Any]:
        """Plain, JSON-safe dict. Enums become their string values so every
        backend stores and compares the same thing."""
        return _plain(asdict(self))  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        return cls(**data)


class CountermeasureStrength(str, Enum):
    """The Toyota countermeasure strength ladder.

    Docs: docs/research/toyota-continuous-improvement.md section 5.
    """

    TAISHO = "taisho"           # containment: stops the bleeding, not the cause
    TAISAKU = "taisaku"         # countermeasure against a *verified* root cause
    MIZEN_BOUSHI = "mizen_boushi"  # design the failure mode out, upstream

    @property
    def rank(self) -> int:
        return {"taisho": 1, "taisaku": 2, "mizen_boushi": 3}[self.value]


class ProblemStatus(str, Enum):
    OPEN = "open"
    ANALYSED = "analysed"
    IN_EXPERIMENT = "in_experiment"
    VERIFIED = "verified"
    STANDARDISED = "standardised"
    ABANDONED = "abandoned"


class ExperimentStatus(str, Enum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------

@dataclass
class Observation(Record):
    """A single fact captured at the gemba (the real place work happens).

    Never a self-report of intent — a measurement, a log line, a telemetry
    sample. Principle 12: go and see for yourself.
    """

    _kind = "observation"
    _id_field = "observation_id"

    agent: str
    metric: str
    value: float
    source: str = "telemetry"          # where the number came from
    context: dict[str, Any] = field(default_factory=dict)
    observation_id: str = field(default_factory=lambda: _uid("obs"))
    ts: float = field(default_factory=_now)




@dataclass
class Problem(Record):
    """TBP steps 1-2: the gap between ideal and actual, broken down.

    ``ideal`` and ``actual`` are required because a problem without a stated
    standard is an opinion (Principle 6).
    """

    _kind = "problem"
    _id_field = "problem_id"

    agent: str
    capability: str                    # the standard-work unit this problem is against
    ideal: str                         # what "good" is, per the current standard
    actual: str                        # what is happening, per observation
    gap: str                           # the quantified/qualified difference
    breakdown: list[str] = field(default_factory=list)  # step 2: specific pieces
    priority_point: Optional[str] = None  # the one piece worth attacking first
    status: ProblemStatus = ProblemStatus.OPEN
    problem_id: str = field(default_factory=lambda: _uid("prb"))
    opened_ts: float = field(default_factory=_now)


@dataclass
class Target(Record):
    """TBP step 3: a specific, measurable commitment to close the gap by a date.

    A target is NOT a countermeasure. "Implement standardised work" is a means;
    "cut tool-call count from 14 to 6 by 2026-10-15" is a target.
    """

    _kind = "target"
    _id_field = "target_id"

    problem_id: str
    metric: str
    baseline: float
    goal: float
    deadline: str                      # ISO date string
    direction: str = "decrease"        # "decrease" | "increase"
    target_id: str = field(default_factory=lambda: _uid("tgt"))
    ts: float = field(default_factory=_now)

    def met(self, value: float) -> bool:
        if self.direction == "decrease":
            return value <= self.goal
        return value >= self.goal


@dataclass
class Why(Record):
    """One link in a 5-Why chain."""

    _kind = "why"
    _id_field = "why_id"

    problem_id: str
    level: int                         # 1..n
    question: str                      # the "why" asked
    answer: str                        # the observed answer
    evidence: str = ""                 # what makes this true (genba)
    why_id: str = field(default_factory=lambda: _uid("why"))
    ts: float = field(default_factory=_now)


@dataclass
class RootCause(Record):
    """TBP step 4: the verified root cause.

    Verification is a hard requirement: ``verified_by`` must name the
    observation/experiment that proves it, and ``therefore_test_ok`` must be
    True. An unverified root cause cannot back a taisaku.
    """

    _kind = "root_cause"
    _id_field = "root_cause_id"

    problem_id: str
    statement: str
    verified_by: str = ""              # evidence reference; empty => not verified
    therefore_test_ok: bool = False
    root_cause_id: str = field(default_factory=lambda: _uid("rc"))
    ts: float = field(default_factory=_now)

    @property
    def verified(self) -> bool:
        return bool(self.verified_by) and self.therefore_test_ok


@dataclass
class Countermeasure(Record):
    """TBP step 5: an action against a root cause, classified by strength.

    A TAISHO may be applied immediately to protect the customer. A TAISAKU
    requires a verified RootCause — the loop refuses otherwise.
    """

    _kind = "countermeasure"
    _id_field = "countermeasure_id"

    problem_id: str
    description: str
    strength: CountermeasureStrength = CountermeasureStrength.TAISAKU
    root_cause_id: Optional[str] = None
    expected_effect: str = ""
    cost: str = "low"                  # low | medium | high
    risk: str = "low"
    countermeasure_id: str = field(default_factory=lambda: _uid("cm"))
    ts: float = field(default_factory=_now)


@dataclass
class Check(Record):
    """TBP step 7: evaluate BOTH results and process.

    ``results_met`` answers "did the metric reach the target, measured the same
    way?". ``process_holds`` answers "are the conditions that keep the gain in
    place still there?" — the part teams forget.
    """

    _kind = "check"
    _id_field = "check_id"

    experiment_id: str
    metric: str
    after_value: float
    results_met: bool
    process_holds: bool = False
    process_notes: str = ""
    period: str = ""                   # over what window the gain was observed
    check_id: str = field(default_factory=lambda: _uid("chk"))
    ts: float = field(default_factory=_now)

    @property
    def successful(self) -> bool:
        return self.results_met and self.process_holds


@dataclass
class Experiment(Record):
    """TBP step 6 (Do) + step 7 (Check): a controlled kaizen experiment.

    One variable. Small scale first. The same metric as the target, measured the
    same way.
    """

    _kind = "experiment"
    _id_field = "experiment_id"

    problem_id: str
    target_id: str
    hypothesis: str
    countermeasure_ids: list[str] = field(default_factory=list)
    metric: str = ""
    before_value: Optional[float] = None
    after_value: Optional[float] = None
    status: ExperimentStatus = ExperimentStatus.RUNNING
    do_log: list[str] = field(default_factory=list)
    check_id: Optional[str] = None
    experiment_id: str = field(default_factory=lambda: _uid("exp"))
    started_ts: float = field(default_factory=_now)
    closed_ts: Optional[float] = None


@dataclass
class Standard(Record):
    """TBP step 8: a proven countermeasure promoted to the new baseline.

    A Standard is versioned and supersedes a previous one. Until a countermeasure
    becomes a Standard, it "depends on memory and goodwill, and decays".
    """

    _kind = "standard"
    _id_field = "standard_id"

    agent: str
    capability: str
    description: str
    from_experiment: Optional[str] = None
    version: int = 1
    supersedes: Optional[str] = None
    active: bool = True
    standard_id: str = field(default_factory=lambda: _uid("std"))
    ts: float = field(default_factory=_now)


@dataclass
class Spread(Record):
    """Yokoten: the horizontal propagation of a standard to sibling agents."""

    _kind = "spread"
    _id_field = "spread_id"

    standard_id: str
    from_agent: str
    targets: list[str] = field(default_factory=list)
    rationale: str = ""
    applied: list[str] = field(default_factory=list)
    spread_id: str = field(default_factory=lambda: _uid("spr"))
    ts: float = field(default_factory=_now)


@dataclass
class Hansei(Record):
    """Reflection: mandatory, recorded even when the experiment succeeded.

    Not blame — learning, so capability compounds over time.
    """

    _kind = "hansei"
    _id_field = "hansei_id"

    subject_id: str                    # problem or experiment id
    went_well: list[str] = field(default_factory=list)
    went_poorly: list[str] = field(default_factory=list)
    why: list[str] = field(default_factory=list)
    next_time: list[str] = field(default_factory=list)
    hansei_id: str = field(default_factory=lambda: _uid("han"))
    ts: float = field(default_factory=_now)


@dataclass
class Andon(Record):
    """Principle 5 / jidoka: a stop-the-line signal.

    Raised the instant an abnormality is detected, before a defective result
    ships.
    """

    _kind = "andon"
    _id_field = "andon_id"

    agent: str
    severity: str = "warning"          # info | warning | critical
    reason: str = ""
    stopped: bool = False              # did it actually halt the work?
    resolved: bool = False
    resolution: str = ""
    andon_id: str = field(default_factory=lambda: _uid("and"))
    ts: float = field(default_factory=_now)
    resolved_ts: Optional[float] = None
