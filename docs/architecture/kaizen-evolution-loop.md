# Architecture — the Kaizen Evolution Loop

How the Toyota concepts in
[`docs/research/toyota-continuous-improvement.md`](../research/toyota-continuous-improvement.md)
become a running loop over an agent's memory.

---

## 1. Concept → code map

| Toyota concept | Code symbol | Where |
|---|---|---|
| Genchi genbutsu (go and see) | `Observation`, `EvolutionMemory.observe()` | `models.py`, `plugin.py` |
| Gap against a standard | `Problem` (ideal / actual / gap) | `models.py` |
| Standard work | `Standard`, `active_standard()` | `models.py`, `plugin.py` |
| TBP 1 clarify | `open_problem()` | `plugin.py` |
| TBP 2 break down | `Problem.breakdown`, `priority_point` | `models.py` |
| TBP 3 target | `Target`, `set_target()` | `models.py` |
| TBP 4 root cause / 5-Why | `Why`, `ask_why()`, `assert_root_cause()` | `plugin.py` |
| Therefore Test | `EvolutionMemory.therefore_test()` | `plugin.py` |
| TBP 5 countermeasure | `Countermeasure`, `propose_countermeasure()` | `plugin.py` |
| Taisho / taisaku / mizen-boushi | `CountermeasureStrength` | `models.py` |
| TBP 6 Do | `Experiment`, `start_experiment()`, `log_do()` | `plugin.py` |
| TBP 7 Check (results + process) | `Check`, `check()` | `plugin.py` |
| TBP 8 Act: standardise | `standardise()` | `plugin.py` |
| TBP 8 Act: sustain | `KaizenLoop.audit_standard()` | `loop.py` |
| Yokoten (spread) | `Spread`, `yokoten()`, `mark_spread()` | `plugin.py` |
| Hansei (reflection) | `Hansei`, `hansei()` | `plugin.py` |
| Jidoka / andon (stop the line) | `Andon`, `andon()`, `resolve_andon()` | `plugin.py` |
| A3 report | `EvolutionMemory.a3()` | `plugin.py` |
| Kaizen vs kaikaku | `ChangeScope`, `KaikakuNotApproved` | `loop.py` |
| PDCA cycle | `KaizenLoop.run(spec)` | `loop.py` |
| Heijunka / pull | `query(..., limit=)`, journal windows | `backend.py` |

---

## 2. The loop, step by step

```
        ┌─────────────────────────────────────────────────────┐
        │  PLAN  (5 of the 8 steps live here)                 │
        │                                                     │
  standard ──► 1 clarify ──► 2 break down ──► 3 target        │
        │        (ideal vs actual)  (priority point)          │
        │                │                                    │
        │                ▼                                    │
        │        4 root cause   ◄── 5-Why chain + Therefore   │
        │        (must be VERIFIED by evidence)               │
        │                │                                    │
        │                ▼                                    │
        │        5 countermeasures  (taisho? taisaku?         │
        │                            mizen-boushi?)            │
        └────────────────┬────────────────────────────────────┘
                         ▼
        ┌─────────────────────────────────────────────────────┐
        │  DO    6 see the countermeasure through             │
        │        (one variable, small scale first)            │
        ├─────────────────────────────────────────────────────┤
        │  CHECK 7 evaluate RESULTS *and* PROCESS             │
        │        (did the metric move? does the gain hold?)   │
        ├─────────────────────────────────────────────────────┤
        │  ACT   8 standardise  ──► new baseline (v+1)        │
        │        yokoten     ──► spread to sibling agents     │
        │        hansei      ──► reflect, even on success     │
        └─────────────────────────────────────────────────────┘
                         │
                         └──► audit_standard() later ──► drift? ──► andon
```

The arrow back into the standard on the left is the point: the loop is a **cycle
that resets the baseline**, not a task that ends.

---

## 3. The discipline invariants (enforced, not documented)

These are the reasons the plugin is more than a key-value store. Each is a real
`raise DisciplineError` in `plugin.py`, and each is covered by a test.

| Invariant | Guard | Why Toyota does it |
|---|---|---|
| A problem needs ideal, actual and gap | `open_problem` | Without a standard there is no gap, only opinion |
| A breakdown needs a priority point | `open_problem` | Step 2 is the step everyone skips |
| A target needs a deadline and a real gap | `set_target` | A wish is not a target |
| A root cause needs evidence | `assert_root_cause` | Genchi genbutsu: verify at the source |
| The 5-Why must pass the Therefore Test | `therefore_test` | A poorly reasoned chain leads nowhere |
| A taisaku needs a *verified* root cause | `propose_countermeasure` | Stops symptom-chasing |
| An experiment needs a countermeasure | `start_experiment` | No experiment without a hypothesis to test |
| Standardising needs a passing Check | `standardise` | Implementation is not improvement |
| Standardising needs hansei | `standardise` | Reflection is mandatory, even on success |
| Yokoten needs a live standard | `yokoten` | Never spread a stale baseline |
| Hansei must name a criticism | `hansei` | It is not a victory lap |
| Kaikaku needs an approval token | `ChangeScope.validate` | Changing the roots is a gated act |

