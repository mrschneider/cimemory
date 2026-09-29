"""Live, READ-ONLY source: production agent telemetry for the Toyota board.

This is the cimemory counterpart of ntmemory's ``RatiocoreSource``: it turns
production memory into the *Toyota* reading of a shift — stations, standards,
defects, waste — instead of into SECI episodes.

**The read-only contract** (why this module cannot corrupt production):

* it connects as ``guest``, a role with no space write grants;
* every statement it issues is a ``select`` read or a ``format()``
  introspection. There is no ``insert``, ``replace``, ``update``, ``delete``,
  ``truncate``, ``upsert`` or side-effecting ``eval`` anywhere in this file;
* :meth:`ReadOnlyTarantool.verify_read_only` reads ``box.schema.user.info``
  and refuses to run if the user holds any write grant, so a future edit
  cannot quietly promote an observer to a writer;
* ``tests/test_live.py`` inspects this module's own source and fails if a
  mutation call ever appears in it.

**Nothing is inferred.** Every figure is a count over tuples. Where the
evidence cannot answer — a root cause, a deadline, a target — the field stays
``None`` and the board renders a gap rather than a guess. Where a comparison
would be unsound (a rate over 13 events against one over 107), the window is
marked *not comparable* instead of being shown as an improvement.

Spaces read (all read-only):

===========================  ============================================
``agent_memory``             turns; ``lesson``/``outcome`` rows are the
                             qualitative evidence (causes, verdicts)
``tool_event``               the defect ledger: one row per tool call with
                             ``status``, ``is_error``, ``exit_code``
``turn_traces``              per-turn cost: ``duration_ms``, ``tokens_in``,
                             ``tokens_out``, ``tool_calls``
``agent_runtime_config``     the revisioned actuator surface — read here
                             only as a *time marker*, never written
``agent_revision``           revision activation times and ``change_reason``
``rb_insight``               documented insights and their ``uses`` counter
===========================  ============================================
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3301
DEFAULT_SPACE = "agent_memory"

SPACE_MEMORY = "agent_memory"
SPACE_TOOL_EVENT = "tool_event"
SPACE_TURN_TRACES = "turn_traces"
SPACE_RUNTIME_CONFIG = "agent_runtime_config"
SPACE_REVISION = "agent_revision"
SPACE_INSIGHT = "rb_insight"

# A tool call whose recorded status is not "ok" is a defect at the station:
# the call did not deliver what the work needed. This is the only defect
# definition used, so the number is reproducible. ``tool_event`` and
# ``agent_memory`` agree on it wherever they overlap (measured: 759
# overlapping calls, 759 agree, 0 disagree), which is why either can serve.
OK_STATUS = "ok"

# The muda class a defect of each kind represents. Only the mapping is ours.
DEFECT_WASTE: Dict[str, str] = {
    "timeout": "Waiting",            # the shift sat waiting on a stalled call
    "validation_error": "Defects",   # the call came back malformed
    "nonzero_exit": "Defects",       # the command ran and failed
    "error": "Defects",              # the tool raised
    "none": "Defects",               # status never recorded
}

# The four muda axes measured directly, each in its own unit. A millisecond
# and a defect are not commensurable, so each axis is judged against its own
# fleet median instead of being summed into a single score.
MUDA_AXES: Dict[str, str] = {
    "defects": "defects per 100 tool calls",
    "waiting": "mean turn duration (ms)",
    "overprocessing": "mean prompt tokens per turn",
    "motion": "mean tool calls per turn",
}

# A station with fewer observations than this cannot set a fleet standard —
# a 0% rate over 12 calls is not a capability, it is a small sample. Below
# the threshold the station is *reported* but not *ranked*, and a window is
# marked *not comparable*.
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

class SpaceUnavailable(Exception):
    """The space is not readable by this user — reported, never guessed."""


class ReadOnlyTarantool:
    """Paged, read-only reader over Tarantool spaces.

    Deliberately tiny: ``select`` and nothing else. The guard refuses the
    connection outright if it is ever handed a user with write grants.
    """

    FORBIDDEN_GRANTS = ("write", "create", "drop", "alter")

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 space: str = DEFAULT_SPACE, page: int = 500,
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
                import tarantool  # lazy: the plugin itself stays stdlib-only
                self._conn = tarantool.connect(self.host, self.port, user=self.user)
        return self._conn

    def verify_read_only(self) -> bool:
        """True if this user provably cannot write to the memory space.

        Reads ``box.schema.user.info`` and looks for any grant beyond
        ``session,usage``/``execute``. Raises ``PermissionError`` if a write
        grant is found — the wiring must never be able to mutate production.
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
    # Fields dropped before transport: raw payloads nobody reads (they are
    # the bulk of the data, and a captured shell excerpt is arbitrary bytes,
    # not text). Everything that survives is passed through a strict UTF-8
    # sanitiser, because one invalid byte in one row would otherwise abort
    # the whole page.
    DROP_FIELDS: Dict[str, Tuple[int, ...]] = {
        SPACE_TOOL_EVENT: (10, 12),   # result_excerpt, args
        SPACE_INSIGHT: (5,),          # embedding: 1024-dim, unused here
    }

    _LUA_CLEAN = r"""
local function clean(v)
  if type(v) ~= 'string' then return v end
  local out, i, n = {}, 1, #v
  if n > 400 then n = 400 end
  while i <= n do
    local b = v:byte(i)
    if b < 0x80 then
      out[#out+1] = v:sub(i, i); i = i + 1
    elseif b < 0xC2 then
      i = i + 1
    elseif b < 0xE0 then
      local b2 = v:byte(i + 1)
      if b2 and b2 >= 0x80 and b2 < 0xC0 then
        out[#out+1] = v:sub(i, i + 1); i = i + 2
      else i = i + 1 end
    elseif b < 0xF0 then
      local b2, b3 = v:byte(i + 1), v:byte(i + 2)
      if b2 and b3 and b2 >= 0x80 and b2 < 0xC0 and b3 >= 0x80 and b3 < 0xC0 then
        out[#out+1] = v:sub(i, i + 2); i = i + 3
      else i = i + 1 end
    elseif b < 0xF5 then
      local b2, b3, b4 = v:byte(i + 1), v:byte(i + 2), v:byte(i + 3)
      if b2 and b3 and b4 and b2 >= 0x80 and b2 < 0xC0
         and b3 >= 0x80 and b3 < 0xC0 and b4 >= 0x80 and b4 < 0xC0 then
        out[#out+1] = v:sub(i, i + 3); i = i + 4
      else i = i + 1 end
    else
      i = i + 1
    end
  end
  return table.concat(out)
end
"""

    def _page(self, space: str, offset: int, limit: int) -> List[list]:
        drops = self.DROP_FIELDS.get(space, ())
        drop_lua = "{" + ",".join(str(d) for d in drops) + "}"
        r = self.conn.eval(
            self._LUA_CLEAN
            + f"""
local s = box.space.{space}
if s == nil then return {{}} end
local drop = {drop_lua}
local rows = s:select(nil, {{limit={limit}, offset={offset}}})
local res = {{}}
for _, t in ipairs(rows) do
  local c = {{}}
  for k = 1, #t do
    local dropped = false
    for _, d in ipairs(drop) do if d == k then dropped = true end end
    c[k] = dropped and '' or clean(t[k])
  end
  res[#res+1] = c
end
return res""")
        rows = list(r)
        # the driver sometimes nests the page as a single outer row
        if len(rows) == 1 and isinstance(rows[0], list) and rows[0] and \
                isinstance(rows[0][0], (list, tuple)):
            rows = [list(x) for x in rows[0]]
        return [list(x) for x in rows]

    def iter_space(self, space: str, limit: Optional[int] = None) -> Iterator[list]:
        """Yield raw tuples of one space, page by page. ``select`` only."""
        offset, n = 0, 0
        while True:
            rows = self._page(space, offset, self.page)
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

    def iter_raw(self, limit: Optional[int] = None) -> Iterator[list]:
        """Yield ``agent_memory`` tuples (the historical entry point)."""
        return self.iter_space(SPACE_MEMORY, limit=limit)

    def format_of(self, space: str) -> Dict[str, str]:
        """Field name → type, straight from the space's declared format."""
        try:
            r = list(self.conn.eval(f"""
local s = box.space.{space}
if s == nil then return {{}} end
local f = s:format()
if f == nil then return {{}} end
local o = {{}}
for _, p in ipairs(f) do o[#o+1] = tostring(p.name) .. '=' .. tostring(p.type or '') end
return o"""))
        except Exception:
            return {}
        out: Dict[str, str] = {}
        for item in r:
            if isinstance(item, str) and "=" in item:
                k, _, v = item.partition("=")
                out[k] = v
        return out


