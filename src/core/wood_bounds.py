"""Metal-anchored, air-refined wood bounds for the app's auto guide lines.

# STABLE DETECTION - DO NOT MODIFY CORE (audit 0AG)
# This module is the validated detection core (0AF: full-frame -> wood-edge
# envelope on every reference specimen).  Auto-snap and any cut-line
# padding/offsets belong to the COPY layer (core/auto_snap.py + the UI),
# never here.  Only additive evidence fields or comment/doc changes are
# acceptable; any behavioural edit requires re-running the full gate plus
# the debug overlays in debug_roi_fix/.

Resolution-adaptive: every scale constant is expressed in PHYSICAL units
(micrometres / millimetres) and converted to pixels through the specimen's
voxel size, so 6 µm, 24 µm, 66 µm, 120 µm — and anything beyond — behave
identically.  Fractions (percentiles, base-slab width share) are already
scale-free.

Detection priority (mirrors the app's data model — metal first, air second):

1. **Metal anchor (priority 1, sagittal + coronal).**  The specimen sits on
   a dense metal base that only the metal class separates reliably.  A
   slice anchors only when the base — a slab spanning at least ``BASE_FRAC``
   of the ortho profile width — is seen by **both** lines in the same slice
   (straps/pins are laterally thin and cannot qualify at any resolution).
   The 2-D slab test is hardened with a **column quorum**: on each plane
   ``ORTHO_QUORUM`` independent mid-column profiles must agree, so a single
   noisy column can no longer fake or hide a base.  When the pipeline's
   bottom-metal-count anchor is known (``det_anchor``), the **bottom-most
   slab run that reaches it** is the base — that reproduces the detector's
   anchor on every validated specimen while the quorum width test still
   protects against thin hardware inside the wood.  Without a detector
   anchor the bottom-most agreeing run wins (the base is at the bottom).
   The base top, backed off by a physical halo guard, defines the highest
   slice whose air statistics are trustworthy.

2. **Air refinement (priority 2, all planes).**  Air is measured *after*
   the metal window is fixed, so it can never move the metal cut line:

   * Z (all planes): a uniform pool of axial slices over the trusted
     window (step ~``POOL_STEP_MM``, resolution-adaptive) provides the
     wood's Z extent — the top-air edge becomes the Keep line and the
     bottom edge the Cut suggestion.  An air-curtain guard requires the
     extreme pooled slices to be *clearly* air (object fraction below
     ``EDGE_AIR_MAX``) before their edge is adopted; a foggy edge defers
     to the previous guide instead of inventing a wrong one.
   * Lateral (sagittal + coronal witnesses + axial): each axial slice is
     the YZ witness for X and the XZ witness for Y.  On each plane the
     axial evidence (occupancy-profile margins, aggregated by percentile
     over the pool) is cross-checked against the matching ORTHO plane
     witness — the mid-column air margin of the sagittal/coronal stacks —
     and the tighter margin is adopted **only when the two witnesses
     agree** (within ``WITNESS_AGREE_MM``).  On disagreement the axial
     margin stands (conservative: never cuts into the wood, at worst
     leaves a little air).  A **component size gate** excludes specks,
     debris and scanner fog: tiny far-out components cannot inflate the
     wood envelope (use ``AIR_MIN_AREA_MM2`` in physical units, so it
     scales across resolutions).

   The wood class (HU window, largest-run per column/row for the
   witnesses) excludes metal and fog from the evidence; morphological
   closing scales with resolution (0.15 mm radius); percentile
   aggregation (20th/80th) keeps the modal extent — immune to fog
   outliers, tolerant of taper and of several sticks sharing one scan.

The result is read-only geometry for line placement — it never touches
the pipeline or the delivery.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

try:                                    # scipy is a hard dep of the pipeline
    from scipy import ndimage as ndi
except Exception:                       # pragma: no cover
    ndi = None

# ---------------------------------------------------------------------------
# physical scale model (the ONLY place resolution-dependent constants live)
# ---------------------------------------------------------------------------
AIR_HU_DEFAULT = -900.0
WOOD_HU_DEFAULT = (-990.0, -500.0)      # dense-wood HU window (AD datasets)
PCT_LO, PCT_HI = 20.0, 80.0             # percentile aggregation (scale-free)
MIN_EVIDENCE = 5                        # min usable estimates per axis
BASE_FRAC = 0.12                        # metal slab ≥12% of ortho profile width
BASE_MIN_PX = 2                         # absolute floor for the slab test
ORTHO_QUORUM = 2                        # independent mid-columns that must agree
ORTHO_COLS = 5                          # mid-columns probed per ortho plane
CLOSING_MM = 0.15                       # morphological closing radius
HALO_MM = 0.2                           # slices above the base top to skip
EDGE_AIR_MAX = 0.05                     # top edge air-curtain clearance gate
AIR_MIN_AREA_MM2 = 0.15                 # ignore components smaller than this
FOG_BLANKET_FRAC = 0.60                 # edge slice mostly-filled -> fog
LAT_EDGE_CLEAR_MM = 0.5                 # lateral evidence: physical width of
                                        # the frame-edge band probed on every
                                        # pooled slice / plane row
LAT_BLANKET_FRAC = 0.50                 # band occupancy above half -> the
                                        # slice is a fog blanket (full-frame
                                        # fill); z evidence only (audit 0AF)
LAT_EDGE_FRAC = 0.40                    # lateral lane threshold: a lane
                                        # belongs to the wood when its pooled
                                        # projection carries at least this
                                        # share of the peak lane.  Calibrated
                                        # on the reference fleet (audit 0AF):
                                        # the dim fog ring around a block
                                        # carries 25-32 % of peak, the wood
                                        # plateau 95-100 %, so the separating
                                        # valley sits at 40-50 %; the
                                        # originally prescribed 0.05 was
                                        # proven insufficient (every
                                        # reference specimen came out
                                        # full-frame with it).
LAT_KNEE_HI = 0.50                      # upper clamp of the Otsu knee: keeps
                                        # the threshold inside the valley on
                                        # unimodal/full-width wood too
N_AXIAL_POOL = 32                       # axial slices sampled for the pool
_POOL_READ_BATCH = 4                    # pool slices held in RAM at once
POOL_STEP_MM = 0.85                     # reference pool spacing (physical mm)
KEEP_AIR_MARGIN_MM = 0.3                # Keep line clearance above the curtain
KEEP_CLEAR_MM = 0.2                     # verified clear air required above it
# Ultra-high-res compute guard (the 1-100 um resolution envelope): at 1 um
# CLOSING_MM is 150 px and a disk kernel that size would cost minutes per
# slice.  The physical closing stops scaling beyond this pixel radius; the
# keep/cut margins (0.2/0.3 mm) dwarf the residual kernel-edge lag, so the
# validated line placement is unchanged at every capped resolution.
CLOSING_PX_MAX = 24
# At/above this radius the closing switches to a distance-transform
# implementation: the same Euclidean ball, O(N) instead of O(N*r^2).
# Border semantics differ from the classic kernel (EDT does not
# artificially erode the mask at array borders — semantically better
# for a specimen touching the FOV edge); the validated fleet voxels
# close at r<=6 and never take this path (byte-identical there).
# Measured: 3.9 s at 6000x6000 r=24 vs minutes for the explicit kernel.
CLOSE_EDT_MIN_R = 8
# Contiguous edge walks probe every slice across the pool step; at fine
# voxels (z_step == voxel) that is hundreds of 300+ MB slice reads per
# walk.  Below this voxel size the walks probe at a capped stride and
# refine the terminal gap at unit stride — the contiguity contract
# (max stride px between verified slices) and millimetre accuracy are
# preserved, real material is far thicker than the stride, and at
# coarser voxels the stride is 1: fleet behaviour byte-identical.
FINE_STRIDE_MAX_VUM = 20.0
FINE_STRIDE_CAP = 20
KEEP_SCAN_MM = 6.0                      # curtain scan span above the wood apex
WITNESS_MARGIN_MM = 1.0                 # ortho witness clearance from the FOV
WITNESS_AGREE_MM = 1.5                  # axial vs ortho agreement tolerance

RefProvider = Callable[[list[int]], dict[int, np.ndarray]]


def _px(phys_um: float, voxel_um: float | None) -> int:
    """Physical length (µm) → whole pixels (≥1) for the given voxel size."""
    if not voxel_um or voxel_um <= 0:
        voxel_um = 25.0                 # 24 µm-class reference fallback
    return max(1, int(round(float(phys_um) / float(voxel_um))))


def _walk_stride(voxel_um: float | None) -> int:
    """Probe stride for the z edge walks (1 = fully contiguous).

    Above ``FINE_STRIDE_MAX_VUM`` the stride is 1 — the validated
    contiguous behaviour.  Below it the stride grows as the voxel
    shrinks (capped), so a 1 µm scan walks in 20-slice probes instead
    of ~850 unit steps per 0.85 mm pool gap.
    """
    v = float(voxel_um) if voxel_um and voxel_um > 0 else 25.0
    if v >= FINE_STRIDE_MAX_VUM:
        return 1
    return max(2, min(FINE_STRIDE_CAP,
                      int(round(FINE_STRIDE_MAX_VUM / v))))


def adaptive_scale(voxel_um: float | None) -> dict:
    """Pixel constants for this specimen's resolution (audit-friendly).

    The axial pool is defined over the PHYSICAL window (the same specimen
    spans the same millimetres at any resolution), so its slice count is
    resolution-free; the pixel-domain constants below are not.
    """
    area_px = 1
    if voxel_um and voxel_um > 0:
        area_px = max(1, int(round(AIR_MIN_AREA_MM2
                                   / (voxel_um * voxel_um * 1e-6))))
    return {
        "voxel_um": round(float(voxel_um), 4) if voxel_um else None,
        "closing_px": min(CLOSING_PX_MAX,
                          max(1, _px(CLOSING_MM * 1000.0, voxel_um))),
        "halo_px": _px(HALO_MM * 1000.0, voxel_um),
        "air_min_area_px": area_px,
        "pool": N_AXIAL_POOL,
        "pool_step_mm": POOL_STEP_MM,
    }


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------
def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive (start, end) index runs of True."""
    out: list[tuple[int, int]] = []
    idx = np.nonzero(mask)[0]
    if idx.size == 0:
        return out
    start = prev = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i > prev + 1:
            out.append((start, prev))
            start = i
        prev = i
    out.append((start, prev))
    return out


