"""Results crop: the After (right) half of a Before | After image keeps only the L/R box.

Display only: the Before half, the saved frames and the export are not changed.
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

from widgets.viewer_2d import crop_after_panel  # noqa: E402

failures: list[str] = []
BG = (13, 15, 20)
WHITE = (255, 255, 255)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def rgb_at(img, x: int, y: int) -> tuple[int, int, int]:
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


app = QApplication.instance() or QApplication(sys.argv)

# Before 0..199 | gap 200..209 | After 210..409, 100 rows high
pm = QPixmap(410, 100)
pm.fill(QColor(*WHITE))

# horizontal box 25%..75% of the After panel = columns 260..359
img = crop_after_panel(pm, (0.25, 0.75), None).toImage()
check("inside the L/R box the After panel is unchanged", rgb_at(img, 300, 50) == WHITE)
check("left of the box the After panel is cleared", rgb_at(img, 230, 50) == BG)
check("right of the box the After panel is cleared", rgb_at(img, 380, 50) == BG)
check("the Before panel is untouched", rgb_at(img, 100, 50) == WHITE)

# vertical box 50%..100%: the top half of the After panel is cleared
img_v = crop_after_panel(pm, None, (0.5, 1.0)).toImage()
check("above the vertical box the After panel is cleared", rgb_at(img_v, 300, 10) == BG)
check("inside the vertical box the After panel is unchanged", rgb_at(img_v, 300, 80) == WHITE)
check("the Before panel ignores the vertical box", rgb_at(img_v, 100, 10) == WHITE)

# the whole axis is no crop: the same pixmap comes back
check("no box: the frame is returned as it is", crop_after_panel(pm, None, None) is pm)

if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
