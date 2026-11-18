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
saved_globals = (csx.CUSTOM_DIR, csx.REGISTRY, csx.DATA_DIR)
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

    # ---- directory junctions for DICOM sources (Task 9) -------------------
    jn = work / "junctions"
    jn.mkdir()
    csx.CUSTOM_DIR = jn / "custom"
    csx.DATA_DIR = csx.CUSTOM_DIR / "data"
    csx.REGISTRY = csx.CUSTOM_DIR / "registry.json"
    src = jn / "src&dir"                 # cmd.exe reads & as a command separator
    src.mkdir()
    (src / "s0000.dcm").write_bytes(b"x")

    def register_orig(folder: Path) -> None:
        csx._write_registry([{"specimen": "orig", "source_kind": "dicom",
                              "source_folder": str(folder), "config_overrides": {}}])

    def run_step(label: str, fn) -> bool:
        try:
            fn()
            return True
        except Exception as exc:
            check(label, False, f"{type(exc).__name__}: {exc}")
            return False

    register_orig(src)
    link1 = csx.DATA_DIR / "copy_one" / "XY"
    if run_step("junction: link is created through a folder name containing &",
                lambda: csx.duplicate_specimen("orig", "copy_one")):
        check("junction: link resolves through a folder name containing &",
              link1.is_dir() and (link1 / "s0000.dcm").is_file(), str(link1))

    moved = jn / "src_moved"
    src.rename(moved)                    # the source moves: the link now dangles
    run_step("remove: a dangling junction can be removed",
             lambda: csx.remove_specimen("copy_one"))
    check("remove: the dangling link is gone", not os.path.lexists(link1))
    check("remove: the source folder itself is untouched",
          (moved / "s0000.dcm").is_file())

    src2 = jn / "src2"
    src2.mkdir()
    (src2 / "s0000.dcm").write_bytes(b"x")
    register_orig(src2)
    if run_step("re-register: a moved source does not block the same id",
                lambda: csx.duplicate_specimen("orig", "copy_one")):
        check("re-register: the id resolves to the new source",
              (link1 / "s0000.dcm").is_file())
    # ---- a link that cannot be removed must not keep the ID registered ----
    stuck_src = jn / 'stuck_src'
    stuck_src.mkdir()
    (stuck_src / 's0000.dcm').write_bytes(b'x')
    csx._write_registry([{'specimen': 'stuck', 'source_kind': 'dicom', 'source_folder': str(stuck_src), 'config_overrides': {}}])
    (csx.DATA_DIR / 'stuck').mkdir(parents=True, exist_ok=True)
    csx._mklink_junction(csx.DATA_DIR / 'stuck' / 'XY', stuck_src)
    real_rmdir_junction = csx._rmdir_junction
    def refused(link):
        raise OSError(448, 'The path cannot be traversed because it contains an untrusted mount point', str(link))
    csx._rmdir_junction = refused
    try:
        removed = csx.remove_specimen('stuck')
        still_registered = 'stuck' in csx.registered_specimens()
    except OSError as exc:
        removed, still_registered = 'raised', 'stuck' in csx.registered_specimens()
    finally:
        csx._rmdir_junction = real_rmdir_junction
        if os.path.lexists(csx.DATA_DIR / 'stuck' / 'XY'):
            real_rmdir_junction(csx.DATA_DIR / 'stuck' / 'XY')
    check('a link that cannot be removed still unregisters the ID', removed is True and still_registered is False, f'removed={removed} still={still_registered}')
    # ---- user state never falls back into the install folder (Task 15) ----
    from core import paths as app_paths
    blocker = work / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    saved_data = os.environ.get("CLEANCT_DATA")
    os.environ["CLEANCT_DATA"] = str(blocker / "state")
    try:
        fallback = app_paths.state_root()
    finally:
        if saved_data is None:
            os.environ.pop("CLEANCT_DATA", None)
        else:
            os.environ["CLEANCT_DATA"] = saved_data
    check("unwritable state folder falls back to the temp folder, not the app folder",
          fallback == Path(tempfile.gettempdir()) / "cleanCT"
          and fallback != app_paths.APP_ROOT, str(fallback))
finally:
    csx.CUSTOM_DIR, csx.REGISTRY, csx.DATA_DIR = saved_globals
    shutil.rmtree(work, ignore_errors=True)

ok = all(results)
print("ALL PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