def _largest_run(mask: np.ndarray) -> tuple[int, int] | None:
    r = _runs(mask)
    if not r:
        return None
    return max(r, key=lambda t: t[1] - t[0])


def _percentile_bounds(lo: list[int], hi: list[int]) -> tuple[int, int] | None:
    """Percentile aggregation of per-slice/per-row (lo, hi) estimates."""
    if len(lo) < MIN_EVIDENCE or len(lo) != len(hi):
        return None
    a = int(round(np.percentile(lo, PCT_LO)))
    b = int(round(np.percentile(hi, PCT_HI)))
    return (a, b) if b > a else None


def _disk(r: int) -> np.ndarray:
    """Disk structuring element of radius r (cross when r == 1)."""
    if r <= 1:
        return np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (y * y + x * x) <= r * r


def _close(m: np.ndarray, r: int) -> np.ndarray:
    r = min(int(r), CLOSING_PX_MAX)     # soft cap for ultra-high-res voxels
    if ndi is None or r <= 0:
        return m
    if r >= CLOSE_EDT_MIN_R:
        # large-radius closing via Euclidean distance transforms (O(N)):
        # dilation = pixels within r of the object, then erosion = pixels
        # farther than r from the dilated background — the same Euclidean
        # ball as _disk(r) in the interior (measured 6x faster on 6000^2
        # slices); unlike the kernel path it does not artificially erode
        # objects that touch the array border.  Fleet voxels (r<=6) never
        # take this branch — validated behaviour byte-identical.
        dil = ndi.distance_transform_edt(~m) <= float(r)
        return ndi.distance_transform_edt(dil) > float(r)
    return ndi.binary_closing(m, structure=_disk(r), iterations=1)


def _viewer_helpers():
    """Return (pick_slices, source_slices) regardless of import context."""
    try:
        from core import viewer_core as vc
    except ImportError:                     # pragma: no cover - direct layout
        import viewer_core as vc
    return vc._pick_slices, vc._source_slices


def need_of(w: int) -> int:
    """Minimum slab width (px) for a column of ``w`` pixels."""
    return max(BASE_MIN_PX, int(round(BASE_FRAC * w)))


