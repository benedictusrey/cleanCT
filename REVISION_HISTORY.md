# REVISION_HISTORY.md

Complete chronological revision history of the cleanCT workstation, from the
v1.0.0 baseline to the current build. The full per-round audit record with
per-release hashes lives in `AUDIT.md`; this file is the human-readable
changelog of what changed and why.

---

## 2026-09-24 — Initial State from v1.0.0

- Baseline: the audited 1.0.0 release (AUDIT §0Z) — flat checkout layout,
  PyInstaller 6.22.2 launcher with embedded icon, portable ZIP + ISCC
  setup.exe, 10-suite regression gate, USER_GUIDE shipped in every package.
- Working features at baseline: load (DICOM/TIFF/NIfTI) → specimen list →
  3-plane visualize → keep/cut lines → history → export → checkpoint
  save/load; transactional bundle export; torch-free CuPy GPU path.
- Known open items carried in: drafted checkpoint refinements (G.2),
  post-publication bytecode residue, ISCC not on PATH.

## 2026-09-24 — Fix: Checkpoint Session Hardening (0AA)

- **Problem:** the first-run empty-state toggle could unmount an active
  checkpoint-snapshot view; a failed snapshot-only load could leave the
  saved preview blank; loading a checkpoint-only snapshot appended a
  duplicate history entry; history restore forced a source reconnect; the
  packaged `--selfcheck` did not verify the window icon; a source recorded
  under an 8.3 short path (`C:\Users\LABPC~1\…`) was rejected against the
  canonical long path on reconnect.
- **Fix:** the stacked workspace stays always visible (only the empty card
  toggles); snapshot-only load failures defensively repaint the saved
  preview; `_record_session_preview` returns early while snapshot-only;
  history restore accepts a snapshot-only session; `--selfcheck` verifies
  the packaged icon; `_checkpoint_source_available` canonicalizes both
  paths via `Path.resolve()` (`_same_source_path`).
- **Files:** `src/main_window.py`, `src/core/viewer_core.py` (cache
  versions), `tests/test_render_async.py`, `main.py`.
- Backup: `0BACKUP/audit_20260924_checkpoint_hardening_r8`.

## 2026-09-24 — Restructure: Structured Checkout + Specimen Panel (0AB)

- **Problem:** the checkout root was cluttered (old exes/specs, superseded
  round scripts, empty venv duplicate, Avast/quarantine junk, cache and
  log debris); the left specimen list was a flat name-only list with no
  management actions; a QThread garbage-collected mid-run hard-crashed the
  app (0xC0000409) in the size-scan worker.
