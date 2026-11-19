"""UI and pipeline probe for cleanCT (offscreen, Qt-native).

Qt Widgets has no DevTools protocol, so this probe drives the real MainWindow
with Qt's own event simulation (QTest), walks the widget tree, renders each
state at the sizes the window can really reach, and times the pipelines while
a heartbeat timer checks that the UI thread keeps answering.

Safety rails
- Output is unbuffered, and a faulthandler watchdog dumps every thread's stack
  if the run exceeds its time budget, so a stall shows where it is stuck.
- A guard timer closes any modal dialog or prompt that appears, and records
  its title and text. A prompt never blocks the run; each one is reported.

Run with the isolated environment the gate uses:
    CLEANCT_ENGINE, CLEANCT_DATA, CLEANCT_TEST_TMP_DIR, CLEANCT_OUTPUT_ROOT

    python tests/ui_probe.py              # full probe, writes report.json
    python tests/ui_probe.py --selftest   # planted defects must all be found
"""
from __future__ import annotations

import faulthandler
import html
import json
import os
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
for var in ("CLEANCT_ENGINE", "CLEANCT_DATA", "CLEANCT_TEST_TMP_DIR", "CLEANCT_OUTPUT_ROOT"):
    if not os.environ.get(var):
        raise SystemExit(f"Set {var} to an isolated folder first")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QAbstractButton, QCheckBox, QComboBox, QFrame, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QTextEdit, QWidget,
)

import theme  # noqa: E402
import capture_screens as cs  # noqa: E402  (reuses the synthetic writer and pump)
import main_window as mw  # noqa: E402
from core import custom_series as csx  # noqa: E402

OUT = ROOT / "tests" / "screenshots" / "probe"
SIZES = [(1540, 960), (1280, 800), (1920, 1080), (1024, 768), (1280, 720)]
TIME_BUDGET_S = int(os.environ.get("PROBE_TIMEOUT", "1500"))
ALLOW_CAPS = {
    "GPU", "CUDA", "CPU", "TIFF", "ROI", "HU", "CT", "XCT", "MB", "KB", "GB", "ID", "OK",
    "XY", "XZ", "YZ", "NII", "DCM", "PNG", "RTX", "SUPER", "API", "PDF", "JSON",
    "DICOM", "NIFTI", "KPI", "ESC", "RAW", "HDR", "SHA", "DPI", "NVIDIA",
}
# U+25A0 (a filled square) is the legend colour key, not an icon: checked for contrast
PICTO = re.compile("[\u2190-\u21FF\u2300-\u23FF\u25A1-\u25FF\u2600-\u27BF"
                   "\u2B00-\u2BFF\U0001F300-\U0001FAFF]")
LEAF_TYPES = (QLabel, QAbstractButton, QCheckBox, QComboBox, QLineEdit)
NAME_REQUIRED = ("QAbstractSpinBox", "QSlider", "QComboBox")

findings: list[dict] = []
stats: dict[str, object] = {"prompts": []}
STAGE = ["setup"]
_SEEN: dict[tuple, dict] = {}


def find(area: str, sev: str, where: str, what: str, evidence: str = "") -> None:
    """One entry per distinct problem. The same defect at four window sizes is
    one finding with a count, not four."""
    base = re.sub(r"^\[[^\]]*\] ", "", where)
    key = (sev, area, what, base, re.sub(r"\d+(\.\d+)?", "#", evidence)[:120])
    if key in _SEEN:
        _SEEN[key]["count"] += 1
        return
    entry = {"area": area, "sev": sev, "where": where, "what": what,
             "evidence": evidence, "stage": STAGE[0], "count": 1}
    _SEEN[key] = entry
    findings.append(entry)


def plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or ""))


def mnemonic_free(text: str) -> str:
    return re.sub(r"&(?!&)", "", text).replace("&&", "&")


def label_of(w: QWidget) -> str:
    if isinstance(w, QLabel):
        return plain(w.text())
    if isinstance(w, QAbstractButton):
        return mnemonic_free(w.text())
    if isinstance(w, QComboBox):
        return w.currentText()
    if isinstance(w, QLineEdit):
        return w.text() or w.placeholderText()
    return ""


def visible(root: QWidget) -> list[QWidget]:
    return [w for w in root.findChildren(QWidget)
            if w.isVisibleTo(root) and w.width() > 2 and w.height() > 2]


