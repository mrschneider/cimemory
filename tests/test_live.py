"""Tests for the live (read-only) wiring.

No Tarantool is needed: the source is injected. The most important test in
this file is ``test_the_module_cannot_write`` — the read-only promise is a
property of the code, so it is asserted against the code.
"""

from __future__ import annotations

import inspect
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cimemory.live import source as SRC  # noqa: E402
from cimemory.live.capture_live import build_live  # noqa: E402
from cimemory.live.source import (  # noqa: E402
    MIN_EVIDENCE, ReadOnlyTarantool, classify_strength, measure, probe,
)


# ---------------------------------------------------------------------------
# fixtures: a fake production
# ---------------------------------------------------------------------------

def turn(turn_id, agent, role, content="", ts=0.0, sid="s1", status=None):
    """One tuple exactly as box.space.agent_memory stores it."""
    meta = {"ts": ts, "sid": sid}
    if status is not None:
        meta["status"] = status
    return [turn_id, agent, role, content, [], meta]


def tool_turn(agent, ok_count=0, bad=None, ts=0.0):
    """Build ``ok_count`` good tool calls and the bad ones named in ``bad``."""
    rows = []
    for i in range(ok_count):
        rows.append(turn(f"t-{agent}-ok{i}", agent, "tool", "ok output",
                         ts=ts, status="ok"))
    for kind, n in (bad or {}).items():
        for i in range(n):
            rows.append(turn(f"t-{agent}-{kind}{i}", agent, "tool",
                             "failed output", ts=ts, status=kind))
    return rows


class FakeSource:
    """Stands in for ReadOnlyTarantool. Reads a list; writes nothing."""

    host, port, space, user = "fake", 0, "agent_memory", "guest"

    def __init__(self, rows):
        self.rows = rows
        self.pages = 0

    def iter_raw(self, limit=None):
        self.pages += 1
        for i, r in enumerate(self.rows):
            if limit is not None and i >= limit:
                return
            yield r

    def stats(self):
        return {"rows_read": len(self.rows), "space": self.space}


def fleet():
    """Three stations: one clearly worse than the other two.

    alpha 29/169, beta 3/100, gamma 0/40  -> standard (median) 3.0
    """
    rows = []
    rows += tool_turn("alpha", ok_count=140, bad={"validation_error": 18,
                                                  "nonzero_exit": 11})
    rows += tool_turn("beta", ok_count=97, bad={"nonzero_exit": 3})
    rows += tool_turn("gamma", ok_count=40)
    rows += [turn("l1", "alpha", "lesson",
                  "CAUSA REAL medida: o executor degenerou em 0 arquivos", ts=100),
             turn("l2", "alpha", "lesson",
                  "Suspeita: o executor editou outro diretório e nunca "
                  "escreveu util.py", ts=200),
             turn("l3", "beta", "lesson",
                  "o conftest exigia que o diretório do banco existisse", ts=300),
             turn("l4", "beta", "lesson",
                  "nota sem classificação nenhuma sobre o run", ts=400),
             turn("v1", "alpha", "outcome",
                  "outcome failed apos 3 tentativa(s) [a1:criterion_failed; "
                  "a2:criterion_failed; a3:criterion_failed] para: criar util.py",
                  ts=500),
             turn("v2", "alpha", "outcome",
                  "outcome done apos 2 tentativa(s) [a1:criterion_failed; "
                  "a2:verified] para: criar tests/util.py", ts=600)]
    return FakeSource(rows)


# ---------------------------------------------------------------------------
# the promise
# ---------------------------------------------------------------------------

def test_the_module_cannot_write():
    """The live source must contain no mutation call at all."""
    text = inspect.getsource(SRC)
    body = "\n".join(l for l in text.splitlines()
                     if not l.strip().startswith("#"))
    for forbidden in ("insert(", "replace(", "update(", "delete(",
                      "truncate(", "upsert(", "box.schema.user.grant"):
        assert forbidden not in body, f"live source contains {forbidden!r}"


def test_reader_exposes_no_write_method():
    public = [n for n in dir(ReadOnlyTarantool) if not n.startswith("_")]
    for forbidden in ("insert", "replace", "update", "delete", "truncate", "upsert"):
        assert forbidden not in public


def test_verify_read_only_refuses_a_writer():
    src = ReadOnlyTarantool(connect=lambda *a, **k: _FakeConn(
        [["read,write", "space", "agent_memory"]]))
    with pytest.raises(PermissionError):
        src.verify_read_only()


