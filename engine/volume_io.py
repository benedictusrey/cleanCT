#!/usr/bin/env python
"""Validated, slice-oriented readers for non-DICOM cleanCT volumes.

The processing engine uses one canonical array contract: float32 ``(z, y, x)``
with right-anterior-superior millimetre geometry. DICOM stays on its existing
validated path; this module handles TIFF stacks and 3-D NIfTI without forcing
the viewer to materialize a full source volume.
"""
from __future__ import annotations

import atexit
import errno
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

import numpy as np


class VolumeInputError(ValueError):
    """An input is empty, ambiguous, malformed, or not a supported volume."""


_NIFTI_CACHE_LOCK = threading.RLock()
_NIFTI_CACHE: dict[str, Path] = {}
_NUMERIC_KINDS = "iuf"


def _natural_key(path: Path):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", path.name)]


def _unit_to_mm(unit: str | None) -> float | None:
    value = (unit or "").strip().lower().replace("μ", "u").replace("µ", "u")
    return {"mm": 1.0, "millimeter": 1.0, "millimetre": 1.0,
            "m": 1000.0, "meter": 1000.0, "metre": 1000.0,
            "um": 0.001, "micron": 0.001, "micrometer": 0.001,
            "micrometre": 0.001, "nm": 1e-6, "cm": 10.0}.get(value)


def _sample_stats(planes: list[np.ndarray]) -> dict:
    chunks = []
    for plane in planes:
        a = np.asarray(plane)
        if a.ndim != 2 or a.size == 0:
            raise VolumeInputError("source contains an empty or non-2-D slice")
        if a.dtype.kind not in _NUMERIC_KINDS:
            raise VolumeInputError(f"unsupported pixel type: {a.dtype}")
        sample = np.asarray(a[::16, ::16], dtype=np.float32).ravel()
        if not np.isfinite(sample).all():
            raise VolumeInputError("source contains NaN or infinite pixel values")
        if sample.size:
            chunks.append(sample)
    if not chunks:
        raise VolumeInputError("source contains no readable pixel data")
    values = np.concatenate(chunks)
    if not np.isfinite(values).all():
        raise VolumeInputError("source contains non-finite pixel values")
    qs = np.percentile(values, [2, 5, 10, 50, 90, 95, 98, 99, 99.5])
    names = ("p02", "p05", "p10", "p50", "p90", "p95", "p98", "p99", "p995")
    return {name: float(v) for name, v in zip(names, qs)}


def _intensity_mode(stats: dict, requested: str = "auto") -> str:
    requested = str(requested or "auto").lower()
    if requested in {"hu", "raw"}:
        return requested
    if requested != "auto":
        raise VolumeInputError(f"unknown intensity interpretation: {requested}")
    # Signed, negative-to-positive reconstructions are commonly HU-like.
    # Positive-only grayscale is treated as raw and gets explicit adaptive
    # thresholds recorded in the processing report.
    return "hu" if stats["p02"] < 0 < stats["p98"] else "raw"


def _source_signature(path: Path, members: list[Path] | None = None) -> dict:
    paths = members if members is not None else [path]
    rows = []
    digest = hashlib.sha256()
    for item in paths:
        try:
            st = item.stat()
        except OSError as exc:
            raise VolumeInputError(f"cannot access source file {item}: {exc}") from exc
        token = f"{item.resolve()}|{st.st_size}|{st.st_mtime_ns}\n"
        digest.update(token.encode("utf-8", errors="replace"))
        rows.append({"name": item.name, "bytes": int(st.st_size),
                     "mtime_ns": int(st.st_mtime_ns)})
    return {"sha256": digest.hexdigest(), "files": len(rows),
            "total_bytes": sum(row["bytes"] for row in rows),
            "members": rows if len(rows) <= 128 else []}


