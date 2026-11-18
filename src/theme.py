"""cleanCT visual system: a dark and a light palette, one stylesheet builder.

The scan canvases stay dark in both themes, so an image keeps its contrast
whatever the chrome around it looks like. Everything else follows the chosen
palette. Text colours reach WCAG AA contrast (4.5:1) on their ground; the test
in tests/test_theme.py checks every pair.

Use ``color(name)`` for a colour in the active theme. ``set_role`` gives a
widget a QSS role; ``apply(app)`` installs the palette and stylesheet.
"""
from __future__ import annotations

from string import Template

FONT_UI = '"Segoe UI", "Segoe UI Variable", sans-serif'
FONT_DISPLAY = '"Bahnschrift", "Segoe UI", sans-serif'
FONT_MONO = '"Cascadia Mono", "Consolas", monospace'

DARK = {
    "app": "#15181d",          # window ground
    "panel": "#1b1f25",        # sidebar, panels, lists
    "raised": "#232830",       # fields, hovered rows, segmented groups
    "canvas": "#0b0d10",       # scan canvases (both themes)
    "line": "#2b313a",         # hairline dividers
    "line_strong": "#3b4350",  # control borders
    "text": "#e8ebef",
    "text_2": "#aab2bd",       # secondary labels
    "text_3": "#8b94a2",       # hints and captions
    "accent": "#3fc6b6",       # cut lines, the primary action, the active state
    "accent_hover": "#5ad7c8",
    "on_accent": "#0a1714",
    "ok": "#7bd389",
    "warn": "#e9b44c",
    "error": "#ef7065",
    "info": "#8ab4f8",
}

LIGHT = {
    "app": "#f1f3f5",
    "panel": "#ffffff",
    "raised": "#e8ecf0",
    "canvas": "#0b0d10",
    "line": "#d6dce3",
    "line_strong": "#b8c1cc",
    "text": "#14181d",
    "text_2": "#465060",
    "text_3": "#5f6977",
    "accent": "#0a7266",
    "accent_hover": "#085d53",
    "on_accent": "#ffffff",
    "ok": "#1d7a3c",
    "warn": "#8f5e00",
    "error": "#b3261e",
    "info": "#1f5fbf",
}

MODES = ("dark", "light")
_mode = "dark"


def set_mode(mode: str) -> None:
    """Choose the active theme. Unknown names fall back to dark."""
    global _mode
    _mode = mode if mode in MODES else "dark"


def mode() -> str:
    return _mode


def color(name: str) -> str:
    """A colour token in the active theme, e.g. color("text")."""
    return (LIGHT if _mode == "light" else DARK)[name]


