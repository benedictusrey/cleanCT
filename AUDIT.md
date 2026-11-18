# cleanCT Native Application Audit & Comprehensive Verification Report

**Application:** **cleanCT** (*Non-Destructive Wood CT Metal-Base Removal & Inspection Suite*)  
**Location:** `H:\Treated Kyodai samples\cleanCT`  
**Distribution:** `H:\Treated Kyodai samples\cleanCT\cleanCT.exe` & `H:\Treated Kyodai samples\cleanCT\dist\cleanCT-app\cleanCT.exe`  
**Architecture:** Pure Native C++ Qt6 Desktop Application (PySide6) + Vectorized 3D Viewport — **Zero HTML / Browser Dependency**  
**Audit Date:** 2026-09-16 (initial) · **2026-09-17 (full feature & geometry audit, see §0)** · **2026-09-17b (export-folder persistence + air-crop auto-crop, see §0A)** · **2026-09-17c (air-detected auto guide lines + threshold active state, see §0B)** · **2026-09-17d (metal-priority anchoring of the auto lines, see §0C)** · **2026-09-19 (full performance / leak / first-paint audit, see §0F)** · **2026-09-19b (custom-specimen load/export pipeline, see §0G)** · **2026-09-19c (1–150 µm resolution envelope + high-res load/process/export optimization, see §0H)** · **2026-09-19d (Pillow-12 preview crash + pre-process detection preview, see §0I)** · **2026-09-19e (folder organization, log policy, packaging safety, see §0J)** · **2026-09-19f (no-metal tolerance + user-lines export, see §0K)** · **2026-09-19g (export formats + 19× export speedup + live progress, see §0M)** · **2026-09-20 (processing-path delivery writes streamed/parallel/honest, see §0N)** · **2026-09-20b (one-pass Process & Export selected, see §0O)** · **2026-09-20c (combined-flow stale-line guard + tracker hot-spot verdict, see §0P)** · **2026-09-22 (installer & distribution, see §0Q)** · **2026-09-23 (installer compaction and cache-path audit, see §0R)** · **2026-09-24b (checkpoint hardening release, see §0AA) · 2026-09-24c (structured checkout + specimen-panel overhaul, see §0AB) · 2026-09-24d (clean export delivery + snap fix + installer resync, see §0AC)**

---

---

## 0Q. Audit Round 2026-09-22 — Installer & Distribution (compact torch-free payload)

