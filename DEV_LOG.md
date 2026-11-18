# cleanCT - DEV_LOG & Revision History

Single source of truth for the cleanCT project: what the app is, what was
changed and why, the current defect status, how the ROI cut logic works, and
how to verify it.  Companion docs: `REVISION_HISTORY.md` (condensed
changelog), `AUDIT.md` (per-release audit record), `USER_GUIDE.md` (end-user),
`DEV_README.md` (developer setup).

- Checkout (source of truth): `H:\Treated Kyodai samples\cleanCT`
- Release folder: `version\cleanCT_v1.0.0\` in the checkout (the old sibling mirror `H:\Treated Kyodai samples\cleanCT_v1.0.0` is being retired)
- Detection engine (sibling): `H:\Treated Kyodai samples\metal_remover`
- App version: 1.0.0 - app entry `main.py` (PySide6)

---

## 1. Project Overview

cleanCT is a PySide6 desktop application for micro-CT analysis of degraded
wood specimens (Kyodai degradation study).  It loads a specimen's DICOM
series, previews the reconstruction in three orthogonal views, strips the
metal hardware with the external `metal_remover` engine, lets the operator
place the four ROI cut guides, and exports the cleaned ROI as DICOM / NIfTI
with a JSON sidecar.

### 1.1 Layout

```
cleanCT/
  main.py                  app entry (thin launcher)
  src/
    main_window.py         main window: specimen panel, job flow, prefs view,
                           context menus, checkpoint sessions
    core/
      viewer_core.py       payload builder + disk caches; version constants
                           PREV_VERSION=11 / CACHE_VERSION=19 /
                           ORTHO_CACHE_VERSION=3 (bumped by detection changes)
      wood_bounds.py       metal-anchored, air-refined detection of the four
                           cut lines (this is the "auto guides" brain)
      auto_snap.py         pure detection -> cut-line copy layer (0AG)
      bundle_export.py     delivery bundles (DICOM series / NIfTI / sidecar)
    widgets/
      viewer_2d.py         2D slice + ortho viewer with draggable guides
      specimen_panel.py    searchable specimen list, metadata rows
    dialogs/properties_dialog.py
  data/                    runtime state (registry, caches, settings, logs)
  installer/               build_installer.py, cleanct.iss, staged _pkg, out/
  tests/                   regression gate + suites + tools (venv_notorch/)
  assets/icons/            app icons (production .ico embedded in launcher)
  0BACKUP/                 per-round full-system audit backups (zips)
  debug/ debug_roi_fix/    generated diagnostics (not shipped)