# ---------------------------------------------------------------------------
# priority 1: metal anchor from sagittal + coronal agreement
# ---------------------------------------------------------------------------
def _solid_metal(line: np.ndarray, metal_hu: float,
                 quorum: int = ORTHO_QUORUM) -> np.ndarray:
    """Per-slice support of one ortho plane (multi-column quorum).

    Rank-3 input (n_slices, n_cols, profile_len): slice z is
    metal-supported when the slab test passes on a QUORUM of independent
    mid-column profiles — a run of metal-HU pixels spanning at least
    ``BASE_FRAC`` of that column's length on at least ``quorum`` of the
    ``ORTHO_COLS`` probed columns.  The base is a wide slab; straps, pins
    and inclusions are laterally thin and cannot qualify on several
    columns at ANY resolution (the test is a width fraction).  A single
    noisy column can no longer fake or hide a base.

    Rank-2 input (n_slices, profile_len) is a single mid-column stack and
    keeps the original per-slice run-length slab test (validated legacy
    path; the stack has no lateral room for a quorum).

    Returns a boolean (n,) vector.
    """
    line = np.asarray(line, np.float32)
    if line.ndim == 3:
        n, ncols, w = line.shape
        if n == 0 or w == 0 or ncols == 0:
            return np.zeros(n, bool)
        # evenly spaced mid-columns, always including the exact middle
        cols = sorted({min(ncols - 1, max(0, int(round(v))))
                       for v in np.linspace(ncols / 2, ncols - 1,
                                            min(ORTHO_COLS, ncols))})
        sup_cols: list[np.ndarray] = []
        for c in cols:
            colv = line[:, c, :]                     # (n, w)
            met = np.isfinite(colv) & (colv > metal_hu)
            sup = np.zeros(n, bool)
            for z in range(n):
                for a, b in _runs(met[z]):
                    if b - a + 1 >= need_of(w):
                        sup[z] = True
                        break
            sup_cols.append(sup)
        votes = np.sum(sup_cols, axis=0)
        return votes >= max(1, min(quorum, len(sup_cols)))
    if line.ndim != 2:
        raise ValueError("ortho line stack must be rank-2 or rank-3")
    n, w = line.shape
    if n == 0 or w == 0:
        return np.zeros(n, bool)
    need = max(BASE_MIN_PX, int(round(BASE_FRAC * w)))
    met = np.isfinite(line) & (line > metal_hu)
    sup = np.zeros(n, bool)
    for z in range(n):
        for a, b in _runs(met[z]):
            if b - a + 1 >= need:
                sup[z] = True
                break
    return sup


def _edge_band_frac(m: np.ndarray, band_px: int) -> float:
    """Worst-case occupancy of the frame-edge band (audit 0AF).

    ``band_px`` columns/rows on every side of the mask are probed and the
    highest occupied fraction is returned.  Fog blankets fill the FOV and
    touch the edge (frac tens of percent); clean wood slices leave the
    outer physical clearance nearly empty (frac ~0).  For a 1-D row only
    the two lateral bands are probed.
    """
    band = max(1, int(band_px))
    v = np.asarray(m)
    if v.ndim == 1:
        return max(float(v[:band].mean()), float(v[-band:].mean()))
    return max(float(v[:, :band].mean()), float(v[:, -band:].mean()),
               float(v[:band, :].mean()), float(v[-band:, :].mean()))