def test_verify_read_only_accepts_guest():
    src = ReadOnlyTarantool(connect=lambda *a, **k: _FakeConn(
        [["session,usage", "universe", ""]]))
    assert src.verify_read_only() is True


class _FakeConn:
    def __init__(self, grants):
        self.grants = grants

    def eval(self, _lua):
        return [self.grants]


# ---------------------------------------------------------------------------
# classification: the board must not promote a note into a fix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("CAUSA REAL medida: o executor degenerou", "taisaku"),
    ("Root cause: the daemon never wrote the artefact", "taisaku"),
    ("Suspeita: editou outro diretório", "taisho"),
    ("Hipótese: o worktree estava sujo", "taisho"),
    ("o conftest exigia que o diretório existisse", "mizen_boushi"),
    ("O verificador precisa rodar a suite", "mizen_boushi"),
    ("Tarefa falhou 3 vezes no workspace novo", "unclassified"),
    ("", "unclassified"),
])
def test_classify_strength(text, expected):
    got, basis = classify_strength(text)
    assert got == expected
    if expected == "unclassified":
        assert basis == ""
    else:
        assert basis  # the phrase that decided it is always exposed


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

def test_measure_builds_stations_and_standard():
    m = measure(fleet())
    by = {s.agent: s for s in m.stations}
    assert by["alpha"].tool_calls == 169
    assert by["alpha"].defects == 29
    assert by["alpha"].defect_rate == pytest.approx(17.16, abs=0.01)
    assert by["alpha"].first_pass_yield == pytest.approx(82.84, abs=0.01)
    assert by["beta"].defect_rate == pytest.approx(3.0, abs=0.01)
    assert by["gamma"].defects == 0
    # median of [0.0, 3.0, 17.16] = 3.0
    assert m.standard == pytest.approx(3.0, abs=0.01)
    assert m.goal == pytest.approx(0.0, abs=0.01)
    assert m.worst == pytest.approx(17.16, abs=0.01)


def test_median_is_the_middle_not_the_mean():
    """A mean would let one bad station redefine the standard."""
    m = measure(fleet())
    mean = (0 + 3 + 17.16) / 3
    assert m.standard != pytest.approx(mean, abs=0.4)


def test_only_stations_over_the_standard_raise_an_andon():
    m = measure(fleet())
    assert [s.agent for s in m.abnormal] == ["alpha"]


def test_small_samples_do_not_set_the_standard():
    """A 0% rate over 10 calls is not evidence; it must not become the goal."""
    rows = tool_turn("big", ok_count=90, bad={"error": 10})   # 10%
    rows += tool_turn("tiny", ok_count=10)                     # 0%, n < 30
    m = measure(FakeSource(rows))
    tiny = next(s for s in m.stations if s.agent == "tiny")
    assert tiny.evidence is False
    assert tiny.tool_calls == 10 < MIN_EVIDENCE
    assert tiny not in m.abnormal


def test_defect_mix_drives_the_waste_class():
    m = measure(FakeSource(tool_turn("a", ok_count=50, bad={"timeout": 5})))
    st = m.stations[0]
    assert st.dominant_defect == "timeout"
    assert st.waste == "Waiting"
    assert st.waste_detail == "timeout 5"


def test_verdicts_are_parsed_from_the_real_line():
    m = measure(fleet())
    failed = [v for v in m.verdicts if v.outcome == "failed"]
    assert len(failed) == 1
    v = failed[0]
    assert v.attempts == 3
    assert v.trace == ["a1:criterion_failed", "a2:criterion_failed",
                       "a3:criterion_failed"]
    assert v.subject.startswith("criar util.py")
    assert any(v.outcome == "done" for v in m.verdicts)


def test_measure_never_invents_a_window():
    m = measure(fleet())
    assert m.window == (100.0, 600.0)


def test_measure_is_pure_reads():
    src = fleet()
    measure(src)
    assert src.pages == 1


def test_probe_reports_failure_without_raising():
    """An unreachable memory is reported, not thrown at the caller."""
    from cimemory.live import source as S
    real_connect = S.ReadOnlyTarantool.__init__

    def boom(*a, **k):
        raise OSError("connection refused")

    S.ReadOnlyTarantool.__init__ = lambda self, **kw: boom()
    try:
        r = probe()
    finally:
        S.ReadOnlyTarantool.__init__ = real_connect
    assert r["ok"] is False and "OSError" in r["error"] and r["readonly"] is True


