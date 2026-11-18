"""Offline unit tests for the wood_bounds v2 detection rules (no GPU/DICOM).

Covers the hardened rules added for the metal-first / air-second redesign:

1. Metal quorum (priority 1): a base slab must be seen on >= ORTHO_QUORUM
   independent mid-columns; a thin strap pin — visible on ONE column only —
   must NOT anchor, on either the rank-3 quorum path or the legacy rank-2
   path, at any of several resolutions.
2. Detector-anchor fusion: with ``det_anchor`` given, the base is the slab
   run reaching the detector's seed (validated detection reproduced); a
   strap run higher up never steals the base.
3. Top-air clearance gate (priority 2, Keep line): fog HUGGING the wood
   top (no air between) defers (keep None); clear-air top edges adopt
   the wood top; a SEPARATED fog island above the wood is bypassed and
   the Keep line rides the main wood run (contiguous edge walk).
4. Air witness agreement: lateral bounds never EXPAND because of the
   witness; on agreement the ortho margin can only refine (tighten).
5. Component size gate: tiny specks outside the wood cannot inflate the
   envelope at any resolution.

Air evidence is injected through ``slice_provider``; ortho stacks are
synthetic — nothing touches the real datasets.
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
# synthetic world (physical coordinates, mm)
# ---------------------------------------------------------------------------
FOV_MM = 28.0
N_SLICES = 300
CUT_FROM = 270
BASE_TOP_MM = 26.0
WOOD_TOP_MM = 1.2
WOOD_BOTTOM_MM = 24.0
WOOD_Y_MM = (6.0, 22.0)
WOOD_X_MM = (7.0, 21.0)
AIR_HU, WOOD_LO, WOOD_HI, METAL_HU = -900.0, -990.0, -500.0, 0.0


def render_slice(voxel_um: float, z: int, *, fog: bool = False,
                 fog_top: bool = False, speck: bool = False) -> np.ndarray:
    n = max(8, int(round(FOV_MM * 1000.0 / voxel_um)))
    mm_per_px = FOV_MM / n
    yy, xx = np.mgrid[0:n, 0:n]
    y_mm = yy * mm_per_px
    x_mm = xx * mm_per_px
    z_mm = z * (28.0 / N_SLICES)
    img = np.full((n, n), -1000.0, np.float32)
    if z_mm >= BASE_TOP_MM:
        img[:] = 500.0
        return img
    wm = ((y_mm >= WOOD_Y_MM[0]) & (y_mm <= WOOD_Y_MM[1])
          & (x_mm >= WOOD_X_MM[0]) & (x_mm <= WOOD_X_MM[1])
          & (z_mm >= WOOD_TOP_MM) & (z_mm < WOOD_BOTTOM_MM))
    img[wm] = -600.0
    if fog:                      # fog BLANKET HUGGING the wood top: fills
        if 0.2 <= z_mm < 1.35:   # the whole FOV and runs into the wood
            img[:, :] = -700.0   # with no air between (the defer case; a
                                 # SEPARATED fog island is the gap test)
    if fog_top:                  # fog reaching the VOLUME TOP: no clear
        if z_mm < 0.2:           # air above the curtain exists anywhere
            img[:, :] = -700.0
    if speck:                    # tiny 2x2 dense speck far from the wood
        if abs(z_mm - 12.0) < 0.5:
            y0 = int(1.0 / mm_per_px)
            x0 = int(1.0 / mm_per_px)
            img[y0:y0 + 2, x0:x0 + 2] = -600.0
    return img


def make_provider(voxel_um: float, **kw) -> wb.RefProvider:
    def provider(zs: list[int]) -> dict[int, np.ndarray]:
        return {z: render_slice(voxel_um, z, **kw) for z in zs}
    return provider


def make_ortho(voxel_um: float, *, rank3: bool = True, strap: bool = False,
               fog: bool = False):
    """Sagittal/coronal stacks.

    rank3: (n, n_cols, profile) multi-column band; else legacy (n, profile).
    strap: a thin metal pin (~4% of width, under the 12% slab gate) spanning
           slices 30..33 on ONE column of the band.
    fog:   the top fog band is present in the ortho stacks too.
    """
    n = max(8, int(round(FOV_MM * 1000.0 / voxel_um)))
    ncols = 5
    base_w = max(8, int(round(0.55 * n)))
    off = (n - base_w) // 2
    wood_w = max(2, int(round(0.45 * n)))
    woff = (n - wood_w) // 2
    stack_shape = (N_SLICES, ncols, n) if rank3 else (N_SLICES, n)
    sag = np.full(stack_shape, -1000.0, np.float32)
    for z in range(N_SLICES):
        z_mm = z * (28.0 / N_SLICES)
        if z_mm >= BASE_TOP_MM:
            sl = np.full((ncols, n) if rank3 else (n,), -1000.0, np.float32)
            sl[..., off:off + base_w] = 500.0
            sag[z] = sl
        elif WOOD_TOP_MM <= z_mm < WOOD_BOTTOM_MM:
            sl = np.full((ncols, n) if rank3 else (n,), -1000.0, np.float32)
            sl[..., woff:woff + wood_w] = -600.0
            sag[z] = sl
        elif fog and 0.2 <= z_mm < 1.35:
            sag[z] = -700.0
    if strap:
        # thin pin on the FIRST band column only, ~4% of width: never a slab
        pin_w = max(1, int(round(0.04 * n)))
        for z in range(30, 34):
            if rank3:
                sag[z, 0, off:off + pin_w] = 500.0
            else:
                sag[z, off:off + pin_w] = 500.0
    return sag, sag.copy()


Z_STEP_MM = 28.0 / N_SLICES            # synthetic slice thickness (mm)


def run_bounds(voxel_um: float, **kw):
    rank3 = kw.pop("rank3", True)
    strap = kw.pop("strap", False)
    fog = kw.pop("fog", False)
    sag, cor = make_ortho(voxel_um, rank3=rank3, strap=strap, fog=fog)
    return wb.wood_bounds(
        None, "syn", n_slices=N_SLICES, cut_from=CUT_FROM,
        sag=sag, cor=cor, metal_hu=METAL_HU,
        track_z=(0, CUT_FROM - 1), voxel_um=voxel_um,
        wood_hu=(WOOD_LO, WOOD_HI),
        slice_provider=make_provider(voxel_um, fog=fog, **kw),
        z_step_um=Z_STEP_MM * 1000.0)


# ---------------------------------------------------------------------------
# 1. metal quorum: strap pin can never anchor
# ---------------------------------------------------------------------------
print("\n-- metal quorum (priority 1) --")
for vu in (12.0, 25.0, 66.0, 120.0):
    for rank3 in (True, False):
        b = run_bounds(vu, rank3=rank3, strap=True)
        ok = (b is not None and b["anchor"]["ok"]
              and b["anchor"]["z"][0] * (28.0 / N_SLICES) >= BASE_TOP_MM - 0.5)
        check(f"{vu:g}um rank{'3' if rank3 else '2'}: strap never anchors, base does",
              ok, str(b and b["anchor"]))

# rank-3 quorum really engages (a single-column slab is rejected)
sag3, _ = make_ortho(25.0, rank3=True)
n3 = sag3.shape[0]
single_col_slab = sag3.copy()
base_only_col0 = np.full_like(single_col_slab, -1000.0)
w = single_col_slab.shape[2]
bw = max(8, int(round(0.55 * w)))
base_only_col0[:, 0, (w - bw) // 2:(w - bw) // 2 + bw] = 500.0
sup_all = wb._solid_metal(sag3, METAL_HU)
sup_one = wb._solid_metal(base_only_col0, METAL_HU)
check("quorum: base on all columns is supported", bool(sup_all[280]))
check("quorum: base on ONE column is rejected", not bool(sup_one[280]))

# ---------------------------------------------------------------------------
# 2. detector-anchor fusion
# ---------------------------------------------------------------------------
print("\n-- detector-anchor fusion --")
sag, cor = make_ortho(25.0, rank3=True, strap=True)
# strap occupies slices 30..33; the detector's anchor seed is the base top
# (synthetic base starts at z=279 → 26.0 mm + one slice)
b = wb.wood_bounds(
    None, "syn", n_slices=N_SLICES, cut_from=CUT_FROM, sag=sag, cor=cor,
    metal_hu=METAL_HU, track_z=(0, CUT_FROM - 1), voxel_um=25.0,
    wood_hu=(WOOD_LO, WOOD_HI), slice_provider=make_provider(25.0),
    det_anchor=279)
check("det_anchor: base run reaches the detector seed",
      b is not None and b["anchor"]["z"][0] == 279, str(b and b["anchor"]))
check("det_anchor: strap run never chosen",
      b is not None and b["anchor"]["z"][0] not in (30, 31, 32, 33),
      str(b and b["anchor"]))
check("det_anchor: source recorded as detector-fused",
      b is not None and b["anchor"]["source"] == "detector-fused",
      str(b and b["anchor"]["source"]))
b2 = wb.wood_bounds(
    None, "syn", n_slices=N_SLICES, cut_from=CUT_FROM, sag=sag, cor=cor,
    metal_hu=METAL_HU, track_z=(0, CUT_FROM - 1), voxel_um=25.0,
    wood_hu=(WOOD_LO, WOOD_HI), slice_provider=make_provider(25.0))
check("no det_anchor: source is ortho-quorum",
      b2 is not None and b2["anchor"]["source"] == "ortho-quorum",
      str(b2 and b2["anchor"]["source"]))

# det_cut precedence: the cut guide is the halo ONSET the pipeline cuts at
# (the physical metal-threshold line), not the base top
b3 = wb.wood_bounds(
    None, "syn", n_slices=N_SLICES, cut_from=CUT_FROM, sag=sag, cor=cor,
    metal_hu=METAL_HU, track_z=(0, CUT_FROM - 1), voxel_um=25.0,
    wood_hu=(WOOD_LO, WOOD_HI), slice_provider=make_provider(25.0),
    det_anchor=279, det_cut=262)
check("det_cut: cut guide == detector halo onset (not the base top)",
      b3 is not None and b3["zb"]["cut"] == 262, str(b3 and b3["zb"]))
check("det_cut: anchor evidence still carries the base top",
      b3 is not None and b3["anchor"]["z"][0] == 279, str(b3 and b3["anchor"]))

# ---------------------------------------------------------------------------
# 3. top-air clearance gate (Keep line)
# ---------------------------------------------------------------------------
print("\n-- top-air clearance gate (priority 2) --")
b_clean = run_bounds(25.0, rank3=True)
check("clear top air: keep line clears the wood apex (curtain model)",
      b_clean is not None and b_clean["zb"]["keep"] is not None
      and 0 <= b_clean["zb"]["wood_top"] - b_clean["zb"]["keep"]
      <= round(wb.KEEP_AIR_MARGIN_MM * 1000.0 / (Z_STEP_MM * 1000.0)) + 2,
      str(b_clean and b_clean["zb"]))
check("clear top air: line sits in verified clear air (top_ok)",
      b_clean is not None and b_clean["zb"]["top_ok"] is True,
      str(b_clean and b_clean["zb"]))
b_fog = run_bounds(25.0, rank3=True, fog=True)
# fog HUGS the wood top (0.2..1.35 mm): the curtain walk must place the
# line ABOVE the fog band (in the clear air over it), not at the apex
curt_mm = 0.2
marg = max(1, int(round(wb.KEEP_AIR_MARGIN_MM * 1000.0
                        / (Z_STEP_MM * 1000.0))))
exp_keep = max(0, int(round(curt_mm / Z_STEP_MM)) - marg)
check("fog hugging the wood top: keep line clears the fog band",
      b_fog is not None and b_fog["zb"]["keep"] == exp_keep,
      str(b_fog and b_fog["zb"]) + f" expected {exp_keep}")
check("fog hugging the wood top: line sits in verified clear air",
      b_fog is not None and b_fog["zb"]["top_ok"] is True,
      str(b_fog and b_fog["zb"]))
# curtain reaching the VOLUME TOP: no clear air above it exists — the
# only honest answer is to defer (keep None, evidence flag recorded)
b_ftop = run_bounds(25.0, rank3=True, fog=True, fog_top=True)
check("curtain reaches the volume top: keep line deferred (None)",
      b_ftop is not None and b_ftop["zb"]["keep"] is None,
      str(b_ftop and b_ftop["zb"]))
check("curtain reaches the volume top: deferral recorded in evidence",
      b_ftop is not None and bool((b_ftop["evidence"] or {}).get("fog_defer")),
      str(b_ftop and (b_ftop["evidence"] or {}).get("fog_defer")))

# fog ISLAND above the wood (separate presence run): the Keep line must
# ride the MAIN wood run, not the island (gap-tolerant run selection)
def make_provider_gap(vu: float) -> wb.RefProvider:
    def provider(zs: list[int]) -> dict[int, np.ndarray]:
        out = {}
        for z in zs:
            img = render_slice(vu, z)
            z_mm = z * (28.0 / N_SLICES)
            if 0.3 <= z_mm < 1.0:            # island well ABOVE the wood top
                n = img.shape[0]
                mm = FOV_MM / n
                yy, xx = np.mgrid[0:n, 0:n]
                isl = ((yy * mm >= 4.0) & (yy * mm <= 6.0)
                       & (xx * mm >= 8.0) & (xx * mm <= 20.0))
                img[isl] = -600.0
            out[z] = img
        return out
    return provider

sag_g, cor_g = make_ortho(25.0, rank3=True)
b_gap = wb.wood_bounds(
    None, "syn", n_slices=N_SLICES, cut_from=CUT_FROM, sag=sag_g, cor=cor_g,
    metal_hu=METAL_HU, track_z=(0, CUT_FROM - 1), voxel_um=25.0,
    wood_hu=(WOOD_LO, WOOD_HI), slice_provider=make_provider_gap(25.0),
    z_step_um=Z_STEP_MM * 1000.0)
check("fog island above the wood: keep line clears the ISLAND",
      b_gap is not None and b_gap["zb"]["keep"] == max(0, 4 - marg),
      str(b_gap and b_gap["zb"]) + f" expected {max(0, 4 - marg)}")

# ---------------------------------------------------------------------------
# 4. air witnesses: envelope can only tighten or stay
# ---------------------------------------------------------------------------
print("\n-- witness agreement / conservative fusion --")
for vu in (25.0, 66.0):
    b = run_bounds(vu, rank3=True)
    if b is None:
        check(f"{vu:g}um: bounds returned", False)
        continue
    mm = FOV_MM / b["W"]
    x0m, x1m = b["x0"] * mm, (b["x1"] + 1) * mm
    check(f"{vu:g}um: witness fusion keeps the physical wood bounds",
          abs(x0m - WOOD_X_MM[0]) < 0.6 and abs(x1m - WOOD_X_MM[1]) < 0.6,
          f"x {x0m:.2f}..{x1m:.2f} mm")
    ev = b["evidence"]["lateral"]
    check(f"{vu:g}um: witness flags recorded",
          "y_defer" in ev and "x_defer" in ev, str(ev))

# ---------------------------------------------------------------------------
# 5. component size gate
# ---------------------------------------------------------------------------
print("\n-- component size gate --")
b_speck = run_bounds(25.0, rank3=True, speck=True)
b_plain = run_bounds(25.0, rank3=True)
check("specks outside the wood do not inflate the envelope",
      b_speck is not None and b_plain is not None
      and b_speck["x0"] == b_plain["x0"] and b_speck["y0"] == b_plain["y0"]
      and b_speck["x1"] == b_plain["x1"] and b_speck["y1"] == b_plain["y1"],
      f"speck={b_speck and (b_speck['x0'], b_speck['y0'], b_speck['x1'], b_speck['y1'])} "
      f"plain={b_plain and (b_plain['x0'], b_plain['y0'], b_plain['x1'], b_plain['y1'])}")

# ---------------------------------------------------------------------------
# 6. adaptive scale sanity
# ---------------------------------------------------------------------------
print("\n-- adaptive scale --")
sc24 = wb.adaptive_scale(24.85)
sc66 = wb.adaptive_scale(66.21)
check("pool covers the same physical window at any resolution",
      sc24["pool"] == 32 and sc66["pool"] == 32,
      f"24um pool {sc24['pool']} vs 66um pool {sc66['pool']}")
check("air min-area in px scales with the voxel area",
      sc66["air_min_area_px"] < sc24["air_min_area_px"],
      f"24um {sc24['air_min_area_px']} px vs 66um {sc66['air_min_area_px']} px")
check("air min-area is ~0.15 mm^2 at both resolutions",
      abs(sc24["air_min_area_px"] * (24.85 ** 2) * 1e-6 - 0.15) < 0.01
      and abs(sc66["air_min_area_px"] * (66.21 ** 2) * 1e-6 - 0.15) < 0.02,
      f"24um {sc24['air_min_area_px'] * 24.85**2 * 1e-6:.3f} mm2, "
      f"66um {sc66['air_min_area_px'] * 66.21**2 * 1e-6:.3f} mm2")

print(f"\n{'ALL PASS' if not failures else 'FAILURES: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
