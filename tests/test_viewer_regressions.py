from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

if (not os.environ.get("CLEANCT_ENGINE") or not os.environ.get("CLEANCT_DATA")
        or not os.environ.get("CLEANCT_TEST_TMP_DIR")
        or not os.environ.get("CLEANCT_OUTPUT_ROOT")):
    raise SystemExit("Set isolated CLEANCT_ENGINE, CLEANCT_DATA, "
                     "CLEANCT_TEST_TMP_DIR, and CLEANCT_OUTPUT_ROOT paths first")

APP = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
TMP_ROOT = Path(os.environ.get("CLEANCT_TEST_TMP_DIR", Path(__file__).resolve().parent))
APP.mkdir(parents=True, exist_ok=True)
TMP_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "src"))

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from core import custom_series as csx
from core import viewer_core as vc
import tomograph as tg

# All derived caches stay in the disposable test directory, even when the
# project is a writable development checkout.
vc.CACHE_DIR = TMP_ROOT / "viewer_cache"
vc.CACHE_DIR.mkdir(parents=True, exist_ok=True)


failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> int:
    # the worker count follows the machine (8..16 cores); normal slices keep all of it
    check("normal slices retain full I/O concurrency",
          vc._source_batch_size_for_shape(1200, 1200) == vc._IO_WORKERS, str(vc._IO_WORKERS))
    check("6000px slices reduce concurrency",
          1 <= vc._source_batch_size_for_shape(6000, 6000) < 16)
    check("very large slices use one reader",
          vc._source_batch_size_for_shape(20000, 20000) == 1)

    raw = np.array([[-32768, -1000, 0, 32767]], dtype=np.int16)
    expected = raw.astype(np.float32) * 1.23456789 - 1024.1234567
    actual = vc._rescale_pixels(raw, 1.23456789, -1024.1234567)
    check("in-place HU rescale is byte-equivalent",
          np.array_equal(actual, expected) and np.array_equal(raw, [[-32768, -1000, 0, 32767]]))

    tmp = Path(tempfile.mkdtemp(prefix="cleanct_viewer_reg_", dir=TMP_ROOT))
    name = f"rect_reg_{os.getpid()}"
    series = tmp / "XY"
    series.mkdir()
    study_uid, series_uid = generate_uid(), generate_uid()
    rows, columns, n_slices = 64, 80, 24
    rr, cc = np.mgrid[:rows, :columns]
    wood = (rr - rows // 2) ** 2 + (cc - columns // 2) ** 2 <= 18 ** 2
    try:
        for i in range(n_slices):
            pixels = np.full((rows, columns), 24, np.int16)  # -1000 HU after intercept
            pixels[wood] = 424                                  # -600 HU
            if i >= 20:
                pixels[wood] = 4095                              # metal slab
            d = Dataset()
            d.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
            d.SOPInstanceUID = generate_uid()
            d.StudyInstanceUID = study_uid
            d.SeriesInstanceUID = series_uid
            d.Modality = "CT"
            d.Rows, d.Columns = rows, columns
            d.SamplesPerPixel = 1
            d.BitsAllocated = 16
            d.BitsStored = 16
            d.HighBit = 15
            d.PixelRepresentation = 1
            d.PhotometricInterpretation = "MONOCHROME2"
            d.PixelSpacing = [0.033, 0.041]
            d.SliceThickness = 0.5
            d.ImagePositionPatient = [0, 0, float(i)]
            d.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            d.RescaleSlope, d.RescaleIntercept = 1.0, -1024.0
            d.PixelData = pixels.tobytes()
            d.file_meta = FileMetaDataset()
            d.file_meta.MediaStorageSOPClassUID = d.SOPClassUID
            d.file_meta.MediaStorageSOPInstanceUID = d.SOPInstanceUID
            d.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            # Deliberately reverse filename order relative to physical slice
            # order: the viewer must agree with the pipeline's DICOM geometry.
            pydicom.dcmwrite(series / f"s{n_slices - i:04d}.dcm", d,
                             enforce_file_format=True)

        csx.register_series(series, name)
        ds = vc._get_ds("custom", name)
        output_override = Path(os.environ["CLEANCT_OUTPUT_ROOT"])
        check("custom processing output uses the selected per-user root",
              vc.output_root(ds) == output_override / "custom",
              str(vc.output_root(ds)))
        os.environ.pop("CLEANCT_OUTPUT_ROOT", None)
        try:
            legacy_root = vc.output_root(ds)
        finally:
            os.environ["CLEANCT_OUTPUT_ROOT"] = str(output_override)
        # without CLEANCT_OUTPUT_ROOT: the build PC's folder when it exists, else data/ in the checkout
        fallback = (tg.OUT_ROOT if tg.OUT_ROOT.is_dir()
                    else Path(tg.__file__).resolve().parents[1] / "data" / "pipeline_output")
        check("development output fallback follows the build-folder rule",
              legacy_root == fallback / "custom", str(legacy_root))
        sag, cor, sagc, corc = vc._orig_ortho_columns(
            ds, name, include_midlines=True)
        old_sag, old_cor = vc._orig_ortho_lines(ds, name)
        check("rectangular ortho profile shapes",
              sag.shape == (n_slices, rows) and cor.shape == (n_slices, columns)
              and sagc.shape == (n_slices, 5, rows)
              and corc.shape == (n_slices, 5, columns),
              f"sag={sag.shape}, cor={cor.shape}, sag_cols={sagc.shape}, cor_cols={corc.shape}")
        check("combined center lines equal legacy mid-lines",
              np.array_equal(sag, old_sag) and np.array_equal(cor, old_cor))
        check("sagittal stack contains exact center profile",
              np.array_equal(sagc[0, sagc.shape[1] // 2], old_sag[0]))
        check("coronal stack contains exact center profile",
              np.array_equal(corc[0, corc.shape[1] // 2], old_cor[0]))

        uncached = vc._source_slices(ds, name, [0, 23], cache=False)
        check("uncached slice reads return requested HU arrays",
              set(uncached) == {0, 23}
              and uncached[0].shape == (rows, columns)
              and float(uncached[0][0, 0]) == -1000.0
              and float(uncached[0][32, 40]) == -600.0
              and float(uncached[23][32, 40]) == 3071.0,
              "physical z order survives reversed filenames")
        check("uncached reads do not populate global slice cache",
              not any(k.startswith(f"custom/{name}") for k in vc.ORIG_SLICE_CACHE))
        metal = vc._metal_points(ds, name, 20, n_slices, 1, 1000.0, 10000)
        check("metal point sampling returns points without caching full slices",
              len(metal) > 0
              and not any(k.startswith(f"custom/{name}") for k in vc.ORIG_SLICE_CACHE))

        cached = vc._source_slices(ds, name, [0, 23])
        check("bounded slice cache keeps requested entries",
              set(cached) == {0, 23}
              and any(k.startswith(f"custom/{name}") for k in vc.ORIG_SLICE_CACHE))

        sdir = vc.output_root(ds) / name
        a = vc._ortho_columns_cached(ds, name, sdir)
        b = vc._ortho_columns_cached(ds, name, sdir)
        check("versioned orthogonal disk cache round-trips",
              all(np.array_equal(x, y) for x, y in zip(a, b))
              and a[2] is not None and a[3] is not None)

        old_budget = vc._PREV_MAX_BYTES
        try:
            vc._PREV.clear()
            vc._PREV_MAX_BYTES = 64
            vc._store_prev("too-large", {"sag": np.zeros(32, np.float32)})
            vc._store_prev("a", {"sag": np.zeros(8, np.float32)})
            vc._store_prev("b", {"sag": np.zeros(8, np.float32)})
            check("preview cache enforces aggregate byte budget",
                  "too-large" not in vc._PREV
                  and sum(vc._preview_array_bytes(v) for v in vc._PREV.values()) <= 64)
        finally:
            vc._PREV_MAX_BYTES = old_budget
            vc._PREV.clear()

        preview = vc.get_preview("custom", name, plane="axial", z=23, width=160)
        check("rectangular axial preview renders",
              bool(preview.get("png")) and preview.get("n_slices") == n_slices)
    except Exception as exc:
        check("rectangular custom-series pipeline", False,
              f"{type(exc).__name__}: {exc}")
    finally:
        vc.ORIG_SLICE_CACHE.clear()
        vc._PREV.clear()
        try:
            csx.remove_specimen(name)
        except Exception:
            pass
        out_root = vc.output_root(vc._get_ds("custom", name))
        shutil.rmtree(out_root / name, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"RESULT: {len(failures)} failed" if failures else "RESULT: ALL PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
