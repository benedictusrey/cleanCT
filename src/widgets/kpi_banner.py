"""Top KPI strip: one row of specimen statistics and cut status.

Cards are separated by hairline dividers. A value that does not exist yet reads
in words ("Not yet", "No reference"), never a dash.
"""
from __future__ import annotations

import theme
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel

PENDING = "Not yet"        # a value the pipeline has not produced for this scan
NO_REFERENCE = "No reference"  # no manual ground truth for this scan


class KPIBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("kpi_bar")
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 6, 0, 6)
        self.layout.setSpacing(0)

        self.cards: dict[str, tuple[QLabel, QLabel]] = {}
        items = [
            ("cut", "Cut slice"),
            ("range", "Kept range"),
            ("removed", "Removed"),
            ("roi", "ROI slices"),
            ("voxel", "Voxel"),
            ("gt", "Benchmark"),
        ]
        for index, (key, title) in enumerate(items):
            if index:
                divider = QFrame()
                divider.setObjectName("vdivider")
                self.layout.addSpacing(16)
                self.layout.addWidget(divider)
                self.layout.addSpacing(16)

            card = QVBoxLayout()
            card.setSpacing(1)

            lbl_title = QLabel(title)
            theme.set_role(lbl_title, "kpi-title")

            lbl_val = QLabel(PENDING)
            lbl_val.setObjectName(f"kpi_{key}")
            theme.set_role(lbl_val, "kpi-value")

            card.addWidget(lbl_title)
            card.addWidget(lbl_val)
            self.layout.addLayout(card)
            self.cards[key] = (lbl_title, lbl_val)

        self.layout.addStretch()
        self._settle_roles()

    def _settle_roles(self) -> None:
        """A value not produced yet is muted; a real value is full strength, and
        the cut slice, the result that matters most, is the accented hero."""
        for key, (_, val) in self.cards.items():
            if key == "gt":
                continue
            if val.text() == PENDING:
                theme.set_role(val, "kpi-muted")
            else:
                theme.set_role(val, "kpi-hero" if key == "cut" else "kpi-value")

    def updateMetrics(self, report: dict | None, override_range: tuple[int, int] | None = None,
                      effective: tuple[int, int] | None = None):
        if not report or report.get("empty"):
            # no processed data (fresh specimen): every card says it is pending
            for _, val in self.cards.values():
                val.setText(PENDING)
            self.cards["gt"][1].setText(NO_REFERENCE)
            theme.set_role(self.cards["gt"][1], "kpi-muted")
            self._settle_roles()
            return

        # Two supported shapes: the raw pipeline report (nested platform /
        # metrics / meta dicts) and the viewer's flat summary payload.
        if "cut_from" in report:                      # flat summary shape
            plat = report.get("platform", {}) or {}
            metrics = {
                "removed_fraction": report.get("removed_fraction"),
            }
            meta = {"n_slices": report.get("n_slices"),
                    "pixel_spacing_yx_mm": [report.get("voxel_mm", 0) / 1000.0]}
            roi_count = report.get("roi_n_slices")
            gt_info = report.get("ground_truth") or {}
        else:                                          # raw report shape
            plat = report.get("platform", {}) or {}
            metrics = report.get("metrics", {}) or {}
            meta = report.get("meta", {}) or {}
            roi_count = ((report.get("wood_roi", {}) or {})
                         .get("track", {}) or {}).get("n_slices_tracked")
            gt_info = report.get("ground_truth") or {}

        cut_slice = plat.get("cut_from", report.get("cut_from", PENDING))
        n_slices = meta.get("n_slices", 0)
        keep_from = plat.get("keep_from", report.get("keep_from", 0))

        # Effective (keep, cut) from the auto-placed job lines: the whole
        # header (cut + range) always mirrors the exact slices the user
        # sees on the sliders and the drawn detection lines — the header
        # can never disagree with the working lines.
        if effective is not None:
            try:
                keep_from, cut_slice = int(effective[0]), int(effective[1])
            except (TypeError, ValueError):
                pass

        # Cut
        self.cards["cut"][1].setText(str(cut_slice))

        # Range
        if override_range:
            k0, k1 = override_range
            self.cards["range"][1].setText(f"{k0}–{k1}")
        else:
            self.cards["range"][1].setText(f"{keep_from}–{cut_slice}")

        # Removed %
        rem_frac = metrics.get("removed_fraction")
        if rem_frac is not None:
            self.cards["removed"][1].setText(f"{rem_frac * 100:.2f}%")
        else:
            self.cards["removed"][1].setText(PENDING)

        # ROI slices
        self.cards["roi"][1].setText(str(roi_count) if roi_count else PENDING)

        # Voxel spacing
        spacing = meta.get("pixel_spacing_yx_mm", [0.0, 0.0])[0]
        if spacing:
            self.cards["voxel"][1].setText(f"{float(spacing) * 1000:.2f} µm")
        else:
            self.cards["voxel"][1].setText(PENDING)

        # GT Benchmark
        if gt_info and "manual_kept_slices" in gt_info:
            gt_val = gt_info["manual_kept_slices"]
            try:
                d = int(cut_slice) - int(gt_val)
            except (TypeError, ValueError):
                d = 0
            if d == 0:
                self.cards["gt"][1].setText("Match")
                theme.set_role(self.cards["gt"][1], "kpi-ok")
            else:
                self.cards["gt"][1].setText(f"{d:+d} vs manual")
                theme.set_role(self.cards["gt"][1], "kpi-warn")
        else:
            self.cards["gt"][1].setText(NO_REFERENCE)
            theme.set_role(self.cards["gt"][1], "kpi-muted")
        self._settle_roles()