def detect_source_kind(path: str | Path) -> str:
    """Detect DICOM, TIFF, or NIfTI from a selected file/folder."""
    path = Path(path).expanduser()
    if path.is_file():
        name = path.name.lower()
        if name.endswith((".nii", ".nii.gz")):
            return "nifti"
        if path.suffix.lower() in {".tif", ".tiff"}:
            return "tiff"
        if path.suffix.lower() == ".dcm":
            return "dicom"
        raise VolumeInputError(
            f"unsupported file type: {path.name}; choose .dcm, .tif/.tiff, or .nii/.nii.gz")
    if not path.is_dir():
        raise VolumeInputError(f"source path does not exist: {path}")

    root = path / "XY" if (path / "XY").is_dir() else path
    found = set()
    if any(root.glob("*.dcm")):
        found.add("dicom")
    if any(root.glob("*.tif")) or any(root.glob("*.tiff")):
        found.add("tiff")
    if any(p.name.lower().endswith((".nii", ".nii.gz")) for p in root.iterdir()
           if p.is_file()):
        found.add("nifti")
    if not found:
        child_hits = []
        for child in root.iterdir():
            if child.is_dir() and (any(child.glob("*.dcm")) or
                                   any(child.glob("*.tif")) or
                                   any(child.glob("*.tiff"))):
                child_hits.append(child)
        if len(child_hits) == 1:
            return detect_source_kind(child_hits[0])
        if len(child_hits) > 1:
            raise VolumeInputError("folder contains multiple candidate image series; choose one series folder")
    if len(found) > 1:
        raise VolumeInputError(
            "folder contains more than one supported format; choose a single file or format-specific series folder")
    if not found:
        raise VolumeInputError("folder contains no .dcm series or TIFF slices")
    return next(iter(found))


def _resolve_tiff(path: Path) -> tuple[Path, list[Path]]:
    if path.is_file():
        if path.suffix.lower() not in {".tif", ".tiff"}:
            raise VolumeInputError("select a TIFF file or a folder containing TIFF slices")
        return path, []
    if not path.is_dir():
        raise VolumeInputError(f"TIFF source not found: {path}")
    root = path / "XY" if (path / "XY").is_dir() else path
    files = sorted([*root.glob("*.tif"), *root.glob("*.tiff")], key=_natural_key)
    files = [p for p in files if p.is_file()]
    if not files:
        children = []
        for child in root.iterdir():
            if child.is_dir() and (any(child.glob("*.tif")) or
                                   any(child.glob("*.tiff"))):
                children.append(child)
        if len(children) == 1:
            root = children[0]
            files = sorted([*root.glob("*.tif"), *root.glob("*.tiff")],
                           key=_natural_key)
            files = [p for p in files if p.is_file()]
        elif len(children) > 1:
            raise VolumeInputError("folder contains multiple TIFF series; choose one series folder")
    if not files:
        raise VolumeInputError(f"no TIFF slices found in {root}")
    return root, files


def _tiff_resolution_mm(page, tag_name: str) -> float | None:
    tag = page.tags.get(tag_name)
    unit = page.tags.get("ResolutionUnit")
    if tag is None or unit is None:
        return None
    try:
        value = float(tag.value[0]) / float(tag.value[1])
        unit_code = int(unit.value)
        mm_per_unit = {2: 25.4, 3: 10.0}.get(unit_code)
        return mm_per_unit / value if value > 0 and mm_per_unit else None
    except Exception:
        return None


def _ome_spacing(description: str) -> tuple[float | None, float | None, float | None]:
    if not description or "<OME" not in description:
        return None, None, None
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(description)
        pixels = next(node for node in root.iter()
                      if node.tag.rsplit("}", 1)[-1] == "Pixels")
        def val(axis: str):
            raw = pixels.attrib.get(f"PhysicalSize{axis}")
            if raw is None:
                return None
            unit = pixels.attrib.get(f"PhysicalSize{axis}Unit", "µm")
            factor = _unit_to_mm(unit)
            value = float(raw)
            return value * factor if factor and np.isfinite(value) and value > 0 else None
        return val("Z"), val("Y"), val("X")
    except Exception:
        return None, None, None


