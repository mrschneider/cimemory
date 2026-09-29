# Live wiring: cimemory reads production agent memory

`python3 -m cimemory.dashboard` → the board opens on **live** memory.
Click the source chip in the header to swap to the scripted demo and back.

```
live · ratiocore agent memory @ 127.0.0.1:3301 (tool_event + turn_traces, role=guest, select-only)
demo · the scripted seven-cycle programme in dashboard/capture.py
```

If the memory is unreachable the server falls back to the demo **and says so**
on the chip (`source_note` in `/api/data`, `live.reachable: false` in
`/api/health`). It never quietly substitutes a script for production and lets
you believe it was real.

---

## 1. The read-only contract

This is the whole point of the wiring, so it is enforced in four places
rather than promised in one.

| Where | What it guarantees |
|---|---|
| **Connection role** | connects as `guest`, whose only grant is `session,usage` on `universe`. It has no space grants at all. |
| **Statements** | the only statements issued are paged `select(...)` reads and `format()` introspection. There is no `insert`, `replace`, `update`, `delete`, `truncate` or `upsert` anywhere in `cimemory/live/`. |
| **Runtime guard** | `ReadOnlyTarantool.verify_read_only()` reads `box.schema.user.info` and raises `PermissionError` if the user holds any write grant — so pointing this at a writable user fails loudly instead of mutating production. |
| **Test** | `tests/test_live.py::test_the_module_cannot_write` inspects the module's own source and fails if a mutation call ever appears in it. |

The board is an **observation instrument**. It consumes memory; it never
writes improvement work back. That is the requirement you set, and it is the
reason live mode reports the loop as *not run* rather than running it.

---

## 2. The space it reads

`box.space.agent_memory`, one tuple per turn:

```
[turn_id, profile, role, content, embedding, metadata]
```

| field | meaning | what the board does with it |
|---|---|---|
| `profile` | the agent | becomes the **station** |
| `role` | `user · assistant · tool · system · lesson · outcome` | `tool` carries the defects, `lesson` the countermeasures, `outcome` the verdicts |
| `metadata.ts` | epoch seconds | the observation window |
| `metadata.sid` | session | counted, not used as a station |
| `metadata.status` | `ok · error · nonzero_exit · validation_error · timeout` | **the defect signal** |

Measured on the day this was wired: **1089 tuples, 749 tool calls, 58
defects, 13 agents, 13 lessons, 7 verdicts**, over 2026-09-12 → 2026-09-29.

---

## 3. How production memory becomes a Toyota board

Every mapping is a count of tuples. Nothing is modelled, sampled or invented.

| Toyota | Live board | Source |
|---|---|---|
| **Station** | an agent (`profile`) | distinct profiles with tool calls |
| **Defect** | a tool call whose recorded `status` is not `ok` | `metadata.status` |
| **Actual** | defects per 100 tool calls at that station | computed |
| **Standard** | the **fleet median** defect rate over the window, among stations with ≥ 30 tool calls | `MIN_EVIDENCE` |
| **Goal** | the **best demonstrated** rate in the fleet | same population |
| **Abnormal → andon** | a station above the standard | opens a real andon |
| **Muda (waste)** | the defect kind, mapped: `timeout → Waiting`, everything else → `Defects` | `DEFECT_WASTE` |
| **Countermeasure** | a `role=lesson` tuple — the agent's own written-down learning | `lesson` rows |
| **Strength ladder** | classified from the agent's own wording (`taisaku` for a measured cause, `taisho` for a suspicion, `mizen_boushi` for a design-level finding) | `classify_strength` |
| **Verdict / problem** | a `role=outcome` tuple, with its real attempt trace `[a1:criterion_failed; a2:rules…]` | `outcome` rows |
| **5 Whys** | rung 1 = the real attempt trace; rung 2 = the agent's own note, quoted | never an asserted cause |
| **Yokoten** | a lesson whose *failing artefact* appears in more than one note: written down, never spread | `_recurrence` |

### The three judgements that keep it honest

**The standard is the median, not the mean.** A mean lets one bad station
redefine what "normal" means; the median is what the fleet actually
established. `test_median_is_the_middle_not_the_mean` locks this in.

**Small samples cannot set the target.** 0 defects over 12 tool calls is not
a capability, it is a small sample. Stations below 30 tool calls are shown on
the board but excluded from the standard and from the goal, and their card is
marked `no data` / low evidence rather than green.

**A note is not a fix.** A lesson is only promoted to `taisaku` when the
agent's own wording claims a measured cause; a suspicion stays `taisho`;
anything else stays `unclassified`. The classification always ships with the
phrase that decided it (`basis`), so you can audit the label.

---

## 4. What the live board refuses to do

Toyota Business Practices has ten steps. A read-only observer performs **two**.

* **1 · Clarify the problem** — the fleet runs at 7.74 defects per 100 tool
  calls against a standard of 4.07; the gap is real and measured.
* **2 · Break it down** — stratified by station, then by defect kind. Three
  stations carry the gap: predman 17.16, geosupply 10.57, tanya 9.30.

Steps 3–8 (target, root cause, countermeasures, experiment, check, hansei,
standardise, yokoten) are reported as **not performed**, with the reason
stated on the board: acting on the gap means writing improvement work back
into production memory, which this wiring must not do. The wheel therefore
lights two of ten steps, and `cycles run` reads *not run*. That is not the
board being broken — it is the board being honest about who is acting.

The same discipline shows up in the A3: the worst station on the floor
(predman, 17.16 per 100, 29 of 169 tool calls failing) has **no root cause
and no countermeasure on file**, because memory holds none. The A3 shows that
hole rather than filling it. On a real shop floor that is the single most
useful thing an observation board can tell you.

