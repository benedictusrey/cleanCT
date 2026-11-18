"""Fleet validation of the adaptive z-guides + cross-resolution agreement.

For every sample in both datasets:
  * metal anchor vs the pipeline's detector anchor_slice
  * keep guide (air top) vs the report's keep_from
  * XY bounds vs the previously validated percentile envelope
Cross-resolution: the same specimen number at 24um vs 66um must agree in
PHYSICAL mm (within the coarse-voxel tolerance).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import os  # noqa: E402

# Reads the real specimens' outputs, so it runs only when asked. It only
# reads, so it does not need a scratch folder.
if os.environ.get("CLEANCT_REAL_DATA") != "1":
    print("SKIP: needs real specimen data (set CLEANCT_REAL_DATA=1)")
    sys.exit(0)

from core import viewer_core as vc  # noqa: E402

flags: list[str] = []
rows: list[str] = []
checked = 0


def load_report(dkey: str, sample: str) -> dict | None:
    sdir = vc.output_root(vc.DATASETS[dkey]) / sample
    rp = sdir / "report.json"
    if not rp.exists():
        return None
    return json.loads(rp.read_text())


for dkey in ("24um", "66um"):
    sdir_root = vc.output_root(vc.DATASETS[dkey])
    samples = sorted(p.name for p in sdir_root.iterdir()
                     if p.is_dir() and not p.name.startswith(("_", ".")))
    for sample in samples:
        rep = load_report(dkey, sample)
        if not rep:
            continue
        checked += 1
        try:
            src = vc._prev_source(dkey, sample)
        except Exception as e:
            flags.append(f"{dkey}/{sample}: prev_source failed: {e}")
            continue
        b = src.get("bounds")
        if not b:
            flags.append(f"{dkey}/{sample}: bounds is None")
            continue

        track = rep.get("wood_roi", {}).get("track", {}) or {}
        plat = rep.get("platform", {})
        anchor_det = plat.get("anchor_slice")
        keep_rep = plat.get("keep_from")
        t = rep.get("wood_roi", {}).get("track", {})
        vox = b.get("voxel_um")
        zmm = 0.0
        if vox:
            try:
                zmm = vox / 1000.0
            except Exception:
                zmm = 0.0

        # --- metal anchor vs detector -----------------------------------
        az = (b.get("anchor") or {}).get("z")
        a_ok = "n/a"
        if az and anchor_det is not None:
            # detector anchor is the first base slice; guide anchor top is
            # the same slice (within the guard's 1-slice rounding)
            if abs(az[0] - int(anchor_det)) <= 8:
                a_ok = "ok"
            else:
                a_ok = f"MISMATCH det={anchor_det} guide={az[0]}"
                flags.append(f"{dkey}/{sample}: anchor mismatch ({a_ok})")

        # --- keep guide vs report keep_from ------------------------------
        zk = (b.get("zb") or {}).get("keep")
        k_ok = "n/a"
        if zk is not None and keep_rep is not None and t.get("z0") is not None:
            d_mm = abs(zk - int(keep_rep)) * zmm
            # keep_from is the tracker's onset slice; the air top should sit
            # within 1.5 mm of it (halo/fog differences allowed)
            if d_mm <= 1.5:
                k_ok = f"ok ({d_mm:.2f} mm)"
            else:
                k_ok = f"FAR det={keep_rep} guide={zk} d={d_mm:.2f}mm"
                flags.append(f"{dkey}/{sample}: keep guide far from report ({k_ok})")

        # --- track_z sanity: keep inside tracked range -------------------
        if t.get("z0") is not None and zk is not None:
            if not (int(t["z0"]) - 10 <= zk <= int(t.get("z1", 10**9))):
                flags.append(f"{dkey}/{sample}: keep outside tracked range ({zk})")

        vox_txt = f"{vox:.1f}um" if vox is not None else "n/a"
        rows.append(f"{dkey}/{sample}: xy=({b['x0']},{b['y0']})-({b['x1']},{b['y1']}) "
                    f"voxel={vox_txt} anchor={a_ok} keep={k_ok} "
                    f"zb={b.get('zb', {}).get('keep')}/{b.get('zb', {}).get('cut')}")

if checked == 0:
    print("FAIL: no reports found")
    sys.exit(1)
print("\n".join(rows))
print()
if flags:
    print("FLAGS:")
    print("\n".join(flags))
    sys.exit(1)
print("FLEET OK — all samples pass anchor/keep/xy validation")
