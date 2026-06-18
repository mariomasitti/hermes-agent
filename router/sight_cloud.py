"""Phase 2: CLOUD vision tie-breaker — Claude-vision via the gateway's OAuth transport.

Used ONLY when local Qwen-VL is uncertain (low confidence or inconclusive). Subscription-
capped (no metered keys). Shells into the gateway venv (the bridge imports the gateway agent
package and invokes the gateway's own authenticated client — no creds are read here).

Verified facts (smoke-tested 2026-05-31, NOT the predicted '1210' gotcha):
  - claude-sonnet-4.6 over OAuth ACCEPTS both max_tokens and temperature via this path.
  - OpenAI-style image_url data-URI (JPEG) is converted to an Anthropic base64 image block
    by the gateway's anthropic_adapter._image_source_from_openai_url.
"""
from __future__ import annotations
import base64
import json
import os
import subprocess
import tempfile
from .context import SelfGrade
from .sight_probe import parse_vision_verdict, GRADE_PROMPT

_GATEWAY_PY = "/home/mai/.hermes/hermes-agent/venv/bin/python"
_BRIDGE = "/home/mai/projects/delegation-router/gateway_vision_call.py"
CLOUD_PROVIDER, CLOUD_MODEL = "anthropic", "claude-sonnet-4.6"


def cloud_vision_grade(jpeg_b64: str, expectation: str, timeout: int = 120):
    """Adjudicate a render with cloud vision. Returns (SelfGrade|None, meta).
    Grade is None when the cloud call itself FAILED (unreachable/unauthed) — distinct from a
    render FAIL — so the caller can fall back to local rather than misread a fault as a verdict."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(base64.b64decode(jpeg_b64)); path = f.name
    try:
        env = dict(os.environ, GW_MAXTOK="400", GW_VTEMP="0.0",
                   GW_VSYS="You are a meticulous UI reviewer. Respond only with the requested JSON.")
        p = subprocess.run([_GATEWAY_PY, _BRIDGE, CLOUD_PROVIDER, CLOUD_MODEL, path],
                           input=GRADE_PROMPT.format(exp=expectation),
                           capture_output=True, text=True, timeout=timeout, env=env)
        lines = [ln for ln in p.stdout.strip().splitlines() if ln.startswith("{")]
        d = json.loads(lines[-1]) if lines else {"ok": False, "error": (p.stderr or "no output")[-300:]}
        if not d.get("ok"):
            return None, d  # cloud unreachable/unauthed — NOT a render verdict
        rp, conf, issues = parse_vision_verdict(d.get("text", ""))
        grade = SelfGrade(confidence=(conf if conf is not None else 0.5), uncertainties=issues,
                          checks_run=[{"name": "cloud_vision_render_pass", "passed": bool(rp)}])
        return grade, d
    except subprocess.TimeoutExpired:
        return None, {"ok": False, "error": f"cloud vision timed out after {timeout}s"}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
