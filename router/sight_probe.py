"""Phase 1: LOCAL Qwen-VL render grade ($0) — the model's own eyes."""
from __future__ import annotations
import json
import re
from .probe import _client, QWEN_MODEL, _NO_THINK, _content, _JSON_RE
from .context import SelfGrade

_RP_RE = re.compile(r'"render_pass"\s*:\s*(true|false)', re.I)
_CONF_RE = re.compile(r'"confidence"\s*:\s*([01](?:\.\d+)?)')

# Shared grading prompt — local AND cloud rails ask the identical question so verdicts compare.
GRADE_PROMPT = ("You are verifying a rendered web UI. EXPECTATION: {exp}\n"
                "Look at the screenshot and decide if it MEETS the expectation. "
                'Respond ONLY JSON: {{"render_pass": true|false, "confidence": 0.0-1.0, "issues": ["..."]}}.')


def parse_vision_verdict(raw):
    """Robustly parse a vision JSON verdict -> (render_pass|None, confidence, issues).
    render_pass None => truly unparseable; caller should treat as INCONCLUSIVE (conf 0.0),
    not a silent FAIL (a false-FAIL would wrongly trigger escalation)."""
    m = _JSON_RE.search(raw or "")
    if m:
        try:
            d = json.loads(m.group(0))
            return bool(d.get("render_pass")), float(d.get("confidence", 0.5)), list(d.get("issues", []))[:4]
        except Exception:
            pass
    # JSON unparseable (e.g. a stray quote in the issues array) — recover the verdict by regex.
    rm = _RP_RE.search(raw or "")
    if rm:
        cm = _CONF_RE.search(raw or "")
        conf = min(float(cm.group(1)), 0.6) if cm else 0.5  # malformed payload => cap confidence
        return rm.group(1).lower() == "true", conf, ["(vision JSON malformed; verdict recovered by regex)"]
    return None, 0.0, ["(vision output unparseable)"]


def vision_grade(jpeg_b64: str, expectation: str, max_tokens: int = 300) -> SelfGrade:
    r = _client.chat.completions.create(
        model=QWEN_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": GRADE_PROMPT.format(exp=expectation)},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{jpeg_b64}"}}]}],
        extra_body=_NO_THINK, max_tokens=max_tokens, temperature=0.0)
    rp, conf, issues = parse_vision_verdict(_content(r))
    return SelfGrade(confidence=conf, uncertainties=issues,
                     checks_run=[{"name": "vision_render_pass", "passed": bool(rp)}])