def text_need(w: QWidget) -> int:
    """Width the widget's own text needs; clipping means this exceeds the width."""
    if isinstance(w, QLabel) and not w.wordWrap():
        return w.fontMetrics().horizontalAdvance(plain(w.text())) + 2
    if isinstance(w, (QAbstractButton, QCheckBox, QComboBox)):
        return w.sizeHint().width()
    return 0


# --- static checks -------------------------------------------------------------

def check_text(vis: list[QWidget], tag: str) -> None:
    for w in vis:
        if isinstance(w, QTextEdit) or not isinstance(w, (QLabel, QAbstractButton, QCheckBox,
                                                           QComboBox, QLineEdit)):
            continue
        text = label_of(w)
        if not text.strip():
            continue
        where = f"{tag} {w.objectName() or type(w).__name__}"
        if re.fullmatch(r"[\s\u2014\u2013\-\u2022]*", text):
            continue                       # a dash placeholder for an empty value
        if "\u2014" in text:
            find("copy", "P3", where, "em dash in visible text", text[:80])
        if "\u00b7" in text:
            find("copy", "P3", where, "middle dot joins text fragments", text[:80])
        if PICTO.search(text):
            find("copy", "P2", where, "pictograph or arrow glyph in text", text[:80])
        if "\\" in text or "://" in text:
            continue                       # file paths are data, not copy
        for word in re.findall(r"\b[A-Z]{3,}\b", text):
            if word not in ALLOW_CAPS:
                find("copy", "P3", where, f"all-caps word '{word}'", text[:80])
                break


def check_clipping(vis: list[QWidget], tag: str) -> None:
    for w in vis:
        if not isinstance(w, (QLabel, QAbstractButton, QCheckBox, QComboBox)):
            continue
        need = text_need(w)
        if need and need > w.width() + 2:
            find("layout", "P1", f"{tag} {w.objectName() or type(w).__name__}",
                 "text clipped: the control is narrower than its text",
                 f"'{label_of(w)[:50]}' needs {need}px, has {w.width()}px")


def inside_scroll(w: QWidget) -> bool:
    anc = w.parentWidget()
    while anc is not None:
        if isinstance(anc, QScrollArea):
            return True
        anc = anc.parentWidget()
    return False


def check_outside_parent(vis: list[QWidget], tag: str) -> None:
    for w in vis:
        parent = w.parentWidget()
        if parent is None or inside_scroll(w):
            continue                       # scroll content is meant to overflow its viewport
        pr, wr = parent.rect(), w.geometry()
        if wr.right() > pr.right() + 2 or wr.bottom() > pr.bottom() + 2:
            find("layout", "P2", f"{tag} {w.objectName() or type(w).__name__}",
                 "control extends past its parent",
                 f"child {wr.width()}x{wr.height()} in parent {pr.width()}x{pr.height()}")


def check_overlap(vis: list[QWidget], tag: str) -> None:
    """Leaf controls must not overlap each other, in any panel."""
    leaves = [w for w in vis if isinstance(w, LEAF_TYPES)]
    rects = {id(w): QRectGlobal(w) for w in leaves}
    for i, a in enumerate(leaves):
        for b in leaves[i + 1:]:
            if a.isAncestorOf(b) or b.isAncestorOf(a):
                continue
            inter = rects[id(a)].intersected(rects[id(b)])
            if inter.width() > 4 and inter.height() > 4:
                find("layout", "P1", f"{tag} {a.objectName() or type(a).__name__}",
                     "two controls overlap",
                     f"'{label_of(a)[:30]}' and '{label_of(b)[:30]}' share "
                     f"{inter.width()}x{inter.height()}px")


def QRectGlobal(w: QWidget):
    from PySide6.QtCore import QRect
    top_left = w.mapToGlobal(w.rect().topLeft())
    return QRect(top_left, w.size())


