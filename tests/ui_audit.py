"""UI audit harness: drive every control in the main window in each state, and
check the invariants after every step. Slow (about eight minutes): run it by
hand after UI changes, not in the regression gate.

Run with the isolated environment the gate uses (see tests/ui_probe.py).

A step is OK when it raises nothing, opens no prompt the step did not expect,
and leaves the window consistent. Anything else is a finding with the step's
name, so it can be reproduced. Output: one line per step, then a summary.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import ui_probe as up  # noqa: E402  (offscreen env, helpers, prompt guard)
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton, QApplication, QComboBox, QDialog, QFileDialog, QInputDialog,
    QMenu, QMessageBox, QPushButton,
)

app = QApplication.instance() or QApplication(sys.argv)
import theme  # noqa: E402
import main_window as mw  # noqa: E402
import capture_screens as cs  # noqa: E402
from core import custom_series as csx  # noqa: E402
from dialogs.load_dialog import LoadDialog  # noqa: E402

TMP = Path(os.environ["CLEANCT_TEST_TMP_DIR"]) / "audit"
TMP.mkdir(parents=True, exist_ok=True)
OUT = TMP / "audit_results.txt"

findings: list[str] = []
rows: list[str] = []
excepts: list[str] = []
expected_prompts: set[str] = set()
prompt_log: list[str] = []


def excepthook(exc_type, exc, tb):
    excepts.append(f"{exc_type.__name__}: {exc}")
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = excepthook

# modal dialogs: answer them here, so the audit never blocks
answers = {"question": QMessageBox.Yes}
QMessageBox.question = staticmethod(lambda *a, **k: answers["question"])
QInputDialog.getText = staticmethod(lambda *a, **k: (k.get("text", "") or "audit_renamed", True))
QMenu.exec = lambda self, *a, **k: None
picked: dict = {}
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: picked.get("dir", str(TMP / "picked")))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (picked.get("save", str(TMP / "saved.ctcheckpoint.json")), ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (picked.get("open", ""), ""))
spawned: list = []
subprocess.Popen = lambda *a, **k: spawned.append(a)


def fake_load_exec(self):
    """Stand in for the Load dialog: type a source and an ID, press Load & Register."""
    self.edit_folder.setText(picked["load_src"])
    self.edit_specimen.setText(picked["load_id"])
    self._validate_and_accept()
    return 1 if self.result() == QDialog.Accepted else 0


LoadDialog.exec = fake_load_exec


def about_exec(self):
    return 0


def settle(window, seconds: float = 0.0):
    for _ in range(3):
        app.processEvents()
    if seconds:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)


def wait_idle(window):
    cs.pump(app, lambda: window._active_worker is None and not window._loading
            and window._preview_worker is None and not window._preview_timer.isActive(), 240)
    settle(window, 0.2)


def invariants(window) -> list[str]:
    """Consistency rules that must hold once the window is idle."""
    bad: list[str] = []
    busy = bool(window._loading or (window._active_worker is not None
                                    and window._active_worker.isRunning()))
    has_payload = window.payload is not None
    unprocessed = bool((window.payload or {}).get("unprocessed"))
    if not busy:
        if not window.btn_load.isEnabled():
            bad.append("Load scan disabled while idle")
        if not window.sample_list.isEnabled():
            bad.append("specimen list disabled while idle")
        # Process runs on any loaded specimen, processed or not: that is its job
        if window.btn_process.isEnabled() != has_payload:
            bad.append(f"Process enabled={window.btn_process.isEnabled()} with a specimen={has_payload}")
        # Save checkpoint is available once a preview exists, and stays so while idle
        if has_payload and window._last_pref_preview is not None \
                and not window.btn_save_checkpoint.isEnabled():
            bad.append("Save checkpoint disabled while idle with a preview present")
    if window.stack.currentIndex() not in (0, 1, 2):
        bad.append("stack on an unknown page")
    tabs = {0: window.btn_tab_auto, 1: window.btn_tab_prefs, 2: window.btn_tab_settings}
    active = [i for i, b in tabs.items() if b.property("active") == "true"]
    if active != [window.stack.currentIndex()]:
        bad.append(f"tab highlight {active} does not match page {window.stack.currentIndex()}")
    if window.settings_nav.currentRow() != window.settings_stack.currentIndex():
        bad.append("settings rail and section disagree")
    seg = [k for k, b in window.ctrl_segments.items() if b.property("active") == "true"]
    keys = list(window.ctrl_segments)
    if seg != [keys[window.ctrl_stack.currentIndex()]]:
        bad.append(f"Boundaries segment highlight {seg} does not match its page")
    if not has_payload and window.lbl_state_chip.isVisible():
        bad.append("state chip shown with no specimen")
    for lo, slo in ((window.spin_lo, window.slider_lo), (window.spin_hi, window.slider_hi)):
        if lo.value() != slo.value():
            bad.append(f"threshold spin {lo.value()} and slider {slo.value()} disagree")
    return bad


def step(name: str, fn, window, expect_prompt: bool = False):
    """Run one control action; record exceptions, prompts and invariant violations."""
    before_prompts = len(up.stats["prompts"])
    before_exc = len(excepts)
    t0 = time.monotonic()
    status = "OK"
    detail = ""
    try:
        fn()
        settle(window, 0.05)
    except Exception as exc:  # noqa: BLE001
        status, detail = "RAISED", f"{type(exc).__name__}: {exc}"
    new_prompts = up.stats["prompts"][before_prompts:]
    if new_prompts and not expect_prompt:
        status = "PROMPT" if status == "OK" else status
        detail += " | prompts: " + "; ".join(
            p["title"] + ": " + p["text"][:120].replace("\n", " ") for p in new_prompts)
    if len(excepts) > before_exc:
        status = "EXCEPTION"
        detail += " | " + "; ".join(excepts[before_exc:])
    elapsed = time.monotonic() - t0
    wait_idle(window)
    bad = invariants(window)
    if bad:
        status = "INVARIANT" if status == "OK" else status
        detail += " | " + "; ".join(bad)
    line = f"{status:9s} {name}  ({elapsed:.2f}s)" + (f"  {detail}" if detail and status != "OK" else "")
    rows.append(line)
    if status != "OK":
        findings.append(line)
    print(line, flush=True)


def click(widget):
    """A real mouse click on the widget's centre."""
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, widget.rect().center())


