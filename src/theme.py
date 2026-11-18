"""Dark graphite luxury theme and stylesheet for cleanCT native desktop application."""
from __future__ import annotations

# Palette
BG_DARK = "#0d1017"
BG_MAIN = "#12151b"
BG_PANEL = "#171b26"
BG_PANEL2 = "#1e2433"
BORDER = "#2b3447"
BORDER_LIGHT = "#3d4963"

TEXT_PRIMARY = "#f0f4fc"
TEXT_SECONDARY = "#9daabf"
TEXT_MUTED = "#7d8aa0"     # hints only (4.9:1 on BG_PANEL, WCAG AA)
TEXT_LABEL = "#c0cbe0"

ACCENT_AMBER = "#f2b23c"
ACCENT_AMBER_HOVER = "#ffc55a"
ACCENT_BLUE = "#4f8cff"
ACCENT_BLUE_HOVER = "#70a2ff"
ACCENT_GREEN = "#37d67a"
ACCENT_RED = "#ff463c"
INFO = "#82b1ff"
BG_SUNKEN = "#10131b"
BG_JOB = "#141822"

QSS = f"""
QMainWindow, QDialog {{
    background-color: {BG_MAIN};
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", -apple-system, sans-serif;
}}

QWidget {{
    background-color: transparent;
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}

QToolTip {{
    background-color: {BG_PANEL2};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_LIGHT};
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 12px;
}}

/* Sidebar & Panels */
QFrame#sidebar {{
    background-color: {BG_PANEL};
    border-right: 1px solid {BORDER};
}}

QFrame.panel {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

QFrame#kpi_bar {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px 14px;
}}

/* Tactile Buttons */
QPushButton {{
    background-color: {BG_PANEL2};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 15px;
    font-weight: 600;
    font-size: 12px;
}}

QPushButton:hover {{
    background-color: #262e40;
    border-color: {BORDER_LIGHT};
    color: #ffffff;
}}

QPushButton:pressed {{
    background-color: #171c26;
    border-color: {BORDER};
}}

QPushButton:disabled {{
    background-color: #141720;
    color: {TEXT_MUTED};
    border-color: #202636;
}}

/* Primary Amber Action Button */
QPushButton#btn_process, QPushButton#btn_apply_prefs, QPushButton#btn_load_confirm, QPushButton#btn_about_close {{
    background-color: {ACCENT_AMBER};
    color: #151106;
    border: 1px solid {ACCENT_AMBER};
    font-weight: 700;
}}

QPushButton#btn_process:hover, QPushButton#btn_apply_prefs:hover, QPushButton#btn_load_confirm:hover, QPushButton#btn_about_close:hover {{
    background-color: {ACCENT_AMBER_HOVER};
    border-color: {ACCENT_AMBER_HOVER};
}}

QPushButton#btn_process:disabled, QPushButton#btn_apply_prefs:disabled, QPushButton#btn_load_confirm:disabled {{
    background-color: #3b301c;
    color: #826e49;
    border-color: #3b301c;
}}

/* Active Segmented Pill Toggles */
QPushButton[active="true"] {{
    background-color: {ACCENT_AMBER};
    color: #151106;
    border: 1px solid {ACCENT_AMBER};
    font-weight: 700;
}}

QPushButton[active="true"]:hover {{
    background-color: {ACCENT_AMBER_HOVER};
    border-color: {ACCENT_AMBER_HOVER};
}}

QPushButton[active="false"] {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    font-weight: 500;
}}

QPushButton[active="false"]:hover {{
    background-color: {BG_PANEL2};
    border-color: {BORDER_LIGHT};
    color: {TEXT_PRIMARY};
}}

/* Turntable Spin Active Animation Style */
QPushButton#btn_spin3d[spinning="true"] {{
    background-color: rgba(242, 178, 60, 0.22);
    border: 1px solid {ACCENT_AMBER};
    color: {ACCENT_AMBER};
    font-weight: 700;
}}

/* Input Fields & Spinboxes */
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_PANEL2};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 12px;
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT_BLUE};
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 6px;
    background: #141822;
    border-radius: 3px;
}}

QSlider::sub-page:horizontal {{
    background: {ACCENT_AMBER};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background: #ffffff;
    border: 2px solid {ACCENT_AMBER};
    width: 14px;
    margin-top: -4px;
    margin-bottom: -4px;
    border-radius: 7px;
}}

QSlider::handle:horizontal:hover {{
    background: {ACCENT_AMBER_HOVER};
    width: 16px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 8px;
}}

/* Checkboxes */
QCheckBox {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
    font-weight: 600;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid {BORDER};
    background-color: {BG_PANEL2};
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT_AMBER};
    border-color: {ACCENT_AMBER};
}}

/* Sample List & Tree */
QListWidget {{
    background-color: transparent;
    border: none;
    outline: none;
}}

QListWidget#sample_list::item {{
    padding: 0px;
    margin: 1px 2px;
}}

QListWidget::item {{
    padding: 7px 10px;
    border-radius: 8px;
    color: {TEXT_SECONDARY};
    margin: 1px 4px;
}}

QListWidget::item:hover {{
    background-color: rgba(255, 255, 255, 0.05);
    color: {TEXT_PRIMARY};
}}

QListWidget::item:selected {{
    background-color: rgba(242, 178, 60, 0.16);
    color: {ACCENT_AMBER};
    font-weight: 700;
    border: 1px solid rgba(242, 178, 60, 0.35);
}}

/* Specimen panel: filter box + compact row actions */
QLineEdit#edit_search {{
    background-color: {BG_PANEL2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px 8px;
    font-size: 11px;
}}

QLineEdit#edit_search:focus {{
    border-color: {ACCENT_BLUE};
}}

QLineEdit#edit_search:disabled {{
    color: {TEXT_MUTED};
    border-color: #202636;
}}

QPushButton#btn_specimen_action {{
    background-color: {BG_PANEL2};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px 2px;
    font-weight: 600;
    font-size: 10px;
}}

QPushButton#btn_specimen_action:hover {{
    background-color: #262e40;
    border-color: {BORDER_LIGHT};
    color: {TEXT_PRIMARY};
}}

QPushButton#btn_specimen_action:pressed {{
    background-color: #171c26;
}}

QPushButton#btn_specimen_action:disabled {{
    background-color: #141720;
    color: {TEXT_MUTED};
    border-color: #202636;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background: #2a3345;
    min-height: 24px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: #3c4860;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0px;
}}

QScrollBar::handle:horizontal {{
    background: #2a3345;
    min-width: 24px;
    border-radius: 4px;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* Progress Bar */
QProgressBar {{
    background-color: #12151c;
    border: 1px solid {BORDER};
    border-radius: 5px;
    text-align: center;
    color: {TEXT_PRIMARY};
    font-size: 10px;
    height: 10px;
}}

QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_BLUE}, stop:1 {ACCENT_AMBER});
    border-radius: 4px;
}}

/* Roles: text colours and frames that used to be set inline per widget.
   Set with theme.set_role(widget, "hint") and similar. */
QLabel[role="hint"] {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 500;
}}
QLabel[role="primary"] {{
    color: {TEXT_PRIMARY};
    font-size: 12px;
    font-weight: 500;
}}
QLabel[role="secondary"] {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
    font-weight: 500;
}}
QLabel[role="label"] {{
    color: {TEXT_LABEL};
    font-size: 12px;
    font-weight: 500;
}}
QLabel[role="accent"] {{
    color: {ACCENT_AMBER};
    font-size: 12px;
    font-weight: 700;
}}
QLabel[role="title"] {{
    color: {TEXT_PRIMARY};
    font-size: 16px;
    font-weight: 700;
}}
QLabel[role="kpi-title"] {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 700;
}}
QLabel[role="kpi-value"] {{
    color: {TEXT_PRIMARY};
    font-size: 15px;
    font-weight: 700;
}}
QLabel[role="kpi-ok"] {{
    color: {ACCENT_GREEN};
    font-size: 15px;
    font-weight: 700;
}}
QLabel[role="kpi-warn"] {{
    color: {ACCENT_AMBER};
    font-size: 15px;
    font-weight: 700;
}}
QLabel[role="kpi-muted"] {{
    color: {TEXT_MUTED};
    font-size: 15px;
    font-weight: 700;
}}
QLabel[role="section"] {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
    font-weight: 700;
}}
QLabel[role="info"] {{
    color: {INFO};
    font-size: 12px;
    font-weight: 600;
}}
QLabel[role="status-ok"] {{
    color: {ACCENT_GREEN};
    font-size: 12px;
    font-weight: 600;
}}
QLabel[role="status-warn"] {{
    color: {ACCENT_AMBER};
    font-size: 12px;
    font-weight: 600;
}}
QLabel[role="status-error"] {{
    color: {ACCENT_RED};
    font-size: 12px;
    font-weight: 700;
}}
QWidget#main_area {{
    background-color: {BG_MAIN};
}}
QFrame#brand_card {{
    background-color: transparent;
    border-bottom: 1px solid {BORDER};
    padding-bottom: 12px;
    margin-bottom: 2px;
}}
QFrame#box_card, QFrame#box_action_log {{
    background-color: {BG_JOB};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 10px;
}}
QFrame#box_action_log {{
    background-color: {BG_SUNKEN};
    padding: 6px;
}}
QFrame#box_lateral {{
    background-color: rgba(79, 140, 255, 0.08);
    border: 1px solid rgba(79, 140, 255, 0.35);
    border-radius: 8px;
    padding: 8px;
}}
QFrame#empty_state {{
    background-color: {BG_JOB};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#divider {{
    background-color: {BORDER};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}
QLabel#range_summary {{
    border-top: 1px dashed {BORDER};
    padding-top: 8px;
}}
QLabel#app_icon {{
    padding: 4px;
    border-radius: 26px;
}}
QLabel[role="chip-info"] {{
    background: rgba(79, 140, 255, 0.12);
    color: {INFO};
    border: 1px solid rgba(79, 140, 255, 0.3);
    border-radius: 12px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 500;
}}
QLabel[role="chip-ok"] {{
    background: rgba(55, 214, 122, 0.12);
    color: {ACCENT_GREEN};
    border: 1px solid rgba(55, 214, 122, 0.35);
    border-radius: 12px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel[role="chip-warn"] {{
    background: rgba(255, 176, 32, 0.12);
    color: {ACCENT_AMBER};
    border: 1px solid rgba(255, 176, 32, 0.35);
    border-radius: 12px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton[role="link"] {{
    background: transparent;
    border: none;
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 500;
    padding: 1px 5px;
}}
QPushButton[role="preset"] {{
    font-size: 11px;
    padding: 2px 6px;
}}
QPushButton#btn_th_reset {{
    background-color: #242c3d;
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 5px;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 6px;
}}
QPushButton#btn_th_reset[active="true"] {{
    background-color: rgba(242, 178, 60, 0.16);
    border: 1px solid {ACCENT_AMBER};
    color: {ACCENT_AMBER};
}}
QPushButton#btn_th_reset:hover {{
    background-color: #2e384d;
    border-color: {ACCENT_BLUE};
    color: #ffffff;
}}
QFrame#job_box {{
    background-color: {BG_JOB};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 10px;
}}
QTextEdit#log_view {{
    background-color: {BG_SUNKEN};
    color: {TEXT_LABEL};
    border: none;
    border-radius: 8px;
    padding: 6px;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 11px;
}}

/* Combo boxes, menus, message boxes and scroll areas were unstyled: they
   showed black boxes with white borders on the dark theme. */
QComboBox {{
    background-color: {BG_PANEL2};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 12px;
    min-height: 22px;
}}
QComboBox:focus, QComboBox:on {{
    border-color: {ACCENT_BLUE};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL2};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_LIGHT};
    selection-background-color: rgba(242, 178, 60, 0.22);
    selection-color: {ACCENT_AMBER};
    outline: none;
}}
QMenu {{
    background-color: {BG_PANEL2};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: rgba(242, 178, 60, 0.16);
    color: {ACCENT_AMBER};
}}
QMenu::item:disabled {{
    color: {TEXT_MUTED};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}
QMessageBox {{
    background-color: {BG_PANEL};
}}
QMessageBox QLabel {{
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
"""


def palette():
    """Application palette from the tokens, so dialogs and widgets without QSS
    still follow the dark theme (the Fusion style is used with it)."""
    from PySide6.QtGui import QColor, QPalette
    colours = {
        QPalette.Window: BG_MAIN,
        QPalette.WindowText: TEXT_PRIMARY,
        QPalette.Base: BG_PANEL2,
        QPalette.AlternateBase: BG_PANEL,
        QPalette.Text: TEXT_PRIMARY,
        QPalette.Button: BG_PANEL2,
        QPalette.ButtonText: TEXT_PRIMARY,
        QPalette.Highlight: ACCENT_AMBER,
        QPalette.HighlightedText: "#151106",
        QPalette.ToolTipBase: BG_PANEL2,
        QPalette.ToolTipText: TEXT_PRIMARY,
        QPalette.PlaceholderText: TEXT_MUTED,
        QPalette.Link: ACCENT_BLUE,
    }
    result = QPalette()
    for role, colour in colours.items():
        result.setColor(role, QColor(colour))
    return result


def set_role(widget, role: str) -> None:
    """Give a widget a QSS role and re-apply the style (needed after a change)."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
