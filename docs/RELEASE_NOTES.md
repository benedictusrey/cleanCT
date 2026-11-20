# cleanCT 1.0.0 — Release notes

**Platforms:** Windows 10 or 11 (64-bit) · Linux x86_64 with glibc 2.28 or newer · Python 3.12 source for Windows and Linux. macOS is not part of this release.

## Packages

| File | Use |
|---|---|
| `cleanCT-1.0.0-setup.exe` | Windows: per-machine installer (Program Files; asks for administrator approval). |
| `cleanCT-1.0.0-portable.zip` | Windows: extract the whole folder and run `cleanCT.exe`. No administrator rights needed. |
| `cleanCT-1.0.0-linux-x86_64.tar.gz` | Linux x86_64: extract and run `./cleanCT`; `./install.sh` adds a per-user install and a menu entry. |
| `cleanCT-1.0.0-python-source.zip` | Any Windows or Linux PC with Python 3.12: extract, run `python -m pip install -r installer/requirements-core.txt` in the folder, then `python main.py`. |
| `SHA256SUMS` | SHA-256 of every file above. |

Check a download with `Get-FileHash <file> -Algorithm SHA256` (Windows), `sha256sum -c SHA256SUMS` (Linux).

## Highlights

- Load DICOM series, TIFF stacks and NIfTI volumes; sources are registered in place and never modified.
- Automatic detection of the Keep (wood top), Cut (metal top) and L/R lines, placed on editable lines (Auto snap); Apply lines reprocesses the scan.
- Results: Before and After axial and longitudinal views, and a 3-D point cloud. Panel labels are drawn by the application.
- Export of the inner wood region as DICOM and NIfTI with the same voxels, plus a JSON sidecar and a text report. A bundle is verified before it is promoted.
- Preview checkpoints (`.ctcheckpoint.json`) and a per-session preview history.
- NVIDIA GPU through CuPy (CUDA 12) when available; validated CPU path otherwise.

## Changes since the first 1.0.0 build

- Export delivers only the processed run. A cut past the processed run is refused, so no blank or metal slices are written.
- Process and export applies the lines on screen first, then exports the run it processed.
- The NIfTI volume is cropped to the same L/R box as the DICOM series, in X and Y. The sidecar and the text report record the box.
- Margin above cut: the delivery stops that many slices above the Cut line (Cut minus margin).
- Process uses the Auto-crop setting. The check box trims the processing output (`wood_roi.nii`); the bundle is cut to the lines.
- Boundaries panel labels are drawn by the application; the raw axial view uses the bone palette.
- Results: a render started before a slider move no longer overwrites the slider position.
- The quick-look pictures (`*_qa_removal.png`, `*_qa_roi.png`) are drawn without matplotlib. The same slices and colours are shown; the font and spacing differ from earlier builds.
- The Linux `install.sh` refuses to run from the installed copy in every spelling of its path, so it cannot delete the installed app.
- The NVIDIA GPU is optional. The app uses CuPy on an NVIDIA GPU when one is found, and runs on the CPU otherwise. The self-check passes on a PC without a GPU and reports which one is in use.
- The Python source keeps its results in `data/pipeline_output` inside its folder. Earlier source builds wrote to a fixed folder on the developer's H: drive, which other PCs do not have.
- Renaming a loaded specimen is consistent when the save fails: the registry and the specimen's folder keep the old name.
- The specimen registry is written to disk before it is renamed, so a power cut cannot empty it.

## Verification

- Linux (CI run 44656346619, commit a45e4c2): regression gate, package self-check, self-checks in clean Ubuntu 22.04 and Debian 12 containers, and the Python source self-check in a fresh venv all passed.
- Windows (built from commit a45e4c2): regression gate 45 of 45 suites PASS; packaged launcher self-check PASS; the portable self-check PASS with the GPU active (NVIDIA GeForce RTX 4080 SUPER through CuPy) and with the GPU hidden (CPU); both files match their SHA-256 sidecars.
- Python source: exported from commit a45e4c2 and checked in a fresh venv in CI. Its self-check passes without CuPy.
- The packaged app and engine files match the source tree.

## Known limitations

- The processed axial view steps through 16 stored frames, not every slice.
- A running pipeline cannot be stopped.
- The longitudinal Results view reads the source folders; a moved source shows an error.
- macOS is not part of this release.
- The Linux GUI runs only headless (no screen) in CI. Nobody has run it on a physical Linux screen. CI does not exercise the Linux CUDA path.
- No NVIDIA GPU runs in CI, so the GPU path is verified on Windows only.

## Documentation

See [`README.md`](../README.md) and [`docs/USER_GUIDE.md`](USER_GUIDE.md).
