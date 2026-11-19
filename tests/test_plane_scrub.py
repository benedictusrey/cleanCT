"""The Boundaries preview scrubs the plane's own axis, and the AFTER panel shows the L/R box.

1. The sagittal slider scrubs X (the sagittal plane sits at an X column), the
   coronal slider scrubs Y (the coronal plane sits at a Y row), the axial slider
   scrubs Z.  The slider range follows the axis it scrubs.
2. ``viewer_core._ortho_plane`` returns the true sagittal column or coronal row
   of the source series, so a scrub really changes the picture.
3. The KEPT (AFTER) panel is masked to the L/R box as well as to the Keep/Cut
   range: material outside L and R is not shown.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if (not os.environ.get("CLEANCT_ENGINE") or not os.environ.get("CLEANCT_DATA")
        or not os.environ.get("CLEANCT_TEST_TMP_DIR")):
    raise SystemExit("Set isolated CLEANCT_ENGINE, CLEANCT_DATA, and "
                     "CLEANCT_TEST_TMP_DIR paths first")
TEST_TMP = Path(os.environ["CLEANCT_TEST_TMP_DIR"])
TEST_TMP.mkdir(parents=True, exist_ok=True)
APP = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "src"))

import numpy as np  # noqa: E402
import pydicom  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import capture_screens as cs  # noqa: E402
from core import custom_series as csx  # noqa: E402
from core import viewer_core as vc  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# a synthetic series: 14 slices, 24 rows (Y) by 40 columns (X)
ROWS, COLS, NZ = 24, 40, 14
src = TEST_TMP / "plane_src"
cs.write_wood_metal_series(src / "XY", n=NZ, rows=ROWS, cols=COLS, um=66.0)
name = "plane_spec"
if name not in csx.registered_specimens():
    csx.register_series(src, name)

# 1. sagittal = column x of every slice; coronal = row y of every slice
ds = vc._get_ds("custom", name)
files = sorted((src / "XY").glob("*.dcm"))


def hu(f):
    d = pydicom.dcmread(str(f))
    return d.pixel_array.astype(np.float32) * float(d.RescaleSlope) + float(d.RescaleIntercept)


direct = np.stack([hu(f) for f in files])          # Hounsfield units, as the viewer reads them
sag5 = vc._ortho_plane(ds, name, "sagittal", 5)
sag20 = vc._ortho_plane(ds, name, "sagittal", 20)
cor7 = vc._ortho_plane(ds, name, "coronal", 7)
check("the sagittal plane at x=5 is column 5 of every slice",
      sag5.shape == (NZ, ROWS) and np.allclose(sag5, direct[:, :, 5]),
      str(sag5.shape))
check("the coronal plane at y=7 is row 7 of every slice",
      cor7.shape == (NZ, COLS) and np.allclose(cor7, direct[:, 7, :]),
      str(cor7.shape))
check("a scrub changes the sagittal picture", not np.allclose(sag5, sag20))

# 2. the slider range follows the axis it scrubs (sagittal = X, coronal = Y, axial = Z)
import main_window as mw  # noqa: E402

window = mw.MainWindow()
window.resize(1280, 720)
window.show()
window._select_sample("custom", name)
cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)
for _ in range(10):
    app.processEvents()
def wait_for_plane(plane: str) -> None:
    """Wait for the preview of ``plane`` (the previous plane's preview is still there)."""
    cs.pump(app, lambda: (window._last_pref_preview or {}).get("plane") == plane, 120)
    for _ in range(10):
        app.processEvents()


window._set_pref_plane("sagittal")
wait_for_plane("sagittal")
check("sagittal slider scrubs X (range = columns)", window.pref_slider.maximum() == COLS - 1,
      f"max={window.pref_slider.maximum()}")
window._set_pref_plane("coronal")
wait_for_plane("coronal")
check("coronal slider scrubs Y (range = rows)", window.pref_slider.maximum() == ROWS - 1,
      f"max={window.pref_slider.maximum()}")
window._set_pref_plane("axial")
wait_for_plane("axial")
check("axial slider scrubs Z (range = slices)", window.pref_slider.maximum() == NZ - 1,
      f"max={window.pref_slider.maximum()}")
window.close()

# 3. the KEPT panel is masked to the L/R columns: a pure check of the panel renderer
line = np.ones((40, 60), np.float32)                 # rows = z, columns = lateral
canvas = vc._ortho_panel(line, cut=30, margin=0, keep_from=5, roi_z=None,
                         lo=0.0, hi=1.0, metal_lo=2.0, z_line=10, width=200,
                         cmap="grayscale", cols=(15, 45))
arr = np.asarray(canvas.convert("RGB")).astype(int)
pw = int(60 * 200 / 40)
kx = pw + 10                                         # the KEPT panel starts here
y = 15 * (200 / 40)                                  # a row inside the Keep..Cut range
outside = arr[int(y), kx + int(10 * 5)].sum()        # lateral column 10: left of L
inside = arr[int(y), kx + int(30 * 5)].sum()         # lateral column 30: inside L..R
check("the KEPT panel hides material outside L", outside < 90, f"sum={outside}")
check("the KEPT panel shows material inside L and R", inside > 200, f"sum={inside}")

# a full-scale value is drawn with the top colour, not the darkest (it used to be the darkest)
from core.viewer_core import _apply_cmap  # noqa: E402

top = _apply_cmap(np.array([1.0], np.float32), "grayscale")[0]
check("full-scale values take the top colour", float(top.sum()) > 2.7,
      f"rgb={np.round(top * 255)}")

if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
