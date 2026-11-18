from __future__ import annotations

import base64
import io
import json
import os
import sys
import threading
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if (not os.environ.get("CLEANCT_ENGINE") or not os.environ.get("CLEANCT_DATA")
        or not os.environ.get("CLEANCT_TEST_TMP_DIR")):
    raise SystemExit("Set isolated CLEANCT_ENGINE, CLEANCT_DATA, and "
                     "CLEANCT_TEST_TMP_DIR paths first")
TEST_TMP = Path(os.environ["CLEANCT_TEST_TMP_DIR"])
TEST_TMP.mkdir(parents=True, exist_ok=True)
APP = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(APP))

from PIL import Image
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import main_window as mw
from widgets.viewer_2d import Viewer2D
from widgets.viewer_3d import Viewer3D

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def pump_until(app, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


class NoStartupIOWindow(mw.MainWindow):
    def _check_gpu(self):
        self._gpu_worker = None

    def _refresh_sidebar(self):
        pass

    def _update_lateral_panel_for_plane(self):
        pass

    def _select_sample(self, ds: str, sample: str, _async: bool = True):
        pass


class MissingOutputWindow(mw.MainWindow):
    """Keep normal sidebar construction while suppressing all source I/O."""
    def _check_gpu(self):
        self._gpu_worker = None

    def _update_lateral_panel_for_plane(self):
        pass

    def _select_sample(self, ds: str, sample: str, _async: bool = True):
        pass


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    dark = QColor("#12151b")
    for viewer_type in (Viewer2D, Viewer3D):
        viewer = viewer_type()
        viewer.setMinimumSize(0, 0)
        viewer.resize(1, 1)
        viewer.show()
        app.processEvents()
        pixel = viewer.grab().toImage().pixelColor(0, 0)
        check(f"{viewer_type.__name__} paints opaque 1x1 resize",
              pixel == dark, str(pixel.getRgb()))
        viewer.close()

    original_output_root = mw.tg.output_root
    empty_root = Path(tempfile.mkdtemp(prefix="cleanct_empty_output_",
                                      dir=TEST_TMP)) / "outputs"
    mw.tg.output_root = lambda _ds: empty_root
    empty_window = None
    try:
        empty_window = MissingOutputWindow()
        item_data = [empty_window.sample_list.item(i).data(Qt.UserRole)
                     for i in range(empty_window.sample_list.count())]
        check("first-run missing output folders show a clear empty state",
              empty_window.sample_list.count() == 1
              and item_data == [None]
              and not empty_window.empty_state.isHidden()
              and not empty_window.stack.isHidden()
              and empty_window.btn_load.isEnabled()
              and empty_window.btn_process.isEnabled() is False
              and empty_window.btn_process_export.isEnabled() is False
              and empty_window.btn_export.isEnabled() is False,
              f"count={empty_window.sample_list.count()}, data={item_data}, "
              f"empty_hidden={empty_window.empty_state.isHidden()}")
    except Exception as exc:
        check("first-run missing output folders keep sidebar usable", False,
              f"{type(exc).__name__}: {exc}")
    finally:
        app.processEvents()
        mw.tg.output_root = original_output_root

    if empty_window is not None:
        checkpoint_path = TEST_TMP / "empty-state.ctcheckpoint.json"
        try:
            empty_window.dataset = "custom"
            empty_window.sample = "preview-only"
            empty_window.pref_cut = 6
            empty_window.pref_keep = 2
            empty_window.pref_margin = 1
            empty_window.pref_plane = "axial"
            empty_window.pref_cmap = "thermal"
            empty_window.pref_lo = -700.0
            empty_window.pref_hi = 450.0
            empty_window.pref_viewer.setPlane("axial")
            empty_window.pref_viewer.setAxisBounds(
                {"x": [0.2, 0.8], "y": [0.25, 0.75]})
            empty_window.pref_viewer.setGuideMode("4lines")
            empty_window._last_pref_preview = {
                "png": "",
                "n_slices": 8, "z": 3,
            }
            # Build a tiny PNG before saving (the rendering worker is not run here).
            preview_bytes = io.BytesIO()
            Image.new("RGB", (8, 8), (32, 64, 96)).save(preview_bytes, format="PNG")
            empty_window._last_pref_preview["png"] = (
                "data:image/png;base64," +
                base64.b64encode(preview_bytes.getvalue()).decode("ascii"))
            empty_window.save_checkpoint_file(checkpoint_path)
            restored = empty_window.load_checkpoint_file(checkpoint_path)
            check("checkpoint restores its preview snapshot without scan data",
                  restored["state"]["sample"] == "preview-only"
                  and empty_window.payload is None
                  and empty_window._checkpoint_snapshot_only
                  and not empty_window.pref_viewer._pixmap.isNull()
                  and empty_window.pref_cut == 6
                  and empty_window.pref_keep == 2
                  and empty_window.pref_margin == 1
                  and empty_window.pref_plane == "axial"
                  and empty_window.pref_cmap == "thermal"
                  and empty_window.pref_viewer._guide_mode == "4lines"
                  and empty_window.pref_viewer.axisBounds()["x"] == (0.2, 0.8)
                  and empty_window.btn_process.isEnabled() is False
                  and empty_window.btn_export.isEnabled() is False,
                  f"snapshot={empty_window._checkpoint_snapshot_only}, "
                  f"payload={empty_window.payload}")
            check("checkpoint-only snapshot does not append a duplicate history entry",
                  len(empty_window._session_preview_history) == 0
                  and empty_window.combo_preview_history.count() == 1
                  and empty_window._checkpoint_snapshot_only,
                  f"history={len(empty_window._session_preview_history)}, "
                  f"snapshot={empty_window._checkpoint_snapshot_only}, "
                  f"count={empty_window.combo_preview_history.count()}, "
                  f"item0={empty_window.combo_preview_history.itemText(0)!r}")
            empty_window._checkpoint_snapshot_only = False
            empty_window._record_session_preview()
            check("session preview history remains available through empty state",
                  len(empty_window._session_preview_history) == 1
                  and empty_window.combo_preview_history.count() == 1,
                  f"history={len(empty_window._session_preview_history)}")
        except Exception as exc:
            check("checkpoint restores its preview snapshot without scan data",
                  False, f"{type(exc).__name__}: {exc}")
        finally:
            try:
                checkpoint_path.unlink(missing_ok=True)
            except OSError:
                pass
            empty_window.close()
            app.processEvents()

    # A checkpoint with a still-registered processed specimen must reconnect
    # asynchronously and restore process-capable preview controls.
    reconnect_root = TEST_TMP / "checkpoint_reconnect_outputs"
    reconnect_dir = reconnect_root / "1-restore"
    reconnect_dir.mkdir(parents=True, exist_ok=True)
    (reconnect_dir / "report.json").write_text(
        json.dumps({"report": {"source_kind": "dicom"}}), encoding="utf-8")
    original_output_root = mw.tg.output_root
    original_build_payload = mw.viewer_core.build_payload
    mw.tg.output_root = lambda _ds: reconnect_root

    def checkpoint_payload(dataset, sample):
        return {
            "unprocessed": True, "sample": sample, "dataset": dataset,
            "source_kind": "dicom",
            "report": {"n_slices": 8, "voxel_mm": 33.0,
                       "win_lo": -950.0, "win_hi": 350.0},
            "bounds": None,
        }

    class CheckpointReconnectWindow(mw.MainWindow):
        def _check_gpu(self):
            self._gpu_worker = None

        def _refresh_sidebar(self):
            pass

    mw.viewer_core.build_payload = checkpoint_payload
    reconnect_window = None
    reconnect_file = TEST_TMP / "checkpoint-reconnect.ctcheckpoint.json"
    try:
        reconnect_window = CheckpointReconnectWindow()
        reconnect_window._schedule_prefs_preview = lambda: None
        state = {
            "dataset": "24um", "sample": "1-restore",
            "cut": 6, "keep": 2, "margin": 1, "n_slices": 8,
            "plane": "coronal", "z": 3, "cmap": "viridis",
            "lo": -500.0, "hi": 500.0,
            "bounds": {"x": [0.2, 0.8], "y": [0.25, 0.75]},
            "guide_mode": "4lines", "guides": True, "air_crop": True,
            "pref_dirty": True, "long_view": "coronal", "axial_idx": 4,
            "tab": "prefs",
        }
        reconnect_preview_bytes = io.BytesIO()
        Image.new("RGB", (8, 8), (72, 96, 120)).save(
            reconnect_preview_bytes, format="PNG")
        reconnect_png = ("data:image/png;base64," +
                         base64.b64encode(reconnect_preview_bytes.getvalue()).decode("ascii"))
        document = mw.checkpoint_file.new_document(
            state, reconnect_png, source_path=str(reconnect_dir),
            source_kind="dicom")
        mismatch = {**document, "source_path": str(TEST_TMP / "different-source")}
        check("checkpoint rejects a same-ID specimen from a different source path",
              not reconnect_window._checkpoint_source_available(mismatch))
        mw.checkpoint_file.save_checkpoint(reconnect_file, document)
        reconnect_window.load_checkpoint_file(reconnect_file)
        reconnected = pump_until(
            app,
            lambda: not reconnect_window._loading
            and not reconnect_window._load_workers,
            timeout=5.0,
        )
        check("checkpoint reconnects to an available source asynchronously",
              reconnected and reconnect_window.payload is not None
              and reconnect_window.payload.get("unprocessed")
              and not reconnect_window._checkpoint_snapshot_only
              and reconnect_window.btn_process.isEnabled()
              and reconnect_window.pref_cut == 6
              and reconnect_window.pref_keep == 2
              and reconnect_window.pref_plane == "coronal"
              and reconnect_window.pref_cmap == "viridis",
              f"loaded={reconnected}, payload={bool(reconnect_window.payload)}, "
              f"snapshot={reconnect_window._checkpoint_snapshot_only}, "
              f"sub={reconnect_window.lbl_sample_sub.text()!r}, "
              f"pending={reconnect_window._pending_select}")
    except Exception as exc:
        check("checkpoint reconnects to an available source asynchronously",
              False, f"{type(exc).__name__}: {exc}")
    finally:
        if reconnect_window is not None:
            reconnect_window.close()
        app.processEvents()
        mw.tg.output_root = original_output_root
        mw.viewer_core.build_payload = original_build_payload
        reconnect_file.unlink(missing_ok=True)

    image_buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (18, 21, 27)).save(image_buffer, format="PNG")
    png = "data:image/png;base64," + base64.b64encode(image_buffer.getvalue()).decode()
    calls: list[tuple[int, float]] = []
    gui_thread = threading.get_ident()

    def slow_preview(dataset, sample, **kwargs):
        lo = float(kwargs["lo"])
        calls.append((threading.get_ident(), lo))
        time.sleep(0.55 if lo == -950.0 else 0.02)
        return {
            "n_slices": 8, "z": 3, "png": png,
            "default_lo": -950.0, "default_hi": 350.0,
        }

    original = mw.viewer_core.get_preview
    mw.viewer_core.get_preview = slow_preview
    window = NoStartupIOWindow()
    window.dataset, window.sample = "custom", "synthetic-preview"
    window.payload = {"unprocessed": True, "report": {"n_slices": 8}}
    window._thresh_defaults_stale = False
    pulse_count = [0]
    pulse = QTimer(window)
    pulse.setInterval(15)
    pulse.timeout.connect(lambda: pulse_count.__setitem__(0, pulse_count[0] + 1))
    pulse.start()
    try:
        window.pref_lo = -950.0
        window._schedule_prefs_preview()
        check("checkpoint save waits for a matching preview generation",
              not window.btn_save_checkpoint.isEnabled())
        check("first preview starts in a worker",
              pump_until(app, lambda: len(calls) == 1),
              f"calls={calls}")
        first_thread = calls[0][0] if calls else gui_thread

        window.pref_lo = -600.0
        window._schedule_prefs_preview()
        latest_generation = window._preview_generation
        ok = pump_until(
            app,
            lambda: (window._preview_applied_generation == latest_generation
                     and window._preview_worker is None),
            timeout=5.0,
        )
        check("preview worker keeps the GUI event loop responsive",
              pulse_count[0] >= 10, f"timer ticks={pulse_count[0]}")
        check("stale preview is discarded and latest request is applied",
              ok and len(calls) == 2 and calls[-1][1] == -600.0
              and window._preview_applied_generation == latest_generation
              and window.btn_save_checkpoint.isEnabled(),
              f"calls={calls}, applied={window._preview_applied_generation}")
        check("preview rendering never runs on the GUI thread",
              len(calls) == 2 and all(tid != gui_thread for tid, _ in calls),
              f"gui={gui_thread}, workers={calls}")
    finally:
        pulse.stop()
        window.close()
        app.processEvents()
        mw.viewer_core.get_preview = original

    # Latest selection wins when several sidebar clicks arrive during a load.
    original_build_payload = mw.viewer_core.build_payload
    load_calls: list[str] = []

    def delayed_payload(dataset, sample):
        load_calls.append(sample)
        if sample == "slow":
            time.sleep(0.25)
        return {
            "unprocessed": True, "sample": sample, "dataset": dataset,
            "report": {"n_slices": 8, "voxel_mm": 33.0,
                       "win_lo": -950.0, "win_hi": 350.0},
            "bounds": None,
        }

    class QueueTestWindow(mw.MainWindow):
        def __init__(self):
            self._suppress_initial_load = True
            super().__init__()
            self._suppress_initial_load = False

        def _check_gpu(self):
            self._gpu_worker = None

        def _refresh_sidebar(self):
            pass

        def _update_lateral_panel_for_plane(self):
            pass

        def _select_sample(self, ds, sample, _async=True):
            if self._suppress_initial_load:
                return
            return mw.MainWindow._select_sample(self, ds, sample, _async)

    mw.viewer_core.build_payload = delayed_payload
    queue_window = QueueTestWindow()
    queue_window._schedule_prefs_preview = lambda: None
    try:
        queue_window._select_sample("synthetic", "slow")
        pump_until(app, lambda: len(load_calls) == 1)
        queue_window._select_sample("synthetic", "latest")
        loaded_latest = pump_until(
            app,
            lambda: queue_window.sample == "latest" and not queue_window._loading,
            timeout=5.0,
        )
        pump_until(app, lambda: not queue_window._load_workers)
        check("latest sidebar selection is loaded after an in-flight load",
              loaded_latest and load_calls == ["slow", "latest"],
              f"calls={load_calls}, sample={queue_window.sample}")
    finally:
        queue_window.close()
        app.processEvents()
        mw.viewer_core.build_payload = original_build_payload

    # Processing jobs capture the selected specimen when queued.
    snapshot_window = NoStartupIOWindow()
    queued = {}
    snapshot_window.dataset, snapshot_window.sample = "66um", "1-1"
    snapshot_window.payload = {"unprocessed": True, "report": {"n_slices": 8}}
    snapshot_window._start_job = lambda label, func, **kw: queued.update(func=func)
    original_backend, original_process = mw.tg.get_backend, mw.tg.process_sample
    observed = {}

    def fake_process(name, cfg, ds, diagnose_only, gpu, verbose=True):
        observed.update(sample=name, dataset=ds.key)
        return {"sample": name, "dataset": ds.key}

    mw.tg.get_backend = lambda **kw: object()
    mw.tg.process_sample = fake_process
    try:
        snapshot_window._process_selected()
        snapshot_window.dataset, snapshot_window.sample = "24um", "changed"
        result = queued["func"]()
        check("queued processing cannot switch to a later sidebar selection",
              observed == {"sample": "1-1", "dataset": "66um"}
              and result["sample"] == "1-1"
              and result["dataset"] == "66um", str(observed))
    finally:
        mw.tg.get_backend, mw.tg.process_sample = original_backend, original_process
        snapshot_window.close()
        app.processEvents()

    # Empty/truncated processed NIfTI files must reach the ordinary load-error
    # state instead of leaving a half-alive QThread or hanging the window.
    from types import SimpleNamespace

    corrupt_root = TEST_TMP / "corrupt_nifti_outputs"
    corrupt_root.mkdir(parents=True, exist_ok=True)
    bad_inputs = {
        "empty_nii": ("stripped.nii", b""),
        "truncated_nii_gz": ("stripped.nii.gz", b"\x1f\x8b\x08\x00bad"),
    }
    for sample, (filename, raw) in bad_inputs.items():
        out_dir = corrupt_root / sample
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(json.dumps({
            "platform": {"cut_from": 1},
            "meta": {"n_slices": 2},
        }), encoding="utf-8")
        (out_dir / filename).write_bytes(raw)

    old_get_ds = mw.viewer_core._get_ds
    old_viewer_output_root = mw.viewer_core.output_root
    old_cache_dir = mw.viewer_core.CACHE_DIR
    old_payload_cache = mw.viewer_core._CACHE
    mw.viewer_core._get_ds = lambda _dataset, _sample: SimpleNamespace(
        key="corrupt_nifti")
    mw.viewer_core.output_root = lambda _ds: corrupt_root
    mw.viewer_core.CACHE_DIR = TEST_TMP / "corrupt_nifti_cache"
    mw.viewer_core._CACHE = {}
    error_window = NoStartupIOWindow()
    error_window._schedule_prefs_preview = lambda: None
    try:
        handled = []
        for sample in bad_inputs:
            mw.MainWindow._select_sample(
                error_window, "corrupt_nifti", sample, _async=True)
            drained = pump_until(
                app,
                lambda: (not error_window._loading
                         and not error_window._load_workers),
                timeout=5.0,
            )
            handled.append(
                drained and error_window.lbl_sample_sub.text().startswith(
                    "Load failed:"))
        check("empty/corrupt NIfTI load fails cleanly and releases workers",
              all(handled) and not error_window._load_workers
              and error_window._load_worker is None,
              f"handled={handled}, workers={len(error_window._load_workers)}")
    finally:
        error_window.close()
        app.processEvents()
        mw.viewer_core._get_ds = old_get_ds
        mw.viewer_core.output_root = old_viewer_output_root
        mw.viewer_core.CACHE_DIR = old_cache_dir
        mw.viewer_core._CACHE = old_payload_cache

    # keep >= cut: every export-type action refuses before any job or export starts
    keepcut = NoStartupIOWindow()
    keepcut_tmp = Path(tempfile.mkdtemp(prefix="cleanct_keepcut_", dir=TEST_TMP))
    (keepcut_tmp / "report.json").write_text(json.dumps({
        "platform": {"cut_from": 18, "keep_from": 0},
        "meta": {"pixel_spacing_yx_mm": [0.033, 0.033]},
    }), encoding="utf-8")
    try:
        keepcut.payload = {"unprocessed": False}
        keepcut.dataset, keepcut.sample = "synthetic", "slow"
        keepcut.spin_cut.setValue(18)
        keepcut.spin_keep.setValue(20)            # keep >= cut, via the spin
        starts: list[str] = []
        exports: list[str] = []

        class _QuietBox:
            @staticmethod
            def _quiet(*args, **kwargs):
                return None

            warning = critical = information = _quiet

        real_message_box = mw.QMessageBox
        real_export = mw.bundle_export.export_bundle
        keepcut._validated_dest_root = lambda: keepcut_tmp
        _NoSource = type("_NoSource", (), {"source_kind": "dicom", "source_path": None})
        keepcut._resolve_sources = lambda: (_NoSource(), keepcut_tmp, None, keepcut_tmp)
        keepcut._start_job = lambda label, *a, **k: starts.append(label)
        mw.QMessageBox = _QuietBox
        mw.bundle_export.export_bundle = lambda *a, **k: exports.append("export") or {}
        try:
            for action in (keepcut._export_bundle, keepcut._process_and_export,
                           keepcut._apply_and_process):
                try:
                    action()
                except Exception as exc:
                    starts.append(f"raised {type(exc).__name__}: {exc}")
        finally:
            mw.QMessageBox = real_message_box
            mw.bundle_export.export_bundle = real_export
        check("keep>=cut: export, process-and-export and apply start nothing",
              exports == [] and starts == [], f"exports={exports} starts={starts}")
        status = keepcut.lbl_export_status.text()
        check("keep>=cut: the refusal is shown in the export status",
              "Keep line" in status and "Cut line" in status, status)
    finally:
        keepcut.close()
        app.processEvents()

    # closing while a job finishes or fails: no new load, no modal box
    closing = NoStartupIOWindow()
    try:
        closing.dataset, closing.sample = "synthetic", "slow"
        select_calls: list[tuple] = []
        boxes: list[str] = []
        loads: list[tuple] = []
        closing._select_sample = lambda ds, sample, _async=True: select_calls.append((ds, sample))

        class _BoxSpy:
            @staticmethod
            def critical(*args, **kwargs):
                boxes.append(str(args[-1]))

        real_message_box = mw.QMessageBox
        real_build = mw.viewer_core.build_payload
        mw.QMessageBox = _BoxSpy
        mw.viewer_core.build_payload = lambda *a, **k: (loads.append(a), {})[1]
        try:
            closing._closing = True
            closing._job_kind = "process"
            closing._on_job_finished({"report": {}})
            closing._job_kind = "process"
            closing._on_job_error("boom")
            mw.MainWindow._select_sample(closing, "synthetic", "slow")
            check("closing: finished job starts no reload",
                  select_calls == [], str(select_calls))
            check("closing: failed job opens no modal box",
                  boxes == [], str(boxes))
            check("closing: direct select starts no loader",
                  not closing._loading and not closing._load_workers,
                  f"loading={closing._loading} workers={len(closing._load_workers)}")
            pump_until(app, lambda: not closing._load_workers, timeout=5.0)
            select_calls.clear()
            closing._closing = False
            closing._job_kind = "process"
            closing._on_job_finished({"report": {}})
            check("control: the same finish reloads when not closing",
                  select_calls == [("synthetic", "slow")], str(select_calls))
        finally:
            mw.QMessageBox = real_message_box
            mw.viewer_core.build_payload = real_build
    finally:
        closing.close()
        app.processEvents()

    print("RESULT: ALL PASS" if not failures else f"RESULT: {len(failures)} FAIL")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
