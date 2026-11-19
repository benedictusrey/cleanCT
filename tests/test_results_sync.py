"""Results and Boundaries agree on the lines.

The Results viewers draw the processed cut and keep (report.json), at the real
slice count, not the widget defaults (cut 50 of 100).  When the pending lines
on Boundaries move away from the processed run, Results keep the processed
lines and show a "Lines changed" marker.  A raw scan follows the pending lines,
like the AFTER panel.

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

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import theme  # noqa: E402
import main_window as mw  # noqa: E402
import capture_screens as cs  # noqa: E402
from core import custom_series as csx  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


theme.set_mode("dark")
theme.apply(app)
src = TEST_TMP / "results_src"
cs.write_wood_metal_series(src / "XY", n=60, rows=256, cols=256, um=0.066)
csx.register_series(src, "results_spec")
raw = TEST_TMP / "results_raw"
cs.write_wood_metal_series(raw / "XY", n=60, rows=256, cols=256, um=0.066)
csx.register_series(raw, "results_raw")

window = mw.MainWindow()
window.resize(1280, 720)
window.show()

# --- a processed specimen -------------------------------------------------------
window._select_sample("custom", "results_spec")
cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)
window._process_selected()
cs.pump(app, lambda: window._active_worker is not None, 10)
cs.pump(app, lambda: window._active_worker is None and not window._loading, 240)
for _ in range(20):
    app.processEvents()

rep = window.payload.get("report") or {}
cut_done = int(rep.get("cut_from") or 0)
n = int(rep.get("n_slices") or 0)
ax, lg = window.axial_viewer, window.long_viewer
check("processed run: the report carries the cut and the slice count",
      cut_done > 0 and n == 60, f"cut={cut_done} n={n}")
check("Results axial draws the processed cut", ax._cut == cut_done,
      f"axial cut={ax._cut} expected {cut_done}")
check("Results axial uses the real slice count (not the 100 default)",
      ax._n_slices == n, f"axial n={ax._n_slices} expected {n}")
check("Results longitudinal draws the processed cut", lg._cut == cut_done,
      f"long cut={lg._cut} expected {cut_done}")
check("in sync: no Lines changed marker", window.lbl_results_stale.isHidden())

window.spin_cut.setValue(max(1, cut_done - 5))
app.processEvents()
check("pending cut moved: Results keep the processed cut", ax._cut == cut_done,
      f"axial cut={ax._cut}")
check("pending cut moved: Lines changed marker shown", not window.lbl_results_stale.isHidden())
check("pending cut moved: marker says what Results show",
      str(cut_done) in window.lbl_results_stale.toolTip(), window.lbl_results_stale.toolTip())
window._update_axial_frame(0)
check("scrubbing keeps the processed cut and slice count",
      ax._cut == cut_done and ax._n_slices == n, f"cut={ax._cut} n={ax._n_slices}")
window.spin_cut.setValue(cut_done)
app.processEvents()
check("pending back on the processed cut: marker hidden", window.lbl_results_stale.isHidden())

# --- a raw scan: Results follow the pending lines ----------------------------------
window._select_sample("custom", "results_raw")
cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)
for _ in range(20):
    app.processEvents()
check("raw scan: Results draw the pending cut", ax._cut == window.pref_cut,
      f"axial cut={ax._cut} pending {window.pref_cut}")
check("raw scan: no Lines changed marker", window.lbl_results_stale.isHidden())

window.close()
if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
