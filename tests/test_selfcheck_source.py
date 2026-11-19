"""The self-check of a source checkout passes without CuPy; a packaged build still needs it.

CuPy is an optional GPU package. A source checkout has no runtime/ folder beside
its app/ folder; the packaged Windows and Linux builds always do.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import main  # noqa: E402  (importing the entry point starts nothing)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""),
          flush=True)
    if not ok:
        failures.append(name)


check("a source checkout does not require CuPy", not main._cupy_required())

with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "cleanCT" / "runtime").mkdir(parents=True)
    main.ROOT = Path(tmp) / "cleanCT" / "app"    # ROOT.parent holds runtime/ in a packaged build
    check("a packaged build requires CuPy", main._cupy_required())
    main.ROOT = ROOT

sys.modules["cupy"] = None      # importing cupy now raises ImportError, as on a PC without it
rc = main._selfcheck()
check("the self-check passes without CuPy in a source checkout", rc == 0, f"exit {rc}")

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"), flush=True)
sys.exit(1 if failures else 0)
