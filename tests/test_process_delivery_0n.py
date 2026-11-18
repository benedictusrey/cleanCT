"""Audit 0N — real-specimen E2E: streamed delivery writes == old in-RAM path.

Re-processes the REAL 2-21 with the exact config of its stored report,
then byte-compares every delivery artifact against the reference outputs
produced by the pre-0N code (in-RAM nib.save + serial DICOM loop):
  * stripped.nii     — full-FOV stripped volume (streamed, was untimed)
  * wood_roi.nii     — ROI NIfTI with comment extension (streamed)
  * wood_roi_dicom/  — derived series (parallel workers, deterministic UIDs)
  * wood_roi_dicom_index.csv + wood_roi_provenance.json
Also reports the wall-clock speedup and the new timings_s breakdown.
"""
import filecmp
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, r"H:\Treated Kyodai samples\metal_remover")

import tomograph as tg

OUT = Path(r"H:\Treated Kyodai samples\metal_remover\output\custom\2-21")
REF = OUT.parent / "2-21_ref0n"
NAME = "2-21"

FAILS = []


def check(name, ok, extra=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {extra}" if extra else ""))
    if not ok:
        FAILS.append(name)


# crash-safety: a previous interrupted run may have left the reference aside
if REF.exists() and (REF / "report.json").exists():
    if OUT.exists():
        shutil.rmtree(OUT)
    REF.rename(OUT)

report = json.loads((OUT / "report.json").read_text())
cfg_dict = dict(report["config"])
cfg_dict["io_workers"] = 16
cfg_dict["save_stripped_nii"] = True
cfg = tg.DEFAULTS.overridden(cfg_dict)

ds_source = Path(r"H:\Treated Kyodai samples\1 MONTH\3 after oven-dry state"
                 r"\24.852 um per px\Bottle 1")
from tomograph import DatasetSpec  # noqa: E402
ds = DatasetSpec(key="custom", source=ds_source, out_sub="custom",
                 config_overrides={}, ground_truth={})

# preserve the reference outputs
if REF.exists():
    shutil.rmtree(REF)
shutil.move(str(OUT), str(REF))
OUT.mkdir(parents=True, exist_ok=True)

gpu = tg.get_backend(verbose=False, preference="auto")
t0 = time.perf_counter()
r = tg.process_sample(NAME, cfg, ds, False, gpu, verbose=False)
elapsed = time.perf_counter() - t0

print(f"\n=== elapsed {elapsed:.1f}s (reference run: 197 s) ===")
print("timings:", r.get("timings_s"))

# ---- comparisons -----------------------------------------------------------
def same_file(a: Path, b: Path) -> bool:
    if not (a.exists() and b.exists()):
        return False
    if a.stat().st_size != b.stat().st_size:
        return False
    return filecmp.cmp(str(a), str(b), shallow=False)


stripped_ok = same_file(OUT / "stripped.nii", REF / "stripped.nii")
check("stripped.nii byte-identical", stripped_ok,
      f"{(OUT / 'stripped.nii').stat().st_size if (OUT / 'stripped.nii').exists() else 0} B")
if not stripped_ok:
    import numpy as _np
    _a = (OUT / "stripped.nii").read_bytes()[:352]
    _b = (REF / "stripped.nii").read_bytes()[:352]
    _diffs = [i for i in range(352) if _a[i] != _b[i]]
    print(f"  header diffs: {len(_diffs)} bytes -> {_diffs[:12]}")
    for _i in _diffs[:12]:
        print(f"    byte {_i}: new={_a[_i]:02x} old={_b[_i]:02x}")
    _na = _np.memmap(OUT / "stripped.nii", dtype=_np.float32, mode="r", offset=352)
    _nb = _np.memmap(REF / "stripped.nii", dtype=_np.float32, mode="r", offset=352)
    _n = min(_na.size, _nb.size, 50_000_000)
    _eq = (_na[:_n] == _nb[:_n]) | (_np.isnan(_na[:_n]) & _np.isnan(_nb[:_n]))
    _dd = _np.flatnonzero(~_eq)
    print(f"  data diffs in first {_n:,} voxels: {_dd.size:,}")
    if _dd.size:
        _i = int(_dd[0])
        print(f"    first at voxel {_i:,}: new={_na[_i]} old={_nb[_i]}")
    del _na, _nb
check("wood_roi.nii byte-identical",
      same_file(OUT / "wood_roi.nii", REF / "wood_roi.nii"))
check("index csv byte-identical",
      same_file(OUT / "wood_roi_dicom_index.csv",
                REF / "wood_roi_dicom_index.csv"))

# provenance.json: integers + strings must match exactly; float64 reduction
# statistics (profile sums over the volume) may differ in the last digits
# when the two runs used different GPU backends (torch vs CuPy) — different
# reduction order, same physics.  Backend is recorded in the report.
def provenance_compatible(a: Path, b: Path) -> tuple[bool, str]:
    if not (a.exists() and b.exists()):
        return False, "missing file"
    la, lb = a.read_text().splitlines(), b.read_text().splitlines()
    if len(la) != len(lb):
        return False, f"line count {len(la)} vs {len(lb)}"
    import re as _re
    _num = _re.compile(r'"([a-z0-9_]+)": (-?\d+\.\d+(?:e-?\d+)?|-?\d+)')
    for i, (xa, xb) in enumerate(zip(la, lb)):
        if xa == xb:
            continue
        ma, mb = _num.search(xa), _num.search(xb)
        if not (ma and mb and ma.group(1) == mb.group(1)):
            return False, f"line {i + 1}: {xa!r} vs {xb!r}"
        try:
            va, vb = float(ma.group(2)), float(mb.group(2))
        except ValueError:
            return False, f"line {i + 1}: unparsable float"
        if va == vb:
            continue
        if va.is_integer() and vb.is_integer():
            return False, f"line {i + 1}: integer mismatch {xa!r} vs {xb!r}"
        denom = max(abs(va), abs(vb), 1e-30)
        if abs(va - vb) / denom > 1e-9:
            return False, f"line {i + 1}: beyond backend epsilon: {xa!r} vs {xb!r}"
    return True, f"float64 reductions within backend epsilon"

_prov_ok, _prov_note = provenance_compatible(OUT / "wood_roi_provenance.json",
                                             REF / "wood_roi_provenance.json")
check("provenance identical (float stats within backend epsilon)",
      _prov_ok, _prov_note)

ref_dcm = sorted((REF / "wood_roi_dicom").glob("*.dcm"))
new_dcm = sorted((OUT / "wood_roi_dicom").glob("*.dcm"))
check("dicom series count", len(ref_dcm) == len(new_dcm) and len(new_dcm) > 0,
      f"ref={len(ref_dcm)} new={len(new_dcm)}")
mismatch = 0
for a, b in zip(new_dcm, ref_dcm):
    if not same_file(a, b):
        mismatch += 1
        if mismatch <= 3:
            print(f"  differ: {a.name}")
check("dicom series byte-identical", mismatch == 0,
      f"{len(new_dcm) - mismatch}/{len(new_dcm)} identical")

# report semantics (timings/gpu differ by design)
ref_r = json.loads((REF / "report.json").read_text())
check("cut_from identical",
      r["platform"]["cut_from"] == ref_r["platform"]["cut_from"],
      f"cut={r['platform']['cut_from']} (accepted_by={r['platform']['accepted_by']})")
check("keep_from identical",
      r["platform"]["keep_from"] == ref_r["platform"]["keep_from"],
      f"keep={r['platform']['keep_from']}")
check("metrics identical",
      r["metrics"]["removed_fraction"] == ref_r["metrics"]["removed_fraction"],
      f"{r['metrics']['removed_fraction']:.4%}")
check("roi bbox identical",
      r["wood_roi"]["bbox_zyx"] == ref_r["wood_roi"]["bbox_zyx"],
      f"bbox={r['wood_roi']['bbox_zyx']}")

# cleanup: on success restore the reference as the canonical output;
# on failure keep both trees for post-mortem
if not FAILS:
    shutil.rmtree(OUT)
    REF.rename(OUT)
else:
    print(f"  (kept for post-mortem: {OUT} and {REF})")

print()
if FAILS:
    print(f"FAILURES: {FAILS}")
    sys.exit(1)
print("ALL PASS")
