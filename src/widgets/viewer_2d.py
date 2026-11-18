"""Interactive 2D slice & orthogonal reconstruction viewer with draggable 2-line/4-line guides."""
from __future__ import annotations

import math
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPixmap
from PySide6.QtWidgets import QWidget


class Viewer2D(QWidget):
    cutChanged = Signal(int)             # bottom cut slice index
    keepChanged = Signal(int)            # top keep slice index
    leftChanged = Signal(int)            # left lateral bound percent (0..50)
    rightChanged = Signal(int)           # right lateral bound percent (50..100)
    topChanged = Signal(int)             # axial top bound percent (0..50)
    bottomChanged = Signal(int)          # axial bottom bound percent (50..100)
    boundsChanged = Signal(float, float) # lateral x0, x1 fractions (0..1)
    sliceScrubbed = Signal(int)          # scrubbed z slice index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(280, 150)   # lets two stacked viewers fit a 720 px window
        self._empty_text = "Load a scan to see it here."
        # Paint hardening: the widget paints every pixel of itself in
        # paintEvent (background fill first), so Qt can skip the implicit
        # erase — removes the white/black flash on resize and image swaps.
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        # Image state
        self._pixmap: QPixmap | None = None
        self._n_slices: int = 100
        self._cut: int = 50
        self._keep: int = 0
        self._scrub_z: int = 0
        self._plane: str = "sagittal"  # 'sagittal', 'coronal', 'axial'

        # Guides state
        self._guide_enabled: bool = True
        self._guide_mode: str = "2lines"  # "2lines" or "4lines"
        # The four guide bounds as fractions 0..1 of the panel.  Meaning is
        # PLANE-AWARE (set by _apply_plane_bounds):
        #   sagittal: _x0/_x1 = Y-axis bounds (the horizontal axis is Y)
        #   coronal : _x0/_x1 = X-axis bounds
        #   axial   : _x0/_x1 = X bounds, _y0/_y1 = Y bounds (extraction box)
        self._x0: float = 0.15
        self._x1: float = 0.85
        self._y0: float = 0.15
        self._y1: float = 0.85
        # Air-detected wood bounds: {"x": (f0, f1), "y": (f0, f1)}.  Set by
        # the window from the robust percentile envelope; None keeps the
        # manual defaults.
        self._auto_bounds: dict | None = None
        # Auto z-guides from the metal-anchored air evidence:
        # {"keep": int|None, "cut": int|None}.  Dotted reference lines on
        # the longitudinal planes (air top / metal base top); the
        # interactive Keep/Cut lines remain user- and report-driven.
        self._auto_z: dict | None = None
        # Manual bound state lives in per-axis pairs so a plane switch never
        # loses the user's drags: the horizontal lines always show the active
        # axis' pair, and edits are written back on switch.
        self._axis_pairs: dict[str, list[float]] = {"x": [0.15, 0.85],
                                                    "y": [0.15, 0.85]}
        self._cur_axis: str = "y"      # horizontal axis of the initial plane

        # Drag state
        self._active_drag: str | None = None  # 'cut', 'keep', 'left', 'right', 'top', 'bottom'

    # ---------------------------------------------------------------- Properties
    def setPixmap(self, pixmap: QPixmap, n_slices: int = 100, plane: str | None = None):
        self._pixmap = pixmap
        self._n_slices = max(1, n_slices)
        if plane is not None:
            self._plane = plane
        self.update()

    def setSliceCount(self, n_slices: int):
        """Declare the line coordinate space BEFORE any preview image lands.

        Payload loads set the real slice count here so Keep/Cut placement
        and snaps can never be silently clamped to a stale preview-space
        default (the defect that made 'Snap to detection' pin large
        volumes at the preview's old n)."""
        self._n_slices = max(1, int(n_slices))
        self._cut = max(0, min(self._n_slices, self._cut))
        self._keep = max(0, min(self._cut, self._keep))
        self.update()

    def setPlane(self, plane: str):
        # write the current horizontal bounds back to the axis they belong to
        self._axis_pairs[self._cur_axis] = [self._x0, self._x1]
        if self._plane == "axial":
            # axial vertical edits (top/bottom) belong to the Y pair
            self._axis_pairs["y"] = [self._y0, self._y1]
        self._plane = plane
        self._cur_axis = "y" if plane == "sagittal" else "x"
        self._x0, self._x1 = self._axis_pairs[self._cur_axis]
        if plane == "axial":
            self._y0, self._y1 = self._axis_pairs["y"]
        self.update()

    def setCut(self, cut: int):
        self._cut = max(0, min(self._n_slices, int(cut)))
        self.update()

    def setKeep(self, keep: int):
        self._keep = max(0, min(self._cut, int(keep)))
        self.update()

    def setAutoBounds(self, bounds: dict | None):
        """Adopt air-detected wood bounds {"x": (f0,f1), "y": (f0,f1)}.

        Applied once per specimen load: both axis pairs are set so every
        plane starts on the wood.  Later manual drags win until a new
        specimen (or an explicit re-adopt) replaces the pairs — plane
        switches only swap which pair is shown.
        """
        self._auto_bounds = bounds or None
        if not bounds:
            return
        xf, yf = bounds.get("x"), bounds.get("y")
        if xf:
            self._axis_pairs["x"] = [float(xf[0]), float(xf[1])]
        if yf:
            self._axis_pairs["y"] = [float(yf[0]), float(yf[1])]
        self._x0, self._x1 = self._axis_pairs[self._cur_axis]
        if self._plane == "axial":
            self._y0, self._y1 = self._axis_pairs["y"]
        self.update()

    def setAutoZ(self, zb: dict | None):
        """Adopt auto z-guides {"keep": int|None, "cut": int|None}.

        Reference lines only: they visualise where the metal-anchored
        air/wood edges landed so the user can compare them with the job
        Keep/Cut lines before applying.  ``None`` clears the guides.
        """
        self._auto_z = zb or None
        self.update()

    def setLeft(self, left_pct: int):
        f = max(0.0, min(1.0, float(left_pct) / 100.0))
        self._x0 = min(f, self._x1 - 0.04)
        self.update()

    def setRight(self, right_pct: int):
        f = max(0.0, min(1.0, float(right_pct) / 100.0))
        self._x1 = max(f, self._x0 + 0.04)
        self.update()

    def setTop(self, top_pct: int):
        f = max(0.0, min(1.0, float(top_pct) / 100.0))
        self._y0 = min(f, self._y1 - 0.04)
        self.update()

    def setBottom(self, bottom_pct: int):
        f = max(0.0, min(1.0, float(bottom_pct) / 100.0))
        self._y1 = max(f, self._y0 + 0.04)
        self.update()

    def setScrubZ(self, z: int):
        self._scrub_z = max(0, min(self._n_slices - 1, int(z)))
        self.update()

    def setGuideEnabled(self, enabled: bool):
        self._guide_enabled = bool(enabled)
        self.update()

    def setGuideMode(self, mode: str):
        self._guide_mode = "4lines" if mode == "4lines" else "2lines"
        self.update()

    def axisBounds(self) -> dict[str, tuple[float, float]]:
        """Return manual bounds for both image axes without exposing internals."""
        pairs = dict(self._axis_pairs)
        pairs[self._cur_axis] = [self._x0, self._x1]
        if self._plane == "axial":
            pairs["y"] = [self._y0, self._y1]
        return {axis: (float(pair[0]), float(pair[1]))
                for axis, pair in pairs.items()}

    def setAxisBounds(self, bounds: dict) -> None:
        """Restore validated x/y bounds while keeping plane state coherent."""
        for axis in ("x", "y"):
            pair = bounds.get(axis) if isinstance(bounds, dict) else None
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            low, high = float(pair[0]), float(pair[1])
            if (math.isfinite(low) and math.isfinite(high) and
                    0 <= low <= 1 and 0 <= high <= 1 and high - low >= 0.04):
                self._axis_pairs[axis] = [low, high]
        self._x0, self._x1 = self._axis_pairs[self._cur_axis]
        if self._plane == "axial":
            self._y0, self._y1 = self._axis_pairs["y"]
        self.update()

    # ---------------------------------------------------------------- Layout
    def _image_rect(self) -> QRectF:
        """Calculate letterboxed/pillarboxed rect of the pixmap."""
        if not self._pixmap or self._pixmap.isNull():
            return QRectF(0, 0, self.width(), self.height())
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        scale = min(ww / pw, wh / ph)
        nw, nh = pw * scale, ph * scale
        x = (ww - nw) / 2
        y = (wh - nh) / 2
        return QRectF(x, y, nw, nh)

    def _panel_rects(self, img_rect: QRectF) -> tuple[QRectF, QRectF | None]:
        """Detect if pixmap is dual-panel (Before | After) and return (orig_rect, after_rect)."""
        if not self._pixmap or self._pixmap.isNull():
            return img_rect, None
        aspect = self._pixmap.width() / max(1, self._pixmap.height())
        if aspect > 1.3:
            # Dual-panel side-by-side with 10px center gap
            gap = 10.0 * (img_rect.width() / max(1.0, float(self._pixmap.width())))
            pw = (img_rect.width() - gap) / 2.0
            r_left = QRectF(img_rect.left(), img_rect.top(), pw, img_rect.height())
            r_right = QRectF(img_rect.left() + pw + gap, img_rect.top(), pw, img_rect.height())
            return r_left, r_right
        return img_rect, None

    def _slice_to_y(self, slice_idx: int, img_rect: QRectF) -> float:
        frac = max(0.0, min(1.0, slice_idx / max(1, self._n_slices - 1)))
        return img_rect.top() + frac * img_rect.height()

    def _y_to_slice(self, y: float, img_rect: QRectF) -> int:
        frac = max(0.0, min(1.0, (y - img_rect.top()) / max(1.0, img_rect.height())))
        return int(round(frac * (self._n_slices - 1)))

    # ---------------------------------------------------------------- Painting
    def set_empty_text(self, text: str) -> None:
        """Text shown while there is no image (depends on the load state)."""
        self._empty_text = text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        # WA_OpaquePaintEvent promises full coverage even during a transient
        # tiny resize before the layout enforces the minimum widget size.
        painter.fillRect(self.rect(), QColor("#12151b"))
        if self.width() <= 4 or self.height() <= 4:
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # Pixmap
        img_rect = self._image_rect()
        if self._pixmap and not self._pixmap.isNull():
            painter.drawPixmap(img_rect.toRect(), self._pixmap)
        else:
            painter.setPen(QColor("#6f7c91"))
            painter.drawText(self.rect(), Qt.AlignCenter, self._empty_text)
            return

        if not self._guide_enabled:
            return

        # Resolve Left (Original) and Right (After) panel rects
        r_left, r_right = self._panel_rects(img_rect)

        # =========================================================================
        # 1. AXIAL PLANE GUIDE RENDERING
        # In Axial cross-section: horizontal/vertical lines define the extraction ROI window
        # =========================================================================
        if self._plane == "axial":
            # X bounds (0..1 of r_left)
            x_left = r_left.left() + self._x0 * r_left.width()
            x_right = r_left.left() + self._x1 * r_left.width()
            y_top = r_left.top() + self._y0 * r_left.height()
            y_bot = r_left.top() + self._y1 * r_left.height()

            # Central extraction box tint on Original panel
            box_orig = QRectF(x_left, y_top, x_right - x_left, y_bot - y_top)
            painter.fillRect(box_orig, QColor(79, 140, 255, 36))
            painter.setPen(QPen(QColor(79, 140, 255, 120), 1, Qt.SolidLine))
            painter.drawRect(box_orig)

            # Mirrored box on Right (After) panel
            if r_right:
                xr_left = r_right.left() + self._x0 * r_right.width()
                xr_right = r_right.left() + self._x1 * r_right.width()
                box_r = QRectF(xr_left, y_top, xr_right - xr_left, y_bot - y_top)
                painter.fillRect(box_r, QColor(55, 214, 122, 24))
                painter.setPen(QPen(QColor(55, 214, 122, 90), 1, Qt.DashLine))
                painter.drawRect(box_r)

            # Vertical Lines (Left & Right - Cyan)
            v_pen = QPen(QColor("#4f8cff"), 2, Qt.DashLine)
            painter.setPen(v_pen)
            painter.drawLine(QPointF(x_left, r_left.top()), QPointF(x_left, r_left.bottom()))
            painter.drawLine(QPointF(x_right, r_left.top()), QPointF(x_right, r_left.bottom()))

            # Left & Right Handles
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#4f8cff"))
            painter.drawRoundedRect(QRectF(x_left - 4, r_left.center().y() - 14, 8, 28), 4, 4)
            painter.drawRoundedRect(QRectF(x_right - 4, r_left.center().y() - 14, 8, 28), 4, 4)

            # Horizontal Lines (Top & Bottom)
            # In 2-lines mode: shows Top & Bottom extraction window lines
            h_pen = QPen(QColor("#37d67a"), 2, Qt.DashLine)
            painter.setPen(h_pen)
            painter.drawLine(QPointF(r_left.left(), y_top), QPointF(r_left.right(), y_top))
            painter.drawLine(QPointF(r_left.left(), y_bot), QPointF(r_left.right(), y_bot))

            # Horizontal Handles
            painter.setBrush(QColor("#37d67a"))
            painter.drawEllipse(QPointF(r_left.center().x(), y_top), 6, 6)
            painter.drawEllipse(QPointF(r_left.center().x(), y_bot), 6, 6)

            # Axial ROI Info Badge (both axes)
            badge_rect = QRectF(r_left.left() + 10, r_left.bottom() - 26, 190, 20)
            painter.setBrush(QColor(18, 22, 30, 230))
            painter.setPen(QPen(QColor("#4f8cff"), 1))
            painter.drawRoundedRect(badge_rect, 4, 4)
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.setPen(QColor("#4f8cff"))
            painter.drawText(badge_rect, Qt.AlignCenter,
                             f"ROI X {int(self._x0*100)}..{int(self._x1*100)}%  ·  Y {int(self._y0*100)}..{int(self._y1*100)}%")
            return

        # =========================================================================
        # 2. LONGITUDINAL PLANES (SAGITTAL & CORONAL)
        # Vertical axis = Slice Index (z: 0..N). Horizontal lines = Keep Start & Cut
        # =========================================================================
        y_keep = self._slice_to_y(self._keep, img_rect)
        y_cut = self._slice_to_y(self._cut, img_rect)
        x_left = r_left.left() + self._x0 * r_left.width()
        x_right = r_left.left() + self._x1 * r_left.width()

        # ---------------- 4-Lines Bounding Box Overlay ----------------
        if self._guide_mode == "4lines":
            top_y = min(y_keep, y_cut)
            bot_y = max(y_keep, y_cut)
            box_rect = QRectF(x_left, top_y, x_right - x_left, bot_y - top_y)
            painter.fillRect(box_rect, QColor(79, 140, 255, 36))
            painter.setPen(QPen(QColor(79, 140, 255, 110), 1, Qt.SolidLine))
            painter.drawRect(box_rect)

            # Mirrored indicator on Right (After) panel
            if r_right:
                xr_left = r_right.left() + self._x0 * r_right.width()
                xr_right = r_right.left() + self._x1 * r_right.width()
                box_r = QRectF(xr_left, top_y, xr_right - xr_left, bot_y - top_y)
                painter.fillRect(box_r, QColor(55, 214, 122, 24))
                painter.setPen(QPen(QColor(55, 214, 122, 90), 1, Qt.DashLine))
                painter.drawRect(box_r)

            # Left Vertical Line (Cyan) — on Original panel
            v_pen_l = QPen(QColor("#4f8cff"), 2, Qt.DashLine)
            painter.setPen(v_pen_l)
            painter.drawLine(QPointF(x_left, r_left.top()), QPointF(x_left, r_left.bottom()))

            # Left Handles & Badges
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#4f8cff"))
            painter.drawEllipse(QPointF(x_left, r_left.top() + 18), 7, 7)
            painter.drawEllipse(QPointF(x_left, r_left.bottom() - 18), 7, 7)
            painter.drawRoundedRect(QRectF(x_left - 5, r_left.center().y() - 16, 10, 32), 4, 4)

            badge_l = QRectF(x_left + 8, r_left.center().y() - 10, 52, 20)
            painter.setBrush(QColor(18, 22, 30, 225))
            painter.setPen(QPen(QColor("#4f8cff"), 1))
            painter.drawRoundedRect(badge_l, 4, 4)
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.setPen(QColor("#4f8cff"))
            painter.drawText(badge_l, Qt.AlignCenter, f"L {int(self._x0*100)}%")

            # Right Vertical Line (Cyan) — on Original panel
            v_pen_r = QPen(QColor("#4f8cff"), 2, Qt.DashLine)
            painter.setPen(v_pen_r)
            painter.drawLine(QPointF(x_right, r_left.top()), QPointF(x_right, r_left.bottom()))

            # Right Handles & Badges
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#4f8cff"))
            painter.drawEllipse(QPointF(x_right, r_left.top() + 18), 7, 7)
            painter.drawEllipse(QPointF(x_right, r_left.bottom() - 18), 7, 7)
            painter.drawRoundedRect(QRectF(x_right - 5, r_left.center().y() - 16, 10, 32), 4, 4)

            badge_r = QRectF(x_right - 60, r_left.center().y() - 10, 52, 20)
            painter.setBrush(QColor(18, 22, 30, 225))
            painter.setPen(QPen(QColor("#4f8cff"), 1))
            painter.drawRoundedRect(badge_r, 4, 4)
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.setPen(QColor("#4f8cff"))
            painter.drawText(badge_r, Qt.AlignCenter, f"R {int(self._x1*100)}%")

        # ---------------- Auto z-guides (air top / metal base, dotted) ------
        # Drawn beneath the interactive Keep/Cut lines so the job lines and
        # their handles stay fully visible; a guide only appears when its
        # slice is inside the displayed z-range.
        if self._auto_z and self._guide_enabled:
            zk = self._auto_z.get("keep")
            zc = self._auto_z.get("cut")
            zw = (self._auto_z.get("wood_top")
                  if zk is None else None)
            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            if zw is not None:
                # air top deferred (foggy edge): still show the detected
                # wood-top evidence so Snap's fallback target is visible
                y_w = self._slice_to_y(int(zw), img_rect)
                if img_rect.top() - 6 <= y_w <= img_rect.bottom() + 6:
                    painter.setPen(QPen(QColor("#37d67a"), 1, Qt.DotLine))
                    painter.drawLine(QPointF(img_rect.left(), y_w),
                                     QPointF(img_rect.right(), y_w))
                    painter.setBrush(QColor(18, 22, 30, 200))
                    painter.setPen(QPen(QColor("#37d67a"), 1))
                    wb = QRectF(img_rect.left() + 6, y_w - 9, 86, 18)
                    painter.drawRoundedRect(wb, 4, 4)
                    painter.setPen(QColor("#37d67a"))
                    painter.drawText(wb, Qt.AlignCenter, f"wood top {int(zw)}")
            if zk is not None:
                y_a = self._slice_to_y(int(zk), img_rect)
                if img_rect.top() - 6 <= y_a <= img_rect.bottom() + 6:
                    painter.setPen(QPen(QColor("#37d67a"), 1, Qt.DotLine))
                    painter.drawLine(QPointF(img_rect.left(), y_a),
                                     QPointF(img_rect.right(), y_a))
                    painter.setBrush(QColor(18, 22, 30, 200))
                    painter.setPen(QPen(QColor("#37d67a"), 1))
                    ab = QRectF(img_rect.left() + 6, y_a - 9, 86, 18)
                    painter.drawRoundedRect(ab, 4, 4)
                    painter.setPen(QColor("#37d67a"))
                    painter.drawText(ab, Qt.AlignCenter, f"air top {int(zk)}")
            if zc is not None:
                y_b = self._slice_to_y(int(zc), img_rect)
                if img_rect.top() - 6 <= y_b <= img_rect.bottom() + 6:
                    painter.setPen(QPen(QColor("#ff9f43"), 1, Qt.DotLine))
                    painter.drawLine(QPointF(img_rect.left(), y_b),
                                     QPointF(img_rect.right(), y_b))
                    painter.setBrush(QColor(18, 22, 30, 200))
                    painter.setPen(QPen(QColor("#ff9f43"), 1))
                    # flip above the line when the badge would clip at the
                    # panel bottom, and offset right of the Cut badge
                    # (left+28..left+120) so the two never overlap
                    if y_b + 19 <= img_rect.bottom():
                        ay, ax = y_b + 1, img_rect.left() + 6
                    else:
                        ay, ax = y_b - 19, img_rect.left() + 130
                    ab2 = QRectF(ax, ay, 100, 18)
                    painter.drawRoundedRect(ab2, 4, 4)
                    painter.setPen(QColor("#ff9f43"))
                    painter.drawText(ab2, Qt.AlignCenter, f"metal top {int(zc)}")

        # ---------------- Top Horizontal Line (Keep / Green) ----------------
        pen_keep = QPen(QColor("#37d67a"), 2, Qt.DashLine)
        painter.setPen(pen_keep)
        painter.drawLine(QPointF(img_rect.left(), y_keep), QPointF(img_rect.right(), y_keep))

        # Keep Handles
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#37d67a"))
        painter.drawEllipse(QPointF(img_rect.left() + 18, y_keep), 7, 7)
        painter.drawEllipse(QPointF(img_rect.right() - 18, y_keep), 7, 7)

        # Keep Badges
        badge_w, badge_h = 92, 20
        badge_rect = QRectF(img_rect.right() - badge_w - 28, max(img_rect.top() + 2, y_keep - 10), badge_w, badge_h)
        painter.setBrush(QColor(18, 22, 30, 225))
        painter.setPen(QPen(QColor("#37d67a"), 1))
        painter.drawRoundedRect(badge_rect, 4, 4)
        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        painter.setPen(QColor("#37d67a"))
        painter.drawText(badge_rect, Qt.AlignCenter, f"Keep: {self._keep}")

        # ---------------- Bottom Horizontal Line (Cut / Red) ----------------
        pen_cut = QPen(QColor("#ff463c"), 2, Qt.DashLine)
        painter.setPen(pen_cut)
        painter.drawLine(QPointF(img_rect.left(), y_cut), QPointF(img_rect.right(), y_cut))

        # Cut Handles
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ff463c"))
        painter.drawEllipse(QPointF(img_rect.left() + 18, y_cut), 7, 7)
        painter.drawEllipse(QPointF(img_rect.right() - 18, y_cut), 7, 7)

        # Cut Badges
        badge_rect2 = QRectF(img_rect.left() + 28, min(img_rect.bottom() - badge_h - 2, y_cut - 10), badge_w, badge_h)
        painter.setBrush(QColor(18, 22, 30, 225))
        painter.setPen(QPen(QColor("#ff463c"), 1))
        painter.drawRoundedRect(badge_rect2, 4, 4)
        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        painter.setPen(QColor("#ff463c"))
        painter.drawText(badge_rect2, Qt.AlignCenter, f"Cut: {self._cut}")

    # ---------------------------------------------------------------- Interactivity
    def _hit_test(self, pos: QPointF) -> str | None:
        if not self._guide_enabled:
            return None
        img_rect = self._image_rect()
        r_left, _ = self._panel_rects(img_rect)

        tol = 16.0

        if self._plane == "axial":
            x_left = r_left.left() + self._x0 * r_left.width()
            x_right = r_left.left() + self._x1 * r_left.width()
            y_top = r_left.top() + self._y0 * r_left.height()
            y_bot = r_left.top() + self._y1 * r_left.height()

            if abs(pos.x() - x_left) < tol:
                return "left"
            if abs(pos.x() - x_right) < tol:
                return "right"
            if abs(pos.y() - y_top) < tol:
                return "top"
            if abs(pos.y() - y_bot) < tol:
                return "bottom"
            return None

        y_keep = self._slice_to_y(self._keep, img_rect)
        y_cut = self._slice_to_y(self._cut, img_rect)

        # Horizontal checks
        if abs(pos.y() - y_keep) < tol:
            return "keep"
        if abs(pos.y() - y_cut) < tol:
            return "cut"

        # Vertical checks (4 lines) strictly on Left (Original) panel
        if self._guide_mode == "4lines":
            x_left = r_left.left() + self._x0 * r_left.width()
            x_right = r_left.left() + self._x1 * r_left.width()
            if abs(pos.x() - x_left) < tol:
                return "left"
            if abs(pos.x() - x_right) < tol:
                return "right"

        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            hit = self._hit_test(event.position())
            if hit:
                self._active_drag = hit
                self.setCursor(Qt.ClosedHandCursor)
            else:
                img_rect = self._image_rect()
                if img_rect.contains(event.position()) and self._plane != "axial":
                    z = self._y_to_slice(event.position().y(), img_rect)
                    self.sliceScrubbed.emit(z)

    def mouseMoveEvent(self, event):
        img_rect = self._image_rect()
        r_left, _ = self._panel_rects(img_rect)
        pos = event.position()

        if self._active_drag:
            if self._active_drag == "keep":
                new_keep = self._y_to_slice(pos.y(), img_rect)
                new_keep = min(self._cut - 1 if self._cut > 0 else 0, max(0, new_keep))
                if new_keep != self._keep:
                    self._keep = new_keep
                    self.keepChanged.emit(self._keep)
                    self.update()
            elif self._active_drag == "cut":
                new_cut = self._y_to_slice(pos.y(), img_rect)
                new_cut = max(self._keep + 1, min(self._n_slices, new_cut))
                if new_cut != self._cut:
                    self._cut = new_cut
                    self.cutChanged.emit(self._cut)
                    self.update()
            elif self._active_drag == "left":
                new_x0 = max(0.0, min(self._x1 - 0.04, (pos.x() - r_left.left()) / max(1.0, r_left.width())))
                self._x0 = new_x0
                self.leftChanged.emit(int(round(self._x0 * 100)))
                self.boundsChanged.emit(self._x0, self._x1)
                self.update()
            elif self._active_drag == "right":
                new_x1 = max(self._x0 + 0.04, min(1.0, (pos.x() - r_left.left()) / max(1.0, r_left.width())))
                self._x1 = new_x1
                self.rightChanged.emit(int(round(self._x1 * 100)))
                self.boundsChanged.emit(self._x0, self._x1)
                self.update()
            elif self._active_drag == "top":
                self._y0 = max(0.0, min(self._y1 - 0.04, (pos.y() - r_left.top()) / max(1.0, r_left.height())))
                self.topChanged.emit(int(round(self._y0 * 100)))
                self.update()
            elif self._active_drag == "bottom":
                self._y1 = max(self._y0 + 0.04, min(1.0, (pos.y() - r_left.top()) / max(1.0, r_left.height())))
                self.bottomChanged.emit(int(round(self._y1 * 100)))
                self.update()
        else:
            hit = self._hit_test(pos)
            if hit in ("keep", "cut", "top", "bottom"):
                self.setCursor(Qt.SizeVerCursor)
            elif hit in ("left", "right"):
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.CrossCursor)

    def mouseReleaseEvent(self, event):
        self._active_drag = None
        self.setCursor(Qt.ArrowCursor)
