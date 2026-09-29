#!/usr/bin/env python3
"""Experiment 001 — does the loop actually improve, and is it DB-agnostic?

Scenario (synthetic but realistic): an ADK pilot agent, ``balboa``, is burning
tool calls. Mean tool calls per task is 14 against a standard of 6. We run one
full TBP/PDCA cycle and check two things:

  A. **Discipline** — the plugin refuses the shortcuts (taisaku with no verified
     root cause, standardising a failed Check).
  B. **Portability** — the same cycle, run over three different backends
     (memory, sqlite, jsonl), produces the same outcome.

Run:  python experiments/experiment_001_kaizen_cycle.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cimemory import (  # noqa: E402
    CountermeasureSpec,
    CountermeasureStrength,
    DisciplineError,
    EvolutionMemory,
    KaizenLoop,
    KaizenSpec,
    get_backend,
)

CAP = "tool-call-efficiency"
WHYS = [
    ("Why do tasks take ~14 tool calls?",
     "The agent re-reads files it has already read.",
     "trace analysis: 62% of read calls hit a file already read in-task"),
    ("Why does it re-read them?",
     "It has no durable record of what it already read.",
     "no memory records exist for tool results"),
    ("Why is there no record?",
     "Context compaction drops earlier tool results.",
     "compaction events in the run log"),
    ("Why does compaction drop them?",
     "Tool results are never written to durable memory before reuse.",
     "read path in the daemon writes nothing"),
    ("Why is nothing written?",
     "No standard-work step requires persisting a tool result before reuse.",
     "standard work doc has no such step"),
]

COUNTERMEASURES = [
    CountermeasureSpec(
        "Cap repeated reads of the same file at 2 per task (containment)",
        strength=CountermeasureStrength.TAISHO,
        expected_effect="stops the worst re-read spikes immediately",
        cost="low", risk="low",
    ),
    CountermeasureSpec(
        "Persist every tool result to the evolution memory and consult it "
        "before any re-read",
        strength=CountermeasureStrength.TAISAKU,
        expected_effect="removes the reason to re-read at all",
        cost="medium", risk="low",
    ),
    CountermeasureSpec(
        "Make the tool layer refuse a read whose result is already in memory "
        "(poka-yoke)",
        strength=CountermeasureStrength.MIZEN_BOUSHI,
        expected_effect="the failure mode cannot occur; it is designed out",
        cost="medium", risk="medium",
    ),
]


def build_spec() -> KaizenSpec:
    return KaizenSpec(
        capability=CAP,
        ideal="mean tool calls per task <= 6 (standard work)",
        actual="mean tool calls per task = 14",
        gap="8 calls per task above standard; ~57% overhead",
        breakdown=[
            "redundant file reads (62% of reads)",
            "duplicate status polling",
            "re-reading context after compaction",
        ],
        priority_point="redundant file reads after compaction",
        metric="mean_tool_calls_per_task",
        goal=6.0,
        deadline="2026-10-15",
        direction="decrease",
        whys=WHYS,
        root_cause=(
            "no standard-work step requires a tool result to be persisted to "
            "durable memory before reuse, so compaction erases it and the agent "
            "re-reads"
        ),
        root_cause_verified_by="trace analysis + daemon read path inspection",
        countermeasures=COUNTERMEASURES,
        hypothesis=(
            "persisting tool results and consulting memory before a read will cut "
            "mean tool calls per task from 14 to below 6"
        ),
        before_value=14.0,
        after_value=5.4,
        period="5 consecutive runs, 240 tasks",
        process_holds=True,
        process_notes=(
            "memory-write is part of the standard work checklist and a CI audit "
            "fails the build if a read path bypasses memory"
        ),
        standard_description=(
            "standard work: persist tool results to evolution memory; consult "
            "memory before any re-read; tool layer refuses redundant reads"
        ),
        went_well=[
            "breakdown found the priority point quickly",
            "process check caught an unstable first attempt",
        ],
        went_poorly=[
            "first attempt standardised on one run only — had to redo the check",
            "no baseline observation was recorded before the change began",
        ],
        reflection_why=[
            "we were in a hurry to see a number move",
            "we treated implementation as improvement",
        ],
        next_time=[
            "record baseline observations before opening the problem",
            "require the gain to hold for 3 runs before standardising",
        ],
        spread_to=["argus", "kenji"],
    )


def demonstrate_discipline(mem: EvolutionMemory, loop: KaizenLoop) -> list[str]:
    """Prove the plugin refuses the shortcuts. Returns the refusals."""
    refusals: list[str] = []
    p = mem.open_problem(
        "prompt-length",
        "prompt stays under 8k tokens",
        "prompt reaches 41k tokens",
        "5x over standard",
        breakdown=["unbounded tool output"],
        priority_point="unbounded tool output",
    )

    # 1. a taisaku with no root cause
    try:
        mem.propose_countermeasure(p.problem_id, "truncate everything")
        refusals.append("FAIL: taisaku without root cause was accepted")
    except DisciplineError as e:
        refusals.append(f"refused (taisaku, no root cause): {e}")

    # 2. an unverified root cause
    try:
        mem.assert_root_cause(p.problem_id, "the prompt is just too long",
                              verified_by="")
        refusals.append("FAIL: unverified root cause was accepted")
    except DisciplineError as e:
        refusals.append(f"refused (unverified root cause): {e}")

    # 3. a well-formed chain but the Therefore Test fails
    mem.ask_why(p.problem_id, 1, "why 41k?", "", evidence="none")
    mem.ask_why(p.problem_id, 2, "why again?", "because it is long", evidence="none")
    try:
        mem.assert_root_cause(p.problem_id, "it is long", verified_by="log")
        refusals.append("FAIL: empty why-answer was accepted")
    except DisciplineError as e:
        refusals.append(f"refused (broken why-chain): {e}")

    # 4. standardise without a passing check
    try:
        mem.standardise("exp_does_not_exist", "nope")
        refusals.append("FAIL: standardise on missing experiment accepted")
    except KeyError as e:
        refusals.append(f"refused (missing experiment): {e}")
    return refusals


def run_backend(name: str, **kwargs) -> dict:
    backend = get_backend(name, **kwargs)
    mem = EvolutionMemory(backend, agent="balboa")
    loop = KaizenLoop(mem)

    # gemba observations: the real measurement, before anything changes
    for value in (14.2, 13.8, 14.1):
        mem.observe("mean_tool_calls_per_task", value, source="run-traces")

    refusals = demonstrate_discipline(mem, loop)

    outcome = loop.run(build_spec())
    audit = loop.audit_standard(CAP, observed_value=5.1)

    result = {
        "backend": backend.capabilities().name,
        "improved": outcome.improved,
        "standard_version": outcome.standard_version,
        "check_passed": outcome.check_passed,
        "steps": outcome.steps_completed,
        "audit_holds": audit["holds"],
        "refusals": refusals,
        "a3": outcome.a3,
        "status": mem.status(),
        "history_versions": [
            s["version"] for s in loop.improvements(CAP)
        ],
    }

    # second cycle on the same capability: the baseline must be the v1 standard
    spec2 = build_spec()
    spec2.actual = "mean tool calls per task = 5.9 (v1 standard met)"
    spec2.gap = "0.1 calls above tightened standard 5.0"
    spec2.goal = 4.5
    spec2.before_value = 5.9
    spec2.after_value = 4.4
    spec2.whys = [
        ("Why still 5.9?", "two reads still repeat after cache eviction",
         "cache eviction counters"),
        ("Why do they repeat?", "eviction is not reflected in memory",
         "eviction log has no memory event"),
    ]
    spec2.root_cause = "cache eviction does not invalidate the memory record"
    spec2.root_cause_verified_by = "cache eviction log vs memory journal diff"
    spec2.countermeasures = [CountermeasureSpec(
        "invalidate the memory record on cache eviction",
        strength=CountermeasureStrength.TAISAKU,
    )]
    spec2.standard_description = "standard work v2: memory invalidated on eviction"
    spec2.spread_to = []
    spec2.went_poorly = ["eviction path was undocumented"]
    outcome2 = loop.run(spec2)
    result["second_cycle_version"] = outcome2.standard_version
    result["history_versions_after"] = [
        s["version"] for s in loop.improvements(CAP)
    ]
    active = mem.active_standard(CAP)
    result["active_standard_v"] = active["version"] if active else None
    mem.close()
    return result


def main() -> int:
    print("=" * 78)
    print("EXPERIMENT 001 — one TBP/PDCA cycle across three backends")
    print("=" * 78)

    results = []
    for name, kwargs in (
        ("memory", {}),
        ("sqlite", {"path": ":memory:"}),
        ("jsonl", {"path": "/tmp/cimemory_exp001.jsonl"}),
    ):
        if name == "jsonl" and os.path.exists(kwargs["path"]):
            os.remove(kwargs["path"])
        print(f"\n--- backend: {name} " + "-" * (60 - len(name)))
        r = run_backend(name, **kwargs)
        results.append(r)
        print(f"improved:            {r['improved']}")
        print(f"standard:            v{r['standard_version']} "
              f"(active now v{r['active_standard_v']})")
        print(f"check passed:        {r['check_passed']}")
        print(f"sustain audit holds: {r['audit_holds']}")
        print(f"history versions:    {r['history_versions']} -> "
              f"{r['history_versions_after']}")
        print(f"steps:               {' -> '.join(r['steps'])}")
        print("discipline refusals:")
        for line in r["refusals"]:
            print(f"  - {line}")
        print(f"status: {r['status']['standards']} active standards, "
              f"{r['status']['open_problems']} open problems, "
              f"{r['status']['journal_entries']} journal entries")

    print("\n" + "=" * 78)
    print("A3 (memory backend, cycle 1)")
    print("=" * 78)
    print(results[0]["a3"][:2600])

    agreement = all(
        (r["improved"], r["check_passed"], r["standard_version"],
         r["audit_holds"], r["active_standard_v"], r["history_versions_after"])
        == (True, True, 1, True, 2, [1, 2])
        for r in results
    )
    refused = all(len(r["refusals"]) == 4 and
                  all(not x.startswith("FAIL") for x in r["refusals"])
                  for r in results)
    print("\n" + "-" * 78)
    print(f"portable across backends: {agreement}")
    print(f"discipline enforced:      {refused}")
    print("-" * 78)
    return 0 if (agreement and refused) else 1


if __name__ == "__main__":
    raise SystemExit(main())