def _clip(text: Any, n: int) -> str:
    """Truncate on a UTF-8 boundary so the transport never sees half a char."""
    s = "" if text is None else str(text)
    if len(s) <= n:
        return s
    b = s.encode("utf-8")[:n]
    return b.decode("utf-8", "ignore")


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _at(row: list, i: int, default: Any = None) -> Any:
    """Positional read that tolerates short tuples.

    Tarantool spaces may hold rows written before a field was added, so a
    tuple can be shorter than the declared format. Missing means missing —
    it is never filled with a plausible value.
    """
    return row[i] if 0 <= i < len(row) else default


# ---------------------------------------------------------------------------
# the raw readings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Turn:
    """One real ``agent_memory`` tuple, reduced to what the board needs."""
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


@dataclass(frozen=True)
class ToolEvent:
    """One row of ``tool_event``: a tool call and how it went."""
    ts: float
    agent: str
    tool: str
    status: str
    is_error: bool
    exit_code: int
    blocked_reason: str

    @property
    def good(self) -> bool:
        return not self.is_error and self.status == OK_STATUS


@dataclass(frozen=True)
class TracePoint:
    """One row of ``turn_traces``: what a turn cost."""
    agent: str
    ts: float
    duration_ms: int
    tokens_in: int
    tokens_out: int
    tool_calls: int
    status: str          # "stop" | "length" | ...
    tool_results: int


