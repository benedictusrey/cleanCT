# cleanCT — Native Desktop Application
### Non-Destructive Wood CT Metal-Base Removal & Inspection Suite

**cleanCT** is a native Windows desktop workstation application (built on PySide6 and C++ Qt) for high-performance tomographic inspection and non-destructive metal mounting platform removal from high-resolution micro-CT wood scans.

**New to cleanCT?** Start with `USER_GUIDE.md` for clear steps to open a scan, review the detected boundaries, process it, and export a bundle. The portable package includes this guide beside `cleanCT.exe`.

---

## Folder Layout (structured checkout)

```
cleanCT\
  main.py               Entry point (run this from source)
  README.md             This developer overview
  USER_GUIDE.md         End-user walkthrough (ships in every package)
  AUDIT.md              Complete audit & release record
  src\                  Application sources (packaged into the payload)
    main_window.py      Complete UI, state machine, workers, checkpoint & history logic
    theme.py            Dark graphite QSS theme
    icon_utils.py       Window/taskbar icon loading + native Win32 icon injection
    core\               paths, viewer_core, custom_series, bundle_export,
                        checkpoint_file, wood_bounds
    widgets\            viewer_2d, viewer_3d, kpi_banner, specimen_panel
    dialogs\            load_dialog, about_dialog
  assets\
    app.ico, app_icon_256.png      Window icon assets (staged into every package)
    icons\                          Canonical 36-file production icon pack
    design\                         Banner/design source archive (not packaged)
  data\                 Per-user state in development runs (never versioned)
    settings.json      Remembered export destination & format
    logs\              Runtime logs
    export\            Default export bundles
    custom\            Loaded-specimen registry (+ DICOM junctions)
    cache\             Generated viewer caches
  installer\            build_installer.py, cleanct.iss, launcher_main.py,
                        setup_env.ps1, README_INSTALLER.txt, _pkg\, out\
  tests\                Regression gate: run_cleanct_regressions.ps1 + suites,
                        pkg_gui_smoke.py, capture_screens.py + screenshots\,
                        create_audit_backup.py, venv_notorch\ (test interpreter)
  dist\                 Reference standalone build (dist\cleanCT-app)
  version\             Release folders written by installer\build_installer.py
                        (version\cleanCT_v1.0.0\)
  0BACKUP\              Hashed round snapshots of the whole system
```

The sibling engine lives at `H:\Treated Kyodai samples\metal_remover` (copied into every package). Per-user state under `%LOCALAPPDATA%\cleanCT` is used by installed builds; the development checkout uses `data\`.

---

## 1. Key Architectural Upgrades

- **Stacked 2D Merged Layout:** On the Results tab, the Axial view (Original | Stripped side by side with yellow wood ROI envelope and red metal tint) is stacked directly above the Longitudinal cut boundary view, aligning horizontal cross-sections and axial slice scrubbers.
- **Ultra-Fast 3D Vectorized Projection (>200 FPS):** Single-pass NumPy array projection buffer with 2×2 particle splatting renders dense 45,000+ point clouds in 3.7 ms for fluid 360° mouse orbiting and continuous turntable spinning.
- **Specimen Panel (left sidebar):** live search/filter, count chip, two-line rows with metadata (format · slices · dimensions · voxel · size on disk), right-click context menu (Open / Rename / Duplicate / Locate in Explorer / Remove), compact action row, confirmation dialogs, and a busy spinner during loads. Loaded specimens can be renamed, duplicated (same source, new ID — no data copied), and removed (registry + link only; sources, processed results, and exports are always kept). Built-in dataset specimens can be hidden for the session.
- **Enhanced Visual Luminosity & Clarity:** perceptual gamma lift (`gamma = 0.85`) across 2D/3D colormaps (`Spectral`, `Thermal`, `Grayscale`, `Viridis`, `Plasma`).
- **Asynchronous by design:** specimen loads, GPU probes, and preview renders run on workers — the window never blocks; latest-only scheduling discards stale previews.
- **Checkpoint sessions:** Save/Open checkpoint (`.ctcheckpoint.json`) with reconnect-or-snapshot semantics; preview history persists until exit.
- **Torch-free GPU path:** CuPy (CUDA 12.x) with validated CPU fallback; the engine preloads the pinned NVRTC pair.

---

## 2. Running cleanCT

```powershell
# GUI from source (checkout root)
C:\ProgramData\anaconda3\python.exe main.py

# Health check from source (RESULT: PASS)
$env:QT_QPA_PLATFORM = "offscreen"; $env:PYTHONUTF8 = "1"
& "$PWD\tests\venv_notorch\Scripts\python.exe" "$PWD\main.py" --selfcheck

# Packaged launcher health check (exit 0 = PASS)
& "$PWD\installer\_pkg\cleanCT.exe" --selfcheck
```

Production launcher: `installer\_pkg\cleanCT.exe` (PyInstaller one-file, windowless; spawns `runtime\python.exe -X utf8 app\main.py` next to itself). Release artifacts: `version\cleanCT_v1.0.0\` holds the portable ZIP and its `.sha256`, `cleanCT-1.0.0-setup.exe`, `README_INSTALLER.txt`, `USER_GUIDE.md`, `THIRD_PARTY_NOTICES.md`, and `RELEASE_NOTES.md`. `installer\out` keeps the same build outputs.

---

## 3. Quality Gates

```powershell
# 1) Regression gate: 37 focused suites — must PASS before any release
powershell -NoProfile -ExecutionPolicy Bypass -File "$PWD\tests\run_cleanct_regressions.ps1"

# 2) Full release rebuild: gate, package, fresh icon-embedded launcher,
#    launcher smoke, portable ZIP, ISCC setup.exe (transactional publication)
& "C:\ProgramData\anaconda3\python.exe" "$PWD\installer\build_installer.py"

# 3) Classic installer only
ISCC.exe "$PWD\installer\cleanct.iss"

# 4) Packaged GUI smoke (real MainWindow from _pkg, offscreen)
& "$PWD\tests\venv_notorch\Scripts\python.exe" "$PWD\tests\pkg_gui_smoke.py"

# 5) Screenshot evidence: landing / loaded / cutting / history
& "$PWD\tests\venv_notorch\Scripts\python.exe" "$PWD\tests\capture_screens.py"

# 6) Hashed audit snapshot under 0BACKUP\
& "$PWD\tests\venv_notorch\Scripts\python.exe" "$PWD\tests\create_audit_backup.py"
```

Suites: `test_checkpoint_file.py`, `test_viewer_regressions.py`, `test_render_async.py`, `test_specimen_panel.py`, `test_wood_bounds.py`, `test_auto_snap.py`, `test_unproc_and_frames.py`, `test_export_formats.py`, `test_export_stream.py`, `test_nifti_roundtrip.py`, `test_state_files.py`, `test_pipeline_synthetic.py`, `test_volume_inputs.py`, `test_launcher_paths.py`, `test_installer_icons.py`.

---

## 4. Notes

- Source scans are never modified; registration references sources in place (DICOM junctions under `data\custom\data\<specimen>\XY` in development, `%LOCALAPPDATA%\cleanCT\custom\...` when installed).
- `data\` is user-owned and ignored by version control; everything under `installer\_pkg`, `installer\out`, and `tests\venv_notorch` is regenerable.
- The complete release history (per-release hashes, scope limits) is `AUDIT.md`.
