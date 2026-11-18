"""Dialog to load and register a DICOM, TIFF, or NIfTI volume."""
from __future__ import annotations

from pathlib import Path
import theme
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QMessageBox, QComboBox
)

from core import custom_series as csx


class LoadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load Custom Volume")
        self.setFixedSize(610, 360)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.folder_path: str = ""
        self.specimen_id: str = ""
        self.intensity_mode: str = "auto"
        self.source_info: dict = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header
        hdr = QLabel("Load XCT Volume")
        theme.set_role(hdr, "title")
        layout.addWidget(hdr)

        sub = QLabel("Choose a DICOM series folder, TIFF stack, or 3-D NIfTI file.")
        theme.set_role(sub, "secondary")
        layout.addWidget(sub)

        # Folder Input row
        fld_box = QVBoxLayout()
        fld_box.setSpacing(4)
        lbl_fld = QLabel("Source file or series folder:")
        theme.set_role(lbl_fld, "secondary")
        fld_box.addWidget(lbl_fld)

        row_fld = QHBoxLayout()
        self.edit_folder = QLineEdit()
        self.edit_folder.setObjectName("edit_load_folder")
        self.edit_folder.setPlaceholderText(r"e.g. H:\scans\specimen_01\XY")
        self.edit_folder.setToolTip(
            "A DICOM series folder (or one .dcm file inside it), a\n"
            "multipage TIFF stack (.tif/.tiff), a folder of matching\n"
            "TIFF slices, or one 3-D NIfTI volume (.nii / .nii.gz).")
        self.edit_folder.textChanged.connect(self._on_folder_changed)
        row_fld.addWidget(self.edit_folder)

        btn_browse_file = QPushButton("File…")
        btn_browse_file.setObjectName("btn_load_browse_file")
        btn_browse_file.setToolTip("Pick a single volume file (.dcm/.tif/.nii…).")
        btn_browse_file.clicked.connect(self._browse_file)
        row_fld.addWidget(btn_browse_file)
        btn_browse_folder = QPushButton("Folder…")
        btn_browse_folder.setObjectName("btn_load_browse")
        btn_browse_folder.setToolTip("Pick a folder that contains the series.")
        btn_browse_folder.clicked.connect(self._browse_folder)
        row_fld.addWidget(btn_browse_folder)
        fld_box.addLayout(row_fld)
        layout.addLayout(fld_box)

        # Specimen ID row
        id_box = QVBoxLayout()
        id_box.setSpacing(4)
        lbl_id = QLabel("Specimen ID (alias):")
        theme.set_role(lbl_id, "secondary")
        id_box.addWidget(lbl_id)

        self.edit_specimen = QLineEdit()
        self.edit_specimen.setObjectName("edit_load_specimen")
        self.edit_specimen.setPlaceholderText("e.g. 3-4")
        self.edit_specimen.setToolTip(
            "How this scan appears in the specimen list.\n"
            "Letters, digits, underscores and dashes are kept.")
        id_box.addWidget(self.edit_specimen)
        layout.addLayout(id_box)

        mode_box = QVBoxLayout()
        mode_box.setSpacing(4)
        lbl_mode = QLabel("Intensity interpretation:")
        theme.set_role(lbl_mode, "secondary")
        mode_box.addWidget(lbl_mode)
        self.combo_intensity = QComboBox()
        self.combo_intensity.setObjectName("combo_intensity_mode")
        self.combo_intensity.addItem("Auto-detect (recommended)", "auto")
        self.combo_intensity.addItem("Stored values are already HU", "hu")
        self.combo_intensity.setToolTip(
            "Positive-only grayscale data gets robust percentile-based thresholds. "
            "Choose HU only when the source values are calibrated Hounsfield units.")
        mode_box.addWidget(self.combo_intensity)
        layout.addLayout(mode_box)

        # Validation status note
        self.lbl_status = QLabel("")
        theme.set_role(self.lbl_status, "status-ok")
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self.btn_confirm = QPushButton("Load && Register")
        self.btn_confirm.setObjectName("btn_load_confirm")
        self.btn_confirm.setProperty("class", "btn-primary")
        self.btn_confirm.clicked.connect(self._validate_and_accept)
        btn_row.addWidget(self.btn_confirm)
        layout.addLayout(btn_row)

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select XCT Volume", "",
            "XCT volumes (*.dcm *.tif *.tiff *.nii *.nii.gz);;All files (*)")
        if path:
            self.edit_folder.setText(path)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select DICOM/TIFF Series Folder")
        if folder:
            self.edit_folder.setText(folder)

    def _on_folder_changed(self, text: str):
        p = Path(text.strip())
        if p.name and not self.edit_specimen.text():
            if p.is_file():
                name = p.name[:-7] if p.name.lower().endswith(".nii.gz") else p.stem
            else:
                name = p.name if p.name.lower() != "xy" else p.parent.name
            self.edit_specimen.setText(name)

    def _validate_and_accept(self):
        folder = self.edit_folder.text().strip()
        specimen = self.edit_specimen.text().strip()
        if not folder:
            QMessageBox.warning(self, "Missing Source", "Choose a DICOM series folder or a TIFF/NIfTI file.")
            return
        if not specimen:
            QMessageBox.warning(self, "Missing ID", "Please specify a specimen ID.")
            return

        p = Path(folder)
        if not p.exists():
            QMessageBox.critical(self, "Invalid Path", f"The selected file or folder does not exist:\n{folder}")
            return

        # Validation can decode a sample plane or spot-read DICOM headers —
        # guard it with a busy cursor and keep the button single-shot.
        from PySide6.QtWidgets import QApplication
        self.btn_confirm.setEnabled(False)
        theme.set_role(self.lbl_status, "secondary")
        self.lbl_status.setText("Validating the source (reading headers)…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            mode = str(self.combo_intensity.currentData() or "auto")
            info = csx.validate_input(p, intensity=mode)
        except csx.LoadError as err:
            QApplication.restoreOverrideCursor()
            self.btn_confirm.setEnabled(True)
            theme.set_role(self.lbl_status, "status-error")
            self.lbl_status.setText("Validation failed. See the message.")
            QMessageBox.critical(
                self, "Validation Failed",
                f"Could not validate the selected volume:\n{err}")
            return
        except Exception as err:
            QApplication.restoreOverrideCursor()
            self.btn_confirm.setEnabled(True)
            theme.set_role(self.lbl_status, "status-error")
            self.lbl_status.setText("Unexpected validation error.")
            QMessageBox.critical(self, "Validation Failed", str(err))
            return
        QApplication.restoreOverrideCursor()
        self.btn_confirm.setEnabled(True)
        kind = str(info.get("source_kind", "dicom")).upper()
        n = int(info.get("n_slices", 0))
        voxel = float(info.get("pixel_um", 0) or 0)
        spacing = f", {voxel:.3f} µm pixels" if voxel else ", physical scale missing"
        note = " Check the physical scale." if info.get("geometry_assumed") else ""
        if info.get("intensity_mode") == "raw":
            note += " Intensity thresholds will be estimated."
        theme.set_role(self.lbl_status, "status-ok")
        self.lbl_status.setText(
            f"Valid {kind} volume: {n} slices, {info.get('rows')} × {info.get('cols')}{spacing}.{note}")
        self.lbl_status.setWordWrap(True)
        self.folder_path = str(p)
        self.specimen_id = specimen
        self.intensity_mode = mode
        self.source_info = info
        self.accept()
