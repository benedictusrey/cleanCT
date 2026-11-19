# cleanCT: how the Wood top, Metal top, L and R lines are found and used

This note records how each guide line is detected on a loaded specimen, how the
line is placed on the screen, and how the DICOM export is clipped to the four
lines. It describes cleanCT 1.0.0 as built from commit `dc95ca1` and later.

## 1. The four lines at a glance

| Line on screen | What it is | Axis in the scan | Detected by | Placed by (copy layer) | Export effect |
|---|---|---|---|---|---|
| **Wood top** (green dashed, "Keep: N") | Top of the wood, where the kept range starts | Z (slice) | `wood_bounds`: wood top from the axial pool and edge walk (`zb.wood_top`) | Keep = `zb.wood_top` | Slices above it are removed |
| **Metal top** (red dashed, "Cut: N") | Top of the metal base, where the kept range ends | Z (slice) | `wood_bounds`: metal anchor from the ortho quorum, fused with the detector anchor (`zb.metal_top`) | Cut = `zb.metal_top` | Slices at and below it are removed |
| **L / R, axial and coronal** (blue vertical) | Left and right edge of the wood | X (columns of each DICOM slice) | Lateral projection of the wood, confirmed by the sagittal and coronal witnesses | X pair = fractions of the width | Columns outside the box are removed |
| **L / R, sagittal** (blue vertical) | Left and right edge of the wood, as seen in the sagittal plane | Y (rows of each DICOM slice) | Lateral projection of the wood, confirmed by the ortho witness | Y pair = fractions of the height | Rows outside the box are removed |

"Top" and "bottom" are the slice direction (Z). The DICOM slices are axial: rows
are Y and columns are X. So in the exported slices the sagittal L/R lines clip the
rows and the axial/coronal L/R lines clip the columns.

## 2. Detection: `core/wood_bounds.py`

The module is the validated detection core. Its header is marked "STABLE
DETECTION - DO NOT MODIFY CORE". Only the changes listed in section 9 were made
to it, and they are behaviour fixes or additive keys. Every physical length is
given in millimetres and converted to pixels with the voxel size, so 6 µm to
120 µm scans behave the same.

### 2.1 Constants that set the lines

| Constant | Value | Meaning |
|---|---|---|
| `POOL_STEP_MM` | 0.85 mm | Spacing of the axial pool that measures Z |
| `N_AXIAL_POOL` | 32 | Axial slices sampled for the pool |
| `CLOSING_MM` | 0.15 mm | Radius of the morphological closing |
| `AIR_MIN_AREA_MM2` | 0.15 mm² | Components below this are specks and are ignored, also when alone |
| `BASE_FRAC` | 0.12 | A metal base must span at least 12% of the ortho profile width |
| `ORTHO_COLS` / `ORTHO_QUORUM` | 5 / 2 | Mid-columns probed per ortho plane; how many must agree |
| `HALO_MM` | 0.2 mm | Halo guard above the base top |
| `EDGE_AIR_MAX` | 0.05 | An edge slice must be almost air to be adopted |
| `KEEP_AIR_MARGIN_MM` | 0.3 mm | Air-top line sits this far above the curtain (not used by the copy layer) |
| `KEEP_CLEAR_MM` | 0.2 mm | Clear air that must be verified above the curtain |
| `KEEP_SCAN_MM` | 6.0 mm | How far above the wood top the curtain is searched |
| `WITNESS_AGREE_MM` | 1.5 mm | Axial and ortho lateral estimates must agree within this |
| `AIR_HU_DEFAULT` | −900 HU | Air threshold for the air-top and object tests |
| `WOOD_HU_DEFAULT` | (−990, −500) HU | Dense-wood window of the processed pipeline |
| `UNPROC_WOOD` (viewer_core) | (−960, −500) HU | Wood window before processing (see 9.2) |

### 2.2 Metal top (Cut): the metal anchor

