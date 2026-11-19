#!/usr/bin/env python
"""Viewer cache builder: 2D frames + 3D point cloud from pipeline outputs.

Memory-safe by design: the original volume is sampled slice-wise from the
source DICOMs (a handful of reads), and the stripped volume is accessed
through nibabel's lazy ArrayProxy so only the needed rows/columns are read
from disk — a full float32 volume (~5 GB) is never materialized.

Per sample (built once, reused while outputs stay unchanged):
  * axial frames at log-spaced z  (original | stripped side by side,
    ROI envelope outlined amber, metal>threshold tinted red)
  * sagittal + coronal mid-planes of the stripped volume (cut line drawn)
  * decimated 3D point cloud (wood amber, metal silver) for WebGL
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import threading
import time
from pathlib import Path

import sys
try:
    from core.paths import ensure_engine_on_path, state_root
except ImportError:
    from paths import ensure_engine_on_path, state_root

_PIPELINE = ensure_engine_on_path()
if _PIPELINE.is_dir() and str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

import numpy as np
from PIL import Image, ImageDraw

from tomograph import DATASETS, output_root  # pipeline registry
from roi_delivery import sorted_source_files as _sorted_source_files
from volume_io import inspect_source as _inspect_source_volume
from volume_io import read_source_slices as _read_source_volume_slices
try:                                    # package import (app) or direct (tools)
    from core.lateral import lateral_range
    from core.wood_bounds import wood_bounds
except ImportError:                     # pragma: no cover
    from lateral import lateral_range
    from wood_bounds import wood_bounds

_CACHE: dict[str, dict] = {}
CACHE_VERSION = 22   # v22: payload bounds carry zb.metal_top; Results outlines are smooth (v21 caches are stale)
ORTHO_CACHE_VERSION = 3
# Generated viewer caches always live in the writable per-user state root:
# %LOCALAPPDATA%\cleanCT\cache for installed builds, <checkout>\data\cache
# for development runs (both writable; Program Files stays read-only).
CACHE_DIR = state_root() / "cache"

ORTHO_COL_COUNT = 5   # mid-column stacks read per ortho plane (metal quorum)

N_AXIAL = 16
CLOUD_MAX_POINTS = 62_000
ORIG_SLICE_CACHE: dict[str, dict[int, np.ndarray]] = {}

# Scrubbing keeps a bounded, least-recently-used working set. The byte
# cap matters more than the slice count for high-resolution scans.
ORIG_SLICE_CACHE_MAX_SLICES = 256
ORIG_SLICE_CACHE_MAX_KEYS = 2
ORIG_SLICE_CACHE_MAX_BYTES = 512 * 1024 * 1024  # 512 MiB per specimen

# Full-size DICOM conversions have a temporary decode + float working set.
# Scale concurrent reads down when a slice is large; ordinary ~1200px scans
# retain the existing 16-reader path.
SOURCE_SLICE_WORKING_BUDGET_BYTES = 512 * 1024 * 1024
SOURCE_SLICE_WORKING_BYTES_PER_PIXEL = 8  # decoded + float32 working copy
SCAN_BLOCK_TARGET_BYTES = 128 * 1024 * 1024
SCAN_BLOCK_MAX_SLICES = 32

# Serialises payload/preview cache mutation when loads run on a worker
# thread while the GUI thread renders previews (leak/race guard).
LOCK = threading.RLock()

# DICOM decode pool: 16 parallel readers match the 20-core host (halves
# the wall time of the threaded slice/ortho reads).
_IO_WORKERS = max(8, min(16, os.cpu_count() or 8))

# Memoised XY file listings: the detection curtain/edge walks read one
# slice at a time and would otherwise re-glob the ~1000-file directory
# on EVERY single-slice read (hundreds of redundant directory scans).
_XY_FILES: dict[str, list[Path]] = {}
_SLICE_SHAPES: dict[str, tuple[int, int]] = {}


def _source_metadata(ds) -> dict:
    """Return the registered non-DICOM source descriptor."""
    info = dict(getattr(ds, "source_metadata", {}) or {})
    if info:
        return info
    source = getattr(ds, "source_path", None)
    if source is None:
        raise FileNotFoundError("registered volume has no source path")
    info = _inspect_source_volume(source)
    return info


def _source_cache_token(ds) -> str:
    if getattr(ds, "source_kind", "dicom") == "dicom":
        return "dicom"
    signature = (_source_metadata(ds).get("source_signature") or {})
    return str(signature.get("sha256") or "unfingerprinted")[:16]


def source_identity(ds, sample: str) -> str:
    """Digest of what a registered scan points at right now: the resolved
    folder or file, its size and its modification time. Built-in datasets
    have fixed folders and return "". A specimen ID re-registered to another
    folder changes this value, so cached views of the old scan are not reused.
    """
    if getattr(ds, "key", None) != "custom":
        return ""
    if getattr(ds, "source_kind", "dicom") == "dicom":
        candidate = Path(ds.source) / sample / "XY"
    else:
        candidate = Path(getattr(ds, "source_path", None) or "")
    try:
        status = candidate.stat()
        text = f"{candidate.resolve()}|{status.st_size}|{status.st_mtime_ns}"
    except OSError:
        text = f"{candidate}|missing"
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def _prune_disk_cache(dataset: str, sample: str, kind: str, keep: Path) -> None:
    """Delete superseded cache files for one specimen and kind, and temp
    files left by killed writes (older than an hour).

    ``kind`` is "payload" (preview payloads) or "ortho" (ortho columns).
    Without this, the cache folder grows by one file per source change and
    per cache-version bump, and nothing removes the superseded ones.
    """
    stem = f"{dataset}~{sample}~"
    cutoff = time.time() - 3600
    try:
        entries = list(CACHE_DIR.iterdir())
    except OSError:
        return
    for path in entries:
        name = path.name
        try:
            if name.endswith(".tmp.npz"):
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                continue
            if name.endswith(".npz") and "~" not in name:
                path.unlink()             # older naming: regenerable, never reused
                continue
            if (path == keep or not name.startswith(stem)
                    or not name.endswith(".npz")):
                continue
            if ("_orig_v" in name) == (kind == "ortho"):
                path.unlink()
        except OSError:
            continue


def forget_specimen(sample: str, dataset: str = "custom") -> None:
    """Drop the in-memory views of a specimen ID that was removed or renamed."""
    prefix = f"{dataset}/{sample}"
    for store in (_XY_FILES, _SLICE_SHAPES, ORIG_SLICE_CACHE, _CACHE, _PREV):
        for key in [k for k in store if k == prefix or k.startswith(prefix + ":")]:
            store.pop(key, None)


def _source_cache_key(ds, sample: str) -> str:
    base = f"{ds.key}/{sample}"
    if getattr(ds, "source_kind", "dicom") != "dicom":
        base = f"{base}:{_source_cache_token(ds)}"
    identity = source_identity(ds, sample)
    return f"{base}:{identity}" if identity else base


def _xy_files(ds, sample: str) -> list[Path]:
    key = _source_cache_key(ds, sample)
    files = _XY_FILES.get(key)
    if files is None:
        # The processing pipeline indexes slices by physical position, not
        # by filename. User-loaded scans are often named by acquisition
        # order, so a filename sort can silently pair viewer slice z with the
        # wrong source image even though processing and export are correct.
        sample_dir = ds.source / sample
        if (sample_dir / "XY").is_dir():
            files = _sorted_source_files(sample_dir)
        else:
            files = []
        if len(_XY_FILES) >= 8:
            _XY_FILES.clear()
            _SLICE_SHAPES.clear()
        _XY_FILES[key] = files
    return files


def _source_slice_shape(ds, sample: str) -> tuple[int, int]:
    key = _source_cache_key(ds, sample)
    shape = _SLICE_SHAPES.get(key)
    if shape is not None:
        return shape
    if getattr(ds, "source_kind", "dicom") != "dicom":
        info = _source_metadata(ds)
        shape = int(info["shape_zyx"][1]), int(info["shape_zyx"][2])
        if len(_SLICE_SHAPES) >= 8:
            _SLICE_SHAPES.clear()
        _SLICE_SHAPES[key] = shape
        return shape
    files = _xy_files(ds, sample)
    if not files:
        return 0, 0
    import pydicom
    header = pydicom.dcmread(files[0], stop_before_pixels=True)
    shape = int(header.Rows), int(header.Columns)
    if len(_SLICE_SHAPES) >= 8:
        _SLICE_SHAPES.clear()
    _SLICE_SHAPES[key] = shape
    return shape


def _source_batch_size_for_shape(rows: int, columns: int,
                                 max_items: int | None = None) -> int:
    pixels = max(1, int(rows)) * max(1, int(columns))
    estimated_working_bytes = pixels * SOURCE_SLICE_WORKING_BYTES_PER_PIXEL
    budget_items = max(1, SOURCE_SLICE_WORKING_BUDGET_BYTES
                       // estimated_working_bytes)
    limit = _IO_WORKERS if max_items is None else max(1, int(max_items))
    return max(1, min(_IO_WORKERS, limit, int(budget_items)))


def _source_batch_size(ds, sample: str, max_items: int | None = None) -> int:
    rows, columns = _source_slice_shape(ds, sample)
    return _source_batch_size_for_shape(rows, columns, max_items)


def _scan_block_slices_for_shape(nx: int, ny: int, nz: int,
                                 target_bytes: int = SCAN_BLOCK_TARGET_BYTES,
                                 max_slices: int = SCAN_BLOCK_MAX_SLICES) -> int:
    """Bound decoded NIfTI scan blocks as volume resolution increases."""
    plane_bytes = max(1, int(nx)) * max(1, int(ny)) * np.dtype(np.float32).itemsize
    budget_slices = max(1, int(target_bytes) // plane_bytes)
    return max(1, min(max(1, int(nz)), max(1, int(max_slices)),
                      int(budget_slices)))


def _rescale_pixels(pixels: np.ndarray, slope: float,
                    intercept: float) -> np.ndarray:
    # Rescale one decoded slice without allocating multiply/add temporaries.
    out = np.asarray(pixels).astype(np.float32, copy=False)
    if not out.flags.writeable:
        out = out.copy()
    if slope != 1.0:
        np.multiply(out, float(slope), out=out)
    if intercept != 0.0:
        np.add(out, float(intercept), out=out)
    return out


def _get_ds(dataset: str, sample: str):
    if dataset == "custom":
        # The module lives at core/custom_series.py — import it through the
        # package (with a direct-import fallback for flat layouts).
        # "import custom_series" can never resolve from inside the app and
        # crashed every custom-specimen load with ModuleNotFoundError.
        try:
            from core import custom_series as csx
        except ImportError:                     # pragma: no cover
            import custom_series as csx
        import tomograph as tg
        entry = csx.registered_specimens().get(sample) or {}
        return tg.DatasetSpec(
            key="custom",
            source=csx.DATA_DIR,
            out_sub="custom",
            ground_truth={},
            config_overrides=entry.get("config_overrides") or {},
            source_kind=str(entry.get("source_kind") or "dicom"),
            source_path=(Path(entry["source_path"])
                         if entry.get("source_path") else None),
            source_metadata=dict(entry.get("source_metadata") or {}),
        )
    return DATASETS[dataset]


# --------------------------------------------------------------------------
# io helpers
# --------------------------------------------------------------------------
def _nii_path(sample_dir: Path, which: str) -> Path:
    p = sample_dir / f"{which}.nii"
    return p if p.exists() else sample_dir / f"{which}.nii.gz"


def _proxy(sample_dir: Path, which: str):
    """Lazy nibabel proxy — supports [z, y, x] slicing without full load."""
    import nibabel as nib
    return nib.load(_nii_path(sample_dir, which)).dataobj


def _source_slices(ds, sample: str, zs: list[int], *,
                   cache: bool = True) -> dict[int, np.ndarray]:
    """Read requested original slices with memory-sized concurrency.

    Results are a call-local snapshot. Cache entries are LRU-bounded by count
    and bytes; slices larger than the cache budget are returned to this caller
    without being retained globally.
    """
    cache_key = _source_cache_key(ds, sample)
    series_cache = ORIG_SLICE_CACHE.get(cache_key)
    if series_cache is None:
        series_cache = {}
        if cache:
            ORIG_SLICE_CACHE[cache_key] = series_cache
    else:
        ORIG_SLICE_CACHE.pop(cache_key)
        ORIG_SLICE_CACHE[cache_key] = series_cache

    result: dict[int, np.ndarray] = {}
    for z in zs:
        arr = series_cache.pop(z, None)
        if arr is not None:
            series_cache[z] = arr
            result[z] = arr

    missing = sorted({int(z) for z in zs if int(z) not in result})
    if missing:
        if getattr(ds, "source_kind", "dicom") != "dicom":
            info = _source_metadata(ds)
            loaded = _read_source_volume_slices(ds.source_path, missing,
                                                metadata=info)
            result.update(loaded)
        else:
            import pydicom
            from concurrent.futures import ThreadPoolExecutor
            files = _xy_files(ds, sample)
            if not files:
                raise RuntimeError(
                    f"loaded specimen {sample!r} has no readable source "
                    "series — load the source folder again")
            top = max(missing)
            if top >= len(files):
                raise RuntimeError(
                    f"slice {top} is outside the registered source series "
                    f"({len(files)} slices) for {sample!r}")

            def _read(z: int):
                d = pydicom.dcmread(files[z])
                arr = _rescale_pixels(
                    d.pixel_array,
                    float(getattr(d, "RescaleSlope", 1.0)),
                    float(getattr(d, "RescaleIntercept", 0.0)),
                )
                return z, arr

            workers = min(len(missing), _source_batch_size(ds, sample, len(missing)))
            with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
                result.update(dict(ex.map(_read, missing)))
        for z in missing:
            arr = result[z]
            if cache and arr.nbytes <= ORIG_SLICE_CACHE_MAX_BYTES:
                series_cache[z] = arr
                cached_bytes = sum(a.nbytes for a in series_cache.values())
                while (len(series_cache) > ORIG_SLICE_CACHE_MAX_SLICES or
                       cached_bytes > ORIG_SLICE_CACHE_MAX_BYTES):
                    oldest = next(iter(series_cache))
                    removed = series_cache.pop(oldest)
                    cached_bytes -= removed.nbytes

    while len(ORIG_SLICE_CACHE) > ORIG_SLICE_CACHE_MAX_KEYS:
        ORIG_SLICE_CACHE.pop(next(iter(ORIG_SLICE_CACHE)), None)
    return {int(z): result[int(z)] for z in zs if int(z) in result}


def _mtime_key(sample_dir: Path) -> str:
    h = hashlib.md5()
    for w in ("stripped", "wood_roi"):
        p = _nii_path(sample_dir, w)
        if p.exists():
            h.update(f"{p.name}:{p.stat().st_mtime_ns}".encode())
    return h.hexdigest()[:12]


# --------------------------------------------------------------------------
# rendering primitives
# --------------------------------------------------------------------------
def _b64(img: Image.Image, jpeg: bool = True) -> str:
    buf = io.BytesIO()
    if jpeg:
        img.save(buf, format="JPEG", quality=85)   # ~8x smaller than PNG
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


_STOPS = np.array([[16, 18, 24], [48, 54, 70], [96, 102, 122],
                   [168, 168, 168], [238, 232, 220]], np.float32) / 255.0


def _rgb(u: np.ndarray) -> np.ndarray:
    """Bone-like colormap, u in [0,1]."""
    t = np.clip(u, 0, 1)[..., None] * (len(_STOPS) - 1)
    # the segment is found from floor(t) and the fraction taken from it, so u = 1 gives the last stop
    i0 = np.clip(np.floor(t).astype(np.int32), 0, len(_STOPS) - 2)[..., 0]
    f = (t - i0[..., None])[..., 0]
    return _STOPS[i0] * (1 - f[..., None]) + _STOPS[i0 + 1] * f[..., None]


def _u8(a: np.ndarray, lo: float, hi: float) -> np.ndarray:
    a = np.nan_to_num(np.asarray(a, np.float32), nan=float(lo))
    return np.clip((a - lo) / max(hi - lo, 1e-6), 0.0, 1.0)


def _tint(rgb: np.ndarray, mask: np.ndarray, color, strength: float):
    m = mask[..., None]
    c = np.array(color, np.float32)
    return rgb * (1 - m * strength) + c * (m * strength)


def _frame_img(rgb: np.ndarray, width: int) -> Image.Image:
    h, w = rgb.shape[:2]
    img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), "RGB")
    if w > 2 * width:
        # ultra-high-res frames: a single BOX-reduce step to just above the
        # target before LANCZOS is several times faster than one giant
        # LANCZOS, with imperceptible quality difference.  (Image.REDUCE
        # was removed in Pillow 10 — under Pillow 12 it raised AttributeError
        # and killed every custom-specimen frame build with slices more
        # than twice the frame width; Image.Resampling.BOX is the enum for
        # the identical filter and exists on every supported Pillow.)
        img = img.resize((2 * width, int(h * 2 * width / w)),
                         Image.Resampling.BOX)
    return img.resize((width, int(h * width / w)), Image.Resampling.LANCZOS)


def _pick_slices(n: int, k: int = N_AXIAL) -> list[int]:
    if n <= k:
        return list(range(n))
    zs = {0, n - 1}
    zs |= {round((n - 1) * (math.exp(t / (k - 1)) - 1) / (math.e - 1))
           for t in range(k)}
    return sorted(z for z in zs if 0 <= z < n)[:k]


# --------------------------------------------------------------------------
# windows
# --------------------------------------------------------------------------
def _win_from_report(report: dict, sample_slice: np.ndarray) -> tuple[float, float, float]:
    meta = report["meta"]
    slope = float(meta.get("rescale_slope", 1.0))
    intercept = float(meta.get("rescale_intercept", 0.0))
    # wood HU window from config, widened for context
    cfg = report.get("config", {})
    lo = float(cfg.get("wood_hu_min", -990)) - 120
    hi = float(cfg.get("wood_hu_max", -500)) + 200
    metal_lo = float(cfg.get("metal_hu", 0.0))
    _ = (slope, intercept, sample_slice)
    return lo, hi, metal_lo


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------
def _wood_mask(strip_sl: np.ndarray, cfg: dict) -> np.ndarray:
    """Binary wood mask for one slice (same window as the ROI tracker)."""
    lo_w = float(cfg.get("wood_hu_min", -990))
    hi_w = float(cfg.get("wood_hu_max", -500))
    m = np.isfinite(strip_sl) & (strip_sl > lo_w) & (strip_sl < hi_w)
    if m.any():                                  # keep the largest component
        from scipy import ndimage as ndi
        lab, n = ndi.label(m)
        if n > 1:
            sizes = np.bincount(lab.ravel())
            sizes[0] = 0
            m = lab == sizes.argmax()
    return m


def _draw_contours(img: Image.Image, mask: np.ndarray, scale: float,
                   color, width: int = 2, x_off: int = 0, sigma: float = 3.0):
    """Draw a mask's outline as a clean line on the true edge.

    The mask is blurred before the contour is taken, so speckle at the edge
    does not show, and the line is simplified so it is not stair-stepped.
    (The old block coarsening pushed each outline out by up to a block.)"""
    from scipy import ndimage as ndi
    from skimage import measure
    smooth = ndi.gaussian_filter(mask.astype(np.float32), sigma)
    d = ImageDraw.Draw(img)
    for c in measure.find_contours(smooth, 0.5):
        if len(c) < 30:                           # specks and fragments
            continue
        c = measure.approximate_polygon(c, tolerance=1.5)
        pts = [(p[1] * scale + x_off, p[0] * scale) for p in c]
        if len(pts) > 2:
            d.line(pts, fill=color, width=width, joint="curve")


def _axial_pair(orig_sl: np.ndarray, strip_sl: np.ndarray, lo, hi, metal_lo,
                roi_box, cfg, size: int = 460) -> Image.Image:
    wood_m = _wood_mask(strip_sl, cfg)
    metal_m = np.isfinite(orig_sl) & (orig_sl > metal_lo)
    panels = []
    for vol_sl, is_orig in ((orig_sl, True), (strip_sl, False)):
        rgb = _rgb(_u8(vol_sl, lo, hi))
        if not is_orig:
            met_s = np.isfinite(vol_sl) & (vol_sl > metal_lo)
            if met_s.any():
                rgb = _tint(rgb, met_s, (1.0, 0.25, 0.2), 0.65)
        panels.append(rgb)
    h, w = panels[0].shape[:2]
    pw = int(w * size / h)
    canvas = Image.new("RGB", (pw * 2 + 10, size), (13, 15, 20))
    for i, rgb in enumerate(panels):
        canvas.paste(_frame_img(rgb, pw), (i * (pw + 10), 0))
    sc = size / h
    # specimen outline (amber) on both panels; metal contour (red) on original
    if wood_m.mean() > 0.02:                      # only where wood dominates
        _draw_contours(canvas, wood_m, sc, (255, 176, 32), 2, 0)
        _draw_contours(canvas, wood_m, sc, (255, 176, 32), 2, pw + 10)
    if metal_m.mean() > 0.001:
        _draw_contours(canvas, metal_m, sc, (255, 70, 60), 2, 0)
    d = ImageDraw.Draw(canvas)
    if roi_box:
        y0, y1, x0, x1 = roi_box
        for off in (0, pw + 10):
            d.rectangle((x0 * sc + off, y0 * sc, x1 * sc + off, y1 * sc),
                        outline=(255, 176, 32, 120), width=1)
    d.text((10, 8), "ORIGINAL", fill=(185, 195, 210))
    d.text((pw + 20, 8), "STRIPPED (platform removed)", fill=(255, 120, 110))
    return canvas


def _longitudinal(sag: np.ndarray, cor: np.ndarray, cut_from: int,
                  lo, hi, width: int = 980) -> tuple[Image.Image, Image.Image]:
    """Build side-by-side Before/After cleaning longitudinal mid-plane images."""
    out = []
    for sl in (sag, cor):
        sl_orig = np.asarray(sl, np.float32)
        # After cleaning: platform below cut slice is cleanly removed
        sl_clean = np.where(np.arange(sl.shape[0])[:, None] < cut_from, sl_orig, np.nan)

        rgb_orig = _rgb(_u8(sl_orig, lo, hi))
        rgb_clean = _rgb(_u8(sl_clean, lo, hi))

        h, w = rgb_orig.shape[:2]
        target_h = int(width * 0.45)
        pw = int(w * target_h / h)
        canvas = Image.new("RGB", (pw * 2 + 10, target_h), (13, 15, 20))
        canvas.paste(_frame_img(rgb_orig, pw), (0, 0))
        canvas.paste(_frame_img(rgb_clean, pw), (pw + 10, 0))

        sc = target_h / sl.shape[0]
        y = cut_from * sc
        d = ImageDraw.Draw(canvas)
        for off in (0, pw + 10):
            for x in range(0, pw, 18):
                d.line((x + off, y, x + 10 + off, y), fill=(255, 70, 60), width=3)
        d.text((10, 8), "BEFORE (Original)", fill=(185, 195, 210))
        d.text((pw + 20, 8), "AFTER (Stripped)", fill=(120, 220, 160))
        out.append(canvas)
    return out[0], out[1]


def _scan(proxy, metal_lo: float, target: int = CLOUD_MAX_POINTS):
    """One sequential sweep over the volume (disk order is (x, y, z), so
    z-blocks are contiguous): extracts the sagittal/coronal mid-plane lines
    and the wood/metal cloud candidates in a single pass."""
    nx, ny, nz = proxy.shape
    x_mid, y_mid = nx // 2, ny // 2
    sag = np.empty((nz, ny), np.float32)          # rows z, cols y
    cor = np.empty((nz, nx), np.float32)          # rows z, cols x
    step = max(2, int(round((nz * ny * nx / 4e6) ** (1 / 3) * 2)))
    wood_parts: list[np.ndarray] = []
    wood_vals: list[np.ndarray] = []
    metal_parts: list[np.ndarray] = []
    # A fixed 32-plane block is fast for ordinary scans but can exceed 4 GiB
    # at 6000 x 6000. Scale the block down to a bounded working set.
    B = _scan_block_slices_for_shape(nx, ny, nz)
    for z0 in range(0, nz, B):
        z1 = min(nz, z0 + B)
        blk = np.asarray(proxy[:, :, z0:z1], dtype=np.float32)   # (x, y, B)
        sag[z0:z1] = blk[x_mid].T                 # (B, ny)
        cor[z0:z1] = blk[:, y_mid].T              # (B, nx)
        sub = blk[::step, ::step, ::step]
        wm = np.isfinite(sub) & (sub > -900) & (sub < -150)
        mm = np.isfinite(sub) & (sub > metal_lo)
        xi, yi, zi = np.nonzero(wm)
        if len(xi):
            wood_parts.append(np.stack([zi * step + z0, yi * step,
                                        xi * step], 1))
            wood_vals.append(sub[wm])
        xi, yi, zi = np.nonzero(mm)
        if len(xi):
            metal_parts.append(np.stack([zi * step + z0, yi * step,
                                         xi * step], 1))
    wv = (np.concatenate(wood_vals) if wood_vals
          else np.empty((0,), np.float32))
    wood = (np.concatenate(wood_parts) if wood_parts
            else np.empty((0, 3), np.int64))
    metal = (np.concatenate(metal_parts) if metal_parts
             else np.empty((0, 3), np.int64))
    rng = np.random.default_rng(7)
    want_w = int(target * 0.6)
    if len(wood) > want_w:
        keep = rng.choice(len(wood), want_w, replace=False)
        wood, wv = wood[keep], wv[keep]
    want_m = int(target * 0.15)
    if len(metal) > want_m:
        metal = metal[rng.choice(len(metal), want_m, replace=False)]
    # value ramp for shading (clamped wood window -> 0..255)
    if len(wv):
        wv8 = np.clip((wv + 990.0) / 490.0 * 255.0, 0, 255)
    else:
        wv8 = wv.astype(np.uint8)
    return sag, cor, wood, wv8.astype(np.uint8), metal, step


# --------------------------------------------------------------------------
# report summary
# --------------------------------------------------------------------------
def _metal_points(ds, sample: str, cut_from: int, n_slices: int,
                  step: int, metal_lo: float,
                  target: int) -> np.ndarray:
    """Metal points from sampled original slices; release each bounded batch."""
    if cut_from >= n_slices:
        return np.empty((0, 3), np.int64)
    zs = list(range(cut_from, n_slices, step))
    if zs[-1] != n_slices - 1:
        zs.append(n_slices - 1)
    pts = []
    batch_size = _source_batch_size(ds, sample, len(zs))
    for start in range(0, len(zs), batch_size):
        batch = zs[start:start + batch_size]
        orig = _source_slices(ds, sample, batch, cache=False)
        for z in batch:
            sl = orig[z][::step, ::step]
            m = np.isfinite(sl) & (sl > metal_lo)
            yi, xi = np.nonzero(m)
            if len(yi):
                pts.append(np.stack([np.full(len(yi), z), yi * step,
                                     xi * step], 1))
        del orig
    if not pts:
        return np.empty((0, 3), np.int64)
    arr = np.concatenate(pts)
    if len(arr) > target:
        arr = arr[np.random.default_rng(7).choice(len(arr), target,
                                                  replace=False)]
    return arr


def _report_summary(r: dict) -> dict:
    p = r.get("platform", {})
    t = r.get("wood_roi", {}).get("track", {})
    m = r.get("metrics", {})
    meta = r.get("meta", {})
    # calibrated 2D window for this specimen (same formula as
    # _win_from_report): the Threshold Reset baseline in the app
    cfg = r.get("config", {})
    value_range = cfg.get("intensity_range_estimate")
    if not value_range:
        stats = meta.get("intensity_sample_percentiles") or {}
        if "p02" in stats and "p995" in stats:
            value_range = [stats["p02"], stats["p995"]]
    return {
        "sample": r.get("sample"), "dataset": r.get("dataset"),
        "source_kind": meta.get("source_kind", "dicom"),
        "intensity_unit": meta.get("intensity_unit", "HU"),
        "value_range": value_range,
        "n_slices": meta.get("n_slices"),
        "voxel_mm": float(meta.get("pixel_spacing_yx_mm", [0])[0]) * 1000,
        "win_lo": float(cfg.get("wood_hu_min", -990.0)) - 120.0,
        "win_hi": float(cfg.get("wood_hu_max", -500.0)) + 200.0,
        "cut_from": p.get("cut_from"), "anchor": p.get("anchor_slice"),
        "accepted_by": p.get("accepted_by"),
        "detected_cut_from": p.get("detected_cut_from"),
        "keep_from": p.get("keep_from"),
        "cut_margin_slices": r.get("config", {}).get("cut_margin_slices"),
        "baseline_hu": p.get("baseline_hu"),
        "removed_fraction": m.get("removed_fraction"),
        "voxels_removed": m.get("voxels_removed"),
        "roi_z": [t.get("z0"), t.get("z1")],
        "roi_n_slices": t.get("n_slices_tracked"),
        "gpu": r.get("gpu", {}), "timings_s": r.get("timings_s", {}),
        "ground_truth": r.get("ground_truth"),
        "platform": p,
    }


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def _cache_stem(key: str) -> str:
    """File-name form of a cache key. "~" separates the parts because sample
    IDs may contain "_" (a "_" separator made specimen "x" match "x_y")."""
    return key.replace("/", "~").replace(":", "~")


def _disk_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = _cache_stem(key)
    return CACHE_DIR / (safe + ".npz")


def _cloud_binary(cloud: dict) -> tuple[bytes, dict]:
    """Pack the cloud as uint16 xyz triplets (shape<=65535 per axis)."""
    shape = cloud["shape"]
    parts = []
    for name in ("wood", "metal"):
        arr = np.asarray(cloud[name], np.uint16).reshape(-1)
        parts.append(arr)
    meta = {"wood_n": int(len(cloud["wood"])),
            "metal_n": int(len(cloud["metal"]))}
    return np.concatenate(parts).tobytes(), meta


def build_payload(dataset: str, sample: str, use_disk: bool = True) -> dict:
    """Thread-safe facade: the payload build (caches + disk IO) is
    serialised so a worker-thread load can never race a GUI-thread
    preview render on the shared caches."""
    with LOCK:
        return _build_payload_locked(dataset, sample, use_disk)


def _minimal_payload(dataset: str, sample: str, ds) -> dict:
    """Graceful payload for a specimen that has NOT been processed yet (no
    report.json / stripped.nii — the normal state right after registering a
    custom series).  The app renders empty viewers, dashes in the header and
    a 'process first' hint instead of crashing the load."""
    intensity_unit = "HU"
    value_range = None
    try:
        if getattr(ds, "source_kind", "dicom") == "dicom":
            files = _xy_files(ds, sample)
            n = len(files)
            first = pydicom_hdr(ds, sample)
            voxel_um = float(first.PixelSpacing[0]) * 1000.0
        else:
            info = _source_metadata(ds)
            n = int(info["shape_zyx"][0])
            voxel_um = float(info["pixel_spacing_yx_mm"][0] or 0) * 1000.0
            intensity_unit = str(info.get("intensity_unit") or "stored values")
            stats = info.get("intensity_sample_percentiles") or {}
            if "p02" in stats and "p995" in stats:
                value_range = [stats["p02"], stats["p995"]]
    except Exception:
        n, voxel_um = 0, 0.0
    window = (-950.0, 350.0)
    if getattr(ds, "source_kind", "dicom") != "dicom":
        try:
            scan = _scan_meta(ds, sample)
            window = (float(scan["win_lo"]), float(scan["win_hi"]))
        except Exception:
            pass
    return {
        "key": f"{dataset}/{sample}:unprocessed",
        "sample": sample, "dataset": dataset,
        "source_kind": getattr(ds, "source_kind", "dicom"),
        "intensity_unit": intensity_unit,
        "report": {"sample": sample, "dataset": dataset,
                   "n_slices": n, "voxel_mm": voxel_um,
                   "source_kind": getattr(ds, "source_kind", "dicom"),
                   "intensity_unit": intensity_unit,
                   "value_range": value_range,
                   "processed": False,
                   "win_lo": window[0], "win_hi": window[1]},
        "frames": [], "sagittal": "", "coronal": "",
        "cut_from": 0, "voxel_mm": voxel_um,
        "cloud": {"wood": [], "metal": [], "shape": [1, 1, 1], "step": 1},
        "gpu": {}, "bounds": None, "unprocessed": True,
    }


def pydicom_hdr(ds, sample: str):
    """First DICOM header of a series (memoised; headers only)."""
    import pydicom
    files = _xy_files(ds, sample)
    return pydicom.dcmread(files[0], stop_before_pixels=True)


def _build_payload_locked(dataset: str, sample: str, use_disk: bool = True) -> dict:
    ds = _get_ds(dataset, sample)
    sdir = output_root(ds) / sample
    if not (sdir / "report.json").exists():
        # registered but not processed (typical fresh custom specimen):
        # degrade gracefully instead of crashing the load
        payload = _minimal_payload(dataset, sample, ds)
        # Pre-process detection: the user must be able to CHECK the
        # air-top / metal-top guides BEFORE committing to a run.  The
        # shared _PREV source computes exactly this (scan-native geometry
        # + full-voxel detection) and caches it — reuse it here so the
        # payload and the preferences preview show the same lines.
        try:
            b = _prev_source(dataset, sample).get("bounds")
            if b:
                payload["bounds"] = b
                payload["unprocessed_bounds"] = True
        except Exception:
            pass
        return payload
    key = (f"{dataset}/{sample}:{_mtime_key(sdir)}:"
           f"src{_source_cache_token(ds)}:id{source_identity(ds, sample)}"
           f":v{CACHE_VERSION}")
    hit = _CACHE.get(key)
    if hit:
        return hit
    dp = _disk_path(key)
    if use_disk and dp.exists():
        try:
            with np.load(dp, allow_pickle=False) as z:
                payload = json.loads(str(z["payload"]))
                pts = z["cloud"]
            wn, mn = payload["cloud"]["wood_n"], payload["cloud"]["metal_n"]
            u16 = np.frombuffer(pts, np.uint16)
            payload["cloud"]["wood"] = u16[: wn * 3].reshape(-1, 3).tolist()
            payload["cloud"]["metal"] = (u16[wn * 3: (wn + mn) * 3]
                                         .reshape(-1, 3).tolist())
            payload["cloud"].pop("wood_n", None)
            payload["cloud"].pop("metal_n", None)
            payload["cloud"]["packed"] = True
            payload["disk_hit"] = True
            if payload.get("bounds") is None:
                # self-heal caches written before the bounds field existed
                try:
                    rep = json.loads((sdir / "report.json").read_text())
                    sag_o, cor_o, sagc_o, corc_o = _ortho_columns_cached(
                        ds, sample, sdir)
                    t = rep.get("wood_roi", {}).get("track", {}) or {}
                    cfg = rep.get("config", {})
                    sp = (rep.get("meta", {}).get("pixel_spacing_yx_mm") or [None])
                    payload["bounds"] = wood_bounds(
                        ds, sample, n_slices=int(rep["meta"]["n_slices"]),
                        cut_from=int(rep["platform"]["cut_from"]),
                        sag=sagc_o if sagc_o is not None else sag_o,
                        cor=corc_o if corc_o is not None else cor_o,
                        metal_hu=float(cfg.get("metal_hu", 0.0)),
                        track_z=(t.get("z0"), t.get("z1")),
                        voxel_um=(float(sp[0]) * 1000.0 if sp and sp[0] else None),
                        wood_hu=(float(cfg.get("wood_hu_min", -990.0)),
                                 float(cfg.get("wood_hu_max", -500.0))),
                        det_anchor=rep["platform"].get("anchor_slice"),
                        det_cut=int(rep["platform"].get("detected_cut_from")
                                    or rep["platform"]["cut_from"]),
                        z_step_um=(float(rep["meta"].get("slice_thickness_mm",
                                                          0.0)) * 1000.0))
                except Exception:
                    payload["bounds"] = None
            _CACHE.clear()
            _CACHE[key] = payload
            return payload
        except Exception:
            pass  # fall through to rebuild

    report = json.loads((sdir / "report.json").read_text())
    cut_from = int(report["platform"]["cut_from"])
    n_slices = int(report["meta"]["n_slices"])
    track = report.get("wood_roi", {}).get("track", {})
    roi_box = ((track.get("y0"), track.get("y1"),
                track.get("x0"), track.get("x1")) if track else None)

    strip = _proxy(sdir, "stripped")
    # window calibration from one real slice (disk order is (x, y, z))
    cal = np.asarray(strip[:, :, n_slices // 2], np.float32)
    lo, hi, metal_lo = _win_from_report(report, cal)

    zs = [z for z in _pick_slices(n_slices) if z < cut_from + 30]

    (sag_lines, cor_lines, wood, wood_vals,
     metal_from_strip, step) = _scan(strip, metal_lo)
    metal = _metal_points(ds, sample, cut_from, n_slices, step, metal_lo,
                          int(CLOUD_MAX_POINTS * 0.15))
    # Metal-anchored, air-refined wood bounds (metal priority: the ortho
    # columns anchor the base via the quorum slab test fused with the
    # pipeline detector anchor; air evidence pooled from all planes).
    try:
        sag_o, cor_o, sagc_o, corc_o = _ortho_columns_cached(ds, sample, sdir)
        cfg = report.get("config", {})
        sp = (report.get("meta", {}).get("pixel_spacing_yx_mm") or [None])
        bounds = wood_bounds(ds, sample, n_slices=n_slices, cut_from=cut_from,
                             sag=(sagc_o if sagc_o is not None else sag_o),
                             cor=(corc_o if corc_o is not None else cor_o),
                             metal_hu=metal_lo,
                             track_z=(track.get("z0"), track.get("z1")),
                             voxel_um=(float(sp[0]) * 1000.0 if sp and sp[0] else None),
                             wood_hu=(float(cfg.get("wood_hu_min", -990.0)),
                                      float(cfg.get("wood_hu_max", -500.0))),
                             det_anchor=report.get("platform", {}).get("anchor_slice"),
                             det_cut=int(report.get("platform", {})
                                         .get("detected_cut_from") or cut_from),
                             z_step_um=(float(report["meta"].get(
                                 "slice_thickness_mm", 0.0)) * 1000.0))
    except Exception:
        bounds = None
    frames = []
    frame_batch_size = _source_batch_size(ds, sample, len(zs))
    for start in range(0, len(zs), frame_batch_size):
        batch = zs[start:start + frame_batch_size]
        orig_map = _source_slices(ds, sample, batch)
        for z in batch:
            if z not in orig_map:
                continue
            img = _axial_pair(orig_map[z],
                              np.asarray(strip[:, :, z]).T,   # (x,y,z)->(y,x)
                              lo, hi, metal_lo, roi_box,
                              report.get("config", {}))
            frames.append({"z": int(z), "png": _b64(img)})
        del orig_map

    sag, cor = _longitudinal(sag_lines, cor_lines, cut_from, lo, hi)

    cloud = {"wood": wood.astype(int).tolist(),
             "wood_vals": wood_vals.astype(int).tolist(),
             "metal": metal.astype(int).tolist(),
             "shape": [int(strip.shape[2]), int(strip.shape[1]),
                       int(strip.shape[0])],   # (z, y, x) for the viewer
             "step": int(step)}
    payload = {
        "key": key, "sample": sample, "dataset": dataset,
        "report": _report_summary(report),
        "frames": frames, "sagittal": _b64(sag), "coronal": _b64(cor),
        "cut_from": cut_from,
        "voxel_mm": float(report["meta"]["pixel_spacing_yx_mm"][0]) * 1000,
        "cloud": cloud,
        "gpu": report.get("gpu", {}),
        "bounds": bounds,
    }
    # store compactly on disk: JSON body + binary cloud (uint16 triplets)
    try:
        disk = {k: v for k, v in payload.items() if k != "cloud"}
        disk["cloud"] = {k: v for k, v in cloud.items()
                         if k not in ("wood", "metal")}
        blob, meta = _cloud_binary(cloud)
        disk["cloud"].update(meta)
        tmp = dp.with_name(dp.stem + ".tmp.npz")
        np.savez_compressed(tmp, payload=np.array(json.dumps(disk)),
                            cloud=blob)
        os.replace(tmp, dp)
        _prune_disk_cache(dataset, sample, "payload", dp)
    except Exception:
        pass                                  # cache is best-effort
    for cache_key in list(ORIG_SLICE_CACHE):
        if (cache_key == f"{ds.key}/{sample}" or
                cache_key.startswith(f"{ds.key}/{sample}:")):
            ORIG_SLICE_CACHE.pop(cache_key, None)
    _CACHE.clear()
    _CACHE[key] = payload
    return payload


# ==========================================================================
# Preferences preview: ORIGINAL reconstruction in scientific colormaps
# (spectral rainbow, thermal flame, grayscale CT density, viridis, plasma)
# with interactive cut / collection-range handling and user threshold windowing.
# Bright, vibrant palette curves tailored for high-contrast micro-CT inspection.
# ==========================================================================
_CMAP_STOPS = {
    # High-luminosity Spectral rainbow: vibrant blue -> cyan -> green -> yellow -> red
    "spectral": np.array([
        [15, 60, 210], [0, 140, 255], [0, 235, 235], [60, 255, 110],
        [255, 235, 20], [255, 75, 20], [225, 25, 25]], np.float32) / 255.0,
    # Luminous Thermal / Flame palette
    "thermal": np.array([
        [15, 5, 25], [110, 15, 30], [215, 50, 10], [255, 130, 0],
        [255, 215, 30], [255, 255, 160], [255, 255, 255]], np.float32) / 255.0,
    # High-contrast Tomographic linear density grayscale
    "grayscale": np.array([
        [18, 20, 26], [255, 255, 255]], np.float32) / 255.0,
    # Viridis (perceptually uniform)
    "viridis": np.array([
        [68, 1, 84], [59, 82, 139], [33, 145, 140],
        [94, 201, 98], [253, 231, 37]], np.float32) / 255.0,
    # Plasma (dense tomographic)
    "plasma": np.array([
        [13, 8, 135], [126, 3, 168], [204, 71, 120],
        [248, 149, 64], [240, 249, 33]], np.float32) / 255.0,
}


def _apply_cmap(u: np.ndarray, cmap: str = "spectral", gamma: float = 0.85) -> np.ndarray:
    """Apply scientific colormap with gentle perceptual gamma illumination, u in [0,1]."""
    stops = _CMAP_STOPS.get(cmap.lower(), _CMAP_STOPS["spectral"])
    # Perceptual gamma boost: lifts wood anatomical details out of shadow
    u_lifted = np.clip(u, 0.0, 1.0) ** gamma
    t = u_lifted[..., None] * (len(stops) - 1)
    # u = 1 must give the last stop (the old fraction was 0 there, so full-scale values rendered darkest)
    i0 = np.clip(np.floor(t).astype(np.int32), 0, len(stops) - 2)[..., 0]
    f = (t - i0[..., None])[..., 0]
    return stops[i0] * (1 - f[..., None]) + stops[i0 + 1] * f[..., None]


# ---- per-sample preview source data (LRU, rebuilt from disk on demand) ----
_PREV_MAX = 3
_PREV_MAX_BYTES = 1024 * 1024 * 1024  # 1 GiB total preview arrays
_PREV: dict[str, dict] = {}          # insertion order is the LRU order
PREV_VERSION = 11   # v11: edge-band-gated lateral projections (audit 0AF)

# Scan-native fallback geometry for NOT-processed specimens (no report.json
# yet): the delivery equals the whole scan, and the window is the general
# CT view (wood window widened for context — the same formula _win_from_report
# applies to a processed specimen's config).  UNPROC_WOOD is the engine's
# canonical wood class for the pre-process air-top / metal-top detection.
UNPROC_WIN = (-950.0, 350.0, 0.0)
# Lower bound -960, not -990: on 2_666_5 the jar's halo sits between -990 and
# -960 at the top of the scan (5607 px at slice 30, none above -960), so -990
# put the wood top at slice 11.  Measured wood tops: 2_666_5 at -960 gives 88,
# the yellow line; 2-5 at -960 gives 23 against 19 with the processed bounds.
# shortcut: pre-process only (no pipeline track yet); the processed bounds use the report config.
UNPROC_WOOD = (-960.0, -500.0)


def _prev_key(dataset: str, sample: str, sdir: Path) -> str:
    return f"{dataset}/{sample}:{_mtime_key(sdir)}:p{PREV_VERSION}"


def _preview_array_bytes(src: dict) -> int:
    return sum(int(value.nbytes) for value in src.values()
               if isinstance(value, np.ndarray))


def _evict_prev():
    total = sum(_preview_array_bytes(value) for value in _PREV.values())
    while len(_PREV) > _PREV_MAX or total > _PREV_MAX_BYTES:
        oldest = next(iter(_PREV))
        total -= _preview_array_bytes(_PREV.pop(oldest))


def _store_prev(key: str, src: dict) -> None:
    if _preview_array_bytes(src) > _PREV_MAX_BYTES:
        _PREV.pop(key, None)
        return
    _PREV.pop(key, None)
    _PREV[key] = src
    _evict_prev()


def _orig_ortho_lines(ds, sample: str) -> tuple[np.ndarray, np.ndarray]:
    """Sagittal + coronal mid-lines read slice-wise without volume materialization."""
    if getattr(ds, "source_kind", "dicom") != "dicom":
        info = _source_metadata(ds)
        n, rows, columns = map(int, info["shape_zyx"])
        sag = np.empty((n, rows), np.float32)
        cor = np.empty((n, columns), np.float32)
        batch = max(1, min(16, _source_batch_size_for_shape(rows, columns)))
        for lo in range(0, n, batch):
            zs = list(range(lo, min(n, lo + batch)))
            planes = _read_source_volume_slices(ds.source_path, zs, metadata=info)
            for i in zs:
                px = planes[i]
                sag[i] = px[:, columns // 2]
                cor[i] = px[rows // 2, :]
        return sag, cor
    import pydicom
    from concurrent.futures import ThreadPoolExecutor
    files = _xy_files(ds, sample)
    n = len(files)
    first = pydicom.dcmread(files[0], stop_before_pixels=True)
    rows, columns = int(first.Rows), int(first.Columns)
    sag = np.empty((n, rows), np.float32)
    cor = np.empty((n, columns), np.float32)

    def _read(i: int):
        d = pydicom.dcmread(files[i])
        px = _rescale_pixels(
            d.pixel_array,
            float(getattr(d, "RescaleSlope", 1.0)),
            float(getattr(d, "RescaleIntercept", 0.0)),
        )
        return i, px[:, columns // 2], px[rows // 2, :]

    with ThreadPoolExecutor(max_workers=_source_batch_size(ds, sample, n)) as ex:
        for i, col, row in ex.map(_read, range(n)):
            sag[i] = col
            cor[i] = row
    return sag, cor


def _orig_ortho_columns(ds, sample: str, ncols: int = ORTHO_COL_COUNT,
                        *, include_midlines: bool = False):
    # Read multi-column sagittal/coronal profiles from each source slice.
    # Sagittal profiles sample image columns and run along Rows (Y); coronal
    # profiles sample image rows and run along Columns (X). Both center profiles
    # are included so a cold cache needs only one DICOM series pass.
    if getattr(ds, "source_kind", "dicom") != "dicom":
        info = _source_metadata(ds)
        n, rows, columns = map(int, info["shape_zyx"])

        def mid_span(size: int) -> list[int]:
            lo, hi = size * 0.25, size * 0.75
            idx = sorted({min(size - 1, max(0, int(round(v))))
                          for v in np.linspace(lo, hi, ncols)})
            if size // 2 not in idx:
                idx = sorted(idx + [size // 2])
            return idx

        x_cols, y_rows = mid_span(columns), mid_span(rows)
        sag_center, cor_center = x_cols.index(columns // 2), y_rows.index(rows // 2)
        sag_cols = np.empty((n, len(x_cols), rows), np.float32)
        cor_cols = np.empty((n, len(y_rows), columns), np.float32)
        sag = np.empty((n, rows), np.float32)
        cor = np.empty((n, columns), np.float32)
        batch = max(1, min(16, _source_batch_size_for_shape(rows, columns)))
        for start in range(0, n, batch):
            zs = list(range(start, min(n, start + batch)))
            planes = _read_source_volume_slices(ds.source_path, zs, metadata=info)
            for i in zs:
                px = planes[i]
                sag_i = np.stack([px[:, c] for c in x_cols], axis=1)
                cor_i = np.stack([px[r, :] for r in y_rows], axis=0)
                sag_cols[i] = sag_i.T
                cor_cols[i] = cor_i
                sag[i] = sag_i[:, sag_center]
                cor[i] = cor_i[cor_center, :]
        if include_midlines:
            return sag, cor, sag_cols, cor_cols
        return sag_cols, cor_cols

    import pydicom
    from concurrent.futures import ThreadPoolExecutor
    files = _xy_files(ds, sample)
    n = len(files)
    first = pydicom.dcmread(files[0], stop_before_pixels=True)
    rows, columns = int(first.Rows), int(first.Columns)

    def mid_span(size: int) -> list[int]:
        lo, hi = size * 0.25, size * 0.75
        idx = sorted({min(size - 1, max(0, int(round(v))))
                      for v in np.linspace(lo, hi, ncols)})
        if size // 2 not in idx:
            idx = sorted(idx + [size // 2])
        return idx

    x_cols = mid_span(columns)
    y_rows = mid_span(rows)
    sag_center = x_cols.index(columns // 2)
    cor_center = y_rows.index(rows // 2)
    sag_cols = np.empty((n, len(x_cols), rows), np.float32)
    cor_cols = np.empty((n, len(y_rows), columns), np.float32)
    sag = np.empty((n, rows), np.float32)
    cor = np.empty((n, columns), np.float32)

    def _read(i: int):
        d = pydicom.dcmread(files[i])
        px = _rescale_pixels(
            d.pixel_array,
            float(getattr(d, "RescaleSlope", 1.0)),
            float(getattr(d, "RescaleIntercept", 0.0)),
        )
        sag_i = np.stack([px[:, c] for c in x_cols], axis=1)
        cor_i = np.stack([px[r, :] for r in y_rows], axis=0)
        return i, sag_i.T, cor_i, sag_i[:, sag_center], cor_i[cor_center, :]

    workers = _source_batch_size(ds, sample, n)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for i, sag_i, cor_i, sag_mid, cor_mid in ex.map(_read, range(n)):
            sag_cols[i] = sag_i
            cor_cols[i] = cor_i
            sag[i] = sag_mid
            cor[i] = cor_mid
    if include_midlines:
        return sag, cor, sag_cols, cor_cols
    return sag_cols, cor_cols


def _scan_meta(ds, sample: str) -> dict:
    """Slice count, voxel size, z-step and window defaults read straight
    from the scan (first DICOM header + file positions) — the metadata a
    NOT-processed specimen has when report.json does not exist yet."""
    n = 0
    voxel_um = 0.0
    z_step_um = 0.0
    if getattr(ds, "source_kind", "dicom") != "dicom":
        info = _source_metadata(ds)
        n = int(info["shape_zyx"][0])
        spacing = info.get("spacing_zyx_mm") or [0, 0, 0]
        z_step_um = float(spacing[0] or 0) * 1000.0
        voxel_um = float((info.get("pixel_spacing_yx_mm") or [0])[0] or 0) * 1000.0
        metal_lo = UNPROC_WIN[2]
        wood_range = UNPROC_WOOD
        win_lo, win_hi = UNPROC_WIN[0], UNPROC_WIN[1]
        if info.get("intensity_mode") == "raw":
            try:
                import tomograph as tg
                from volume_io import adaptive_thresholds
                thresholds = adaptive_thresholds(info, tg.DEFAULTS)
                metal_lo = float(thresholds["metal_hu"])
                wood_range = (float(thresholds["wood_hu_min"]),
                              float(thresholds["wood_hu_max"]))
                spread = max(1.0, wood_range[1] - wood_range[0])
                win_lo = wood_range[0] - 0.25 * spread
                win_hi = wood_range[1] + 0.25 * spread
            except Exception:
                pass
        return {"n": n, "voxel_um": voxel_um, "z_step_um": z_step_um,
                "win_lo": win_lo, "win_hi": win_hi,
                "metal_lo": metal_lo, "wood_hu": wood_range}
    import pydicom  # module-local import: this file has no top-level pydicom
    try:
        files = _xy_files(ds, sample)
        n = len(files)
        first = pydicom.dcmread(files[0], stop_before_pixels=True)
        try:
            voxel_um = float(first.PixelSpacing[0]) * 1000.0
        except Exception:
            voxel_um = 0.0
        # True z geometry: prefer the header slice thickness, fall back
        # to the physical spacing between the first two slices (micro-CT
        # recon exports are frequently ANISOTROPIC — µm pixels with
        # mm-scale z steps — and assuming isotropy there poisons the
        # pre-process detection's physical evidence gates).
        try:
            z_step_um = float(first.SliceThickness) * 1000.0
        except Exception:
            z_step_um = 0.0
        if n >= 2 and (z_step_um <= 0 or z_step_um > 5000.0):
            try:
                d2 = pydicom.dcmread(files[1], stop_before_pixels=True)
                z2 = float(d2.ImagePositionPatient[2])
                z1 = float(first.ImagePositionPatient[2])
                step = abs(z2 - z1)
                if step > 0:
                    z_step_um = step * 1000.0
            except Exception:
                pass
    except Exception:
        pass
    return {"n": n, "voxel_um": voxel_um, "z_step_um": z_step_um,
            "win_lo": UNPROC_WIN[0], "win_hi": UNPROC_WIN[1]}


def _prev_source_unprocessed(dataset: str, sample: str, meta: dict) -> dict:
    """Preview source for a specimen with no report.json yet.

    The ortho/axial preview needs no processing at all — it renders the
    ORIGINAL reconstruction with the delivery geometry.  Without a report
    the delivery is the whole scan, so the source falls back to scan-native
    geometry (cut = n, margin 0, keep 0, the general CT window) and the
    detection runs over the full voxel to give the pre-process air-top /
    metal-top guides the user checks before committing to a run.
    """
    sag, cor, sagc, corc = _ortho_columns_cached(
        ds := _get_ds(dataset, sample), sample,
        output_root(ds) / sample)
    bounds = None
    try:
        bounds = wood_bounds(
            ds, sample, n_slices=int(meta["n"]), cut_from=max(1, int(meta["n"])),
            sag=(sagc if sagc is not None else sag),
            cor=(corc if corc is not None else cor),
            metal_hu=float(meta.get("metal_lo", UNPROC_WIN[2])),
            track_z=None, voxel_um=(meta["voxel_um"] or None),
            wood_hu=meta.get("wood_hu", UNPROC_WOOD),
            det_anchor=None, det_cut=None,
            z_step_um=(meta.get("z_step_um") or None))
    except Exception:
        bounds = None
    return {
        "key": f"{dataset}/{sample}:unprocessed",
        "sag": sag, "cor": cor, "n_slices": int(sag.shape[0]),
        "cut": int(meta["n"]), "detected_cut": int(meta["n"]),
        "anchor": int(meta["n"]), "keep": 0, "margin": 0, "roi_z": None,
        "lo": meta["win_lo"], "hi": meta["win_hi"],
        "metal_lo": float(meta.get("metal_lo", UNPROC_WIN[2])), "unprocessed": True,
        "bounds": bounds,
    }


def _prev_source(dataset: str, sample: str) -> dict:
    """Heavy per-sample preview data: original ortho lines (threaded read),
    stripped lines, window + cut geometry. Cached in-process and on disk."""
    ds = _get_ds(dataset, sample)
    sdir = output_root(ds) / sample
    key = (f"{_prev_key(dataset, sample, sdir)}:src{_source_cache_token(ds)}"
           f":id{source_identity(ds, sample)}")
    hit = _PREV.get(key)
    if hit:
        _PREV.pop(key)
        _PREV[key] = hit
        return hit
    if not (sdir / "report.json").exists():
        # registered but not processed (typical fresh custom specimen):
        # the preview still works — scan-native geometry + pre-process
        # detection guides instead of crashing the plane switch
        src = _prev_source_unprocessed(dataset, sample, _scan_meta(ds, sample))
        _store_prev(key, src)
        return src
    report = json.loads((sdir / "report.json").read_text())
    cut = int(report["platform"]["cut_from"])
    det_cut = int(report["platform"].get("detected_cut_from") or cut)
    lo, hi, metal_lo = _win_from_report(report, np.zeros((4, 4), np.float32))
    track = report.get("wood_roi", {}).get("track", {}) or {}
    sag, cor, sagc, corc = _ortho_columns_cached(ds, sample, sdir)
    # Metal-anchored, air-refined wood bounds for the auto guide lines.
    # REUSE the payload's detection when it exists (mtime-keyed disk cache,
    # identical inputs): recomputing the full detection here cost ~8 s on
    # a 24 µm specimen and froze the GUI on the first plane switch of
    # every session.  The full recompute below is only the fallback for
    # specimens that have no payload yet.
    bounds = None
    try:
        p = _build_payload_locked(dataset, sample)
        bounds = p.get("bounds")
    except Exception:
        bounds = None
    if bounds is None:
        try:
            cfg = report.get("config", {})
            sp = (report.get("meta", {}).get("pixel_spacing_yx_mm") or [None])
            bounds = wood_bounds(ds, sample, n_slices=int(report["meta"]["n_slices"]),
                                 cut_from=cut,
                                 sag=(sagc if sagc is not None else sag),
                                 cor=(corc if corc is not None else cor),
                                 metal_hu=metal_lo,
                                 track_z=(track.get("z0"), track.get("z1")),
                                 voxel_um=(float(sp[0]) * 1000.0 if sp and sp[0] else None),
                                 wood_hu=(float(cfg.get("wood_hu_min", -990.0)),
                                          float(cfg.get("wood_hu_max", -500.0))),
                                 det_anchor=report.get("platform", {}).get("anchor_slice"),
                                 det_cut=int(report.get("platform", {})
                                             .get("detected_cut_from") or cut),
                                 z_step_um=(float(report["meta"].get(
                                     "slice_thickness_mm", 0.0)) * 1000.0))
        except Exception:
            bounds = None

    src = {
        "key": key, "sag": sag, "cor": cor,
        "n_slices": int(sag.shape[0]), "cut": cut,
        "detected_cut": det_cut,
        "anchor": int(report["platform"].get("anchor_slice") or cut),
        "keep": int(report["platform"].get("keep_from") or 0),
        "margin": int(report.get("config", {}).get("cut_margin_slices") or 0),
        "roi_z": [track.get("z0"), track.get("z1")] if track else None,
        "lo": lo, "hi": hi, "metal_lo": metal_lo,
        "bounds": bounds,
    }
    _store_prev(key, src)
    return src


_ORTHO_PLANE_CACHE: dict = {}
_ORTHO_PLANE_MAX = 12        # planes kept; one plane is 576 x 648 float32 (~1.5 MB)


def _series_dims(ds, sample: str) -> tuple[int, int] | None:
    """(rows, columns) of a DICOM series from its first header; None if not DICOM."""
    files = _xy_files(ds, sample) if getattr(ds, "source_kind", "dicom") == "dicom" else []
    if not files:
        return None
    import pydicom
    first = pydicom.dcmread(str(files[0]), stop_before_pixels=True)
    return int(first.Rows), int(first.Columns)


def _ortho_plane(ds, sample: str, plane: str, index: int) -> np.ndarray | None:
    """The sagittal column x = index (rows = Y) or the coronal row y = index
    (columns = X) of every slice, z down the image.  Read from the source series
    in batches, so any X or Y can be scrubbed.  None for a non-DICOM source
    (the mid-plane preview is kept then)."""
    files = _xy_files(ds, sample) if getattr(ds, "source_kind", "dicom") == "dicom" else []
    if not files:
        return None
    key = (_source_cache_key(ds, sample), plane, int(index))
    hit = _ORTHO_PLANE_CACHE.get(key)
    if hit is not None:
        return hit
    rows = []
    for start in range(0, len(files), 32):
        zs = list(range(start, min(len(files), start + 32)))
        arrs = _source_slices(ds, sample, zs, cache=False)
        for z in zs:
            a = np.asarray(arrs[z], np.float32)
            rows.append(a[:, index] if plane == "sagittal" else a[index, :])
    img = np.stack(rows)
    if len(_ORTHO_PLANE_CACHE) >= _ORTHO_PLANE_MAX:
        _ORTHO_PLANE_CACHE.pop(next(iter(_ORTHO_PLANE_CACHE)))
    _ORTHO_PLANE_CACHE[key] = img
    return img


def _lateral_box(lateral: dict | None, shape) -> tuple[int, int, int, int] | None:
    """(y0, y1, x0, x1) inside the L/R box for an axial slice of ``shape``, or None."""
    if not lateral:
        return None
    ys = lateral_range(lateral.get("y"), int(shape[0]))
    xs = lateral_range(lateral.get("x"), int(shape[1]))
    if ys is None and xs is None:
        return None
    y0, y1 = ys or (0, int(shape[0]))
    x0, x1 = xs or (0, int(shape[1]))
    return (y0, y1, x0, x1)


def _ortho_columns_cached(ds, sample: str, sdir: Path,
                          ncols: int = ORTHO_COL_COUNT
                          ) -> tuple[np.ndarray, np.ndarray,
                                     np.ndarray | None, np.ndarray | None]:
    """Cached multi-column ortho stacks (sag, cor, sag_cols, cor_cols).

    The column stacks feed the metal quorum slab test in wood_bounds;
    ``None`` columns mean the cache predates them (callers then fall back
    to the legacy rank-2 path, which wood_bounds still honours).
    """
    key = (f"{ds.key}/{sample}:{_mtime_key(sdir)}:src{_source_cache_token(ds)}"
           f":id{source_identity(ds, sample)}")
    disk = CACHE_DIR / (_cache_stem(key)
                        + f"_orig_v{ORTHO_CACHE_VERSION}.npz")
    if disk.exists():
        try:
            with np.load(disk) as z:
                sagc = z["sagc"] if "sagc" in z.files else None
                corc = z["corc"] if "corc" in z.files else None
                return z["sag"], z["cor"], sagc, corc
        except Exception:
            pass
    try:
        sag, cor, sagc, corc = _orig_ortho_columns(
            ds, sample, ncols, include_midlines=True)
    except Exception:
        # Preserve the simpler mid-line fallback for malformed or partial series.
        sag, cor = _orig_ortho_lines(ds, sample)
        sagc = corc = None
    try:
        tmp = disk.with_suffix(".tmp.npz")
        if sagc is not None and corc is not None:
            np.savez_compressed(tmp, sag=sag, cor=cor, sagc=sagc, corc=corc)
        else:
            np.savez_compressed(tmp, sag=sag, cor=cor)
        os.replace(tmp, disk)
        _prune_disk_cache(ds.key, sample, "ortho", disk)
    except Exception:
        pass
    return sag, cor, sagc, corc


def _ortho_panel(orig_line, cut: int, margin: int,
                 keep_from: int, roi_z, lo, hi, metal_lo, z_line: int,
                 width: int, cmap: str = "spectral",
                 cols: tuple[int, int] | None = None) -> Image.Image:
    """ORIG | KEPT side-by-side ortho panel with cut / range annotations.

    The KEPT panel previews the delivery exactly: original slices between Keep
    and Cut, and columns inside the L/R box (`cols`, or all), as the bundle
    will contain them."""
    orig_line = np.asarray(orig_line, np.float32)
    in_z = ((np.arange(orig_line.shape[0])[:, None] >= keep_from) &
            (np.arange(orig_line.shape[0])[:, None] < cut))
    in_x = np.ones((1, orig_line.shape[1]), bool)
    if cols is not None:
        in_x[:] = False
        in_x[0, cols[0]:cols[1]] = True
    strip_line = np.where(in_z & in_x, orig_line, np.nan)
    def render(line, is_orig):
        rgb = _apply_cmap(_u8(line, lo, hi), cmap)
        met = np.isfinite(line) & (line > metal_lo)
        if is_orig and met.any():
            rgb = _tint(rgb, met, (0.85, 0.88, 0.95), 0.75)
        return rgb
    panels = [render(orig_line, True), render(strip_line, False)]
    h, w = panels[0].shape[:2]
    pw = int(w * width / h)
    canvas = Image.new("RGB", (pw * 2 + 10, width), (13, 15, 20))
    for i, rgb in enumerate(panels):
        canvas.paste(_frame_img(rgb, pw), (i * (pw + 10), 0))
    sc = width / h
    d = ImageDraw.Draw(canvas)
    for off in (0, pw + 10):
        y = cut * sc
        for x in range(0, pw, 18):
            d.line((x + off, y, x + 10 + off, y), fill=(255, 70, 60), width=3)
        if margin > 0:
            ym = max(0, cut - margin) * sc
            for x in range(0, pw, 14):
                d.line((x + off, ym, x + 7 + off, ym), fill=(255, 176, 32),
                       width=2)
        if keep_from > 0:
            yk = keep_from * sc
            for x in range(0, pw, 14):
                d.line((x + off, yk, x + 7 + off, yk), fill=(55, 214, 122),
                       width=2)
        if roi_z and roi_z[0] is not None:
            y0, y1 = roi_z[0] * sc, (roi_z[1] + 1) * sc
            for x in range(0, pw, 24):
                d.line((x + off, y0, x + 8 + off, y0), fill=(55, 214, 122),
                       width=1)
                d.line((x + off, y1, x + 8 + off, y1), fill=(55, 214, 122),
                       width=1)
        yz = min(max(z_line, 0), h - 1) * sc
        d.line((0, yz, pw, yz), fill=(79, 140, 255), width=1)
    d.text((10, 8), "ORIGINAL", fill=(185, 195, 210))
    d.text((pw + 20, 8), "KEPT (delivery range)", fill=(120, 220, 160))
    return canvas


def _axial_orig(orig_sl: np.ndarray, lo, hi, metal_lo,
                size: int = 480, cmap: str = "spectral",
                is_kept: bool = True,
                box: tuple[int, int, int, int] | None = None) -> Image.Image:
    """Axial slice side-by-side: BEFORE (Original) | AFTER (Kept / Clean preview).

    ``box`` = (y0, y1, x0, x1) is the L/R box; the AFTER panel shows only inside it."""
    orig_sl = np.asarray(orig_sl, np.float32)
    inside = np.ones(orig_sl.shape, bool)
    if box is not None:
        inside[:] = False
        inside[box[0]:box[1], box[2]:box[3]] = True
    clean_sl = np.where(inside, orig_sl, np.nan) if is_kept else np.full_like(orig_sl, np.nan)

    rgb_orig = _apply_cmap(_u8(orig_sl, lo, hi), cmap)
    rgb_clean = _apply_cmap(_u8(clean_sl, lo, hi), cmap)

    met_orig = np.isfinite(orig_sl) & (orig_sl > metal_lo)
    if met_orig.any():
        rgb_orig = _tint(rgb_orig, met_orig, (0.85, 0.88, 0.95), 0.75)

    h, w = rgb_orig.shape[:2]
    pw = int(w * size / h)
    canvas = Image.new("RGB", (pw * 2 + 10, size), (13, 15, 20))
    canvas.paste(_frame_img(rgb_orig, pw), (0, 0))
    canvas.paste(_frame_img(rgb_clean, pw), (pw + 10, 0))

    d = ImageDraw.Draw(canvas)
    d.text((10, 8), "BEFORE (Original)", fill=(185, 195, 210))
    d.text((pw + 20, 8), "AFTER (Delivery Kept)" if is_kept else "AFTER (Platform Removed)",
           fill=(120, 220, 160) if is_kept else (255, 120, 110))
    return canvas


def get_preview(dataset: str, sample: str, cut: int | None = None,
                margin: int | None = None, keep_from: int | None = None,
                plane: str = "sagittal",
                z: int | None = None, width: int = 560,
                cmap: str = "spectral",
                lo: float | None = None,
                hi: float | None = None,
                pos: int | None = None,
                lateral: dict | None = None) -> dict:
    """Thread-safe facade over _get_preview_locked (shared cache mutation)."""
    with LOCK:
        return _get_preview_locked(
            dataset, sample, cut=cut, margin=margin, keep_from=keep_from,
            plane=plane, z=z, width=width, cmap=cmap, lo=lo, hi=hi,
            pos=pos, lateral=lateral)


def _get_preview_locked(dataset: str, sample: str, cut: int | None = None,
                        margin: int | None = None, keep_from: int | None = None,
                        plane: str = "sagittal",
                        z: int | None = None, width: int = 560,
                        cmap: str = "spectral",
                        lo: float | None = None,
                        hi: float | None = None,
                        pos: int | None = None,
                        lateral: dict | None = None) -> dict:
    """Preferences-tab preview: original reconstruction in requested colormap
    with the requested cut / collection-range geometry drawn. ``pos`` is the
    scrubbed position of the plane: X for sagittal, Y for coronal, Z for axial.
    ``lateral`` is the L/R box, {"x": (lo, hi), "y": (lo, hi)} as fractions;
    the AFTER panel shows only inside it. Coordinates are clamped; nothing is
    written to disk."""
    src = _prev_source(dataset, sample)
    ds = _get_ds(dataset, sample)
    n = src["n_slices"]
    cut = src["cut"] if cut is None else int(cut)
    margin = src["margin"] if margin is None else int(margin)
    keep_from = src["keep"] if keep_from is None else int(keep_from)
    cut = int(max(0, min(n, cut)))
    margin = int(max(0, min(cut, margin)))
    keep_from = int(max(0, min(cut, keep_from)))
    win_lo = src["lo"] if lo is None else float(lo)
    win_hi = src["hi"] if hi is None else float(hi)
    if win_lo >= win_hi:
        win_hi = win_lo + 1.0
    cmap = (cmap or "spectral").lower()
    if cmap not in _CMAP_STOPS:
        cmap = "spectral"

    if plane == "axial":
        # Default z to specimen mid-height for clear anatomical visibility (not blank slice 0)
        default_z = (keep_from + cut) // 2 if cut > keep_from else n // 2
        zi = int(max(0, min(n - 1, z if z is not None else default_z)))
        orig_map = _source_slices(ds, sample, [zi])
        is_kept = (keep_from <= zi < cut)
        box = _lateral_box(lateral, orig_map[zi].shape)
        img = _axial_orig(orig_map[zi], win_lo, win_hi, src["metal_lo"], cmap=cmap,
                          is_kept=is_kept, box=box)
        return {"plane": "axial", "z": zi, "n_slices": n, "span": n,
                "png": _b64(img), "cut": cut, "margin": margin,
                "keep_from": keep_from, "detected_cut": src.get("detected_cut", cut),
                "cmap": cmap, "lo": win_lo, "hi": win_hi,
                "default_lo": src["lo"], "default_hi": src["hi"],
                "bounds": src.get("bounds")}
    # sagittal scrubs X (a column of every slice), coronal scrubs Y (a row);
    # the lateral axis across each plane is Y for sagittal and X for coronal
    dims = _series_dims(ds, sample)
    if dims is None:                                  # non-DICOM: mid-plane only
        line_o = src["sag"] if plane == "sagittal" else src["cor"]
        span = int(line_o.shape[1]) if line_o.ndim == 2 else n
        rows_cols = None
    else:
        rows_cols = dims
        span = dims[1] if plane == "sagittal" else dims[0]
    if pos is None:
        pos = span // 2
    pos = int(max(0, min(span - 1, pos)))
    if rows_cols is None:
        line_o = src["sag"] if plane == "sagittal" else src["cor"]
        cols = None
    else:
        line_o = _ortho_plane(ds, sample, plane, pos)
        across = dims[0] if plane == "sagittal" else dims[1]
        pair = (lateral or {}).get("y" if plane == "sagittal" else "x")
        cols = lateral_range(pair, across)
    if z is None:
        z = keep_from + max(0, (cut - keep_from) // 2)
    z = int(max(0, min(n - 1, z)))
    img = _ortho_panel(line_o, cut, margin, keep_from, src["roi_z"],
                       win_lo, win_hi, src["metal_lo"], z, width, cmap=cmap, cols=cols)
    return {"plane": plane, "z": z, "n_slices": n, "span": span, "pos": pos,
            "png": _b64(img),
            "cut": cut, "margin": margin, "keep_from": keep_from,
            "cut_default": src["cut"], "detected_cut": src.get("detected_cut", src["cut"]),
            "margin_default": src["margin"],
            "keep_default": src["keep"], "anchor": src["anchor"],
            "roi_z": src["roi_z"],
            "cmap": cmap, "lo": win_lo, "hi": win_hi,
            "default_lo": src["lo"], "default_hi": src["hi"],
            "bounds": src.get("bounds")}
