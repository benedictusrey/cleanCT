"""About cleanCT dialog with enlarged HD brand icon."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)

try:
    from core.paths import APP_ROOT as ROOT
    from icon_utils import icons_dir
except ImportError:  # direct import (no package context)
    from paths import APP_ROOT as ROOT
    from icon_utils import icons_dir


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About cleanCT")
        self.setFixedSize(540, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)

        # Enlarged HD CleanCT Icon (128x128)
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        _icons = icons_dir(ROOT) or ROOT
        icon_path = _icons / "icon_1024x1024.png"
        if not icon_path.exists():
            icon_path = _icons / "icon_256x256.png"
        if icon_path.exists():
            pm = QPixmap(str(icon_path)).scaled(
                128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            icon_label.setPixmap(pm)
        icon_label.setStyleSheet("""
            QLabel {
                padding: 4px;
                border-radius: 26px;
            }
        """)
        layout.addWidget(icon_label)

        # Brand Title
        title_label = QLabel("clean<span style='color:#f2b23c;'>CT</span>")
        title_label.setTextFormat(Qt.RichText)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        layout.addWidget(title_label)

        # Descriptor
        desc_sub = QLabel("Non-Destructive Wood CT Metal-Base Removal & Inspection")
        desc_sub.setAlignment(Qt.AlignCenter)
        desc_sub.setStyleSheet("color: #9daabf; font-size: 13px; font-weight: 500;")
        layout.addWidget(desc_sub)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("background-color: #2a3244; max-height: 1px;")
        layout.addWidget(div)

        # Description text
        desc_text = QLabel(
            "<b>cleanCT</b> is a native workstation tool for micro-CT wood specimens. "
            "It detects the high-attenuation metal platform beneath the wood block, "
            "removes it at the validated cut boundary, and delivers verified clean DICOM series, "
            "NIfTI-1 volumes, and complete extraction provenance.<br><br>"
            "<b>Workflow:</b> ① Select dataset or load a custom specimen folder, "
            "② inspect unstripped reconstructions with interactive 2D draggable guides & scientific colorspaces, "
            "③ apply overrides and auto-export the delivery bundle.<br><br>"
            "Validated against high-resolution manual ground truth. Original scan data remain untouched in-place."
        )
        desc_text.setWordWrap(True)
        desc_text.setTextFormat(Qt.RichText)
        desc_text.setStyleSheet("color: #c0cbe0; font-size: 12px; line-height: 1.45;")
        layout.addWidget(desc_text)

        # Prepared by section
        author_box = QVBoxLayout()
        author_box.setSpacing(2)
        author_hdr = QLabel("PREPARED BY")
        author_hdr.setStyleSheet("color: #6f7c91; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        author_name = QLabel("Benedictus Reynaldo Hartanto")
        author_name.setStyleSheet("color: #f2b23c; font-size: 14px; font-weight: 600;")
        author_box.addWidget(author_hdr)
        author_box.addWidget(author_name)
        layout.addLayout(author_box)

        layout.addStretch()

        # Close button
        btn_close = QPushButton("Close")
        btn_close.setObjectName("btn_about_close")
        btn_close.setProperty("class", "btn-primary")
        btn_close.setFixedWidth(110)
        btn_close.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)
