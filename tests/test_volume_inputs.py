"""Unified TIFF/NIfTI input, processing, viewer, and export regressions."""
from __future__ import annotations

import contextlib
import gzip
import io
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

if not all(os.environ.get(name) for name in
           ("CLEANCT_ENGINE", "CLEANCT_DATA", "CLEANCT_TEST_TMP_DIR",
            "CLEANCT_OUTPUT_ROOT")):
    raise SystemExit("Set isolated CLEANCT_ENGINE, CLEANCT_DATA, "
                     "CLEANCT_TEST_TMP_DIR, and CLEANCT_OUTPUT_ROOT first")

ROOT = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import nibabel as nib
import numpy as np
import tifffile
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

from core import bundle_export, custom_series as csx, viewer_core
from dialogs.load_dialog import LoadDialog
import tomograph as tg
import volume_io as vio
from volume_io import (VolumeInputError, inspect_source, load_volume,
                       read_source_slices)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'} {name}" +
          (f" [{detail}]" if detail else ""))
    if not condition:
        FAILURES.append(name)


def rejected(label: str, action, expected=VolumeInputError) -> bool:
    try:
        action()
    except expected:
        return True
    except Exception as exc:
        print(f"FAIL {label} [unexpected {type(exc).__name__}: {exc}]")
        FAILURES.append(label)
        return True
    return False


TMP = Path(os.environ["CLEANCT_TEST_TMP_DIR"])
TMP.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix="cleanct_volume_inputs_", dir=TMP))
qt_app = QApplication.instance() or QApplication([])
old_output_root = tg.output_root
old_viewer_output_root = viewer_core.output_root
old_cache_dir = viewer_core.CACHE_DIR

