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
