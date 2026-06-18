"""Routing policy — Phase 1 (+high-stakes gate). Implements route() over rules.yaml (§4a).

Decide-only: no execution, no gateway wiring. Given a RoutingContext, returns a
RouteDecision carrying mandatory, human-readable reasons (the confidence payload).
"""
from __future__ import annotations
import os
import yaml
from .context import RoutingContext, RouteDecision, Tier

_RULES_PATH = os.path.join(os.path.dirname(__file__), "rules.yaml")
_TIER = {"hermes": Tier.LOCAL, "codex": Tier.CODEX, "claude": Tier.CLAUDE}


def load_rules(path: str = _RULES_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def route(ctx: RoutingContext, rules: dict | None = None) -> RouteDecision:
    rules = rules or load_rules()
    types = rules["task_types"]
    rule = types.get(ctx.task_type, types["_default"])
    models = rules.get("models", {})
    defaults = rules.get("defaults", {})
    autonomy = rules.get("autonomy", {})
    esc_service = rule["escalates_to"]
    esc_tier = _TIER[esc_service]
    threshold = rule.get("threshold", defaults.get("self_grade_threshold", 0.6))
    force_hs = autonomy.get("force_approval_high_stakes", False)
    reasons: list[str] = []

    def escalate() -> RouteDecision:
        is_high_stakes = ctx.high_stakes or rule.get("always_escalate", False)
        gate = False
        if esc_service == "claude":
            a = autonomy.get("claude", {})
            hard = a.get("hard_stop_usd", 90.0)
            cap = a.get("day_cap_usd", 20.0)
            auto_under = a.get("auto_if_cost_under", 0.50)
            if ctx.day_spend_usd >= hard:
                gate = True
                reasons.append(f"BLOCKED: day spend ${ctx.day_spend_usd:.2f} >= hard stop ${hard:.0f} — needs your call")
            elif ctx.est_cost_usd >= auto_under or ctx.day_spend_usd >= cap:
                gate = True
                reasons.append(f"Claude cost-gated: est ${ctx.est_cost_usd:.2f} >= ${auto_under:.2f} or day ${ctx.day_spend_usd:.2f} >= cap ${cap:.0f}")
            else:
                reasons.append(f"Claude cost-ok: est ${ctx.est_cost_usd:.2f} < ${auto_under:.2f}, day ${ctx.day_spend_usd:.2f} < cap ${cap:.0f}")
        else:
            reasons.append("Codex auto tier (flat OAuth, ~$0 marginal) — no cost gate")
        if is_high_stakes and force_hs:
            reasons.append("high-stakes -> forced approval regardless of cost")
        requires_approval = gate or (is_high_stakes and force_hs)
        conf = ctx.self_grade.confidence if ctx.self_grade else 1.0
        return RouteDecision(esc_tier, models.get(esc_service, ""), reasons, conf, requires_approval)

    if rule.get("always_escalate"):
        reasons.append(f"{ctx.task_type}: always escalate (high-stakes default on) -> {esc_service}")
        return escalate()
    if ctx.high_stakes and rule.get("high_stakes_eager"):
        reasons.append(f"high-stakes {ctx.task_type}: straight to {esc_service}")
        return escalate()
    if ctx.self_grade is None:
        reasons.append("first pass: cheap local probe on Qwen before any escalation")
        return RouteDecision(Tier.LOCAL, models.get("hermes", ""), reasons, 0.0, False)

    sg = ctx.self_grade
    checks = sg.checks_run or []
    failed = [c.get("name", "?") for c in checks if c.get("passed") is False]
    if failed:
        reasons.append(f"local checks failed ({', '.join(failed)}) -> escalate to {esc_service}")
        return escalate()
    if checks and not ctx.high_stakes:
        reasons.append(f"deterministic checks pass -> keep local (Qwen), $0 (self-grade {sg.confidence:.2f} noted)")
        return RouteDecision(Tier.LOCAL, models.get("hermes", ""), reasons, max(sg.confidence, 0.9), False)
    if sg.confidence < threshold:
        why = f"self-grade {sg.confidence:.2f} < theta {threshold:.2f}"
        if sg.uncertainties:
            why += f" (unsure: {'; '.join(sg.uncertainties[:2])})"
        reasons.append(f"{why} -> escalate to {esc_service}")
        return escalate()

    reasons.append(f"self-grade {sg.confidence:.2f} >= theta {threshold:.2f} and checks pass -> keep local (Qwen), $0")
    return RouteDecision(Tier.LOCAL, models.get("hermes", ""), reasons, sg.confidence, False)
