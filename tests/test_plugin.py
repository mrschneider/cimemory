"""Tests for the cimemory plugin: contract, discipline, and the loop.

Run:  python -m pytest tests/ -q      (or)  python tests/test_plugin.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from cimemory import (  # noqa: E402
    CountermeasureSpec,
    CountermeasureStrength,
    DisciplineError,
    EvolutionMemory,
    InMemoryBackend,
    JsonlBackend,
    KaikakuNotApproved,
    KaizenLoop,
    KaizenSpec,
    SQLiteBackend,
    get_backend,
)

CAP = "test-capability"


@pytest.fixture(params=["memory", "sqlite", "jsonl"])
def mem(request, tmp_path):
    """A fresh backend per test — never share storage between tests."""
    name = request.param
    if name == "sqlite":
        backend = get_backend("sqlite", path=":memory:")
    elif name == "jsonl":
        backend = get_backend("jsonl", path=str(tmp_path / "t.jsonl"))
    else:
        backend = get_backend("memory")
    memory = EvolutionMemory(backend, agent="test-agent")
    yield memory
    backend.close()


def _spec(**overrides) -> KaizenSpec:
    base: dict[str, Any] = dict(
        capability=CAP,
        ideal="p95 latency <= 500ms",
        actual="p95 latency = 1800ms",
        gap="1300ms over standard",
        breakdown=["db round-trips", "serialization"],
        priority_point="db round-trips",
        metric="p95_latency_ms",
        goal=500.0,
        deadline="2026-12-01",
        whys=[
            ("Why 1800ms?", "N+1 queries in the join", "query log shows 42 queries"),
            ("Why N+1?", "the ORM loads rows lazily", "ORM lazy-load counter"),
        ],
        root_cause="lazy loading causes N+1 queries in the join path",
        root_cause_verified_by="query log + ORM counters",
        countermeasures=[CountermeasureSpec(
            "eager-load the join and batch the queries",
            strength=CountermeasureStrength.TAISAKU,
        )],
        hypothesis="eager loading cuts p95 to under 500ms",
        before_value=1800.0,
        after_value=420.0,
        period="3 runs",
        process_holds=True,
        process_notes="query-count assertion added to CI",
        standard_description="eager-load join; CI asserts query count",
        went_poorly=["first target was set before measuring the baseline"],
        spread_to=["sibling-agent"],
    )
    base.update(overrides)
    return KaizenSpec(**base)


# --------------------------------------------------------------------------
# backend contract
# --------------------------------------------------------------------------

def test_backend_contract(mem):
    b = mem.backend
    caps = b.capabilities()
    assert caps.name in ("memory", "sqlite", "jsonl")

    b.write("thing", "t1", {"id": "t1", "v": 1})
    assert b.read("thing", "t1")["v"] == 1
    assert b.read("thing", "nope") is None

    b.write("thing", "t1", {"id": "t1", "v": 2})
    assert b.read("thing", "t1")["v"] == 2

    b.write("thing", "t2", {"id": "t2", "v": 9})
    assert len(b.query("thing")) == 2
    assert [r["v"] for r in b.query("thing", where={"v": 9})] == [9]

    assert b.delete("thing", "t2") is True
    assert b.delete("thing", "t2") is False

    if caps.supports("append_only_journal"):
        b.append({"ts": 1.0, "event": "x"})
        b.append({"ts": 2.0, "event": "y"})
        assert [e["event"] for e in b.journal()] == ["x", "y"]
        assert [e["event"] for e in b.journal(since=2.0)] == ["y"]


def test_capabilities_are_truthful():
    assert not InMemoryBackend().capabilities().durable
    assert SQLiteBackend(":memory:").capabilities().transactional
    assert SQLiteBackend(":memory:").capabilities().temporal_versioning
    assert JsonlBackend("/tmp/x.jsonl").capabilities().durable
    assert not JsonlBackend("/tmp/x.jsonl").capabilities().transactional


def test_unknown_backend_raises():
    with pytest.raises(KeyError):
        get_backend("mysql")


# --------------------------------------------------------------------------
# discipline — the plugin must refuse shortcuts
# --------------------------------------------------------------------------

def test_taisaku_requires_root_cause(mem):
    p = mem.open_problem(CAP, "ideal", "actual", "gap")
    with pytest.raises(DisciplineError, match="must name the root cause"):
        mem.propose_countermeasure(p.problem_id, "do something")


def test_taisaku_requires_verified_root_cause(mem):
    p = mem.open_problem(CAP, "ideal", "actual", "gap")
    with pytest.raises(DisciplineError, match="unverified root cause"):
        mem.assert_root_cause(p.problem_id, "something", verified_by="")


def test_failing_therefore_test_blocks(mem):
    p = mem.open_problem(CAP, "ideal", "actual", "gap")
    mem.ask_why(p.problem_id, 1, "why?", "", evidence="none")
    mem.ask_why(p.problem_id, 2, "why again?", "because", evidence="none")
    with pytest.raises(DisciplineError, match="Therefore Test"):
        mem.assert_root_cause(p.problem_id, "rc", verified_by="log")


def test_taisho_is_allowed_without_root_cause(mem):
    p = mem.open_problem(CAP, "ideal", "actual", "gap")
    cm = mem.propose_countermeasure(
        p.problem_id, "contain it now", strength=CountermeasureStrength.TAISHO
    )
    assert cm.strength is CountermeasureStrength.TAISHO


def test_open_problem_needs_a_gap(mem):
    with pytest.raises(DisciplineError, match="gap against a standard"):
        mem.open_problem(CAP, "ideal", "", "gap")
    with pytest.raises(DisciplineError, match="priority point"):
        mem.open_problem(CAP, "ideal", "actual", "gap", breakdown=["x"])


def test_target_needs_deadline_and_a_real_gap(mem):
    p = mem.open_problem(CAP, "ideal", "actual", "gap")
    with pytest.raises(DisciplineError, match="deadline"):
        mem.set_target(p.problem_id, "m", 10.0, 5.0, "")
    with pytest.raises(DisciplineError, match="identical"):
        mem.set_target(p.problem_id, "m", 10.0, 10.0, "2026-01-01")


def test_hansei_requires_a_criticism(mem):
    with pytest.raises(DisciplineError, match="not a victory lap"):
        mem.hansei("exp_x", went_well=["everything"])


def test_cannot_standardise_without_hansei(mem):
    mem.observe("m", 10.0)
    p = mem.open_problem(CAP, "ideal", "actual", "gap")
    mem.ask_why(p.problem_id, 1, "q", "a", evidence="e")
    mem.ask_why(p.problem_id, 2, "q", "b", evidence="e")
    rc = mem.assert_root_cause(p.problem_id, "rc", verified_by="e")
    cm = mem.propose_countermeasure(p.problem_id, "fix", root_cause_id=rc.root_cause_id)
    t = mem.set_target(p.problem_id, "m", 10.0, 5.0, "2026-01-01")
    exp = mem.start_experiment(p.problem_id, t.target_id, "h", [cm.countermeasure_id])
    mem.check(exp.experiment_id, 4.0, process_holds=True)
    with pytest.raises(DisciplineError, match="hansei"):
        mem.standardise(exp.experiment_id, "desc")


def test_cannot_standardise_a_failed_check(mem):
    loop = KaizenLoop(mem)
    spec = _spec(after_value=1700.0, process_holds=True)
    out = loop.run(spec)
    assert out.check_passed is False
    assert out.standard_id is None
    assert out.improved is False


def test_cannot_standardise_when_process_does_not_hold(mem):
    loop = KaizenLoop(mem)
    out = loop.run(_spec(process_holds=False))
    assert out.check_passed is False
    assert out.standard_id is None


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------

def test_full_cycle_standardises(mem):
    loop = KaizenLoop(mem)
    mem.observe("p95_latency_ms", 1800.0, source="apm")
    out = loop.run(_spec())

    assert out.improved is True
    assert out.check_passed is True
    assert out.standard_version == 1
    assert out.spread_id is not None
    assert "8-standardise" in out.steps_completed
    assert "8-yokoten" in out.steps_completed

    std = mem.active_standard(CAP)
    assert std is not None and std["version"] == 1 and std["active"] is True

    # the A3 story rendered and covers every phase
    assert "## 4. Root cause" in out.a3
    assert "eager-load" in out.a3


def test_second_cycle_supersedes_the_first(mem):
    loop = KaizenLoop(mem)
    first = loop.run(_spec())
    second = loop.run(_spec(
        metric="p95_latency_ms", before_value=420.0, after_value=380.0,
        goal=400.0, standard_description="further batching",
        spread_to=[], went_poorly=["n/a"],
    ))
    assert (first.standard_version, second.standard_version) == (1, 2)
    active = mem.active_standard(CAP)
    assert active["version"] == 2
    superseded = mem.backend.read("standard", first.standard_id)
    assert superseded["active"] is False
    assert active["supersedes"] == first.standard_id


def test_yokoten_refuses_a_superseded_standard(mem):
    loop = KaizenLoop(mem)
    first = loop.run(_spec(spread_to=[]))
    loop.run(_spec(before_value=420.0, after_value=380.0, goal=400.0,
                   spread_to=[], went_poorly=["n/a"]))
    with pytest.raises(DisciplineError, match="superseded standard"):
        mem.yokoten(first.standard_id, ["someone"])


def test_audit_detects_standard_drift(mem):
    loop = KaizenLoop(mem)
    loop.run(_spec())
    assert loop.audit_standard(CAP, 450.0)["holds"] is True
    drift = loop.audit_standard(CAP, 900.0)
    assert drift["holds"] is False
    andons = mem.open_andons()
    assert len(andons) == 1 and "standard drift" in andons[0]["reason"]


def test_kaikaku_needs_approval(mem):
    loop = KaizenLoop(mem)
    from cimemory import ChangeScope
    with pytest.raises(KaikakuNotApproved):
        loop.run(_spec(scope=ChangeScope(mode="kaikaku")))
    ok = loop.run(_spec(
        scope=ChangeScope(mode="kaikaku", approval_token="ticket-42"),
        spread_to=[],
    ))
    assert ok.improved is True


def test_andon_lifecycle(mem):
    a = mem.andon("tool returned empty result", severity="critical", stopped=True)
    assert len(mem.open_andons()) == 1
    mem.resolve_andon(a.andon_id, "upstream timeout, retried")
    assert len(mem.open_andons()) == 0


def test_journal_is_append_only_history(mem):
    loop = KaizenLoop(mem)
    loop.run(_spec())
    if mem.backend.capabilities().supports("append_only_journal"):
        events = [e["event"] for e in mem.backend.journal()]
        assert "experiment_started" in events
        assert "check" in events
        assert "standardised" in events


# --------------------------------------------------------------------------
# portability — same story, three backends
# --------------------------------------------------------------------------

def test_all_backends_reach_the_same_outcome(tmp_path):
    outcomes = []
    for name, kwargs in (
        ("memory", {}),
        ("sqlite", {"path": ":memory:"}),
        ("jsonl", {"path": str(tmp_path / "b.jsonl")}),
    ):
        backend = get_backend(name, **kwargs)
        memory = EvolutionMemory(backend, agent="a")
        loop = KaizenLoop(memory)
        out = loop.run(_spec())
        outcomes.append((
            out.improved, out.check_passed, out.standard_version,
            memory.status()["standards"], memory.status()["backend"],
        ))
        backend.close()
    assert len({o[:4] for o in outcomes}) == 1
    assert {o[4] for o in outcomes} == {"memory", "sqlite", "jsonl"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