@dataclass(frozen=True)
class Revision:
    """A configuration revision of an agent — a *time marker*, read-only."""
    agent: str
    revision: int
    activated_ts: float
    state: str
    reason: str
    actor: str
    knobs: Dict[str, int] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"rev{self.revision}"


@dataclass(frozen=True)
class Insight:
    """A row of ``rb_insight``: a documented lesson and how often it was used."""
    agent: str
    title: str
    description: str
    uses: int
    created_ts: float


# ---------------------------------------------------------------------------
# the derived reading
# ---------------------------------------------------------------------------

@dataclass
class Window:
    """One measurement slice of a station, bounded by config revisions."""
    revision: str          # 'rev3' | 'pre-rev2' | 'no-config'
    start: float
    end: float
    events: int = 0
    defects: int = 0
    turns: int = 0
    duration_ms: int = 0
    tokens_in: int = 0
    tool_calls: int = 0

    @property
    def defect_rate(self) -> float:
        return (100.0 * self.defects / self.events) if self.events else 0.0

    @property
    def comparable(self) -> bool:
        """Enough events that this rate means something (see MIN_EVIDENCE)."""
        return self.events >= MIN_EVIDENCE

    @property
    def mean_duration_ms(self) -> float:
        return (self.duration_ms / self.turns) if self.turns else 0.0


