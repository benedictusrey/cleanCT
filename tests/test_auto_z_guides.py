"""Auto z-guides: the physical metal top and the halo-onset cut are two lines.

The metal top is the detector anchor (the physical base top).  The halo onset
is the cut the pipeline makes.  Each must sit at its own slice and carry its
own name, so a "metal top" label never lands on the cut slice.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from widgets.viewer_2d import Viewer2D  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def guides_of(viewer: Viewer2D) -> dict:
    return {kind: (sl, label) for kind, sl, label in viewer._auto_z_guides()}


app = QApplication.instance() or QApplication(sys.argv)
viewer = Viewer2D()

# 2_666_5 payload: the Keep is the wood top (88), the air top (83) is not drawn,
# the Cut is the metal top (521); the halo onset (353 on 2-5) is never a line
viewer.setAutoZ({"keep": 83, "cut": 521, "wood_top": 88, "metal_top": 521,
                 "wood_bottom": 518, "top_ok": True})
g = guides_of(viewer)
check("keep guide sits on the wood top (88)",
      g.get("wood") == (88, "wood top 88"), str(g.get("wood")))
check("metal top guide sits on the physical metal top (521)",
      g.get("metal") == (521, "metal top 521"), str(g.get("metal")))
check("no air top line: the Keep rides the wood top", "air" not in g, str(g))
check("no halo onset line", "halo" not in g, str(g))

# older payload without wood_top: the Keep falls back to the air top
viewer.setAutoZ({"keep": 19, "cut": 353})
g_old = guides_of(viewer)
check("no wood_top: the Keep guide is the air top", g_old.get("air") == (19, "air top 19"),
      str(g_old))
check("no metal_top: no metal guide", "metal" not in g_old, str(g_old))

# air top deferred (foggy edge): wood top evidence shows instead
viewer.setAutoZ({"keep": None, "cut": 353, "wood_top": 1, "metal_top": 405})
g_def = guides_of(viewer)
check("air deferred: wood top guide drawn", g_def.get("wood") == (1, "wood top 1"),
      str(g_def.get("wood")))
check("air deferred: no air guide", "air" not in g_def, str(g_def))

viewer.setAutoZ(None)
check("cleared guides: nothing drawn", viewer._auto_z_guides() == [])

# layering: a guide label sits in front of the job line that shares its slice.
# Keep = wood top = slice 100 and Cut = metal top = slice 160 (the screenshots).
# Sample the left margin of each label, where no text is: a red pixel there
# means the Cut line was painted over the label.
from PySide6.QtGui import QPixmap  # noqa: E402

lay = Viewer2D()
lay.resize(420, 320)
lay.setPixmap(QPixmap(200, 200), 200)
lay.setSliceCount(200)
lay.setKeep(100)
lay.setCut(160)
lay.setGuideEnabled(True)
lay.setAutoZ({"keep": 100, "wood_top": 100, "cut": 160, "metal_top": 160})
lay.show()
app.processEvents()
grab = lay.grab().toImage()
img_rect = lay._image_rect()
bad = []
for kind, sl in (("wood", 100), ("metal", 160)):
    y = int(round(lay._slice_to_y(sl, img_rect)))
    x0 = int(img_rect.left() + 30) if kind == "wood" else int(img_rect.right() - 146)
    reds = 0
    for yy in range(y - 6, y + 7):
        for xx in range(x0 + 2, x0 + 9):
            c = grab.pixelColor(xx, yy)
            if c.red() > 200 and c.green() < 120 and c.blue() < 120:
                reds += 1
    if reds:
        bad.append(f"{kind} label: {reds} red px")
check("guide labels are drawn in front of the job lines", not bad, "; ".join(bad))

if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
