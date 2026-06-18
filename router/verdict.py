"""Phase 3: verdict — run deterministic checks on BOTH attempts, pick a winner,
keep the loser. Passing tests is the objective signal; ties prefer cheaper local.
"""
from __future__ import annotations
from .verify import extract_code, run_checks


def judge(task_test: str, local_text: str, esc_text: str) -> dict:
    lc = run_checks(extract_code(local_text), task_test)
    ec = run_checks(extract_code(esc_text), task_test)
    lpass = all(c["passed"] for c in lc)
    epass = all(c["passed"] for c in ec)
    if lpass and not epass:
        winner = "local"
    elif epass and not lpass:
        winner = "escalated"
    elif lpass and epass:
        winner = "local"      # tie -> prefer the cheaper local result
    else:
        winner = "neither"
    return {"local_pass": lpass, "esc_pass": epass, "winner": winner,
            "local_checks": lc, "esc_checks": ec}
