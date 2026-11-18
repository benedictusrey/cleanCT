"""Proof: streamed NIfTI export == in-RAM NIfTI export (byte identical).

Builds a small synthetic stripped.nii, runs _write_kept_nifti through the
normal RAM path and through the streamed path (threshold forced tiny),
then byte-compares the two outputs.
"""
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import nibabel as nib
from pydicom import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from core import bundle_export as be

work_root = Path(os.environ.get("CLEANCT_TEST_TMP_DIR", tempfile.gettempdir()))
work_root.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix="cleanct_export_stream_", dir=work_root))

NZ, NY, NX, N_KEEP = 24, 40, 40, 18
rng = np.random.default_rng(7)
vol = (rng.random((NZ, NY, NX)) * 1200 - 1000).astype(np.float32)
stripped = work / "stripped.nii"
nib.save(nib.Nifti1Image(vol.transpose(2, 1, 0), np.eye(4)), stripped)

# Small synthetic source DICOMs are used for geometry validation. The affine
# is patched because this test compares streaming against RAM serialization,
# not DICOM orientation conversion.
import core.bundle_export as bex


def fake_affine(files, rng_arg):
    return np.diag([0.5, 0.5, 0.5, 1.0]).astype(np.float64)


bex.nifti_affine = fake_affine

meta = {"platform": {"keep_from": 6},
        "meta": {"pixel_spacing_yx_mm": [0.0249, 0.0249]}}

source_dir = work / "source"
source_dir.mkdir()
study_uid = generate_uid()
series_uid = generate_uid()
files = []
for i in range(N_KEEP):
    path = source_dir / f"slice_{i:03d}.dcm"
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
    ds.PixelSpacing = [0.0249, 0.0249]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0, 0, i * 0.5]
    ds.SliceThickness = 0.5
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.save_as(path, enforce_file_format=True)
    files.append(str(path))

(work / "stream").mkdir(exist_ok=True)
out_ram = bex._write_kept_nifti(stripped, work, "SYN", "syn", N_KEEP, files, meta)

old_thr = be.STREAM_VOL_MAX_BYTES
be.STREAM_VOL_MAX_BYTES = 1          # force the streamed path
out_stream = bex._write_kept_nifti(stripped, work / "stream", "SYN", "syn",
                                  N_KEEP, files, meta)
be.STREAM_VOL_MAX_BYTES = old_thr


class BrokenProxy:
    shape = (NX, NY, NZ)

    def __init__(self, xyz):
        self.xyz = xyz
        self.reads = 0

    def __getitem__(self, key):
        self.reads += 1
        if self.reads == 2:
            raise OSError("synthetic interrupted volume read")
        return self.xyz[key]


failure_dir = work / "failure"
failure_dir.mkdir()
protected = failure_dir / "FAIL.nii"
protected.write_bytes(b"previous complete export")
try:
    bex._write_kept_nifti_streamed(
        BrokenProxy(vol.transpose(2, 1, 0)), 0, N_KEEP, failure_dir,
        "FAIL", "syn", files, {"meta": meta["meta"]})
    interrupted = False
except OSError as exc:
    interrupted = "synthetic interrupted" in str(exc)
tmp_clean = not (failure_dir / "FAIL.nii.tmp").exists()
previous_kept = protected.read_bytes() == b"previous complete export"
print(f"failed stream handled={interrupted}, temp cleaned={tmp_clean}, "
      f"previous output preserved={previous_kept}")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


h1, h2 = sha(out_ram["nii"]), sha(out_stream["nii"])
print(f"RAM     {out_ram['nii']}  {h1[:16]}  shape={out_ram['shape']}")
print(f"STREAM  {out_stream['nii']}  {h2[:16]}  shape={out_stream['shape']}")

# numeric equivalence too (headers may embed nothing differing)
v1 = np.asanyarray(nib.load(out_ram["nii"]).dataobj)
v2 = np.asanyarray(nib.load(out_stream["nii"]).dataobj)
same = np.array_equal(v1, v2)
print(f"numeric identical: {same}   max|diff|={float(np.abs(v1 - v2).max()):.6g}")
print("BYTE IDENTICAL" if h1 == h2 else "BYTE DIFFER (see above)")

ok = (same and h1 == h2 and out_ram["shape"] == out_stream["shape"]
      and interrupted and tmp_clean and previous_kept)
print("ALL PASS" if ok else "FAIL")
shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