1. The sagittal and coronal stacks give, for each slice, whether the metal base
   spans at least `BASE_FRAC` of the profile width on each of `ORTHO_COLS`
   mid-columns. A slice anchors only when at least `ORTHO_QUORUM` columns agree on
   both planes. Straps and pins are thin and cannot pass.
2. If the pipeline gave a detector anchor (`det_anchor`, the report's
   `anchor_slice`), the anchor is the bottom-most slab run that reaches it. Without
   one, the bottom-most agreeing run wins.
3. The halo guard (`HALO_MM`) keeps the air statistics above the base top clean.
4. Output: `anchor.z = [top, bottom]` and `zb.metal_top = top`. When a detector
   anchor exists, `zb.metal_top` is the detector anchor itself. This is the line the
   user checks against the metal base.
5. `zb.cut` is the pipeline's halo onset (`det_cut`). It is reported as
   "auto-detected" in the Boundaries panel and is no longer drawn as a line
   (section 8).

### 2.3 Wood top (Keep): the axial pool and edge walk

1. Over the trusted window (above the base top, below the cut), the axial
   slices are sampled every `POOL_STEP_MM` (32 slices at most).
2. Each sampled slice is classified as wood, using the wood HU window, metal
   excluded. The wood mask is closed (`CLOSING_MM`), its holes are filled, and its
   components smaller than `AIR_MIN_AREA_MM2` are dropped. A lone component is
   gated too (the fix in section 9.1).
3. The largest gap-tolerant run of wood slices is the wood body. The edge walk
   starts inside that run and walks toward the top, contiguously. It stops at the
   first air slice. That slice is `zb.wood_top`.
4. An air-curtain guard (`EDGE_AIR_MAX`) refuses an edge slice that is not clearly
   air. A foggy edge defers to the previous guide instead of inventing one.
5. Predicted on loaded samples: 2-5 (processed) gives `wood_top = 19`, the
   same as the auto Keep shown on screen. 3_694_7 (pre-process) gives 94 and
   2_666_5 (pre-process) gives 88. Both match the yellow lines marked on the
   screenshots.

### 2.4 Air top (curtain): reported, not drawn as the Keep

`zb.keep` is the topmost non-air material within `KEEP_SCAN_MM` above the wood
top, minus `KEEP_AIR_MARGIN_MM`. It is adopted only when `KEEP_CLEAR_MM` of clear
air is verified above that material. It is kept in the payload for reference. The
copy layer no longer uses it (section 8). Setting `keep_on_wood_top=False` in
`auto_snap.detected_lines` restores the air-top rule.

### 2.5 L and R lines: the lateral box

1. Each axial slice gives, per column, the wood occupancy. The lateral lane bounds
   come from the projection over the pooled slices (`_projection_lane_bounds`),
   with a physical clearance of `LAT_EDGE_CLEAR_MM`. The same is done per row.
2. The ortho witnesses give the mid-column air margins of the sagittal stack (Y)
   and the coronal stack (X). A witness margin is adopted only when it agrees with
   the axial margin within `WITNESS_AGREE_MM`. Otherwise the axial margin stands,
   so the line never cuts into the wood.
3. Output: `x0, x1` (columns) and `y0, y1` (rows) of the wood, plus the image size
   `W, H`. The copy layer turns them into fractions:
   `x = (x0 / W, (x1 + 1) / W)` and `y = (y0 / H, (y1 + 1) / H)`. A pair must span at
   least 4% of the axis (`MIN_PAIR_SPAN`).
4. Predicted on loaded samples (pre-process):

| Sample | X pair (axial and coronal L/R) | Y pair (sagittal L/R) |
|---|---|---|
| 3_694_7 | 2% to 97% | 14% to 80% |
| 2_666_5 | 1% to 96% | 17% to 82% |

The percentages are shown truncated, as the screens show them. The screens show
the same values: 3_694_7 reads "L 2% R 97%" in the coronal view and "L 14% R 80%"
in the sagittal view.

## 3. Pre-process and processed bounds

