"""Capture the four audited UI states of cleanCT as PNG evidence.

Runs the real MainWindow fully offscreen against a sandboxed per-user
state root, registers a synthetic wood-on-metal DICOM series, and grabs:

  1. landing.png   — first-run empty state (fresh install look)
  2. loaded.png    — specimen loaded, Auto tab merged views + 3D cloud
  3. cutting.png   — Preferences tab with keep/cut guide lines
  4. history.png   — session history populated in the sidebar

Outputs go to tests/screenshots/.  No scan data is modified anywhere.
"""
from __future__ import annotations

import os
import shutil
import sys
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
sys.path.insert(0, str(APP / "src"))

import numpy as np
from PySide6.QtWidgets import QApplication

import main_window as mw
import theme
from core import custom_series as csx

# The offscreen platform plugin has no system font database — point it at
# the Windows font directory so screenshots carry real text.
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

OUT_DIR = APP / "tests" / "screenshots"
SHOTS = ("landing.png", "loaded.png", "cutting.png", "history.png")
SHOT_W, SHOT_H = 1540, 960


def write_wood_metal_series(folder: Path, n=36, rows=96, cols=96, um=0.033):
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    folder.mkdir(parents=True, exist_ok=True)
    study_uid, series_uid = generate_uid(), generate_uid()
    rng = np.random.default_rng(11)
    rr, cc = np.mgrid[:rows, :cols]
    radii = np.sqrt((rr - rows // 2) ** 2 + (cc - cols // 2) ** 2)
    disk = radii <= rows // 3
    for i in range(n):
        z = np.full((rows, cols), -1000.0, np.float32)
        # organic wood cylinder with ring texture
        z[disk] = (-600.0 + 60.0 * np.sin(radii[disk] * 0.9)).astype(np.float32)
        z += rng.normal(0.0, 6.0, z.shape).astype(np.float32)
        if i >= n - 5:                        # metal platform slab
            z[disk] = 3000.0
        d = Dataset()
        d.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        d.SOPInstanceUID = generate_uid()
        d.StudyInstanceUID = study_uid
        d.SeriesInstanceUID = series_uid
        d.Modality = "CT"
        d.Rows, d.Columns = rows, cols
        d.SamplesPerPixel = 1
        d.BitsAllocated = 16
        d.BitsStored = 16
        d.HighBit = 15
        d.PixelRepresentation = 1
        d.PhotometricInterpretation = "MONOCHROME2"
        d.PixelSpacing = [um, um]
        d.SliceThickness = 0.5
        d.ImagePositionPatient = [0, 0, float(i)]
        d.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        d.RescaleSlope, d.RescaleIntercept = 1.0, -1024.0
        d.file_meta = FileMetaDataset()
        d.file_meta.MediaStorageSOPClassUID = d.SOPClassUID
        d.file_meta.MediaStorageSOPInstanceUID = d.SOPInstanceUID
        d.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        d.PixelData = (z.astype(np.int16) - (-1024)).tobytes()
        pydicom.dcmwrite(folder / f"s{i:04d}.dcm", d, enforce_file_format=True)


def pump(app, predicate, timeout=25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def grab(app, window, path: Path) -> None:
    window.resize(SHOT_W, SHOT_H)
    window.center_on_screen()
    window.resize(SHOT_W, SHOT_H)
    app.processEvents()
    pm = window.grab()
    pm.save(str(path), "PNG")
    print(f"  saved {path.name} ({pm.width()}x{pm.height()})")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.QSS)
    app.setApplicationName("cleanCT")
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1) landing: fresh install, empty list ---------------------------
    landing = mw.MainWindow()
    landing.center_on_screen()
    landing.show()
    app.processEvents()
    grab(app, landing, out_dir / "landing.png")
    landing.close()
    app.processEvents()

    # ---- register + load a synthetic specimen ----------------------------
    src = TEST_TMP / "shots_src"
    write_wood_metal_series(src / "XY")
    csx.register_series(src, "shot_specimen")

    window = mw.MainWindow()
    window.center_on_screen()
    window.resize(SHOT_W, SHOT_H)
    window.show()
    app.processEvents()

    window._select_sample("custom", "shot_specimen")
    loaded = pump(app, lambda: (not window._loading)
                  and window.payload is not None, timeout=180.0)
    if not loaded:
        print("FAIL specimen payload never arrived")
        return 1
    print("  payload ready "
          f"(slices={int((window.payload.get('report') or {}).get('n_slices') or 0)})")

    # drain the async prefs preview so the history entry appears
    preview_ready = pump(app, lambda: window._last_pref_preview is not None
                         and window._preview_worker is None, timeout=180.0)
    if not preview_ready:
        print("FAIL prefs preview never completed")
        return 1
    # let the GPU chip settle (the CuPy probe takes a few seconds)
    pump(app, lambda: window.lbl_gpu.text() != "⚡ Checking GPU…", timeout=90.0)

    # ---- 3) cutting (Preferences with guide lines) -----------------------
    window._switch_tab("prefs", schedule=False)
    app.processEvents()
    time.sleep(0.25)
    app.processEvents()
    grab(app, window, out_dir / "cutting.png")

    # ---- 2) loaded (Auto workspace) ---------------------------------------
    window._switch_tab("auto", schedule=False)
    app.processEvents()
    time.sleep(0.25)
    app.processEntries = app.processEvents
    app.processEvents()
    grab(app, window, out_dir / "loaded.png")

    # ---- 4) history populated ----------------------------------------------
    entries = window._session_preview_history
    if not entries:
        print("FAIL history empty after applied preview")
        return 1
    window.axial_slider.blockSignals(True)
    window.axial_slider.setValue(2)
    window.axial_slider.blockSignals(False)
    window._record_session_preview()
    window._switch_tab("prefs", schedule=False)
    app.processEvents()
    grab(app, window, out_dir / "history.png")
    print(f"  history entries={len(window._session_preview_history)}")

    window.close()
    app.processEvents()

    # ---- cleanup: unregister + remove synthetic artifacts -------------------
    try:
        csx.remove_specimen("shot_specimen")
        shutil.rmtree(src, ignore_errors=True)
        from core import viewer_core as vc
        out_dir_processed = vc.output_root(vc._get_ds("custom", "shot_specimen"))
        shutil.rmtree(out_dir_processed / "shot_specimen", ignore_errors=True)
        for k in [k for k in list(vc._PREV) if "shot_specimen" in k]:
            vc._PREV.pop(k, None)
    except Exception as exc:
        print(f"  cleanup warning: {exc}")

    ok = all((out_dir / name).is_file()
             and (out_dir / name).stat().st_size > 10_000
             for name in SHOTS)
    print("RESULT:", "ALL SHOTS SAVED" if ok else "MISSING SHOTS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