- **Fix:** structured layout (`src\`, `assets\icons` canonical pack,
  `data\` per-user state, `tests\`, `dist\`, `0BACKUP\`); duplicates and
  temp files removed; all path contracts made layout-aware
  (`core/paths.py` APP_ROOT resolver, dev state root = `data\`); tooling
  re-pointed (runner, builder, backup script, .gitignore); specimen panel
  overhaul (search/filter with live count, two-line metadata rows, lazy
  stat-only size worker with keep-alive list + close drain, right-click
  context menu, confirmations, busy spinner, real-backend GPU chip);
  `custom_series` gained rename/duplicate/unique-ID.
- **Files:** `src/core/paths.py`, `src/core/custom_series.py`,
  `src/core/viewer_core.py`, `src/main_window.py`, `src/icon_utils.py`,
  `src/theme.py`, `src/widgets/specimen_panel.py` (new), `main.py`,
  `tests/run_cleanct_regressions.ps1`, `installer/build_installer.py`,
  `tests/create_audit_backup.py`, `.gitignore`.
- Backup: `0BACKUP/audit_20260924_structured_overhaul_r9`.

## 2026-09-24 — Fix: Clean Export Delivery + Snap Pipeline (0AC)

- **Problem (filenames):** exported artifacts carried `_rem_` markers
  (`<specimen>_rem_dcm/<specimen>_rem_0001.dcm`, `<specimen>_rem.nii`,
  `<specimen>_rem.json`).
- **Fix:** delivered names are clean — the DICOM series is
  `<specimen>_dcm/` with every kept slice under its ORIGINAL source
  filename (`OriginalName.dcm`), the volume `<specimen>.nii`, the sidecar
  `<specimen>.json`; legacy `_rem` bundles are swept, recovered and
  adopted under the clean names; update-in-place retention semantics
  preserved.
- **Problem (metadata):** exported DICOMs carried only PatientName
  enrichment.
- **Fix:** every exported slice now carries full delivery metadata on top
  of the byte-preserved source tags: PatientName (specimen ID),
  PatientID (source value, else specimen ID), Modality (CT),
  StudyDescription, SeriesDescription, InstitutionName,
  SoftwareVersions = cleanCT, SliceThickness, PixelSpacing,
  AcquisitionDate/Time, and the processing history in
  ImageComments/AdditionalPatientHistory; the NIfTI descrip header leads
  with `cleanCT 1.0.0`; the sidecar records the exact tag block; export
  self-verification checks every enriched tag via pydicom readback
  (UID-matched — original filenames are not positionally sorted).
- **Problem (snap):** "Snap to detection" appeared not to move the canvas
  lines on large volumes — the viewer's line coordinate space came from
  the last rendered preview, so payload loads and preview applications
  clamped the solid Keep/Cut lines (994 → 100) before the real slice
  count was known.
- **Fix:** `viewer_2d.setSliceCount(n)` declares the real slice count at
  every payload load; `_on_prefs_preview_ready` applies the pixmap FIRST
  and re-places the lines afterwards; a fog-deferred air top now draws a
  dotted "wood top" evidence guide and Snap falls back to it.
- **Also:** rebuilt context menu (Open/Rename/Duplicate/Show in
  Explorer/Properties/Remove/Clear all), `dialogs/properties_dialog.py`,
  keyboard shortcuts F2/Del, installer folder location-tolerant
  (`_discover_roots`) and synced into `cleanCT_v1.0.0\installer\`.
- **Files:** `src/core/bundle_export.py`, `src/core/viewer_core.py`,
  `src/main_window.py`, `src/widgets/viewer_2d.py`,
  `src/dialogs/properties_dialog.py` (new), `main.py`,
  `installer/build_installer.py`, `tests/test_export_formats.py`,
  `tests/test_export_stream.py`, `tests/test_pipeline_synthetic.py`.
- Backup: `0BACKUP/audit_20260924_final_polish_r10`.

## 2026-09-24 — Fix: Wood Top Value 692 → 65 + Text Clipping (0AD)

- **Problem (wood top):** on the real 1098-slice specimen `1-17_OD` the
  detection reported `wood top 692` while the true apex is slice 65 (the
  pipeline's wood track reads `z0=65, z1=1021`; ROI = 957 slices).
- **Root cause:** `wood_bounds._object_mask` required wood-class pixels to
  ALSO exceed the module's fixed air default (`AIR_HU_DEFAULT = -900 HU`)
  even when a calibrated wood window was supplied. This oven-dry
  specimen's top half reads ≈ -990..-900 HU, so the fixed floor erased it
  from the wood class; the pooled run started ~692 slices deep and
  `wood_top` inherited the first wood-present pooled sample.
- **Fix:** with a calibrated wood window the window DEFINES the class
  (its lower bound is the calibrated air/wood boundary); the fog-curtain
  walk above the apex uses the same calibrated floor. Cache versions
  bumped (`PREV_VERSION 9`, `CACHE_VERSION 17`) so stale payloads
  regenerate. Verified through the app's real payload path:
  `wood top = 65` with `wood_bottom/cut/anchor` unchanged; the validated
  fleet detection stays intact (66 µm `1-1` still `[15, 378]`; 24 µm
  `1-1`'s wood top corrected 44 → true apex 40 — the same
  misclassification).
- **Fix (top/bottom placement pipeline):** the viewer's line coordinate
  space came from the last preview; `_apply_checkpoint_controls` now
  declares the clamped real slice count before placing lines, and the
  Preferences drag handlers adopt the SPIN-clamped value into the job
  state — a stale viewer space can no longer push the job state outside
  the loaded specimen (the reported 4022-style values become impossible).
- **Fix (UI/UX clipping):** Save/Load checkpoint buttons stacked
  full-width (were clipped to "ave checkpoint…" / "oad checkpoint…");
  GPU chip compact text + tooltip (was clipped at "(CuPy C…"); Qt
  application display-name registration removed (the title bar
  duplicated as "… Metal-Base Removal - cleanCT"); action log wraps at
  word boundaries (no mid-word breaks); the bundle-destination field's
  full path is mirrored in its tooltip and kept in step on edits.
- **Files:** `src/core/wood_bounds.py`, `src/core/viewer_core.py`,
  `src/main_window.py`, `main.py`.
- Backup: `0BACKUP/audit_20260924_woodtop_fix_r11`.

## 2026-09-24 — Fix: Left/Right ROI Alignment (0AE)

- **Root cause:** the lateral envelope was the percentile aggregation of
  per-slice bounding-box extents over ALL pooled slices. With the
  corrected (calibrated) wood class, near-air fog at ≈ -990..-978 HU in
  the dry region falls INSIDE the calibrated window, so fog-blanket
  slices report full-frame extents (0..H-1, 0..W-1); the 20/80 percentile
  envelope then stretched to (nearly) the full frame. Axis order
  (`_mask_extent` → y0,y1,x0,x1) and the coordinate system were checked
  and are consistent; no hardcoded lateral values exist — the detachment
  came from fog-polluted extents feeding the percentile envelope.
- **Fix:** the lateral envelope is now computed from the pooled VERTICAL
  PROJECTION PROFILE (sum over Y per column for the X bounds; sum over X
  per row for the Y envelope) of the FOG-FREE wood core — the upper share
  of the calibrated wood window (`LAT_CORE_FRAC = 0.2`), which by
  construction excludes the fog band sitting at the window's lower edge.
  The first/last lane whose projection exceeds a share of the peak lane
  (`LAT_EDGE_FRAC = 0.15`) is the edge — the lines tightly hug the wood.
  The percentile envelope remains only as a fallback; the ortho-plane
  witness adoption (agreement-gated) is unchanged. Top/bottom logic
  untouched and re-verified (the calibrated window floor that fixed
  wood_top=65 still drives the z edges).
- **Files:** `src/core/wood_bounds.py`, `tests/test_wood_bounds.py`
  (regression cases incl. fog-blanket lateral pollution),
  `tests/debug_lines_overlay.py` + `debug/` overlays (verification).

## 2026-09-25 - Fix: Left/Right ROI Alignment #2 (0AF)

- **Why the 0AE fix did not hold (proven by probes):** on the oven-dry
  specimen the wood reads -989..-958 HU (at the window floor), so the
  0AE "fog-free core" (upper 20 % of the window, -892..-500) contains NO
  wood on clean slices and plenty of FOG on blanket slices - the core
  projection was 100 % fog and came out full-frame. The fog-blanket fill
  test could not see those slices either (the wood block itself fills
  ~72 % of the FOV), and the dim fog ring touches the FOV edge on almost
  every slice, so strict per-slice band gates starve the evidence.
- **Fix (per-axis, per-view, decoupled from z):** slices whose outer
  0.5 mm band is >50 % occupied are excluded as fog blankets; the
  remaining slices are projected per lane (`sum(axis=0)` -> X,
  `sum(axis=1)` -> Y); the envelope is the first/last lane above the
  Otsu valley clamped into [0.40, 0.50] x peak (empirically: fog ring
  25-32 % of peak, wood plateau 95-100 %; the prescribed 0.05 threshold
  measured full-frame on all reference specimens). Ortho witnesses use
  the same principle; top/bottom z logic untouched and now carries
  `# LOCKED - CORRECT - DO NOT MODIFY` banners.
- **Verified:** `custom/1-17_OD` `[6,1193]x[6,1191]` ->
  `[97,1111]x[89,1110]`; `24um/1-1` -> `[58,1068]x[64,1081]`;
  `24um/1-15` -> `[63,1075]x[54,1067]`; `66um/1-1` -> `[26,405]x[25,407]`;
  zb byte-identical before/after on all four; synthetic sparse-fog and
  oven-dry scenarios PASS; 12-suite gate PASS; before/after overlays in
  `debug_roi_fix/`. Cache versions: `CACHE_VERSION 19`, `PREV_VERSION 11`.
- **Files:** `src/core/wood_bounds.py`, `src/core/viewer_core.py`,
  `tests/debug_lines_overlay.py`, `tests/test_wood_bounds.py`, `DEV_LOG.md`
  (new single source of truth).
- **Release:** rebuilt ZIP/setup.exe (launcher selfcheck PASS; snapshot
  `cleanCT_v1.0.0\installer\` mirrored); backup
  `0BACKUP/audit_20260925_roi_lateral_r13`.

## 2026-09-25 - Feature: Auto Snap to Detection (0AG)

- **Problem:** the detection -> cut copy step was partial and implicit: a
  fog-deferred air top left Keep at the report value (whole scan), the
  wood-top fallback existed only behind the explicit Snap button, and
  there was no toggle or manual-override state.  The detection itself was
  correct (0AF) and is now frozen.
- **Fix (copy layer only):** new pure module `src/core/auto_snap.py`
  (`detected_lines`: cut = halo onset; keep = air top else wood top,
  clamped below cut; lateral pairs = detected envelope as fractions);
  `Auto snap to detection` checkbox (default ON) in the guide bar;
  `_apply_auto_snap()` copies detection onto Keep/Cut and both lateral
  pairs on every load/re-detect and on toggle-on; any manual edit (spins,
  sliders, viewer drags incl. the newly wired axial Top/Bottom) suspends
  the copy layer until the next detection; checkpoint restores count as
  manual state; the Snap button re-arms.  Detection core carries
  `# STABLE DETECTION - DO NOT MODIFY CORE` (comments only).
- **Docs:** `ROI_LOGIC.md` created - per-view/per-axis detection formulas,
  coordinate systems (`axis=0` vs `axis=1`), the detection vs cut
  distinction, and the auto-snap contract.
- **Files:** `src/core/auto_snap.py` (new), `src/main_window.py`,
  `src/core/wood_bounds.py` (LOCK comments), `tests/test_auto_snap.py`
  (13th gate suite), `tests/debug_snap_overlay.py` + `debug_snap/`
  overlays, `ROI_LOGIC.md`, `DEV_LOG.md`.
- **Verification:** 13-suite gate PASS; `test_auto_snap.py` ALL PASS;
  snap overlays for `24um/1-1`, `24um/1-15`, `66um/1-1` show the snapped
  box identical to the detection envelope and keep = wood-top fallback
  (40/38/15).
- **Release:** rebuilt ZIP/setup.exe (launcher selfcheck PASS; snapshot
  `cleanCT_v1.0.0\installer\` mirrored); backup
  `0BACKUP/audit_20260925_auto_snap_r14`.

## 2026-11-18 — Audit fix plan for cleanCT 1.0.0

- **Export correctness:** DICOM-sourced NIfTI now opens with (x, y, z) voxels;
  derived DICOM series get their own UIDs; verification no longer loads every
  slice's pixels.
- **State safety:** a damaged settings or registry file is kept as
  `<name>.corrupt-<stamp>`; a re-registered specimen ID no longer reuses old
  views; cache folders are pruned; user state never falls back into the install
  folder.
- **Keep, Cut and Snap:** Keep >= Cut is refused by all three export-type
  actions; Snap and Reset now also place the lateral boundaries from the
  detection.
- **Engine:** a failing CuPy step falls back to the CPU for that step, and the
  probe no longer flashes a console window.
- **Release:** the builder publishes `version\cleanCT_v1.0.0\`, and the portable
  ZIP's top folder is `cleanCT-1.0.0`.
- **UI:** the main area renders dark (the palette and Fusion style are applied),
  labels have no pictographs, the audit renames are in (Boundaries, Load scan,
  Export to, Open checkpoint), boundary controls lock during jobs, a re-export
  asks before it replaces a bundle, and Ctrl+O, Ctrl+R, Ctrl+E and Ctrl+S are
  available. The launcher reports start-up failures with the log location.
- Details, files and open items: `DEV_LOG.md` section 2.8.

## 2026-11-18 — Post-audit fixes (WinError 448 report)

- **Setup and elevation:** the setup starts cleanCT as the original user, and the
  launcher warns when it starts as administrator. The builder template keeps the
  setting, and the test checks the template as well.
- **Specimens:** removing a specimen whose link cannot be removed no longer keeps
  its ID registered; a failed cleanup no longer hides the real error; a rename
  moves the processed folder first and moves it back on failure; Windows device
  names are valid IDs with a suffix.
- **Viewer cache:** cache file names cannot collide between specimens
  (`CACHE_VERSION` 21).
- Details, commits and open items: `DEV_LOG.md` section 2.8.