# ---------------------------------------------------------------------------
# the board built from live memory
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live():
    return build_live(measurement=measure(fleet()))


def test_frame_contract_matches_the_demo_capture(live):
    """Same keys as dashboard/capture.py emits, so the views need no changes."""
    from cimemory.dashboard.capture import build as build_demo
    demo = build_demo()
    assert set(live) == set(demo) == {"meta", "frames"}
    assert set(live["frames"][0]) == set(demo["frames"][0])


def test_live_meta_declares_what_it_is(live):
    m = live["meta"]
    assert m["mode"] == "live"
    assert m["readonly"] is True
    assert m["loop_ran"] is False
    assert m["verdict"] is None
    assert m["steps_performed"] == ["1-clarify", "2-breakdown"]
    assert m["steps_not_performed"]          # the refusal is stated, not implied
    assert m["fleet"]["open_andons"] == 1


def test_the_wheel_only_lights_the_steps_a_readonly_observer_performs(live):
    done = set()
    for f in live["frames"]:
        done |= set(f["steps_done"])
    assert done == {"1-clarify", "2-breakdown"}
    assert len(live["meta"]["steps"]) == 10  # the other eight stay dark


def test_one_andon_frame_per_abnormal_station(live):
    andon_frames = [f for f in live["frames"] if f["kind"] == "andon"]
    andons = live["frames"][-1]["store"]["andons"]
    assert len(andon_frames) == len(andons) == 1
    assert andons[0]["agent"] == "alpha"
    assert andons[0]["resolved"] is False
    assert andons[0]["severity"] == "high"   # 17.16 >= 2 * 3.0


def test_the_a3_shows_the_hole_instead_of_filling_it(live):
    a3 = next(f for f in live["frames"] if f["kind"] == "a3")["a3"]
    assert a3["problem"]["capability"] == "alpha"
    assert a3["root_cause"] is None
    assert a3["countermeasures"] == []
    assert a3["target"] is None
    assert a3["therefore_ok"] is False
    assert a3["not_performed"]


def test_standards_are_marked_as_never_verified(live):
    stds = live["frames"][0]["store"]["standards"]
    assert stds, "a station with evidence has a standard"
    for s in stds:
        assert s["from_experiment"] is None      # established, not verified
        assert s["active"] is True


def test_lessons_become_countermeasures_with_their_class(live):
    cms = live["frames"][0]["store"]["countermeasures"]
    classes = {c["strength"] for c in cms}
    assert classes <= {"taisho", "taisaku", "mizen_boushi", "unclassified"}
    assert "taisaku" in classes
    # an unclassifiable note is never promoted
    assert "unclassified" in classes


def test_whys_quote_the_note_rather_than_assert_a_cause(live):
    whys = live["frames"][-1]["store"]["whys"]
    assert whys
    assert all(w["evidence"] for w in whys), "every rung carries evidence"
    level2 = [w for w in whys if w["level"] == 2]
    assert level2, "the failing verdict has a note on file, so it gets a 2nd rung"
    assert any("own note" in w["evidence"] for w in level2)
    # level 2 answers with the note's own words, never with a cause we invented
    for w in level2:
        assert w["answer"].startswith(("Suspeita", "CAUSA", "o conftest", "nota"))


def test_a_verdict_with_no_note_gets_no_invented_rung():
    """No evidence, no rung. The board stops rather than speculate."""
    rows = [turn("v9", "solo", "outcome",
                 "outcome failed apos 3 tentativa(s) [a1:criterion_failed; "
                 "a2:criterion_failed; a3:criterion_failed] para: criar zzz.py",
                 ts=10)]
    rows += tool_turn("solo", ok_count=40, bad={"error": 2}, ts=11)
    data = build_live(measurement=measure(FakeSource(rows)))
    whys = data["frames"][-1]["store"]["whys"]
    assert [w["level"] for w in whys] == [1]


def test_board_marks_low_evidence_separately_from_abnormal(live):
    board = live["frames"][0]["board"]
    assert board["alpha"]["status"] == "abnormal"
    assert board["beta"]["status"] == "normal"
    assert board["gamma"]["status"] == "normal"
    # no station in this fixture has tool calls == 0, so none is "no data"
    assert all(v["standard"] == 3.0 for v in board.values())