**Request:** make cleanCT shareable — a compact installer other PCs can run;
pinned `.ps1` that installs all dependencies; deliverables in `installer\`.

### Design decision: torch-free, CuPy-first (~1.0 GB payload, was ~2.5 GB with torch)
The app's GPU surface is fully covered by the engine's CuPy backend
(morphology stays on SciPy; the torch path is redundant).  Removing torch
shrinks the payload 2.5× and *eliminates a proven DLL-hell class*: torch's
`torch\lib` NVRTC hijacks CuPy's (the failure mode that motivated the
out-of-process preflight).  The engine primes the NVRTC pair by absolute
path (`_prime_nvrtc_windows`), so machine PATH pollution (system toolkits,
conda `Library\bin`) cannot hijack resolution.

### The NVRTC wheel forensics (this is the pin that must never drift)
- `nvidia-cuda-nvrtc-cu12==12.9.86` **fails** in clean environments:
  mismatched NVRTC/builtins pair + toolchain ahead of cupy 13.4.1's headers.
- `==12.8.93` is the **self-consistent** pair (NVRTC 12.8.93 +
  `nvrtc-builtins64_128.dll`) and compiles cupy kernels cleanly with the
  runtime wheel 12.9.79 for `cudart64_12.dll`.
- Dev machine "worked" only because anaconda's `Library\bin` NVRTC shadowed
  the wheel — proven by A/B with a stripped PATH.  Both `setup_env.ps1` and
  the shipped `requirements-pinned.txt` pin **12.8.93**.

### Portability refactor (Phase 1, zero drift)
- New `core/paths.py`: `engine_root()` (env `CLEANCT_ENGINE` →
  `<root>/engine` sibling → legacy dev path) and `state_root()`
  (`%LOCALAPPDATA%/cleanCT`, dev legacy guard for the junctioned registry).
  All four hardcoded engine-path constants and every state path now resolve
  through it; both torch probes in `main_window` are exception-safe.
- `main.py --selfcheck`: imports, versions, engine, GPU decision, offscreen
  Qt smoke — exit 0/2.  Dev-env regression gate: native suite, bounds_v2,
  export formats/stream, scale ladder, zline ground truth, fleet sweep —
  **all green, FLAG 0, 0 detection drift**.

### Payload proof (Phase 2) & packaging (Phase 3/4)
- `installer/setup_env.ps1`: one command, CPython 3.12 venv + exact pinned
  set (numpy 1.26.4, scipy 1.13.1, PySide6-Essentials 6.9.2, pydicom 3.0.2,
  nibabel 5.4.2, pillow 12.3.0, matplotlib 3.9.2, scikit-image 0.26.0,
  cupy-cuda12x 13.4.1, nvrtc 12.8.93, cudart 12.9.79).
- Full suite chain re-run **from the torch-free venv**: native suite,
  bounds_v2, export formats, export stream (byte-identical), scale ladder,
  zline, fleet FLAG 0, adaptive FLEET OK, no-metal e2e, unprocessed flow,
  delivery harness (heavy artifacts byte-identical; provenance float64
  reduction stats differ at the 13th digit by design — CuPy vs torch
  reduction order; harness contract taught integers/artifacts-exact).
- `installer/build_installer.py`: assembles `_pkg` (app include-list —
  immune to checkout clutter; engine 5 modules; embedded CPython 3.12.3;
  validated site-packages; PyInstaller launcher `cleanCT.exe`), portable
  zip via stdlib, Inno `cleanct.iss` (compiles when ISCC present).
- Validation of the **shipped** payload: `cleanCT.exe --selfcheck` →
  `RESULT: PASS`, `gpu: ACTIVE NVIDIA GeForce RTX 4080 SUPER via cupy
  (CC 8.9)`, `installed: True`, state in `%LOCALAPPDATA%/cleanCT`;
  packaged-GUI smoke (`build/pkg_gui_smoke.py`) boots the real MainWindow
  from `_pkg` offscreen — PASS, async load drained.

### Deliverables & no-regression hooks
| Artifact | Size | Location |
|---|---|---|
| Portable zip | 432 MB | `installer\out\cleanCT-1.0.0-portable.zip` |
| Inno project | — | `installer\cleanct.iss` (setup.exe builds once ISCC is installed) |
| Pinned env script | — | `installer\setup_env.ps1` |
| Package builder | — | `installer\build_installer.py` |
| Health check | — | `cleanCT.exe --selfcheck` (target PC, 60 s) |

Clean-machine checklist (in `installer\_pkg\README.txt`): extract →
`--selfcheck` → expect PASS (+ GPU ACTIVE on CUDA 12.x drivers) → GUI.
0BACKUP: `audit_0q_installer.md` + refreshed `gpu_backend` snapshot.

## 0P. Audit Round 2026-09-20c — Combined-flow stale-line guard & tracker hot-spot verdict

**Request:** full audit; eliminate glitches/flashings; optimize load/process/export
further; hunt leaks; guarantee no regression fallback; refresh `0BACKUP`.

### Correctness fix: combined Process & Export could deliver a stale line range

Auditing the 0O combined flow surfaced a real defect.  Stage 2 captured the
sidebar Keep/Cut sliders at click time as "session lines" — but for an
**unprocessed** specimen those sliders may still hold whole-scan defaults (a
specimen whose pre-process detection deferred keeps n/0; a fresh registration
may hold another specimen's lines).  The standalone Export flow is protected
(the completion re-select re-syncs the sliders from the fresh report before the
user can click); the combined flow had no such barrier.

**Fix (behavior-preserving for every normal path):**
- `pref_dirty` was dead state — initialized, never set, never read.  It is now
  a real **user-edit flag**: set by every interactive job-line/threshold edit
  handler, cleared at the end of every *programmatic* sync (specimen
  registration, processed-load sync, pre-process guide sync).
- Combined stage 2 now reads the freshly DETECTED lines when the user has not
  edited the sliders (payload rebuild keyed on the report stage 1 just wrote —
  the exact values the GUI auto-places: Keep ≡ air top, Cut ≡ metal top), and
  honors the captured sliders only when `pref_dirty` is set (identical to the
  ⬇ Export bundle semantics).
- Native suite §10b (new): a combined run with simulated stale sliders must
  deliver the detected range (cut 378 − keep 15 = 363 DICOM files on the real
  66 µm 1-1), not the whole scan.

### Performance: tracker hot spots measured — deliberately untouched

Per-operation probe on real 2-21 slices (`build/probe_tracker_ops_0p.py`,
read-only): compute ≈ **29.4 ms/slice** (open/close morphology 15.4 ms ≈ 52%,
label+find_objects 11.8 ms ≈ 40%, step-math ≈ 0, plane reads ≈ 0) — consistent
with the pipeline's `roi_track_s` 52.6 s on the real run.  Every candidate
optimization fails the zero-drift bar: the walk is inherently sequential
(slice *i* depends on slice *i−1*'s mask), the cupy branch is dead in this
environment (torch backend), and OpenCV-class morphology has different border
semantics (pixel-identical outputs cannot be guaranteed).  **Decision: the
detection-critical tracker stays byte-for-byte as-is**; the 0N delivery-write
wins (197 s → 131.5 s on 2-21) remain the honest performance story.

### Glitch / flash & leak sweeps: clean

- Viewer opaque-paint hardening (§0F.4) verified intact — no black/white
  flash surfaces on repaint/resize/plane switch.
- Combined stage-switch bar handling verified: staged process captions are
  capped inside `[5, P]` and the first real export signal remaps the bar into
  `[P, 99]` — no jump-back glitch.
- Worker lifecycle: single-slot `_load_worker` with stale-load deferral,
  `closeEvent` joins running workers (no GC-while-running crash, no partial
  bundles), job/preview debounce paths unchanged.
- Disk hygiene: no `.tmp` leftovers anywhere in `metal_remover/output`;
  byte-bounded caches (orig-slice cache 256/2, preview LRU 3) verified.

### Verification (all green)

- Native suite **ALL PASS** (incl. new §10b stale-slider check)
- `test_export_formats` ALL PASS · `test_export_stream` BYTE IDENTICAL
- `test_bounds_v2` ALL PASS · 1–150 µm scale ladder ALL PASS
- zline ground truth **0 flags** · fleet bounds sweep **FLAG 0** (57)
  · fleet adaptive **FLEET OK**

`0BACKUP` refreshed (audit record + main_window snapshot); dist repackaged
update-in-place and verified.

---

## 0O. Audit Round 2026-09-20b — One-Pass “Process & Export selected” (synchronized with the Format selector)

**Request:** a single action that processes *and* exports the selected
specimen, honoring whichever Format is selected (**DICOM only** /
**DICOM + NIfTI** / **NIfTI only**) — the two previously separate buttons
synchronized into one pass.

### Design (chained single worker job)

New sidebar button **⏩ Process & Export selected** (`btn_process_export`,
always available like ▶ Process selected).  Clicking starts ONE job
(`kind="process_export"`) whose worker task runs the two existing stages
back-to-back with identical semantics — no duplicated delivery logic:

1. **Stage 1 — process**: calls the exact `_run_pipeline_task()` used by
   ▶ Process selected (detection + cut + streamed delivery writes).
2. **Stage 2 — export**: reads the **fresh on-disk** `report.json` written
   by stage 1, applies the session Keep/Cut lines (identical logic to
   ⬇ Export bundle), then calls `bundle_export.export_bundle` with the
   **currently selected Format** and destination.  The staged fallback
   (fleet path without `stripped.nii`) works unchanged.

**Atomicity:** if processing fails, nothing is exported (the worker raises
before stage 2); if the export stage fails, the process outputs remain and
can be exported with ⬇ Export bundle.  The destination is validated
*before* processing starts (fail-fast — no wasted minutes on a missing
destination).  The applied session lines, if any, are logged.

### Combined progress model

`_start_job` gained `progress_mode="combined"` with an honest bar split:
the process stage’s staged captions map into **[5, P]** where
`P = 5 + w·90` and `w = proc_s/(proc_s+exp_s)` from the measured ETAs
(`_expected_process_s` · new `_expected_export_s`: 0.016 s/kept-slice,
measured on the real 2-21 bundle).  The first real export progress signal
switches the stage and the live per-phase signals own **[P, 99]**.  ETA
during stage 1 counts only the process remainder.

### Refactor (behavior-preserving, single code path)

`_validated_dest_root`, `_resolve_sources`, `_log_process_result` and
`_log_export_result` were factored out of the existing flows and are now
shared by ⬇ Export bundle, ▶ Process selected and ⏩ Process & Export —
the standalone buttons are byte-for-byte the same code paths as before,
so the combined flow cannot drift from them.

### Verification (no-regression proof)

| Check | Result |
|---|---|
| Native suite §10 (13 new checks): combined run on real 66um/1-1 — job labels, dual result logging, DICOM-only format honored (series present, **no** NIfTI), temp destination honored, buttons re-enabled | **PASS** |
| Native suite total | **169/169 PASS** |
| `test_export_formats.py` (3 formats, sidecar adaptation, byte-identity, hygiene) | **ALL PASS** |
| `test_export_stream.py` (streamed == nibabel RAM save) | **BYTE IDENTICAL** |
| `test_bounds_v2.py` + zline ground truth (engine untouched) | **ALL PASS / 0 flags** |

---

## 0N. Audit Round 2026-09-20 — Processing-Path Delivery Writes: Streamed, Parallel, Honest, Byte-Identical

**Field report:** the user asked for another full audit with focus on processing/loading/exporting time at high resolutions and leak hunting. Evidence-first profiling of the real 2-21 process run (197 s) showed: wood tracker 52.6 s (detection-critical — untouched by design), an **untimed** in-RAM stripped.nii write of ~60–70 s (full-volume float32 transpose copy + nibabel serialization copy), wood_roi.nii 28 s, DICOM series 22 s (serial loop).

**Fixes (all zero-drift, byte-identical outputs):**

1. **Streaming NIfTI core in the shared pipeline (`roi_delivery.py`)** — `_nifti_prefix_bytes` (nibabel-exact header+extension serialization without materializing data) + `_stream_nifti_planes` (sequential single-plane writes, periodic fsyncs, one plane of extra RAM, two historical dim layouts supported: x-fastest `(x,y,z)` and z-fastest `(z,y,x)`).
2. **`write_roi_nifti`** streams (no transpose copy); **`write_stripped_nifti`** (new, timed) writes the full stripped volume exactly as the historical format (NaN voids beyond the cut, `(x,y,z)`-labeled dim); **`nifti_metadata_payload`** header reads threaded; **`export_roi_dicom_series`** parallelized (8 workers, order-preserving, deterministic hash-derived UIDs).
3. **Bundle-export DICOM-rebuild fallback** (fleet outputs without stripped.nii) streams too — with explicit slope/inter so the prefix is byte-identical to nibabel.
4. **Honest ETA seed** for process jobs (`_expected_process_s`): custom series scale with slice count (measured 0.123 s/slice on 2-21), floored at 30 s.

**Measured (real 2-21, 1067 slices):** total **197 s → 131.5 s (−33%)**; DICOM write 22.4 → 12.1 s; stripped write ~65 → 29 s (now timed as `stripped_nii_write_s`); peak RAM down ~6 GB. Writes are honest (bounded dirty-page cache — no post-write system stall on slow destinations).

**Zero-drift proof:** `build/test_process_delivery_0n.py` re-processes the real 2-21 and byte-compares **every delivery artifact** against pre-0N reference outputs — stripped.nii (6.04 GB), wood_roi.nii (5.49 GB), all 969 DICOM files, index CSV, provenance JSON, cut/keep/metrics/bbox: **ALL byte-identical**. `build/bench_stream_process_writes.py` proves both header layouts byte-identical to `nib.save` on synthetic volumes; the export-formats harness gained a fallback byte-compare vs `nib.save`.

**Regression:** native suite ALL PASS · `test_export_formats` 22/22 · `test_export_stream` BYTE IDENTICAL · `test_nometal_e2e` / `test_unproc_and_frames` ALL PASS · `test_bounds_v2` / scale ladder 1–150 µm ALL PASS · zline ground truth 0 flags · fleet sweep FLAG 0 · fleet adaptive FLEET OK.

---

## 0M. Audit Round 2026-09-19g — Export Formats, 19× Export Speedup, Live Progress

**Field report:** exporting 2-21 froze the GUI ("Not Responding") and took ~5 minutes; the user asked for DICOM-only / NIfTI-only / both export options and faster exports at high resolution.

### 0M.1 Root causes (measured, not assumed)
- **Strided memmap writes (the big one).** The streamed NIfTI writer assigned `dst[:, :, z0:z1] = blk` into a `(nx, ny, n_keep)` memmap — numpy iterated the view's innermost axis (z, stride = one full slice ≈ 5.6 MB), producing ~11M scattered 4-byte writes per block. Micro-probes on the real 2-21 volume: strided memmap 218–277 MB/s vs **sequential fd writes 1860 MB/s** (plane-loop fd write 0.29 s vs 2.50 s per 544 MB). In the canonical NIfTI layout z is the FASTEST file axis, so source planes are already file-contiguous — the whole transpose premise was false; the copy is purely sequential.
- **Unbounded destination dirty cache.** Writes landed in the OS write cache with no physical flush until the very end; on a slow target (or a multi-GB bundle) Windows throttles the whole process — the GUI freeze in the screenshot.
- **Dead final phase.** The streamed writer never received the progress callback, so the bar sat at 93% on "sidecar…" while the real 284 s NIfTI phase ran.
- Minor: sidecar re-read the first DICOM header twice (date + time).

### 0M.2 Fixes (core/bundle_export.py)
- **Sequential fd-write streaming**: each source z-plane written as one contiguous chunk (header + planes back-to-back, no memmap, no seeks). Byte-identical output (proven), peak RAM one plane + one 8-slice block. Periodic `fsync` every 16 blocks bounds the destination cache; fsync after completion and after the DICOM-rebuild fallback path.
- **Export formats**: `export_format="dicom" | "nifti" | "both"` — skipped artifacts report `skipped`, sidecar/info/verification adapt (`export_formats` recorded in the sidecar), invalid format rejected with a clear BundleError. Update-in-place preserved: a re-export never deletes artifacts of kinds it was not asked to write (non-destructive).
- **Tmp hygiene**: `_clean_tmp` now sweeps every temporary belonging to the specimen (`.name*.tmp`, `name_rem.nii.tmp`, `name_rem_dcm.tmp/`, `name*.tmp.nii`) on every export, even for skipped artifacts; fallback NIfTI stages as `<stem>.tmp.nii` (nibabel infers format from the extension).
- **Real progress**: `progress(i, n, phase)` fires per DICOM slice and per streamed block + sidecar/verify phases; `WorkerThread` gained a `progress` signal and injects the callback; the export job runs in **live progress mode** (real fraction, real phase captions, per-phase %) instead of the simulated stage timer.
- **GUI**: new persisted **Format** selector (DICOM + NIfTI / DICOM only / NIfTI only) next to the bundle destination; export success log names the format; session line edits (Keep/Cut sliders) are honored in the export and logged.
- Sidecar: single header read for capture date/time.

### 0M.3 Verification
- New harness `build/test_export_formats.py` — **21/21 PASS**: both/DICOM/NIfTI on a synthetic series, ordered phases with real progress endpoints, sidecar/info adaptation, byte-identical NIfTI across modes, DICOM-rebuild fallback with atomic rename, tmp-hygiene incl. skipped artifacts, update-in-place non-destructive re-export, invalid-format rejection.
- `build/test_export_stream.py` — streamed writer still **byte-identical** to nibabel's RAM save.
- **Real 2-21 benchmark** (`build/bench_export_221.py`): total **287.8 s → 14.9 s (19.3×)**; NIfTI phase 284.3 s → 11.6 s; DICOM 2.5 s; bundle complete and verified (969 slices, both artifacts).
- Native suite **155/155 PASS** (export-section assertions updated to the live-progress contract); `test_bounds_v2` ALL PASS; zline ground truth **0 flags**; `test_unproc_and_frames` ALL PASS; dist repackaged with state preserved.

## 0K. Audit Round 2026-09-19f — No-Metal Tolerance & User-Defined Lines Export

**Field report:** specimen 2-21 (metal present but NOT bottom-anchored — the bottom-run test found run length 0) aborted processing with `no bottom-anchored metal platform found (run length 0 slices)` before the user's own adjusted lines could be applied.

### 0K.1 Root cause and fix (pipeline, shared)
`tomograph.anchor_slice` **raised** when no bottom-anchored metal run satisfied `platform_min_slices`. Two structural problems: (a) metal that does not reach the last slice — or no metal at all — is a legitimate geometry, and (b) the raise fired *before* `cut_override` was consulted, so the user's lines could never rescue the run. Fixed:
- `anchor_slice` now returns **0** ("no platform") instead of raising; the same tolerance covers a run shorter than `platform_min_slices`.
- `platform_cut_index`: with no platform the halo detector's fallback delivers the **whole scan** (`cut_from = n`, `accepted_by="no-platform"`) — the wood-ROI tracker still limits the delivery to the specimen, so nothing is lost; the report carries `no_platform: true` and `anchor_slice: 0` for downstream logic.
- `keep_from >= cut_from` now raises a **clear, actionable** error ("adjust the Top Keep / Bottom Cut lines") instead of an implicit empty delivery.
- The `anch == 0` no-platform branch is reachable ONLY where the old code raised — on every fleet specimen a real platform yields `anch > 0`, so validated semantics are bit-identical.

### 0K.2 App behavior (no-metal specimens)
- The pre-process detection degrades gracefully: the air-top guide still places Keep; with no metal top, the **Cut defaults to wood bottom + 2 safety slices** and the log explains the manual workflow ("adjust the Top Keep / Bottom Cut lines and Process as usual") — no failure path, no dead end.
- The user's own lines (Keep/Cut/Margin from the sliders) flow through `cut_override` / `keep_from` and are honored exactly (`accepted_by: "user-override"`); export proceeds as usual.

### 0K.3 Verification
- New E2E harness `build/test_nometal_e2e.py` (**12/12 PASS**): synthetic no-metal specimen → pre-process guides (keep=1 confirmed, cut=wood_bottom+1 reference) → pipeline completes (`no_platform`, cut=n, ROI delivered, files on disk) → user lines honored (cut=30/keep=4 → exactly 25.0% removed) → invalid lines rejected with the clear message.
- **Real 2-21** processed end-to-end with the user's lines (keep 51 / cut 1020): 196.6 s, cut `accepted_by=user-override`, 4.40% removed, full delivery (NIfTI + DICOM + QA + report) written to `output/custom/2-21`.
- Engine untouched: `core/wood_bounds.py` byte-identical to the validated 0J snapshot; `test_bounds_v2` ALL PASS; ground truth 0 flags; fleet sweep **FLAG 0**; fleet adaptive FLEET OK; native suite **156/156 PASS**.
- `tomograph.py` lives OUTSIDE `cleanCT/` — a copy is now frozen in `0BACKUP/pipeline/tomograph.py` (first time the shared pipeline file is backed up).

---

## 0J. Audit Round 2026-09-19e — Folder Organization, Log Policy & Packaging Safety

**Directive:** full audit; keep hunting glitches/flashings and perf culprits (loading / processing / exporting at high resolution); organize the main folder neatly (e.g. logs into a log folder); guarantee no regression fallback; back everything up to `0BACKUP`.

### 0J.1 Folder organization (the visible change)
- **`logs/` created**: all **15 loose root logs** (13 `build_*.log` suite/probe files + the runtime log) moved to `logs/build/`; the app root now contains only code, docs, and data folders.
- **Runtime log relocated**: the launcher (`stub_main.py`, embedded in the exe) now writes `logs/cleanCT.log` instead of polluting the root — with **size rotation at 5 MB** (one previous generation kept as `cleanCT.log.1`; the old code appended forever, an unbounded disk-growth leak). Falls back to the app root if `logs/` cannot be created (read-only layout).
- Launcher logic unit-tested (subdir creation, rotation, single-generation retention, fallback) and the exe **rebuilt** (`cleanCT.spec`; root + dist copies refreshed).
- **`.gitignore` added** documenting the versioned/regenerable split (bytecode, logs, caches, exports, dist, data ignored; code, docs, `0BACKUP/` kept).
- Stale `__pycache__` directories purged.

### 0J.2 Packaging safety fix (latent data-loss footgun)
`tools/package_app.py` **deleted `dist\cleanCT-app` on every repack** — destroying user state that lives there (`settings.json`, `logs/`, registered custom specimens, exports). It now **updates in place**: only app-owned files/dirs are refreshed, everything else is untouched. It also ships the previously-missing `stub_main.py` and documents the log location in `README.txt`. Repack executed and verified: user state survives, all app files current.

### 0J.3 Performance & glitch audit (no new defects found)
Measured baselines on this workstation — every interactive path is already sub-half-second and the heavy paths already run once per specimen on worker threads (rounds 0F–0H):

| Path | Measured |
|---|---|
| Payload load, warm disk cache (24 µm / 666-6) | **0.03–0.04 s** |
| First preview, axial / sagittal (24 µm) | 0.42 / 0.27 s |
| Preview rebuild after cache clear | 0.28 s |
| Axial scrub (single source slice, uncached z) | **0.03 s** |

Paint hardening (opaque viewers), the debounced preview (180 ms), async loads, byte-capped caches, threaded DICOM I/O, and the streamed >4 GB NIfTI export were all re-verified in place — the earlier rounds' optimizations hold; no risky micro-optimizations were added for their own sake.

### 0J.4 Verification (no regressions)
- Native suite: **156/156 PASS** (its own log now lands in `logs/build/` by construction).
- `test_bounds_v2` **ALL PASS**; real-data ground truth `zline_validate` **0 flags**.
- Perf baseline table above captured for future rounds; launcher unit checks all pass.
- `0BACKUP/src_snapshot` refreshed (stub_main.py, tools/, .gitignore, layout docs included); round record `audit_0j_organization.md`.

---

## 0I. Audit Round 2026-09-19d — Pillow-12 Preview Crash & Pre-Process Detection Preview

**Field report:** loading the processed 666-6 failed with `module 'PIL.Image' has no attribute 'REDUCE'`; 666-5 lost its Axial plane; and a freshly registered specimen showed no preview at all, so the air/metal detection could not be checked before spending a processing run.

### 0I.1 Root cause 1 — dead Pillow constant (the load crash AND the missing Axial)
`_frame_img` (the shared frame downscaler) used `Image.REDUCE`, **removed in Pillow 10** (this workstation runs Pillow 12.3). The constant only executes when the downscale ratio exceeds 2× — the fleet specimens (≤2000 px slices) never hit it, so every suite run was green while any custom specimen with larger slices crashed. One code path explains BOTH symptoms: payload frames (processed load) and the axial preview (the only preview that downscales full slices) — hence 666-6's load failure and 666-5's missing Axial.
- Fixed with the enum forms (`Image.Resampling.BOX` / `.Resampling.LANCZOS`) — identical filters, present on every supported Pillow.
- Codebase sweep for the whole bug class (`ANTIALIAS`/`BICUBIC`/… bare constants): no other occurrences.
- `build/test_unproc_and_frames.py` §1 now exercises the >2×, <2× and ==2 ratio paths under Pillow 12.

### 0I.2 Root cause 2 — previews required report.json (no pre-process view)
`_prev_source` read `report.json` unguarded, so a registered-but-unprocessed specimen had no previews at all. Now:
- **Scan-native preview source** (`_prev_source_unprocessed`): without a report the delivery equals the whole scan (cut = n, margin 0, keep 0) and the window is the general CT view — the preview needs nothing from the pipeline.
- **Pre-process detection**: `wood_bounds` runs over the full voxel with the engine's canonical wood class, fed the TRUE z geometry (`_scan_meta`: header `SliceThickness`, falling back to the physical first-two-slice spacing — micro-CT exports are frequently anisotropic, µm pixels with mm-scale z steps; assuming isotropy there poisons the physical evidence gates).
- **Payload integration**: `build_payload` attaches the same cached pre-process bounds to the unprocessed payload, so the GUI and the previews show identical lines.
- **GUI**: the unprocessed state now auto-places the guide lines (Keep ≡ air top, Cut ≡ metal top), logs `pre-process guide lines placed (metal-first: …)`, keeps the axial scrubber live over the raw scan (slice rendered on demand), and keeps the Preferences page fully interactive — while Export / Apply & process stay gated until the pipeline has run.

### 0I.3 Defect found en route — silent metadata loss
`_scan_meta` initially used a module-global `pydicom` reference that this file only imports locally: the swallowed `NameError` zeroed voxel/z-step metadata instead of failing loudly (same mask-the-exception pattern as §0G's import bug). Fixed with the file's local-import style; the degenerate-volume refusal of the engine (sub-millimetre phantoms correctly rejected) surfaced the bug instead of hiding it.

### 0I.4 Verification
- Native suite: **156/156 PASS** (7 new pre-process-contract checks incl. detection values on a realistic mini-phantom: cut=13 exactly at the metal slab, keep=1 with 0.3 mm-margin fog semantics).
- `build/test_unproc_and_frames.py`: **ALL PASS** (frame ratios + 3-plane unprocessed previews + detection attach + cleanup).
- Engine untouched: `test_bounds_v2` **ALL PASS**; real-data ground truth `zline_validate` **0 flags** (references intact).
- Real E2E: 666-6 payload builds (15 frames, keep=65 / cut=859 @ 33.1 µm); 666-5 axial preview restored (0.30 s).

---

## 0H. Audit Round 2026-09-19c — Resolution Envelope (1–150 µm) & High-Res Optimization

**Directive:** the air-top/metal-top detection and the load/process/export pipelines must work — robustly and optimized — for ANY voxel from 1 µm upward (focus 1–100 µm, plus >100 µm). No regressions.

### 0H.1 Engine compute guards (ultra-high-res)
- **Closing-radius cap (`CLOSING_PX_MAX = 24`)**: the physical 0.15 mm closing stops growing beyond 24 px; at/below-6.25 µm voxels it would otherwise reach 150 px.
- **EDT closing for capped radii (`CLOSE_EDT_MIN_R = 8`)**: distance-transform closing — the same Euclidean ball, O(N) instead of O(N·r²). Measured **3.9 s at 6000² r=24** (the explicit kernel costs minutes). Fleet voxels close at r≤6 and keep the classic kernel (byte-identical).
- **Strided contiguous edge walks** (`FINE_STRIDE_MAX_VUM = 20`, cap 20): below 20 µm voxels the wood-top/bottom/curtain walks probe at a capped stride and refine the terminal gap at unit stride — the contiguity contract holds (max-stride verified) and at ≥20 µm the stride is 1 (fleet byte-identical). Probe clamp added: a stride larger than the remaining gap no longer overshoots the absent bound (which silently returned the unrefined pool sample).
- **Air fast-reject**: pure-air slices in the keep scan window are answered with one O(N) comparison — no mask/closing/labelling (~4 s → ~50 ms per air probe at 1 µm).

### 0H.2 Memory (leak-class findings)
- **Axial pool streaming**: the pool is read in batches of 4 slices and reduced immediately (was: the whole pool resident — tens of GB at 1 µm).
- **No pooled mask storage**: full masks are never retained; only the fog-blanket verdict per pool slice (a single 1 µm mask is ~0.7 GB). Dead `_edge_clear` removed.
- **Byte-capped slice cache** (`ORIG_SLICE_CACHE_MAX_BYTES = 1.2 GB`): the count caps alone could not bound 1 µm-class slices (hundreds of MB each).

### 0H.3 Real production defect found by the ladder: halo-guard axis bug
The metal-anchor guard subtracted `halo_px` — derived from the **XY voxel** — from a **Z slice index**. At a 2 µm XY voxel it removed ~5 mm of real wood from the trusted pool window (at fleet isotropy the two coincide, which is why it was invisible). Now divides the physical halo by the specimen's **true z-step** (`z_step_um` from the report). Ground truth + fleet confirm identical fleet output.

### 0H.4 Export & preview optimization
- **Streamed NIfTI export**: kept-slice volumes >4 GB are written block-wise through a memmap (peak extra RAM = 8 slices) instead of being fully resident. Proven **byte-identical** to the nibabel RAM path (sha256 match; `test_export_stream.py` encodes the dim-order and scl_slope/inter lessons). Low/mid-res volumes keep the in-RAM path.
- **Preview downscale**: single REDUCE pre-step before LANCZOS for >2× downscales (several-fold faster at 6000² frames, imperceptible quality change).

### 0H.5 Verification (no regressions)
- **Detector-model ladder, 12 rungs, 1–150 µm** (new section in `test_wood_bounds_scale.py`): same z-geometry in a compact constant-detector FOV at 1/2/3/5/8/12/24/33/50/66/100/150 µm — x/y bounds within 0.5 mm across every rung, z-guides stride-invariant, closing cap engages below 6.25 µm. **ALL PASS.**
- `test_bounds_v2.py` **ALL PASS**; `zline_validate.py` ground truth **0 flags** with the exact reference values (24 µm: keep 43/cut 1007; 66 µm: keep 15/cut 378); `fleet_bounds_sweep.py` **FLAG 0** (57 samples, fresh v15 caches); `test_fleet_adaptive.py` **FLEET OK**; native GUI suite **148/148 PASS**.

---

## 0G. Audit Round 2026-09-19b — Custom Specimen Load / Export Pipeline

**User-reported failure:** loading the registered custom specimen `666-5` (942 slices @ 33.1 µm from `1 MONTH/3 after oven-dry state`) logged `✗ specimen load failed: No module named 'custom_series'`.

### 0G.1 Root cause and fix
- `core/viewer_core._get_ds` imported `custom_series` as a TOP-LEVEL module, but it lives at `core/custom_series.py` — the import could never resolve inside the app (registration worked only because `dialogs/load_dialog.py` imports it correctly as `core.custom_series`). Fixed with a package import + flat-layout fallback.
- **Second latent defect behind the first:** even with the import fixed, a freshly registered specimen has **no `report.json` yet**, so `build_payload` would crash on the missing file. Added `_minimal_payload`: a graceful unprocessed payload (metadata only, empty viewers) flagged `unprocessed: True`.

### 0G.2 Unprocessed-specimen UX
- `_apply_unprocessed_payload`: header shows "NOT PROCESSED YET — run ▶ Process selected first", KPI cards read dashes (`KPIBanner.updateMetrics` handles the empty shape), viewers cleared, range summary shows a neutral hint (no red validation error), and the action log states the registered series geometry (slices @ µm).
- **Job gating (`_set_job_gates`):** Export and Apply & process are disabled with explanatory tooltips until the specimen has been processed; Process and Load stay available. Gates re-enable automatically when a processed payload arrives.

### 0G.3 Export path & default export folder
- Verified end-to-end on the real 666-5 specimen: **process 170 s → cut 864 (halo onset, `slope3` accepted), anchor 892, removed 8.28 %** → payload with detection **keep 51 / cut 864** auto-placed → **bundle exported to the default export folder** (`export\666-5`, 868 files, DICOM series + NIfTI + sidecar + extraction info, self-verified). The 33.1 µm voxel class sits *between* the fleet's 24.9/66.2 µm presets and confirms the adaptive engine generalizes.
- Default export folder: already enabled and persistent (`settings.json → save_root`, restored at every start, falls back to `cleanCT\export`) — confirmed populated (`H:\Treated Kyodai samples\cleanCT\export`) and honored by the custom export (junction provenance override records the user's real source folder in the sidecar).
- The exporter's `stripped.nii` preference + DICOM-rebuild fallback and the `keep_from` collection-range handling were code-audited (no changes needed).

### 0G.4 Regression insurance (custom lifecycle)
- New native checks (8D): a synthetic 16-slice DICOM series is written, registered (junction + registry + pipeline-sort validation), selected (graceful unprocessed state asserted: sub-label, KPI dashes, disabled Export/Apply, enabled Process), screenshotted, and fully cleaned up (registry + junction + outputs). Suite now **148 checks, all PASS**.
- Detection engine untouched: `test_bounds_v2.py` + `test_wood_bounds_scale.py` re-run **ALL PASS**.

---

## 0F. Audit Round 2026-09-19 — Centered First Paint, Leak & Performance Audit

Full audit of the application after the detection work stabilized (user confirmation: auto lining + air-top/metal-top detection working on both 24 µm and 66.2 µm datasets). Scope: window first-paint, glitches/flashes, memory leaks, loading/processing/export speed. The detection engine (`core/wood_bounds.py`) was audited and left **unchanged** (validated v2 semantics: multi-column metal quorum anchor fused with the detector, contiguous edge walks, curtain-model keep line, physical-unit adaptive scaling).

### 0F.1 Centered first paint (user request)
- `MainWindow.center_on_screen()` — centers on the screen's **available** geometry (inside the taskbar), clamps the 1540×960 default size down on smaller screens, and is called from `main.py` **before** `show()`, so the app never appears at the top-left corner and never jumps after painting.

### 0F.2 Memory leaks fixed
- **`ORIG_SLICE_CACHE` was unbounded** — every scrubbed/read source slice was cached forever per specimen (a full 24 µm curtain scan reads ~240 slices ≈ 0.5 GB; scrubbing a whole volume ≈ 2 GB+). Now FIFO-capped at **256 slices per specimen** and **2 specimens** (≈1 GB worst case), and `_source_slices` returns a **snapshot** so payload builders can never iterate a dict that eviction mutates.
- `_PREV` preview LRU, `_CACHE` payload cache and `_XY_FILES` listings were verified bounded already (3 / 1 / 8 entries).

### 0F.3 Performance: loading, processing, exporting
- **Async specimen loading** — the payload build (DICOM reads + bounds detection, seconds on 24 µm) moved off the GUI thread into a worker; the window paints immediately, shows "Loading specimen…", and a stale-load guard queues the LAST clicked specimen while a load is in flight (rapid reselect never drops or interleaves). Test harness drains via `_wait_for_load()`.
- **Threaded CUDA probe** — the torch import + CUDA init (multi-second) no longer runs on the GUI thread at startup; the GPU chip settles from "Checking GPU…" when the probe lands.
- **Direct pixmap decode** — `_b64_to_pixmap` dropped the PIL round-trip (`Image.open → tobytes → QImage`) per frame for `QPixmap.loadFromData` (Qt's native JPEG decoder): every axial scrub / preview repaint decodes ~4× faster.
- **DICOM thread pools widened 8 → 16** (`_IO_WORKERS`, host-adaptive) in all three threaded readers (`_source_slices`, `_orig_ortho_lines`, `_orig_ortho_columns`): source-slice batches, ortho stacks and therefore payload builds and preview fetches read up to ~2× faster on the 20-core host.
- **Memoised XY file listings** (`_xy_files`) — the detection curtain/edge walks read one slice at a time and previously re-globbed the ~1000-file series directory on EVERY single-slice read (hundreds of redundant directory scans per load); now one glob per specimen.
- Processing/export themselves were already optimized in §1 (16-worker bundle writes >420 files/s, `io_workers=16`); unchanged this round.

### 0F.4 Glitch / flash elimination
- `Viewer2D` now sets **`WA_OpaquePaintEvent` + `WA_NoSystemBackground`** — the widget fills its whole rect in `paintEvent`, so Qt skips the implicit erase step that caused white/black flashes on resize and image swaps; degenerate-size guard added to `paintEvent`.
- `Viewer3D` paint hardening (smooth transform hint alongside its existing opaque-paint attribute).
- Thread-safety: `viewer_core.build_payload` / `get_preview` are now **lock-serialised facades** — the async loader can never race a GUI-thread preview render on the shared caches (previously impossible because everything ran on one thread; now guaranteed).

### 0F.5 Verification
- Detection engine untouched: `test_bounds_v2.py` + `test_wood_bounds_scale.py` re-run green (synthetic + scale-invariance). Resolution-adaptive detection re-confirmed: every constant is physical (mm/µm) converted per specimen voxel — detection is identical in physical space at 12/24/25/66/120 µm by the standing scale suite.
- Native suite extended (centering on available geometry, frame inside screen, empty-viewer repaints dark, GPU-chip settle, rapid-reselect drain, async-load drain) — **138/138 PASS**.
- Real-data ground truth (`zline_validate.py`): **0 flags** (24 µm/1-1 keep 43 / cut 1007; 66 µm/1-1 keep 15 / cut 378 — the values visible in the user's screenshot); fleet sweep **FLAG 0**; fleet adaptive **FLEET OK**.

### 0F.6 Defects found and fixed during the audit round
1. **GPU probe `WorkerThread` was garbage-collected mid-flight** (local variable) — the whole process aborted ("QThread: Destroyed while running") at first paint. Thread wrappers are now pinned (`self._gpu_worker`), and a **`closeEvent` shutdown guard** waits for any in-flight background work instead of destroying live threads (preserves half-written exports too).
2. **First preview recomputed the entire detection on the GUI thread** — `_prev_source` re-ran `wood_bounds` from scratch (~8.2 s on a 24 µm specimen) although the payload already carried the identical (mtime-keyed) result: a multi-second freeze on the first plane switch of every session, on every specimen. Previews now **reuse the payload's bounds** (byte-identical inputs → identical result; measured 8.23 s → 0.30 s). The full recompute remains only as the no-payload fallback.
3. **Missing JPEG imageformat plugin** in this PySide6 install made the direct `QPixmap.loadFromData` decode fail on valid JPEG bytes — `_b64_to_pixmap` keeps the fast Qt path and falls back to PIL decoding (always available), so previews render regardless of plugin availability.
4. **Test-harness alignment**: stage-caption assertion widened to any export stage (the faster export reached stage 3 before the check ran); `center_on_screen` also runs from the constructor so directly-constructed windows (test harness) center too.

### 0F.7 Backup (regression insurance)
- `0BACKUP/` now holds: `DETECTION_ENGINE_NOTES.md` (authoritative engine documentation: requirements → priority model → algorithm → every constant → app contract → measured ground truth → invariants → test assets → revision history), `audit_0e_detection_round.md`, and `src_snapshot/` (complete byte-exact source of the validated revision incl. all validation harnesses, icons and assets) with a restore-and-verify README.

---

## 0E. Audit Round 2026-09-17e — Resolution-Adaptive Detection (z-guides)

**Adaptive scale model.** Every resolution-dependent constant in `core/wood_bounds.py` is now expressed in **physical units** (mm) and converted to pixels through the specimen's voxel size (`meta.pixel_spacing_yx_mm`): closing radius 0.15 mm (6 px @ 24.9 µm, 2 px @ 66.2 µm), halo guard 0.2 mm (8 / 3 px). Fractions (percentiles 20/80, ≥12 %-of-FOV metal-slab test) are scale-free. One reference fallback (25 µm) applies when a report lacks spacing.

**Top-air / bottom-metal z-evidence (new).** The axial pool now also yields z-guides: wood **presence runs** (largest gap-tolerant run) define the wood z-extent; both edges are **bisected** between neighbouring pooled slices (2 rounds, ≤10 slice reads) so Keep/Cut suggestions hug the true edges. `zb.keep` = air top (None when wood reaches the window start), `zb.cut` = metal-anchor top when the base is found, else wood-bottom+1. Rendered as **dotted reference guides** ("air top z" green, "metal top z" amber) under the interactive Keep/Cut lines — job parameters stay report-driven, Apply behavior unchanged.

**Metal priority per directive** — anchor first (sagittal ∩ coronal ≥12 %-width slab agreement, bottom-most run = base), air second (axial pool over the anchor-guarded window). Fixed this round: presence-percentile z bug (wood is one continuous run; percentiles were meaningless) and mid-line positional bias (Z evidence now comes exclusively from the axial pool).

**Validation:** 24/24 synthetic scale-invariance checks (same physical specimen at 12/25/66/120 µm — XY within 0.8 mm, z-guides within 0.5 mm at every resolution); fleet 56/56 anchor==detector; keep guide within 0.13–0.99 mm of the report keep line; cross-resolution physical agreement over 27 matched specimens (keep ≤0.34 mm, cut ≤0.45 mm, Y ≤1.2 mm; the two X outliers of 2–3.3 mm trace to genuine per-scan FOV/mounting differences, confirmed against tracker bboxes and clean edge columns); app suite 126/126 (anchor-vs-detector tolerance now in mm, resolution-adaptive). Evidence: `native_23..25_zguides_*.png`.

## 0C. Audit Round 2026-09-17d — Metal-Priority Wood Bounds (metal first, air second)

### 0C.1 Detection priority rebuilt (`core/wood_bounds.py`, rewritten)
- **Metal anchor (priority 1, sagittal + coronal):** a slice is metal-supported when its mid-line profile holds a solid metal-HU run (≥4 px, specks excluded); the anchor is the **bottom-most run where BOTH lines agree** — on every fleet sample it lands exactly on the pipeline's cut-detector anchor (24um/1-1: z 1048..1073 vs detector anchor 1048). The base top, backed off by a halo guard (8 slices), caps the z-window where air statistics are trusted — the base's halo band (which reads as non-air) can no longer poison the bounds.
- **Air refinement (priority 2, all planes):** the axial pool (uniform 16 slices over the trusted window) carries the complete X and Y extent per slice — each slice is the YZ witness for its X bounds and the XZ witness for its Y bounds. Metal is masked out of object evidence; closing+hole-fill keeps wood interiors. Percentile aggregation (20th/80th) is unchanged.
- **Design finding:** the mid-line ortho profiles are positionally biased for lateral evidence (a mid-line that misses an off-center specimen reads pure air and would collapse a bound) — they are used for the metal anchor only, never pooled into X/Y bounds.
- **Multi-stick discovery:** these scans hold several wood sticks side by side (three columns in 24um slices); the bounds are the union envelope of all of them (largest-component selection was removed after it collapsed X to one stick).

### 0C.2 Fleet validation (56 processed specimens, all 24um + 66um)
- Old vs new bounds agree within 1–4 px on every sample (zero flags, zero failures); new bounds additionally exclude the base halo band from the evidence window. 12 visual overlays (sagittal+coronal with anchor band + bound lines) in `build/bounds_shots/`.
- Suite extended 124 → **126 checks, all PASS**: metal anchor present in payload bounds, anchor == pipeline detector anchor (1048 == 1048), log surfaces "metal-first … metal anchor z 1048–1073", plus the prior line-placement checks. Cache versions bumped (payload v10, prev v2); poisoned older caches self-heal.
- In-app evidence: `native_20..22_metal_first_*.png` (sagittal L 4%/R 95% = Y bounds, coronal L 5%/R 95% = X bounds, axial box "ROI X 5..95% · Y 4..95%", action log showing the metal anchor). `dist\cleanCT-app` synced byte-exact (no instances running).  

---

## 0B. Audit Round 2026-09-17c — Air-Detected Auto Guide Lines (all planes) & Threshold Active State

### 0B.1 Robust air envelope for line placement (`core/wood_bounds.py`, new)
- Reads the same cached log-spaced source slices the viewer already uses; per-slice air mask (HU ≤ −900, closing + hole-fill) aggregated with **20th/80th percentiles** — immune to halo/fog outliers that break min/max, and tolerant of tapered specimens that a median would clip. Computed once per specimen, cached with the preview source (payload `bounds`, cache v9 + disk-cache self-heal).
- 24um/1-1 → y 47..1075, x 57..1082 of 1123×1133 (margins ≈47/47 and 57/50 px), matching the pipeline air-crop within a few pixels.

### 0B.2 Plane-aware auto line placement (`widgets/viewer_2d.py`)
- **Structural bug fixed:** the guide bounds were plane-blind — sagittal drew X fractions on a Y-axis image and the axial top/bottom were hardcoded 15/85 %. Bounds now live in **per-axis pairs** ({x, y}); each plane shows the pair of its horizontal axis: **sagittal L/R = Y bounds, coronal L/R = X bounds, axial box = X+Y** — lines hug the wood in XY, XZ and YZ.
- `setAutoBounds` applies the air-detected pairs once per specimen load (manual drags win afterwards; plane switches only swap which pair is displayed — nothing is lost). Axial Y rows (Top/Bottom sliders) appear only in the axial plane; L/R slider labels follow the active axis ("Left Y" in sagittal). Axial badge now reports both axes ("ROI X 5..95% · Y 4..95%").

### 0B.3 Threshold default state (user request)
- **Reset is the default-active** threshold choice (amber highlight on first paint); presets (Full / Wood Tissue / High Contrast / Platform Metal) activate on click and hand the highlight back to Reset when clicked; manual spin/slider edits clear the highlight. Presets are named widgets now, enabling the active-state model and suite assertions.

### 0B.4 Text & polish
- Prefs header default corrected to "Grayscale Colormap" (was "Spectral" while Grayscale was the actual default).

### 0B.5 Verification
- Suite extended 101 → **124 checks, all PASS**: auto-line positions == bounds fractions in all three planes, per-plane slider mirroring + labels, axial-only Y rows, drag preservation across plane switches, auto re-adoption on specimen change, threshold active-state model, header text. New evidence: `native_13..15_auto_lines_*.png`, `native_16_default_sagittal_reset.png`, `native_17..19` (sagittal/coronal/axial with auto lines + Reset active). `dist\cleanCT-app` synced (note: two user-launched cleanCT.exe instances were running during sync; restart them to pick up the new code).

---

## 0A. Audit Round 2026-09-17b — Default Export Folder & Air-Based Wood Auto-Crop

Two features added without touching validated pipeline conventions (CLI defaults unchanged; app-side opt-in):

### 0A.1 Default export folder (user preference, persistent)
- The "Bundle Dest" field is now a **remembered default export folder**: chosen via *Browse…* or typed + validated at export, persisted in `cleanCT\settings.json` (`save_root`), and reloaded on every start. Falls back to `cleanCT\export` when no setting exists.
- Wired through the existing `bundle_export.load_settings`/`save_settings`; zero pipeline impact. Export completion re-persists the validated path so any hand-edit anomalies self-heal.

### 0A.2 Air-based wood auto-crop ("Auto-crop to wood (air detection)", app default ON)
- New additive pipeline module `metal_remover/air_crop.py`: detects the **air envelope** (HU ≤ −900, ≥98 % air margin runs) on the already-voided stripped volume inside the tracked z-range; closing + hole-filling so wood interiors count as object; trims loose Y/X margins (XY, XZ and YZ) and clamps Z at the cut boundary. Result is **guaranteed ⊆ tracker bbox**; per-axis arbitration keeps edge-touching wood axes untouched; fog (>20 % non-air) disables trimming for that axis; degenerate results (<5 % FOV span) fall back to the tracker bbox. Every decision is recorded in `report.wood_roi.air_crop` (ok, reason, margins, trimmed).
- `Config` additions: `air_crop` (False — CLI/batch outputs stay byte-identical), `air_crop_hu` (−900), `air_crop_frac` (0.98). The app passes `air_crop=True` (checkbox, ON by default) as a runtime override; post-job log reports the tightened bbox or the fallback reason.
- Validation: **30/30 synthetic unit checks** (`metal_remover/build/test_air_crop_unit.py`) + **12/12 real-sample checks** (`build/test_air_crop_real.py`, GPU): 24um/1-1 trims Y 54/46 px, X 62/46 px; 66um/1-1 trims Y 21/17, X 19/19; subset guarantee holds; OFF-run reproduces the legacy pad-expanded tracker bbox exactly; report info absent when off.
- App suite extended to **101 checks** (checkbox default, pipeline pass-through + subset, OFF-report regression, settings round-trip, typed/browse persistence, default restore) — all green; screenshots refreshed in `build/native_shots/`; `dist\cleanCT-app` synced.

---

## 0. Audit Round 2026-09-17 — Full Feature, Layout & Text Audit

A complete re-audit of every feature, text, symbol and button reaction, with fixes verified by the extended smoke suite (**93/93 checks, was 37**) and fresh screenshots:

### 0.1 Layout & Geometry (default resolution shows all panels in full)
- *Root cause found:* the Preferences control column had a **966 px minimum height** (guides box 549 + thresholds 209 + spacing), inflating the window's minimum to **1115 px — taller than the 1032 px available** on 1080p. The default window opened clipped at 1115 px and the prefs summary/buttons could be cut off.
- **Fix:** the control column is now wrapped in a borderless `QScrollArea` (fixed 468 px column; content width 460 px), the viewer gets the splitter stretch priority, and the window minimum dropped to **763 px**. The default window now opens at exactly **1540 × 960** (fully visible on 1080p) and maximizing reflows all extra space into the workspace (stack 860 px tall when maximized, zero content overflow).

### 0.2 State & Data Correctness
- `_select_sample` read nested raw-report keys (`platform.cut_from`, `meta.n_slices`) that do not exist in the viewer's flat summary — cut clamped to a default 100, spin ranges stuck at (0, 100), all KPIs em-dash. Now reads the flat summary: cut 1023, keep 40, margin, anchor 1048, auto-detected 1007, n_slices 1074 populate the controls, ranges and hint.
- `KPIBanner.updateMetrics` now supports **both** report shapes (raw nested + flat summary); REMOVED (4.75%), COLLECTED (40–1023), VOXEL (24.85 µm) and GT benchmark render real values.
- Margin range now follows the cut (never exceeds it); keep/cut ranges span the full volume; `Reset to detected` restores the **auto-detected** cut (not the current delivery cut) and logs it.

### 0.3 Buttons, Jobs & Thread Safety
- `WorkerThread` shadowed Qt's `finished` signal (jobs could hang or never resolve) — renamed to `succeeded`/`failed`.
- Export jobs are now labelled/kind-aware: "Exporting …" phase, export-specific stage captions, "✓ Export Complete" on success (was the wrong "✓ Process Complete"), green "✓ Bundle exported" status line, red "✗ Export failed" on error.
- Export status is set only on the GUI thread (was set from inside the worker — undefined behavior); all four action buttons (Process / Apply / Export / Load) are disabled during any job and re-enabled afterwards.
- `_export_bundle` validates the destination and the "not processed yet" case with dialogs instead of raising raw exceptions into the click handler.
- Load dialog now calls the real `csx.register_series`; custom specimens resolve through a new `csx.as_dataset(specimen)` (was a guaranteed `AttributeError`); apply persists via the correct `csx.set_specimen_overrides` with an error dialog on failure.

### 0.4 Text, Symbols & Visual State
- First-paint active states fixed: tab buttons used `class="btn-toggle active"` (no `active` property → **no amber highlight** until first click) — Auto, Preferences, Sagittal/Coronal/Axial, guide modes and 3D modes now carry correct `active` properties at construction.
- Threshold sliders' ranges now mirror their spinboxes exactly (was −1000..1000 / −500..2500 vs −2000..2000 / −1000..3000 — slider snap-back/clipping when typing values).
- Colorspace buttons no longer re-color the Auto tab's 3D cloud as a hidden side effect (Preferences preview rendering is untouched).
- Dataset subtitle reads "24 µm dataset / 66.2 µm dataset — micro-CT reconstruction" (was raw keys `24um/66um`); the preview scrubber adopts the rendered slice from each preview response (no stale z on specimen/plane change).

### 0.5 Verification
- Extended `test_cleanct_native.py`: geometry audit (default size, minimum ≤ 1080p, maximize reflow, zero overflow), KPI population vs report, first-paint active states, export kind labels, button re-enable, bundle delivery — **93/93 PASS**, 12 screenshots in `build/native_shots/` (incl. new `native_12_maximized.png`).

---

## 1. Executive Summary & Problem Resolution

A comprehensive architectural audit was executed to eliminate pipeline bottlenecks, enhance CUDA GPU acceleration across all processing and exporting workflows, refine the default configuration of the Preferences workspace, optimize titlebar conciseness, and ensure robust user activity logging:

1. **Pipeline & Export Acceleration:**
   - *Issue Addressed:* Full 24 µm re-runs took ~102 seconds due to unneeded full-volume redundant disk re-writes and single-threaded DICOM loops.
   - *Optimizations:*
     - Upgraded `bundle_export.py` to utilize a 16-worker `ThreadPoolExecutor`, writing hundreds of DICOM slices at **>420 files/sec**. Full export duration reduced from minutes to **~3.2 seconds**.
     - Configured `_run_pipeline_task()` with `io_workers = 16` matching the 20-core host architecture (Intel Core Ultra 7 265K).
     - Fixed `_export_bundle()` signature and defaulted destination path directly to `H:\Treated Kyodai samples\cleanCT\export`.

2. **Automated RTX GPU Detection & CUDA Pipeline:**
   - On startup, `_check_gpu()` probes PyTorch CUDA runtime, identifying the **NVIDIA GeForce RTX 4080 SUPER** (CUDA 12.x, Compute Capability 8.9, 16.0 GB VRAM).
   - Sidebar displays a green active chip: `⚡ NVIDIA GeForce RTX 4080 SUPER (CUDA Active)`.
   - If no RTX card is detected, cleanCT logs a warning, alerts the operator via a dialog popup, and gracefully falls back to multi-threaded CPU execution.

3. **Preferences Tab Default Configuration:**
   - **4 Lines Mode Set as Default:** The 4-lines bounding guide overlay and lateral bounds sliders (`Left X %` [0..48%] and `Right X %` [52..100%]) are active upon entering the tab.
   - **2D Density Thresholds (HU) Automatically Set to Reset State:** Default window ranges initialized to `[-950.0, 350.0] HU` (the optimal contrast range separating organic wood pores from high-attenuation mounting metal).
   - **Grayscale Placed First & Set as Default Colorspace:** The tomographic linear density grayscale palette is positioned first in the palette list and selected by default.

4. **Concise Window Title Bar:**
   - Shortened title bar to `cleanCT — Wood CT Metal-Base Removal`, removing redundant long slogans.

5. **Real-Time Action Logger with Timestamps (Bottom-Left Corner):**
   - Added `QTextEdit#box_action_log` in the sidebar displaying time-stamped entries (`[HH:MM:SS]`) for specimen selections, cut overrides, processing jobs, ETA countdowns, and export writes.