def check_names_and_reasons(vis: list[QWidget], tag: str) -> None:
    from PySide6.QtWidgets import QAbstractSpinBox, QSlider
    for w in vis:
        if isinstance(w, QAbstractButton) and not w.text().strip():
            if not w.toolTip() and not w.accessibleName():
                find("a11y", "P1", f"{tag} {w.objectName() or 'button'}",
                     "icon-only control with no name or tooltip")
        if isinstance(w, QAbstractButton) and w.text().strip() and not w.isEnabled():
            if not w.toolTip():
                find("ux", "P2", f"{tag} {w.objectName() or mnemonic_free(w.text())}",
                     "disabled control gives no reason", mnemonic_free(w.text()))
        if isinstance(w, (QAbstractSpinBox, QSlider)) and not w.accessibleName():
            find("a11y", "P2", f"{tag} {w.objectName() or type(w).__name__}",
                 "input has no accessible name for screen readers",
                 f"{type(w).__name__} at {w.geometry().x()},{w.geometry().y()}")
        if isinstance(w, QLineEdit) and isinstance(w.parentWidget(), (QAbstractSpinBox,
                                                                       QComboBox)):
            continue                       # the internal editor of a spin box or combo
        if isinstance(w, QLineEdit) and not (
                w.toolTip() or w.accessibleName() or w.placeholderText()):
            find("a11y", "P2", f"{tag} {w.objectName() or type(w).__name__}",
                 "field has no name, placeholder or tooltip")


def check_scroll(vis: list[QWidget], root: QWidget, tag: str) -> None:
    for area in root.findChildren(QScrollArea):
        if not area.isVisibleTo(root):
            continue
        bar = area.horizontalScrollBar()
        if bar.maximum() > 0:
            # below 1280 px the page scrolls sideways: works, but is outside the
            # supported width, so it is graded P2; at 1280 px and up it is P1
            sev = "P1" if root.width() >= 1280 else "P2"
            find("responsive", sev, f"{tag} {area.objectName() or 'page'}",
                 "page needs sideways scroll at this window size",
                 f"content {area.widget().width()}px in a {area.viewport().width()}px viewport")


def check_inline_contrast(vis: list[QWidget], tag: str) -> None:
    """A colour key (a filled square) needs 3:1 against the canvas it sits on
    (WCAG 1.4.11); coloured text needs 4.5:1 against the panel (1.4.3)."""
    for w in vis:
        if not (isinstance(w, QLabel) and "<span" in w.text()):
            continue
        for match in re.finditer(r"<span style='([^']*)'>([^<]*)<", w.text()):
            style, run = match.group(1), match.group(2)
            colour = re.search(r"(?<![-\w])color:(#[0-9a-fA-F]{6})", style)
            if not colour:
                continue
            color = colour.group(1)
            chip = re.search(r"background-color:(#[0-9a-fA-F]{6})", style)
            if "\u25a0" in run:
                ratio = _contrast(color, chip.group(1) if chip else theme.color("panel"))
                if ratio < 3.0:
                    find("theme", "P2", f"{tag} {w.objectName() or 'label'}",
                         "colour key below 3:1 on the canvas it marks", f"{color} {ratio:.2f}:1")
            else:
                ratio = _contrast(color, theme.color("panel"))
                if ratio < 4.5:
                    find("theme", "P2", f"{tag} {w.objectName() or 'label'}",
                         "coloured text below 4.5:1 on the panel", f"{color} {ratio:.2f}:1")


def _lum(hex_colour: str) -> float:
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def run_static_checks(root: QWidget, tag: str) -> None:
    QApplication.processEvents()
    vis = visible(root)
    check_text(vis, tag)
    check_clipping(vis, tag)
    check_outside_parent(vis, tag)
    check_overlap(vis, tag)
    check_names_and_reasons(vis, tag)
    check_scroll(vis, root, tag)
    check_inline_contrast(vis, tag)


# --- keyboard and interaction --------------------------------------------------

def tab_order(window: QWidget) -> tuple[list[str], list[str], int]:
    """Press Tab until focus returns to the start. Returns the names reached, the
    enabled focusable controls Tab never reached, and the number of focusable
    controls found (a sanity count: zero means the probe measured nothing)."""
    window.activateWindow()
    window.setFocus()
    QApplication.processEvents()
    reached: list[str] = []
    for _ in range(400):
        QTest.keyClick(window, Qt.Key_Tab)
        QApplication.processEvents()
        focus = QApplication.focusWidget()
        if focus is None:
            break
        name = focus.objectName() or type(focus).__name__
        if reached and reached[0] == name:
            break
        reached.append(name)
    focusable = [w for w in visible(window)
                 if w.isEnabled() and w.focusPolicy() != Qt.NoFocus
                 and isinstance(w, (QAbstractButton, QLineEdit, QComboBox, QCheckBox))]
    names = {w.objectName() or type(w).__name__ for w in focusable}
    missed = sorted(n for n in names if n not in reached)
    return reached, missed, len(focusable)