def test_every_live_number_traces_to_a_tuple(live):
    """Each figure on the board must equal a count over the input tuples.

    This is the anti-fabrication test: if a number cannot be recomputed from
    the rows, it does not belong on the board.
    """
    rows = fleet().rows
    rows += []  # the tuples the fake production returned
    tools = [r for r in rows if r[2] == "tool"]
    m = measure(FakeSource(rows))

    assert m.n_tool_calls == len(tools) == 309
    assert m.n_defects == sum(1 for r in tools if r[5].get("status") != "ok") == 32
    assert m.defect_rate == pytest.approx(100.0 * 32 / 309, abs=0.01)

    # per-station mixes sum to that station's defect count
    for s in m.stations:
        assert sum(s.defect_mix.values()) == s.defects

    # the board restates the measurement, it does not recompute it
    board = live["frames"][0]["board"]
    by = {s.agent: s for s in m.stations}
    for agent, cell in board.items():
        assert cell["actual"] == round(by[agent].defect_rate, 2)
        assert cell["standard"] == round(m.standard, 2)

    # the andon text is the measurement, spelled out
    andon = live["frames"][-1]["store"]["andons"][0]
    assert f"{by['alpha'].defect_rate:.2f}" in andon["reason"]
    assert f"{by['alpha'].defects} of {by['alpha'].tool_calls}" in andon["reason"]


# ---------------------------------------------------------------------------
# the wider evidence base: tool_event, turn_traces, revisions, insights
# ---------------------------------------------------------------------------

def tool_event(ts, agent, tool="bash", status="ok", is_error=0, exit_code=0):
    """One tuple as box.space.tool_event stores it (13 fields)."""
    return [ts, agent, "sess", f"c-{agent}-{ts}", tool, "h", is_error, status,
            exit_code, "raw excerpt", 1, "raw args", ""]


def cfg(agent_id, revision, ts, **knobs):
    """One tuple as box.space.agent_runtime_config stores it (16 fields)."""
    k = {"max_tokens": 8000, "context_length": 128000, "turn_timeout_s": 1200,
         "idle_timeout_s": 900, "max_tool_iterations": 24, "max_same_error": 3,
         "max_drift_repeat": 2, "tool_concurrency": 4}
    k.update(knobs)
    return [f"cfg-{agent_id}-{revision}", "t1", agent_id, revision,
            k["max_tokens"], k["context_length"], k["turn_timeout_s"],
            k["idle_timeout_s"], k["max_tool_iterations"], k["max_same_error"],
            k["max_drift_repeat"], k["tool_concurrency"], "", "",
            "active", ts]


def revision(agent_id, rev, ts, reason="", actor="ops"):
    """One tuple as box.space.agent_revision stores it (8 fields)."""
    return [agent_id, rev, rev - 1, "snap", "active", actor, ts, reason]


def trace(agent, ts, duration_ms, tokens_in, tool_calls, status="stop"):
    """One tuple as box.space.turn_traces stores it (10 fields)."""
    return [f"tr-{agent}-{ts}", agent, "sess", ts, duration_ms, tokens_in,
            1000, tool_calls, status, {"tool_results": tool_calls}]


def insight(agent, title, uses, ts=1000.0):
    """One tuple as box.space.rb_insight stores it (9 fields)."""
    return [f"i-{title}", title, "desc", "content", [0.0] * 4, "cat", agent,
            uses, ts]


class MultiSource:
    """A fake production with several spaces. Raises for the ones it lacks."""

    host, port, space, user = "fake", 0, "agent_memory", "guest"

    def __init__(self, spaces):
        self.spaces = dict(spaces)
        self.reads = []

    def iter_space(self, space, limit=None):
        self.reads.append(space)
        if space not in self.spaces:
            raise SRC.SpaceUnavailable(f"{space} not readable")
        yield from self.spaces[space]

    def stats(self):
        return {"rows_read": sum(len(v) for v in self.spaces.values())}