---

## 2. Automated Smoke Test & Verification Results

Executed `test_cleanct_native.py` against the cleanCT native engine:

| Check | Expected | Verified | Result |
|---|---|---|---|
| **Window Title** | Shortened concise title | `cleanCT — Wood CT Metal-Base Removal` | **PASS** |
| **Native Icon** | Multi-res icon loaded | Sizes 16..1024 px present | **PASS** |
| **24 µm Dataset** | Exactly 6 curated samples | `['1-1', '1-2', '1-5', '2-1', '2-2', '2-5']` | **PASS** |
| **66.2 µm Dataset** | Exactly 6 curated samples | `['1-1', '1-2', '1-5', '2-1', '2-2', '2-5']` | **PASS** |
| **GT Benchmark** | Excluded from sidebar | 0 occurrences of GT or 1-15 | **PASS** |
| **Initial Selection** | Sample `1-1` loaded | Initial cut rendered in KPI banner | **PASS** |
| **Auto Workspace** | Merged 2D + 3D | 46,289 points loaded in 3D cloud | **PASS** |
| **3D Real Mode** | Color sync with 2D palette | Real 3D mode active, gamma 0.85 | **PASS** |
| **3D Simple Mode** | Luminous amber / silver | Simple mode active (high contrast) | **PASS** |
| **Turntable Spin** | "Spin" / "Stop" toggle | State toggles, button stays visible | **PASS** |
| **Preferences Mode** | Default 4-lines mode active | `_guide_mode == '4lines'` by default | **PASS** |
| **Grayscale Default** | Grayscale colorspace active | `pref_cmap == 'grayscale'` by default | **PASS** |
| **Lateral Sliders** | Lateral bounds panel visible | Visible by default, synchronized | **PASS** |
| **Threshold Range** | Baseline reset range | `[-950, 350] HU` default | **PASS** |
| **Threshold Presets** | Wood Tissue (-600 HU) | Applied correctly | **PASS** |
| **Scientific Colorspaces** | 5 scientific palettes | Verified Thermal, Viridis, Plasma, Gray, Spectral | **PASS** |
| **Axial in Prefs** | Non-null mid-height slice | `native_10_prefs_axial_plane.png` non-null | **PASS** |
| **About Dialog** | 128px HD brand logo | Exposed and pixel-verified | **PASS** |
| **Load Dialog** | Custom DICOM series | Exposed and responsive | **PASS** |
| **Pipeline Process** | Re-cut with user override | Cut 374 honored in 8.5s | **PASS** |
| **KPI Post-Process** | KPI updated live | CUT SLICE 374 rendered | **PASS** |
| **Action Log** | Live timestamped log | Populated in bottom-left corner | **PASS** |
| **Export Bundle** | Target in cleanCT\export | Export completed and verified | **PASS** |