def install_prompt_guard(app) -> QTimer:
    """Close any modal prompt that appears, and record what it said."""
    guard = QTimer()

    def sweep():
        modal = QApplication.activeModalWidget()
        if modal is None:
            return
        title = modal.windowTitle()
        text = modal.text() if isinstance(modal, QMessageBox) else ""
        stats["prompts"].append({"stage": STAGE[0], "title": title, "text": text[:400]})
        modal.close()

    guard.timeout.connect(sweep)
    guard.start(60)
    return guard


def probe_interactions(window: QWidget, app) -> None:
    STAGE[0] = "interaction"
    window.activateWindow()
    actions = {
        "tab switch to Boundaries": lambda: window.btn_tab_prefs.click(),
        "tab switch back to Auto": lambda: window.btn_tab_auto.click(),
        "tab switch to Settings": lambda: window.btn_tab_settings.click(),
        "settings nav: Export": lambda: window.settings_nav.setCurrentRow(1),
        "settings nav: Shortcuts": lambda: window.settings_nav.setCurrentRow(3),
        "tab switch back to Auto from Settings": lambda: window.btn_tab_auto.click(),
        "activity drawer open": lambda: window.btn_log_toggle.click(),
        "activity drawer close": lambda: window.btn_log_toggle.click(),
        "clear activity": lambda: window._clear_log(),
        "about dialog": lambda: window._open_about_dialog(),
        "load dialog": lambda: window._open_load_dialog(),
    }
    for name, action in actions.items():
        STAGE[0] = f"interaction: {name}"
        try:
            action()
            QApplication.processEvents()
        except Exception as exc:       # noqa: BLE001 - a crash is a finding
            find("interaction", "P0", name, "action raised an exception",
                 f"{type(exc).__name__}: {exc}")
    STAGE[0] = "interaction: theme"
    for index in (1, 0):
        window.cmb_theme.setCurrentIndex(index)
        QApplication.processEvents()
    if theme.mode() != "dark":
        find("interaction", "P1", "theme switch", "switching back to dark did not apply")
    STAGE[0] = "interaction: shortcuts"
    for seq in ("Ctrl+O", "Ctrl+R", "Ctrl+E", "Ctrl+S"):
        QTest.keySequence(window, seq)
        QApplication.processEvents()
    STAGE[0] = "interaction: keyboard"
    # the sidebar is locked while a load or job runs: walk the Tab order once idle
    cs.pump(app, lambda: not window._loading and window._active_worker is None, 240)
    reached, missed, focusable = tab_order(window)
    stats["keyboard_reached"] = len(reached)
    stats["keyboard_focusable"] = focusable
    if focusable == 0:
        find("a11y", "P0", "keyboard", "no focusable controls found: the probe measured nothing")
    if missed:
        find("a11y", "P2", "keyboard", "controls Tab never reaches", ", ".join(missed[:20]))


# Controls that change data or start work: clicked only by the pipeline stages.
NO_CLICK = {"btn_remove", "btn_process", "btn_process_export", "btn_export",
            "btn_rename", "btn_duplicate", "btn_locate", "btn_empty_load"}


def probe_every_click(window: QWidget, app) -> None:
    """Click every visible, enabled button and checkbox on each page, in both
    themes. A click that raises, or opens a prompt nobody expected, is a finding."""
    from PySide6.QtWidgets import QAbstractButton
    STAGE[0] = "every click"
    clicked = 0
    # every settings section is a view of its own: a hidden section's buttons
    # are not visible, so they would be skipped without this
    views = [("auto", None), ("prefs", None)] + [("settings", row) for row in range(4)]
    for theme_name in ("light", "dark"):
        window.cmb_theme.setCurrentIndex(window.cmb_theme.findData(theme_name))
        for tab, row in views:
            window._switch_tab(tab, schedule=False)
            if row is not None:
                window.settings_nav.setCurrentRow(row)
            tab = tab if row is None else f"settings {row}"
            QApplication.processEvents()
            names = []
            for btn in window.findChildren(QAbstractButton):
                if btn.isVisible() and btn.isEnabled():
                    names.append(btn.objectName() or btn.text() or type(btn).__name__)
            for btn in list(window.findChildren(QAbstractButton)):
                key = btn.objectName() or btn.text() or type(btn).__name__
                if key not in names or key in NO_CLICK or not btn.isVisible() or not btn.isEnabled():
                    continue
                STAGE[0] = f"click: {key} [{theme_name} {tab}]"
                try:
                    btn.click()
                    QApplication.processEvents()
                    clicked += 1
                except Exception as exc:      # noqa: BLE001 - a crash is a finding
                    find("interaction", "P0", key, "click raised an exception",
                         f"{type(exc).__name__}: {exc}")
    stats["clicks"] = clicked
    window.cmb_theme.setCurrentIndex(window.cmb_theme.findData("dark"))
    window._switch_tab("auto", schedule=False)
    QApplication.processEvents()


