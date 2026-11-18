"""The window fits a 1280x720 client without scrolling, on every page.

Each Boundaries group (Lines, Display, Lateral box) must fit the stack it sits in,
so no control is hidden behind a scroll bar. The apply row stays pinned. The header
and the sidebar follow the copy and clipping rules.
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import theme  # noqa: E402
import main_window as mw  # noqa: E402
from core import custom_series as csx  # noqa: E402
import capture_screens as cs  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def overflowing_areas(window) -> list[str]:
    """Visible scroll areas that need a vertical scroll bar at this size."""
    found = []
    for area in window.findChildren(QScrollArea):
        if area.isVisible() and area.verticalScrollBar().maximum() > 0:
            found.append(area.objectName() or type(area.widget()).__name__)
    return found


def settle(window) -> None:
    for _ in range(3):
        app.processEvents()


theme.set_mode("dark")
theme.apply(app)
src = TEST_TMP / "layout_fit_src"
cs.write_wood_metal_series(src / "XY", n=60, rows=384, cols=384, um=0.066)
csx.register_series(src, "layout_fit")

window = mw.MainWindow()
window.show()
window._select_sample("custom", "layout_fit")
cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)
settle(window)

for width, height in ((1280, 720), (1920, 1080)):
    window.resize(width, height)
    for tab in ("auto", "prefs", "settings"):
        window._switch_tab(tab, schedule=False)
        settle(window)
        overflow = overflowing_areas(window)
        check(f"{width}x{height} {tab} needs no vertical scroll", not overflow,
              ", ".join(overflow))

    window._switch_tab("prefs", schedule=False)
    for key in ("lines", "display", "lateral"):
        window._set_ctrl_segment(key)
        settle(window)
        page = window.ctrl_stack.currentWidget()
        need, have = page.sizeHint().height(), window.ctrl_stack.height()
        check(f"{width}x{height} Boundaries '{key}' fits its stack", need <= have,
              f"needs {need}px, has {have}px")
    check(f"{width}x{height} apply row stays visible",
          window.btn_apply_prefs.isVisible()
          and window.btn_apply_prefs.geometry().bottom() <= window.height(),
          f"bottom {window.btn_apply_prefs.geometry().bottom()}, height {window.height()}")

# tab menu: workspace tabs are underlined, and Settings is a tab too
check("the three tabs use the underlined tab role",
      all(b.property("role") == "tab"
          for b in (window.btn_tab_auto, window.btn_tab_prefs, window.btn_tab_settings)))
check("the active tab carries the active state",
      window.btn_tab_prefs.property("active") in ("true", True))

# header: the subtitle states the state; the name is in the title
window._switch_tab("auto", schedule=False)
check("the subtitle does not repeat the specimen name",
      "layout_fit" not in window.lbl_sample_sub.text(), window.lbl_sample_sub.text()[:60])

# sidebar: no sideways bar on the specimen list
check("the specimen list has no sideways scroll bar",
      window.sample_list.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff)

window.close()
print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
sys.exit(1 if failures else 0)