**Design rule:** every one of these guards exists because the *un-guarded* path
is the failure mode Toyota spent decades eliminating. Weak enforcement makes a
filing cabinet; enforcing these makes a learning loop.

---

## 4. Why the countermeasure taxonomy is a first-class type

`CountermeasureStrength` is not decoration. It is the difference between fixing a
problem and hiding it:

- `TAISHO` — containment. Allowed with no root cause, because protecting the
  customer right now is legitimate.
- `TAISAKU` — the plugin **refuses** it without a verified root cause.
- `MIZEN_BOUSHI` — the target state: change the conditions so the failure cannot
  occur.

`EvolutionMemory.countermeasure_strength(problem_id)` reports the strongest
countermeasure proposed. A loop that keeps ending at `taisho` is not improving —
and a dashboard showing that distribution is exactly the visual control of
Principle 7.

---

## 5. Backend-agnostic by construction

```
KaizenLoop ──► EvolutionMemory ──► MemoryBackend (protocol)
                                        ├── InMemoryBackend
                                        ├── SQLiteBackend   (durable, versioned)
                                        ├── JsonlBackend    (minimal)
                                        └── <your adapter>
```

- The plugin imports no driver. It imports `MemoryBackend` (a `Protocol`).
- Capability differences are negotiated, never assumed: the plugin calls
  `capabilities().supports("append_only_journal")` before relying on the journal.
- The conformance suite runs every test against all three adapters, so
  "DB-agnostic" is verified, not claimed.

Requirements the layer must satisfy: see
[`docs/requirements/generic-memory-requirements.md`](../requirements/generic-memory-requirements.md).

---

## 6. Wiring it into an agent

An agent runtime only needs four hooks. Nothing about the loop requires the
agent to be a particular framework.

```python
from cimemory import EvolutionMemory, KaizenLoop, KaizenSpec, get_backend

mem  = EvolutionMemory(get_backend("sqlite", path="~/.agent/evolution.db"),
                       agent="balboa")
loop = KaizenLoop(mem)

# hook 1 — every tool result becomes an observation (genchi genbutsu)
mem.observe("mean_tool_calls_per_task", measured, source="run-traces")

# hook 2 — before a costly action, consult memory (the strongest countermeasure)
if mem.backend.capabilities().supports("full_text_search"):
    hits = mem.backend.search_text("observation", "mean_tool_calls_per_task")
    if hits:
        reuse(hits[-1])          # do not re-derive what you already know

# hook 3 — an abnormality stops the line (jidoka)
if measured > BUDGET:
    mem.andon("tool-call budget exceeded", severity="critical", stopped=True)

# hook 4 — between tasks, run a cycle
loop.run(KaizenSpec(capability="tool-call-efficiency", ...))
```

The four hooks are the whole integration surface: observe, consult, interrupt,
improve.

---

## 7. The sustain path (the step everyone forgets)

Standardising is not the end. `KaizenLoop.audit_standard()` is the follow-up:

- read the active standard,
- read the target it came from,
- measure the current value,
- if it violates the target → raise an `Andon` for standard drift.

Without this, "the old condition quietly returns" — Toyota's exact warning about
standards that decay once a project closes. It is a small method because the work
is small; the discipline is in *scheduling* it.

---

## 8. Module reference

| Module | Responsibility |
|---|---|
| `cimemory/models.py` | The twelve record kinds as dataclasses. No storage knowledge. |
| `cimemory/backend.py` | `MemoryBackend` protocol + `BackendCapabilities` + `BaseBackend`. |
| `cimemory/backends/memory.py` | Zero-dependency, non-durable. |
| `cimemory/backends/sqlite.py` | Durable, transactional, versioned (history table). |
| `cimemory/backends/jsonl.py` | Minimal file adapter; proves the contract is thin. |
| `cimemory/plugin.py` | `EvolutionMemory` — semantics + enforcement + A3 rendering. |
| `cimemory/loop.py` | `KaizenLoop`, `KaizenSpec`, the kaizen/kaikaku gate. |
| `experiments/experiment_001_kaizen_cycle.py` | The experiment: real cycle across three backends. |
| `tests/test_plugin.py` | Contract, discipline, loop, and portability tests. |
