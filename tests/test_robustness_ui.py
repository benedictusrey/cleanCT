"""Robustness of the window's transitions: the preview wait is shown and explained,
and closing while a step runs keeps the window on screen and says what it waits for.

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

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import theme  # noqa: E402
import main_window as mw  # noqa: E402
import capture_screens as cs  # noqa: E402
from core import custom_series as csx  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


theme.set_mode("dark")
theme.apply(app)
src = TEST_TMP / "robust_src"
cs.write_wood_metal_series(src / "XY", n=60, rows=256, cols=256, um=0.066)
csx.register_series(src, "robust_spec")

window = mw.MainWindow()
window.resize(1280, 720)
window.show()
window._select_sample("custom", "robust_spec")
cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)
window._process_selected()
cs.pump(app, lambda: window._active_worker is not None, 10)
cs.pump(app, lambda: window._active_worker is None and not window._loading, 240)
for _ in range(20):
    app.processEvents()

# --- the preview wait is shown, and the save button says why it waits -------------
preview = window._last_pref_preview
window._last_pref_preview = None
window._set_job_gates(process_ready=True)
check("the preview wait is shown in the status bar",
      window.lbl_preview_status.text() == "Preparing the preview…",
      window.lbl_preview_status.text())
check("Save checkpoint says it waits for the preview",
      not window.btn_save_checkpoint.isEnabled()
      and "Available once the preview is ready." in window.btn_save_checkpoint.toolTip(),
      window.btn_save_checkpoint.toolTip().replace("\n", " | "))
window._last_pref_preview = preview
window._set_job_gates(process_ready=True)
check("the preview wait clears once the preview is there",
      window.lbl_preview_status.text() == "",
      repr(window.lbl_preview_status.text()))
check("Save checkpoint is available with a preview",
      window.btn_save_checkpoint.isEnabled())
check("the Save tooltip drops the waiting note once available",
      "Available once the preview is ready." not in window.btn_save_checkpoint.toolTip())

# --- closing during a step: the window stays visible and says what it waits for ---
window._process_selected()
cs.pump(app, lambda: window._active_worker is not None, 10)
seen: dict = {}


def record_while_closing():
    seen["visible"] = window.isVisible()
    seen["phase"] = window.lbl_job_phase.text()
    seen["job_box"] = window.job_box.isVisible()


QTimer.singleShot(60, record_while_closing)
window.close()
check("the window stays on screen while a step finishes",
      seen.get("visible") is True, str(seen))
check("closing says what it waits for",
      seen.get("phase", "").startswith("Finishing the current step"), seen.get("phase", ""))
check("the progress shows while closing", seen.get("job_box") is True)

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
sys.exit(1 if failures else 0)