_QSS = Template("""
QMainWindow, QDialog { background: $app; color: $text; }
QWidget { color: $text; font-family: $font_ui; font-size: 13px; background: transparent; }
QWidget#main_area { background: $app; }
QToolTip { background: $raised; color: $text; border: 1px solid $line_strong;
           padding: 6px 8px; border-radius: 6px; font-size: 12px; }

/* surfaces: one level of framing, never a box inside a box */
QFrame#sidebar { background: $panel; border-right: 1px solid $line; }
QFrame.panel, QFrame#box_card, QFrame#box_lateral, QFrame#box_action_log,
QFrame#job_box, QFrame#kpi_bar, QFrame#empty_state {
    background: $panel; border: 1px solid $line; border-radius: 8px; }
QFrame#brand_card { background: transparent; border: none; }
QFrame#kpi_bar { background: transparent; border: none; }
QFrame#divider { background: $line; border: none; min-height: 1px; max-height: 1px; }

/* text roles */
QLabel[role="title"] { font-family: $font_display; font-size: 19px; font-weight: 600; color: $text; }
QLabel[role="section"] { font-size: 14px; font-weight: 600; color: $text; }
QLabel[role="secondary"], QLabel[role="label"] { color: $text_2; }
QLabel[role="label"] { font-size: 12px; }
QLabel[role="hint"] { color: $text_3; font-size: 12px; }
QLabel[role="compact"], QLabel[role="preset"] { font-size: 12px; color: $text_2; }
QLabel[role="accent"] { color: $accent; font-weight: 600; }
QLabel[role="info"], QLabel[role="chip-info"] { color: $info; font-size: 12px; }
QLabel[role="chip-ok"], QLabel[role="status-ok"] { color: $ok; font-size: 12px; }
QLabel[role="chip-warn"] { color: $warn; font-size: 12px; }
QLabel[role="status-error"] { color: $error; font-size: 12px; }
QLabel[role="kpi-title"], QLabel[role="kpi-muted"] { color: $text_3; font-size: 12px; }
QLabel[role="kpi-value"] { font-family: $font_display; font-size: 17px; font-weight: 600; color: $text; }
QLabel[role="kpi-ok"] { font-family: $font_display; font-size: 17px; font-weight: 600; color: $ok; }
QLabel[role="kpi-warn"] { font-family: $font_display; font-size: 17px; font-weight: 600; color: $warn; }
QLabel#range_summary { color: $text_2; font-size: 12px; }

/* buttons: secondary by default; primary is the one action of a region */
QPushButton { background: transparent; color: $text; border: 1px solid $line_strong;
              border-radius: 6px; padding: 6px 12px; min-height: 18px; }
QPushButton:hover { background: $raised; }
QPushButton:pressed { background: $line; }
QPushButton:disabled { color: $text_3; border-color: $line; background: transparent; }
QPushButton:focus { border-color: $accent; }
QPushButton[role="primary"], QPushButton#btn_process, QPushButton#btn_apply_prefs,
QPushButton#btn_load_confirm, QPushButton#btn_about_close {
    background: $accent; color: $on_accent; border: 1px solid $accent; font-weight: 600; }
QPushButton[role="primary"]:hover, QPushButton#btn_process:hover,
QPushButton#btn_apply_prefs:hover, QPushButton#btn_load_confirm:hover,
QPushButton#btn_about_close:hover { background: $accent_hover; }
QPushButton[role="primary"]:disabled, QPushButton#btn_process:disabled,
QPushButton#btn_apply_prefs:disabled, QPushButton#btn_load_confirm:disabled {
    background: $raised; color: $text_3; border-color: $line; }
QPushButton[role="ghost"], QPushButton[role="link"], QPushButton#btn_about,
QPushButton#btn_specimen_action, QPushButton#btn_th_reset {
    background: transparent; border: none; color: $text_2; padding: 6px 8px; }
QPushButton[role="ghost"]:hover, QPushButton[role="link"]:hover,
QPushButton#btn_specimen_action:hover, QPushButton#btn_th_reset:hover {
    color: $text; background: $raised; }
QPushButton[role="link"], QPushButton#btn_about { color: $accent; }
QPushButton[active="true"] { background: $accent; color: $on_accent;
                             border: 1px solid $accent; font-weight: 600; }
QPushButton[active="true"]:hover { background: $accent_hover; }

/* fields */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: $raised; color: $text; border: 1px solid $line; border-radius: 6px;
    padding: 5px 8px; selection-background-color: $accent; selection-color: $on_accent; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QComboBox:on { border-color: $accent; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: $text_3; }
QLineEdit#edit_search { background: $raised; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: $panel; color: $text; border: 1px solid $line_strong;
    selection-background-color: $accent; selection-color: $on_accent; outline: none; }
QTextEdit#log_view, QPlainTextEdit#log_view { font-family: $font_mono; font-size: 12px;
    color: $text_2; background: $app; border: 1px solid $line; border-radius: 6px; }

/* lists and menus */
QListWidget { background: transparent; border: none; outline: none; color: $text; }
QListWidget#sample_list { background: transparent; }
QListWidget::item { padding: 8px 10px; border-radius: 6px; color: $text; }
QListWidget::item:hover { background: $raised; }
QListWidget::item:selected { background: $raised; color: $text; }
QMenu { background: $panel; color: $text; border: 1px solid $line_strong;
        padding: 4px; border-radius: 6px; }
QMenu::item { padding: 6px 18px; border-radius: 4px; }
QMenu::item:selected { background: $raised; }
QMenu::item:disabled { color: $text_3; }
QMenu::separator { height: 1px; background: $line; margin: 4px 6px; }
QMessageBox { background: $panel; }
QMessageBox QLabel { color: $text; }

/* progress, sliders, scrollbars, checkboxes */
QProgressBar { background: $raised; border: none; border-radius: 3px; max-height: 6px;
               min-height: 6px; color: transparent; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }
QSlider::groove:horizontal { height: 4px; background: $line_strong; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { background: $text; width: 12px; height: 12px;
                             margin: -4px 0; border-radius: 6px; }
QSlider::handle:horizontal:hover { background: $accent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: $line_strong; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: $text_3; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: $line_strong; border-radius: 4px; min-width: 28px; }
QScrollBar::handle:horizontal:hover { background: $text_3; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QCheckBox { spacing: 8px; color: $text; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid $line_strong;
                       border-radius: 3px; background: $raised; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QScrollArea { background: transparent; border: none; }
QSplitter::handle { background: $line; }
""")


def qss() -> str:
    """The stylesheet for the active theme."""
    tokens = dict(LIGHT if _mode == "light" else DARK)
    tokens.update(font_ui=FONT_UI, font_display=FONT_DISPLAY, font_mono=FONT_MONO)
    return _QSS.substitute(tokens)


def palette():
    """Application palette from the active tokens, so dialogs and widgets that
    have no stylesheet rule still follow the theme (the Fusion style is used)."""
    from PySide6.QtGui import QColor, QPalette
    colours = {
        QPalette.Window: color("app"),
        QPalette.WindowText: color("text"),
        QPalette.Base: color("raised"),
        QPalette.AlternateBase: color("panel"),
        QPalette.Text: color("text"),
        QPalette.Button: color("raised"),
        QPalette.ButtonText: color("text"),
        QPalette.Highlight: color("accent"),
        QPalette.HighlightedText: color("on_accent"),
        QPalette.ToolTipBase: color("raised"),
        QPalette.ToolTipText: color("text"),
        QPalette.PlaceholderText: color("text_3"),
        QPalette.Link: color("accent"),
    }
    result = QPalette()
    for role, colour in colours.items():
        result.setColor(role, QColor(colour))
    return result


def apply(app) -> None:
    """Install the palette and stylesheet for the active theme on a QApplication."""
    app.setPalette(palette())
    app.setStyleSheet(qss())


def set_role(widget, role: str) -> None:
    """Give a widget a QSS role and re-apply the style (needed after a change)."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
