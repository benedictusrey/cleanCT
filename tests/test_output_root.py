"""Where the pipeline writes results when no output folder is set.

A checkout on a PC without the build machine's output folder must keep its
results inside the checkout, not on a drive that may not exist there.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from core.paths import ensure_engine_on_path  # noqa: E402

ensure_engine_on_path()
import tomograph as tg  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""),
          flush=True)
    if not ok:
        failures.append(name)


ds = tg.DATASETS["66um"]
saved_env = os.environ.pop("CLEANCT_OUTPUT_ROOT", None)
saved_root = tg.OUT_ROOT
try:
    with tempfile.TemporaryDirectory() as tmp:
        tg.OUT_ROOT = Path(tmp) / "absent" / "output"       # no such folder on this PC
        got = tg.output_root(ds)
        engine_home = Path(tg.__file__).resolve().parents[1]     # the checkout (or the gate's copy)
        check("without the build folder, results go inside the checkout",
              got.is_relative_to(engine_home), str(got))

        tg.OUT_ROOT = Path(tmp)                              # the folder exists here
        check("an existing build folder keeps its results",
              tg.output_root(ds) == Path(tmp) / ds.out_sub, str(tg.output_root(ds)))

        os.environ["CLEANCT_OUTPUT_ROOT"] = str(Path(tmp) / "chosen")
        check("CLEANCT_OUTPUT_ROOT overrides both",
              tg.output_root(ds) == Path(tmp) / "chosen" / ds.out_sub, str(tg.output_root(ds)))
finally:
    tg.OUT_ROOT = saved_root
    os.environ.pop("CLEANCT_OUTPUT_ROOT", None)
    if saved_env is not None:
        os.environ["CLEANCT_OUTPUT_ROOT"] = saved_env

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"), flush=True)
sys.exit(1 if failures else 0)
