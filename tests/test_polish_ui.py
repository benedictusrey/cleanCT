"""Polish pass: the header states the state, the status line has one home, copy is
sentence case, nothing wraps that should not, and the toggles share one style.

Runs offscreen against the sandboxed state root that the regression runner sets.
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

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import theme  # noqa: E402
import main_window as mw  # noqa: E402
from core import custom_series as csx  # noqa: E402
import capture_screens as cs  # noqa: E402
from widgets import viewer_3d  # noqa: E402
from widgets.specimen_panel import ROW_HEIGHT  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def label_with(window, needle: str):
    for label in window.findChildren(QLabel):
        if needle in label.text():
            return label
    return None


theme.set_mode("dark")
theme.apply(app)
src = TEST_TMP / "polish_src"
cs.write_wood_metal_series(src / "XY", n=60, rows=384, cols=384, um=0.066)
csx.register_series(src, "polish_spec")

window = mw.MainWindow()
window.resize(1280, 720)
window.show()
app.processEvents()

# --- header: the state chip and a subtitle that does not repeat the name -----------
chip = window.lbl_state_chip
check("the header has a state chip", chip is not None)
window._select_sample("custom", "polish_spec")
cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)
app.processEvents()
check("an unprocessed specimen shows 'Not processed'", chip.text() == "Not processed",
      chip.text())
check("the subtitle does not repeat the specimen name",
      "polish_spec" not in window.lbl_sample_sub.text(), window.lbl_sample_sub.text())

# --- status: one home at the bottom of the workspace --------------------------------
status = window.findChild(QFrame, "statusbar")
check("the window has a bottom status bar", status is not None)
check("the job progress sits in the status bar",
      status is not None and status.isAncestorOf(window.job_box))
check("export messages sit in the status bar",
      status is not None and status.isAncestorOf(window.lbl_export_status))
check("the export status is not in the header row",
      not window.findChild(QFrame, "tabbar").isAncestorOf(window.lbl_export_status))

# --- sidebar: the specimen list keeps room for several rows at 1280x720 -------------
check("the specimen list shows at least four rows at 1280x720",
      window.sample_list.viewport().height() >= 4 * ROW_HEIGHT,
      f"viewport {window.sample_list.viewport().height()} px, row {ROW_HEIGHT} px")

# --- no wrapping where the text must stay on one line -----------------------------
legend = label_with(window, "wood ROI")
check("the axial legend does not wrap", legend is not None and not legend.wordWrap())
check("the export path does not wrap", not window.lbl_export_dest.wordWrap())

# --- activity: one line, sentence case --------------------------------------------
window._log_action("test message for the activity line")
check("activity lines start with a capital letter",
      window.lbl_log_last.toolTip().endswith("Test message for the activity line"),
      window.lbl_log_last.toolTip())   # the label is elided to its width; the tooltip keeps the line
check("the activity line is one line", not window.lbl_log_last.wordWrap())

# --- copy: sentence case, en dashes, no leading lower-case words ------------------
check("the delivery summary starts with a capital",
      window.lbl_range_summary.text()[:1].isupper(), window.lbl_range_summary.text())
check("the 3-D caption starts with a capital",
      viewer_3d.caption("simple", "spectral")[:1].isupper(),
      viewer_3d.caption("simple", "spectral"))
check("the 3-D caption names the look in plain words",
      viewer_3d.caption("simple", "spectral") == "Amber wood, silver metal",
      viewer_3d.caption("simple", "spectral"))

# --- toggles share one segment style ----------------------------------------------
toggles = (window.btn_plane_sag, window.btn_plane_cor, window.btn_plane_ax,
           window.btn_guide_2l, window.btn_guide_4l,
           window.btn_long_sag, window.btn_long_cor,
           window.btn_3d_simple, window.btn_3d_real)
check("every mode toggle uses the segment style",
      all(b.property("role") == "segment" for b in toggles),
      ", ".join(b.text() for b in toggles if b.property("role") != "segment"))

# --- KPI: the cut slice is the hero value; pending values read muted --------------
check("the cut slice is the hero KPI",
      window.kpi_banner.cards["cut"][1].property("role") == "kpi-hero")
check("a pending KPI value reads muted",
      window.kpi_banner.cards["removed"][1].property("role") == "kpi-muted")

# --- colour keys: re-rendered on a theme change, and 3:1 on the light panel --------
window.cmb_theme.setCurrentIndex(window.cmb_theme.findData("light"))
app.processEvents()
keep_light = theme.LIGHT["key_keep"]
check("the colour keys follow the light theme",
      keep_light in window.lbl_top.text(), window.lbl_top.text()[:80])


def _lum(hex_colour: str) -> float:
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


for key in ("key_wood", "key_metal", "key_keep", "key_lateral"):
    ratio = _ratio(theme.LIGHT[key], theme.LIGHT["panel"])
    check(f"light {key} reads at 3:1 on the panel", ratio >= 3.0, f"{ratio:.2f}:1")
window.cmb_theme.setCurrentIndex(window.cmb_theme.findData("dark"))
app.processEvents()

window.close()
print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
sys.exit(1 if failures else 0)
