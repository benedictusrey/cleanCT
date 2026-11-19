# cleanCT 1.0.0 — Release notes

**Release date:** 2026-11-19 · **Platform:** Windows 10 or 11, 64-bit · **Engine:** metal_remover 2a53ba6

## Packages

| File | Use |
|---|---|
| `cleanCT-1.0.0-portable.zip` | Extract the whole folder and run `cleanCT.exe`. No administrator rights needed. |
| `cleanCT-1.0.0-portable.zip.sha256` | SHA-256 of the ZIP. |
| `cleanCT-1.0.0-setup.exe` | Per-machine installer (Program Files; asks for administrator approval). |

Check a download with `Get-FileHash <file> -Algorithm SHA256` and compare the value with the `.sha256` file.

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

## Verification

- Regression gate: 37 suites, PASS.
- Packaged launcher self-check: PASS. Extracted portable self-check: PASS, GPU active.
- The application sources in the package are identical to the source tree.

## Known limitations

- The processed axial view steps through 16 stored frames, not every slice.
- A running pipeline cannot be stopped.
- The longitudinal Results view reads the source folders; a moved source shows an error.
- Windows only.

## Documentation

See [`README.md`](../README.md), [`docs/USER_GUIDE.md`](USER_GUIDE.md) and [`docs/cleanCT_details.md`](cleanCT_details.md).
