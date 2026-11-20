# ROI Detection & Cut Lines - Technical Documentation

> Partly superseded on 2026-11-19: the Keep line is the wood top and the Cut line is the metal top.

How cleanCT 1.0.0 determines the wood ROI and how the detected lines become
the user-facing cut lines.  Written against the current source (audits 0AF +
0AG).  Companion docs: `DEV_LOG.md` (changelog), `AUDIT.md` (release record).

Key source files:

- `src/core/wood_bounds.py` - detection core (`# STABLE DETECTION - DO NOT
  MODIFY CORE`), frozen in 0AG.
- `src/core/auto_snap.py` - pure "copy detection -> cut lines" mapping.
- `src/main_window.py` - load / re-detect application, toggle, suspension.
- `src/widgets/viewer_2d.py` - the four draggable guide lines (view state).

Ground truth used for validation: `custom/1-17_OD` (1098 slices, 24.852 um,
oven-dry) plus `24um/1-1`, `24um/1-15`, `66um/1-1`.  Evidence overlays live in
`debug_roi_fix/` (detection) and `debug_snap/` (detection vs snapped lines).

---

## 1. Detection Lines Logic

### 1.0 Trigger and data flow

- `viewer_core.build_payload(dataset, sample)` runs on a worker for every
  specimen selection and after every Process job (the completion re-selects
  the specimen).  It builds the ortho column stacks and calls
  `wood_bounds(...)`.
- Inputs: `n_slices`, `cut_from`, the sagittal/coronal stacks (5 mid-columns
  each), `metal_hu`, the calibrated `wood_hu` window, `voxel_um`,
  `z_step_um`, the detector metal anchor `det_anchor`, and the halo-onset
  `det_cut`.
- Output (`payload["bounds"]`): `y0 y1 x0 x1 H W n`, `zb{keep, cut,
  wood_top, wood_bottom, top_ok}`, `anchor`, `margins{x,y}`, `evidence`.

### 1.1 wood_mask generation (per slice and per ortho plane)

1. `_object_mask(vals, air_hu, wood_hu, metal_hu)`:
   `finite AND wood_hu[0] <= v <= wood_hu[1] AND v < metal_hu`.
   When a calibrated window exists its LOWER BOUND is the air/wood boundary
   (0AD fix); the generic `AIR_HU_DEFAULT = -900` applies only without one.
   This is a pure HU threshold - there is no per-slice Otsu on the mask
   itself.
2. `_close(m, r)` - morphological closing, radius `CLOSING_MM = 0.15 mm` in
   pixels (capped at 24 px; Euclidean-distance implementation above 8 px).
3. `binary_fill_holes` (scipy) - closes internal voids.
4. `_largest_components(m, min_area_px)` - drops components below
   `AIR_MIN_AREA_MM2 = 0.15 mm^2` (physical, converted via the voxel size).

The same mask function is used by the axial pool, the z edge walks, and the
ortho witnesses.

### 1.2 Top / Bottom lines (z axis) - LOCKED CORE

Axial pool: up to 32 slices spread over the trusted z-window (tracked ROI
intersected with `cut_from`, capped by the metal anchor minus the physical
halo guard, `HALO_MM = 0.2`).

- Presence flags + largest gap-tolerant run select the main wood body.
- `_edge_walk` walks contiguously from inside the run to the first air slice
  -> `wood_top` / `wood_bottom` at slice resolution.
- **Keep line**: `_curtain_top` scans upward from `wood_top` for any non-air
  material within `KEEP_SCAN_MM = 6 mm`; if `KEEP_CLEAR_MM = 0.2 mm` of
  contiguous clear air is verified above the curtain top, keep =
  curtain_top - `KEEP_AIR_MARGIN_MM = 0.3 mm` (slices).  Otherwise
  `keep = None` (fog-deferred - the report default stands).
- **Cut line**: `zb.cut = det_cut` (pipeline halo onset) when known, else the
  anchor top, else `wood_bottom + 1`.
- These paths carry `# LOCKED - CORRECT - DO NOT MODIFY` (0AF) and
  `# STABLE DETECTION - DO NOT MODIFY CORE` (0AG).  They are byte-compared
  before/after every change (e.g. `custom/1-17_OD`:
  `wood_top=28, wood_bottom=1066, keep=10, cut=1074`).

