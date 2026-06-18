"""Phase 3: escalation execution.

- mock_provider: deterministic stand-in (used while OAuth isn't authenticated).
- gateway_provider: REAL call via the gateway's authenticated OAuth transports
  (Codex / Claude subscriptions). Requires `hermes login` to have authenticated
  the provider. Does NOT read credential files — it invokes the gateway's own
  client (resolve_provider_client), which uses the gateway's creds.
"""
from __future__ import annotations
import json
import subprocess

# router tier -> (gateway provider id, model slug)
TIER_PROVIDER = {
    "codex":  ("codex", "gpt-5.4-mini"),
    "claude": ("anthropic", "claude-sonnet-4.6"),
}
_GATEWAY_PY = "/home/mai/.hermes/hermes-agent/venv/bin/python"
_BRIDGE = "/home/mai/projects/delegation-router/gateway_call.py"


def mock_provider(model: str, task_text: str, known_good: str) -> str:
    return f"```python\n{known_good.strip()}\n```"


def gateway_provider(tier: str, task_text: str, timeout: int = 180,
                     system: str | None = None, max_tokens: int = 2048) -> str:
    """Real escalation via the gateway OAuth transports. Raises with the
    gateway's own error (e.g. 'no Codex OAuth token') if not authenticated."""
    import os
    provider, model = TIER_PROVIDER[tier]
    env = dict(os.environ, GW_MAXTOK=str(max_tokens))
    if system is not None:
        env["GW_SYSTEM"] = system
    p = subprocess.run([_GATEWAY_PY, _BRIDGE, provider, model],
                       input=task_text, capture_output=True, text=True, timeout=timeout, env=env)
    lines = [ln for ln in p.stdout.strip().splitlines() if ln.startswith("{")]
    d = json.loads(lines[-1]) if lines else {"ok": False, "error": p.stderr[-300:]}
    if not d.get("ok"):
        raise RuntimeError(d.get("error", "gateway call failed"))
    return d["text"]
