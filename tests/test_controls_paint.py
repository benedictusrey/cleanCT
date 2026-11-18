"""Spin boxes and combo boxes draw their arrows in both themes.

The stylesheet gives these fields their own background and border, which switches
off Qt's native arrows. Without arrow rules the up and down arrows (spin boxes) and
the chevron (combo boxes) do not show at all. This test renders each control and
checks that pixels in the arrow area match the theme's arrow colour.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QSpinBox, QVBoxLayout, QWidget  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import theme  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(label)


def hex_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def near(pixel, rgb, tolerance: int = 12) -> bool:
    return (abs(pixel.red() - rgb[0]) + abs(pixel.green() - rgb[1])
            + abs(pixel.blue() - rgb[2])) <= tolerance


def arrow_pixels(image, widget, root, half: str | None = None) -> int:
    """Count pixels in the widget's right-hand 22 px strip that match the arrow colour."""
    origin = widget.mapTo(root, widget.rect().topLeft())
    colour = hex_rgb(theme.color("text_2"))
    h = widget.height()
    y0, y1 = {"top": (3, h // 2), "bottom": (h // 2, h - 3), None: (3, h - 3)}[half]
    count = 0
    for dx in range(widget.width() - 16, widget.width() - 5):
        for dy in range(y0, y1):
            if near(image.pixelColor(origin.x() + dx, origin.y() + dy), colour):
                count += 1
    return count


for mode in ("dark", "light"):
    theme.set_mode(mode)
    theme.apply(app)
    root = QWidget()
    layout = QVBoxLayout(root)
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(42)
    dspin = QDoubleSpinBox()
    dspin.setRange(0.0, 9.0)
    combo = QComboBox()
    combo.addItems(["Dark", "Light"])
    for widget in (spin, dspin, combo):
        layout.addWidget(widget)
    root.resize(240, 130)
    root.show()
    app.processEvents()
    image = root.grab().toImage()

    check(f"{mode}: spin box up arrow draws", arrow_pixels(image, spin, root, "top") >= 3,
          f"{arrow_pixels(image, spin, root, 'top')} px")
    check(f"{mode}: spin box down arrow draws", arrow_pixels(image, spin, root, "bottom") >= 3,
          f"{arrow_pixels(image, spin, root, 'bottom')} px")
    check(f"{mode}: double spin box arrows draw",
          arrow_pixels(image, dspin, root, "top") >= 3
          and arrow_pixels(image, dspin, root, "bottom") >= 3)
    check(f"{mode}: combo box chevron draws", arrow_pixels(image, combo, root) >= 3,
          f"{arrow_pixels(image, combo, root)} px")
    root.close()

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
sys.exit(1 if failures else 0)
