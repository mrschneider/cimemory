# Toyota Continuous Improvement — Research Notes

Foundation research for `cimemory`: what Toyota actually does when it improves a
process, and which of those mechanisms are portable to an autonomous agent's
evolution loop.

Sources are listed at the bottom. Everything here is synthesis of those sources,
not invention.

---

## 1. The frame: The Toyota Way

Toyota formalised its culture in 2001 as the **Toyota Way 2001**, built on **two
pillars**:

1. **Continuous improvement** (改善 *kaizen* — literally "change for the better")
2. **Respect for people**

Jeff Liker's 2004 book *The Toyota Way* expanded this into **14 management
principles** organised in the **4 P model**:

| 4P | Meaning | Principles |
|---|---|---|
| **Philosophy** | Long-term thinking over short-term gain | 1 |
| **Process** | The right process produces the right results | 2–8 |
| **People & Partners** | Add value by developing people and partners | 9–11 |
| **Problem Solving** | Continuous root-cause solving drives organisational learning | 12–14 |

### The 14 principles (Liker)

1. Base management decisions on a **long-term philosophy**, even at the expense of short-term financial goals.
2. Create **continuous process flow** to bring problems to the surface.
3. Use **pull systems** to avoid overproduction (*kanban*).
4. **Level out the workload** (*heijunka*) — eliminate *muda*, *mura*, *muri*.
5. Build a culture of **stopping to fix problems**, to get quality right the first time (*jidoka*, *andon*).
6. **Standardised tasks** are the foundation for continuous improvement and employee empowerment.
7. Use **visual control** so no problems are hidden (*5S*, *A3*).
8. Use only **reliable, thoroughly tested technology** that serves people and processes.
9. **Grow leaders** who thoroughly understand the work, live the philosophy, and teach it.
10. **Develop exceptional people and teams** who follow the company's philosophy.
11. **Respect the extended network** of partners and suppliers by challenging and helping them improve.
12. **Go and see for yourself** (*genchi genbutsu*) to thoroughly understand the situation.
13. **Make decisions slowly by consensus** (*nemawashi*), thoroughly considering all options; **implement decisions rapidly**.
14. Become a **learning organisation** through relentless reflection (*hansei*) and continuous improvement (*kaizen*).

Principles 1–2 and 12–14 are the ones that translate directly into an agent
memory architecture. Principles 6 and 7 (standard work + visual control) define
what the memory must *store*. Principle 5 defines what the runtime must be able
to *interrupt*.

---

## 2. The two improvement modes: Kaizen vs Kaikaku

| Mode | Japanese | Scope | Cadence | Risk |
|---|---|---|---|---|
| **Kaizen** | 改善 | Incremental, daily, bottom-up from the *gemba* | Continuous | Low |
| **Kaikaku** | 改革 | Radical / transformational redesign of the business model | Rare, deliberate | High |

> "Continuous improvement (*kaizen*) is the key to evolving existing standards…
> It is therefore a daily, continuous activity that acts on processes through
> bottom-up communication, from the *gemba* to the management, **but does not
> change the roots of the business model**." — Toyota Italy, *Beyond Zero*

**Portable rule:** an agent should run **many small, cheap kaizen iterations**
against its current standard, and escalate to a *kaikaku* (large, risky refactor
of its own policy/prompt/architecture) only through an explicit, deliberate gate.
Kaizen must never silently rewrite the agent's identity — that is a separate,
higher-approval act.

---

## 3. The engine: PDCA and Toyota Business Practices (TBP)

Everything Toyota does is a PDCA story. **TBP** is PDCA made explicit in **8
steps**, codified in 2001 as the company-wide standard:

| PDCA | Step | TBP |
|---|---|---|
| **Plan** | 1 | Clarify the problem (ideal vs actual → the gap) |
| | 2 | Break down the problem into specific, manageable pieces; find the priority point of cause |
| | 3 | Set a target — specific, measurable, with a deadline |
| | 4 | Analyse the **root cause** (5-Why at the *genba*, verified by observation, not opinion) |
| | 5 | Develop **countermeasures** against the root cause |
| **Do** | 6 | See countermeasures through (implement, ideally small-scale first) |
| **Check** | 7 | Evaluate **both results and process** (did it hit the target? what was learned? is the gain stable?) |
| **Act** | 8 | **Standardise** the success and **share** the learning (*yokoten*) |

Critical structural facts:

- **Five of the eight steps are Plan.** Toyota front-loads understanding. Most
  failures come from rushing or skipping the Plan steps. *"Teams that struggle
  almost always rushed or skipped the Plan steps."*
