"""Round-trip: a DICOM-sourced NIfTI export must open with the voxel axes its
header and affine declare, through both writers that DICOM exports use.

  * streamed writer  - stripped.nii present (the normal path)
  * legacy writer    - no stripped.nii; slices are decoded from the DICOMs

Each voxel stores its own position, v = z*10000 + y*100 + x, on a non-square
24 x 40 series, so any x/y/z swap shows up as a wrong value. The reloaded
file must be (x, y, z) with x fastest on disk, and its affine column norms
must equal the (column, row, slice) spacings.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import nibabel as nib  # noqa: E402
from pydicom import FileDataset, FileMetaDataset  # noqa: E402
from pydicom.uid import (ExplicitVRLittleEndian,  # noqa: E402
                         SecondaryCaptureImageStorage, generate_uid)

from core import bundle_export as be  # noqa: E402

NZ, NY, NX = 30, 24, 40          # source series: 24 rows, 40 columns
KEEP_FROM, N_KEEP = 4, 20        # kept window [4, 24)
ROW_SP, COL_SP = 0.0249, 0.0333  # mm, distinct so axes are distinguishable
SLICE_STEP = 0.5                 # mm

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    suffix = f" [{detail}]" if detail else ""
    print(("PASS " if ok else "FAIL ") + label + suffix)


def write_source_series(source_dir: Path, vol_zyx: np.ndarray) -> list[str]:
    source_dir.mkdir(parents=True)
    study_uid, series_uid = generate_uid(), generate_uid()
    files = []
    for z in range(NZ):
        path = source_dir / f"slice_{z:03d}.dcm"
        file_meta = FileMetaDataset()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=bytes(128))
        ds.SOPClassUID = SecondaryCaptureImageStorage
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.Modality = "CT"
        ds.Rows = NY
        ds.Columns = NX
        ds.PixelSpacing = [ROW_SP, COL_SP]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0, 0, z * SLICE_STEP]
        ds.SliceThickness = SLICE_STEP
        ds.BitsAllocated = 32
        ds.BitsStored = 32
        ds.HighBit = 31
        ds.PixelRepresentation = 1
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.PixelData = vol_zyx[z].astype("<i4").tobytes()
        ds.save_as(path, enforce_file_format=True)
        files.append(str(path))
    return files


def write_export(kind: str, work: Path, kept: list[str]) -> dict:
    dest = work / kind
    dest.mkdir()
    meta = {"platform": {"keep_from": KEEP_FROM},
            "meta": {"pixel_spacing_yx_mm": [ROW_SP, COL_SP]}}
    if kind == "streamed":
        stripped = work / "stripped.nii"
        # stripped.nii is stored in disk order (x, y, z)
        nib.save(nib.Nifti1Image(VOL_ZYX.transpose(2, 1, 0), np.eye(4)), stripped)
    else:
        stripped = work / "no_stripped_nii.nii"   # absent -> legacy DICOM path
    return be._write_kept_nifti(stripped, dest, "SYN", "syn", N_KEEP, kept, meta)


zz, yy, xx = np.meshgrid(np.arange(NZ), np.arange(NY), np.arange(NX), indexing="ij")
VOL_ZYX = (zz * 10000 + yy * 100 + xx).astype(np.float32)   # (z, y, x)
EXPECTED_XYZ = VOL_ZYX[KEEP_FROM:KEEP_FROM + N_KEEP].transpose(2, 1, 0).copy()

work_root = Path(os.environ.get("CLEANCT_TEST_TMP_DIR", tempfile.gettempdir()))
work_root.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix="cleanct_nifti_roundtrip_", dir=work_root))
try:
    sources = write_source_series(work / "source", VOL_ZYX)
    kept = sources[KEEP_FROM:KEEP_FROM + N_KEEP]
    for kind in ("streamed", "legacy"):
        out = write_export(kind, work, kept)
        img = nib.load(out["nii"])
        data = np.asanyarray(img.dataobj)
        check(f"{kind}: reported shape is (x, y, z)",
              list(out["shape"]) == [NX, NY, N_KEEP], f"reported {out['shape']}")
        check(f"{kind}: file shape is (x, y, z)",
              data.shape == EXPECTED_XYZ.shape, f"file {data.shape}")
        if data.shape == EXPECTED_XYZ.shape:
            diff = float(np.abs(data - EXPECTED_XYZ).max())
            check(f"{kind}: every voxel holds its own (z, y, x) position",
                  np.array_equal(data, EXPECTED_XYZ), f"max|diff|={diff:.6g}")
        norms = np.linalg.norm(img.affine[:3, :3], axis=0)
        check(f"{kind}: affine column norms are (col, row, slice) spacing",
              np.allclose(norms, [COL_SP, ROW_SP, SLICE_STEP], atol=1e-6),
              f"norms={np.round(norms, 5).tolist()}")
finally:
    shutil.rmtree(work, ignore_errors=True)

ok = all(results)
print("ALL PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