def click_text(window, text: str):
    for b in window.findChildren(QAbstractButton):
        if b.text() == text and b.isVisible() and b.isEnabled():
            return click(b)
    raise LookupError(f"no visible enabled button '{text}'")


def click_row(window, index: int):
    item = window.sample_list.item(index)
    rect = window.sample_list.visualItemRect(item)
    QTest.mouseClick(window.sample_list.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())


def set_value(widget, value):
    widget.setValue(value)


def controls_for_state(window, label: str):
    """Every control in the main window, once, in this state."""
    s = lambda name, fn, expect=False: step(f"[{label}] {name}", fn, window, expect)  # noqa: E731

    # --- sidebar: specimen list, filter, row actions ---------------------------
    for i in range(min(window.sample_list.count(), 6)):
        if window.sample_list.item(i).data(Qt.UserRole):
            s(f"select specimen row {i}", lambda i=i: click_row(window, i))
    s("filter: type 'probe'", lambda: window.edit_search.setText("probe"))
    s("filter: clear", lambda: window.edit_search.setText(""))
    if window.btn_rename.isEnabled():
        s("rename selected", lambda: click(window.btn_rename))
    if window.btn_duplicate.isEnabled():
        s("copy (duplicate) selected", lambda: click(window.btn_duplicate))
    if window.btn_locate.isEnabled():
        s("find (locate) selected", lambda: click(window.btn_locate))
    s("Load scan (fake source)", lambda: (picked.update(load_src=str(src_loaded()),
                                                       load_id=f"audit_{time.monotonic_ns() % 100000}"),
                                          click(window.btn_load)))
    if window.combo_preview_history.count() > 1:
        home = (window.dataset, window.sample)
        for i in range(1, window.combo_preview_history.count()):
            s(f"preview history entry {i}", lambda i=i: window.combo_preview_history.setCurrentIndex(i))
        window.combo_preview_history.setCurrentIndex(0)
        # a history entry for another specimen selects that specimen: come back to ours
        if home[0] and (window.dataset, window.sample) != home:
            window._select_sample(*home)
            wait_idle(window)
    s("Save checkpoint", lambda: click(window.btn_save_checkpoint),
      expect=not window.btn_save_checkpoint.isEnabled())
    s("Open checkpoint (saved file)", lambda: (picked.update(open=str(TMP / "saved.ctcheckpoint.json")),
                                              click(window.btn_load_checkpoint)))

    # --- activity -----------------------------------------------------------------
    s("activity: show", lambda: click(window.btn_log_toggle))
    s("activity: hide", lambda: click(window.btn_log_toggle))
    s("activity: clear", lambda: click(_clear_button(window)))

    # --- the three tabs and the settings rail -----------------------------------
    s("tab: Boundaries", lambda: click(window.btn_tab_prefs))
    s("tab: Results", lambda: click(window.btn_tab_auto))
    s("tab: Settings", lambda: click(window.btn_tab_settings))
    for row in range(window.settings_nav.count()):
        s(f"settings rail row {row}", lambda row=row: click_row_nav(window, row))
    s("settings: theme light", lambda: window.cmb_theme.setCurrentIndex(window.cmb_theme.findData("light")))
    s("settings: theme dark", lambda: window.cmb_theme.setCurrentIndex(window.cmb_theme.findData("dark")))
    s("settings: export folder typed", lambda: (window.edit_save_root.setText(str(TMP / "typed")),
                                               window.edit_save_root.editingFinished.emit()))
    s("settings: export folder Browse", lambda: (picked.update(dir=str(TMP / "browsed")),
                                                click_obj(window, "btn_browse_export")))
    for i in range(window.combo_export_format.count()):
        s(f"settings: format {i}", lambda i=i: window.combo_export_format.setCurrentIndex(i))
    s("settings: checkpoint folder Choose", lambda: (picked.update(dir=str(TMP / "ckpt")),
                                                    click_obj(window, "btn_choose_checkpoint_dir")))
    s("tab: Results (again)", lambda: click(window.btn_tab_auto))

    # --- Results page: export, long view, 3-D ---------------------------------
    s("Change in Settings link", lambda: click_obj(window, "btn_change_export"))
    s("Results: back to Results", lambda: click(window.btn_tab_auto))
    s("Results: axial slider 0", lambda: window.axial_slider.setValue(0))
    s("Results: axial slider max", lambda: window.axial_slider.setValue(window.axial_slider.maximum()))
    s("Results: long view Coronal", lambda: click(window.btn_long_cor))
    s("Results: long view Sagittal", lambda: click(window.btn_long_sag))
    s("3-D: Real 3D", lambda: click(window.btn_3d_real))
    s("3-D: Simple", lambda: click(window.btn_3d_simple))
    s("3-D: Reset view", lambda: click_text(window, "Reset view"))
    s("3-D: Spin on", lambda: click(window.btn_spin_3d))
    s("3-D: Spin off", lambda: click(window.btn_spin_3d))
    s("Export (header)", lambda: click(window.btn_export),
      expect=not window.btn_export.isEnabled())
    s("Process selected", lambda: click(window.btn_process),
      expect=not window.btn_process.isEnabled())
    s("Process and export", lambda: click(window.btn_process_export),
      expect=not window.btn_process_export.isEnabled())
    s("About (open, closed by the guard)", lambda: click_obj(window, "btn_about"),
      expect=True)

    # --- Boundaries page ---------------------------------------------------------
    s("tab: Boundaries (open)", lambda: click(window.btn_tab_prefs))
    for key in ("lines", "display", "lateral"):
        s(f"Boundaries segment {key}", lambda key=key: window._set_ctrl_segment(key))
    window._set_ctrl_segment("lines")
    for name in ("btn_plane_cor", "btn_plane_ax", "btn_plane_sag"):
        s(f"plane {name}", lambda n=name: click(getattr(window, n)))
    s("Interactive guides off", lambda: window.chk_guides.setChecked(False))
    s("Interactive guides on", lambda: window.chk_guides.setChecked(True))
    s("2 lines", lambda: click(window.btn_guide_2l))
    s("4 lines", lambda: click(window.btn_guide_4l))
    s("Snap to detection", lambda: click(window.btn_snap_lines), expect=False)
    s("auto snap off", lambda: window.chk_auto_snap.setChecked(False))
    s("auto snap on", lambda: window.chk_auto_snap.setChecked(True))
    for key in ("keep", "cut", "margin"):
        spin, slider = getattr(window, f"spin_{key}"), getattr(window, f"slider_{key}")
        s(f"{key}: spin to 5", lambda sp=spin: sp.setValue(5))
        s(f"{key}: slider to 1", lambda sl=slider: sl.setValue(1))
        s(f"{key}: spin past the top", lambda sp=spin: sp.setValue(sp.maximum()))
    for key in ("left", "right", "top", "bottom"):
        spin = getattr(window, f"spin_{key}")
        s(f"lateral {key}: spin to 30", lambda sp=spin: sp.setValue(30))
    window._set_ctrl_segment("display")
    for cm in ("grayscale", "spectral", "thermal", "viridis", "plasma"):
        s(f"palette {cm}", lambda c=cm: window._set_pref_cmap(c))
    for name, lo, hi in (("Full", -1000, 2000), ("Wood Tissue", -600, 350),
                         ("High Contrast", -350, 150), ("Platform Metal", 0, 1600)):
        s(f"threshold preset {name}", lambda n=name: click_text(window, n))
    s("threshold Reset", lambda: click(window.btn_th_reset))
    s("min HU spin -300", lambda: window.spin_lo.setValue(-300))
    s("max HU slider 200", lambda: window.slider_hi.setValue(200))
    window._set_ctrl_segment("lateral")
    s("air crop off", lambda: window.chk_air_crop.setChecked(False))
    s("air crop on", lambda: window.chk_air_crop.setChecked(True))
    window._set_ctrl_segment("lines")
    s("Reset to detected", lambda: click_text(window, "Reset to detected"))
    s("Apply lines", lambda: click(window.btn_apply_prefs),
      expect=not window.btn_apply_prefs.isEnabled())
    s("Boundaries: pref slice slider", lambda: window.pref_slider.setValue(window.pref_slider.maximum() // 2))
    s("tab: Results (leave Boundaries)", lambda: click(window.btn_tab_auto))

    # --- keyboard shortcuts ----------------------------------------------------
    s("shortcut Ctrl+S (save checkpoint)", lambda: QTest.keySequence(window, "Ctrl+S"))
    s("shortcut Ctrl+O (load scan)", lambda: (picked.update(load_src=str(src_loaded()),
                                                           load_id=f"audit_k{time.monotonic_ns() % 100000}"),
                                              QTest.keySequence(window, "Ctrl+O")))
    s("shortcut F2 (rename, list focused)", lambda: (window.sample_list.setFocus(),
                                                    QTest.keySequence(window.sample_list, "F2")))
    s("shortcut Ctrl+R (process)", lambda: QTest.keySequence(window, "Ctrl+R"))
    s("shortcut Ctrl+E (export)", lambda: QTest.keySequence(window, "Ctrl+E"))
    # Delete on a disposable specimen only: the later steps still need the others
    picked.update(load_src=str(src_loaded()), load_id=f"audit_del{time.monotonic_ns() % 100000}")
    s("load a disposable specimen for Delete", lambda: click(window.btn_load))
    s("shortcut Delete (remove the disposable)", lambda: (window.sample_list.setFocus(),
                                                         QTest.keySequence(window.sample_list, "Del")))


def click_obj(window, object_name: str):
    widget = window.findChild(QAbstractButton, object_name)
    if widget is None:
        raise LookupError(object_name)
    click(widget)


def click_row_nav(window, row: int):
    item = window.settings_nav.item(row)
    rect = window.settings_nav.visualItemRect(item)
    QTest.mouseClick(window.settings_nav.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())


def _clear_button(window):
    for b in window.findChildren(QPushButton):
        if b.text() == "Clear":
            return b
    raise LookupError("Clear")


_SRC: dict = {}


def src_loaded() -> Path:
    if "p" not in _SRC:
        _SRC["p"] = TMP / "audit_src"
        cs.write_wood_metal_series(_SRC["p"] / "XY", n=60, rows=256, cols=256, um=0.066)
    return _SRC["p"]


def main() -> int:
    theme.set_mode("dark")
    theme.apply(app)
    guard = up.install_prompt_guard(app)
    window = mw.MainWindow()
    window.resize(1280, 720)
    window.show()
    settle(window, 0.5)

    # landing: no specimen selected yet
    controls_for_state(window, "landing")

    # unprocessed specimen
    csx.register_series(src_loaded(), "audit_unprocessed")
    window._select_sample("custom", "audit_unprocessed")
    cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)
    wait_idle(window)
    controls_for_state(window, "unprocessed")

    # processed specimen
    window._process_selected()
    cs.pump(app, lambda: window._active_worker is not None, 10)
    wait_idle(window)
    controls_for_state(window, "processed")

    guard.stop()
    window.close()
    OUT.write_text("\n".join(rows) + f"\n\nSUMMARY: {len(rows)} steps, {len(findings)} findings\n",
                   encoding="utf-8")
    print(f"SUMMARY: {len(rows)} steps, {len(findings)} findings", flush=True)
    print("RESULTS:", OUT, flush=True)
    print("AUDIT_DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
