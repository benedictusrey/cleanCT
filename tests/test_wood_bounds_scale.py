"""Offline tests for the resolution-adaptive wood_bounds (no GPU, no DICOM).

1. Unit checks on a synthetic specimen rendered at 12 µm / 66 µm (low-res
   variants are analytically downsampled, so no big arrays are ever built).
2. Physical-consistency sweep: the SAME physical specimen rendered at
   12 / 25 / 66 / 120 µm must produce bounds agreeing in MILLIMETRES —
   this is the definition of resolution-adaptive behaviour.
3. Detector-model ladder: real micro-CT scanners keep the detector width
   roughly constant and SHRINK the FOV as the voxel shrinks, so a full
   1-100 µm ladder at constant FOV would need 28000^2 arrays at 1 µm
   (physically meaningless).  The ladder instead renders the same z
   geometry in a compact FOV across 1 / 2 / 3 / 5 / 8 / 12 / 24 / 33 /
   50 / 66 / 100 µm — this is what exercises the ultra-high-res compute
   guards (closing-radius cap, strided edge walks, streaming axial pool)
   and proves the lines stay put in millimetres at every rung.

Air evidence is injected through ``slice_provider`` so the test never
touches the real dataset cache.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from core import wood_bounds as wb

failures: list[str] = []


def check(name: str, cond: bool, info: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}" + (f"  ({info})" if info and not cond else ""))
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------------------
# synthetic specimen (physical coordinates, mm)
# ---------------------------------------------------------------------------
FOV_MM = 28.0          # physical width/height of the scan FOV
N_SLICES = 300
CUT_FROM = 270         # wood lives below this
BASE_TOP_MM = 26.0     # metal base occupies 26..28 mm
WOOD_TOP_MM = 1.2
WOOD_BOTTOM_MM = 24.0  # wood touches the trusted window bottom
WOOD_Y_MM = (6.0, 22.0)
WOOD_X_MM = (7.0, 21.0)
AIR_HU, WOOD_LO, WOOD_HI, METAL_HU = -900.0, -990.0, -500.0, 0.0

# z := y here (axial slices are (y, x), depth runs along rows) — the wood
# spans rows; the "z" axis of the synthetic volume is the FIRST image axis
# of each axial slice is y; presence varies with the slice index only.


def render_slice(voxel_um: float, z: int) -> np.ndarray:
    """Axial slice at index z for a voxel size; downsamples analytically."""
    n = max(8, int(round(FOV_MM * 1000.0 / voxel_um)))
    yy, xx = np.mgrid[0:n, 0:n]
    y_mm = yy * (FOV_MM / n)
    x_mm = xx * (FOV_MM / n)

    z_mm = z * (28.0 / N_SLICES)          # 1 slice == 0.0933 mm slab
    img = np.full((n, n), -1000.0, np.float32)

    # metal base slab
    if z_mm >= BASE_TOP_MM:
        img[:] = 500.0
        return img

    # wood block (with a fog-free interior)
    wm = ((y_mm >= WOOD_Y_MM[0]) & (y_mm <= WOOD_Y_MM[1])
          & (x_mm >= WOOD_X_MM[0]) & (x_mm <= WOOD_X_MM[1])
          & (z_mm >= WOOD_TOP_MM) & (z_mm < WOOD_BOTTOM_MM))
    img[wm] = -600.0
    return img


def make_provider(voxel_um: float) -> wb.RefProvider:
    def provider(zs: list[int]) -> dict[int, np.ndarray]:
        return {z: render_slice(voxel_um, z) for z in zs}
    return provider


def make_ortho(voxel_um: float):
    """Sagittal/coronal stacks (n, w): per-slice 1D profile through the base."""
    n = max(8, int(round(FOV_MM * 1000.0 / voxel_um)))
    base_w = max(8, int(round(0.55 * n)))
    off = (n - base_w) // 2
    sag = np.full((N_SLICES, n), -1000.0, np.float32)
    for z in range(N_SLICES):
        z_mm = z * (28.0 / N_SLICES)
        if z_mm >= BASE_TOP_MM:
            sag[z, off:off + base_w] = 500.0
        elif WOOD_TOP_MM <= z_mm < WOOD_BOTTOM_MM:
            sag[z, off + base_w // 4: off + base_w // 4 + max(2, base_w // 8)] = -600.0
    return sag, sag.copy()


def sag_cor_for(voxel_um: float):
    return make_ortho(voxel_um)


Z_STEP_UM = 28.0 / N_SLICES * 1000.0   # synthetic slice thickness (µm)


def run_bounds(voxel_um: float) -> dict:
    sag, cor = sag_cor_for(voxel_um)
    return wb.wood_bounds(
        None, "syn", n_slices=N_SLICES, cut_from=CUT_FROM,
        sag=sag, cor=cor, metal_hu=METAL_HU,
        track_z=(0, CUT_FROM - 1), voxel_um=voxel_um,
        wood_hu=(WOOD_LO, WOOD_HI), slice_provider=make_provider(voxel_um),
        z_step_um=Z_STEP_UM)


# ---------------------------------------------------------------------------
# 1. unit checks at two resolutions
# ---------------------------------------------------------------------------
for vu in (12.0, 66.0):
    b = run_bounds(vu)
    check(f"{vu:g}um: bounds returned", b is not None)
    if b is None:
        continue
    mm = FOV_MM / b["W"]
    y0m, y1m = b["y0"] * mm, (b["y1"] + 1) * mm
    x0m, x1m = b["x0"] * mm, (b["x1"] + 1) * mm
    check(f"{vu:g}um: X bounds match physical wood",
          abs(x0m - WOOD_X_MM[0]) < 0.6 and abs(x1m - WOOD_X_MM[1]) < 0.6,
          f"x {x0m:.2f}..{x1m:.2f} mm vs {WOOD_X_MM}")
    check(f"{vu:g}um: Y bounds match physical wood",
          abs(y0m - WOOD_Y_MM[0]) < 0.6 and abs(y1m - WOOD_Y_MM[1]) < 0.6,
          f"y {y0m:.2f}..{y1m:.2f} mm vs {WOOD_Y_MM}")
    check(f"{vu:g}um: metal anchor found at the base",
          b["anchor"]["ok"] and b["anchor"]["z"][0] * (28.0 / N_SLICES) >= BASE_TOP_MM - 0.5,
          str(b["anchor"]))
    check(f"{vu:g}um: cut guide == base top", b["zb"]["cut"] == b["anchor"]["z"][0],
          f"cut={b['zb']['cut']} anchor={b['anchor']['z'][0]}")
    check(f"{vu:g}um: keep guide clears the wood apex (curtain model)",
          b["zb"]["keep"] is not None
          and 0 <= b["zb"]["wood_top"] - b["zb"]["keep"]
          <= round(wb.KEEP_AIR_MARGIN_MM * 1000.0 / Z_STEP_UM) + 2,
          f"keep={b['zb']['keep']} wood_top={b['zb']['wood_top']}")
    check(f"{vu:g}um: adaptive scale uses the voxel size",
          b["scale"]["voxel_um"] == vu and b["scale"]["closing_px"] >= 1,
          str(b["scale"]))

# ---------------------------------------------------------------------------
# 2. physical-consistency sweep across resolutions
# ---------------------------------------------------------------------------
print("\n-- physical consistency sweep (same specimen, different voxels) --")
results = {}
for vu in (12.0, 25.0, 66.0, 120.0):
    b = run_bounds(vu)
    check(f"{vu:g}um: bounds returned", b is not None)
    if b is None:
        continue
    mm = FOV_MM / b["W"]
    results[vu] = {
        "x_mm": (b["x0"] * mm, (b["x1"] + 1) * mm),
        "y_mm": (b["y0"] * mm, (b["y1"] + 1) * mm),
        "keep_mm": b["zb"]["keep"] * (28.0 / N_SLICES),
        "cut_mm": b["zb"]["cut"] * (28.0 / N_SLICES),
    }

ref = results.get(12.0)
if ref:
    for vu, r in results.items():
        dx = max(abs(r["x_mm"][0] - ref["x_mm"][0]), abs(r["x_mm"][1] - ref["x_mm"][1]))
        dy = max(abs(r["y_mm"][0] - ref["y_mm"][0]), abs(r["y_mm"][1] - ref["y_mm"][1]))
        dz = max(abs(r["keep_mm"] - ref["keep_mm"]), abs(r["cut_mm"] - ref["cut_mm"]))
        check(f"{vu:g}um: X within 0.8 mm of 12um reference", dx < 0.8, f"dX={dx:.3f} mm")
        check(f"{vu:g}um: Y within 0.8 mm of 12um reference", dy < 0.8, f"dY={dy:.3f} mm")
        check(f"{vu:g}um: z-guides within 0.5 mm of 12um reference", dz < 0.5, f"dZ={dz:.3f} mm")

# ---------------------------------------------------------------------------
# 3. robustness edges
# ---------------------------------------------------------------------------
print("\n-- robustness edges --")
b = run_bounds(24.0)
check("no-anchor fallback: cut = wood bottom + 1", b is not None)
if b is not None:
    sag, cor = sag_cor_for(24.0)
    b2 = wb.wood_bounds(None, "syn", n_slices=N_SLICES, cut_from=CUT_FROM,
                        sag=sag, cor=cor, metal_hu=None,
                        track_z=(0, CUT_FROM - 1), voxel_um=24.0,
                        wood_hu=(WOOD_LO, WOOD_HI),
                        slice_provider=make_provider(24.0),
                        z_step_um=Z_STEP_UM)
    check("air-only mode still returns bounds", b2 is not None)
    if b2 is not None:
        check("air-only: no anchor recorded", not b2["anchor"]["ok"], str(b2["anchor"]))
        check("air-only: cut guide at/below wood bottom",
              b2["zb"]["cut"] >= b2["zb"]["wood_bottom"], str(b2["zb"]))
    b3 = wb.wood_bounds(None, "syn", n_slices=N_SLICES, cut_from=CUT_FROM,
                        sag=None, cor=None, metal_hu=METAL_HU,
                        track_z=(0, CUT_FROM - 1), voxel_um=24.0,
                        wood_hu=(WOOD_LO, WOOD_HI),
                        slice_provider=make_provider(24.0),
                        z_step_um=Z_STEP_UM)
    # graceful degradation: air-only bounds from the axial pool, no anchor
    check("missing ortho lines -> air-only degradation (no crash, no anchor)",
          b3 is None or (b3 is not None and not b3["anchor"]["ok"]),
          str(b3))

print(f"\n-- detector-model ladder (constant detector width, 1-100 um) --")

import time

DET_MM = 6.0                    # compact detector/world width (mm)
# >100 µm class included per directive: the code must not break on any
# voxel from 1 µm upward (150 µm rung exercises the coarse fallbacks).
LADDER_UM = (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 24.0, 33.0, 50.0, 66.0, 100.0, 150.0)
LADDER_WOOD = (1.5, 4.5)        # wood y/x span inside the compact FOV


def det_n(voxel_um: float) -> int:
    return max(8, int(round(DET_MM * 1000.0 / voxel_um)))


def render_det_slice(voxel_um: float, z: int) -> np.ndarray:
    """Axial slice in the compact world (1D-vector math: no full-size grids)."""
    n = det_n(voxel_um)
    step = DET_MM / n
    yr = np.arange(n, dtype=np.float32) * step
    z_mm = z * (28.0 / N_SLICES)
    img = np.full((n, n), -1000.0, np.float32)
    if z_mm >= BASE_TOP_MM:
        img[:] = 500.0
        return img
    if WOOD_TOP_MM <= z_mm < WOOD_BOTTOM_MM:
        wm = ((yr[:, None] >= LADDER_WOOD[0]) & (yr[:, None] <= LADDER_WOOD[1])
              & (yr[None, :] >= LADDER_WOOD[0]) & (yr[None, :] <= LADDER_WOOD[1]))
        img[wm] = -600.0
    return img


def det_ortho(voxel_um: float):
    """Sagittal/coronal stacks sized to the compact detector."""
    n = det_n(voxel_um)
    base_w = max(8, int(round(0.55 * n)))
    off = (n - base_w) // 2
    wseg = max(2, base_w // 8)
    sag = np.full((N_SLICES, n), -1000.0, np.float32)
    for z in range(N_SLICES):
        z_mm = z * (28.0 / N_SLICES)
        if z_mm >= BASE_TOP_MM:
            sag[z, off:off + base_w] = 500.0
        elif WOOD_TOP_MM <= z_mm < WOOD_BOTTOM_MM:
            sag[z, off + base_w // 4: off + base_w // 4 + wseg] = -600.0
    return sag, sag.copy()


def run_det_bounds(voxel_um: float) -> dict:
    sag, cor = det_ortho(voxel_um)
    return wb.wood_bounds(
        None, "syn", n_slices=N_SLICES, cut_from=CUT_FROM,
        sag=sag, cor=cor, metal_hu=METAL_HU,
        track_z=(0, CUT_FROM - 1), voxel_um=voxel_um,
        wood_hu=(WOOD_LO, WOOD_HI),
        slice_provider=lambda zs: {z: render_det_slice(voxel_um, z)
                                   for z in zs},
        z_step_um=Z_STEP_UM)


ref = None
import os
_ladder_env = os.environ.get("LADDER_UM")            # chunked runs: "1,2,3"
for vu in (tuple(float(x) for x in _ladder_env.split(","))
           if _ladder_env else LADDER_UM):
    t0 = time.perf_counter()
    b = run_det_bounds(vu)
    dt = time.perf_counter() - t0
    check(f"{vu:g}um det-ladder: bounds returned", b is not None)
    if b is None:
        continue
    print(f"    {vu:>5g} um: W={b['W']:>6} px  closing_px={b['scale']['closing_px']:>2}"
          f"  det {dt:5.1f}s")
    mm = DET_MM / b["W"]
    det = {
        "x_mm": (b["x0"] * mm, (b["x1"] + 1) * mm),
        "y_mm": (b["y0"] * mm, (b["y1"] + 1) * mm),
        "keep_mm": (b["zb"]["keep"] or 0) * (28.0 / N_SLICES),
        "cut_mm": b["zb"]["cut"] * (28.0 / N_SLICES),
    }
    if ref is None:
        ref = (vu, det)
        continue
    dx = max(abs(det["x_mm"][0] - ref[1]["x_mm"][0]),
             abs(det["x_mm"][1] - ref[1]["x_mm"][1]))
    dy = max(abs(det["y_mm"][0] - ref[1]["y_mm"][0]),
             abs(det["y_mm"][1] - ref[1]["y_mm"][1]))
    dz = max(abs(det["keep_mm"] - ref[1]["keep_mm"]),
             abs(det["cut_mm"] - ref[1]["cut_mm"]))
    check(f"{vu:g}um det-ladder: X within 0.5 mm of {ref[0]:g}um reference",
          dx < 0.5, f"dX={dx:.3f} mm")
    check(f"{vu:g}um det-ladder: Y within 0.5 mm of {ref[0]:g}um reference",
          dy < 0.5, f"dY={dy:.3f} mm")
    check(f"{vu:g}um det-ladder: z-guides within 0.5 mm of {ref[0]:g}um reference",
          dz < 0.5, f"dZ={dz:.3f} mm")

# the compute guards must actually engage below 6.25 um (150/24) —
# this is what keeps the 1-6 um rungs from costing minutes per slice
for vu in (1.0, 2.0, 3.0, 5.0):
    sc = wb.adaptive_scale(vu)
    check(f"{vu:g}um det-ladder: closing_px capped at {wb.CLOSING_PX_MAX}",
          sc["closing_px"] == wb.CLOSING_PX_MAX, str(sc))

print(f"\n{'ALL PASS' if not failures else 'FAILURES: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