- **Step 2 (break down) is the step most people skip** and the one that most
  determines success. Large vague problems cannot be solved directly.
- **Step 3 target vs countermeasure:** *"Implement standardised work" is not a
  target — it is a proposed means.* The target states the **what** and the
  **how-much-by-when**.
- **Step 7 checks two things:** results (did the metric move, measured the same
  way, over what period) **and** process (are the conditions that hold the gain
  still in place — is the strainer still there, who cleans it, how often).
  *"Checking results is the most-skipped step in all of problem solving."*
- **Step 8 has three parts:** standardise, **sustain** (standards drift; layered
  audits confirm months later), and **share** (*yokoten*).

---

## 4. Root cause: 5-Why and the "Therefore Test"

Once organising tool: cause-and-effect / Ishikawa diagram, **Pareto
stratification** (by product, time, location, type) to find the **priority point
of cause**.

The discipline:

- Ask **why** repeatedly (rule of thumb: five times) tracing symptom → root cause.
- **Verify the root cause by observation at the genba**, never assume it from a
  brainstorming session.
- **Therefore Test** to validate the chain: read it backwards — "…(last answer),
  *therefore* (previous answer), *therefore* …". If it does not make sense
  backwards, the chain is not well reasoned.
- Taiichi Ohno: *"When a problem arises, if our search for the cause is not
  thorough, the actions taken can be out of focus."* and *"It is difficult to do
  even though it sounds easy."*

---

## 5. Countermeasure discipline (the most important vocabulary)

Toyota deliberately avoids the word *solution*. A **countermeasure** (対策
*taisaku*) acknowledges our understanding may be incomplete and may need
adjustment.

Two distinct acts that English collapses into "fix":

| Term | Meaning | Example |
|---|---|---|
| **Taisho** 対処 | Immediate response that **contains the symptom** so work can continue | replace the fuse, rework the bad part, add inspection |
| **Taisaku** 対策 | **Countermeasure against the verified root cause** so the problem does not return | redesign the worn fixture |

> *"The most common way a 'solved' problem comes back is declaring victory at
> the taisho and never completing the taisaku."*

Countermeasure **strength ladder** (Toyota pushes every countermeasure as far up
as feasible):

1. **Weak** — leans on vigilance: training, a reminder, an updated SOP. Decays
   with turnover and distraction.
2. **Medium** — **in-process detection / poka-yoke** (mistake-proofing): a
   sensor, andon, vision/torque check that *catches the error after it occurs*
   and stops it moving downstream. Contains, does not prevent.
3. **Strongest** — **mizen-boushi** 未然防止: change the underlying conditions so
   the failure **cannot arise in the first place** (design the failure mode out,
   upstream).

Evaluate candidates on **effectiveness, cost, time, risk**. *"If your best
countermeasure is still a piece of paperwork, that is usually a sign the root
cause was never truly reached."*

---

## 6. Interruption: Jidoka and Andon

- **Jidoka** 自働化 — "automation with a human touch": the machine/line detects an
  abnormality and **stops itself** rather than producing bad output.
- **Andon** 行灯 — the signal that makes the problem visible so it can be
  addressed immediately. Toyota designs the line in segments with **small
  buffers** between them, so most issues are corrected inside the 5–10-minute
  buffer window without shutting the whole line.

**Portable rule (Principle 5):** the loop must be able to **stop the line** —
halt the agent's current action, flag the abnormality, and resolve it *before*
shipping a defective result. Cheap detection + a small buffer beats a full stop.

---

## 7. Standard work: the anchor of all improvement

> Principle 6: *"Standardised tasks are the foundation for continuous
> improvement and employee empowerment."*

The sequence is: **agree the standard → let people try changes against it →
incorporate what works into the new standard → train on it → require it.**

Without a frozen standard there is **no baseline**, and therefore **no
measurable gap** — improvement becomes opinion. Practical consequence: *"A
countermeasure not built into a standard depends on memory and goodwill, and
decays. Standardisation locks the gain and resets the baseline."*

---

## 8. Visual control and the A3

- **5S** — *seiri, seiton, seiso, seiketsu, shitsuke* (sort, set in order, shine,
  standardise, sustain): standardise and optimise the work area.
- **Visual control** — simple systems at the point of work so no problem hides.
- **A3** — the whole PDCA story on a single sheet (297×420 mm). Developed at
  Toyota in the late 1970s and institutionalised through the **Kanri Nouryoku
  ("Kan-Pro") program** run by Masao Nemoto for ~2000 managers. Not about paper:
  LEI names eight facets — paper size, template, storyboard, report,
  problem-solving methodology, management discipline, way of thinking, alignment
  tool. **The constraint forces conciseness, visual communication, structured
  thinking.**

