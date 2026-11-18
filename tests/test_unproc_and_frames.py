"""Unit harness for the 0I fixes (run from the repo root).

1) _frame_img: the >2x downscale path must survive Pillow 12 (Image.REDUCE
   was removed in Pillow 10 and crashed every custom-specimen frame build
   whose slices exceeded twice the frame width).
2) _prev_source on a NOT-processed custom series must return a scan-native
   preview source (no report.json) with live sagittal/coronal/axial
   previews and the pre-process detection bounds.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from PIL import Image

fail = 0


def check(name, cond, extra=""):
    global fail
    if cond:
        print(f"  PASS  {name} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


# ---------------------------------------------------------------- 1: frames
print("[1] _frame_img downscale paths (Pillow 12)")
from core.viewer_core import _frame_img

for w, width, tag in [(4000, 560, "ratio>2 (BOX path)"),
                      (900, 560, "ratio<2 (LANCZOS only)"),
                      (1120, 560, "ratio==2 edge")]:
    rgb = np.random.default_rng(0).random((300, w, 3)).astype(np.float32)
    try:
        img = _frame_img(rgb, width)
        check(f"frame {tag}", img.size[0] == width, f"-> {img.size}")
    except Exception as e:
        check(f"frame {tag}", False, f"raised {type(e).__name__}: {e}")

check("Image.REDUCE really absent (precondition)",
      not hasattr(Image, "REDUCE") and hasattr(Image, "Resampling"))

# ------------------------------------------------- 2: unprocessed preview
print("[2] unprocessed custom series: previews + detection")
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from core import custom_series as csx
from core import viewer_core as vc

test_tmp_raw = os.environ.get("CLEANCT_TEST_TMP_DIR")
test_tmp = Path(test_tmp_raw) if test_tmp_raw else Path(tempfile.gettempdir())
test_tmp.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="cleanct_unproc_", dir=test_tmp))
ser = tmp / "XY"
ser.mkdir(parents=True)
rng = np.random.default_rng(42)
N = 24
study_uid, series_uid = generate_uid(), generate_uid()
# phantom: air around a wood cylinder (HU ~ -600) sitting on a metal base
for i in range(N):
    z = np.full((64, 64), -1000.0, np.float32)
    rr, cc = np.mgrid[:64, :64]
    disk = (rr - 32) ** 2 + (cc - 32) ** 2 <= 18 ** 2
    z[disk] = -600.0
    if i >= 20:                       # metal slab at the bottom
        z[disk] = 3000.0
    d = Dataset()
    d.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    d.SOPInstanceUID = generate_uid()
    d.StudyInstanceUID = study_uid
    d.SeriesInstanceUID = series_uid
    d.Modality = "CT"
    d.Rows, d.Columns = 64, 64
    d.SamplesPerPixel = 1
    d.BitsAllocated = 16
    d.BitsStored = 16
    d.HighBit = 15
    d.PixelRepresentation = 1
    d.PhotometricInterpretation = "MONOCHROME2"
    d.PixelSpacing = [0.033, 0.033]
    d.SliceThickness = 0.5
    d.ImagePositionPatient = [0, 0, float(i)]
    d.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    d.RescaleSlope, d.RescaleIntercept = 1.0, -1024.0
    d.file_meta = FileMetaDataset()
    d.file_meta.MediaStorageSOPClassUID = d.SOPClassUID
    d.file_meta.MediaStorageSOPInstanceUID = d.SOPInstanceUID
    d.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    d.PixelData = (z.astype(np.int16) - (-1024)).tobytes()
    pydicom.dcmwrite(ser / f"s{i:04d}.dcm", d, enforce_file_format=True)

# sanity: the tiny series reads back
ds0 = pydicom.dcmread(ser / "s0000.dcm")
check("tiny DICOM series written + readable",
      ds0.pixel_array.shape == (64, 64), f"px={ds0.pixel_array.shape}")

# register it as a custom specimen (no processing afterwards!)
name = "unproc_ut"
csx.register_series(ser, name)

# no report.json must exist
out_root = vc.output_root(vc._get_ds("custom", name))
check("no report.json (unprocessed precondition)",
      not (out_root / name / "report.json").exists())

# payload: graceful + carries the pre-process detection
p = vc.build_payload("custom", name)
check("payload flags unprocessed", p.get("unprocessed") is True)
check("payload carries pre-process bounds", p.get("bounds") is not None
      and p["bounds"].get("zb") is not None,
      f"zb={((p.get('bounds') or {}).get('zb') or {})}")

# previews on all three planes
for plane in ("sagittal", "coronal", "axial"):
    try:
        prev = vc.get_preview("custom", name, plane=plane, width=480,
                              cmap="grayscale")
        ok = bool(prev.get("png")) and prev.get("n_slices") == N
        check(f"preview plane={plane}", ok,
              f"z={prev.get('z')} bytes={len(prev.get('png') or '')}")
    except Exception as e:
        check(f"preview plane={plane}", False,
              f"raised {type(e).__name__}: {e}")

# the preview source must be flagged scan-native/unprocessed
src = vc._prev_source("custom", name)
check("preview source is scan-native", src.get("unprocessed") is True
      and src.get("cut") == N)

# ---------------- cleanup (de-register + delete synthetic specimen)
try:
    import shutil
    for k in [k for k in list(vc._PREV) if k.startswith(f"custom/{name}")]:
        vc._PREV.pop(k, None)
    csx.remove_specimen(name)
    shutil.rmtree(out_root / name, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("  cleanup ok")
except Exception as e:
    print(f"  cleanup warning: {e}")

print()
print("RESULT:", "ALL PASS" if fail == 0 else f"{fail} FAIL")
sys.exit(1 if fail else 0)
