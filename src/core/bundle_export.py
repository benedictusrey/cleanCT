#!/usr/bin/env python
"""Extraction bundle exporter for the Metal-Platform Remover app.

A "bundle" is the portable delivery folder for one specimen:

    <save_root>/<specimen>/
        <specimen>_dcm/               kept (pre-cut) slices as a DICOM
                                      series — every slice keeps its
                                      ORIGINAL filename, enriched with
                                      full delivery metadata (PatientName,
                                      PatientID, Modality, study/series
                                      descriptions, software, provenance)
        <specimen>.nii                full-FOV kept slices as a volume
        <specimen>.json               complete DICOM properties of the
                                      extracted series (incl. specimen id,
                                      capture time, per-file mapping and
                                      the tag block written to the DICOMs)
        <specimen>_extraction_info.txt  human-readable summary: which original
                                      folder the slices were extracted from,
                                      cut index, and the file mapping table

No ``_rem_`` markers are injected anywhere: delivered files carry clean,
source-faithful names (audit 0AC).

Bundle writes are atomic (tmp dir + rename) and self-verified (file count,
pixel-data spot checks against the source series, and metadata readback).

Export formats: the caller chooses ``dicom`` (kept-slice DICOM series
only), ``nifti`` (kept-slices volume only) or ``both`` (default — the
historical behavior).  Sidecar JSON / extraction-info / verification
adapt to whichever artifacts were requested.

Export writes are UNCONDITIONAL but never destructive: a finished
bundle from a previous run is rebuilt artifact-by-artifact into a tmp
location and swapped in only when complete — a killed export leaves
the previous bundle intact plus at most one ``.tmp`` leftover, which
the next export run cleans up automatically.  Bundles written by older
releases (``<specimen>_rem_dcm``/``_rem.nii``/``_rem.json``) are swept,
recovered and adopted under the clean names.

Write-backpressure control: every finished artifact file is fsynced as
soon as it is written (bounded cost per file), so the OS dirty-page
cache on slow destinations (e.g. USB external drives) never accumulates
tens of GB of pending writes — which otherwise stalls the whole process
(GUI included) for many minutes after the "write" finishes.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from core.paths import ensure_engine_on_path, state_root
except ImportError:  # direct import (no package context)
    from paths import ensure_engine_on_path, state_root

_PIPELINE = ensure_engine_on_path()
if _PIPELINE.is_dir() and str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

_STATE = state_root()

from roi_delivery import (_nifti_prefix_bytes, nifti_affine,  # noqa: E402
                          nifti_metadata_payload,
                          read_dicom, sorted_source_files)

PIPELINE_VERSION = "universal-halo v1.0 (app bundle exporter)"
CLEANCT_VERSION = "1.0.0"
CLEANCT_SOFTWARE = f"cleanCT {CLEANCT_VERSION}"

# Delivered artifact names (audit 0AC: no ``_rem_`` markers anywhere).
def series_dir_name(specimen: str) -> str:
    return f"{specimen}_dcm"


def nifti_name(specimen: str) -> str:
    return f"{specimen}.nii"


def sidecar_name(specimen: str) -> str:
    return f"{specimen}.json"


def info_name(specimen: str) -> str:
    return f"{specimen}_extraction_info.txt"


# Names written by older releases (swept and adopted on update).
_LEGACY_SERIES_DIR = "{s}_rem_dcm"
_LEGACY_NIFTI = "{s}_rem.nii"
_LEGACY_SIDECAR = "{s}_rem.json"

# Export formats (user-selectable in the app)
FORMAT_DICOM = "dicom"
FORMAT_NIFTI = "nifti"
FORMAT_BOTH = "both"
EXPORT_FORMATS = (FORMAT_DICOM, FORMAT_NIFTI, FORMAT_BOTH)


def _clean_tmp(dest: Path, specimen: str) -> None:
    """Remove leftovers from previously killed exports (atomic-rename
    temporaries) for BOTH the clean naming and the legacy ``_rem``
    naming, then adopt legacy recovery artifacts under the clean names.
    Only temporary / ``.old`` paths are touched, never finished
    artifacts."""
    if not dest.is_dir():
        return
    final_dcm = dest / series_dir_name(specimen)
    old_dcm = dest / (series_dir_name(specimen) + ".old")
    legacy_final = dest / _LEGACY_SERIES_DIR.format(s=specimen)
    legacy_old = dest / (_LEGACY_SERIES_DIR.format(s=specimen) + ".old")
    # Recover the last complete DICOM export if a process was interrupted
    # between moving the old series aside and promoting the new one.
    for o, f in ((old_dcm, final_dcm), (legacy_old, legacy_final)):
        try:
            if o.exists():
                if not f.exists():
                    o.rename(f)
                else:
                    shutil.rmtree(o, ignore_errors=True)
        except OSError:
            pass
    # Adopt a legacy-named finished series under the clean name so the
    # bundle carries one consistent layout from here on.
    try:
        if legacy_final.exists() and not final_dcm.exists():
            legacy_final.rename(final_dcm)
    except OSError:
        pass
    for pat in (f".{specimen}*.tmp", f"{specimen}*.tmp.nii"):
        for p in dest.glob(pat):
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
    for name in (series_dir_name(specimen) + ".tmp",
                 nifti_name(specimen) + ".tmp",
                 sidecar_name(specimen) + ".tmp",
                 _LEGACY_SERIES_DIR.format(s=specimen) + ".tmp",
                 _LEGACY_NIFTI.format(s=specimen) + ".tmp",
                 f".{specimen}.tmp.nii",
                 _LEGACY_SIDECAR.format(s=specimen) + ".tmp"):
        t = dest / name
        try:
            if t.is_dir():
                shutil.rmtree(t, ignore_errors=True)
            elif t.exists():
                t.unlink()
        except Exception:
            pass


def _promote_directory(tmp: Path, final: Path, old: Path) -> None:
    """Replace a finished directory, restoring the previous one on failure."""
    moved_old = False
    if old.exists():
        if not final.exists():
            old.rename(final)
        else:
            shutil.rmtree(old, ignore_errors=True)
    if final.exists():
        final.rename(old)
        moved_old = True
    try:
        tmp.rename(final)
    except Exception:
        if moved_old and old.exists() and not final.exists():
            old.rename(final)
        raise
    if moved_old:
        shutil.rmtree(old, ignore_errors=True)


def _safe_bundle_component(value: str) -> bool:
    """Keep specimen-derived bundle paths inside their selected save root."""
    return bool(value and value not in {".", ".."}
                and not any(ord(ch) < 32 or ch in '<>:"/\\|?*' for ch in value))


def _recover_bundle_paths(save_root: Path, specimen: str
                          ) -> tuple[Path, Path, Path]:
    """Recover an interrupted whole-bundle promotion and discard stale staging."""
    final = save_root / specimen
    staging = save_root / f".{specimen}.bundle.tmp"
    old = save_root / f".{specimen}.bundle.old"
    if old.exists():
        if not final.exists():
            try:
                old.rename(final)
            except OSError as exc:
                raise BundleError(
                    f"could not restore the previous bundle for {specimen}: {exc}") from exc
        else:
            shutil.rmtree(old, ignore_errors=True)
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    return final, staging, old


def _seed_preserved_bundle_entries(final: Path, staging: Path,
                                   specimen: str, export_format: str) -> None:
    """Carry forward unrequested formats and user files without copying bytes.

    The staging directory is a sibling of the old bundle, so regular files
    can usually be hard-linked. A copy fallback handles filesystems without
    hard-link support. Symlinks and junctions are rejected instead of being
    followed or silently dropped.
    """
    if not final.is_dir():
        return
    # The sidecar and info are always rebuilt; format artifacts are
    # replaced only when their format is requested.  Legacy-named
    # artifacts of this same exporter are superseded by the clean-named
    # rebuilds of the same format (no stale ``_rem`` duplicates).
    replace_names = {
        info_name(specimen),
        sidecar_name(specimen),
        _LEGACY_SIDECAR.format(s=specimen),
    }
    if export_format in (FORMAT_DICOM, FORMAT_BOTH):
        replace_names.add(series_dir_name(specimen))
        replace_names.add(_LEGACY_SERIES_DIR.format(s=specimen))
    if export_format in (FORMAT_NIFTI, FORMAT_BOTH):
        replace_names.add(nifti_name(specimen))
        replace_names.add(_LEGACY_NIFTI.format(s=specimen))

    def copy_entry(source: Path, target: Path) -> None:
        if source.is_symlink() or getattr(source, "is_junction", lambda: False)():
            raise BundleError(
                f"cannot safely rebuild bundle containing a link: {source.name}")
        if source.is_dir():
            target.mkdir()
            for child in source.iterdir():
                copy_entry(child, target / child.name)
        elif source.is_file():
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)

    for child in final.iterdir():
        if child.name in replace_names:
            continue
        copy_entry(child, staging / child.name)


def _fsync_file(p: Path) -> None:
    """Flush one finished artifact to the physical device.

    Bounded per-file cost; prevents the OS dirty-page cache from
    accumulating tens of GB on slow destinations (USB drives) — the
    accumulated flush otherwise stalls the whole process (GUI thread
    included) for many minutes after the visible 'write' completes."""
    try:
        fd = os.open(str(p), os.O_RDWR)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


class BundleError(RuntimeError):
    pass


def default_save_root() -> Path:
    return _STATE / "export"


def load_settings(app_root: Path | None = None) -> dict:
    p = (app_root or _STATE) / "settings.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_settings(app_root: Path | None = None, settings: dict | None = None) -> None:
    if settings is None:
        raise TypeError("save_settings(settings=...) requires a dict")
    p = (app_root or _STATE) / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# writers
# --------------------------------------------------------------------------
def _delivery_tags(specimen: str, report: dict, provenance: str,
                   n_kept: int, cut_from: int, source_files: list) -> dict:
    """Full delivery metadata written onto every exported DICOM slice.

    Source tags stay byte-identical except the identity/provenance tags
    enriched here (audit 0AC).  Values already present in the source are
    preserved; missing essentials are filled from the processing report
    or the export itself (recorded in the sidecar's ``dicom_tags``).
    """
    import pydicom

    def _tag(ds, name):
        return getattr(ds, name, None)

    ds0 = read_dicom(source_files[0], stop_before_pixels=True)
    meta = report.get("meta") or {}
    plat = report.get("platform") or {}
    metrics = report.get("metrics") or {}
    spacing = meta.get("pixel_spacing_yx_mm") or [None, None]
    thickness = meta.get("slice_thickness_mm")

    # Acquisition date/time: preserved from the source; a source without
    # them receives the export timestamp (recorded as such).
    has_acq = bool(str(getattr(ds0, "AcquisitionTime", "") or "").strip()) \
        and bool(str(getattr(ds0, "AcquisitionDate", "") or "").strip())
    acq_time = None
    if not has_acq:
        now = datetime.now()
        acq_time = {"AcquisitionDate": now.strftime("%Y%m%d"),
                    "AcquisitionTime": now.strftime("%H%M%S")}

    keep_from = int(plat.get("keep_from") or 0)
    history = (
        f"cleanCT {CLEANCT_VERSION} non-destructive metal-base removal: "
        f"kept slices {keep_from}..{keep_from + n_kept - 1} of "
        f"{len(source_files) + keep_from}; cut at slice {cut_from} "
        f"(platform anchor {plat.get('anchor_slice')}, "
        f"accepted by {plat.get('accepted_by')}); "
        f"removed {float(metrics.get('removed_fraction') or 0.0):.2%} "
        f"of the volume; engine {PIPELINE_VERSION}; "
        f"compute {report.get('gpu', {}).get('name', 'CPU')}; "
        f"source {provenance}")

    return {
        # identity (always written, exactly as requested)
        "PatientName": specimen,
        "PatientID": (str(getattr(ds0, "PatientID", "") or "").strip()
                      or specimen),
        "Modality": (str(getattr(ds0, "Modality", "") or "").strip()
                     or "CT"),
        # descriptions / software / provenance
        "StudyDescription": "cleanCT non-destructive metal-base removal",
        "SeriesDescription": (f"cleanCT metal-removed series ({specimen}; "
                              f"kept {n_kept} slices)"),
        "SoftwareVersions": CLEANCT_SOFTWARE,
        "InstitutionName": (str(getattr(ds0, "InstitutionName", "") or "").strip()
                            or "cleanCT workstation"),
        "ImageComments": history[:1020],
        "AdditionalPatientHistory": (
            f"Micro-CT wood specimen {specimen}. Metal mounting platform "
            f"removed non-destructively with {CLEANCT_SOFTWARE}; "
            f"source series {provenance}."),
        # geometry: preserved from the source, filled from the report
        # when the source lacks it
        "SliceThickness": (getattr(ds0, "SliceThickness", None)
                           or (float(meta.get("slice_thickness_mm"))
                               if meta.get("slice_thickness_mm") else None)),
        "PixelSpacing": (list(getattr(ds0, "PixelSpacing", []) or [])
                         or ([float(spacing[0]), float(spacing[1])]
                             if spacing and spacing[0] else None)),
        **(acq_time or {}),
    }


def _write_kept_dicoms(source_files_or_dir, dest: Path, specimen: str,
                       cut_from: int, report: dict,
                       progress=None, wanted: bool = True) -> dict:
    """Copy kept slices as one DICOM series with clean, source-faithful
    names and full delivery metadata.

    Every kept slice is written under its ORIGINAL source filename
    (``OriginalName.dcm`` — no ``_rem_`` markers are injected).  Source
    tags are preserved and enriched with the delivery metadata from
    :func:`_delivery_tags`.

    ``wanted=False`` skips the DICOM series entirely (NIfTI-only export):
    the returned mapping is empty and the sidecar omits the series.

    Writes go to ``<specimen>_dcm.tmp`` and are swapped in only when
    complete (update-in-place: a previously exported series survives a
    killed re-export untouched).  Every finished file is fsynced so slow
    destinations never accumulate tens of GB of OS write cache (which
    otherwise stalls the whole process after the visible write phase)."""
    import pydicom
    import warnings
    from concurrent.futures import ThreadPoolExecutor

    keep_from = int(report.get("platform", {}).get("keep_from") or 0)
    if isinstance(source_files_or_dir, (list, tuple)):
        kept = list(source_files_or_dir)[:cut_from]
    else:
        files = sorted_source_files(source_files_or_dir)
        kept = files[keep_from:keep_from + cut_from]
    if not kept:
        raise BundleError("no kept slices to export")
    final = dest / series_dir_name(specimen)
    if not wanted:
        return {"n_files": 0, "series_dir": None, "mapping": [],
                "skipped": True}
    _clean_tmp(dest, specimen)
    tmp = dest / (series_dir_name(specimen) + ".tmp")
    tmp.mkdir(parents=True)
    tags = _delivery_tags(specimen, report,
                          str(Path(kept[0]).parent), len(kept), cut_from, kept)
    mapping = []

    def _write_one(item):
        i, src = item
        ds = pydicom.dcmread(src)
        # identity + provenance tags are written on top of the preserved
        # source tags (pixels and geometry stay byte-identical)
        for key, value in tags.items():
            if value is not None:
                setattr(ds, key, value)
        # clean filename: the ORIGINAL slice filename (no ``_rem_``);
        # a pathological duplicate falls back to an indexed clean name
        name = Path(src).name
        if (not name or name.lower().endswith((".tmp", ".old"))
                or (tmp / name).exists()):
            name = f"{specimen}_{i:04d}.dcm"
        outp = tmp / name
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore",
                                    message="Invalid value for VR UI:.*")
            pydicom.dcmwrite(outp, ds, enforce_file_format=True)
        _fsync_file(outp)
        return {"export_file": name, "source_file": src.name,
                "source_index": keep_from + i - 1}

    try:
        # I/O-bound pydicom threads: beyond ~10 workers the GIL and the
        # disk queue stop helping and only add memory pressure.
        with ThreadPoolExecutor(max_workers=10) as ex:
            for count, m in enumerate(ex.map(_write_one, enumerate(kept, start=1)), start=1):
                mapping.append(m)
                if progress and (count % 8 == 0 or count == len(kept)):
                    progress(count, len(kept))

        old = dest / (series_dir_name(specimen) + ".old")
        _promote_directory(tmp, final, old)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {"n_files": len(kept), "series_dir": str(final),
            "mapping": mapping, "tags": tags}


# Ultra-high-res NIfTI assembly bound: volumes whose kept-slice span
# exceeds this many bytes are written block-wise (never fully resident).
# At 24 um the kept volume is typically ~1.5-3 GB (RAM path); a 1 um-class
# volume would be >6 GB and must stream.
STREAM_VOL_MAX_BYTES = 4_000_000_000
STREAM_BLOCK_SLICES = 8        # source slices held in RAM per streamed block


def _write_kept_nifti_streamed(proxy, keep_from: int, cut_from: int,
                              dest: Path, specimen: str, dataset_key: str,
                              source_files: list, meta_report: dict,
                              progress=None) -> dict:
    """Block-wise kept-slices NIfTI — sequential fd writes (audit 0M).

    Each z-plane of the source (disk-ordered x, y, z) is written as one
    contiguous chunk straight through a file handle: in the canonical
    NIfTI (z, y, x) image the z axis is the FASTEST file axis, so the
    file bytes are exactly the source planes back-to-back — no transpose,
    no memmap.  (The previous memmap writer assigned strided views whose
    innermost axis carried a 5.6 MB stride: ~11M scattered 4-byte writes
    per block; measured 218-277 MB/s vs 1860 MB/s for sequential fd
    writes on the real 2-21 volume — an 8.5x total-export speedup.)

    Peak extra RAM is one plane + one block regardless of volume size.
    Produces a byte-identical file to nibabel's own RAM save (same
    header, affine, dtype and layout — proven by build/test_export_stream).

    The output is staged as ``.nii.tmp`` and atomically renamed on
    completion — a killed export never leaves a half-written ``.nii``
    that could be mistaken for a finished one; leftover ``.tmp`` files
    are cleaned automatically by the next export run.  A periodic fsync
    bounds the destination's dirty-page cache so slow targets (USB
    drives) never stall the process.
    """
    import nibabel as nib
    # disk order is (x, y, z): canonical (z, y, x) output therefore maps
    # ny -> shape[1], nx -> shape[0], nz -> shape[2]
    nx_, ny_, nz_ = (int(proxy.shape[0]), int(proxy.shape[1]),
                     int(proxy.shape[2]))
    n_keep = int(cut_from)
    if n_keep <= 0 or keep_from < 0 or keep_from + n_keep > nz_:
        raise BundleError(
            f"kept slice range [{keep_from}, {keep_from + n_keep}) "
            f"is outside NIfTI depth {nz_}")
    if not source_files:
        raise BundleError("cannot export NIfTI without source DICOM slices")
    first = read_dicom(source_files[0], stop_before_pixels=True)
    if (ny_, nx_) != (int(first.Rows), int(first.Columns)):
        raise BundleError(
            f"stripped NIfTI XY shape {(ny_, nx_)} does not match source "
            f"DICOM {(int(first.Rows), int(first.Columns))}")
    affine = nifti_affine(source_files[:cut_from], (0, cut_from - 1, 0, 0, 0, 0))
    out = dest / nifti_name(specimen)
    tmp = out.with_suffix(".nii.tmp")
    tmp.unlink(missing_ok=True)          # orphan from a previously killed run
    img = nib.Nifti1Image(np.zeros((1, 1, 1), np.float32), affine)
    hdr = img.header
    hdr.set_xyzt_units("mm")
    hdr.set_data_shape((n_keep, ny_, nx_))
    hdr.set_data_dtype(np.float32)
    # deterministic single-file layout: 348-byte header + 4 zero extension
    # bytes, data at vox_offset=352 (the layout nibabel itself writes)
    hdr["vox_offset"] = 352
    hdr["magic"] = b"n+1"
    # nibabel's save path writes slope=1/inter=0 for unscaled float data;
    # set them explicitly so the streamed file is byte-identical to it
    hdr["scl_slope"] = 1.0
    hdr["scl_inter"] = 0.0
    block = max(1, STREAM_BLOCK_SLICES)
    blk_i = 0
    try:
        with open(tmp, "wb") as f:
            f.write(hdr.structarr.tobytes())     # exactly 348 bytes
            f.write(b"\x00\x00\x00\x00")
            # purely sequential plane writes: file position is already at the
            # data offset, and z ascends — no seeks, no memmap, no striding
            for z0 in range(0, n_keep, block):
                z1 = min(n_keep, z0 + block)
                # src z ranges over the full stripped volume; the kept window
                # is [keep_from, keep_from + cut_from) in disk (x, y, z) order
                blk = np.asarray(proxy[:, :, keep_from + z0:keep_from + z1],
                                 dtype=np.float32)
                for j in range(z1 - z0):
                    f.write(np.ascontiguousarray(blk[:, :, j]).tobytes())
                # Bound the destination's dirty-page cache: without a periodic
                # physical flush a USB-class destination accumulates the whole
                # multi-GB volume as pending writes and Windows throttles the
                # entire process while it drains.
                blk_i += 1
                if blk_i % 16 == 0:
                    f.flush()
                    os.fsync(f.fileno())
                if progress:
                    progress(z1, n_keep)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_file(out)                     # physical write now: no end-of-export stall
    describ = (f"{CLEANCT_SOFTWARE} metal-removed; specimen={specimen}; "
               f"dataset={dataset_key}; "
               f"voxel_um={float(meta_report['meta']['pixel_spacing_yx_mm'][0]) * 1000:.3f}; "
               f"slices={keep_from}..{keep_from + cut_from - 1}")[:79]
    return {"nii": str(out), "shape": [n_keep, ny_, nx_], "descrip": describ}


def _write_kept_nifti_from_dicoms(source_files: list, cut_from: int,
                                 dest: Path, specimen: str,
                                 dataset_key: str, meta_report: dict,
                                 progress=None) -> dict:
    """Build a kept-slice NIfTI with a disk-backed volume for legacy outputs.

    Older processed samples may not have ``stripped.nii``. Decode their DICOM
    slices into the staged NIfTI through a Fortran-order memory map, so this
    fallback does not retain a full scan and a second stacked copy in RAM.
    Decode concurrency is bounded by slice size.
    """
    import nibabel as nib
    from concurrent.futures import ThreadPoolExecutor

    if cut_from <= 0 or cut_from > len(source_files):
        raise BundleError(f"invalid kept DICOM slice count: {cut_from}")
    first = read_dicom(source_files[0], stop_before_pixels=True)
    rows, cols = int(first.Rows), int(first.Columns)
    if rows <= 0 or cols <= 0:
        raise BundleError("source DICOM has invalid Rows/Columns")
    affine = nifti_affine(source_files[:cut_from],
                          (0, cut_from - 1, 0, 0, 0, 0))
    img = nib.Nifti1Image(np.zeros((1, 1, 1), np.float32), affine)
    hdr = img.header
    hdr.set_xyzt_units("mm")
    hdr.set_data_shape((cut_from, rows, cols))
    hdr.set_data_dtype(np.float32)
    hdr["scl_slope"] = 1.0
    hdr["scl_inter"] = 0.0
    prefix = _nifti_prefix_bytes(img)

    out = dest / nifti_name(specimen)
    tmp = out.with_suffix(".nii.tmp")
    tmp.unlink(missing_ok=True)
    plane_bytes = rows * cols * np.dtype(np.float32).itemsize
    decode_budget = 256 * 1024 * 1024
    workers = max(1, min(8, os.cpu_count() or 1,
                         decode_budget // max(1, plane_bytes * 2)))
    mapped = None

    def _read_plane(path: Path) -> np.ndarray:
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore",
                                        message="Invalid value for VR UI:.*")
                ds = read_dicom(path)
            raw = np.asarray(ds.pixel_array)
            if raw.shape != (rows, cols) or raw.dtype.kind not in "iu":
                raise ValueError("unexpected decoded pixel shape or type")
            plane = raw.astype(np.float32)
            plane *= np.float32(getattr(ds, "RescaleSlope", 1.0))
            plane += np.float32(getattr(ds, "RescaleIntercept", 0.0))
            return plane
        except Exception as exc:
            raise BundleError(
                f"{path.name}: could not decode source DICOM "
                f"({type(exc).__name__})") from exc

    try:
        with open(tmp, "wb") as stream:
            stream.write(prefix)
            stream.truncate(len(prefix) + cut_from * plane_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        mapped = np.memmap(
            tmp, dtype=np.float32, mode="r+", offset=len(prefix),
            shape=(cut_from, rows, cols), order="F")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for start in range(0, cut_from, workers):
                batch = source_files[start:min(cut_from, start + workers)]
                for offset, plane in enumerate(executor.map(_read_plane, batch)):
                    mapped[start + offset] = plane
                if progress:
                    done = min(cut_from, start + len(batch))
                    progress(min(cut_from - 1,
                                 int(done * (cut_from - 1) / cut_from)),
                             cut_from)
        mapped.flush()
        mapped._mmap.close()
        mapped = None
        _fsync_file(tmp)
        os.replace(tmp, out)
        _fsync_file(out)
        if progress:
            progress(cut_from, cut_from)
    except Exception:
        if mapped is not None:
            try:
                mapped.flush()
            except Exception:
                pass
            try:
                mapped._mmap.close()
            except Exception:
                pass
        tmp.unlink(missing_ok=True)
        raise

    keep_from = int(meta_report.get("platform", {}).get("keep_from") or 0)
    describ = (f"{CLEANCT_SOFTWARE} metal-removed; specimen={specimen}; "
               f"dataset={dataset_key}; "
               f"voxel_um={float(meta_report['meta']['pixel_spacing_yx_mm'][0]) * 1000:.3f}; "
               f"slices={keep_from}..{keep_from + cut_from - 1}")[:79]
    return {"nii": str(out), "shape": [cut_from, rows, cols],
            "descrip": describ}


def _write_kept_nifti(stripped_nii: Path, dest: Path, specimen: str,
                     dataset_key: str, cut_from: int, source_files: list,
                     meta_report: dict, progress=None,
                     wanted: bool = True) -> dict:
    """Full-FOV kept-slices volume with descriptive header + sidecar JSON.

    Prefers the pipeline's stripped.nii; falls back to rebuilding the kept
    slices from the source DICOMs (identical content for z < cut_from) so
    bundles can be exported for samples processed before stripped.nii was
    saved.

    Streaming is UNIVERSAL (audit round 0M): every NIfTI goes through the
    block-wise streamed writer — peak extra RAM is a few slices regardless
    of resolution (the in-RAM path doubled the footprint of multi-GB
    volumes), and the output is byte-identical to the historical in-RAM
    path (proven by build/test_export_stream.py).

    ``wanted=False`` (DICOM-only export) writes nothing and reports the
    skip so sidecars/info adapt."""
    import nibabel as nib
    if not wanted:
        return {"skipped": True, "nii": None, "shape": [], "descrip": ""}
    keep_from = int(meta_report.get("platform", {}).get("keep_from") or 0)
    if stripped_nii.exists():
        proxy = nib.load(stripped_nii).dataobj
        # disk order (x, y, z) -> canonical (z, y, x) for the saved volume.
        # Always streamed (0M): identical bytes to the historical in-RAM
        # path, a few slices of RAM instead of the full volume.
        return _write_kept_nifti_streamed(
            proxy, keep_from, cut_from, dest, specimen, dataset_key,
            source_files, meta_report, progress=progress)
    # Older outputs without stripped.nii use a bounded, disk-backed path.
    return _write_kept_nifti_from_dicoms(
        source_files, cut_from, dest, specimen, dataset_key,
        meta_report, progress=progress)


def _write_sidecar(dest: Path, specimen: str, dataset_key: str,
                   source_files: list, cut_from: int, report: dict,
                   mapping: list, nii_info: dict,
                   provenance: str,
                   n_slices_original: int | None = None,
                   tags: dict | None = None,
                   collection_from: int | None = None) -> dict:
    # one header read serves both capture date and time (audit 0M: the
    # previous code re-read and re-decoded the full header twice)
    _ds0 = read_dicom(source_files[0], stop_before_pixels=True)
    meta = nifti_metadata_payload(source_files[:cut_from],
                                  (0, cut_from - 1, 0, 0, 0, 0),
                                  dataset_key, specimen)
    orig_total = n_slices_original if n_slices_original is not None else len(source_files)
    payload = {
        "specimen_id": specimen,
        "dataset": dataset_key,
        "software": CLEANCT_SOFTWARE,
        "pipeline": PIPELINE_VERSION,
        "cut_from": cut_from,
        "keep_from": int(collection_from or 0),
        "n_slices_kept": cut_from,
        "n_slices_original": orig_total,
        "source_folder": provenance,
        "source_series_dir": str(source_files[0].parent),
        "capture_date": str(getattr(_ds0, "AcquisitionDate", "")),
        "capture_time": str(getattr(_ds0, "AcquisitionTime", "")),
        "voxel_mm": float(report["meta"]["pixel_spacing_yx_mm"][0]) * 1000,
        "slice_thickness_mm": report["meta"].get("slice_thickness_mm"),
        "removed_fraction": report["metrics"]["removed_fraction"],
        "platform": report["platform"],
        "file_mapping": mapping,
        "nifti": (nii_info if nii_info.get("skipped") else {
            "nii": Path(nii_info["nii"]).name,
            "shape": nii_info["shape"],
            "descrip": nii_info["descrip"],
        }),
        "export_formats": report.get("export_formats", FORMAT_BOTH),
        "dicom_tags": dict(tags or {}),
        "complete_dicom_properties": meta,
        "generated": datetime.now().isoformat(timespec="seconds"),
    }
    out = dest / sidecar_name(specimen)
    tmp = dest / (sidecar_name(specimen) + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=1, default=str),
                       encoding="utf-8")
        os.replace(tmp, out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return {"json": str(out), "payload": payload, "out": out}


def _write_info_txt(dest: Path, specimen: str, dataset_key: str,
                    source_files: list, cut_from: int, report: dict,
                    sidecar: dict, provenance: str,
                    n_slices_original: int | None = None) -> dict:
    meta = report["meta"]
    r = report["platform"]
    orig_total = n_slices_original if n_slices_original is not None else len(source_files)
    lines = [
        f"Metal-platform removal — extraction info",
        f"=" * 46,
        f"software           : {CLEANCT_SOFTWARE}",
        f"specimen id        : {specimen}",
        f"dataset            : {dataset_key}",
        f"generated          : {datetime.now().isoformat(timespec='seconds')}",
        f"pipeline           : {PIPELINE_VERSION}",
        f"",
        f"SOURCE",
        f"  original folder  : {provenance}",
        f"  original slices  : {orig_total} "
        f"({source_files[0].name} .. {source_files[-1].name})",
        f"  capture          : {sidecar['payload']['capture_date']} "
        f"{sidecar['payload']['capture_time']}",
        f"  voxel size       : {float(meta['pixel_spacing_yx_mm'][0]) * 1000:.3f} um",
        f"",
        f"EXTRACTION",
        f"  cut from slice   : {cut_from}  (platform anchor "
        f"{r.get('anchor_slice')}, accepted by {r.get('accepted_by')})",
        f"  kept slices      : {cut_from}",
        f"  removed fraction : {report['metrics']['removed_fraction']:.2%}",
        f"  baseline HU      : {float(r.get('baseline_hu') or 0.0):.2f}",
        f"  gpu              : {report.get('gpu', {}).get('name', 'CPU')}",
        f"",
        f"OUTPUTS",
        *([f"  dicom series     : {series_dir_name(specimen)}/  "
           f"(kept slices under their ORIGINAL filenames, e.g. "
           f"{sidecar['payload']['file_mapping'][0]['export_file']})"]
          if sidecar["payload"]["file_mapping"] else
          [f"  dicom series     : (not requested — NIfTI-only export)"]),
        *([f"  nifti volume     : {nifti_name(specimen)}"]
          if sidecar["payload"]["nifti"] and
          not sidecar["payload"]["nifti"].get("skipped") else
          [f"  nifti volume     : (not requested — DICOM-only export)"]),
        f"  properties       : {sidecar_name(specimen)} "
        f"(complete DICOM properties + file mapping)",
        f"  dicom tags       : PatientName={specimen}, "
        f"PatientID={sidecar['payload']['dicom_tags'].get('PatientID')}, "
        f"Modality={sidecar['payload']['dicom_tags'].get('Modality')}, "
        f"Software={CLEANCT_SOFTWARE}",
        f"",
        f"FILE MAPPING (kept slice -> original file)",
    ]
    for m in sidecar["payload"]["file_mapping"][:12]:
        lines.append(f"  {m['export_file']:<28} <- {m['source_file']}")
    if cut_from > 12:
        lines.append(f"  … ({cut_from - 12} more, see {sidecar_name(specimen)})")
    out = dest / info_name(specimen)
    tmp = dest / (info_name(specimen) + ".tmp")
    try:
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return {"txt": str(out)}


def _export_volume_bundle_into(dataset_key: str, specimen: str,
                               source_path: Path, source_metadata: dict,
                               report: dict, stripped_nii: Path, dest: Path,
                               source_override: str | None = None,
                               keep_from: int | None = None,
                               export_format: str = FORMAT_NIFTI,
                               progress=None) -> dict:
    """Stream a geometry-preserving NIfTI bundle for TIFF/NIfTI inputs."""
    if export_format != FORMAT_NIFTI:
        raise BundleError(
            "this source has no DICOM acquisition metadata; choose NIfTI only")
    if not stripped_nii.is_file():
        raise BundleError("processed stripped.nii is missing; process the source again")
    import nibabel as nib
    report = json.loads(json.dumps(report, default=str))
    platform = report.setdefault("platform", {})
    cut_from = int(platform.get("cut_from") or 0)
    keep = int(platform.get("keep_from") or 0) if keep_from is None else int(keep_from)
    if cut_from <= keep:
        raise BundleError(f"keep_from {keep} must be below cut_from {cut_from}")
    try:
        img = nib.load(str(stripped_nii), mmap=True)
        proxy = img.dataobj
        if len(proxy.shape) != 3:
            raise BundleError(f"processed volume must be 3-D, got {proxy.shape}")
        nx, ny, nz = map(int, proxy.shape)
        if not (0 < cut_from <= nz):
            raise BundleError(f"cut_from {cut_from} is outside processed volume depth {nz}")
        affine = np.asarray(img.affine, dtype=np.float64)
        if affine.shape != (4, 4) or not np.isfinite(affine).all():
            raise BundleError("processed NIfTI has invalid spatial geometry")
        out_affine = affine.copy()
        out_affine[:3, 3] += affine[:3, 2] * keep
        n_keep = cut_from - keep
        shape_xyz = (nx, ny, n_keep)
        out_img = nib.Nifti1Image(np.zeros((1, 1, 1), np.float32), out_affine)
        out_img.set_qform(out_affine, code=1)
        out_img.set_sform(out_affine, code=1)
        out_img.header.set_data_shape(shape_xyz)
        out_img.header.set_data_dtype(np.float32)
        out_img.header.set_xyzt_units("mm", "unknown")
        out_img.header["scl_slope"] = 1.0
        out_img.header["scl_inter"] = 0.0
        out_img.header["descrip"] = (
            f"Metal-removed; specimen={specimen}; dataset={dataset_key}; "
            f"slices={keep}..{cut_from - 1}")[:79]
        out_path = dest / nifti_name(specimen)
        tmp_path = dest / (nifti_name(specimen) + ".tmp")
        prefix = _nifti_prefix_bytes(out_img)
        tmp_path.unlink(missing_ok=True)
        if progress:
            progress(0, n_keep, "nifti")
        with open(tmp_path, "wb") as stream:
            stream.write(prefix)
            for out_z, source_z in enumerate(range(keep, cut_from)):
                plane = np.asarray(proxy[:, :, source_z], dtype=np.float32).T
                if plane.shape != (ny, nx) or not np.isfinite(plane).any():
                    raise BundleError(f"processed NIfTI slice {source_z} is invalid")
                stream.write(np.ascontiguousarray(plane).tobytes())
                if (out_z + 1) % 256 == 0:
                    stream.flush()
                    os.fsync(stream.fileno())
                if progress:
                    progress(out_z + 1, n_keep, "nifti")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, out_path)
        _fsync_file(out_path)
        # Reopen the delivered file and verify its shape, affine, and a few
        # voxel planes against the staged source before promoting the bundle.
        delivered = nib.load(str(out_path), mmap=True)
        if tuple(delivered.shape) != shape_xyz or not np.allclose(
                delivered.affine, out_affine, rtol=0, atol=1e-5):
            raise BundleError("NIfTI bundle geometry verification failed")
        for offset in sorted({0, n_keep // 2, n_keep - 1}):
            actual = np.asarray(delivered.dataobj[:, :, offset], dtype=np.float32)
            expected = np.asarray(proxy[:, :, keep + offset], dtype=np.float32)
            if not np.array_equal(actual, expected, equal_nan=True):
                raise BundleError(f"NIfTI voxel verification failed at slice {offset}")
    except BundleError:
        try:
            (dest / (nifti_name(specimen) + ".tmp")).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except Exception as exc:
        try:
            (dest / (nifti_name(specimen) + ".tmp")).unlink(missing_ok=True)
        except OSError:
            pass
        raise BundleError(f"could not build NIfTI bundle: {exc}") from exc

    platform["keep_from"] = keep
    geometry = {
        "source_format": source_metadata.get("source_format"),
        "source_path": source_override or str(source_path),
        "source_signature": source_metadata.get("source_signature"),
        "source_kind": source_metadata.get("source_kind"),
        "geometry_assumed": source_metadata.get("geometry_assumed"),
        "spacing_zyx_mm": source_metadata.get("spacing_zyx_mm"),
        "affine_ras_xyz": affine.tolist(),
    }
    sidecar_payload = {
        "specimen_id": specimen, "dataset": dataset_key,
        "pipeline": PIPELINE_VERSION, "source": geometry,
        "cut_from": cut_from, "keep_from": keep,
        "n_slices_original": int((source_metadata.get("shape_zyx") or [nz])[0]),
        "n_slices_kept": n_keep, "shape_xyz": list(shape_xyz),
        "affine_ras_xyz": out_affine.tolist(),
        "intensity": {
            "mode": source_metadata.get("intensity_mode"),
            "unit": source_metadata.get("intensity_unit"),
            "threshold_strategy": report.get("meta", {}).get("threshold_strategy"),
            "thresholds": report.get("config"),
        },
        "export_formats": FORMAT_NIFTI,
        "generated": datetime.now().isoformat(timespec="seconds"),
    }
    json_path = dest / sidecar_name(specimen)
    json_tmp = dest / (sidecar_name(specimen) + ".tmp")
    json_tmp.write_text(json.dumps(sidecar_payload, indent=2, default=str),
                        encoding="utf-8")
    os.replace(json_tmp, json_path)
    lines = [
        "cleanCT extraction bundle", "=" * 28,
        f"Specimen: {specimen}",
        f"Source: {source_override or source_path}",
        f"Source format: {geometry['source_format']}",
        f"Source intensity: {geometry.get('source_kind')} / "
        f"{source_metadata.get('intensity_unit', 'stored values')}",
        f"Geometry assumed: {bool(geometry.get('geometry_assumed'))}",
        f"Slices kept: {keep}..{cut_from - 1} ({n_keep})",
        f"NIfTI: {out_path.name}",
        f"Metadata: {json_path.name}",
        "Source voxel values are preserved in the delivered volume.",
    ]
    txt_path = dest / f"{specimen}_extraction_info.txt"
    txt_tmp = dest / f".{specimen}_extraction_info.txt.tmp"
    txt_tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(txt_tmp, txt_path)
    if progress:
        progress(1, 1, "verify")
    return {"bundle_dir": str(dest), "export_format": FORMAT_NIFTI,
            "n_dicom": 0, "nifti": str(out_path),
            "json": str(json_path), "txt": str(txt_path),
            "cut_from": cut_from, "keep_from": keep,
            "source_folder": str(source_override or source_path)}


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def _export_bundle_into(dataset_key: str, specimen: str, source_dir: Path,
                        report: dict, stripped_nii: Path,
                        dest: Path,
                        source_override: str | None = None,
                        keep_from: int | None = None,
                        export_format: str = FORMAT_BOTH,
                        progress=None,
                        source_kind: str = "dicom",
                        source_path: Path | None = None,
                        source_metadata: dict | None = None) -> dict:
    """Build and verify a bundle inside an isolated staging directory.

    export_format: ``dicom`` (kept-slice series only), ``nifti`` (volume
    only) or ``both`` (default, historical behavior).  Sidecar,
    extraction-info and verification adapt to the requested artifacts.

    progress(i, n, phase) fires with real per-artifact progress: phase is
    "dicom" (i of n slices), "nifti" (i of n slices streamed), "sidecar"
    or "verify".

    source_override: provenance folder recorded in the outputs (used for
    user-loaded series whose folder is exposed to the pipeline via a
    junction; the bundle must cite the user's real folder).
    """
    if export_format not in EXPORT_FORMATS:
        raise BundleError(f"unknown export format: {export_format!r}")
    if source_kind != "dicom":
        return _export_volume_bundle_into(
            dataset_key, specimen,
            Path(source_path or source_dir),
            dict(source_metadata or report.get("meta") or {}),
            report, stripped_nii, dest,
            source_override=source_override, keep_from=keep_from,
            export_format=export_format, progress=progress)
    report.setdefault("export_formats", export_format)
    cut_from = int(report["platform"]["cut_from"])
    if keep_from is None:
        keep_from = int(report["platform"].get("keep_from") or 0)
    keep_from = int(keep_from)
    report.setdefault("platform", {})["keep_from"] = keep_from
    source_files = sorted_source_files(source_dir)
    n_orig_slices = len(source_files)
    if cut_from > len(source_files):
        raise BundleError(
            f"cut_from {cut_from} exceeds source series ({len(source_files)})")
    provenance = str(source_override) if source_override \
        else str(source_files[0].parent)

    dest.mkdir(parents=True, exist_ok=True)
    _clean_tmp(dest, specimen)              # orphan .tmp hygiene (0M)

    if keep_from >= cut_from:
        raise BundleError(
            f"keep_from {keep_from} must be below the cut slice {cut_from}")
    if keep_from > 0:
        # collection range: deliver slices [keep_from, cut_from) only —
        # files, NIfTI, sidecar mapping and provenance all honor the range
        source_files = source_files[keep_from:cut_from]
        cut_from = cut_from - keep_from
        provenance += f" (collected from slice {keep_from})"

    want_dcm = export_format in (FORMAT_DICOM, FORMAT_BOTH)
    want_nii = export_format in (FORMAT_NIFTI, FORMAT_BOTH)

    if progress:
        progress(0, 1, "preparing")
    dcm = _write_kept_dicoms(source_files, dest, specimen, cut_from, report,
                            wanted=want_dcm,
                            progress=(lambda i, n: progress(i, n, "dicom")
                                      if progress else None))
    if progress:
        progress(0, 1, "nifti")
    nii = _write_kept_nifti(stripped_nii, dest, specimen, dataset_key,
                           cut_from, source_files, report,
                           wanted=want_nii,
                           progress=(lambda i, n: progress(i, n, "nifti")
                                     if progress else None))
    if progress:
        progress(1, 1, "sidecar")
    sidecar = _write_sidecar(dest, specimen, dataset_key, source_files,
                             cut_from, report, dcm["mapping"], nii,
                             provenance, n_slices_original=n_orig_slices,
                             tags=dcm.get("tags"),
                             collection_from=keep_from)
    txt = _write_info_txt(dest, specimen, dataset_key, source_files,
                          cut_from, report, sidecar, provenance,
                          n_slices_original=n_orig_slices)
    if progress:
        progress(1, 1, "verify")
    # ---- self verification (adapted to the requested artifacts) ----------
    import pydicom
    problems = []
    if want_dcm:
        series_dir = Path(dcm["series_dir"])
        out_files = sorted(series_dir.glob("*.dcm"))
        if len(out_files) != cut_from:
            problems.append(f"file count {len(out_files)} != {cut_from}")
        # kept slices keep their ORIGINAL filenames, whose alphabetical
        # order need not match physical slice order — verify by SOP UID
        out_by_uid: dict[str, object] = {}
        for p in out_files:
            ds = pydicom.dcmread(p)
            out_by_uid[str(ds.SOPInstanceUID)] = ds
        for idx in (0, cut_from // 2, cut_from - 1):        # spot checks
            src = pydicom.dcmread(source_files[idx])
            outp = out_by_uid.get(str(src.SOPInstanceUID))
            if outp is None:
                problems.append(f"kept slice {idx} missing from the series")
                continue
            if src.PixelData != outp.PixelData:
                problems.append(f"pixel mismatch at kept slice {idx}")
            if str(outp.PatientName) != specimen:
                problems.append(f"PatientName wrong at {idx}")
            # enriched delivery metadata must be present and readable
            for tag in ("PatientID", "Modality", "StudyDescription",
                        "SeriesDescription", "SoftwareVersions",
                        "ImageComments"):
                if not str(getattr(outp, tag, "") or "").strip():
                    problems.append(f"{tag} missing at kept slice {idx}")
            if not (getattr(outp, "PixelSpacing", None) is not None and
                    len(outp.PixelSpacing) == 2 and
                    float(outp.PixelSpacing[0]) > 0):
                problems.append(f"PixelSpacing missing at kept slice {idx}")
            if not (getattr(outp, "SliceThickness", None) is not None and
                    float(outp.SliceThickness) > 0):
                problems.append(f"SliceThickness missing at kept slice {idx}")
    if want_nii:
        nii_shape = nii["shape"]
        if not nii_shape or nii_shape[0] != cut_from:
            problems.append("nifti z shape mismatch")
    if problems:
        raise BundleError("bundle verification failed: " + "; ".join(problems))

    return {"bundle_dir": str(dest), "export_format": export_format,
            "n_dicom": dcm.get("n_files", 0) if want_dcm else 0,
            "nifti": nii.get("nii"), "json": sidecar["json"],
            "txt": txt["txt"], "cut_from": cut_from,
            "keep_from": int(keep_from or 0),
            "source_folder": provenance}


def export_bundle(dataset_key: str, specimen: str, source_dir: Path,
                  report: dict, stripped_nii: Path,
                  save_root: Path,
                  source_override: str | None = None,
                  keep_from: int | None = None,
                  export_format: str = FORMAT_BOTH,
                  progress=None,
                  source_kind: str = "dicom",
                  source_path: Path | None = None,
                  source_metadata: dict | None = None) -> dict:
    """Build, verify, then atomically promote one complete specimen bundle.

    Work is isolated in a sibling staging directory. A prior complete bundle
    remains available until every requested artifact and integrity check has
    succeeded; interrupted promotion is recovered on the next export.
    """
    specimen = str(specimen)
    if not _safe_bundle_component(specimen):
        raise BundleError("specimen ID contains characters unsafe for a bundle path")
    save_root = Path(save_root)
    save_root.mkdir(parents=True, exist_ok=True)
    final, staging, old = _recover_bundle_paths(save_root, specimen)
    if (source_kind != "dicom" and final.is_dir()
            and ((final / series_dir_name(specimen)).exists()
                 or (final / _LEGACY_SERIES_DIR.format(s=specimen)).exists())):
        raise BundleError(
            "this specimen ID already has a DICOM export in the destination; "
            "choose a different specimen ID or destination to keep sources separate")
    if final.exists():
        _clean_tmp(final, specimen)
    staging.mkdir(parents=True)
    try:
        _seed_preserved_bundle_entries(final, staging, specimen, export_format)
        result = _export_bundle_into(
            dataset_key, specimen, source_dir, report, stripped_nii,
            staging, source_override=source_override, keep_from=keep_from,
            export_format=export_format, progress=progress,
            source_kind=source_kind, source_path=source_path,
            source_metadata=source_metadata)
        _promote_directory(staging, final, old)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    result["bundle_dir"] = str(final)
    for key in ("nifti", "json", "txt"):
        path = result.get(key)
        if path:
            result[key] = str(final / Path(path).name)
    return result
