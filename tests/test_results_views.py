"""The Results view shows the L/R box, and a raw scan's longitudinal view is the prediction.

1. A processed frame (axial) and a processed sagittal view keep only the L/R box on
   the After panel; the Before panel and the frame's other pixels are unchanged.
2. A raw scan (registered, not processed) gets its predicted longitudinal view from
   the Boundaries preview, on a worker thread, once the window has loaded it.
3. The raw scan's axial view draws the same L/R box on its After panel.
"""
from __future__ import annotations

import base64
import io
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

from PIL import Image  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import capture_screens as cs  # noqa: E402
from core import custom_series as csx  # noqa: E402
from core import viewer_core as vc  # noqa: E402

failures: list[str] = []
BG = (13, 15, 20)
LIGHT = (200, 200, 200)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def rgb(img, x: int, y: int) -> tuple[int, int, int]:
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def png_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# A synthetic Before | After frame: 10 px gap, each panel 200 wide, 100 high; all light grey
PW, H = 200, 100
frame = Image.new("RGB", (2 * PW + 10, H), LIGHT)
frame_url = png_url(frame)

# 14 slices of a wood/metal series, the same fixture as the plane scrub test
ROWS, COLS, NZ = 24, 40, 14
src = TEST_TMP / "views_src"          # its own folder: test_results_sync writes results_src
cs.write_wood_metal_series(src / "XY", n=NZ, rows=ROWS, cols=COLS, um=66.0)
name = "views_spec"
if name not in csx.registered_specimens():
    csx.register_series(src, name)

import main_window as mw  # noqa: E402

window = mw.MainWindow()
window.resize(1280, 720)
window.show()
window._select_sample("custom", name)
cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)

# 1. processed frame: the After panel keeps only the L/R box (x 25..75 %, y 25..75 %)
window.pref_viewer.setAxisBounds({"x": (0.25, 0.75), "y": (0.25, 0.75)})
window.payload = {"frames": [{"z": 3, "png": frame_url}], "unprocessed": False,
                  "report": {"n_slices": NZ}}
window._update_axial_frame(0)
ax = window.axial_viewer._pixmap.toImage()
# After panel = x 210..409; box = x 260..359 and y 25..74
check("processed axial: the After panel is cleared left of the L/R box",
      rgb(ax, 230, 50) == BG, str(rgb(ax, 230, 50)))
check("processed axial: the After panel is cleared right of the L/R box",
      rgb(ax, 380, 50) == BG, str(rgb(ax, 380, 50)))
check("processed axial: the After panel is kept inside the L/R box",
      rgb(ax, 300, 50) == LIGHT, str(rgb(ax, 300, 50)))
check("processed axial: the Before panel is untouched",
      rgb(ax, 100, 50) == LIGHT, str(rgb(ax, 100, 50)))

# 1c. the Results lines are the Boundaries lines (the Wood Top and the Cut on screen), even
# when the shown run was processed with other lines: the processed run used cut 9 and keep 0,
# the lines on screen are cut 11 and keep 2; the stale marker flags the difference
window.payload = {"frames": [], "unprocessed": False,
                  "report": {"n_slices": NZ, "cut_from": 9, "keep_from": 0}}
window.pref_cut, window.pref_keep = 11, 2
window._refresh_results_sync()
check("Results draw the Boundaries lines: keep 2 on the long view",
      window.long_viewer._keep == 2, f"keep={window.long_viewer._keep}")
check("Results draw the Boundaries lines: cut 11 on the long view",
      window.long_viewer._cut == 11, f"cut={window.long_viewer._cut}")
check("the stale marker shows: the processed run differs from the lines on screen",
      not window.lbl_results_stale.isHidden())

# 1d. the AFTER shows only the slices from Keep to Cut (the export keeps source[keep:cut]),
# on the on-screen lines: keep 2 and cut 11 of 14 slices, the stripped planes are not cut at
# the Keep line; the axial slice outside the kept slices is blank on the AFTER
window.pref_cut, window.pref_keep = 11, 2
window.long_view = "sagittal"
window._long_pos = None
window.long_viewer.setPixmap(QPixmap(), 1)
window.payload = {"frames": [{"z": 1, "png": frame_url}, {"z": 5, "png": frame_url}],
                  "unprocessed": False, "sagittal": frame_url,
                  "report": {"n_slices": NZ, "cut_from": 9, "keep_from": 0}}
