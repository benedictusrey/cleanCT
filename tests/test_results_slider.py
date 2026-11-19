"""The Results longitudinal view has a position slider: X for Sagittal, Y for Coronal.

1. The slider covers the plane's own axis: X (the columns) for sagittal, Y (the rows)
   for coronal, and starts at the middle, as the Boundaries preview does.
2. The label reads x=N (sagittal) or y=N (coronal), like the Boundaries label.
3. Moving the slider renders the plane at that position (the image changes), and
   the coronal toggle switches the slider to Y.
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

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import capture_screens as cs  # noqa: E402
from core import custom_series as csx  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


ROWS, COLS, NZ = 24, 40, 14
src = TEST_TMP / "slider_src"
cs.write_wood_metal_series(src / "XY", n=NZ, rows=ROWS, cols=COLS, um=66.0)
name = "slider_spec"
if name not in csx.registered_specimens():
    csx.register_series(src, name)

import main_window as mw  # noqa: E402

window = mw.MainWindow()
window.resize(1280, 720)
window.show()
window._select_sample("custom", name)
cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)


def long_pixmap_key():
    pm = window.long_viewer._pixmap
    return None if pm is None or pm.isNull() else pm.cacheKey()


# 1. sagittal: the X slider covers the columns and starts in the middle
cs.pump(app, lambda: window.long_slider.maximum() == COLS - 1, 60)
check("sagittal: the X slider covers the columns", window.long_slider.maximum() == COLS - 1,
      f"max={window.long_slider.maximum()}")
check("sagittal: the X slider starts in the middle", window.long_slider.value() == COLS // 2,
      f"value={window.long_slider.value()}")
check("sagittal: the label reads x=N", window.lbl_long_pos.text() == f"x={COLS // 2}",
      window.lbl_long_pos.text())

# 2. moving the slider renders the plane at that X
before = long_pixmap_key()
window.long_slider.setValue(5)
cs.pump(app, lambda: window._long_pos == 5 and long_pixmap_key() != before, 60)
check("moving the X slider renders the plane at x=5", window._long_pos == 5
      and window.lbl_long_pos.text() == "x=5", f"pos={window._long_pos} label={window.lbl_long_pos.text()}")
check("the picture changes with the X position", long_pixmap_key() != before)

# 3. coronal: the Y slider covers the rows
window._toggle_long_view("coronal")
cs.pump(app, lambda: window.long_slider.maximum() == ROWS - 1, 60)
check("coronal: the Y slider covers the rows", window.long_slider.maximum() == ROWS - 1,
      f"max={window.long_slider.maximum()}")
check("coronal: the label reads y=N", window.lbl_long_pos.text() == f"y={ROWS // 2}",
      window.lbl_long_pos.text())

window.close()
if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