| | Before processing (the "Not processed" state) | After processing |
|---|---|---|
| Z range | Whole scan (`cut_from = n`) | Report cut and keep, after Apply |
| Metal anchor | Ortho quorum only | Detector anchor from the report fused with the ortho quorum |
| Halo onset | none | Report `detected_cut_from` |
| Wood window | `UNPROC_WOOD` = (−960, −500) | Report config (default (−990, −500)) |
| Wood Z window | Full scan | Pipeline ROI track (`track_z`) |

## 4. Copy layer: `core/auto_snap.py`

`detected_lines(bounds)` is the single rule for the lines shown and for the lines
delivered:

- `cut = cut_target(zb)` = `zb.metal_top`, else `zb.cut`.
- `keep = zb.wood_top` (the Wood top). Without a wood top it falls back to
  `zb.keep`. `keep_on_wood_top=False` uses the air top only.
- `keep` is clamped to `cut − 1`.
- `x` and `y` are the lateral fractions of section 2.5.

Auto snap places the lines on load, and the lines return to the detection after
the Snap button. A manual drag or typed value suspends the copy layer until the
next detection. Process and export take the same values from `detected_lines`.
The Results view marks "Lines changed" when the applied cut or keep differs from
the processed run.

## 5. Apply: what the pipeline and the export receive

"Apply lines" writes the lines to the specimen's registry entry
(`core/custom_series.py`):

- `config_overrides`: `cut_override`, `keep_from`, `cut_margin_slices`. These go
  to the pipeline. Unknown keys are refused there.
- `lateral`: `{"x": [lo, hi], "y": [lo, hi]}`, the lateral box of section 2.5.
  Kept outside `config_overrides` because the pipeline rejects unknown keys. It is
  read at export time only (`lateral_box(specimen)`).

Lines change the processed result only after Apply, the same as the cut and keep
before this round.

## 6. Export: what the DICOM series keeps

The export is DICOM only in this round. The NIfTI export clips Z the same way,
but it does not clip X or Y (section 9.4).

1. **Z (Wood top and Metal top).** `core/bundle_export.py`, `_export_bundle_into`
   takes the source slices `[keep_from, cut_from)`. The slices above the Wood top and
   at or below the Metal top are never written. This was already the behaviour.
2. **X and Y (L/R lines).** `_write_kept_dicoms` reads the stored box and converts
   it to pixels with `lateral_range(pair, n)`. `None` means the whole axis. For each
   kept slice `_crop_slice(ds, y0, y1, x0, x1)`:
   - copies the box of pixels into `PixelData` and sets `Rows` and `Columns`;
   - moves `ImagePositionPatient` to the first kept row and column, using
     `PixelSpacing` ([row, column]) and the two direction triplets of
     `ImageOrientationPatient`;
   - keeps the source tags, the file name and the file mapping; each slice gets a
     new SOP instance UID that references its source slice.
3. A compressed series is refused with a clear message. The scan series are
   uncompressed.

### Verified on real data (read-only)

Slice `XY0100.dcm` of 2-5 (458 rows by 449 columns, 66.212 µm pixels), cropped in
memory with the L/R values of the screen (Y 5% to 94%, X 14% to 80%):

- rows 23 to 430, columns 63 to 358, so 408 rows by 296 columns;
- the pixels equal the source box exactly;
- the origin moved by 1.523 mm along Y and 4.171 mm along X, which is
  23 × 0.066212 mm and 63 × 0.066212 mm.

## 7. Labels and layering on the Boundaries view

The guide lines (dotted) are drawn beneath the job lines so the job handles stay
visible. The guide labels ("wood top N", "metal top N") are drawn after the Keep and
Cut lines and labels, so the job line never crosses a guide label. Before this
round the Cut line crossed the "metal top" label whenever both sat on the same
slice.

## 8. Decisions made in this round (to review)

1. **Cut = metal top.** The Cut follows the metal base (the detector anchor), not
   the halo onset. On 2-5 this moves the auto Cut from 353 to 405. The halo onset
   is still reported in the panel.