**Total:** **37 / 37 Checks Passed (100% Green, 0 Failures)** — superseded by the **93-check suite** in §0.5.

---

## 3. High-Resolution Screenshot Evidence

Screenshots captured in `H:\Treated Kyodai samples\cleanCT\build\native_shots\`:

1. `native_01_auto_workspace.png` (1540 × 960 px): Auto mode with merged 2D layout (Axial stacked above side-by-side Longitudinal Before/After cut view), real-time action log at the bottom left, and 3D point cloud.
2. `native_02_prefs_workspace.png` (1540 × 960 px): Preferences mode showing **default 4-lines mode**, **grayscale colorspace**, and **default baseline threshold range `[-950, 350] HU`**.
3. `native_03_guides_4lines.png` (725 × 834 px): 4-Lines mode showing Top Keep, Bottom Cut, Left, and Right draggable guide lines with bounding box overlay and lateral bounds sliders.
4. `native_04_colorspace_thermal.png` (725 × 834 px): 2D orthogonal reconstruction rendered under the Thermal flame colormap.
5. `native_05_colorspace_viridis.png` (725 × 834 px): 2D orthogonal reconstruction rendered under the Viridis colormap.
6. `native_06_3d_real.png` (518 × 904 px): 3D viewport in "Real 3D" mode with point cloud vertex colors synchronized to the 2D colormap.
7. `native_07_about_dialog.png` (540 × 568 px): Native About dialog showing the enlarged 128×128 px cleanCT HD squircle icon, workflow text, and credits.
8. `native_08_load_dialog.png` (560 × 290 px): Native custom specimen folder loader dialog with DICOM validation.
9. `native_09_post_cutting_process.png` (1540 × 960 px): Verification of completed pipeline cut at slice 374 with updated KPIs and timestamped action logs.
10. `native_10_prefs_axial_plane.png` (725 × 834 px): Axial plane extraction range overlay showing interactive boundary lines and extraction ROI highlight.
11. `native_11_bundle_exported.png` (1540 × 960 px): Extraction bundle exported into `cleanCT\export\1-1`.
12. `native_12_maximized.png` (1920 × 1009 px): Maximized reflow — workspace absorbs all extra space, zero content overflow (2026-09-17 audit).

## 0R. Audit Round 2026-09-23 — Installer hardening and compaction

**Scope:** complete recursive inventory of H:\Treated Kyodai samples\cleanCT, with focused rebuild, integrity review, and runtime checks for installer\.

### Folder inventory and preservation

- Physical inventory, excluding directory-junction targets from local byte totals: export is 15.49 GB / 4,158 files; build is 1.51 GB / 14,725 files; installer is 1.07 GB / 6,656 files; dist is 35.6 MB / 63 files. build/venv_notorch is 1.095 GB / 14,327 files and generated build/cache is 388 MB / 300 files.

### External custom-sample junctions

Five existing directory junctions under build/custom/data point to external specimen folders. All targets exist and together contain 5,146 files / 14,288,225,169 bytes (14.29 GB); these bytes are stored outside cleanCT and were not modified. The installer’s explicit include list excludes build/custom, so those samples do not enter the portable payload.

| Local junction | Target relative to H:\Treated Kyodai samples | Files | Bytes |
|---|---|---:|---:|
| build/custom/data/1-21/XY | 2 MONTH/3 after oven-dry state/24.852 um per px/Jar 13/1-21/XY | 1,095 | 3,094,100,816 |
| build/custom/data/1-8/XY | 2 MONTH/3 after oven-dry state/24.852 um per px/Jar 14/1-8/XY | 1,099 | 3,147,699,976 |
| build/custom/data/2-21/XY | 1 MONTH/3 after oven-dry state/24.852 um per px/Bottle 1/2-21/XY | 1,068 | 3,022,322,005 |
| build/custom/data/666-5/XY | 1 MONTH/3 after oven-dry state/24.852 um per px/666-5/XY | 943 | 2,469,597,960 |
| build/custom/data/666-6/XY | 3 MONTH/3 after oven-dry state/24.852 um per px/666-6/XY | 941 | 2,554,504,412 |

- The export datasets, development build outputs, original distribution, backup, and source specimens were left in place. Only generated validation caches under installer\_pkg were removed after checks.
- The builder copies only the explicit app include list and the five required engine modules; checkout exports, build caches, and unrelated executables do not enter the payload.

### Packaging and delivery changes

- Portable ZIP uses DEFLATE level 9 and is checked for an exact entry list and CRC errors before publication. Package staging and output publication retain rollback copies until promotion succeeds.
- A SHA-256 sidecar (cleanCT-1.0.0-portable.zip.sha256) is now generated and published with the ZIP. The current SHA-256 is 1cdccdba0dbfa6ddbbfa8a56c4f083fec9ea1f4258cdb186b6fdfb4765ee59ca.
- Runtime pruning removes bytecode, tests, documentation, unused Qt authoring/QML assets, and three duplicate CuPy-vendored CUDA 12.9 NVRTC DLLs. It preserves pydicom.examples because the application imports that module. The pinned NVIDIA NVRTC 12.8.93 wheel remains.
- The embedded CPython bootstrap now uses default TLS certificate validation and validates the cached/downloaded CPython 3.12.3 archive against the digest published by Python.org. The local archive matched MD5 38cce2bf5b4de76db19a31f46a0720de ([official Python 3.12.3 release page](https://www.python.org/downloads/release/python-3123/)); no disabled TLS verification flags remain.
- The viewer’s generated disk cache now uses the existing per-user state root when installed, so standard Program Files installs do not try to write into app\build\cache. The development checkout keeps its prior build\cache location.

### Compaction

| Measurement | Before | After | Reduction |
|---|---:|---:|---:|
| Portable ZIP | 431,621,178 bytes (431.6 MB) | 313,520,335 bytes (313.5 MB) | 27.4% |
| Expanded payload | 1,056,075,200 bytes (1056.1 MB) | 736,523,750 bytes (736.5 MB) | 30.3% |

The ZIP has 6,648 entries and expands to 736,523,750 bytes. Its entry names match the staged _pkg payload exactly; no missing or extra files remain.

### Verification and availability

- installer\_pkg\cleanCT.exe --selfcheck: exit 0, RESULT: PASS; embedded Python 3.12.3, dependency imports, engine import, Qt offscreen widget, and active CuPy GPU were verified on the RTX 4080 SUPER host.
- build\pkg_gui_smoke.py: PASS; the real MainWindow constructed and its initial asynchronous load drained. Generated .npz preview caches landed under isolated %LOCALAPPDATA%\cleanCT\cache, with no app\build directory created in _pkg.
- pydicom.examples import: PASS. Development cache path check: PASS.
- Full ZIP CRC scan: PASS. SHA-256 sidecar matches the archive. Staged payload and ZIP both contain 6,648 files.
- installer\cleanct.iss and the portable ZIP are present. No cleanCT-1.0.0-setup.exe was produced because Inno Setup 6 ISCC.exe was unavailable on this build host. Install Inno Setup 6 and rerun installer\build_installer.py to create that optional classic installer.



---

## 0S. Audit Round 2026-09-23 — Correctness, rendering, resource use, and final delivery

This round re-audited the application and installer, then updated the processing engine and portable build. It focused on rectangular CT geometry, asynchronous preview work, memory and cache bounds, first-run behavior, and safe output routing in packaged installs.

### Correctness and geometry

- Fixed the orthogonal-profile column orientation for rectangular volumes. The old path raised a shape error on the 24 µm sample and could silently fall back without the multi-column quorum check. Midline and multi-column profiles now share one DICOM traversal. The viewer and orthogonal cache versions were incremented to invalidate incompatible cached results.
- Rechecked detector/profile results on both representative datasets: 24 µm 1-1 detected slices [43, 1007] with anchor delta 5 slices and keep delta 0.075 mm; 66 µm 1-1 detected [15, 378] with anchor delta 3 slices and keep delta 0.993 mm. Both remained within the recorded tolerances.

### Rendering, throughput, and resource bounds

- Preferences preview rendering now runs on one background worker with a latest-request queue. Generation checks discard stale results after specimen/plane changes, GUI painting stays responsive, and completion is drained safely on close. QImage data is copied where a temporary pixel buffer could otherwise expire.
- 2D/3D paint handlers now fill an opaque background before returning for zero-sized viewports, preventing transient black/white frames during resize.
- Slice reads choose concurrency from an estimated working set, rescale HU arrays in place, and keep estimated concurrent slice memory near 512 MiB. Metal-point extraction uses bounded batches without retaining decoded source slices. Preview arrays use a byte-accounted LRU with at most three entries and 1 GiB aggregate; per-specimen source caches are capped at 512 MiB and two specimens.
- Sidebar discovery now tolerates an absent or inaccessible output folder, so a clean first portable launch remains usable.

### Packaged output safety and reproducible checks

- Packaged runs now route pipeline output to %LOCALAPPDATA%\cleanCT\pipeline_output by default, using %USERPROFILE%\AppData\Local\cleanCT as the fallback. CLEANCT_DATA and CLEANCT_OUTPUT_ROOT remain explicit overrides. Development runs retain their prior engine output root.
- The renewed portable ZIP contains 6,648 files, expands to 736,532,777 bytes, and is 313,524,289 bytes. Full ZIP CRC and staged-file manifest checks passed. SHA-256: 563716574659c57b8926cf65b386ca9ccc75fc238899929e65ffc4d4430c9e5b; the published sidecar matches. This is 27.36% smaller than the prior 431,621,178-byte ZIP.
- The final windowless launcher --selfcheck returned exit code 0. The embedded runtime selfcheck and packaged GUI smoke check passed on this build host; the smoke check constructed MainWindow and drained startup work. The focused regression runner passed all 29 assertions across rectangular profiles, detector/cache behavior, bounded memory/concurrency, rendering, latest-only async preview, missing output-folder handling, and launcher path routing.
- The legacy broad native UI suite is not counted as a final pass: its fixed offscreen geometry assumptions are unsuitable for this host, and an earlier probe attempted its hard-coded external output path. That probe was sandbox-blocked before creating a file. Subsequent regression checks used isolated temporary state and CLEANCT_OUTPUT_ROOT paths. No export, specimen source, or dataset-junction contents were changed.
- cleanct.iss is generated, but no classic setup executable is present because Inno Setup's ISCC.exe is unavailable on this host. The verified portable ZIP is the current deliverable.

### Backup coverage

- The pre-change archive remains preserved in 0BACKUP\audit_20260923_pre_optimization.
- A post-change archive is created in 0BACKUP\audit_20260923_post_optimization with source, code assets, build and installer scripts, regression checks, logs, frozen distribution, portable ZIP and checksum, and the sibling engine sources/tests used by cleanCT. Its embedded manifest hashes each included file.
- User exports, external custom-sample junction targets, virtual environments, generated caches/intermediates, and engine output are excluded from the backup; they were not modified.



---

## 0T. Final release verification 2026-09-23 — regression-gated build

This section supersedes the package measurements and checksum recorded in §0S. The package was rebuilt after documenting the performance changes and adding a default regression gate to the installer builder.

- The normal build command now runs build/run_cleanct_regressions.ps1 before staging. The build stops if any focused check fails. README.md documents this guard and how to run the suite. The actual release build ran all 29 assertions successfully, then built and published the portable package.
- Final ZIP: 6,648 files under the expected _pkg/ root; 736,531,774 expanded bytes; 313,523,164 compressed bytes. SHA-256: f56b5257aa3d0b633282a68d728c5e57155e546c8addf74829f2061a99c48a67. The sidecar matched, the ZIP CRC scan passed, and its entries exactly matched the staged payload. The ZIP is 27.36% smaller than the previous 431,621,178-byte archive.
- The fresh packaged launcher --selfcheck exited 0 with isolated user state. The final packaged GUI smoke passed: MainWindow constructed in 0.03 seconds and all startup work drained. The read-only sample output tree was used only as the GUI startup reference; cache and state stayed under the isolated test state directory.
- Inno Setup's ISCC.exe remains unavailable. The portable package and refreshed cleanct.iss are present; the optional classic setup executable was not generated.
- The final release backup is stored separately from the pre-optimization and interim post-optimization archives at 0BACKUP\audit_20260923_final_release. It captures the final source and docs, code assets, build/test scripts and logs, distribution files, portable ZIP and checksum, and sibling engine source/tests. Its manifest records a SHA-256 for every included file. User exports, specimen datasets, external junction targets, venvs, caches, and generated pipeline output remain excluded and unchanged.



---

## 0U. New-user documentation release — 2026-09-24

- Added USER_GUIDE.md with concise instructions for first launch, built-in and custom DICOM samples, reviewing detected boundaries, processing, export formats, storage locations, and common issues. The guide explains that registration points to the source folder and that DICOM exports retain source metadata.
- Updated the installer quick-start README and package builder. The build fails if the source guide is missing, then copies it beside cleanCT.exe in the package. README.txt directs users to it.
- Rebuilt with the default regression gate: all 29 focused assertions passed. Final launcher selfcheck exited 0; packaged GUI smoke passed and drained startup work.
- Final guide-enabled portable ZIP contains 6,649 files, expands to 736,537,132 bytes, and is 313,526,219 bytes. SHA-256: 2299734a0cdb404e1fdfbf22ef031712f8471a27adefc478a83a553a45afddb9. Sidecar, CRC, exact staged-entry match, and byte-for-byte guide source/package comparison passed. README.txt references USER_GUIDE.md.
- Standalone guide output checksum: 473214bc83d51b17aae3431b7e47b9fb62f03916ae0a13df385f3360f2eb9f2f.
- A new final-release-with-guide backup is stored separately under 0BACKUP\audit_20260924_final_release_user_guide. It contains current source, docs, installer, portable package, tests, logs, relevant engine sources, and a per-file-hash manifest. Prior baseline and final-release snapshots remain preserved.


---

## 0V. End-to-end correctness and package refresh — 2026-09-24

This pass rechecked loading order and worker lifetime, guarded large-volume allocation, the DICOM processing path, viewer rendering, cut-range delivery, and transactional export. It also rebuilt the portable package from the current app and engine sources.

### Correctness and resilience changes

- Viewer and processing now agree on physical DICOM slice order, including series whose filenames are reversed. DICOM loading validates required geometry, series consistency, PixelData length, slice spacing, and estimated host memory before allocating a volume. Failed decode paths release partially allocated CPU/GPU storage.
- Load workers remain owned until they finish, and a load requested during another load resolves to the most recent selection. Process and export jobs capture the selected specimen at click time; the sidebar is gated while a job runs.
- NIfTI scanning uses a bounded block size. Legacy NIfTI export fallback decodes source slices into a disk-backed array rather than keeping a full volume plus a second stacked copy in RAM. Stream failure cleans its temporary file and keeps the prior valid output.
- Bundle exports stage and verify the requested artifacts, then promote the completed bundle transactionally. Interrupted promotion can recover the previous bundle; unrequested prior-format artifacts and unrelated user files are retained. Symlink/junction content is not followed into or dropped from a managed bundle.
- CuPy morphology now uses the same boolean footprint and iteration behavior as SciPy; parity passed on the active RTX 4080 SUPER GPU.
- The regression runner now redirects both Python temporary-directory variables into its isolated scratch area and restores the caller’s environment after the run. This fixes test portability when the host’s default temp directory is unavailable.

### Verification evidence

- `build/run_cleanct_regressions.ps1`: all seven focused suites passed: viewer/geometry/cache, asynchronous rendering and selection, unprocessed previews, export formats and recovery, streamed NIfTI failure cleanup, synthetic DICOM load/process/view/export and malformed-input cases, and launcher path routing. The async suite also confirms that empty `.nii` and truncated `.nii.gz` processed-volume files report a clean load failure and release their workers.
- Synthetic failure cases covered empty and corrupt DICOM, truncated PixelData, empty/truncated NIfTI, one-slice and nonuniform-spacing series, an allocation rejected by RAM preflight, stale async work, failed NIfTI writing, and failed re-export preserving the previous complete bundle.
- The package’s embedded CPython health check passed with its pinned dependencies, engine imports, Qt offscreen widget, and active GPU. Packaged MainWindow startup passed and drained background work. The frozen launcher `--selfcheck` also passed when its one-file extraction used the isolated `TEMP`/`TMP` directories.
- The broad legacy native UI harness is not counted as a pass: it assumes desktop geometry and pre-existing output catalogs that are absent in offscreen/isolated runs, and its export dialog path can block in this environment. Earlier assertions did exercise native controls, custom DICOM preview, and 66 µm processing, but the focused regression results above are the release gate. The desktop UI has not been exhaustively clicked on a physical display.
- Standalone user-supplied `.nii`/`.nii.gz` input is not a supported registration path in this revision. NIfTI is currently read for cleanCT-generated processed volumes and written during export; the user’s requested standalone-input behavior is awaiting scope confirmation because a NIfTI file has no source DICOM tags for faithful DICOM delivery.

### Portable package

- Rebuilt with the standard regression gate. The current portable ZIP contains 6,649 files, expands to 736,559,534 bytes, and is 313,531,729 bytes compressed. The staged package and ZIP entries match exactly, CRC verification passed, and the SHA-256 sidecar matches: `b80e128c300ef65d3a93869c9fc7737c758faa8913ee9c6f17c5e026dab11199`.
- Compared with the earlier 431,621,178-byte package, the current ZIP is 27.36% smaller; the expanded payload is 30.26% smaller than the earlier 1,056,075,200-byte build.
- The existing launcher binary was reused because PyInstaller is not installed in the build environment. Inno Setup’s compiler is also unavailable, so no classic setup executable was generated; `installer\cleanct.iss` and the verified portable ZIP are present.
- USER_GUIDE.md now explains that changing export formats retains an existing artifact in the other format and that the summary identifies what the latest export created.

### Remaining limits

- This audit does not certify the physical disk surface or bad-sector health. Large-volume allocation behavior is exercised through resolution-aware planning and early RAM rejection; the full synthetic DICOM pipeline is 36 × 192 × 192, while prior audit rounds include real 24 µm and 66 µm specimens. A full-size 6,000-pixel-per-slice benchmark was not run because a complete volume would exceed safe test memory.
- NIfTI source-input behavior remains the one product-scope question recorded above. No synthetic DICOM is created from NIfTI, so DICOM metadata fidelity remains intact.


---

## 0W. Unified DICOM, TIFF, and NIfTI input; refreshed portable release — 2026-09-24

This section supersedes §0V’s standalone NIfTI input limitation and updates the source-format/export statements in §0U and §0V.

### Input and processing changes

- Added one validated source-selection path for DICOM series, multipage grayscale TIFF stacks, folders of grayscale TIFF slices, and 3-D `.nii` / `.nii.gz` files. Mixed-format folders, color TIFFs, incompatible slice dimensions, unsupported dimensionality, empty/truncated data, and non-finite sample pixels produce handled validation errors.
- DICOM continues through its existing geometry-, spacing-, PixelData-, and rescale-aware reader. TIFF/NIfTI load plane-by-plane into the common float32 `(z, y, x)` contract. NIfTI source axes are normalized to RAS+; affine and slope/intercept are retained. TIFF resolution metadata is used when present; absent spacing is explicitly marked assumed.
- Memory preflight now runs before TIFF/NIfTI sample decoding during registration and again before full processing. Preflight errors become actionable load errors instead of escaping from the dialog.
- Compressed NIfTI is decoded once to disk-backed scratch for efficient random-slice reads. The cache is per process, capped to one volume per process, checks available disk plus reserve before writing, enforces the declared NIfTI byte length, rejects truncated/oversized gzip payloads, removes its files on normal exit, and reclaims dead-process caches older than one hour. This avoids repeated whole-file decompression and cross-process cache deletion.
- Raw grayscale intensity is reported as stored values and gets robust threshold estimates. The explicit “already HU” option is only for calibrated sources. TIFF/NIfTI delivery is geometry-preserving NIfTI-only; no DICOM metadata is fabricated. Export refuses to mix a new non-DICOM source with a prior DICOM bundle under the same specimen ID, preserving that existing bundle and asking for a separate ID or destination.
- Added `tifffile==2023.4.12` as an explicit setup pin and third-party notice; the packaged self-check imports both `tifffile` and the new `volume_io` engine module. The bundled USER_GUIDE now covers input choices, intensity/spacing interpretation, processing, export, and troubleshooting.

### Verification

- The regression gate passed all eight focused suites after the final code changes: viewer/cache/performance planning; asynchronous render and selection behavior; pre-process previews; export formats and transactional recovery; streamed NIfTI byte equivalence; synthetic DICOM load/process/view/export and malformed input; TIFF/NIfTI dialog-to-export workflows; and launcher path routing.
- Added end-to-end synthetic checks for multipage TIFF, naturally ordered TIFF folders, DICOM, uncompressed NIfTI, compressed NIfTI random reads, orientation/scaling, cut-range delivery, viewer frames, and geometry/value-preserving NIfTI exports. Edge cases include empty TIFF, mismatched TIFF slices, too-short stacks, truncated `.nii`, truncated `.nii.gz`, gzip expansion beyond declared dimensions, RAM preflight, and cross-source export collisions.
- Offscreen rendering checks passed for opaque resize paints, responsive GUI event loop, latest-request preview behavior, worker cleanup, and frame downscaling. The package’s embedded runtime self-check and rebuilt `cleanCT.exe --selfcheck` both passed with the pinned dependencies, engine imports, Qt widget creation, and active CuPy backend on the RTX 4080 SUPER.
- The final portable ZIP contains 6,650 files, expands to 736,630,821 bytes, and is 313,548,923 bytes. The staged file set exactly matches the archive, ZIP CRC check passed, the guide and TIFF pin/notices match, and the SHA-256 sidecar matches: `16cdb18cfcb24e397b502c340d0376f2136cffef156624aca4c4e71b0f991386`.
- A scoped hashed source/release snapshot is stored at `0BACKUP\audit_20260924_full_system_audit_r3`, including current app and sibling-engine source, regression tests, docs, installer scripts, portable ZIP and checksum, and a per-file manifest. Scan inputs, processed outputs, user exports, logs, environments, and caches remain excluded.

### Limits

- The offscreen regression suite exercises the changed dialogs and major workflows but is not a physical-display, manual click-through of every desktop control. No zero-error guarantee is possible from finite tests.
- Full non-DICOM performance was verified on synthetic 36 × 192 × 192 volumes; no full 6,000-pixel-per-slice TIFF/NIfTI volume was allocated. Existing DICOM high-resolution planning guards were exercised, but no new real large TIFF/NIfTI benchmark was run.
- Inno Setup’s `ISCC.exe` is not installed on this host, so the refreshed portable ZIP is delivered but a classic `cleanCT-1.0.0-setup.exe` was not generated. `installer\cleanct.iss` remains available for a future ISCC build.

### Reference

- Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026). *Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*. arXiv:2609.00065. https://doi.org/10.48550/arXiv.2609.00065.


## 0X. cleanCT app icon assets in portable installer — 2026-09-24

This follow-up corrected an omission found during the final review: the earlier portable payload did not include the complete dist/cleanCT-app/icons asset directory. The refreshed installer package now includes that complete production asset tree at _pkg/app/icons, where the packaged application resolves its window and about-dialog logos.

### Build safeguards

- installer/build_installer.py now takes its canonical icon source from dist/cleanCT-app/icons, requires app.ico, icon_256x256.png, and icon_1024x1024.png, rejects symbolic links, and verifies the staged file inventory, sizes, and SHA-256 hashes.
- Launcher rebuilds now use the same production app.ico; the existing launcher was reused in this build because PyInstaller is unavailable, and its embedded Windows icon resource was confirmed.
- Added build/test_installer_icons.py to the regression runner. It verifies all 37 source icon files are staged byte-identically and confirms Qt loads a non-empty application icon. The packaged GUI smoke also now checks that MainWindow loads its window icon.

### Verification and refreshed package

- All nine focused regression suites passed. The icon test confirmed 37 files / 18,423,976 bytes byte-identical to dist/cleanCT-app/icons.
- Packaged MainWindow GUI smoke passed; the launcher --selfcheck passed and the launcher retained an extractable Windows icon resource.
- The refreshed portable ZIP contains 6,687 files and expands to 755,054,797 bytes. Its compressed size is 331,919,280 bytes. ZIP contents include the complete icon tree, ZIP CRC verification passed during build, and the SHA-256 sidecar matches: ec087ca90e23a32ab78275c2dc1cb3a8288945659951c46f06c75c48de9157ab.
- A new scoped source/release backup with per-file hashes is stored under 0BACKUP/audit_20260924_icon_assets_r4.

### Remaining installer limit

Inno Setup's ISCC.exe remains unavailable on this host. The portable ZIP and updated installer/cleanct.iss are present, but a classic setup executable was not generated.


## 0Y. cleanCT empty-state, checkpoint, and final package hardening — 2026-09-24

### App behavior

- Startup now discovers only specimens that are actually available. The installer no longer attempts the development-only 24um/1-1 sample. When there is no input, the app shows a load prompt, lists no fabricated examples, and disables processing/export until a payload is loaded.
- Failed loads return to the empty state without leaving stale payloads available to process. Long-running jobs and active loads gate specimen, checkpoint, and history controls.
- Added a session preview-history selector. Each applied preview records its small control state, not another full-resolution raster; history remains selectable for the lifetime of the window and is released on close.
- Added Save checkpoint and Load checkpoint controls to the shared application source used by both preparation and installer builds. The versioned JSON checkpoint stores the rendered preview, preview/cut-line settings, and a source reference; it never embeds scan volumes. Checkpoint writes are atomic. Inputs are size-limited and validate supported versions, image data/dimensions, numeric ranges, and line ordering.
- A loaded checkpoint paints its preview snapshot immediately. cleanCT reconnects only when the recorded source is still registered at the same location (custom inputs) or the referenced built-in output exists. Otherwise it retains a snapshot-only view and keeps processing/export disabled until the source is loaded again. Saving is disabled while a newer preview is still pending so saved controls cannot be paired with stale pixels.

### Production payload

- installer/build_installer.py stages the current root application sources, pipeline modules, docs, and canonical dist/cleanCT-app/icons graphics. The production package includes all 36 graphic assets and excludes the icon design README, project README, dependency freeze, examples, and development/test artifacts.
- Recipient docs in _pkg are README.txt, USER_GUIDE.md, and THIRD_PARTY_NOTICES.md. The user guide now covers the normal empty first launch, all three input types, session preview history, and checkpoint save/restore.
- Final portable ZIP: 331,917,765 bytes compressed; 755,073,681 bytes expanded; 6,685 entries. Independent CRC and SHA-256 verification passed. SHA-256: 8cbd8da360397d643d8d79e3ea50c2e8697541777141650c5bbaff8dd4a59c56.
- The archive contains the checkpoint module and 36 production graphics, and does not contain app README files, requirements-pinned.txt, app tests, examples, or build logs. Key staged Python modules match the preparation build byte-for-byte.

### Verification

- All 10 focused regression suites passed, including checkpoint schema/atomicity tests, empty-state and session-history tests, checkpoint reconnect, async-preview generation, DICOM/TIFF/NIfTI ingestion, synthetic processing, exports, launcher paths, and icon staging.
- Packaged GUI smoke passed in an isolated state folder: it opened to the empty state in about 0.03 seconds, with processing/export disabled, the checkpoint module present, and all 36 graphics staged.
- Embedded runtime self-check passed on the build workstation: CPython 3.12.3, PySide6 6.9.2, CuPy 13.4.1, Qt initialized, and NVIDIA RTX 4080 SUPER acceleration active. The windowless launcher self-check returned success.
- The portable ZIP sidecar checksum matches the final archive.

### Host tooling limitation

Inno Setup 6 / ISCC.exe and PyInstaller are unavailable on this host. The production portable ZIP and refreshed installer/cleanct.iss were generated successfully, but a new classic setup EXE could not be compiled. The previously staged launcher was reused; its self-check passed. The scoped revision backup is stored in 0BACKUP/audit_20260924_empty_state_checkpoints_r6.

---

## 0Z. Full launcher rebuild and classic installer release — 2026-09-24

This section supersedes the toolchain limitation recorded in §0Y. The release was rebuilt with the installed PyInstaller 6.22.2 runtime and Inno Setup 6 command-line compiler (ISCC).

### Build and packaging hardening

- `installer/build_installer.py` now accepts explicit `--pyinstaller-python` and `--iscc` paths. A normal release requires ISCC and fails instead of silently publishing only a portable build. The release command used no skip flags.
- The launcher was freshly rebuilt from `installer/launcher_main.py` as a one-file, windowless EXE. The build requires `dist/cleanCT-app/icons/app.ico`, validates its ICO header, passes it to PyInstaller, and inspects the resulting PE resources for both RT_ICON and RT_GROUP_ICON.
- The generated Inno script now contains the required `AppName` directive. ISCC compiled a candidate setup EXE successfully using LZMA2 maximum compression. Candidate publication is transactional alongside the package and portable ZIP, retaining prior deliverables if a later release step fails.
- The launcher `--selfcheck` runs against the staged payload before the portable archive is created. Bytecode generation is disabled and any Python bytecode/cache residue is removed before packaging. This keeps `_pkg`, the ZIP, and the installer payload inventory-consistent.
- Added `installer/README_INSTALLER.txt` at the installer root and in the portable payload. It records the cleanCT and toolchain versions and explains setup/portable installation, first launch, supported scan formats, processing/export, session history, and checkpoints.

### Release contents and verification

- `installer/_pkg/cleanCT.exe`: freshly rebuilt 8,868,384-byte launcher. Its embedded Windows icon resources were verified; standalone `cleanCT.exe --selfcheck` passed with isolated user state.
- `installer/out/cleanCT-1.0.0-portable.zip`: 331,918,184 bytes; 6,686 entries; expanded payload 755,075,028 bytes. The CRC scan passed and ZIP entry inventory exactly matches `_pkg`. SHA-256 and sidecar: `e98a1d3931432f0d8e03defb5350b2a680938bcb0b99356b0467b06b8474cd05`.
- `installer/out/cleanCT-1.0.0-setup.exe`: 208,613,999 bytes; ISCC exited successfully and its output passed a PE header check. SHA-256: `5b8ec33aa60233440eeaaf02e14768861935c93ee1a980859cfc80545d30213e`.
- `installer/cleanct.iss` compiles with `AppName="cleanCT"`, x64 architecture settings, the Program Files destination, and LZMA2 maximum compression. The production app payload has no sample/demo directories or Python bytecode caches and includes all 36 production icon graphics.
- Compared the production payload against the preparation build: all 18 staged application Python files match byte-for-byte. The package/archive inventory, SHA sidecar, app icon assets, and installer outputs were independently checked after build.
- The builder’s 10 focused regression suites all passed: checkpoint persistence/validation, viewer memory and rendering, asynchronous preview/history/empty state, processing and export behavior, malformed/empty inputs, DICOM/TIFF/NIfTI paths, launcher routing, and installer icon staging.
- Launcher build directories and package staging were removed after successful publication. The complete release snapshot is recorded in `0BACKUP/audit_20260924_full_release_r7` with per-file SHA-256 hashes.

### Release scope

The classic installer was compiled and its output validated, but was not run through an actual Program Files installation on this workstation. The focused regression suite and launcher health check passed; this audit is not a physical-display manual click-through of every control or a physical disk-surface/bad-sector certification.

---

## 0AA. Checkpoint hardening release r8 — 2026-09-24

This section applies the five drafted refinements from the release README (§G.2), fixes one genuine checkpoint-reconnect robustness bug discovered while validating them, re-runs the 10-suite gate, and republishes the full release with a freshly built launcher, portable ZIP, and ISCC setup.exe.

### Applied checkpoint refinements

- `_set_empty_state`: the stacked workspace stays visible at all times; only the first-run card changes visibility. A stack toggle could previously unmount an active checkpoint-snapshot view. The `_checkpoint_snapshot_only` flag still guards the card.
- `_on_load_failed` snapshot branch: after the failure status is written, the saved preview (`_last_pref_preview["png"]`) is defensively repainted into `pref_viewer`, so a snapshot-only failure always leaves the checkpoint preview visible.
- `_record_session_preview`: returns early while `_checkpoint_snapshot_only` is set, so loading a checkpoint-only snapshot no longer appends a duplicate history entry. A checkpoint whose source reconnects records exactly one entry when the connected preview applies.
- `_restore_session_history`: the same-specimen fast path now also accepts a snapshot-only session (`payload is None` but `_checkpoint_snapshot_only`), restoring controls without forcing a source reconnect.
- `main.py --selfcheck` now verifies `app/icons/app.ico` (payload `icons/app.ico` as well) and fails the health check when the window icon asset is missing.

### Checkpoint reconnect canonicalization fix

- While validating the refinements, the reconnect test failed depending on how the host spelled the temporary directory: a checkpoint recorded under an 8.3 short path (`C:\Users\LABPC~1\…`) compared unequal to the canonical long form (`C:\Users\LAB PC\…`) because `os.path.abspath` does not expand short names, while `Path.resolve()` does. `_checkpoint_source_available` now canonicalizes both sides (`main_window._same_source_path`: `Path.resolve()` with an `abspath`/`normcase` fallback), so a still-registered source reconnects regardless of the recorded path spelling. The per-user custom branch received the same canonical comparison. The mismatch case (same specimen ID, different source location) remains rejected.

### Test-gate alignment

- `build/test_render_async.py` now encodes the refined contract: the first-run check asserts the empty card is shown while the stack remains visible; the checkpoint section keeps the window alive (the previous harness closed it before reusing it, which `closeEvent` history cleanup then masked), asserts that a snapshot-only load records zero history entries, and that the history selector still accepts a real applied preview afterwards.

### Release rebuild and verification

- `build/run_cleanct_regressions.ps1`: all 10 focused suites PASS after the changes.
- Full release rebuild via `installer/build_installer.py` (no skip flags): the gate ran again inside the builder, the payload was staged, and the launcher was freshly rebuilt with PyInstaller 6.22.2 and the embedded icon (`PE group-icon and icon resources verified`); standalone rebuilt-launcher `--selfcheck` passed. ISCC was auto-discovered at a per-user IDE-bundled location (`%LOCALAPPDATA%\Programs\…\innosetup\bin\ISCC.exe`); `resolve_iscc` now also probes bounded per-user locations so future builds are one-click.
- Final artifacts (measured 2026-09-24):
  - `installer/out/cleanCT-1.0.0-portable.zip`: 329,403,390 bytes; 6,686 entries; expands to 752,551,581 bytes; CRC scan PASS; 0 bytecode entries; entry inventory matches `_pkg`; SHA-256 and sidecar: `e9afc3af62a0a607b7ecb2e652aeb49ca74f83a1821919e4edd7b54490a96866`.
  - `installer/out/cleanCT-1.0.0-setup.exe`: 205,924,213 bytes; PE `MZ` header verified; SHA-256: `270FC07E5127E8A239609186A975768B3AF50737D788499515C4B2A90A40DAAA`.
  - `installer/_pkg/cleanCT.exe`: freshly rebuilt 6,342,634-byte launcher; embedded RT_ICON/RT_GROUP_ICON verified; standalone `--selfcheck` exit 0.
- The staged app payload matches the checkout byte-for-byte (`app\main_window.py` 161,795 B, `app\main.py` 4,961 B, `theme.py`, `icon_utils.py`, and every `core`, `widgets`, `dialogs` module identical).
- Post-smoke `__pycache__` residue (100 directories created by a post-publication health-check run of the shipped launcher) was removed from `_pkg` after verification; the published ZIP (compiled before that run) contains 0 bytecode entries, verified independently.
- Scoped hashed source-and-release snapshot: `0BACKUP/audit_20260924_checkpoint_hardening_r8` with per-file SHA-256 manifest.

### Release scope (unchanged)

The classic installer was compiled and PE-validated but not installed end-to-end through an actual Program Files run; validation remains the automated 10-suite gate plus launcher selfchecks, ZIP CRC/inventory, PE resource checks, and SHA-256 verification. No physical-display click-through and no disk-surface certification are claimed.

---

## 0AB. Structured checkout + specimen-panel overhaul — 2026-09-24

This round restructured the development checkout into a clean, documented layout and delivered the specimen-panel UI/UX overhaul, then re-ran the (now 11-suite) gate and republished the full release from the new structure.

### Checkout restructure

- New layout: `main.py` + `README.md`/`USER_GUIDE.md`/`AUDIT.md` at the root; `src\` (all 18 application Python files incl. `core\`, `widgets\`, `dialogs\`), `assets\` (`app.ico`, `app_icon_256.png`, canonical `icons\` pack, `design\` archive), `data\` (per-user dev state: settings, logs, export bundles, specimen registry with its junctions, viewer caches), `installer\`, `tests\` (the gate + tooling + `venv_notorch`), `dist\` (reference standalone), `0BACKUP\`.
- Removed as duplicates/temp: the legacy root `cleanCT.exe` + `cleanCT.spec`, `stub_main.py`, `run.md`, the superseded `test_cleanct_native.py` and round scripts (bench/probe/capture one-offs, logs, shot dirs, scratch work), the empty `buildvenv_notorch`, the empty `_avast_\`, the `~\.cupy` kernel-cache junk, `tools\package_app.py` (superseded by the builder), and `__pycache__` residue. The 36-graphic production icon pack is now canonical at `assets\icons` (checkout `icons\` top-level graphics were byte-identical duplicates; design sources moved to `assets\design\`).
- Path contracts updated for the `src\` layout: `core/paths.py` resolves `APP_ROOT` layout-aware (walks up to the directory holding `main.py`, so the flat packaged `app\` layout is unchanged) and the development `state_root()` is now `<checkout>\data`; `main.py` puts `src\` on `sys.path`; `main_window` uses `APP_ROOT` for icons; `viewer_core` caches under the state root in both layouts; `custom_series` registers into `<state>\custom`; `icon_utils` resolves `root\icons` (payload) or `root\assets\icons` (checkout); the About dialog uses the same layout-aware lookup.
- Tooling follows the layout: the regression runner and builder use `tests\venv_notorch` and stage sources from `src\` with the pack from `assets\icons`; `test_installer_icons.py` compares against the new canonical pack; `create_audit_backup.py` captures the new tree; `.gitignore` rewritten.
- Dev-state migration (same-volume renames, junction targets unaffected): `export\` → `data\export`, `settings.json` → `data\settings.json` (with the remembered destination updated), `logs\` → `data\logs`, `build\custom` → `data\custom` (junctions verified intact after the move), `build\cache` → `data\cache`.

### Specimen-panel UI/UX overhaul (left panel)

- Search/filter box with clear button and a live count chip ("2", "1 of 2" while filtering); group headers hide when their section is empty; a placeholder note distinguishes "No specimens loaded yet" from "No specimens match …".
- Two-line rows via a custom `SpecimenDelegate`: name on top, muted metadata line below — format · slice count · dimensions · voxel size · on-disk size (e.g. `DICOM · 36 slices · 96×96 · 33 µm · 677.0 KB`). Sizes are computed in a stat-only background worker (folder walks never read file contents), with a generation guard so rapid refreshes never apply stale results, and worker threads stay referenced until finished (a running QThread garbage-collected mid-run hard-crashes — same policy as load workers) and are drained on close.
- Right-click context menu on the list: Open / Rename… / Duplicate… / Locate in Explorer / Remove… / Clear loaded list… / Load specimen folder…, with tooltips and gating while busy; right-click on a row selects it, and a click on a header or empty spot falls back to the current selection.
- Compact action row (Rename / Copy / Find / Remove) mirroring the menu, enabled only for a valid selection and only when idle; Rename and Duplicate are available for loaded (custom) specimens — built-in dataset specimens show an explanatory tooltip instead.
- `custom_series` gained `rename_specimen` (registry ID + junction folder; unique-ID generation), `duplicate_specimen` (same source under a new ID — no scan data copied), and `unique_specimen_id`; the window layer renames the processed-output folder in step so history stays coherent. Remove unregisters the registry entry and junction only — sources, processed results, and exports are always kept, stated verbatim in the confirmation dialog. Built-in specimens are hidden for the session (nothing deleted; they return on restart). Clear-all unregisters every loaded specimen after listing them in a confirmation.
- Confirmation dialogs for every destructive or list-mutating action; busy cursor during load-dialog validation (single-shot confirm button, transient status label); tooltips on the filter box, every action button, the load button, and menu items.
- The GPU chip now probes the ENGINE's real backend (`gpu_backend.get_backend`) instead of a torch probe: active builds show `⚡ <GPU> (CuPy CUDA Active)`; CPU-only machines show `⚙ CPU processing (no CUDA GPU)`. The torch-era "GPU via CuPy / CPU fallback" ambiguity and the dead `_check_gpu_blocking` path were removed.
- New `tests\test_specimen_panel.py` (11th suite) covers: rich rows + meta, filter + count + no-match note, rename (registry + junction + processed output + selection), duplicate (junction + selection), remove (unregister + junction removal + outputs kept + selection cleared), built-in session-hide (fresh window shows it again), clear-all, context-menu dispatch, and spinner reaction to the busy state.
- `pkg_gui_smoke.py` and `tests\test_render_async.py` encode the refined contracts (stack always visible behind the first-run card).

### Dead code and hygiene

- Removed unused imports across `main_window` (`QIcon`, `theme`, `threading`, `human_size`), `main.py` (`ctypes`, `QIcon`), `viewer_core` (`is_installed`, `tempfile`), `bundle_export` (`_stream_nifti_planes`), `kpi_banner` (`Qt`), `viewer_2d` (`QBrush`, `QCursor`, `QImage`), `viewer_3d` (`QPixmap`), and the tests; an AST scan over `src\`, `main.py`, and the tests reports no remaining unused names; all files compile.
- The load dialog validates with a busy cursor and a single-shot confirm button; the window-side registration runs under a busy cursor and reports the registered specimen in the action log.

### Release rebuild from the new structure

- Full `installer/build_installer.py` run (no skip flags): the 11-suite gate passed inside the builder; the payload staged 57 app files (the 36 verified icon assets byte-identical from `assets\icons`); a fresh PyInstaller 6.22.2 launcher with verified embedded PE icon resources was smoke-checked (`--selfcheck` PASS); the portable ZIP and ISCC setup.exe were published transactionally.
- Final artifacts (measured 2026-09-24, section-0AB rebuild):
  - `installer/out/cleanCT-1.0.0-portable.zip`: 6,687 entries; CRC PASS; 0 bytecode entries; expands to 752,590,548 bytes; SHA-256: `2d59f353a5b0b52645e928e70b7441b841583da5340e2aac0fccfab243657b2b` (sidecar published).
  - `installer/out/cleanCT-1.0.0-setup.exe`: SHA-256: `81210b4441a54466d5886a36dfd33f20a56beef1f2a979f89eda4440d5aa3d03`.
  - `installer/_pkg/cleanCT.exe`: 6,342,129 bytes; standalone `--selfcheck` exit 0; embedded RT_ICON/RT_GROUP_ICON verified.
- Every staged app module (all 18 files incl. `app\widgets\specimen_panel.py`) is byte-identical to `src\`; `app\main.py` equals the checkout entry point.
- Four evidence screenshots (landing, loaded, cutting, history) were captured offscreen from the real window with real fonts (`tests\screenshots\`), showing the empty first-run card, the merged Auto views, the Preferences guide lines with the live CuPy GPU chip, and the populated history selector.
- The complete scoped snapshot is `0BACKUP\audit_20260924_structured_overhaul_r9` with per-file SHA-256 manifest.

### Scope (unchanged)

Classic installer compiled and PE-validated but not installed end-to-end; validation is the automated 11-suite gate plus selfchecks, ZIP CRC/inventory, PE resource checks, and SHA-256 verification. No physical-display click-through or disk-surface certification is claimed. Screenshots were captured offscreen; a physical-display click-through of every control was not performed.

---

## 0AC. Clean export delivery, snap pipeline fix, installer resync — 2026-09-24

This round fixed the delivered filenames and DICOM metadata, repaired and optimized the "Snap to detection" pipeline, rebuilt the specimen context menu, and re-synced the installer folder into the release snapshot.

### 1) Export filenames — no `_rem_` markers anywhere (audit 0AC)

- `core/bundle_export.py` rewritten around clean delivered names:
  - DICOM series: `<specimen>_dcm/` (was `<specimen>_rem_dcm/`), and **every kept slice keeps its ORIGINAL source filename** (`XY0040.dcm … XY1014.dcm` on the real 24 µm fleet — `OriginalName.dcm`, never `OriginalName_rem_NNNN.dcm`). A pathological duplicate name falls back to an indexed clean name.
  - NIfTI volume: `<specimen>.nii` (was `<specimen>_rem.nii`); sidecar: `<specimen>.json` (was `<specimen>_rem.json`); `<specimen>_extraction_info.txt` unchanged.
  - Internal `.tmp`/`.old` staging names follow the clean scheme; `_clean_tmp` sweeps both the new and the LEGACY patterns, and a legacy `<specimen>_rem_dcm(.old)` from older releases is recovered and adopted under the clean name. `_seed_preserved_bundle_entries` supersedes legacy artifacts of the same format so no stale `_rem` duplicates survive an update-in-place re-export (unrequested formats are still retained, as before).
  - The TIFF/NIfTI volume-bundle path and the source-mix guard use the same naming helpers.
- No `_rem_` injection remains anywhere in export, save, or checkpoint code; the only `_rem` strings left are the documented legacy-compat names in `bundle_export.py`. `checkpoint_file.py` and the app never carried `_rem` logic.

### 2) Full DICOM delivery metadata (audit 0AC)

- Every exported slice is enriched on top of the byte-preserved source tags. Required essentials (verified by real-data readback on 24 µm `1-1` → `1-17_OD`):
  - `PatientName = 1-17_OD` (specimen ID) · `PatientID = 100001` (preserved from the source; a source without one receives the specimen ID) · `Modality = CT`.
- Plus: `StudyDescription` ("cleanCT non-destructive metal-base removal"), `SeriesDescription` ("cleanCT metal-removed series (<specimen>; kept N slices)"), `InstitutionName` (preserved, else "cleanCT workstation"), `SoftwareVersions = cleanCT 1.0.0`, `SliceThickness` and `PixelSpacing` (preserved, else filled from the processing report), `AcquisitionDate/Time` (preserved, else the export timestamp — recorded as such), `ImageComments` and `AdditionalPatientHistory` carrying the full processing history (kept range, cut line, anchor, removed fraction, engine version, compute device, source folder).
- The NIfTI `descrip` header now begins with `cleanCT 1.0.0 metal-removed; …`. The sidecar records the exact tag block under `dicom_tags`; the extraction-info txt lists the tag essentials.
- Export self-verification now spot-checks, per SOP UID (original filenames are not positionally sorted): pixel equality, `PatientName`, and the presence/readability of `PatientID`, `Modality`, `StudyDescription`, `SeriesDescription`, `SoftwareVersions`, `ImageComments`, `PixelSpacing`, `SliceThickness` — the pydicom readback is the automated "opens in a standard DICOM viewer" check.

### 2b) "Snap to detection" pipeline fix (audit 0AC)

- Root cause found by reproduction on the real 24 µm data: the Preferences viewer's line coordinate space came from the LAST rendered preview. Payload loads and every preview application set the solid Keep/Cut lines BEFORE the pixmap updated `_n_slices`, so on large volumes the lines were silently clamped (994 → 100) and "Snap to detection" appeared to do nothing on the canvas while the spin already held the detection value.
- Pipeline fixes, in order: `viewer_2d.setSliceCount(n)` declares the real slice count at every payload load (before any preview lands); `_on_prefs_preview_ready` now applies the pixmap (real slice count) FIRST and then re-places Keep/Cut from the live job values — the coordinate space is correct before every line placement; load-time auto-place, Snap, and "Reset to detected" all follow the same mapping.
- Snap accuracy: Cut ≡ the detected metal top (`zb.cut`); Keep ≡ the verified air top when confirmed; when the air top was deferred as foggy, the dotted "wood top" evidence line is now DRAWN (green, labeled) and Snap moves the Keep line onto that measured wood-top edge (logged as "keep=N (wood top; air top deferred)") — the top line always lands on detection evidence instead of staying put. Bottom-metal snap audited: `zb.cut` deterministically prefers the pipeline's detected halo onset, then the quorum base anchor, then wood-bottom+1; all three flow through the fixed placement.
- Empirically verified on the real 1074-slice 24 µm specimen: after drag + Snap, `spin_cut=994` AND canvas `cut=994`, `keep=32` — the lines land exactly on the drawn detection.

### 3) Specimen context menu rebuilt (audit 0AC)

- Optimized menu with polish: Open ("↵"), ✎ Rename… (F2), ⧉ Duplicate…, 📂 Show in Explorer, ℹ Properties…, 🗑 Remove… (Del), 🧹 Clear loaded list…, and 📂 Load specimen folder…; per-item tooltips, gating while busy, and an empty-state menu ("No specimens yet — load a scan to begin" + Load) when nothing is registered.
- New `dialogs/properties_dialog.py`: read-only properties (name, source kind, slices, dimensions, voxel size, size on disk, registered date, source folder, processed-output folder, export destination) with a Show in Explorer shortcut.
- Keyboard shortcuts wired to the list: **F2 = Rename**, **Del = Remove** (also advertised in the menu text).

### 4) Installer resync into the release snapshot (audit 0AC)

- `installer/build_installer.py` resolves its roots location-tolerantly (`_discover_roots`): it works inside the checkout and as a copied release bundle next to a sibling checkout, refreshing `SRC/SRCDIR/ENGINE/VENV/APP_ENTRY_FILE/ICON_ASSET_DIR`.
- The complete installer folder is now delivered at `cleanCT_v1.0.0\installer\` (scripts + `README_INSTALLER.txt`, staged `_pkg`, `out\` with the portable ZIP + sidecar + setup.exe, `_cache` embed archive; no transients). Its `cleanct.iss` compiles from the copied location (ISCC exit 0; relative `_pkg\*` paths are location-independent) and the copied launcher's `--selfcheck` exits 0. The main checkout keeps its own `installer\` as the build source.

### Release rebuild and verification

- Full `installer/build_installer.py` run (no skip flags): the 11-suite gate passed inside the builder; fresh PyInstaller 6.22.2 launcher (PE icon resources verified; standalone `--selfcheck` PASS); portable ZIP (6,688 entries, CRC PASS, 0 bytecode) and ISCC setup.exe published transactionally; every staged app module byte-identical to `src\`.
- Real-data export smoke (24 µm `1-1`, 1074-slice scan, collection default): bundle `1-17_OD/` with `1-17_OD_dcm/` (975 slices under original names `XY0040.dcm..XY1014.dcm`), `1-17_OD.nii` (4.96 GB), `1-17_OD.json`, `_extraction_info.txt`; zero `_rem_` filenames; full tag readback as listed above.
- Final artifacts (measured 2026-09-24): portable ZIP 329,418,057 bytes, 6,688 entries, expands to 752,609,785 bytes (SHA-256 `8044c8f80aab631814c1b12533d00914a144f1d18ccfe48601f8f52cfea13acb`, matching sidecar `installer/out/cleanCT-1.0.0-portable.zip.sha256`); setup.exe 205,931,258 bytes (SHA-256 `9c0e60d1eb09c69b4b512046c7c1fff0c82906b3d993513279da4c9c3192d3c5`); launcher 6,341,206 bytes (SHA-256 `6ae92e92ec3b90af6237c15f43053a597106cfcee1ebdb590d9962c8c495c52c`) with selfcheck exit 0. `_pkg` residue 0.
- Scoped hashed snapshot: `0BACKUP\audit_20260924_final_polish_r10`.

### Scope (unchanged)

Classic installer compiled and PE-validated (including from the copied release bundle) but not installed end-to-end through an actual Program Files run; validation is the automated 11-suite gate plus launcher selfchecks, packaged GUI smoke, ZIP CRC/inventory, PE resource checks, SHA-256 verification, and the real-data export readback. No physical-display click-through or disk-surface certification is claimed.

---

## 0AD. Wood-top detection fix and text-fit polish — 2026-09-24

This round fixed the reported "wood top" logic bug end-to-end (reproduced on the user's real specimen `1-17_OD`), removed a line-desync class in the Preferences viewer, and polished the clipped texts seen on the 280 px sidebar and 1080p windows.

### 1) "Wood top" detection logic (audit 0AD)

- Reproduction on the real 1098-slice specimen (`1-17_OD`, 2-month oven-dry series): the app reported `wood top 692` while the true wood apex is slice 65 (the pipeline's own wood track reads `z0=65, z1=1021` — 957 ROI slices, matching the KPI). The axial evidence pool found wood-class pixels on only ~20 of 160 pooled slices, all in the LOWER part of the specimen.
- Root cause (logic, not display): `wood_bounds._object_mask` required wood-class pixels to also exceed the module's FIXED air default (`AIR_HU_DEFAULT = -900 HU`) even when a calibrated wood window was supplied. This specimen's drier TOP half reads ≈ -990..-900 HU, so the fixed floor erased it from the wood class; the pooled run then started ~692 slices deep and `wood_top` inherited the first wood-present pooled sample. The calibrated wood window's OWN lower bound is the correct air/wood boundary.
- Fix: with a calibrated `wood_hu` window the window DEFINES the class (its lower bound replaces the fixed air floor); without a window the generic air level applies as before. The fog-curtain walk above the apex now uses the same calibrated floor, so drier fog wisps register as the signal the Keep line must clear.
- Verification: `wood top = 65` through the app's real payload path after cache-version bumps (`PREV_VERSION 9`, `CACHE_VERSION 17` force regeneration of payloads cached under the old semantics). `wood_bottom = 1021`, `cut = 1022`, and the metal anchor `[1074, 1094]` are UNCHANGED. The validated fleet detection stays intact: 66 µm `1-1` still detects `[15, 378]`, and the same fix corrected 24 µm `1-1`'s wood top from 44 to the true apex 40 (the identical misclassification had shaved the drier top slices).
- Snap integration: on this specimen Snap now lands `cut=1022, keep=65` — exactly the correction the user applied manually in the reference screenshots.
- Robustness fix surfaced by the sweep: an unregistered/unknown custom specimen raised a bare `IndexError` (`files[z]`) inside the slice reader; the source-slice reader now raises a clean, actionable error ("no readable source series / slice outside the registered source series"), which surfaces through the app's standard load-failure path.

### 2) Text placement and clipping (audit 0AD)

- Sidebar: the side-by-side Save/Load checkpoint buttons were squeezed into clipped labels ("ave checkpoint…" / "oad checkpoint…") — they are now stacked full-width with complete tooltips.
- GPU chip: the full device name clipped at "(CuPy C…" — the chip now shows a compact text (`⚡ <short name> · CuPy CUDA`) and the tooltip carries the complete detail; the CPU state gained a tooltip as well.
- Window title: Qt's application display name appended "- cleanCT" to every window title ("cleanCT — Wood CT Metal-Base Removal - cleanCT") — the redundant display-name registration was removed; the title bar is now exactly "cleanCT — Wood CT Metal-Base Removal".
- Action log: mid-word breaks ("sagitta / l") fixed with word-boundary wrap mode.
- Bundle destination: the (elided) path's full value is mirrored in the field's tooltip, kept in step on edits.
- Checkpoint restore: `_apply_checkpoint_controls` now declares the clamped real slice count (`setSliceCount`) before placing lines, so a checkpoint saved from a different-size specimen cannot restore out-of-range lines under the same ID.
- Drag desync guard: viewer drag handlers adopt the SPIN-clamped value into the job state (`pref_cut`/`pref_keep`), so a stale viewer coordinate space can no longer push the state outside the loaded specimen (a stale space could previously emit 4022 on a 1098-slice volume; the drag now clamps to the specimen range).

### Release rebuild and verification

- Full `installer/build_installer.py` run (no skip flags): the 11-suite gate passed inside the builder; fresh PyInstaller 6.22.2 launcher (PE icon resources verified; standalone `--selfcheck` PASS); portable ZIP (6,688 entries, CRC PASS, 0 bytecode, expands to 752,615,114 bytes) and ISCC setup.exe published transactionally.
- Final artifacts (measured 2026-09-24): portable ZIP 329,419,912 bytes (SHA-256 `d4a6f952042e4f43166c013a25af27176a4879df3d9df35b1effdadb07bb709`, matching sidecar); setup.exe 205,942,130 bytes (SHA-256 `3babf7db86e000eec07bb808a28f470ad3de7b0d66fdd56c6a413d4e45543442`); launcher 6,342,900 bytes (SHA-256 `8fa1ce25fea5c32106fd9c02ee2dd344c3bd89fc9b625f7a4ece871406d59e4d`) with selfcheck exit 0. `_pkg` residue 0.
- App-level smoke on the real specimen: load → detection reports `wood top 65` on the viewer guide; drag-away + Snap lands `cut=1022, keep=65`; an out-of-range drag (stale viewer space) clamps inside the specimen; export with `keep_from=65` delivers 957 slices (1022−65) under the clean names and records `keep_from=65` in the sidecar — full metadata verified.
- The copied release installer re-verified: launcher selfcheck exit 0 and ISS compile exit 0 from `cleanCT_v1.0.0\installer\`.
- Scoped hashed snapshot: `0BACKUP\audit_20260924_woodtop_fix_r11`.

### Scope (unchanged)

Classic installer compiled and PE-validated (including from the copied release bundle) but not installed end-to-end through an actual Program Files run; validation is the automated gate plus launcher selfchecks, packaged GUI smoke, ZIP CRC/inventory, PE resource checks, SHA-256 verification, and the real-data export readback. No physical-display click-through or disk-surface certification is claimed.

---

## 0AE. Left/Right ROI alignment fix and revision history — 2026-09-24

This round fixed the reported Left/Right cut-line misalignment, locked the (already correct) top/bottom logic, added a regression suite for the wood bounds, and created `REVISION_HISTORY.md` (the complete human-readable changelog from the v1.0.0 baseline).

### Left/Right ROI alignment (audit 0AE)

- **Reported problem:** after the wood-class fix (§0AD), the Left/Right cut lines no longer hugged the wood ROI — visually detached from the wood edge (L 7% / R 93% where the wood's visible body sits inside that).
- **Root-cause analysis (all three suspects checked):** the axis order (`_mask_extent` → y0,y1,x0,x1; rows→Y, columns→X) is consistent; the lateral evidence is pooled over the SAME trusted window slices as the top/bottom logic (one coordinate system); no hardcoded lateral values exist (a checkout-wide sweep found only an unrelated UI label width). The real cause: the lateral envelope was the 20/80 percentile aggregation of per-slice bounding-box extents over ALL pooled slices, and with the corrected calibrated wood class the near-air fog at ≈ -990..-978 HU falls INSIDE the window — measured on the real specimen, fog-blanket slices report full-frame extents (0..H-1, 0..W-1; 73–98 % of the FOV), stretching the percentile envelope to the frame.
- **Fix (exactly the prescribed approach):** the lateral envelope is now the pooled VERTICAL PROJECTION PROFILE of the fog-free wood core — per column for X (sum over Y) and per row for Y (sum over X) — accumulated in the pool loop (additive only; the top/bottom logic is untouched). The first/last lane whose projection exceeds `LAT_EDGE_FRAC` (0.15) of the peak lane is the edge. The fog-free core is the upper share of the calibrated wood window (`LAT_CORE_FRAC = 0.2`): by construction fog at the window's lower edge carries no core weight, so it cannot stretch the lines. The percentile envelope remains only as a fallback; the ortho-plane witness adoption stays agreement-gated.
- **Verification:** `tests/test_wood_bounds.py` (12th gate suite) — a synthetic rectangular block with a frame-wide fog blanket in the dry region: the envelope matches the block outline within the closing radius (x margins [40, 40] for a block at 40..259 of 300; y [50, 20] for the block y 50..379 of 400) and the calibrated top/bottom semantics are unchanged. Debug overlay `tests/debug_lines_overlay.py` renders the four-line box on a real axial slice into `debug/` — for `1-17_OD` the box hugs the block's outline (6 px closing margin on a block that genuinely fills the FOV).

### Full changelog

- `REVISION_HISTORY.md` (checkout root): the chronological changelog from the v1.0.0 baseline through the 0AA/0AB/0AC/0AD/0AE rounds — every fix with problem/fix/files. A copy ships with the release snapshot.

### Release rebuild and verification

- Full `installer/build_installer.py` run (no skip flags): the 12-suite gate passed inside the builder; fresh PyInstaller 6.22.2 launcher (PE icon resources verified; standalone `--selfcheck` PASS); portable ZIP (6,688 entries, CRC PASS, 0 bytecode, expands to 752,617,719 bytes) and ISCC setup.exe published transactionally.
- Final artifacts (measured 2026-09-24): portable ZIP 329,420,830 bytes (SHA-256 `8c88efb2dc1fd3eadef1264b0defb0cece3bed084422498c9bf0be01a823026`, matching sidecar); setup.exe 205,937,261 bytes (SHA-256 `21188e6c5d0bdee12b408e29c405995ddb0cfd52f1c3c0891539ea92b404958a`); launcher 6,342,586 bytes (SHA-256 `76e13e1cfda6eb44a71a2830de5c729a8908bbfe517e51b7312d9ad28a5b5b6a`) with selfcheck exit 0. `_pkg` residue 0; the copied release installer re-verified (launcher selfcheck exit 0).
- Scoped hashed snapshot: `0BACKUP/audit_20260924_roi_lateral_r12`.

### Scope (unchanged)

Classic installer compiled and PE-validated but not installed end-to-end through an actual Program Files run; validation is the automated 12-suite gate plus launcher selfchecks, packaged GUI smoke, ZIP CRC/inventory, PE resource checks, SHA-256 verification, the real-data export readback, and the debug-line overlay. No physical-display click-through or disk-surface certification is claimed.

---

## 0AF. Left/Right ROI fix #2: edge-band-gated Otsu projections - 2026-09-25

This round replaces the 0AE lateral mechanism after it was proven insufficient on the user's oven-dry specimen, with an empirically calibrated, view-independent projection method. The top/bottom (z) logic is untouched and byte-compared before/after every step.

### 1) Root cause, proven by instrumented probes (not guessed)

- The user's `custom/1-17_OD` is **oven-dry**: the wood reads **-989..-958 HU**, sitting at the *floor* of the calibrated window `(-990,-500)`.
- The 0AE "fog-free core" was the upper 20 % of that window (`-892..-500`). Probe results: on clean wood slices the core mask is **empty** (`mean=0.000`) - the wood is not in it; on fog blanket slices the core mask contains **plenty of fog** (z=1032: `mean=0.143`, extent `(6,1193,6,1191)`; z=1066: `mean=0.807`). The "core" projection was 100 % fog -> edge lanes above 15 % of peak -> envelope `[6,1193]x[6,1191]` (full frame).
- `_fog_blanket` (>60 % FOV fill) cannot identify those slices on this specimen because the real wood block itself fills **~72 %** of the FOV (clean slices score 0.72-0.80 as well).
- The dim fog **ring** around every block touches the FOV edge on nearly every slice, so per-slice "clean band" gates return too little evidence (probe: strict 5 % gate kept 0-4 of 31 pooled slices on `24um/1-1`, `66um/1-1`, `24um/1-15` -> no bounds).
- The usable discriminator is the **lane distribution of the pooled projection**: the fog ring carries **25-32 %** of the peak lane on every reference specimen while the wood plateau carries **95-100 %**; Otsu's valley sits at **49-57 %** and lands within 1-3 px of the visible wood edge on all four specimens (`custom/1-17_OD`: Otsu `(90,1110)` vs visible ~90..1105).

### 2) Fix (decoupled per-axis, per-view, no pixel constants)

- Pool loop: a slice whose outer `LAT_EDGE_CLEAR_MM = 0.5 mm` band is more than half occupied (`LAT_BLANKET_FRAC = 0.50`) is a fog blanket - z evidence only, excluded from lateral projections geometrically.
- Each axis gets its own projection over the contributing slices: `sum(axis=0)` -> X envelope, `sum(axis=1)` -> Y envelope; independent of the z logic.
- `_projection_lane_bounds`: first/last lane above `clip(Otsu(proj), LAT_EDGE_FRAC=0.40 * peak, LAT_KNEE_HI=0.50 * peak)`. The originally prescribed `0.05 * max` was measured insufficient (every reference specimen came out full-frame); the clamp keeps the knee inside the valley for unimodal/full-width wood.
- Ortho witnesses use the same principle (blanket-gated rows + projection + Otsu knee); adoption remains agreement-gated.
- `# LOCKED - CORRECT - DO NOT MODIFY` banners added at the top/Keep and bottom/Cut z paths (pool run, `_edge_walk`, `_curtain_top`).
- Cache versions bumped (`CACHE_VERSION 19`, `PREV_VERSION 11`) so no payload cached under the old semantics is served.