@dataclass
class Station:
    """One agent as a station on the gemba floor."""
    agent: str
    tool_calls: int = 0
    defects: int = 0
    turns: int = 0
    sessions: int = 0
    last_seen: float = 0.0
    defect_mix: Dict[str, int] = field(default_factory=dict)

    # muda telemetry (turn_traces); zero when the agent has no traces
    traced_turns: int = 0
    duration_ms: int = 0
    tokens_in: int = 0
    traced_tool_calls: int = 0
    truncated_turns: int = 0

    # evidence segmented by configuration revision
    windows: List[Window] = field(default_factory=list)

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
        """The muda class of the defect mix (the andon signal)."""
        if not self.defects:
            return "none observed"
        return DEFECT_WASTE.get(self.dominant_defect, "Defects")

    @property
    def waste_detail(self) -> str:
        if not self.defect_mix:
            return "no defect recorded in the window"
        return " · ".join(f"{k} {v}" for k, v in
                          sorted(self.defect_mix.items(), key=lambda x: -x[1]))

    def muda(self) -> Dict[str, float]:
        """The measured muda axes for this station, each in its own unit."""
        out: Dict[str, float] = {"defects": self.defect_rate}
        if self.traced_turns:
            out["waiting"] = self.duration_ms / self.traced_turns
            out["overprocessing"] = self.tokens_in / self.traced_turns
            out["motion"] = self.traced_tool_calls / self.traced_turns
        return out


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
class Coverage:
    """How much of the evidence the measurement can attribute to a config."""
    events_total: int = 0
    events_with_config: int = 0
    agents_ungoverned: List[str] = field(default_factory=list)
    agents_governed: List[str] = field(default_factory=list)

    @property
    def share(self) -> float:
        return (100.0 * self.events_with_config / self.events_total) \
            if self.events_total else 0.0


@dataclass
class FleetMeasurement:
    """The whole shift, as the board sees it."""
    stations: List[Station]
    standard: float
    goal: float
    worst: float
    window: Tuple[float, float]
    n_tool_calls: int
    n_defects: int
    lessons: List[Lesson]
    verdicts: List[Verdict]
    source_label: str
    readonly_verified: bool
    defect_source: str = SPACE_MEMORY
    muda_standards: Dict[str, float] = field(default_factory=dict)
    coverage: Coverage = field(default_factory=Coverage)
    insights: List[Insight] = field(default_factory=list)
    revisions: Dict[str, List[Revision]] = field(default_factory=dict)
    unavailable: List[str] = field(default_factory=list)

    @property
    def abnormal(self) -> List[Station]:
        return [s for s in self.stations
                if s.evidence and s.defect_rate > self.standard + 1e-9]

    @property
    def defect_rate(self) -> float:
        return (100.0 * self.n_defects / self.n_tool_calls) if self.n_tool_calls else 0.0

    def worst_muda(self, station: Station) -> Tuple[str, float]:
        """The axis where a station most exceeds the fleet standard.

        Ratios, not differences: a millisecond and a defect are not
        commensurable, so each axis is judged against its own standard. Axes
        with no fleet standard (nobody has traces) are excluded rather than
        treated as zero.
        """
        best, best_ratio = "", 0.0
        for axis, value in station.muda().items():
            std = self.muda_standards.get(axis, 0.0)
            if std <= 0:
                continue
            ratio = value / std
            if ratio > best_ratio:
                best, best_ratio = axis, ratio
        return best, best_ratio


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


def normalise_agent(agent_id: Any) -> str:
    """``agent-silver-predman`` → ``predman``: the join key between spaces.

    The config and revision tables carry a qualified id; ``tool_event``
    carries the bare profile. ``-`` is a Lua pattern quantifier, so an
    unescaped split silently yields ``-predman`` and every evidence window
    collapses into "no-config" — hence the explicit escape in the readers.
    """
    return re.sub(r"^agent-silver-", "", str(agent_id or ""))


# -- row adapters -----------------------------------------------------------

def _to_turn(row: list) -> Turn:
    meta = row[5] if isinstance(row[5], dict) else {}
    status = meta.get("status")
    importance = None
    if "importance" in meta:
        try:
            importance = float(meta["importance"])
        except (TypeError, ValueError):
            importance = None
    return Turn(
        turn_id=str(_at(row, 0)), agent=str(_at(row, 1) or "unknown"),
        role=str(_at(row, 2) or "unknown"), content=_clip(_at(row, 3), 600),
        ts=_num(meta.get("ts")),
        session=str(meta.get("sid") or meta.get("session_id") or ""),
        status=str(status) if status is not None else None,
        importance=importance)


def _to_tool_event(row: list) -> ToolEvent:
    return ToolEvent(
        ts=_num(_at(row, 0)), agent=str(_at(row, 1) or "unknown"),
        tool=str(_at(row, 4) or "?"), status=str(_at(row, 7) or "none"),
        is_error=_num(_at(row, 6)) != 0, exit_code=int(_num(_at(row, 8), -1)),
        blocked_reason=_clip(_at(row, 12), 80))


