"""Render detection vs auto-snapped cut lines on a real CT slice (audit 0AG).

For each specimen:
* dashed rectangle = the FROZEN detection envelope (wood_bounds);
* solid rectangle  = what Auto Snap to Detection copies onto the cut lines
  (core.auto_snap.detected_lines - the pure copy layer);
* text = snapped keep/cut + keep source (air top vs wood-top fallback).

Output: debug_snap/<dataset>_<sample>_snap.png (and .json)

Usage:  python debug_snap_overlay.py [dataset sample]
        (defaults to the three reference Kyodai specimens)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP / "engine"))

import numpy as np
from PIL import Image, ImageDraw

from core import viewer_core as vc
from core import auto_snap

vc.ensure_engine_on_path()

OUT_DIR = APP / "debug_snap"
SPECS = [("24um", "1-1"), ("24um", "1-15"), ("66um", "1-1")]


def _dashed_line(draw, p0, p1, fill, width=3, dash=18, gap=12):
    (x0, y0), (x1, y1) = p0, p1
    length = float(np.hypot(x1 - x0, y1 - y0))
    if length <= 0:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    pos = 0.0
    while pos < length:
        end = min(length, pos + dash)
        draw.line([(x0 + ux * pos, y0 + uy * pos),
                   (x0 + ux * end, y0 + uy * end)], fill=fill, width=width)
        pos += dash + gap


def _dashed_rect(draw, box, fill, width=3):
    x0, y0, x1, y1 = box
    _dashed_line(draw, (x0, y0), (x1, y0), fill, width)
    _dashed_line(draw, (x1, y0), (x1, y1), fill, width)
    _dashed_line(draw, (x1, y1), (x0, y1), fill, width)
    _dashed_line(draw, (x0, y1), (x0, y0), fill, width)


def overlay(dataset: str, sample: str) -> Path | None:
    p = vc.build_payload(dataset, sample)
    b = p.get("bounds") or {}
    if not b or not b.get("H") or not b.get("W"):
        print(f"no bounds for {dataset}/{sample}")
        return None
    H, W = int(b["H"]), int(b["W"])
    zb = b.get("zb") or {}
    tg = auto_snap.detected_lines(b)

    mid = (int(zb.get("wood_top") or 0) + int(zb.get("wood_bottom") or H)) // 2
    mid = max(0, min(H - 1, mid))
    sl = vc._source_slices(ds := vc._get_ds(dataset, sample), sample,
                           [mid]).get(mid)
    if sl is None:
        print("no source slice")
        return None

    v = np.asarray(sl, np.float32)
    p1, p99 = (float(np.percentile(v, 1.0)), float(np.percentile(v, 99.0)))
    pad = max(1.0, 0.05 * (p99 - p1))
    lo, hi = p1 - pad, p99 + pad
    span = max(1.0, hi - lo)
    rgb = np.stack([np.clip((v - lo) / span * 255.0, 0, 255)] * 3,
                   axis=-1).astype(np.uint8)

    im = Image.fromarray(rgb, "RGB")
    draw = ImageDraw.Draw(im)
    amber = (242, 178, 60)
    cyan = (90, 200, 255)
    green = (55, 214, 122)
    red = (255, 70, 60)

    # dashed = frozen detection envelope
    _dashed_rect(draw, (int(b["x0"]), int(b["y0"]), int(b["x1"]), int(b["y1"])),
                 cyan, 3)
    # solid = auto-snapped lateral cut lines (the copy layer's output)
    if tg["x"] and tg["y"]:
        sx0 = int(round(tg["x"][0] * W))
        sx1 = int(round(tg["x"][1] * W)) - 1
        sy0 = int(round(tg["y"][0] * H))
        sy1 = int(round(tg["y"][1] * H)) - 1
        draw.rectangle([sx0, sy0, sx1, sy1], outline=amber, width=3)
        for line, col in ((sx0, green), (sx1, green), (sy0, green),
                          (sy1, green)):
            pass
    else:
        sx0 = sy0 = sx1 = sy1 = -1

    keep_src = tg.get("keep_source") or "none"
    text = (f"{dataset}/{sample}  z={mid}  voxel={b.get('voxel_um')} um\n"
            f"detection (dashed cyan): X {b['x0']}..{b['x1']}  "
            f"Y {b['y0']}..{b['y1']}\n"
            f"snapped cut lines (solid amber): X {sx0}..{sx1}  "
            f"Y {sy0}..{sy1}\n"
            f"snapped keep = {tg['keep']} ({keep_src})   "
            f"snapped cut = {tg['cut']}\n"
            f"raw detection: keep={zb.get('keep')} wood_top={zb.get('wood_top')}"
            f" cut={zb.get('cut')}")
    ty = 10
    for line in text.splitlines():
        draw.text((12, ty), line, fill=amber)
        ty += 18
    # z annotation marks on the right edge (keep green / cut red)
    for value, color, label in ((tg.get("keep"), green, "keep"),
                                (tg.get("cut"), red, "cut")):
        if value is None:
            continue
        mark = max(0, min(H - 1, int(value)))
        draw.line([(W - 70, mark), (W - 1, mark)], fill=color, width=3)
        draw.text((W - 220, max(2, mark - 18)), f"{label}={value}", fill=color)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{dataset}_{sample}_snap.png"
    im.save(str(out))
    meta = {"dataset": dataset, "sample": sample, "z": mid,
            "H": H, "W": W, "voxel_um": b.get("voxel_um"),
            "detection": {"x0": int(b["x0"]), "x1": int(b["x1"]),
                          "y0": int(b["y0"]), "y1": int(b["y1"]),
                          "keep": zb.get("keep"),
                          "wood_top": zb.get("wood_top"),
                          "cut": zb.get("cut")},
            "snapped": {"x0": sx0, "x1": sx1, "y0": sy0, "y1": sy1,
                        "keep": tg["keep"], "cut": tg["cut"],
                        "keep_source": keep_src}}
    (OUT_DIR / f"{dataset}_{sample}_snap.json").write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(f"snap overlay saved: {out}   detection X {b['x0']}..{b['x1']} "
          f"Y {b['y0']}..{b['y1']}  ->  snapped X {sx0}..{sx1} Y {sy0}..{sy1}  "
          f"keep={tg['keep']}({keep_src}) cut={tg['cut']}")
    return out


if __name__ == "__main__":
    specs = ([(sys.argv[1], sys.argv[2])] if len(sys.argv) > 2 else SPECS)
    for ds, sp in specs:
        overlay(ds, sp)
