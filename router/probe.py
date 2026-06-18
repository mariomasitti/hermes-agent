"""Phase 2: local-first probe + structured self-grade against the Qwen endpoint.

Standalone — does NOT touch the live gateway. Talks to the OpenAI-compatible Qwen
server directly. Qwen3.6 is a reasoning model; we disable thinking for clean,
parseable output (mirrors the gateway's auxiliary-call config).
"""
from __future__ import annotations
import json
import os
import re
from openai import OpenAI
from .context import SelfGrade

QWEN_BASE_URL = os.environ.get("QWEN_BASE_URL", "http://172.19.10.50:7700/v1")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "Qwen3.6-35B-A3B-UD-Q5_K_XL.gguf")
_NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}
_client = OpenAI(base_url=QWEN_BASE_URL, api_key=os.environ.get("QWEN_API_KEY", "not-needed"))


def _content(r) -> str:
    m = r.choices[0].message
    return (m.content or getattr(m, "reasoning_content", "") or "")


def attempt(task_text: str, max_tokens: int = 1536):
    r = _client.chat.completions.create(
        model=QWEN_MODEL,
        messages=[
            {"role": "system", "content": "You are a precise coding assistant. Return only the requested Python function in a single ```python code block."},
            {"role": "user", "content": task_text},
        ],
        temperature=0.2, max_tokens=max_tokens, extra_body=_NO_THINK)
    txt = _content(r)
    u = getattr(r, "usage", None)
    usage = {"in": getattr(u, "prompt_tokens", 0), "out": getattr(u, "completion_tokens", 0)} if u else {}
    return txt, usage


_JSON_RE = re.compile(r"\{[^{}]*\}", re.S)


def self_grade(task_text: str, attempt_text: str, check_results: list[dict], max_tokens: int = 300) -> SelfGrade:
    summary = "; ".join(f"{c['name']}={'pass' if c['passed'] else 'FAIL'}" for c in check_results) or "none"
    prompt = (
        f"TASK:\n{task_text}\n\nYOUR ATTEMPT:\n{attempt_text}\n\n"
        f"AUTOMATED CHECKS: {summary}\n\n"
        'Rate your own attempt. Respond with ONLY JSON: '
        '{"confidence": <0.0-1.0>, "uncertainties": ["..."]}. '
        "Be honest; if checks failed, confidence must be low.")
    r = _client.chat.completions.create(
        model=QWEN_MODEL, messages=[{"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=max_tokens, extra_body=_NO_THINK)
    raw = _content(r)
    conf, unc = 0.5, []
    for m in _JSON_RE.finditer(raw):
        try:
            d = json.loads(m.group(0))
            if "confidence" in d:
                conf = float(d.get("confidence", 0.5))
                unc = list(d.get("uncertainties", []))[:4]
                break
        except Exception:
            continue
    return SelfGrade(confidence=conf, uncertainties=unc, checks_run=check_results)