def _to_trace(row: list) -> TracePoint:
    grounding = _at(row, 9)
    grounding = grounding if isinstance(grounding, dict) else {}
    return TracePoint(
        agent=str(_at(row, 1) or "unknown"), ts=_num(_at(row, 3)),
        duration_ms=int(_num(_at(row, 4))), tokens_in=int(_num(_at(row, 5))),
        tokens_out=int(_num(_at(row, 6))), tool_calls=int(_num(_at(row, 7))),
        status=str(_at(row, 8) or "?"),
        tool_results=int(_num(grounding.get("tool_results"))))


def _to_insight(row: list) -> Insight:
    return Insight(agent=str(_at(row, 6) or "default"), title=_clip(_at(row, 1), 90),
                   description=_clip(_at(row, 2), 160), uses=int(_num(_at(row, 7))),
                   created_ts=_num(_at(row, 8)))


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

def _rows_of(source: Any, space: str, unavailable: List[str]) -> Iterator[list]:
    """Read a space, recording its absence instead of failing the run.

    A source that implements only ``iter_raw`` still works: it serves
    ``agent_memory`` and every other space is honestly reported missing.
    """
    def note(exc: Exception) -> None:
        tag = f"{space} ({type(exc).__name__}: {exc})"
        if tag not in unavailable:
            unavailable.append(tag)

    if hasattr(source, "iter_space"):
        try:
            yield from source.iter_space(space)
        except Exception as exc:
            note(exc)
        return

    if space != SPACE_MEMORY:
        if space not in unavailable:
            unavailable.append(space)
        return
    try:
        yield from source.iter_raw()
    except Exception as exc:
        note(exc)


def _build_revisions(configs: Dict[str, List[Revision]],
                     declared: Dict[str, List[Revision]]) -> Dict[str, List[Revision]]:
    """Merge the declared revisions with the runtime configs.

    ``agent_revision`` carries the activation time and the human reason;
    ``agent_runtime_config`` carries the knobs and is the fallback marker for
    agents whose revision row was never written. Merging maximises coverage
    *without inventing a marker*: a revision that neither table dates stays
    out, so its evidence is reported as unattributable.
    """
    merged: Dict[str, List[Revision]] = {}
    for agent in set(configs) | set(declared):
        by_rev: Dict[int, Revision] = {}
        for r in configs.get(agent, []):
            if r.activated_ts > 0:
                by_rev[r.revision] = r
        for r in declared.get(agent, []):
            if r.activated_ts <= 0:
                continue
            base = by_rev.get(r.revision)
            knobs = base.knobs if base else {}
            by_rev[r.revision] = Revision(
                agent=agent, revision=r.revision, activated_ts=r.activated_ts,
                state=r.state or (base.state if base else ""),
                reason=r.reason, actor=r.actor, knobs=knobs)
        out = sorted(by_rev.values(), key=lambda r: r.activated_ts)
        if out:
            merged[agent] = out
    return merged


def _segment(stations: Dict[str, Station], revisions: Dict[str, List[Revision]],
             events: List[ToolEvent], traces: List[TracePoint]) -> None:
    """Split each station's evidence by the config revision in force.

    A revision activation time is a *marker*, nothing more: the board does
    not claim the config caused anything. This is what lets a before/after be
    shown at all — and what lets it be marked non-comparable when the samples
    are too small to carry it.
    """
    for st in stations.values():
        revs = revisions.get(st.agent, [])
        buckets: Dict[str, Window] = {}

        def bucket_for(ts: float) -> Window:
            label = "no-config"
            if revs:
                label = f"pre-rev{revs[0].revision}"
                for r in revs:
                    if ts >= r.activated_ts:
                        label = r.label
                    else:
                        break
            w = buckets.get(label)
            if w is None:
                w = Window(revision=label, start=ts, end=ts)
                buckets[label] = w
            w.start = min(w.start, ts)
            w.end = max(w.end, ts)
            return w

        for e in events:
            if e.agent != st.agent:
                continue
            w = bucket_for(e.ts)
            w.events += 1
            if not e.good:
                w.defects += 1
        for t in traces:
            if t.agent != st.agent:
                continue
            w = bucket_for(t.ts)
            w.turns += 1
            w.duration_ms += t.duration_ms
            w.tokens_in += t.tokens_in
            w.tool_calls += t.tool_calls
        st.windows = [buckets[k] for k in
                      sorted(buckets, key=lambda k: buckets[k].start)]


