"""Build the Gemba Board from LIVE production memory (read-only).

Emits exactly the frame contract ``dashboard/capture.py`` emits, so all seven
views replay it unchanged — the difference is that every number here is a
count of real tuples in ``box.space.agent_memory``, and nothing is invented.

**What the live board may and may not claim.** Toyota's cycle starts with
genchi genbutsu — go and see. That is precisely what a read-only observer can
do, so live mode performs steps 1 and 2 of Toyota Business Practices (clarify
the problem, break it down) and *stops*: target-setting, root-cause analysis,
countermeasures, experiments, checks and standardisation all require an owner
to act, and writing them back into production memory is exactly what this
wiring is forbidden to do. Those steps are therefore reported as not
performed, never faked.

Consequences, stated plainly on the board:

* the wheel shows two steps lit out of ten — the loop has not been run;
* a station's standard is the fleet median, marked ``from_experiment: None``
  (an established practice, not a verified one);
* the worst station has no root cause and no countermeasure, because none is
  recorded in memory — the A3 shows that hole rather than filling it.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional

from .source import FleetMeasurement, Lesson, ReadOnlyTarantool, measure

BOARD_AGENT = "cimemory"
OBSERVER = "gemba-observer"

# The only two TBP steps a read-only observer legitimately performs.
OBSERVED_STEPS = ["1-clarify", "2-breakdown"]

STEPS = ["1-clarify", "2-breakdown", "3-target", "4-root-cause",
         "5-countermeasures", "6-do", "7-check", "8-hansei",
         "8-standardise", "8-yokoten"]

PDCA = {
    "1-clarify": "Plan", "2-breakdown": "Plan", "3-target": "Plan",
    "4-root-cause": "Plan", "5-countermeasures": "Plan",
    "6-do": "Do", "7-check": "Check",
    "8-hansei": "Act", "8-standardise": "Act", "8-yokoten": "Act",
}

NOT_PERFORMED = (
    "not performed — a read-only observer may see and stratify the gap, but "
    "acting on it would mean writing improvement work back into production "
    "memory, which this wiring is forbidden to do"
)

_WORKSPACE = re.compile(r"(/(?:home/[\w.-]+/)?[\w./-]*?wt-[\w-]+|/projects/[\w-]+)")
_FILEISH = re.compile(r"\b((?:tests?/)?[\w-]+\.py)\b")


def _iso(ts: float) -> str:
    if not ts:
        return "—"
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _recurrence(lessons: List[Lesson]) -> Dict[str, List[Lesson]]:
    """Group lessons that name the *same* failing artefact.

    A signature that appears in more than one lesson, spread over time, is
    the real signal that a documented countermeasure was never spread —
    Toyota's yokoten failure, measured instead of asserted.
    """
    groups: Dict[str, List[Lesson]] = {}
    for l in lessons:
        m = _FILEISH.search(l.text or "")
        key = m.group(1) if m else None
        if not key:
            continue
        groups.setdefault(key, []).append(l)
    return {k: v for k, v in groups.items() if len(v) > 1}


class LiveCapture:
    """Frame emitter over a real fleet measurement."""

    def __init__(self, m: FleetMeasurement) -> None:
        self.m = m
        self.frames: List[dict] = []
        self.i = 0
        self.tally: Dict[str, int] = {}
        self.active: Optional[str] = None
        self.recurrence = _recurrence(m.lessons)
        self.t0 = m.window[0] or 0.0
        self._reasons: Dict[str, str] = {}

    # -- helpers ----------------------------------------------------------
    def _stations_meta(self) -> Dict[str, dict]:
        out = {}
        for s in self.m.stations:
            out[s.agent] = {
                "label": s.agent,
                "metric": "defect_rate_per_100_tool_calls",
                "unit": "per 100",
                "waste": s.waste,
                "waste_detail": s.waste_detail,
                "ideal": ("every tool call returns ok on the first pass "
                          "(first-pass yield 100)"),
                "direction": "decrease",
            }
        return out

    def _board(self) -> Dict[str, dict]:
        std, goal = self.m.standard, self.m.goal
        out = {}
        for s in self.m.stations:
            if not s.tool_calls:
                status = "no data"
            elif not s.evidence:
                status = "low evidence"
            elif s.defect_rate > std + 1e-9:
                status = "abnormal"
            else:
                status = "normal"
            out[s.agent] = {
                "label": s.agent,
                "metric": "defect_rate_per_100_tool_calls",
                "unit": "per 100",
                "standard": round(std, 2),
                "actual": round(s.defect_rate, 2),
                "goal": round(goal, 2),
                "status": status,
                "waste": s.waste,
                "waste_detail": s.waste_detail,
                "direction": "decrease",
            }
        return out

    def _store(self) -> Dict[str, Any]:
        m = self.m
        ts_end = m.window[1]
        standards = [{
            "id": f"std-{s.agent}",
            "capability": s.agent,
            "version": 1,
            "active": True,
            "description": (f"fleet standard work: defect rate <= {m.standard} "
                            f"per 100 tool calls (median over the window)"),
            "from_experiment": None,
            "ts": ts_end,
        } for s in m.stations if s.evidence]

        problems = []
        for s in m.abnormal:
            problems.append({
                "id": f"gap-{s.agent}",
                "capability": s.agent,
                "status": "open",
                "gap": (f"{s.defect_rate:.2f} per 100 against a standard of "
                        f"{m.standard} per 100 — {s.defect_rate - m.standard:+.2f}"),
                "ideal": "every tool call returns ok on the first pass",
                "actual": f"{s.defects} of {s.tool_calls} tool calls failed",
                "breakdown": [f"{k} {v}" for k, v in
                              sorted(s.defect_mix.items(), key=lambda x: -x[1])],
                "priority_point": (f"{s.dominant_defect} "
                                   f"({s.defect_mix.get(s.dominant_defect, 0)} of "
                                   f"{s.defects} defects)"),
                "opened_ts": ts_end,
            })
        for v in m.verdicts:
            if v.outcome != "failed":
                continue
            problems.append({
                "id": f"outcome-{int(v.ts)}",
                "capability": v.agent,
                "status": "open",
                "gap": f"task ended {v.outcome} after {v.attempts} attempt(s)",
                "ideal": "the criterion is met on the first attempt",
                "actual": " · ".join(v.trace) or "no attempt trace recorded",
                "breakdown": v.trace,
                "priority_point": v.trace[0] if v.trace else "",
                "opened_ts": v.ts,
            })

        countermeasures = [{
            "id": f"lesson-{int(l.ts)}-{i}",
            "problem_id": None,
            "description": l.text,
            "strength": l.strength,
            "expected_effect": "",       # unknowable from memory alone
            "cost": "unknown",
            "risk": "unknown",
        } for i, l in enumerate(m.lessons)]

        root_causes = [{
            "id": f"rc-{int(l.ts)}-{i}",
            "problem_id": None,
            "statement": l.text,
            "verified_by": f"agent's own note ({l.basis})" if l.basis else "",
            "verified": l.strength == "taisaku",
        } for i, l in enumerate(m.lessons) if l.strength in ("taisaku", "mizen_boushi")]

        whys: List[dict] = []
        for v in m.verdicts:
            if v.outcome != "failed":
                continue
            pid = f"outcome-{int(v.ts)}"
            chain = [
                (f"Why did the task end {v.outcome}?",
                 f"the criterion failed on every one of {v.attempts} attempts",
                 " · ".join(v.trace) or "attempt trace in memory"),
            ]
            sig = _FILEISH.search(v.subject or "")
            cause = None
            if sig is not None:
                cause = next((l for l in m.lessons
                              if sig.group(1) in (l.text or "")), None)
            if cause is not None:
                # Level 2 quotes the agent's own note rather than asserting a
                # cause: the note may itself be a suspicion, and the board must
                # not launder a suspicion into a root cause.
                chain.append((
                    "What did the run itself record about this failure?",
                    cause.text[:220],
                    f"{cause.agent}'s own note, {_iso(cause.ts)}"))
            whys.extend({
                "id": f"{pid}-w{n}", "problem_id": pid, "level": n,
                "question": q, "answer": a, "evidence": e,
            } for n, (q, a, e) in enumerate(chain, start=1))

        spreads = [{
            "id": f"yokoten-{key}-{i}",
            "standard_id": f"std-{group[0].agent}",
            "from_agent": group[0].agent,
            "targets": sorted({l.agent for l in group}) or [group[0].agent],
            "rationale": (f"{key} fails again in {len(group)} separate notes "
                          f"({_iso(group[0].ts)} → {_iso(group[-1].ts)}): the "
                          "countermeasure was written down but never spread"),
            "applied": False,
            "ts": group[-1].ts,
        } for i, (key, group) in enumerate(sorted(
            self.recurrence.items(), key=lambda kv: kv[1][-1].ts))]

        andons = [{
            "id": f"andon-{s.agent}",
            "agent": s.agent,
            "severity": "high" if s.defect_rate >= 2 * m.standard else "medium",
            "reason": (f"defect rate {s.defect_rate:.2f} per 100 is above the "
                       f"fleet standard of {m.standard} per 100 "
                       f"({s.defects} of {s.tool_calls} tool calls failed)"),
            "stopped": False,
            "resolved": False,
            "resolution": "",
            "ts": m.window[1],
            "resolved_ts": None,
        } for s in m.abnormal]

        return {
            "n_observation": m.n_tool_calls,
            "standards": standards,
            "problems": problems,
            "countermeasures": countermeasures,
            "root_causes": root_causes,
            "whys": whys,
            "andons": andons,
            "spreads": spreads,
        }

    def frame(self, kind: str, title: str, text: str = "", *, cap: Optional[str] = None,
              step: Optional[str] = None, problem_id: Optional[str] = None,
              andon_id: Optional[str] = None,
              extra: Optional[dict] = None) -> None:
        if step:
            self.tally[step] = self.tally.get(step, 0) + 1
        probe = cap or self.active
        line: Dict[str, Any] = {}
        if probe:
            s = next((x for x in self.m.stations if x.agent == probe), None)
            if s:
                line = {
                    "capability": probe,
                    "actual": round(s.defect_rate, 2),
                    "standard": round(self.m.standard, 2),
                    "goal": round(self.m.goal, 2),
                    "control": 0.0,
                    "unit": "per 100",
                }
        self.frames.append({
            "i": self.i,
            "sim_ts": self.m.window[1],
            "cycle": 1,
            "kind": kind,
            "title": title,
            "text": text,
            "agent": BOARD_AGENT,
            "step": step,
            "steps_done": list(self.tally),
            "steps_tally": dict(self.tally),
            "cap": probe,
            "problem_id": problem_id,
            "andon_id": andon_id,
            "line": line,
            "board": self._board(),
            "store": self._store(),
            "a3": self._a3(problem_id),
            "extra": extra or {},
        })
        self.i += 1

    # -- A3 -----------------------------------------------------------------
    def _a3(self, problem_id: Optional[str]) -> Optional[dict]:
        if not problem_id:
            return None
        prob = next((p for p in self._store()["problems"]
                     if p["id"] == problem_id), None)
        if prob is None:
            return None
        st = self._store()
        whys = [w for w in st["whys"] if w["problem_id"] == problem_id]
        return {
            "problem": prob,
            "whys": whys,
            # Never asserted: memory holds no verified root cause for a gap
            # the fleet has not analysed. The A3 shows the hole.
            "root_cause": None,
            "countermeasures": [],
            "target": None,
            "experiment": None,
            "check": None,
            "hansei": None,
            "standard": next((s for s in st["standards"]
                              if s["capability"] == prob["capability"]), None),
            "therefore_ok": False,
            "not_performed": NOT_PERFORMED,
        }


def build_live(source: Optional[ReadOnlyTarantool] = None,
               measurement: Optional[FleetMeasurement] = None,
               *, limit: Optional[int] = None) -> dict:
    """Read production memory and emit the board. Read-only, always."""
    if measurement is None:
        measurement = measure(source or ReadOnlyTarantool(), limit=limit)
    c = LiveCapture(measurement)
    m = measurement

    n_rows = sum(s.turns for s in m.stations)
    c.frame("idle", "Board opened · live memory",
            f"{m.source_label}. {n_rows} memory rows read, "
            f"{m.n_tool_calls} of them tool calls, over "
            f"{_iso(m.window[0])} → {_iso(m.window[1])}. "
            "Nothing is written back: this is observation, not improvement.",
            extra={"readonly": True, "rows": n_rows,
                   "source": m.source_label, "window": list(m.window)})

    c.frame("round", "1 · Clarify the problem",
            f"The fleet runs at {m.defect_rate:.2f} defects per 100 tool calls "
            f"({m.n_defects} of {m.n_tool_calls}). The standard is the fleet "
            f"median, {m.standard} per 100; the best demonstrated level is "
            f"{m.goal}.", step="1-clarify",
            extra={"fleet_defect_rate": round(m.defect_rate, 2),
                   "standard": m.standard, "goal": m.goal})

    for s in m.stations:
        if not s.tool_calls:
            continue
        c.frame("observe", f"Observe · {s.agent}", 
                f"{s.tool_calls} tool calls, {s.defects} without an ok status "
                f"→ {s.defect_rate:.2f} per 100 against the standard of "
                f"{m.standard}. {s.waste_detail}.",
                cap=s.agent)

    for s in m.abnormal:
        c.frame("andon", f"Andon · {s.agent}",
                f"{s.defect_rate:.2f} per 100 against a standard of "
                f"{m.standard} — the station is abnormal. "
                f"Dominant defect: {s.dominant_defect}.",
                cap=s.agent, andon_id=f"andon-{s.agent}",
                extra={"severity": "high" if s.defect_rate >= 2 * m.standard else "medium"})

    c.frame("round", "2 · Break down the problem",
            "Stratified by station and then by defect kind. The gap is not "
            "spread evenly: " + ", ".join(
                f"{s.agent} {s.defect_rate:.2f}" for s in m.abnormal) +
            " carry it.", step="2-breakdown",
            extra={"abnormal": [s.agent for s in m.abnormal]})

    if m.lessons:
        strongest = max(m.lessons, key=lambda l: {"taisho": 1, "taisaku": 2,
                                                  "mizen_boushi": 3}.get(l.strength, 0))
        c.frame("countermeasure", "Countermeasures already on record",
                f"{len(m.lessons)} lessons are documented in memory. The "
                f"strongest class on file is {strongest.strength}. They were "
                "written by the agents themselves, not by this board.",
                extra={"lessons": len(m.lessons), "strongest": strongest.strength})

    for key, group in c.recurrence.items():
        c.frame("spread", f"Yokoten check · {key}",
                f"{len(group)} separate notes mention {key}, from "
                f"{_iso(group[0].ts)} to {_iso(group[-1].ts)}. The countermeasure "
                "existed in writing and the defect still recurred: it was never "
                "spread.", extra={"applied": False, "recurrences": len(group)})

    if m.abnormal:
        worst = max(m.abnormal, key=lambda s: s.defect_rate)
        c.frame("a3", f"A3 · {worst.agent}",
                f"The largest gap on the board. Memory holds no root cause and "
                f"no countermeasure for it: {worst.agent} has never analysed "
                "this defect.",
                cap=worst.agent, problem_id=f"gap-{worst.agent}")

    c.frame("idle", "Where the loop stops",
            "Two steps performed of ten. Observing and stratifying a gap is "
            "read-only work; targeting, root-cause analysis, countermeasures, "
            "experiments, checks and standardisation all require an owner to "
            "act — and writing them back into production memory is what this "
            "wiring must not do. The board ends here on purpose.")

    meta = {
        "agent": BOARD_AGENT,
        "observer": OBSERVER,
        "siblings": sorted(s.agent for s in m.stations if s.tool_calls),
        "n_frames": len(c.frames),
        "n_cycles": 1,
        "stations": c._stations_meta(),
        "t0": m.window[0] or 0.0,
        "sim_step": 0,
        "steps": STEPS,
        "pdca": PDCA,
        # --- live-only, and deliberately loud about it -------------------
        "source": m.source_label,
        "mode": "live",
        "readonly": True,
        "window": list(m.window),
        "window_label": f"{_iso(m.window[0])} → {_iso(m.window[1])}",
        "standard_basis": "fleet median defect rate (established practice)",
        "goal_basis": "best demonstrated rate (evidence >= 30 tool calls)",
        "defect_basis": "tool calls whose recorded status is not 'ok'",
        "steps_performed": OBSERVED_STEPS,
        "steps_not_performed": NOT_PERFORMED,
        "loop_ran": False,
        "fleet": {"defect_rate": round(m.defect_rate, 2),
                  "tool_calls": m.n_tool_calls,
                  "defects": m.n_defects,
                  "open_andons": len(m.abnormal)},
        "verdict": None,
    }
    return {"meta": meta, "frames": c.frames}
