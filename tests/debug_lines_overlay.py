"""Render a debug overlay of the four cut lines on a real CT slice.

Draws the detection's wood-ROI box (Left/Right/Y bounds) plus the
Keep/Cut slice annotations on an axial source slice, so the lateral
line fit can be judged visually.

Output:  debug_roi_fix/<dataset>_<sample>_<tag>.png
         debug_roi_fix/<dataset>_<sample>_<tag>.json   (raw values)

Usage:  python debug_lines_overlay.py [dataset sample tag]
        (defaults: custom 1-17_OD overlay)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP.parent / "metal_remover"))

import numpy as np
from PIL import Image, ImageDraw

from core import viewer_core as vc

vc.ensure_engine_on_path()

OUT_DIR = APP / "debug_roi_fix"


def overlay(dataset: str, sample: str, tag: str = "overlay",
            source_json: str | None = None) -> Path | None:
    if source_json:
        meta = json.loads(Path(source_json).read_text(encoding="utf-8"))
        H, W = int(meta["H"]), int(meta["W"])
        y0, y1 = int(meta["y0"]), int(meta["y1"])
        x0, x1 = int(meta["x0"]), int(meta["x1"])
        zb = meta.get("zb") or {}
        voxel = meta.get("voxel_um")
    else:
        p = vc.build_payload(dataset, sample)
        b = p.get("bounds") or {}
        if not b or not b.get("H") or not b.get("W"):
            print(f"no bounds for {dataset}/{sample}")
            return None
        H, W = int(b["H"]), int(b["W"])
        margins = b.get("margins") or {}
        zb = b.get("zb") or {}
        # margins are edge distances [lo, hi]: box sides are lo and W-1-hi
        y0 = int(margins["y"][0])
        y1 = H - 1 - int(margins["y"][1])
        x0 = int(margins["x"][0])
        x1 = W - 1 - int(margins["x"][1])   # (0AF fix: was drawn at the margin)
        voxel = b.get("voxel_um")

    mid = (int(zb.get("wood_top") or 0) + int(zb.get("wood_bottom") or H)) // 2
    mid = max(0, min(H - 1, mid))
    sl = vc._source_slices(ds := vc._get_ds(dataset, sample), sample, [mid]).get(mid)
    if sl is None:
        print("no source slice")
        return None

    # deterministic display window from the slice's own HU distribution
    # (report windows vary between legacy/fresh payloads; percentiles keep
    # before/after renderings comparable)
    v = np.asarray(sl, np.float32)
    p1, p99 = (float(np.percentile(v, 1.0)), float(np.percentile(v, 99.0)))
    pad = max(1.0, 0.05 * (p99 - p1))
    lo, hi = p1 - pad, p99 + pad
    span = max(1.0, hi - lo)
    img = np.clip((v - lo) / span * 255.0, 0, 255)
    rgb = np.stack([img] * 3, axis=-1).astype(np.uint8)

    im = Image.fromarray(rgb, "RGB")
    draw = ImageDraw.Draw(im)
    amber = (242, 178, 60)
    red = (255, 70, 60)
    green = (55, 214, 122)
    blue = (79, 140, 255)
    # Left/Right (X) lines
    draw.line([(x0, 0), (x0, H - 1)], fill=blue, width=3)
    draw.line([(x1, 0), (x1, H - 1)], fill=blue, width=3)
    # Y bounds (top/bottom of the lateral box)
    draw.line([(0, y0), (W - 1, y0)], fill=blue, width=3)
    draw.line([(0, y1), (W - 1, y1)], fill=blue, width=3)
    keep, cut = zb.get("keep"), zb.get("cut")
    text = (f"{dataset}/{sample}  z={mid}  voxel={voxel} um  [{tag}]\n"
            f"wood_top={zb.get('wood_top')} wood_bottom={zb.get('wood_bottom')}"
            f"  keep={keep} cut={cut}\n"
            f"Y box {y0}..{y1} ({y0/H:.1%}..{y1/H:.1%})   "
            f"X box {x0}..{x1} ({x0/W:.1%}..{x1/W:.1%})")
    ty = 8
    for line in text.splitlines():
        draw.text((10, ty), line, fill=amber)
        ty += 16
    # mark the keep/cut slice positions along the right edge (z axis)
    for value, color, label in ((keep, green, "keep"), (cut, red, "cut")):
        if value is None:
            continue
        v = max(0, min(H - 1, int(value)))
        draw.line([(W - 60, v), (W - 1, v)], fill=color, width=3)
        draw.text((W - 200, max(2, v - 18)), f"{label}={value}", fill=color)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{dataset}_{sample}_{tag}.png"
    im.save(str(out))
    meta = {"dataset": dataset, "sample": sample, "tag": tag,
            "y0": y0, "y1": y1, "x0": x0, "x1": x1, "H": H, "W": W,
            "zb": zb, "voxel_um": voxel}
    (OUT_DIR / f"{dataset}_{sample}_{tag}.json").write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(f"overlay saved: {out}   y0={y0} y1={y1} x0={x0} x1={x1} "
          f"zb_top={zb.get('wood_top')} zb_bottom={zb.get('wood_bottom')} "
          f"keep={keep} cut={cut}")
    return out


if __name__ == "__main__":
    ds, sp = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else \
        ("custom", "1-17_OD")
    tg = sys.argv[3] if len(sys.argv) > 3 else "overlay"
    src = sys.argv[4] if len(sys.argv) > 4 else None
    overlay(ds, sp, tg, src)
