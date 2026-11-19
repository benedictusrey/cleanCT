<p align="center">
  <img src="assets/icons/icon_1024x1024.png" width="112" alt="cleanCT icon">
</p>

<h1 align="center">cleanCT</h1>

<p align="center"><b>Non-destructive metal-base removal and inspection of micro-CT wood scans</b></p>

<p align="center">
  <a href="docs/RELEASE_NOTES.md"><img src="https://img.shields.io/badge/version-1.0.0-2f81f7?style=flat-square" alt="Version 1.0.0"></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%C2%B7%20Linux%20%C2%B7%20macOS-0078d4?style=flat-square" alt="Platform: Windows, Linux, macOS">
  <img src="https://img.shields.io/badge/python-3.12-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/Qt-PySide6%20%2F%20Qt%206-41cd52?style=flat-square&logo=qt&logoColor=white" alt="PySide6 / Qt 6">
  <img src="https://img.shields.io/badge/GPU-CUDA%2012%20%28optional%29-76b900?style=flat-square&logo=nvidia&logoColor=white" alt="CUDA 12, optional">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-ff6b35?style=flat-square" alt="License: PolyForm Noncommercial 1.0.0"></a>
</p>

<p align="center">
  <img src="assets/banner/Main%20Hero%20Banner_cleanCT%20Flagship%20%283D%20Before%20%26%20After%29.jpeg" alt="cleanCT flagship view: 3D before and after metal-base removal">
</p>

---

## Abstract

cleanCT is a native desktop application for Windows, Linux and macOS (PySide6 / Qt 6) for micro-CT scans of wood specimens mounted on a metal base. It locates the metal base and the wood, shows four guide lines for review, removes the base with a metal-removal engine, and exports the inner wood region as DICOM and NIfTI with a verified bundle. Source scans are never modified.

## Features

- **Scan input.** DICOM series, multipage TIFF stacks and 3-D NIfTI (`.nii`, `.nii.gz`). Scans are registered in place; DICOM folders are linked by junction.
- **Detection.** The metal top (Cut), the wood top (Keep) and the lateral box (L, R) are detected from the scan and placed on editable lines (Auto snap).
- **Review.** The Boundaries tab: drag or type the lines, scrub the sagittal, coronal and axial planes, choose colour maps and density windows. Apply lines reprocesses the scan.
- **Results.** Before and After axial and longitudinal views, a 3-D point cloud, and a marker when the processed run differs from the lines on screen.
- **Inner-ROI export.** The delivered region is the kept slices between Keep and Cut, clipped to the L/R box. The DICOM and NIfTI outputs hold the same voxels.
- **Verified bundles.** A bundle is staged, checked (UIDs, pixel values, geometry) and only then promoted. A failed check writes nothing.
- **Checkpoints.** A preview with its lines and settings can be saved as `.ctcheckpoint.json` and reopened. Applied previews are kept as a history for the session.
- **Compute.** NVIDIA GPU through CuPy (CUDA 12) on Windows and Linux when available; the validated CPU path otherwise (always on macOS), with the same algorithm.

## Gallery

| Overview and 3-D point cloud | Interactive cut boundaries |
|---|---|
| ![Overview and 3-D point cloud](assets/banner/Hero%20Banner%201_Overview%20%26%203D%20Point%20Cloud.jpeg) | ![Interactive cut boundaries](assets/banner/Hero%20Banner%202_Interactive%20Cut%20Boundaries.jpeg) |
| Results view: axial and longitudinal panels with the delivered region, and the 3-D point cloud (amber wood, silver metal). | Boundaries tab: Keep (wood top), Cut (metal top) and the L/R lateral box, with 2-line and 4-line controls. |
| **Wood micro-CT inspection** | **Portable workstation and export** |
| ![Wood micro-CT inspection](assets/banner/Hero%20Banner%203_Wood%20Micro-CT%20Inspection.jpeg) | ![Portable workstation and export](assets/banner/Hero%20Banner%204_Portable%20Windows%20Workstation%20%26%20Export%20Pipeline.jpeg) |
| Metal-first anchor detection on a wood scan; the wood region is preserved and the platform artefact removed. | Settings, export formats (DICOM, NIfTI), checkpoints and the activity log. Runs from a portable folder. |

## Installation

| Platform | File | Notes |
|---|---|---|
| Windows, installer | `cleanCT-1.0.0-setup.exe` | Per-machine setup; asks for administrator approval. |
| Windows, portable | `cleanCT-1.0.0-portable.zip` | Extract the whole folder and run `cleanCT.exe`. No administrator rights needed. |
| Linux x86_64, portable | `cleanCT-1.0.0-linux-x86_64.tar.gz` | Extract and run `./cleanCT`. `./install.sh` adds a per-user install, a `cleanct` command and a menu entry. |
| macOS, Apple silicon | `cleanCT-1.0.0-macos-arm64.dmg` | Open the DMG and drag cleanCT to Applications. |
| macOS, Intel | `cleanCT-1.0.0-macos-x86_64.dmg` | The same, for Intel Macs. |

Every file is attached to the GitHub Release with a SHA-256 sidecar; `SHA256SUMS` lists all of them. The macOS app is not notarized: on first launch, Control-click it and choose Open (macOS 15 and later: System Settings › Privacy & Security › Open Anyway). If macOS says the app is damaged, run `xattr -dr com.apple.quarantine /Applications/cleanCT.app` in Terminal.

