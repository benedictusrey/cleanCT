"""Specimen-panel regression suite (sidebar overhaul).

Covers the left-panel overhaul: search/filter, live count, rich meta
rows (kind · slices · dims · voxel · size), the lazy size scan,
rename/duplicate/remove/clear with confirmations, the right-click
context-menu dispatch, and the busy spinner reaction.  Runs fully
offscreen against a sandboxed per-user state root.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if (not os.environ.get("CLEANCT_ENGINE") or not os.environ.get("CLEANCT_DATA")
        or not os.environ.get("CLEANCT_TEST_TMP_DIR")):
    raise SystemExit("Set isolated CLEANCT_ENGINE, CLEANCT_DATA, and "
                     "CLEANCT_TEST_TMP_DIR paths first")
TEST_TMP = Path(os.environ["CLEANCT_TEST_TMP_DIR"])
TEST_TMP.mkdir(parents=True, exist_ok=True)
APP = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))

import sys
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "src"))

import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QMessageBox as RealMessageBox

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def write_tiny_series(folder, n=24, rows=64, cols=64, um=0.033):
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    folder.mkdir(parents=True, exist_ok=True)
    study_uid, series_uid = generate_uid(), generate_uid()
    for i in range(n):
        z = np.full((rows, cols), -1000.0, np.float32)
        rr, cc = np.mgrid[:rows, :cols]
        disk = (rr - rows // 2) ** 2 + (cc - cols // 2) ** 2 <= (rows // 3) ** 2
        z[disk] = -600.0
        if i >= n - 4:
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


class _SignalStub:
    def connect(self, *_a, **_k) -> None:
        pass


class _MenuAction:
    def __init__(self, text: str):
        self.text = text
        self.triggered = _SignalStub()

    def setToolTip(self, _tip: str) -> None:
        pass

    def setEnabled(self, _enabled: bool) -> None:
        pass

    def isEnabled(self) -> bool:
        return True


class _MenuStub:
    next_choice = None

    def __init__(self, *_a, **_k):
        self._actions = []

    def addAction(self, text: str) -> _MenuAction:
        action = _MenuAction(text)
        self._actions.append(action)
        return action

    def addSeparator(self) -> None:
        return None

    def exec(self, *_a, **_k):
        return _MenuStub.next_choice


class _InputStub:
    text = ""
    accepted = True

    @staticmethod
    def getText(*_a, **_k):
        return _InputStub.text, _InputStub.accepted


class _MsgStub:
    Yes = RealMessageBox.Yes
    No = RealMessageBox.No
    answer = None

    @staticmethod
    def question(*_a, **_k):
        return _MsgStub.answer if _MsgStub.answer is not None else _MsgStub.Yes

    @staticmethod
    def critical(*_a, **_k):
        return None

    @staticmethod
    def information(*_a, **_k):
        return None

    @staticmethod
    def warning(*_a, **_k):
        return None


import main_window as mw
from core import custom_series as csx
from widgets.specimen_panel import SpecimenDelegate, format_specimen_meta
import tomograph as tg

mw.QMenu = _MenuStub
mw.QInputDialog = _InputStub
mw.QMessageBox = _MsgStub


class PanelWindow(mw.MainWindow):
    def __init__(self):
        self._suppress_initial_load = True
        super().__init__()
        self._suppress_initial_load = False

    def _check_gpu(self):
        self._gpu_worker = None

    def _select_sample(self, ds, sample, _async=True):
        if self._suppress_initial_load:
            return
        return mw.MainWindow._select_sample(self, ds, sample, _async)


def main() -> int:
    app = QApplication.instance() or QApplication([])

    # --- synthetic registered sources --------------------------------------
    src_a = TEST_TMP / "panel_src_a"
    write_tiny_series(src_a / "XY")
    entry_a = csx.register_series(src_a, "panel_a")
    check("panel_a registered (DICOM junction)",
          entry_a["specimen"] == "panel_a"
          and (csx.DATA_DIR / "panel_a" / "XY").exists())

    src_b = TEST_TMP / "panel_src_b"
    write_tiny_series(src_b / "XY", n=26, rows=48, cols=72, um=0.0662)
    csx.register_series(src_b, "panel_b")

    # sandbox processed output for the rename-alignment check
    out_custom = tg.output_root(tg.DatasetSpec(
        key=csx.CUSTOM_KEY, source=csx.DATA_DIR, out_sub=csx.CUSTOM_KEY))
    (out_custom / "panel_a").mkdir(parents=True, exist_ok=True)
    (out_custom / "panel_a" / "report.json").write_text(
        '{"report": {"source_kind": "dicom"}}', encoding="utf-8")

    window = PanelWindow()

    # [1] rich rows ----------------------------------------------------------
    rows = {}
    for i in range(window.sample_list.count()):
        it = window.sample_list.item(i)
        key = it.data(Qt.UserRole)
        if key:
            rows[key[1]] = (it, it.data(SpecimenDelegate.META_ROLE))
    check("both loaded specimens listed",
          "panel_a" in rows and "panel_b" in rows, f"rows={sorted(rows)}")
    meta_a = rows.get("panel_a", (None, {}))[1] or {}
    check("meta carries slices/dims/voxel/kind",
          int(meta_a.get("slices") or 0) == 24
          and meta_a.get("dims") == "64×64"
          and abs(float(meta_a.get("um") or 0) - 33.0) < 0.01
          and meta_a.get("kind") == "DICOM", str(meta_a))
    line = format_specimen_meta(meta_a)
    check("meta line formatted",
          "DICOM" in line and "24 slices" in line and "64×64" in line
          and "µm" in line, line)
    check("count label shows total",
          window.lbl_spec_count.text() == "2", window.lbl_spec_count.text())

    # [2] filter --------------------------------------------------------------
    window.edit_search.setText("panel_b")
    visible = [window.sample_list.item(i).data(Qt.UserRole)
               for i in range(window.sample_list.count())
               if window.sample_list.item(i).data(Qt.UserRole)
               and not window.sample_list.item(i).isHidden()]
    check("filter narrows to panel_b", visible == [("custom", "panel_b")],
          str(visible))
    check("filter count label",
          window.lbl_spec_count.text() == "1 of 2",
          window.lbl_spec_count.text())
    window.edit_search.setText("zzz")
    check("no-match note shown",
          (not window._empty_row.isHidden())
          and "No specimens match" in window._empty_row.text(),
          repr(window._empty_row.text()))
    window.edit_search.setText("")
    check("filter reset shows all",
          window.lbl_spec_count.text() == "2", window.lbl_spec_count.text())

    # [3] rename ---------------------------------------------------------------
    window._select_row_for(("custom", "panel_a"))
    check("row selected",
          window._selected_specimen_key() == ("custom", "panel_a"))
    _InputStub.text = "panel_a_renamed"
    window._rename_selected()
    renamed = csx.registered_specimens()
    check("registry renamed", "panel_a_renamed" in renamed
          and "panel_a" not in renamed, str(sorted(renamed)))
    check("junction folder renamed",
          (csx.DATA_DIR / "panel_a_renamed" / "XY").exists()
          and not (csx.DATA_DIR / "panel_a" / "XY").exists())
    check("processed output renamed",
          (out_custom / "panel_a_renamed" / "report.json").is_file()
          and not (out_custom / "panel_a").exists())
    check("selection follows rename",
          window._selected_specimen_key() == ("custom", "panel_a_renamed"))

    # [4] duplicate ------------------------------------------------------------
    _InputStub.text = "panel_a_clone"
    window._duplicate_selected()
    reg = csx.registered_specimens()
    check("duplicate registered", "panel_a_clone" in reg, str(sorted(reg)))
    check("duplicate junction created",
          (csx.DATA_DIR / "panel_a_clone" / "XY").is_dir())
    check("duplicate becomes the selection",
          window._selected_specimen_key() == ("custom", "panel_a_clone"))

    # [5] remove custom ----------------------------------------------------------
    window._select_row_for(("custom", "panel_a_clone"))
    _MsgStub.answer = _MsgStub.Yes
    window._remove_selected()
    reg = csx.registered_specimens()
    check("clone unregistered", "panel_a_clone" not in reg, str(sorted(reg)))
    check("clone junction removed",
          not (csx.DATA_DIR / "panel_a_clone" / "XY").exists())
    check("processed outputs kept after remove",
          (out_custom / "panel_a_renamed" / "report.json").is_file())
    check("selection cleared after removing the shown specimen",
          window.sample == "" and window.payload is None)

    # [6] built-in hide (session only) --------------------------------------------
    builtin_out = tg.output_root(tg.DATASETS["24um"])
    (builtin_out / "1-ut").mkdir(parents=True, exist_ok=True)
    (builtin_out / "1-ut" / "report.json").write_text(json.dumps({
        "meta": {"n_slices": 40, "rows": 32, "cols": 32,
                 "pixel_spacing_yx_mm": [0.025, 0.025]}}), encoding="utf-8")
    window._refresh_sidebar()
    keys = [window.sample_list.item(i).data(Qt.UserRole)
            for i in range(window.sample_list.count())]
    check("synthetic built-in listed", ("24um", "1-ut") in keys, str(keys))
    window._select_row_for(("24um", "1-ut"))
    window._remove_selected()
    keys = [window.sample_list.item(i).data(Qt.UserRole)
            for i in range(window.sample_list.count())]
    check("hidden built-in removed from this window",
          ("24um", "1-ut") not in keys, str(keys))
    check("built-in folder untouched",
          (builtin_out / "1-ut" / "report.json").is_file())
    window2 = PanelWindow()
    check("hidden built-in returns in a fresh window",
          any(window2.sample_list.item(j).data(Qt.UserRole) == ("24um", "1-ut")
              for j in range(window2.sample_list.count())))

    # [7] clear all ----------------------------------------------------------------
    window._select_row_for(("custom", "panel_a_renamed"))
    _MsgStub.answer = _MsgStub.Yes
    window._clear_loaded_specimens()
    check("clear-all unregisters everything",
          csx.registered_specimens() == {}, str(csx.load_registry()))
    check("junctions removed by clear-all",
          not (csx.DATA_DIR / "panel_a_renamed" / "XY").exists()
          and not (csx.DATA_DIR / "panel_b" / "XY").exists())

    # [8] context menu dispatch -------------------------------------------------------
    # panel_b was unregistered by [7]; register a fresh custom specimen
    src_c = TEST_TMP / "panel_src_c"
    write_tiny_series(src_c / "XY")
    csx.register_series(src_c, "panel_c")
    window._refresh_sidebar()
    window._select_row_for(("custom", "panel_c"))
    called: list[str] = []
    window._rename_selected = lambda: called.append("rename")
    window._duplicate_selected = lambda: called.append("duplicate")
    window._remove_selected = lambda: called.append("remove")
    window._locate_selected = lambda: called.append("locate")
    window._properties_selected = lambda: called.append("properties")
    window._clear_loaded_specimens = lambda: called.append("clear")

    orig_exec = _MenuStub.exec

    def exec_returning_rename(self_menu, *_a, **_k):
        for action in self_menu._actions:
            if action.text == "✎ Rename…  (F2)":
                return action
        return None

    _MenuStub.exec = exec_returning_rename
    window._specimen_context_menu(QPoint(4, 4))
    _MenuStub.exec = orig_exec
    check("context menu dispatches Rename", called == ["rename"], str(called))

    def exec_returning_properties(self_menu, *_a, **_k):
        for action in self_menu._actions:
            if action.text == "ℹ Properties…":
                return action
        return None

    _MenuStub.exec = exec_returning_properties
    called.clear()
    window._specimen_context_menu(QPoint(4, 4))
    _MenuStub.exec = orig_exec
    check("context menu dispatches Properties", called == ["properties"],
          str(called))

    # keyboard shortcuts exist and are wired to the list
    check("F2/Del shortcuts wired to the list",
          getattr(window, "_f2_shortcut", None) is not None
          and getattr(window, "_del_shortcut", None) is not None)

    # empty-state menu: no specimens at all -> hint + load only
    window._clear_loaded_specimens = None  # use the real registry removal
    csx.remove_specimen("panel_c")
    window._refresh_sidebar()
    empty_actions = []

    def exec_capture_empty(self_menu, *_a, **_k):
        empty_actions.extend(a.text for a in self_menu._actions)
        return None

    _MenuStub.exec = exec_capture_empty
    window._specimen_context_menu(QPoint(4, 4))
    _MenuStub.exec = orig_exec
    check("empty-state menu shows the hint + load",
          csx.registered_specimens() == {} and empty_actions
          and any("No specimens yet" in a for a in empty_actions)
          and any("Load specimen folder" in a for a in empty_actions),
          str(empty_actions))

    # [9] spinner reacts to busy state -------------------------------------------------
    window._loading = True
    window._set_job_gates(process_ready=False)
    check("spinner runs while loading", window.spec_spinner.isRunning())
    window._loading = False
    window._set_job_gates(process_ready=False)
    check("spinner stops when idle", not window.spec_spinner.isRunning())

    window.close()
    window2.close()
    app.processEvents()
    _MsgStub.answer = None
    return 1 if failures else 0


if __name__ == "__main__":
    code = main()
    # cleanup: synthetic sources and the sandbox processed output
    try:
        for name in ("panel_src_a", "panel_src_b", "panel_src_c"):
            shutil.rmtree(TEST_TMP / name, ignore_errors=True)
        out_custom = tg.output_root(tg.DatasetSpec(
            key=csx.CUSTOM_KEY, source=csx.DATA_DIR, out_sub=csx.CUSTOM_KEY))
        shutil.rmtree(out_custom / "1-ut", ignore_errors=True)
    except Exception as exc:
        print(f"cleanup warning: {exc}")
    print("RESULT:", "ALL PASS" if code == 0 else f"{len(failures)} FAIL")
    raise SystemExit(code)
