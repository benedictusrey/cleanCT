"""The DICOM export keeps only the wood between the Wood top, Metal top and the L/R lines.

Z is clipped by the Keep and Cut lines (the export takes the kept slices only).
The two lateral pairs clip each kept slice: X (columns) by the vertical L/R lines
of the axial and coronal views, and Y (rows) by the L/R lines of the sagittal
view.  The origin moves to the first kept row and column, and the bundle's own
pixel check expects the cropped pixels.

1. ``core.lateral.lateral_range``: fractions -> pixels, or None for the whole axis.
2. ``bundle_export._crop_slice``: pixels, size and origin of a cropped slice.
3. ``bundle_export.export_bundle`` with a box: verifies and writes the box only.
"""
from __future__ import annotations

import os
import sys
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

import numpy as np  # noqa: E402
from pydicom.dataset import FileDataset, FileMetaDataset  # noqa: E402
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid  # noqa: E402

from core import bundle_export as be  # noqa: E402


failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# 1. fractions -> pixels
check("the whole axis is no crop", be.lateral_range(None, 449) is None
      and be.lateral_range((0.0, 1.0), 449) is None)
check("L 14% and R 80% map to pixels 63..358",
      be.lateral_range((0.14, 0.80), 449) == (63, 359),
      str(be.lateral_range((0.14, 0.80), 449)))
check("a degenerate pair keeps one pixel",
      be.lateral_range((0.5, 0.5), 449) == (224, 225),
      str(be.lateral_range((0.5, 0.5), 449)))


