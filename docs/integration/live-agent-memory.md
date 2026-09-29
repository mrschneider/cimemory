# Live wiring: cimemory reads production agent memory

`python3 -m cimemory.dashboard` → the board opens on **live** memory.
Click the source chip in the header to swap to the scripted demo and back.

```
live  · ratiocore agent_memory @ 127.0.0.1:3301 (agent_memory, role=guest, select-only)
demo  · the scripted seven-cycle programme in dashboard/capture.py
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
| **Statements** | the only statement issued is `box.space.agent_memory:select(...)`, paged. There is no `insert`, `replace`, `update`, `delete`, `truncate` or `upsert` anywhere in `cimemory/live/`. |
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
