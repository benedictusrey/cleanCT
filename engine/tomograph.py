#!/usr/bin/env python
"""tomograph.py - universal metal-platform removal for micro-CT wood volumes.

Works on any Comscan/Bruker reconstruction laid out as ``<sample>/XY/*.dcm``
(HU-valued DICOM series, wood specimen mounted on a metal platform at the
bottom of the scan).  Two datasets are registered below:

    24um  H:\\Treated Kyodai samples\\...\\AD\\24 micro   (validated vs 1-15 cleaned)
    66um  H:\\Treated Kyodai samples\\...\\AD\\66 micro   (66.206 um voxels)

Method (identical logic for every dataset; all parameters derived from
per-dataset pixel scale, not hard-coded to one scan)
---------------------------------------------------------------------
1. **Anchor**: the bottom-anchored metal platform component (HU > 0,
   >= ``platform_min_voxels`` px per slice) - the last contiguous run of
   slices with a big metal cross-section.
2. **Halo cut (the sweetspot)**: the platform's partial-volume /
   beam-hardening halo contaminates the slices above the pure-metal
   region *before* any pixel reaches metal HU.  Track the mean HU of the
   bottom ``baseline_row_frac`` rows per slice; its baseline (median over
   the clean middle of the stack) is stable to <1 HU.  The cut is the
   first slice that violates ``baseline + halo_delta_hu`` **and** shows a
   genuine onset: a local 3-slice slope >= ``min_onset_slope_hu`` OR a
   rise >= ``min_onset_rise_hu`` within the previous 15 slices.  This
   rejects the slow thermal/reconstruction drift (~0.02 HU/slice) seen in
   the 66 um data while catching every real halo ramp (>=0.3 HU/slice).
   A guard window (anchor - ``anchor_guard_slices``) bounds the search.
3. **Cut**: void every voxel at and below ``cut_from`` (NaN) - a clean
   z-truncation identical in convention to the manual ``1-15 cleaned``.
4. **Wood ROI**: per-slice 2D tracking of the dense-wood window (see
   wood_track.py) seeded at the cleanest mid-stack component.
5. **Outputs**: cropped wood-ROI DICOM slices, an uncompressed ``.nii``
   NIfTI-1 volume with embedded source metadata, QA montages, and JSON report.

Acceleration
------------
* Any CUDA GPU (RTX 4080 SUPER and friends) is detected and used
  adaptively for HU conversion, threshold reductions, NaN voiding and
  TIFF quantisation (gpu_backend.py); every op has an identical CPU
  fallback, so results are correct on GPU-less machines.
* The DICOM loader reads and parses slices in a thread pool.

Command line
------------
    python tomograph.py --list [--dataset 66um]
    python tomograph.py --dataset 66um --sample 1-1 --diagnose
    python tomograph.py --dataset 66um --all
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np
import pydicom

from gpu_backend import get_backend
from roi_delivery import (export_roi_dicom_series, sorted_source_files,
                          write_provenance, write_roi_nifti,
                          write_stripped_nifti)
from wood_track import SliceTrack, track_wood_by_slices, crop_by_footprints
from air_crop import apply_air_crop

# ---------------------------------------------------------------------------
# dataset registry
# ---------------------------------------------------------------------------
_BASE = Path(r"H:\Treated Kyodai samples\1 MONTH"
             r"\0 Wood Degradation (Validation)\AD")


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    source: Path
    out_sub: str                       # subfolder under OUT_ROOT ('' = legacy)
    # ground truth: sample -> number of kept slices in the manual cleanup
    ground_truth: dict[str, int] = field(default_factory=dict)
    # per-dataset overrides merged into Config (pixel-scale dependent)
    config_overrides: dict = field(default_factory=dict)
    # DICOM remains the default source contract for all existing datasets.
    # User-loaded TIFF/NIfTI volumes use these optional source descriptors.
    source_kind: str = "dicom"
    source_path: Path | None = None
    source_metadata: dict = field(default_factory=dict)


DATASETS: dict[str, DatasetSpec] = {
    "24um": DatasetSpec(
        key="24um",
        source=_BASE / "24 micro",
        out_sub="",                    # legacy location output/<sample>
        ground_truth={"1-15": 1006},
        config_overrides=dict(
            roi_seed_min_area=20_000, roi_min_area=400,
            platform_min_voxels=20_000,
        ),
    ),
    "66um": DatasetSpec(
        key="66um",
        source=_BASE / "66 micro",
        out_sub="66um",
        ground_truth={},
        config_overrides=dict(
            # pixel area is (24.852/66.206)^2 = 0.141x the 24um one
            roi_seed_min_area=7_500, roi_min_area=150,
            platform_min_voxels=7_400,
            # 66um scans show a gentle pre-halo swell (~0.1-0.15 HU/slice
            # over 20-35 slices, a scanner warm-up artefact) that must not
            # trigger the onset detector; the true fog ramps here are
            # >=3 HU/slice, so require 0.5 HU/slice locally (24um halos
            # start at ~0.2 HU/slice and keep the global 0.15)
            min_onset_slope_hu=0.5,
        ),
    ),
}

OUT_ROOT = Path(r"H:\Treated Kyodai samples\metal_remover\output")

# DICOM decoding returns one host array per slice before HU conversion. Keep
# the whole decode batch bounded at high resolutions instead of always
# holding 64 slices at once (64 x 6000 x 6000 can exceed 4 GiB).
DICOM_LOAD_BATCH_BUDGET_BYTES = 256 * 1024 * 1024
DICOM_LOAD_MAX_BATCH_SLICES = 64
DICOM_LOAD_WORKING_BYTES_PER_PIXEL = 8  # decode buffer + conversion headroom
DICOM_LOAD_HOST_VOLUME_MULTIPLIER = 3  # input, stripped copy, ROI headroom


def output_root(ds: DatasetSpec) -> Path:
    override = os.environ.get("CLEANCT_OUTPUT_ROOT")
    root = Path(override) if override else OUT_ROOT
    return root / ds.out_sub if ds.out_sub else root


# ---------------------------------------------------------------------------
# configuration (universal; dataset overrides fill the pixel-scale fields)
# ---------------------------------------------------------------------------
@dataclass
class Config:
    # ---- platform anchor ---------------------------------------------------
    metal_hu: float = 0.0             # HU threshold for "metal"
    platform_min_voxels: int = 20_000 # min metal px per slice in anchor run
    platform_min_slices: int = 5      # anchor run must span this many slices
    # ---- halo-based cut ------------------------------------------------------
    baseline_row_frac: float = 0.40   # bottom fraction of rows for the profile
    baseline_z_lo: float = 0.25       # baseline window: this .. anchor-10
    halo_delta_hu: float = 2.0        # violation level: baseline + delta
    min_onset_slope_hu: float = 0.15  # genuine onset: 3-slice slope >= this
    min_onset_rise_hu: float = 3.0    # ... or rise over the previous 15 slices
    onset_rise_window: int = 15
    anchor_guard_slices: int = 60     # search onset no higher than anchor-this
    cut_margin_slices: int = 0        # 0 reproduces the manual 1-15 cleanup
    cut_override: int | None = None   # user-defined cut slice (app Preferences); None = detector
    keep_from: int = 0                # first collected slice of the delivery (app Preferences)
    # ---- air-curtain voiding (off: outputs match the manual convention) ------
    curtain_removal: bool = False
    curtain_air_hu: float = -900.0
    curtain_air_frac: float = 0.90
    # ---- wood ROI --------------------------------------------------------------
    wood_hu_min: float = -990.0       # dense-wood HU window (AD datasets)
    wood_hu_max: float = -500.0
    roi_slice_erode: int = 0
    roi_min_overlap: float = 0.50
    roi_min_shrink: float = 0.40
    roi_seed_min_area: int = 20_000   # px (dataset override scales this)
    roi_min_area: int = 400           # px
    roi_footprint_dilate: int = 3
    roi_exclude_border: bool = False  # specimens may touch the FOV edge
    roi_bbox_pad: int = 6
    # ---- air-envelope crop (app Preferences "Auto-crop to wood") -------------
    # Tightens the tracked ROI bbox to the wood by trimming (nearly) pure-air
    # margins at the FOV borders.  Off by default so CLI/batch outputs stay
    # byte-identical with the validated runs; the desktop app turns it on.
    air_crop: bool = False
    air_crop_hu: float = -900.0       # HU at/below this counts as air
    air_crop_frac: float = 0.98       # margin must be >=98% air to trim
    # ---- outputs / performance -------------------------------------------------
    save_nifti: bool = True
    save_dicom: bool = True
    save_qa_montage: bool = True
    # full-FOV kept-slices volume (app bundle export needs it; off by default
    # so built-in dataset outputs stay byte-for-byte as validated)
    save_stripped_nii: bool = False
    io_workers: int = 8               # DICOM read threads
    intensity_auto_calibrated: bool = False
    intensity_range_estimate: list[float] | None = None

    def overridden(self, overrides: dict) -> "Config":
        d = asdict(self)
        d.update(overrides)
        return Config(**d)

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULTS = Config()

# ---------------------------------------------------------------------------
# discovery + loading
# ---------------------------------------------------------------------------
def discover_samples(ds: DatasetSpec) -> list[str]:
    """All sample folders with an XY DICOM subfolder, sorted."""
    return sorted(d.name for d in ds.source.iterdir()
                  if d.is_dir() and (d / "XY").is_dir())


def list_dicom_files(sample_dir: Path) -> list[Path]:
    xy = sample_dir / "XY"
    files = sorted(p for p in xy.glob("*.dcm") if p.is_file())
    if not files:
        raise FileNotFoundError(f"no DICOM files under {xy}")
    return files


def _read_header(p: Path) -> dict:
    try:
        ds = pydicom.dcmread(p, stop_before_pixels=True)
        rows, cols = int(ds.Rows), int(ds.Columns)
        frames = int(getattr(ds, "NumberOfFrames", 1))
        samples = int(getattr(ds, "SamplesPerPixel", 1))
        bits = int(ds.BitsAllocated)
        pixel_repr = int(getattr(ds, "PixelRepresentation", 0))
        ps = tuple(float(v) for v in ds.PixelSpacing)
        ipp = tuple(float(v) for v in ds.ImagePositionPatient)
        iop = tuple(float(v) for v in ds.ImageOrientationPatient)
        slope = float(getattr(ds, "RescaleSlope", 1.0))
        intercept = float(getattr(ds, "RescaleIntercept", 0.0))
        if rows <= 0 or cols <= 0:
            raise ValueError("Rows and Columns must be positive")
        if frames != 1 or samples != 1:
            raise ValueError("only single-frame monochrome slices are supported")
        if bits not in (8, 16, 32) or pixel_repr not in (0, 1):
            raise ValueError(f"unsupported pixel encoding ({bits} bits, "
                             f"PixelRepresentation={pixel_repr})")
        if len(ps) != 2 or not np.isfinite(ps).all() or min(ps) <= 0:
            raise ValueError("PixelSpacing must contain two positive values")
        if len(ipp) != 3 or not np.isfinite(ipp).all():
            raise ValueError("ImagePositionPatient must contain three finite values")
        if len(iop) != 6 or not np.isfinite(iop).all():
            raise ValueError("ImageOrientationPatient must contain six finite values")
        row_dir, col_dir = np.asarray(iop[:3]), np.asarray(iop[3:])
        if (not np.isclose(np.linalg.norm(row_dir), 1.0, atol=1e-5)
                or not np.isclose(np.linalg.norm(col_dir), 1.0, atol=1e-5)
                or not np.isclose(np.dot(row_dir, col_dir), 0.0, atol=1e-5)):
            raise ValueError("ImageOrientationPatient direction cosines are invalid")
        if not np.isfinite((slope, intercept)).all():
            raise ValueError("RescaleSlope/RescaleIntercept must be finite")
        photometric = str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2"))
        if photometric not in ("MONOCHROME1", "MONOCHROME2"):
            raise ValueError(f"unsupported PhotometricInterpretation={photometric}")
        return dict(rows=rows, cols=cols, z=ipp[2], slope=slope,
                    intercept=intercept, ps=ps, ipp=ipp, iop=iop,
                    bits_allocated=bits, pixel_repr=pixel_repr)
    except Exception as exc:
        raise ValueError(f"{p.name}: invalid or unsupported DICOM header: {exc}") from exc


def _read_pixels(p: Path, rows: int, cols: int) -> np.ndarray:
    """Decode one supported monochrome DICOM slice (rescale happens later)."""
    try:
        ds = pydicom.dcmread(p)
        if int(getattr(ds, "NumberOfFrames", 1)) != 1:
            raise ValueError("multi-frame pixel data is not supported")
        if int(getattr(ds, "SamplesPerPixel", 1)) != 1:
            raise ValueError("only monochrome pixel data is supported")
        bits = int(ds.BitsAllocated)
        if bits not in (8, 16, 32):
            raise ValueError(f"unsupported BitsAllocated={bits}")
        expected = int(rows) * int(cols) * (bits // 8)
        pixels = ds.get("PixelData")
        transfer_syntax = getattr(getattr(ds, "file_meta", None),
                                  "TransferSyntaxUID", None)
        compressed = bool(transfer_syntax and
                          getattr(transfer_syntax, "is_compressed", False))
        if not pixels:
            raise ValueError("PixelData is empty or missing")
        if not compressed and len(pixels) < expected:
            raise ValueError(f"pixel buffer too small ({len(pixels)} B; "
                             f"need at least {expected} B)")
        arr = np.asarray(ds.pixel_array)
        if arr.shape != (int(rows), int(cols)):
            raise ValueError(f"decoded pixel shape {arr.shape} != "
                             f"({int(rows)}, {int(cols)})")
        if arr.dtype.kind not in "iu":
            raise ValueError(f"decoded pixels have unsupported dtype {arr.dtype}")
        return arr
    except Exception as exc:
        raise ValueError(f"{p.name}: could not decode DICOM pixels: {exc}") from exc


def _dicom_load_plan(rows: int, cols: int, requested_workers: int,
                     *, cpu_count: int | None = None) -> tuple[int, int]:
    """Return (batch slices, read workers) under the decode working budget."""
    pixels = max(1, int(rows)) * max(1, int(cols))
    working_per_slice = max(1, pixels * DICOM_LOAD_WORKING_BYTES_PER_PIXEL)
    batch_limit = max(1, DICOM_LOAD_BATCH_BUDGET_BYTES // working_per_slice)
    batch = max(1, min(DICOM_LOAD_MAX_BATCH_SLICES, int(batch_limit)))
    cpu_limit = max(1, int(cpu_count if cpu_count is not None
                            else (os.cpu_count() or 1)))
    requested = max(1, int(requested_workers))
    workers = max(1, min(requested, cpu_limit, batch))
    return batch, workers


def _available_host_memory_bytes() -> int | None:
    """Read available physical RAM without adding a runtime dependency."""
    if os.name == "nt":
        try:
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys)
        except Exception:
            return None
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        if page_size > 0 and pages > 0:
            return page_size * pages
    except (AttributeError, OSError, ValueError):
        pass
    return None


def _check_load_memory(n_slices: int, rows: int, cols: int,
                       batch_slices: int, *,
                       available_bytes: int | None = None) -> int | None:
    """Fail with a clear message before a volume allocation can exhaust RAM."""
    available = (_available_host_memory_bytes() if available_bytes is None
                 else int(available_bytes))
    if available is None or available <= 0:
        return None
    pixels = int(n_slices) * int(rows) * int(cols)
    volume_bytes = pixels * np.dtype(np.float32).itemsize
    decode_bytes = (int(batch_slices) * int(rows) * int(cols)
                    * DICOM_LOAD_WORKING_BYTES_PER_PIXEL)
    estimate = volume_bytes * DICOM_LOAD_HOST_VOLUME_MULTIPLIER + decode_bytes
    budget = int(available * 0.85)  # leave RAM for Windows, Qt, and the GPU driver
    if estimate > budget:
        raise MemoryError(
            f"estimated processing working set is {estimate / 2**30:.1f} GiB, "
            f"but only {available / 2**30:.1f} GiB RAM is available; "
            "close other applications or use a smaller scan")
    return estimate


def load_volume(sample_dir: Path, gpu, workers: int = 8,
                timings: dict | None = None) -> tuple[np.ndarray, dict]:
    """Load one sample as a float32 HU volume (z, y, x) plus metadata.

    On GPU the returned volume is a device array; on CPU a host array.
    Slice order is ascending physical z (from ImagePositionPatient).
    """
    t0 = time.perf_counter()
    files = list_dicom_files(sample_dir)
    n = len(files)
    if n < 2:
        raise ValueError("a DICOM volume needs at least two slices to determine spacing")

    header_workers = max(1, min(max(1, int(workers)),
                                os.cpu_count() or 1, n))
    with ThreadPoolExecutor(max_workers=header_workers) as ex:
        heads = list(ex.map(_read_header, files))

    shapes = {(h["rows"], h["cols"]) for h in heads}
    if len(shapes) != 1:
        raise ValueError(f"inconsistent slice shapes: {shapes}")
    (H, W), = shapes
    encodings = {(h["bits_allocated"], h["pixel_repr"]) for h in heads}
    if len(encodings) != 1:
        raise ValueError("inconsistent BitsAllocated/PixelRepresentation across series")
    slopes = {h["slope"] for h in heads}
    intercepts = {h["intercept"] for h in heads}
    if len(slopes) != 1 or len(intercepts) != 1:
        raise ValueError("inconsistent rescale slope/intercept across series")
    spacings = {h["ps"] for h in heads}
    if len(spacings) != 1:
        raise ValueError(f"inconsistent pixel spacing: {spacings}")

    orientations = {h["iop"] for h in heads}
    if len(orientations) != 1:
        raise ValueError("inconsistent ImageOrientationPatient across series")
    iop, = orientations
    row_dir = np.asarray(iop[:3], dtype=np.float64)
    col_dir = np.asarray(iop[3:], dtype=np.float64)
    normal = np.cross(row_dir, col_dir)
    normal_len = float(np.linalg.norm(normal))
    if not np.isfinite(normal_len) or normal_len <= 1e-8:
        raise ValueError("invalid ImageOrientationPatient slice normal")
    normal /= normal_len
    positions = np.asarray([np.dot(np.asarray(h["ipp"]), normal)
                            for h in heads])
    if not np.isfinite(positions).all():
        raise ValueError("ImagePositionPatient contains non-finite slice positions")
    order = np.argsort(positions, kind="stable")
    dz = np.diff(positions[order])
    step = float(np.median(dz))
    if (not np.isfinite(step) or step <= 0 or np.any(dz <= 0)
            or not np.all(np.abs(dz - step) < 1e-3)):
        raise ValueError(f"non-uniform slice spacing: {dz.min()}..{dz.max()}")
    ordered = [files[i] for i in order]
    slope, = slopes
    intercept, = intercepts
    t1 = time.perf_counter()

    def batches(lst: list[Path], size: int) -> Iterator[list[Path]]:
        for i in range(0, len(lst), size):
            yield lst[i:i + size]

    batch_size, pixel_workers = _dicom_load_plan(H, W, workers)
    _check_load_memory(n, H, W, batch_size)
    try:
        vol = gpu.empty_like((n, H, W), dtype=np.float32)
    except Exception as exc:
        gpu.release()
        raise MemoryError(
            f"could not allocate the {n} x {H} x {W} processing volume "
            f"with the selected compute backend: {exc}") from exc
    raw: list[np.ndarray] = []
    try:
        with ThreadPoolExecutor(max_workers=pixel_workers) as ex:
            done = 0
            for batch in batches(ordered, batch_size):
                raw = list(ex.map(lambda p: _read_pixels(p, H, W), batch))
                for j, a in enumerate(raw):
                    gpu.put_rescaled_slice(vol, done + j, a, slope, intercept)
                done += len(batch)
                raw.clear()
    except Exception:
        # A corrupt later slice or a backend transfer failure must not leave
        # a partially filled CUDA volume cached for the next specimen.
        raw.clear()
        del vol
        try:
            gpu.release()
        except Exception:
            pass
        raise
    t2 = time.perf_counter()

    if timings is not None:
        timings["load_headers_s"] = round(t1 - t0, 2)
        timings["load_pixels_s"] = round(t2 - t1, 2)

    (ps_row, ps_col), = spacings
    meta = dict(
        n_slices=n, rows=H, cols=W,
        source_kind="dicom", source_format="DICOM series",
        intensity_mode="hu", intensity_unit="HU",
        threshold_strategy="DICOM rescale slope/intercept",
        pixel_spacing_yx_mm=(ps_row, ps_col),
        slice_thickness_mm=step,
        voxel_mm3=ps_row * ps_col * step,
        rescale_slope=slope, rescale_intercept=intercept,
        image_orientation_patient=iop,
        image_position_first_mm=heads[int(order[0])]["ipp"],
        image_position_last_mm=heads[int(order[-1])]["ipp"],
        z_first_mm=float(heads[int(order[0])]["ipp"][2]),
        z_last_mm=float(heads[int(order[-1])]["ipp"][2]),
    )
    return vol, meta


def load_dataset_volume(ds: DatasetSpec, name: str, gpu,
                        workers: int = 8,
                        timings: dict | None = None) -> tuple[np.ndarray, dict]:
    """Load a dataset through its declared source adapter.

    DICOM delegates to the historical reader, preserving its physical slice
    order, pixel conversion, and memory behavior. TIFF and NIfTI use the
    slice-oriented reader and the same CPU/GPU volume contract.
    """
    if ds.source_kind == "dicom":
        return load_volume(ds.source / name, gpu, workers=workers,
                           timings=timings)
    if ds.source_kind not in {"tiff", "nifti"} or ds.source_path is None:
        raise ValueError(f"unsupported or incomplete source registration: {ds.source_kind}")
    from volume_io import load_volume as load_non_dicom, inspect_source
    metadata = dict(ds.source_metadata or {})
    path = Path(ds.source_path)
    current = inspect_source(
        path, intensity=str(metadata.get("intensity_mode") or "auto"),
        memory_check=_check_load_memory)
    old_signature = (metadata.get("source_signature") or {}).get("sha256")
    new_signature = (current.get("source_signature") or {}).get("sha256")
    if old_signature and new_signature != old_signature:
        raise ValueError(
            "source volume changed after registration; load it again before processing")
    metadata = current
    return load_non_dicom(path, gpu, metadata=metadata,
                          memory_check=_check_load_memory,
                          timings=timings)


# ---------------------------------------------------------------------------
# detection statistics (computed on the best available device)
# ---------------------------------------------------------------------------
def metal_counts(vol, gpu, thr: float) -> np.ndarray:
    return gpu.metal_counts(vol, thr)


def bottom_mean_profile(vol, gpu, frac: float) -> np.ndarray:
    """Per-slice mean HU of the bottom ``frac`` rows."""
    H = vol.shape[1]
    r0 = int(H * (1.0 - frac))
    return gpu.bottom_rows_mean(vol, r0)


def anchor_slice(metal_cnt: np.ndarray, cfg: Config) -> int:
    """First slice (from the bottom) of the contiguous bottom metal run.

    Specimens WITHOUT a bottom metal platform are legitimate (the metal
    does not always reach the last slice, and some scans have none at
    all): instead of failing the run, return 0 — "no platform" — and let
    the caller decide (the halo detector then falls back to the wood
    bottom, and the app defaults the user-adjustable Cut line to the
    air/wood envelope plus a safety margin).  ``platform_min_slices``
    still governs: a real platform shorter than that is treated the same
    as no platform.
    """
    n = metal_cnt.size
    run_start = None
    run_len = 0
    i = n - 1
    while i >= 0:
        if metal_cnt[i] >= cfg.platform_min_voxels:
            run_start = i
            run_len += 1
            i -= 1
        else:
            break
    if run_start is None or run_len < cfg.platform_min_slices:
        return 0                     # no bottom-anchored platform (graceful)
    return run_start


def platform_cut_index(metal_cnt: np.ndarray, prof: np.ndarray, cfg: Config,
                       ) -> tuple[int, dict]:
    """Slices [0, cut_from) are kept; [cut_from, n) contain the platform.

    Universal halo detector: violation of ``baseline + delta`` accepted
    only with a genuine onset (local slope or rise), guarded to the
    anchor neighbourhood.  Returns (cut_from, diagnostics).
    """
    n = prof.size
    anch = anchor_slice(metal_cnt, cfg)
    no_platform = (anch == 0)

    lo = int(n * cfg.baseline_z_lo)
    hi = max(lo + 1, anch - 10)
    baseline = float(np.median(prof[lo:hi]))

    # robust drift estimate over the baseline window (per-slice HU)
    win = prof[lo:hi]
    slope_est = float(np.median(np.abs(np.diff(win))))
    limit = baseline + cfg.halo_delta_hu

    guard = max(0, anch - cfg.anchor_guard_slices)
    diff = np.diff(prof)

    candidates: list[int] = []
    for j in range(guard, n):
        if prof[j] > limit:
            candidates.append(j)

    accepted = None
    accepted_by = ""
    for k, j in enumerate(candidates):
        # persistence: violation must hold on the next slice (unless the
        # candidate IS the anchor slice itself)
        if j + 1 < n and prof[j + 1] <= limit and j != anch:
            continue
        slope3 = float((prof[j] - prof[max(0, j - 3)]) / 3.0)
        w0 = max(0, j - cfg.onset_rise_window)
        rise15 = float(prof[j] - prof[w0: j].min()) if j > w0 else 0.0
        if slope3 >= cfg.min_onset_slope_hu or rise15 >= cfg.min_onset_rise_hu:
            accepted = j
            accepted_by = ("slope3" if slope3 >= cfg.min_onset_slope_hu
                           else "rise15")
            accepted_diag = (slope3, rise15)
            break
    fallback = accepted is None
    if fallback:
        if no_platform:
            # No bottom-anchored platform: there is no metal line to fall
            # back to — deliver everything and let the user's adjustable
            # Cut line (app Preferences / pre-process guides) define the
            # actual cut.  The wood bottom still draws the reference
            # guide in the app.
            accepted = n - 1
            accepted_by = "no-platform"
        else:
            accepted = anch       # halo merging into the anchor: cut at anchor
        accepted_diag = (float("nan"), float("nan"))

    cut_from = max(0, accepted + cfg.cut_margin_slices)
    detected_cut = int(accepted)
    if no_platform and cfg.cut_override is None:
        # no platform: the default delivery keeps the WHOLE scan (the
        # wood-ROI tracker still limits the delivery to the specimen)
        cut_from = n
        detected_cut = n
    if cfg.cut_override is not None:            # user-defined cut (app Preferences)
        user_cut = int(cfg.cut_override)
        if not 0 <= user_cut <= n:
            raise ValueError(f"cut_override {user_cut} outside 0..{n}")
        cut_from = user_cut
        accepted_by = "user-override"
    diag = dict(
        anchor_slice=int(anch),
        no_platform=bool(no_platform),
        baseline_hu=baseline,
        halo_limit_hu=limit, drift_hu_per_slice=slope_est,
        cut_from=int(cut_from), accepted_by=accepted_by,
        detected_cut_from=int(detected_cut),
        user_cut_override=(None if cfg.cut_override is None
                           else int(cfg.cut_override)),
        onset_slope3_hu=accepted_diag[0], onset_rise15_hu=accepted_diag[1],
        n_candidates=len(candidates), fallback=fallback,
        profile_at_cut=float(prof[cut_from]) if cut_from < n else float("nan"),
        profile_at_anchor=float(prof[anch]),
        profile_last=float(prof[n - 1]),
    )
    return int(cut_from), diag


def build_cut_mask(n: int, shape_yx: tuple[int, int], cut_from: int) -> np.ndarray:
    cut = np.zeros((n, *shape_yx), dtype=bool)
    cut[cut_from:, :, :] = True
    return cut


def drop_curtain(stripped: np.ndarray, cfg: Config) -> tuple[np.ndarray, int]:
    """Void fully-air rows above the topmost solid row of each slice."""
    if not cfg.curtain_removal:
        return stripped, 0
    out = stripped.copy()
    n_rows = 0
    for i in range(stripped.shape[0]):
        sl = stripped[i]
        air_like = ~np.isfinite(sl) | (sl <= cfg.curtain_air_hu)
        frac_air = air_like.mean(axis=1)
        solid_rows = np.nonzero(frac_air < cfg.curtain_air_frac)[0]
        if solid_rows.size == 0:
            continue
        top = int(solid_rows[0])
        if top > 0:
            block = out[i, :top]
            block[np.isfinite(block)] = np.nan
            n_rows += top
    return out, n_rows


# ---------------------------------------------------------------------------
# analysis (shared by diagnose and process)
# ---------------------------------------------------------------------------
def analyze(vol, meta: dict, cfg: Config, gpu, timings: dict | None = None,
            verbose: bool = True) -> dict:
    t0 = time.perf_counter()
    mcnt = metal_counts(vol, gpu, cfg.metal_hu)
    prof = bottom_mean_profile(vol, gpu, cfg.baseline_row_frac)
    cut_from, diag = platform_cut_index(mcnt, prof, cfg)
    t1 = time.perf_counter()

    vol_host = gpu.to_cpu(vol) if gpu.active else vol
    t2 = time.perf_counter()
    gpu.release()

    # void the platform slab on the host copy (no second device transfer)
    stripped_host = vol_host.copy()
    stripped_host[cut_from:] = np.nan
    n_removed = int((stripped_host.shape[0] - cut_from)
                    * stripped_host.shape[1] * stripped_host.shape[2])
    t3 = time.perf_counter()
    gpu.release()

    stripped_host, n_curtain_rows = drop_curtain(stripped_host, cfg)

    track, footprints = track_wood_by_slices(
        stripped_host,
        wood_hu_min=cfg.wood_hu_min, wood_hu_max=cfg.wood_hu_max,
        slice_erode=cfg.roi_slice_erode,
        min_overlap_frac=cfg.roi_min_overlap,
        min_shrink_frac=cfg.roi_min_shrink,
        seed_min_area=cfg.roi_seed_min_area,
        min_area=cfg.roi_min_area,
        footprint_dilate=cfg.roi_footprint_dilate,
        exclude_border=cfg.roi_exclude_border,
        verbose=verbose, gpu=gpu)
    t4 = time.perf_counter()

    roi_vol = bbox = None
    air_crop_info: dict | None = None
    if track.n_slices_tracked > 0:
        roi_vol, bbox = crop_by_footprints(stripped_host, footprints,
                                           pad=cfg.roi_bbox_pad)
        z_max = cut_from - 1            # clamp z padding at the cut boundary
        if bbox[1] > z_max:
            keep_to = z_max - bbox[0] + 1
            roi_vol = roi_vol[:keep_to]
            bbox = (bbox[0], z_max, *bbox[2:])
        if cfg.air_crop and bbox is not None:
            # Tighten the tracker bbox to the wood using air margins (XY,
            # XZ and YZ).  The air envelope is a guaranteed subset of the
            # tracker bbox; on any guard trip the tracker bbox stands.
            new_bbox, env = apply_air_crop(
                stripped_host, bbox=bbox, air_hu=cfg.air_crop_hu,
                air_frac=cfg.air_crop_frac, z_clamp_hi=cut_from - 1)
            air_crop_info = env.as_dict()
            if env.ok and new_bbox != bbox:
                z0b, z1b, y0b, y1b, x0b, x1b = new_bbox
                roi_vol = stripped_host[z0b:z1b + 1,
                                        y0b:y1b + 1, x0b:x1b + 1].copy()
                bbox = new_bbox
            elif not env.ok:
                if verbose:
                    print(f"  air-crop: fallback to tracker bbox "
                          f"({env.fallback_reason})")
    t5 = time.perf_counter()

    if timings is not None:
        timings["detect_s"] = round(t1 - t0, 2)
        timings["to_host_s"] = round(t2 - t1, 2)
        timings["cut_s"] = round(t3 - t2, 2)
        timings["roi_track_s"] = round(t4 - t3, 2)
        timings["roi_crop_s"] = round(t5 - t4, 2)

    keep = np.isfinite(stripped_host)
    over = keep & (vol_host > cfg.metal_hu)
    metrics = {
        "voxels_total": int(vol_host.size),
        "voxels_removed": n_removed,
        "removed_fraction": n_removed / vol_host.size,
        "kept_voxels": int(keep.sum()),
        "kept_metal_voxels": int(over.sum()),
        "kept_max_hu": float(vol_host[over].max()) if over.any() else None,
        "kept_max_intensity": float(vol_host[over].max()) if over.any() else None,
        "intensity_unit": meta.get("intensity_unit", "HU"),
    }
    return {
        "vol_host": vol_host, "cut_from": cut_from, "diag": diag,
        "stripped": stripped_host, "n_removed": n_removed,
        "n_curtain_rows": n_curtain_rows,
        "track": track, "footprints": footprints,
        "roi_vol": roi_vol, "roi_bbox": bbox, "metrics": metrics,
        "air_crop_info": air_crop_info,
    }


# ---------------------------------------------------------------------------
# QA
# ---------------------------------------------------------------------------
def _cmap():
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import colors as mcolors
    cdict = {
        "red":   [(0, 0, 0), (.30, 0, 0), (.55, .9, .9), (.75, 1, 1), (1, 1, 1)],
        "green": [(0, 0, 0), (.30, .6, .6), (.55, .3, .3), (.75, .9, .9), (1, 1, 1)],
        "blue":  [(0, 0, 0), (.30, .6, .6), (.55, .1, .1), (.75, 0, 0), (1, 1, 1)],
    }
    return mcolors.LinearSegmentedColormap("wm", cdict)


def save_qa_montage(vol: np.ndarray, stripped: np.ndarray, cut_from: int,
                    sample: str, out_dir: Path,
                    pick_idx: Sequence[int],
                    window: tuple[float, float] = (-1200.0, 300.0)) -> None:
    import matplotlib.pyplot as plt
    cmap = _cmap()
    fig, axes = plt.subplots(len(pick_idx), 2, figsize=(7.4, 3.0 * len(pick_idx)),
                             facecolor="#202020")
    axes = np.atleast_2d(axes)
    for r, i in enumerate(pick_idx):
        panels = [
            (vol[i], f"slice {i} original", cmap, window[0], window[1]),
            (stripped[i], f"slice {i} stripped (NaN=grey)", cmap, window[0], window[1]),
        ]
        for c, (img, title, cm, vmin, vmax) in enumerate(panels):
            ax = axes[r, c]
            ax.set_facecolor("#404040")
            ax.imshow(img, cmap=cm, vmin=vmin, vmax=vmax,
                      interpolation="nearest")
            ax.set_title(title, fontsize=8, color="w")
            ax.axis("off")
    fig.suptitle(f"{sample}: platform removal (cut from slice {cut_from})",
                 color="w")
    fig.tight_layout()
    out = out_dir / f"{sample}_qa_removal.png"
    fig.savefig(out, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  QA montage: {out}")


def save_roi_qa(vol: np.ndarray, roi_vol: np.ndarray, bbox,
                sample: str, out_dir: Path, pick_idx: Sequence[int],
                window: tuple[float, float] = (-1200.0, 300.0)) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    cmap = _cmap()
    z0, z1, y0, y1, x0, x1 = bbox
    fig, axes = plt.subplots(len(pick_idx), 2, figsize=(7.2, 3.0 * len(pick_idx)),
                             facecolor="#202020")
    axes = np.atleast_2d(axes)
    for r, i in enumerate(pick_idx):
        zi = min(max(i, z0), z1)
        ax = axes[r, 0]
        ax.set_facecolor("#404040")
        ax.imshow(vol[zi], cmap=cmap, vmin=window[0], vmax=window[1],
                  interpolation="nearest")
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0,
                               fill=False, edgecolor="#00e5ff", lw=1.2))
        ax.set_title(f"z={zi} original + ROI box", fontsize=8, color="w")
        ax.axis("off")
        ax = axes[r, 1]
        ax.set_facecolor("#404040")
        ax.imshow(roi_vol[zi - z0], cmap=cmap, vmin=window[0], vmax=window[1],
                  interpolation="nearest")
        ax.set_title(f"z={zi} ROI crop", fontsize=8, color="w")
        ax.axis("off")
    fig.suptitle(f"{sample}: wood ROI extraction QA", color="w")
    fig.tight_layout()
    out = out_dir / f"{sample}_qa_roi.png"
    fig.savefig(out, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  ROI QA montage: {out}")


# ---------------------------------------------------------------------------
# diagnose / process
# ---------------------------------------------------------------------------
def diagnose(vol, meta: dict, cfg: Config, name: str, ds: DatasetSpec,
             gpu, mcnt: np.ndarray, prof: np.ndarray) -> dict:
    n = prof.size
    unit = str(meta.get("intensity_unit") or "HU")
    cut_from, diag = platform_cut_index(mcnt, prof, cfg)
    print(f"\n=== DIAGNOSE {name} [{ds.key}] ({n} slices) ===")
    print(f"anchor slice {diag['anchor_slice']}, baseline "
          f"{diag['baseline_hu']:.2f} {unit}, halo limit "
          f"{diag['halo_limit_hu']:.2f} {unit}, drift "
          f"{diag['drift_hu_per_slice']:.3f} {unit}/slice")
    print(f"halo onset -> cut_from = {cut_from} "
          f"(accepted by {diag['accepted_by']}, "
          f"slope3 {diag['onset_slope3_hu']:.2f}, "
          f"rise15 {diag['onset_rise15_hu']:.2f}, "
          f"{diag['n_candidates']} raw candidates; "
          f"profile {diag['profile_at_cut']:.2f} {unit} at cut)")
    gt = ds.ground_truth.get(name)
    if gt is not None:
        print(f"ground truth ({name} cleaned): kept 0..{gt - 1} "
              f"-> manual cut_from = {gt}; "
              f"difference = {cut_from - gt:+d} slices "
              f"({(cut_from - gt) * meta['slice_thickness_mm'] * 1000:+.0f} um)")

    print(f"\nbottom-40% mean-{unit} profile near the cut (every slice from "
          "cut_from-8 to cut_from+8):")
    for i in range(max(0, cut_from - 8), min(n, cut_from + 9)):
        mark = "  <-- cut" if i == cut_from else ""
        print(f"  [{i:4d}] {prof[i]:9.2f}{mark}")
    return {"cut_from": cut_from, "diag": diag}


def process_sample(name: str, cfg: Config, ds: DatasetSpec, diagnose_only: bool,
                   gpu, verbose: bool = True) -> dict:
    t0 = time.perf_counter()
    timings: dict = {}
    print(f"\n################  {name} [{ds.key}]  ################")
    vol, meta = load_dataset_volume(ds, name, gpu, workers=cfg.io_workers,
                                    timings=timings)
    if ds.source_kind != "dicom":
        from volume_io import adaptive_thresholds
        adaptive = adaptive_thresholds(meta, cfg)
        if adaptive:
            cfg = cfg.overridden(adaptive)
            meta["threshold_strategy"] = (
                "robust source-intensity percentiles; estimated thresholds, "
                "source voxel values preserved")
        else:
            meta["threshold_strategy"] = "stored values treated as HU"
        if cfg.save_dicom:
            # A TIFF/NIfTI source has no DICOM acquisition metadata or source
            # SOP references. Never synthesize misleading DICOM derivatives.
            cfg = cfg.overridden({"save_dicom": False})
        meta["source_kind"] = ds.source_kind
    print(f"loaded {meta['n_slices']} slices "
          f"({vol.shape[0]}x{vol.shape[1]}x{vol.shape[2]}), "
          f"voxel {float(meta['pixel_spacing_yx_mm'][0]) * 1000:.2f} um "
          f"[load {timings.get('load_headers_s', 0)}+"
          f"{timings.get('load_pixels_s', 0)} s]")

    mcnt = metal_counts(vol, gpu, cfg.metal_hu)
    prof = bottom_mean_profile(vol, gpu, cfg.baseline_row_frac)

    if diagnose_only:
        out = diagnose(vol, meta, cfg, name, ds, gpu, mcnt, prof)
        gpu.release()
        return {"sample": name, "dataset": ds.key, "mode": "diagnose", **out}

    res = analyze(vol, meta, cfg, gpu, timings=timings, verbose=verbose)
    del vol                                    # host copy kept via res
    cut_from = res["cut_from"]
    track = res["track"]
    print(f"platform: cut from slice {cut_from} "
          f"(anchor {res['diag']['anchor_slice']}, baseline "
          f"{res['diag']['baseline_hu']:.2f} {meta.get('intensity_unit', 'HU')}, by "
          f"{res['diag']['accepted_by']}); removed "
          f"{res['metrics']['voxels_removed']} voxels "
          f"({res['metrics']['removed_fraction']:.2%}); "
          f"curtain rows voided: {res['n_curtain_rows']}")
    print(f"wood ROI: tracked {track.n_slices_tracked} slices "
          f"z {track.z0}..{track.z1}, envelope y {track.y0}..{track.y1} "
          f"x {track.x0}..{track.x1}, bbox={res['roi_bbox']}")
    gt = ds.ground_truth.get(name)
    if gt is not None:
        print(f"ground truth check: manual cut_from = {gt}, "
              f"pipeline = {cut_from} ({cut_from - gt:+d} slices)")

    out_dir = output_root(ds) / name
    out_dir.mkdir(parents=True, exist_ok=True)

    if cfg.keep_from >= cut_from:
        if res["diag"].get("anchor_slice", 0) == 0 and cfg.keep_from >= cut_from:
            # no-platform specimen with an over-generous keep line: the
            # delivery must still contain at least one slice
            raise RuntimeError(
                f"keep_from {cfg.keep_from} must be below the cut slice "
                f"{cut_from} — adjust the Top Keep / Bottom Cut lines")
        raise RuntimeError(
            f"keep_from {cfg.keep_from} must be below the cut slice {cut_from}")
    if cfg.keep_from > 0:
        # collection range starts above the ROI top: trim the delivery ROI
        bb = res.get("roi_bbox")
        if bb and bb[0] < cfg.keep_from:
            z0 = min(int(cfg.keep_from), bb[1])
            res["roi_vol"] = res["roi_vol"][z0 - bb[0]:]
            res["roi_bbox"] = (z0, bb[1], *bb[2:])

    report = {
        "sample": name,
        "dataset": ds.key,
        "config": cfg.as_dict(),
        "meta": meta,
        "gpu": asdict(gpu.info),
        "timings_s": timings,
        "platform": {
            "cut_from": int(cut_from),
            "keep_from": int(cfg.keep_from),
            **{k: (float(v) if isinstance(v, float) else v)
               for k, v in res["diag"].items()},
        },
        "curtain_rows_voided": int(res["n_curtain_rows"]),
        "wood_roi": {
            "track": asdict(track),
            "bbox_zyx": list(res["roi_bbox"]) if res["roi_bbox"] else None,
            "air_crop": res.get("air_crop_info"),
        },
        "metrics": res["metrics"],
        "ground_truth": {"manual_kept_slices": gt} if gt else None,
    }

    if res["roi_vol"] is None or res["roi_bbox"] is None:
        raise RuntimeError("wood ROI extraction produced no deliverable volume")
    is_dicom = ds.source_kind == "dicom"
    source_files = sorted_source_files(ds.source / name) if is_dicom else None
    delivery: dict = {}
    t_out = time.perf_counter()
    if cfg.save_nifti:
        delivery.update(write_roi_nifti(
            res["roi_vol"], out_dir / "wood_roi.nii",
            source_files=source_files,
            source_affine_xyz=(None if is_dicom
                               else meta["affine_ras_xyz"]),
            source_metadata=(None if is_dicom else meta),
            bbox=res["roi_bbox"],
            dataset_key=ds.key, specimen_id=name,
        ))
    t_nii = time.perf_counter()
    if cfg.save_dicom and is_dicom:
        delivery.update(export_roi_dicom_series(
            ds.source / name, out_dir, report, ds.key, name,
        ))
    elif not is_dicom:
        delivery["dicom"] = {"skipped": True,
                             "reason": "source has no DICOM acquisition metadata"}
    t_dicom = time.perf_counter()
    if cfg.save_stripped_nii and res.get("stripped") is not None:
        # audit 0N: streamed plane writes replace the in-RAM transpose +
        # nib.save (byte-identical output, ~2-4x faster, no full-volume copy)
        t_stripped0 = time.perf_counter()
        write_stripped_nifti(
            np.asarray(res["stripped"], dtype=np.float32),
            out_dir / "stripped.nii", source_files=source_files,
            source_affine_xyz=(None if is_dicom
                               else meta["affine_ras_xyz"]),
            source_metadata=(None if is_dicom else meta),
            cut_from=cut_from, dataset_key=ds.key, specimen_id=name)
        timings["stripped_nii_write_s"] = round(
            time.perf_counter() - t_stripped0, 2)
    report["delivery"] = delivery

    if cfg.save_qa_montage:
        picks = [0, meta["n_slices"] // 2, cut_from - 10, cut_from - 1,
                 cut_from + 5, meta["n_slices"] - 1]
        picks = sorted({p for p in picks if 0 <= p < meta["n_slices"]})
        qa_window = (-1200.0, 300.0)
        if cfg.intensity_auto_calibrated:
            spread = max(1.0, cfg.wood_hu_max - cfg.wood_hu_min)
            qa_window = (cfg.wood_hu_min - 0.25 * spread,
                         cfg.wood_hu_max + 0.25 * spread)
        save_qa_montage(res["vol_host"], res["stripped"], cut_from, name,
                        out_dir, picks, window=qa_window)
        if res["roi_vol"] is not None:
            save_roi_qa(res["vol_host"], res["roi_vol"], res["roi_bbox"],
                        name, out_dir, picks, window=qa_window)

    timings.update(nifti_write_s=round(t_nii - t_out, 2),
                   dicom_write_s=round(t_dicom - t_nii, 2))
    write_provenance(out_dir, report, delivery)
    with open(out_dir / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  report: {out_dir / 'report.json'} "
          f"(nii {timings['nifti_write_s']} s, DICOM "
          f"{timings['dicom_write_s']} s)")
    print(f"elapsed {time.perf_counter() - t0:.1f} s "
          f"[detect {timings.get('detect_s')} s, roi {timings.get('roi_track_s')} s]")
    return report


def validate_dataset(ds: DatasetSpec, cfg: Config, gpu) -> int:
    """Detector-only validation of every sample of a dataset.

    For 24um this must reproduce every stored legacy report's cut exactly
    (and the 1-15 ground truth); for 66um it prints the detected cuts.
    Returns the number of mismatches.
    """
    legacy = OUT_ROOT / ds.out_sub if ds.out_sub else OUT_ROOT
    bad = 0
    for name in discover_samples(ds):
        try:
            vol, meta = load_volume(ds.source / name, gpu,
                                    workers=cfg.io_workers)
            mcnt = metal_counts(vol, gpu, cfg.metal_hu)
            prof = bottom_mean_profile(vol, gpu, cfg.baseline_row_frac)
            cut, diag = platform_cut_index(mcnt, prof, cfg)
            gpu.release()
            rep_path = legacy / name / "report.json"
            ref = None
            if rep_path.exists():
                ref = json.loads(rep_path.read_text())["platform"]["cut_from"]
            gt = ds.ground_truth.get(name)
            line = (f"  {name}: cut {cut} (by {diag['accepted_by']}, "
                    f"n_cand {diag['n_candidates']}, fallback "
                    f"{diag['fallback']})")
            if ref is not None:
                line += f" | stored {ref}"
                if ref != cut:
                    line += "  MISMATCH"
                    bad += 1
            if gt is not None:
                line += f" | GT {gt}"
                if gt != cut:
                    line += "  MISMATCH"
                    bad += 1
            print(line)
            del vol
            gpu.release()
        except Exception as exc:
            print(f"  {name}: FAILED {type(exc).__name__}: {exc}")
            bad += 1
    return bad


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default="24um", choices=sorted(DATASETS),
                    help="which registered dataset to work on")
    ap.add_argument("--list", action="store_true",
                    help="list discoverable samples and exit")
    ap.add_argument("--all", action="store_true", help="process all samples")
    ap.add_argument("--sample", help="process a single sample")
    ap.add_argument("--samples", nargs="+", help="process several samples")
    ap.add_argument("--diagnose", action="store_true",
                    help="print diagnostics only, write no outputs")
    ap.add_argument("--validate", action="store_true",
                    help="detector-only validation against stored reports/GT")
    ap.add_argument("--no-curtain", action="store_true",
                    help="disable air-curtain voiding")
    ap.add_argument("--cpu", action="store_true",
                    help="force CPU even if a GPU is available")
    ap.add_argument("--backend", choices=["auto", "torch", "cupy", "cpu"],
                    default="auto", help="compute backend (default: auto)")
    ap.add_argument("--gpu-index", type=int,
                    help="framework-visible CUDA device index (default: best free memory)")
    ap.add_argument("--no-dicom", action="store_true",
                    help="skip cropped ROI DICOM output")
    ap.add_argument("--workers", type=int, default=8,
                    help="DICOM read threads")
    args = ap.parse_args(argv)

    ds = DATASETS[args.dataset]
    cfg = DEFAULTS.overridden(ds.config_overrides)
    cfg.io_workers = args.workers
    if args.no_curtain:
        cfg.curtain_removal = False
    if args.no_dicom:
        cfg.save_dicom = False

    preference = "cpu" if args.cpu else args.backend
    gpu = get_backend(verbose=True, preference=preference,
                      device_index=args.gpu_index)

    samples = discover_samples(ds)
    if args.list:
        print(f"[{ds.key}] {len(samples)} samples: {samples}")
        return 0

    if args.validate:
        bad = validate_dataset(ds, cfg, gpu)
        print(f"\nvalidation mismatches: {bad}")
        return 1 if bad else 0

    if args.sample:
        names = [args.sample]
    elif args.samples:
        names = args.samples
    elif args.all:
        names = samples
    else:
        ap.error("choose --list, --all, --sample, --samples, --diagnose "
                 "or --validate")

    failures = 0
    for nm in names:
        if nm not in samples:
            print(f"unknown sample '{nm}'; available: {samples}")
            return 2
        try:
            process_sample(nm, cfg, ds, args.diagnose, gpu)
        except Exception as exc:  # keep the batch going
            failures += 1
            print(f"!! {nm} FAILED: {type(exc).__name__}: {exc}")
    print(f"\ndone: {len(names) - failures}/{len(names)} ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