# 2. the crop itself
def slice_ds(rows: int = 12, cols: int = 20):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    ds = FileDataset("slice.dcm", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.Rows, ds.Columns = rows, cols
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
    ds.PixelRepresentation, ds.SamplesPerPixel = 1, 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelSpacing = [0.5, 0.25]          # [rows, columns] spacing in mm
    ds.ImagePositionPatient = [10.0, 20.0, 5.0]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    arr = (np.arange(rows * cols).reshape(rows, cols) - 100).astype(np.int16)
    ds.PixelData = arr.tobytes()
    return ds, arr


ds, arr = slice_ds()
be._crop_slice(ds, (2, 9, 5, 15))
check("the cropped slice keeps rows 2..8 and columns 5..14",
      ds.Rows == 7 and ds.Columns == 10, f"rows={ds.Rows} cols={ds.Columns}")
check("the cropped pixels are the source box", np.array_equal(ds.pixel_array, arr[2:9, 5:15]))
origin = [float(v) for v in ds.ImagePositionPatient]
# column 5 is 5 * 0.25 mm along +x; row 2 is 2 * 0.5 mm along +y (the column direction)
check("the origin moves to the first kept row and column",
      np.allclose(origin, [10.0 + 5 * 0.25, 20.0 + 2 * 0.5, 5.0]), str(origin))

# 3. a full export with a lateral box: the bundle verifies and every slice is the box
import json  # noqa: E402

import capture_screens as cs  # noqa: E402
import pydicom  # noqa: E402

exp_src = TEST_TMP / "clip_export_src"
cs.write_wood_metal_series(exp_src / "XY", n=14, rows=32, cols=40, um=66.0)
report = {"platform": {"cut_from": 12, "keep_from": 3}, "config": {}, "wood_roi": {},
          "metrics": {"removed_fraction": 0.1},
          "meta": {"n_slices": 14, "pixel_spacing_yx_mm": [0.066, 0.066],
                   "slice_thickness_mm": 0.066, "source_kind": "dicom"}}
out_root = TEST_TMP / "clip_export_out"
try:
    res = be.export_bundle("custom", "clip_export", exp_src, json.loads(json.dumps(report)),
                           exp_src / "missing_stripped.nii", out_root,
                           export_format=be.FORMAT_DICOM, source_kind="dicom",
                           lateral={"x": (0.25, 0.75), "y": (0.125, 0.875)})
    series = Path(res["bundle_dir"]) / be.series_dir_name("clip_export")
    exported = sorted(series.glob("*.dcm"))
    sizes = {(d.Rows, d.Columns) for d in (pydicom.dcmread(p, stop_before_pixels=True) for p in exported)}
    # Y 0.125..0.875 of 32 rows = rows 4..27 (24 rows); X 0.25..0.75 of 40 columns = 10..29 (20 columns)
    check("the export with a lateral box verifies and writes the box",
          len(exported) == 9 and sizes == {(24, 20)}, f"files={len(exported)} sizes={sizes}")
except be.BundleError as exc:
    check("the export with a lateral box verifies and writes the box", False, str(exc))

# 4. the NIfTI volume clips X and Y to the same box as the DICOM series
import nibabel as nib  # noqa: E402

from core.auto_snap import delivered_cut  # noqa: E402

vol = np.arange(40 * 32 * 14, dtype=np.float32).reshape(40, 32, 14)   # disk order (x, y, z)
vol_path = TEST_TMP / "clip_nifti_stripped.nii"
nib.save(nib.Nifti1Image(vol, np.eye(4)), vol_path)
box = {"x": (0.25, 0.75), "y": (0.125, 0.875)}   # X 10..29, Y 4..27; Z keeps 3..11
full_out, box_out = TEST_TMP / "clip_nifti_full", TEST_TMP / "clip_nifti_box"
try:
    full = be.export_bundle("custom", "clip_nifti", exp_src, json.loads(json.dumps(report)),
                            vol_path, full_out, export_format=be.FORMAT_NIFTI, source_kind="dicom")
    boxed = be.export_bundle("custom", "clip_nifti", exp_src, json.loads(json.dumps(report)),
                             vol_path, box_out, export_format=be.FORMAT_NIFTI,
                             source_kind="dicom", lateral=box)
    img_b = nib.load(boxed["nifti"])
    img_f = nib.load(full["nifti"])
    data_ok = np.array_equal(np.asarray(img_b.dataobj, np.float32), vol[10:30, 4:28, 3:12])
    check("the NIfTI keeps the box: shape 20 x 24 x 9 and the same voxels",
          img_b.shape == (20, 24, 9) and data_ok, f"shape={img_b.shape}")
    shift = np.asarray(img_f.affine)[:3, 0] * 10 + np.asarray(img_f.affine)[:3, 1] * 4
    check("the NIfTI origin moves to the box corner",
          np.allclose(np.asarray(img_b.affine)[:3, 3], np.asarray(img_f.affine)[:3, 3] + shift, atol=1e-4))
    sidecar = json.loads(Path(boxed["json"]).read_text(encoding="utf-8"))
    check("the sidecar records the L/R box", sidecar.get("lateral_box") is not None
          and sidecar["lateral_box"]["x"] == [0.25, 0.75])
except be.BundleError as exc:
    check("the NIfTI keeps the box: shape 20 x 24 x 9 and the same voxels", False, str(exc))

# 5. a blank plane inside Keep..Cut is refused, never written
blank = vol.copy()
blank[:, :, 5] = np.nan                     # the processed run has no data at slice 5
blank_path = TEST_TMP / "clip_nifti_blank.nii"
nib.save(nib.Nifti1Image(blank, np.eye(4)), blank_path)
try:
    be.export_bundle("custom", "clip_blank", exp_src, json.loads(json.dumps(report)),
                     blank_path, TEST_TMP / "clip_blank_out", export_format=be.FORMAT_NIFTI,
                     source_kind="dicom")
    check("a blank plane inside Keep..Cut is refused", False, "export was written")
except be.BundleError:
    check("a blank plane inside Keep..Cut is refused", True)

# 6. a TIFF/NIfTI source: the volume export clips the same box
src_nii = TEST_TMP / "clip_source.nii"
nib.save(nib.Nifti1Image(vol, np.eye(4)), src_nii)
try:
    vb = be.export_bundle("custom", "clip_vol", src_nii, json.loads(json.dumps(report)),
                          vol_path, TEST_TMP / "clip_vol_out", export_format=be.FORMAT_NIFTI,
                          source_kind="nifti", source_path=src_nii, source_metadata={},
                          lateral=box)
    check("the volume export keeps the box: shape 20 x 24 x 9",
          nib.load(vb["nifti"]).shape == (20, 24, 9), str(nib.load(vb["nifti"]).shape))
except be.BundleError as exc:
    check("the volume export keeps the box: shape 20 x 24 x 9", False, str(exc))

# 7. the delivered cut is the Cut line pulled back by the margin, never below 0
check("the delivered cut is the Cut minus the margin",
      delivered_cut(20, 5) == 15 and delivered_cut(12, 0) == 12 and delivered_cut(3, 9) == 0)

if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