def probe_dialogs(app) -> None:
    """Open each dialog in both themes and run the same static checks as the
    windows: a dialog that paints the wrong ground or unreadable text is a finding."""
    from dialogs.about_dialog import AboutDialog
    from dialogs.load_dialog import LoadDialog
    STAGE[0] = "dialogs"
    for theme_name in ("light", "dark"):
        theme.set_mode(theme_name)
        theme.apply(app)
        for factory in (LoadDialog, AboutDialog):
            STAGE[0] = f"dialog: {factory.__name__} [{theme_name}]"
            dialog = factory()
            dialog.show()
            QApplication.processEvents()
            run_static_checks(dialog, f"[dialog {factory.__name__} {theme_name}]")
            dialog.close()
    theme.set_mode("dark")
    theme.apply(app)


def probe_sizes(window: QWidget, app, shots: bool) -> None:
    STAGE[0] = "layout"
    for theme_name in ("dark", "light"):
        # switch through the Appearance control, as a user does: the window's own
        # handler must update every colour that is built into the widgets
        window.cmb_theme.setCurrentIndex(window.cmb_theme.findData(theme_name))
        QApplication.processEvents()
        for tab in ("auto", "prefs", "settings"):
            window._switch_tab(tab, schedule=False)
            for w, h in SIZES:
                window.resize(w, h)
                # a resize lays out over more than one event pass: settle before measuring
                for _ in range(4):
                    QApplication.processEvents()
                tag = f"[{theme_name} {tab} {window.width()}x{window.height()}]"
                if (window.width(), window.height()) != (w, h):
                    stats.setdefault("clamped", []).append(
                        f"requested {w}x{h}, window is {window.width()}x{window.height()}")
                run_static_checks(window, tag)
                # every page must fit its window: a scroll bar means hidden controls
                for area in window.findChildren(QScrollArea):
                    if area.isVisible() and area.verticalScrollBar().maximum() > 0:
                        find("layout", "P2", tag, "page needs a vertical scroll bar",
                             area.objectName() or type(area.widget()).__name__)
                if shots and (w, h) in ((1540, 960), (1280, 800)):
                    OUT.mkdir(parents=True, exist_ok=True)
                    window.grab().save(str(OUT / f"{theme_name}_{tab}_{window.width()}x"
                                              f"{window.height()}.png"), "PNG")
    window.cmb_theme.setCurrentIndex(window.cmb_theme.findData("dark"))
    window._switch_tab("auto", schedule=False)
    window.resize(1540, 960)
    QApplication.processEvents()


# --- pipelines -----------------------------------------------------------------

def write_realistic_scan(folder: Path, name: str) -> Path:
    """A 384 px, 60-slice scan at 66 um: processes with the app's default settings
    in about two seconds. (A 96 px scan cannot pass the default seed thresholds.)"""
    src = folder / name
    cs.write_wood_metal_series(src / "XY", n=60, rows=384, cols=384, um=0.066)
    return src


def run_job(window: QWidget, app, name: str, start, limit: float, gaps: list) -> None:
    STAGE[0] = f"pipeline: {name}"
    gaps.clear()
    begin = time.monotonic()
    start()
    QApplication.processEvents()
    started = cs.pump(app, lambda: window._active_worker is not None, 5)
    done = cs.pump(app, lambda: window._active_worker is None and started, limit)
    elapsed = time.monotonic() - begin
    stall = max(gaps) if gaps else 0.0
    stats[f"{name}_seconds"] = round(elapsed, 2)
    stats[f"{name}_max_stall_ms"] = round(stall * 1000)
    if not started:
        find("pipeline", "P1", name, "the job never started")
    if not done:
        find("pipeline", "P0", name, "job did not finish in time", f"{limit}s")
    if stall > 0.25:
        find("responsive", "P1", name, "the window stopped answering while the job ran",
             f"longest gap {stall * 1000:.0f} ms")


