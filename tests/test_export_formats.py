"""Export-format + progress + hygiene harness (audit round 0M).

Covers the reworked bundle exporter end-to-end on a synthetic DICOM
series (wood cylinder + metal base, 24 slices):

  1. BOTH    — DICOM series + NIfTI + sidecar + info, real progress phases
  2. DICOM   — series only; no .nii anywhere; sidecar/info adapted
  3. NIFTI   — volume only; no series dir; sidecar/info adapted
  4. NIfTI bytes identical across export modes (universal streaming)
  5. DICOM-rebuild fallback (no stripped.nii) still works, atomic tmp+rename
  6. Update-in-place re-export + killed-run tmp hygiene (incl. skipped modes)
  7. Format validation + collection-range bookkeeping (keep_from > 0)
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, r"H:\Treated Kyodai samples\metal_remover")

import numpy as np
import nibabel as nib
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from core import bundle_export as be

FAILS = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- synthetic series
tmp_root = Path(os.environ.get("CLEANCT_TEST_TMP_DIR", tempfile.gettempdir()))
tmp_root.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="cleanct_export_", dir=tmp_root))
ser = tmp / "XY"
ser.mkdir(parents=True)
rng = np.random.default_rng(11)
N = 24
study_uid, series_uid = generate_uid(), generate_uid()
for i in range(N):
    z = np.full((64, 64), -1000.0, np.float32)
    rr, cc = np.mgrid[:64, :64]
    disk = (rr - 32) ** 2 + (cc - 32) ** 2 <= 18 ** 2
    z[disk] = -600.0
    if i >= 20:
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

# stripped.nii in disk (x, y, z) order — as the pipeline writes it
vol_xyz = rng.random((64, 64, N)).astype(np.float32) * 400 - 1000
stripped = tmp / "stripped.nii"
nib.save(nib.Nifti1Image(vol_xyz, np.eye(4)), stripped)

report = {
    "platform": {"cut_from": 18, "keep_from": 4, "anchor_slice": 20,
                 "accepted_by": "detector", "baseline_hu": -951.3},
    "meta": {"pixel_spacing_yx_mm": [0.033, 0.033],
             "slice_thickness_mm": 0.5},
    "metrics": {"removed_fraction": 0.12},
    "gpu": {"name": "TEST"},
}
SPEC = "EXPSYN"
N_KEPT = 18 - 4          # collection range [4, 18)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def bundle_state(dest: Path):
    d = dest / SPEC
    return {
        "dcm": sorted((d / be.series_dir_name(SPEC)).glob("*.dcm"))
        if (d / be.series_dir_name(SPEC)).is_dir() else [],
        "nii": d / be.nifti_name(SPEC),
        "json": d / be.sidecar_name(SPEC),
        "txt": d / f"{SPEC}_extraction_info.txt",
    }


# ================================================================ 1) BOTH
dest_both = tmp / "out_both"
calls = []
res_both = be.export_bundle("syn", SPEC, tmp, json.loads(json.dumps(report)),
                            stripped, dest_both, keep_from=4,
                            export_format="both",
                            progress=lambda i, n, ph: calls.append((i, n, ph)))
st = bundle_state(dest_both)
check("BOTH: dicom series written (14 files)", len(st["dcm"]) == N_KEPT,
      f"n={len(st['dcm'])}")
check("BOTH: nifti + json + txt present",
      st["nii"].exists() and st["json"].exists() and st["txt"].exists())
check("BOTH: return contract",
      res_both["n_dicom"] == N_KEPT and res_both["export_format"] == "both"
      and res_both["nifti"] and res_both["cut_from"] == N_KEPT,
      f"n_dicom={res_both['n_dicom']} fmt={res_both['export_format']}")
phases = [ph for _i, _n, ph in calls]
first = []
for ph in phases:
    if not first or first[-1] != ph:
        first.append(ph)
check("BOTH: ordered phases preparing→dicom→nifti→sidecar→verify",
      first == ["preparing", "dicom", "nifti", "sidecar", "verify"],
      f"got {first}")
check("BOTH: real dicom progress reaches (n, n)",
      (N_KEPT, N_KEPT, "dicom") in calls,
      f"last dicom={[c for c in calls if c[2]=='dicom'][-1:]}")
check("BOTH: real nifti progress reaches (n, n) slices",
      (N_KEPT, N_KEPT, "nifti") in calls,
      f"last nifti={[c for c in calls if c[2]=='nifti'][-1:]}")
side = json.loads(st["json"].read_text(encoding="utf-8"))
check("BOTH: sidecar bookkeeping",
      side["n_slices_kept"] == N_KEPT and side["n_slices_original"] == N
      and side["export_formats"] == "both"
      and len(side["file_mapping"]) == N_KEPT
      and "collected from slice 4" in side["source_folder"],
      f"kept={side['n_slices_kept']} orig={side['n_slices_original']} "
      f"fmt={side.get('export_formats')}")
check("BOTH: sidecar nifti block populated",
      isinstance(side["nifti"], dict) and str(side["nifti"].get("nii", "")).endswith(".nii"),
      f"nifti={side['nifti']}")
check("BOTH: PatientName = specimen id",
      str(pydicom.dcmread(st["dcm"][0]).PatientName) == SPEC)
_check0 = pydicom.dcmread(st["dcm"][0])
_src_names = be.sorted_source_files(tmp)[4:4 + N_KEPT]
check("BOTH: exported files keep ORIGINAL slice filenames",
      st["dcm"][0].name == _src_names[0].name
      and not any("_rem" in f.name for f in st["dcm"]),
      f"first={st['dcm'][0].name}")
check("BOTH: full delivery metadata written and readable",
      str(_check0.PatientID) == SPEC
      and str(_check0.Modality) == "CT"
      and "cleanCT" in str(_check0.SoftwareVersions)
      and "cleanCT" in str(_check0.StudyDescription)
      and str(_check0.SeriesDescription).startswith("cleanCT")
      and "cleanCT" in str(_check0.ImageComments)
      and float(_check0.SliceThickness) > 0
      and len(_check0.PixelSpacing) == 2
      and str(getattr(_check0, "AcquisitionTime", "")) != "",
      f"pid={_check0.PatientID} mod={_check0.Modality} sw={_check0.SoftwareVersions}")
check("BOTH: sidecar records the written DICOM tags",
      side.get("dicom_tags", {}).get("PatientName") == SPEC
      and str(side.get("dicom_tags", {}).get("SoftwareVersions", "")).startswith("cleanCT"),
      str(side.get("dicom_tags", {}))[:120])
nii_sha_both = sha(st["nii"])
check("BOTH: nifti (x, y, z) shape (64, 64, 14)",
      tuple(nib.load(st["nii"]).shape) == (64, 64, N_KEPT),
      f"shape={nib.load(st['nii']).shape}")

# ================================================================ 2) DICOM only
dest_dcm = tmp / "out_dcm"
res_dcm = be.export_bundle("syn", SPEC, tmp, json.loads(json.dumps(report)),
                           stripped, dest_dcm, keep_from=4,
                           export_format="dicom")
st2 = bundle_state(dest_dcm)
check("DICOM: series written, NO nifti anywhere",
      len(st2["dcm"]) == N_KEPT and not st2["nii"].exists())
check("DICOM: return contract (nifti None, n_dicom set)",
      res_dcm["nifti"] is None and res_dcm["n_dicom"] == N_KEPT
      and res_dcm["export_format"] == "dicom")
side2 = json.loads(st2["json"].read_text(encoding="utf-8"))
check("DICOM: sidecar marks nifti skipped + formats",
      side2["nifti"].get("skipped") is True
      and side2["export_formats"] == "dicom")
txt2 = st2["txt"].read_text(encoding="utf-8")
check("DICOM: info txt adapted",
      "DICOM-only export" in txt2 and "not requested" in txt2)

# ================================================================ 3) NIfTI only
dest_nii = tmp / "out_nii"
res_nii = be.export_bundle("syn", SPEC, tmp, json.loads(json.dumps(report)),
                           stripped, dest_nii, keep_from=4,
                           export_format="nifti")
st3 = bundle_state(dest_nii)
check("NIFTI: volume written, NO series dir",
      st3["nii"].exists() and not (dest_nii / SPEC / be.series_dir_name(SPEC)).exists())
check("NIFTI: return contract (n_dicom 0)",
      res_nii["n_dicom"] == 0 and res_nii["nifti"] and
      res_nii["export_format"] == "nifti")
side3 = json.loads(st3["json"].read_text(encoding="utf-8"))
check("NIFTI: sidecar empty mapping + formats",
      side3["file_mapping"] == [] and side3["export_formats"] == "nifti")
txt3 = st3["txt"].read_text(encoding="utf-8")
check("NIFTI: info txt adapted",
      "NIfTI-only export" in txt3 and "nifti volume" in txt3
      and "not requested" in txt3,
      repr(txt3[txt3.find("OUTPUTS"):txt3.find("OUTPUTS") + 220]))

# ================================================================ 4) byte identity across modes
check("NIfTI bytes identical across export modes",
      nii_sha_both == sha(st3["nii"]),
      f"{nii_sha_both[:12]} vs {sha(st3['nii'])[:12]}")

# ================================================================ 5) DICOM-rebuild fallback (no stripped.nii)
dest_fb = tmp / "out_fb"
res_fb = be.export_bundle("syn", SPEC, tmp, json.loads(json.dumps(report)),
                          tmp / "missing.nii", dest_fb, keep_from=4,
                          export_format="nifti")
img_fb = nib.load(res_fb["nifti"])
check("FALLBACK: volume rebuilt from DICOMs, atomic tmp rename",
      tuple(img_fb.shape) == (64, 64, N_KEPT)
      and not (dest_fb / SPEC / (be.nifti_name(SPEC) + ".tmp")).exists(),
      f"shape={img_fb.shape}")
# The disk-backed fallback must stay byte-identical to nib.save of the same
# rebuilt volume. export_bundle slices source_files to the kept range first.
_keep = 4
_files_kept = be.sorted_source_files(tmp)[_keep:_keep + N_KEPT]


def _reference_plane(path):
    dataset = pydicom.dcmread(path)
    return (dataset.pixel_array.astype(np.float32)
            * float(getattr(dataset, "RescaleSlope", 1.0))
            + float(getattr(dataset, "RescaleIntercept", 0.0)))


# stacking planes gives (z, y, x); NIfTI volumes are (x, y, z) like the affine
_vol_ref = np.stack([_reference_plane(path) for path in _files_kept],
                    axis=0).transpose(2, 1, 0).copy()
_ref_img = nib.Nifti1Image(
    _vol_ref, be.nifti_affine(_files_kept[:N_KEPT],
                              (0, N_KEPT - 1, 0, 0, 0, 0)))
_ref_img.header.set_xyzt_units("mm")
_ref_img.header["scl_slope"] = 1.0
_ref_img.header["scl_inter"] = 0.0
_nib_ref = tmp / "fb_ref.nii"
nib.save(_ref_img, str(_nib_ref))
check("FALLBACK: streamed bytes == nib.save bytes",
      sha(res_fb["nifti"]) == sha(_nib_ref),
      f"{sha(res_fb['nifti'])[:12]} vs {sha(_nib_ref)[:12]}")
if sha(res_fb["nifti"]) != sha(_nib_ref):
    _a = Path(res_fb["nifti"]).read_bytes()
    _b = _nib_ref.read_bytes()
    print(f"  sizes: streamed={len(_a)} nibsave={len(_b)}")
    _n = min(len(_a), len(_b))
    _dd = [i for i in range(_n) if _a[i] != _b[i]]
    print(f"  differing bytes: {len(_dd)}; first 16: {_dd[:16]}")
    for _i in _dd[:16]:
        print(f"    byte {_i}: streamed={_a[_i]:02x} nibsave={_b[_i]:02x}")
    _ia = nib.load(res_fb["nifti"])
    _ib = nib.load(_nib_ref)
    print(f"  affines equal: {np.allclose(_ia.affine, _ib.affine)}")
    print(f"  streamed affine z-col: {_ia.affine[:, 2]}, t: {_ia.affine[:, 3]}")
    print(f"  nibsave  affine z-col: {_ib.affine[:, 2]}, t: {_ib.affine[:, 3]}")
    print(f"  streamed qform_code={int(_ia.header['qform_code'])} "
          f"sform_code={int(_ia.header['sform_code'])} pixdim={_ia.header['pixdim']}")
    print(f"  nibsave  qform_code={int(_ib.header['qform_code'])} "
          f"sform_code={int(_ib.header['sform_code'])} pixdim={_ib.header['pixdim']}")

# ================================================================ 6) tmp hygiene + update-in-place
dest_hyg = tmp / "out_hyg"
be.export_bundle("syn", SPEC, tmp, json.loads(json.dumps(report)),
                 stripped, dest_hyg, keep_from=4, export_format="both")
# plant killed-run leftovers: exact-stem dicom tmp dir + nii tmp file
(tmp_hyg_dir := dest_hyg / SPEC / (be.series_dir_name(SPEC) + ".tmp")).mkdir(parents=True)
(tmp_hyg_dir / "junk.dcm").write_bytes(b"x")
(dest_hyg / SPEC / (be.nifti_name(SPEC) + ".tmp")).write_bytes(b"x")
# re-export DICOM-ONLY: tmp cleanup must happen even for skipped artifacts
be.export_bundle("syn", SPEC, tmp, json.loads(json.dumps(report)),
                 stripped, dest_hyg, keep_from=4, export_format="dicom")
check("HYGIENE: tmp leftovers cleaned even when artifacts are skipped",
      not tmp_hyg_dir.exists()
      and not (dest_hyg / SPEC / (be.nifti_name(SPEC) + ".tmp")).exists())
st4 = bundle_state(dest_hyg)
# update-in-place is NON-destructive: the series is rebuilt; the NIfTI
# from the earlier BOTH export is not requested and therefore left untouched
check("HYGIENE: update-in-place re-export verifies (non-destructive)",
      len(st4["dcm"]) == N_KEPT and st4["nii"].exists(),
      f"dcm={len(st4['dcm'])} nii_exists={st4['nii'].exists()}")

# A later artifact failure must not publish a mixed-generation bundle.
old_dcm_hash = sha(st4["dcm"][0])
old_nii_hash = sha(st4["nii"])
old_json = st4["json"].read_bytes()
real_nifti_writer = be._write_kept_nifti


def fail_nifti_write(*_args, **_kwargs):
    raise OSError("synthetic NIfTI write interruption")


be._write_kept_nifti = fail_nifti_write
try:
    try:
        be.export_bundle("syn", SPEC, tmp, json.loads(json.dumps(report)),
                         stripped, dest_hyg, keep_from=4,
                         export_format="both")
        interrupted_export = False
    except OSError as exc:
        interrupted_export = "synthetic NIfTI write interruption" in str(exc)
finally:
    be._write_kept_nifti = real_nifti_writer
after_failure = bundle_state(dest_hyg)
check("TRANSACTION: failed re-export preserves previous complete bundle",
      interrupted_export and len(after_failure["dcm"]) == N_KEPT
      and sha(after_failure["dcm"][0]) == old_dcm_hash
      and sha(after_failure["nii"]) == old_nii_hash
      and after_failure["json"].read_bytes() == old_json
      and not (dest_hyg / f".{SPEC}.bundle.tmp").exists()
      and not (dest_hyg / f".{SPEC}.bundle.old").exists())

# ================================================================ 7) format validation
try:
    be.export_bundle("syn", SPEC, tmp, json.loads(json.dumps(report)),
                     stripped, tmp / "out_bad", keep_from=4,
                     export_format="parquet")
    check("FORMAT: invalid format rejected", False)
except be.BundleError as e:
    check("FORMAT: invalid format rejected", "unknown export format" in str(e),
          str(e))

shutil.rmtree(tmp, ignore_errors=True)
print()
print("ALL PASS" if not FAILS else f"FAILURES: {FAILS}")
sys.exit(0 if not FAILS else 1)
