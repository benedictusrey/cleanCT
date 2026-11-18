"""Wood-bounds regression suite: lateral projection envelope + top/bottom
invariants (audits 0AE/0AF).

Synthetic scale-invariance harness, two scenarios:

1. a rectangular wood block with a sparse frame-wide fog grid in the dry
   top region (0AE case - the fog must not stretch the Left/Right lines);
2. an OVEN-DRY reproduction (0AF case): wood HU at the window floor, a
   dense fog blanket (with pixels inside the old "core" band) that fills
   the whole FOV, and a block itself filling >60% of the FOV so the
   fog-blanket fill test cannot identify the fog slices either.

In both cases the edge-band-gated projections with the Otsu knee must
hug the block outline while the top/bottom z logic keeps its calibrated
semantics.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.paths import ensure_engine_on_path  # noqa: E402

ensure_engine_on_path()     # the isolated engine copy (CLEANCT_ENGINE) when set

import tomograph as tg
from core.wood_bounds import wood_bounds

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


class _FakeDS:
    key = "syn"
    source_kind = "dicom"


def make_reader(H: int, W: int, n: int, block, wood_hu=-600.0, air=-1000.0):
    """Synthetic slice provider: a wood block with a frame-wide fog band
    around it in the top region; the block keeps its true outline."""
    y0, y1, x0, x1 = block

    def read(zs):
        out = {}
        for z in zs:
            sl = np.full((H, W), air, np.float32)
            # the block: wood from the window start to the bottom
            if z < n:
                sl[y0:y1, x0:x1] = wood_hu
            # fog: a frame-wide band slightly above the window floor, in
            # the top quarter (the dry region of the reported specimen)
            if z < n // 4:
                sl[:, :] = np.where(
                    np.arange(W)[None, :] % 7 == 0, sl, -985.0)
            out[int(z)] = sl
        return out

    return read


def main() -> int:
    H, W, n = 400, 300, 200
    block = (50, 350, 40, 260)          # true wood outline (y, x)
    fog_floor = (-990.0, -500.0)
    b = wood_bounds(
        None, "syn", n_slices=n, cut_from=n,
        sag=None, cor=None, metal_hu=0.0,
        track_z=None, voxel_um=24.852,
        wood_hu=fog_floor,
        slice_provider=make_slice(),
        det_anchor=None, det_cut=None, z_step_um=24.852)
    if b is None:
        check("bounds computed on the synthetic fog case", False)
        return 1
    zb = b["zb"]
    margins = b["margins"]
    check("wood top/bottom keep the calibrated semantics",
          zb["wood_top"] == 0 and zb["wood_bottom"] <= n - 1,
          str(zb))

    y_lo, y_hi = margins["y"]
    x_lo, x_hi = margins["x"]
    # margins are edge distances: [lo, H-1-hi] / [lo, W-1-hi]
    fy0, fy1 = y_lo / H, y_hi / H
    fx0, fx1 = x_lo / W, x_hi / W
    # the fog must not stretch the lateral envelope beyond the block
    # (block x 40..259 of 300 -> ~13.3%; y 50..379 of 400 -> 12.5%/5%)
    check("left line hugs the wood (no fog-frame margin)",
          0.10 <= fx0 <= 0.18, f"x_lo={fx0:.1%}")
    check("right line hugs the wood",
          0.10 <= fx1 <= 0.20, f"x_hi={fx1:.1%}")
    check("y envelope hugs the block",
          0.10 <= fy0 <= 0.20 and fy1 <= 0.20, f"y={fy0:.1%}/{fy1:.1%}")

    # the envelope equals the block outline within the closing radius
    check("x envelope matches the block outline",
          abs(x_lo - 40) <= 6 and abs(x_hi - (W - 1 - 259)) <= 6,
          f"x margins={margins['x']}")
    check("y envelope matches the block outline",
          abs(y_lo - 50) <= 6 and abs(y_hi - (H - 1 - 379)) <= 6,
          f"y margins={margins['y']}")

    # ---- scenario 2 (audit 0AF): oven-dry specimen ---------------------
    # Wood HU sits AT the window floor and the fog blanket contains
    # pixels inside the old "core" band (-892..-500), while the block
    # itself fills >60 % of the FOV.  The 0AE core projection failed
    # exactly here (wood contributed nothing to the core, fog dominated
    # and dragged the envelope full-frame).  The edge-band gate must
    # exclude the fog slices geometrically and hug the block.
    H2, W2, n2 = 300, 300, 120
    block2 = (30, 270, 30, 270)
    od = wood_bounds(
        None, "syn_od", n_slices=n2, cut_from=n2,
        sag=None, cor=None, metal_hu=0.0,
        track_z=None, voxel_um=24.852,
        wood_hu=fog_floor,
        slice_provider=make_od_slice(),
        det_anchor=None, det_cut=None, z_step_um=24.852)
    if od is None:
        check("bounds computed on the oven-dry dense-blanket case", False)
    else:
        m2 = od["margins"]
        zb2 = od["zb"]
        check("oven-dry wood top/bottom keep the calibrated semantics",
              zb2["wood_top"] == 0 and zb2["wood_bottom"] <= n2 - 1,
              str(zb2))
        y0m, y1m = m2["y"]
        x0m, x1m = m2["x"]
        check("oven-dry left line hugs the wood (fog not adopted)",
              abs(x0m - block2[2]) <= 6, f"x_lo margin={x0m}")
        check("oven-dry right line hugs the wood",
              abs(x1m - (W2 - 1 - block2[3])) <= 6, f"x_hi margin={x1m}")
        check("oven-dry y envelope hugs the block",
              abs(y0m - block2[0]) <= 6
              and abs(y1m - (H2 - 1 - block2[1])) <= 6,
              f"y margins={m2['y']}")
        check("oven-dry envelope is NOT full-frame",
              x0m > 10 and y0m > 10 and x1m > 10 and y1m > 10,
              f"margins={m2}")
        check("oven-dry full-frame fraction test misfires (block > 60 %)",
              (block2[1] - block2[0]) * (block2[3] - block2[2])
              / float(H2 * W2) > 0.60, "the case must exercise that gate too")

    return 1 if FAILS else 0


def make_slice():
    """Provider over a rectangular block with a frame-wide fog blanket."""
    H, W, n = 400, 300, 200
    y0, y1, x0, x1 = 50, 380, 40, 260

    def provide(zs):
        out = {}
        for z in zs:
            sl = np.full((H, W), -1000.0, np.float32)
            sl[y0:y1, x0:x1] = -600.0
            if z < n // 4:                      # fog in the dry top region
                fog = (np.arange(H)[:, None] % 11 == 0) | \
                      (np.arange(W)[None, :] % 13 == 0)
                sl[fog] = -985.0
            out[int(z)] = sl
        return out

    return provide


def make_od_slice():
    """Oven-dry reproduction (audit 0AF): wood HU at the window floor, a
    dense fog blanket whose pixels also land in the old core band, and a
    block that fills >60 % of the FOV (so the fog-blanket fill test
    cannot identify the fog slices either)."""
    H, W, n = 300, 300, 120
    y0, y1, x0, x1 = 30, 270, 30, 270

    def provide(zs):
        out = {}
        for z in zs:
            sl = np.full((H, W), -1000.0, np.float32)
            sl[y0:y1, x0:x1] = -970.0            # dry wood at the floor
            if z < n // 5 or z >= n - n // 5:    # dense fog top and bottom
                sl[:, :] = -975.0
                sl[::3, :] = -820.0              # old core band (-892..-500)
            out[int(z)] = sl
        return out

    return provide


if __name__ == "__main__":
    code = main()
    print("RESULT:", "ALL PASS" if code == 0 else f"FAILURES: {FAILS}")
    sys.exit(code)