try:
    # Multipage TIFF stack with HU-like raw grayscale classes. It exercises
    # the adaptive thresholds without changing delivered source values.
    sample = "TIFF_SYNTHETIC"
    n, rows, cols = 36, 192, 192
    yy, xx = np.mgrid[:rows, :cols]
    wood_mask = (yy - rows // 2) ** 2 + (xx - cols // 2) ** 2 <= 60 ** 2
    rng = np.random.default_rng(2026)
    volume = np.zeros((n, rows, cols), dtype=np.uint16)
    for z in range(n):
        volume[z, wood_mask] = rng.integers(7900, 8101, size=int(wood_mask.sum()),
                                            dtype=np.uint16)
        if z >= 30:
            volume[z, wood_mask] = rng.integers(59000, 61001,
                                                size=int(wood_mask.sum()),
                                                dtype=np.uint16)
    tiff_path = WORK / "wood_platform_stack.tiff"
    tifffile.imwrite(tiff_path, volume, metadata={"axes": "ZYX"})
    info = inspect_source(tiff_path)
    check("multipage TIFF auto-detected as a 3-D stack",
          info["source_kind"] == "tiff" and info["shape_zyx"] == [n, rows, cols]
          and info["intensity_mode"] == "raw",
          f"shape={info['shape_zyx']}, intensity={info['intensity_mode']}")
    check("unknown TIFF spacing is marked assumed, not presented as measured",
          info["geometry_assumed"] is True)
    check("TIFF slice reader returns requested float32 slices",
          np.array_equal(read_source_slices(tiff_path, [0, 35], metadata=info)[0],
                         volume[0].astype(np.float32)))

    # Per-slice TIFF folders must use natural numeric ordering and the same
    # shape/intensity contract as a multipage TIFF stack.
    tiff_folder = WORK / "tiff_slice_folder"
    tiff_folder.mkdir()
    for z in range(n):
        tifffile.imwrite(tiff_folder / f"slice_{z + 1}.tif", volume[z])
    folder_info = inspect_source(tiff_folder)
    folder_planes = read_source_slices(tiff_folder, [0, 9, 35],
                                       metadata=folder_info)
    check("TIFF slice folder is ordered and read through the shared adapter",
          folder_info["source_kind"] == "tiff"
          and folder_info["shape_zyx"] == [n, rows, cols]
          and np.array_equal(folder_planes[9], volume[9].astype(np.float32)))

    # Exercise the real load dialog callbacks without opening native pickers.
    load_dialog = LoadDialog()
    chooser_calls = []
    def choose_tiff(_parent, title, start, file_filter):
        chooser_calls.append((title, file_filter))
        return str(tiff_path), "XCT volumes"
    with patch.object(QFileDialog, "getOpenFileName", side_effect=choose_tiff):
        load_dialog._browse_file()
    load_dialog.edit_specimen.setText("dialog_tiff")
    load_dialog._validate_and_accept()
    check("load dialog file picker and validation accept TIFF sources",
          load_dialog.result() == QDialog.DialogCode.Accepted
          and load_dialog.source_info.get("source_kind") == "tiff"
          and ".nii.gz" in chooser_calls[0][1]
          and ".tiff" in chooser_calls[0][1])
    folder_dialog = LoadDialog()
    with patch.object(QFileDialog, "getExistingDirectory",
                      return_value=str(tiff_folder)):
        folder_dialog._browse_folder()
    folder_dialog.edit_specimen.setText("dialog_tiff_folder")
    folder_dialog._validate_and_accept()
    check("load dialog folder picker and validation accept TIFF series",
          folder_dialog.result() == QDialog.DialogCode.Accepted
          and folder_dialog.source_info.get("source_kind") == "tiff")

    # Validation must surface a handled resource-limit result before processing
    # begins, rather than allowing the GUI to fail during sample decoding.
    original_memory_check = tg._check_load_memory
    def reject_memory(*_args, **_kwargs):
        raise MemoryError("synthetic RAM limit")
    tg._check_load_memory = reject_memory
    try:
        check("TIFF registration handles RAM preflight before decode",
              rejected("TIFF RAM preflight", lambda: csx.validate_input(tiff_path),
                       csx.LoadError))
    finally:
        tg._check_load_memory = original_memory_check

    # Registration keeps the input in place and records the detected adapter.
    entry = csx.register_series(tiff_path, sample, intensity="auto")
    ds = csx.as_dataset(sample)
    check("TIFF registration retains the source path and metadata",
          entry["source_kind"] == "tiff" and ds.source_kind == "tiff"
          and ds.source_path == tiff_path.resolve()
          and not entry["config_overrides"].get("save_dicom", True))

    # Generic readers call the same RAM preflight contract as DICOM and fill
    # the existing backend using bounded slice transfers.
    seen_memory = []
    loaded, loaded_meta = load_volume(
        tiff_path, tg.get_backend(preference="cpu", verbose=False),
        metadata=info,
        memory_check=lambda *args: seen_memory.append(args))
    check("TIFF loading uses one-slice RAM preflight and canonical z-y-x layout",
          loaded.shape == (n, rows, cols) and seen_memory == [(n, rows, cols, 1)]
          and loaded_meta["source_kind"] == "tiff")
    del loaded

    # Full process -> viewer -> atomic NIfTI bundle export, all isolated from
    # user data. The explicit Cut line keeps this synthetic scan deterministic.
    output_root = WORK / "pipeline_output"
    tg.output_root = lambda _dataset: output_root
    viewer_core.output_root = lambda _dataset: output_root
    viewer_core.CACHE_DIR = WORK / "viewer_cache"
    viewer_core._CACHE.clear()
    viewer_core._PREV.clear()
    viewer_core.ORIG_SLICE_CACHE.clear()
    viewer_core._XY_FILES.clear()
    viewer_core._SLICE_SHAPES.clear()
    cfg = tg.DEFAULTS.overridden({
        **ds.config_overrides,
        "platform_min_voxels": 5000,
        "platform_min_slices": 5,
        "roi_seed_min_area": 4000,
        "roi_min_area": 300,
        "roi_bbox_pad": 4,
        "cut_override": 25,
        "keep_from": 0,
        "save_nifti": True,
        "save_dicom": False,
        "save_qa_montage": False,
        "save_stripped_nii": True,
        "io_workers": 4,
    })
    with contextlib.redirect_stdout(io.StringIO()):
        report = tg.process_sample(
            sample, cfg, ds, False,
            tg.get_backend(preference="cpu", verbose=False), verbose=False)
    processed = output_root / sample
    disk_report = json.loads((processed / "report.json").read_text())
    check("TIFF processing writes the NIfTI ROI and source-faithful report",
          report["platform"]["cut_from"] == 25
          and report["meta"]["intensity_unit"] == "stored grayscale values"
          and report["config"]["intensity_auto_calibrated"]
          and (processed / "wood_roi.nii").is_file()
          and (processed / "stripped.nii").is_file()
          and not (processed / "wood_roi_dicom").exists())

    payload = viewer_core.build_payload("custom", sample, use_disk=False)
    check("viewer displays processed TIFF source slices and retains source units",
          not payload.get("unprocessed") and payload.get("frames")
          and payload["report"].get("source_kind") == "tiff"
          and payload["report"].get("intensity_unit") == "stored grayscale values",
          f"frames={len(payload.get('frames', []))}")

    bundle = bundle_export.export_bundle(
        "custom", sample, tiff_path, disk_report,
        processed / "stripped.nii", WORK / "bundles",
        source_override=str(tiff_path), export_format="nifti",
        source_kind="tiff", source_path=tiff_path,
        source_metadata=ds.source_metadata)
    bundle_nii = nib.load(bundle["nifti"])
    stripped_img = nib.load(processed / "stripped.nii")
    check("NIfTI bundle preserves source values, affine, and selected z-range",
          bundle_nii.shape == (cols, rows, 25)
          and np.allclose(bundle_nii.affine, stripped_img.affine, atol=1e-5)
          and np.array_equal(np.asarray(bundle_nii.dataobj[:, :, 12]),
                             np.asarray(stripped_img.dataobj[:, :, 12]))
          and bundle["n_dicom"] == 0
          and Path(bundle["json"]).is_file() and Path(bundle["txt"]).is_file())

    # Full NIfTI input path: registration -> processing -> viewer -> bundle.
    nifti_sample = "NIFTI_SYNTHETIC"
    nifti_source = WORK / "nifti_source.nii"
    nifti_affine = np.diag([0.0662, 0.0662, 0.5, 1.0])
    source_img = nib.Nifti1Image(volume.transpose(2, 1, 0), nifti_affine)
    source_img.header.set_xyzt_units("mm")
    nib.save(source_img, nifti_source)
    nifti_entry = csx.register_series(nifti_source, nifti_sample)
    nifti_ds = csx.as_dataset(nifti_sample)
    nifti_cfg = tg.DEFAULTS.overridden({
        **nifti_ds.config_overrides,
        "platform_min_voxels": 5000,
        "platform_min_slices": 5,
        "roi_seed_min_area": 4000,
        "roi_min_area": 300,
        "roi_bbox_pad": 4,
        "cut_override": 25,
        "keep_from": 0,
        "save_nifti": True,
        "save_dicom": False,
        "save_qa_montage": False,
        "save_stripped_nii": True,
        "io_workers": 4,
    })
    with contextlib.redirect_stdout(io.StringIO()):
        nifti_report = tg.process_sample(
            nifti_sample, nifti_cfg, nifti_ds, False,
            tg.get_backend(preference="cpu", verbose=False), verbose=False)
    nifti_processed = output_root / nifti_sample
    nifti_disk_report = json.loads(
        (nifti_processed / "report.json").read_text())
    nifti_payload = viewer_core.build_payload(
        "custom", nifti_sample, use_disk=False)
    nifti_bundle = bundle_export.export_bundle(
        "custom", nifti_sample, nifti_source, nifti_disk_report,
        nifti_processed / "stripped.nii", WORK / "nifti_bundles",
        source_override=str(nifti_source), export_format="nifti",
        source_kind="nifti", source_path=nifti_source,
        source_metadata=nifti_entry["source_metadata"])
    nifti_delivered = nib.load(nifti_bundle["nifti"])
    nifti_processed_img = nib.load(nifti_processed / "stripped.nii")
    check("NIfTI registration, processing, viewer, and export complete end to end",
          nifti_report["platform"]["cut_from"] == 25
          and nifti_entry["source_kind"] == "nifti"
          and nifti_payload.get("frames")
          and nifti_delivered.shape == (cols, rows, 25)
          and np.allclose(nifti_delivered.affine,
                          nifti_processed_img.affine, atol=1e-5)
          and np.array_equal(np.asarray(nifti_delivered.dataobj[:, :, 12]),
                             np.asarray(nifti_processed_img.dataobj[:, :, 12]))
          and not (Path(nifti_bundle["bundle_dir"])
                   / f"{nifti_sample}_rem_dcm").exists()
          and nifti_disk_report["meta"]["intensity_unit"]
          == "stored NIfTI values")
    check("non-DICOM source refuses fabricated DICOM exports",
          rejected("DICOM export rejected for TIFF", lambda: bundle_export.export_bundle(
              "custom", sample, tiff_path, disk_report,
              processed / "stripped.nii", WORK / "bad_bundle",
              source_kind="tiff", source_path=tiff_path,
              source_metadata=ds.source_metadata, export_format="both"),
              bundle_export.BundleError))

    # NIfTI orientation and scl_slope/inter are applied lazily and consistently
    # with nibabel's closest-canonical representation.
    xyz_shape = (32, 24, 16)
    raw_xyz = (np.arange(np.prod(xyz_shape), dtype=np.int16)
               .reshape(xyz_shape) % 3000 - 1000).astype(np.int16)
    affine = np.diag([-0.025, 0.03, 0.5, 1.0])
    affine[0, 3] = 0.775  # keep the left-facing axis origin in RAS coordinates
    nii_path = WORK / "oriented_scaled.nii"
    img = nib.Nifti1Image(raw_xyz, affine)
    img.header.set_xyzt_units("mm")
    img.header.set_slope_inter(0.5, -200.0)
    nib.save(img, nii_path)
    ni = inspect_source(nii_path)
    loaded_nii, loaded_nii_meta = load_volume(
        nii_path, tg.get_backend(preference="cpu", verbose=False), metadata=ni)
    canonical = nib.as_closest_canonical(nib.load(nii_path))
    expected_zyx = np.asarray(canonical.dataobj, dtype=np.float32).transpose(2, 1, 0)
    check("NIfTI orientation, scaling, and physical affine are normalized correctly",
          ni["intensity_mode"] == "hu"
          and loaded_nii.shape == expected_zyx.shape
          and np.allclose(loaded_nii, expected_zyx)
          and np.allclose(loaded_nii_meta["affine_ras_xyz"], canonical.affine),
          f"shape={loaded_nii.shape}, unit={ni['intensity_unit']}")
    del loaded_nii

    nii_gz = WORK / "oriented_scaled.nii.gz"
    with open(nii_path, "rb") as source, gzip.open(nii_gz, "wb") as target:
        shutil.copyfileobj(source, target)
    gz_info = inspect_source(nii_gz)
    gz_slices = read_source_slices(nii_gz, [0, 8, 15], metadata=gz_info)
    check("compressed NIfTI validates and serves random slices from one bounded decode",
          gz_info["source_kind"] == "nifti" and len(gz_slices) == 3
          and all(a.dtype == np.float32 for a in gz_slices.values()))
    legacy_gz_info = dict(gz_info)
    legacy_gz_info.pop("nifti_expected_bytes", None)
    check("older registered NIfTI metadata remains readable",
          bool(read_source_slices(nii_gz, [3], metadata=legacy_gz_info)))
    check("compressed NIfTI cache is isolated to this app process",
          bool(vio._NIFTI_CACHE)
          and all(path.parent.name == str(os.getpid())
                  for path in vio._NIFTI_CACHE.values()))
    stale_cache_root = TMP / "cleanct-volume-cache"
    stale_cache = stale_cache_root / "2000000000"
    stale_cache.mkdir(parents=True, exist_ok=True)
    (stale_cache / "orphan.nii").write_bytes(b"stale")
    os.utime(stale_cache, (1, 1))
    vio._cleanup_stale_nifti_cache_dirs(stale_cache_root)
    check("abandoned compressed-volume cache is reclaimed after process exit",
          not stale_cache.exists())
    oversized_gz = WORK / "oversized.nii.gz"
    with gzip.open(oversized_gz, "wb") as dst:
        dst.write(nii_path.read_bytes() + b"x")
    check("compressed NIfTI expansion beyond declared dimensions is rejected",
          rejected("oversized NIfTI.GZ rejection",
                   lambda: inspect_source(oversized_gz)))

    # Do not silently combine old DICOM output with a newly selected
    # non-DICOM input that happens to reuse the same specimen ID.
    mixed_bundle_root = WORK / "mixed_source_bundles"
    prior_dicom = mixed_bundle_root / sample / f"{sample}_rem_dcm"
    prior_dicom.mkdir(parents=True)
    prior_file = prior_dicom / f"{sample}_rem_0001.dcm"
    prior_file.write_bytes(b"preserve existing output")
    check("cross-source export refuses to mix old DICOM with TIFF/NIfTI",
          rejected("mixed-source bundle rejection",
                   lambda: bundle_export.export_bundle(
                       "custom", sample, tiff_path, disk_report,
                       processed / "stripped.nii", mixed_bundle_root,
                       source_kind="tiff", source_path=tiff_path,
                       source_metadata=ds.source_metadata,
                       export_format="nifti"), bundle_export.BundleError)
          and prior_file.read_bytes() == b"preserve existing output")

    # File/stack edge cases: empty data, mismatched dimensions, truncation,
    # and too-few slices are rejected with a handled validation error.
    empty_tif = WORK / "empty.tif"
    empty_tif.write_bytes(b"")
    check("empty TIFF is rejected cleanly",
          rejected("empty TIFF rejection", lambda: inspect_source(empty_tif)))
    mismatch = WORK / "mismatched_tiff"
    mismatch.mkdir()
    tifffile.imwrite(mismatch / "slice_1.tif", np.zeros((20, 24), np.uint16))
    tifffile.imwrite(mismatch / "slice_2.tif", np.zeros((21, 24), np.uint16))
    check("TIFF slice dimension mismatch is rejected before processing",
          rejected("mismatched TIFF rejection", lambda: inspect_source(mismatch)))
    small_stack = WORK / "too_few.tif"
    tifffile.imwrite(small_stack, np.zeros((4, 16, 16), np.int16),
                     metadata={"axes": "ZYX"})
    check("registration rejects TIFF stacks below processable depth",
          rejected("short TIFF registration rejection",
                   lambda: csx.validate_input(small_stack), csx.LoadError))
    truncated = WORK / "truncated.nii"
    shutil.copy2(nii_path, truncated)
    truncated.write_bytes(truncated.read_bytes()[:-32])
    check("truncated NIfTI data is rejected during metadata preflight",
          rejected("truncated NIfTI rejection", lambda: inspect_source(truncated)))
    broken_gz = WORK / "broken.nii.gz"
    broken_gz.write_bytes(nii_gz.read_bytes()[:-64])
    check("truncated compressed NIfTI is rejected cleanly",
          rejected("truncated NIfTI.GZ rejection", lambda: inspect_source(broken_gz)))
finally:
    tg.output_root = old_output_root
    viewer_core.output_root = old_viewer_output_root
    viewer_core.CACHE_DIR = old_cache_dir
    viewer_core._CACHE.clear()
    viewer_core._PREV.clear()
    viewer_core.ORIG_SLICE_CACHE.clear()
    viewer_core._XY_FILES.clear()
    viewer_core._SLICE_SHAPES.clear()
    shutil.rmtree(WORK, ignore_errors=True)

if FAILURES:
    raise SystemExit(f"{len(FAILURES)} unified-volume check(s) failed: "
                     + ", ".join(FAILURES))
