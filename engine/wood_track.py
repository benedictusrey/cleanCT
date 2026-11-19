#!/usr/bin/env python
"""wood_track.py - per-slice 2D tracking of the wood specimen ROI.

All connected-component and morphology operations dispatch through the
adaptive GPU backend (gpu_backend.py) when a CUDA GPU is present; the CPU
fallback uses scipy with identical structures, so results are the same.

Why per-slice?  Metal-deposit streaks and beam-hardening fog create
z-directional corridors of intermediate HU that merge the specimen with
neighbouring samples in any 3D connectivity analysis.  Within a single
slice such corridors rarely connect distinct solid objects, so a 2D
component walk - seeded on a clean mid-stack slice and propagated up/down
in z by footprint overlap - isolates the specimen robustly.

Robustness measures
-------------------
* Seed scan runs from the stack centre outward and takes the first slice
  with a large solid component that does not touch the image border
  (late-stack slices are fog-dominated and unusable for seeding).
* In fog slices the window component may swallow the whole FOV; the walk
  therefore matches the *previous footprint neighbourhood*: a candidate
  must overlap the previous footprint by at least ``min_overlap_frac``,
  and the new footprint is the candidate restricted to a small dilation
  of the previous footprint (prevents growth along fog corridors).
* The new footprint must not touch the image border and must not shrink
  below ``min_shrink_frac`` of the previous footprint - both conditions
  stop the walk instead of letting it drift onto debris or neighbours.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi

from gpu_backend import run_gpu_or_cpu

_CROSS = ndi.generate_binary_structure(2, 1)   # 4-connectivity in 2D


@dataclass
class SliceTrack:
    """Bounding envelope of the tracked specimen and tracking metadata."""
    seed_slice: int
    z0: int                       # inclusive
    z1: int                       # inclusive
    y0: int
    y1: int
    x0: int
    x1: int
    n_slices_tracked: int
    seed_bbox: tuple[int, int, int, int]
    seed_area: int
    walk_up_end: int              # first slice (from seed side) where walk stopped
    walk_down_end: int
    stop_reason_up: str
    stop_reason_down: str


def _window_mask(stripped: np.ndarray, i: int, wlo: float, whi: float,
                 erode: int, gpu=None) -> np.ndarray:
    sl = stripped[i]
    m = np.isfinite(sl) & (sl >= wlo) & (sl <= whi)

    def on_cpu() -> np.ndarray:
        out = ndi.binary_erosion(m, iterations=erode) if erode else m
        out = ndi.binary_opening(out, structure=_CROSS)
        return ndi.binary_closing(out, structure=_CROSS)

    def on_gpu() -> np.ndarray:
        out = gpu.binary_erosion(m, iterations=erode) if erode else m
        out = gpu.binary_opening(out)
        out = gpu.binary_closing(out)
        return gpu.to_cpu(out).astype(bool)

    return run_gpu_or_cpu(gpu, on_gpu, on_cpu)


def _components(m: np.ndarray, min_area: int, gpu=None,
                ) -> list[tuple[int, int, int, int, int, np.ndarray]]:
    """2D components of ``m`` -> (area, y0, y1, x0, x1, mask)."""
    def on_gpu():
        lab_dev, n_found = gpu.label_slice(gpu.to_gpu(m))
        lab_host = gpu.to_cpu(lab_dev)
        gpu.release()
        return lab_host, n_found

    def on_cpu():
        return ndi.label(m, structure=_CROSS)

    lab, n = run_gpu_or_cpu(gpu, on_gpu, on_cpu)
    out: list[tuple[int, int, int, int, int, np.ndarray]] = []
    if n == 0:
        return out
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    objs = ndi.find_objects(lab)
    for k, box in enumerate(objs, start=1):
        if box is None or sizes[k] < min_area:
            continue
        ysl, xsl = box
        out.append((int(sizes[k]), ysl.start, ysl.stop - 1,
                    xsl.start, xsl.stop - 1, lab == k))
    return out


def _touches_border(y0: int, y1: int, x0: int, x1: int, H: int, W: int) -> bool:
    return y0 == 0 or x0 == 0 or y1 == H - 1 or x1 == W - 1


def track_wood_by_slices(stripped: np.ndarray,
                         wood_hu_min: float = -910.0,
                         wood_hu_max: float = -300.0,
                         slice_erode: int = 1,
                         min_overlap_frac: float = 0.50,
                         min_shrink_frac: float = 0.40,
                         seed_min_area: int = 20_000,
                         min_area: int = 2_000,
                         footprint_dilate: int = 2,
                         seed_slice: int | None = None,
                         exclude_border: bool = True,
                         verbose: bool = False,
                         gpu=None,
                         ) -> tuple[SliceTrack,
                                    list[tuple[int, int, int, int] | None]]:
    """Track the specimen slice-by-slice; returns (SliceTrack, footprints).

    footprints[i] = (y0, y1, x0, x1) for every tracked slice, else None.
    """
    nz, H, W = stripped.shape
    st3 = ndi.generate_binary_structure(2, 1)

    def comps_of(i: int):
        return _components(_window_mask(stripped, i, wood_hu_min,
                                        wood_hu_max, slice_erode, gpu),
                           min_area, gpu)

    # ---- seed scan: centre outward -----------------------------------------
    center = nz // 2
    if seed_slice is None:
        order = sorted(range(nz), key=lambda i: abs(i - center))
    else:
        order = [seed_slice]
    seed_comps: list = []
    seed_pick = None
    for i in order:
        cands = [c for c in comps_of(i)
                 if (not exclude_border
                     or not _touches_border(c[1], c[2], c[3], c[4], H, W))
                 and c[0] >= seed_min_area]
        if cands:
            cy, cx = (H - 1) / 2.0, (W - 1) / 2.0
            def centrality(c):
                ys, xs = np.nonzero(c[5])
                return abs(ys.mean() - cy) + abs(xs.mean() - cx)
            seed_pick = (i, min(cands, key=centrality))
            break
    if seed_pick is None:
        raise RuntimeError("no clean seed slice found (all slices fogged or "
                           "border-locked); inspect the scan")
    seed_slice, seed = seed_pick
    _, sy0, sy1, sx0, sx1, seed_mask = seed
    if verbose:
        print(f"  seed slice {seed_slice}: bbox y {sy0}..{sy1} "
              f"x {sx0}..{sx1}, area {seed[0]}")

    footprints: list[tuple[int, int, int, int] | None] = [None] * nz
    footprints[seed_slice] = (sy0, sy1, sx0, sx1)
    n_tracked = 1

    def step(i: int, ref: np.ndarray):
        """One walk step; returns (footprint, mask, reason)."""
        ref_area = int(ref.sum())

        def on_gpu():
            out = gpu.to_cpu(gpu.binary_dilation(gpu.to_gpu(ref),
                                                 iterations=footprint_dilate))
            gpu.release()
            return out

        def on_cpu():
            return ndi.binary_dilation(ref, structure=st3,
                                       iterations=footprint_dilate)

        allow = run_gpu_or_cpu(gpu, on_gpu, on_cpu)
        best = None
        best_key = (-1, -1)
        for (area, y0, y1, x0, x1, mask) in comps_of(i):
            ov = int((mask & ref).sum())
            if ref_area == 0 or ov / ref_area < min_overlap_frac:
                continue
            restricted = mask & allow
            ra = int(restricted.sum())
            if ra < min_shrink_frac * ref_area:
                continue
            rr = np.nonzero(restricted)
            if rr[0].size == 0:
                continue
            ry0, ry1 = int(rr[0].min()), int(rr[0].max())
            rx0, rx1 = int(rr[1].min()), int(rr[1].max())
            if exclude_border and _touches_border(ry0, ry1, rx0, rx1, H, W):
                continue
            key = (ov, ra)
            if key > best_key:
                best_key = key
                best = ((ry0, ry1, rx0, rx1), restricted)
        if best is None:
            return None, None, "no valid component"
        return best[0], best[1], "tracked"

    def walk(direction: int):
        nonlocal n_tracked
        ref = seed_mask.copy()
        i = seed_slice + direction
        end = seed_slice
        at_edge = ((direction > 0 and seed_slice == nz - 1)
                   or (direction < 0 and seed_slice == 0))
        reason = "reached stack edge" if at_edge else "tracked"
        while 0 <= i < nz:
            fp, mask, why = step(i, ref)
            if fp is None:
                reason = f"stopped at slice {i}: {why}"
                break
            footprints[i] = fp
            ref = mask
            end = i
            n_tracked += 1
            i += direction
        return end, reason

    up_end, up_reason = walk(+1)
    down_end, down_reason = walk(-1)

    tracked = [b for b in footprints if b is not None]
    z_tracked = [i for i, b in enumerate(footprints) if b is not None]
    track = SliceTrack(
        seed_slice=int(seed_slice),
        z0=min(z_tracked), z1=max(z_tracked),
        y0=min(b[0] for b in tracked), y1=max(b[1] for b in tracked),
        x0=min(b[2] for b in tracked), x1=max(b[3] for b in tracked),
        n_slices_tracked=n_tracked,
        seed_bbox=(sy0, sy1, sx0, sx1),
        seed_area=int(seed[0]),
        walk_up_end=int(up_end),
        walk_down_end=int(down_end),
        stop_reason_up=up_reason,
        stop_reason_down=down_reason,
    )
    if verbose:
        print(f"  tracked {n_tracked} slices: z {track.z0}..{track.z1}; "
              f"up stop: {up_reason}; down stop: {down_reason}")
        print(f"  envelope y {track.y0}..{track.y1} x {track.x0}..{track.x1}")
    return track, footprints


def crop_by_footprints(stripped: np.ndarray,
                       footprints: list[tuple[int, int, int, int] | None],
                       pad: int = 8,
                       ) -> tuple[np.ndarray, tuple[int, int, int, int, int, int]]:
    """Crop the stripped volume to the tracked bbox (+padding)."""
    tracked = [i for i, b in enumerate(footprints) if b is not None]
    if not tracked:
        raise RuntimeError("no tracked slices to crop")
    b = [fp for fp in footprints if fp is not None]
    z0 = max(0, min(tracked) - pad)
    z1 = min(stripped.shape[0] - 1, max(tracked) + pad)
    y0 = max(0, min(x[0] for x in b) - pad)
    y1 = min(stripped.shape[1] - 1, max(x[1] for x in b) + pad)
    x0 = max(0, min(x[2] for x in b) - pad)
    x1 = min(stripped.shape[2] - 1, max(x[3] for x in b) + pad)
    return stripped[z0:z1 + 1, y0:y1 + 1, x0:x1 + 1].copy(), \
        (z0, z1, y0, y1, x0, x1)
