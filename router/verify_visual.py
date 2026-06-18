"""Two-rail visual verdict (+ optional cloud tie-breaker).
RAIL 1 (deterministic: console/http/non-blank/DOM-selectors) short-circuits to FAIL-with-reason.
RAIL 2 (Qwen-VL perceptual) adjudicates 'looks right' — only weighted when RAIL 1 passes.
TIE-BREAK (Phase 2, opt-in): Claude-vision over OAuth adjudicates the perceptual question.
  Modes (tie_break=):
    False      off ($0).
    True        fire only when local Qwen-VL is UNCERTAIN (confidence < threshold, incl. the
                conf-0.0 inconclusive case). NOTE: measured 2026-05-31 that local confidence is
                poorly calibrated (high even when wrong) — so this rarely fires. Cheap secondary.
    "always"   fire on every perceptual verdict that passes RAIL 1 — the right policy for
                perceptual-CRITICAL task types, since local can be confidently wrong.
  Cost-honest either way: never fires when the deterministic rail already settled it (FAIL).
  Subscription-capped, no metered keys.
"""
from __future__ import annotations
from . import sight, sight_probe, sight_cloud


def verify(url, viewport, expectation, dom_assertions=None, wait_selector=None,
           run_vision=True, tie_break=False, tie_break_threshold=0.7):
    ev = sight.capture(url, viewport, dom_assertions, wait_selector)
    checks = [{"name": "console_errors", "passed": len(ev.console_errors) == 0,
               "detail": f"{len(ev.console_errors)} errors"}]
    if ev.http_status is not None:
        checks.append({"name": "http_2xx", "passed": 200 <= ev.http_status < 300,
                       "detail": f"status {ev.http_status}"})
    checks.append({"name": "resource_loads", "passed": len(ev.failed_requests) == 0,
                   "detail": f"{len(ev.failed_requests)} failed: {ev.failed_requests[:2]}"})
    checks.append({"name": "non_blank", "passed": ev.pixel_variance > 2.0,
                   "detail": f"variance {ev.pixel_variance:.1f}"})
    checks.extend(ev.dom_checks)
    rail1 = all(c["passed"] for c in checks)
    out = {"rail1_pass": rail1, "checks": checks, "evidence": ev, "vision": None,
           "cloud_vision": None, "tie_break_fired": False,
           "render_pass": rail1, "method": "visual-deterministic"}
    if run_vision:
        sg = sight_probe.vision_grade(ev.jpeg_b64, expectation)
        vp = sg.checks_run[0]["passed"]
        out["vision"] = {"render_pass": vp, "confidence": sg.confidence, "issues": sg.uncertainties}
        out["method"] = "visual"
        out["render_pass"] = rail1 and vp
        # Tie-breaker: only when the deterministic rail PASSED (don't pay cloud on an objective FAIL).
        # "always" => every perceptual verdict; True => only when local is uncertain.
        should_tie = rail1 and ((tie_break == "always") or (tie_break and sg.confidence < tie_break_threshold))
        if should_tie:
            cg, meta = sight_cloud.cloud_vision_grade(ev.jpeg_b64, expectation)
            if cg is not None:
                cp = cg.checks_run[0]["passed"]
                out["cloud_vision"] = {"render_pass": cp, "confidence": cg.confidence,
                                       "issues": cg.uncertainties, "model": meta.get("final_model")}
                out["tie_break_fired"] = True
                out["method"] = "visual-tiebreak"
                # Measured 2026-05-31: cloud is NOT an oracle (it caught local's tiny-text error
                # but miscounted bars, breaking a correct answer). So treat the two eyes as
                # independent opinions: clean PASS needs BOTH; disagreement => flag for a human
                # rather than blindly trust either (precise visual reasoning is unreliable in both).
                out["agreement"] = (vp == cp)
                out["needs_human"] = not out["agreement"]
                out["render_pass"] = rail1 and vp and cp
            else:
                out["cloud_error"] = meta.get("error")
    if not rail1:
        out["reason"] = "RAIL1 FAIL: " + ", ".join(c["name"] for c in checks if not c["passed"])
    elif out["tie_break_fired"]:
        cp, lp = out["cloud_vision"]["render_pass"], out["vision"]["render_pass"]
        if not out["agreement"]:
            out["reason"] = (f"DISAGREEMENT: local Qwen-VL={lp} ({out['vision']['confidence']:.2f}) vs "
                             f"cloud={cp} ({out['cloud_vision']['confidence']:.2f}) -> FLAG FOR HUMAN "
                             f"(precise visual reasoning unreliable in both)")
        elif cp:
            out["reason"] = "PASS (both eyes agree: local + cloud)"
        else:
            out["reason"] = f"FAIL (both eyes agree): {out['cloud_vision']['issues'][:1]}"
    elif out["vision"] and not out["vision"]["render_pass"]:
        out["reason"] = f"RAIL1 ok but vision FAIL: {out['vision']['issues']}"
    else:
        out["reason"] = "PASS (deterministic + vision)"
    return out
