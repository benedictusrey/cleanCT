"""Results axial frames: clean outlines, and a payload cache that rebuilds them.

1. The metal and wood outlines follow the true edge. The old renderer
   coarsened the mask in blocks, which pushed each outline out by up to a
   block and drew stair-steps and lace.
2. The payload cache version moves on whenever the payload's contents change.
   Version 21 payloads carry no ``zb.metal_top`` and hold the old frames, so
   they must not be reused.
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
APP = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "src"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from core import viewer_core  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# a true disc of radius R with 30% speckle in a 4 px band at its edge
N, R, C = 460, 120.0, 230.0
yy, xx = np.mgrid[0:N, 0:N]
radius = np.hypot(yy - C, xx - C)
rng = np.random.default_rng(0)
mask = radius < R
band = np.abs(radius - R) < 4
mask = np.where(band & (rng.random((N, N)) < 0.3), ~mask, mask)

img = Image.new("RGB", (N, N), (0, 0, 0))
viewer_core._draw_contours(img, mask, 1.0, (255, 70, 60), 2, 0)
drawn = np.asarray(img).astype(int)
ink = (drawn[..., 0] > 200) & (drawn[..., 1] < 120)
ys, xs = np.nonzero(ink)
dev = np.abs(np.hypot(ys - C, xs - C) - R)
check("outline is drawn", ink.sum() > 500, f"pixels={int(ink.sum())}")
# the speckle band is 4 px deep, so ~2 px is the honest floor; the old
# block-coarsened drawer measured 6-13 px
check("outline is within 2.5 px of the true edge (95th percentile)",
      dev.size > 0 and float(np.percentile(dev, 95)) <= 2.5,
      f"p95 {float(np.percentile(dev, 95)) if dev.size else -1:.2f} px")
check("no stray spike further than 3.5 px from the true edge",
      dev.size > 0 and float(dev.max()) <= 3.5,
      f"max {float(dev.max()) if dev.size else -1:.2f} px")

check("payload cache version moved past v21 (old payloads lack zb.metal_top)",
      viewer_core.CACHE_VERSION >= 22, f"CACHE_VERSION={viewer_core.CACHE_VERSION}")

if failures:
    print("FAILURES: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL PASS")
