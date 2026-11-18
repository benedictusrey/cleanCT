"""The Settings tab: where each setting lives, that it is saved as it changes,
and that the export row and the checkpoint dialogs follow those settings.

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

from PySide6.QtWidgets import QApplication, QLabel, QFileDialog, QPushButton  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import theme  # noqa: E402
import main_window as mw  # noqa: E402
from core import bundle_export  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def saved(key: str):
    return bundle_export.load_settings(mw.STATE).get(key)


window = mw.MainWindow()
window.show()
app.processEvents()

# --- placement: three tabs, and each setting on the page that owns it -------------
check("the mode row has a Settings tab", window.btn_tab_settings.text() == "Settings")
check("the stack has three pages", window.stack.count() == 3, str(window.stack.count()))
window._switch_tab("settings")
check("Settings opens its page", window.stack.currentIndex() == 2)
check("the Settings tab is the active one",
      window.btn_tab_settings.property("active") == "true"
      and window.btn_tab_auto.property("active") == "false")
check("the theme lives on Settings, not the Boundaries panel",
      window.page_settings.isAncestorOf(window.cmb_theme)
      and not window.page_prefs.isAncestorOf(window.cmb_theme))
check("the export folder and format live on Settings",
      window.page_settings.isAncestorOf(window.edit_save_root)
      and window.page_settings.isAncestorOf(window.combo_export_format))
check("the Settings rail lists four sections", window.settings_nav.count() == 4,
      str(window.settings_nav.count()))

# --- the export row shows the destination, elided, and links to Settings ----------
long_root = str(TEST_TMP / ("very_long_export_folder_name_" * 8))
window.save_root = long_root
window._refresh_export_summary()
shown = window.lbl_export_dest.text()
check("a long export path is elided in the export row",
      len(shown) < len(long_root) and "…" in shown, shown[:60])
check("the full export path is still in the tooltip",
      window.lbl_export_dest.toolTip() == long_root)
window.save_root = str(bundle_export.default_save_root())
window._refresh_export_summary()
window._switch_tab("auto", schedule=False)
window.findChild(QPushButton, "btn_change_export").click()
app.processEvents()
check("Change in Settings opens Settings on the Export section",
      window.stack.currentIndex() == 2 and window.settings_stack.currentIndex() == 1)

# --- the export folder is remembered when typed, not only when browsed ------------
typed = TEST_TMP / "typed_export"
window.edit_save_root.setText(str(typed))
window._on_save_root_edited()
check("a typed export folder is saved to settings",
      saved("save_root") == str(typed), str(saved("save_root")))
window.edit_save_root.setText("   ")
window._on_save_root_edited()
check("an empty export folder is refused and the working one comes back",
      window.edit_save_root.text() == str(typed) and window.save_root == str(typed))

# --- the export format shows what it writes, and is saved -------------------------
window.combo_export_format.setCurrentIndex(window._format_index(bundle_export.FORMAT_DICOM))
app.processEvents()
check("the format hint says what the chosen format writes",
      window.lbl_format_hint.text() == window._FORMAT_HINTS[bundle_export.FORMAT_DICOM])
check("the chosen format is saved", saved("export_format") == bundle_export.FORMAT_DICOM,
      str(saved("export_format")))
check("the export row shows the chosen format",
      window.lbl_export_format.text() == window.combo_export_format.currentText())
window.combo_export_format.setCurrentIndex(window._format_index(bundle_export.FORMAT_BOTH))

# --- the theme is chosen on Settings and saved ------------------------------------
window.cmb_theme.setCurrentIndex(window.cmb_theme.findData("light"))
app.processEvents()
check("the Settings theme switch applies", theme.mode() == "light")
check("the Settings theme switch is saved", saved("theme") == "light", str(saved("theme")))
window.cmb_theme.setCurrentIndex(window.cmb_theme.findData("dark"))
app.processEvents()

# --- checkpoints start in the folder used last ------------------------------------
ckpt_dir = TEST_TMP / "checkpoints_here"
ckpt_dir.mkdir(parents=True, exist_ok=True)
window._remember_checkpoint_dir(str(ckpt_dir))
check("the checkpoint folder is saved", saved("checkpoint_dir") == str(ckpt_dir))
check("the checkpoint folder is shown on Settings",
      window.lbl_checkpoint_dir.toolTip() == str(ckpt_dir))
reopened = mw.MainWindow()
check("a new window starts in the saved checkpoint folder",
      reopened.checkpoint_dir == str(ckpt_dir), reopened.checkpoint_dir)
reopened.close()

seen: dict = {}
original_open = QFileDialog.getOpenFileName


def _capture_start(*args, **kwargs):
    """Record the folder the dialog opens in; the user picks nothing."""
    seen["start"] = args[2]
    return ("", "")


QFileDialog.getOpenFileName = staticmethod(_capture_start)
try:
    window._open_load_checkpoint()
finally:
    QFileDialog.getOpenFileName = original_open
check("Open checkpoint starts in the checkpoint folder", seen.get("start") == str(ckpt_dir),
      str(seen.get("start")))

# --- shortcuts are listed, and each section opens from the rail -------------------
keys = {label.text() for label in window.page_settings.findChildren(QLabel)
        if label.property("role") == "key"}
check("the Shortcuts section lists Ctrl+S", "Ctrl+S" in keys, ", ".join(sorted(keys)))
window._open_settings("shortcuts")
check("the rail opens the Shortcuts section", window.settings_stack.currentIndex() == 3)
window._open_settings("appearance")
check("the rail opens the Appearance section", window.settings_stack.currentIndex() == 0)

window._switch_tab("auto", schedule=False)
window.close()

failures_text = "ALL PASS" if not failures else f"{len(failures)} FAIL"
print("RESULT: " + failures_text)
sys.exit(1 if failures else 0)