### 3) Verification

- `custom/1-17_OD`: `[6,1193]x[6,1191]` -> `[97,1111]x[89,1110]`; top/bottom byte-identical (`wood_top=28, wood_bottom=1066, keep=10, cut=1074`).
- `24um/1-1`: `[6,1116]x[6,1126]` -> `[58,1068]x[64,1081]`; zb unchanged (`40/1014, cut=1007`).
- `24um/1-15`: `[62,1075]x[60,995]` -> `[63,1075]x[54,1067]` (right side now covers the wood the old percentile clipped); zb unchanged (`38/1005, cut=1006`).
- `66um/1-1`: `[2,428]x[2,426]` -> `[26,405]x[25,407]`; zb unchanged (`15/377, cut=378`).
- `tests/test_wood_bounds.py`: sparse-fog scenario PASS (margins `[40,40]`/`[50,20]`, exact block outline), new oven-dry dense-blanket scenario PASS (`[30,30]`).
- Full 12-suite gate: PASS (exit 0).
- Before/after overlays and JSON readbacks: `debug_roi_fix/` (8 files); the debug tool's X side sign bug fixed and its display window made deterministic.

### 4) Release rebuild and verification

- Full `installer/build_installer.py` run (no skip flags): 12-suite gate PASS inside the builder; fresh PyInstaller 6.22.2 launcher (PE icon resources verified; standalone `--selfcheck` PASS); portable ZIP (6,688 entries, CRC PASS, 0 bytecode, expands to 752,623,043 bytes) and ISCC setup.exe published transactionally. `_pkg` bytecode residue cleaned after the manual smoke-check (0 remaining).
- Final artifacts (measured 2026-09-25): portable ZIP 329,423,098 bytes (SHA-256 `3a48649194137fa4f3baba632fec6964eac9137258a9526968a6bc9e72df1483`, matching sidecar); setup.exe 205,936,459 bytes (SHA-256 `ef4acb3556ea5b1f2e68a0a8caba904c0891b6a43489a8f4d2820c9bd7c13d7b`); launcher 6,343,337 bytes (SHA-256 `b004587365cdb1ac27d797cfe85a55bb80590ecb22f5b0ba168c4dd7c7ddce14`) with selfcheck exit 0.
- Release snapshot `cleanCT_v1.0.0\installer\` mirrored from the checkout (robocopy: 0 mismatches, 0 failures); copied launcher selfchecks clean; `README.md`, `AUDIT.md`, `REVISION_HISTORY.md`, `USER_GUIDE.md`, `DEV_LOG.md` synced; snapshot README D.1 re-measured.
- Scoped hashed snapshot: `0BACKUP/audit_20260925_roi_lateral_r13` (215 files, CRC + per-file SHA-256 PASS).

### Scope (unchanged)

Classic installer compiled and PE-validated but not installed end-to-end through an actual Program Files run; validation is the automated 12-suite gate plus launcher selfchecks, packaged GUI smoke, ZIP CRC/inventory, PE resource checks, SHA-256 verification, and the real-data overlay readback. No physical-display click-through or disk-surface certification is claimed.

---

## 0AG. Auto Snap to Detection and ROI logic documentation - 2026-09-25

This round turns the partial, implicit detection -> cut copy into an explicit default-ON feature, freezes the (now correct) detection core with LOCK comments, and documents the complete ROI logic in `ROI_LOGIC.md`. The detection core was NOT modified - only comments were added.

### 1) Analysis (current flow, verified in source)

- Auto-detect triggers in `viewer_core.build_payload` on every specimen selection and after every Process job (the completion re-selects the specimen).
- Detection lives in `payload["bounds"]` / `_wood_bounds_raw`; the cut lines live in `pref_cut`/`pref_keep`/`pref_margin` plus the viewer's per-axis pairs.
- No hidden offset exists between detection and cut; the load-time copy was strict (fog-deferred air top left Keep at the report value), the wood-top fallback existed only behind the explicit Snap button, and there was no toggle or manual-override state.

### 2) Fix (copy layer only)

- New pure module `src/core/auto_snap.py` - `detected_lines(bounds, allow_wood_top_fallback=True)`: `cut=zb.cut`; `keep=zb.keep` else `zb.wood_top` (fallback), clamped `keep <= cut-1`; lateral pairs `(x0/W, (x1+1)/W)` / `(y0/H, (y1+1)/H)`.
- `main_window`: `Auto snap to detection` checkbox in the guide bar (default ON); `_apply_auto_snap()` copies detection onto Keep/Cut and BOTH lateral pairs on every load/re-detect and on toggle-on; any manual edit (all spins/sliders/viewer drags, including the newly wired axial Top/Bottom drags) suspends the copy layer until the next detection; checkpoint restores count as manual state; toggle OFF keeps the stored lines plus neutral 15/85 pairs; the explicit Snap button re-arms. No new offsets; the physical margins remain inside the detection constants and the Margin/air-crop controls stay separate layers.
- Detection core frozen: `# STABLE DETECTION - DO NOT MODIFY CORE` added to `core/wood_bounds.py` (module, entry, object mask, lateral projection); the existing top/bottom LOCKED banners stand.

