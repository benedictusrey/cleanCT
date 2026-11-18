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
TEXT_MUTED = "#6f7c91"

ACCENT_AMBER = "#f2b23c"
ACCENT_AMBER_HOVER = "#ffc55a"
ACCENT_BLUE = "#4f8cff"
ACCENT_BLUE_HOVER = "#70a2ff"
ACCENT_GREEN = "#37d67a"
ACCENT_RED = "#ff463c"

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
"""