def probe_pipeline(window: QWidget, app, beat_gaps: list) -> None:
    tmp = Path(os.environ["CLEANCT_TEST_TMP_DIR"])
    STAGE[0] = "pipeline: load"
    src = write_realistic_scan(tmp, "probe_src")
    csx.register_series(src, "probe_specimen")
    window._select_sample("custom", "probe_specimen")
    t0 = time.monotonic()
    loaded = cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)
    stats["load_seconds"] = round(time.monotonic() - t0, 2)
    if not loaded:
        find("pipeline", "P0", "load", "scan never finished loading")
        return
    if not window.btn_process.isEnabled():
        find("pipeline", "P1", "process", "Process stays disabled after a load")
    else:
        run_job(window, app, "process", window._process_selected, 300, beat_gaps)
    export_dir = tmp / "probe_export"
    window.edit_save_root.setText(str(export_dir))
    window.edit_save_root.editingFinished.emit()
    # the Export gate is applied a moment after the worker ends: wait for it
    cs.pump(app, lambda: window.btn_export.isEnabled(), 5)
    if window.btn_export.isEnabled():
        run_job(window, app, "export", window._export_bundle, 300, beat_gaps)
        bundle = export_dir / "probe_specimen"
        stats["bundle_files"] = sorted(p.name for p in bundle.glob("*")) if bundle.exists() else []
        if not stats["bundle_files"]:
            find("pipeline", "P1", "export", "no bundle written to the export folder")
    else:
        find("pipeline", "P2", "export", "Export stays disabled after processing")

    STAGE[0] = "pipeline: checkpoint"
    ckpt = tmp / "probe.cleanct.json"
    try:
        window.save_checkpoint_file(ckpt)
        QApplication.processEvents()
        window.load_checkpoint_file(ckpt)
        QApplication.processEvents()
        if window.sample != "probe_specimen":
            find("pipeline", "P1", "checkpoint", "restore did not select the saved specimen",
                 f"window shows '{window.sample}'")
    except Exception as exc:       # noqa: BLE001
        find("pipeline", "P1", "checkpoint", "save or restore raised",
             f"{type(exc).__name__}: {exc}")


def probe_bad_scan(app) -> None:
    """Negative path: a scan the pipeline cannot process must fail in plain words."""
    STAGE[0] = "pipeline: bad scan"
    tmp = Path(os.environ["CLEANCT_TEST_TMP_DIR"])
    src = tmp / "bad_src"
    cs.write_wood_metal_series(src / "XY", n=36, rows=96, cols=96, um=0.033)
    csx.register_series(src, "bad_scan")
    window = mw.MainWindow()
    window.show()
    window._select_sample("custom", "bad_scan")
    cs.pump(app, lambda: (not window._loading) and window.payload is not None, 240)
    before = len(stats["prompts"])
    window._process_selected()
    cs.pump(app, lambda: window._active_worker is None, 120)
    shown = [p for p in stats["prompts"][before:] if "Error" in p["title"] or "rror" in p["text"]]
    if not shown:
        find("pipeline", "P2", "bad scan", "a failing scan showed no error prompt")
    else:
        text = shown[0]["text"]
        stats["bad_scan_error"] = text[:300]
        # the plain sentence is what the user reads; "Details" keeps the raw text
        plain_part = text.split("\n\nDetails:")[0]
        if not text.count("\n\nDetails:"):
            find("copy", "P2", "processing error", "no separate details line for support")
        if re.search(r"\b(seed|fogged|border-locked|pipeline|inspect the scan)\b", plain_part):
            find("copy", "P2", "processing error",
                 "the error uses internal terms and gives no next step", plain_part[:200])
    window.close()


# --- self-test -----------------------------------------------------------------

