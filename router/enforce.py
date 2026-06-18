"""Router Phase 4 — budget & autonomy ENFORCEMENT.

rules.yaml already DEFINES the guards + autonomy knobs, and policy.route() already computes
`requires_approval`. This module makes them BITE:
  - live usage from fleet.db (escalations/hour, estimated day-spend),
  - per-task runaway guards (escalations, wall-clock, est-$) that BLOCK escalation, and
  - an approval gate that actually PAUSES — with no approver, the model is NOT called.

Honest about money: cloud is reached over FLAT-RATE OAuth subscriptions (no per-call billing),
so the $ figures here are ESTIMATES (rules.yaml `est_cloud_call_usd`) used only for the day-cap /
hard-stop ceilings. The hard-enforced guards are the COUNT and WALL-CLOCK ones — those are real.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from . import ledger


@dataclass
class GateResult:
    allowed: bool                 # did the runaway guards permit it?
    requires_approval: bool       # did policy/autonomy require human approval?
    executed: bool                # was the action actually run?
    reasons: list = field(default_factory=list)
    tripped: list = field(default_factory=list)   # which guards blocked
    output: object = None         # the action's return value, when executed


class BudgetGate:
    """Per-task enforcement. One gate instance per task run; it counts that task's own
    escalations/spend in-process and reads the ledger for the hour/day windows."""

    def __init__(self, rules: dict, task_id: str):
        self.rules = rules
        self.guards = rules.get("guards", {})
        self.task_id = task_id
        self.escalations_this_task = 0
        self.est_spend_task = 0.0
        self.task_started = time.time()

    # ----- live usage from the ledger -----
    def _hour_escalations(self) -> int:
        c = ledger._conn()
        try:
            return c.execute(
                "SELECT COUNT(*) FROM delegations WHERE escalated_from IS NOT NULL AND created_at >= ?",
                (time.time() - 3600,)).fetchone()[0]
        finally:
            c.close()

    def est_day_spend(self) -> float:
        """ESTIMATED cloud spend today (OAuth is flat-rate; this drives the day-cap ceiling only)."""
        rate = self.guards.get("est_cloud_call_usd", 0.02)
        c = ledger._conn()
        try:
            n = c.execute(
                "SELECT COUNT(*) FROM delegations WHERE chosen_service IN ('claude','codex') AND created_at >= ?",
                (time.time() - 86400,)).fetchone()[0]
        finally:
            c.close()
        return n * rate

    # ----- runaway guards (the hard-enforced layer) -----
    def authorize(self, decision, est_cost_usd: float = 0.0) -> GateResult:
        """Pre-flight check — does NOT execute. Returns whether escalation is allowed
        and whether it needs approval."""
        g, tripped, reasons = self.guards, [], list(decision.reason)
        if self.escalations_this_task + 1 > g.get("max_escalations_per_task", 1 << 30):
            tripped.append(f"max_escalations_per_task={g['max_escalations_per_task']} "
                           f"(this would be #{self.escalations_this_task + 1})")
        hr = self._hour_escalations()
        if hr + 1 > g.get("max_escalations_per_hour", 1 << 30):
            tripped.append(f"max_escalations_per_hour={g['max_escalations_per_hour']} (already {hr} this hour)")
        mw = g.get("max_wall_clock_per_task_s")
        elapsed = time.time() - self.task_started
        if mw and elapsed > mw:
            tripped.append(f"max_wall_clock_per_task_s={mw} (task at {elapsed:.0f}s)")
        proj = self.est_spend_task + est_cost_usd
        if proj > g.get("max_usd_per_task", 1e18):
            tripped.append(f"max_usd_per_task=${g['max_usd_per_task']} (est ${proj:.2f})")
        return GateResult(allowed=not tripped, requires_approval=bool(decision.requires_approval),
                          executed=False, reasons=reasons, tripped=tripped)

    # ----- the gate that actually pauses -----
    def run_or_pause(self, decision, action, est_cost_usd: float = 0.0,
                     approver=None, task_type: str = "") -> GateResult:
        """Enforce, then maybe execute `action` (a 0-arg callable doing the real escalation).
          - runaway guard tripped  -> BLOCKED, action NOT called.
          - approval required       -> approver(decision) must return True, else PAUSED (not called).
          - otherwise               -> action() runs; per-task counters advance.
        Every outcome is logged to fleet.db (phase4-enforce/*)."""
        res = self.authorize(decision, est_cost_usd)
        svc = getattr(decision.tier, "value", str(decision.tier))

        if not res.allowed:
            res.reasons.append(f"BLOCKED by runaway guard: {res.tripped}")
            self._log(task_type, svc, "blocked", res, est_cost_usd)
            return res

        if res.requires_approval:
            granted = bool(approver(decision)) if approver else False
            if not granted:
                res.reasons.append("PAUSED: approval required, none granted -> model NOT called")
                self._log(task_type, svc, "paused", res, est_cost_usd)
                return res
            res.reasons.append("approval GRANTED -> proceeding")

        res.output = action()
        res.executed = True
        self.escalations_this_task += 1
        self.est_spend_task += est_cost_usd
        res.reasons.append(f"executed (task escalation #{self.escalations_this_task}, "
                           f"est task spend ${self.est_spend_task:.2f})")
        self._log(task_type, svc, "executed", res, est_cost_usd)
        return res

    def _log(self, task_type, svc, kind, res, est_cost_usd):
        try:
            ledger.record_delegation(
                task_type or "_enforce", svc, getattr(self, "_model", svc),
                res.reasons, {"task_id": self.task_id, "kind": kind,
                              "tripped": res.tripped, "est_cost_usd": est_cost_usd,
                              "escalations_this_task": self.escalations_this_task, "real": True},
                outcome=f"phase4-enforce/{kind}")
        except Exception:
            pass