window._update_long_view()
cs.pump(app, lambda: window.long_viewer._pixmap is not None and not window.long_viewer._pixmap.isNull(), 240)
kz = window.long_viewer._pixmap.toImage()
kpw = (kz.width() - 10) // 2
ax_mid = kpw + 10 + kpw // 2                      # the After panel, middle of the L/R box
row_keep = round(2 / (NZ - 1) * (kz.height() - 1))
row_cut = round(11 / (NZ - 1) * (kz.height() - 1))
def dark(img, x, y):
    c = img.pixelColor(x, y)
    return max(c.red(), c.green(), c.blue()) < 40
check("longitudinal AFTER is blank above the Keep line", dark(kz, ax_mid, row_keep - 25),
      str(rgb(kz, ax_mid, row_keep - 25)))
check("longitudinal AFTER is blank below the Cut line", dark(kz, ax_mid, row_cut + 25),
      str(rgb(kz, ax_mid, row_cut + 25)))
check("longitudinal AFTER is blank outside the Y box", dark(kz, kpw + 10 + 3, row_cut - 60),
      str(rgb(kz, kpw + 10 + 3, row_cut - 60)))
window._update_axial_frame(0)
az = window.axial_viewer._pixmap.toImage()
check("axial AFTER is blank for a slice above the Keep line (z 1 < keep 2)",
      rgb(az, 300, 50) == BG, str(rgb(az, 300, 50)))
window._update_axial_frame(1)
az = window.axial_viewer._pixmap.toImage()
check("axial AFTER keeps a slice between Keep and Cut (z 5)",
      rgb(az, 300, 50) == LIGHT, str(rgb(az, 300, 50)))

# 2. raw scan: the predicted longitudinal view arrives from the Boundaries preview
window.payload = {"unprocessed": True, "report": {"n_slices": NZ}, "frames": []}
window._results_long_key = None
window.pref_viewer.setAxisBounds({"x": (0.25, 0.75), "y": (0.25, 0.75)})
window.long_view = "sagittal"
window._refresh_results_long()
cs.pump(app, lambda: window.long_viewer._pixmap is not None and not window.long_viewer._pixmap.isNull(),
        120)
pm = window.long_viewer._pixmap
check("raw scan: the predicted longitudinal view is drawn",
      pm is not None and not pm.isNull() and pm.width() > 2 * 10, "no pixmap")
check("raw scan: the predicted view is the Before | After pair",
      pm is not None and pm.width() > pm.height() * 0.5, str(None if pm is None else pm.size()))

# 3. raw scan axial: the box is drawn on the After panel of the raw slice
window.payload = {"unprocessed": True, "report": {"n_slices": NZ, "win_lo": -950.0,
                                                  "win_hi": 350.0}, "frames": []}
window._update_axial_frame(NZ // 2)
ax_raw = window.axial_viewer._pixmap
check("raw scan axial: a slice is drawn", ax_raw is not None and not ax_raw.isNull())
if ax_raw is not None and not ax_raw.isNull():
    img_raw = ax_raw.toImage()
    pw_raw = (img_raw.width() - 10) // 2
    off = pw_raw + 10
    edge = rgb(img_raw, off + 2, img_raw.height() // 2)      # After panel, outside the box
    inside_px = rgb(img_raw, off + pw_raw // 2, img_raw.height() // 2)
    # the raw slice draws removed material as NaN (the dark colour of the Platform
    # removed panel), so outside the box it is dark, not the kept grey
    check("raw scan axial: the After panel is cleared outside the L/R box",
          max(edge) < 40, str(edge))
    check("raw scan axial: the box keeps the kept slice inside", inside_px != BG,
          str(inside_px))

window.close()
if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
