#!/usr/bin/env python
"""Metadata-preserving DICOM and NIfTI delivery for cropped wood ROIs."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import warnings
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Iterable

import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, UID, generate_uid


DELIVERY_SCHEMA = "metal-remover-roi-delivery/1.0"
# The legacy scanner's SOP Instance UID suffixes contain leading zeros. Keep
# them verbatim in provenance strings, but suppress the known validation noise
# while reading; derivative UID elements are generated validly and verified.
warnings.filterwarnings("ignore", message=r"Invalid value for VR UI:.*",
                        category=UserWarning)
INDEX_FIELDS = [
    "dataset", "specimen_id", "roi_file", "roi_instance", "source_file",
    "source_instance", "source_sop_instance_uid", "derived_sop_instance_uid",
    "derived_series_instance_uid", "image_position_patient",
    "rows", "columns", "pixel_spacing", "pixel_sha256",
]


def read_dicom(path: Path, *, stop_before_pixels: bool = False):
    """Read legacy scanner DICOM while containing its known invalid-UID noise."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Invalid value for VR UI:.*")
        return pydicom.dcmread(path, stop_before_pixels=stop_before_pixels)


def list_dicom_files(sample_dir: Path) -> list[Path]:
    xy = sample_dir / "XY"
    files = sorted(p for p in xy.glob("*.dcm") if p.is_file())
    if not files:
        raise FileNotFoundError(f"no DICOM files under {xy}")
    return files


def _orientation(ds: Dataset) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    try:
        values = np.asarray(ds.ImageOrientationPatient, dtype=np.float64)
    except Exception as exc:
        raise ValueError("ImageOrientationPatient is missing or invalid") from exc
    if values.shape != (6,) or not np.isfinite(values).all():
        raise ValueError("ImageOrientationPatient must contain six values")
    row_dir, col_dir = values[:3], values[3:]
    if not np.isclose(np.linalg.norm(row_dir), 1.0, atol=1e-5):
        raise ValueError("invalid DICOM row direction cosine")
    if not np.isclose(np.linalg.norm(col_dir), 1.0, atol=1e-5):
        raise ValueError("invalid DICOM column direction cosine")
    if not np.isclose(np.dot(row_dir, col_dir), 0.0, atol=1e-5):
        raise ValueError("DICOM row and column direction cosines are not orthogonal")
    normal = np.cross(row_dir, col_dir)
    normal_length = float(np.linalg.norm(normal))
    if not np.isfinite(normal_length) or normal_length <= 1e-8:
        raise ValueError("invalid DICOM slice normal")
    normal /= normal_length
    return row_dir, col_dir, normal


def sorted_source_files(sample_dir: Path) -> list[Path]:
    """Sort single-frame DICOM slices by position along their slice normal."""
    files = list_dicom_files(sample_dir)
    first = read_dicom(files[0], stop_before_pixels=True)
    _, _, normal = _orientation(first)
    positions = []
    expected_iop = np.asarray(first.ImageOrientationPatient, dtype=np.float64)
    expected_shape = (int(first.Rows), int(first.Columns))
    expected_spacing = tuple(float(v) for v in first.PixelSpacing)
    if (min(expected_shape) <= 0 or len(expected_spacing) != 2
            or not np.isfinite(expected_spacing).all()
            or min(expected_spacing) <= 0):
        raise ValueError("invalid Rows/Columns or PixelSpacing in first DICOM")
    series_uid = str(getattr(first, "SeriesInstanceUID", "") or "")
    for path in files:
        ds = read_dicom(path, stop_before_pixels=True)
        if (int(ds.Rows), int(ds.Columns)) != expected_shape:
            raise ValueError(f"{path.name}: inconsistent Rows/Columns")
        if not np.allclose(np.asarray(ds.ImageOrientationPatient, float),
                           expected_iop, atol=1e-6):
            raise ValueError(f"{path.name}: inconsistent orientation")
        spacing = tuple(float(v) for v in ds.PixelSpacing)
        if spacing != expected_spacing:
            raise ValueError(f"{path.name}: inconsistent PixelSpacing")
        this_series = str(getattr(ds, "SeriesInstanceUID", "") or "")
        if series_uid and this_series and this_series != series_uid:
            raise ValueError(f"{path.name}: different SeriesInstanceUID")
        if int(getattr(ds, "NumberOfFrames", 1)) != 1:
            raise ValueError(f"{path.name}: multi-frame DICOM is not supported")
        if int(getattr(ds, "SamplesPerPixel", 1)) != 1:
            raise ValueError(f"{path.name}: only monochrome DICOM slices are supported")
        ipp = np.asarray(ds.ImagePositionPatient, dtype=np.float64)
        if ipp.shape != (3,) or not np.isfinite(ipp).all():
            raise ValueError(f"{path.name}: invalid ImagePositionPatient")
        positions.append(float(np.dot(ipp, normal)))
    positions = np.asarray(positions, dtype=np.float64)
    if not np.isfinite(positions).all():
        raise ValueError("DICOM slice positions contain non-finite values")
    order = np.argsort(positions, kind="stable")
    ordered = [files[int(i)] for i in order]
    steps = np.diff(positions[order])
    if len(steps) and (np.any(steps <= 0)
                       or not np.allclose(steps, np.median(steps), atol=1e-3)):
        raise ValueError("DICOM slice positions are duplicate or non-uniform")
    return ordered


