"""Viewer caches must follow the registered scan and must not grow without bound.

* A specimen ID that is registered to another folder gets a new source
  identity, so cached views of the old scan are not reused.
* Writing a cache file removes superseded files for the same specimen and
  kind, plus temp files left by killed writes.
* Removing or renaming a specimen drops its in-memory views.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = Path(os.environ.get("CLEANCT_TEST_TMP_DIR", tempfile.gettempdir()))
TMP_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from core import viewer_core as vc  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + label + (f" [{detail}]" if detail else ""))


class Source:
    """Stand-in for a DatasetSpec: only the fields the cache keys read."""

    def __init__(self, key, kind, source, source_path=None):
        self.key = key
        self.source_kind = kind
        self.source = source
        self.source_path = source_path


work = Path(tempfile.mkdtemp(prefix="cleanct_viewer_cache_", dir=TMP_ROOT))
saved_cache_dir = vc.CACHE_DIR
try:
    folder_a = work / "scan_a"
    folder_a.mkdir()
    (folder_a / "a.tif").write_bytes(b"A" * 10)
    folder_b = work / "scan_b"
    folder_b.mkdir()
    (folder_b / "b.tif").write_bytes(b"B" * 20)

    identity = getattr(vc, "source_identity", None)
    ds_a = Source("custom", "tiff", work, folder_a)
    ds_b = Source("custom", "tiff", work, folder_b)
    if identity is None:
        check("source identity follows the registered folder", False, "missing")
    else:
        check("source identity follows the registered folder",
              identity(ds_a, "x") != identity(ds_b, "x"))
        check("source identity is empty for built-in datasets",
              identity(Source("24um", "dicom", work), "x") == "")

    cache_dir = work / "cache"
    cache_dir.mkdir()
    vc.CACHE_DIR = cache_dir
    old_payload = cache_dir / "custom_x_aaaa_v19.npz"
    older_payload = cache_dir / "custom~x~bbbb_v21.npz"
    newest = cache_dir / "custom~x~cccc_v21.npz"
    other_specimen = cache_dir / "custom~x2~dddd_v21.npz"
    ortho = cache_dir / "custom~x~eeee_src_orig_v3.npz"
    stray = cache_dir / "custom~x~ffff_v21.tmp.npz"
    for path in (old_payload, older_payload, newest, other_specimen, ortho, stray):
        path.write_bytes(b"cache")
    two_hours_ago = time.time() - 7200
    os.utime(stray, (two_hours_ago, two_hours_ago))

    prune = getattr(vc, "_prune_disk_cache", None)
    if prune is None:
        check("pruning keeps only the newest payload for a specimen", False, "missing")
    else:
        sibling = cache_dir / "custom~x_y~bbbb_v21.npz"  # specimen "x_y" must not be pruned with "x"
        sibling.write_bytes(b"cache")
        prune("custom", "x", "payload", newest)
        check("pruning keeps only the newest payload for a specimen",
              newest.exists() and not old_payload.exists()
              and not older_payload.exists())
        check("pruning leaves other specimens and cache kinds alone",
              other_specimen.exists() and ortho.exists() and sibling.exists())
        check("pruning removes temp files older than an hour", not stray.exists())

    forget = getattr(vc, "forget_specimen", None)
    vc._XY_FILES["custom/x"] = []
    vc._XY_FILES["custom/x:tok"] = []
    vc._XY_FILES["custom/x2"] = []
    if forget is None:
        check("removing a specimen drops its in-memory views", False, "missing")
    else:
        forget("x")
        check("removing a specimen drops its in-memory views of that ID only",
              "custom/x" not in vc._XY_FILES and "custom/x:tok" not in vc._XY_FILES
              and "custom/x2" in vc._XY_FILES)
finally:
    vc.CACHE_DIR = saved_cache_dir
    vc._XY_FILES.pop("custom/x", None)
    vc._XY_FILES.pop("custom/x:tok", None)
    vc._XY_FILES.pop("custom/x2", None)
    shutil.rmtree(work, ignore_errors=True)

ok = all(results)
print("ALL PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