A3 anatomy — **left side = Plan** (background, current condition, problem/goal,
root cause analysis), **right side = Do-Check-Act** (countermeasures,
implementation plan, check/confirmation, follow-up). Plan should take the
majority of the effort.

The Kan-Pro culture point matters as much as the tool: officers asked *"what is
the major cause of the problem?"* rather than *"who made those mistakes?"*, and
Nemoto **praised managers who reported their mistakes**, not their successes.
That is *why* Toyota people do not hide bad news.

---

## 9. Consensus and spread: Nemawashi, Yokoten, Hansei

- **Nemawashi** 根回し — discuss the problem and options with everyone affected,
  collect their ideas, get agreement *before* the decision. Slow to decide,
  **fast to implement**. ("Fire bullets, then cannonballs.")
- **Yokoten** 横展開 — horizontal spread: take a proven countermeasure and the
  thinking behind it to other lines/shifts/plants facing the same problem.
  *"A problem solved on one line is very often present elsewhere."*
- **Hansei** 反省 — relentless reflection: openly identify all weaknesses in the
  process **and in yourself**. *"The other steps fix the problem; reflection
  improves the problem solver."* Expected, scheduled, and taken seriously **even
  when a project succeeds**. Not blame — learning, so capability compounds.

---

## 10. Waste taxonomy

- **Muda** 無駄 — waste (the classic 7 wastes: overproduction, waiting,
  transport, over-processing, inventory, motion, defects).
- **Mura** 斑 — unevenness / inconsistency in workload.
- **Muri** 無理 — overburden on people or machines.

**Heijunka** 平準化 — levelling output by volume *and* mix (produce
`ABABABABA`, not `AAAAABBBB`). **Pull / kanban** — only start work in response to
a signal; avoid push.

---

## 11. What an agent evolution loop must take from this

The non-negotiable mechanisms, in dependency order:

1. **A frozen standard** (baseline) per capability — without it there is no gap.
2. **Observation at the genba** — real telemetry/evidence, not self-report.
3. **A structured problem record** (A3-shaped) with ideal / actual / gap.
4. **Breakdown** into a specific, observable priority point of cause.
5. **A measurable, time-bound target** — never confused with the countermeasure.
6. **A verified root cause** — 5-Why chain that passes the *Therefore Test*.
7. **Countermeasures classified by strength** — taisho vs taisaku vs
   mizen-boushi, so containment is never mistaken for a fix.
8. **A controlled experiment** — small scale first, one variable, measured.
9. **A Check on both results and process** — including "is the gain still
   holding later?"
10. **Standardisation** — promote a proven countermeasure to the new baseline.
11. **Yokoten** — propagate the countermeasure + reasoning to sibling agents.
12. **Hansei** — mandatory reflection, recorded even on success.
13. **Jidoka/andon** — the ability to stop and flag before shipping a defect.
14. **A default to kaizen, a gated path to kaikaku.**

Those 14 are the specification the plugin in this repo implements.

---

## Sources

- Toyota Motor Corporation, *The Toyota Way / TPS* (global.toyota) and
  *Our DNA is Creating Ever-Better Cars*, annual report 2014 — kaizen, jidoka,
  just-in-time, the Five Whys.
- Toyota Italy, *Beyond Zero* booklet — Toyota Way 2001, kaizen vs kaikaku,
  genchi genbutsu, Taiichi Ohno.
- Toyota UK Magazine, *What is kaizen and how does Toyota use it?*
- Toyota Canada, *How Kaizen can power your productivity*.
- Wikipedia, *The Toyota Way* — 14 principles, 4P structure, hansei/kaizen.
- Jeff Liker, *The Toyota Way: 14 Management Principles* (2004), summarised at
  leaneast.com.
- Art of Lean, *TBP (Toyota Business Practice)* and *The 8 Steps of Toyota
  Problem Solving* — 8 steps mapped to PDCA, taisho vs taisaku, mizen-boushi,
  countermeasure strength ladder, yokoten, hansei.
- Art of Lean, *A3 — TPS Encyclopedia* — A3 facets and anatomy.
- Lean Enterprise Institute, *Using A3 Problem Solving to Make the Thinking
  Process Visible* and *How the A3 Came to Be Toyota's Go-To Management Process*
  — TBP, Kan-Pro, Nemoto, the blame-free review culture.
- IndustryWeek, *The Patois of the Toyota Production System* — 8-step patois,
  SMART goal, the Therefore Test, gemba.
- Schwägerman & Ulmer, *The A3 Lean Management and Leadership Thought Process*,
  JTMAE — PDCA/A3/TBP as an integrated culture.
