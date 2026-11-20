"""Renaming a loaded specimen keeps its registry entry and its link folder in step."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from core.paths import ensure_engine_on_path  # noqa: E402

ensure_engine_on_path()
from core import custom_series as csx  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""),
          flush=True)
    if not ok:
        failures.append(name)


with tempfile.TemporaryDirectory() as tmp:
    # keep the registry and the link folder in this temporary folder
    csx.CUSTOM_DIR = Path(tmp) / "custom"
    csx.DATA_DIR = csx.CUSTOM_DIR / "data"
    csx.REGISTRY = csx.CUSTOM_DIR / "registry.json"
    csx._write_registry([{"specimen": "old_id", "source_kind": "tiff",
                          "source_path": str(Path(tmp)), "config_overrides": {}}])
    (csx.DATA_DIR / "old_id" / "XY").mkdir(parents=True)

    real_write = csx._write_registry

    def disk_full(entries):
        raise OSError(28, "No space left on device")

    csx._write_registry = disk_full
    try:
        csx.rename_specimen("old_id", "new_id")
        raised = False
    except OSError:
        raised = True
    finally:
        csx._write_registry = real_write
    check("a registry write error reaches the caller", raised)
    check("a failed registry write leaves the link folder under its old ID",
          (csx.DATA_DIR / "old_id" / "XY").is_dir() and not (csx.DATA_DIR / "new_id").exists(),
          str(sorted(p.name for p in csx.DATA_DIR.iterdir())))
    check("the registry still names the old ID",
          [e["specimen"] for e in csx._read_registry()] == ["old_id"])

    accepted = csx.rename_specimen("old_id", "new_id")
    check("a normal rename returns the new ID", accepted == "new_id", accepted)
    check("a normal rename moves the link folder with it",
          (csx.DATA_DIR / "new_id" / "XY").is_dir() and not (csx.DATA_DIR / "old_id").exists())
    check("a normal rename updates the registry",
          [e["specimen"] for e in csx._read_registry()] == ["new_id"])

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"), flush=True)
sys.exit(1 if failures else 0)
