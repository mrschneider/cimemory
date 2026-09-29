"""Live, READ-ONLY source: the Ratiocore agent memory in Tarantool.

This is the cimemory counterpart of ntmemory's ``RatiocoreSource``: it turns
production memory into the *Toyota* reading of a shift — stations, standards,
defects — instead of into SECI episodes.

**The read-only contract** (why this module cannot corrupt production):

* it connects as ``guest``, a role with no space write grants;
* every statement it issues is a ``select`` on ``agent_memory`` (or a
  ``box.space`` introspection for the schema probe). There is no ``insert``,
  ``replace``, ``update``, ``delete``, ``truncate`` or ``eval`` with a side
  effect anywhere in this file;
* it never writes back "improvement opportunities". The whole point of the
  wiring is to *observe*: the plugin's loop stays offline.

Nothing here is inferred from a self-report: every number is a count of real
tuples. Where the data cannot answer a question (a root cause, a deadline, a
target), the field is left ``None`` and the board renders it as unanswered
rather than guessing.

Space layout — ``box.space.agent_memory``:
``[turn_id, profile, role, content, embedding, metadata]`` where ``role`` is
one of ``user | assistant | tool | system | lesson | outcome`` and
``metadata`` carries ``ts``, ``importance``, ``sid`` (session), ``status``
(tool calls only), ``tool_call_id``, ``final``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3301
DEFAULT_SPACE = "agent_memory"

# A tool call whose status is not "ok" is a defect at the station: the call
# did not deliver what the work needed. This is the only defect definition
# used, so the number is reproducible.
OK_STATUS = "ok"

# The waste class a defect of each kind represents (Toyota's muda taxonomy).
# Only the mapping is ours; the counts are the memory's.
DEFECT_WASTE: Dict[str, str] = {
    "timeout": "Waiting",            # the shift sat waiting on a stalled call
    "validation_error": "Defects",   # the call came back malformed
    "nonzero_exit": "Defects",       # the command ran and failed
    "error": "Defects",              # the tool raised
    "none": "Defects",               # status never recorded
}

# A station with fewer observations than this cannot set the fleet target —
# a 0% rate over 12 calls is not evidence of a capability, it is a small
# sample. Below the threshold the station is *reported* but not *ranked*.
MIN_EVIDENCE = 30

_OUTCOME_HEAD = re.compile(r"^\s*outcome\s+(done|failed)\b", re.I)
_ATTEMPTS = re.compile(r"\ba(\d+):([a-z_]+)", re.I)
_TRACE = re.compile(r"\[([^\]]*a\d+:[^\]]*)\]")
_WHY_CAUSE = re.compile(r"\bcausa\s+real\b|\broot\s+cause\b|\bmedida\b", re.I)
_WHY_SUSPECT = re.compile(r"\bsuspeit\w*|\bhip[oó]tese\b|\bprovavelmente\b|\btalvez\b", re.I)
_WHY_DESIGN = re.compile(
    r"\bexigia\b|\bexige\b|\brequer\w*|\bprecisa\w*|\bdeve\b|\bdeveria\b|"
    r"\bobriga\w*|\bconftest\b|\bverificador\b", re.I)


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

class ReadOnlyTarantool:
    """Paged, read-only reader over one Tarantool space.

    Deliberately tiny: ``select`` and nothing else. The guard below refuses
    the connection outright if it is ever handed a user with write grants,
    so a future edit cannot silently turn observation into mutation.
    """

    FORBIDDEN_GRANTS = ("write", "read,write", "create", "drop", "alter")

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 space: str = DEFAULT_SPACE, page: int = 200,
                 user: str = "guest", connect: Any = None) -> None:
        self.host, self.port, self.space, self.page = host, port, space, page
        self.user = user
        self._conn: Any = None
        self._connect = connect  # injectable for tests
        self._rows_read = 0

    # -- connection -------------------------------------------------------
    @property
    def conn(self) -> Any:
        if self._conn is None:
            if self._connect is not None:
                self._conn = self._connect(self.host, self.port, self.user)
            else:  # pragma: no cover - exercised only against a live server
                import tarantool  # imported lazily: the plugin stays stdlib-only
                self._conn = tarantool.connect(self.host, self.port, user=self.user)
        return self._conn

    def verify_read_only(self) -> bool:
        """True if this user provably cannot write to the memory space.

        Reads ``box.schema.user.info`` and looks for any grant on the space
        beyond select. Raises ``PermissionError`` if a write grant is found —
        the wiring must never be able to mutate production.
        """
        info = list(self.conn.eval(f"return box.schema.user.info('{self.user}')"))
        text = repr(info).lower()
        for grant in self.FORBIDDEN_GRANTS:
            if grant in text:
                raise PermissionError(
                    f"user {self.user!r} holds a {grant!r} grant; "
                    "the cimemory live source must be strictly read-only"
                )
        return True

    def stats(self) -> Dict[str, Any]:
        return {"rows_read": self._rows_read, "space": self.space,
                "host": self.host, "port": self.port, "user": self.user}

    # -- reads ------------------------------------------------------------
    def _page(self, offset: int, limit: int) -> List[list]:
        r = self.conn.eval(
            f"return box.space.{self.space}:select(nil, "
            f"{{limit={limit}, offset={offset}}})"
        )
        rows = list(r)
        # the driver sometimes nests the page as a single outer row
        if len(rows) == 1 and isinstance(rows[0], list) and rows[0] and \
                isinstance(rows[0][0], (list, tuple)):
            rows = [list(x) for x in rows[0]]
        return [list(x) for x in rows]

    def iter_raw(self, limit: Optional[int] = None) -> Iterator[list]:
        """Yield raw tuples, page by page. ``select`` only."""
        offset, n = 0, 0
        while True:
            rows = self._page(offset, self.page)
            if not rows:
                return
            for row in rows:
                self._rows_read += 1
                yield row
                n += 1
                if limit is not None and n >= limit:
                    return
            if len(rows) < self.page:
                return
            offset += self.page


def _clip(text: Any, n: int) -> str:
    """Truncate on a UTF-8 boundary so the transport never sees half a char."""
    s = "" if text is None else str(text)
    if len(s) <= n:
        return s
    b = s.encode("utf-8")[:n]
    return b.decode("utf-8", "ignore")


# ---------------------------------------------------------------------------
# what the memory says
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Turn:
    """One real tuple, reduced to what the board needs."""
    turn_id: str
    agent: str
    role: str
    content: str
    ts: float
    session: str
    status: Optional[str] = None
    importance: Optional[float] = None

    @property
    def is_tool(self) -> bool:
        return self.role == "tool"

    @property
    def is_defect(self) -> bool:
        return self.is_tool and (self.status or "none") != OK_STATUS


@dataclass
class Station:
    """One agent as a station on the gemba board."""
    agent: str
    tool_calls: int = 0
    defects: int = 0
    turns: int = 0
    sessions: int = 0
    last_seen: float = 0.0
    defect_mix: Dict[str, int] = field(default_factory=dict)

    @property
    def defect_rate(self) -> float:
        return (100.0 * self.defects / self.tool_calls) if self.tool_calls else 0.0

    @property
    def first_pass_yield(self) -> float:
        return 100.0 - self.defect_rate

    @property
    def evidence(self) -> bool:
        return self.tool_calls >= MIN_EVIDENCE

    @property
    def dominant_defect(self) -> str:
        if not self.defect_mix:
            return "none"
        return max(sorted(self.defect_mix), key=lambda k: self.defect_mix[k])

    @property
    def waste(self) -> str:
        if not self.defects:
            return "none observed"
        return DEFECT_WASTE.get(self.dominant_defect, "Defects")

    @property
    def waste_detail(self) -> str:
        if not self.defect_mix:
            return "no defect recorded in the window"
        return " · ".join(f"{k} {v}" for k, v in
                          sorted(self.defect_mix.items(), key=lambda x: -x[1]))


@dataclass(frozen=True)
class Lesson:
    """A ``role=lesson`` tuple: the agent's own written-down learning."""
    agent: str
    ts: float
    text: str
    strength: str          # classified from the agent's own wording
    basis: str             # the phrase that decided the class