---

## 5. Running it

```bash
# live (default when the memory is reachable), LAN-visible
python3 -m cimemory.dashboard --host 0.0.0.0 --port 8700

# the scripted programme
python3 -m cimemory.dashboard --source demo

# a different memory
python3 -m cimemory.dashboard --tnt-host 192.168.0.70 --tnt-port 3301
# or CIMEMORY_TNT_HOST / CIMEMORY_TNT_PORT / CIMEMORY_LIVE_TTL
```

The live read is cached for `CIMEMORY_LIVE_TTL` seconds (default 60) so the
board does not poll production; `?regen=1` forces a re-read.

```bash
curl -s 'localhost:8700/api/health' | python3 -m json.tool
curl -s 'localhost:8700/api/data?source=live' -o /dev/null -w '%{size_download}\n'
```

## 6. Reading the source directly

```python
from cimemory.live import ReadOnlyTarantool, measure, probe

probe()                                  # {'ok': True, 'rows': 1089, 'readonly': True}
src = ReadOnlyTarantool()                # 127.0.0.1:3301, space agent_memory, user guest
src.verify_read_only()                   # raises if the user could write
fleet = measure(src)
print(fleet.standard, fleet.goal, [s.agent for s in fleet.abnormal])
print(fleet.stations[0].defect_rate, fleet.stations[0].waste_detail)
```

Requires the `tarantool` client library — imported lazily, so the plugin
itself and the demo source stay **stdlib-only**.


---

## 6. The full evidence base (measurement only)

The first version of the wiring read `agent_memory` alone: 739 tool calls over
about three days. But `agent_memory` is the *conversational* record, not the
whole floor. Production also keeps a call-level ledger and a cost trace, and
they cover an order of magnitude more work:

| Space | What it is | Rows at the time of writing |
|---|---|---|
| `agent_memory` | turns; `lesson`/`outcome` rows are the qualitative evidence | ~1 128 |
| `tool_event` | one row per tool call: `status`, `is_error`, `exit_code`, `blocked_reason` | 11 864 |
| `turn_traces` | what a turn cost: `duration_ms`, `tokens_in`, `tokens_out`, `tool_calls` | 23 |
| `agent_runtime_config` | the revisioned actuator surface, read **only as a time marker** | 12 |
| `agent_revision` | revision activation times, `change_reason`, actor | 19 |
| `rb_insight` | documented insights and their `uses` counter | 83 |

Where the two ledgers overlap they agree exactly — 759 overlapping calls, 759
agree, 0 disagree — so either can serve as the defect ledger. `tool_event` is
preferred because it is wider, and the board reports which one it used
(`meta.defect_source`) rather than assuming.

### 6.1 The four muda axes

A defect rate alone sees only one kind of waste. `turn_traces` makes three
more measurable, each in its own unit:

| Axis | Unit | Muda |
|---|---|---|
| `defects` | defects per 100 tool calls | Defects |
| `waiting` | mean turn duration (ms) | Waiting |
| `overprocessing` | mean prompt tokens per turn | Over-processing |
| `motion` | mean tool calls per turn | Motion |

The axes are **not summed**. A millisecond and a defect are not commensurable,
so each axis is judged against the median of the same axis across the fleet,
and the station's `worst_muda` is the axis where it exceeds that standard by
the largest *ratio*. Axes with no fleet standard (nobody has traces) are
excluded, never treated as zero.

### 6.2 The measurement's own limits, reported

Three things the wiring deliberately refuses to hide:

**Coverage.** `meta.coverage` reports how much evidence is attributable to a
configuration at all. At the time of writing: **661 of 11 864 events (5.6 %)**.
The other 94.4 % come from agents with no `agent_runtime_config` row — and
those agents (`ginger`, `tanya`, `trin`, plus `dimi` and `presales`) are
precisely the high-volume ones. An agent the system does not govern is an
agent whose improvement cannot be attributed to a change. That is a finding,
not a gap in the code.

**Comparability.** A rate over five calls is not a capability. Every window
carries `comparable`, true only when the window holds at least
`MIN_EVIDENCE` (30) events. A window below the floor is drawn hollow grey and
its label says `NOT COMPARABLE`, so it can never be read as an improvement. In
the current data every station's *after* window is below the floor, so **no
before/after claim is supportable anywhere in the fleet** — which is the
honest answer, and the reason the check step of the loop cannot be closed yet.

**Definition drift.** The revision tables qualify the agent id
(`agent-silver-predman`) while the event ledger uses the bare profile
(`predman`). The join normalises with an escaped pattern: in Lua `-` is a
quantifier, so `^agent-silver-` silently matches "agent-silve" and every
window collapses into `no-config`. `normalise_agent()` escapes it, and a test
pins the behaviour.

### 6.3 What the revision join is, and is not

A revision activation time is a **time marker**, nothing more. The board
segments a station's evidence at those markers so a before/after can be
*shown* — it never claims the configuration caused the difference. The
staircase draws:

* one dashed column per revision window, labelled with the revision;
* the **actual** rate of each window;
* the **standard**, seeded with the fleet median, which only ever tightens —
  a window worse than the standing standard does not move it, so the baseline
  is never lowered to accommodate a bad shift.

### 6.4 Yokoten, measured

`rb_insight` carries a `uses` counter, so "was this countermeasure adopted?"
is a number rather than an opinion. Current reading: **83 insights, 22 used at
least once, 61 never used**. The yokoten view draws the unused ones as
*not-spread* items — a countermeasure written down and never applied has not
left its author, let alone reached a sibling. Where a station has no measured
standard at all, the finding is still shown and is labelled `no standard yet`
rather than being hung on an invented standard id.
