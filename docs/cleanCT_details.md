# cleanCT 1.0.0: implementation details

This document explains how cleanCT 1.0.0 is built and how each part works: loading a scan, finding the guide lines, the Boundaries and Results views, processing, export, checkpoints, the installer and the tests. It describes the released 1.0.0 code at commit 69987da (branch ui/full-view-redesign, 2026-11-19), with the processing engine at metal_remover commit 2a53ba6.

Where a number was measured on a real specimen in an earlier round, the text says so. The history of each round is in DEV_LOG.md.

How to read it: sections 1 to 4 give the big picture. Sections 5 to 9 cover specimens, the Boundaries lines and the copy layer. Section 10 covers processing. Sections 11 to 14 cover the Results view, export, checkpoints and settings. Sections 15 to 18 cover the look, the installer, the tests and the reference checkpoint. Section 19 is a code map. Section 20 lists the known limits and open items found while writing this update.

## 1. What cleanCT does

- cleanCT is a Windows desktop app built with PySide6 (Qt 6). It reviews micro-CT scans of wood that sits on a metal mounting base.
- It finds the metal base and the wood, shows four guide lines, and lets the user adjust them. Processing then removes the metal base with the metal-remover engine. Export writes a result bundle.
- Inputs: a DICOM series (one folder of .dcm slices), a TIFF stack (one multipage file, or a folder of matching grayscale slices), or a 3-D NIfTI file (.nii or .nii.gz).
- Output: one bundle folder per specimen. For DICOM sources it holds a DICOM series of the kept slices and a NIfTI volume. For TIFF and NIfTI sources it holds a NIfTI volume only. Every bundle also holds a JSON sidecar and a plain-text extraction report.
- Source scans are never changed. Registering a scan keeps a reference to it: a folder junction for DICOM, a file path for TIFF and NIfTI. The scan is not copied.
- The app works offline on one PC. It uses an NVIDIA GPU through CuPy when a compatible driver is present. Without one it runs the CPU path, which gives the same results.

## 2. Layout

### 2.1 The checkout

| Path | What it holds |
|---|---|
| main.py | Entry point. Starts the GUI, or runs the --selfcheck health check. |
| src\main_window.py | The main window, about 5,000 lines: the three tabs, the sidebar, jobs, export, checkpoints and settings. |
| src\core\ | Logic with no Qt widgets (no core module imports PySide6). See section 3.1. |
| src\widgets\ | viewer_2d.py (the 2-D viewer that draws the lines), viewer_3d.py (point cloud), kpi_banner.py, specimen_panel.py (sidebar list). |
| src\dialogs\ | load_dialog.py, properties_dialog.py, about_dialog.py. |
| src\theme.py | Dark and light colour tokens, the stylesheet and the palette. |
| src\icon_utils.py | Window and taskbar icons, and the Windows app ID. |
| assets\ | app.ico and app_icon_256.png (window icon), assets\icons\ (the production icon pack, packaged), assets\design\ (design source archive, not packaged). |
| installer\ | build_installer.py, launcher_main.py, cleanct.iss, setup_env.ps1, README_INSTALLER.txt. Generated folders: _pkg\, _cache\, out\. |
| tests\ | Regression suites, run_cleanct_regressions.ps1, tools, screenshots\, venv_notorch\ (the test interpreter; not versioned). |
| version\ | Release folder cleanCT_v1.0.0\ (portable ZIP, setup, notes) and RELEASE_NOTES.md. |
| data\ | User state of development runs: settings, registry, cache, exports, logs. Not versioned. |
| dist\, 0BACKUP\, debug\ | An older reference build, hashed snapshots and debug overlays. Not versioned. |
| codebase\ | Reference checkpoint of the code. See section 17. |
| docs\cleanCT_details.md, docs\cleanCT_details.docx | This document, in Markdown and Word. |
| README.md | GitHub front page: features, installation, build and structure. |
| docs\ | User guide (ships with the app), release notes, this document, and the change records (DEV_LOG, REVISION_HISTORY, AUDIT, ROI_LOGIC). |
| PRODUCT.md, DESIGN.md | Design context; kept at the root for the design tools. |

### 2.2 The engine

