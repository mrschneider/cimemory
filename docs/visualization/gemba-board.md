# The Gemba Board — the cimemory visualization

`python3 -m cimemory.dashboard` → <http://127.0.0.1:8700>

A live, replayable board of one improvement programme: five stations on a shop
floor, their andon lamps, the standards ratchet, the A3 of the problem being
worked, the 5-Why ladder, the waste ledger and the yokoten map.

**Design thesis:** every view is a *Toyota management artifact*, not a chart.
Toyota's visual management exists to make abnormality visible at a glance and to
force structured thinking. So there is no "metrics tab" here — there is an andon
board, a PDCA wheel, an A3 sheet, a 5-Why ladder, a muda ledger and a yokoten
map, because those are the instruments Toyota actually uses.

---

## 1. Design language — a shop-floor instrument

| Element | Meaning |
|---|---|
| **Andon lamps** (glowing circles) | station state: green = inside standard, amber = drifting, red = line stopped |
| **Hazard tape** (amber/black diagonal stripes) | a *gated* or *radical* event — the kaikaku gate, the A3 header |
| **Graph-paper ground** | the gemba floor: a ruled work surface, not a polished dashboard |
| **Punch-card docket** (the A3) | a physical single sheet; the constraint is the discipline |
| **Rubber stamps** (`CHAIN READS TRUE`, `CHECK FAILED`) | Toyota's blame-free review marks |
| **Saira Condensed** | stencilled industrial display type |
| **IBM Plex Mono** | machine readouts, always tabular |

Colour is never decorative — it is vocabulary:

| Colour | Means |
|---|---|
| amber `#ffb020` | warning · Do phase · *taisaku* |
| red `#ff3b30` | stop the line · defects · the no-memory control |
| green `#2fd07f` | normal · Check phase · *mizen-boushi* prevent |
| blue `#4aa3ff` | Plan phase |
| violet `#a98bff` | Act phase · yokoten spread |
| safety yellow `#ffe14d` | kaikaku — a roots change |

---

## 2. The seven views

| # | View | Toyota artifact it re-creates | What it shows |
|---|---|---|---|
| 1 | **Andon Board** | the andon board above the line | every station with a lamp, its standard / actual / goal gauge, its waste class, and the log of stop-the-line signals and discipline refusals |
| 2 | **The Wheel** | PDCA / Toyota Business Practices | the eight TBP steps as ten ring stations; **five of them are Plan**; the current step lights, the sweep marker shows where the wheel is, counters show how many times each step has run |
| 3 | **The Staircase** | standard work and the ratchet | the standard as a step function that is never lowered, the actual line, the goal, and the identical no-memory agent drifting the other way |
| 4 | **The A3** | the single-sheet A3 report | left = Plan (background, breakdown, target, root cause), right = Do–Check–Act (countermeasures, do log, check on results *and* process, hansei, standard, yokoten) |
| 5 | **The Five Whys** | 5-Why at the gemba | symptom at the top, cause at the bottom, each rung carrying its observed evidence; the Therefore Test panel reads the chain backwards |
| 6 | **The Ledger** | muda accounting + countermeasure strength | one row per station with the waste it was opened against and whether it is open, contained or eliminated; the ladder counts taisho / taisaku / mizen-boushi |
| 7 | **Yokoten** | horizontal spread | the proven standard leaving the proving ground for sibling agents, fanned out per standard version |

### Why these seven

They are the *minimum* set that makes the loop legible:

- The **Andon Board** answers "is anything wrong right now?" (Principle 7, visual control).
- The **Wheel** answers "where in the thinking are we?" (TBP / PDCA).
- The **Staircase** answers "has the baseline actually moved?" (Principle 6, standard work).
- The **A3** answers "do we understand this problem?" (TBP, single sheet).
- The **Five Whys** answers "is the cause real or assumed?" (genchi genbutsu).
- The **Ledger** answers "are we fixing causes or hiding symptoms?" (muda; taisho vs taisaku vs mizen-boushi).
- **Yokoten** answers "did anyone else learn from it?" (Principle 11).

Nothing else earned a place. A view that does not correspond to a Toyota
practice would be decoration, and decoration hides abnormality.

---

## 3. What the frames contain

The telemetry is **not a mock**. `cimemory/dashboard/capture.py` drives the real
plugin — `EvolutionMemory` + `KaizenLoop` over `InMemoryBackend` — through a
scripted improvement programme (seven kaizen cycles, one rejected countermeasure,
one drift caught by audit, one gated kaikaku) and snapshots the store after
every semantic event.

Each frame:

```jsonc
{
  "i": 104, "sim_ts": 1762183200.0, "cycle": 6,
  "kind": "check",              // idle|observe|step|why|root_cause|countermeasure|
                                // experiment|do|check|hansei|standard|yokoten|
                                // andon|refusal|audit|kaikaku
  "title": "7 · Check — PASS",
  "step": "7-check",            // which TBP step is active (drives the wheel)
  "steps_tally": { ... },       // cumulative runs per step
  "line":   { "capability": "…", "actual": 4.4, "standard": 4.4,
              "goal": 4.5, "control": 14.28 },   // the staircase series
  "board":  { "<cap>": { "label": "…", "standard": 5.4, "actual": 5.9,
                         "goal": 4.5, "status": "abnormal",
                         "waste": "Motion", "waste_detail": "…" } },
  "store":  { "standards": [...], "problems": [...], "countermeasures": [...],
              "root_causes": [...], "whys": [...], "andons": [...],
              "spreads": [...], "n_observation": 10 },
  "a3":     { "problem": {...}, "whys": [...], "root_cause": {...},
              "target": {...}, "experiment": {...}, "check": {...},
              "hansei": {...}, "standard": {...}, "therefore_ok": true }
}
```

Because `store` is a real snapshot, every view is showing **what the plugin
actually held at that instant** — including the andons that were open then, which
are marked resolved by the end of the run.

Capture is deterministic (fixed script, fixed sim clock; no randomness). The only
synthetic element is the no-memory control line, which models an agent with the
same starting point that never learns.

---

## 4. Running and regenerating

```bash
python3 -m cimemory.dashboard                  # serve, reusing data/frames.json
python3 -m cimemory.dashboard --regen          # rebuild the telemetry first
python3 -m cimemory.dashboard --host 0.0.0.0 --port 8700
python3 -m cimemory.dashboard.capture          # just rebuild the JSON
```

Endpoints: `/` (UI), `/api/data` (gzip, the whole trace), `/api/health`.

Transport: **space** plays/pauses, **←/→** step, **Home/End** jump, **1–7** switch
views, the scrubber is draggable. Cycle bands in the scrubber are outlined when
they contain an andon (red) or a kaikaku (yellow).

**No dependencies.** The server is `http.server` from the standard library; the
frontend is plain ES5-era JavaScript and hand-written SVG. Nothing to install.

---

## 5. Extending it

**Add a station.** Append to `STATIONS` in `dashboard/capture.py` (label, metric,
unit, direction, waste, ideal, start values) and give it a cycle in `build()`.
It appears on the andon board and in the ledger automatically.

**Add a view.** Create `static/js/views/<name>.js`, push onto
`window.GEMBA_VIEWS` with `{id, label, render(f, ctx)}`, and add a `<section
class="view" id="view-<name>">` plus a `<script>` tag in `index.html`. `ctx`
gives you `{meta, frames, i, state, render}` — `frames` lets a view read history
(e.g. "every refusal so far"), `i` is the current frame.

**Rule for new views:** name the Toyota artifact you are re-creating. If you
cannot name one, the information belongs in an existing view.