2. **Keep = wood top.** The auto Keep sits on the wood top. The 0.3 mm air margin is
   not applied on the copy layer, so fog above the wood apex falls outside the
   delivery. DEV_LOG 4.2 describes the air-top rule.
3. **L/R means the vertical lines of the current view.** In the sagittal view these
   are the Y pair, and in the axial and coronal views they are the X pair. The
   export clips both pairs, so the delivered box is the wood box in all three axes
   between the lines. To clip only one pair, leave that key out of the box that
   `_apply_and_process` stores.

## 9. Changes made to the detection and the export in this round

1. **A lone speck is not signal.** `_largest_components` returned a single
   component without the size gate. On 2_666_5 a 3 px speck at slice 7 set the curtain
   top, which pulled the air-top line to slice 2. The gate now applies to a lone
   component too. Test: `tests/test_bounds_v2.py`.
2. **Pre-process wood window −960 HU.** On 2_666_5 the jar's halo lies between −990
   and −960 HU at the top of the scan: 5,607 pixels at slice 30 and none above −960.
   At −990 the wood top went to slice 11. At −960 it is 88. 2-5 at −960 gives 23
   against 19 for the processed bounds. The processed bounds keep the report's
   window. Shortcut noted in the code: pre-process only.
3. **Labels in front of the lines.** Section 7. Test:
   `tests/test_auto_z_guides.py` (layering, by pixel).
4. **Export clipped to the L/R lines.** Section 6. Tests: `tests/test_export_clip.py`.
   The NIfTI export does not clip X or Y yet.

## 10. Known limits

- The export does not list the L/R box in `extraction_info.txt` yet.
- The processed bounds of 2_666_5 use the report window (−990). They have not been
  checked on screen after a Process. Check the Keep and the L/R lines after the first
  run.
- Apply is the only way the L/R box reaches the export. A box dragged but not
  applied is not exported.
- The Y pair (sagittal L/R) is clipped in the DICOM export only. The NIfTI export
  clips Z only.
- A running pipeline cannot be stopped. This is an engine change and is not part of
  this round.

## 11. Code map

| Purpose | File and function |
|---|---|
| Detection (metal anchor, wood top, air top, lateral box) | `src/core/wood_bounds.py`: `wood_bounds`, `_metal_anchor`, `_edge_walk`, `_curtain_top`, `_largest_components`, `_projection_lane_bounds` |
| Pre-process windows | `src/core/viewer_core.py`: `UNPROC_WIN`, `UNPROC_WOOD`, `_prev_source_unprocessed` |
| Copy layer | `src/core/auto_snap.py`: `cut_target`, `detected_lines` |
| Guide lines on screen | `src/widgets/viewer_2d.py`: `_auto_z_guides`, `paintEvent` |
| Apply and the lines in the window | `src/main_window.py`: `_apply_and_process`, `_apply_auto_snap`, `_apply_payload_state` |
| Registry: overrides and the lateral box | `src/core/custom_series.py`: `set_specimen_overrides`, `set_specimen_lateral`, `lateral_box` |
| Export: Z range, X/Y crop | `src/core/bundle_export.py`: `_export_bundle_into`, `_write_kept_dicoms`, `lateral_range`, `_crop_slice` |

## 12. Tests that protect this

- `tests/test_bounds_v2.py`: lateral and witness rules; a lone speck is not signal.
- `tests/test_auto_snap.py`: Keep rides the wood top; Cut follows the metal top; the
  window behaviour on load, toggle and unprocessed load.
- `tests/test_auto_z_guides.py`: the guides, no halo line, the layering by pixel.
- `tests/test_axial_outline.py`: outline precision, the cache version and the
  pre-process window.
- `tests/test_export_clip.py`: the lateral range, the crop of pixels and origin, and
  the stored box.
- `tests/test_results_sync.py`: the Results view and the "Lines changed" marker.
