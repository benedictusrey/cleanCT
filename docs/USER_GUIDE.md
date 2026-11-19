# cleanCT 1.0.0 — User Guide

cleanCT reviews and processes micro-CT scans from DICOM, TIFF, or NIfTI sources, then exports a separate result bundle. DICOM sources can be exported as DICOM, NIfTI, or both. TIFF and NIfTI sources are exported as NIfTI so cleanCT does not invent missing DICOM acquisition metadata.

## 1. Start the app

1. **Windows:** install with `cleanCT-1.0.0-setup.exe`, or extract the complete portable ZIP and open `cleanCT.exe` from the `cleanCT-1.0.0` folder.
2. **Linux:** extract `cleanCT-1.0.0-linux-x86_64.tar.gz` and run `./cleanCT` in the extracted folder. For a per-user install with an application-menu entry, run `./install.sh` instead.
3. **macOS:** open the DMG and drag cleanCT to Applications. The app is not notarized, so the first launch needs approval: Control-click cleanCT and choose Open. On macOS 15 and later, open System Settings › Privacy & Security and choose Open Anyway.

The first launch may take a little longer while the app prepares its runtime. No Python installation or administrator setup is needed. Use a local drive with enough free space for processing results and exports. An NVIDIA GPU is used automatically on Windows and Linux when a compatible driver is available; otherwise cleanCT uses the CPU, which may take longer. macOS always uses the CPU.

## 2. Choose a scan

The sidebar lists specimens already available on this computer. A new portable install may start with an empty list; this is normal. Select **Load scan…** and choose one source:

- **DICOM:** the folder containing one `.dcm` series, or its immediate parent if it contains one series folder. Do not select a folder containing multiple series.
- **TIFF:** one multipage grayscale `.tif`/`.tiff` stack, or a folder of grayscale TIFF slices with matching dimensions. Color TIFFs and mixed or mismatched stacks are rejected.
- **NIfTI:** one 3-D `.nii` or `.nii.gz` file. Four-dimensional data is not supported. NIfTI orientation, affine, and stored scaling are read when available.

Enter a short **Specimen ID** and select **Load & Register**. cleanCT validates the source and adds it under **Loaded specimens**. Registration keeps a reference to the original file or folder; it does not copy the scan. Keep the source in place while it is registered.

For TIFF or NIfTI data, **Auto-detect** is the recommended intensity setting. Choose **Stored values are already HU** only when you know the voxels are calibrated Hounsfield units. Otherwise, thresholds are estimated from sampled stored values and are reported as stored intensity, not HU. DICOM rescale metadata is used for DICOM HU. If TIFF physical spacing is missing, cleanCT marks geometry as assumed; verify the scale before interpreting measurements. A `.nii.gz` file is expanded into temporary storage for efficient random slice access, so the temp drive needs roughly the uncompressed file size plus a small reserve.

Select the registered specimen in the left-hand list to load it.

### Save and restore a preview checkpoint

- **Save checkpoint** saves the current preview image, cut lines, intensity window, viewing plane, and related preview settings to a compact .ctcheckpoint.json file.
- Save and Open start in the folder used last. **Settings > Checkpoints** shows that folder and lets you choose another.
- **Open checkpoint** restores the saved preview immediately. If the original registered source is still available at the same location, cleanCT reconnects it so you can continue processing. If it is missing or moved, the preview remains available as a snapshot; load and register the source again to process or export.
- A checkpoint stores a preview and settings, not the scan volume. Keep the original scan available separately.
- **Preview history · this session** keeps applied preview states available in the sidebar until you exit cleanCT. Choose a history entry to restore it. This history is not written to disk unless you save a checkpoint.

## 3. Review the scan and boundaries

The **Results** tab shows the scan views. Open **Boundaries** to inspect the reconstruction and its guide lines. cleanCT places the guides from its detection; review them against the scan before processing.

- The green **Keep** line marks where the collected range begins. The **Wood Top** guide (green, dotted) marks the top of the wood, and Keep follows it.
- The red **Cut** line marks the platform cut. The **Metal Top** guide (orange, dotted) marks the top of the metal base, and Cut follows it.
- **Margin above cut** stops the delivery that many slices above the Cut line, a safety buffer between the cut and the metal. The delivered range ends at Cut minus margin.
- **2 Lines (Z Range)** shows the keep/cut range. **4 Lines (Box Bounds)** also shows lateral box limits. Drag a guide or use its sliders to adjust it.
- **Snap to detection** and **Reset to detected** restore detected boundaries.
- **Auto-crop to wood (air detection)** is enabled by default. It trims the wood box in the processing output (wood_roi.nii). The bundle is cut to the Keep, Cut and L/R lines, not to this box.

The colorspace, density thresholds, and preview slice controls change the on-screen preview. They do not change the saved scan by themselves. After changing keep/cut or box bounds, select **Apply lines** to apply them and process the scan again.

## 4. Process and export

Choose one of these actions in the left sidebar:

- **Process** runs processing for the selected specimen.
- **Apply lines** (in Boundaries) applies the adjusted boundaries and processes again.
- **Process and export** applies the lines on screen, processes, and exports in one job, using the current destination and format.

To export a specimen that has already been processed:

1. Open the **Settings** tab (right end of the tab row), then the **Export** section. Enter a destination folder or select **Browse…**. Typed or browsed folders are saved for later sessions. The export row above the viewers shows the current folder; **Change in Settings** opens this section.
2. In the same section, choose a format for this export:
   - For DICOM sources: **DICOM + NIfTI** (default), **DICOM only**, or **NIfTI only**. The line under the format says what each one writes.
   - For TIFF/NIfTI sources: cleanCT uses **NIfTI only**, preserving source voxel values and physical affine where available.
3. Select **Export** in the export row and wait for the completion status. Export is refused when the Cut is past the processed run: select **Apply lines**, then export again.

The bundle is saved in a subfolder named for the specimen. It includes the requested output files and a summary with processing and source details. Exports are separate from the source scan. Re-exporting updates that specimen’s bundle only after the new export is complete. For DICOM sources, an existing unrequested format is retained. To prevent source mixing, a TIFF/NIfTI export stops if the destination already contains a DICOM bundle with the same specimen ID; choose a different ID or destination.

## 5. Where files are stored

- Windows: `%LOCALAPPDATA%\cleanCT\` (processing results in `pipeline_output`, default exports in `export`).
- Linux: `~/.local/share/cleanCT/` (or `$XDG_DATA_HOME/cleanCT/` when that is set).
- macOS: `~/Library/Application Support/cleanCT/`.
- If you change **Export to**, exports go to that folder instead.

The original scan remains at its source location. DICOM exports retain source metadata; review that metadata and follow your organization’s data-handling rules before sharing an export. TIFF/NIfTI bundles include source format, intensity, geometry, and threshold notes; missing TIFF spacing is identified as assumed.

## 6. If something goes wrong

- If a scan will not load, select one supported source at a time. For DICOM, choose the folder containing the series. For a TIFF folder, confirm it contains matching grayscale slices. For NIfTI, choose a single 3-D `.nii`/`.nii.gz` file and ensure the temp drive has enough free space.
- If **Export** reports that the scan has not been processed, run **Process** first or use **Process and export**.
- Processing time depends on scan size and available hardware. The progress panel and action log show the current stage. CPU mode is supported when a compatible NVIDIA GPU is unavailable.
- If an error appears, note its text and the specimen ID. Keep the source folder unchanged and include those details when asking for help.
