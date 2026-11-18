"""E2E: a specimen with NO bottom metal platform must process cleanly.

The 2-21 field failure (2-21 has metal, but not bottom-anchored — run
length 0) is reproduced with a synthetic metal-free scan: registration →
process_sample → report with no_platform=True, keep/cut honored, real
delivery outputs written.  Fleet specimens (all WITH metal) must be
byte-identical in semantics — their anchor path never touches the new
branch (anch != 0).
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import os  # noqa: E402

# Not a gate test: it runs the real engine, so it runs only when asked, and
# only into scratch folders under the temp directory.
if os.environ.get("CLEANCT_REAL_DATA") != "1":
    print("SKIP: needs real specimen data (set CLEANCT_REAL_DATA=1)")
    sys.exit(0)
for _var in ("CLEANCT_DATA", "CLEANCT_OUTPUT_ROOT"):
    _value = os.environ.get(_var, "")
    if not _value or not Path(_value).resolve().is_relative_to(
            Path(tempfile.gettempdir()).resolve()):
        print(f"FAIL: {_var} must point at a scratch folder under the temp directory")
        sys.exit(1)

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

fail = 0


def check(name, cond, extra=""):
    global fail
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fail += 1


print("[1] synthetic NO-METAL specimen (air + wood only)")
tmp = Path(tempfile.mkdtemp(prefix="nometal_"))
ser = tmp / "XY"
ser.mkdir(parents=True)
N = 40                                        # 40 x 2 mm = 80 mm tall
# 256^2 matrix: the 33.1 um custom preset needs a >=20,000 px wood seed
# (a 64^2 phantom can never satisfy it — and no real scan is that small)
rr, cc = np.mgrid[:256, :256]
DISK = (rr - 128) ** 2 + (cc - 128) ** 2 <= 100 ** 2   # ~31k px
study_uid, series_uid = generate_uid(), generate_uid()
for i in range(N):
    z = np.full((256, 256), -1000.0, np.float32)
    if 16 <= i < 38:
        z[DISK] = -600.0                      # wood cylinder; 16 air slices
                                              # above (0.32 mm > fog margin)
    d = Dataset()
    d.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    d.SOPInstanceUID = generate_uid()
    d.StudyInstanceUID = study_uid
    d.SeriesInstanceUID = series_uid
    d.Modality = "CT"
    d.Rows, d.Columns = 256, 256
    d.SamplesPerPixel = 1
    d.BitsAllocated = 16
    d.BitsStored = 16
    d.HighBit = 15
    d.PixelRepresentation = 1
    d.PhotometricInterpretation = "MONOCHROME2"
    d.PixelSpacing = [0.020, 0.020]           # 20 µm isotropic (0.3 mm fog
    d.SliceThickness = 0.020                  # margin = 15 slices of clearance)
    d.ImagePositionPatient = [0, 0, float(i) * 2.0]
    d.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    d.RescaleSlope, d.RescaleIntercept = 1.0, -1024.0
    d.file_meta = FileMetaDataset()
    d.file_meta.MediaStorageSOPClassUID = d.SOPClassUID
    d.file_meta.MediaStorageSOPInstanceUID = d.SOPInstanceUID
    d.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    d.PixelData = (z.astype(np.int16) - (-1024)).tobytes()
    pydicom.dcmwrite(ser / f"s{i:04d}.dcm", d, enforce_file_format=True)

from core import custom_series as csx
import sys as _sys
import time as _time
# unique per run: re-registering the same name would inherit the previous
# run's pipeline outputs (report.json poisons the preview cache)
NAME = f"ZZ_nometal_{_time.strftime('%H%M%S')}"
OUT_DIR = Path(os.environ["CLEANCT_OUTPUT_ROOT"]) / "custom" / NAME
from core.paths import ensure_engine_on_path  # noqa: E402
ensure_engine_on_path()
import tomograph as tg

csx.remove_specimen(NAME)                     # idempotent
csx.register_series(ser, NAME)

print("[2] pre-process detection: no metal-top guide, wood bottom present")
from core import viewer_core as vc
for k in [k for k in list(vc._PREV) if k.startswith("custom/" + NAME)]:
    vc._PREV.pop(k)
src = vc._prev_source("custom", NAME)
b = src.get("bounds") or {}
zb = b.get("zb") or {}
check("no metal-top cut guide (falls back to wood bottom)",
      zb.get("cut") is not None and zb["cut"] == zb.get("wood_bottom", -9) + 1,
      str(zb))
check("air top confirmed (clear margin at 20 um voxels)",
      zb.get("keep") is not None and 1 <= zb["keep"] <= 4, str(zb.get("keep")))
check("wood bottom present for the reference", zb.get("wood_bottom") is not None
      and 30 <= zb["wood_bottom"] <= 39, str(zb.get("wood_bottom")))

print("[3] pipeline run (the operation that used to hard-fail)")
ds = csx.as_dataset(NAME)
cfg_dict = dict(ds.config_overrides)
cfg_dict["io_workers"] = 16
cfg_dict["save_stripped_nii"] = True
cfg = tg.DEFAULTS.overridden(cfg_dict)
gpu = tg.get_backend(verbose=False, preference="auto")
r = tg.process_sample(NAME, cfg, ds, False, gpu, verbose=False)
gpu.release()
rep = r                       # process_sample returns the report dict
plat = rep.get("platform", {})
check("pipeline completed (no exception)", True)
check("report flags no_platform", plat.get("no_platform") is True,
      f"anchor={plat.get('anchor_slice')}")
check("delivery cut = n (whole scan kept, ROI limits delivery)",
      plat.get("cut_from") == N, f"cut_from={plat.get('cut_from')}")
check("wood ROI delivered non-empty",
      (rep.get("wood_roi", {}).get("bbox_zyx") or [None])[0] is not None)
check("delivery files written on disk",
      any((p.name.startswith("wood_roi")) for p in (Path('../metal_remover/output/custom') / NAME).glob('*')),
      str(sorted(p.name for p in (Path('../metal_remover/output/custom') / NAME).glob('*'))[:4]))

print("[4] user-defined lines are honored (keep + cut override)")
cfg_dict2 = dict(cfg_dict)
cfg_dict2["cut_override"] = 30          # user: keep 0..29
cfg_dict2["keep_from"] = 4              # user: start at slice 4
cfg2 = tg.DEFAULTS.overridden(cfg_dict2)
gpu = tg.get_backend(verbose=False, preference="auto")
r2 = tg.process_sample(NAME, cfg2, ds, False, gpu, verbose=False)
gpu.release()
p2 = r2["platform"]
check("user cut_override honored", p2.get("cut_from") == 30,
      f"cut_from={p2.get('cut_from')} accepted_by={p2.get('accepted_by')}")
check("user keep_from honored", p2.get("keep_from") == 4)
check("removed fraction sane (slices 30..39 removed = 25%)",
      abs(r2["metrics"]["removed_fraction"] - 0.25) < 0.05,
      f"{r2['metrics']['removed_fraction']:.3f}")

print("[5] invalid user lines raise a CLEAR error")
try:
    cfg_dict3 = dict(cfg_dict)
    cfg_dict3["cut_override"] = 30
    cfg_dict3["keep_from"] = 30            # keep >= cut → must raise, clearly
    cfg3 = tg.DEFAULTS.overridden(cfg_dict3)
    gpu = tg.get_backend(verbose=False, preference="auto")
    tg.process_sample(NAME, cfg3, ds, False, gpu, verbose=False)
    gpu.release()
    check("keep>=cut rejected", False, "no exception raised")
except RuntimeError as e:
    check("keep>=cut rejected with clear message",
          "must be below the cut slice" in str(e), str(e)[:80])

print()
print("RESULT:", "ALL PASS" if fail == 0 else f"{fail} FAIL")
csx.remove_specimen(NAME)
import shutil
shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(OUT_DIR, ignore_errors=True)
print("(cleanup ok)")
sys.exit(1 if fail else 0)
