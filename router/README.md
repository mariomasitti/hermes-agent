# HERMES-ROUTER-001 — router package

Modular delegation router. **In-gateway but coupled at ONE seam:** the gateway's
delegation path calls `router.policy.route()` + `router.ledger.*`; nothing here
imports gateway internals, so the package stays liftable.

Phase 0 status: scaffold only — nothing in the live gateway imports this yet.

- context.py  — RoutingContext / RouteDecision / Verdict / SelfGrade
- rules.yaml  — the routing matrix (thresholds are starting guesses)
- policy.py   — route(ctx) -> RouteDecision  (stub; Phase 1)
- tracing.py  — OTel -> self-hosted Phoenix
- ledger.py   — fleet.db writer (single source of truth)

Full design: research/delegation-router/HERMES-ROUTER-001-CHARTER.md (on the Mac).