The engine is the `engine\` folder of the checkout. The app imports six of its modules. The installer copies the same six into the package.

| Module | Role |
|---|---|
| tomograph.py | The pipeline: dataset registry, configuration, volume loading, the metal anchor and halo cut, wood tracking, air crop, output files and the report. |
| roi_delivery.py | Reads and sorts DICOM, writes the DICOM ROI series, the NIfTI writers (including the streamed stripped volume) and the provenance record. |
| wood_track.py | Tracks the wood slice by slice (seed, then footprint walk up and down) and crops by footprints. |
| air_crop.py | Trims near-pure-air margins from the tracked wood box. |
| gpu_backend.py | Chooses and checks the compute backend: PyTorch CUDA, then CuPy, then NumPy and SciPy. Preloads the NVRTC library. |
| volume_io.py | Readers for TIFF and NIfTI that give one float32 volume in (z, y, x) order. Estimates intensity thresholds for non-HU sources. |

### 2.3 The installed package

| Folder | Contents |
|---|---|
| cleanCT.exe | The windowless launcher (PyInstaller, one file). |
| app\ | main.py, main_window.py, theme.py, icon_utils.py, core\, widgets\, dialogs\, icons\. |
| engine\ | The six engine modules. |
| runtime\ | An embedded CPython 3.12.3 with pinned wheels: numpy, scipy, PySide6 (Essentials), pydicom, nibabel, Pillow, matplotlib, scikit-image, and CuPy with its NVRTC wheel. PyTorch is not included. |

In the checkout the app sources live under src\. In the package they sit directly under app\. That is why main.py adds both paths to the import path.

### 2.4 Two roots

| Item | Development checkout | Installed |
|---|---|---|
| App sources | checkout\src | app\ next to cleanCT.exe |
| Engine | the checkout's engine\ folder (CLEANCT_ENGINE overrides it) | engine\ next to cleanCT.exe |
| User state (settings, registry, cache, exports, logs) | checkout\data | %LOCALAPPDATA%\cleanCT |
| Processing outputs | metal_remover\output (custom specimens: output\custom\<id>) | %LOCALAPPDATA%\cleanCT\pipeline_output |
| Source scans | never changed | never changed |

The environment variables that change these roots are CLEANCT_ENGINE (engine folder), CLEANCT_DATA (state folder) and CLEANCT_OUTPUT_ROOT (processing outputs). The regression gate sets all three to a scratch folder.

## 3. Architecture

### 3.1 Modules

- main.py starts the application. It runs the self-check when asked, sets the Windows app ID and the theme, and starts MainWindow.
- main_window.py assembles the whole window from the widgets in src\widgets and the dialogs in src\dialogs. It calls the core modules for all data work.
- core\viewer_core.py makes previews, the axial frames, the 3-D cloud and the payload that the Results view shows. It holds the caches.
- core\wood_bounds.py finds the four guide lines. Its header says it is frozen (section 7).
- core\auto_snap.py is the copy layer. It maps the detected values onto the Keep, Cut and L/R lines (section 8).
- core\custom_series.py is the registry of loaded specimens and the junctions that link DICOM folders.
- core\bundle_export.py writes and checks the export bundle.
- core\checkpoint_file.py reads and writes checkpoint files.
- core\paths.py finds the engine, the state folder and the output folder. core\lateral.py turns a lateral pair into pixels. core\single_instance.py keeps one window open. core\user_messages.py turns pipeline errors into plain messages.

### 3.2 Threads

- Slow work runs on a WorkerThread (a QThread). It has three signals: succeeded (a dict), failed (a message) and progress (done, total, phase).
- Work that uses a worker: loading a specimen (viewer_core.build_payload), the processing and export jobs, the Boundaries preview, the Results longitudinal preview and the GPU probe.
- viewer_core.LOCK is a re-entrant lock. Payload builds and previews take it, so they never change the shared caches at the same time.
- Latest request wins. The Boundaries preview numbers each request. If a worker is still running, the newest request is kept as the one pending request, and older results are dropped. The Results longitudinal preview works the same way with its own key.
- Debounce: the Boundaries preview waits 180 ms after the last change. The Results longitudinal view waits 150 ms.

### 3.3 Caches

| Cache | Where | Limit | Key and version |
|---|---|---|---|
| Last payload | memory (_CACHE) | one entry | dataset, specimen and the modification times of the stripped and wood ROI files |
| Payload on disk | state cache folder, .npz | superseded files are removed | CACHE_VERSION 23 |
| Preview sources | memory | 3 entries and 1 GiB of arrays | PREV_VERSION 11 |
| Original slices | memory | 256 slices per key, 2 keys, 512 MiB per specimen | the source identity |
| Ortho columns and planes | disk and memory | 12 planes kept in memory | ORTHO_CACHE_VERSION 3 |

The payload key includes the modification times of the stripped and wood ROI files. Processing a specimen again therefore rebuilds its payload. Temporary cache files older than one hour are removed.

### 3.4 Settings file

- The file is state\settings.json. It is written to a temporary file first, then renamed, so a crash cannot leave half a file.
- Keys: save_root (export folder), export_format (dicom, nifti or both), checkpoint_dir (start folder for Save and Open checkpoint), theme (dark or light).
- A damaged file is renamed to settings.json.corrupt-<time> and the app starts with defaults.

## 4. Startup, self-check and launcher

### 4.1 Start-up order (main.py)

1. Set the output root for installed runs.
2. If --selfcheck was given, run the health check and exit.
3. Set the Windows app ID and the window icon.
4. Stop a second copy: a named mutex (Local\cleanCT-main-window). A second start shows a message and exits.
5. Set the Fusion style, the theme from settings, and the window and taskbar icons.
6. Create MainWindow, centre it, show it, and set the native icon.

### 4.2 The self-check (cleanCT.exe --selfcheck)

It prints the Python version, the app root, the engine folder, the state folder, the output folder and whether the install is detected. It checks the app.ico file. It imports numpy, scipy, pydicom, nibabel, Pillow, tifffile, cupy and PySide6, and prints each version. It imports the six engine modules, prints the GPU decision, and creates a Qt widget offscreen. It prints PASS (exit 0) or FAIL (exit 2).

### 4.3 The launcher (installer\launcher_main.py)

- The launcher has no app logic. It finds app\main.py, engine\tomograph.py and runtime\python.exe next to itself.
- It sets CLEANCT_ENGINE and starts runtime\python.exe -X utf8 app\main.py.
- Its output goes to a rotating log (5 MB) in %LOCALAPPDATA%\cleanCT\logs. If the state folder is unavailable, it uses the logs folder next to the program.
- If the payload is damaged (for example, an antivirus quarantined a file), it shows a Windows message box.

## 5. Specimens: loading and the registry

### 5.1 Accepted sources

| Source | Accepted | Checks |
|---|---|---|
| DICOM | A folder holding one .dcm series, or its immediate parent holding one series folder. | Headers are read. At least 12 slices (MIN_SLICES). The series must sort through the pipeline's reader, through the junction, with the same slice count. The folder must be on this PC. |
| TIFF | One multipage grayscale .tif or .tiff file, or a folder of grayscale TIFF slices of the same size. | Colour TIFFs and mixed stacks are refused. If physical spacing is missing, the geometry is marked as assumed. |
| NIfTI | One 3-D .nii or .nii.gz file. | Four-dimensional data is refused. Affine and stored scaling are read. A .nii.gz file is expanded to temporary storage first. |

The intensity option matters for TIFF and NIfTI sources. Auto-detect estimates the thresholds from sampled stored values and reports them as stored intensity. "Stored values are already HU" treats the stored values as Hounsfield units. DICOM always uses its rescale metadata.

A DICOM junction can only point to a folder on a local drive. UNC paths and mapped network drives are refused, with a message that says to copy the scan to this PC first.

### 5.2 Registering a scan

- DICOM: validate the folder, make the specimen ID unique, check that the folder is local, create the junction at <state>\custom\data\<id>\XY, and check the sort through the junction. If the check fails, the junction is removed and nothing is registered.
- TIFF and NIfTI: validate the file or folder and store its path. No junction is made.
- The new entry is written to the registry file.

### 5.3 Specimen IDs

- Letters, digits, underscore and hyphen are kept. Any other character becomes an underscore. Leading and trailing underscores are removed.
- At most 48 characters (MAX_SPECIMEN_LEN). An empty result becomes "specimen".
- Windows device names (CON, PRN, AUX, NUL, COM1 to COM9, LPT1 to LPT9) get the suffix _scan.
- If the ID is taken, a suffix _2, _3 and so on is added. An existing specimen is never overwritten.

### 5.4 The registry file

The registry is <state>\custom\registry.json. Each entry holds:

- specimen: the ID.
- dataset_key: always "custom".
- source_kind: dicom, tiff or nifti.
- source_path and source_folder: where the scan is.
- source_metadata: the validation result (size, spacing, geometry notes).
- config_overrides: settings the pipeline receives for this specimen.
- added: the registration time.

The starting overrides depend on the pixel size:

| Pixel size class | roi_seed_min_area | roi_min_area | platform_min_voxels | min_onset_slope_hu |
|---|---|---|---|---|
| 24 µm class (35 µm or less) | 20000 | 400 | 20000 | 0.15 (default) |
| 66 µm class (up to 80 µm) | 7500 | 150 | 7400 | 0.5 |
| Other sizes | scaled from 24 µm by pixel area, never below 300 | scaled, never below 50 | scaled, never below 1000 | 0.15 (default) |

For TIFF and NIfTI entries, save_dicom is set to false. After Apply, the registry also stores cut_override, keep_from and cut_margin_slices (section 8.3).

### 5.5 Managing the list

- Rename (F2): the registry ID changes. The DICOM junction folder is renamed too. The processed output folder is renamed too, and the change is rolled back if that fails. Built-in specimens cannot be renamed.
- Duplicate: the same source is registered under a new ID. No scan data is copied, and the DICOM junction points to the same folder.
- Remove (Del): the registry entry is removed first, then the junction. Sources, processed results and exports are kept.
- A built-in specimen that is removed from the list is hidden until the app restarts.
- Clear loaded list: removes every loaded entry after a confirmation.
- Context menu: Open, Rename, Duplicate, Show in Explorer, Properties, Remove, and Load scan.

### 5.6 Built-in specimens

Two datasets come from tomograph.py: 24um (scan folder "24 micro", outputs in the output root) and 66um (outputs in output\66um). They are processed the same way as loaded specimens. They have no registry entry.

## 6. The Boundaries tab

### 6.1 Layout

The tab has two columns.

- Left, the preview panel titled "Original scan". It has the plane buttons Sagittal, Coronal and Axial, an Interactive Guides check box, the colour map, the 2 Lines (Z range) and 4 Lines (Box Bounds) buttons, Snap to detection, the preview image, and a slider labelled z=, x= or y=.
- Right, "Cut and range controls". It has the Top line (keep start) and Bottom line (platform cut) spin boxes and sliders, and Margin above cut (slices kept back from the Cut). In 4-line mode it also shows Left X, Right X, Top Y (axial box) and Bottom Y (axial box). Below that are the density thresholds (Min HU, Max HU, and the presets Full, Wood Tissue, High Contrast, Platform Metal, Reset). It ends with Auto-crop to wood (air detection), Auto snap to detection, the delivery summary, Reset to detected and Apply lines.

Defaults: the plane is sagittal, the colour map is grayscale, Interactive Guides and Auto snap are on, and Auto-crop is on.

The thresholds change the preview only. They do not change the scan.

### 6.2 The lines on screen

| On screen | Colour and style | Where it is drawn | What it is | Set by |
|---|---|---|---|---|
| Keep: N | green (#37d67a), dashed, with handles | across both panels; the badge sits on the After side | the first kept slice (keep_from) | the copy layer (wood top), or the user |
| Cut: N | red (#ff463c), dashed, with handles | across both panels; the badge sits on the After side | the cut slice (cut_from); slices at and below it are removed | the copy layer (metal top), or the user |
| Wood Top N | green, dotted, no handles | the Before side, label at the left | the detected wood top (zb.wood_top) | detection only |
| Air Top N | green, dotted | the Before side | used only when a payload has no wood top (zb.keep) | detection only |
| Metal Top N | orange (#ff9f43), dotted | the Before side | the detected metal top (zb.metal_top) | detection only |
| L and R | blue (#4f8cff), dashed, with handles and L x% and R x% badges | vertical lines in the sagittal, axial and coronal views | the lateral box (section 7.5) | the copy layer, or the user |
| Top Y and Bottom Y | green, dashed | horizontal lines in the axial view | the Y pair of the lateral box | the copy layer, or the user |

Two detector values are not drawn. The halo onset (zb.cut) is reported in the panel but has no line, because the Cut sits on the metal top. The margin has no line either: the kept panel of the preview ends at Cut minus margin, which is where the delivery ends.

When the Keep and Cut lines are closer than one label, the Cut label moves down under the Keep label, so the two never overlap. The guide labels are drawn last, so no job line crosses them.

### 6.3 Editing the lines

- A line moves by dragging its handle, typing in its spin box, or moving its slider. All three paths note a manual edit.
- A manual edit pauses Auto snap until the next detection. The next detection is a load, Snap to detection, Reset to detected, or switching Auto snap on again.
- Keep stays above the delivered cut (Cut minus margin). Auto snap clamps Keep to Cut minus 1. A Keep at or above the delivered cut blocks Process, Export and Process and export, with the message "Keep line must be above the Cut line (keep < cut)."
- Left stays at least 4 % below Right. Top Y stays at least 4 % above Bottom Y. Both use LATERAL_MIN_GAP_PCT = 4.
- Snap to detection applies the copy layer to the lines again. If the specimen has no detection evidence, the lines stay as they are and the Activity log says so.
- Reset to detected sets the margin to 0 and applies the copy layer. If there is no detection, it falls back to the detected cut and a Keep of 0.
- Apply lines saves the values for this specimen and processes it again (section 8.3).

### 6.4 What the preview shows

- The preview is produced by viewer_core.get_preview. It is an image of the original scan in the chosen plane, 640 px wide, with the colour map and window applied.
- It has two panels: the original (left) and the kept result (right). The kept panel keeps only the slices from Keep to the delivered cut (Cut minus margin) and the columns or rows inside the L/R box. The rest is blank.
- Nothing is written to disk. Coordinates are clamped to the scan.
- The image carries no text and no job lines. The panel names (BEFORE (Original) and AFTER (Stripped)) are drawn by the app in front of the image, the same as in the Results view.

### 6.5 Scrubbing

| Plane | Slider scrubs | Label |
|---|---|---|
| Sagittal | X: one column of every slice | x=N |
| Coronal | Y: one row of every slice | y=N |
| Axial | Z: one slice | z=N |

For DICOM sources, viewer_core._ortho_plane reads the column or row across all slices in batches. One plane takes about 0.5 s on a 576-slice series. It keeps up to 12 planes. For TIFF and NIfTI sources, the sagittal and coronal views show the middle plane only, so the slider has no effect there.

## 7. Detection of the four lines

This section describes the frozen detection core, core\wood_bounds.py. Its header reads "STABLE DETECTION - DO NOT MODIFY CORE". Its outputs are read-only geometry. It never changes the pipeline or the delivered files. All physical sizes are given in millimetres or micrometres and converted to pixels with the voxel size. So a 6 µm scan and a 120 µm scan behave the same.

### 7.1 The four lines at a glance

| Line | What it is | Axis | Detected by | Copy layer value | Export effect |
|---|---|---|---|---|---|
| Wood top (Keep) | Top of the wood, where the kept range starts | Z (slice) | wood_bounds, wood top from the axial pool and the edge walk (zb.wood_top) | Keep = zb.wood_top | slices above Keep are not written |
| Metal top (Cut) | Top of the metal base, where the kept range ends | Z (slice) | wood_bounds, metal anchor from the ortho quorum, fused with the detector anchor (zb.metal_top) | Cut = zb.metal_top | slices at and below Cut are not written |
| L and R, axial and coronal | Left and right edge of the wood | X (columns) | lateral projection, confirmed by the sagittal and coronal witnesses | X pair = fractions of the width | DICOM: columns outside the box are removed |
| L and R, sagittal | Left and right edge in the sagittal plane | Y (rows) | lateral projection, confirmed by the ortho witness | Y pair = fractions of the height | DICOM: rows outside the box are removed |

Top and bottom mean the slice direction. In the DICOM slices, rows are Y and columns are X. So the sagittal L/R lines clip rows, and the axial and coronal L/R lines clip columns.

### 7.2 Constants

| Constant | Value | Meaning |
|---|---|---|
| AIR_HU_DEFAULT | −900 HU | Air threshold for the object and air tests |
| WOOD_HU_DEFAULT | (−990, −500) HU | Dense-wood window of the processed pipeline |
| UNPROC_WOOD (viewer_core) | (−960, −500) HU | Wood window before processing (section 7.7) |
| UNPROC_WIN (viewer_core) | (−950, 350, 0) | Display window and metal level before processing |
| BASE_FRAC | 0.12 | A metal base must span at least 12 % of the ortho profile width |
| BASE_MIN_PX | 2 | Absolute floor for the base test |
| ORTHO_COLS / ORTHO_QUORUM | 5 / 2 | Mid-columns probed per ortho plane, and how many must agree |
| HALO_MM | 0.2 mm | Halo guard above the base top |
| POOL_STEP_MM / N_AXIAL_POOL | 0.85 mm / 32 | Spacing and count of the axial pool that measures Z |
| CLOSING_MM | 0.15 mm | Radius of the morphological closing |
| AIR_MIN_AREA_MM2 | 0.15 mm² | Components below this are specks and are ignored, also when alone |
| EDGE_AIR_MAX | 0.05 | An edge slice must be almost air to be adopted |
| FOG_BLANKET_FRAC | 0.60 | An edge slice this full is treated as fog |
| KEEP_SCAN_MM | 6.0 mm | How far above the wood top the air curtain is searched |
| KEEP_AIR_MARGIN_MM | 0.3 mm | Air-top line clearance above the curtain (not used by the copy layer) |
| KEEP_CLEAR_MM | 0.2 mm | Clear air that must be verified above the curtain |
| LAT_EDGE_CLEAR_MM | 0.5 mm | Physical clearance of the lateral lane bounds |
| LAT_BLANKET_FRAC / LAT_EDGE_FRAC | 0.50 / 0.40 | Lateral occupancy thresholds (band full, lane edge) |
| WITNESS_MARGIN_MM | 1.0 mm | Clearance of the ortho witness from the field of view |
| WITNESS_AGREE_MM | 1.5 mm | Axial and ortho lateral estimates must agree within this |
| MIN_PAIR_SPAN (auto_snap) | 0.04 | A lateral pair must span at least 4 % of the axis |

### 7.3 Metal top (Cut): the metal anchor

1. For each sagittal and coronal slice, the code checks whether the metal base spans at least BASE_FRAC of the profile width on each of ORTHO_COLS mid-columns. A slice anchors only when at least ORTHO_QUORUM columns agree on both planes. Straps and pins are thin and cannot pass.
2. If the pipeline gave a detector anchor (the report's anchor_slice), the base is the bottom-most slab run that reaches it. Without one, the bottom-most agreeing run wins.
3. The halo guard (HALO_MM above the base top) keeps the air statistics clean.
4. Output: anchor.z = [top, bottom] and zb.metal_top = top. When a detector anchor exists, zb.metal_top is that anchor. This is the line the user checks against the metal base.
5. zb.cut is the pipeline's halo onset. It is reported in the panel and is not drawn.

### 7.4 Wood top (Keep): the axial pool and the edge walk

1. Over the trusted window (above the base top, below the cut), axial slices are sampled every POOL_STEP_MM, at most 32 slices.
2. Each sampled slice is classified as wood with the wood HU window, metal excluded. The wood mask is closed, its holes are filled, and components below AIR_MIN_AREA_MM2 are dropped. A lone component is checked too.
3. The largest gap-tolerant run of wood slices is the wood body. The edge walk starts inside that run and walks toward the top, contiguously. It stops at the first air slice. That slice is zb.wood_top.
4. The air-curtain guard (EDGE_AIR_MAX) refuses an edge slice that is not clearly air. A foggy edge defers to the previous guide instead of inventing one.

Measured earlier on loaded specimens (not re-measured in this update):

- 2-5, processed: wood top 19. The processed run keeps 19, the same as the auto Keep shown on screen.
- 3_694_7, before processing: wood top 94.
- 2_666_5, before processing: wood top 88.

### 7.5 Air top (curtain): reported, not used as the Keep

zb.keep is the topmost non-air material within KEEP_SCAN_MM above the wood top, minus KEEP_AIR_MARGIN_MM. It is adopted only when KEEP_CLEAR_MM of clear air is verified above that material. It stays in the payload for reference. The copy layer uses it only when keep_on_wood_top is set to false in auto_snap.detected_lines, or when there is no wood top.

### 7.6 L and R lines: the lateral box

1. Each axial slice gives the wood occupancy per column and per row. The lateral lane bounds come from the projection over the pooled slices (_projection_lane_bounds), with the clearance of LAT_EDGE_CLEAR_MM.
2. The ortho witnesses give the mid-column air margins of the sagittal stack (Y) and the coronal stack (X). A witness margin is used only when it agrees with the axial margin within WITNESS_AGREE_MM. Otherwise the axial margin stands, so the line never cuts into the wood.
3. Output: x0, x1 (columns), y0, y1 (rows), and the image size W and H.
4. The copy layer turns them into fractions: x = (x0 / W, (x1 + 1) / W) and y = (y0 / H, (y1 + 1) / H). A pair must span at least 4 % of its axis.

Measured earlier on loaded specimens (not re-measured in this update), before processing:

- 3_694_7: X pair 2 % to 97 % (shown as L 2 % and R 97 % in the coronal view); Y pair 14 % to 80 % (L 14 % and R 80 % in the sagittal view).
- 2_666_5: X pair 1 % to 96 %; Y pair 17 % to 82 %.

### 7.7 Before processing and after processing

| | Before processing (Not processed state) | After processing |
|---|---|---|
| Z range | the whole scan (cut = n) | the report's cut and keep, after Apply |
| Metal anchor | ortho quorum only | the detector anchor from the report, fused with the ortho quorum |
| Halo onset | none | the report's detected_cut_from |
| Wood window | UNPROC_WOOD (−960, −500) | the report's configuration (default −990 to −500) |
| Wood Z window | the whole scan | the pipeline's ROI track (track_z) |

The −960 HU window before processing was chosen on 2_666_5, where the jar's halo lies between −990 and −960 HU at the top of the scan. The processed bounds keep the report's window. The code notes this as a shortcut: pre-process only.

### 7.8 Processed values on record

These values come from the processing reports in the installed app's output folder, %LOCALAPPDATA%\cleanCT\pipeline_output\custom (checked in this update):

| Specimen | Cut | Keep | Detector cut | Metal anchor | Scan slices |
|---|---|---|---|---|---|
| 2-5 | 402 (user override) | 19 | 353 | 405 | 428 |
| 2_666_5 | 501 | 0 | 501 | 515 | 576 |
| 3_694_7 | 507 | 0 | 507 | 511 | 576 |

For 2-5, the user's override (402) replaced the detector cut (353). The metal anchor is 405.

## 8. The copy layer: auto_snap

### 8.1 The rule

core\auto_snap.py is a pure mapping. It never measures anything.

- cut = cut_target(zb): zb.metal_top when the payload has it, else zb.cut.
- keep = zb.wood_top. Without a wood top, zb.keep is used. Keep is clamped to cut minus 1.
- x and y: the lateral fractions from section 7.6. A pair with a span under 4 % is refused.
- The result is a dict with cut, keep, keep_source, x and y. A value that could not be found is None, and the caller keeps its previous value.

### 8.2 When it runs

- On load, when Auto snap is on, the copy layer places the lines.
- When Auto snap is switched on.
- On Snap to detection and on Reset to detected.
- A manual edit pauses it (section 6.3). It resumes on the next detection.

### 8.3 What each action delivers

| Action | Keep and Cut used | L/R box used | Stored |
|---|---|---|---|
| Apply lines (Boundaries) | the on-screen values; the delivered cut is Cut minus margin | the on-screen values | cut_override, keep_from and cut_margin_slices in the registry; the pipeline runs again |
| Process (Ctrl+R) | the stored values from the last Apply (delivered cut = Cut minus margin) | not used | none |
| Export (Ctrl+E) | the on-screen Keep and the delivered cut; refused when the delivered cut is past the processed cut | the on-screen box (DICOM, NIfTI and volume) | none |
| Process and export | the on-screen values, applied and processed first, then exported | the on-screen box (DICOM, NIfTI and volume) | the same as Apply |

The Results view shows the Lines changed marker when the on-screen Keep or delivered Cut differs from the processed run (section 11.3).

## 9. Processing

### 9.1 The job

- Every job runs on a WorkerThread. While it runs, the buttons that start jobs, the sidebar and the history list are disabled. The job box shows the phase, the progress bar and the time left.
- Process and Apply lines: the progress is staged. Captions show each stage, and the bar follows the expected time.
- Export: the progress comes from the export itself (the DICOM slices, the NIfTI slices, the sidecar and the check).
- Process and export: one job. Processing takes the first part of the bar, and the export takes the rest. If processing fails, nothing is exported.
- There is no Cancel. A running pipeline cannot be stopped (limit 10).

### 9.2 What the job sends to the engine

_run_pipeline_task builds the configuration like this:

1. It starts from the specimen's stored overrides (registry config_overrides). For built-in specimens it starts from the dataset defaults.
2. Every job passes the Auto-crop check box as air_crop, read on the GUI thread before the job starts. Apply lines and Process and export also pass the on-screen cut_override, keep_from and cut_margin_slices. Whatever the source of the cut_override (stored or on screen), the engine receives Cut minus margin (the delivered cut).
3. It sets io_workers to 16. For a loaded specimen it sets save_stripped_nii to true, so the full-field stripped volume is written.
4. It takes the GPU backend with preference "auto".
5. It calls tomograph.process_sample(name, cfg, dataset, diagnose_only=False, gpu, verbose=False).

### 9.3 What the engine does (tomograph.process_sample)

1. Load the volume as float32 (z, y, x). DICOM uses the pipeline's reader. TIFF and NIfTI use volume_io. For non-HU sources the thresholds are estimated from the stored values.
2. Count the metal voxels in each slice (HU above metal_hu = 0) and the mean HU of the bottom 40 % of rows in each slice. These run on the GPU when it is active.
3. Find the platform cut. The anchor is the bottom run of slices with a large metal cross-section. The halo onset is the first slice whose bottom-row HU rises above the baseline by halo_delta_hu (2 HU) with a genuine onset (a 3-slice slope of at least 0.15 HU, or a rise of at least 3 HU within 15 slices). The cut is that slice plus cut_margin_slices. A cut_override replaces this result. The app sends the delivered cut (Cut minus margin) as the override.
4. Make a host copy and set every slice at and below the cut to NaN.
5. Optional curtain voiding (curtain_removal). It is off, so air above the wood is kept.
6. Track the wood slice by slice. The window is −990 to −500 HU. The seed is the first slice from the centre outward with a large solid component that does not touch the border. The walk moves up and down. A footprint must overlap the previous one by at least 50 %.
7. Crop the tracked footprints to one box, with 6 voxels of padding. Clamp z at the cut minus 1, and trim the box to keep_from.
8. Optional air crop (air_crop_hu −900; at least 98 % air needed). It trims near-pure-air margins on the field-of-view borders. It never grows the box. On any guard trip it keeps the tracker box.
9. Write the outputs (section 9.4).
10. Write report.json last.

### 9.4 Outputs of a processed run

The output folder for a loaded specimen is <output root>\custom\<id>. A built-in specimen uses its own folder.

| File | When | What it is |
|---|---|---|
| stripped.nii | loaded specimens | the full-field volume with the metal below the cut set to NaN; the bundle reads it |
| wood_roi.nii | save_nifti is on (default) | the tracked wood box, after the air crop if it ran |
| wood_roi_dicom\ and wood_roi_dicom_index.csv | DICOM sources | the engine's own cropped DICOM series |
| wood_roi_provenance.json | every run | the provenance record of the ROI files |
| <id>_qa_removal.png and <id>_qa_roi.png | save_qa_montage is on | quick-look montages |
| report.json | every run | the whole report (below) |

report.json holds: sample, dataset, config (the full configuration), meta (geometry and intensity), gpu, timings_s, platform (cut_from, keep_from, detected_cut_from, anchor_slice, baseline_hu, halo_limit_hu, accepted_by, user_cut_override and others), curtain_rows_voided, wood_roi (track, bbox_zyx, air_crop), metrics, ground_truth and delivery.

### 9.5 Configuration defaults (tomograph.Config)

| Group | Key values |
|---|---|
| Platform anchor | metal_hu 0; platform_min_voxels 20000 (7400 for 66 µm class); platform_min_slices 5 |
| Halo cut | baseline_row_frac 0.40; baseline_z_lo 0.25; halo_delta_hu 2.0; min_onset_slope_hu 0.15 (0.5 for 66 µm class); min_onset_rise_hu 3.0; onset_rise_window 15; anchor_guard_slices 60; cut_margin_slices 0; cut_override None; keep_from 0 |
| Curtain | curtain_removal False |
| Wood ROI | wood_hu_min −990; wood_hu_max −500; roi_min_overlap 0.50; roi_min_shrink 0.40; roi_seed_min_area 20000 (7500 for 66 µm class); roi_min_area 400 (150 for 66 µm class); roi_footprint_dilate 3; roi_exclude_border False; roi_bbox_pad 6 |
| Air crop | air_crop False in the engine (the app turns it on); air_crop_hu −900; air_crop_frac 0.98 |
| Outputs | save_nifti True; save_dicom True; save_qa_montage True; save_stripped_nii False in the engine (the app sets it true for loaded specimens); io_workers 8 in the engine (16 in the app) |

### 9.6 The GPU backend (gpu_backend.py)

- Order: PyTorch CUDA first if it is present, then CuPy, then NumPy and SciPy. A framework counts as active only after a small preflight passes: transfer, comparison, reduction and a float64 mean.
- CUDA_VISIBLE_DEVICES is respected.
- The NVRTC library is preloaded from the pinned wheel (12.8.93) so CuPy finds the right version.
- A CuPy step that fails falls back to the CPU for that step. The CPU path uses the same structures, so the results match.
- The app's sidebar shows the decision in the GPU chip. The self-check prints it too.
- The packaged app contains CuPy and no PyTorch. Machines without an NVIDIA GPU run the CPU path.

## 10. The Results tab

### 10.1 Layout

- Axial pane: "Axial: original and stripped". Before on the left and After on the right, a z slider and the label z=N, and the Lines changed marker.
- Longitudinal pane: "Longitudinal: cut boundary alignment". Sagittal and Coronal buttons (sagittal is the default), an x= or y= slider with its label, and the view.
- 3-D pane: "3D point cloud". Simple (amber wood, silver metal) and Real 3D (wood coloured by the colour map), Spin and Reset view.

### 10.2 Labels and lines

- "BEFORE (Original)" sits on the left panel and "AFTER (Stripped)" on the right panel. The app draws both in front of the image (Viewer2D.setResultsOverlay). The text is not baked into any image in the Results view.
- The Before panel carries the Boundaries lines, without handles and without line labels: Keep and Cut (dashed), the Wood Top and Metal Top guides (dotted), and the L and R lines (blue). In the axial view, the Top and Bottom lines are green.
- The After panel shows only the result. There are no lines on it.

### 10.3 Which values the Results use

- The Results follow the Boundaries lines in both states (pending Keep and Cut, the L/R box, and the guides). So the Before panel matches the Boundaries tab.
- The After panel shows the processed run.
- When the on-screen Keep or Cut differs from the processed run, the Lines changed marker shows. Its tooltip gives the processed cut and keep.
- The Results refresh whenever the Boundaries lines change.

### 10.4 The After crop

- The After panel shows only the slices from Keep to Cut and the columns or rows inside the L/R box. This is the same rule the DICOM export applies.
- Axial: crop_after_panel masks the After image outside the box (main_window._results_crop_axial). Outside Keep to Cut the After panel is blank.
- Longitudinal: the preview is masked the same way (section 6.4).
- Above Keep, the stripped planes keep the air (about −1000 HU). The crop removes it from view.
- The stripped planes equal the original planes inside Keep to Cut. This was checked on 2-5 and 2_666_5 at several positions, with no difference.

### 10.5 The axial view

- Processed specimen: the frames the payload stores. The payload stores at most 16 slices, chosen on an exponential spacing from the first slice toward the end of the scan, and keeps only those below cut + 30. The frames use the bone palette and draw the wood and metal contours. The slider moves through these stored frames, so its steps are not single slices. Its label gives the slice of the frame.
- Unprocessed specimen: one source slice rendered when the slider moves. It uses the grayscale palette.

### 10.6 The longitudinal view

- The view is viewer_core.get_preview at the slider position, with the Boundaries lines and the bone palette. It starts in the middle.
- Sagittal scrubs X and coronal scrubs Y. The label reads x=N or y=N.
- The Before panel shows the original plane, so the metal base is visible. The After panel shows the masked delivery.
- The width is 640 px. Moves are debounced by 150 ms. A stale render is dropped.
- For a raw scan, the view shows the predicted lines and the predicted L/R box, using the same preview.

## 11. Export

### 11.1 Entry points and checks

- Export (Ctrl+E) exports a processed specimen. Process and export (in the sidebar) first applies the lines on screen, as Apply lines does, then processes and exports in one job. So the export is always the run it processed.
- Before a job starts, the app checks, in this order: a specimen is loaded; Keep is above the delivered cut (Cut minus margin); the destination is valid; a replacement is confirmed; the sources can be found; and the report exists. If the report is missing, the message is "This sample has not been processed yet: run Process first."
- A delivery is refused when the delivered cut is past the processed cut, because the processed run holds no data past its own cut. Apply lines and process again, then export.

### 11.2 Destination and format

- Destination: the export folder in Settings > Export. The default is %LOCALAPPDATA%\cleanCT\export (development: data\export). A typed or browsed folder is saved.
- Format for DICOM sources: DICOM + NIfTI (default), DICOM only, or NIfTI only.
- Format for TIFF and NIfTI sources: NIfTI only. The source's voxel values and affine are kept.

### 11.3 The bundle folder

The bundle is <destination>\<id>\. It holds:

| File | Written for | What it is |
|---|---|---|
| <id>_dcm\ | DICOM and DICOM + NIfTI | the kept DICOM slices, under their original file names |
| <id>.nii | NIfTI and DICOM + NIfTI, and all TIFF and NIfTI sources | the kept slices as one NIfTI volume |
| <id>.json | every bundle | the sidecar (below) |
| <id>_extraction_info.txt | every bundle | the plain-text extraction report |

Bundles are built in a staging folder (.<id>.bundle.tmp), checked, and then promoted. The previous bundle is kept as .<id>.bundle.old until the new one is complete. If a promotion was interrupted, the next export restores or removes the old folder. When a DICOM export is re-run as NIfTI only, the existing DICOM series is kept.

A TIFF or NIfTI export refuses a destination that already holds a DICOM bundle with the same ID. This keeps the two kinds of source apart.

### 11.4 The DICOM series

1. Kept slices are the source slices from keep_from to cut_from, minus 1 (not including cut_from).
2. If the L/R box applies, each slice keeps only that box of pixels (`_crop_slice`). The rows and columns are taken from the on-screen values through lateral_range, which rounds to whole pixels.
3. The origin moves to the first kept row and column, using the pixel spacing (rows, then columns) and the two direction vectors of the orientation.
4. Each slice keeps its source tags, plus the delivery tags: PatientName equals the specimen ID; StudyDescription and SeriesDescription name cleanCT; SoftwareVersions is "cleanCT 1.0.0"; ImageComments records the history (up to 1020 characters).
5. Each slice gets a new SOPInstanceUID. It refers to its source slice through SourceImageSequence. The series gets a new SeriesInstanceUID.
6. A compressed DICOM series is refused, with a clear message. Scan series are uncompressed.

### 11.5 The NIfTI volume

- The volume is the stripped volume (stripped.nii) for the kept slices, cropped to the L/R box when one is set. Its header carries a description with the specimen ID and the dataset.
- If stripped.nii is missing (older outputs), the slices are rebuilt from the source DICOM files in bounded batches.
- The NIfTI volume is cropped to the same L/R box as the DICOM series, in X and Y. Its origin moves to the box corner, so the NIfTI and the DICOM describe the same region.
- The NIfTI and the DICOM of one export hold the same voxels in the box, slice for slice. Checked on 2-5_aft: 383 slices, zero difference, and a test in tests/test_export_clip.py.
- A kept plane with no data (blank, NaN) stops the export with an error, and no bundle is written.

### 11.6 Volume sources (TIFF and NIfTI)

- The export writes NIfTI only. The kept slices come from the report's cut and keep, with the source's affine.
- The L/R box is applied in X and Y, as for the DICOM series. Its origin moves to the box corner.

### 11.7 Sidecar and information text

The JSON sidecar (<id>.json) holds: specimen_id, dataset, software, pipeline, cut_from, keep_from, n_slices_kept, n_slices_original, source_folder, source_series_dir, capture_date and capture_time, voxel_mm, slice_thickness_mm, removed_fraction, platform, file_mapping (each DICOM file and its source), nifti (name, shape and description), export_formats, dicom_tags, complete_dicom_properties and the time of writing.

The extraction information text (<id>_extraction_info.txt) is a plain-text summary of the source, the slices kept and the files written.

Both files record the L/R box as fractions: the sidecar has the key lateral_box, and the info text has a line L/R box.

### 11.8 Self-check before promotion

A failed check raises BundleError, and nothing is promoted.

- DICOM: the number of files equals the kept count. Three slices are spot-checked (first, middle and last kept). For each one, the output file is found through its SourceImageSequence, its pixels equal the source pixels inside the L/R box, and PatientName equals the specimen ID.
- DICOM: PatientID, Modality, StudyDescription, SeriesDescription, SoftwareVersions and ImageComments are present, and PixelSpacing and SliceThickness are valid.
- NIfTI: the number of Z slices equals the kept count.

### 11.9 Measured on real data (earlier round)

Slice XY0100.dcm of 2-5 is 458 rows by 449 columns, with 66.212 µm pixels. Cropped in memory with the on-screen values (Y 5 % to 94 %, X 14 % to 80 %), it gives rows 23 to 430 and columns 63 to 358, so 408 rows by 296 columns. The pixels equal the source box exactly. The origin moved by 1.523 mm along Y and 4.171 mm along X, which is 23 and 63 pixels at 0.066212 mm.

## 12. Checkpoints and session history

### 12.1 The file

- A checkpoint is a .ctcheckpoint.json file. Its schema is "cleanct-checkpoint", version 1. It is at most 12 MB.
- The state holds: dataset (24um, 66um or custom), sample, cut, keep, margin, plane (sagittal, coronal or axial), z, n_slices, cmap (grayscale, spectral, thermal, viridis or plasma), lo and hi, bounds (x and y pairs), guide_mode, guides, air_crop, pref_dirty, long_view, axial_idx and tab.
- The preview is stored as a PNG. It is fitted to 1600 px on the longest side when saved, and a preview of up to 8 MB and 2048 px is accepted on load.
- The source path and source kind are stored too.
- Loading validates every field. A file that fails is refused with a plain message.

### 12.2 Save, open and reconnect

- Save checkpoint writes the current preview and its settings. It needs a preview that has finished.
- Open checkpoint restores the preview and the settings at once.
- If the registered source is still at the stored path, the source reconnects, and processing and export work again. If it is missing or moved, the checkpoint opens as a snapshot. The status reads "Snapshot only, source unavailable". The user must register the source again to process or export.
- Save and Open start in the checkpoint folder from settings (checkpoint_dir). Each save or open moves that folder to the folder used.

### 12.3 Session preview history

- "Preview history, this session" lists each applied preview state, in the order applied. Choosing an entry restores it.
- The list is kept in memory until the app closes. It is not written to disk unless a checkpoint is saved.
- An identical state is not added twice in a row. A restored snapshot does not add a new entry.

## 13. Settings tab

- Appearance: Dark or Light. The choice is saved as theme.
- Export: the export folder (Browse, or type a folder; typed folders are saved), and the format (three options, with a line of help under the choice).
- Checkpoints: the start folder (Choose).
- Shortcuts (a reference, not a setting):

| Key | Action |
|---|---|
| Ctrl+O | Load a scan |
| Ctrl+R | Process the selected specimen |
| Ctrl+E | Export the bundle |
| Ctrl+S | Save a checkpoint |
| F2 | Rename the selected specimen |
| Del | Remove the selected specimen from the list |

The Ctrl shortcuts work anywhere in the window. F2 and Del act on the selected specimen in the list.

## 14. The sidebar and the window

- Brand card: "Wood CT metal-base removal" and an About button. The About dialog has links to the User guide (USER_GUIDE.md), the Activity log and the Data folder.
- GPU chip: "Checking GPU…", then the result.
- Specimens: a search box, a count, and the list. Each row shows the kind, slices, dimensions, voxel size and size on disk. Actions: Rename, Copy (duplicate), Find (Show in Explorer), Remove.
- Buttons: Load scan…, Save checkpoint, Open checkpoint, the preview history list, Process, Process and export.
- Job box: the phase, progress, time left, and the Show activity log.
- Export row above the viewers: Export to (the destination, elided if long), the format, Change in Settings, and Export.
- Status bar: the last export status and the preview status.
- Tabs: Results, Boundaries, Settings (at the right end).
- The loading dialog ("Load Custom Volume"): a source file or series folder (File… or Folder…), the Specimen ID (alias), the Intensity interpretation, and Load & Register.

## 15. Look and feel

### 15.1 Theme tokens (dark)

| Token | Colour | Use |
|---|---|---|
| app | #15181d | window background |
| panel | #1b1f25 | sidebar, panels and lists |
| raised | #232830 | fields, hovered rows, segmented groups |
| canvas | #0b0d10 | scan canvases (both themes) |
| text | #e8ebef | primary text |
| text_2, text_3 | #aab2bd, #8b94a2 | secondary text and hints |
| accent | #3fc6b6 | the primary action, active state, and the After label |
| ok, warn, error | #7bd389, #e9b44c, #ef7065 | status |

The light theme has its own token set in theme.py. The stylesheet is built from these tokens, so both themes use the same layout.

### 15.2 Viewer line colours

The line colours are the same in both themes: Keep #37d67a, Cut #ff463c, Metal Top guide #ff9f43, Wood Top guide #37d67a, L and R #4f8cff.

### 15.3 Colour maps

- The user chooses from Grayscale, Spectral, Thermal, Viridis and Plasma. Each uses a gamma of 0.85.
- The Results views use the bone palette. It is internal, not in the user's list. It is the same palette the processed frames use.

### 15.4 Fonts

The UI uses Segoe UI (with Segoe UI Variable as the first choice). Display text uses Bahnschrift. Monospace values use Cascadia Mono.

## 16. Installer and release

### 16.1 The build (installer\build_installer.py)

The build runs these steps in order, and stops at the first failure:

1. Check the toolchain: the checkout (main.py), the application sources, the engine folder, the Windows icon, PyInstaller and ISCC.
2. Remove leftover rollback folders from earlier builds.
3. Run the focused regression gate (run_cleanct_regressions.ps1). The build stops if it fails.
4. Stage the app: the sources under app\, plus the icon pack (every file under assets\icons except README.md), app.ico and app_icon_256.png.
5. Stage the engine: the six modules under engine\.
6. Stage the runtime: the embedded CPython 3.12.3 (checked by its published MD5), the pinned wheels, with tests, documentation and unused Qt and CUDA files removed.
7. Build the launcher from installer\launcher_main.py with PyInstaller (6.22.2 in this release), or reuse the existing launcher with --skip-launcher.
8. Write the package documents: README.txt, USER_GUIDE.md, THIRD_PARTY_NOTICES.md and README_INSTALLER.txt.
9. Run the launcher's --selfcheck on the staged package.
10. Build the portable ZIP and its SHA-256 sidecar.
11. Promote the staged package to installer\_pkg, keeping the old one until everything succeeds.
12. Publish the ZIP and its sidecar, then compile the setup with ISCC (cleanct.iss).
13. Write the release folder version\cleanCT_v1.0.0\.

Each publish step keeps the previous file until the new one is in place, and rolls back on failure.

### 16.2 Outputs

| Output | Where |
|---|---|
| Payload | installer\_pkg\ (cleanCT.exe, app\, engine\, runtime\, documents) |
| Portable ZIP and SHA-256 | installer\out\cleanCT-1.0.0-portable.zip (and .sha256) |
| Setup | installer\out\cleanCT-1.0.0-setup.exe |
| Release folder | version\cleanCT_v1.0.0\ (the ZIP, the setup, README_INSTALLER.txt, USER_GUIDE.md, THIRD_PARTY_NOTICES.md, RELEASE_NOTES.md) |

### 16.3 The setup (installer\cleanct.iss)

- Installs to Program Files\cleanCT (an administrator approval is asked for).
- Compression: LZMA2 maximum, solid. The payload is about 719 MB before compression.
- Optional desktop shortcut. A Start menu entry is always made.
- The app starts after setup as the original user, not elevated. An elevated process cannot follow the junctions (WinError 448).
- Uninstall keeps the logs and state under %LOCALAPPDATA%\cleanCT.

### 16.4 Release 1.0.0

Rebuilt 2026-11-19 from the code at commit 69987da. The engine is at 2a53ba6.

- Portable ZIP SHA-256: 17b8d850570c256eb4ec8c8f3955bfd95aa4a2dd687b22518e47bc8eec992e6a
- Setup SHA-256: 82ecbe382ce1dd0ca11f3b0c25a2ed74b47c53e12209da91ec42e529792be694

For this release, the regression gate (37 suites) and the build's gate passed, the launcher self-check passed, and the extracted portable cleanCT.exe --selfcheck exited with 0 (DEV_LOG 2.24). The application sources in the package were compared with the checkout in section 17.4.

### 16.5 Rebuild commands

- Full release (gate, package, launcher, ZIP and setup): `C:\ProgramData\anaconda3\python.exe installer\build_installer.py`
- Classic setup only: `ISCC.exe installer\cleanct.iss`
- Packaged GUI smoke: `tests\venv_notorch\Scripts\python.exe tests\pkg_gui_smoke.py`
- Health check of the package: `installer\_pkg\cleanCT.exe --selfcheck`

## 17. Tests, tools and the reference checkpoint

### 17.1 The regression gate

tests\run_cleanct_regressions.ps1 runs the focused suites in a fresh scratch folder:

- It copies the six engine modules into the scratch folder, sets the environment (CLEANCT_APP_ROOT, CLEANCT_ENGINE, CLEANCT_DATA, CLEANCT_TEST_TMP_DIR, CLEANCT_OUTPUT_ROOT, QT_QPA_PLATFORM=offscreen, PYTHONUTF8, PYTHONPATH and the temp folders), and runs each suite with tests\venv_notorch\Scripts\python.exe.
- It stops at the first failing suite and prints "cleanCT focused regression suite: PASS" when all pass.
- The scratch folder is removed afterwards. The folder must be inside the temp folder.

The 37 suites, in gate order: test_checkpoint_file, test_viewer_regressions, test_render_async, test_specimen_panel, test_wood_bounds, test_auto_snap, test_unproc_and_frames, test_export_formats, test_export_stream, test_nifti_roundtrip, test_state_files, test_viewer_cache, test_pipeline_synthetic, test_volume_inputs, test_launcher_paths, test_installer_icons, test_installer_script, test_theme, test_user_messages, test_dialogs, test_theme_tokens, test_settings_page, test_layout_fit, test_controls_paint, test_polish_ui, test_robustness_ui, test_bounds_v2, test_auto_z_guides, test_results_sync, test_dialog_close, test_axial_outline, test_export_clip, test_plane_scrub, test_results_crop, test_results_views, test_results_overlay, test_results_slider.

The gate passed on the code of the export and margin fixes (37 suites, exit 0).

### 17.2 Other tests and tools

Suites outside the gate:

| File | What it checks | Why it is outside the gate |
|---|---|---|
| test_fleet_adaptive.py | Metal anchor and guides against the pipeline on the reference specimens | the real fleet scans |
| test_nometal_e2e.py | A metal-free synthetic scan processes cleanly | not in the gate list |
| test_process_delivery_0n.py | The streamed delivery writes match the earlier reference bytes on 2-21 | the real specimen 2-21 |
| test_wood_bounds_scale.py | Detection at 12, 25, 66 and 120 µm agrees in millimetres | not in the gate list |

Tools:

| File | What it does |
|---|---|
| ui_audit.py | Drives every control in each state and checks the invariants after each step. About eight minutes. Last run on this code: 370 steps, 0 findings. |
| ui_probe.py | Walks the widget tree, renders each state at the sizes the window can reach, and times the pipelines. |
| capture_screens.py | Captures the four UI states as PNG evidence (landing, loaded, cutting and history). |
| pkg_gui_smoke.py | Runs the real main window from the package, offscreen. |
| create_audit_backup.py | Writes a hashed snapshot of the sources and release to 0BACKUP. |
| debug_lines_overlay.py, debug_snap_overlay.py | Draw the detected and copied lines on a real slice, for visual checks. |

### 17.3 The reference checkpoint (codebase\)

The codebase\ folder keeps the code the app uses, so a later release can be compared with this one.

- main.py; src\ (every module); assets\app.ico, assets\app_icon_256.png and assets\icons\ (the production icon pack, README excluded); engine\ (the six engine modules from engine\); installer\ (the build script, the launcher source, cleanct.iss, setup_env.ps1 and README_INSTALLER.txt); tests\ (every suite and tool at the top level of tests\, plus run_cleanct_regressions.ps1).
- Not included: the release folders, the installer outputs, the test interpreter, screenshots, the data folder, the caches, and the documents.
- The copy is the released 1.0.0 code at 69987da. CHECKPOINT.txt records the commits and the release hashes. SHA256SUMS.txt lists the SHA-256 of every file in the copy.
- The copy is not runnable as a whole. The gate and the build expect the checkout layout, with the engine in a folder beside the checkout. The self-check runs from the copy when CLEANCT_ENGINE points at engine\.

### 17.4 Verification of the copy

- Every copied file was compared byte for byte with its source (SHA-256).
- The application sources in the release package (installer\_pkg\app) were compared with src\ and main.py, and the engine modules in the package with engine\.
- The code in the checkout was not changed by the copy (git reports no change to the copied paths).

## 18. Decisions made in this round of the design

1. Cut equals the metal top. The Cut follows the metal base (the detector anchor), not the halo onset. On 2-5 the detector cut is 353 and the metal anchor is 405. The halo onset is still reported.
2. Keep equals the wood top. The 0.3 mm air margin is not applied in the copy layer, so fog above the wood apex falls outside the delivery. DEV_LOG 4.2 describes the older air-top rule.
3. L and R mean the vertical lines of the current view. In the sagittal view they are the Y pair. In the axial and coronal views they are the X pair. The DICOM export clips both pairs.
4. The Results follow the Boundaries lines. The After shows the processed run, and the Lines changed marker says when the two differ.
5. The export takes the on-screen lines, not a stored box. The box is not stored in the registry.
6. Auto snap pauses after a manual edit and resumes on the next detection.
7. The margin pulls the delivered cut back. The delivery stops the margin slices above the Cut line (Cut minus margin), in the processing run, the Results, the preview and the export. This reading follows the user guide's safety slices: the buffer sits between the Cut line and the metal. The user confirmed this reading.
8. The Results labels are drawn by the app, in front of the image, and are not baked into the Results frames.
9. Process and export applies the lines on screen first, as Apply lines does. An auto cut that was never applied is applied and saved for the specimen, so the export is always the run it processed.

## 19. Code map

| Purpose | File and function |
|---|---|
| Detection: metal anchor, wood top, air top, lateral box | src\core\wood_bounds.py: wood_bounds, _metal_anchor, _edge_walk, _curtain_top, _largest_components, _projection_lane_bounds |
| Copy layer | src\core\auto_snap.py: cut_target, detected_lines, delivered_cut |
| Lateral pixel ranges | src\core\lateral.py: lateral_range |
| Payload, frames, caches | src\core\viewer_core.py: build_payload, _build_payload_locked, _axial_pair, _prev_source, _prev_source_unprocessed, _ortho_columns_cached |
| Preview and the Boundaries panels | src\core\viewer_core.py: get_preview, _get_preview_locked, _ortho_panel, _axial_orig, _ortho_plane, _lateral_box, _apply_cmap, _CMAP_STOPS |
| Viewer: lines, labels, Results overlay, crop | src\widgets\viewer_2d.py: paintEvent, _auto_z_guides, _paint_results, _paint_panel_label, crop_after_panel, setResultsOverlay, setAxisBounds, axisBounds |
| Window: Boundaries lines and copy layer | src\main_window.py: _apply_auto_snap, _snap_lines_to_detection, _reset_to_detected, _note_manual_lines_edit, _valid_keep_cut, _set_lateral, _on_pref_*_dragged |
| Window: Boundaries preview | src\main_window.py: _fetch_prefs_preview, _start_prefs_preview, _on_prefs_preview_ready, _schedule_prefs_preview |
| Window: Results | src\main_window.py: _refresh_results_sync, _update_axial_frame, _results_crop_axial, _refresh_results_long, _on_results_long_ready, _on_long_slider_changed, _processed_lines |
| Window: jobs and processing | src\main_window.py: _start_job, _run_pipeline_task, _process_selected, _apply_and_process, _process_and_export, _on_job_finished, _on_job_error |
| Window: export | src\main_window.py: _export_bundle, _export_lateral, _resolve_sources, _validated_dest_root, _confirm_replace_export |
| Window: specimens | src\main_window.py: _select_sample, _apply_sample_payload, _refresh_sidebar, _rename_selected, _duplicate_selected, _remove_selected, _properties_selected |
| Window: checkpoints and history | src\main_window.py: _capture_checkpoint_state, _make_checkpoint_document, save_checkpoint_file, load_checkpoint_file, _record_session_preview, _restore_session_history |
| Window: settings | src\main_window.py: _build_settings_page, _on_theme_changed, _on_save_root_edited, _on_export_format_changed, _choose_checkpoint_dir |
| Registry and junctions | src\core\custom_series.py: register_series, validate_input, validate_series, set_specimen_overrides, remove_specimen, rename_specimen, duplicate_specimen, config_overrides_for_spacing, _sanitize_specimen |
| Export: bundle, DICOM, NIfTI, sidecar, check | src\core\bundle_export.py: export_bundle, _export_bundle_into, _export_volume_bundle_into, _write_kept_dicoms, _crop_slice, _lateral_box_px, _write_kept_nifti, _write_kept_nifti_streamed, _write_sidecar, _write_info_txt, _delivery_tags, _promote_directory |
| Checkpoint file | src\core\checkpoint_file.py: validate_checkpoint, save_checkpoint, load_checkpoint, new_document, fit_preview |
| Paths | src\core\paths.py: engine_root, state_root, ensure_output_root, is_installed |
| Single window | src\core\single_instance.py: acquire |
| Theme and icons | src\theme.py: DARK, LIGHT, qss, apply; src\icon_utils.py: get_app_icon, apply_native_window_icon |
| 3-D view | src\widgets\viewer_3d.py: setData, setVisualMode, setColorMap, _rebuild_colors; src\core\viewer_core.py: _scan, _metal_points |
| Engine: pipeline | engine\tomograph.py: load_dataset_volume, metal_counts, bottom_mean_profile, platform_cut_index, analyze, process_sample, drop_curtain |
| Engine: ROI and delivery | engine\roi_delivery.py: export_roi_dicom_series, write_roi_nifti, write_stripped_nifti, write_provenance |
| Engine: wood tracking and air crop | engine\wood_track.py: track_wood_by_slices, crop_by_footprints; engine\air_crop.py: detect_air_envelope, apply_air_crop |
| Engine: GPU and volume readers | engine\gpu_backend.py: get_backend, GpuBackend; engine\volume_io.py: inspect_source, load_volume, read_source_slices, adaptive_thresholds |
| Installer | installer\build_installer.py: main, step_app, step_engine, step_runtime, step_launcher, step_docs, step_launcher_smoke, step_portable, step_inno, step_regressions |
| Launcher | installer\launcher_main.py: payload_dirs and the start-up logic |

## 20. Known limits and open items

Found in the audit. Each item says whether it is by design or still open.

1. The Auto-crop check box trims only the processing output wood_roi.nii. The bundle is cut to the lines on screen. By design; the tooltip says so.
2. The processed axial view steps through at most 16 stored frames (N_AXIAL), not every slice (section 10.5). The Boundaries slider covers every slice. By design for now; open for a later change.
3. The header KPI mirrors the working lines on screen, as its code comment says. By design. The Lines changed marker shows when the processed run differs.
4. A running pipeline cannot be stopped. Stopping needs a change in the engine. Open; not part of this release.
5. The Results longitudinal view reads the source folders, as Boundaries does. A moved source folder shows an error text rather than the cached image. Open.
6. Older payload caches still hold the legacy sagittal and coronal image keys. They are ignored.
7. The "untrusted mount point" messages in the gate output come from test_state_files, which simulates error 448 on purpose. Expected.
8. The two NIfTI writers still exist side by side (streamed DICOM and volume). Merging them is a later lean step. Open.

## 21. Records

- DEV_LOG.md: the change log. Sections 2.20 to 2.24 cover the Results work and the export crop. Section 4 holds the ROI logic, and section 4.2 describes the older air-top rule.
- AUDIT.md: the full audit with the hashes of each release.
- REVISION_HISTORY.md: a condensed history from the 1.0.0 baseline.
- ROI_LOGIC.md: the detection formulas and coordinate systems.
- version\RELEASE_NOTES.md: the release notes of the 1.0.0 folder.
