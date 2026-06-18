"""Phase 2: deterministic verifier — extract code, run tests in a subprocess."""
from __future__ import annotations
import os
import re
import subprocess
import tempfile

_FENCE = re.compile(r"```(?:python|py)?\s*\n?(.*?)```", re.S | re.I)
_OPEN_FENCE = re.compile(r"```(?:python|py)?\s*\n?(.*)$", re.S | re.I)
_CODE_START = re.compile(r"^(?:from |import |def |class )", re.M)


def extract_code(text: str) -> str:
    """Tolerant of prose around code, truncated (unclosed) fences, and no fence."""
    text = text or ""
    blocks = _FENCE.findall(text)
    if blocks:
        for b in blocks:                       # prefer a block that defines something
            if re.search(r"\bdef\b|\bclass\b", b):
                return b.strip()
        return max(blocks, key=len).strip()
    m = _OPEN_FENCE.search(text)               # unclosed fence (token truncation)
    if m and re.search(r"\bdef\b", m.group(1)):
        return m.group(1).strip()
    mi = _CODE_START.search(text)              # no fence: start at first def/import
    if mi:
        return text[mi.start():].strip()
    return text.strip()


def run_checks(code: str, test_code: str, timeout: int = 15) -> list[dict]:
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "solution.py"), "w").write(code)
        open(os.path.join(d, "runner.py"), "w").write(
            "import solution\n" + test_code + "\nprint('ALL_TESTS_PASSED')\n")
        try:
            p = subprocess.run(["python3", "runner.py"], cwd=d, capture_output=True,
                               text=True, timeout=timeout)
            passed = "ALL_TESTS_PASSED" in p.stdout and p.returncode == 0
            tail = (p.stdout + p.stderr).strip().splitlines()
            return [{"name": "tests", "passed": passed, "detail": (tail[-1] if tail else "")[:200]}]
        except subprocess.TimeoutExpired:
            return [{"name": "tests", "passed": False, "detail": "timeout"}]
        except Exception as e:
            return [{"name": "tests", "passed": False, "detail": str(e)[:200]}]