def _inspect_tiff(path: Path, intensity: str = "auto",
                  memory_check=None) -> dict:
    try:
        import tifffile
    except Exception as exc:
        raise VolumeInputError(f"TIFF support is unavailable: {exc}") from exc
    root, files = _resolve_tiff(path)
    planes: list[np.ndarray] = []
    if files:
        if len(files) < 2:
            raise VolumeInputError("a TIFF slice folder needs at least two images")
        try:
            with tifffile.TiffFile(files[0]) as tf:
                if len(tf.pages) != 1 or len(tf.pages[0].shape) != 2:
                    raise VolumeInputError(
                        f"{files[0].name}: expected one monochrome 2-D image per slice")
                shape = tuple(tf.pages[0].shape)
                dtype = np.dtype(tf.pages[0].dtype)
        except VolumeInputError:
            raise
        except Exception as exc:
            raise VolumeInputError(f"{files[0].name}: invalid TIFF header: {exc}") from exc
        if dtype.kind not in _NUMERIC_KINDS:
            raise VolumeInputError(f"{files[0].name}: unsupported pixel type {dtype}")
        n, (rows, cols) = len(files), shape
        if memory_check:
            memory_check(n, rows, cols, 1)
        # Validate every slice header for dimensions, page count, dtype, and
        # orientation before a long processing job begins; only three pixel
        # payloads are decoded here to keep registration quick.
        for file in files:
            try:
                with tifffile.TiffFile(file) as tf:
                    if len(tf.pages) != 1:
                        raise VolumeInputError(f"{file.name}: expected one image page per file")
                    page = tf.pages[0]
                    if (tuple(page.shape) != tuple(shape) or
                            np.dtype(page.dtype) != np.dtype(dtype)):
                        raise VolumeInputError(f"{file.name}: inconsistent slice dimensions or pixel type")
                    orientation = page.tags.get("Orientation")
                    if orientation is not None and int(orientation.value) != 1:
                        raise VolumeInputError(f"{file.name}: TIFF orientation must be top-left (1)")
            except VolumeInputError:
                raise
            except Exception as exc:
                raise VolumeInputError(f"{file.name}: invalid TIFF header: {exc}") from exc
        picks = sorted({0, n // 2, n - 1})
        for i in picks:
            try:
                with tifffile.TiffFile(files[i]) as tf:
                    a = tf.pages[0].asarray()
            except Exception as exc:
                raise VolumeInputError(
                    f"{files[i].name}: could not read TIFF pixels: {exc}") from exc
            if a.shape != shape or a.dtype != dtype or not np.isfinite(a).all():
                raise VolumeInputError(
                    f"{files[i].name}: invalid shape, pixel type, or pixel values")
            planes.append(a)
        with tifffile.TiffFile(files[0]) as tf:
            page = tf.pages[0]
            dz, dy, dx = _ome_spacing(str(page.description or ""))
            dy = dy or _tiff_resolution_mm(page, "YResolution")
            dx = dx or _tiff_resolution_mm(page, "XResolution")
        source_members = files
        axes = "ZYX (natural filename order)"
    else:
        try:
            with tifffile.TiffFile(path) as tf:
                if not tf.series:
                    raise VolumeInputError("TIFF contains no image series")
                if len(tf.series) != 1:
                    raise VolumeInputError("TIFF contains multiple image series; select a single-series file")
                series = tf.series[0]
                shape3 = tuple(int(x) for x in series.shape)
                axes = str(series.axes)
                if (len(shape3) != 3 or len(axes) != 3 or
                        axes[-2:] != "YX" or axes[0] in "CT"):
                    raise VolumeInputError(
                        f"unsupported TIFF axes {axes!r}; expected a grayscale ZYX/page stack")
                n, rows, cols = shape3
                if n < 2 or not series.pages:
                    raise VolumeInputError("TIFF must contain at least two 2-D slices")
                if len(series.pages) < n:
                    raise VolumeInputError("TIFF page count is shorter than its declared volume")
                page_dtype = np.dtype(series.pages[0].dtype)
                if page_dtype.kind not in _NUMERIC_KINDS:
                    raise VolumeInputError(
                        f"TIFF page 0: unsupported pixel type {page_dtype}")
                for i, page in enumerate(series.pages):
                    if tuple(page.shape) != (rows, cols):
                        raise VolumeInputError(f"TIFF page {i}: inconsistent slice shape")
                    orientation = page.tags.get("Orientation")
                    if orientation is not None and int(orientation.value) != 1:
                        raise VolumeInputError(f"TIFF page {i}: orientation must be top-left (1)")
                    if np.dtype(page.dtype) != page_dtype:
                        raise VolumeInputError(f"TIFF page {i}: inconsistent pixel type")
                if memory_check:
                    memory_check(n, rows, cols, 1)
                picks = sorted({0, n // 2, n - 1})
                for i in picks:
                    page = series.pages[i]
                    if int(getattr(page, "imagedepth", 1) or 1) != 1:
                        raise VolumeInputError(
                            "multi-sample/color TIFF data is not supported")
                    plane = page.asarray()
                    if not np.isfinite(plane).all():
                        raise VolumeInputError(
                            f"TIFF page {i}: pixel values are not finite")
                    planes.append(plane)
                page0 = series.pages[0]
                dz, dy, dx = _ome_spacing(str(page0.description or ""))
                dy = dy or _tiff_resolution_mm(page0, "YResolution")
                dx = dx or _tiff_resolution_mm(page0, "XResolution")
                source_members = None
        except VolumeInputError:
            raise
        except Exception as exc:
            raise VolumeInputError(f"could not inspect TIFF stack: {exc}") from exc
    if len({p.dtype.str for p in planes}) != 1:
        raise VolumeInputError("TIFF slices use inconsistent pixel types")
    if any(p.shape != (rows, cols) for p in planes):
        raise VolumeInputError("TIFF contains mismatched slice dimensions")
    stats = _sample_stats(planes)
    mode = _intensity_mode(stats, intensity)
    assumed = not all(v and v > 0 for v in (dz, dy, dx))
    dz = float(dz or 1.0)
    dy = float(dy or 1.0)
    dx = float(dx or 1.0)
    affine = np.diag([dx, dy, dz, 1.0]).astype(float)
    sig = _source_signature(path, source_members)
    return {
        "source_kind": "tiff", "source_path": str(path.resolve()),
        "source_format": "multipage TIFF" if not files else "TIFF slice series",
        "source_signature": sig, "shape_zyx": [n, rows, cols],
        "spacing_zyx_mm": [dz, dy, dx],
        "pixel_spacing_yx_mm": [dy, dx], "slice_thickness_mm": dz,
        "voxel_mm3": dz * dy * dx, "affine_ras_xyz": affine.tolist(),
        "orientation": "RAS+ (assumed axis aligned)",
        "geometry_assumed": bool(assumed), "tiff_axes": axes,
        "dtype": planes[0].dtype.str, "intensity_mode": mode,
        "intensity_unit": "HU" if mode == "hu" else "stored grayscale values",
        "intensity_sample_percentiles": stats,
        "sample_count": len(planes),
    }


def _nifti_context(path: Path):
    try:
        import nibabel as nib
        img = nib.load(str(path), mmap=True)
    except Exception as exc:
        raise VolumeInputError(f"could not read NIfTI header: {exc}") from exc
    if len(img.shape) != 3 or any(int(n) <= 0 for n in img.shape):
        raise VolumeInputError(f"NIfTI must be a non-empty 3-D volume; got shape {img.shape}")
    affine = np.asarray(img.affine, dtype=np.float64)
    if affine.shape != (4, 4) or not np.isfinite(affine).all():
        raise VolumeInputError("NIfTI affine is missing or non-finite")
    try:
        spatial_unit, _time_unit = img.header.get_xyzt_units()
    except Exception:
        spatial_unit = None
    factor = {"mm": 1.0, "meter": 1000.0, "micron": 0.001}.get(spatial_unit)
    unit_assumed = factor is None
    factor = float(factor or 1.0)
    affine_mm = affine.copy()
    affine_mm[:3, :] *= factor
    if abs(float(np.linalg.det(affine_mm[:3, :3]))) < 1e-12:
        raise VolumeInputError("NIfTI affine has zero or invalid voxel spacing")
    spacing_xyz = np.linalg.norm(affine_mm[:3, :3], axis=0)
    if not np.isfinite(spacing_xyz).all() or np.any(spacing_xyz <= 0):
        raise VolumeInputError("NIfTI voxel spacing must be finite and positive")
    try:
        source_ornt = nib.orientations.io_orientation(affine_mm)
        target_ornt = nib.orientations.axcodes2ornt(("R", "A", "S"))
        transform = nib.orientations.ornt_transform(source_ornt, target_ornt)
        inv = nib.orientations.inv_ornt_aff(transform, img.shape)
        affine_ras = affine_mm @ inv
    except Exception as exc:
        raise VolumeInputError(f"could not resolve NIfTI axis orientation: {exc}") from exc
    if not np.isfinite(affine_ras).all():
        raise VolumeInputError("NIfTI canonical affine is not finite")
    shape_xyz = tuple(int(x) for x in img.shape)
    shape_zyx = tuple(shape_xyz[i] for i in np.argsort(transform[:, 0])[::-1])
    # Sorting explicitly from output xyz dimensions avoids assumptions about
    # the source axis order after RAS canonicalization.
    out_shape_xyz = tuple(shape_xyz[int(np.where(transform[:, 0] == i)[0][0])]
                          for i in range(3))
    shape_zyx = (out_shape_xyz[2], out_shape_xyz[1], out_shape_xyz[0])
    return nib, img, transform, affine_ras, shape_zyx, spacing_xyz, unit_assumed


def _read_nifti_plane(img, transform: np.ndarray, z: int) -> np.ndarray:
    src_shape = tuple(int(x) for x in img.shape)
    src_z_axes = np.flatnonzero(np.asarray(transform)[:, 0].astype(int) == 2)
    if len(src_z_axes) != 1:
        raise VolumeInputError("NIfTI orientation does not map one source axis to slices")
    fixed_axis = int(src_z_axes[0])
    fixed_index = int(z)
    if int(transform[fixed_axis, 1]) < 0:
        fixed_index = src_shape[fixed_axis] - 1 - fixed_index
    selection: list[slice | int] = [slice(None)] * 3
    selection[fixed_axis] = fixed_index
    try:
        raw = np.asarray(img.dataobj[tuple(selection)], dtype=np.float32)
    except Exception as exc:
        raise VolumeInputError(f"could not decode NIfTI slice {z}: {exc}") from exc
    remaining = [axis for axis in range(3) if axis != fixed_axis]
    for position, axis in enumerate(remaining):
        if int(transform[axis, 1]) < 0:
            raw = np.flip(raw, axis=position)
    out_axes = [int(transform[axis, 0]) for axis in remaining]
    permutation = (out_axes.index(0), out_axes.index(1))
    plane_xy = np.transpose(raw, permutation)
    plane_yx = plane_xy.T
    if plane_yx.ndim != 2 or not np.isfinite(plane_yx).all():
        raise VolumeInputError(f"NIfTI slice {z} has invalid pixel values")
    return np.asarray(plane_yx, dtype=np.float32)


def _nifti_expected_file_bytes(img) -> int:
    """Return the complete NIfTI header/extension plus voxel payload size."""
    dtype = np.dtype(img.get_data_dtype())
    offset = int(round(float(img.header.get_data_offset() or 352)))
    expected = offset + math.prod(int(dim) for dim in img.shape) * dtype.itemsize
    if expected < 352 or expected > (1 << 63) - 1:
        raise VolumeInputError("NIfTI declares an unsupported voxel payload size")
    return expected


def _nifti_expected_bytes_from_info(info: dict) -> int:
    """Support persisted source metadata written before expected-size caching."""
    cached = info.get("nifti_expected_bytes")
    if cached is not None:
        return int(cached)
    shape = tuple(int(dim) for dim in info["nifti_shape_xyz"])
    dtype = np.dtype(info["dtype"])
    offset = int(info.get("nifti_data_offset", 352))
    expected = offset + math.prod(shape) * dtype.itemsize
    if expected < 352 or expected > (1 << 63) - 1:
        raise VolumeInputError("NIfTI declares an unsupported voxel payload size")
    return expected


def _inspect_nifti(path: Path, intensity: str = "auto",
                   memory_check=None) -> dict:
    nib, img, transform, affine, shape_zyx, spacing_xyz, unit_assumed = _nifti_context(path)
    n, rows, cols = shape_zyx
    if n < 2:
        raise VolumeInputError("NIfTI must contain at least two slices")
    try:
        data_dtype = np.dtype(img.get_data_dtype())
        if data_dtype.kind not in _NUMERIC_KINDS:
            raise VolumeInputError(f"unsupported NIfTI pixel type: {data_dtype}")
        expected_bytes = _nifti_expected_file_bytes(img)
        if memory_check:
            memory_check(n, rows, cols, 1)
        if path.name.lower().endswith(".gz"):
            decoded = _decode_nifti_gz(path, expected_bytes)
            img = nib.load(str(decoded), mmap=True)
        samples = [_read_nifti_plane(img, transform, z)
                   for z in sorted({0, n // 2, n - 1})]
    except VolumeInputError:
        raise
    except Exception as exc:
        raise VolumeInputError(f"could not sample NIfTI pixels: {exc}") from exc
    if any(p.shape != (rows, cols) for p in samples):
        raise VolumeInputError("NIfTI canonical slices have inconsistent dimensions")
    stats = _sample_stats(samples)
    mode = _intensity_mode(stats, intensity)
    file_path = Path(path)
    signature = _source_signature(file_path)
    try:
        # Detect truncated uncompressed files before processing allocates RAM.
        if not file_path.name.lower().endswith(".gz"):
            if file_path.stat().st_size < expected_bytes:
                raise VolumeInputError(
                    f"NIfTI data is truncated ({file_path.stat().st_size} bytes; at least {expected_bytes} required)")
    except VolumeInputError:
        raise
    except Exception:
        pass
    spacing_zyx = [float(spacing_xyz[int(np.where(transform[:, 0] == axis)[0][0])])
                   for axis in (2, 1, 0)]
    return {
        "source_kind": "nifti", "source_path": str(file_path.resolve()),
        "source_format": ".nii.gz" if file_path.name.lower().endswith(".gz") else ".nii",
        "source_signature": signature, "shape_zyx": list(shape_zyx),
        "spacing_zyx_mm": spacing_zyx,
        "pixel_spacing_yx_mm": spacing_zyx[1:],
        "slice_thickness_mm": spacing_zyx[0],
        "voxel_mm3": float(np.prod(spacing_zyx)),
        "affine_ras_xyz": affine.tolist(),
        "orientation": "RAS+", "geometry_assumed": bool(unit_assumed),
        "nifti_transform": np.asarray(transform, dtype=float).tolist(),
        "nifti_shape_xyz": list(img.shape), "dtype": data_dtype.str,
        "nifti_expected_bytes": expected_bytes,
        "nifti_slope_intercept": [float(getattr(img.dataobj, "slope", 1.0) or 1.0),
                                   float(getattr(img.dataobj, "inter", 0.0) or 0.0)],
        "spatial_units_original": img.header.get_xyzt_units()[0] or "unknown",
        "intensity_mode": mode,
        "intensity_unit": "HU" if mode == "hu" else "stored NIfTI values",
        "intensity_sample_percentiles": stats,
    }


def inspect_source(path: str | Path, *, intensity: str = "auto",
                   memory_check=None) -> dict:
    """Inspect a TIFF or NIfTI source and validate metadata plus sample slices."""
    source = Path(path).expanduser().resolve()
    kind = detect_source_kind(source)
    if kind == "tiff":
        return _inspect_tiff(source, intensity=intensity,
                             memory_check=memory_check)
    if kind == "nifti":
        if source.is_dir():
            raise VolumeInputError("choose a specific .nii or .nii.gz file")
        return _inspect_nifti(source, intensity=intensity,
                              memory_check=memory_check)
    raise VolumeInputError("DICOM sources use the DICOM series validator")


def _tiff_read_planes(info: dict, zs: list[int]) -> dict[int, np.ndarray]:
    import tifffile
    path = Path(info["source_path"])
    root, files = _resolve_tiff(path)
    result = {}
    if files:
        for z in zs:
            try:
                with tifffile.TiffFile(files[z]) as tf:
                    a = tf.pages[0].asarray()
            except Exception as exc:
                raise VolumeInputError(f"{files[z].name}: could not decode TIFF slice: {exc}") from exc
            result[z] = np.asarray(a, dtype=np.float32)
    else:
        try:
            with tifffile.TiffFile(path) as tf:
                series = tf.series[0]
                for z in zs:
                    a = series.pages[z].asarray()
                    result[z] = np.asarray(a, dtype=np.float32)
        except Exception as exc:
            raise VolumeInputError(f"could not decode TIFF slice: {exc}") from exc
    rows, cols = (int(info["shape_zyx"][1]), int(info["shape_zyx"][2]))
    for z, a in result.items():
        if a.shape != (rows, cols) or a.ndim != 2 or not np.isfinite(a).all():
            raise VolumeInputError(f"TIFF slice {z} has invalid shape or pixel values")
    return result


def read_source_slices(path: str | Path, zs: list[int], *,
                       metadata: dict | None = None) -> dict[int, np.ndarray]:
    """Read selected source slices as float32 ``(y, x)`` arrays."""
    info = metadata or inspect_source(path)
    kind = info.get("source_kind")
    n = int(info["shape_zyx"][0])
    indices = sorted({int(z) for z in zs})
    if any(z < 0 or z >= n for z in indices):
        raise VolumeInputError(f"requested slice is outside the volume depth {n}")
    if not indices:
        return {}
    if kind == "tiff":
        return _tiff_read_planes(info, indices)
    if kind != "nifti":
        raise VolumeInputError(f"unsupported slice reader: {kind}")
    nifti_path = Path(info["source_path"])
    if nifti_path.name.lower().endswith(".gz"):
        nifti_path = _decode_nifti_gz(
            nifti_path, _nifti_expected_bytes_from_info(info))
    try:
        import nibabel as nib
        img = nib.load(str(nifti_path), mmap=True)
        transform = np.asarray(info["nifti_transform"], dtype=float)
    except Exception as exc:
        raise VolumeInputError(f"could not open NIfTI source slices: {exc}") from exc
    return {z: _read_nifti_plane(img, transform, z) for z in indices}


def _cleanup_stale_nifti_cache_dirs(cache_root: Path,
                                    stale_after_s: float = 3600.0) -> None:
    """Remove abandoned process caches without touching a live app's files."""
    try:
        children = list(cache_root.iterdir())
    except OSError:
        return
    now = time.time()
    for child in children:
        if child.is_symlink() or not child.is_dir() or not child.name.isdigit():
            continue
        try:
            pid = int(child.name)
            if pid == os.getpid() or now - child.stat().st_mtime < stale_after_s:
                continue
            os.kill(pid, 0)
            continue  # a different cleanCT process still owns this cache
        except PermissionError:
            continue  # process exists but this user cannot query it
        except OSError as exc:
            no_such_process = (
                exc.errno == errno.ESRCH
                or getattr(exc, "winerror", None) in {87, 1168})
            if not no_such_process:
                continue
        except (OverflowError, ValueError):
            continue
        shutil.rmtree(child, ignore_errors=True)


def _decode_nifti_gz(path: Path, expected_bytes: int | None = None) -> Path:
    """Decode a .nii.gz once into a bounded single-volume scratch cache.

    Nibabel's gzip ArrayProxy must otherwise restart decompression for each
    random slice. Keeping one decompressed source per process makes processing
    and interactive slice review linear-time. The temp is removed at shutdown.
    """
    if expected_bytes is None or int(expected_bytes) < 352:
        raise VolumeInputError("compressed NIfTI size could not be validated")
    expected_bytes = int(expected_bytes)
    key = f"{path.resolve()}|{path.stat().st_size}|{path.stat().st_mtime_ns}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:20]
    with _NIFTI_CACHE_LOCK:
        existing = _NIFTI_CACHE.get(digest)
        if (existing and existing.is_file()
                and existing.stat().st_size == expected_bytes):
            return existing
        # Bound the cache to one open source volume so repeated specimen
        # changes cannot accumulate multi-gigabyte decompressed copies.
        for old_key, old_path in list(_NIFTI_CACHE.items()):
            if old_key != digest:
                try:
                    old_path.unlink(missing_ok=True)
                except OSError:
                    pass
                _NIFTI_CACHE.pop(old_key, None)
        base = (os.environ.get("CLEANCT_TEST_TMP_DIR")
                or os.environ.get("TEMP") or tempfile.gettempdir())
        # A per-process location prevents parallel cleanCT launches from
        # overwriting or deleting one another's memory-mapped source file.
        cache_root = Path(base) / "cleanct-volume-cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        _cleanup_stale_nifti_cache_dirs(cache_root)
        cache_dir = cache_root / str(os.getpid())
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"{digest}.nii"
        tmp = cache_dir / f".{digest}.{os.getpid()}.tmp"
        try:
            # Reserve a small margin for the OS and fail before writing if
            # the decompressed source cannot fit on the selected temp drive.
            reserve = max(16 * 1024 * 1024, expected_bytes // 100)
            free_bytes = shutil.disk_usage(cache_dir).free
            if free_bytes < expected_bytes + reserve:
                raise VolumeInputError(
                    f"compressed NIfTI needs about {expected_bytes / 2**30:.1f} GiB "
                    f"of temporary space; only {free_bytes / 2**30:.1f} GiB is free")
            written = 0
            with gzip.open(path, "rb") as src, open(tmp, "wb") as dst:
                while written < expected_bytes:
                    chunk = src.read(min(4 * 1024 * 1024,
                                         expected_bytes - written))
                    if not chunk:
                        break
                    dst.write(chunk)
                    written += len(chunk)
                # Probe one byte beyond the declared NIfTI payload to reject
                # malformed files and decompression bombs before exhausting disk.
                if src.read(1):
                    raise VolumeInputError(
                        "compressed NIfTI expands beyond its declared dimensions")
            if written < expected_bytes:
                raise VolumeInputError("compressed NIfTI data is truncated")
            os.replace(tmp, target)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            if isinstance(exc, VolumeInputError):
                raise
            raise VolumeInputError(f"could not decompress NIfTI input: {exc}") from exc
        _NIFTI_CACHE[digest] = target
        return target


def _cleanup_nifti_cache() -> None:
    with _NIFTI_CACHE_LOCK:
        cache_dirs = {path.parent for path in _NIFTI_CACHE.values()}
        for path in _NIFTI_CACHE.values():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        _NIFTI_CACHE.clear()
        for cache_dir in cache_dirs:
            try:
                cache_dir.rmdir()
            except OSError:
                pass


atexit.register(_cleanup_nifti_cache)


def load_volume(path: str | Path, gpu, *, metadata: dict | None = None,
                memory_check=None, timings: dict | None = None) -> tuple[np.ndarray, dict]:
    """Load TIFF/NIfTI by slices into the existing CPU/GPU backend."""
    import time
    started = time.perf_counter()
    info = metadata or inspect_source(path)
    source_path = Path(info["source_path"])
    kind = info["source_kind"]
    n, rows, cols = map(int, info["shape_zyx"])
    if n < 2 or rows < 1 or cols < 1:
        raise VolumeInputError("volume dimensions must all be positive")
    if memory_check:
        memory_check(n, rows, cols, 1)
    if kind == "nifti":
        import nibabel as nib
        nifti_path = source_path
        if source_path.name.lower().endswith(".gz"):
            try:
                nifti_path = _decode_nifti_gz(
                    source_path, _nifti_expected_bytes_from_info(info))
            except OSError as exc:
                raise VolumeInputError(f"could not prepare compressed NIfTI: {exc}") from exc
        try:
            img = nib.load(str(nifti_path), mmap=True)
            transform = np.asarray(info["nifti_transform"], dtype=float)
        except Exception as exc:
            raise VolumeInputError(f"could not open NIfTI volume: {exc}") from exc
        read_plane = lambda z: _read_nifti_plane(img, transform, z)
        tiff_handle = None
    elif kind == "tiff":
        tiff_handle = None
        if source_path.is_file():
            try:
                import tifffile
                tiff_handle = tifffile.TiffFile(source_path)
                series = tiff_handle.series[0]
                read_plane = lambda z: series.pages[z].asarray()
            except Exception as exc:
                if tiff_handle is not None:
                    tiff_handle.close()
                raise VolumeInputError(f"could not open TIFF stack: {exc}") from exc
        else:
            read_plane = lambda z: _tiff_read_planes(info, [z])[z]
    else:
        raise VolumeInputError(f"unsupported volume type: {kind}")
    try:
        volume = gpu.empty_like((n, rows, cols), dtype=np.float32)
    except Exception as exc:
        if tiff_handle is not None:
            tiff_handle.close()
        gpu.release()
        raise MemoryError(f"could not allocate {n} × {rows} × {cols} volume: {exc}") from exc
    try:
        for z in range(n):
            plane = np.asarray(read_plane(z), dtype=np.float32)
            if plane.shape != (rows, cols):
                raise VolumeInputError(f"slice {z} shape {plane.shape} does not match {(rows, cols)}")
            if not np.isfinite(plane).all():
                raise VolumeInputError(f"slice {z} contains non-finite values")
            gpu.put_rescaled_slice(volume, z, plane, 1.0, 0.0)
    except Exception:
        del volume
        try:
            gpu.release()
        except Exception:
            pass
        raise
    finally:
        if tiff_handle is not None:
            tiff_handle.close()
    if timings is not None:
        timings["load_pixels_s"] = round(time.perf_counter() - started, 2)
    out = dict(info)
    out.update(n_slices=n, rows=rows, cols=cols,
               rescale_slope=1.0, rescale_intercept=0.0,
               pixel_spacing_yx_mm=tuple(info["pixel_spacing_yx_mm"]),
               slice_thickness_mm=float(info["slice_thickness_mm"]),
               voxel_mm3=float(info["voxel_mm3"]))
    return volume, out


def adaptive_thresholds(meta: dict, cfg) -> dict:
    """Map HU-tuned segmentation thresholds to an uncalibrated grayscale.

    Calibrated input leaves the historical HU values untouched. For raw
    intensity sources, robust sampled percentiles establish a reproducible
    range; output voxel values remain in source units and the report records
    that these thresholds are estimates.
    """
    if meta.get("intensity_mode") != "raw":
        return {}
    stats = meta.get("intensity_sample_percentiles") or {}
    try:
        p02, p05, p10 = (float(stats[k]) for k in ("p02", "p05", "p10"))
        p90, p95, p98 = (float(stats[k]) for k in ("p90", "p95", "p98"))
        p995 = float(stats["p995"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VolumeInputError("raw grayscale calibration statistics are incomplete") from exc
    spread = max(0.0, p98 - p02)
    if not np.isfinite(spread) or spread <= 0:
        raise VolumeInputError("raw grayscale has no usable intensity contrast")
    gain = spread / 2000.0
    # Exclude the darkest background and brightest metal tail from the wood
    # tracker. The metal threshold uses a high-tail percentile so small bright
    # structures do not dominate the anchor count.
    return {
        "metal_hu": p95,
        "wood_hu_min": p05,
        "wood_hu_max": p98,
        "curtain_air_hu": p05,
        "air_crop_hu": p05,
        "halo_delta_hu": max(gain * float(cfg.halo_delta_hu), spread * 1e-5),
        "min_onset_slope_hu": max(gain * float(cfg.min_onset_slope_hu), spread * 1e-6),
        "min_onset_rise_hu": max(gain * float(cfg.min_onset_rise_hu), spread * 1e-5),
        "intensity_auto_calibrated": True,
        "intensity_range_estimate": [p02, p995],
    }
