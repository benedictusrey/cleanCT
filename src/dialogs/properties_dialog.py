"""Specimen properties dialog for the cleanCT specimen panel."""
from __future__ import annotations

from pathlib import Path

import theme
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QScrollArea
)


MISSING = "not recorded"


def _row(label: str, value: str) -> str:
    # colours come from the active theme, so the rows read in both themes
    return (f"<tr><td style='color:{theme.color('text_2')}; padding:2px 14px 2px 0; "
            f"white-space:nowrap; vertical-align:top;'>{label}</td>"
            f"<td style='color:{theme.color('text')};'>{value}</td></tr>")


class SpecimenPropertiesDialog(QDialog):
    """Read-only overview of one specimen: identity, geometry, on-disk
    size, source and processed-output locations."""

    def __init__(self, parent, info: dict):
        super().__init__(parent)
        name = info.get("name") or ""
        self.setWindowTitle(f"Properties: {name}")
        self.setModal(True)
        self.setMinimumWidth(580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        rows = [
            _row("Specimen", f"<b>{name}</b>"),
            _row("Source", info.get("kind_label") or info.get("kind") or MISSING),
            _row("Slices", str(info.get("slices") or MISSING)),
            _row("Dimensions", info.get("dims") or MISSING),
            _row("Voxel size", (f"{float(info['um']):.4g} µm"
                                if info.get("um") else MISSING)),
            _row("Size on disk", info.get("size_label") or MISSING),
            _row("Dataset", info.get("dataset") or MISSING),
        ]
        if info.get("added"):
            rows.append(_row("Registered", str(info["added"])))
        if info.get("source"):
            rows.append(_row("Source folder", f"<code>{info['source']}</code>"))
        if info.get("processed"):
            rows.append(_row("Processed output",
                             f"<code>{info['processed']}</code>"))
        if info.get("export_dest"):
            rows.append(_row("Export destination",
                             f"<code>{info['export_dest']}</code>"))

        html = ("<table cellspacing='0' cellpadding='0' style='font-size:12px;'>"
                + "".join(rows) + "</table>")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        title = QLabel("Specimen properties")
        theme.set_role(title, "title")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QLabel(html)
        inner.setTextFormat(Qt.RichText)
        inner.setWordWrap(True)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        if info.get("source") and Path(info["source"]).exists():
            btn_locate = QPushButton("Show in Explorer")
            btn_locate.setToolTip("Open the specimen folder in Windows Explorer.")
            btn_locate.clicked.connect(self._locate)
            btn_row.addWidget(btn_locate)
        btn_close = QPushButton("Close")
        btn_close.setObjectName("btn_about_close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._target = info.get("source") or ""

    def _locate(self):
        target = self._target
        if target and Path(target).exists():
            import subprocess
            subprocess.Popen(["explorer", f"/select,{target}"], shell=False)
        self.accept()