def planted_scene() -> tuple[QWidget, dict[str, str]]:
    """A small scene with one known defect of each kind. The probe must find
    every one of them, and the clean control must stay clean."""
    from PySide6.QtWidgets import QHBoxLayout
    root = QWidget()
    root.resize(600, 300)
    row = QHBoxLayout(root)
    clipped = QPushButton("A button whose label is far too long for its width")
    clipped.setFixedWidth(60)
    row.addWidget(clipped)
    em = QLabel("Cut slice \u2014 value")
    row.addWidget(em)
    a, b = QPushButton("Overlap A"), QPushButton("Overlap B")
    a.setParent(root)
    b.setParent(root)
    a.setGeometry(10, 120, 120, 30)
    b.setGeometry(60, 120, 120, 30)
    icon_only = QPushButton("")
    row.addWidget(icon_only)
    disabled = QPushButton("Process selected")
    disabled.setEnabled(False)
    row.addWidget(disabled)
    scroll = QScrollArea(root)
    scroll.setGeometry(10, 170, 200, 60)
    wide = QWidget()
    wide.setMinimumWidth(600)
    scroll.setWidget(wide)
    outside = QLabel("outside", root)
    outside.setGeometry(560, 260, 80, 30)
    clean = QPushButton("Save")
    clean.setObjectName("clean_control")
    clean.setToolTip("Save the checkpoint")
    row.addWidget(clean)
    root.show()
    QApplication.processEvents()
    expected = {
        "clipped button": "text clipped",
        "em dash": "em dash",
        "overlap": "overlap",
        "icon-only": "icon-only",
        "disabled no reason": "disabled control gives no reason",
        "sideways scroll": "sideways scroll",
        "outside parent": "extends past its parent",
    }
    return root, expected


def selftest(app) -> int:
    saved = list(findings)
    findings.clear()
    scene, expected = planted_scene()
    run_static_checks(scene, "[selftest]")
    got = [f["what"] for f in findings]
    failed = []
    for label, needle in expected.items():
        hit = any(needle in g for g in got)
        print(("PASS " if hit else "MISS ") + f"planted {label}")
        if not hit:
            failed.append(label)
    clean_only = [f for f in findings if "clean_control" in f["where"]]
    print(("PASS " if not clean_only else "FAIL ") + "clean control stays clean")
    if clean_only:
        failed.append("clean control")
    findings[:] = saved
    scene.close()
    print("SELFTEST: " + ("PASS" if not failed else f"FAIL ({', '.join(failed)})"))
    return 0 if not failed else 1


def main() -> int:
    faulthandler.dump_traceback_later(TIME_BUDGET_S, exit=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("cleanCT")
    theme.apply(app)
    if "--selftest" in sys.argv:
        return selftest(app)

    guard = install_prompt_guard(app)
    window = mw.MainWindow()
    window.center_on_screen()
    window.show()
    QApplication.processEvents()
    STAGE[0] = "setup: gpu"
    gpu_ready = cs.pump(app, lambda: window.lbl_gpu.text() != "Checking GPU…", 90)
    stats["gpu_chip"] = window.lbl_gpu.text()
    stats["gpu_settled"] = bool(gpu_ready)

    probe_sizes(window, app, shots=True)                  # landing state
    probe_interactions(window, app)
    probe_every_click(window, app)
    probe_dialogs(app)
    gaps: list[float] = []
    last = [time.monotonic()]
    beat = QTimer()

    def tick():
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now

    beat.timeout.connect(tick)
    beat.start(10)
    probe_pipeline(window, app, gaps)
    beat.stop()
    stats["gui_gap_max_ms"] = round(max(gaps) * 1000) if gaps else 0
    probe_sizes(window, app, shots=True)                  # loaded state
    window.close()
    probe_bad_scan(app)
    guard.stop()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(
        json.dumps({"stats": stats, "findings": findings}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    by_sev: dict[str, int] = {}
    for f in findings:
        by_sev[f["sev"]] = by_sev.get(f["sev"], 0) + 1
    print("stats:", json.dumps({k: v for k, v in stats.items() if k != "prompts"},
                               ensure_ascii=False))
    print(f"prompts closed by the guard: {len(stats['prompts'])}")
    for p in stats["prompts"]:
        print(f"  prompt [{p['stage']}] {p['title']}: {p['text'][:160]}")
    print("findings:", by_sev or "none")
    for f in findings:
        times = f"  (x{f['count']})" if f["count"] > 1 else ""
        print(f"  {f['sev']} [{f['area']}] {f['where']}: {f['what']} | {f['evidence']}{times}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