```

### 1.2 Runtime model (short)

1. `viewer_core.build_payload(dataset, sample)` reads metadata + a slice
   pool, builds the sagittal/coronal ortho column stacks, runs
   `wood_bounds(...)`, and caches the payload (mtime-keyed; version
   constants gate stale caches).
2. `wood_bounds` returns the wood envelope `{y0,y1,x0,x1}` + z lines
   `zb{keep,cut,wood_top,wood_bottom,top_ok}` + `margins` (edge distances)
   + `evidence` (audit trail).
3. `main_window` converts the envelope to fractions and pushes them into
   `viewer_2d.setAutoBounds` (x/y guide pairs) and `setAutoZ` (dotted
   Keep/Cut reference); the job's solid Keep/Cut lines auto-place onto the
   detected values, after which manual drags win until the next specimen.
4. Metal stripping + export run through the engine; delivery is a clean
   DICOM series (`<specimen>_dcm/`), `<specimen>.nii`, `<specimen>.json`.

### 1.3 Coordinate systems (the part that keeps biting)

- Volumes are read as 2-D axial slices indexed `[row, col] = [y, x]`.
- Stack order is `z` (slice index) ascending.
- **In an axial slice**: `axis=0` = rows = **Y**, `axis=1` = columns = **X**.
  - `m.sum(axis=1)` -> per-row counts -> **horizontal projection** -> Y envelope.
  - `m.sum(axis=0)` -> per-column counts -> **vertical projection** -> X envelope.
- **In a sagittal ortho plane** `(z, y)`: `axis=0` = z, `axis=1` = **Y**.
- **In a coronal ortho plane** `(z, x)`: `axis=0` = z, `axis=1` = **X**.
- Lateral guide pairs are per-axis, not per-view: the *Y pair* is drawn
  horizontally on the sagittal view and vertically on the axial view; the
  *X pair* horizontally on the coronal view and horizontally on the axial
  view.  One value per axis keeps all three views consistent.
- `margins` = edge distances `[lo, H-1-hi]`; the box side is
  `H-1-margin_hi` (sign inversion!).  Getting this wrong silently swaps or
  doubles a line (found in the debug tool, fixed 0AF).

---

## 2. Changelog (Chronological)

### 2.1 [2026-09-24] 0AA - Checkpoint session hardening
- **Problem:** checkpoint save/load sessions could reconnect stale mounts,
  duplicate history rows, and accepted bogus 8.3 short paths.
- **Root cause:** snapshot handle never unmounted; history keyed on raw path
  string; short-path (8.3) tokens not canonicalized.
- **Fix:** unmount on close; de-duplicate history entries; canonicalize
  paths (`Path.resolve()`); selfcheck verifies the embedded icon resource.
- **Files:** `src/main_window.py`, `installer/build_installer.py`.
- **Verification:** suite gate + backup round
  `0BACKUP/audit_20260924_checkpoint_hardening_r8`.

### 2.2 [2026-09-24] 0AB - Structured checkout + specimen panel
- **Problem:** flat checkout mixed sources, data and backups; specimen list
  was a plain list with no search/filter/metadata.
- **Root cause:** initial prototype layout.
- **Fix:** move code under `src/`, assets under `assets/icons`, runtime under
  `data/`, tests under `tests/`; specimen panel gains search/filter, metadata
  rows, context menu, busy spinner; QThread GC crash fixed.
- **Files:** whole checkout restructure; `src/widgets/specimen_panel.py`,
  `src/main_window.py`, `tests/*`.
- **Verification:** 11-suite gate; screenshots; backup
  `0BACKUP/audit_20260924_structured_overhaul_r9`.

### 2.3 [2026-09-24] 0AC - Clean export naming + DICOM metadata + snap pipeline
- **Problem:** exported DICOM filenames carried `_rem_`; metadata was sparse;
  the Keep/Cut snap could land off the detected lines.
- **Root cause:** legacy naming from the engine era; delivery tags only
  copied a few fields; snap mapped panel coordinates across an extra
  conversion (off-by-one/cross-space drift).
- **Fix:** strip `_rem_` everywhere; write full patient/study/series tags +
  `PixelSpacing`/`SliceThickness`/`ImageComments`; keep ORIGINAL slice
  filenames in `<specimen>_dcm/`; sidecar records `keep_from`; snap pipeline
  recomputed in one coordinate space.
- **Files:** `src/core/bundle_export.py`, `src/main_window.py`,
  `src/widgets/viewer_2d.py`.
- **Verification:** export suite + real-specimen checks; backup
  `0BACKUP/audit_20260924_final_polish_r10`.

### 2.4 [2026-09-24] 0AD - Wood top 692 -> 65 + text clipping
- **Problem:** auto wood-top on the user's oven-dry `1-17_OD` landed at
  slice 692 (should be 65); several controls clipped their text.
- **Root cause:** `_object_mask` used the generic `AIR_HU_DEFAULT = -900`
  floor when no calibrated window was passed, erasing drier wood
  (-990..-900 HU) -> the top edge walked hundreds of slices too deep.
  UI: stacked buttons/compact chips/title duplication/log wrap.
- **Fix:** when a calibrated wood window exists its **lower bound replaces
  the generic air floor** (`wood_bounds._object_mask`); drag handlers clamp
  `pref_cut`/`pref_keep` to the spin range; Save/Load checkpoint buttons
  stacked; compact GPU chip; title de-duplicated; log wraps.
- **Files:** `src/core/wood_bounds.py`, `src/main_window.py`,
  `src/widgets/viewer_2d.py`.
- **Verification:** payload path gives `wood_top=65`, snap lands
  `cut=1022 / keep=65`; gate PASS; backup
  `0BACKUP/audit_20260924_woodtop_fix_r11`.

### 2.5 [2026-09-24] 0AE - Left/Right attempt #1 (core-window projection)
- **Problem:** Left/Right lines did not fit the wood on the oven-dry
  specimen (full-frame).
- **Attempted fix:** a "fog-free core" = upper 20 % of the calibrated window
  (`LAT_CORE_FRAC`), pooled column/row projections, lanes above 15 % of peak.
- **Files:** `src/core/wood_bounds.py`, `tests/test_wood_bounds.py`,
  `tests/debug_lines_overlay.py`.
- **Verification:** synthetic *sparse*-fog test passed; real specimen
  overlay still full-frame.  **Later proven insufficient - see 0AF.**

### 2.6 [2026-09-25] 0AF - Left/Right fix #2 (edge-band-gated projections)
- **Problem:** on `custom/1-17_OD` the Y box is `[6, 1193]` and the X box
  `[6, 1191]` of `(H,W)=(1200,1198)` - i.e. full frame; the visible wood
  block edge sits at ~90..1105 px (7.5 %..91 %).  Same on `24um/1-1`
  (`[6,1116] x [6,1126]`).  Top/Bottom are correct and must not regress.
- **Root cause (proven by probe, not guessed):**
  1. The specimen is **oven-dry**: wood reads **-989..-958 HU**, i.e. at the
     *floor* of the calibrated window `(-990,-500)`.
  2. The 0AE "core" window `(-892,-500)` therefore contains **no wood on
     clean slices** (core mask empty, `mean=0.000`), but **fog blanket
     slices contain plenty of core pixels** (z=1032: core `mean=0.143`,
     extent `(6,1193,6,1191)`; z=1066: core `mean=0.807`).  The "core"
     projection was 100 % fog -> edge lanes > 15 % of peak -> full frame.
  3. `_fog_blanket` (>60 % FOV fill) cannot identify those slices here
     because the real wood block itself fills **~72 %** of the FOV, so clean
     slices also score 0.72-0.80.
  - Net: the lateral envelope was driven by fog geometry, not wood geometry.
- **Fix (decoupled per-axis, no shared state, no pixel constants):**
  - Per pooled slice, a **fog-blanket gate**: a slice whose outer physical
    band (`LAT_EDGE_CLEAR_MM = 0.5 mm` on all four sides) is more than
    half occupied is a full-FOV fog blanket and is excluded from the
    lateral evidence (z evidence untouched).  Blankets are excluded
    *geometrically* because their HU overlaps the oven-dry wood.
  - Each axis then gets its own **vertical/horizontal projection** of the
    full wood mask over the contributing slices: `sum(axis=0)` for X,
    `sum(axis=1)` for Y - independently of the z logic.
  - Envelope = first/last lane above the **Otsu valley** of the lane
    distribution, clamped into `[LAT_EDGE_FRAC=0.40, LAT_KNEE_HI=0.50]`
    of the peak lane.  Empirical calibration on the reference fleet: the
    dim fog ring around a block carries 25-32 % of peak, the wood plateau
    95-100 %.  (The originally prescribed `0.05 * max` was measured on
    all four reference specimens: every one came out full-frame; 0.40-0.50
    lands within 1-3 px of the visible edge.)  Relative, scale-free.
  - The ortho witnesses (sagittal->Y, coronal->X) use the same principle
    (blanket-gated rows + projection + Otsu knee) and stay
    adoption-gated by agreement, so all three views share one consistent
    value per axis.
  - Top/Bottom code is untouched and now carries
    `# LOCKED - CORRECT - DO NOT MODIFY` banners.
  - Debug tool X side fixed (`W-1-margin_hi`, was drawn at the margin);
    deterministic percentile display window; before/after overlays and
    JSON readbacks written to `debug_roi_fix/`.
- **Files:** `src/core/wood_bounds.py`, `src/core/viewer_core.py`
  (CACHE_VERSION 19 / PREV_VERSION 11), `tests/debug_lines_overlay.py`,
  `tests/test_wood_bounds.py` (oven-dry regression case).
- **Verification (2026-09-25):**
  - `custom/1-17_OD`: `y [6,1193], x [6,1191]` -> `y [97,1111],
    x [89,1110]` (visible block edge ~90..1105).  zb byte-identical:
    `wood_top=28 wood_bottom=1066 keep=10 cut=1074`.
  - `24um/1-1`: `[6,1116]x[6,1126]` -> `[58,1068]x[64,1081]`;
    zb `40/1014, keep=None, cut=1007` unchanged.
  - `24um/1-15`: `[62,1075]x[60,995]` -> `[63,1075]x[54,1067]`
    (right side now covers the wood the old percentile had clipped);
    zb `38/1005, cut=1006` unchanged.
  - `66um/1-1`: `[2,428]x[2,426]` -> `[26,405]x[25,407]`;
    zb `15/377, cut=378` unchanged.
  - `tests/test_wood_bounds.py`: both scenarios PASS - sparse-fog
    margins `[40,40]x[50,20]` and oven-dry `[30,30]x[30,30]`, exactly
    the block outlines.
  - Full 12-suite gate PASS (exit 0); visual before/after overlays in
    `debug_roi_fix/`.
  - Release rebuilt (12-suite gate PASS inside the builder; launcher
    selfcheck exit 0): ZIP 329,423,098 B SHA-256 `3a486491...df1483`;
    setup.exe 205,936,459 B SHA-256 `ef4acb35...c13d7b`; launcher
    6,343,337 B SHA-256 `b0045873...ddce14`; release snapshot
    `cleanCT_v1.0.0\installer\` mirrored (0 mismatches); backup
    `0BACKUP/audit_20260925_roi_lateral_r13` (215 files, CRC + per-file
    hashes PASS).

### 2.7 [2026-09-25] 0AG - Auto Snap to Detection + ROI logic documentation
- **Problem:** detection was correct but the load-time copy layer was
  partial and implicit: a fog-deferred air top left Keep at the report
  value (whole scan), the wood-top fallback existed only behind the
  explicit Snap button, there was no master toggle, and no state that
  distinguished "lines currently hold the detection" from "user edited".
- **Root cause:** the copy step was a strict `_auto_place_detected_lines`
  call inside the load path; no shared mapping module, no suspension
  semantics, no toggle.
- **Fix (copy layer only - detection core frozen):**
  - new pure module `src/core/auto_snap.py`:
    `detected_lines(bounds, allow_wood_top_fallback=True)` maps the frozen
    detection onto cut/keep (wood-top fallback, keep<=cut clamp) and the
    lateral pairs `(x0/W, (x1+1)/W)` / `(y0/H, (y1+1)/H)`.
  - `main_window`: `Auto snap to detection` checkbox (default ON) in the
    guide bar; `_apply_auto_snap()` copies detection onto ALL four sides
    (Keep/Cut + both lateral pairs) on every load/re-detect and on
    toggle-on; any manual edit (spins, sliders, viewer drags incl. the
    newly wired axial Top/Bottom drags) suspends the copy layer until the
    next detection; checkpoint restores count as manual state; toggle OFF
    keeps the stored lines + neutral 15/85 pairs; the explicit Snap button
    re-arms. No hidden offsets; the physical margins stay inside the
    detection constants, `Margin Above Cut` and air-crop are separate
    layers (documented).
- **Files:** `src/core/auto_snap.py` (new), `src/main_window.py`,
  `src/core/wood_bounds.py` (LOCK comments only),
  `tests/test_auto_snap.py` (new, 13th gate suite),
  `tests/debug_snap_overlay.py` (new), `ROI_LOGIC.md` (new),
  `tests/run_cleanct_regressions.ps1`.
- **Verification:**
  - `tests/test_auto_snap.py`: ALL PASS - pure mapping (cut/keep, fallback,
    strict mode, clamping, pair validation) + offscreen window (load
    applies; deferred air top lands on the wood top and says so in the
    log; manual edit suspends; re-detect re-applies; toggle off keeps
    stored lines + neutral pairs; toggle on applies; checkpoint restore
    suspends; unprocessed pre-process load applies).
  - Full 13-suite gate PASS (exit 0).
  - `debug_snap/` overlays for `24um/1-1`, `24um/1-15`, `66um/1-1`:
    dashed detection envelope == solid snapped box
    (`24um/1-1` X 64..1081 Y 58..1068; `24um/1-15` X 54..1067 Y 63..1075;
    `66um/1-1` X 25..407 Y 26..405), keep = wood-top fallback
    (40/38/15 - the air-top curtain deferred on all three), cut =
    1007/1006/378.
  - Release rebuilt (13-suite gate PASS inside the builder; launcher
    selfcheck exit 0): ZIP 329,425,926 B SHA-256 `62af1bb6...b2bc08`;
    setup.exe 205,958,325 B SHA-256 `1c3a7a26...cf47729`; launcher
    6,342,402 B SHA-256 `ae27bb5f...a3f2af`; snapshot
    `cleanCT_v1.0.0\installer\` mirrored; backup
    `0BACKUP/audit_20260925_auto_snap_r14` (218 files, CRC + per-file
    hashes PASS).

---

### 2.8 [2026-11-18] Audit fix plan (cleanCT 1.0.0 audit + UI polish)
The audit and the fix plan are applied in order from the baseline commit
`e34ed17`. The focused gate (`tests/run_cleanct_regressions.ps1`) was run after
every task and passed each time. The engine (`metal_remover`) is versioned in
its own repository, with its baseline at `fc8dbae`.

- **T1 NIfTI axis order (DICOM sources).** Problem: a DICOM-sourced NIfTI opened
  scrambled. Root cause: the streamed and legacy writers declared `(n_keep, ny,
  nx)` and wrote planes with y fastest; the affine and the TIFF writer use
  `(x, y, z)`. Fix: header `(nx, ny, n_keep)`, planes transposed; verification
  reads z at `shape[2]`. Files: `src/core/bundle_export.py`,
  `tests/test_nifti_roundtrip.py` (new), `tests/test_export_formats.py`,
  `tests/test_pipeline_synthetic.py`, `tests/test_export_stream.py`.
- **T2 Output root.** Problem: a run started as `runtime\python.exe app\main.py`
  wrote to the build machine's H: drive. Fix: `paths.ensure_output_root()` for
  installed runs; `main.py` calls it, and `--selfcheck` prints the output root.
  Test: `tests/test_launcher_paths.py`.
- **T3 DICOM UIDs.** Problem: a derived series shared the scan's UIDs, and
  re-exports shared one series UID. Fix: a new SeriesInstanceUID per export and a
  new SOPInstanceUID per slice, with `SourceImageSequence` pointing at the source
  slice; verification matches through that reference. Test:
  `tests/test_export_formats.py` (UID checks).
- **T4 Verification memory.** Problem: verification loaded every output slice
  with pixels (about 16 GB for 2,000 slices of 2k x 2k). Fix: header-only reads;
  pixels for the three spot checks, one at a time. Test: a `dcmread` spy in
  `tests/test_export_formats.py`.
- **T5 Properties.** Problem: `NameError: human_size`. Fix: import it. Test:
  `tests/test_specimen_panel.py` runs the real handler.
- **T6 Settings and registry.** Problem: a damaged file was read as empty and the
  next save overwrote it. Fix: damaged files are kept as
  `<name>.corrupt-<stamp>`, settings saves are atomic, odd JSON shapes and
  entries without a specimen ID are handled. Test: `tests/test_state_files.py`
  (new).
- **T7 Closing during a job.** Problem: a job that finished during close started a
  loader, a failed job opened a box on the hidden window, and the GPU probe
  reference was dropped while its thread ran. Fix: early returns while closing;
  the GPU reference is cleared from the thread's `finished` signal. Test:
  `tests/test_render_async.py`.
- **T8 Keep >= Cut.** Problem: Export and Process & Export accepted an empty
  range. Fix: `_valid_keep_cut()` guards all three actions and drives the range
  label. Test: `tests/test_render_async.py`.
- **T9 Junctions.** Problem: `cmd /c mklink` split paths at `&`; a moved source
  left a junction that `exists()` cannot see, so the id could not be registered
  again. Fix: `_winapi.CreateJunction`, `os.rmdir` for removal (it deletes only
  the link), and a moved junction is repointed. Test: `tests/test_state_files.py`.
- **T10 GPU fallback (engine).** Problem: a CuPy kernel compile error or out-of-
  memory failed the whole specimen; the probe flashed a console window. Fix:
  `run_gpu_or_cpu()` in `metal_remover/gpu_backend.py`, used by
  `metal_remover/wood_track.py`. A failing step disables CUDA for the rest of the
  run and is recomputed on the CPU; the probe runs with `CREATE_NO_WINDOW`.
  Test: `tests/test_pipeline_synthetic.py` (stand-in backend; no GPU needed).
- **T11 Checkpoint restore.** Problem: a preview still in flight for the previous
  specimen could be filed under the restored name. Fix: the restore bumps the
  preview generation first. Test: `tests/test_render_async.py`.
- **T12 Test hygiene.** Every test puts `src/` on the path, so the tests run
  directly. The gate suites use `ensure_engine_on_path()`, not the live engine
  folder. The three real-data scripts exit 0 with SKIP unless
  `CLEANCT_REAL_DATA=1`; the two that write output also refuse unless
  `CLEANCT_DATA` and `CLEANCT_OUTPUT_ROOT` are temp folders. `test_nometal_e2e`
  cleans up under `CLEANCT_OUTPUT_ROOT`. `test_fleet_adaptive` is read-only
  against the real outputs, so it does not require temp folders; it fails when
  no report is found.
- **T13 Small fixes.** Natural sort (`_natural_key`; the old regex had matched a
  literal backslash). The Left and Right boundaries share one helper and stay
  **4 points** apart, the band the viewer already enforces, so the spin, the
  slider and the viewer agree (the plan's example of 1 point was changed to
  match the viewer). The job box hides on one timer that a new job stops. The
  `report.json` reads use UTF-8.
- **T14 Release layout.** The builder publishes `version\cleanCT_v1.0.0\`: the
  portable ZIP and its sidecar, the setup installer when built,
  `README_INSTALLER.txt`, `USER_GUIDE.md`, `THIRD_PARTY_NOTICES.md` and
  `RELEASE_NOTES.md`. The copies go through `.tmp` files and the copied ZIP is
  hashed again. The portable ZIP's top folder is `cleanCT-1.0.0` (was `_pkg`).
  `setup_env.ps1` checks each `pip` exit code. The backup script no longer
  collects `dist\cleanCT-app`, `metal_remover\build` or `scripts`, and skips
  `version\`. `RELEASE_NOTES.md` is the old sibling README with its `H:` paths
  made relative; the `version\` folder is git-ignored, so keep that file safe.
- **T15 Cleanup and state.** Duplicate and dead code removed; one custom-source
  lookup (`_custom_source_path`); the 3-D viewer uses the 2-D colormap table
  (the grayscale start moves from (25, 28, 35) to (18, 20, 26), so the 3-D view is
  slightly darker). **Behaviour change:** Snap and Reset now use the auto-snap
  copy layer (`_apply_auto_snap`), so they also place the lateral X/Y bounds from
  the detection and clear the preview dirty flag. Viewer cache keys carry the
  registered source identity (`CACHE_VERSION` 20); superseded cache files are
  pruned after each write (data\cache had reached 300 files, 371 MB); removing or
  renaming a specimen drops its in-memory views. An unwritable user state folder
  falls back to `<temp>\cleanCT`, not the install folder.
- **T16 UI polish.** Theme tokens and roles (`theme.set_role`), a Qt palette and
  the Fusion style (without them the main area rendered white on this PC), no
  inline colour styles left in `src/`, no pictographs in labels, `&&`
  mnemonics, and the renames: Boundaries, Load scan, Export to, Open checkpoint,
  "+3 vs manual"; KPI titles in sentence case; sidebar grouping (About in the
  brand header, one checkpoint row); contextual empty text; boundary controls
  locked during a job; a re-export asks before it replaces a bundle (default
  No); Ctrl+O, Ctrl+R, Ctrl+E, Ctrl+S. Launcher: a non-zero exit within 20 s of
  start shows the log location. Tests: `tests/test_specimen_panel.py`,
  `tests/test_launcher_paths.py`.

Verification (final build, 2026-11-18): the full builder ran with the gate (PASS
inside the builder), a fresh PyInstaller launcher (self-check PASS), the
portable ZIP (6,689 entries, top folder cleanCT-1.0.0, CRC clean, SHA-256 equal
to its sidecar) and the release folder version\cleanCT_v1.0.0 (ZIP, sidecar,
README_INSTALLER.txt, USER_GUIDE.md, THIRD_PARTY_NOTICES.md, RELEASE_NOTES.md).
Extracted ZIP: cleanCT.exe --selfcheck exit 0, and the log reports the output
root under %LOCALAPPDATA%\cleanCT\pipeline_output. Packaged GUI smoke PASS.

Post-audit fixes (WinError 448 report, same day):
- **Setup starts cleanCT as admin (likely root cause; not reproduced here).** The
  setup's "Launch cleanCT" box ran the app elevated. An elevated process cannot
  follow the junctions the app makes for loaded scans, so each load failed with
  WinError 448. The entry now runs as the original user (`runasoriginaluser`,
  commit `717a306`), and the launcher warns when it starts elevated. The builder
  template had dropped the flag, so every rebuild would have undone it; the
  template is fixed and the guard checks it too (`59cd71d`,
  `tests/test_installer_script.py`).
- **A specimen whose link cannot be removed.** The registry entry is deleted
  first, so a stuck link no longer keeps the ID registered (`df7448b`,
  `remove_specimen`).
- **A failed cleanup hides the real error.** When the pipeline check of a new
  DICOM link fails, a failed removal of the link is logged, and the validation
  error is what the user sees (`a3b8732`, `register_series`). Four junctions
  from earlier failed loads (`2-5`, `2-8`, `1-9_cleaned`, `2-21_cleaned`) are
  still in the state folder with no registry entry; they are safe to remove.
- **Cache names could collide.** Cache file names joined the key parts with
  "_", so pruning specimen `x` could delete the cache of `x_y`. Names now use
  "~"; older names are removed as regenerable; `CACHE_VERSION` is 21 (`df7448b`).
- **Rename order.** The processed folder moves before the registry changes. A
  locked folder stops the rename with a message; a failed registry write moves
  the folder back. Tests: `tests/test_specimen_panel.py` [3c] and [3d]
  (`a3b8732`).
- **Rename into existing results** is refused before anything changes, and a
  name that sanitizes to the current ID is a no-op (`d1b9400`, `a3b8732`).
- **Windows device names.** IDs such as CON, NUL, AUX, COM1 to COM9 and LPT1 to
  LPT9 get a `_scan` suffix, because Windows cannot create those folders
  (`d1b9400`).
- **Open:** the design depends on NTFS junctions. Not changed here; it needs a
  decision (see the audit report).

Verification (rebuild after the post-audit fixes): the builder's gate PASS and the
launcher self-check PASS. The portable ZIP has 6,689 entries under
`cleanCT-1.0.0`, its CRCs are clean, and its SHA-256 equals the sidecar. The
packaged sources contain the fixes. The setup was compiled from the regenerated
`installer\cleanct.iss`, which has `runasoriginaluser`. It has not been installed
on this PC, so the launch behaviour is covered by `tests/test_installer_script.py`,
not by a run.

Open items and deliberate deviations:
- **Setup installer built:** `cleanCT-1.0.0-setup.exe` (208 MB, SHA-256
  `3cb20ae2…26f7`). Install it once to confirm that cleanCT starts as the normal
  user and that the scans from the report load.
- **Sibling mirror `H:\Treated Kyodai samples\cleanCT_v1.0.0`** (about 1.3 GB)
  is still present. It is removed only on explicit confirmation.
- Painted image overlays (7 to 8 pt, drawn over the scan) were left as they are.
- The plan's backlog (about 25 smaller findings and the structural splits) is not
  done in this pass.
- The interactive checks in plan section D.7 were not run by hand. The same
  behaviour is covered offscreen by the gate and by `tests/capture_screens.py`.

### 2.9 [2026-11-18] Installed-app investigation, audit fixes, UI redesign
- **Release rebuilt (2026-11-18, after the redesign).** The builder's gate passed
  and the launcher self-check passed. The portable ZIP has 6,690 entries under
  `cleanCT-1.0.0`, CRCs are clean, and its SHA-256
  (`82c3a5c0…d6a1`) equals the sidecar. The packaged sources contain the
  redesign (activity drawer, light palette) and the single-window guard. The
  setup (`cleanCT-1.0.0-setup.exe`, 208 MB, SHA-256 `71896b6c…22ec`) was compiled
  from `installer\cleanct.iss`, which has `runasoriginaluser`. It has not been
  installed in this session. The stale rollback from the killed build was removed
  by the builder.
- **Installed-app load failure (not reproduced; open).** The installed copy
  (`C:\Program Files\cleanCT`, all fixes present) was tested from this PC with
  its own runtime and engine, in a normal session, with the state folder
  redirected to a temp folder: scan registration, junction reads and the full
  process run (register, then `tomograph.process_sample`) all succeed. The
  Start-menu and desktop shortcuts do not request administrator rights, and the
  launcher manifest is `asInvoker`. `H:` is a local fixed NTFS drive, not a
  network mapping. The failure the user reports therefore depends on a condition
  this PC does not have: an elevated start, another account or PC, or another
  start path. The exact error text and the start method are needed to settle it.
- **Specimen ids capped at 48 characters** (`MAX_SPECIMEN_LEN`). Output paths add
  about 70 characters; Windows refuses paths over 260 unless long paths are
  enabled, which is not the default. This PC has `LongPathsEnabled=1`, so the
  limit is not visible here (`src/core/custom_series.py`).
- **Network-share scans refused with a plain message** (`is_local_folder`). A
  junction must point to a folder on this PC; before, the user saw a raw
  `[WinError 3]`. The mapped-drive case is covered by `GetDriveTypeW`.
  Not tested against a live share: no share was reachable from this PC.
- **One window at a time** (`src/core/single_instance.py`, a named mutex in
  `main.py`). Two windows rewrite the same registry, so one could drop the
  other's scan.
- **Builder removes rollbacks of killed builds** (`prune_stale_rollbacks`). A
  killed build left about 745 MB in `installer\_cache`.
- **UI redesign** (`src/theme.py`, `src/main_window.py`, `DESIGN.md`,
  `PRODUCT.md`). Two palettes, dark default and light, switched under
  Preferences > Appearance and saved in `settings.json`. Teal is the one accent.
  The metrics strip sits flat under the title; export controls have their own
  row; the Activity log is a drawer; long text wraps; each page scrolls sideways
  when narrower than the page needs. Window minimum width fell from about 2,486
  px to about 1,250 px. Tests: `tests/test_theme.py` (WCAG AA for every text pair
  in both themes), `tests/test_specimen_panel.py` (switch and saved choice).

## 3. Current Known Bug (As of Now)

### 3.0 Detection status (0AG): STABLE - frozen
- Top/Bottom and Left/Right detection are correct and defined on every
  reference specimen (0AF).  The detection core
  (`core/wood_bounds.py`) carries `# STABLE DETECTION - DO NOT MODIFY CORE`
  and is frozen; cut-line padding/offsets/margins belong to the copy layer
  (`core/auto_snap.py` + `main_window`), never to the core.
- Full detection/cut logic reference: `ROI_LOGIC.md` (per-view, per-axis,
  formulas, coordinate systems).

### 3.1 Left/Right cut lines NOT fitted to the wood ROI - **RESOLVED in 0AF**
- **Observed (before fix):** lateral box at the frame edge on all views of
  the oven-dry specimen and on the other reference specimens:
  - `custom/1-17_OD`: `y [6,1193]`, `x [6,1191]` of `1200x1198` (0.5 %..99.4 %).
  - `24um/1-1`: `y [6,1116]`, `x [6,1126]`.
  - `66um/1-1`: `y [2,428]`, `x [2,426]`.
- **Affected views:** Sagittal, Coronal, Axial (all draw from the same two
  lateral axis pairs).
- **Status after 0AF (measured):** `custom/1-17_OD` -> `y [97,1111]`,
  `x [89,1110]`; `24um/1-1` -> `[58,1068]x[64,1081]`; `24um/1-15` ->
  `[63,1075]x[54,1067]`; `66um/1-1` -> `[26,405]x[25,407]` - all hugging
  the visible wood outline (before/after overlays in `debug_roi_fix/`).
  The former `LAT_CORE_FRAC` core-window mechanism is removed.
- **Watch item:** any new specimen with wood HU overlapping the window floor
  AND a fog ring/blanket must be checked with
  `tests/debug_lines_overlay.py`; the oven-dry scenario in
  `tests/test_wood_bounds.py` encodes the failure mode synthetically.

### 3.2 LOCKED and correct - do not regress
- **Top/Bottom for Sagittal & Coronal = CORRECT.**
  - Keep line = top of the contiguous non-air curtain minus the physical
    safety margin, adopted only over verified clear air (`_curtain_top`).
  - Cut line = the pipeline's detected halo onset (`det_cut`) else base top
    else one past the wood bottom.
  - Wood top/bottom = contiguous `_edge_walk` from the pooled main run.
  - These code paths carry `# LOCKED - CORRECT - DO NOT MODIFY` and their
    outputs (`zb.keep/cut/wood_top/wood_bottom`) are compared before/after
    every lateral change (must be byte-equal).

---

## 4. ROI Cut Logic Documentation

There are **four sides**: Keep (top z), Cut (bottom z), Left (lo lateral),
Right (hi lateral).  They are computed on different axes and MUST stay
independent - the lateral code never reads a z variable and vice versa.

### 4.1 Common pipeline (`wood_bounds`)

1. **Mask** - `_object_mask(vals, air, wood_window, metal_hu)`: wood =
   `finite AND window[0] <= v <= window[1] AND v < metal`.  With a
   calibrated window `window[0]` IS the air/wood boundary (0AD fix).  Then
   `_close` (0.15 mm), `binary_fill_holes`, `_largest_components` (physical
   min-area gate).
2. **Axial pool** - up to 32 slices spread over the trusted z-window
   (track_z / anchor / cut bounds), read in batches.
3. **Z-window anchor** (`_metal_anchor`): metal slab seen by BOTH sagittal
   and coronal ortho planes, fused to the detector anchor when known; the
   halo guard sets the highest trustworthy slice.

### 4.2 Top = Keep line (z) - **LOCKED**
- Pool flags -> largest gap-tolerant run -> `_edge_walk` from inside the run
  toward the top, contiguous, stops at the first air slice -> `wood_top`.
- `_curtain_top` scans upward from `wood_top` for any non-air material;
  Keep = curtain top minus `KEEP_AIR_MARGIN_MM`, adopted only when
  `KEEP_CLEAR_MM` of contiguous clear air was verified above.
- If no clear air (fog curtain reaches the scan top) -> `keep=None`
  (defer to report/default) and `fog_defer=True`.
- **Never touched by lateral changes.**

### 4.3 Bottom = Cut line (z) - **LOCKED**
- `_edge_walk` down from inside the run -> `wood_bottom`.
- Anchor inside the wood run clamps `wood_bottom` to `anchor_top - 1`.
- Cut = `det_cut` (pipeline halo onset) when known, else anchor top, else
  `wood_bottom + 1`.

### 4.4 Left/Right (lateral, per axis) - 0AF algorithm
- For each pooled **non-blanket** slice (fog-blanket gate, 4.4.1):
  - `col_proj` += `m.sum(axis=0)`  -> per-column counts -> **X envelope**
  - `row_proj` += `m.sum(axis=1)`  -> per-row counts    -> **Y envelope**
- `_projection_lane_bounds(proj)`: first/last lane above
  `thr = clip(Otsu(proj), 0.40 * peak, 0.50 * peak)`.
  - The lane distribution is bimodal on the real fleet: dim fog ring
    25-32 % of peak, wood plateau 95-100 %; Otsu finds the valley, the
    clamp keeps it on the valley for unimodal/full-width wood.
  - `0.05 * max` (prescribed) was measured to fail: every reference
    specimen came out full-frame because the ring clears 5 %.
- Fallback (too little evidence): 20th/80th percentile of per-slice
  extents of the contributing slices.
- Ortho witnesses: sagittal plane -> Y, coronal plane -> X, computed with
  the same blanket-gated column projection; a witness value is adopted
  only when its side has physical clearance and it agrees with the axial
  value within `WITNESS_AGREE_MM = 1.5 mm`; otherwise the axial value
  stands (conservative: never cuts into wood, at worst leaves a little
  air).

#### 4.4.1 Slice fog-blanket gate (the geometric fog filter)
- Band = outer `LAT_EDGE_CLEAR_MM = 0.5 mm` on all four sides of the slice
  (converted via the voxel size: 20 px at 24.85 um, 8 px at 66 um).
- A slice contributes to the lateral evidence when its band occupancy is
  `<= LAT_BLANKET_FRAC = 0.50` - full-FOV fog blankets touch the edge on
  every side (fill > 50 % of the band), while wood slices with a dim fog
  ring (5-30 %) pass and are later handled by the Otsu knee.
- Excluded slices still count for the z logic (`present`, `fog_by_z`) - the
  gate filters ONLY lateral evidence.

#### 4.4.2 View mapping
| View | Horizontal axis | Vertical axis | Left/Right lines | Top/Bottom |
| --- | --- | --- | --- | --- |
| Sagittal | Y (`axis=1` of `(z,y)`) | Z | Y pair from sagittal plane projection (axial Y as primary + witness) | Z Keep/Cut, LOCKED |
| Coronal | X (`axis=1` of `(z,x)`) | Z | X pair from coronal plane projection (axial X as primary + witness) | Z Keep/Cut, LOCKED |
| Axial | X (`axis=1` of `(y,x)`) | Y (`axis=0`) | X pair | Y pair (same lateral algorithm) |

One physical value per axis pair => all views consistent by construction.
Manual drags win after load; plane switches only swap which pair is shown.

### 4.5 Detection -> cut lines copy layer (0AG)
- `core/auto_snap.detected_lines(bounds)`: `cut = zb.cut`,
  `keep = zb.keep` else `zb.wood_top` (fallback, clamped below cut),
  `x = (x0/W, (x1+1)/W)`, `y = (y0/H, (y1+1)/H)`.  Pure, no Qt.
- `main_window._apply_auto_snap()` applies it to the spins + viewer pairs on
  every load/re-detect and on toggle-on; manual edits suspend it until the
  next detection; `Auto snap to detection` checkbox (default ON) is the
  master switch; the explicit Snap button re-arms.
- The detection core is FROZEN (`# STABLE DETECTION - DO NOT MODIFY CORE`).
  Full reference incl. formulas and coordinate systems: `ROI_LOGIC.md`.

---

## 5. Test Checklist

### 5.1 Automated gate (must be ALL PASS before any release)
`tests\run_cleanct_regressions.ps1` - 13 suites (exact runner order):
1. `test_checkpoint_file.py` - checkpoint document schema, save/load,
   reconnect canonicalization.
2. `test_viewer_regressions.py` - viewer geometry: I/O batching, HU rescale
   byte-equivalence, synthetic volume rendering.
3. `test_render_async.py` - offscreen rendering, async workers, startup
   IO suppression, checkpoint reconnect.
4. `test_specimen_panel.py` - specimen panel search/filter/rows/actions.
5. `test_wood_bounds.py` - detection invitations: sparse-fog + oven-dry
   lateral envelope, calibrated z semantics (0AE/0AF).
6. `test_auto_snap.py` - copy layer: pure mapping + offscreen window
   apply/suspend/toggle/checkpoint behavior (0AG).
7. `test_unproc_and_frames.py` - unprocessed previews, Pillow-12 frame
   downscale, pre-process detection.
8. `test_export_formats.py` - clean naming (no `_rem_`), full DICOM tags,
   sidecar, transactional bundle.
9. `test_export_stream.py` - streamed NIfTI/DICOM writes, failed stream
   releases resources.
10. `test_pipeline_synthetic.py` - synthetic end-to-end pipeline runs.
11. `test_volume_inputs.py` - DICOM/TIFF/NIfTI validation and clean
    failure on empty/corrupt/truncated inputs.
12. `test_launcher_paths.py` - packaged launcher output/state routing.
13. `test_installer_icons.py` - staged icon assets byte-identical, Qt load.

### 5.2 0AF-specific checks (manual, evidence kept in `debug_roi_fix/`)
- [x] `custom/1-17_OD`: before `[6,1193]x[6,1191]` -> after
      `[97,1111]x[89,1110]` (visible wood edge ~90..1105 px).
      Top/Bottom identical before/after (`28/1066, keep=10, cut=1074`).
- [x] `24um/1-1` `[6,1116]x[6,1126]` -> `[58,1068]x[64,1081]`;
      `24um/1-15` `[62,1075]x[60,995]` -> `[63,1075]x[54,1067]`;
      `66um/1-1` `[2,428]x[2,426]` -> `[26,405]x[25,407]`;
      `zb.wood_top/wood_bottom/keep/cut` byte-equal before/after on all.
- [x] Oven-dry synthetic case in `test_wood_bounds.py` (dense blanket, wood
      at window floor, block fills ~64 % FOV) passes - margins `[30,30]`.
- [x] Sparse-fog synthetic case (0AE) still passes - margins `[40,40]`,
      `[50,20]` (exact block outline).
- [x] Overlay X-side drawn at `W-1-margin_hi` (not at the margin value);
      display window deterministic (slice percentiles).

### 5.3 0AG-specific checks (manual, evidence kept in `debug_snap/`)
- [x] Auto snap default ON: a fresh load copies detection onto Keep/Cut and
      both lateral pairs (`test_auto_snap.py` window cases).
- [x] Deferred air top falls back to the detected wood top and the action
      log records "(wood top; air top deferred)".
- [x] Manual edit suspends the copy layer (logged once); the next
      detection re-applies and re-arms; the Snap button re-arms.
- [x] Toggle OFF: stored lines + neutral 15/85 pairs; toggle ON applies
      immediately.
- [x] Checkpoint restore suspends auto-snap (restored lines win).
- [x] `debug_snap/` overlays: dashed detection envelope == solid snapped
      box on all 3 Kyodai specimens; keep = wood-top fallback on all 3.
- [x] Detection core frozen: only `# STABLE DETECTION - DO NOT MODIFY CORE`
      comments were added; `test_wood_bounds.py` invariants unchanged.

### 5.4 App-level sanity after any detection or copy-layer change
- [ ] Fresh specimen load: detection guides logged; auto-snap log entry
      shows the applied values and the keep source.
- [ ] Sagittal/Coronal/Axial views draw the same pair values.
- [ ] Manual drags clamp and persist per plane; new specimen re-adopts
      (auto-snap re-arms on the next detection).
- [ ] Delivery unaffected: Process & Export with no edits uses the fresh
      detection; edits deliver the on-screen lines.
- [ ] Launcher `--selfcheck` exit 0; payload byte-identical to `src/`.
