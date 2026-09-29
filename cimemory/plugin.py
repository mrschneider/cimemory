"""EvolutionMemory — the memory plugin for an agent's continuous evolution.

This is the artifact an agent talks to. It is **backend-agnostic**: hand it any
object satisfying ``MemoryBackend`` and it works. It is **semantic**: it does not
expose ``save``/``load``, it exposes the verbs of Toyota's improvement cycle.

The plugin is not a passive store. It **enforces the discipline** of the TBP
loop, because a memory that merely records is a filing cabinet, not a learning
organisation:

* a root cause cannot be recorded without evidence and a passing Therefore Test;
* a taisaku (root-cause countermeasure) is refused unless a *verified* root cause
  exists — this is what stops symptom-chasing;
* an experiment cannot be standardised unless the Check passed on **results and
  process**;
* reflection (hansei) is mandatory before a gain is locked in — even on success;
* yokoten cannot spread a standard that was never standardised.

Raise ``DisciplineError`` and the loop refuses to advance. That refusal is the
feature.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .backend import BackendCapabilities, MemoryBackend
from .models import (
    Andon,
    Check,
    Countermeasure,
    CountermeasureStrength,
    Experiment,
    ExperimentStatus,
    Hansei,
    Observation,
    Problem,
    ProblemStatus,
    RootCause,
    Spread,
    Standard,
    Target,
    Why,
)


class DisciplineError(ValueError):
    """The loop tried to skip a step Toyota does not allow skipping."""


class EvolutionMemory:
    """An agent's continuous-improvement memory, over any backend."""

    __slots__ = ("backend", "agent", "_journal_enabled")

    def __init__(self, backend: MemoryBackend, agent: str) -> None:
        self.backend = backend
        self.agent = agent
        caps: BackendCapabilities = backend.capabilities()
        self._journal_enabled = caps.supports("append_only_journal")

    # ------------------------------------------------------------------
    # internal plumbing
    # ------------------------------------------------------------------

    def _put(self, rec) -> Any:
        self.backend.write(rec.kind, rec.record_id, rec.to_dict())
        self._log("write", kind=rec.kind, record_id=rec.record_id, agent=self.agent)
        return rec

    def _get(self, kind: str, record_id: str) -> Optional[dict[str, Any]]:
        return self.backend.read(kind, record_id)

    def _require(self, kind: str, record_id: str) -> dict[str, Any]:
        rec = self._get(kind, record_id)
        if rec is None:
            raise KeyError(f"{kind} {record_id!r} not found")
        return rec

    def _log(self, event: str, **fields: Any) -> None:
        if self._journal_enabled:
            self.backend.append({"ts": time.time(), "event": event, **fields})

    # ------------------------------------------------------------------
    # genchi genbutsu — observation
    # ------------------------------------------------------------------

    def observe(
        self,
        metric: str,
        value: float,
        *,
        source: str = "telemetry",
        agent: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> Observation:
        """Record a fact from the gemba. Evidence, never self-report of intent."""
        return self._put(Observation(
            agent=agent or self.agent,
            metric=metric,
            value=float(value),
            source=source,
            context=context or {},
        ))

    def observations(self, metric: Optional[str] = None) -> list[dict[str, Any]]:
        where = {"metric": metric} if metric else None
        return self.backend.query("observation", where=where, order_by="ts")

    # ------------------------------------------------------------------
    # TBP steps 1-2 — clarify and break down
    # ------------------------------------------------------------------

    def open_problem(
        self,
        capability: str,
        ideal: str,
        actual: str,
        gap: str,
        *,
        breakdown: Optional[list[str]] = None,
        priority_point: Optional[str] = None,
    ) -> Problem:
        """A problem is a *gap against a standard*. No standard, no problem."""
        if not (ideal.strip() and actual.strip() and gap.strip()):
            raise DisciplineError(
                "a problem needs ideal, actual and gap — otherwise it is an opinion, "
                "not a gap against a standard (Principle 6)"
            )
        if breakdown and not priority_point:
            raise DisciplineError(
                "step 2 requires a priority point of cause: break the problem down, "
                "then say which piece you will attack first"
            )
        return self._put(Problem(
            agent=self.agent,
            capability=capability,
            ideal=ideal,
            actual=actual,
            gap=gap,
            breakdown=breakdown or [],
            priority_point=priority_point,
        ))

    def set_status(self, problem_id: str, status: ProblemStatus) -> dict[str, Any] | None:
        return self.backend.update("problem", problem_id, {"status": status.value})

    def problems(self, capability: Optional[str] = None) -> list[dict[str, Any]]:
        where = {"capability": capability} if capability else None
        return self.backend.query("problem", where=where, order_by="opened_ts")

    # ------------------------------------------------------------------
    # TBP step 3 — target
    # ------------------------------------------------------------------

    def set_target(
        self,
        problem_id: str,
        metric: str,
        baseline: float,
        goal: float,
        deadline: str,
        *,
        direction: str = "decrease",
    ) -> Target:
        self._require("problem", problem_id)
        if not deadline:
            raise DisciplineError(
                "a target without a deadline is a wish, not a target (TBP step 3)"
            )
        if baseline == goal:
            raise DisciplineError(
                "a target must close a gap; baseline and goal are identical"
            )
        return self._put(Target(
            problem_id=problem_id,
            metric=metric,
            baseline=float(baseline),
            goal=float(goal),
            deadline=deadline,
            direction=direction,
        ))

    # ------------------------------------------------------------------
    # TBP step 4 — root cause (5-Why + Therefore Test)
    # ------------------------------------------------------------------

    def ask_why(
        self,
        problem_id: str,
        level: int,
        question: str,
        answer: str,
        *,
        evidence: str = "",
    ) -> Why:
        self._require("problem", problem_id)
        return self._put(Why(
            problem_id=problem_id,
            level=level,
            question=question,
            answer=answer,
            evidence=evidence,
        ))

    def why_chain(self, problem_id: str) -> list[dict[str, Any]]:
        rows = self.backend.query("why", where={"problem_id": problem_id})
        return sorted(rows, key=lambda r: r.get("level", 0))

    def therefore_test(self, problem_id: str) -> tuple[bool, str]:
        """Read the chain backwards with 'therefore'. Toyota's own check."""
        chain = self.why_chain(problem_id)
        if len(chain) < 2:
            return False, "chain too short to validate (need at least 2 whys)"
        parts = [c["answer"] for c in chain]
        backwards = "  THEREFORE  ".join(reversed(parts))
        structured = "  BECAUSE  ".join(reversed(parts))
        ok = all(p.strip() for p in parts)
        return ok, f"{structured}  =>  check backwards: {backwards}"

    def assert_root_cause(
        self,
        problem_id: str,
        statement: str,
        *,
        verified_by: str,
        therefore_test_ok: Optional[bool] = None,
    ) -> RootCause:
        """Record the root cause. Evidence is mandatory.

        If ``therefore_test_ok`` is not supplied, the plugin runs the Therefore
        Test over the recorded why-chain itself.
        """
        self._require("problem", problem_id)
        if not verified_by.strip():
            raise DisciplineError(
                "an unverified root cause may not be recorded: name the observation "
                "or measurement that proves it (genchi genbutsu, TBP step 4)"
            )
        if therefore_test_ok is None:
            therefore_test_ok, _ = self.therefore_test(problem_id)
        if not therefore_test_ok:
            raise DisciplineError(
                "the 5-Why chain fails the Therefore Test — do not proceed to "
                "countermeasures on a poorly reasoned chain"
            )
        rc = self._put(RootCause(
            problem_id=problem_id,
            statement=statement,
            verified_by=verified_by,
            therefore_test_ok=True,
        ))
        self.backend.update("problem", problem_id,
                            {"status": ProblemStatus.ANALYSED.value})
        return rc

    # ------------------------------------------------------------------
    # TBP step 5 — countermeasures
    # ------------------------------------------------------------------

    def propose_countermeasure(
        self,
        problem_id: str,
        description: str,
        *,
        strength: CountermeasureStrength = CountermeasureStrength.TAISAKU,
        root_cause_id: Optional[str] = None,
        expected_effect: str = "",
        cost: str = "low",
        risk: str = "low",
    ) -> Countermeasure:
        """A taisho may be applied immediately. A taisaku may not exist without a
        verified root cause — that is the line between fixing and firefighting."""
        self._require("problem", problem_id)
        strength = CountermeasureStrength(strength)
        if strength is not CountermeasureStrength.TAISHO:
            if root_cause_id is None:
                raise DisciplineError(
                    f"a {strength.value} must name the root cause it addresses"
                )
            rc = self._require("root_cause", root_cause_id)
            if not (rc.get("verified_by") and rc.get("therefore_test_ok")):
                raise DisciplineError(
                    f"a {strength.value} requires a *verified* root cause; "
                    f"{root_cause_id} is not verified"
                )
            if rc["problem_id"] != problem_id:
                raise DisciplineError("root cause belongs to a different problem")
        return self._put(Countermeasure(
            problem_id=problem_id,
            description=description,
            strength=strength,
            root_cause_id=root_cause_id,
            expected_effect=expected_effect,
            cost=cost,
            risk=risk,
        ))

    def countermeasures(self, problem_id: str) -> list[dict[str, Any]]:
        return self.backend.query("countermeasure", where={"problem_id": problem_id})

    def countermeasure_strength(self, problem_id: str) -> str:
        """The strongest countermeasure proposed so far, per the strength ladder."""
        cms = self.countermeasures(problem_id)
        if not cms:
            return "none"
        best = max(cms, key=lambda c: {"taisho": 1, "taisaku": 2,
                                       "mizen_boushi": 3}[c["strength"]])
        return best["strength"]

    # ------------------------------------------------------------------
    # TBP step 6 — Do
    # ------------------------------------------------------------------

    def start_experiment(
        self,
        problem_id: str,
        target_id: str,
        hypothesis: str,
        countermeasure_ids: list[str],
        *,
        metric: str = "",
        before_value: Optional[float] = None,
    ) -> Experiment:
        problem = self._require("problem", problem_id)
        target = self._require("target", target_id)
        if target["problem_id"] != problem_id:
            raise DisciplineError("target belongs to a different problem")
        if not countermeasure_ids:
            raise DisciplineError("an experiment must test at least one countermeasure")
        exp = self._put(Experiment(
            problem_id=problem_id,
            target_id=target_id,
            hypothesis=hypothesis,
            countermeasure_ids=list(countermeasure_ids),
            metric=metric or target["metric"],
            before_value=before_value,
        ))
        self.backend.update("problem", problem_id,
                            {"status": ProblemStatus.IN_EXPERIMENT.value})
        self._log("experiment_started", experiment_id=exp.experiment_id,
                  problem_id=problem_id, capability=problem["capability"])
        return exp

    def log_do(self, experiment_id: str, entry: str) -> dict[str, Any] | None:
        exp = self._require("experiment", experiment_id)
        log = list(exp.get("do_log", []))
        log.append(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {entry}")
        return self.backend.update("experiment", experiment_id, {"do_log": log})

    # ------------------------------------------------------------------
    # TBP step 7 — Check (results AND process)
    # ------------------------------------------------------------------

    def check(
        self,
        experiment_id: str,
        after_value: float,
        *,
        period: str = "",
        process_holds: bool = False,
        process_notes: str = "",
    ) -> Check:
        """Evaluate results against the target *and* whether the conditions that
        hold the gain are in place. Implementation is not improvement."""
        exp = self._require("experiment", experiment_id)
        target = self._require("target", exp["target_id"])
        results_met = Target(**target).met(float(after_value))
        chk = self._put(Check(
            experiment_id=experiment_id,
            metric=target["metric"],
            after_value=float(after_value),
            results_met=results_met,
            process_holds=process_holds,
            process_notes=process_notes,
            period=period,
        ))
        status = (ExperimentStatus.PASSED if chk.successful
                  else ExperimentStatus.FAILED)
        self.backend.update("experiment", experiment_id, {
            "after_value": float(after_value),
            "status": status.value,
            "check_id": chk.check_id,
            "closed_ts": time.time(),
        })
        self._log("check", experiment_id=experiment_id,
                  results_met=results_met, process_holds=process_holds)
        return chk

    # ------------------------------------------------------------------
    # hansei — reflection (mandatory, even on success)
    # ------------------------------------------------------------------

    def hansei(
        self,
        subject_id: str,
        *,
        went_well: Optional[list[str]] = None,
        went_poorly: Optional[list[str]] = None,
        why: Optional[list[str]] = None,
        next_time: Optional[list[str]] = None,
    ) -> Hansei:
        if not went_poorly:
            raise DisciplineError(
                "hansei is not a victory lap: name at least one thing that went "
                "poorly, even when the experiment succeeded (Principle 14)"
            )
        return self._put(Hansei(
            subject_id=subject_id,
            went_well=went_well or [],
            went_poorly=went_poorly,
            why=why or [],
            next_time=next_time or [],
        ))

    # ------------------------------------------------------------------
    # TBP step 8 — Act: standardise and share
    # ------------------------------------------------------------------

    def standardise(
        self,
        experiment_id: str,
        description: str,
        *,
        capability: str = "",
    ) -> Standard:
        """Promote a proven countermeasure to the new baseline.

        Requires: a successful Check (results *and* process) and a recorded
        hansei. Both are non-negotiable.
        """
        exp = self._require("experiment", experiment_id)
        if exp.get("status") != ExperimentStatus.PASSED.value:
            raise DisciplineError(
                "cannot standardise: the Check did not pass on both results and "
                "process. Standardising an unverified gain locks in a fiction."
            )
        chk = self._require("check", exp["check_id"])
        if not (chk["results_met"] and chk["process_holds"]):
            raise DisciplineError("cannot standardise: Check is not successful")
        if not self.backend.query("hansei", where={"subject_id": experiment_id}):
            raise DisciplineError(
                "cannot standardise without hansei: reflection is mandatory before "
                "a gain is locked into the standard (Principle 14)"
            )
        problem = self._require("problem", exp["problem_id"])
        cap = capability or problem["capability"]
        previous = self.active_standard(cap)
        new_version = (previous["version"] + 1) if previous else 1
        std = self._put(Standard(
            agent=self.agent,
            capability=cap,
            description=description,
            from_experiment=experiment_id,
            version=new_version,
            supersedes=previous["standard_id"] if previous else None,
            active=True,
        ))
        if previous:
            self.backend.update("standard", previous["standard_id"], {"active": False})
        self.backend.update("problem", exp["problem_id"],
                            {"status": ProblemStatus.STANDARDISED.value})
        self._log("standardised", standard_id=std.standard_id, capability=cap,
                  version=new_version)
        return std

    def active_standard(self, capability: str) -> Optional[dict[str, Any]]:
        rows = self.backend.query(
            "standard", where={"capability": capability, "active": True}
        )
        return rows[-1] if rows else None

    def standards(self, capability: Optional[str] = None) -> list[dict[str, Any]]:
        where = {"capability": capability} if capability else None
        return self.backend.query("standard", where=where, order_by="ts")

    def yokoten(
        self,
        standard_id: str,
        targets: list[str],
        *,
        rationale: str = "",
    ) -> Spread:
        """Spread a *standardised* countermeasure to sibling agents."""
        std = self._require("standard", standard_id)
        if not std.get("active"):
            raise DisciplineError(
                "cannot spread a superseded standard — yokoten carries the current "
                "standard, not a stale one"
            )
        if not targets:
            raise DisciplineError("yokoten needs at least one target agent")
        return self._put(Spread(
            standard_id=standard_id,
            from_agent=self.agent,
            targets=list(targets),
            rationale=rationale,
        ))

    def mark_spread(self, spread_id: str, applied: list[str]) -> dict[str, Any] | None:
        return self.backend.update("spread", spread_id, {"applied": list(applied)})

    # ------------------------------------------------------------------
    # Principle 5 — jidoka / andon (stop the line)
    # ------------------------------------------------------------------

    def andon(
        self,
        reason: str,
        *,
        severity: str = "warning",
        stopped: bool = False,
        agent: Optional[str] = None,
    ) -> Andon:
        """Raise a stop-the-line signal the moment an abnormality is seen."""
        if severity not in ("info", "warning", "critical"):
            raise DisciplineError("severity must be info|warning|critical")
        a = self._put(Andon(
            agent=agent or self.agent,
            severity=severity,
            reason=reason,
            stopped=stopped,
        ))
        self._log("andon", andon_id=a.andon_id, severity=severity, stopped=stopped)
        return a

    def resolve_andon(self, andon_id: str, resolution: str) -> dict[str, Any] | None:
        self._require("andon", andon_id)
        return self.backend.update("andon", andon_id, {
            "resolved": True,
            "resolution": resolution,
            "resolved_ts": time.time(),
        })

    def open_andons(self, agent: Optional[str] = None) -> list[dict[str, Any]]:
        where = {"agent": agent} if agent else None
        return [a for a in self.backend.query("andon", where=where)
                if not a.get("resolved")]

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------

    def a3(self, problem_id: str) -> str:
        """Render the single-sheet A3 story. Left side = Plan, right side = DCA."""
        p = self._require("problem", problem_id)
        targets = self.backend.query("target", where={"problem_id": problem_id})
        rcs = self.backend.query("root_cause", where={"problem_id": problem_id})
        cms = self.countermeasures(problem_id)
        exps = self.backend.query("experiment", where={"problem_id": problem_id})
        stds = [s for s in self.standards(p["capability"]) if s["active"]]

        def _bullets(items, fmt):
            return "\n".join(f"- {fmt(i)}" for i in items) or "- _(none)_"

        lines = [
            f"# A3 — {p['capability']}  ({p['problem_id']})",
            f"_agent: {p['agent']} · status: {p['status']}_",
            "",
            "## 1. Background / standard", f"- **ideal:** {p['ideal']}",
            f"- **actual:** {p['actual']}", f"- **gap:** {p['gap']}",
            "",
            "## 2. Breakdown",
            _bullets(p.get("breakdown", []), lambda b: str(b)),
            f"- **priority point:** {p.get('priority_point') or '_(none)_'}",
            "",
            "## 3. Target",
            _bullets(targets, lambda t: (
                f"{t['metric']}: {t['baseline']} → {t['goal']} by {t['deadline']}")),
            "",
            "## 4. Root cause",
            _bullets(rcs, lambda r: (
                f"{r['statement']} (verified by {r['verified_by']})")),
            "",
            "## 5. Countermeasures",
            _bullets(cms, lambda c: (
                f"[{c['strength']}] {c['description']}")),
            "",
            "## 6-7. Do / Check",
            _bullets(exps, lambda e: (
                f"{e['experiment_id']}: {e.get('status')} "
                f"(before {e.get('before_value')} → after {e.get('after_value')})")),
            "",
            "## 8. Standard / yokoten",
            _bullets(stds, lambda s: f"v{s['version']}: {s['description']}"),
        ]
        return "\n".join(lines)

    def status(self) -> dict[str, Any]:
        """Cheap health view: what is open, what is stuck."""
        caps = self.backend.capabilities()
        open_problems = [p for p in self.problems()
                         if p["status"] not in ("standardised", "abandoned")]
        return {
            "agent": self.agent,
            "backend": caps.name,
            "backend_capabilities": caps.__dict__,
            "standards": len([s for s in self.standards() if s["active"]]),
            "open_problems": len(open_problems),
            "open_andons": len(self.open_andons()),
            "journal_entries": (len(self.backend.journal())
                                if caps.supports("append_only_journal") else None),
        }

    def close(self) -> None:
        self.backend.close()