def governed_world():
    """alpha: 3 revision windows, traces; beta: clean; no config for gamma.

    alpha  pre-rev1 (ts 100-250, n=60, 12 defects)   rev1 (ts 350-500, n=40, 4)
           rev2   (ts 700-750, n=5, 0 defects)       <- below the evidence floor
    beta   no-config (n=90, 0 defects)
    gamma  no-config (n=40, 0 defects), no config row  -> ungoverned
    """
    events = []
    for i in range(60):
        ts = 100 + i
        bad = i < 12
        events.append(tool_event(ts, "alpha", status="nonzero_exit" if bad else "ok",
                                 is_error=1 if bad else 0, exit_code=1 if bad else 0))
    for i in range(40):
        ts = 350 + i
        bad = i < 4
        events.append(tool_event(ts, "alpha", status="timeout" if bad else "ok",
                                 is_error=1 if bad else 0))
    for i in range(5):
        events.append(tool_event(700 + i, "alpha"))
    events += [tool_event(100 + i, "beta") for i in range(90)]
    events += [tool_event(100 + i, "gamma") for i in range(40)]

    spaces = {
        SRC.SPACE_MEMORY: [turn("t1", "alpha", "lesson",
                                "CAUSA REAL medida: degenerou", ts=150)],
        SRC.SPACE_TOOL_EVENT: events,
        SRC.SPACE_TURN_TRACES: [trace("alpha", 200, 60_000, 100_000, 10),
                                trace("alpha", 210, 60_000, 100_000, 10),
                                trace("alpha", 220, 60_000, 100_000, 10)],
        SRC.SPACE_RUNTIME_CONFIG: [cfg("agent-silver-alpha", 1, 300),
                                   cfg("agent-silver-alpha", 2, 600)],
        SRC.SPACE_REVISION: [revision("agent-silver-alpha", 1, 300, "first onboarding"),
                             revision("agent-silver-alpha", 2, 600, "raise iterations")],
        SRC.SPACE_INSIGHT: [insight("alpha", "Never used", 0, 900.0),
                            insight("beta", "In use", 3, 950.0)],
    }
    return MultiSource(spaces)


def test_tool_event_is_the_defect_ledger_when_it_is_readable():
    """The wider ledger wins, and the board says which one it used."""
    m = measure(governed_world())
    assert m.defect_source == SRC.SPACE_TOOL_EVENT
    # alpha 16 defects of 105 calls, beta 0/90, gamma 0/40
    assert m.n_tool_calls == 235
    assert m.n_defects == 16
    assert m.unavailable == []


def test_agent_memory_remains_the_fallback():
    """A source that only serves agent_memory still measures, and says so."""
    m = measure(FakeSource(fleet().rows))
    assert m.defect_source == SRC.SPACE_MEMORY
    assert m.n_tool_calls == 309
    # every space it could not read is named, not silently treated as empty
    assert SRC.SPACE_TOOL_EVENT in m.unavailable
    assert any(u.startswith(SRC.SPACE_TURN_TRACES) for u in m.unavailable)


def test_turn_traces_give_the_muda_axes():
    m = measure(governed_world())
    a = next(s for s in m.stations if s.agent == "alpha")
    assert a.traced_turns == 3
    assert a.muda()["waiting"] == pytest.approx(60_000)
    assert a.muda()["overprocessing"] == pytest.approx(100_000)
    assert a.muda()["motion"] == pytest.approx(10)
    # a station with no traces has no cost axes at all - not zeros
    g = next(s for s in m.stations if s.agent == "gamma")
    assert "waiting" not in g.muda()


def test_evidence_is_segmented_by_configuration_revision():
    m = measure(governed_world())
    a = next(s for s in m.stations if s.agent == "alpha")
    labels = [w.revision for w in a.windows]
    assert labels == ["pre-rev1", "rev1", "rev2"]
    pre, r1, r2 = a.windows
    assert (pre.events, pre.defects) == (60, 12)
    assert (r1.events, r1.defects) == (40, 4)
    assert (r2.events, r2.defects) == (5, 0)
    assert pre.defect_rate == pytest.approx(20.0)
    assert r1.defect_rate == pytest.approx(10.0)


def test_a_thin_window_is_marked_not_comparable():
    """A rate over 5 calls must never be shown as an improvement."""
    m = measure(governed_world())
    a = next(s for s in m.stations if s.agent == "alpha")
    pre, r1, r2 = a.windows
    assert pre.comparable and r1.comparable
    assert not r2.comparable          # 5 events < MIN_EVIDENCE
    assert r2.events < MIN_EVIDENCE


def test_the_revision_timeline_is_read_from_both_tables():
    """agent_revision carries the reason; the config is the fallback marker."""
    m = measure(governed_world())
    revs = m.revisions["alpha"]
    assert [r.revision for r in revs] == [1, 2]
    assert revs[1].reason == "raise iterations"
    assert revs[0].knobs["turn_timeout_s"] == 1200


