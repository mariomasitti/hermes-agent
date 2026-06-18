"""Phase 1: the EYES — render a UI, capture an RGB screenshot + runtime evidence + DOM asserts.

Pixels captured locally and returned inline (base64) so nothing ever FETCHES a localhost URL
(that is what the gateway 'vision' tool rejects). Screenshot is JPEG => RGB (Qwen-VL 400s on RGBA).
"""
from __future__ import annotations
import base64
import statistics
from dataclasses import dataclass
from playwright.sync_api import sync_playwright

CHROME = "/home/mai/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome"


@dataclass
class Evidence:
    jpeg_b64: str
    console_errors: list
    http_status: int | None
    pixel_variance: float
    dom_checks: list      # [{name, passed, detail}]
    failed_requests: list
    viewport: dict


def _variance(jpeg: bytes) -> float:
    s = jpeg[::97][:2000]
    return statistics.pstdev(s) if len(s) > 1 else 0.0


def capture(url: str, viewport: dict, dom_assertions: list | None = None,
            wait_selector: str | None = None, timeout: int = 15000) -> Evidence:
    """dom_assertions: [{name, js, expect}] — js is evaluated in-page, compared == expect."""
    console_errors: list = []   # genuine JS errors only
    failed_requests: list = []  # non-favicon 4xx/5xx
    status = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
        pg = b.new_page(viewport=viewport)
        pg.on("console", lambda m: console_errors.append(m.text) if (m.type == "error" and not m.text.startswith("Failed to load resource")) else None)
        pg.on("pageerror", lambda e: console_errors.append("Uncaught: " + (str(e).splitlines() or ["JS error"])[0]))
        failed_raw: list = []  # (status, url, method) during load; bodies fetched after goto
        pg.on("response", lambda r: failed_raw.append((r.status, r.url, r.request.method)) if (r.status >= 400 and "favicon.ico" not in r.url) else None)
        resp = pg.goto(url, wait_until="networkidle", timeout=timeout)
        status["s"] = resp.status if resp else None
        # enrich failed requests with the actionable error BODY (a 422 validation message names
        # the offending field/pattern; status+url alone is too thin to reason a fix). Re-fetch is
        # safe for idempotent GETs only; best-effort.
        for _st, _u, _method in failed_raw:
            _detail = f"{_st} {_u}"
            if _method == "GET" and 400 <= _st < 500:
                try:
                    _body = pg.request.get(_u, timeout=4000).text()
                    if _body:
                        _detail += " — " + " ".join(_body.split())[:200]
                except Exception:
                    pass
            failed_requests.append(_detail)
        if wait_selector:
            try: pg.wait_for_selector(wait_selector, timeout=3000)
            except Exception: pass
        jpeg = pg.screenshot(type="jpeg", quality=90)
        # Disambiguate "X is not defined": the eyes run AFTER load, so if X resolves NOW it was
        # referenced before its (deferred/late) defining script ran — a load-order/timing race, not a
        # genuinely missing symbol. Models read the bare error as "define it"; this points at the cause.
        import re as _re
        for _ce in list(console_errors):
            _m = _re.search(r"(?:Uncaught:\s*)?(\w+) is not defined", _ce)
            if not _m:
                continue
            _sym = _m.group(1)
            try:
                _t = pg.evaluate("typeof " + _sym)
            except Exception:
                _t = "undefined"
            if _t and _t != "undefined":
                console_errors.append(
                    "NOTE: '" + _sym + "' IS defined after load (typeof " + _t + ") despite the error "
                    "above — it was referenced before its defining script executed (a load-order/timing "
                    "race), not a genuinely missing symbol.")
        dom_checks = []
        for a in (dom_assertions or []):
            try:
                val = pg.evaluate(a["js"])
                dom_checks.append({"name": a["name"], "passed": val == a["expect"],
                                   "detail": f"got {val!r} expect {a['expect']!r}"})
            except Exception as e:
                dom_checks.append({"name": a["name"], "passed": False, "detail": f"eval error: {e}"})
        b.close()
    return Evidence(base64.b64encode(jpeg).decode(), console_errors, status.get("s"),
                    _variance(jpeg), dom_checks, failed_requests, viewport)
