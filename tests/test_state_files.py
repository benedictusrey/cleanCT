"""State-file safety for per-user data.

Corrupt settings.json or registry.json must be kept on disk (renamed to
``<name>.corrupt-<timestamp>``), never silently replaced by the next save.
Registry entries without a specimen id are skipped instead of raising.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from core import bundle_export as be  # noqa: E402
from core import custom_series as csx  # noqa: E402

work_root = Path(os.environ.get("CLEANCT_TEST_TMP_DIR", tempfile.gettempdir()))
work_root.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix="cleanct_state_", dir=work_root))
results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + label + (f" [{detail}]" if detail else ""))


TRUNCATED = '{"save_root": "D:/exports", '     # what a crash mid-write leaves
saved_globals = (csx.CUSTOM_DIR, csx.REGISTRY)
try:
    # ---- settings.json ----------------------------------------------------
    settings_root = work / "settings"
    settings_root.mkdir()
    (settings_root / "settings.json").write_text(TRUNCATED, encoding="utf-8")
    loaded = be.load_settings(settings_root)
    be.save_settings(settings_root, {"x": 1})
    kept = sorted(settings_root.glob("settings.json.corrupt-*"))
    check("settings: corrupt file is kept, not overwritten",
          len(kept) == 1 and kept[0].read_text(encoding="utf-8") == TRUNCATED,
          f"kept={[k.name for k in kept]}")
    check("settings: corrupt file loads as empty", loaded == {}, repr(loaded))
    check("settings: next save is readable",
          json.loads((settings_root / "settings.json").read_text(encoding="utf-8"))
          == {"x": 1})

    (settings_root / "settings.json").write_text("[1, 2]", encoding="utf-8")
    check("settings: JSON that is not an object loads as empty",
          be.load_settings(settings_root) == {})

    # ---- registry.json ----------------------------------------------------
    reg_dir = work / "registry"
    reg_dir.mkdir()
    csx.CUSTOM_DIR = reg_dir
    csx.REGISTRY = reg_dir / "registry.json"

    csx.REGISTRY.write_text(TRUNCATED, encoding="utf-8")
    csx.registered_specimens()                       # the read that sees the damage
    csx._write_registry(csx._read_registry() + [{"specimen": "new_one"}])
    kept = sorted(reg_dir.glob("registry.json.corrupt-*"))
    check("registry: corrupt file is kept, not overwritten",
          len(kept) == 1 and kept[0].read_text(encoding="utf-8") == TRUNCATED,
          f"kept={[k.name for k in kept]}")
    check("registry: next write holds only the new entry",
          set(csx.registered_specimens()) == {"new_one"},
          str(sorted(csx.registered_specimens())))

    csx.REGISTRY.write_text('{"specimen": "x"}', encoding="utf-8")
    check("registry: JSON that is not a list is quarantined",
          csx.registered_specimens() == {}
          and len(sorted(reg_dir.glob("registry.json.corrupt-*"))) == 2)

    csx.REGISTRY.write_text(json.dumps(
        [{"specimen": "ok_one", "source": "a"}, {"name": "no_id"}, "junk", 7]),
        encoding="utf-8")
    try:
        names = set(csx.registered_specimens())
        skipped_ok = names == {"ok_one"}
        detail = repr(sorted(names))
    except KeyError as exc:
        skipped_ok, detail = False, f"KeyError {exc}"
    check("registry: entries without a specimen id are skipped", skipped_ok, detail)
finally:
    csx.CUSTOM_DIR, csx.REGISTRY = saved_globals
    shutil.rmtree(work, ignore_errors=True)

ok = all(results)
print("ALL PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
