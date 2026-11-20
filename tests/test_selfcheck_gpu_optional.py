"""The self-check passes on a PC without a GPU: CuPy is optional, and the gpu line reports it."""
from __future__ import annotations

import os
import sys
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


sys.modules["cupy"] = None      # importing cupy now fails, as on a PC without a CUDA stack
rc = main._selfcheck()
check("the self-check passes without CuPy", rc == 0, f"exit {rc}")

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"), flush=True)
sys.exit(1 if failures else 0)
