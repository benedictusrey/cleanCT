"""Auto z-guides and job labels on the sagittal and coronal views.

The metal top is the detector anchor (the physical base top).  The halo onset
is the cut the pipeline makes.  Each must sit at its own slice and carry its
own name, so a "Metal Top" label never lands on the cut slice.

Placement: the guide labels (Wood Top, Metal Top) sit on the Before (left)
panel; the job labels (Keep, Cut) sit on the After (right) panel.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from widgets.viewer_2d import Viewer2D  # noqa: E402

failures: list[str] = []

GREEN = (55, 214, 122)      # wood top guide and Keep label
ORANGE = (255, 159, 67)     # metal top guide
RED = (255, 70, 60)         # Cut label and Cut line


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def guides_of(viewer: Viewer2D) -> dict:
    return {kind: (sl, label) for kind, sl, label in viewer._auto_z_guides()}


def ink(grab, x0: float, x1: float, y: int, rgb) -> int:
    """Pixels of colour ``rgb`` in columns x0..x1, in rows above and below the
    line (not on it: the line itself is the same colour)."""
    hits = 0
    for yy in [*range(y - 8, y - 1), *range(y + 2, y + 9)]:
        for xx in range(int(x0), int(x1)):
            c = grab.pixelColor(xx, yy)
            if abs(c.red() - rgb[0]) + abs(c.green() - rgb[1]) + abs(c.blue() - rgb[2]) <= 90:
                hits += 1
    return hits


app = QApplication.instance() or QApplication(sys.argv)
viewer = Viewer2D()

# 2_666_5 payload: the Keep is the wood top (88), the air top (83) is not drawn,
# the Cut is the metal top (521); the halo onset (353 on 2-5) is never a line
viewer.setAutoZ({"keep": 83, "cut": 521, "wood_top": 88, "metal_top": 521,
                 "wood_bottom": 518, "top_ok": True})
g = guides_of(viewer)
check("keep guide sits on the wood top (88)",
      g.get("wood") == (88, "Wood Top 88"), str(g.get("wood")))
check("metal top guide sits on the physical metal top (521)",
      g.get("metal") == (521, "Metal Top 521"), str(g.get("metal")))
check("no air top line: the Keep rides the wood top", "air" not in g, str(g))
check("no halo onset line", "halo" not in g, str(g))

# older payload without wood_top: the Keep falls back to the air top
viewer.setAutoZ({"keep": 19, "cut": 353})
g_old = guides_of(viewer)
check("no wood_top: the Keep guide is the air top", g_old.get("air") == (19, "Air Top 19"),
      str(g_old))
check("no metal_top: no metal guide", "metal" not in g_old, str(g_old))

# air top deferred (foggy edge): wood top evidence shows instead
viewer.setAutoZ({"keep": None, "cut": 353, "wood_top": 1, "metal_top": 405})
g_def = guides_of(viewer)
check("air deferred: wood top guide drawn", g_def.get("wood") == (1, "Wood Top 1"),
      str(g_def.get("wood")))
check("air deferred: no air guide", "air" not in g_def, str(g_def))

viewer.setAutoZ(None)
check("cleared guides: nothing drawn", viewer._auto_z_guides() == [])

# placement on a Before | After pair (400 px wide: the dual-panel aspect).
# Wood top = 60, Keep = 100, Cut = Metal top = 150; the Metal Top label and the
# Cut line share slice 150, so the layering check runs on that pair.
lay = Viewer2D()
lay.resize(420, 320)
pm = QPixmap(400, 200)
pm.fill(QColor(70, 70, 70))
lay.setPixmap(pm, 200)
lay.setSliceCount(200)
lay.setCut(150)          # cut first: setKeep clamps to the cut
lay.setKeep(100)
lay.setGuideEnabled(True)
lay.setAutoZ({"keep": 100, "wood_top": 60, "cut": 150, "metal_top": 150})
lay.show()
app.processEvents()
grab = lay.grab().toImage()
img_rect = lay._image_rect()
left, right = lay._panel_rects(img_rect)
check("the test canvas is a Before | After pair", right is not None)

cases = [
    ("Wood Top label", 60, GREEN, "left"),
    ("Metal Top label", 150, ORANGE, "left"),
    ("Keep label", 100, GREEN, "right"),
    ("Cut label", 150, RED, "right"),
]
for name, sl, rgb, side in cases:
    y = int(round(lay._slice_to_y(sl, img_rect)))
    on_left = ink(grab, left.left() + 27, left.right(), y, rgb)
    on_right = ink(grab, right.left(), right.right() - 27, y, rgb)
    # a label is many pixels on its own panel; a stray antialiased pixel on the other is not a label
    ok = (on_left > 20 and on_right * 10 < on_left) if side == "left" \
        else (on_right > 20 and on_left * 10 < on_right)
    check(f"{name} sits on the {side} panel", ok, f"left={on_left} right={on_right}")

# layering: the Metal Top label sits in front of the Cut line on the same slice.
# A red pixel inside the label's left margin means the line was painted over it.
y = int(round(lay._slice_to_y(150, img_rect)))
x0 = int(left.left() + 30)
reds = 0
for yy in range(y - 6, y + 7):
    for xx in range(x0 + 2, x0 + 9):
        c = grab.pixelColor(xx, yy)
        if c.red() > 200 and c.green() < 120 and c.blue() < 120:
            reds += 1
check("guide labels are drawn in front of the job lines", reds == 0, f"{reds} red px")

if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
