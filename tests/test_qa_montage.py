"""The QA montages are drawn with Pillow and never load matplotlib.

matplotlib scans every system font on its first use. On the macOS arm64 runner
that scan died with a bus error inside the pipeline's worker thread, so the
quick-look pictures are drawn with Pillow and its bundled font.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from core.paths import ensure_engine_on_path  # noqa: E402

ensure_engine_on_path()
import tomograph as tg  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""),
          flush=True)
    if not ok:
        failures.append(name)


WINDOW = (-1200.0, 300.0)
edge = tg._qa_rgb(np.array([[-1200.0, 300.0, np.nan]]), WINDOW)
check("the low end of the window is black", tuple(edge[0, 0]) == (0, 0, 0), str(tuple(edge[0, 0])))
check("the high end of the window is white", tuple(edge[0, 1]) == (255, 255, 255),
      str(tuple(edge[0, 1])))
check("blank (NaN) pixels are grey", tuple(edge[0, 2]) == (64, 64, 64), str(tuple(edge[0, 2])))

vol = np.full((4, 40, 60), -1200.0, np.float32)
vol[:, 10:30, 20:40] = 300.0          # a white block on every slice
stripped = vol.copy()
stripped[2] = np.nan                  # slice 2 is blank after the cut

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp)
    tg.save_qa_montage(vol, stripped, 2, "qa_check", out, [0, 2], window=WINDOW)
    png = out / "qa_check_qa_removal.png"
    check("the removal montage is written", png.is_file())
    pic = np.asarray(Image.open(png).convert("RGB"))
    check("the removal montage shows the white block", bool(np.any(np.all(pic == 255, axis=2))))
    check("the removal montage shows blank slices in grey",
          bool(np.any(np.all(pic == 64, axis=2))))

    roi = vol[0:3, 5:35, 10:50].copy()
    tg.save_roi_qa(vol, roi, (0, 3, 5, 35, 10, 50), "qa_check", out, [0, 2], window=WINDOW)
    roi_png = out / "qa_check_qa_roi.png"
    check("the ROI montage is written", roi_png.is_file())
    pic = np.asarray(Image.open(roi_png).convert("RGB"))
    check("the ROI box is drawn in cyan", bool(np.any(np.all(pic == (0, 229, 255), axis=2))))

check("the QA pictures do not load matplotlib", "matplotlib" not in sys.modules)

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"), flush=True)
sys.exit(1 if failures else 0)
