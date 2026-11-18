from __future__ import annotations

import io
import os
import sys
from pathlib import Path

if not os.environ.get("CLEANCT_TEST_TMP_DIR"):
    raise SystemExit("Set CLEANCT_TEST_TMP_DIR first")
TEST_TMP = Path(os.environ["CLEANCT_TEST_TMP_DIR"])
TEST_TMP.mkdir(parents=True, exist_ok=True)
APP = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(APP))

from PIL import Image
from core import checkpoint_file as cp

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def main():
    out = io.BytesIO()
    Image.new("RGB", (24, 16), (30, 60, 90)).save(out, format="PNG")
    import base64
    png = "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    state = {
        "dataset": "custom", "sample": "synthetic",
        "cut": 20, "keep": 4, "margin": 2, "n_slices": 30,
        "plane": "axial", "z": 12, "cmap": "thermal",
        "lo": -400.0, "hi": 1200.0,
        "bounds": {"x": [0.1, 0.9], "y": [0.2, 0.8]},
        "guide_mode": "4lines", "guides": True, "air_crop": False,
        "pref_dirty": True, "long_view": "coronal", "axial_idx": 10, "tab": "prefs",
    }
    path = TEST_TMP / "checkpoint-roundtrip.ctcheckpoint.json"
    try:
        document = cp.new_document(state, png, "C:/scans/synthetic.tif", "tiff")
        cp.save_checkpoint(path, document)
        restored = cp.load_checkpoint(path)
        check("checkpoint round-trip preserves state and preview",
              restored["state"]["plane"] == "axial"
              and restored["state"]["cut"] == 20
              and restored["state"]["bounds"]["y"] == [0.2, 0.8]
              and restored["preview_png"] == png)
        cp.save_checkpoint(path, cp.new_document(
            {**state, "sample": "replacement"}, png, "", ""))
        check("checkpoint replace is atomic and leaves no temporary files",
              cp.load_checkpoint(path)["state"]["sample"] == "replacement"
              and not list(TEST_TMP.glob(".checkpoint-roundtrip.ctcheckpoint.json.*.tmp")))

        invalid = dict(document)
        invalid["version"] = cp.VERSION + 1
        try:
            cp.validate_checkpoint(invalid)
            ok = False
        except cp.CheckpointError:
            ok = True
        check("unsupported checkpoint version is rejected", ok)

        invalid = dict(document)
        invalid["state"] = {**state, "keep": 21}
        try:
            cp.validate_checkpoint(invalid)
            ok = False
        except cp.CheckpointError:
            ok = True
        check("crossing keep/cut lines are rejected", ok)

        invalid = dict(document)
        invalid["preview_png"] = "data:image/png;base64,AAAA"
        try:
            cp.validate_checkpoint(invalid)
            ok = False
        except cp.CheckpointError:
            ok = True
        check("corrupt preview image is rejected", ok)

        invalid = dict(document)
        invalid["state"] = {**state, "lo": float("nan")}
        try:
            cp.validate_checkpoint(invalid)
            ok = False
        except cp.CheckpointError:
            ok = True
        check("non-finite thresholds are rejected", ok)

        empty = TEST_TMP / "empty.ctcheckpoint.json"
        empty.write_bytes(b"")
        try:
            cp.load_checkpoint(empty)
            ok = False
        except cp.CheckpointError:
            ok = True
        check("empty checkpoint file is rejected", ok)
    finally:
        for target in (path, TEST_TMP / "empty.ctcheckpoint.json"):
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
