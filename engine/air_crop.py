#!/usr/bin/env python
"""air_crop.py - air-margin based tight cropping of the wood ROI.

Idea: the same air that outlines the metal platform also outlines the wood
specimen.  On the stripped volume (platform slab already voided with NaN
below the cut) air is anything at or below ``air_hu`` HU (~ -900).  Rows and
columns of the sample XY field whose occupancy is essentially all air are
outside the specimen; trimming those margins crops the delivery tightly to
the wood in every plane (XY, XZ and YZ).

Design (kept deliberately simple, robust and conservative):

* ``edge-run`` margins - a margin is trimmed only where the rows/columns
  **adjacent to the FOV border** are (nearly) pure air.  We never cut inside
  the object, so the result can never exclude wood.
* per-axis arbitration - an axis is trimmed only if a real air margin of at
  least ``min_margin_px`` exists there; when the wood touches the FOV edge
  on an axis that axis keeps the tracker's coordinate.
* subset guarantee - the caller passes the tracker envelope; every returned
  coordinate is clamped inside it, so the air envelope is always a subset of
  the tracker envelope (delivery can only get tighter, never wrong).
* guarded - degenerate results (empty, or shrinking below a sane fraction of
  the FOV) are refused and the caller falls back to the tracker envelope.

Pure NumPy over the host volume (no new dependency); the volume is accessed
slice-wise so no extra full copy is made.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi

_FILL = ndi.generate_binary_structure(2, 2)     # 8-connectivity for closing


@dataclass
class AirEnvelope:
    """Detected air envelope and diagnostics (all inclusive, z, y, x)."""
    ok: bool
    z0: int
    z1: int
    y0: int
    y1: int
    x0: int
    x1: int
    method: str = "air-envelope"
    margins: dict | None = None       # per-axis air margins detected
    fallback_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "method": self.method,
            "bbox_zyx": [self.z0, self.z1, self.y0, self.y1,
                         self.x0, self.x1],
            "margins": self.margins or {},
            "fallback_reason": self.fallback_reason,
        }


def _slice_object_mask(sl: np.ndarray, air_hu: float) -> np.ndarray:
    """Object mask of one axial slice: non-air, holes filled."""
    obj = np.isfinite(sl) & (sl > air_hu)
    if not obj.any():
        return obj
    obj = ndi.binary_closing(obj, structure=_FILL)
    return ndi.binary_fill_holes(obj)


def detect_air_envelope(stripped: np.ndarray, *,
                        z0: int, z1: int,
                        y0: int, y1: int,
                        x0: int, x1: int,
                        air_hu: float = -900.0,
                        air_frac: float = 0.98,
                        min_margin_px: int = 2,
                        min_keep_frac: float = 0.05,
                        ) -> AirEnvelope:
    """Tighten the given (z, y, x) envelope to the wood using air margins.

    Parameters map 1:1 to the pipeline Config: ``air_hu`` (air threshold),
    ``air_frac`` (fraction of a border row/column that must be air for the
    margin to be trimmed), ``min_margin_px`` (an axis moves only when at
    least this many air columns/rows are behind the current bound).

    The tracker envelope is an upper bound: the result never exceeds it and
    never becomes degenerate (guards below); on any guard trip ``ok=False``
    with a reason is returned so the caller can keep the tracker envelope.
    """
    nz, H, W = stripped.shape
    fail = lambda reason: AirEnvelope(False, z0, z1, y0, y1, x0, x1,
                                      method="tracker",
                                      fallback_reason=reason)  # noqa: E731

    z0, z1 = max(0, int(z0)), min(nz - 1, int(z1))
    if z1 < z0:
        return fail(f"empty z range {z0}..{z1}")

    # ---- per-slice object masks over the tracked z-range -------------------
    # masks_by_z covers EVERY slice of the range (None = pure-air slice) so
    # z arithmetic stays aligned; obj_masks (non-empty) feed the XY margins.
    masks_by_z: list[np.ndarray | None] = []
    for z in range(z0, z1 + 1):
        m = _slice_object_mask(stripped[z], air_hu)
        masks_by_z.append(m if m.any() else None)
    obj_masks = [m for m in masks_by_z if m is not None]
    if not obj_masks:
        return fail("no object voxels above the air threshold in the "
                    "tracked range")

    # ---- occupancy projections -------------------------------------------
    # A border row/column/slice is trimmable when its object presence is
    # below a small tolerance, i.e. it is essentially pure air.  The
    # tolerance derives from ``air_frac`` (the fraction of the line that
    # must be air): air_frac=0.98 allows <=2% object pixels (noise),
    # air_frac=1.0 demands perfectly pure air.
    tol_y = max(1, int(round((1.0 - air_frac) * W)))   # object px per row
    tol_x = max(1, int(round((1.0 - air_frac) * H)))   # object px per col
    tol_z = max(1, int(round((1.0 - air_frac) * H * W)))

    row_dens = np.stack([m.sum(axis=1) for m in obj_masks])     # (n, H)
    col_dens = np.stack([m.sum(axis=0) for m in obj_masks])     # (n, W)
    row_obj = (row_dens >= tol_y).any(axis=0)                   # (H,)
    col_obj = (col_dens >= tol_x).any(axis=0)                   # (W,)
    y_nz = np.nonzero(row_obj)[0]
    x_nz = np.nonzero(col_obj)[0]
    if y_nz.size == 0 or x_nz.size == 0:
        return fail("no object rows/columns above the air tolerance")
    y_first, y_last = int(y_nz[0]), int(y_nz[-1])
    x_first, x_last = int(x_nz[0]), int(x_nz[-1])

    # air margins measured *inside the tracker bbox* (never expand it)
    y_lo, y_hi = max(0, y_first - y0), max(0, y1 - y_last)
    x_lo, x_hi = max(0, x_first - x0), max(0, x1 - x_last)

    # ---- Z: essentially-empty slices at the range borders -----------------
    z_dens = np.array([0 if m is None else int(m.sum())
                       for m in masks_by_z], dtype=np.int64)
    z_obj = z_dens >= tol_z
    z_nz = np.nonzero(z_obj)[0]
    if z_nz.size == 0:
        return fail("all slices below the object tolerance")
    z_first, z_last = int(z_nz[0]), int(z_nz[-1])
    n_z = len(z_obj)
    z_lo, z_hi = z_first, n_z - 1 - z_last

    ny0 = y0 + y_lo if y_lo >= min_margin_px else y0
    ny1 = y1 - y_hi if y_hi >= min_margin_px else y1
    nx0 = x0 + x_lo if x_lo >= min_margin_px else x0
    nx1 = x1 - x_hi if x_hi >= min_margin_px else x1
    nz0 = z0 + z_lo if z_lo >= min_margin_px else z0
    nz1 = z1 - z_hi if z_hi >= min_margin_px else z1

    margins = {
        "air": {"y": [int(y_lo), int(y_hi)], "x": [int(x_lo), int(x_hi)],
                "z": [int(z_lo), int(z_hi)]},
        "trimmed": {"y": [int(ny0 - y0), int(y1 - ny1)],
                    "x": [int(nx0 - x0), int(x1 - nx1)],
                    "z": [int(nz0 - z0), int(z1 - nz1)]},
    }

    env = AirEnvelope(True, nz0, nz1, ny0, ny1, nx0, nx1,
                      method="air-envelope", margins=margins)

    # ---- guards -------------------------------------------------------------
    if (env.z1 < env.z0 or env.y1 < env.y0 or env.x1 < env.x0):
        return fail("degenerate envelope after trimming")
    area = ((env.z1 - env.z0 + 1) * (env.y1 - env.y0 + 1)
            * (env.x1 - env.x0 + 1))
    full = ((z1 - z0 + 1) * H * W)
    if area < min_keep_frac * full:
        return fail(f"trimmed volume below {min_keep_frac:.0%} of the FOV "
                    f"range ({area} < {min_keep_frac * full:.0f})")
    return env


def apply_air_crop(stripped: np.ndarray, *,
                   bbox: tuple[int, int, int, int, int, int],
                   air_hu: float = -900.0,
                   air_frac: float = 0.98,
                   min_margin_px: int = 2,
                   min_keep_frac: float = 0.05,
                   z_clamp_hi: int | None = None,
                   ) -> tuple[tuple[int, int, int, int, int, int],
                              AirEnvelope]:
    """Pipeline entry: tighten ``bbox`` (z0,z1,y0,y1,x0,x1) on air margins.

    Returns the final bbox plus the envelope diagnostics.  On any guard trip
    the original bbox is returned with ``ok=False`` (caller logs the
    fallback).  ``z_clamp_hi`` (the cut boundary) caps z1 exactly like the
    existing pipeline clamp.
    """
    z0, z1, y0, y1, x0, x1 = (int(v) for v in bbox)
    env = detect_air_envelope(stripped, z0=z0, z1=z1, y0=y0, y1=y1,
                              x0=x0, x1=x1, air_hu=air_hu,
                              air_frac=air_frac, min_margin_px=min_margin_px,
                              min_keep_frac=min_keep_frac)
    if not env.ok:
        return (z0, z1, y0, y1, x0, x1), env

    out = (env.z0, env.z1, env.y0, env.y1, env.x0, env.x1)
    if z_clamp_hi is not None:
        zc = min(out[1], int(z_clamp_hi))
        if zc < out[0]:
            return (z0, z1, y0, y1, x0, x1), env.__class__(
                False, out[0], out[1], out[2], out[3], out[4], out[5],
                method="tracker",
                fallback_reason="air envelope entirely above the cut clamp")
        out = (out[0], zc, *out[2:])
    return out, env