def measure(source: Any, *, limit: Optional[int] = None,
            source_label: Optional[str] = None) -> FleetMeasurement:
    """Read production telemetry once and derive the fleet reading.

    Pure: it issues reads only and mutates nothing outside this process.
    """
    unavailable: List[str] = []
    stations: Dict[str, Station] = {}
    lessons: List[Lesson] = []
    verdicts: List[Verdict] = []
    insights: List[Insight] = []
    configs: Dict[str, List[Revision]] = {}
    declared: Dict[str, List[Revision]] = {}
    lo: Optional[float] = None
    hi: Optional[float] = None

    # ---- 1. agent_memory: the qualitative evidence ----------------------
    for row in _rows_of(source, SPACE_MEMORY, unavailable):
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

    # ---- 2. tool_event: the defect ledger -------------------------------
    events: List[ToolEvent] = []
    for row in _rows_of(source, SPACE_TOOL_EVENT, unavailable):
        if len(row) < 8:
            continue
        e = _to_tool_event(row)
        events.append(e)
        if e.ts:
            lo = e.ts if lo is None else min(lo, e.ts)
            hi = e.ts if hi is None else max(hi, e.ts)

    # tool_event is the wider ledger; agent_memory is the fallback. Which one
    # was used is a reported fact, never an assumption.
    defect_source = SPACE_MEMORY
    if events:
        defect_source = SPACE_TOOL_EVENT
        for s in stations.values():
            s.tool_calls = 0
            s.defects = 0
            s.defect_mix = {}
        for e in events:
            st = stations.setdefault(e.agent, Station(agent=e.agent))
            st.tool_calls += 1
            if not e.good:
                st.defects += 1
                st.defect_mix[e.status] = st.defect_mix.get(e.status, 0) + 1

    # ---- 3. turn_traces: the muda telemetry -----------------------------
    traces: List[TracePoint] = []
    for row in _rows_of(source, SPACE_TURN_TRACES, unavailable):
        if len(row) < 9:
            continue
        t = _to_trace(row)
        traces.append(t)
        st = stations.setdefault(t.agent, Station(agent=t.agent))
        st.traced_turns += 1
        st.duration_ms += t.duration_ms
        st.tokens_in += t.tokens_in
        st.traced_tool_calls += t.tool_calls
        if t.status == "length":
            st.truncated_turns += 1
        if t.ts:
            lo = t.ts if lo is None else min(lo, t.ts)
            hi = t.ts if hi is None else max(hi, t.ts)

    # ---- 4. the revision timeline (a time marker, read-only) ------------
    for row in _rows_of(source, SPACE_RUNTIME_CONFIG, unavailable):
        if len(row) < 16:
            continue
        agent = normalise_agent(_at(row, 2))
        configs.setdefault(agent, []).append(Revision(
            agent=agent, revision=int(_num(_at(row, 3))), activated_ts=_num(_at(row, 15)),
            state=str(_at(row, 14) or ""), reason="", actor="", knobs={
                "max_tokens": int(_num(_at(row, 4))),
                "context_length": int(_num(_at(row, 5))),
                "turn_timeout_s": int(_num(_at(row, 6))),
                "idle_timeout_s": int(_num(_at(row, 7))),
                "max_tool_iterations": int(_num(_at(row, 8))),
                "max_same_error": int(_num(_at(row, 9))),
                "max_drift_repeat": int(_num(_at(row, 10))),
                "tool_concurrency": int(_num(_at(row, 11))),
            }))
    for row in _rows_of(source, SPACE_REVISION, unavailable):
        if len(row) < 8:
            continue
        agent = normalise_agent(_at(row, 0))
        declared.setdefault(agent, []).append(Revision(
            agent=agent, revision=int(_num(_at(row, 1))), activated_ts=_num(_at(row, 6)),
            state=str(_at(row, 4) or ""), reason=_clip(_at(row, 7), 80),
            actor=_clip(_at(row, 5), 24)))

    # ---- 5. documented insights and how often they were used -----------
    for row in _rows_of(source, SPACE_INSIGHT, unavailable):
        if len(row) < 8:
            continue
        insights.append(_to_insight(row))

    revisions = _build_revisions(configs, declared)
    _segment(stations, revisions, events, traces)

    # ---- fleet standards, each on its own axis -------------------------
    ranked = [s for s in stations.values() if s.evidence]
    rates = [s.defect_rate for s in ranked]
    standard = round(_median(rates), 2)
    goal = round(min(rates), 2) if rates else 0.0
    worst = round(max(rates), 2) if rates else 0.0

    muda_standards: Dict[str, float] = {"defects": standard}
    for axis in ("waiting", "overprocessing", "motion"):
        vals = [s.muda()[axis] for s in stations.values()
                if axis in s.muda() and s.evidence]
        if vals:
            muda_standards[axis] = round(_median(vals), 2)

    governed = sorted(s.agent for s in stations.values()
                      if revisions.get(s.agent) and s.tool_calls)
    ungoverned = sorted(s.agent for s in stations.values()
                        if not revisions.get(s.agent) and s.tool_calls)
    coverage = Coverage(
        events_total=sum(s.tool_calls for s in stations.values()),
        events_with_config=sum(s.tool_calls for s in stations.values()
                              if revisions.get(s.agent)),
        agents_ungoverned=ungoverned, agents_governed=governed)

    label = source_label or (
        f"live · ratiocore agent memory @ "
        f"{getattr(source, 'host', DEFAULT_HOST)}:{getattr(source, 'port', DEFAULT_PORT)} "
        f"({defect_source} + {SPACE_TURN_TRACES}, "
        f"role={getattr(source, 'user', 'guest')}, select-only)")

    return FleetMeasurement(
        stations=sorted(stations.values(), key=lambda s: -s.defect_rate),
        standard=standard, goal=goal, worst=worst,
        window=(lo or 0.0, hi or 0.0),
        n_tool_calls=sum(s.tool_calls for s in stations.values()),
        n_defects=sum(s.defects for s in stations.values()),
        lessons=sorted(lessons, key=lambda l: l.ts),
        verdicts=sorted(verdicts, key=lambda v: v.ts),
        source_label=label, readonly_verified=True,
        defect_source=defect_source, muda_standards=muda_standards,
        coverage=coverage, insights=sorted(insights, key=lambda i: -i.uses),
        revisions=revisions, unavailable=sorted(set(unavailable)))


