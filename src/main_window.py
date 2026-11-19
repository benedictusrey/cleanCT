"""Master Native Application Window for cleanCT (PySide6)."""
from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from PIL import Image

from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QPixmap, QImage, QFont, QColor, QKeySequence, \
    QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QFrame, QListWidget, QListWidgetItem, QStackedWidget, QLineEdit,
    QSpinBox, QSlider, QCheckBox, QFileDialog, QMessageBox, QProgressBar,
    QSplitter, QTextEdit, QScrollArea, QLayout, QComboBox, QInputDialog,
    QMenu, QApplication, QGridLayout, QSizePolicy
)

# Core pipeline imports
try:
    from core.paths import APP_ROOT as ROOT, ensure_engine_on_path, \
        reveal_in_file_manager, state_root
except ImportError:  # direct import (no package context)
    from paths import APP_ROOT as ROOT, ensure_engine_on_path, \
        reveal_in_file_manager, state_root

PIPELINE = ensure_engine_on_path()
STATE = state_root()
BUSY_NOTE = "Wait for the current job to finish."
# Names for screen readers, taken from the visible labels of the controls
ACCESSIBLE_NAMES = {
    "spin_lo": "Minimum density, HU", "slider_lo": "Minimum density, HU",
    "spin_hi": "Maximum density, HU", "slider_hi": "Maximum density, HU",
    "spin_keep": "Top line, keep start", "slider_keep": "Top line, keep start",
    "spin_cut": "Bottom line, platform cut", "slider_cut": "Bottom line, platform cut",
    "spin_margin": "Margin above cut, slices", "slider_margin": "Margin above cut, slices",
    "spin_left": "Left X boundary", "slider_left": "Left X boundary",
    "spin_right": "Right X boundary", "slider_right": "Right X boundary",
    "spin_top": "Top Y boundary", "slider_top": "Top Y boundary",
    "spin_bottom": "Bottom Y boundary", "slider_bottom": "Bottom Y boundary",
    "axial_slider": "Axial slice", "pref_slider": "Preview slice",
    "long_slider": "Longitudinal position",
}
# Why a threshold preset or Reset is unavailable before a scan is loaded
PRESET_TIP = "Available after a scan is loaded."
AIR_CROP_TIP = ("Trims near-pure-air margins (HU ≤ −900) from the wood box in the processing "
                "output (wood_roi.nii). The bundle is cut to the Keep, Cut and L/R lines, "
                "not to this box.\n"
                "Wood touching the scan edge keeps that axis untouched; heavy fog disables "
                "trimming for safety; the result never grows beyond the tracked wood ROI.")
TIPS = {
    "btn_th_reset": "Restore the default density thresholds. " + PRESET_TIP,
    "btn_th_full": "Show the full density range. " + PRESET_TIP,
    "btn_th_wood": "Set the thresholds to the wood tissue range. " + PRESET_TIP,
    "btn_th_contrast": "Set the thresholds for high contrast. " + PRESET_TIP,
    "btn_th_metal": "Set the thresholds to the platform metal range. " + PRESET_TIP,
}
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import viewer_core, custom_series as csx, bundle_export, \
    checkpoint_file, auto_snap, user_messages
import theme
import tomograph as tg

from widgets.viewer_2d import Viewer2D, crop_after_panel
from widgets.viewer_3d import Viewer3D
from widgets.kpi_banner import KPIBanner
from widgets.specimen_panel import (BusySpinner, SpecimenDelegate,
                                    folder_size_bytes, human_size)
from dialogs.about_dialog import AboutDialog
from dialogs.load_dialog import LoadDialog
from dialogs.properties_dialog import SpecimenPropertiesDialog
import icon_utils


def _natural_key(value: str) -> list:
    """Sort key that compares embedded numbers as numbers (1-2 before 1-10)."""
    return [int(token) if token.isdigit() else token
            for token in re.split(r"(\d+)", value)]


# Minimum Left-to-Right band in percent: the viewer keeps the same gap.
LATERAL_MIN_GAP_PCT = 4


def key_swatch(name: str, text: str = "") -> str:
    """A colour key: a swatch in the line's colour, then its label. The colour
    comes from the active theme, so the key re-renders when the theme changes."""
    swatch = f"<span style='color:{theme.color(f'key_{name}')};'>■</span>"
    return f"{swatch} {text}" if text else swatch


def _b64_to_pixmap(data_url: str) -> QPixmap:
    if not data_url:
        return QPixmap()
    b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
    raw = base64.b64decode(b64)
    pm = QPixmap()
    # Fast path: Qt's native decoder (~4x faster than the old PIL
    # round-trip).  Some PySide6 installs ship without the JPEG
    # imageformat plugin: loadFromData then fails on VALID bytes, so
    # fall back to decoding through PIL (always available here).
    if pm.loadFromData(raw):
        return pm
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
        rgba = im.tobytes("raw", "RGBA")
        qim = QImage(rgba, im.width, im.height, im.width * 4,
                     QImage.Format_RGBA8888).copy()
        return QPixmap.fromImage(qim)
    except Exception:
        return QPixmap()


