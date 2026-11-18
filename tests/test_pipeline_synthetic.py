"""Synthetic, isolated end-to-end checks for DICOM load/process/view/export."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

if not all(os.environ.get(name) for name in
           ("CLEANCT_ENGINE", "CLEANCT_DATA", "CLEANCT_TEST_TMP_DIR",
            "CLEANCT_OUTPUT_ROOT")):
    raise SystemExit("Set isolated CLEANCT_ENGINE, CLEANCT_DATA, "
                     "CLEANCT_TEST_TMP_DIR, and CLEANCT_OUTPUT_ROOT first")

ROOT = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))

import nibabel as nib
import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from scipy import ndimage as ndi

from core import bundle_export, viewer_core
import tomograph as tg
from gpu_backend import _CROSS_BOOL

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def write_slice(path: Path, z: float, pixels: np.ndarray | None = None,
                *, rows: int = 192, cols: int = 192,
                series_uid: str | None = None,
                pixel_data: bytes | None = None) -> None:
    d = Dataset()
    d.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    d.SOPInstanceUID = generate_uid()
    d.StudyInstanceUID = STUDY_UID
    d.SeriesInstanceUID = series_uid or SERIES_UID
    d.Modality = "CT"
    d.Rows, d.Columns = rows, cols
    d.SamplesPerPixel = 1
    d.BitsAllocated = 16
    d.BitsStored = 16
    d.HighBit = 15
    d.PixelRepresentation = 1
    d.PhotometricInterpretation = "MONOCHROME2"
    d.PixelSpacing = [0.033, 0.033]
    d.SliceThickness = 0.5
    d.ImagePositionPatient = [0, 0, float(z)]
    d.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    d.RescaleSlope, d.RescaleIntercept = 1.0, 0.0
    d.file_meta = FileMetaDataset()
    d.file_meta.MediaStorageSOPClassUID = d.SOPClassUID
    d.file_meta.MediaStorageSOPInstanceUID = d.SOPInstanceUID
    d.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    if pixel_data is not None:
        d.PixelData = pixel_data
    elif pixels is not None:
        d.PixelData = np.asarray(pixels, dtype=np.int16).tobytes()
    else:
        d.PixelData = np.zeros((rows, cols), np.int16).tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    pydicom.dcmwrite(path, d, enforce_file_format=True)


STUDY_UID, SERIES_UID = generate_uid(), generate_uid()
WORK_ROOT = Path(tempfile.mkdtemp(prefix="cleanct_pipeline_synthetic_",
                                  dir=os.environ["CLEANCT_TEST_TMP_DIR"]))

try:
    # Resolution-aware batching and deterministic early memory rejection.
    small_plan = tg._dicom_load_plan(1200, 1200, 16, cpu_count=20)
    large_plan = tg._dicom_load_plan(6000, 6000, 16, cpu_count=20)
    check("DICOM decode batches stay bounded as slice size grows",
          small_plan[0] > large_plan[0] >= 1 and large_plan[1] == 1,
          f"1200px={small_plan}, 6000px={large_plan}")
    try:
        tg._check_load_memory(1000, 6000, 6000, 1,
                              available_bytes=2 * 1024**3)
        memory_rejected = False
    except MemoryError:
        memory_rejected = True
    check("volume allocation rejects a RAM-impossible scan before allocation",
          memory_rejected)

    # Empty directory, one-slice input, empty/corrupt DICOM and short PixelData.
    empty_dir = WORK_ROOT / "empty" / "XY"
    empty_dir.mkdir(parents=True)
    try:
        tg.load_volume(empty_dir.parent, tg.get_backend(preference="cpu"), workers=2)
        empty_rejected = False
    except FileNotFoundError:
        empty_rejected = True
    check("empty DICOM directory is rejected with a handled error", empty_rejected)

    single = WORK_ROOT / "single" / "XY"
    write_slice(single / "one.dcm", 0, np.zeros((16, 16), np.int16),
                rows=16, cols=16)
    try:
        tg.load_volume(single.parent, tg.get_backend(preference="cpu"), workers=2)
        single_rejected = False
    except ValueError as exc:
        single_rejected = "at least two slices" in str(exc)
    check("single-slice volume is rejected before spacing math", single_rejected)

    corrupt_header = WORK_ROOT / "corrupt_header" / "XY"
    write_slice(corrupt_header / "valid.dcm", 0,
                np.zeros((16, 16), np.int16), rows=16, cols=16)
    (corrupt_header / "empty.dcm").write_bytes(b"")
    try:
        tg.load_volume(corrupt_header.parent,
                       tg.get_backend(preference="cpu"), workers=2)
        bad_header_rejected = False
    except ValueError as exc:
        bad_header_rejected = "empty.dcm" in str(exc)
    check("empty/corrupt DICOM header is reported as a controlled input error",
          bad_header_rejected)

    corrupt_pixels = WORK_ROOT / "corrupt_pixels" / "XY"
    write_slice(corrupt_pixels / "a.dcm", 0,
                pixel_data=b"\x00\x00", rows=16, cols=16)
    write_slice(corrupt_pixels / "b.dcm", 0.5,
                np.zeros((16, 16), np.int16), rows=16, cols=16)
    pixel_backend = tg.get_backend(preference="cpu")
    released = []
    pixel_backend.release = lambda: released.append(True)
    try:
        tg.load_volume(corrupt_pixels.parent, pixel_backend, workers=2)
        bad_pixels_rejected = False
    except ValueError as exc:
        bad_pixels_rejected = "pixel buffer too small" in str(exc)
    check("truncated DICOM PixelData is rejected before array decode",
          bad_pixels_rejected)
    check("failed DICOM decode releases its partially allocated backend volume",
          released == [True], f"release calls={len(released)}")

    nonuniform = WORK_ROOT / "nonuniform" / "XY"
    for z in (0, 0.5, 1.5):
        write_slice(nonuniform / f"z{z}.dcm", z,
                    np.zeros((16, 16), np.int16), rows=16, cols=16)
    try:
        tg.load_volume(nonuniform.parent,
                       tg.get_backend(preference="cpu"), workers=2)
        nonuniform_rejected = False
    except ValueError as exc:
        nonuniform_rejected = "non-uniform slice spacing" in str(exc)
    check("nonuniform slice spacing is rejected", nonuniform_rejected)

    # A CuPy step that fails mid-run must fall back to CPU for that step and
    # disable the backend for the rest of the run. No GPU is needed: a stand-in
    # reports backend "cupy" and its label kernel fails the way an NVRTC
    # compile error does.
    import subprocess
    import gpu_backend as gb
    import wood_track as wt
    from scipy import ndimage as _ndi

    class _FailingCupy:
        backend = "cupy"

        def __init__(self):
            self.disabled_reason = None

        def to_gpu(self, arr):
            return np.asarray(arr)

        def to_cpu(self, arr):
            return np.asarray(arr)

        def release(self):
            pass

        def label_slice(self, mask):
            raise RuntimeError("nvrtc: synthetic compile failure")

        def disable(self, reason):
            self.backend = "cpu"
            self.disabled_reason = reason

    fallback_mask = np.zeros((40, 40), dtype=bool)
    fallback_mask[4:12, 4:30] = True
    fallback_mask[20:35, 20:24] = True
    fake_gpu = _FailingCupy()
    try:
        cpu_parts = wt._components(fallback_mask, 1, gpu=None)
        gpu_parts = wt._components(fallback_mask, 1, gpu=fake_gpu)
        same = (len(cpu_parts) == len(gpu_parts) and all(
            a[:5] == b[:5] and np.array_equal(a[5], b[5])
            for a, b in zip(cpu_parts, gpu_parts)))
        check("GPU label failure falls back to CPU with identical components",
              same and len(cpu_parts) == 2,
              f"cpu={len(cpu_parts)} fallback={len(gpu_parts)}")
    except Exception as exc:
        check("GPU label failure falls back to CPU with identical components",
              False, f"raised {type(exc).__name__}: {exc}")
    check("GPU failure is logged as the reason the backend was disabled",
          fake_gpu.disabled_reason is not None
          and "nvrtc" in str(fake_gpu.disabled_reason),
          str(fake_gpu.disabled_reason))

    # the startup probe must not flash a console window under the launcher
    captured: dict = {}
    real_run = gb.subprocess.run

    def probe_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

    gb.subprocess.run = probe_run
    try:
        gb._cupy_candidate()
    finally:
        gb.subprocess.run = real_run
    check("CuPy probe runs with CREATE_NO_WINDOW",
          captured.get("creationflags") == getattr(subprocess, "CREATE_NO_WINDOW", 0),
          repr(captured.get("creationflags")))

    cupy_backend = tg.get_backend(preference="cupy", verbose=False)
    if cupy_backend.backend != "cupy":
        print("SKIP CuPy morphology iteration parity (needs an active CuPy device)")
    else:
        morph_mask = np.zeros((64, 64), dtype=bool)
        morph_mask[12:52, 12:52] = True
        morph_mask[28:36, 28:36] = False
        morph_ok = True
        try:
            for operation in ("binary_erosion", "binary_dilation",
                              "binary_opening", "binary_closing"):
                actual = cupy_backend.to_cpu(
                    getattr(cupy_backend, operation)(morph_mask, iterations=2))
                expected = getattr(ndi, operation)(
                    morph_mask, structure=_CROSS_BOOL, iterations=2)
                morph_ok &= np.array_equal(actual, expected)
        except Exception as exc:
            morph_ok = False
            morph_error = type(exc).__name__
        else:
            morph_error = ""
        finally:
            cupy_backend.release()
        check("CuPy morphology iteration parity", morph_ok, morph_error)

    # Complete miniature workflow with deliberately reversed filenames.
    sample = "SYNTHETIC"
    sample_dir = WORK_ROOT / "data" / sample
    series = sample_dir / "XY"
    rows = cols = 192
    yy, xx = np.mgrid[:rows, :cols]
    wood = (yy - rows // 2) ** 2 + (xx - cols // 2) ** 2 <= 60 ** 2
    n_slices = 36
    for z in range(n_slices):
        hu = np.full((rows, cols), -1000, np.int16)
        if z < 30:
            hu[wood] = -600
        else:
            hu[wood] = 2500
        # Name order is opposite to physical z order.
        write_slice(series / f"slice_{n_slices-z:04d}.dcm", z * 0.5, hu)

    output_root = WORK_ROOT / "pipeline_output"
    ds = tg.DatasetSpec(key="synthetic", source=sample_dir.parent,
                        out_sub="", config_overrides={})
    cfg = tg.DEFAULTS.overridden({
        "platform_min_voxels": 5000,
        "platform_min_slices": 5,
        "roi_seed_min_area": 4000,
        "roi_min_area": 300,
        "roi_bbox_pad": 4,
        "cut_override": 25,
        "keep_from": 0,
        "save_nifti": True,
        "save_dicom": True,
        "save_qa_montage": False,
        "save_stripped_nii": True,
        "io_workers": 4,
    })
    old_output_root = tg.output_root
    old_viewer_output_root = viewer_core.output_root
    old_get_ds = viewer_core._get_ds
    old_cache_dir = viewer_core.CACHE_DIR
    try:
        tg.output_root = lambda _ds: output_root
        viewer_core.output_root = lambda _ds: output_root
        viewer_core._get_ds = lambda _dataset, _sample: ds
        viewer_core.CACHE_DIR = WORK_ROOT / "viewer_cache"
        viewer_core._CACHE.clear()
        viewer_core._PREV.clear()
        viewer_core.ORIG_SLICE_CACHE.clear()
        viewer_core._XY_FILES.clear()
        viewer_core._SLICE_SHAPES.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            report = tg.process_sample(
                sample, cfg, ds, False,
                tg.get_backend(preference="cpu", verbose=False),
                verbose=False)
        processed = output_root / sample
        disk_report = json.loads((processed / "report.json").read_text())
        payload = viewer_core.build_payload("synthetic", sample, use_disk=False)
        check("synthetic DICOM -> processing -> NIfTI/ROI report completes",
              report["platform"]["cut_from"] == 25
              and report["wood_roi"]["bbox_zyx"] is not None
              and (processed / "stripped.nii").is_file()
              and (processed / "wood_roi.nii").is_file()
              and len(list((processed / "wood_roi_dicom").glob("*.dcm"))) > 0)
        check("viewer reconstructs physically ordered processed slices",
              not payload.get("unprocessed") and payload.get("frames")
              and payload["cloud"]["shape"] == [n_slices, rows, cols],
              f"frames={len(payload.get('frames', []))}, "
              f"shape={payload.get('cloud', {}).get('shape')}")

        bundle = bundle_export.export_bundle(
            "synthetic", sample, sample_dir, disk_report,
            processed / "stripped.nii", WORK_ROOT / "bundle",
            export_format="both")
        bundle_dir = Path(bundle["bundle_dir"])
        exported_dcm = sorted(
            (bundle_dir / bundle_export.series_dir_name(sample)).glob("*.dcm"))
        exported_nii = nib.load(bundle["nifti"])
        check("bundle export produces complete DICOM + NIfTI delivery",
              bundle["cut_from"] == 25 and bundle["n_dicom"] == 25
              and len(exported_dcm) == 25
              and tuple(exported_nii.shape) == (cols, rows, 25)
              and Path(bundle["json"]).is_file()
              and Path(bundle["txt"]).is_file(),
              f"DICOM={len(exported_dcm)}, NIfTI={exported_nii.shape}")
        check("bundle export leaves no temporary DICOM swap directory",
              not (bundle_dir /
                   (bundle_export.series_dir_name(sample) + ".tmp")).exists()
              and not (bundle_dir /
                       (bundle_export.series_dir_name(sample)
                        + ".old")).exists())
    finally:
        tg.output_root = old_output_root
        viewer_core.output_root = old_viewer_output_root
        viewer_core._get_ds = old_get_ds
        viewer_core.CACHE_DIR = old_cache_dir
        viewer_core._CACHE.clear()
        viewer_core._PREV.clear()
        viewer_core.ORIG_SLICE_CACHE.clear()
        viewer_core._XY_FILES.clear()
        viewer_core._SLICE_SHAPES.clear()

finally:
    shutil.rmtree(WORK_ROOT, ignore_errors=True)

print("RESULT: ALL PASS" if not failures else f"RESULT: {len(failures)} FAIL")
sys.exit(1 if failures else 0)