def cropped_image_position(ds: Dataset, y0: int, x0: int) -> np.ndarray:
    """Patient-space center of cropped pixel (row=0, column=0)."""
    row_dir, col_dir, _ = _orientation(ds)
    row_spacing, col_spacing = (float(v) for v in ds.PixelSpacing)
    origin = np.asarray(ds.ImagePositionPatient, dtype=np.float64)
    return (origin + row_dir * (x0 * col_spacing)
            + col_dir * (y0 * row_spacing))


def _valid_uid(value: object) -> bool:
    try:
        return bool(value) and UID(str(value)).is_valid
    except Exception:
        return False


def _derived_uid(*parts: object) -> str:
    return generate_uid(entropy_srcs=[DELIVERY_SCHEMA, *(str(p) for p in parts)])


def _stored_pixel_bytes(arr: np.ndarray, ds: Dataset) -> bytes:
    bits = int(ds.BitsAllocated)
    signed = int(ds.PixelRepresentation) == 1
    if bits == 8:
        dtype = np.dtype("i1" if signed else "u1")
    elif bits == 16:
        dtype = np.dtype("<i2" if signed else "<u2")
    elif bits == 32:
        dtype = np.dtype("<i4" if signed else "<u4")
    else:
        raise ValueError(f"unsupported BitsAllocated={bits}")
    return np.ascontiguousarray(arr, dtype=dtype).tobytes()


def _specimen_sequence(specimen_id: str, dataset_key: str) -> Sequence:
    item = Dataset()
    item.SpecimenIdentifier = specimen_id
    item.SpecimenUID = _derived_uid("specimen", dataset_key, specimen_id)
    item.SpecimenShortDescription = f"Wood specimen {specimen_id}"
    return Sequence([item])