class WorkerThread(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)
    progress = Signal(int, int, str)   # i, n, phase (audit 0M: live jobs)

    def __init__(self, task_func, *args, **kwargs):
        super().__init__()
        self.task_func = task_func
        self.args = args
        self.kwargs = kwargs
        self.with_progress = False   # True: task accepts job_progress callable

    def run(self):
        try:
            if self.with_progress:
                # emit from this (worker) thread; Qt queues it to the GUI
                res = self.task_func(job_progress=self.progress.emit)
            else:
                res = self.task_func(*self.args, **self.kwargs)
            self.succeeded.emit(res or {})
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("cleanCT: wood CT metal-base removal")
        # the supported minimum: at 1280 px the Auto page fits without scrolling
        self.setMinimumWidth(1280)
        self.resize(1540, 960)

        # Set Window Icon (Native Multi-Res with all explicit pixel mipmaps)
        self.setWindowIcon(icon_utils.get_app_icon(ROOT))

        # State
        self.dataset: str = ""
        self.sample: str = ""
        self.payload: dict | None = None
        self._session_preview_history: list[dict] = []
        self._last_pref_preview: dict | None = None
        self._checkpoint_snapshot_only = False
        self._pending_view_restore: dict | None = None
        self._pending_view_restore_kind = ""
        self._history_restore_generation: int | None = None
        self.axial_idx: int = 0
        self.long_view: str = "sagittal"

        # Preferences default state: 4 Lines active, Grayscale as first & default colorspace
        self.pref_cut: int = 1000
        self.pref_margin: int = 0
        self.pref_keep: int = 0
        self.pref_plane: str = "sagittal"
        self.pref_cmap: str = "grayscale"
        self.pref_lo: float = -950.0
        self.pref_hi: float = 350.0
        self.pref_default_lo: float = -950.0
        self.pref_default_hi: float = 350.0
        # True only while the JOB lines hold user edits made in this
        # session (slider/spin/viewer-line drags).  Every programmatic
        # sync (load, auto-place) clears it: the combined Process &
        # Export stage 2 uses it to distinguish "deliver the lines the
        # user adjusted" from "deliver the freshly detected lines".
        self.pref_dirty: bool = False
        self._pref_z_explicit: int | None = None
        self._pref_pos: int | None = None      # X (sagittal) or Y (coronal) of the preview
        self._job_kind: str = "process"
        self._job_progress_mode: str = "staged"   # "staged" | "real" (0M)
        # Default export folder: user preference persisted in settings.json
        # (Part A).  Falls back to cleanCT\export when no setting exists.
        try:
            _saved_root = str(bundle_export.load_settings(STATE).get("save_root") or "").strip()
        except Exception:
            _saved_root = ""
        self.save_root: str = _saved_root or str(bundle_export.default_save_root())
        # Export format preference (audit 0M): "both" | "dicom" | "nifti".
        try:
            _saved_fmt = str(bundle_export.load_settings(STATE)
                             .get("export_format") or "").strip()
        except Exception:
            _saved_fmt = ""
        self.export_format: str = (_saved_fmt
                                   if _saved_fmt in bundle_export.EXPORT_FORMATS
                                   else bundle_export.FORMAT_BOTH)
        # Start folder for Save and Open checkpoint: the folder of the last
        # save, open or choice (settings.json). Empty until the first one.
        try:
            self.checkpoint_dir: str = str(bundle_export.load_settings(STATE)
                                           .get("checkpoint_dir") or "").strip()
        except Exception:
            self.checkpoint_dir = ""
        self._air_crop_enabled: bool = True
        # Air-detected wood bounds (fractions) for the auto guide lines,
        # refreshed on every specimen load from the robust envelope.
        self._wood_bounds: dict | None = None
        self._wood_bounds_raw: dict | None = None
        # Auto Snap to Detection (audit 0AG): the copy layer that maps the
        # frozen detection onto the cut lines.  Armed by default; a manual
        # line edit SUSPENDS it until the next detection (load/re-detect).
        # ``_applying_auto_snap`` guards the programmatic writes so they
        # can never self-suspend.
        self._auto_snap_suspended: bool = False
        self._applying_auto_snap: bool = False

        self._active_worker: WorkerThread | None = None
        self._preview_worker: WorkerThread | None = None
        self._preview_generation = 0
        self._preview_applied_generation = -1
        self._preview_pending_request: dict | None = None
        # Results longitudinal view of a raw scan: the predicted lines preview
        self._results_long_key: tuple | None = None
        self._results_long_gen = 0
        self._results_workers: list = []
        self._long_pos: int | None = None          # longitudinal position; None = middle
        self._long_timer = QTimer(self)
        self._long_timer.setSingleShot(True)
        self._long_timer.timeout.connect(self._refresh_results_long)
        self._closing = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._fetch_prefs_preview)
        # threshold-defaults adoption guard (one lazy adoption per specimen)
        self._thresh_defaults_stale = True
        # async specimen loading state
        self._loading: bool = False
        self._pending_select: tuple[str, str] | None = None
        self._load_worker: WorkerThread | None = None
        # Keep each loader thread alive through its finished signal: result
        # delivery may precede the worker thread's return from run().
        self._load_workers: list[WorkerThread] = []
        # specimen panel state (search filter, session-hidden built-ins,
        # lazy on-disk size scan generation)
        self._filter_text: str = ""
        self._hidden_builtins: set[tuple[str, str]] = set()
        self._specimen_meta_generation = 0
        # every size-scan thread stays referenced until it finishes: a
        # running QThread garbage-collected mid-run hard-crashes (same
        # policy as the load workers above)
        self._specimen_meta_workers: list[WorkerThread] = []
        self._header_items: list[QListWidgetItem] = []
        self._empty_row: QListWidgetItem | None = None

        self._init_ui()
        self._wrap_long_labels()
        # the app always opens centered (idempotent; main.py re-applies it
        # before show(): this also covers direct construction, e.g. the
        # native test harness)
        self.center_on_screen()
        self._log_action("cleanCT native workstation application initialized")
        self._check_gpu()
        self._refresh_sidebar()
        self._update_lateral_panel_for_plane()
        first_specimen = next((self.sample_list.item(i).data(Qt.UserRole)
                               for i in range(self.sample_list.count())
                               if self.sample_list.item(i).data(Qt.UserRole)), None)
        if first_specimen:
            self._select_sample(*first_specimen)
        else:
            self._set_empty_state(True)
            self._set_job_gates(process_ready=False)

    # the header's state chip: text and pill style for each state of a specimen
    _STATE_CHIPS = {
        "unprocessed": ("Not processed", "pill-warn"),
        "processed": ("Processed", "pill-ok"),
        "exported": ("Exported", "pill-accent"),
    }

    def _set_state_chip(self, kind: str | None) -> None:
        """Show the specimen's state next to its name; None hides the chip."""
        if kind is None:
            self.lbl_state_chip.setVisible(False)
            return
        text, role = self._STATE_CHIPS[kind]
        self.lbl_state_chip.setText(text)
        theme.set_role(self.lbl_state_chip, role)
        self.lbl_state_chip.setVisible(True)

    def _set_empty_state(self, empty: bool):
        """Show the production first-run prompt when no specimen is loaded."""
        if not hasattr(self, "empty_state"):
            return
        if empty:
            self._set_state_chip(None)
        snapshot = bool(getattr(self, "_checkpoint_snapshot_only", False))
        show_empty = bool(empty and not snapshot)
        self.empty_state.setVisible(show_empty)
        # The stack stays visible: toggling it can unmount an active
        # snapshot view (e.g. a checkpoint-only session), so only the
        # empty-state card changes its visibility.
        if hasattr(self, "stack") and not self.stack.isVisible():
            self.stack.setVisible(True)

    # ------------------------------------------------------------------ async load
    def _select_sample(self, ds: str, sample: str, _async: bool = True):
        """Select a specimen.  The heavy payload build (DICOM reads + bounds
        detection) runs on a WORKER thread so the window paints immediately
        and the GUI never blocks: the earlier synchronous build froze the
        whole interface for seconds on the 24 µm volumes.  ``_async=False``
        drains synchronously (test harness only)."""
        if self._closing:
            return          # window is going away: no new loader thread
        if _async:
            if self._loading:
                self._pending_select = (ds, sample)   # honor the LAST click
                return
            self._loading = True
            self._pending_select = None
            self._set_job_gates(process_ready=False)
            self.lbl_sample_sub.setText("Loading specimen…")
            self._log_action(f"Loading specimen: {ds}/{sample}")
            worker = WorkerThread(viewer_core.build_payload, ds, sample)
            self._load_worker = worker
            self._load_workers.append(worker)
            worker.succeeded.connect(
                lambda p, d=ds, s=sample: self._apply_sample_payload(d, s, p))
            worker.failed.connect(self._on_load_failed)
            worker.finished.connect(self._on_load_worker_finished)
            worker.start()
            return
        p = viewer_core.build_payload(ds, sample)
        self._apply_sample_payload(ds, sample, p)

    def _on_load_worker_finished(self):
        worker = self.sender()
        if worker in self._load_workers:
            self._load_workers.remove(worker)
        if self._load_worker is worker:
            self._load_worker = None

    def _continue_pending_select(self, completed: tuple[str, str]) -> None:
        pending = self._pending_select
        self._pending_select = None
        if pending and pending != completed:
            self._select_sample(*pending)

    def _on_load_failed(self, err: str):
        self._loading = False
        self._log_action(f"specimen load failed: {err}")
        if self._checkpoint_snapshot_only:
            self._pending_view_restore = None
            self._pending_view_restore_kind = ""
            self.lbl_sample_sub.setText(
                f"Checkpoint preview snapshot: source could not be loaded: {err}")
            self.lbl_export_status.setText("Snapshot only, source unavailable")
            self._set_empty_state(False)
            self._set_job_gates(process_ready=False)
            # Defensively repaint the saved preview so a snapshot-only
            # failure always leaves the checkpoint image on screen.
            snap = self._last_pref_preview or {}
            png = snap.get("png")
            if png:
                try:
                    self.pref_viewer.setPixmap(
                        _b64_to_pixmap(png), int(snap.get("n_slices") or 0))
                except Exception:
                    pass
        else:
            self.payload = None
            self._last_pref_preview = None
            self.lbl_sample_title.setText("No specimen loaded")
            self.lbl_sample_sub.setText(f"Load failed: {err}")
            self.kpi_banner.updateMetrics({"empty": True})
            self.viewer_3d.setData(None)
            self._set_empty_state(True)
            self._set_job_gates(process_ready=False)
        if self._pending_select:
            nxt = self._pending_select
            self._pending_select = None
            self._select_sample(*nxt)

    def _wait_for_load(self, timeout_s: float = 300.0):
        """Drain a pending async load synchronously (test harness)."""
        t0 = time.time()
        while self._loading and self._load_worker is not None and \
                time.time() - t0 < timeout_s:
            if not self._load_worker.isRunning():
                break
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            time.sleep(0.02)
        if self._pending_select:
            nxt = self._pending_select
            self._pending_select = None
            self._select_sample(*nxt, _async=False)

    def _log_action(self, msg: str):
        """Record one action: the activity drawer keeps every line; the sidebar
        shows the latest one on a single line, elided to fit, with the full text
        in its tooltip. Lines start with a capital, like the rest of the copy."""
        now_str = datetime.now().strftime("%H:%M:%S")
        sentence = msg[:1].upper() + msg[1:]
        if hasattr(self, "log_view") and self.log_view:
            self.log_view.append(f"[{now_str}] {sentence}")
        if hasattr(self, "lbl_log_last") and self.lbl_log_last:
            line = f"{now_str}  {sentence}"
            width = max(self.lbl_log_last.width(), 220)
            self.lbl_log_last.setText(
                self.lbl_log_last.fontMetrics().elidedText(line, Qt.ElideRight, width))
            self.lbl_log_last.setToolTip(f"[{now_str}] {sentence}")

    def _set_log_open(self, opened: bool) -> None:
        self.log_view.setVisible(opened)
        self.btn_log_toggle.setText("Hide activity" if opened else "Show activity")

    def _clear_log(self) -> None:
        self.log_view.clear()
        self.lbl_log_last.setText("")
        self.lbl_log_last.setToolTip("")

    def center_on_screen(self):
        """Center the window on the screen's AVAILABLE geometry (the area
        inside the taskbar), clamped so the frame never lands partially
        off-screen.  Called before show(): the app always opens centered,
        aesthetic and convenient, at the correct default size."""
        scr = self.screen()
        if scr is None:
            from PySide6.QtGui import QGuiApplication
            scr = QGuiApplication.primaryScreen()
        if scr is None:
            return
        avail = scr.availableGeometry()
        # default audited size, clamped down on screens smaller than it
        # (no adjustSize: it would shrink the window to its layout minimum
        # instead of the audited default)
        self.resize(min(1540, avail.width()), min(960, avail.height()))
        fw, fh = self.frameGeometry().width(), self.frameGeometry().height()
        x = avail.x() + max(0, (avail.width() - min(fw, avail.width())) // 2)
        y = avail.y() + max(0, (avail.height() - min(fh, avail.height())) // 2)
        self.move(x, y)

    def _set_empty_text(self, unprocessed: bool) -> None:
        """Say what is missing: no scan yet, or a scan not processed yet."""
        text = ("Run Process to see the stripped result."
                if unprocessed else "Load a scan to see it here.")
        for viewer in (self.axial_viewer, self.long_viewer, self.viewer_3d):
            viewer.set_empty_text(text)

    def _apply_sample_payload(self, ds: str, sample: str, p: dict):
        """GUI-thread application of a finished specimen payload: header,
        viewers, preferences state and detection alignment (see
        _select_sample for the async dispatch).  An unprocessed specimen
        (fresh custom series) takes the graceful not-processed path."""
        self._loading = False
        self._set_empty_text(bool(p.get("unprocessed")))
        self._results_long_key = None
        self._long_pos = None
        self.long_viewer.setPixmap(QPixmap(), 1)   # never show the previous specimen's view
        try:
            if p.get("unprocessed"):
                self._apply_unprocessed_payload(ds, sample, p)
            else:
                self._set_job_gates(process_ready=True)
                self.dataset = ds
                self.sample = sample
                self.lbl_sample_title.setText(sample)
                ds_label = {"24um": "24 µm dataset",
                            "66um": "66.2 µm dataset"}.get(ds, "Custom specimen")
                # the title already names the specimen; the subtitle says what it is
                self.lbl_sample_sub.setText(
                    f"{ds_label}, micro-CT reconstruction"
                    if ds != "custom"
                    else "User-loaded scan")
                self._set_state_chip("processed")
                self._log_action(f"Loaded specimen: {ds}/{sample}")
                self._apply_payload_state(p)
            self._set_empty_state(False)
            if self._pending_view_restore is not None:
                state = self._pending_view_restore
                kind = self._pending_view_restore_kind
                self._pending_view_restore = None
                self._pending_view_restore_kind = ""
                generation = self._apply_checkpoint_controls(state, schedule=True)
                if kind == "history":
                    self._history_restore_generation = generation
                self._checkpoint_snapshot_only = False
        finally:
            self._applying_auto_snap = False
            self._continue_pending_select((ds, sample))

    def _apply_unprocessed_payload(self, ds: str, sample: str, p: dict):
        """Registered but not processed (fresh custom specimen): show the
        scan metadata, the ORIGINAL reconstruction viewers, and the
        PRE-PROCESS air-top / metal-top detection as auto-placed guide
        lines: so the user can verify the detection BEFORE committing to
        a processing run.  Export / Apply stay gated until the pipeline
        has run; the axial scrubber scrubs the raw scan."""
        self.dataset = ds
        self.sample = sample
        self.payload = p
        # Programmatic line sync is the auto copy layer (0AG): never a
        # user edit; the outer payload apply clears the guard.
        self._applying_auto_snap = True
        self.lbl_sample_title.setText(sample)
        rep = p.get("report") or {}
        self._set_intensity_controls(rep)
        n = int(rep.get("n_slices") or 0)
        vox = float(rep.get("voxel_mm") or 0.0)
        # the title already names the specimen: the subtitle says only the state
        self.lbl_sample_sub.setText("Check the detection guides, then run Process.")
        self._set_state_chip("unprocessed")
        self._set_export_source_kind(
            str(p.get("source_kind") or rep.get("source_kind") or "dicom"))
        self.kpi_banner.updateMetrics({"empty": True})
        self.viewer_3d.setData(None)

        # Preferences geometry from the scan-native preview source
        # (whole scan = delivery, margins 0) so the prefs page matches
        # what a processed specimen shows.
        self.pref_cut = n
        self.pref_margin = 0
        self.pref_keep = 0
        hi = max(1, n)
        self.spin_cut.setRange(0, hi)
        self.slider_cut.setRange(0, hi)
        self.spin_margin.setRange(0, max(1, min(100, n)))
        self.slider_margin.setRange(0, max(1, min(100, n)))
        self.spin_keep.setRange(0, hi)
        self.slider_keep.setRange(0, hi)
        self.spin_cut.setValue(self.pref_cut)
        self.slider_cut.setValue(self.pref_cut)
        self.spin_margin.setValue(0)
        self.slider_margin.setValue(0)
        self.spin_keep.setValue(0)
        self.slider_keep.setValue(0)
        self.pref_viewer.setCut(self.pref_cut)
        self.pref_viewer.setKeep(self.pref_keep)
        self.pref_viewer.setPlane(self.pref_plane)
        self._pref_z_explicit = None
        self._pref_pos = None

        # Declare the REAL slice count before any preview lands: Keep/Cut
        # placement (and later snaps) must never be clamped to the stale
        # preview-space default (the defect behind "Snap to detection"
        # pinning large volumes at the old preview n).
        self.pref_viewer.setSliceCount(n)

        # Detection guides: the payload carries the pre-process bounds
        # (same shared detection the previews use).  Auto-place Keep ≡ air
        # top, Cut ≡ metal top exactly like a processed load, plus the
        # lateral Y/X envelope.
        self._wood_bounds = None
        self._wood_bounds_raw = None
        self.pref_viewer.setAutoZ(None)
        b = p.get("bounds")
        if b and b.get("H") and b.get("W"):
            bf = {
                "x": (b["x0"] / b["W"], (b["x1"] + 1) / b["W"]),
                "y": (b["y0"] / b["H"], (b["y1"] + 1) / b["H"]),
            }
            self._wood_bounds = bf
            self._wood_bounds_raw = b
            self.pref_viewer.setAutoZ(b.get("zb") or None)
            if self.chk_auto_snap.isChecked():
                placed = self._apply_auto_snap("pre-process load")
                if placed:
                    self._log_action(
                        "auto-snap applied on pre-process detection: "
                        + ", ".join(placed))
            else:
                self.pref_viewer.setAxisBounds(
                    {"x": (0.15, 0.85), "y": (0.15, 0.85)})
                self._sync_lateral_sliders_from_viewer()
                self._log_action(
                    "auto snap OFF: detection guides shown; manual "
                    "lines kept")
            self._update_lateral_panel_for_plane()
            ainfo = b.get("anchor") or {}
            az = ainfo.get("z")
            asrc = ainfo.get("source") or "none"
            anch = (f", metal anchor z {az[0]}–{az[1]} [{asrc}]"
                    if az else ", no metal anchor")
            zbg = b.get("zb") or {}
            zg = ""
            if zbg.get("keep") is not None:
                zg += f", air top z {zbg['keep']}"
            else:
                zg += ", air top deferred (edge not clear)"
            if zbg.get("metal_top") is not None:
                zg += f", metal top z {zbg['metal_top']}"
            if zbg.get("cut") is not None:
                zg += f", halo onset z {zbg['cut']}"
            if b.get("voxel_um"):
                zg += f" @ {b['voxel_um']:.1f} µm"
            self._log_action(
                "pre-process guide lines placed (metal-first: "
                f"X {bf['x'][0]*100:.0f}–{bf['x'][1]*100:.0f}%, "
                f"Y {bf['y'][0]*100:.0f}–{bf['y'][1]*100:.0f}%"
                f"{anch}{zg})")
            anch = ainfo.get("z")
            self.lbl_anchor_hint.setText(
                f"detector anchor: slice {anch[0]}–{anch[1]} (pre-process)"
                if anch else "detector anchor:: (pre-process estimate)")
            # No-metal specimen: there is no metal-top line to place the
            # Cut on.  Default the Cut to just below the wood bottom (+2
            # safety slices) so the delivery keeps the whole specimen; the
            # user adjusts the lines freely and processes: no metal is
            # REQUIRED for a successful run.
            if zbg.get("cut") is None and zbg.get("wood_bottom") is not None:
                nb = int(rep.get("n_slices") or 0)
                default_cut = min(max(int(zbg["wood_bottom"]) + 2, 1),
                                  max(1, nb - 1))
                self.spin_cut.setValue(default_cut)
                self._log_action(
                    f"no metal platform detected: Cut defaults to "
                    f"wood bottom + 2 (slice {default_cut}); "
                    "adjust the Top Keep / Bottom Cut lines and Process "
                    "as usual")
        else:
            self.lbl_anchor_hint.setText(
                "detector anchor:: (detection unavailable pre-process)")

        # Threshold defaults: Reset (calibrated baseline) + Grayscale,
        # same lazy-adoption contract as a processed load.
        self.pref_default_lo = float(rep.get("win_lo") or viewer_core.UNPROC_WIN[0])
        self.pref_default_hi = float(rep.get("win_hi") or viewer_core.UNPROC_WIN[1])
        self._thresh_defaults_stale = True
        self._sync_threshold_defaults()

        self._update_range_summary()
        # Programmatic sync complete: the lines below now hold the
        # detection (auto-placed), not user edits.
        self.pref_dirty = False
        # Live ORIGINAL previews (sagittal/coronal/axial all work —
        # nothing here needs report.json or the stripped volume)
        self._schedule_prefs_preview()
        self._refresh_results_views()     # the predicted lines on the Results view
        # Axial scrubber over the raw scan, parked mid-height
        if n:
            self.axial_slider.setRange(0, n - 1)
            self.axial_slider.setValue(n // 2)
        self._set_job_gates(process_ready=False)
        self._log_action(
            f"{sample} registered ({n} slices @ {vox:.1f} µm): "
            "not processed yet; detection guides are live: verify them, "
            "then run Process to detect and cut")

    def _boundary_widgets(self) -> list:
        names = ("spin_cut", "slider_cut", "spin_keep", "slider_keep",
                 "spin_left", "slider_left", "spin_right", "slider_right",
                 "spin_top", "slider_top", "spin_bottom", "slider_bottom",
                 "spin_margin", "slider_margin", "btn_snap_lines",
                 "chk_auto_snap", "btn_th_reset", "btn_th_full",
                 "btn_th_wood", "btn_th_contrast", "btn_th_metal")
        return [getattr(self, name) for name in names if hasattr(self, name)]

    def _set_boundary_enabled(self, enabled: bool) -> None:
        for widget in self._boundary_widgets():
            widget.setEnabled(enabled)

    def _gate_tip(self, btn, busy: bool) -> None:
        """Say why a control is unavailable while a job runs. The control's own
        tooltip is kept, and the busy reason is added below it."""
        bases = self.__dict__.setdefault("_base_tips", {})
        base = bases.setdefault(id(btn), btn.toolTip())
        btn.setToolTip(f"{base}\n{BUSY_NOTE}".strip() if busy else base)

    def _set_job_gates(self, process_ready: bool):
        """Apply action availability from payload, processing, and load state."""
        has_payload = self.payload is not None
        unprocessed = bool((self.payload or {}).get("unprocessed"))
        busy = bool(self._loading or
                    (self._active_worker is not None and self._active_worker.isRunning()))
        can_process = has_payload and not busy
        self.btn_process.setEnabled(can_process)
        self.btn_process_export.setEnabled(can_process)
        self.btn_load.setEnabled(not busy)
        self.sample_list.setEnabled(not busy)
        if hasattr(self, "edit_search"):
            self.edit_search.setEnabled(not busy)
        if hasattr(self, "spec_spinner"):
            self.spec_spinner.setRunning(busy)
        self._update_specimen_actions()
        if hasattr(self, "combo_preview_history"):
            self.combo_preview_history.setEnabled(not busy)
        if hasattr(self, "btn_empty_load"):
            self.btn_empty_load.setEnabled(not busy)
        if hasattr(self, "btn_load_checkpoint"):
            self.btn_load_checkpoint.setEnabled(not busy)
        if hasattr(self, "btn_save_checkpoint"):
            self.btn_save_checkpoint.setEnabled(
                not busy and (self._last_pref_preview is not None or
                              self._checkpoint_snapshot_only))
        # the preview of a freshly processed specimen is prepared after its load:
        # say so, and say why Save checkpoint waits for it
        preparing = bool(has_payload and not busy and not unprocessed
                         and self._last_pref_preview is None
                         and not self._checkpoint_snapshot_only)
        if hasattr(self, "lbl_preview_status"):
            self.lbl_preview_status.setText("Preparing the preview…" if preparing else "")
        self.btn_export.setEnabled(bool(process_ready and has_payload and not busy))
        self.btn_export.setToolTip(
            BUSY_NOTE if busy else
            "" if process_ready and has_payload else
            ("Load a specimen before exporting." if not has_payload else
             "This specimen has not been processed yet. Run Process "
             "(or Apply lines) first."))
        self.btn_apply_prefs.setEnabled(bool(process_ready and has_payload and not busy))
        self.btn_apply_prefs.setToolTip(
            BUSY_NOTE if busy else
            "" if process_ready and has_payload else
            ("Load a specimen before applying cut lines." if not has_payload else
             "Process the specimen first. The detection needs the pipeline "
             "outputs (report.json and the stripped volume)."))
        for btn in (self.btn_load, self.btn_process, self.btn_process_export,
                    getattr(self, "btn_empty_load", None),
                    getattr(self, "btn_load_checkpoint", None),
                    getattr(self, "btn_save_checkpoint", None)):
            if btn is not None:
                self._gate_tip(btn, busy)
        self._set_boundary_enabled(not busy)
        if hasattr(self, "btn_save_checkpoint") and not busy and has_payload \
                and not self.btn_save_checkpoint.isEnabled():
            # after the busy tips above: the note says why Save waits
            base = self.__dict__.get("_base_tips", {}).get(
                id(self.btn_save_checkpoint), self.btn_save_checkpoint.toolTip())
            self.btn_save_checkpoint.setToolTip(f"{base}\nAvailable once the preview is ready.")
        if process_ready:
            self._update_range_summary()          # restores the enabled state

    # ---------------------------------------------------------------- UI Setup
    def _keyed(self, label: QLabel, build) -> QLabel:
        """A label whose text is a colour key; it is re-rendered on a theme change."""
        label.setText(build())
        self._key_rows.append((label, build))
        return label

    def _init_ui(self):
        self._key_rows: list = []      # (label, builder) for the colour keys
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        root_layout = QHBoxLayout(main_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---------------- 1. Sidebar ----------------
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(280)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 16, 14, 14)
        side_layout.setSpacing(8)     # tight: the specimen list keeps four rows at 720 px

        # Brand Header (Vertically centered, elegant alignment)
        brand_card = QFrame()
        brand_card.setObjectName("brand_card")
        brand_layout = QHBoxLayout(brand_card)
        brand_layout.setContentsMargins(2, 2, 2, 2)
        brand_layout.setSpacing(12)
        brand_layout.setAlignment(Qt.AlignVCenter)

        lbl_logo = QLabel()
        lbl_logo.setFixedSize(46, 46)
        lbl_logo.setAlignment(Qt.AlignCenter)
        logo_png = (icon_utils.icons_dir(ROOT) or ROOT) / "icon_256x256.png"
        if logo_png.exists():
            pm = QPixmap(str(logo_png)).scaled(46, 46, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl_logo.setPixmap(pm)
        brand_layout.addWidget(lbl_logo)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        brand_text.setAlignment(Qt.AlignVCenter)

        lbl_title = QLabel(self._brand_html())
        self.lbl_brand = lbl_title
        lbl_title.setTextFormat(Qt.RichText)
        lbl_title.setFont(QFont("Segoe UI", 17, QFont.Bold))

        lbl_sub = QLabel("Wood CT metal-base removal")
        lbl_sub.setWordWrap(True)
        theme.set_role(lbl_sub, "secondary")

        brand_text.addWidget(lbl_title)
        brand_text.addWidget(lbl_sub)
        brand_layout.addLayout(brand_text)
        brand_layout.addStretch()
        btn_about = QPushButton("About")
        btn_about.setObjectName("btn_about")
        theme.set_role(btn_about, "link")
        btn_about.clicked.connect(self._open_about_dialog)
        brand_layout.addWidget(btn_about, 0, Qt.AlignTop)
        side_layout.addWidget(brand_card)

        # GPU Chip
        self.lbl_gpu = QLabel("Checking GPU…")
        theme.set_role(self.lbl_gpu, "chip-info")
        side_layout.addWidget(self.lbl_gpu)

        # Specimen panel: section header with live count and busy spinner
        spec_head = QHBoxLayout()
        spec_head.setSpacing(6)
        lbl_specimens = QLabel("Specimens")
        theme.set_role(lbl_specimens, "hint")
        self.lbl_spec_count = QLabel("")
        theme.set_role(self.lbl_spec_count, "hint")
        self.spec_spinner = BusySpinner(self)
        spec_head.addWidget(lbl_specimens)
        spec_head.addStretch()
        spec_head.addWidget(self.lbl_spec_count)
        spec_head.addSpacing(4)
        spec_head.addWidget(self.spec_spinner)
        side_layout.addLayout(spec_head)

        # Search / filter box
        self.edit_search = QLineEdit()
        self.edit_search.setObjectName("edit_search")
        self.edit_search.setPlaceholderText("Filter specimens…")
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.setToolTip(
            "Filter the specimen list by name as you type.\n"
            "Clear the field to show every specimen.")
        self.edit_search.textChanged.connect(self._apply_specimen_filter)
        side_layout.addWidget(self.edit_search)

        # Specimen List (two-line rows via SpecimenDelegate)
        self.sample_list = QListWidget()
        self.sample_list.setObjectName("sample_list")
        self.sample_list.setItemDelegate(SpecimenDelegate(self.sample_list))
        self.sample_list.setMouseTracking(True)
        # rows are the list's full width: a sideways bar would only show clipping
        self.sample_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sample_list.itemClicked.connect(self._on_sample_clicked)
        self.sample_list.itemSelectionChanged.connect(
            self._update_specimen_actions)
        self.sample_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sample_list.customContextMenuRequested.connect(
            self._specimen_context_menu)
        side_layout.addWidget(self.sample_list, 1)

        # Keyboard shortcuts on the list (also shown in the context menu):
        # F2 = rename the selected loaded specimen, Del = remove it.
        self._f2_shortcut = QShortcut(QKeySequence("F2"), self.sample_list)
        self._f2_shortcut.setContext(Qt.WidgetShortcut)
        self._f2_shortcut.activated.connect(self._rename_selected)
        self._del_shortcut = QShortcut(QKeySequence.Delete, self.sample_list)
        self._del_shortcut.setContext(Qt.WidgetShortcut)
        self._del_shortcut.activated.connect(self._remove_selected)
        for sequence, slot in (("Ctrl+O", self._open_load_dialog),
                               ("Ctrl+R", self._process_selected),
                               ("Ctrl+E", self._export_bundle),
                               ("Ctrl+S", self._open_save_checkpoint)):
            QShortcut(QKeySequence(sequence), self).activated.connect(slot)

        # Row actions: rename / duplicate / locate / remove
        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.btn_rename = QPushButton("Rename")
        self.btn_duplicate = QPushButton("Copy")
        self.btn_locate = QPushButton("Find")
        self.btn_remove = QPushButton("Remove")
        for _b in (self.btn_rename, self.btn_duplicate,
                   self.btn_locate, self.btn_remove):
            _b.setObjectName("btn_specimen_action")
            _b.setEnabled(False)
            action_row.addWidget(_b, 1)
        side_layout.addLayout(action_row)
        self.btn_rename.clicked.connect(self._rename_selected)
        self.btn_duplicate.clicked.connect(self._duplicate_selected)
        self.btn_locate.clicked.connect(self._locate_selected)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_rename.setToolTip(
            "Rename the selected loaded specimen (registry ID and link).\n"
            "Shortcut: F2. Built-in dataset specimens keep their names.")
        self.btn_duplicate.setToolTip(
            "Register the same scan again under a new ID: no data is copied.\n"
            "Built-in dataset specimens cannot be duplicated.")
        self.btn_locate.setToolTip(
            "Show the specimen's source folder (loaded scans) or its\n"
            "processed-output folder (built-in datasets) in Explorer.")
        self.btn_remove.setToolTip(
            "Remove the selected specimen from the list. Shortcut: Del.\n"
            "Loaded scans: unregistered: source, processed results, and\n"
            "exports are kept. Built-in specimens are hidden until restart.")

        # Sidebar Actions
        self.btn_load = QPushButton("Load scan…")
        self.btn_load.setObjectName("btn_load")
        self.btn_load.setToolTip(
            "Register a DICOM series folder, a multipage TIFF stack or\n"
            "slice folder, or one 3-D NIfTI volume (.nii / .nii.gz).")
        self.btn_load.clicked.connect(self._open_load_dialog)
        self.btn_load.setToolTip(self.btn_load.toolTip() + "\nShortcut: Ctrl+O")
        side_layout.addWidget(self.btn_load)

        # Checkpoint actions: stacked full-width so the labels are never
        # clipped by the 280 px sidebar (the side-by-side row squeezed
        # them into "ave checkpoint…").
        self.btn_save_checkpoint = QPushButton("Save checkpoint")
        self.btn_save_checkpoint.setObjectName("btn_save_checkpoint")
        theme.set_role(self.btn_save_checkpoint, "compact")
        self.btn_save_checkpoint.setToolTip(
            "Save the current preview and cut-line settings for a quick restore.")
        self.btn_save_checkpoint.clicked.connect(self._open_save_checkpoint)
        self.btn_save_checkpoint.setToolTip(
            "Save the current preview and cut-line settings for a quick restore.\n"
            "Shortcut: Ctrl+S")
        self.btn_load_checkpoint = QPushButton("Open checkpoint")
        self.btn_load_checkpoint.setObjectName("btn_load_checkpoint")
        theme.set_role(self.btn_load_checkpoint, "compact")
        self.btn_load_checkpoint.setToolTip(
            "Restore a saved checkpoint (.ctcheckpoint.json): the preview,\n"
            "cut lines and view settings come back instantly; the source\n"
            "reconnects when it is still registered at the same location.")
        self.btn_load_checkpoint.clicked.connect(self._open_load_checkpoint)
        checkpoint_row = QHBoxLayout()
        checkpoint_row.setSpacing(6)
        checkpoint_row.addWidget(self.btn_save_checkpoint, 1)
        checkpoint_row.addWidget(self.btn_load_checkpoint, 1)
        side_layout.addLayout(checkpoint_row)

        history_label = QLabel("Preview history, this session")
        theme.set_role(history_label, "hint")
        side_layout.addWidget(history_label)
        self.combo_preview_history = QComboBox()
        self.combo_preview_history.setObjectName("combo_preview_history")
        self.combo_preview_history.addItem("No preview history yet")
        self.combo_preview_history.setToolTip(
            "Preview states remain available until cleanCT exits.")
        self.combo_preview_history.currentIndexChanged.connect(
            self._restore_session_history)
        side_layout.addWidget(self.combo_preview_history)

        self.btn_process = QPushButton("Process")
        self.btn_process.setObjectName("btn_process")
        self.btn_process.setProperty("class", "btn-primary")
        self.btn_process.clicked.connect(self._process_selected)
        self.btn_process.setToolTip("Shortcut: Ctrl+R")
        side_layout.addWidget(self.btn_process)

        # One-pass delivery (audit 0O): process then export in a single job.
        self.btn_process_export = QPushButton("Process and export")
        self.btn_process_export.setObjectName("btn_process_export")
        self.btn_process_export.setToolTip(
            "One-pass delivery: detect & cut (same as Process),\n"
            "then export the bundle to the destination folder using the\n"
            "selected Format (DICOM only / DICOM + NIfTI / NIfTI only).")
        self.btn_process_export.clicked.connect(self._process_and_export)
        side_layout.addWidget(self.btn_process_export)

        # Job Box
        self.job_box = QFrame()
        self.job_box.setObjectName("job_box")
        self.job_box.setVisible(False)
        # one timer for the hide delay: a new job stops it instead of letting a
        # stale single-shot hide the box while the next job runs
        self._job_box_hide_timer = QTimer(self)
        self._job_box_hide_timer.setSingleShot(True)
        self._job_box_hide_timer.setInterval(2500)
        self._job_box_hide_timer.timeout.connect(
            lambda: self.job_box.setVisible(False))
        # one row, in the bottom status bar: phase, progress, time left
        job_layout = QHBoxLayout(self.job_box)
        job_layout.setContentsMargins(0, 0, 0, 0)
        job_layout.setSpacing(12)

        self.lbl_job_phase = QLabel("Processing…")
        theme.set_role(self.lbl_job_phase, "accent")
        self.job_progress = QProgressBar()
        self.job_progress.setFixedSize(220, 8)
        self.job_progress.setRange(0, 100)
        self.job_progress.setValue(0)
        self.lbl_job_eta = QLabel("~8s left")
        theme.set_role(self.lbl_job_eta, "secondary")
        # the detail line is kept for the tooltip; the row stays one line
        self.lbl_job_sub = QLabel("Initializing backend…")
        theme.set_role(self.lbl_job_sub, "hint")
        self.lbl_job_sub.setVisible(False)
        job_layout.addWidget(self.lbl_job_phase)
        job_layout.addWidget(self.job_progress)
        job_layout.addWidget(self.lbl_job_eta)
        job_layout.addWidget(self.lbl_job_sub)

        # Activity: the latest message stays visible; the full log opens on demand
        box_log = QFrame()
        box_log.setObjectName("box_action_log")
        log_layout = QVBoxLayout(box_log)
        log_layout.setContentsMargins(10, 6, 10, 6)
        log_layout.setSpacing(6)

        log_head = QHBoxLayout()
        self.btn_log_toggle = QPushButton("Show activity")
        self.btn_log_toggle.setObjectName("btn_log_toggle")
        self.btn_log_toggle.setCheckable(True)
        theme.set_role(self.btn_log_toggle, "ghost")
        self.btn_log_toggle.toggled.connect(self._set_log_open)
        log_head.addWidget(self.btn_log_toggle)
        log_head.addStretch()
        btn_clear_log = QPushButton("Clear")
        theme.set_role(btn_clear_log, "ghost")
        btn_clear_log.clicked.connect(self._clear_log)
        log_head.addWidget(btn_clear_log)
        log_layout.addLayout(log_head)
        self.lbl_log_last = QLabel("")
        self.lbl_log_last.setObjectName("lbl_log_last")
        self.lbl_log_last.setWordWrap(False)     # one line; _log_action elides it
        theme.set_role(self.lbl_log_last, "hint")
        log_layout.addWidget(self.lbl_log_last)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(120)
        self.log_view.setMaximumHeight(220)
        # wrap at word boundaries; a mid-word break reads badly
        from PySide6.QtGui import QTextOption
        self.log_view.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.log_view.setObjectName("log_view")
        self.log_view.setVisible(False)
        log_layout.addWidget(self.log_view)
        side_layout.addWidget(box_log)

        # About Button

        root_layout.addWidget(sidebar)

        # ---------------- 2. Main Area ----------------
        main_area = QFrame()
        main_area.setObjectName("main_area")
        main_area_layout = QVBoxLayout(main_area)
        main_area_layout.setContentsMargins(20, 14, 20, 12)
        main_area_layout.setSpacing(8)

        # Top Header Bar (Title + KPI Banner)
        top_bar = QVBoxLayout()
        top_bar.setSpacing(8)

        # title and subtitle share one baseline: one line of header, not two
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        self.lbl_sample_title = QLabel("Select a sample")
        theme.set_role(self.lbl_sample_title, "title")
        # the state of this specimen at a glance: Not processed, Processed or Exported
        self.lbl_state_chip = QLabel("")
        self.lbl_state_chip.setObjectName("lbl_state_chip")
        self.lbl_state_chip.setVisible(False)
        self.lbl_sample_sub = QLabel("Pick a dataset & sample from the sidebar")
        theme.set_role(self.lbl_sample_sub, "secondary")
        title_row.addWidget(self.lbl_sample_title, 0, Qt.AlignBaseline)
        title_row.addWidget(self.lbl_state_chip, 0, Qt.AlignBaseline)
        title_row.addWidget(self.lbl_sample_sub, 1, Qt.AlignBaseline)
        top_bar.addLayout(title_row)

        self.kpi_banner = KPIBanner()
        top_bar.addWidget(self.kpi_banner)
        main_area_layout.addLayout(top_bar)

        self.empty_state = QFrame()
        self.empty_state.setObjectName("empty_state")
        empty_layout = QHBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(18, 12, 18, 12)
        empty_copy = QVBoxLayout()
        self.lbl_empty_title = QLabel("Load a scan to begin")
        theme.set_role(self.lbl_empty_title, "kpi-value")
        self.lbl_empty_copy = QLabel(
            "Choose a DICOM series, TIFF stack, or 3-D NIfTI file to preview, "
            "set cut lines, process, and export.")
        self.lbl_empty_copy.setWordWrap(True)
        theme.set_role(self.lbl_empty_copy, "secondary")
        empty_copy.addWidget(self.lbl_empty_title)
        empty_copy.addWidget(self.lbl_empty_copy)
        empty_layout.addLayout(empty_copy, 1)
        self.btn_empty_load = QPushButton("Load scan…")
        self.btn_empty_load.setObjectName("btn_empty_load")
        self.btn_empty_load.clicked.connect(self._open_load_dialog)
        empty_layout.addWidget(self.btn_empty_load)
        main_area_layout.addWidget(self.empty_state)
        self.empty_state.hide()

        # Mode Tab Bar & Export Bar Row
        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)

        # Mode Tabs: [ Auto | Preferences ]
        self.btn_tab_auto = QPushButton("Results")
        self.btn_tab_auto.setObjectName("tab_btn_auto")
        self.btn_tab_auto.setProperty("active", "true")
        self.btn_tab_auto.setCheckable(True)
        self.btn_tab_auto.setChecked(True)
        self.btn_tab_auto.clicked.connect(lambda: self._switch_tab("auto"))
        mode_row.addWidget(self.btn_tab_auto)

        self.btn_tab_prefs = QPushButton("Boundaries")
        self.btn_tab_prefs.setObjectName("tab_btn_prefs")
        self.btn_tab_prefs.setProperty("active", "false")
        self.btn_tab_prefs.setCheckable(True)
        self.btn_tab_prefs.clicked.connect(lambda: self._switch_tab("prefs"))
        mode_row.addWidget(self.btn_tab_prefs)

        mode_row.addStretch()
        # Settings sits apart from the two working tabs, at the right end
        self.btn_tab_settings = QPushButton("Settings")
        self.btn_tab_settings.setObjectName("tab_btn_settings")
        self.btn_tab_settings.setProperty("active", "false")
        self.btn_tab_settings.setCheckable(True)
        self.btn_tab_settings.clicked.connect(lambda: self._switch_tab("settings"))
        mode_row.addWidget(self.btn_tab_settings)
        for tab_button in (self.btn_tab_auto, self.btn_tab_prefs, self.btn_tab_settings):
            theme.set_role(tab_button, "tab")
        # one underlined row: the frame draws the baseline the tabs sit on
        tabbar = QFrame()
        tabbar.setObjectName("tabbar")
        tabbar.setLayout(mode_row)
        main_area_layout.addWidget(tabbar)

        # Export bar on its own row, so the tabs and the export settings do not
        # form one long row that sets the window's minimum width
        # The folder and format are set on the Settings tab. This row shows
        # where the bundle goes and starts the export; a long path is elided,
        # so it never sets the window's minimum width.
        export_row = QHBoxLayout()
        export_row.setSpacing(10)
        lbl_export_to = QLabel("Export to:")
        theme.set_role(lbl_export_to, "secondary")
        export_row.addWidget(lbl_export_to)
        self.lbl_export_dest = QLabel()
        self.lbl_export_dest.setObjectName("lbl_export_dest")
        self.lbl_export_dest.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_export_dest.setProperty("nowrap", True)     # elided, never two lines
        export_row.addWidget(self.lbl_export_dest, 1)
        self.lbl_export_format = QLabel()
        self.lbl_export_format.setObjectName("lbl_export_format")
        theme.set_role(self.lbl_export_format, "hint")
        export_row.addWidget(self.lbl_export_format)
        btn_change_dest = QPushButton("Change in Settings")
        btn_change_dest.setObjectName("btn_change_export")
        theme.set_role(btn_change_dest, "link")
        btn_change_dest.clicked.connect(lambda: self._open_settings("export"))
        export_row.addWidget(btn_change_dest)

        self.btn_export = QPushButton("Export")
        self.btn_export.setObjectName("btn_export")
        self.btn_export.clicked.connect(self._export_bundle)
        export_row.addWidget(self.btn_export)
        main_area_layout.addLayout(export_row)

        # the outcome line lives in the bottom status bar, not in the header
        self.lbl_export_status = QLabel("Ready")
        theme.set_role(self.lbl_export_status, "hint")
        self.lbl_export_status.setWordWrap(False)

        # ---------------- 3. Stacked Workspaces (Auto vs Preferences) ----------------
        self.stack = QStackedWidget()
        main_area_layout.addWidget(self.stack, 1)

        # Bottom status bar: the one place for outcome messages and job progress
        statusbar = QFrame()
        statusbar.setObjectName("statusbar")
        status_row = QHBoxLayout(statusbar)
        status_row.setContentsMargins(4, 4, 4, 0)
        status_row.setSpacing(12)
        status_row.addWidget(self.lbl_export_status, 1)
        # shown while the preview of a freshly processed specimen is prepared
        self.lbl_preview_status = QLabel("")
        self.lbl_preview_status.setObjectName("lbl_preview_status")
        theme.set_role(self.lbl_preview_status, "hint")
        status_row.addWidget(self.lbl_preview_status)
        status_row.addWidget(self.job_box)
        main_area_layout.addWidget(statusbar)

        # Page 0: Auto Tab Workspace
        # Each page scrolls sideways when the window is narrower than the page
        # needs, instead of forcing the whole window wider than the screen.
        def _scrollable(page: QWidget) -> QScrollArea:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.NoFrame)
            area.setWidget(page)
            return area

        self.page_auto = self._build_auto_page()
        self.stack.addWidget(_scrollable(self.page_auto))

        # Page 1: Preferences Tab Workspace
        self.page_prefs = self._build_prefs_page()
        self.stack.addWidget(_scrollable(self.page_prefs))

        # Page 2: Settings (appearance, export, checkpoints, shortcuts)
        self.page_settings = self._build_settings_page()
        self.stack.addWidget(_scrollable(self.page_settings))

        # every mode toggle is a segment: one size, one look, across the pages
        for name in ("btn_plane_sag", "btn_plane_cor", "btn_plane_ax",
                     "btn_guide_2l", "btn_guide_4l", "btn_long_sag", "btn_long_cor",
                     "btn_3d_simple", "btn_3d_real"):
            theme.set_role(getattr(self, name), "segment")

        root_layout.addWidget(main_area, 1)
        self._refresh_export_summary()

    # ---------------------------------------------------------------- Auto Tab UI
    def _build_auto_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        splitter = QSplitter(Qt.Horizontal)

        # ---------------- Left Column: Merged 2D Layout (Axial ABOVE Longitudinal) ----------------
        merged_2d_frame = QFrame()
        merged_2d_frame.setProperty("class", "panel")
        m2d_layout = QVBoxLayout(merged_2d_frame)
        m2d_layout.setContentsMargins(12, 10, 12, 10)
        m2d_layout.setSpacing(10)

        # 1. Top Half: Axial View (Original | Stripped side by side)
        axial_box = QVBoxLayout()
        axial_box.setSpacing(6)

        ax_head = QHBoxLayout()
        lbl_ax_title = QLabel("Axial: original and stripped")
        theme.set_role(lbl_ax_title, "section")
        ax_head.addWidget(lbl_ax_title)
        # shown while the pending lines differ from the processed run
        self.lbl_results_stale = QLabel("Lines changed")
        theme.set_role(self.lbl_results_stale, "pill-warn")
        self.lbl_results_stale.setVisible(False)
        ax_head.addWidget(self.lbl_results_stale)
        ax_head.addStretch()
        lbl_legend = self._keyed(QLabel(), lambda: (
            f"{key_swatch('wood', 'wood ROI')}  {key_swatch('metal', 'metal')}"))
        lbl_legend.setTextFormat(Qt.RichText)
        lbl_legend.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)  # never squeezed
        lbl_legend.setProperty("nowrap", True)                             # one line
        theme.set_role(lbl_legend, "hint")
        # the layout may not squeeze the legend below the width its text needs
        lbl_legend.setMinimumWidth(lbl_legend.sizeHint().width() + 4)
        ax_head.addWidget(lbl_legend)
        axial_box.addLayout(ax_head)

        self.axial_viewer = Viewer2D()
        self.axial_viewer.setGuideEnabled(False)
        self.axial_viewer.setResultsOverlay(True)
        axial_box.addWidget(self.axial_viewer, 1)

        # Axial Scrubber
        scrub_box = QHBoxLayout()
        self.axial_slider = QSlider(Qt.Horizontal)
        self.axial_slider.setRange(0, 100)
        self.axial_slider.valueChanged.connect(self._on_axial_slider_changed)
        self.lbl_axial_z = QLabel("z=0")
        self.lbl_axial_z.setFixedWidth(55)
        theme.set_role(self.lbl_axial_z, "accent")
        scrub_box.addWidget(self.axial_slider)
        scrub_box.addWidget(self.lbl_axial_z)
        axial_box.addLayout(scrub_box)
        m2d_layout.addLayout(axial_box, 1)

        # Subtle elegant divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setObjectName("divider")
        m2d_layout.addWidget(div)

        # 2. Bottom Half: Longitudinal Cut View (Sagittal | Coronal)
        long_box = QVBoxLayout()
        long_box.setSpacing(6)

        long_head = QHBoxLayout()
        lbl_long_title = QLabel("Longitudinal: cut boundary alignment")
        theme.set_role(lbl_long_title, "section")
        long_head.addWidget(lbl_long_title)
        long_head.addStretch()

        self.btn_long_sag = QPushButton("Sagittal")
        self.btn_long_sag.setProperty("active", "true")
        self.btn_long_sag.clicked.connect(lambda: self._toggle_long_view("sagittal"))
        long_head.addWidget(self.btn_long_sag)

        self.btn_long_cor = QPushButton("Coronal")
        self.btn_long_cor.setProperty("active", "false")
        self.btn_long_cor.clicked.connect(lambda: self._toggle_long_view("coronal"))
        long_head.addWidget(self.btn_long_cor)
        long_box.addLayout(long_head)

        self.long_viewer = Viewer2D()
        self.long_viewer.setGuideEnabled(False)
        self.long_viewer.setResultsOverlay(True)
        long_box.addWidget(self.long_viewer, 1)
        # position scrubber: X for the sagittal plane, Y for the coronal one
        long_scrub = QHBoxLayout()
        self.long_slider = QSlider(Qt.Horizontal)
        self.long_slider.setRange(0, 0)
        self.long_slider.valueChanged.connect(self._on_long_slider_changed)
        self.lbl_long_pos = QLabel("x=0")
        self.lbl_long_pos.setFixedWidth(55)
        theme.set_role(self.lbl_long_pos, "accent")
        long_scrub.addWidget(self.long_slider)
        long_scrub.addWidget(self.lbl_long_pos)
        long_box.addLayout(long_scrub)
        m2d_layout.addLayout(long_box, 1)

        splitter.addWidget(merged_2d_frame)

        # ---------------- Right Column: 3D Visualization ----------------
        v3d_frame = QFrame()
        v3d_frame.setProperty("class", "panel")
        v3d_layout = QVBoxLayout(v3d_frame)
        v3d_layout.setContentsMargins(12, 10, 12, 10)
        v3d_layout.setSpacing(8)

        v3d_head = QHBoxLayout()
        lbl_3d_title = QLabel("3D point cloud")
        theme.set_role(lbl_3d_title, "section")
        v3d_head.addWidget(lbl_3d_title)
        v3d_head.addStretch()

        self.btn_3d_simple = QPushButton("Simple")
        self.btn_3d_simple.setProperty("active", "true")
        self.btn_3d_simple.clicked.connect(lambda: self._set_3d_mode("simple"))
        v3d_head.addWidget(self.btn_3d_simple)

        self.btn_3d_real = QPushButton("Real 3D")
        self.btn_3d_real.setProperty("active", "false")
        self.btn_3d_real.clicked.connect(lambda: self._set_3d_mode("real"))
        v3d_head.addWidget(self.btn_3d_real)

        btn_reset_3d = QPushButton("Reset view")
        btn_reset_3d.clicked.connect(lambda: self.viewer_3d.resetView())
        v3d_head.addWidget(btn_reset_3d)

        self.btn_spin_3d = QPushButton("Spin")
        self.btn_spin_3d.setObjectName("btn_spin3d")
        self.btn_spin_3d.clicked.connect(self._toggle_spin_3d)
        v3d_head.addWidget(self.btn_spin_3d)
        v3d_layout.addLayout(v3d_head)

        self.viewer_3d = Viewer3D()
        self.viewer_3d.spinChanged.connect(self._on_spin_changed)
        v3d_layout.addWidget(self.viewer_3d, 1)

        splitter.addWidget(v3d_frame)
        splitter.setSizes([850, 690])
        layout.addWidget(splitter)
        return page

    # ---------------------------------------------------------------- Preferences Tab UI
    def _build_prefs_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        splitter = QSplitter(Qt.Horizontal)

        # Left: 2D Reconstruction Preview with Interactive Draggable Guides
        prev_frame = QFrame()
        prev_frame.setProperty("class", "panel")
        prev_layout = QVBoxLayout(prev_frame)
        prev_layout.setContentsMargins(14, 10, 14, 10)
        prev_layout.setSpacing(8)

        head_row = QHBoxLayout()
        self.lbl_pref_head = QLabel("Original scan")
        self.lbl_pref_head.setWordWrap(True)
        theme.set_role(self.lbl_pref_head, "section")
        head_row.addWidget(self.lbl_pref_head)
        head_row.addStretch()

        self.btn_plane_sag = QPushButton("Sagittal")
        self.btn_plane_sag.setProperty("active", "true")
        self.btn_plane_sag.clicked.connect(lambda: self._set_pref_plane("sagittal"))
        head_row.addWidget(self.btn_plane_sag)

        self.btn_plane_cor = QPushButton("Coronal")
        self.btn_plane_cor.setProperty("active", "false")
        self.btn_plane_cor.clicked.connect(lambda: self._set_pref_plane("coronal"))
        head_row.addWidget(self.btn_plane_cor)

        self.btn_plane_ax = QPushButton("Axial")
        self.btn_plane_ax.setProperty("active", "false")
        self.btn_plane_ax.clicked.connect(lambda: self._set_pref_plane("axial"))
        head_row.addWidget(self.btn_plane_ax)
        prev_layout.addLayout(head_row)

        # Interactive Guides Toolbar
        guide_bar = QHBoxLayout()
        guide_bar.setSpacing(10)
        self.chk_guides = QCheckBox("Interactive Guides")
        self.chk_guides.setChecked(True)
        self.chk_guides.toggled.connect(self._on_guide_toggled)
        guide_bar.addWidget(self.chk_guides)

        self.btn_guide_2l = QPushButton("2 Lines (Z Range)")
        self.btn_guide_2l.setProperty("active", "false")
        self.btn_guide_2l.clicked.connect(lambda: self._set_guide_mode("2lines"))
        guide_bar.addWidget(self.btn_guide_2l)

        self.btn_guide_4l = QPushButton("4 Lines (Box Bounds)")
        self.btn_guide_4l.setProperty("active", "true")
        self.btn_guide_4l.clicked.connect(lambda: self._set_guide_mode("4lines"))
        guide_bar.addWidget(self.btn_guide_4l)

        self.btn_snap_lines = QPushButton("Snap to detection")
        self.btn_snap_lines.setObjectName("btn_snap_lines")
        self.btn_snap_lines.setToolTip(
            "Move the Keep/Cut lines to the validated detection: the Keep "
            "line to the air-detected wood top and the Cut line to the "
            "pipeline's halo-onset cut (the metal threshold line).")
        self.btn_snap_lines.clicked.connect(self._snap_lines_to_detection)

        self.chk_auto_snap = QCheckBox("Auto snap to detection")
        self.chk_auto_snap.setChecked(True)
        self.chk_auto_snap.setToolTip(
            "Default ON: every detected load / re-detect copies the detection "
            "onto the Keep/Cut lines and the lateral box.\n"
            "Dragging any line pauses auto-snap until the next detection;\n"
            "uncheck to keep manual lines untouched across loads.")
        self.chk_auto_snap.toggled.connect(self._on_auto_snap_toggled)

        guide_bar.addStretch()
        prev_layout.addLayout(guide_bar)

        # snap and auto-snap get their own row, so the toolbar fits beside the controls
        snap_bar = QHBoxLayout()
        snap_bar.setSpacing(10)
        snap_bar.addWidget(self.btn_snap_lines)
        snap_bar.addWidget(self.chk_auto_snap)
        snap_bar.addStretch()
        lbl_hint = QLabel("drag lines to adjust")
        theme.set_role(lbl_hint, "hint")
        snap_bar.addWidget(lbl_hint)
        prev_layout.addLayout(snap_bar)

        # 2D Interactive Viewer (4 Lines enabled by default)
        self.pref_viewer = Viewer2D()
        self.pref_viewer.setGuideMode("4lines")
        self.pref_viewer.cutChanged.connect(self._on_pref_cut_dragged)
        self.pref_viewer.keepChanged.connect(self._on_pref_keep_dragged)
        self.pref_viewer.leftChanged.connect(self._on_pref_left_dragged)
        self.pref_viewer.rightChanged.connect(self._on_pref_right_dragged)
        self.pref_viewer.topChanged.connect(self._on_pref_top_dragged)
        self.pref_viewer.bottomChanged.connect(self._on_pref_bottom_dragged)
        self.pref_viewer.sliceScrubbed.connect(self._on_pref_slice_scrubbed)
        prev_layout.addWidget(self.pref_viewer, 1)

        # Slice Scrubber
        scrub_box = QHBoxLayout()
        self.pref_slider = QSlider(Qt.Horizontal)
        self.pref_slider.setRange(0, 100)
        self.pref_slider.valueChanged.connect(self._on_pref_slider_changed)
        self.lbl_pref_z = QLabel("z=0")
        self.lbl_pref_z.setFixedWidth(65)
        scrub_box.addWidget(self.pref_slider)
        scrub_box.addWidget(self.lbl_pref_z)
        prev_layout.addLayout(scrub_box)

        splitter.addWidget(prev_frame)

        # Right: Control Panel (Colorspace, Thresholds, Overrides)
        # The controls live inside a scroll area so the control column never
        # dictates the window's minimum height: the default window fits
        # 1080p entirely and maximizing gives the extra space to the viewer.
        ctrl_frame = QFrame()
        ctrl_frame.setProperty("class", "panel")
        ctrl_frame.setMinimumWidth(380)
        ctrl_layout = QVBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(18, 14, 18, 14)
        ctrl_layout.setSpacing(12)
        ctrl_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)

        lbl_ctrl_title = QLabel("Cut and range controls")
        theme.set_role(lbl_ctrl_title, "section")
        ctrl_layout.addWidget(lbl_ctrl_title)

        # Three segments, one visible at a time, so each group fits the window
        # without scrolling. The apply row below the stack never moves.
        seg_row = QHBoxLayout()
        seg_row.setSpacing(6)
        self.ctrl_segments: dict[str, QPushButton] = {}
        for key, label, tip in (
            ("lines", "Lines", "Keep, cut and margin lines."),
            ("display", "Display", "Colour palette and density thresholds."),
            ("lateral", "Lateral box", "Left, right, top and bottom bounds, and auto-crop."),
        ):
            btn = QPushButton(label)
            btn.setObjectName(f"btn_seg_{key}")
            btn.setToolTip(tip)
            btn.setProperty("active", "true" if key == "lines" else "false")
            theme.set_role(btn, "segment")
            btn.clicked.connect(lambda _=False, k=key: self._set_ctrl_segment(k))
            seg_row.addWidget(btn)
            self.ctrl_segments[key] = btn
        seg_row.addStretch()
        ctrl_layout.addLayout(seg_row)

        self.ctrl_stack = QStackedWidget()
        self.ctrl_stack.setObjectName("ctrl_stack")
        ctrl_layout.addWidget(self.ctrl_stack, 1)

        def segment_page() -> QVBoxLayout:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(12)
            page_layout.setAlignment(Qt.AlignTop)
            self.ctrl_stack.addWidget(page)
            return page_layout

        lines_layout = segment_page()        # index 0
        display_layout = segment_page()      # index 1
        lateral_layout = segment_page()      # index 2

        # 1. Colorspace Palette Selector (the theme lives on the Settings tab)
        box_cmap = QVBoxLayout()
        box_cmap.setSpacing(6)
        lbl_cmap = QLabel("Colorspace Palette:")
        theme.set_role(lbl_cmap, "secondary")
        box_cmap.addWidget(lbl_cmap)

        cmap_row = QHBoxLayout()
        cmap_row.setSpacing(4)
        self.cmap_buttons = {}
        # Grayscale placed first as primary CT colorspace, followed by Spectral, Thermal, Viridis, Plasma
        for cm in ["Grayscale", "Spectral", "Thermal", "Viridis", "Plasma"]:
            b = QPushButton(cm)
            b.setProperty("active", "true" if cm == "Grayscale" else "false")
            b.clicked.connect(lambda _, c=cm.lower(): self._set_pref_cmap(c))
            cmap_row.addWidget(b)
            self.cmap_buttons[cm.lower()] = b
        box_cmap.addLayout(cmap_row)
        display_layout.addLayout(box_cmap)

        # 2. Density Thresholds (Min HU / Max HU)
        box_thresh = QFrame()
        box_thresh.setObjectName("box_card")
        th_layout = QVBoxLayout(box_thresh)
        th_layout.setContentsMargins(8, 8, 8, 8)
        th_layout.setSpacing(8)

        th_head = QHBoxLayout()
        th_head.setContentsMargins(0, 0, 0, 0)
        self.lbl_th_head = QLabel("2D Density Thresholds (HU)")
        theme.set_role(self.lbl_th_head, "secondary")
        th_head.addWidget(self.lbl_th_head)
        th_head.addStretch()

        self.btn_th_reset = QPushButton("Reset")
        self.btn_th_reset.setObjectName("btn_th_reset")
        # Reset is the DEFAULT-active threshold choice: the baseline window
        # renders until a preset is chosen; presets hand the highlight back
        # to Reset via the active-state model.
        self.btn_th_reset.setProperty("active", "true")
        self.btn_th_reset.setFixedWidth(64)
        self.btn_th_reset.setFixedHeight(24)
        self.btn_th_reset.setObjectName("btn_th_reset")
        self.btn_th_reset.clicked.connect(self._reset_thresholds)
        th_head.addWidget(self.btn_th_reset)
        th_layout.addLayout(th_head)

        # Min HU Row
        row_min = QHBoxLayout()
        self.lbl_min_thresh = QLabel("Min HU:")
        row_min.addWidget(self.lbl_min_thresh)
        self.spin_lo = QSpinBox()
        self.spin_lo.setRange(-2000, 2000)
        self.spin_lo.setValue(int(self.pref_lo))
        self.spin_lo.valueChanged.connect(self._on_spin_lo_changed)
        row_min.addWidget(self.spin_lo)

        self.slider_lo = QSlider(Qt.Horizontal)
        self.slider_lo.setRange(-2000, 2000)   # mirrors the spinbox range
        self.slider_lo.setValue(int(self.pref_lo))
        self.slider_lo.valueChanged.connect(self._on_slider_lo_changed)
        row_min.addWidget(self.slider_lo, 1)
        th_layout.addLayout(row_min)

        # Max HU Row
        row_max = QHBoxLayout()
        self.lbl_max_thresh = QLabel("Max HU:")
        row_max.addWidget(self.lbl_max_thresh)
        self.spin_hi = QSpinBox()
        self.spin_hi.setRange(-1000, 3000)
        self.spin_hi.setValue(int(self.pref_hi))
        self.spin_hi.valueChanged.connect(self._on_spin_hi_changed)
        row_max.addWidget(self.spin_hi)

        self.slider_hi = QSlider(Qt.Horizontal)
        self.slider_hi.setRange(-1000, 3000)   # mirrors the spinbox range
        self.slider_hi.setValue(int(self.pref_hi))
        self.slider_hi.valueChanged.connect(self._on_slider_hi_changed)
        row_max.addWidget(self.slider_hi, 1)
        th_layout.addLayout(row_max)

        # Presets Row (named buttons so the active-state model can highlight
        # the chosen preset; Reset de-highlights them when clicked)
        presets_row = QHBoxLayout()
        presets_row.setSpacing(4)
        self.btn_th_full = QPushButton("Full")
        self.btn_th_wood = QPushButton("Wood Tissue")
        self.btn_th_contrast = QPushButton("High Contrast")
        self.btn_th_metal = QPushButton("Platform Metal")
        for b, nm, lo, hi in [
            (self.btn_th_full, "full", -1000, 2000),
            (self.btn_th_wood, "wood", -600, 350),
            (self.btn_th_contrast, "contrast", -350, 150),
            (self.btn_th_metal, "metal", 0, 1600),
        ]:
            b.setFixedHeight(22)
            b.setProperty("active", "false")
            theme.set_role(b, "preset")
            b.clicked.connect(lambda _, l=lo, h=hi, n=nm: self._apply_thresh_preset(l, h, n))
            presets_row.addWidget(b)
        th_layout.addLayout(presets_row)
        display_layout.addWidget(box_thresh)
        display_layout.addStretch()

        # 3. Interactive Guide Sliders (2 Lines & 4 Lines)
        box_guides_sec = QFrame()
        box_guides_sec.setObjectName("box_card")
        g_layout = QVBoxLayout(box_guides_sec)
        g_layout.setContentsMargins(6, 6, 6, 6)
        g_layout.setSpacing(10)

        lbl_g_head = QLabel("Boundary lines")
        theme.set_role(lbl_g_head, "accent")
        g_layout.addWidget(lbl_g_head)
        lbl_g_hint = QLabel("Drag a line on the preview, or type a slice number.")
        lbl_g_hint.setWordWrap(True)
        theme.set_role(lbl_g_hint, "hint")
        g_layout.addWidget(lbl_g_hint)

        # Top Line: Keep From (Green)
        box_keep = QVBoxLayout()
        box_keep.setSpacing(2)
        lbl_keep = self._keyed(QLabel(), lambda: key_swatch("keep", "Top line: keep start"))
        lbl_keep.setTextFormat(Qt.RichText)
        theme.set_role(lbl_keep, "label")
        box_keep.addWidget(lbl_keep)
        row_keep = QHBoxLayout()
        self.spin_keep = QSpinBox()
        self.spin_keep.setRange(0, 2000)
        self.spin_keep.valueChanged.connect(self._on_spin_keep_changed)
        row_keep.addWidget(self.spin_keep)
        self.slider_keep = QSlider(Qt.Horizontal)
        self.slider_keep.setRange(0, 2000)
        self.slider_keep.valueChanged.connect(self._on_slider_keep_changed)
        row_keep.addWidget(self.slider_keep, 1)
        box_keep.addLayout(row_keep)
        g_layout.addLayout(box_keep)

        # Bottom Line: Cut Slice (Red)
        box_cut = QVBoxLayout()
        box_cut.setSpacing(2)
        lbl_cut = self._keyed(QLabel(), lambda: key_swatch("metal", "Bottom line: platform cut"))
        lbl_cut.setTextFormat(Qt.RichText)
        theme.set_role(lbl_cut, "label")
        box_cut.addWidget(lbl_cut)
        row_cut = QHBoxLayout()
        self.spin_cut = QSpinBox()
        self.spin_cut.setRange(0, 2000)
        self.spin_cut.valueChanged.connect(self._on_spin_cut_changed)
        row_cut.addWidget(self.spin_cut)
        self.slider_cut = QSlider(Qt.Horizontal)
        self.slider_cut.setRange(0, 2000)
        self.slider_cut.valueChanged.connect(self._on_slider_cut_changed)
        row_cut.addWidget(self.slider_cut, 1)
        box_cut.addLayout(row_cut)
        self.lbl_anchor_hint = QLabel("detector anchor: not measured yet")
        theme.set_role(self.lbl_anchor_hint, "hint")
        box_cut.addWidget(self.lbl_anchor_hint)
        g_layout.addLayout(box_cut)

        # Margin (Safety Buffer)
        box_margin = QVBoxLayout()
        box_margin.setSpacing(2)
        lbl_margin = self._keyed(QLabel(), lambda: key_swatch("wood", "Margin above cut: slices kept"))
        lbl_margin.setTextFormat(Qt.RichText)
        theme.set_role(lbl_margin, "label")
        box_margin.addWidget(lbl_margin)
        row_margin = QHBoxLayout()
        self.spin_margin = QSpinBox()
        self.spin_margin.setRange(0, 100)
        self.spin_margin.valueChanged.connect(self._on_spin_margin_changed)
        row_margin.addWidget(self.spin_margin)
        self.slider_margin = QSlider(Qt.Horizontal)
        self.slider_margin.setRange(0, 100)
        self.slider_margin.valueChanged.connect(self._on_slider_margin_changed)
        row_margin.addWidget(self.slider_margin, 1)
        box_margin.addLayout(row_margin)
        g_layout.addLayout(box_margin)

        # Lateral Bounds Sliders (Visible in 4-Lines Mode)
        self.box_lateral = QFrame()
        self.box_lateral.setObjectName("box_lateral")
        lat_layout = QVBoxLayout(self.box_lateral)
        lat_layout.setContentsMargins(4, 4, 4, 4)
        lat_layout.setSpacing(6)
        lbl_lat = self._keyed(QLabel(), lambda: key_swatch("lateral", "Lateral ROI boundary lines (4-line mode)"))
        lbl_lat.setTextFormat(Qt.RichText)
        theme.set_role(lbl_lat, "info")
        lat_layout.addWidget(lbl_lat)

        row_lat_l = QHBoxLayout()
        self.lbl_left = QLabel("Left X:")
        row_lat_l.addWidget(self.lbl_left)
        self.spin_left = QSpinBox()
        self.spin_left.setRange(0, 100)
        self.spin_left.setValue(4)
        self.spin_left.setSuffix("%")
        self.spin_left.valueChanged.connect(self._on_spin_left_changed)
        row_lat_l.addWidget(self.spin_left)
        self.slider_left = QSlider(Qt.Horizontal)
        self.slider_left.setRange(0, 100)
        self.slider_left.setValue(4)
        self.slider_left.valueChanged.connect(self._on_slider_left_changed)
        row_lat_l.addWidget(self.slider_left, 1)
        lat_layout.addLayout(row_lat_l)

        row_lat_r = QHBoxLayout()
        self.lbl_right = QLabel("Right X:")
        row_lat_r.addWidget(self.lbl_right)
        self.spin_right = QSpinBox()
        self.spin_right.setRange(0, 100)
        self.spin_right.setValue(96)
        self.spin_right.setSuffix("%")
        self.spin_right.valueChanged.connect(self._on_spin_right_changed)
        row_lat_r.addWidget(self.spin_right)
        self.slider_right = QSlider(Qt.Horizontal)
        self.slider_right.setRange(0, 100)
        self.slider_right.setValue(96)
        self.slider_right.valueChanged.connect(self._on_slider_right_changed)
        row_lat_r.addWidget(self.slider_right, 1)
        lat_layout.addLayout(row_lat_r)

        # Axial-plane Y bounds (top / bottom of the extraction box).  Visible
        # only in the axial plane where the box has a vertical extent.
        self.row_lat_top = QVBoxLayout()
        self.row_lat_top.setSpacing(2)
        self.lbl_top = self._keyed(QLabel(), lambda: key_swatch("keep", "Top Y (axial box)"))
        self.lbl_top.setTextFormat(Qt.RichText)
        theme.set_role(self.lbl_top, "label")
        self.row_lat_top.addWidget(self.lbl_top)
        row_lat_t = QHBoxLayout()
        self.spin_top = QSpinBox()
        self.spin_top.setRange(0, 100)
        self.spin_top.setValue(4)
        self.spin_top.setSuffix("%")
        self.spin_top.valueChanged.connect(self._on_spin_top_changed)
        row_lat_t.addWidget(self.spin_top)
        self.slider_top = QSlider(Qt.Horizontal)
        self.slider_top.setRange(0, 100)
        self.slider_top.setValue(4)
        self.slider_top.valueChanged.connect(self._on_slider_top_changed)
        row_lat_t.addWidget(self.slider_top, 1)
        self.row_lat_top.addLayout(row_lat_t)
        lat_layout.addLayout(self.row_lat_top)

        self.row_lat_bottom = QVBoxLayout()
        self.row_lat_bottom.setSpacing(2)
        self.lbl_bottom = self._keyed(QLabel(), lambda: key_swatch("keep", "Bottom Y (axial box)"))
        self.lbl_bottom.setTextFormat(Qt.RichText)
        theme.set_role(self.lbl_bottom, "label")
        self.row_lat_bottom.addWidget(self.lbl_bottom)
        row_lat_b = QHBoxLayout()
        self.spin_bottom = QSpinBox()
        self.spin_bottom.setRange(0, 100)
        self.spin_bottom.setValue(96)
        self.spin_bottom.setSuffix("%")
        self.spin_bottom.valueChanged.connect(self._on_spin_bottom_changed)
        row_lat_b.addWidget(self.spin_bottom)
        self.slider_bottom = QSlider(Qt.Horizontal)
        self.slider_bottom.setRange(0, 100)
        self.slider_bottom.setValue(96)
        self.slider_bottom.valueChanged.connect(self._on_slider_bottom_changed)
        row_lat_b.addWidget(self.slider_bottom, 1)
        self.row_lat_bottom.addLayout(row_lat_b)
        lat_layout.addLayout(self.row_lat_bottom)

        lateral_layout.addWidget(self.box_lateral)
        self.box_lateral.setVisible(True)

        lines_layout.addWidget(box_guides_sec)
        lines_layout.addStretch()

        # Auto-crop to wood (air detection): trims near-pure-air margins so the
        # exported ROI spans the wood itself in XY, XZ and YZ.
        self.chk_air_crop = QCheckBox("Auto-crop to wood (air detection)")
        self.chk_air_crop.setChecked(True)
        self.chk_air_crop.setToolTip(AIR_CROP_TIP)
        lateral_layout.addWidget(self.chk_air_crop)
        lateral_layout.addStretch()

        # Live Range Summary: pinned under the segments, always visible
        self.lbl_range_summary = QLabel("Delivery: not calculated yet")
        self.lbl_range_summary.setObjectName("range_summary")
        self.lbl_range_summary.setWordWrap(True)
        theme.set_role(self.lbl_range_summary, "secondary")
        ctrl_layout.addWidget(self.lbl_range_summary)

        # Action Buttons
        btn_action_row = QHBoxLayout()
        btn_action_row.setSpacing(10)

        btn_reset_detected = QPushButton("Reset to detected")
        btn_reset_detected.clicked.connect(self._reset_to_detected)
        btn_action_row.addWidget(btn_reset_detected)

        self.btn_apply_prefs = QPushButton("Apply lines")
        self.btn_apply_prefs.setToolTip(
            "Apply the lines shown here and process the scan again with them.")
        self.btn_apply_prefs.setObjectName("btn_apply_prefs")
        self.btn_apply_prefs.setProperty("class", "btn-primary")
        self.btn_apply_prefs.clicked.connect(self._apply_and_process)
        btn_action_row.addWidget(self.btn_apply_prefs)
        ctrl_layout.addLayout(btn_action_row)


        ctrl_scroll = QScrollArea()
        ctrl_scroll.setWidgetResizable(True)
        ctrl_scroll.setWidget(ctrl_frame)
        ctrl_scroll.setFrameShape(QFrame.NoFrame)
        ctrl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ctrl_scroll.setFixedWidth(468)          # 460 content + scrollbar margin
        splitter.addWidget(ctrl_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1072, 468])
        layout.addWidget(splitter)
        return page

    # ---------------------------------------------------------------- Data & Sidebar

    # ---------------------------------------------------------------- Settings Tab UI
    _SETTINGS_SECTIONS = ("appearance", "export", "checkpoints", "shortcuts")
    _SHORTCUTS = (
        ("Ctrl+O", "Load a scan"),
        ("Ctrl+R", "Process the selected specimen"),
        ("Ctrl+E", "Export the bundle"),
        ("Ctrl+S", "Save a checkpoint"),
        ("F2", "Rename the selected specimen"),
        ("Del", "Remove the selected specimen from the list"),
    )
    _FORMAT_HINTS = {
        bundle_export.FORMAT_BOTH: "Writes the kept-slice DICOM series and one NIfTI volume.",
        bundle_export.FORMAT_DICOM: "Writes only the kept-slice DICOM series.",
        bundle_export.FORMAT_NIFTI: "Writes only the NIfTI volume: the fastest, and the smallest.",
    }

    @staticmethod
    def _setting_label(text: str) -> QLabel:
        label = QLabel(text)
        theme.set_role(label, "secondary")
        return label

    def _build_settings_page(self) -> QWidget:
        """Settings: a left rail of sections, one card per section. Every choice
        is saved to settings.json as it changes, so there is no Save button."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        head = QLabel("Settings")
        theme.set_role(head, "title")
        outer.addWidget(head)
        sub = QLabel("Choose how cleanCT looks, where it saves, and which keys act. "
                     "Changes are saved as you make them.")
        sub.setWordWrap(True)
        theme.set_role(sub, "secondary")
        outer.addWidget(sub)
        outer.addSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(18)
        self.settings_nav = QListWidget()
        self.settings_nav.setObjectName("settings_nav")
        self.settings_nav.setFixedWidth(200)
        for label in ("Appearance", "Export", "Checkpoints", "Shortcuts"):
            self.settings_nav.addItem(label)
        body.addWidget(self.settings_nav, 0, Qt.AlignTop)

        self.settings_stack = QStackedWidget()
        self.settings_stack.setMaximumWidth(760)
        body.addWidget(self.settings_stack, 1)
        body.addStretch()
        outer.addLayout(body, 1)

        def card(title: str, hint: str) -> QGridLayout:
            """A section card: title, one line of purpose, then its rows."""
            frame = QFrame()
            frame.setProperty("class", "panel")
            col = QVBoxLayout(frame)
            col.setContentsMargins(22, 20, 22, 20)
            col.setSpacing(12)
            head_label = QLabel(title)
            theme.set_role(head_label, "section")
            col.addWidget(head_label)
            hint_label = QLabel(hint)
            hint_label.setWordWrap(True)
            theme.set_role(hint_label, "hint")
            col.addWidget(hint_label)
            grid = QGridLayout()
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(12)
            grid.setColumnMinimumWidth(0, 110)
            grid.setColumnStretch(1, 1)
            col.addLayout(grid)
            # the card keeps its own height; the page below it stays empty
            wrap = QWidget()
            wrap_col = QVBoxLayout(wrap)
            wrap_col.setContentsMargins(0, 0, 0, 0)
            wrap_col.addWidget(frame)
            wrap_col.addStretch()
            self.settings_stack.addWidget(wrap)
            return grid

        # Appearance: the theme (kept in settings.json)
        grid = card("Appearance",
                    "Dark suits a dim room and light suits a bright one. The scan "
                    "canvas stays dark in both, so the image keeps its contrast.")
        self.cmb_theme = QComboBox()
        self.cmb_theme.setObjectName("cmb_theme")
        self.cmb_theme.addItem("Dark", "dark")
        self.cmb_theme.addItem("Light", "light")
        self.cmb_theme.setCurrentIndex(0 if theme.mode() == "dark" else 1)
        self.cmb_theme.setFixedWidth(200)
        self.cmb_theme.setToolTip("Switch the chrome between dark and light.")
        self.cmb_theme.currentIndexChanged.connect(self._on_theme_changed)
        grid.addWidget(self._setting_label("Theme"), 0, 0)
        grid.addWidget(self.cmb_theme, 0, 1, Qt.AlignLeft)

        # Export: the folder and the format of every bundle
        grid = card("Export",
                    "Export writes to this folder, and Process and export "
                    "uses it too.")
        self.edit_save_root = QLineEdit(self.save_root)
        self.edit_save_root.setObjectName("edit_save_root")
        self.edit_save_root.setMinimumWidth(180)
        self.edit_save_root.setToolTip(
            "Default folder for exported extraction bundles.\n"
            "Remembered across sessions.")
        self.edit_save_root.editingFinished.connect(self._on_save_root_edited)
        btn_browse_root = QPushButton("Browse…")
        btn_browse_root.setObjectName("btn_browse_export")
        btn_browse_root.clicked.connect(self._browse_save_root)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        folder_row.addWidget(self.edit_save_root, 1)
        folder_row.addWidget(btn_browse_root)
        grid.addWidget(self._setting_label("Folder"), 0, 0)
        grid.addLayout(folder_row, 0, 1)

        self.combo_export_format = QComboBox()
        self.combo_export_format.setObjectName("combo_export_format")
        self._EXPORT_FORMAT_ITEMS = [
            ("DICOM + NIfTI", bundle_export.FORMAT_BOTH),
            ("DICOM only", bundle_export.FORMAT_DICOM),
            ("NIfTI only", bundle_export.FORMAT_NIFTI),
        ]
        for label, _val in self._EXPORT_FORMAT_ITEMS:
            self.combo_export_format.addItem(label)
        self.combo_export_format.setFixedWidth(200)
        self.combo_export_format.setToolTip(
            "Which artifacts to write into the bundle:\n"
            "• DICOM + NIfTI: kept-slice series AND the volume (default)\n"
            "• DICOM only: just the kept-slice .dcm series\n"
            "• NIfTI only: just the .nii volume (fastest, smallest I/O)")
        self.combo_export_format.setCurrentIndex(self._format_index(self.export_format))
        self.combo_export_format.currentIndexChanged.connect(self._on_export_format_changed)
        grid.addWidget(self._setting_label("Format"), 1, 0)
        grid.addWidget(self.combo_export_format, 1, 1, Qt.AlignLeft)
        self.lbl_format_hint = QLabel()
        self.lbl_format_hint.setObjectName("lbl_format_hint")
        self.lbl_format_hint.setWordWrap(True)
        theme.set_role(self.lbl_format_hint, "hint")
        grid.addWidget(self.lbl_format_hint, 2, 1)

        # Checkpoints: where Save and Open start
        grid = card("Checkpoints",
                    "A checkpoint keeps the preview, the cut and keep lines, the colour "
                    "map and the view settings. Open one to restore them. The scan "
                    "reconnects when it is still registered at the same place.")
        self.lbl_checkpoint_dir = QLabel()
        self.lbl_checkpoint_dir.setObjectName("lbl_checkpoint_dir")
        self.lbl_checkpoint_dir.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        btn_choose_ckpt = QPushButton("Choose…")
        btn_choose_ckpt.setObjectName("btn_choose_checkpoint_dir")
        btn_choose_ckpt.clicked.connect(self._choose_checkpoint_dir)
        ckpt_row = QHBoxLayout()
        ckpt_row.setSpacing(8)
        ckpt_row.addWidget(self.lbl_checkpoint_dir, 1)
        ckpt_row.addWidget(btn_choose_ckpt)
        grid.addWidget(self._setting_label("Start folder"), 0, 0)
        grid.addLayout(ckpt_row, 0, 1)
        ckpt_hint = QLabel("Save and Open start in this folder. Each save or open "
                           "moves it to the folder used.")
        ckpt_hint.setWordWrap(True)
        theme.set_role(ckpt_hint, "hint")
        grid.addWidget(ckpt_hint, 1, 1)
        self._refresh_checkpoint_dir()

        # Shortcuts: a reference, not a setting
        grid = card("Shortcuts",
                    "Ctrl shortcuts work anywhere in the window. F2 and Del act on the "
                    "selected specimen, so select it in the list first.")
        for row_index, (keys, action) in enumerate(self._SHORTCUTS):
            key = QLabel(keys)
            theme.set_role(key, "key")
            grid.addWidget(key, row_index, 0, Qt.AlignLeft)
            grid.addWidget(QLabel(action), row_index, 1)

        self.settings_nav.currentRowChanged.connect(self.settings_stack.setCurrentIndex)
        self.settings_nav.setCurrentRow(0)
        return page

    def _open_settings(self, section: str = "appearance") -> None:
        self._switch_tab("settings")
        self.settings_nav.setCurrentRow(self._SETTINGS_SECTIONS.index(section))

    def _refresh_export_summary(self) -> None:
        """Keep the export row and the Settings hint in step with the folder and format."""
        label = self.combo_export_format.currentText()
        shown = self.lbl_export_dest.fontMetrics().elidedText(self.save_root, Qt.ElideMiddle, 420)
        self.lbl_export_dest.setText(shown)
        self.lbl_export_dest.setToolTip(self.save_root)
        self.lbl_export_format.setText(label)
        self.btn_export.setToolTip(f"Write the bundle to the export folder ({label}).")
        if self.combo_export_format.isEnabled():
            # read the combo, not self.export_format: that is updated after this refresh
            chosen = self._EXPORT_FORMAT_ITEMS[self.combo_export_format.currentIndex()][1]
            self.lbl_format_hint.setText(self._FORMAT_HINTS[chosen])
        else:
            self.lbl_format_hint.setText(
                "TIFF and NIfTI sources have no DICOM tags, so the bundle is a NIfTI volume.")

    def _refresh_checkpoint_dir(self) -> None:
        text = self.checkpoint_dir or "Not chosen yet"
        self.lbl_checkpoint_dir.setText(
            self.lbl_checkpoint_dir.fontMetrics().elidedText(text, Qt.ElideMiddle, 420))
        self.lbl_checkpoint_dir.setToolTip(self.checkpoint_dir or text)

    def _remember_checkpoint_dir(self, folder: str) -> None:
        """Save and Open start in the folder used last (settings.json)."""
        if not folder or folder == self.checkpoint_dir:
            return
        self.checkpoint_dir = folder
        self._refresh_checkpoint_dir()
        try:
            settings = bundle_export.load_settings(STATE)
            settings["checkpoint_dir"] = folder
            bundle_export.save_settings(STATE, settings)
        except Exception as e:
            self._log_action(f"could not remember the checkpoint folder: {e}")

    def _choose_checkpoint_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the checkpoint folder", self.checkpoint_dir)
        if folder:
            self._remember_checkpoint_dir(folder)
            self._log_action(f"checkpoint folder set: {folder}")

    def _check_gpu(self):
        """Probe the ENGINE's real backend (CuPy/CUDA vs CPU) on a WORKER
        thread: the probe takes seconds and must not delay first paint.
        The chip reflects the actual processing decision, not a torch
        probe (this payload is torch-free by design)."""
        def _probe():
            try:
                from gpu_backend import get_backend
                be = get_backend(verbose=False)
                if be.active:
                    return {"active": True,
                            "name": str(getattr(be.info, "name", "") or
                                        be.backend)}
                return {"active": False,
                        "reason": str(getattr(be.info, "reason", "") or
                                      "no usable CUDA framework")}
            except Exception as exc:
                return {"active": False, "reason": f"{type(exc).__name__}: {exc}"}

        def _done(res: dict):
            if res.get("active"):
                name = str(res.get("name") or "CUDA GPU")
                # compact chip text: the full device name clipped at the
                # 280 px sidebar; the tooltip carries the complete detail
                short = (name.replace("NVIDIA GeForce ", "")
                         .replace("NVIDIA ", ""))
                self.lbl_gpu.setText(f"GPU: {short}, CuPy CUDA")
                self.lbl_gpu.setToolTip(
                    f"GPU acceleration active: {name} via CuPy (CUDA 12.x)")
                theme.set_role(self.lbl_gpu, "chip-ok")
                self._log_action(f"GPU acceleration active: {name} via CuPy")
            else:
                reason = str(res.get("reason") or "no usable CUDA framework")
                self.lbl_gpu.setText("CPU processing (no CUDA GPU)")
                self.lbl_gpu.setToolTip(
                    f"CPU processing: {reason}; no GPU required")
                theme.set_role(self.lbl_gpu, "chip-warn")
                self._log_action(
                    f"CPU processing ({reason}): multi-threaded CPU is "
                    "used; no GPU required")

        def _err(msg: str):
            self.lbl_gpu.setText("CPU processing (backend probe failed)")
            self.lbl_gpu.setToolTip("GPU probe failed; CPU processing in use")
            theme.set_role(self.lbl_gpu, "chip-warn")
            self._log_action(f"GPU probe exception: {msg}; using CPU")

        # the thread wrapper MUST outlive run(): a local would be
        # garbage-collected mid-flight ("QThread: Destroyed while thread
        # is still running" aborts the process)
        self._gpu_worker = WorkerThread(lambda: dict(_probe()))
        self._gpu_worker.succeeded.connect(_done)
        self._gpu_worker.failed.connect(_err)
        self._gpu_worker.finished.connect(self._on_gpu_probe_finished)
        self._gpu_worker.start()

    def _on_gpu_probe_finished(self):
        # cleared only once the probe thread has finished: dropping the
        # reference from succeeded/failed freed a QThread still inside run()
        if self._gpu_worker is self.sender():
            self._gpu_worker = None

    # ---- sidebar meta helpers -------------------------------------------
    @staticmethod
    def _meta_from_report(out_dir: Path) -> dict:
        """Lightweight meta for a processed specimen row (report.json is
        tiny; read is cheap and always on the GUI thread)."""
        meta: dict = {}
        try:
            data = json.loads(
                (out_dir / "report.json").read_text(encoding="utf-8"))
            rep = data.get("report") if isinstance(data, dict) else {}
            m = (rep or {}).get("meta") or data.get("meta") or {}
            n = int(m.get("n_slices") or (rep or {}).get("n_slices") or 0)
            rows = int(m.get("rows") or 0)
            cols = int(m.get("cols") or 0)
            spacing = m.get("pixel_spacing_yx_mm") or []
            um = float(spacing[0]) * 1000.0 if spacing and spacing[0] else 0.0
            if n:
                meta["slices"] = n
            if rows and cols:
                meta["dims"] = f"{rows}×{cols}"
            if um:
                meta["um"] = um
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return meta

    def _builtin_specimen_dir(self, ds: str, specimen: str) -> Path | None:
        try:
            return (tg.output_root(tg.DATASETS[ds]) / specimen)
        except (KeyError, AttributeError, TypeError):
            return None

    def _specimen_output_dir(self, ds: str, specimen: str) -> Path | None:
        """Where this specimen's processed outputs live (renamed along
        with the specimen ID so history stays coherent)."""
        if ds == "custom":
            try:
                spec = tg.DatasetSpec(key=csx.CUSTOM_KEY, source=csx.DATA_DIR,
                                      out_sub=csx.CUSTOM_KEY)
            except Exception:
                return None
            return tg.output_root(spec) / specimen
        return self._builtin_specimen_dir(ds, specimen)

    def _custom_source_path(self, specimen: str,
                            entry: dict | None = None) -> Path | None:
        """Where a loaded specimen's scan lives: the registered source
        folder or file, or the DATA_DIR junction for a DICOM folder that was
        registered without one."""
        if entry is None:
            entry = csx.registered_specimens().get(specimen) or {}
        kind = str(entry.get("source_kind") or "dicom")
        source = (entry.get("source_path") if kind != "dicom"
                  else entry.get("source_folder"))
        if not source and kind == "dicom":
            source = str(csx.DATA_DIR / specimen / "XY")
        return Path(source) if source else None

    def _refresh_sidebar(self):
        self.sample_list.clear()
        self._header_items = []
        self._empty_row = None

        nat_key = _natural_key

        # Show only specimens that are actually available on this machine.
        catalog = {}
        for key, ds in tg.DATASETS.items():
            root = tg.output_root(ds)
            try:
                all_samples = ([entry.name for entry in root.iterdir()
                                if entry.is_dir() and
                                (entry / "report.json").is_file() and
                                entry.name != "1-15"]
                               if root.is_dir() else [])
            except OSError:
                all_samples = []
            first = sorted((name for name in all_samples
                            if name.startswith("1-")), key=nat_key)[:3]
            second = sorted((name for name in all_samples
                             if name.startswith("2-")), key=nat_key)[:3]
            catalog[key] = first + second

        labels = {"24um": "24 µm dataset", "66um": "66.2 µm dataset"}

        def add_header(text: str, color: str):
            header = QListWidgetItem(text)
            header.setFlags(Qt.NoItemFlags)
            header.setForeground(QColor(color))
            header.setFont(QFont("Segoe UI", 10, QFont.Bold))
            header.setData(self._SECTION_ROLE, "header")
            self._header_items.append(header)
            self.sample_list.addItem(header)

        for key in ("24um", "66um"):
            samples = catalog.get(key, [])
            samples = [s for s in samples if (key, s) not in self._hidden_builtins]
            if not samples:
                continue
            add_header(f"{labels[key]} ({len(samples)} specimens)", theme.color("accent"))
            for specimen in samples:
                meta = self._meta_from_report(
                    self._builtin_specimen_dir(key, specimen) or Path())
                meta["kind"] = labels[key].replace(" dataset", "")
                item = QListWidgetItem(specimen)
                item.setData(Qt.UserRole, (key, specimen))
                item.setData(SpecimenDelegate.META_ROLE, meta)
                self.sample_list.addItem(item)

        customs = csx.registered_specimens()
        available_customs = {}
        for specimen, entry in customs.items():
            try:
                source = self._custom_source_path(specimen, entry)
                if source and source.exists():
                    available_customs[specimen] = entry
            except (OSError, TypeError, ValueError):
                continue
        if available_customs:
            add_header("Loaded specimens", theme.color("info"))
            for specimen, entry in available_customs.items():
                kind = str(entry.get("source_kind") or "dicom")
                meta = {
                    "kind": {"dicom": "DICOM", "tiff": "TIFF",
                             "nifti": "NIfTI"}.get(kind, kind.upper()),
                    "slices": int(entry.get("n_slices") or 0) or None,
                    "dims": (f"{int(entry['rows'])}×{int(entry['cols'])}"
                             if entry.get("rows") and entry.get("cols")
                             else None),
                    "um": float(entry.get("pixel_um") or 0) or None,
                }
                item = QListWidgetItem(specimen)
                item.setData(Qt.UserRole, ("custom", specimen))
                item.setData(SpecimenDelegate.META_ROLE, meta)
                self.sample_list.addItem(item)

        empty = QListWidgetItem("No specimens loaded yet")
        empty.setFlags(Qt.NoItemFlags)
        empty.setForeground(QColor(theme.color("text_3")))
        empty.setData(self._SECTION_ROLE, "empty")
        self.sample_list.addItem(empty)
        self._empty_row = empty

        self._refresh_specimen_filter()
        self._queue_specimen_meta()

    # ---- specimen panel: filter, actions, context menu, meta scan --------
    _SECTION_ROLE = SpecimenDelegate.META_ROLE + 1

    def _apply_specimen_filter(self, text: str):
        self._filter_text = text.strip().lower()
        self._refresh_specimen_filter()

    def _refresh_specimen_filter(self):
        q = self._filter_text
        lst = self.sample_list
        header = None
        shown = 0
        total = 0
        group_shown: dict[int, int] = {}
        for i in range(lst.count()):
            it = lst.item(i)
            tag = it.data(self._SECTION_ROLE)
            if tag == "header":
                header = it
                continue
            if tag == "empty":
                continue
            if it.data(Qt.UserRole):
                total += 1
                match = (not q) or (q in str(it.data(Qt.UserRole)[1]).lower())
                it.setHidden(not match)
                if match:
                    shown += 1
                    if header is not None:
                        group_shown[id(header)] = \
                            group_shown.get(id(header), 0) + 1
        for h in self._header_items:
            h.setHidden(group_shown.get(id(h), 0) == 0)
        if self._empty_row is not None:
            if total == 0:
                self._empty_row.setText("No specimens loaded yet")
                self._empty_row.setHidden(False)
            elif shown == 0:
                self._empty_row.setText(
                    f"No specimens match “{q}”")
                self._empty_row.setHidden(False)
            else:
                self._empty_row.setHidden(True)
        self._update_spec_count(total, shown)
        self._update_specimen_actions()

    def _update_spec_count(self, total: int, shown: int) -> None:
        if self._filter_text and shown != total:
            self.lbl_spec_count.setText(f"{shown} of {total}")
        else:
            self.lbl_spec_count.setText(str(total))

    def _selected_specimen_key(self) -> tuple[str, str] | None:
        item = self.sample_list.currentItem()
        if item is None:
            return None
        key = item.data(Qt.UserRole)
        return key if key else None

    def _specimen_context_menu(self, pos) -> None:
        menu = QMenu(self)
        item = self.sample_list.itemAt(pos)
        key = item.data(Qt.UserRole) if item is not None else None
        if item is not None and key:
            # right-click on a row selects it (standard desktop UX)
            self.sample_list.setCurrentItem(item)
        else:
            # a header or empty spot: operate on the current selection
            key = self._selected_specimen_key()
        busy = self._actions_busy()
        customs = csx.registered_specimens()

        # ---- specimen section (only with a selection) -------------------
        act_open = act_rename = act_dup = act_locate = None
        act_props = act_remove = act_clear = None
        if key:
            ds, sp = key
            is_custom = ds == "custom"
            act_open = menu.addAction(f"Open “{sp}”")
            act_open.setToolTip("Load this specimen and show its views.")
            act_open.triggered.connect(
                lambda _checked=False, k=key: self._select_sample(*k))
            menu.addSeparator()
            act_rename = menu.addAction("Rename…  (F2)")
            act_rename.setEnabled(not busy and is_custom)
            act_rename.setToolTip(
                "Rename the loaded specimen (registry ID and link).\n"
                "Existing exports keep the old name."
                if is_custom else
                "Built-in dataset specimens are named by their "
                "processed-output folder and cannot be renamed.")
            act_dup = menu.addAction("Duplicate…")
            act_dup.setEnabled(not busy and is_custom)
            act_dup.setToolTip(
                "Register the same scan again under a new ID: no data is "
                "copied." if is_custom else
                "Built-in dataset specimens cannot be duplicated.")
            act_locate = menu.addAction("Show in Explorer")
            act_locate.setEnabled(not busy)
            act_locate.setToolTip(
                "Show the specimen's source folder (loaded scans) or its "
                "processed-output folder (built-in datasets).")
            act_props = menu.addAction("Properties…")
            act_props.setEnabled(not busy)
            act_props.setToolTip(
                "Size, dimensions, slice count, voxel size, and the "
                "source / processed-output folders.")
            menu.addSeparator()
            act_remove = menu.addAction("Remove…  (Del)")
            act_remove.setToolTip(
                "Loaded scans: unregistered: source, processed results, "
                "and exports are kept. Built-in specimens are hidden "
                "until restart. Asks for confirmation.")
            act_remove.setEnabled(not busy)
            menu.addSeparator()
        elif not customs:
            # empty-state: a hint instead of a bare context menu
            note = menu.addAction("No specimens yet: load a scan to begin")
            note.setEnabled(False)
            menu.addSeparator()
        if customs:
            act_clear = menu.addAction("Clear loaded list…")
            act_clear.setToolTip(
                "Unregister every loaded specimen. Sources are NOT "
                "deleted; processed results and exports are kept.")
            act_clear.setEnabled(not busy)
            menu.addSeparator()
        act_load = menu.addAction("Load scan…")
        act_load.setEnabled(not busy)
        act_load.setToolTip(
            "Register a DICOM series folder, a multipage TIFF stack or\n"
            "slice folder, or one 3-D NIfTI volume (.nii / .nii.gz).")
        act_load.triggered.connect(
            lambda _checked=False: self._open_load_dialog())
        chosen = menu.exec(self.sample_list.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_open:
            self._select_sample(*key)
        elif chosen is act_rename:
            self._rename_selected()
        elif chosen is act_dup:
            self._duplicate_selected()
        elif chosen is act_locate:
            self._locate_selected()
        elif chosen is act_props:
            self._properties_selected()
        elif chosen is act_remove:
            self._remove_selected()
        elif chosen is act_clear:
            self._clear_loaded_specimens()

    # action handlers -------------------------------------------------------
    def _actions_busy(self) -> bool:
        return bool(self._loading or
                    (self._active_worker is not None and
                     self._active_worker.isRunning()))

    def _update_specimen_actions(self) -> None:
        key = self._selected_specimen_key()
        busy = self._actions_busy()
        is_custom = bool(key) and key[0] == "custom"
        self.btn_rename.setEnabled(not busy and is_custom)
        self.btn_duplicate.setEnabled(not busy and is_custom)
        self.btn_locate.setEnabled(not busy and bool(key))
        self.btn_remove.setEnabled(not busy and bool(key))

    def _rename_selected(self) -> None:
        key = self._selected_specimen_key()
        if not key or self._actions_busy():
            return
        ds, sp = key
        if ds != "custom":
            QMessageBox.information(
                self, "Rename specimen",
                "Built-in dataset specimens are named by their processed "
                "output folder and cannot be renamed here.")
            return
        new, ok = QInputDialog.getText(
            self, "Rename specimen",
            f"New specimen ID for “{sp}”:", text=sp)
        if not ok:
            return
        new = new.strip()
        if not new or new == sp:
            return
        target_id = csx.unique_specimen_id(new, ignore=sp)
        if target_id == sp:             # the name sanitizes to the current ID
            return
        out_dir = self._specimen_output_dir(ds, sp)
        # refuse before anything changes: a processed folder that already
        # carries the target ID would leave this specimen's results orphaned
        if out_dir is not None and out_dir.with_name(target_id).exists():
            QMessageBox.warning(self, "Rename specimen",
                                f"“{target_id}” already has processed results. "
                                "Choose another ID.")
            return
        # the processed folder moves first, so a folder that cannot be moved
        # (open in Explorer, a file held by another program) changes nothing
        moved = out_dir is not None and out_dir.is_dir()
        if moved:
            try:
                out_dir.rename(out_dir.with_name(target_id))
            except OSError as e:
                QMessageBox.critical(
                    self, "Rename failed",
                    f"The processed results of “{sp}” could not be moved: {e}\n"
                    "Close any program that has them open, then try again.")
                return
        try:
            accepted = csx.rename_specimen(sp, new)
        except (csx.LoadError, OSError) as e:
            if moved:                   # put the results back under the old ID
                try:
                    out_dir.with_name(target_id).rename(out_dir)
                except OSError as undo:
                    self._log_action(f"could not move the results of {target_id} "
                                     f"back to {sp}: {undo}")
            QMessageBox.critical(self, "Rename failed", str(e))
            return
        viewer_core.forget_specimen(sp)     # the old ID's cached views are stale
        if self.dataset == ds and self.sample == sp and \
                not self._checkpoint_snapshot_only:
            self.sample = accepted
            self.lbl_sample_title.setText(accepted)
        self._refresh_sidebar()
        self._select_row_for((ds, accepted))
        self._log_action(f"renamed specimen {sp} → {accepted} "
                         "(exports keep the old name)")

    def _duplicate_selected(self) -> None:
        key = self._selected_specimen_key()
        if not key or self._actions_busy():
            return
        ds, sp = key
        if ds != "custom":
            QMessageBox.information(
                self, "Duplicate specimen",
                "Built-in dataset specimens cannot be duplicated: loaded "
                "scans can be registered again under a new ID.")
            return
        new, ok = QInputDialog.getText(
            self, "Duplicate specimen",
            f"New ID for a copy of “{sp}” (same source, re-detectable):",
            text=f"{sp}_copy")
        if not ok:
            return
        new = new.strip()
        if not new:
            return
        try:
            entry = csx.duplicate_specimen(sp, new)
        except csx.LoadError as e:
            QMessageBox.critical(self, "Duplicate failed", str(e))
            return
        self._refresh_sidebar()
        self._select_row_for(("custom", entry["specimen"]))
        self._log_action(f"duplicated {sp} → {entry['specimen']} "
                         "(same source; no scan data copied)")

    def _remove_selected(self) -> None:
        key = self._selected_specimen_key()
        if not key or self._actions_busy():
            return
        ds, sp = key
        if ds == "custom":
            answer = QMessageBox.question(
                self, "Remove specimen",
                f"Remove “{sp}” from the loaded list?\n\n"
                "• The scan source is NOT deleted.\n"
                "• Processed results and exports are kept.\n"
                "• You can load the source again at any time.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            try:
                csx.remove_specimen(sp)
            except OSError as e:
                QMessageBox.critical(self, "Remove failed", str(e))
                return
            viewer_core.forget_specimen(sp)
            if (self.dataset == ds and self.sample == sp and
                    not self._checkpoint_snapshot_only):
                self._deselect_current()
            self._refresh_sidebar()
            self._log_action(f"removed loaded specimen {sp} "
                             "(source and results kept)")
        else:
            answer = QMessageBox.question(
                self, "Hide specimen",
                f"Hide “{sp}” from the sidebar?\n\n"
                "Nothing is deleted: the built-in specimen returns the "
                "next time cleanCT starts.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            self._hidden_builtins.add(key)
            if self.dataset == ds and self.sample == sp and \
                    not self._checkpoint_snapshot_only:
                self._deselect_current()
            self._refresh_sidebar()
            self._log_action(f"hid built-in specimen {sp} (session only)")

    def _locate_selected(self) -> None:
        key = self._selected_specimen_key()
        if not key or self._actions_busy():
            return
        folder = self._specimen_folder(*key)
        if not folder or not Path(folder).exists():
            QMessageBox.warning(
                self, "Not available",
                f"The folder for “{key[1]}” is not available on this machine.")
            return
        target = str(Path(folder))
        try:
            reveal_in_file_manager(target)
        except OSError as exc:
            self._log_action(f"could not open location: {exc}")
            return
        self._log_action(f"opened location for {key[1]}: {target}")

    def _specimen_folder(self, ds: str, sp: str) -> str:
        """The folder a 'Show in Explorer' action should reveal: the
        scan source for loaded specimens, the processed output for
        built-in datasets."""
        if ds == "custom":
            return str(self._custom_source_path(sp) or "")
        return str(self._builtin_specimen_dir(ds, sp) or "")

    def _properties_selected(self) -> None:
        key = self._selected_specimen_key()
        if not key:
            return
        ds, sp = key
        folder = self._specimen_folder(ds, sp)
        out_dir = self._specimen_output_dir(ds, sp)
        info: dict = {"name": sp, "dataset": ds, "source": folder,
                      "processed": (str(out_dir) if out_dir else "")}
        if ds == "custom":
            entry = csx.registered_specimens().get(sp) or {}
            kind = str(entry.get("source_kind") or "dicom")
            info["kind_label"] = {"dicom": "DICOM series", "tiff": "TIFF",
                                  "nifti": "NIfTI volume"}.get(kind, kind)
            info["added"] = entry.get("added")
            info["slices"] = int(entry.get("n_slices") or 0) or None
            info["dims"] = (f"{int(entry['rows'])}×{int(entry['cols'])}"
                            if entry.get("rows") and entry.get("cols")
                            else None)
            info["um"] = float(entry.get("pixel_um") or 0) or None
        else:
            info["kind_label"] = "Built-in dataset (processed)"
            meta = self._meta_from_report(self._builtin_specimen_dir(ds, sp)
                                          or Path())
            info["slices"] = meta.get("slices")
            info["dims"] = meta.get("dims")
            info["um"] = meta.get("um")
        try:
            settings = bundle_export.load_settings(STATE)
            dest = str(settings.get("save_root") or
                       bundle_export.default_save_root())
            info["export_dest"] = f"{dest}\\{sp}"
        except Exception:
            pass
        # on-disk size: reuse the row meta when the scan already ran,
        # otherwise stat the folder synchronously (bounded stat walk)
        meta_item = None
        for i in range(self.sample_list.count()):
            it = self.sample_list.item(i)
            if it.data(Qt.UserRole) == (ds, sp):
                meta_item = it.data(SpecimenDelegate.META_ROLE)
                break
        size = (meta_item or {}).get("size")
        if not size and folder and Path(folder).exists():
            size = folder_size_bytes(Path(folder))
        info["size_label"] = human_size(size)
        info["locatable"] = bool(folder and Path(folder).exists())
        dlg = SpecimenPropertiesDialog(self, info)
        dlg.exec()

    def _clear_loaded_specimens(self) -> None:
        customs = csx.registered_specimens()
        if not customs:
            QMessageBox.information(
                self, "Clear loaded list", "There are no loaded specimens.")
            return
        names = "\n".join(f"• {sp}" for sp in sorted(customs))
        answer = QMessageBox.question(
            self, "Clear loaded list",
            f"Unregister every loaded specimen?\n\n{names}\n\n"
            "• The scan sources are NOT deleted.\n"
            "• Processed results and exports are kept.\n"
            "• Each source can be loaded again later.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        removed = 0
        for sp in list(customs):
            try:
                if csx.remove_specimen(sp):
                    viewer_core.forget_specimen(sp)
                    removed += 1
            except OSError as e:
                self._log_action(f"could not unregister {sp}: {e}")
        if (not self._checkpoint_snapshot_only and self.dataset == "custom"
                and customs.get(self.sample)):
            self._deselect_current()
        self._refresh_sidebar()
        self._log_action(f"cleared the loaded list ({removed} specimens)")

    def _deselect_current(self) -> None:
        """Return the workspace to the no-selection state after a removal."""
        self.dataset = self.sample = ""
        self.payload = None
        self._last_pref_preview = None
        self.kpi_banner.updateMetrics({"empty": True})
        self.viewer_3d.setData(None)
        self.lbl_sample_title.setText("No specimen loaded")
        self.lbl_sample_sub.setText("Select a specimen from the list")
        self._set_job_gates(process_ready=False)

    def _select_row_for(self, key: tuple[str, str]) -> None:
        for i in range(self.sample_list.count()):
            it = self.sample_list.item(i)
            if it.data(Qt.UserRole) == key:
                self.sample_list.blockSignals(True)
                self.sample_list.setCurrentItem(it)
                self.sample_list.blockSignals(False)
                self._update_specimen_actions()
                return

    # lazy on-disk size scan (never blocks the GUI thread) -------------------
    def _queue_specimen_meta(self):
        self._specimen_meta_generation += 1
        generation = self._specimen_meta_generation
        jobs: list[tuple[str, str, str]] = []
        for i in range(self.sample_list.count()):
            it = self.sample_list.item(i)
            key = it.data(Qt.UserRole)
            if not key:
                continue
            meta = it.data(SpecimenDelegate.META_ROLE)
            if not isinstance(meta, dict) or meta.get("size") is not None:
                continue
            ds, sp = key
            if ds == "custom":
                folder = self._custom_source_path(sp)
            else:
                folder = self._builtin_specimen_dir(ds, sp)
            if folder is not None:
                jobs.append((ds, sp, str(folder)))
        if not jobs:
            return

        def scan(todo=jobs):
            return {"sizes": [(ds, sp, folder_size_bytes(Path(path)))
                              for ds, sp, path in todo]}

        worker = WorkerThread(scan)
        worker.succeeded.connect(
            lambda res, g=generation: self._apply_specimen_sizes(
                res.get("sizes") or [], g))
        worker.finished.connect(lambda w=worker: self._retire_meta_worker(w))
        self._specimen_meta_workers.append(worker)
        worker.start()

    def _retire_meta_worker(self, worker: WorkerThread) -> None:
        if worker in self._specimen_meta_workers:
            self._specimen_meta_workers.remove(worker)

    def _apply_specimen_sizes(self, sizes, generation: int) -> None:
        if generation != self._specimen_meta_generation:
            return  # a newer refresh already owns these rows
        sizes = {(ds, sp): sz for ds, sp, sz in (sizes or [])}
        changed = False
        for i in range(self.sample_list.count()):
            it = self.sample_list.item(i)
            key = it.data(Qt.UserRole)
            if not key:
                continue
            meta = it.data(SpecimenDelegate.META_ROLE)
            if isinstance(meta, dict) and key in sizes:
                meta["size"] = sizes[key]
                it.setData(SpecimenDelegate.META_ROLE, dict(meta))
                changed = True
        if changed:
            self.sample_list.viewport().update()

    def _on_sample_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if data:
            ds, sp = data
            self._select_sample(ds, sp)

    def _apply_payload_state(self, p: dict):
        """(Continuation of _apply_sample_payload: the former synchronous
        _select_sample body, now fed the built payload instead of blocking
        the GUI thread on viewer_core.build_payload.)"""
        try:
            self.payload = p
            # Programmatic line sync below is the auto copy layer, never a
            # user edit: guard it so it cannot suspend itself (0AG).
            self._applying_auto_snap = True
            self.kpi_banner.updateMetrics(p.get("report"))

            # Update Axial Frames
            frames = p.get("frames", [])
            if frames:
                self.axial_slider.setRange(0, len(frames) - 1)
                self.axial_slider.setValue(len(frames) // 2)
                self._update_axial_frame(len(frames) // 2)

            # Update Longitudinal
            self._update_long_view()

            # Update 3D Cloud
            self.viewer_3d.setData(p.get("cloud"))

            # Update Preferences from the report summary (flat keys)
            rep = p.get("report", {})
            self._set_intensity_controls(rep)
            self._set_export_source_kind(
                str(rep.get("source_kind") or
                    (rep.get("meta") or {}).get("source_kind") or "dicom"))
            n_slices = int(rep.get("n_slices") or 0)
            cut_val = int(rep.get("cut_from") or max(1, n_slices // 2))
            margin_val = int(rep.get("cut_margin_slices") or 0)
            keep_val = int(rep.get("keep_from") or 0)

            self.pref_cut = cut_val
            self.pref_margin = margin_val
            self.pref_keep = min(keep_val, cut_val - 1) if cut_val > 0 else 0

            # Declare the REAL slice count before any preview lands so
            # Keep/Cut placement and snaps can never be clamped to the
            # stale preview-space default.
            self.pref_viewer.setSliceCount(n_slices)

            hi = max(1, n_slices)
            self.spin_cut.setRange(0, hi)
            self.slider_cut.setRange(0, hi)
            self.spin_margin.setRange(0, max(1, min(100, cut_val)))
            self.slider_margin.setRange(0, max(1, min(100, cut_val)))
            self.spin_keep.setRange(0, hi)
            self.slider_keep.setRange(0, hi)

            self.spin_cut.setValue(self.pref_cut)
            self.slider_cut.setValue(self.pref_cut)
            self.spin_margin.setValue(self.pref_margin)
            self.slider_margin.setValue(self.pref_margin)
            self.spin_keep.setValue(self.pref_keep)
            self.slider_keep.setValue(self.pref_keep)

            # Overlay consistency: push the lines into the viewer DIRECTLY,
            # so badges can never show a previous specimen's cut/keep while
            # the sliders already show the new one (the debounced preview is
            # only a repaint, never the source of line state).
            self.pref_viewer.setCut(self.pref_cut)
            self.pref_viewer.setKeep(self.pref_keep)
            self.pref_viewer.setPlane(self.pref_plane)

            # Reset any explicit preview z and X/Y: the new specimen has its own axes
            self._pref_z_explicit = None
            self._pref_pos = None

            anchor = rep.get("anchor")
            detected = rep.get("detected_cut_from")
            hint = f"detector anchor: slice {anchor}" if anchor else "detector anchor: not measured yet"
            if detected is not None:
                hint += f", auto-detected: {detected}"
            self.lbl_anchor_hint.setText(hint)

            # Threshold defaults: Reset is the DEFAULT state on every
            # specimen load: the calibrated baseline window (wood window
            # widened for context, the same formula the previews use) with
            # Grayscale as the colorspace, so air / metal / wood separate
            # cleanly from the first paint.
            win_lo = rep.get("win_lo")
            win_hi = rep.get("win_hi")
            if win_lo is not None:
                self.pref_default_lo = float(win_lo)
            if win_hi is not None:
                self.pref_default_hi = float(win_hi)
            self._thresh_defaults_stale = True
            self._sync_threshold_defaults()

            # Air-detected wood bounds drive the auto guide lines (all
            # planes) and the lateral slider defaults.  Fractions come from
            # the robust percentile envelope in core.wood_bounds.
            b = p.get("bounds")
            if b and b.get("H") and b.get("W"):
                bf = {
                    "x": (b["x0"] / b["W"], (b["x1"] + 1) / b["W"]),
                    "y": (b["y0"] / b["H"], (b["y1"] + 1) / b["H"]),
                }
                self._wood_bounds = bf
                self._wood_bounds_raw = b
                # Auto z-guides (air top / metal base top) from the same
                # metal-anchored evidence: dotted reference lines, always
                # shown so the detection stays visible even with auto snap
                # off.
                self.pref_viewer.setAutoZ(b.get("zb") or None)
                # Auto Snap to Detection (audit 0AG): the copy layer puts
                # the job lines onto the detected edges: Keep ≡ air top
                # (wood top when the air top deferred), Cut ≡ metal top,
                # both lateral pairs ≡ the detected envelope.  Toggle OFF
                # leaves manual lines untouched (neutral 15/85 pairs so no
                # stale values leak between specimens).
                if self.chk_auto_snap.isChecked():
                    placed = self._apply_auto_snap("load")
                    if placed:
                        self._log_action(
                            "auto-snap applied on detection: "
                            + ", ".join(placed))
                else:
                    self.pref_viewer.setAxisBounds(
                        {"x": (0.15, 0.85), "y": (0.15, 0.85)})
                    self._sync_lateral_sliders_from_viewer()
                    self._log_action(
                        "auto snap OFF: detection guides shown; manual "
                        "lines kept")
                self._sync_kpi_effective()
                self._update_lateral_panel_for_plane()
                ainfo = b.get("anchor") or {}
                az = ainfo.get("z")
                asrc = ainfo.get("source") or "none"
                anch = (f", metal anchor z {az[0]}–{az[1]} [{asrc}]"
                        if az else ", no metal anchor")
                vx = b.get("voxel_um")
                zbg = b.get("zb") or {}
                zg = ""
                if zbg.get("keep") is not None:
                    zg += f", air top z {zbg['keep']}"
                else:
                    zg += ", air top deferred (edge not clear)"
                if zbg.get("metal_top") is not None:
                    zg += f", metal top z {zbg['metal_top']}"
                if zbg.get("cut") is not None:
                    zg += f", halo onset z {zbg['cut']}"
                if vx:
                    zg += f" @ {vx:.1f} µm"
                ev = b.get("evidence") or {}
                lat = ev.get("lateral") or {}
                ag = [ax for ax, ok in (("Y", lat.get("y_witness_agree")),
                                        ("X", lat.get("x_witness_agree"))) if ok]
                ags = (f", witnesses agreed {'+'.join(ag)}" if ag
                       else ", witnesses deferred")
                self._log_action(
                    "auto guide lines placed (metal-first: "
                    f"X {bf['x'][0]*100:.0f}–{bf['x'][1]*100:.0f}%, "
                    f"Y {bf['y'][0]*100:.0f}–{bf['y'][1]*100:.0f}%"
                    f"{anch}{zg}{ags})")
            else:
                self._wood_bounds = None
                self._wood_bounds_raw = None
                self.pref_viewer.setAutoZ(None)

            self._update_range_summary()

            # Programmatic sync complete (sliders + auto-place): the job
            # lines now hold the detection, not user edits.
            self.pref_dirty = False

            # Fetch fresh preferences preview
            self._schedule_prefs_preview()
            self._refresh_results_views()     # the L/R box is final now: crop the Results

        except Exception as e:
            self.lbl_sample_sub.setText(f"Loaded but not processed yet: {e}")
        finally:
            self._applying_auto_snap = False

    # ---------------------------------------------------------------- Axial & Longitudinal
    def _on_axial_slider_changed(self, idx: int):
        self.axial_idx = int(idx)
        self._update_axial_frame(idx)

    def _update_axial_frame(self, idx: int):
        if not self.payload:
            return
        frames = self.payload.get("frames", [])
        if frames:
            # Processed specimen: scrub through the pre-rendered frame list.
            if 0 <= idx < len(frames):
                frame = frames[idx]
                z = frame.get("z", idx)
                self.lbl_axial_z.setText(f"z={z}")
                data_url = frame.get("png", "")
                pm = self._results_crop_axial(_b64_to_pixmap(data_url), z)
                self.axial_viewer.setPixmap(pm, self._payload_slices())
                self._refresh_results_sync()
            return
        # Unprocessed specimen: scrub the RAW scan: one source slice per
        # position, rendered on demand (nothing here needs report.json or
        # the stripped volume).
        if not self.dataset or not self.sample:
            return
        n = int((self.payload.get("report") or {}).get("n_slices") or 0)
        if not n:
            return
        zi = int(max(0, min(n - 1, idx)))
        try:
            sl = viewer_core._source_slices(
                viewer_core._get_ds(self.dataset, self.sample), self.sample, [zi])[zi]
            import numpy as _np
            rep = self.payload.get("report") or {}
            lo = float(rep.get("win_lo") or viewer_core.UNPROC_WIN[0])
            hi = float(rep.get("win_hi") or viewer_core.UNPROC_WIN[1])
            arr = _np.asarray(sl, _np.float32)
            img = viewer_core._axial_orig(
                arr, lo, hi, viewer_core.UNPROC_WIN[2],
                cmap="bone",
                is_kept=(self.pref_keep <= zi < auto_snap.delivered_cut(
                    self.pref_cut, self.pref_margin)),
                box=viewer_core._lateral_box(self.pref_viewer.axisBounds(), arr.shape),
                annotate=False)
            pm = _b64_to_pixmap(viewer_core._b64(img))
            self.axial_viewer.setPixmap(pm, n)
            self.lbl_axial_z.setText(f"z={zi}")
            self._refresh_results_sync()
        except Exception:
            pass

    def _toggle_long_view(self, view: str):
        self.long_view = view
        self._long_pos = None                      # the new plane starts in the middle
        self.btn_long_sag.setProperty("active", "true" if view == "sagittal" else "false")
        self.btn_long_cor.setProperty("active", "true" if view == "coronal" else "false")
        self.btn_long_sag.style().unpolish(self.btn_long_sag)
        self.btn_long_sag.style().polish(self.btn_long_sag)
        self.btn_long_cor.style().unpolish(self.btn_long_cor)
        self.btn_long_cor.style().polish(self.btn_long_cor)
        self._update_long_view()

    def _update_long_view(self):
        if not self.payload:
            return
        self._refresh_results_sync()
        self._refresh_results_long()

    def _refresh_results_views(self) -> None:
        """Results shown or loaded: re-crop the processed Results to the current
        L/R box, or re-predict a raw scan's longitudinal view.  Run on load, on
        the Results tab and on the plane toggle, not on every Boundaries edit
        (the Results tab is hidden while the lines move)."""
        if not self.payload or self._closing:
            return
        if self.payload.get("unprocessed"):
            self._refresh_results_long()
        else:
            self._update_axial_frame(self.axial_idx)
            self._update_long_view()

    def _results_crop_axial(self, pm: QPixmap, z: int) -> QPixmap:
        """Axial After: the L/R box, and blank outside the slices from Keep to Cut (the
        export keeps source[keep:cut]), on the lines on screen.  Display only."""
        if not self.pref_keep <= z < auto_snap.delivered_cut(self.pref_cut, self.pref_margin):
            return crop_after_panel(pm, (0.0, 0.0), None)   # (0, 0): the After is blank
        lat = self.pref_viewer.axisBounds()
        return crop_after_panel(pm, lat.get("x"), lat.get("y"))

    def _long_label(self, v: int) -> str:
        return f"{'x' if self.long_view == 'sagittal' else 'y'}={v}"

    def _on_long_slider_changed(self, v: int) -> None:
        self._long_pos = v
        self._results_long_gen += 1                # a render started before this move is stale
        self.lbl_long_pos.setText(self._long_label(v))
        self._long_timer.start(150)                # a drag renders once it settles

    def _refresh_results_long(self) -> None:
        """The longitudinal view is the Boundaries preview at the slider position (X for
        sagittal, Y for coronal), with the lines on screen, for processed and raw
        specimens alike.  It draws on a worker thread; the latest request wins."""
        if not self.payload or not self.dataset or self._closing:
            return
        lat = self.pref_viewer.axisBounds()
        key = (self.long_view, self._long_pos, self.pref_cut, self.pref_keep,
               self.pref_margin, tuple(sorted(lat.items())))
        if key == self._results_long_key:
            return
        self._results_long_key = key
        self._results_long_gen += 1
        worker = WorkerThread(
            viewer_core.get_preview, self.dataset, self.sample, cut=self.pref_cut,
            margin=self.pref_margin, keep_from=self.pref_keep, plane=self.long_view,
            pos=self._long_pos, width=640, cmap="bone", lo=self.pref_lo,
            hi=self.pref_hi, lateral=lat, annotate=False)
        worker.generation = self._results_long_gen
        worker.succeeded.connect(self._on_results_long_ready)
        worker.failed.connect(self._on_results_long_failed)
        self._results_workers = [w for w in self._results_workers if w.isRunning()] + [worker]
        worker.start()

    def _on_results_long_ready(self, prev: dict) -> None:
        worker = self.sender()
        if self._closing or getattr(worker, "generation", -1) != self._results_long_gen:
            return
        pos = int(prev.get("pos") or 0)
        self.long_viewer.setPixmap(_b64_to_pixmap(prev.get("png", "")),
                                   int(prev.get("n_slices") or 100))
        # the slider shows the position that was drawn (clamped), without a new render
        self.long_slider.blockSignals(True)
        self.long_slider.setRange(0, max(0, int(prev.get("span") or 1) - 1))
        self.long_slider.setValue(pos)
        self.long_slider.blockSignals(False)
        self.lbl_long_pos.setText(self._long_label(pos))

    def _on_results_long_failed(self, error: str) -> None:
        if not self._closing and getattr(self.sender(), "generation", -1) == self._results_long_gen:
            self.long_viewer.setPixmap(QPixmap(), 1)
            self.long_viewer.set_empty_text(f"Longitudinal view: {error}")

    @staticmethod
    def _set_row_visible(row_layout, visible: bool):
        for i in range(row_layout.count()):
            it = row_layout.itemAt(i)
            if it is None:
                continue
            w = it.widget()
            if w is not None:
                w.setVisible(visible)
            sub = it.layout()
            if sub is not None:
                for j in range(sub.count()):
                    it2 = sub.itemAt(j)
                    if it2 is not None and it2.widget() is not None:
                        it2.widget().setVisible(visible)

    # ---------------------------------------------------------------- 3D Actions
    def _set_3d_mode(self, mode: str):
        self.btn_3d_simple.setProperty("active", "true" if mode == "simple" else "false")
        self.btn_3d_real.setProperty("active", "true" if mode == "real" else "false")
        self.btn_3d_simple.style().unpolish(self.btn_3d_simple)
        self.btn_3d_simple.style().polish(self.btn_3d_simple)
        self.btn_3d_real.style().unpolish(self.btn_3d_real)
        self.btn_3d_real.style().polish(self.btn_3d_real)
        self.viewer_3d.setVisualMode(mode)

    def _toggle_spin_3d(self):
        self.viewer_3d.toggleSpin()

    def _on_spin_changed(self, spinning: bool):
        self.btn_spin_3d.setText("Stop" if spinning else "Spin")
        self.btn_spin_3d.setProperty("spinning", "true" if spinning else "false")
        self.btn_spin_3d.style().unpolish(self.btn_spin_3d)
        self.btn_spin_3d.style().polish(self.btn_spin_3d)

    # ---------------------------------------------------------------- Tabs & Navigation
    def _switch_tab(self, tab: str, schedule: bool = True):
        index = {"auto": 0, "prefs": 1, "settings": 2}.get(tab, 0)
        self.stack.setCurrentIndex(index)
        for name, button in (("auto", self.btn_tab_auto), ("prefs", self.btn_tab_prefs),
                             ("settings", self.btn_tab_settings)):
            button.setProperty("active", "true" if name == tab else "false")
            button.style().unpolish(button)
            button.style().polish(button)
        if tab == "prefs" and schedule:
            self._schedule_prefs_preview()
        if tab == "auto":
            self._refresh_results_views()

    # ---------------------------------------------------------------- Preferences Actions
    _CTRL_SEGMENTS = ("lines", "display", "lateral")

    def _set_ctrl_segment(self, key: str) -> None:
        """Show one group of the Boundaries controls; the others stay in the stack."""
        self.ctrl_stack.setCurrentIndex(self._CTRL_SEGMENTS.index(key))
        for name, button in self.ctrl_segments.items():
            button.setProperty("active", "true" if name == key else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def _set_pref_plane(self, plane: str):
        self.pref_plane = plane
        self.pref_viewer.setPlane(plane)
        self._log_action(f"Boundaries plane switched to: {plane}")
        self._update_lateral_panel_for_plane()
        for p, b in [("sagittal", self.btn_plane_sag), ("coronal", self.btn_plane_cor), ("axial", self.btn_plane_ax)]:
            b.setProperty("active", "true" if p == plane else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self._schedule_prefs_preview()

    def _on_guide_toggled(self, checked: bool):
        self.pref_viewer.setGuideEnabled(checked)

    def _update_lateral_panel_for_plane(self):
        """Plane-aware boundary-slider panel: relabel Left/Right for the
        axis they actually control, and show the axial Y rows only in the
        axial plane."""
        axis = "Y" if self.pref_plane == "sagittal" else "X"
        self.lbl_left.setText(f"Left {axis}:")
        self.lbl_right.setText(f"Right {axis}:")
        is_axial = self.pref_plane == "axial"
        self._set_row_visible(self.row_lat_top, is_axial)
        self._set_row_visible(self.row_lat_bottom, is_axial)
        self._sync_lateral_sliders_from_viewer()
        self.box_lateral.updateGeometry()

    def _sync_lateral_sliders_from_viewer(self):
        """Mirror the viewer's displayed bounds into the boundary sliders
        (the sliders always represent the lines visible in the current
        plane; the viewer owns the per-axis state)."""
        v = self.pref_viewer
        blocked = [self.spin_left, self.slider_left, self.spin_right,
                   self.slider_right, self.spin_top, self.slider_top,
                   self.spin_bottom, self.slider_bottom]
        for w in blocked:
            w.blockSignals(True)
        self.spin_left.setValue(int(round(v._x0 * 100)))
        self.slider_left.setValue(int(round(v._x0 * 100)))
        self.spin_right.setValue(int(round(v._x1 * 100)))
        self.slider_right.setValue(int(round(v._x1 * 100)))
        self.spin_top.setValue(int(round(v._y0 * 100)))
        self.slider_top.setValue(int(round(v._y0 * 100)))
        self.spin_bottom.setValue(int(round(v._y1 * 100)))
        self.slider_bottom.setValue(int(round(v._y1 * 100)))
        for w in blocked:
            w.blockSignals(False)

    # ------------------------------------------------- auto snap (audit 0AG)
    def _note_manual_lines_edit(self, what: str = "lines"):
        """Suspend auto-snap after a manual line edit (audit 0AG).

        Called from every user-facing line control (spins, sliders, viewer
        drags).  The copy layer stays paused until the next detection
        (load / re-detect), an explicit Snap, or re-arming the toggle, so
        manual work is never silently overwritten mid-session.
        """
        if self._applying_auto_snap:
            return
        chk = getattr(self, "chk_auto_snap", None)
        if chk is None or not chk.isChecked():
            return
        if self._auto_snap_suspended:
            return
        self._auto_snap_suspended = True
        if self._wood_bounds_raw:
            self._log_action(
                f"auto snap paused by manual {what} edit: re-applies on "
                "the next detection")

    def _apply_auto_snap(self, trigger: str, *, mark_clean: bool = True
                         ) -> list[str]:
        """Copy the current detection onto the cut lines (audit 0AG).

        Keep/Cut from the detected z lines (wood-top fallback when the air
        top deferred) plus BOTH lateral pairs from the detected envelope.
        The detection core is never re-measured here: this is the pure
        copy layer.  ``mark_clean`` clears ``pref_dirty`` (auto-applied
        lines are the detection, not user edits).  Returns log labels.
        """
        b = self._wood_bounds_raw or {}
        if not b:
            return []
        tg = auto_snap.detected_lines(b)
        placed: list[str] = []
        self._applying_auto_snap = True
        try:
            if tg["cut"] is not None:
                self.spin_cut.setValue(int(tg["cut"]))
                placed.append(f"cut={int(tg['cut'])}")
            if tg["keep"] is not None:
                cap = (self.spin_cut.value() - 1
                       if self.spin_cut.value() > 0 else 0)
                self.spin_keep.setValue(min(int(tg["keep"]), max(0, cap)))
                src = (" (wood top)"
                       if tg["keep_source"] == auto_snap.KEEP_SOURCE_WOOD_TOP
                       else "")
                placed.append(f"keep={self.spin_keep.value()}{src}")
            if tg["x"] and tg["y"]:
                self.pref_viewer.setAxisBounds({"x": tg["x"], "y": tg["y"]})
                self._sync_lateral_sliders_from_viewer()
                placed.append(
                    f"X {tg['x'][0] * 100:.0f}–{tg['x'][1] * 100:.0f}%, "
                    f"Y {tg['y'][0] * 100:.0f}–{tg['y'][1] * 100:.0f}%")
            if mark_clean:
                self.pref_dirty = False
        finally:
            self._applying_auto_snap = False
        self._auto_snap_suspended = False
        self._sync_kpi_effective()
        return placed

    def _on_auto_snap_toggled(self, on: bool):
        """Master switch: applying now when armed, leaving lines when off."""
        if on:
            placed = self._apply_auto_snap("toggle on")
            if placed:
                self._log_action("auto snap enabled: detection applied: "
                                 + ", ".join(placed))
            else:
                self._log_action(
                    "auto snap enabled: waiting for the next detection")
        else:
            self._log_action(
                "auto snap disabled: manual lines stay untouched across "
                "loads")

    def _sync_kpi_effective(self):
        """Re-render the KPI banner from the LIVE job lines (keep, cut)."""
        p = self.payload or {}
        if p.get("report"):
            self.kpi_banner.updateMetrics(
                p.get("report"), effective=(
                    self.pref_keep, auto_snap.delivered_cut(self.pref_cut, self.pref_margin)))

    def _snap_lines_to_detection(self):
        """Snap the interactive Keep/Cut lines onto the detected edges.

        Same mapping as the load-time auto-place (Keep ≡ air top,
        Cut ≡ metal top); a fog-deferred air top falls back to the
        detected wood top so the top line always lands on detection
        evidence.  A no-op dialog appears only when the specimen has no
        detection evidence at all.
        """
        # the auto-snap copy layer also re-arms itself: the lines now hold
        # the detection, so no manual override is pending
        changed = self._apply_auto_snap("snap")
        if changed:
            self._log_action("snapped lines to detection: " + ", ".join(changed))
        else:
            # an informational result belongs in the Activity line, not a popup
            self._log_action("snap to detection: no detection evidence for this "
                             "specimen; the lines are unchanged")

    def _set_guide_mode(self, mode: str):
        self.btn_guide_2l.setProperty("active", "true" if mode == "2lines" else "false")
        self.btn_guide_4l.setProperty("active", "true" if mode == "4lines" else "false")
        self.btn_guide_2l.style().unpolish(self.btn_guide_2l)
        self.btn_guide_2l.style().polish(self.btn_guide_2l)
        self.btn_guide_4l.style().unpolish(self.btn_guide_4l)
        self.btn_guide_4l.style().polish(self.btn_guide_4l)
        self.pref_viewer.setGuideMode(mode)
        self.box_lateral.setVisible(mode == "4lines")

    def _set_lateral(self, side: str, value: int) -> None:
        """Set the Left or Right boundary. Left stays at least
        LATERAL_MIN_GAP_PCT below Right, the band the viewer keeps; the spin,
        the slider and the viewer all take the clamped value."""
        if side == "left":
            value = max(0, min(value, self.spin_right.value() - LATERAL_MIN_GAP_PCT))
            widgets = (self.spin_left, self.slider_left)
        else:
            value = min(100, max(value, self.spin_left.value() + LATERAL_MIN_GAP_PCT))
            widgets = (self.spin_right, self.slider_right)
        for widget in widgets:
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        if side == "left":
            self.pref_viewer.setLeft(value)
        else:
            self.pref_viewer.setRight(value)
        self._schedule_prefs_preview()        # the AFTER panel follows the L/R box

    def _on_spin_left_changed(self, v: int):
        self._note_manual_lines_edit("Left")
        self._set_lateral("left", v)

    def _on_slider_left_changed(self, v: int):
        self._note_manual_lines_edit("Left")
        self._set_lateral("left", v)

    def _on_spin_top_changed(self, v: int):
        self._note_manual_lines_edit("Top")
        self.slider_top.setValue(v)
        self.pref_viewer.setTop(v)
        self._schedule_prefs_preview()

    def _on_slider_top_changed(self, v: int):
        self._note_manual_lines_edit("Top")
        self.spin_top.setValue(v)
        self.pref_viewer.setTop(v)
        self._schedule_prefs_preview()

    def _on_spin_bottom_changed(self, v: int):
        self._note_manual_lines_edit("Bottom")
        self.slider_bottom.setValue(v)
        self.pref_viewer.setBottom(v)
        self._schedule_prefs_preview()

    def _on_slider_bottom_changed(self, v: int):
        self._note_manual_lines_edit("Bottom")
        self.spin_bottom.setValue(v)
        self.pref_viewer.setBottom(v)
        self._schedule_prefs_preview()

    def _on_pref_left_dragged(self, v: int):
        self._note_manual_lines_edit("Left")
        self.spin_left.setValue(v)

    def _on_pref_top_dragged(self, v: int):
        self._note_manual_lines_edit("Top")
        self.spin_top.setValue(v)

    def _on_pref_bottom_dragged(self, v: int):
        self._note_manual_lines_edit("Bottom")
        self.spin_bottom.setValue(v)

    def _on_spin_right_changed(self, v: int):
        self._note_manual_lines_edit("Right")
        self._set_lateral("right", v)

    def _on_slider_right_changed(self, v: int):
        self._note_manual_lines_edit("Right")
        self._set_lateral("right", v)

    def _on_pref_right_dragged(self, v: int):
        self._note_manual_lines_edit("Right")
        self.spin_right.setValue(v)

    def _set_pref_cmap(self, cmap: str):
        self.pref_cmap = cmap
        self._log_action(f"Colorspace palette set to: {cmap}")
        for c, b in self.cmap_buttons.items():
            b.setProperty("active", "true" if c == cmap else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self.lbl_pref_head.setText(f"Original Reconstruction: {cmap.capitalize()} Colormap")
        self._schedule_prefs_preview()

    def _on_spin_lo_changed(self, v: int):
        self.slider_lo.setValue(v)
        self.pref_lo = float(v)
        # a manual threshold edit leaves the preset/reset row unhighlighted
        self._set_thresh_active(None)
        self._schedule_prefs_preview()

    def _on_slider_lo_changed(self, v: int):
        self.spin_lo.setValue(v)
        self.pref_lo = float(v)
        self._set_thresh_active(None)
        self._schedule_prefs_preview()

    def _on_spin_hi_changed(self, v: int):
        self.slider_hi.setValue(v)
        self.pref_hi = float(v)
        self._set_thresh_active(None)
        self._schedule_prefs_preview()

    def _on_slider_hi_changed(self, v: int):
        self.spin_hi.setValue(v)
        self.pref_hi = float(v)
        self._set_thresh_active(None)
        self._schedule_prefs_preview()

    # ---------------- threshold active-state model (Reset is the default) --
    def _sync_threshold_defaults(self):
        """Make Reset the active state with its baseline values applied.

        Re-applies the current baseline window (per-specimen, adopted from
        the calibrated report window) and highlights Reset.  Signals are
        blocked so this never schedules a preview by itself: callers
        fetch the preview explicitly.
        """
        blocked = [self.spin_lo, self.slider_lo, self.spin_hi, self.slider_hi]
        for w in blocked:
            w.blockSignals(True)
        try:
            self.spin_lo.setValue(int(round(self.pref_default_lo)))
            self.slider_lo.setValue(int(round(self.pref_default_lo)))
            self.spin_hi.setValue(int(round(self.pref_default_hi)))
            self.slider_hi.setValue(int(round(self.pref_default_hi)))
        finally:
            for w in blocked:
                w.blockSignals(False)
        self.pref_lo = float(self.pref_default_lo)
        self.pref_hi = float(self.pref_default_hi)
        self._set_thresh_active("reset")

    def _set_thresh_active(self, name: str | None):
        """Highlight the active threshold choice; None = Reset (baseline)."""
        btn_map = {"reset": getattr(self, "btn_th_reset", None),
                   "full": getattr(self, "btn_th_full", None),
                   "wood": getattr(self, "btn_th_wood", None),
                   "contrast": getattr(self, "btn_th_contrast", None),
                   "metal": getattr(self, "btn_th_metal", None)}
        for key, b in btn_map.items():
            if b is None:
                continue
            b.setProperty("active", "true" if key == name else "false")
            b.style().unpolish(b)
            b.style().polish(b)

    def _apply_thresh_preset(self, lo: float, hi: float, name: str):
        self.spin_lo.setValue(int(lo))
        self.spin_hi.setValue(int(hi))
        self._set_thresh_active(name)
        self._log_action(
            f"Threshold preset applied: {name} [{int(lo)}, {int(hi)}] "
            f"{getattr(self, '_intensity_display_unit', 'HU')}")

    def _reset_thresholds(self):
        self.spin_lo.setValue(int(self.pref_default_lo))
        self.spin_hi.setValue(int(self.pref_default_hi))
        self._set_thresh_active("reset")
        self._log_action(
            f"Reset density thresholds to baseline: "
            f"[{self.pref_default_lo}, {self.pref_default_hi}] "
            f"{getattr(self, '_intensity_display_unit', 'HU')}")

    def _on_spin_cut_changed(self, v: int):
        self._note_manual_lines_edit("Cut")
        self.slider_cut.setValue(v)
        self.pref_cut = v
        self.pref_dirty = True
        self.pref_viewer.setCut(v)
        # margin (safety buffer above cut) can never exceed the cut itself
        self.spin_margin.setRange(0, max(1, min(100, v)))
        self.slider_margin.setRange(0, max(1, min(100, v)))
        self._update_range_summary()
        self._schedule_prefs_preview()

    def _on_slider_cut_changed(self, v: int):
        self._note_manual_lines_edit("Cut")
        self.spin_cut.setValue(v)
        self.pref_cut = v
        self.pref_dirty = True
        self.pref_viewer.setCut(v)
        self.spin_margin.setRange(0, max(1, min(100, v)))
        self.slider_margin.setRange(0, max(1, min(100, v)))
        self._update_range_summary()
        self._schedule_prefs_preview()

    def _on_pref_cut_dragged(self, v: int):
        self._note_manual_lines_edit("Cut")
        self.spin_cut.blockSignals(True)
        self.slider_cut.blockSignals(True)
        # the spin clamps to the specimen's range: a stale viewer
        # coordinate space can emit out-of-range drag values, and the
        # job state must never exceed the loaded specimen
        self.spin_cut.setValue(v)
        self.slider_cut.setValue(self.spin_cut.value())
        self.spin_cut.blockSignals(False)
        self.slider_cut.blockSignals(False)
        self.pref_cut = self.spin_cut.value()
        self.pref_dirty = True
        self._update_range_summary()
        self._schedule_prefs_preview()

    def _on_spin_margin_changed(self, v: int):
        self._note_manual_lines_edit("Margin")
        self.slider_margin.setValue(v)
        self.pref_margin = v
        self.pref_dirty = True
        self._update_range_summary()
        self._schedule_prefs_preview()

    def _on_slider_margin_changed(self, v: int):
        self._note_manual_lines_edit("Margin")
        self.spin_margin.setValue(v)
        self.pref_margin = v
        self.pref_dirty = True
        self._update_range_summary()
        self._schedule_prefs_preview()

    def _on_spin_keep_changed(self, v: int):
        self._note_manual_lines_edit("Keep")
        self.slider_keep.setValue(v)
        self.pref_keep = v
        self.pref_dirty = True
        self.pref_viewer.setKeep(v)
        self._update_range_summary()
        self._schedule_prefs_preview()

    def _on_slider_keep_changed(self, v: int):
        self._note_manual_lines_edit("Keep")
        self.spin_keep.setValue(v)
        self.pref_keep = v
        self.pref_dirty = True
        self.pref_viewer.setKeep(v)
        self._update_range_summary()
        self._schedule_prefs_preview()

    def _on_pref_keep_dragged(self, v: int):
        self._note_manual_lines_edit("Keep")
        self.spin_keep.blockSignals(True)
        self.slider_keep.blockSignals(True)
        # clamp to the specimen's range like the cut drag (stale viewer
        # spaces must never push the job state out of range)
        self.spin_keep.setValue(v)
        self.slider_keep.setValue(self.spin_keep.value())
        self.spin_keep.blockSignals(False)
        self.slider_keep.blockSignals(False)
        self.pref_keep = self.spin_keep.value()
        self.pref_dirty = True
        self._update_range_summary()
        self._schedule_prefs_preview()

    def _on_pref_slice_scrubbed(self, z: int):
        # a drag on the preview sets Z (the cursor); the slider follows only in axial
        self._pref_z_explicit = z
        if self.pref_plane == "axial":
            self.pref_slider.setValue(z)
            self.lbl_pref_z.setText(f"z={z}")

    def _on_pref_slider_changed(self, v: int):
        # the slider scrubs the plane's own axis: X (sagittal), Y (coronal), Z (axial)
        if self.pref_plane == "axial":
            self._pref_z_explicit = v
        else:
            self._pref_pos = v
        self.lbl_pref_z.setText(self._pref_label(v))
        self._schedule_prefs_preview()

    def _pref_label(self, v: int) -> str:
        axis = {"sagittal": "x", "coronal": "y"}.get(self.pref_plane, "z")
        return f"{axis}={v}"

    def _pref_slider_for_plane(self, span: int, value: int) -> None:
        """Set the Boundaries slider to the axis the current plane scrubs."""
        self.pref_slider.blockSignals(True)
        self.pref_slider.setRange(0, max(0, span - 1))
        self.pref_slider.setValue(value)
        self.pref_slider.blockSignals(False)
        self.lbl_pref_z.setText(self._pref_label(value))

    def _valid_keep_cut(self) -> str | None:
        """Why the current Keep/Cut lines cannot be exported, or None."""
        if self.pref_keep >= auto_snap.delivered_cut(self.pref_cut, self.pref_margin):
            return "Keep line must be above the Cut line (keep < cut)."
        return None

    def _block_on_keep_cut(self) -> bool:
        """Show a Keep/Cut error in the export status; True when blocked."""
        err = self._valid_keep_cut()
        if err is None:
            return False
        self.lbl_export_status.setText(f"{err}")
        theme.set_role(self.lbl_export_status, "status-error")
        return True

    def _payload_slices(self) -> int:
        p = self.payload or {}
        return int((p.get("report") or {}).get("n_slices") or p.get("n_slices") or 100)

    def _processed_lines(self) -> tuple[int, int] | None:
        """(cut, keep) of the processed run on show; None for a raw scan."""
        p = self.payload or {}
        rep = p.get("report") or {}
        if not p or p.get("unprocessed") or rep.get("cut_from") is None:
            return None
        return int(rep["cut_from"]), int(rep.get("keep_from") or 0)

    def _refresh_results_sync(self) -> None:
        """The Results lines are the Boundaries lines (pending cut and keep, the L/R
        box, the detection guides), so the Before panel matches Boundaries.  The AFTER
        shows the processed run; the marker flags a processed run whose lines moved."""
        if not self.payload:
            self.lbl_results_stale.setVisible(False)
            return
        done = self._processed_lines()
        cut, keep = self.pref_cut, self.pref_keep
        n = self._payload_slices()
        lat = self.pref_viewer.axisBounds()          # the L/R box, as the AFTER crop uses it
        zb = ((self.payload or {}).get("bounds") or {}).get("zb")
        self.axial_viewer.setPlane("axial")
        self.long_viewer.setPlane(self.long_view)
        for viewer in (self.axial_viewer, self.long_viewer):
            viewer.setSliceCount(n)
            viewer.setCut(cut)
            viewer.setKeep(keep)
            viewer.setAxisBounds(lat)
        self.long_viewer.setAutoZ(zb)                # the Wood Top and Metal Top guides
        stale = done is not None and done != (
            auto_snap.delivered_cut(self.pref_cut, self.pref_margin), self.pref_keep)
        self.lbl_results_stale.setVisible(stale)
        if stale:
            self.lbl_results_stale.setToolTip(
                f"The lines on screen differ from the processed run (cut {done[0]}, "
                f"keep {done[1]}). Apply and process to update the stripped result.")

    def _update_range_summary(self):
        self._refresh_results_sync()
        if not self.payload:
            self.lbl_range_summary.setText("Load a specimen to adjust cut lines.")
            theme.set_role(self.lbl_range_summary, "secondary")
            self.btn_apply_prefs.setEnabled(False)
            return
        if (self.payload or {}).get("unprocessed"):
            self.lbl_range_summary.setText(
                "Specimen not processed yet: run Process")
            theme.set_role(self.lbl_range_summary, "accent")
            self.btn_apply_prefs.setEnabled(False)
            return
        err = self._valid_keep_cut()
        if err:
            self.lbl_range_summary.setText(f"{err}")
            theme.set_role(self.lbl_range_summary, "status-error")
            self.btn_apply_prefs.setEnabled(False)
            return
        cut = auto_snap.delivered_cut(self.pref_cut, self.pref_margin)
        kept = cut - self.pref_keep
        base = f"Delivery: slices {self.pref_keep}–{cut - 1}, {kept} slices"
        if self.pref_margin > 0:
            base += f", {self.pref_margin} held back from the Cut"
        self.lbl_range_summary.setText(base)
        theme.set_role(self.lbl_range_summary, "status-ok")
        self.btn_apply_prefs.setEnabled(True)

    def _schedule_prefs_preview(self):
        self._preview_generation += 1
        self._preview_timer.start(180)
        # The displayed PNG still represents the previous settings until the
        # newest generation paints; never save mismatched controls and pixels.
        if hasattr(self, "btn_save_checkpoint"):
            self.btn_save_checkpoint.setEnabled(False)

    def _fetch_prefs_preview(self):
        """Debounced request; preview decode/render stays off the GUI thread."""
        self._preview_timer.stop()
        if not self.dataset or not self.sample or self._closing:
            return
        request = {
            "generation": self._preview_generation,
            "dataset": self.dataset,
            "sample": self.sample,
            "cut": self.pref_cut,
            "margin": self.pref_margin,
            "keep_from": self.pref_keep,
            "plane": self.pref_plane,
            "z": self._pref_z_explicit,
            "pos": self._pref_pos,
            "lateral": self.pref_viewer.axisBounds(),
            "width": 640,
            "cmap": self.pref_cmap,
            "lo": self.pref_lo,
            "hi": self.pref_hi,
        }
        if self._preview_worker is not None and self._preview_worker.isRunning():
            # Keep only the latest request while an earlier preview owns the
            # shared viewer-cache lock. Scrubs cannot create a worker backlog.
            self._preview_pending_request = request
            return
        self._start_prefs_preview(request)

    def _start_prefs_preview(self, request: dict):
        if self._closing:
            return
        self._preview_pending_request = None
        worker = WorkerThread(
            viewer_core.get_preview, request["dataset"], request["sample"],
            cut=request["cut"], margin=request["margin"],
            keep_from=request["keep_from"], plane=request["plane"],
            z=request["z"], width=request["width"], cmap=request["cmap"],
            lo=request["lo"], hi=request["hi"],
            pos=request["pos"], lateral=request["lateral"], annotate=False,
        )
        worker.preview_generation = request["generation"]
        self._preview_worker = worker
        # Bound QObject slots are queued back to the GUI thread.
        worker.succeeded.connect(self._on_prefs_preview_ready)
        worker.failed.connect(self._on_prefs_preview_failed)
        worker.finished.connect(self._on_prefs_preview_finished)
        worker.start()

    def _on_prefs_preview_ready(self, prev: dict):
        worker = self.sender()
        generation = getattr(worker, "preview_generation", -1)
        if self._closing or generation != self._preview_generation:
            return

        n_slices = prev.get("n_slices", 100)
        actual_z = int(prev.get("z") or 0)
        if prev.get("plane") == "axial":
            self._pref_slider_for_plane(n_slices, actual_z)
        else:                                  # sagittal X / coronal Y from the render
            self._pref_pos = int(prev.get("pos") or 0)
            self._pref_slider_for_plane(int(prev.get("span") or n_slices), self._pref_pos)

        # The pixmap carries the real slice count: apply it FIRST, then
        # place the lines.  Applying the lines before setPixmap clamped
        # them to the previous coordinate space (the root cause of
        # "Snap to detection" leaving large volumes pinned mid-range).
        self.pref_viewer.setPixmap(_b64_to_pixmap(prev.get("png", "")), n_slices)
        self.pref_viewer.setCut(self.pref_cut)
        self.pref_viewer.setKeep(self.pref_keep)
        self.pref_viewer.setPlane(self.pref_plane)
        self.pref_viewer.setGuideEnabled(self.chk_guides.isChecked())

        # Threshold defaults are adopted lazily, once per specimen.
        if getattr(self, "_thresh_defaults_stale", False):
            if "default_lo" in prev:
                self.pref_default_lo = prev["default_lo"]
                self.pref_default_hi = prev["default_hi"]
            self._sync_threshold_defaults()

        self._preview_applied_generation = generation
        self._last_pref_preview = dict(prev)
        if self._history_restore_generation == generation:
            self._history_restore_generation = None
        else:
            self._record_session_preview()
        self._set_job_gates(process_ready=not bool((self.payload or {}).get("unprocessed")))

    def _on_prefs_preview_failed(self, error: str):
        worker = self.sender()
        generation = getattr(worker, "preview_generation", -1)
        if not self._closing and generation == self._preview_generation:
            self.lbl_range_summary.setText(f"Preview error: {error}")

    def _on_prefs_preview_finished(self):
        worker = self.sender()
        if worker is self._preview_worker:
            self._preview_worker = None
        request = self._preview_pending_request
        self._preview_pending_request = None
        if (not self._closing and request is not None and
                request["generation"] == self._preview_generation):
            self._start_prefs_preview(request)

    def _reset_to_detected(self):
        if not self.payload:
            return
        rep = self.payload.get("report", {})
        detected = rep.get("detected_cut_from") or rep.get("cut_from")
        if detected is None:
            return
        self.spin_margin.setValue(0)
        placed = self._apply_auto_snap("reset")
        if placed:
            self._log_action(
                f"reset to detected: {', '.join(placed)} "
                f"(delivered cut was {rep.get('cut_from')})")
        else:
            self.spin_cut.setValue(int(detected))
            self.spin_keep.setValue(0)
            self._log_action(
                f"reset to auto-detected cut: slice {detected} "
                f"(delivered cut was {rep.get('cut_from')})")

    def _lines_overrides(self, dataset: str, sample: str) -> dict | None:
        """The lines on screen as a processing job's overrides. A loaded specimen keeps
        them, so Process later uses the same lines. None when they cannot be saved."""
        overrides = {
            "cut_override": self.pref_cut,
            "cut_margin_slices": self.pref_margin,
            "keep_from": self.pref_keep,
            "air_crop": bool(self.chk_air_crop.isChecked()),
        }
        if dataset == "custom":
            try:
                csx.set_specimen_overrides(sample, {k: overrides[k] for k in csx.PREF_KEYS})
            except Exception as e:
                QMessageBox.critical(self, "Boundaries Error",
                                     f"Could not persist the preferences:\n{e}")
                return None
        return overrides

    def _apply_and_process(self):
        # Override and re-process with cut / keep / margin
        if not self.payload or self._loading:
            self.lbl_export_status.setText("Load a specimen before applying cut lines.")
            return
        if self._block_on_keep_cut():
            return
        dataset, sample = self.dataset, self.sample
        overrides = self._lines_overrides(dataset, sample)
        if overrides is None:
            return
        self._log_action(
            f"Applying cut override: cut={self.pref_cut}, keep={self.pref_keep}, "
            f"margin={self.pref_margin}, "
            f"air-crop={'on' if self.chk_air_crop.isChecked() else 'off'}")
        self._start_job("Apply lines",
                        lambda: self._run_pipeline_task(
                            overrides, dataset=dataset, sample=sample),
                        expected_duration=self._expected_process_s(), kind="process")

    # ---------------------------------------------------------------- Job Processing & Real ETA Engine
    def _start_job(self, label: str, func, expected_duration: float = 8.5,
                   kind: str = "process", progress_mode: str = "staged",
                   combined_split: float | None = None,
                   proc_duration: float | None = None):
        self._job_box_hide_timer.stop()      # a new job keeps the box visible
        if self._active_worker and self._active_worker.isRunning():
            QMessageBox.warning(self, "Busy", "Another operation is running.")
            return

        self._job_kind = kind
        self._job_progress_mode = progress_mode
        # Combined job state (audit 0O): staged process captions span the
        # bar up to P; the first real export signal owns [P, 99] after the
        # stage switch (see _on_job_progress).
        self._job_combined = (progress_mode == "combined")
        self._job_stage = "process" if self._job_combined else ""
        if self._job_combined:
            _p = 5 + int(max(0.05, min(0.95, combined_split or 0.85)) * 90)
            self._job_export_span = (_p, 99)
            self._job_proc_s = float(proc_duration or expected_duration)
        self._log_action(f"Started job: {label} (ETA: ~{int(expected_duration)}s)")
        self.job_box.setVisible(True)
        self.lbl_job_phase.setText(label)
        self.lbl_job_eta.setText(f"~{int(expected_duration)}s left")
        self.lbl_job_sub.setText("initializing compute backend…")
        self.job_progress.setValue(5)
        self.btn_process.setEnabled(False)
        self.btn_process_export.setEnabled(False)
        self.btn_apply_prefs.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.sample_list.setEnabled(False)
        self.combo_preview_history.setEnabled(False)
        self.btn_load_checkpoint.setEnabled(False)
        self.btn_save_checkpoint.setEnabled(False)
        self.btn_empty_load.setEnabled(False)

        t0 = time.time()

        # Dynamic multi-stage timer simulating granular pipeline stages with live ETA countdown
        self._job_timer = QTimer(self)
        self._job_timer.setInterval(250)
        # kind-specific stage captions (display only; the real work runs in
        # the worker thread and the ETA model is linear on expected_duration)
        if kind == "export":
            stages = [
                (0.30, "collecting kept slices from source…"),
                (0.70, "writing DICOM series & NIfTI volume…"),
                (1.01, "sidecar, provenance & verification…"),
            ]
        else:
            stages = [
                (0.25, "reading headers & pixel tensors…"),
                (0.55, "GPU metal detection & halo-slope anchor…"),
                (0.85, "wood ROI morph tracking & boundary cut…"),
                (1.01, "writing NIfTI-1 & DICOM series…"),
            ]

        def _staged_pct(frac: float):
            prev_bound, prev_pct = 0.0, 5
            for upto, text in stages:
                if frac < upto:
                    span = upto - prev_bound
                    return (prev_pct
                            + (frac - prev_bound) / max(span, 1e-6) * (95 - prev_pct),
                            text)
                prev_bound, prev_pct = upto, max(prev_pct, int(upto * 100) - 15)
            return 95.0, stages[-1][1]

        def _tick():
            elapsed = time.time() - t0

            if self._job_progress_mode == "real":
                # Live progress mode (audit 0M): the worker's progress
                # signal drives the bar and phase text; until the first
                # signal arrives the bar idles at its initial 5%.
                return

            if self._job_combined:
                # Combined job (audit 0O): staged process captions mapped
                # into [5, P]; once the export stage starts, the real
                # progress signals own the UI (see _on_job_progress).
                if self._job_stage != "process":
                    return
                frac = min(elapsed / max(self._job_proc_s, 1.0), 0.999)
                rem = max(0.5, self._job_proc_s - elapsed)
                self.lbl_job_eta.setText(f"~{int(rem)}s left")
                pct, text = _staged_pct(frac)
                lo, hi = self._job_export_span
                self.job_progress.setValue(
                    lo + int((pct - 5) / 90 * (hi - lo)))
                self.lbl_job_sub.setText(text)
                return

            rem = max(0.5, expected_duration - elapsed)
            self.lbl_job_eta.setText(f"~{int(rem)}s left")
            frac = min(elapsed / expected_duration, 0.999)
            pct, text = _staged_pct(frac)
            self.job_progress.setValue(min(95, int(pct)))
            self.lbl_job_sub.setText(text)

        self._job_timer.timeout.connect(_tick)
        self._job_timer.start()

        worker = WorkerThread(func)
        worker.succeeded.connect(self._on_job_finished)
        worker.failed.connect(self._on_job_error)
        worker.finished.connect(self._on_active_worker_finished)
        if progress_mode == "real":
            worker.with_progress = True
            worker.progress.connect(self._on_job_progress)
        self._active_worker = worker
        self._set_boundary_enabled(False)
        worker.start()

    def _on_active_worker_finished(self):
        worker = self.sender()
        if worker is self._active_worker:
            self._active_worker = None
        self._set_job_gates(process_ready=bool(
            self.payload and not self.payload.get("unprocessed")))

    _EXPORT_PHASE_LABELS = {
        "preparing": "preparing bundle destination…",
        "dicom": "writing DICOM series…",
        "nifti": "writing NIfTI volume (streamed blocks)…",
        "sidecar": "sidecar, provenance & file mapping…",
        "verify": "verifying bundle integrity…",
    }

    @Slot(int, int, str)
    def _on_job_progress(self, i: int, n: int, phase: str):
        """Live progress from a worker thread (audit 0M): real fraction,
        real phase caption, honest ETA from measured rate.  For combined
        jobs (audit 0O) the first signal switches the staged process stage
        to the real export stage and maps the fraction into [P, 99]."""
        if getattr(self, "_job_combined", False) and self._job_stage == "process":
            self._job_stage = "export"
            self.job_progress.setValue(self._job_export_span[0])
            self.lbl_job_eta.setText("exporting…")
            self.lbl_job_sub.setText("process complete: exporting bundle…")
        if getattr(self, "_job_combined", False):
            if n <= 0:
                self.lbl_job_sub.setText(
                    self._EXPORT_PHASE_LABELS.get(phase, f"{phase}…"))
                return
            lo, hi = self._job_export_span
            frac = max(0.0, min(1.0, i / n))
            self.job_progress.setValue(lo + int(frac * (hi - lo)))
            base = self._EXPORT_PHASE_LABELS.get(phase, phase)
            self.lbl_job_sub.setText(f"{base}  ({i:,} / {n:,})")
            if phase in ("dicom", "nifti"):
                self.lbl_job_eta.setText(
                    f"{phase} {int(frac * 100)}%, checking…")
            return
        if n <= 0:
            self.job_progress.setValue(5)
            self.lbl_job_sub.setText(
                self._EXPORT_PHASE_LABELS.get(phase, f"{phase}…"))
            return
        frac = max(0.0, min(1.0, i / n))
        # 5..99 span so completion (100) stays a distinct final state
        self.job_progress.setValue(5 + int(frac * 94))
        base = self._EXPORT_PHASE_LABELS.get(phase, phase)
        self.lbl_job_sub.setText(f"{base}  ({i:,} / {n:,})")
        if phase in ("dicom", "nifti"):
            self.lbl_job_eta.setText(
                f"{phase} {int(frac * 100)}%, checking…")

    def _run_pipeline_task(self, overrides=None, *, dataset=None, sample=None):
        # Capture the target at queue time so a delayed worker can never read
        # a newer sidebar selection and process the wrong specimen.
        dataset = self.dataset if dataset is None else dataset
        sample = self.sample if sample is None else sample
        if dataset == "custom":
            spec_info = csx.registered_specimens().get(sample)
            if not spec_info:
                raise RuntimeError(f"Specimen {sample} not found")
            ds = csx.as_dataset(sample)
        else:
            ds = tg.DATASETS[dataset]
        cfg_dict = dict(ds.config_overrides)
        # Allocate 16 parallel threads for high-throughput I/O on 20-core CPU & fast NVMe
        cfg_dict["io_workers"] = 16
        if dataset == "custom":
            cfg_dict["save_stripped_nii"] = True
        if overrides:
            for k in csx.PREF_KEYS:
                if k in overrides and overrides[k] is not None:
                    cfg_dict[k] = int(overrides[k])
            if overrides.get("air_crop") is not None:
                cfg_dict["air_crop"] = bool(overrides["air_crop"])
        if cfg_dict.get("cut_override") is not None:      # the delivery stops above the margin
            cfg_dict["cut_override"] = auto_snap.delivered_cut(
                cfg_dict["cut_override"], cfg_dict.get("cut_margin_slices") or 0)

        cfg = tg.DEFAULTS.overridden(cfg_dict)
        cfg.io_workers = 16
        gpu = tg.get_backend(verbose=False, preference="auto")

        # Call pipeline with exact signature: (name, cfg, ds, diagnose_only, gpu, verbose)
        r = tg.process_sample(sample, cfg, ds, False, gpu, verbose=False)
        return {"report": r, "dataset": dataset, "sample": sample}

    def _expected_process_s(self) -> float:
        """Honest ETA seed for process jobs (audit 0N).

        Curated datasets: measured fleet medians.  Custom series scale with
        slice count (measured 0.123 s/slice on the real 2-21: 1067 slices,
        131 s including streamed delivery writes): floored so tiny series
        never show a near-zero countdown.
        """
        if self.dataset == "custom":
            info = csx.registered_specimens().get(self.sample) or {}
            n = int(info.get("n_slices") or 0)
            return max(30.0, n * 0.125) if n else 120.0
        return 8.5 if self.dataset == "66um" else 28.0

    def _process_selected(self):
        if not self.payload or self._loading:
            self.lbl_export_status.setText("Load a specimen before processing.")
            return
        dataset, sample = self.dataset, self.sample
        air = bool(self.chk_air_crop.isChecked())    # read here: the worker never touches widgets
        self._log_action(f"Triggered processing on {dataset}/{sample}")
        self._start_job(f"Processing {sample}",
                        lambda: self._run_pipeline_task({"air_crop": air}, dataset=dataset,
                                                        sample=sample),
                        expected_duration=self._expected_process_s(),
                        kind="process")

    def _expected_export_s(self) -> float:
        """Honest ETA seed for the export stage of combined jobs (audit 0O).

        Measured on the real 2-21 bundle (969 kept slices, DICOM+NIfTI):
        14.9 s → ~0.016 s/kept-slice; small curated specimens floor at 4 s.
        """
        if self.dataset == "custom":
            info = csx.registered_specimens().get(self.sample) or {}
            n = int(info.get("n_slices") or 0)
            if n:
                return max(6.0, n * 0.016)
        return 4.0 if self.dataset == "66um" else 15.0

    def _process_and_export(self):
        """Process and export in one job. The lines on screen are applied first (as Apply
        lines does), so the export delivers exactly the run it processed."""
        if not self.payload or self._loading:
            self.lbl_export_status.setText("Load a specimen before processing and export.")
            return
        if self._block_on_keep_cut():
            return
        dataset, sample = self.dataset, self.sample
        lateral = self._export_lateral(dataset, sample)
        dest_root = self._validated_dest_root()
        if dest_root is None:
            return
        if not self._confirm_replace_export(dest_root, sample):
            return
        srcs = self._resolve_sources()
        if srcs is None:
            QMessageBox.critical(self, "Export Error",
                                 f"Specimen {sample} not found.")
            return
        overrides = self._lines_overrides(dataset, sample)
        if overrides is None:
            return
        _ds, src_dir, src_over, out_dir = srcs
        fmt = (self.export_format if _ds.source_kind == "dicom"
               else bundle_export.FORMAT_NIFTI)
        fmt_name = self._EXPORT_FORMAT_ITEMS[self._format_index(fmt)][0]
        proc_s = self._expected_process_s()
        exp_s = self._expected_export_s()
        split = proc_s / max(proc_s + exp_s, 1e-6)
        self._log_action(
            f"Process and export queued for {dataset}/{sample} → "
            f"{dest_root} (format: {fmt_name})")

        def _task(job_progress=None):
            # Stage 1: process with the lines on screen. Stage 2: export the fresh report.
            proc_res = self._run_pipeline_task(overrides, dataset=dataset,
                                               sample=sample) or {}
            report_p = out_dir / "report.json"
            if not report_p.exists():
                raise RuntimeError(
                    "processing finished but report.json is missing: "
                    "export aborted")
            report = json.loads(report_p.read_text(encoding="utf-8"))
            stripped = out_dir / "stripped.nii"
            if not stripped.exists():
                stripped = out_dir / "stripped.nii.gz"
            exp_res = bundle_export.export_bundle(
                dataset, sample, src_dir, report, stripped, dest_root,
                source_override=src_over,
                export_format=fmt, progress=job_progress,
                source_kind=_ds.source_kind,
                source_path=_ds.source_path,
                source_metadata=_ds.source_metadata,
                lateral=lateral) or {}
            exp_res["sample"] = sample
            return {"report": proc_res.get("report", {}),
                    "export": exp_res, "sample": sample,
                    "dataset": dataset}

        self._start_job(f"Process and export {self.sample}", _task,
                        expected_duration=proc_s + exp_s,
                        kind="process_export", progress_mode="combined",
                        combined_split=split, proc_duration=proc_s)

    def _log_process_result(self, rep: dict) -> None:
        """Log the process-job result lines (cut slice + air-crop)."""
        plat = rep.get("platform", {}) if isinstance(rep, dict) else {}
        cut_done = plat.get("cut_from", "—") if isinstance(plat, dict) else "—"
        self._log_action(f"Job finished successfully. Result cut slice: {cut_done}")
        ac = (rep.get("wood_roi", {}) or {}).get("air_crop") \
            if isinstance(rep, dict) else None
        if isinstance(ac, dict) and ac.get("ok"):
            bb = ac.get("bbox_zyx") or []
            self._log_action(
                "  air-crop: wood-tight ROI " +
                (f"z{bb[0]}..{bb[1]}  y{bb[2]}..{bb[3]}  x{bb[4]}..{bb[5]}"
                 if len(bb) == 6 else "applied"))
        elif isinstance(ac, dict) and not ac.get("ok"):
            self._log_action(
                "  air-crop: tracker ROI kept "
                f"({ac.get('fallback_reason') or 'guard trip'})")

    def _log_export_result(self, exp: dict) -> None:
        """Set the export status line + log the delivered bundle."""
        sample = exp.get("sample") or self.sample
        self.lbl_export_status.setText(f"Bundle exported: {sample}")
        theme.set_role(self.lbl_export_status, "status-ok")
        self._set_state_chip("exported")
        fmt = exp.get("export_format", "both")
        _fmt_detail = ("DICOM + NIfTI" if fmt == "both"
                       else "DICOM series" if fmt == "dicom"
                       else "NIfTI volume")
        self._log_action(
            f"Extraction bundle exported ({_fmt_detail}): "
            f"{exp.get('bundle_dir', '')}")

    def _on_job_finished(self, res: dict):
        if hasattr(self, "_job_timer") and self._job_timer.isActive():
            self._job_timer.stop()
        self.job_progress.setValue(100)
        kind = self._job_kind
        was_export = kind in ("export", "process_export")
        self.lbl_job_phase.setText(
            "Processing and export complete" if kind == "process_export"
            else "Export complete" if was_export else "Processing complete")
        self.lbl_job_eta.setText("done")
        self.lbl_job_sub.setText(
            "Payloads written. Bundle exported and verified."
            if kind == "process_export"
            else "Delivery bundle verified and written."
            if was_export else "Payloads and montages written.")
        self.btn_process.setEnabled(True)
        self.btn_process_export.setEnabled(True)
        self.btn_apply_prefs.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_load.setEnabled(True)
        self.sample_list.setEnabled(True)
        self.combo_preview_history.setEnabled(True)
        self.btn_load_checkpoint.setEnabled(True)
        self.btn_save_checkpoint.setEnabled(bool(
            self._last_pref_preview is not None or self._checkpoint_snapshot_only))
        self.btn_empty_load.setEnabled(True)
        self._job_combined = False
        self._job_stage = ""
        self._set_boundary_enabled(True)
        if kind == "process_export":
            self._log_process_result(res.get("report", {}) or {})
            self._log_export_result(res.get("export", {}) or {})
        elif was_export:
            self._log_export_result(res)
        else:
            self._log_process_result(res.get("report", {}))
        if self._closing:
            return      # window is going away: start no new load
        self._job_box_hide_timer.start()
        report = res.get("report", {}) or {}
        if (kind in ("process", "process_export")
                and report.get("dataset", self.dataset) == self.dataset
                and report.get("sample", self.sample) == self.sample):
            self._select_sample(self.dataset, self.sample)

    def _on_job_error(self, err: str):
        if hasattr(self, "_job_timer") and self._job_timer.isActive():
            self._job_timer.stop()
        self.job_box.setVisible(False)
        self.btn_process.setEnabled(True)
        self.btn_process_export.setEnabled(True)
        self.btn_apply_prefs.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_load.setEnabled(True)
        self.sample_list.setEnabled(True)
        self.combo_preview_history.setEnabled(True)
        self.btn_load_checkpoint.setEnabled(True)
        self.btn_save_checkpoint.setEnabled(bool(
            self._last_pref_preview is not None or self._checkpoint_snapshot_only))
        self.btn_empty_load.setEnabled(True)
        self._set_job_gates(
            process_ready=bool(self.payload and not self.payload.get("unprocessed")))
        self._job_combined = False
        self._job_stage = ""
        self._set_boundary_enabled(True)
        if self._job_kind in ("export", "process_export"):
            self.lbl_export_status.setText("Export failed")
            theme.set_role(self.lbl_export_status, "status-error")
        if self._closing:
            self._log_action(f"Operation failed while closing: {err}")
            return
        plain = user_messages.pipeline_error(err)
        QMessageBox.critical(self, "Processing Error",
                             f"{plain}\n\nDetails: {err}")

    # ---------------------------------------------------------------- Export Bundle
    def _wrap_long_labels(self) -> None:
        """Long explanations wrap onto more lines instead of setting the minimum
        width of the window. An unwrapped sentence pushed the window to about
        2,500 px, which is wider than most screens."""
        from PySide6.QtWidgets import QSizePolicy
        for lbl in self.findChildren(QLabel):
            if lbl.property("nowrap"):          # a single-line element: legend, path, chip
                continue
            if len(lbl.text()) > 28 and lbl.property("role") not in ("title", "section"):
                lbl.setWordWrap(True)
        for box in self.findChildren(QCheckBox):
            if len(box.text()) > 28:
                box.setSizePolicy(QSizePolicy.Ignored, box.sizePolicy().verticalPolicy())
        for attr, name in ACCESSIBLE_NAMES.items():
            widget = getattr(self, attr, None)
            if widget is not None and not widget.accessibleName():
                widget.setAccessibleName(name)
        for attr, tip in TIPS.items():
            widget = getattr(self, attr, None)
            if widget is not None and not widget.toolTip():
                widget.setToolTip(tip)

    def _brand_html(self) -> str:
        """The wordmark: the 'CT' takes the accent of the active theme."""
        return f"clean<span style='color:{theme.color('accent')};'>CT</span>"

    def _on_theme_changed(self, index: int) -> None:
        """Switch the chrome between dark and light, and remember the choice."""
        chosen = self.cmb_theme.itemData(index) or "dark"
        theme.set_mode(chosen)
        theme.apply(QApplication.instance())
        # colours written into rich text or built into rows must follow the theme too
        self.lbl_brand.setText(self._brand_html())
        for label, build in self._key_rows:
            label.setText(build())
        self._refresh_sidebar()
        self.update()
        try:
            settings = bundle_export.load_settings(STATE)
            settings["theme"] = chosen
            bundle_export.save_settings(STATE, settings)
        except Exception as e:
            self._log_action(f"could not save the appearance: {e}")

    def _persist_save_root(self, path: str):
        """Remember the export destination across sessions (settings.json)."""
        self.save_root = path
        try:
            settings = bundle_export.load_settings(STATE)
            settings["save_root"] = path
            bundle_export.save_settings(STATE, settings)
        except Exception as e:
            self._log_action(f"could not persist export folder: {e}")

    def _on_save_root_edited(self):
        typed = self.edit_save_root.text().strip()
        if not typed:
            # an empty folder is not a folder: put the working one back
            self.edit_save_root.setText(self.save_root)
            return
        if typed != self.save_root:
            # typed edits are remembered like Browse picks (they were not before)
            self._persist_save_root(typed)
            self._log_action(f"Default export folder updated: {typed}")
        self._refresh_export_summary()

    def _browse_save_root(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Extraction Bundle Destination", self.save_root)
        if dir_path:
            self.edit_save_root.setText(dir_path)
            self._persist_save_root(dir_path)
            self._log_action(f"Default export folder updated: {dir_path}")
            self._refresh_export_summary()

    def _format_index(self, fmt: str) -> int:
        for i, (_label, val) in enumerate(self._EXPORT_FORMAT_ITEMS):
            if val == fmt:
                return i
        return 0

    def _on_export_format_changed(self, idx: int):
        self._refresh_export_summary()
        if getattr(self, "_setting_export_format", False):
            return
        fmt = self._EXPORT_FORMAT_ITEMS[idx][1]
        self.export_format = fmt
        try:
            settings = bundle_export.load_settings(STATE)
            settings["export_format"] = fmt
            bundle_export.save_settings(STATE, settings)
        except Exception as e:
            self._log_action(f"could not persist export format: {e}")
        self._log_action(f"Export format set to: "
                         f"{self._EXPORT_FORMAT_ITEMS[idx][0]}")

    def _set_export_source_kind(self, source_kind: str) -> None:
        """Disable DICOM bundle choices for sources without DICOM metadata."""
        is_dicom = str(source_kind).lower() == "dicom"
        self._setting_export_format = True
        try:
            self.combo_export_format.setEnabled(is_dicom)
            if is_dicom:
                index = self._format_index(self.export_format)
                self.combo_export_format.setToolTip(
                    "Choose which source-faithful formats to include in the bundle.")
            else:
                index = self._format_index(bundle_export.FORMAT_NIFTI)
                self.combo_export_format.setToolTip(
                    "TIFF/NIfTI sources have no DICOM acquisition tags. "
                    "The bundle uses a geometry-preserving NIfTI export.")
            self.combo_export_format.setCurrentIndex(index)
        finally:
            self._setting_export_format = False
        self._refresh_export_summary()

    def _set_intensity_controls(self, report_summary: dict) -> None:
        """Label threshold controls with the source's actual intensity unit."""
        unit = str(report_summary.get("intensity_unit") or "HU")
        is_hu = unit.strip().upper() == "HU"
        self._intensity_display_unit = "HU" if is_hu else "stored intensity"
        if is_hu:
            self.chk_air_crop.setToolTip(AIR_CROP_TIP)
        else:
            self.chk_air_crop.setToolTip(
                "Use the source's low-intensity percentile as the background/air "
                "threshold. These values are stored grayscale units, not HU; the "
                "processing report records the estimated threshold range.")
        if is_hu:
            self.lbl_th_head.setText("2D Density Thresholds (HU)")
            self.lbl_min_thresh.setText("Min HU:")
            self.lbl_max_thresh.setText("Max HU:")
            lo_limits, hi_limits = (-2000, 2000), (-1000, 3000)
        else:
            self.lbl_th_head.setText("2D Intensity Window (stored values)")
            self.lbl_min_thresh.setText("Min value:")
            self.lbl_max_thresh.setText("Max value:")
            value_range = report_summary.get("value_range") or []
            values = [float(v) for v in value_range[:2]
                      if v is not None and math.isfinite(float(v))]
            values.extend([float(report_summary.get("win_lo", 0)),
                           float(report_summary.get("win_hi", 1))])
            low, high = min(values), max(values)
            margin = max(1.0, (high - low) * 0.1)
            limits = (max(-2_000_000_000, math.floor(low - margin)),
                      min(2_000_000_000, math.ceil(high + margin)))
            if limits[0] >= limits[1]:
                limits = (limits[0] - 1, limits[1] + 1)
            lo_limits = hi_limits = limits
        blocked = (self.spin_lo, self.slider_lo, self.spin_hi, self.slider_hi)
        for widget in blocked:
            widget.blockSignals(True)
        try:
            self.spin_lo.setRange(*lo_limits)
            self.slider_lo.setRange(*lo_limits)
            self.spin_hi.setRange(*hi_limits)
            self.slider_hi.setRange(*hi_limits)
        finally:
            for widget in blocked:
                widget.blockSignals(False)

    def _validated_dest_root(self) -> Path | None:
        """Validate (and remember) the bundle destination; returns None on
        failure with the reason already shown to the user."""
        dest_root = Path(self.edit_save_root.text().strip())
        if not dest_root or str(dest_root) in ("", "."):
            QMessageBox.warning(self, "Missing Destination",
                                "Please set the bundle destination folder.")
            return None
        try:
            dest_root.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Invalid Destination",
                                 f"Cannot create the destination folder:\n{e}")
            return None
        # A validated typed path becomes the remembered default too.
        self._persist_save_root(str(dest_root))
        return dest_root

    def _resolve_sources(self):
        """Resolve (ds, src_dir, src_over, out_dir) for the current
        selection; None when the custom specimen is not registered."""
        if self.dataset == "custom":
            spec_info = csx.registered_specimens().get(self.sample)
            if not spec_info:
                return None
            ds = csx.as_dataset(self.sample)
            src_dir = (Path(ds.source_path)
                       if ds.source_kind != "dicom" and ds.source_path
                       else csx.DATA_DIR / self.sample)
            src_over = (spec_info.get("source_path") or
                        spec_info.get("source_folder"))
        else:
            ds = tg.DATASETS[self.dataset]
            src_dir = ds.source / self.sample
            src_over = None
        out_dir = tg.output_root(ds) / self.sample
        return ds, src_dir, src_over, out_dir

    def _confirm_replace_export(self, dest_root: Path, sample: str) -> bool:
        """Ask before a re-export replaces the bundle already in that folder."""
        target = dest_root / sample
        if not target.exists():
            return True
        answer = QMessageBox.question(
            self, "Replace export",
            f"Replace the existing export for {sample}?\n\n{target}\n\n"
            "The new bundle replaces it only after it is written and verified.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _export_lateral(self, dataset: str, sample: str) -> dict | None:
        """The L/R lines on screen, both pairs: the export crops the wood box to them,
        as it takes the Keep and Cut lines on screen for Z."""
        if dataset != "custom":
            return None
        return self.pref_viewer.axisBounds()

    def _export_bundle(self):
        if not self.payload or self._loading:
            self.lbl_export_status.setText("Load and process a specimen before exporting.")
            return
        if self._block_on_keep_cut():
            return
        dataset, sample = self.dataset, self.sample
        lateral = self._export_lateral(dataset, sample)
        dest_root = self._validated_dest_root()
        if dest_root is None:
            return
        if not self._confirm_replace_export(dest_root, sample):
            return
        srcs = self._resolve_sources()
        if srcs is None:
            QMessageBox.critical(self, "Export Error",
                                 f"Specimen {sample} not found.")
            return
        _ds, src_dir, src_over, out_dir = srcs
        self.lbl_export_status.setText("Exporting bundle…")
        theme.set_role(self.lbl_export_status, "accent")
        self._log_action(f"Exporting extraction bundle for {dataset}/{sample} to {dest_root}")

        report_p = out_dir / "report.json"
        if not report_p.exists():
            QMessageBox.warning(self, "Not Processed Yet",
                                "This sample has not been processed yet: run Process first.")
            return
        report = json.loads(report_p.read_text(encoding="utf-8"))
        stripped = out_dir / "stripped.nii"
        if not stripped.exists():
            stripped = out_dir / "stripped.nii.gz"

        # Per-specimen lines: honor what the user adjusted in this session
        # (Preferences) when they differ from the stored report: the export
        # must deliver exactly the validated cut/keep range on screen.
        plat = report.get("platform") or {}
        processed_cut = int(plat.get("cut_from") or 0)
        _eff_cut = (auto_snap.delivered_cut(self.pref_cut, self.pref_margin) if self.pref_cut
                    else processed_cut)
        if _eff_cut > processed_cut:       # the processed run holds no data past its own cut
            self.lbl_export_status.setText(
                "The Cut is past the processed run. Apply lines and process again, then export.")
            theme.set_role(self.lbl_export_status, "status-error")
            return
        _eff_keep = (int(self.pref_keep)
                     if self.pref_keep is not None
                     else int(plat.get("keep_from") or 0))
        if _eff_cut > 0 and (_eff_cut != int(plat.get("cut_from") or 0)
                             or _eff_keep != int(plat.get("keep_from") or 0)):
            plat["cut_from"] = _eff_cut
            plat["keep_from"] = _eff_keep
            self._log_action(
                f"  exporting with session lines: cut {_eff_cut}, "
                f"keep {_eff_keep}")

        fmt = self.export_format
        if _ds.source_kind != "dicom":
            fmt = bundle_export.FORMAT_NIFTI
        fmt_name = self._EXPORT_FORMAT_ITEMS[
            self._format_index(fmt)][0]
        self._log_action(f"  export format: {fmt_name}")

        def _do_export(job_progress=None):
            result = bundle_export.export_bundle(
                dataset, sample, src_dir, report, stripped,
                dest_root, source_override=src_over,
                export_format=fmt,
                source_kind=_ds.source_kind,
                source_path=_ds.source_path,
                source_metadata=_ds.source_metadata,
                lateral=lateral,
                progress=job_progress)
            result["sample"] = sample
            return result

        exp_s = 4.0 if self.dataset == "66um" else 15.0
        self._start_job(f"Exporting {self.sample}", _do_export,
                        expected_duration=exp_s, kind="export",
                        progress_mode="real")

    # ---------------------------------------------------------------- Shutdown
    def closeEvent(self, event):
        """Drain active work before closing so no QThread outlives its owner."""
        self._closing = True
        self._preview_timer.stop()
        self._preview_pending_request = None
        running = [w for w in (getattr(self, "_gpu_worker", None),
                               getattr(self, "_load_worker", None),
                               getattr(self, "_active_worker", None),
                               getattr(self, "_preview_worker", None))
                   if w is not None and w.isRunning()]
        running.extend(w for w in getattr(self, "_specimen_meta_workers", [])
                       if w is not None and w.isRunning())
        if running:
            # the window stays on screen and says what it waits for: a processing
            # step cannot be stopped midway, so closing waits for the step to end
            self.job_box.setVisible(True)
            self.lbl_job_phase.setText("Finishing the current step before closing")
            self.lbl_job_eta.setText("")
            self.job_progress.setRange(0, 0)
            self.setEnabled(False)
            while any(w.isRunning() for w in running):
                QApplication.processEvents()
                time.sleep(0.02)
        # predicted Results views are short previews: let them end quietly, after the
        # label above is set (_closing stops their result handler from touching the window)
        for w in self._results_workers:
            while w.isRunning():
                QApplication.processEvents()
                time.sleep(0.02)
        self._specimen_meta_workers.clear()
        self._session_preview_history.clear()
        self.combo_preview_history.clear()
        self._last_pref_preview = None
        event.accept()

    # ---------------------------------------------------------------- Dialogs
    def _checkpoint_source_identity(self, dataset: str | None = None,
                                    sample: str | None = None) -> tuple[str, str]:
        dataset = dataset or self.dataset
        sample = sample or self.sample
        if dataset == "custom":
            entry = csx.registered_specimens().get(sample) or {}
            return (str(entry.get("source_path") or entry.get("source_folder") or ""),
                    str(entry.get("source_kind") or "dicom"))
        kind = ""
        report_path = ""
        try:
            if dataset in tg.DATASETS:
                report_path = str((tg.output_root(tg.DATASETS[dataset]) /
                                   sample).resolve())
                report_file = Path(report_path) / "report.json"
                if report_file.is_file():
                    data = json.loads(report_file.read_text(encoding="utf-8"))
                    report = data.get("report", data) if isinstance(data, dict) else {}
                    kind = str(report.get("source_kind") or
                               (report.get("meta") or {}).get("source_kind") or "")
        except Exception:
            pass
        return report_path, kind

    def _capture_checkpoint_state(self) -> dict:
        preview = self._last_pref_preview or {}
        n_slices = int(preview.get("n_slices") or
                       ((self.payload or {}).get("report") or {}).get("n_slices") or 1)
        z = self._pref_z_explicit
        if z is None and preview.get("z") is not None:
            z = int(preview["z"])
        bounds = self.pref_viewer.axisBounds()
        return {
            "dataset": self.dataset,
            "sample": self.sample,
            "cut": int(self.pref_cut),
            "keep": int(self.pref_keep),
            "margin": int(self.pref_margin),
            "plane": self.pref_plane,
            "z": z,
            "n_slices": max(1, n_slices),
            "cmap": self.pref_cmap,
            "lo": float(self.pref_lo),
            "hi": float(self.pref_hi),
            "bounds": {axis: [float(pair[0]), float(pair[1])]
                       for axis, pair in bounds.items()},
            "guide_mode": str(self.pref_viewer._guide_mode),
            "guides": bool(self.chk_guides.isChecked()),
            "air_crop": bool(self.chk_air_crop.isChecked()),
            "pref_dirty": bool(self.pref_dirty),
            "long_view": self.long_view,
            "axial_idx": int(self.axial_idx),
            "tab": "prefs" if self.stack.currentIndex() == 1 else "auto",
        }

    def _make_checkpoint_document(self) -> dict:
        if not self.dataset or not self.sample:
            raise checkpoint_file.CheckpointError("Load a specimen or checkpoint preview first.")
        preview = self._last_pref_preview or {}
        png = str(preview.get("png") or "")
        if not png:
            raise checkpoint_file.CheckpointError(
                "Wait for a preview to finish before saving a checkpoint.")
        source_path, source_kind = self._checkpoint_source_identity()
        # the live preview can be a wide strip of slices: store a fitted thumbnail
        png = checkpoint_file.fit_preview(png)
        return checkpoint_file.new_document(
            self._capture_checkpoint_state(), preview_png=png,
            source_path=source_path, source_kind=source_kind)

    def save_checkpoint_file(self, path: str | Path) -> Path:
        """Save the current preview and controls to a safe, data-only file."""
        return checkpoint_file.save_checkpoint(
            path, self._make_checkpoint_document())

    def _open_save_checkpoint(self):
        if not self.dataset or not self.sample:
            QMessageBox.information(self, "Save checkpoint",
                                    "Load a specimen before saving a checkpoint.")
            return
        default_name = f"{self.sample}.ctcheckpoint.json"
        start = str(Path(self.checkpoint_dir) / default_name) if self.checkpoint_dir else default_name
        path, _ = QFileDialog.getSaveFileName(
            self, "Save preview checkpoint", start,
            "cleanCT checkpoint (*.ctcheckpoint.json);;JSON file (*.json)")
        if not path:
            return
        destination = Path(path)
        if not destination.name.lower().endswith(".json"):
            destination = destination.with_name(destination.name + ".ctcheckpoint.json")
        try:
            self.save_checkpoint_file(destination)
            self._remember_checkpoint_dir(str(destination.parent))
            self.lbl_export_status.setText(f"Checkpoint saved, {destination.name}")
            self._log_action(f"Saved preview checkpoint: {destination}")
        except Exception as exc:
            QMessageBox.critical(self, "Checkpoint error", str(exc))

    @staticmethod
    def _same_source_path(a: str, b: str) -> bool:
        """Canonical path comparison: resolve() expands 8.3 short names
        (LABPC~1 -> the long user folder) and Windows PurePath
        equality is case-insensitive, so a checkpoint recorded under a
        different spelling of the same folder still reconnects."""
        if not a or not b:
            return False
        try:
            return Path(a).resolve() == Path(b).resolve()
        except OSError:
            return os.path.normcase(os.path.abspath(a)) == \
                os.path.normcase(os.path.abspath(b))

    def _checkpoint_source_available(self, document: dict) -> bool:
        state = document["state"]
        dataset, sample = state["dataset"], state["sample"]
        recorded_path = str(document.get("source_path") or "")
        recorded_kind = str(document.get("source_kind") or "")
        try:
            if dataset == "custom":
                entry = csx.registered_specimens().get(sample)
                if not entry:
                    return False
                current_path = str(entry.get("source_path") or
                                   entry.get("source_folder") or "")
                current_kind = str(entry.get("source_kind") or "dicom")
                if (not self._same_source_path(recorded_path, current_path) or
                        (recorded_kind and recorded_kind != current_kind)):
                    return False
                return Path(current_path).exists()
            if dataset not in tg.DATASETS:
                return False
            output = (tg.output_root(tg.DATASETS[dataset]) / sample).resolve()
            if recorded_path and not self._same_source_path(
                    recorded_path, str(output)):
                return False
            report_path = output / "report.json"
            if not report_path.is_file():
                return False
            if recorded_kind:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                report = report.get("report", report) if isinstance(report, dict) else {}
                current_kind = str(
                    report.get("source_kind") or
                    (report.get("meta") or {}).get("source_kind") or "")
                if current_kind and current_kind != recorded_kind:
                    return False
            return True
        except (OSError, KeyError, TypeError, ValueError):
            return False

    def _apply_checkpoint_controls(self, state: dict,
                                   schedule: bool = True) -> int | None:
        """Apply a validated state without emitting a cascade of previews."""
        rep = (self.payload or {}).get("report") or {}
        n = max(1, int(rep.get("n_slices") or state.get("n_slices") or 1))
        cut = min(n, int(state["cut"]))
        keep = min(max(0, int(state["keep"])), max(0, cut - 1))
        margin = min(100, cut, int(state["margin"]))
        self.pref_cut, self.pref_keep, self.pref_margin = cut, keep, margin
        self.pref_plane = state["plane"]
        self.pref_cmap = state["cmap"]
        self.pref_lo = max(-2000.0, min(2000.0, float(state["lo"])))
        self.pref_hi = max(-1000.0, min(3000.0, float(state["hi"])))
        if self.pref_hi <= self.pref_lo:
            self.pref_hi = min(3000.0, self.pref_lo + 1.0)
        self.pref_dirty = bool(state.get("pref_dirty", False))
        # A restored checkpoint is the user's manual line state: suspend
        # auto-snap so the restore is never overwritten mid-session; the
        # next detection (load / re-detect) re-arms and re-applies (0AG).
        self._auto_snap_suspended = True
        self.long_view = state.get("long_view", "sagittal")
        self.axial_idx = min(n - 1, int(state.get("axial_idx", 0)))
        self._pref_z_explicit = (None if state.get("z") is None else
                                 min(n - 1, int(state["z"])))

        for widget in (self.spin_cut, self.slider_cut):
            widget.blockSignals(True)
            widget.setRange(0, n)
            widget.setValue(cut)
            widget.blockSignals(False)
        for widget in (self.spin_margin, self.slider_margin):
            widget.blockSignals(True)
            widget.setRange(0, max(1, min(100, cut)))
            widget.setValue(margin)
            widget.blockSignals(False)
        for widget in (self.spin_keep, self.slider_keep):
            widget.blockSignals(True)
            widget.setRange(0, n)
            widget.setValue(keep)
            widget.blockSignals(False)
        for widget, value in ((self.spin_lo, round(self.pref_lo)),
                              (self.slider_lo, round(self.pref_lo)),
                              (self.spin_hi, round(self.pref_hi)),
                              (self.slider_hi, round(self.pref_hi))):
            widget.blockSignals(True)
            widget.setValue(int(value))
            widget.blockSignals(False)
        self.pref_lo = float(self.spin_lo.value())
        self.pref_hi = float(self.spin_hi.value())

        self.pref_viewer.setPlane(self.pref_plane)
        # the checkpoint's slice count may describe a different (larger)
        # specimen when the source changed under the same ID: declare
        # the clamped real count so restored lines can never exceed it
        self.pref_viewer.setSliceCount(n)
        self.pref_viewer.setAxisBounds(state.get("bounds") or {})
        self.pref_viewer.setCut(cut)
        self.pref_viewer.setKeep(keep)
        self._set_guide_mode(state.get("guide_mode", "2lines"))
        self.chk_guides.setChecked(bool(state.get("guides", True)))
        self.pref_viewer.setGuideEnabled(self.chk_guides.isChecked())
        self.chk_air_crop.setChecked(bool(state.get("air_crop", True)))
        self._update_lateral_panel_for_plane()
        self._toggle_long_view(self.long_view)

        cmap_key = self.pref_cmap.lower()
        for key, button in self.cmap_buttons.items():
            button.setProperty("active", "true" if key == cmap_key else "false")
            button.style().unpolish(button)
            button.style().polish(button)
        self._set_thresh_active(None)
        self.axial_slider.blockSignals(True)
        self.axial_slider.setRange(0, n - 1)
        self.axial_slider.setValue(self.axial_idx)
        self.axial_slider.blockSignals(False)
        self._pref_slider_for_plane(n, self._pref_z_explicit or 0)
        self._switch_tab(state.get("tab", "auto"), schedule=False)
        self._update_range_summary()
        self._set_job_gates(process_ready=bool(
            self.payload is not None and
            not (self.payload or {}).get("unprocessed")))
        if schedule and self.payload is not None:
            self._schedule_prefs_preview()
            return self._preview_generation
        return None

    def _record_session_preview(self):
        if not self.dataset or not self.sample:
            return
        # A checkpoint-only snapshot session does not append history
        # entries: the snapshot itself is already presented, so recording
        # it would create a duplicate history item.
        if self._checkpoint_snapshot_only:
            return
        try:
            state = self._capture_checkpoint_state()
        except Exception:
            return
        if (self._session_preview_history and
                self._session_preview_history[-1]["state"] == state):
            return
        source_path, source_kind = self._checkpoint_source_identity()
        entry = {"state": state, "source_path": source_path,
                 "source_kind": source_kind}
        self._session_preview_history.append(entry)
        combo = self.combo_preview_history
        combo.blockSignals(True)
        try:
            if combo.count() == 1 and combo.itemData(0, Qt.UserRole) is None:
                combo.clear()
            slice_no = state.get("z")
            full = (f"{datetime.now().strftime('%H:%M')}  {self.sample}, "
                    f"{self.pref_plane}, slice {slice_no if slice_no is not None else 'auto'}")
            # elide to the box, and keep the full text as the tooltip
            shown = combo.fontMetrics().elidedText(full, Qt.ElideRight, 210)
            combo.addItem(shown, entry)
            combo.setItemData(combo.count() - 1, full, Qt.ToolTipRole)
            combo.setCurrentIndex(combo.count() - 1)
        finally:
            combo.blockSignals(False)
        self._set_job_gates(process_ready=not bool(
            (self.payload or {}).get("unprocessed")))

    def _restore_session_history(self, index: int):
        entry = self.combo_preview_history.itemData(index, Qt.UserRole)
        if not isinstance(entry, dict):
            return
        state = dict(entry.get("state") or {})
        # A history entry represents a preview; bring that view forward.
        state["tab"] = "prefs"
        dataset, sample = state.get("dataset"), state.get("sample")
        if not dataset or not sample:
            return
        if (dataset == self.dataset and sample == self.sample and
                (self.payload is not None or self._checkpoint_snapshot_only)):
            generation = self._apply_checkpoint_controls(state, schedule=True)
            self._history_restore_generation = generation
            self.lbl_export_status.setText(f"Preview restored, {sample}")
            return
        document = {
            "schema": checkpoint_file.SCHEMA, "version": checkpoint_file.VERSION,
            "state": state, "source_path": entry.get("source_path", ""),
            "source_kind": entry.get("source_kind", ""), "preview_png": "",
        }
        if not self._checkpoint_source_available(document):
            self.lbl_export_status.setText(
                "That history item needs its source, which is no longer available.")
            return
        self._pending_view_restore = state
        self._pending_view_restore_kind = "history"
        self._select_sample(dataset, sample)
        self.lbl_export_status.setText(f"Restoring preview, {sample}")

    def _open_load_checkpoint(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load preview checkpoint", self.checkpoint_dir,
            "cleanCT checkpoint (*.ctcheckpoint.json *.json);;All files (*.*)")
        if not path:
            return
        try:
            self.load_checkpoint_file(path)
            self._remember_checkpoint_dir(str(Path(path).parent))
        except Exception as exc:
            QMessageBox.critical(self, "Checkpoint error", str(exc))

    def load_checkpoint_file(self, path: str | Path) -> dict:
        """Restore the lightweight snapshot immediately, then reconnect source if present."""
        if self._loading or (self._active_worker is not None and
                             self._active_worker.isRunning()):
            raise checkpoint_file.CheckpointError(
                "Wait for the current load or processing job to finish.")
        document = checkpoint_file.load_checkpoint(path)
        if not document.get("preview_png"):
            raise checkpoint_file.CheckpointError(
                "This checkpoint has no preview image to restore.")
        # previews still in flight belong to the specimen being replaced
        self._preview_generation += 1
        state = document["state"]
        self._pending_select = None
        self._pending_view_restore = None
        self._pending_view_restore_kind = ""
        self.payload = None
        self.dataset, self.sample = state["dataset"], state["sample"]
        self._checkpoint_snapshot_only = True
        self._last_pref_preview = {
            "png": document["preview_png"],
            "n_slices": state["n_slices"],
            "z": state["z"] if state["z"] is not None else 0,
        }
        self.lbl_sample_title.setText(self.sample)
        self.lbl_sample_sub.setText("Checkpoint preview snapshot")
        self.lbl_export_status.setText("Restored checkpoint snapshot")
        self.kpi_banner.updateMetrics({"empty": True})
        self.viewer_3d.setData(None)
        self.pref_viewer.setPixmap(
            _b64_to_pixmap(document["preview_png"]), state["n_slices"])
        self.pref_viewer.setPlane(state["plane"])
        self._apply_checkpoint_controls(state, schedule=False)
        # The embedded checkpoint image is the preview pane; make it visible
        # even when the saved working tab was Auto.
        self._switch_tab("prefs", schedule=False)
        self._set_empty_state(False)
        self._set_job_gates(process_ready=False)
        self._record_session_preview()

        if self._checkpoint_source_available(document):
            self._pending_view_restore = state
            self._pending_view_restore_kind = "checkpoint"
            self.lbl_sample_sub.setText(
                "Checkpoint preview restored: reconnecting to source…")
            self._select_sample(state["dataset"], state["sample"])
        else:
            self.lbl_sample_sub.setText(
                "Checkpoint snapshot only: its original source is unavailable. "
                "Load the source again to process or export.")
            self.lbl_export_status.setText("Snapshot only, source unavailable")
        return document

    def _open_about_dialog(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def _open_load_dialog(self):
        dlg = LoadDialog(self)
        if not dlg.exec():
            return
        # Register the validated source (junction/registry work; sources
        # were already validated inside the dialog).
        sp_id = dlg.specimen_id
        fld = dlg.folder_path
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            entry = csx.register_series(Path(fld), sp_id,
                                        intensity=dlg.intensity_mode)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Load Error",
                                 f"Failed to register specimen:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self._refresh_sidebar()
        self._select_sample("custom", entry["specimen"])
        self._log_action(
            f"registered {entry['specimen']} "
            f"({entry.get('n_slices', '?')} slices @ "
            f"{float(entry.get('pixel_um') or 0):.4g} µm)")
