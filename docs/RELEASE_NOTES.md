# cleanCT 1.0.0 — Release notes

**Platforms:** Windows 10 or 11 (64-bit) · Linux x86_64 with glibc 2.28 or newer · macOS 12 or newer (Apple silicon and Intel)

## Packages

| File | Use |
|---|---|
| `cleanCT-1.0.0-setup.exe` | Windows: per-machine installer (Program Files; asks for administrator approval). |
| `cleanCT-1.0.0-portable.zip` | Windows: extract the whole folder and run `cleanCT.exe`. No administrator rights needed. |
| `cleanCT-1.0.0-linux-x86_64.tar.gz` | Linux x86_64: extract and run `./cleanCT`; `./install.sh` adds a per-user install and a menu entry. |
| `cleanCT-1.0.0-macos-arm64.dmg` | macOS, Apple silicon: drag cleanCT to Applications. |
| `cleanCT-1.0.0-macos-x86_64.dmg` | macOS, Intel: drag cleanCT to Applications. |
| `SHA256SUMS` | SHA-256 of every file above. |

Check a download with `Get-FileHash <file> -Algorithm SHA256` (Windows), `sha256sum -c SHA256SUMS` (Linux) or `shasum -a 256 -c SHA256SUMS` (macOS).

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

## Verification

- Windows (built on the maintainer's PC from this source): regression gate 40 of 40 suites PASS; packaged launcher self-check PASS; extracted portable self-check PASS with the GPU active (NVIDIA GeForce RTX 4080 SUPER through CuPy); the ZIP matches its SHA-256 sidecar.
- Linux and macOS: the regression gate, self-check and DMG steps run in CI. This build has not yet passed CI on both platforms; the release is not published until a CI run passes both.
- The Linux package self-checks in clean Ubuntu 22.04 and Debian 12 containers in CI.
- The packaged app and engine files match the source tree.

## Known limitations

- The processed axial view steps through 16 stored frames, not every slice.
- A running pipeline cannot be stopped.
- The longitudinal Results view reads the source folders; a moved source shows an error.
- macOS builds are not notarized; Gatekeeper asks for approval on first launch.
- The Linux and macOS GUIs run only headless (no screen) in CI. Nobody has run them on a physical Linux or Mac screen. CI does not exercise the Linux CUDA path.
- No NVIDIA GPU runs in CI, so the GPU path is verified on Windows only.

## Documentation

See [`README.md`](../README.md), [`docs/USER_GUIDE.md`](USER_GUIDE.md) and [`docs/cleanCT_details.md`](cleanCT_details.md).
