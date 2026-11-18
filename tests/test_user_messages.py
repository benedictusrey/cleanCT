"""Pipeline errors reach the user in plain words, with a next step.

The engine's messages are written for developers ("no clean seed slice found
... inspect the scan"). The known failures are translated; anything else passes
through unchanged, so no error is ever hidden.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from core import user_messages as um  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


seed = um.pipeline_error(
    "no clean seed slice found (all slices fogged or border-locked); inspect the scan")
check("a seed failure names the wood and says what to check",
      "wood" in seed and "metal base" in seed and "edges" in seed, seed[:120])
check("a seed failure drops the engine's internal terms",
      not any(term in seed for term in ("seed", "fogged", "border-locked")))
check("unknown errors pass through unchanged", um.pipeline_error("disk full") == "disk full")
check("the message is one short paragraph of plain sentences",
      seed.count(".") >= 2 and len(seed) < 320, str(len(seed)))

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
sys.exit(1 if failures else 0)