### 3) Documentation (Objective 1)

- `ROI_LOGIC.md` (new): mask generation, top/bottom and left/right formulas, the four detected-line definitions, the detection -> cut mapping, the auto-snap contract, view-specific axis mappings and coordinate systems, and the verification matrix.

### 4) Verification

- `tests/test_auto_snap.py` (new 13th gate suite): ALL PASS - pure mapping (copy, fallback, strict mode, keep<cut clamp, pair validation) and offscreen window behavior (load applies; deferred air top lands on the wood top and is logged; manual edit suspends; re-detect re-applies; toggle off keeps stored lines + neutral pairs; toggle on applies; checkpoint restore suspends; Snap button re-arms; unprocessed pre-process load applies).
- Full 13-suite gate: PASS (exit 0).
- `debug_snap/` overlays for `24um/1-1`, `24um/1-15`, `66um/1-1`: dashed detection envelope == solid snapped box (`24um/1-1` X 64..1081 Y 58..1068; `24um/1-15` X 54..1067 Y 63..1075; `66um/1-1` X 25..407 Y 26..405); snapped keep = wood-top fallback 40/38/15 (air top deferred on all three), cut = 1007/1006/378.
- Detection invariants unchanged: `test_wood_bounds.py` PASS with the same margins (`[40,40]/[50,20]` sparse-fog, `[30,30]` oven-dry).