**Requirements:** Windows 10 or 11 (64-bit); Linux x86_64 with glibc 2.28 or newer, which PySide6 requires (tested in clean Ubuntu 22.04 and Debian 12 containers with `libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libdbus-1-3 libfontconfig1 libglib2.0-0` installed, as on a desktop system); macOS 12 or newer. An NVIDIA GPU with a CUDA 12 driver is optional (Windows and Linux). Keep free disk space for results and exports; a `.nii.gz` source is expanded to temporary storage at about its uncompressed size.

## Quick start

1. **Load scan…** (Ctrl+O): choose a DICOM folder, a TIFF file or a NIfTI file, enter a specimen ID and select *Load & Register*.
2. **Boundaries:** check the Keep, Cut and L/R lines against the scan.
3. **Process** (Ctrl+R), or **Apply lines** after editing a line, to run the metal-removal pipeline.
4. **Results:** review the delivered region.
5. **Export** (Ctrl+E), or **Process and export**, to write the bundle.

## Output bundle

| File | Content |
|---|---|
| `<ID>_dcm/` | Kept DICOM slices under their original file names, with source tags and delivery metadata. |
| `<ID>.nii` | Kept slices as one NIfTI volume, cropped to the same L/R box as the DICOM. |
| `<ID>.json` | Sidecar: cut and keep slices, L/R box, geometry and file mapping. |
| `<ID>_extraction_info.txt` | Plain-text extraction report. |

TIFF and NIfTI sources are exported as NIfTI only.

## Build from source

The processing engine is the `engine/` folder of this repository. Outputs of a source run go to the engine's default output folder unless `CLEANCT_OUTPUT_ROOT` is set.

```powershell
# environment (pinned packages)
powershell -ExecutionPolicy Bypass -File installer\setup_env.ps1 <path to python.exe>

# run from source
python main.py

# health check (exit 0 = PASS)
python main.py --selfcheck

# regression gate (37 suites)
powershell -NoProfile -ExecutionPolicy Bypass -File tests\run_cleanct_regressions.ps1

# release package (gate, package, launcher, portable ZIP, setup)
python installer\build_installer.py --iscc "<path to ISCC.exe>"
```

```sh
# Linux and macOS packages: runtime, gate, self-check, tarball or DMG
python3 installer/build_posix.py linux-x86_64
python3 installer/build_posix.py macos-arm64
```

The Windows release build needs PyInstaller 6.22.2 and Inno Setup 6. The Linux and macOS builds need PowerShell 7 (`pwsh`) for the regression gate, plus `hdiutil`, `iconutil` and `codesign` on macOS.

## Repository structure

| Path | Contents |
|---|---|
| `main.py` | Entry point. |
| `src/` | Application: `core/` (logic), `widgets/`, `dialogs/`, `main_window.py`, `theme.py`. |
| `assets/` | `banner/` (gallery), `screenshots/` (documentation), `icons/` (application icon pack), `design/` (source archive). |
| `engine/` | Processing engine: the six modules the application imports. |
| `installer/` | Windows build (`build_installer.py`, launcher source, Inno Setup script); Linux and macOS build (`build_posix.py`, `posix/install.sh`); pinned requirements. |
| `tests/` | Regression suites and test tools. |
| `docs/` | User guide, implementation details, release notes and change records. |
| `version/` | Release folders (not versioned). |
| `PRODUCT.md`, `DESIGN.md` | Design context. |

## Documentation

| Document | Content |
|---|---|
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | Step-by-step guide. Ships with the application. |
| [`docs/cleanCT_details.md`](docs/cleanCT_details.md) | Implementation details of v1.0.0 (also as `.docx`). |
| [`docs/ROI_LOGIC.md`](docs/ROI_LOGIC.md) | Detection formulas and coordinate systems (earlier design; see the implementation details). |
| [`docs/RELEASE_NOTES.md`](docs/RELEASE_NOTES.md) | Release notes for v1.0.0. |
| [`docs/REVISION_HISTORY.md`](docs/REVISION_HISTORY.md), [`docs/DEV_LOG.md`](docs/DEV_LOG.md), [`docs/AUDIT.md`](docs/AUDIT.md) | Change and audit records. |

## Known limitations

- The processed axial view steps through 16 stored frames, not every slice.
- A running pipeline cannot be stopped.
- The longitudinal Results view reads the source folders; a moved source shows an error.
- Auto-crop trims the processing output only; bundles are cut to the lines on screen.
- Linux and macOS are checked in CI and headless only: their GUIs and the Linux CUDA path have not run on physical machines.
- The macOS app is not notarized (see Installation).
- The Intel macOS build is tested under Rosetta 2 on Apple silicon runners.

## How to cite

If cleanCT contributes to your research, please cite the software (version 1.0.0). The associated article is in preparation; cite it when it is published. GitHub's *Cite this repository* button reads [`CITATION.cff`](CITATION.cff).

APA (7th edition):

> Hartanto, B. R. (2026). *cleanCT* (Version 1.0.0) [Computer software]. https://github.com/benedictusrey/cleanCT

BibTeX:

```bibtex
@software{hartanto2026cleanct,
  author  = {Hartanto, Benedictus Reynaldo},
  title   = {{cleanCT}: Non-destructive metal-base removal and inspection of micro-CT wood scans},
  version = {1.0.0},
  year    = {2026},
  month   = nov,
  url     = {https://github.com/benedictusrey/cleanCT},
  license = {PolyForm Noncommercial 1.0.0}
}
```

## License

Copyright 2026 Benedictus Reynaldo Hartanto. Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). Noncommercial use, including research, teaching and personal study, is permitted. Commercial use is not.
