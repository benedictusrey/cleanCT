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

# shape of the wood_bounds payload for specimen 2-5: keep = air top,
# cut = halo onset (353), metal_top = detector anchor / arrow line (405)
viewer.setAutoZ({"keep": 19, "cut": 353, "wood_top": 1, "metal_top": 405,
                 "wood_bottom": 328, "top_ok": True})
g = guides_of(viewer)
check("metal top guide sits on the physical metal top (405)",
      g.get("metal") == (405, "metal top 405"), str(g.get("metal")))
check("halo onset guide sits on the cut (353), not on the metal top",
      g.get("halo") == (353, "halo onset 353"), str(g.get("halo")))
check("air top guide unchanged", g.get("air") == (19, "air top 19"), str(g.get("air")))
check("no wood top guide while the air top is placed", "wood" not in g, str(g.get("wood")))

# older payload without metal_top: no metal line, and the cut is never
# relabelled as metal
viewer.setAutoZ({"keep": 19, "cut": 353})
g_old = guides_of(viewer)
check("no metal_top: no metal guide", "metal" not in g_old, str(g_old))
check("no metal_top: halo onset still drawn", g_old.get("halo") == (353, "halo onset 353"),
      str(g_old.get("halo")))

# air top deferred (foggy edge): wood top evidence shows instead
viewer.setAutoZ({"keep": None, "cut": 353, "wood_top": 1, "metal_top": 405})
g_def = guides_of(viewer)
check("air deferred: wood top guide drawn", g_def.get("wood") == (1, "wood top 1"),
      str(g_def.get("wood")))
check("air deferred: no air guide", "air" not in g_def, str(g_def))

viewer.setAutoZ(None)
check("cleared guides: nothing drawn", viewer._auto_z_guides() == [])

if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
