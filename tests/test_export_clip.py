"""The DICOM export keeps only the wood between the Wood top, Metal top and the L/R lines.

Z is clipped by the Keep and Cut lines (the export already takes the kept slices
only).  The two lateral pairs clip each kept slice: X (columns) by the vertical
L/R lines of the axial and coronal views, and Y (rows) by the L/R lines of the
sagittal view.  The box is stored per registered specimen when it is applied,
and the origin moves to the first kept row and column.

1. ``bundle_export.lateral_range``: fractions -> pixels, or None for the whole axis.
2. ``bundle_export._crop_slice``: pixels, size and origin of a cropped slice.
3. ``custom_series.set_specimen_lateral`` / ``lateral_box``: the box persists.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if (not os.environ.get("CLEANCT_ENGINE") or not os.environ.get("CLEANCT_DATA")
        or not os.environ.get("CLEANCT_TEST_TMP_DIR")):
    raise SystemExit("Set isolated CLEANCT_ENGINE, CLEANCT_DATA, and "
                     "CLEANCT_TEST_TMP_DIR paths first")
TEST_TMP = Path(os.environ["CLEANCT_TEST_TMP_DIR"])
TEST_TMP.mkdir(parents=True, exist_ok=True)
APP = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "src"))

import numpy as np  # noqa: E402
from pydicom.dataset import FileDataset, FileMetaDataset  # noqa: E402
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid  # noqa: E402

from core import bundle_export as be  # noqa: E402
from core import custom_series as csx  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# 1. fractions -> pixels
check("the whole axis is no crop", be.lateral_range(None, 449) is None
      and be.lateral_range((0.0, 1.0), 449) is None)
check("L 14% and R 80% map to pixels 63..358",
      be.lateral_range((0.14, 0.80), 449) == (63, 359),
      str(be.lateral_range((0.14, 0.80), 449)))
check("a degenerate pair keeps one pixel",
      be.lateral_range((0.5, 0.5), 449) == (224, 225),
      str(be.lateral_range((0.5, 0.5), 449)))


# 2. the crop itself
def slice_ds(rows: int = 12, cols: int = 20):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    ds = FileDataset("slice.dcm", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.Rows, ds.Columns = rows, cols
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
    ds.PixelRepresentation, ds.SamplesPerPixel = 1, 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelSpacing = [0.5, 0.25]          # [rows, columns] spacing in mm
    ds.ImagePositionPatient = [10.0, 20.0, 5.0]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    arr = (np.arange(rows * cols).reshape(rows, cols) - 100).astype(np.int16)
    ds.PixelData = arr.tobytes()
    return ds, arr


ds, arr = slice_ds()
be._crop_slice(ds, 2, 9, 5, 15)
check("the cropped slice keeps rows 2..8 and columns 5..14",
      ds.Rows == 7 and ds.Columns == 10, f"rows={ds.Rows} cols={ds.Columns}")
check("the cropped pixels are the source box", np.array_equal(ds.pixel_array, arr[2:9, 5:15]))
origin = [float(v) for v in ds.ImagePositionPatient]
# column 5 is 5 * 0.25 mm along +x; row 2 is 2 * 0.5 mm along +y (the column direction)
check("the origin moves to the first kept row and column",
      np.allclose(origin, [10.0 + 5 * 0.25, 20.0 + 2 * 0.5, 5.0]), str(origin))

# 3. the box persists per registered specimen
import capture_screens as cs  # noqa: E402

src = TEST_TMP / "clip_src"
cs.write_wood_metal_series(src / "XY", n=14, rows=32, cols=32, um=66.0)
name = "clip_spec"
if name not in csx.registered_specimens():
    csx.register_series(src, name)
check("the lateral box starts unset", csx.lateral_box(name) is None)
box = {"x": (0.2, 0.8), "y": (0.1, 0.9)}
csx.set_specimen_lateral(name, box)
check("the lateral box persists", csx.lateral_box(name) == box, str(csx.lateral_box(name)))
csx.set_specimen_lateral(name, None)
check("the lateral box clears", csx.lateral_box(name) is None)

# 4. with nothing applied, the export crops to the detected L/R pairs (the lines on screen)
from core import auto_snap  # noqa: E402

bounds = {"zb": {"cut": 500, "keep": 90, "wood_top": 90}, "x0": 40, "x1": 599,
          "y0": 60, "y1": 599, "W": 648, "H": 648}
pairs = auto_snap.lateral_pairs(bounds)
check("the detected pairs are the export box when nothing was applied",
      pairs is not None and np.allclose(pairs["x"], (40 / 648, 600 / 648))
      and np.allclose(pairs["y"], (60 / 648, 600 / 648)), str(pairs))
check("no detected pairs means no crop", auto_snap.lateral_pairs(None) is None)

if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