def test_ungoverned_agents_are_reported_not_hidden():
    """gamma has no config row: its evidence exists and is unattributable."""
    m = measure(governed_world())
    assert "gamma" in m.coverage.agents_ungoverned
    assert "alpha" in m.coverage.agents_governed
    assert m.coverage.events_total == 235
    assert m.coverage.events_with_config == 105


def test_unused_insights_become_unapplied_spreads():
    """yokoten of a countermeasure that never entered practice."""
    m = measure(governed_world())
    live = build_live(measurement=m)
    spreads = live["frames"][-1]["store"]["spreads"]
    unused = [s for s in spreads if "never used since" in s["rationale"]]
    assert unused, "the unused insight must appear as a not-spread item"
    assert unused[0]["applied"] is False
    assert unused[0]["from_agent"] == "alpha"
    # the insight that is in use is not reported as unused
    assert all("In use" not in s["rationale"] for s in spreads)


def test_the_staircase_steps_are_real_windows():
    """.staircase draws the revision windows, not a single fictive standard."""
    live = build_live(measurement=measure(governed_world()))
    stds = [s for s in live["frames"][-1]["store"]["standards"]
            if s["capability"] == "alpha"]
    assert [s["version"] for s in stds] == [1, 2, 3]
    assert len([s for s in stds if s["active"]]) == 1
    assert stds[0]["active"] is False and stds[-1]["active"] is True
    assert "20.00 per 100 over 60 tool calls" in stds[0]["description"]
    assert "NOT COMPARABLE" in stds[-1]["description"]


def test_the_board_reports_the_coverage_of_its_own_evidence():
    live = build_live(measurement=measure(governed_world()))
    cov = live["meta"]["coverage"]
    assert cov["events_total"] == 235
    assert cov["events_with_config"] == 105          # only alpha has a config
    assert cov["share"] == pytest.approx(44.7, abs=0.1)
    assert cov["agents_ungoverned"] == ["beta", "gamma"]


def test_normalise_agent_survives_the_lua_pattern_trap():
    """'-' is a Lua quantifier: normalising it naively yields '-predman'."""
    assert SRC.normalise_agent("agent-silver-predman") == "predman"
    assert SRC.normalise_agent("predman") == "predman"
    assert SRC.normalise_agent(None) == ""
    assert not SRC.normalise_agent("agent-silver-predman").startswith("-")


def test_short_tuples_are_read_as_missing_not_as_values():
    """A tuple written before a field existed must not shift the reading."""
    from cimemory.live.source import _at
    assert _at([1, 2], 5) is None
    assert _at([1, 2], 1) == 2
    # 12 fields: one short of the declared format (blocked_reason missing)
    short = tool_event(100.0, "alpha")[:12]
    m = measure(MultiSource({SRC.SPACE_TOOL_EVENT: [short], SRC.SPACE_MEMORY: []}))
    assert m.n_tool_calls == 1
    assert m.n_defects == 0
    # a row too short to be a tool event at all is skipped, not guessed at
    tiny = measure(MultiSource({SRC.SPACE_TOOL_EVENT: [[100.0, "alpha", "s"]],
                                SRC.SPACE_MEMORY: []}))
    assert tiny.n_tool_calls == 0


def test_the_reader_drops_the_raw_payload_fields():
    """Excerpts and args are arbitrary bytes and are never transported."""
    drops = ReadOnlyTarantool.DROP_FIELDS
    assert 10 in drops[SRC.SPACE_TOOL_EVENT] and 12 in drops[SRC.SPACE_TOOL_EVENT]
    assert 5 in drops[SRC.SPACE_INSIGHT]      # the 1024-dim embedding
    # and the transport sanitises what it does carry
    assert "clean(" in ReadOnlyTarantool._LUA_CLEAN


def test_the_muda_class_is_chosen_against_its_own_standard():
    """Axes have different units, so the comparison is a ratio per axis."""
    m = measure(governed_world())
    a = next(s for s in m.stations if s.agent == "alpha")
    axis, ratio = m.worst_muda(a)
    # fabricated ratios: motion 40x, everything else at 1x
    m.muda_standards = {"defects": a.defect_rate, "waiting": a.muda()["waiting"],
                        "overprocessing": a.muda()["overprocessing"],
                        "motion": a.muda()["motion"] / 40.0}
    axis, ratio = m.worst_muda(a)
    assert axis == "motion"
    assert ratio == pytest.approx(40.0)
