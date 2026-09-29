"""KaizenLoop — the eight TBP steps wired into one reproducible cycle.

``EvolutionMemory`` is the storage-and-discipline layer. ``KaizenLoop`` is the
engine that walks a problem through the cycle and refuses to skip steps.

The loop also encodes the **kaizen / kaikaku gate**: daily improvement acts on
the process against the current standard; changing the standard's *roots* — the
agent's policy, prompt, architecture — is a different, rarer act that needs an
explicit escalation and a human approval token.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .models import CountermeasureStrength, Hansei, Standard, Target
from .plugin import DisciplineError, EvolutionMemory


# --------------------------------------------------------------------------
# scope gate
# --------------------------------------------------------------------------

class KaikakuNotApproved(DisciplineError):
    """Raised when the loop tries to make a radical change without approval."""


@dataclass
class ChangeScope:
    """How big a change is this?

    ``kaizen`` = improve the process against the existing standard.
    ``kaikaku`` = change the roots: the agent's policy, objective, prompts or
    architecture. Kaikaku needs an explicit approval token.
    """

    mode: str = "kaizen"           # "kaizen" | "kaikaku"
    touches_roots: bool = False
    approval_token: Optional[str] = None

    def validate(self) -> None:
        if self.mode not in ("kaizen", "kaikaku"):
            raise DisciplineError("mode must be 'kaizen' or 'kaikaku'")
        if self.mode == "kaikaku" or self.touches_roots:
            if not self.approval_token:
                raise KaikakuNotApproved(
                    "kaikaku changes the roots of the standard and requires an "
                    "explicit approval token; run it as a deliberate, gated act"
                )


# --------------------------------------------------------------------------
# cycle spec / outcome
# --------------------------------------------------------------------------

@dataclass
class CountermeasureSpec:
    description: str
    strength: CountermeasureStrength = CountermeasureStrength.TAISAKU
    expected_effect: str = ""
    cost: str = "low"
    risk: str = "low"


def normalize_countermeasure(raw: Any) -> CountermeasureSpec:
    """Accept a CountermeasureSpec, or a compact ``(description, strength)`` pair."""
    if isinstance(raw, CountermeasureSpec):
        return raw
    if isinstance(raw, (tuple, list)) and len(raw) == 2:
        return CountermeasureSpec(description=raw[0], strength=raw[1])
    return CountermeasureSpec(description=str(raw))


@dataclass
class KaizenSpec:
    """Everything one full cycle needs. One problem, one target, one experiment."""

    capability: str
    ideal: str
    actual: str
    gap: str
    metric: str
    goal: float
    deadline: str
    breakdown: list[str] = field(default_factory=list)
    priority_point: Optional[str] = None
    direction: str = "decrease"
    whys: list[tuple[str, str, str]] = field(default_factory=list)  # (q, a, evidence)
    root_cause: str = ""
    root_cause_verified_by: str = ""
    countermeasures: list[Any] = field(default_factory=list)  # CountermeasureSpec | (desc, strength)
    cm_effects: dict[str, str] = field(default_factory=dict)  # desc -> expected effect
    do_log: list[str] = field(default_factory=list)           # step 6 entries
    hypothesis: str = ""
    before_value: Optional[float] = None
    after_value: Optional[float] = None
    period: str = ""
    process_holds: bool = False
    process_notes: str = ""
    standard_description: str = ""
    went_well: list[str] = field(default_factory=list)
    went_poorly: list[str] = field(default_factory=list)
    reflection_why: list[str] = field(default_factory=list)
    next_time: list[str] = field(default_factory=list)
    spread_to: list[str] = field(default_factory=list)
    scope: ChangeScope = field(default_factory=ChangeScope)


@dataclass
class CycleOutcome:
    problem_id: str
    target_id: str
    experiment_id: str
    check_passed: bool
    standard_id: Optional[str] = None
    standard_version: Optional[int] = None
    spread_id: Optional[str] = None
    a3: str = ""
    steps_completed: list[str] = field(default_factory=list)

    @property
    def improved(self) -> bool:
        return self.standard_id is not None


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------

class KaizenLoop:
    def __init__(self, memory: EvolutionMemory) -> None:
        self.mem = memory

    # -- TBP 1..8 ---------------------------------------------------------

    def run(self, spec: KaizenSpec) -> CycleOutcome:
        """Run one full PDCA cycle. Steps 1-5 are Plan; most of the work is there."""
        spec.scope.validate()
        mem = self.mem
        done: list[str] = []

        problem = mem.open_problem(
            spec.capability, spec.ideal, spec.actual, spec.gap,
            breakdown=spec.breakdown, priority_point=spec.priority_point,
        )
        done.append("1-clarify")
        if spec.breakdown:
            done.append("2-breakdown")

        baseline = spec.before_value if spec.before_value is not None else 0.0
        if spec.before_value is None:
            obs = mem.observations(spec.metric)
            baseline = obs[-1]["value"] if obs else 0.0
        target = mem.set_target(
            problem.problem_id, spec.metric, baseline, spec.goal, spec.deadline,
            direction=spec.direction,
        )
        done.append("3-target")

        for i, (question, answer, evidence) in enumerate(spec.whys, start=1):
            mem.ask_why(problem.problem_id, i, question, answer, evidence=evidence)
        if spec.whys:
            done.append("4-whys")
        rc = mem.assert_root_cause(
            problem.problem_id, spec.root_cause,
            verified_by=spec.root_cause_verified_by,
        )
        done.append("4-root-cause")

        cm_ids: list[str] = []
        for raw in spec.countermeasures:
            cm = normalize_countermeasure(raw)
            rec = mem.propose_countermeasure(
                problem.problem_id, cm.description,
                strength=cm.strength, root_cause_id=rc.root_cause_id,
                expected_effect=cm.expected_effect or spec.cm_effects.get(
                    cm.description, ""),
                cost=cm.cost, risk=cm.risk,
            )
            cm_ids.append(rec.countermeasure_id)
        done.append("5-countermeasures")

        exp = mem.start_experiment(
            problem.problem_id, target.target_id, spec.hypothesis, cm_ids,
            metric=spec.metric, before_value=baseline,
        )
        for entry in spec.do_log:
            mem.log_do(exp.experiment_id, entry)
        done.append("6-do")

        chk = mem.check(
            exp.experiment_id,
            spec.after_value if spec.after_value is not None else baseline,
            period=spec.period, process_holds=spec.process_holds,
            process_notes=spec.process_notes,
        )
        done.append("7-check")

        mem.hansei(
            exp.experiment_id,
            went_well=spec.went_well, went_poorly=spec.went_poorly,
            why=spec.reflection_why, next_time=spec.next_time,
        )
        done.append("8-hansei")

        standard: Optional[Standard] = None
        spread_id: Optional[str] = None
        if chk.successful:
            standard = mem.standardise(
                exp.experiment_id,
                spec.standard_description or f"improved {spec.capability}",
            )
            done.append("8-standardise")
            if spec.spread_to:
                spread = mem.yokoten(
                    standard.standard_id, spec.spread_to,
                    rationale=f"proven on {spec.capability}",
                )
                spread_id = spread.spread_id
                done.append("8-yokoten")

        return CycleOutcome(
            problem_id=problem.problem_id,
            target_id=target.target_id,
            experiment_id=exp.experiment_id,
            check_passed=chk.successful,
            standard_id=standard.standard_id if standard else None,
            standard_version=standard.version if standard else None,
            spread_id=spread_id,
            a3=mem.a3(problem.problem_id),
            steps_completed=done,
        )

    # -- sustain: the step everyone forgets --------------------------------

    def audit_standard(self, capability: str, observed_value: float) -> dict[str, Any]:
        """Follow-up audit: is the standard still held?

        Standards drift. Without a follow-up the old condition quietly returns.
        """
        std = self.mem.active_standard(capability)
        if std is None:
            raise DisciplineError(f"no active standard for {capability!r}")
        exp = self.mem.backend.read("experiment", std["from_experiment"])
        if exp is None:
            raise DisciplineError("standard references a missing experiment")
        target = self.mem.backend.read("target", exp["target_id"])
        if target is None:
            raise DisciplineError("experiment references a missing target")
        holds = Target(**target).met(observed_value)
        if not holds:
            self.mem.andon(
                f"standard drift on {capability}: {observed_value} violates "
                f"target {target['goal']} (v{std['version']})",
                severity="warning", stopped=False,
            )
        self.mem._log("standard_audit", capability=capability,
                      standard_id=std["standard_id"], holds=holds)
        return {"standard_id": std["standard_id"], "holds": holds,
                "observed": observed_value, "goal": target["goal"]}

    # -- history -----------------------------------------------------------

    def improvements(self, capability: Optional[str] = None) -> list[dict[str, Any]]:
        """The evolution log: every standardised gain, newest last."""
        stds = self.mem.standards(capability)
        return sorted(stds, key=lambda s: s["version"])
