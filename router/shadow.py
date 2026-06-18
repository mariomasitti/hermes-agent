"""A2.5a SHADOW — observe-only routing on REAL gateway delegation traffic (HERMES-ROUTER-001).

Deploys to the live gateway as `router/shadow.py`. (Kept here in the Mac repo as the mirror copy,
since the engine package otherwise lives only on hermes — a flagged latent risk.)

Logs what `router.policy.route()` WOULD decide for each real delegated task, WITHOUT changing the
model the gateway actually uses. The subagent still runs on the static `config.yaml` model exactly as
today. This is the zero-risk first step of A2.5 (gateway wiring): validate routing quality on real
traffic before any behavior change.

Guarantees (the whole reason this is safe to wire into the live delegate path):
  - FAIL-OPEN: every entry point swallows all exceptions; delegation NEVER breaks if the router does.
  - KILL-SWITCH: disabled unless `HERMES_ROUTER_DELEGATE=1` or `delegation.router_enabled` is true
    (default OFF). `HERMES_ROUTER_DELEGATE=0` force-disables regardless of config.
  - ADDITIVE / ZERO BEHAVIOR CHANGE: nothing here selects the model; it only writes a best-effort
    fleet.db row tagged outcome 'a2.5a-shadow/' recording {would_route_to, requires_approval, reason}.
"""
from __future__ import annotations
import os

# Only the security class matters at DISPATCH time: it always-escalates, so the router would GATE it
# (a meaningful divergence from the gateway's static local run). Every other class routes local-first
# on the first pass (no self-grade yet), so it agrees with the gateway's current behavior by design.
_SECURITY_HINT = ("auth", "authenticat", "credential", "secret", "token", "password",
                  "oauth", "jwt", "encrypt", "payment", "billing", "api key", "api-key", "vault")


def enabled(config=None) -> bool:
    """Kill-switch. Env wins over config; default OFF until shadow data proves routing on real traffic."""
    env = os.environ.get("HERMES_ROUTER_DELEGATE", "").strip()
    if env == "0":
        return False
    if env == "1":
        return True
    try:
        return bool((config or {}).get("router_enabled", False))
    except Exception:
        return False


def _infer_task_type(text):
    t = (text or "").lower()
    if any(k in t for k in _SECURITY_HINT):
        return "security", True
    return "general", False


def _shadow_one(task_text, config, static_model):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from router.context import RoutingContext
    from router import policy, ledger
    task_type, high_stakes = _infer_task_type(task_text)
    ctx = RoutingContext(task_type=task_type, task_text=(task_text or "")[:4000],
                         self_grade=None, high_stakes=high_stakes)
    d = policy.route(ctx)
    would = d.tier.value if hasattr(d.tier, "value") else str(d.tier)
    agree = (would == "hermes") and not d.requires_approval
    reason = list(d.reason) + [
        f"[a2.5a-shadow] dispatch-time/first-pass; gateway ACTUALLY ran static="
        f"{static_model or 'qwen-local'}; router would_route={would} "
        f"approval={d.requires_approval} agree_with_static={agree}"]
    ledger.record_delegation(
        task_type, "hermes", static_model or "qwen-local", reason,
        {"a2.5a_shadow": True, "would_route_to": would, "requires_approval": d.requires_approval,
         "agree": agree, "task_text": (task_text or "")[:300]},
        outcome="a2.5a-shadow/")
    return {"would_route_to": would, "requires_approval": d.requires_approval, "agree": agree}


def shadow_log_tasks(goal=None, tasks=None, role=None, config=None):
    """Called once per delegate_task, right after config load. Observe-only, fail-open. Logs a shadow
    routing decision for the single goal or each batch task. Returns nothing; never raises."""
    try:
        if not enabled(config):
            return
        static_model = None
        try:
            static_model = (config or {}).get("model")
        except Exception:
            pass
        texts = []
        if goal:
            texts.append(goal)
        if tasks:
            for t in tasks:
                try:
                    g = t.get("goal") if isinstance(t, dict) else None
                    if g:
                        texts.append(g)
                except Exception:
                    pass
        for txt in texts[:20]:                 # cap shadow-logging fan-out
            try:
                _shadow_one(txt, config, static_model)
            except Exception:
                pass                           # fail-open per task
    except Exception:
        pass                                   # fail-open overall


# ── standalone test (run under the gateway venv; writes to a TEMP fleet.db) ────────────────────────
if __name__ == "__main__":
    import sys, tempfile, os as _os
    db = _os.path.join(tempfile.mkdtemp(), "shadow_test.db")
    _os.environ["FLEET_DB"] = db
    _os.environ["HERMES_ROUTER_DELEGATE"] = "1"
    # build the schema the ledger expects
    gw = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    sys.path.insert(0, gw)
    import sqlite3
    sqlite3.connect(db).executescript(
        "CREATE TABLE delegations (id TEXT PRIMARY KEY, task_type TEXT, chosen_service TEXT, "
        "chosen_model TEXT, reason TEXT, route_inputs TEXT, outcome TEXT, escalated_from TEXT, "
        "local_attempt_id TEXT, result_quality INT, budget_remaining_at_time REAL, created_at REAL);")
    cfg = {"router_enabled": True, "model": "Qwen3.6-35B.gguf"}
    shadow_log_tasks(goal="Add a helper to parse the CSV header", config=cfg)
    shadow_log_tasks(goal="Rotate the OAuth client secret and update the auth middleware", config=cfg)
    shadow_log_tasks(tasks=[{"goal": "refactor the parser"}, {"goal": "review the JWT token handling"}], config=cfg)
    # also prove the kill-switch
    _os.environ["HERMES_ROUTER_DELEGATE"] = "0"
    shadow_log_tasks(goal="this must NOT be logged (kill-switch on)", config=cfg)
    rows = sqlite3.connect(db).execute(
        "SELECT task_type, outcome, json_extract(route_inputs,'$.would_route_to'), "
        "json_extract(route_inputs,'$.requires_approval'), json_extract(route_inputs,'$.agree') "
        "FROM delegations ORDER BY created_at").fetchall()
    print(f"shadow rows logged: {len(rows)} (expect 4 — kill-switch row suppressed)")
    for r in rows:
        print(f"  type={r[0]:<9} {r[1]} would_route={r[2]:<7} approval={r[3]} agree={r[4]}")
    ok = (len(rows) == 4
          and any(r[0] == "security" and r[2] == "claude" and r[3] == 1 for r in rows)
          and any(r[0] == "general" and r[2] == "hermes" and r[4] == 1 for r in rows))
    print("\nSELFTEST:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
