"""About cleanCT: what it does, how a scan is cleaned, and where its record lives.

The processing line reads the live GPU status from the main window, so the dialog
says what this PC is actually doing, not a generic claim.
"""
from __future__ import annotations

import theme
from core import bundle_export, paths
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from icon_utils import icons_dir


def _document(name: str):
    """A bundled document, found in the development or the installed layout."""
    for folder in (paths.APP_ROOT, paths.APP_ROOT.parent, paths.APP_ROOT / "docs"):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def _open_path(path) -> None:
    if path is not None and path.exists():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class AboutDialog(QDialog):
    STEPS = (
        ("Load a scan", "A DICOM series, a TIFF stack or a NIfTI volume. The source "
                        "files stay where they are."),
        ("Check the lines", "Detection draws the keep and cut lines. Drag any line "
                            "on the preview to correct it."),
        ("Process and export", "The bundle holds the DICOM series, the NIfTI volume "
                               "and the extraction record."),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About cleanCT")
        self.setFixedWidth(600)
        # single-flag call: a flag mask would also drop the close (X) button
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 26, 30, 22)
        root.setSpacing(18)

        root.addLayout(self._header())
        root.addWidget(self._divider())
        root.addWidget(self._lead())
        root.addLayout(self._steps())
        root.addLayout(self._facts(parent))
        root.addLayout(self._links())
        root.addWidget(self._divider())
        root.addLayout(self._footer())
        # the wrapped steps need their real height: size to the contents at the fixed width
        root.activate()
        self.resize(600, self.heightForWidth(600) if self.hasHeightForWidth()
                    else self.sizeHint().height())

    # ----------------------------------------------------------------- pieces
    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setObjectName("divider")
        return line

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(18)
        icon = QLabel()
        icon.setObjectName("app_icon")
        icon.setFixedSize(72, 72)
        icons = icons_dir(paths.APP_ROOT) or paths.APP_ROOT
        for name in ("icon_256x256.png", "icon_1024x1024.png"):
            if (icons / name).exists():
                icon.setPixmap(QPixmap(str(icons / name)).scaled(
                    72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                break
        row.addWidget(icon)

        names = QVBoxLayout()
        names.setSpacing(3)
        title = QLabel(f"clean<span style='color:{theme.color('accent')};'>CT</span>")
        title.setTextFormat(Qt.RichText)
        theme.set_role(title, "about-title")
        names.addWidget(title)
        tagline = QLabel("Wood CT metal-base removal")
        theme.set_role(tagline, "secondary")
        names.addWidget(tagline)
        row.addLayout(names, 1)

        version = QLabel(f"Version {bundle_export.CLEANCT_VERSION}")
        theme.set_role(version, "pill-accent")
        row.addWidget(version, 0, Qt.AlignTop)
        return row

    @staticmethod
    def _lead() -> QLabel:
        lead = QLabel(
            "cleanCT finds the metal platform beneath a wood block, removes it at the "
            "validated cut, and delivers verified clean DICOM series and NIfTI-1 "
            "volumes with the full extraction record. Validated against high-resolution "
            "manual ground truth.")
        lead.setWordWrap(True)
        theme.set_role(lead, "label")
        return lead

    def _steps(self) -> QVBoxLayout:
        block = QVBoxLayout()
        block.setSpacing(10)
        heading = QLabel("How a scan is cleaned")
        theme.set_role(heading, "section")
        block.addWidget(heading)
        # one row per step: a number, then its text, wrapped to the dialog width
        for index, (title, body) in enumerate(self.STEPS):
            row = QHBoxLayout()
            row.setSpacing(14)
            number = QLabel(str(index + 1))
            theme.set_role(number, "accent")
            number.setFont(QFont("Bahnschrift", 15, QFont.DemiBold))
            number.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            number.setFixedWidth(14)
            text = QLabel(f"<b>{title}.</b> {body}")
            text.setTextFormat(Qt.RichText)
            text.setWordWrap(True)
            theme.set_role(text, "label")
            row.addWidget(number, 0, Qt.AlignTop)
            row.addWidget(text, 1)
            block.addLayout(row)
        return block

    def _facts(self, parent) -> QGridLayout:
        """Three facts about this install: the processing mode, the outputs, the source."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        gpu = parent.lbl_gpu.text() if parent is not None and hasattr(parent, "lbl_gpu") else ""
        processing = "GPU (CuPy CUDA)" if "CuPy CUDA" in gpu else "CPU"
        facts = (
            ("Processing", processing),
            ("Outputs", "DICOM, NIfTI, provenance"),
            ("Source scans", "Never modified"),
        )
        for column, (label, value) in enumerate(facts):
            card = QFrame()
            card.setProperty("class", "panel")
            col = QVBoxLayout(card)
            col.setContentsMargins(14, 10, 14, 10)
            col.setSpacing(2)
            caption = QLabel(label)
            theme.set_role(caption, "kpi-title")
            body = QLabel(value)
            theme.set_role(body, "section")
            col.addWidget(caption)
            col.addWidget(body)
            grid.addWidget(card, 0, column)
        return grid

    def _links(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(18)
        for label, target in (
            ("User guide", lambda: _open_path(_document("USER_GUIDE.md"))),
            ("Activity log", lambda: _open_path(paths.state_root() / "logs" / "cleanCT.log")),
            ("Data folder", lambda: _open_path(paths.state_root())),
        ):
            link = QPushButton(label)
            link.setObjectName("btn_about_link")
            link.setCursor(Qt.PointingHandCursor)
            theme.set_role(link, "link")
            link.clicked.connect(target)
            row.addWidget(link)
        row.addStretch()
        return row

    def _footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        prepared = QLabel("Prepared by")
        theme.set_role(prepared, "hint")
        name = QLabel("Benedictus Reynaldo Hartanto")
        theme.set_role(name, "accent")
        row.addWidget(prepared)
        row.addWidget(name)
        row.addStretch()
        close = QPushButton("Close")
        close.setObjectName("btn_about_close")
        close.setProperty("class", "btn-primary")
        close.setMinimumWidth(110)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        return row