### 1.3 Left / Right lines (lateral envelope) - LOCKED CORE

Per axis, independent of the z logic (0AF):

1. **Fog-blanket gate**: a pooled slice contributes lateral evidence only
   when its outer physical band `LAT_EDGE_CLEAR_MM = 0.5 mm` (all four
   sides) is at most `LAT_BLANKET_FRAC = 0.50` occupied.  Full-FOV fog
   blankets are excluded geometrically; slices with only a dim fog ring
   pass.
2. **Projections** over the contributing slices:
   - X envelope: `col_proj = sum over slices of mask.sum(axis=0)`
     (per column - `axis=0` sums over ROWS = Y).
   - Y envelope: `row_proj = sum over slices of mask.sum(axis=1)`
     (per row - `axis=1` sums over COLUMNS = X).
3. **Threshold - Otsu knee, clamped**:
   `thr = clip(otsu(col_proj), 0.40 * peak, 0.50 * peak)` with
   `peak = max(col_proj)`.  Empirically the lane distribution is bimodal:
   fog ring 25-32 % of peak, wood plateau 95-100 %; the Otsu valley sits at
   49-57 %, and the clamp keeps it on the valley for unimodal wood.
4. **Envelope**: first/last lane with `proj > thr` -> `x0..x1` / `y0..y1`.
   (The originally prescribed `0.05 * max` was measured full-frame on every
   reference specimen - see `DEV_LOG.md` section 2.6.)
5. Fallback (too little evidence): 20th/80th percentile of the contributing
   slices' per-slice extents.
6. **Ortho witnesses**: the sagittal plane gives an independent Y envelope
   (rows gated by the same blanket rule, column projection, Otsu knee) and
   the coronal plane an X envelope; a witness value is adopted only when its
   side has physical clearance and agrees with the axial value within
   `WITNESS_AGREE_MM = 1.5 mm`.

Values for the reference fleet (before -> after 0AF):
`custom/1-17_OD [6,1193]x[6,1191] -> [97,1111]x[89,1110]`;
`24um/1-1 [6,1116]x[6,1126] -> [58,1068]x[64,1081]`;
`24um/1-15 [62,1075]x[60,995] -> [63,1075]x[54,1067]`;
`66um/1-1 [2,428]x[2,426] -> [26,405]x[25,407]`.

### 1.4 The four detected lines - summary

| Line | Symbol | Formula (source pixels) | Semantics |
| --- | --- | --- | --- |
| Top (Keep) | `zb.keep` | `curtain_top - 0.3 mm` when clear air verified | highest kept slice (inclusive delivery starts here) |
| Bottom (Cut) | `zb.cut` | `det_cut` else anchor top else `wood_bottom + 1` | first slice NOT delivered (exclusive) |
| Left | `x0` | first X lane with `col_proj > thr` | left edge of the lateral box |
| Right | `x1` | last X lane with `col_proj > thr` | right edge of the lateral box |

`margins.x = [x0, W-1-x1]`, `margins.y = [y0, H-1-y1]` (edge distances -
the box side is `W-1-margin_hi`; the sign inversion caused a debug-tool bug
fixed in 0AF).

---

## 2. Cut Lines Logic

The cut lines are the user-facing keep/cut (z) and the four lateral guide
values.  They are produced by the **copy layer** - `core/auto_snap.py` +
`main_window` - which never re-computes detection, only copies it.

### 2.1 Detection -> cut mapping (`auto_snap.detected_lines`)

```
cut   = zb.cut                       (metal/halo onset)
keep  = zb.keep                      (verified air top)
        else zb.wood_top             (fallback, when allowed)
x pair = (x0 / W, (x1 + 1) / W)      (fractions 0..1)
y pair = (y0 / H, (y1 + 1) / H)
keep is clamped below cut (keep <= cut - 1).
```

- The fallback exists because an oven-dry/dim top can defer the air-top keep
  (`keep = None`); the detected wood top is still real evidence and is the
  same edge the dotted "wood top" guide draws.
- There is **no hidden offset** between detection and cut: the physical
  safety margins are already inside the detection constants
  (`KEEP_AIR_MARGIN_MM`, the clear-air verification, the halo-onset cut).