def _otsu_threshold(v: np.ndarray) -> float:
    """Otsu's between-class variance split of a 1-D projection.

    Returns the bin centre maximising the between-class variance (0 when
    the distribution is degenerate).  Used as the data-driven valley
    locator of the bimodal ring/wood lane distribution (audit 0AF).
    """
    x = np.asarray(v, np.float64).ravel()
    if x.size == 0:
        return 0.0
    lo, hi = float(x.min()), float(x.max())
    if hi <= lo:
        return hi
    hist, edges = np.histogram(x, bins=128)
    centers = 0.5 * (edges[:-1] + edges[1:])
    total = float(hist.sum())
    if total <= 0:
        return hi
    w0 = np.cumsum(hist)
    w1 = total - w0
    m0 = np.cumsum(hist * centers)
    mt = m0[-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        mu0 = m0 / w0
        mu1 = (mt - m0) / w1
        var = w0 * w1 * (mu0 - mu1) ** 2
    var[~np.isfinite(var)] = -1.0
    return float(centers[int(np.argmax(var))])


def _projection_lane_bounds(proj: np.ndarray | None,
                            ) -> tuple[int, int] | None:
    """First/last lane of a pooled wood projection above the lateral knee
    (audits 0AE/0AF).

    # STABLE DETECTION - DO NOT MODIFY CORE (audit 0AG)

    ``proj`` sums the wood mask over the pooled slices — per column for
    the X envelope (sum over Y) and per row for the Y envelope (sum over
    X).  The lane distribution is bimodal on every reference specimen:
    a dim fog ring (25-32 % of the peak lane) around a dense wood
    plateau (95-100 %).  The envelope is the first/last lane above the
    Otsu valley between those modes, clamped into
    ``[LAT_EDGE_FRAC, LAT_KNEE_HI]`` of the peak lane count, so it stays
    scale-free, hugs the wood outline and ignores fog by construction."""
    if proj is None or proj.size == 0:
        return None
    peak = int(proj.max())
    if peak <= 0:
        return None
    knee = _otsu_threshold(proj)
    lo_bound = float(LAT_EDGE_FRAC) * peak
    hi_bound = float(LAT_KNEE_HI) * peak
    thr = int(round(min(max(knee, lo_bound), hi_bound)))
    thr = max(1, thr)
    idx = np.nonzero(proj > thr)[0]
    if idx.size == 0:
        return None
    return int(idx[0]), int(idx[-1])


def _metal_anchor(sag: np.ndarray, cor: np.ndarray, metal_hu: float,
                  det_anchor: int | None = None) -> tuple[int, int] | None:
    """Slice range where BOTH ortho lines see the metal slab.

    With a detector anchor (the pipeline's bottom metal-count seed), the
    base is the bottom-most slab run that REACHES the detector anchor —
    reproducing the validated detection exactly.  Without one, the
    bottom-most agreeing run wins (the base is at the bottom).

    Returns (base_top, base_bottom) in slice indices, or None.
    """
    sag = np.asarray(sag, np.float32)
    cor = np.asarray(cor, np.float32)
    n = min(sag.shape[0], cor.shape[0])
    both = _solid_metal(sag[:n], metal_hu) & _solid_metal(cor[:n], metal_hu)
    runs = _runs(both)
    if not runs:
        return None
    chosen: tuple[int, int] | None = None
    if det_anchor is not None:
        da = int(det_anchor)
        reaching = [r for r in runs if r[0] <= da <= r[1]]
        if reaching:
            chosen = reaching[0]
        else:
            below = [r for r in runs if r[1] < da]
            if below:
                chosen = below[-1]
    if chosen is None:
        chosen = runs[-1]
    return (int(chosen[0]), int(chosen[1]))


# ---------------------------------------------------------------------------
# priority 2: air/wood evidence
# ---------------------------------------------------------------------------
def _object_mask(vals: np.ndarray, air_hu: float,
                 wood: tuple[float, float] | None,
                 metal_hu: float | None) -> np.ndarray:
    """Object = wood class ∩ non-metal (when levels are known).

    # STABLE DETECTION - DO NOT MODIFY CORE (audit 0AG)

    When a calibrated wood window is supplied the window DEFINES the
    class and its lower bound replaces the generic air level.  A fixed
    air default (-900 HU) misclassified the drier top of a real
    specimen (wood reading -990..-900 HU), erased it from the class and
    reported ``wood_top`` hundreds of slices too deep; the window's own
    lower bound is the calibrated air/wood boundary."""
    v = np.asarray(vals, np.float32)
    if wood is not None:
        obj = (np.isfinite(v) & (v >= float(wood[0]))
               & (v <= float(wood[1])))
    else:
        obj = np.isfinite(v) & (v > float(air_hu))
    if metal_hu is not None:
        obj &= v < float(metal_hu)
    return obj


def _largest_components(m: np.ndarray, min_area_px: int) -> np.ndarray:
    """Keep only connected components of at least ``min_area_px`` pixels.

    Specks, debris and scanner fog are tiny and far from the specimen;
    the wood itself is a large object.  The gate is physical
    (``AIR_MIN_AREA_MM2`` → pixels via the voxel size).
    """
    if ndi is None or min_area_px <= 1 or not m.any():
        return m
    lab, n = ndi.label(m)
    if n <= 1:
        return m
    sizes = np.bincount(lab.ravel())
    keep = np.zeros(sizes.shape[0], bool)
    keep[1:] = sizes[1:] >= min_area_px
    return keep[lab]


def _mask_of(sl: np.ndarray, wood: tuple[float, float] | None,
             metal_hu: float | None, closing_px: int,
             min_area_px: int = 1) -> np.ndarray:
    """Closed+filled wood-class mask of one axial source slice."""
    m = _object_mask(np.asarray(sl, np.float32), AIR_HU_DEFAULT, wood, metal_hu)
    m = _close(m, closing_px)
    if ndi is not None:
        m = ndi.binary_fill_holes(m)
    return _largest_components(m, min_area_px)


def _signal_mask(sl: np.ndarray, air_hu: float, min_area_px: int,
                 closing_px: int) -> np.ndarray:
    """Mask of ANY non-air material (fog, wood, metal) in one slice.

    Pixels above ``air_hu`` forming components of at least ``min_area_px``
    after the standard closing — single noisy pixels are not signal.
    """
    m = np.isfinite(sl) & (sl > float(air_hu))
    if not m.any():
        return np.zeros(np.shape(sl), bool)
    m = _close(m, closing_px)
    return _largest_components(m, min_area_px)


def _has_signal(sl: np.ndarray, air_hu: float, min_area_px: int,
                closing_px: int) -> bool:
    """True when a slice carries ANY non-air material (fog, wood, metal)."""
    if sl is None:
        return False
    # fast reject: a pure-air slice (the common case in the keep scan
    # window above the specimen) is answered with one O(N) comparison —
    # no mask, no closing, no labelling.  At ultra-high-res voxels this
    # turns a ~4 s probe into ~50 ms for every air slice.
    v = np.isfinite(sl) & (sl > float(air_hu))
    if not v.any():
        return False
    return bool(_signal_mask(sl, air_hu, min_area_px, closing_px).any())


def _curtain_top(read: Callable[[int], np.ndarray | None], wood_top: int,
                 *, air_hu: float, closing_px: int, min_area_px: int,
                 z_step_um: float, z_min: int, stride: int = 1
                 ) -> tuple[int, bool]:
    """Topmost non-air material above the wood apex, within the scan
    window, plus whether verified clear air sits immediately above it.

    LOCKED - CORRECT - DO NOT MODIFY (top/Keep edge): validated 0AD/0AE.

    Scans EVERY slice from ``wood_top`` up to ``KEEP_SCAN_MM`` (bounded
    by ``z_min``) and reports the smallest z carrying any signal (fog
    wisps, scan-artifact lines, detached debris islands, the wood apex
    itself — anything above ``air_hu`` of at least ``min_area_px``).
    The Keep line must clear the TOPMOST material in the window: a line
    below a detached island would slice through it.  ``clear_ok`` says
    whether ``KEEP_CLEAR_MM`` of CONTIGUOUS clear air was verified
    immediately above the winner — the guarantee that the adopted line
    sits in air, not inside fog.  All spans are physical: ``z_step_um``
    is the specimen's true slice thickness.  Cost is bounded by the
    window (≤ ~240 slice reads at 24 µm; ≤ 6 at the coarsest).
    """
    limit = max(int(z_min),
                int(wood_top) - max(1, int(round(
                    KEEP_SCAN_MM * 1000.0 / max(1.0, float(z_step_um))))))
    clear_need = max(1, int(round(KEEP_CLEAR_MM * 1000.0
                                  / max(1.0, float(z_step_um)))))
    top = int(wood_top)
    clear_above = 0
    z = int(wood_top) - 1
    stride = max(1, int(stride))
    while z >= limit:
        sl = read(z)
        if sl is None:
            break
        if _has_signal(sl, air_hu, min_area_px, closing_px):
            top = z
            clear_above = 0
        else:
            clear_above += stride     # each clear probe covers `stride` slices
        z -= stride
    return top, clear_above >= clear_need


def _fog_blanket(mask: np.ndarray,
                 frac: float = FOG_BLANKET_FRAC) -> bool:
    """True when a slice mask fills most of the FOV (a fog blanket).

    Scanner fog blankets the whole reconstruction; real wood never fills
    more than ~half of the scan field in these specimens.  An edge slice
    whose object mask dominates the FOV is fog that fooled the bisection,
    not the specimen.
    """
    return bool(mask.mean() > frac)


def _edge_walk(read: Callable[[int], np.ndarray | None], present: int,
               absent: int, *, wood: tuple[float, float] | None,
               metal_hu: float | None,                 closing_px: int, min_area_px: int = 1,
               stride: int = 1) -> int:
    """Walk slice-by-slice from the pooled wood-present slice toward the
    absent side and stop at the FIRST air slice.

    LOCKED - CORRECT - DO NOT MODIFY (top/bottom z edges): this is the
    validated 0AD/0AE behaviour and lateral work must not touch it.

    Replaces the earlier sparse bisection: probing sampled the gap and
    returned the first probe with any wood pixel, so an isolated island
    above the wood top (fog chunk, debris) could be returned as the edge
    even though the pool had correctly picked the MAIN wood run.  The
    walk is contiguous by construction — every slice between the result
    and the start is wood — so it cannot hop an air gap, and the
    Keep/Cut lines hug the true wood edges at slice resolution (pool
    step is ~0.9 mm; the walk refines across it).  Costs at most
    ``abs(present - absent)`` reads (a couple of pool steps).
    """
    p, a = int(present), int(absent)
    if p == a:
        return p
    step = -1 if p > a else 1
    stride = max(1, int(stride))

    def _wood(zz: int) -> bool:
        sl = read(zz)
        if sl is None:
            return False
        return bool(_mask_of(sl, wood, metal_hu, closing_px,
                             min_area_px).any())

    if stride == 1:
        last = p
        z = p + step
        while (step < 0 and z >= a) or (step > 0 and z <= a):
            if not _wood(z):
                break
            last = z
            z += step
        return last

    # strided probe: walk at `stride`, then refine the terminal gap at
    # unit stride so the result stays contiguous with the main run (the
    # same slices are classified as a unit walk, just fewer probes).
    # The probe never overshoots the absent bound: when the next stride
    # step would pass ``a``, it is clamped to ``a`` itself — otherwise a
    # stride larger than the remaining gap would skip the walk entirely
    # and return the unrefined pool sample.
    z = p
    fail_z: int | None = None
    while True:
        nxt = z + step * stride
        if (step < 0 and nxt < a) or (step > 0 and nxt > a):
            nxt = a                       # clamp: never overshoot the bound
        if not _wood(nxt):
            fail_z = nxt
            break
        if nxt == a:
            return a                      # walked to the bound, all wood
        z = nxt
    last = z
    s = z + step
    while (step < 0 and s > fail_z) or (step > 0 and s < fail_z):
        if not _wood(s):
            break
        last = s
        s += step
    return last


def _mask_extent(m: np.ndarray) -> tuple[int, int, int, int] | None:
    """(y0, y1, x0, x1) full extent of the object mask; None if empty.

    Deliberately NOT largest-component: these scans hold several wood
    sticks side by side (discrete columns per slice), and the wood ROI is
    the envelope of ALL of them.  Debris/fog is handled by the wood class,
    the component size gate, the percentile aggregation and the
    metal-anchored z-window instead.
    """
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())


