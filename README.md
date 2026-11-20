<p align="center">
  <img src="assets/icons/icon_1024x1024.png" width="112" alt="cleanCT icon">
</p>

<h1 align="center">cleanCT</h1>

<p align="center"><b>Non-destructive metal-base removal and inspection of micro-CT wood scans</b></p>

<p align="center">
  <a href="docs/RELEASE_NOTES.md"><img src="https://img.shields.io/badge/version-1.0.0-2f81f7?style=flat-square" alt="Version 1.0.0"></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%C2%B7%20Linux-0078d4?style=flat-square" alt="Platform: Windows, Linux">
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

cleanCT is a native desktop application for Windows and Linux (PySide6 / Qt 6) for micro-CT scans of wood specimens mounted on a metal base. It locates the metal base and the wood, shows four guide lines for review, removes the base with a metal-removal engine, and exports the inner wood region as DICOM and NIfTI with a verified bundle. Source scans are never modified.

## Features

- **Scan input.** DICOM series, multipage TIFF stacks and 3-D NIfTI (`.nii`, `.nii.gz`). Scans are registered in place; DICOM folders are linked by junction.
- **Detection.** The metal top (Cut), the wood top (Keep) and the lateral box (L, R) are detected from the scan and placed on editable lines (Auto snap).
- **Review.** The Boundaries tab: drag or type the lines, scrub the sagittal, coronal and axial planes, choose colour maps and density windows. Apply lines reprocesses the scan.
- **Results.** Before and After axial and longitudinal views, a 3-D point cloud, and a marker when the processed run differs from the lines on screen.
- **Inner-ROI export.** The delivered region is the kept slices between Keep and Cut, clipped to the L/R box. The DICOM and NIfTI outputs hold the same voxels.
- **Verified bundles.** A bundle is staged, checked (UIDs, pixel values, geometry) and only then promoted. A failed check writes nothing.
- **Checkpoints.** A preview with its lines and settings can be saved as `.ctcheckpoint.json` and reopened. Applied previews are kept as a history for the session.
- **Compute.** NVIDIA GPU through CuPy (CUDA 12) on Windows and Linux when available; the validated CPU path otherwise, with the same algorithm.

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
| Python source, any Windows or Linux PC | `cleanCT-1.0.0-python-source.zip` | Extract, run `python -m pip install -r installer/requirements-core.txt` in the folder, then `python main.py`. Needs Python 3.12. |

Every file is attached to the GitHub Release with a SHA-256 sidecar; `SHA256SUMS` lists all of them. macOS is not part of this release.

**Requirements:** Windows 10 or 11 (64-bit); Linux x86_64 with glibc 2.28 or newer, which PySide6 requires (tested in clean Ubuntu 22.04 and Debian 12 containers with `libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libdbus-1-3 libfontconfig1 libglib2.0-0` installed, as on a desktop system). An NVIDIA GPU with a CUDA 12 driver is optional (Windows and Linux). Keep free disk space for results and exports; a `.nii.gz` source is expanded to temporary storage at about its uncompressed size.

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

## GPU or CPU: measured comparison

cleanCT uses an NVIDIA GPU (CuPy) when one is found, and the CPU otherwise. The two paths write the same output files.

**Setup.** Windows 11; Intel Core Ultra 7 265K (20 cores); 63 GB RAM; NVIDIA GeForce RTX 4080 SUPER (16 GB, driver 621.01). cleanCT v1.0.0 (commit `a45e4c2`), default 66 µm settings, three 66 µm scans. Each scan ran three times per backend. CPU runs hid the GPU with `CUDA_VISIBLE_DEVICES=-1`.

| Scan (slices) | GPU processing (s, mean ± sd) | CPU processing (s, mean ± sd) | GPU speed-up | Output |
|---|---|---|---|---|
| 1-1 (445) | 4.60 ± 0.08 | 5.27 ± 0.09 | 1.15× | identical |
| 1-12 (405) | 5.13 ± 0.45 | 5.63 ± 0.54 | 1.10× | identical |
| 1-13 (405) | 4.83 ± 0.45 | 5.30 ± 0.36 | 1.10× | identical |

"Identical" means the SHA-256 hashes of the two NIfTI outputs (`stripped.nii`, `wood_roi.nii`) match across all runs, and the cut and keep slices match.

- **Where the GPU helps.** ROI tracking is the largest stage (about 2 s). It takes 2.03 s on the GPU and 2.47 s on the CPU. Reading and writing the scan takes about 2 s on both. The speed-up is therefore limited to about 10–15% of the run.
- **Start-up.** Selecting the backend takes 1.1 s with a GPU. Without one, the GPU check fails first, and the CPU start takes 4.3 s. For scan 1-1, the total including start-up is about 5.7 s on the GPU and 9.5 s on the CPU.
- **Scope.** One PC and three scans. Other scan sizes or GPUs may change the ratio. Identical output was observed here; it is not a general guarantee.

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
# Linux package: runtime, gate, self-check, tarball
python3 installer/build_posix.py linux-x86_64
```

The Windows release build needs PyInstaller 6.22.2 and Inno Setup 6. The Linux build needs PowerShell 7 (`pwsh`) for the regression gate.

## Repository structure

| Path | Contents |
|---|---|
| `main.py` | Entry point. |
| `src/` | Application: `core/` (logic), `widgets/`, `dialogs/`, `main_window.py`, `theme.py`. |
| `assets/` | `banner/` (gallery), `screenshots/` (documentation), `icons/` (application icon pack). |
| `engine/` | Processing engine: the six modules the application imports. |
| `installer/` | Windows build (`build_installer.py`, launcher source, Inno Setup script); Linux and macOS build (`build_posix.py`, `posix/install.sh`); pinned requirements. |
| `tests/` | Regression suites (run by `tests/run_cleanct_regressions.ps1`) and their helpers. |
| `tools/` | Developer tools: debug overlays and the audit snapshot script. Not run in CI. |
| `docs/` | User guide, implementation details, release notes and change records. |
| `version/` | Release folders (not versioned). |
| `PRODUCT.md`, `DESIGN.md` | Design context. |

## Documentation

| Document | Content |
|---|---|
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | Step-by-step guide. Ships with the application. |
| [`docs/ROI_LOGIC.md`](docs/ROI_LOGIC.md) | Detection formulas and coordinate systems (earlier design; see the implementation details). |
| [`docs/RELEASE_NOTES.md`](docs/RELEASE_NOTES.md) | Release notes for v1.0.0. |
| [`docs/REVISION_HISTORY.md`](docs/REVISION_HISTORY.md), [`docs/DEV_LOG.md`](docs/DEV_LOG.md), [`docs/AUDIT.md`](docs/AUDIT.md) | Change and audit records. |

## Known limitations

- The processed axial view steps through 16 stored frames, not every slice.
- A running pipeline cannot be stopped.
- The longitudinal Results view reads the source folders; a moved source shows an error.
- Auto-crop trims the processing output only; bundles are cut to the lines on screen.
- Linux is checked in CI and headless only: its GUI and the CUDA path have not run on a physical machine.
- macOS is not part of v1.0.0. The macOS build code stays in the repository for a later release.

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
