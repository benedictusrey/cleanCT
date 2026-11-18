"""Specimen-panel building blocks for the cleanCT sidebar.

Contains the indeterminate busy spinner, the two-line specimen row
delegate (name + metadata), and the formatting helpers shared by the
sidebar.  Kept free of any pipeline imports so it stays importable in
isolated GUI tests.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QWidget

import theme

ROW_HEIGHT = 44
ROW_MARGIN = 6


def human_size(n_bytes: int | None) -> str:
    """Compact human-readable byte size ('1.2 GB', '864 MB', '—')."""
    if not n_bytes or n_bytes <= 0:
        return "—"
    value = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return "—"


def folder_size_bytes(folder: Path) -> int:
    """Recursive on-disk size of a folder (stat-only walk; never reads
    file contents).  Errors are skipped so partially readable sources
    still report a usable size."""
    total = 0
    try:
        for root, _dirs, files in os.walk(folder, onerror=lambda _e: None):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def format_specimen_meta(meta: dict) -> str:
    """Row meta line from a dict of optional fields:
    ``kind`` (str), ``slices`` (int), ``dims`` (str like '512×512'),
    ``um`` (voxel size), ``size`` (bytes or None while scanning)."""
    parts = []
    if meta.get("kind"):
        parts.append(str(meta["kind"]))
    if meta.get("slices"):
        parts.append(f"{int(meta['slices']):,} slices")
    if meta.get("dims"):
        parts.append(str(meta["dims"]))
    if meta.get("um"):
        parts.append(f"{float(meta['um']):.4g} µm")
    if meta.get("size"):
        parts.append(human_size(meta.get("size")))
    elif "size" in meta and not meta.get("size"):
        parts.append("size …")
    return ", ".join(parts)


class BusySpinner(QWidget):
    """Tiny indeterminate arc spinner (sidebar header, 14 px).

    Only repaints while running and visible, so idle sessions never
    wake the event loop.
    """
    INTERVAL_MS = 40

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._angle = 0
        self._running = False
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def setRunning(self, running: bool) -> None:
        if bool(running) == self._running:
            return
        self._running = bool(running)
        if self._running:
            self.show()
            self._timer.start()
        else:
            self._timer.stop()
            self.hide()
            self.update()

    def isRunning(self) -> bool:
        return self._running

    def _tick(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._running:
            return
        pen = QPen(QColor(theme.color("accent")), 2.0)
        pen.setCapStyle(Qt.RoundCap)
        p = QPainter(self)
        p.setRenderHint(p.RenderHint.Antialiasing)
        p.setPen(pen)
        rect = QRectF(0, 0, 14, 14).adjusted(2.5, 2.5, -2.5, -2.5)
        p.drawArc(rect, -self._angle * 16, 100 * 16)
        p.end()


class SpecimenDelegate(QStyledItemDelegate):
    """Two-line specimen row: name on top, muted metadata below.

    Items carry ``Qt.UserRole`` = (dataset, specimen); when absent the
    base class paints (section headers, placeholders).  Hover and
    selection match the dark graphite theme.
    """
    META_ROLE = Qt.UserRole + 1

    def paint(self, painter, option, index) -> None:
        key = index.data(Qt.UserRole)
        if not key:
            super().paint(painter, option, index)
            return
        raw = index.data(self.META_ROLE)
        meta = (format_specimen_meta(raw)
                if isinstance(raw, dict) else str(raw or ""))
        p = painter
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(ROW_MARGIN, 1, -ROW_MARGIN, -1)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected:
            fill = QColor(theme.color("accent"))
            fill.setAlpha(36)
            p.setPen(QColor(theme.color("accent")))
            p.setBrush(fill)
            p.drawRoundedRect(rect, 8, 8)
        elif hovered:
            fill = QColor(theme.color("text"))
            fill.setAlpha(16)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(rect, 8, 8)

        name_rect = rect.adjusted(8, 5, -8, 0)
        name_rect.setHeight(18)
        meta_rect = rect.adjusted(8, 23, -8, 0)
        meta_rect.setHeight(15)

        f = option.font
        f.setBold(True)
        f.setPointSizeF(10.0)
        p.setFont(f)
        p.setPen(QColor(theme.color("accent" if selected else "text")))
        elided_name = QFontMetrics(f).elidedText(
            str(key[1]), Qt.ElideRight, name_rect.width())
        p.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_name)

        f2 = option.font
        f2.setBold(False)
        f2.setPointSizeF(9.0)
        p.setFont(f2)
        p.setPen(QColor(theme.color("text_2" if selected else "text_3")))
        # elide, so a long metadata line never runs past the row's edge
        elided_meta = QFontMetrics(f2).elidedText(
            meta or " ", Qt.ElideRight, meta_rect.width())
        p.drawText(meta_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_meta)

        p.restore()

    def sizeHint(self, option, index) -> QSize:
        if not index.data(Qt.UserRole):
            return super().sizeHint(option, index)
        return QSize(option.rect.width() if option.rect.width() else 240,
                     ROW_HEIGHT)