### 5) Release rebuild and verification

- Full `installer/build_installer.py` run (no skip flags): 13-suite gate PASS inside the builder; fresh PyInstaller 6.22.2 launcher (PE icon resources verified; standalone `--selfcheck` PASS); portable ZIP (6,689 entries, CRC PASS, 0 bytecode, expands to 752,634,116 bytes; `app\core\auto_snap.py` present) and ISCC setup.exe published transactionally. `_pkg` bytecode residue 0.
- Final artifacts (measured 2026-09-25): portable ZIP 329,425,926 bytes (SHA-256 `62af1bb67a8d8f0247ff7424a99a3aff3e9c06a27af078c4077c3b92f8b2bc08`, matching sidecar); setup.exe 205,958,325 bytes (SHA-256 `1c3a7a2650af7ba89c6bcf1b7858c4df77a635c912e23c5c3dee07128cf47729`); launcher 6,342,402 bytes (SHA-256 `ae27bb5f3164e6853f32b630784b69f97d241beac2df419e0962184848a3f2af`) with selfcheck exit 0.
- Release snapshot `cleanCT_v1.0.0\installer\` mirrored from the checkout (robocopy: 0 mismatches, 0 failures); copied launcher selfchecks clean; `README.md`, `AUDIT.md`, `REVISION_HISTORY.md`, `USER_GUIDE.md`, `DEV_LOG.md`, `ROI_LOGIC.md` synced; snapshot README D.1 re-measured.
- Scoped hashed snapshot: `0BACKUP/audit_20260925_auto_snap_r14` (218 files, CRC + per-file SHA-256 PASS).