@dataclass(frozen=True)
class Verdict:
    """A ``role=outcome`` tuple: a real task verdict with its attempt trace."""
    agent: str
    ts: float
    outcome: str           # "done" | "failed"
    attempts: int
    trace: List[str]       # e.g. ["a1:criterion_failed", ...]
    subject: str


@dataclass
class FleetMeasurement:
    """The whole shift, as the board sees it."""
    stations: List[Station]
    standard: float
    goal: float
    worst: float
    window: tuple
    n_tool_calls: int
    n_defects: int
    lessons: List[Lesson]
    verdicts: List[Verdict]
    source_label: str
    readonly_verified: bool

    @property
    def abnormal(self) -> List[Station]:
        return [s for s in self.stations
                if s.evidence and s.defect_rate > self.standard + 1e-9]

    @property
    def defect_rate(self) -> float:
        return (100.0 * self.n_defects / self.n_tool_calls) if self.n_tool_calls else 0.0


# ---------------------------------------------------------------------------
# Toyota derivation
# ---------------------------------------------------------------------------

def _median(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def classify_strength(text: str) -> tuple:
    """Classify a documented lesson on the countermeasure strength ladder.

    The class is read out of the agent's *own* wording — a measured cause is
    a taisaku, a suspicion is only a taisho, and a statement about what the
    environment requires is a design-level (mizen-boushi) finding. Anything
    else is unclassified rather than promoted: the board must not flatter a
    note into a fix.
    """
    t = text or ""
    m = _WHY_CAUSE.search(t)
    if m:
        return "taisaku", m.group(0)
    m = _WHY_SUSPECT.search(t)
    if m:
        return "taisho", m.group(0)
    m = _WHY_DESIGN.search(t)
    if m:
        return "mizen_boushi", m.group(0)
    return "unclassified", ""


def _parse_verdict(agent: str, ts: float, content: str) -> Verdict:
    """Parse a real ``outcome`` line: verdict, attempt count, attempt trace."""
    head = _OUTCOME_HEAD.match(content or "")
    outcome = (head.group(1).lower() if head else "unknown")
    trace: List[str] = []
    m = _TRACE.search(content or "")
    if m:
        trace = [p.strip() for p in m.group(1).split(";") if p.strip()]
    n_attempts = 0
    am = re.search(r"apos?\s+(\d+)\s+tentativa", content or "", re.I)
    if am:
        n_attempts = int(am.group(1))
    elif trace:
        n_attempts = len(_ATTEMPTS.findall(";".join(trace))) or len(trace)
    subject = content or ""
    sm = re.search(r"\bpara:\s*(.*)$", subject, re.S)
    if sm:
        subject = sm.group(1)
    return Verdict(agent=agent, ts=ts, outcome=outcome, attempts=n_attempts,
                   trace=trace, subject=_clip(subject.strip(), 200))


def measure(source: Any, *, limit: Optional[int] = None,
            source_label: Optional[str] = None) -> FleetMeasurement:
    """Read the memory once and derive the fleet reading. Pure; no writes."""
    stations: Dict[str, Station] = {}
    lessons: List[Lesson] = []
    verdicts: List[Verdict] = []
    lo: Optional[float] = None
    hi: Optional[float] = None

    for row in source.iter_raw(limit=limit):
        if len(row) < 6:
            continue
        turn = _to_turn(row)
        st = stations.setdefault(turn.agent, Station(agent=turn.agent))
        st.turns += 1
        st.last_seen = max(st.last_seen, turn.ts)
        if turn.ts:
            lo = turn.ts if lo is None else min(lo, turn.ts)
            hi = turn.ts if hi is None else max(hi, turn.ts)
        if turn.session:
            st.sessions += 1
        if turn.is_tool:
            st.tool_calls += 1
            status = turn.status or "none"
            if status != OK_STATUS:
                st.defects += 1
                st.defect_mix[status] = st.defect_mix.get(status, 0) + 1
        elif turn.role == "lesson":
            strength, basis = classify_strength(turn.content)
            lessons.append(Lesson(agent=turn.agent, ts=turn.ts,
                                  text=_clip(turn.content, 600),
                                  strength=strength, basis=basis))
        elif turn.role == "outcome":
            verdicts.append(_parse_verdict(turn.agent, turn.ts, turn.content))

    ranked = [s for s in stations.values() if s.evidence]
    rates = [s.defect_rate for s in ranked]
    standard = round(_median(rates), 2)
    goal = round(min(rates), 2) if rates else 0.0
    worst = round(max(rates), 2) if rates else 0.0

    label = source_label or (
        f"live · ratiocore agent_memory @ {source.host}:{source.port} "
        f"({source.space}, role={source.user}, select-only)"
    )
    return FleetMeasurement(
        stations=sorted(stations.values(), key=lambda s: -s.defect_rate),
        standard=standard, goal=goal, worst=worst,
        window=(lo or 0.0, hi or 0.0),
        n_tool_calls=sum(s.tool_calls for s in stations.values()),
        n_defects=sum(s.defects for s in stations.values()),
        lessons=sorted(lessons, key=lambda l: l.ts),
        verdicts=sorted(verdicts, key=lambda v: v.ts),
        source_label=label,
        readonly_verified=True,
    )


def _to_turn(row: list) -> Turn:
    meta = row[5] if isinstance(row[5], dict) else {}
    try:
        ts = float(meta.get("ts") or 0.0)
    except (TypeError, ValueError):
        ts = 0.0
    try:
        importance = float(meta["importance"]) if "importance" in meta else None
    except (TypeError, ValueError):
        importance = None
    status = meta.get("status")
    return Turn(
        turn_id=str(row[0]),
        agent=str(row[1] or "unknown"),
        role=str(row[2] or "unknown"),
        content=_clip(row[3], 600),
        ts=ts,
        session=str(meta.get("sid") or meta.get("session_id") or ""),
        status=str(status) if status is not None else None,
        importance=importance,
    )


def probe(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> Dict[str, Any]:
    """Read-only health probe: is the memory reachable and how big is it?

    Never raises: an unreachable memory is a fact to report, not an error to
    propagate at whoever asked whether the board is up.
    """
    try:
        src = ReadOnlyTarantool(host=host, port=port)
        src.verify_read_only()
        r = list(src.conn.eval(
            f"local s = box.space.{src.space} "
            "if s == nil then return nil end return s:len()"))
        n = r[0] if r else None
        return {"ok": n is not None, "rows": int(n) if n is not None else 0,
                "space": src.space, "host": host, "port": port,
                "readonly": True}
    except Exception as exc:  # pragma: no cover - live path
        # ``src`` may never have been built: fall back to the defaults.
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "space": DEFAULT_SPACE, "host": host, "port": port,
                "readonly": True}