def make_roi_dataset(source: Dataset, crop: np.ndarray, *, y0: int, x0: int,
                     specimen_id: str, dataset_key: str, series_uid: str,
                     roi_instance: int) -> Dataset:
    """Create one derived ROI slice while preserving unrelated source tags."""
    if crop.ndim != 2 or int(getattr(source, "SamplesPerPixel", 1)) != 1:
        raise ValueError("only single-frame monochrome DICOM slices are supported")
    ds = deepcopy(source)
    original_sop = str(getattr(source, "SOPInstanceUID", ""))
    original_class = str(source.SOPClassUID)
    derived_sop = _derived_uid("instance", dataset_key, specimen_id,
                               original_sop, y0, x0, crop.shape)

    ds.Rows, ds.Columns = (int(crop.shape[0]), int(crop.shape[1]))
    ds.ImagePositionPatient = [f"{v:.12g}"
                               for v in cropped_image_position(source, y0, x0)]
    ds.PixelData = _stored_pixel_bytes(crop, source)
    ds["PixelData"].VR = "OB" if int(ds.BitsAllocated) <= 8 else "OW"
    ds["PixelData"].is_undefined_length = False
    if "SmallestImagePixelValue" in ds:
        ds.SmallestImagePixelValue = int(np.min(crop))
    if "LargestImagePixelValue" in ds:
        ds.LargestImagePixelValue = int(np.max(crop))

    ds.SOPInstanceUID = derived_sop
    ds.SeriesInstanceUID = series_uid
    # Retain the source InstanceNumber; the ROI series is a contiguous subset.
    ds.ImageType = ["DERIVED", "SECONDARY", "AXIAL"]
    original_desc = str(getattr(source, "SeriesDescription", "") or "")
    suffix = f"Wood ROI [{dataset_key}:{specimen_id}]"
    ds.SeriesDescription = f"{original_desc} | {suffix}" if original_desc else suffix
    ds.DerivationDescription = (
        "Metal-platform removal followed by tracked wood bounding-box crop; "
        f"specimen={specimen_id}; source instance preserved in provenance index"
    )
    ds.SpecimenDescriptionSequence = _specimen_sequence(specimen_id, dataset_key)
    if _valid_uid(original_class) and _valid_uid(original_sop):
        ref = Dataset()
        ref.ReferencedSOPClassUID = original_class
        ref.ReferencedSOPInstanceUID = original_sop
        ds.SourceImageSequence = Sequence([ref])
    elif "SourceImageSequence" in ds:
        del ds.SourceImageSequence

    if not hasattr(ds, "file_meta") or ds.file_meta is None:
        raise ValueError("source DICOM has no File Meta Information")
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = derived_sop
    return ds