- The user-facing **Margin Above Cut** control (`pref_margin`) is an
  explicit, separate safety buffer (default 0) and is never changed by
  auto-snap.
- The pipeline's **air-crop** (`chk_air_crop`, default on) is the lateral
  trim applied during processing; the viewer pairs are the review geometry.

### 2.2 Auto Snap to Detection (0AG, default ON)

- Trigger events: every payload load / re-detect (specimen select, post-
  Process re-select), toggle switched on, and the explicit
  `Snap to detection` button (which also allows the wood-top fallback).
- Behavior: when `Auto snap to detection` is checked and bounds exist, the
  Keep/Cut spins and ALL FOUR lateral values (viewer pairs + sliders) are set
  exactly to the mapping above, then `pref_dirty = False` (delivery follows
  detection until the user edits).
- **Manual edit suspension**: any manual change to Keep, Cut, Margin, or the
  lateral values marks the auto-snap state *suspended* (logged once).
  Suspension lasts until the next detection event, which re-applies and
  re-arms.  Checkpoint restores count as manual state (restore wins; the
  next detection re-snaps).
- Toggle OFF: loads no longer apply the detection copy to the lines; the z
  lines initialize from the specimen's stored cut lines (the pre-existing
  load behavior) and the lateral pairs reset to the neutral 15 %/85 %
  default so no stale values leak between specimens.  Detection guides
  (dotted) stay visible as reference.  Switching the toggle back on
  applies the detection immediately.
- Delivery: `Export bundle` delivers the lines on screen (auto-snapped or
  manual); the combined Process & Export uses the fresh detection when the
  user made no edit this session (`pref_dirty`), exactly as before.

---

## 3. View-Specific Notes

| View | Horizontal axis | Vertical axis | Left/Right lines | Top/Bottom lines |
| --- | --- | --- | --- | --- |
| Sagittal | Y (`axis=1` of the `(z,y)` plane) | Z (slice index) | the **Y pair** (panel labels read "Left/Right Y") | Z Keep/Cut (locked detection) |
| Coronal | X (`axis=1` of the `(z,x)` plane) | Z (slice index) | the **X pair** | Z Keep/Cut (locked detection) |
| Axial | X (`axis=1` of the `(y,x)` slice) | Y (`axis=0` of the slice) | the **X pair** | the **Y pair** (axial Top/Bottom = detected Y envelope); z does not apply in-plane |

Naming and consistency:

- There is exactly ONE lateral value per physical axis (one X pair, one Y
  pair).  The sagittal and coronal views draw the same pair the axial view
  uses for its corresponding side, so the three views can never disagree.
  Plane switches only swap which pair is shown, never re-derive it.
- `_update_lateral_panel_for_plane` relabels the slider panel per plane
  ("Left Y" on sagittal, "Left X" otherwise) and shows the axial
  Top/Bottom (Y) rows only in the axial plane.
- In the axial view the vertical detected pair (Y) is presented as
  Top/Bottom of the visual box; it is the same detected envelope, not a
  second measurement.
- The z Keep/Cut lines exist only on the sagittal and coronal views (they
  are slice indices); the axial view is a single slice and has no z lines.
- Auto-snap sets all of these together from one detection (`_apply_auto_snap`);
  fixing one view never re-derives another - all views read the same pair
  values.

---

## 4. Verification

- `tests/test_wood_bounds.py` - detection invariants (sparse-fog + oven-dry
  dense-blanket scenarios): envelope matches the block outline within the
  closing radius, z semantics calibrated.
- `tests/test_auto_snap.py` - copy-layer suite: pure mapping (cut/keep,
  fallback, pairs, clamping) and offscreen window behavior (load applies,
  fallback keeps the wood top, manual edit suspends, next detection
  re-snaps, toggle off resets pairs, checkpoint restore suspends, snap
  button applies).
- `tools/debug_lines_overlay.py` - detection overlay (blue box) on a real
  axial slice -> `debug_roi_fix/`.
- `tools/debug_snap_overlay.py` - detection vs snapped-lines overlay
  (dotted detection guides, solid snapped cut lines) for
  `24um/1-1`, `24um/1-15`, `66um/1-1` -> `debug_snap/`.
- Full gate: `tests/run_cleanct_regressions.ps1` (13 suites after 0AG).