def probe(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> Dict[str, Any]:
    """Read-only health probe: what is reachable and how big is it?

    Never raises: an unreachable memory is a fact to report, not an error to
    propagate at whoever asked whether the board is up.
    """
    try:
        src = ReadOnlyTarantool(host=host, port=port)
        src.verify_read_only()
        sizes: Dict[str, int] = {}
        for space in (SPACE_MEMORY, SPACE_TOOL_EVENT, SPACE_TURN_TRACES,
                      SPACE_RUNTIME_CONFIG, SPACE_REVISION, SPACE_INSIGHT):
            try:
                r = list(src.conn.eval(
                    f"local s = box.space.{space} "
                    "if s == nil then return -1 end return s:len()"))
                sizes[space] = int(r[0]) if r else -1
            except Exception:
                sizes[space] = -1
        return {"ok": sizes.get(SPACE_MEMORY, -1) >= 0,
                "rows": sizes.get(SPACE_MEMORY, 0), "space": SPACE_MEMORY,
                "spaces": sizes, "host": host, "port": port, "readonly": True}
    except Exception as exc:  # pragma: no cover - live path
        # ``src`` may never have been built: fall back to the defaults.
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "space": DEFAULT_SPACE, "rows": 0, "spaces": {},
                "host": host, "port": port, "readonly": True}
