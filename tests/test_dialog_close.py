"""Dialog title bars keep their close (X) button, and each dialog closes on the X,
on Escape and on its own close button.

A mask like ``windowFlags() & ~Qt.WindowContextHelpButtonHint`` drops every high
window-flag bit in PySide6 (the close button is one of them), so the X vanished
from the About, Load and Properties dialogs.  The single-flag call keeps it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from dialogs.about_dialog import AboutDialog  # noqa: E402
from dialogs.load_dialog import LoadDialog  # noqa: E402
from dialogs.properties_dialog import SpecimenPropertiesDialog  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


app = QApplication.instance() or QApplication(sys.argv)


def make(kind: str):
    if kind == "about":
        return AboutDialog(None)
    if kind == "load":
        return LoadDialog(None)
    return SpecimenPropertiesDialog(None, {"name": "close-test", "slices": 10})


def close_action(dlg, how: str) -> bool:
    """Run one close path while exec() runs; True when exec() returned in time."""
    state = {"stuck": False}

    def fire():
        if how == "x":
            dlg.close()
        elif how == "escape":
            QTest.keyClick(dlg, Qt.Key_Escape)
        else:
            # the dialog's own dismiss button: Close, or Cancel where that is the one
            by_text = {b.text(): b for b in dlg.findChildren(QPushButton)}
            button = by_text.get("Close") or by_text.get("Cancel")
            if button is not None:
                button.click()
            else:
                dlg.reject()

    def guard():
        if dlg.isVisible():
            state["stuck"] = True
            dlg.reject()

    QTimer.singleShot(150, fire)
    QTimer.singleShot(2000, guard)
    dlg.exec()
    return not state["stuck"]


for kind in ("about", "load", "properties"):
    dlg = make(kind)
    flags = dlg.windowFlags()
    check(f"{kind}: title bar keeps the close (X) button",
          bool(flags & Qt.WindowCloseButtonHint), hex(int(flags)))
    check(f"{kind}: the help (?) button is removed",
          not bool(flags & Qt.WindowContextHelpButtonHint), hex(int(flags)))
    dlg.deleteLater()
    app.processEvents()

    for how, label in (("x", "X"), ("escape", "Escape"), ("button", "its close button")):
        dlg = make(kind)
        check(f"{kind}: closes on {label}", close_action(dlg, how))
        dlg.deleteLater()
        app.processEvents()

if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