def _band_object_frac(m: np.ndarray, sl: np.ndarray) -> float:
    """Object fraction of one 1-D band of the (already object-masked) plane."""
    total = sl.size
    if total <= 0:
        return 1.0
    return float(np.count_nonzero(m[sl])) / float(total)


def _ortho_witness(line: np.ndarray, wood: tuple[float, float] | None,
                   metal_hu: float | None, air_hu: float,
                   min_area_px: int,
                   margin_mm: float = WITNESS_MARGIN_MM,
                   voxel_um: float | None = None) -> dict | None:
    """Ortho-plane air witness from one mid-band ortho stack.

    ``line`` is (n_slices, profile) — a single mid-column stack — or
    (n_slices, n_cols, profile), a multi-column band.  The wood-class 2-D
    occupancy of the plane provides two independent pieces of evidence:

    * ``lat`` — margins along the PROFILE axis: where wood stops
      laterally in that plane (sagittal → Y, coronal → X).  Percentile
      aggregation over the plane's slices; each side is reported WITH an
      ``ok`` flag that demands the physical edge band of the plane to be
      CLEAR AIR (object fraction ≤ ``EDGE_AIR_MAX`` over the first/last
      ``margin_mm``) — fog at the FOV edge defers the side instead of
      feeding a wrong margin downstream.
    * ``z_top`` — air margin (slices) above the wood along the SLICE
      axis: the top-air witness for the Keep line (80th percentile of
      per-column wood tops), ``ok`` only when the top band of the plane
      is clear air as well.

    The witness uses the wood CLASS (windowed, closed, component-gated),
    so metal and fog are excluded from the evidence by construction.  A
    physical clearance is demanded before a margin is reported.
    """
    line = np.asarray(line, np.float32)
    if line.ndim == 3:
        # collapse the band to its mid-column (the panel's plane)
        line = line[:, line.shape[1] // 2, :]
    if line.ndim != 2 or line.size == 0:
        return None
    m = _object_mask(line, air_hu, wood, metal_hu)
    m = _close(m, 1)
    if ndi is not None:
        m = ndi.binary_fill_holes(m)
    m = _largest_components(m, max(1, min_area_px))
    if not m.any():
        return None
    clearance = _px(margin_mm * 1000.0, voxel_um)
    n_prof, w = m.shape

    # lateral (audit 0AF): the same blanket-gate + projection principle as
    # the axial pool, applied to this plane's rows: only z-rows that are
    # not fog blankets contribute, then the per-column projection hugs the
    # wood via the Otsu knee.  The clearance gates are evaluated on the
    # SAME contributing rows, so the verdict is consistent with the
    # projection evidence.
    band = _px(LAT_EDGE_CLEAR_MM * 1000.0, voxel_um)
    clean = np.array([bool(m[z].any())
                      and _edge_band_frac(m[z], band) <= LAT_BLANKET_FRAC
                      for z in range(n_prof)], bool)
    lat = None
    if int(clean.sum()) >= MIN_EVIDENCE:
        sub = m[clean]
        pb = _projection_lane_bounds(sub.sum(axis=0, dtype=np.int64))
        if pb is not None:
            lo, hi = pb
            lo_ok = (lo >= clearance
                     and _band_object_frac(
                         sub, np.ix_(np.arange(sub.shape[0]),
                                     np.arange(min(clearance, w))))
                     <= EDGE_AIR_MAX)
            hi_ok = ((w - 1 - hi) >= clearance
                     and _band_object_frac(
                         sub, np.ix_(np.arange(sub.shape[0]),
                                     np.arange(max(w - clearance, 0), w)))
                     <= EDGE_AIR_MAX)
            lat = {"lo": lo, "hi": hi, "lo_ok": bool(lo_ok),
                   "hi_ok": bool(hi_ok)}

    # z: per-column wood top → high percentile (fog-immune top-air witness)
    z_los: list[int] = []
    for c in range(w):
        zs_idx = np.nonzero(m[:, c])[0]
        if zs_idx.size:
            z_los.append(int(zs_idx[0]))
    z_top = None
    z_top_ok = False
    if len(z_los) >= MIN_EVIDENCE:
        t = int(round(np.percentile(z_los, PCT_HI)))
        z_top = t
        z_top_ok = (t >= clearance
                    and _band_object_frac(m, np.ix_(np.arange(min(clearance,
                                                                  n_prof)),
                                                    np.arange(w)))
                        <= EDGE_AIR_MAX)
    return {"lat": lat, "z_top": z_top, "z_top_ok": bool(z_top_ok)}


def _witness_agree(axial_px: int, ortho_px: int, voxel_um: float | None,
                   tol_mm: float = WITNESS_AGREE_MM) -> bool:
    """True when the axial and ortho witnesses agree (within tolerance)."""
    if axial_px is None or ortho_px is None:
        return False
    tol_px = max(1, _px(tol_mm * 1000.0, voxel_um))
    return abs(int(axial_px) - int(ortho_px)) <= tol_px


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------
def wood_bounds(ds, sample: str, *, n_slices: int, cut_from: int,
                sag: np.ndarray | None = None, cor: np.ndarray | None = None,
                metal_hu: float | None = None,
                track_z: tuple[int, int] | None = None,
                voxel_um: float | None = None,
                wood_hu: tuple[float, float] | None = None,
                slice_provider: RefProvider | None = None,                 det_anchor: int | None = None,
                 det_cut: int | None = None,
                 z_step_um: float | None = None) -> dict | None:
    """Metal-anchored, air-refined wood bounds in source pixel coordinates.

    # STABLE DETECTION - DO NOT MODIFY CORE (audit 0AG): the values this
    # function returns ARE the validated detection; the auto-snap copy
    # layer (core/auto_snap.py) only maps them onto the cut lines.

    Returns ``None`` when the volume cannot be characterized (too little
    evidence, degenerate masks) — callers keep their previous behaviour.

    Keys::

        {"y0","y1","x0","x1","H","W","n",
         "zb": {"keep": int|None, "cut": int|None,
                "wood_top": int, "wood_bottom": int, "top_ok": bool},
         "anchor": {"ok": bool, "z": [top, bottom] | None,
                    "guard_applied": bool, "source": str},
         "margins": {"y": [lo, hi], "x": [lo, hi]},
         "voxel_um": float|None, "scale": adaptive_scale dict,
         "evidence": {"axial_slices": int, ...}}

    ``zb.keep`` is the top-air line (None when the wood top touches the
    scanned range or the edge is foggy) and ``zb.cut`` the bottom-metal
    line — the pipeline's detected halo onset (``det_cut``, the physical
    "metal threshold" cut) when known, else the base top, else one slice
    past the wood bottom.  ``voxel_um`` drives the adaptive scale;
    ``wood_hu`` restricts the wood class.  ``slice_provider`` overrides
    the default cached source-slice reader (used by synthetic
    scale-invariance tests).  ``det_anchor`` fuses the pipeline's bottom
    metal-count anchor into the base selection (priority 1); ``det_cut``
    is the detector's halo-onset cut (the line the pipeline actually
    cuts at, validated on the fleet).
    """
    _pick_slices, _source_slices = _viewer_helpers()
    sc = adaptive_scale(voxel_um)

    n = int(n_slices)
    cut = int(max(1, min(n, cut_from)))

    # ---- z search window: tracked wood range ∩ below the cut ---------------
    z_lo, z_hi = 0, cut - 1
    if track_z and track_z[0] is not None and track_z[1] is not None:
        z_lo = max(0, int(track_z[0]))
        z_hi = min(z_hi, int(track_z[1]))
    if z_hi < z_lo:
        return None

    # ---- priority 1: metal anchor fixes the trustworthy z-window -----------
    anchor_z: tuple[int, int] | None = None
    guard_applied = False
    anchor_source = "none"
    fog_defer = False
    if sag is not None and cor is not None and metal_hu is not None:
        try:
            anchor_z = _metal_anchor(sag, cor, float(metal_hu), det_anchor)
        except Exception:
            anchor_z = None
        if anchor_z is not None:
            anchor_source = ("detector-fused" if det_anchor is not None
                             else "ortho-quorum")
            # halo guard in SLICES of the specimen's true z-step: the
            # anchor is a z index, so the halo thickness (a physical
            # length) must be divided by the slice thickness — dividing
            # by the XY voxel size poisoned the window at fine voxels
            # (2 µm removed ~5 mm of real wood from the pool).
            z_step_eff = float(z_step_um) if z_step_um and z_step_um > 0 \
                else float(voxel_um or 25.0)
            halo_sl = max(1, int(round(
                HALO_MM * 1000.0 / max(1.0, z_step_eff))))
            z_trust = int(anchor_z[0]) - halo_sl
            z_hi_before = z_hi
            z_hi = min(z_hi, max(z_trust, z_lo + MIN_EVIDENCE))
            guard_applied = z_hi < z_hi_before
        # else: no anchor — the tracked z-range stands (air-only fallback)

    # ---- priority 2: axial pool over the trusted window (all planes) -------
    span = z_hi - z_lo + 1
    k = min(sc["pool"], span)
    zs = sorted({int(round(v)) for v in np.linspace(z_lo, z_hi, k)})
    if len(zs) < MIN_EVIDENCE:
        return None

    # The axial pool is read in small batches and reduced to per-slice
    # evidence immediately: at ultra-high-res voxels (1-10 µm classes) a
    # single slice can be hundreds of MB, so materializing the whole pool
    # at once would need tens of GB.  Batching through the byte-capped
    # slice cache bounds peak memory to a few slices while still reading
    # every source slice exactly once.
    present: list[int] = []               # slice indices where wood exists
    y0s: list[int] = []
    y1s: list[int] = []
    x0s: list[int] = []
    x1s: list[int] = []
    H = W = 0
    fog_by_z: dict[int, bool] = {}   # zs-indexed fog-blanket verdicts
    # lateral evidence pool (audit 0AF): slices whose frame-edge band is
    # more than half occupied are fog blankets and are excluded
    # geometrically (their HU overlaps the wood on oven-dry specimens, so
    # no intensity test can separate them).  The remaining slices are
    # projected per lane: sum over Y -> columns (X envelope), sum over
    # X -> rows (Y envelope), and the envelope is cut at the Otsu valley
    # between the fog ring and the wood plateau.  The top/bottom logic
    # below is untouched — these accumulators only feed Left/Right.
    lat_band = _px(LAT_EDGE_CLEAR_MM * 1000.0, voxel_um)
    col_proj: np.ndarray | None = None
    row_proj: np.ndarray | None = None
    for b0 in range(0, len(zs), _POOL_READ_BATCH):
        batch = zs[b0:b0 + _POOL_READ_BATCH]
        if slice_provider is not None:
            sl_map = slice_provider(batch)
        else:
            sl_map = _source_slices(ds, sample, batch)
        for z in batch:
            sl = sl_map.get(z)
            if sl is None:
                continue
            H, W = int(sl.shape[0]), int(sl.shape[1])
            m = _mask_of(sl, wood_hu, metal_hu, sc["closing_px"],
                         sc["air_min_area_px"])
            # store the fog verdict only — a full mask per pool slice
            # would be ~0.7 GB each at 1 µm voxels
            fog_by_z[int(z)] = _fog_blanket(m)
            bb = _mask_extent(m)
            if bb is None:
                continue
            present.append(int(z))
            if _edge_band_frac(m, lat_band) > LAT_BLANKET_FRAC:
                continue            # fog blanket: z evidence only, no lateral
            y0s.append(bb[0])
            y1s.append(bb[1])
            x0s.append(bb[2])
            x1s.append(bb[3])
            if col_proj is None:
                col_proj = np.zeros(W, np.int64)
                row_proj = np.zeros(H, np.int64)
            col_proj += m.sum(axis=0, dtype=np.int64)
            row_proj += m.sum(axis=1, dtype=np.int64)

    if len(present) < MIN_EVIDENCE or not H or not W:
        return None

    # ---- pool → presence flags → largest gap-tolerant run ------------------
    # (shared by the top and bottom edge logic below)
    present_set = set(present)
    flags = [z in present_set for z in zs]
    step = (zs[-1] - zs[0]) / max(1, len(zs) - 1)
    gap_tol = max(2, int(round(0.04 * len(zs))))
    runs_i = _runs(flags)
    merged: list[list[int]] = []
    for a, b in runs_i:
        if merged and (zs[a] - zs[merged[-1][1]]) <= step * (gap_tol + 1):
            merged[-1][1] = b
        else:
            merged.append([a, b])
    top_i, bot_i = max(merged, key=lambda r: r[1] - r[0])

    if slice_provider is not None:
        _read = lambda zz: slice_provider([zz]).get(zz)
    else:
        _read = lambda zz: _source_slices(ds, sample, [zz]).get(zz)

    # ------------------------------------------------------------------
    # LOCKED - CORRECT - DO NOT MODIFY
    # Top edge / Keep line (z axis).  Validated 0AD/0AE on the fleet and
    # the oven-dry specimen (wood_top 692 -> 65); byte-compared before and
    # after every lateral change.  The lateral projection above never
    # feeds into these variables.
    # ------------------------------------------------------------------
    if top_i == 0:
        # wood present from the window start: no top-air edge inside the
        # trusted data — the report's keep line stands.  When the window
        # start is itself a fog blanket the deferral is fog-driven.
        wood_top = int(zs[0])
        curtain_top: int | None = None
        keep_clear = True
        zb_keep: int | None = None
        fog_defer = fog_by_z.get(zs[0], False)
    else:
        # Edge walk from the run's SECOND sample, toward and past the run's
        # first sample: a walk started at zs[top_i] itself can stop on an
        # isolated island whose air gap is finer than the pool step (the
        # pool merged it into the run), while starting from the main body
        # forces the walk to cross the separating air first — so the result
        # is always contiguous with the MAIN wood run and cannot hop an
        # air gap.  Walking past the run start refines the edge to slice
        # resolution (finer than the pooled sampling grid).
        wood_top = _edge_walk(
            _read, zs[top_i + 1] if bot_i > top_i else zs[top_i],
            zs[top_i - 1], wood=wood_hu, metal_hu=metal_hu,
            closing_px=sc["closing_px"], min_area_px=sc["air_min_area_px"],
            stride=_walk_stride(voxel_um))
        # Keep line = top of the CONTIGUOUS signal curtain (fog wisps,
        # apex, debris — anything non-air) minus a safety margin, placed
        # in verified clear air.  Measured ground truth (24um/1-1): the
        # user's hand-set line sits ~0.3-0.4 mm above the fog curtain
        # top, NOT at the wood apex — the delivery must never slice
        # through the wisp band, and a line at the apex shaves wood.
        # The curtain walk is contiguous, so a detached fog island above
        # the wood never drags the line up; the margin slice itself is
        # verified clear air before the line is adopted.
        z_step = float(z_step_um) if z_step_um and z_step_um > 0 \
            else float(voxel_um or 25.0)
        curtain_top: int | None = None
        keep_clear = True
        # the curtain is any NON-AIR material the Keep line must clear;
        # with a calibrated wood window its lower bound is the air
        # boundary (a fixed -900 default ignores drier fog wisps)
        curtain_air = (float(wood_hu[0]) if wood_hu is not None
                       else AIR_HU_DEFAULT)
        curtain_top, keep_clear = _curtain_top(
            _read, wood_top, air_hu=curtain_air,
            closing_px=sc["closing_px"],
            min_area_px=sc["air_min_area_px"], z_step_um=z_step,
            z_min=zs[0] if top_i > 0 else 0,
            stride=_walk_stride(voxel_um))
        if not keep_clear:
            # no verified clear air above the curtain within the scan
            # window: the line would sit inside fog — defer instead of
            # guessing (top_ok goes False; the report's default stands)
            zb_keep = None
            fog_defer = True
        else:
            # fog wisps AT the curtain top are exactly what the line
            # clears (measured: the user's hand-placed line sits ~0.3 mm
            # above the fog curtain top on 24um/1-1) — adopt on verified
            # clear air, regardless of what the topmost material is
            raw = curtain_top - max(1, int(round(
                KEEP_AIR_MARGIN_MM * 1000.0 / max(1.0, z_step))))
            if raw < 0:
                # the curtain reaches the volume top: no line above it
                # can clear it — defer to the report default
                zb_keep = None
                fog_defer = True
            else:
                zb_keep = int(raw)
    # ------------------------------------------------------------------
    # LOCKED - CORRECT - DO NOT MODIFY
    # Bottom edge / Cut line (z axis).  Validated on the fleet and the
    # oven-dry specimen; byte-compared before and after every lateral
    # change.  The lateral projection above never feeds into these
    # variables.
    # ------------------------------------------------------------------
    if bot_i == len(zs) - 1:
        wood_bottom = int(zs[-1])          # wood reaches the window bottom
    else:
        # bottom edge: mirror of the top walk — start one sample inside
        # the run and walk past the run end (a sub-step island below the
        # main run cannot steal the edge unless it is truly attached)
        wood_bottom = _edge_walk(
            _read, zs[bot_i - 1] if bot_i > top_i else zs[bot_i],
            zs[bot_i + 1], wood=wood_hu, metal_hu=metal_hu,
            closing_px=sc["closing_px"], min_area_px=sc["air_min_area_px"],
            stride=_walk_stride(voxel_um))
    if anchor_z is not None and anchor_z[0] <= wood_bottom:
        # metal reached inside the pooled wood run: trust the anchor top
        wood_bottom = int(anchor_z[0]) - 1
    # Bottom-metal cut line: the pipeline's detected halo onset is the
    # line the delivery actually cuts at (validated on the fleet and the
    # manual ground truth) — NOT the physical base top, which sits below
    # the halo band and would mislead manual adjustments.  The base top
    # remains available as the metal-first anchor evidence.
    if det_cut is not None:
        zb_cut = int(max(0, min(n, int(det_cut))))
    elif anchor_z is not None:
        zb_cut = int(anchor_z[0])
    else:
        zb_cut = min(n, wood_bottom + 1)

    # ---- lateral envelope: pooled vertical projection of the wood core ----
    # The projection hugs the dense wood (fog blankets sit at the window's
    # lower edge and carry no core weight, so they cannot stretch the
    # lines); the percentile extents remain only as a fallback.
    yb = _projection_lane_bounds(row_proj)
    xb = _projection_lane_bounds(col_proj)
    if yb is None:
        yb = _percentile_bounds(y0s, y1s)
    if xb is None:
        xb = _percentile_bounds(x0s, x1s)
    if yb is None or xb is None:
        return None
    y0, y1 = yb
    x0, x1 = xb

    # ---- ortho-plane air witnesses (sagittal → Y, coronal → X) -------------
    # Each ortho plane's wood-class occupancy provides lateral margins for
    # its axis (adopted only on agreement with the axial pool) and a
    # top-air z witness for the Keep line (confirmation evidence).
    y_agree = x_agree = z_agree = False
    z_wit_top = None
    z_wit_ok = False
    yd_lo = yd_hi = xd_lo = xd_hi = True

    def _apply_witness(line, m_lo: int, m_hi: int):
        """Adopt clear-air ortho margins on agreement; defer otherwise.

        Returns (lo, hi, agreed, wit, defer_lo, defer_hi) where the
        deferred sides fall back to the axial estimates untouched.
        """
        try:
            wit = _ortho_witness(line[:n], wood_hu, float(metal_hu),
                                 AIR_HU_DEFAULT, sc["air_min_area_px"],
                                 voxel_um=voxel_um)
        except Exception:
            wit = None
        if not wit:
            return m_lo, m_hi, False, None, True, True
        lat = wit.get("lat")
        if not lat:
            return m_lo, m_hi, False, wit, True, True
        adopt_lo = bool(lat["lo_ok"]) and _witness_agree(m_lo, lat["lo"], voxel_um)
        adopt_hi = bool(lat["hi_ok"]) and _witness_agree(m_hi, lat["hi"], voxel_um)
        lo = lat["lo"] if adopt_lo else m_lo
        hi = lat["hi"] if adopt_hi else m_hi
        defer_lo = not adopt_lo
        defer_hi = not adopt_hi
        return lo, hi, bool(adopt_lo and adopt_hi), wit, defer_lo, defer_hi

    if sag is not None and metal_hu is not None:
        m_y_lo, m_y_hi = y0, H - 1 - y1
        lo, hi, y_agree, wy, yd_lo, yd_hi = _apply_witness(sag, m_y_lo, m_y_hi)
        y0, y1 = lo, H - 1 - hi
        if wy:
            z_wit_top = wy.get("z_top")
            z_wit_ok = bool(wy.get("z_top_ok"))
    if cor is not None and metal_hu is not None:
        m_x_lo, m_x_hi = x0, W - 1 - x1
        lo, hi, x_agree, wx, xd_lo, xd_hi = _apply_witness(cor, m_x_lo, m_x_hi)
        x0, x1 = lo, W - 1 - hi
    # top-air z witness: agreement between the ortho planes and the pool
    try:
        if z_wit_top is not None and top_i > 0:
            z_agree = bool(z_wit_ok) and _witness_agree(zs[top_i], z_wit_top,
                                                        voxel_um)
    except Exception:
        z_agree = False

    # clamp + sanity
    y0, y1 = max(0, min(y0, y1)), min(H - 1, max(y0, y1))
    x0, x1 = max(0, min(x0, x1)), min(W - 1, max(x0, x1))
    if y1 <= y0 or x1 <= x0:
        return None

    return {
        "y0": y0, "y1": y1, "x0": x0, "x1": x1,
        "H": H, "W": W, "n": n,
        "zb": {"keep": zb_keep, "cut": zb_cut,
               "wood_top": wood_top, "wood_bottom": wood_bottom,
               "top_ok": zb_keep is not None},
        "anchor": {"ok": anchor_z is not None,
                   "z": [int(anchor_z[0]), int(anchor_z[1])] if anchor_z else None,
                   "guard_applied": bool(guard_applied),
                   "source": anchor_source},
        "margins": {"y": [int(y0), int(H - 1 - y1)],
                    "x": [int(x0), int(W - 1 - x1)]},
        "voxel_um": sc["voxel_um"],
        "scale": sc,
        "evidence": {"axial_slices": len(present),
                     "anchor_z": [int(anchor_z[0]), int(anchor_z[1])] if anchor_z else None,
                     "anchor_source": anchor_source,
                     "quorum": ORTHO_QUORUM,
                     "ortho_cols": ORTHO_COLS,
                     "pool_step_mm": POOL_STEP_MM,
                     "edge_air_max": EDGE_AIR_MAX,
                     "witness_agree_mm": WITNESS_AGREE_MM,
                     "lateral": {"y_witness_agree": bool(y_agree),
                                 "x_witness_agree": bool(x_agree),
                                 "y_defer": [bool(yd_lo), bool(yd_hi)],
                                 "x_defer": [bool(xd_lo), bool(xd_hi)]},
                     "z_top_witness": {"ortho_top": int(z_wit_top) if z_wit_top is not None else None,
                                       "agree": bool(z_agree)},
                     "curtain_top": int(curtain_top) if curtain_top is not None else None,
                     "keep_clear": bool(keep_clear),
                     "fog_defer": bool(fog_defer),
                     "det_anchor": int(det_anchor) if det_anchor is not None else None},
    }