def export_roi_dicom_series(sample_dir: Path, out_dir: Path, report: dict,
                            dataset_key: str, specimen_id: str) -> dict:
    """Atomically write a cropped, metadata-preserving DICOM ROI series."""
    bbox = report["wood_roi"]["bbox_zyx"]
    if bbox is None:
        raise ValueError(f"{specimen_id}: report has no wood ROI bbox")
    z0, z1, y0, y1, x0, x1 = (int(v) for v in bbox)
    files = sorted_source_files(sample_dir)
    if not (0 <= z0 <= z1 < len(files)):
        raise ValueError(f"{specimen_id}: ROI z bounds are outside source series")

    first = read_dicom(files[z0], stop_before_pixels=True)
    source_series_uid = str(getattr(first, "SeriesInstanceUID", ""))
    series_uid = _derived_uid("series", dataset_key, specimen_id,
                              source_series_uid, bbox)
    final_dir = out_dir / "wood_roi_dicom"
    tmp_dir = out_dir / ".wood_roi_dicom.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    rows: list[dict] = []

    def _export_one(job: tuple[int, int]) -> dict:
        """Crop + derive + write one ROI slice (thread worker, audit 0N).

        Pure per-slice work — deterministic UIDs (hash-derived), unique
        destination names, order restored by the executor map."""
        roi_i, source_i = job
        source_path = files[source_i]
        source = read_dicom(source_path)
        pixels = source.pixel_array
        crop = np.ascontiguousarray(pixels[y0:y1 + 1, x0:x1 + 1])
        expected_shape = (y1 - y0 + 1, x1 - x0 + 1)
        if crop.shape != expected_shape:
            raise ValueError(f"{source_path.name}: ROI crop shape mismatch")
        ds = make_roi_dataset(
            source, crop, y0=y0, x0=x0, specimen_id=specimen_id,
            dataset_key=dataset_key, series_uid=series_uid,
            roi_instance=roi_i,
        )
        name = f"{specimen_id}_wood_roi_{roi_i:04d}.dcm"
        destination = tmp_dir / name
        pydicom.dcmwrite(destination, ds, enforce_file_format=True)
        return {
            "dataset": dataset_key,
            "specimen_id": specimen_id,
            "roi_file": name,
            "roi_instance": roi_i,
            "source_file": source_path.name,
            "source_instance": str(getattr(source, "InstanceNumber", "")),
            "source_sop_instance_uid": str(getattr(source, "SOPInstanceUID", "")),
            "derived_sop_instance_uid": str(ds.SOPInstanceUID),
            "derived_series_instance_uid": series_uid,
            "image_position_patient": ";".join(str(v)
                                                 for v in ds.ImagePositionPatient),
            "rows": int(ds.Rows),
            "columns": int(ds.Columns),
            "pixel_spacing": ";".join(str(v) for v in ds.PixelSpacing),
            "pixel_sha256": hashlib.sha256(ds.PixelData).hexdigest(),
        }

    try:
        # threaded slice pipeline (audit 0N): pixel decode, crop, derivation
        # and encode are CPU-bound per slice and independent — the executor
        # map preserves ROI order, so the index and series are byte-identical
        # to the serial loop (UIDs are content-hash-derived, not random).
        with ThreadPoolExecutor(max_workers=8) as ex:
            rows = list(ex.map(_export_one,
                               enumerate(range(z0, z1 + 1), start=1)))

        index_tmp = out_dir / ".wood_roi_dicom_index.csv.tmp"
        with open(index_tmp, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        if final_dir.exists():
            shutil.rmtree(final_dir)
        os.replace(tmp_dir, final_dir)
        os.replace(index_tmp, out_dir / "wood_roi_dicom_index.csv")
    except Exception:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        raise

    return {
        "dicom_directory": final_dir.name,
        "dicom_slices": len(rows),
        "derived_series_instance_uid": series_uid,
        "index": "wood_roi_dicom_index.csv",
    }


def _header_json(ds: Dataset) -> dict:
    header = deepcopy(ds)
    if "PixelData" in header:
        del header.PixelData
    return header.to_json_dict()


def nifti_metadata_payload(source_files: list[Path] | None, bbox: Iterable[int],
                           dataset_key: str, specimen_id: str,
                           source_metadata: dict | None = None) -> dict:
    bbox = [int(v) for v in bbox]
    z0, z1, y0, y1, x0, x1 = bbox
    if not source_files:
        metadata = dict(source_metadata or {})
        metadata.pop("intensity_sample_percentiles", None)
        return {
            "schema": DELIVERY_SCHEMA,
            "dataset": dataset_key,
            "specimen_id": specimen_id,
            "coordinate_system": "NIfTI RAS+",
            "roi_bbox_source_zyx_inclusive": bbox,
            "source_format": metadata.get("source_format", "unknown"),
            "source_path": metadata.get("source_path"),
            "source_signature": metadata.get("source_signature"),
            "source_geometry": {
                "shape_zyx": metadata.get("shape_zyx"),
                "spacing_zyx_mm": metadata.get("spacing_zyx_mm"),
                "affine_ras_xyz": metadata.get("affine_ras_xyz"),
                "geometry_assumed": metadata.get("geometry_assumed"),
            },
            "source_intensity": {
                "mode": metadata.get("intensity_mode"),
                "unit": metadata.get("intensity_unit"),
                "threshold_strategy": metadata.get("threshold_strategy"),
            },
            "processing": {
                "description": "metal-platform removal and tracked wood ROI crop",
                "pixel_values": "float32 source values; source scaling applied",
            },
        }
    first = read_dicom(source_files[z0], stop_before_pixels=True)
    last = read_dicom(source_files[z1], stop_before_pixels=True)

    def _slice_info(source_i: int) -> dict:
        ds = read_dicom(source_files[source_i], stop_before_pixels=True)
        return {
            "source_file": source_files[source_i].name,
            "source_instance_number": str(getattr(ds, "InstanceNumber", "")),
            "source_sop_instance_uid": str(getattr(ds, "SOPInstanceUID", "")),
            "source_image_position_patient": [float(v)
                                                for v in ds.ImagePositionPatient],
        }

    # threaded header reads (audit 0N): pure I/O, order preserved by map
    with ThreadPoolExecutor(max_workers=8) as ex:
        slices = list(ex.map(_slice_info, range(z0, z1 + 1)))
    return {
        "schema": DELIVERY_SCHEMA,
        "dataset": dataset_key,
        "specimen_id": specimen_id,
        "coordinate_system": "NIfTI RAS+; original DICOM coordinates are LPS",
        "roi_bbox_source_zyx_inclusive": bbox,
        "source_first_slice_header_dicom_json": _header_json(first),
        "source_file_meta_dicom_json": first.file_meta.to_json_dict(),
        "source_last_image_position_patient": [float(v)
                                                for v in last.ImagePositionPatient],
        "source_slices": slices,
        "processing": {
            "description": "metal-platform removal and tracked wood ROI crop",
            "pixel_values": "float32 modality values; source rescale applied",
        },
    }


def nifti_affine(source_files: list[Path], bbox: Iterable[int]) -> np.ndarray:
    """Return a DICOM-geometry-faithful RAS+ affine for ROI (x, y, z)."""
    z0, z1, y0, y1, x0, x1 = (int(v) for v in bbox)
    first = read_dicom(source_files[z0], stop_before_pixels=True)
    row_dir, col_dir, normal = _orientation(first)
    row_spacing, col_spacing = (float(v) for v in first.PixelSpacing)
    origin = cropped_image_position(first, y0, x0)
    if z1 > z0:
        second = read_dicom(source_files[z0 + 1], stop_before_pixels=True)
        slice_vec = (np.asarray(second.ImagePositionPatient, dtype=np.float64)
                     - np.asarray(first.ImagePositionPatient, dtype=np.float64))
    else:
        dz = float(getattr(first, "SpacingBetweenSlices", 0.0)
                   or getattr(first, "SliceThickness", 1.0))
        slice_vec = normal * dz
    affine_lps = np.eye(4, dtype=np.float64)
    affine_lps[:3, 0] = row_dir * col_spacing
    affine_lps[:3, 1] = col_dir * row_spacing
    affine_lps[:3, 2] = slice_vec
    affine_lps[:3, 3] = origin
    lps_to_ras = np.diag([-1.0, -1.0, 1.0, 1.0])
    return lps_to_ras @ affine_lps


def _nifti_prefix_bytes(img) -> bytes:
    """Serialize a Nifti1Image's on-disk prefix — 348-byte header, 4-byte
    extender, and any extensions — byte-exactly as ``nib.save`` writes it,
    WITHOUT materializing the voxel data (audit 0N).  The caller then
    streams the (z, y, x) planes: in the canonical NIfTI layout each
    plane (y, x) at fixed z is contiguous, so sequential single-plane
    writes reproduce the file exactly (proven byte-identical by
    cleanCT/build/bench_stream_process_writes.py)."""
    import io
    import nibabel as nib
    has_ext = len(img.header.extensions) > 0
    ext_size = (img.header.extensions.get_sizeondisk() if has_ext else 0)
    data_offset = 352 + ext_size
    img.header["vox_offset"] = float(data_offset)
    buf = io.BytesIO()
    buf.write(img.header.structarr.tobytes())
    buf.write(b"\x01\x00\x00\x00" if has_ext else b"\x00\x00\x00\x00")
    if has_ext:
        img.header.extensions.write_to(buf, byteswap=False)
    prefix = buf.getvalue()
    if len(prefix) != data_offset:
        raise RuntimeError(
            f"nifti prefix {len(prefix)} B != computed data offset {data_offset} B")
    return prefix


def _stream_nifti_planes(volume_zyx, prefix: bytes, tmp_path: Path,
                         fsync_every: int = 256,
                         plane_axis: str = "z") -> None:
    """Write the NIfTI data planes sequentially with bounded dirty-page
    pressure (audit 0N).  Byte-identical to the in-RAM nib.save path while
    eliminating the full-volume transpose copy and the end-of-write page-
    cache stall on slow destinations.  Peak extra RAM: one plane.

    nibabel serializes data in Fortran order of the header's dim array:

    * ``plane_axis='z'`` — dim labeled (x, y, z): x varies fastest, so the
      file is the (y, x) planes of the (z, y, x) volume back-to-back
      (the pipeline's wood_roi.nii / stripped.nii layout).
    * ``plane_axis='x'`` — dim labeled (z, y, x): z varies fastest, so the
      file is (y, z) columns grouped per x (the bundle-export fallback's
      historical layout from ``Nifti1Image(vol_zyx)``).
    """
    with open(tmp_path, "wb") as f:
        f.write(prefix)
        if plane_axis == "z":
            planes = range(volume_zyx.shape[0])
            get = lambda i: volume_zyx[i]
        else:
            vol_xyz = volume_zyx.transpose(2, 1, 0)   # (x, y, z) view
            planes = range(vol_xyz.shape[0])
            get = lambda i: vol_xyz[i]
        for i in planes:
            f.write(np.ascontiguousarray(get(i)).tobytes())
            if (i + 1) % fsync_every == 0:
                f.flush()
                os.fsync(f.fileno())
        f.flush()
        os.fsync(f.fileno())


def write_roi_nifti(volume_zyx, path: Path, *, bbox: Iterable[int],
                     dataset_key: str, specimen_id: str,
                     source_files: list[Path] | None = None,
                     source_affine_xyz: np.ndarray | list | None = None,
                     source_metadata: dict | None = None) -> dict:
    """Atomically write uncompressed NIfTI-1 with embedded source metadata.

    Audit 0N: voxel data is streamed plane-by-plane — byte-identical to
    the previous nib.save in-RAM path (which materialized a full (x, y, z)
    transpose copy plus nibabel's own serialization copy), roughly 2-4x
    faster on real volumes, and with periodic fsyncs so a slow destination
    never accumulates a multi-GB write cache that stalls the process."""
    import nibabel as nib

    bbox = [int(v) for v in bbox]
    expected = (bbox[1] - bbox[0] + 1, bbox[3] - bbox[2] + 1,
                bbox[5] - bbox[4] + 1)
    if tuple(volume_zyx.shape) != expected:
        raise ValueError(f"NIfTI source shape {volume_zyx.shape} != ROI {expected}")
    if source_affine_xyz is not None:
        affine = np.asarray(source_affine_xyz, dtype=np.float64)
        if affine.shape != (4, 4) or not np.isfinite(affine).all():
            raise ValueError("source affine must be a finite 4 x 4 matrix")
        shift = np.eye(4, dtype=np.float64)
        shift[:3, 3] = [bbox[4], bbox[3], bbox[0]]
        affine = affine @ shift
    elif source_files:
        affine = nifti_affine(source_files, bbox)
    else:
        raise ValueError("NIfTI export needs DICOM source files or a source affine")
    # Header-only image: the voxel payload is streamed by hand, so the
    # data array is never materialized.  The (dummy, set_data_shape)
    # pattern serializes byte-identically to the full-data constructor
    # (proven by the bench harness).
    img = nib.Nifti1Image(np.zeros((1, 1, 1), np.float32), affine)
    img.set_qform(affine, code=1)
    img.set_sform(affine, code=1)
    img.header.set_data_shape((expected[2], expected[1], expected[0]))
    img.header.set_data_dtype(np.float32)
    img.header.set_xyzt_units("mm", "unknown")
    img.header["descrip"] = f"Wood ROI; specimen={specimen_id}; dataset={dataset_key}"
    img.header["aux_file"] = f"specimen={specimen_id}"
    img.header["intent_name"] = "WOOD_ROI"
    finite = np.isfinite(volume_zyx)
    if finite.any():
        img.header["cal_min"] = float(np.nanmin(volume_zyx))
        img.header["cal_max"] = float(np.nanmax(volume_zyx))
    payload = nifti_metadata_payload(source_files, bbox, dataset_key, specimen_id,
                                     source_metadata=source_metadata)
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    img.header.extensions.clear()
    img.header.extensions.append(nib.nifti1.Nifti1Extension("comment", content))
    img.header["scl_slope"] = 1.0
    img.header["scl_inter"] = 0.0

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.tmp.nii")
    _stream_nifti_planes(volume_zyx, _nifti_prefix_bytes(img), tmp)
    os.replace(tmp, path)
    return {
        "nifti_file": path.name,
        "shape_xyz": [expected[2], expected[1], expected[0]],
        "dtype": "float32",
        "coordinate_system": "RAS+",
        "embedded_metadata_schema": DELIVERY_SCHEMA,
    }


def write_stripped_nifti(volume_zyx, path: Path, *,
                         cut_from: int, dataset_key: str,
                         specimen_id: str,
                         source_files: list[Path] | None = None,
                         source_affine_xyz: np.ndarray | list | None = None,
                         source_metadata: dict | None = None) -> None:
    """Stream the full-FOV stripped volume (audit 0N).

    Replaces the processing path's in-RAM ``nib.save`` — which built a
    second full-volume float32 transpose copy before serializing — with
    sequential plane writes from the in-RAM (z, y, x) volume.  Byte-
    identical output (same header fields as nibabel's own save, proven by
    the bench harness), atomic tmp+rename, bounded write-backpressure.

    NOTE: the FULL volume is written — slices at and beyond the cut carry
    NaN voids exactly as the historical format did (the bundle exporter
    and external tools rely on that shape)."""
    import nibabel as nib

    nz, ny, nx = (int(volume_zyx.shape[0]), int(volume_zyx.shape[1]),
                  int(volume_zyx.shape[2]))
    if cut_from > nz:
        raise ValueError(f"cut_from {cut_from} exceeds volume depth {nz}")
    if source_affine_xyz is not None:
        affine = np.asarray(source_affine_xyz, dtype=np.float64)
        if affine.shape != (4, 4) or not np.isfinite(affine).all():
            raise ValueError("source affine must be a finite 4 x 4 matrix")
    elif source_files:
        affine = nifti_affine(source_files, (0, cut_from - 1, 0, 0, 0, 0))
    else:
        raise ValueError("stripped NIfTI needs DICOM source files or a source affine")
    img = nib.Nifti1Image(np.zeros((1, 1, 1), np.float32), affine)
    # The historical format stores the (x, y, z)-labeled shape (x fastest,
    # produced by the old transpose+save path) — keep that dim order so
    # external tools see the identical volume orientation.
    img.header.set_data_shape((nx, ny, nz))
    img.header.set_data_dtype(np.float32)
    img.header["descrip"] = (
        f"stripped full-FOV; specimen={specimen_id}; dataset={dataset_key}; "
        f"slices=0..{cut_from - 1}")[:79]
    img.header["vox_offset"] = 352
    img.header["magic"] = b"n+1"
    img.header["scl_slope"] = 1.0
    img.header["scl_inter"] = 0.0
    prefix = img.header.structarr.tobytes() + b"\x00\x00\x00\x00"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.tmp.nii")
    _stream_nifti_planes(volume_zyx, prefix, tmp)
    os.replace(tmp, path)


def rewrite_existing_roi_nifti(path: Path, *, source_files: list[Path],
                                bbox: Iterable[int], dataset_key: str,
                                specimen_id: str) -> dict:
    """Reheader an existing ROI NIfTI without changing its voxel values."""
    import nibabel as nib

    import gc

    old = nib.load(str(path), mmap=True)
    # Own the bytes before replacing the same file. A live NumPy memmap keeps
    # the target locked on Windows and makes os.replace fail with WinError 5.
    xyz = np.array(old.dataobj, dtype=np.float32, copy=True)
    del old
    gc.collect()
    # write_roi_nifti accepts z,y,x.
    return write_roi_nifti(xyz.transpose(2, 1, 0), path,
                            source_files=source_files, bbox=bbox,
                            dataset_key=dataset_key, specimen_id=specimen_id)


def write_provenance(out_dir: Path, report: dict, delivery: dict) -> None:
    payload = {
        "schema": DELIVERY_SCHEMA,
        "sample": report.get("sample"),
        "dataset": report.get("dataset"),
        "platform": report.get("platform"),
        "wood_roi": report.get("wood_roi"),
        "source_geometry": report.get("meta"),
        "delivery": delivery,
    }
    tmp = out_dir / ".wood_roi_provenance.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, out_dir / "wood_roi_provenance.json")
