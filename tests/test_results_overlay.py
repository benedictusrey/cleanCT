"""Results overlay: the labels and the Before-panel lines are drawn by the app.

1. The Results viewer draws the Boundaries lines on the Before (left) panel only:
   Cut and Keep (dashed), the L and R lines (blue), and the Wood Top and Metal Top
   guides (dotted), with no handles and no line labels.  The axial view draws the
   L, R, Top and Bottom lines the same way.
2. Each panel carries its label in front of the image: "BEFORE (Original)" on the
   Before panel, "AFTER (Stripped)" in the accent on the After panel.
3. The longitudinal image's Before is the ORIGINAL plane (the metal base shows below
   the cut), the After is the stripped plane above the cut, and the image has no
   baked job lines (no pure-red cut dashes).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import viewer_core as vc  # noqa: E402
from widgets.viewer_2d import Viewer2D  # noqa: E402

failures: list[str] = []

CUT_RED = (255, 70, 60)
KEEP_GREEN = (55, 214, 122)
LATERAL_BLUE = (79, 140, 255)
TEXT_WHITE = (232, 235, 239)
TEAL = (63, 198, 182)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def near(c, rgb, tol: int = 60) -> bool:
    return abs(c.red() - rgb[0]) + abs(c.green() - rgb[1]) + abs(c.blue() - rgb[2]) <= tol


def count(img, x0: float, x1: float, y0: float, y1: float, rgb) -> int:
    hits = 0
    # only pixels inside the grab: an edge column past it reads as black with a Qt warning
    for yy in range(max(0, int(y0)), min(img.height() - 1, int(y1)) + 1):
        for xx in range(max(0, int(x0)), min(img.width() - 1, int(x1)) + 1):
            if near(img.pixelColor(xx, yy), rgb):
                hits += 1
    return hits


app = QApplication.instance() or QApplication(sys.argv)

# 1-2. sagittal Results: a Before | After pair, 400 px wide, grey, 200 slices
lay = Viewer2D()
lay.resize(420, 320)
pm = QPixmap(400, 200)
pm.fill(QColor(70, 70, 70))
lay.setPixmap(pm, 200)
lay.setSliceCount(200)
lay.setCut(150)              # the cut first: setKeep clamps to it
lay.setKeep(100)
lay.setPlane("sagittal")     # the lateral pair is Y for the sagittal plane
lay.setAxisBounds({"x": (0.2, 0.8), "y": (0.25, 0.75)})
lay.setAutoZ({"keep": 100, "wood_top": 60, "cut": 150, "metal_top": 150})
lay.setGuideEnabled(False)   # Results: no editable guides ...
lay.setResultsOverlay(True)  # ... the overlay alone
lay.show()
app.processEvents()
grab = lay.grab().toImage()
img_rect = lay._image_rect()
left, right = lay._panel_rects(img_rect)
y_cut = int(round(lay._slice_to_y(150, img_rect)))
y_keep = int(round(lay._slice_to_y(100, img_rect)))
x_l = int(round(left.left() + 0.25 * left.width()))
band = (left.left() + 30, left.right())  # the Before panel, clear of the handles on its edge

check("the Cut line is drawn on the Before panel",
      count(grab, band[0], band[1], y_cut - 1, y_cut + 1, CUT_RED) > 0)
check("the Cut line is not drawn on the After panel",
      count(grab, right.left(), right.right(), y_cut - 1, y_cut + 1, CUT_RED) == 0)
check("the Keep line is drawn on the Before panel only",
      count(grab, band[0], band[1], y_keep - 1, y_keep + 1, KEEP_GREEN) > 0
      and count(grab, right.left(), right.right(), y_keep - 1, y_keep + 1, KEEP_GREEN) == 0)
check("the L line is drawn on the Before panel only",
      count(grab, x_l - 1, x_l + 1, left.top() + 4, left.bottom() - 4, LATERAL_BLUE) > 0
      and count(grab, right.left(), right.right(), left.top(), left.bottom(), LATERAL_BLUE) == 0)
check("the label Before reads BEFORE (Original) in the primary text",
      count(grab, left.left() + 10, left.left() + 170, left.top() + 10, left.top() + 32,
            TEXT_WHITE) > 0)
check("the label After reads AFTER (Stripped) in the accent on the After panel",
      count(grab, right.left() + 10, right.left() + 170, right.top() + 10, right.top() + 32,
            TEAL) > 0
      and count(grab, left.left() + 10, left.left() + 170, left.top() + 10, left.top() + 32,
                TEAL) == 0)

# 1b. axial Results: the L and R lines and the Top and Bottom lines on the Before panel
ax = Viewer2D()
ax.resize(420, 320)
ax.setPixmap(pm, 200)
ax.setSliceCount(200)
ax.setPlane("axial")
ax.setAxisBounds({"x": (0.25, 0.75), "y": (0.3, 0.7)})
ax.setGuideEnabled(False)
ax.setResultsOverlay(True)
ax.show()
app.processEvents()
a_img = ax.grab().toImage()
a_rect = ax._image_rect()
a_left, a_right = ax._panel_rects(a_rect)
y_top = int(round(a_left.top() + 0.3 * a_left.height()))
check("axial: the Top line is drawn on the Before panel only",
      count(a_img, a_left.left() + 30, a_left.right(), y_top - 1, y_top + 1, KEEP_GREEN) > 0
      and count(a_img, a_right.left(), a_right.right(), y_top - 1, y_top + 1, KEEP_GREEN) == 0)

# 3. the longitudinal view (the preview at the slider position): the Before is the
# ORIGINAL plane, the metal base shows below the cut, the After is blank below the cut,
# and the image carries no baked job lines
n, ny, cut = 20, 30, 12
orig = np.full((n, ny), -800.0, np.float32)
orig[cut:] = 3000.0                          # the metal base below the cut
img = vc._ortho_panel(orig, cut, 0, 0, None, -950.0, 350.0, 2000.0, 0, 300,
                      cmap="grayscale", cols=None, annotate=False)
arr = np.asarray(img.convert("RGB")).astype(int)
h = arr.shape[0]
pw = (arr.shape[1] - 10) // 2
row = h - 6                                  # below the cut
before_sum = int(arr[row, pw // 2].sum())
after_sum = int(arr[row, pw + 10 + pw // 2].sum())
check("the Before of the longitudinal view shows the metal base below the cut",
      before_sum > after_sum + 200, f"before={before_sum} after={after_sum}")
reds = int(((arr[..., 0] > 200) & (arr[..., 1] < 120) & (arr[..., 2] < 120)).sum())
check("the longitudinal image has no baked cut line", reds == 0, f"{reds} red px")

if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
