# cleanCT 1.0.0 — User Guide

cleanCT reviews and processes micro-CT scans from DICOM, TIFF, or NIfTI sources, then exports a separate result bundle. DICOM sources can be exported as DICOM, NIfTI, or both. TIFF and NIfTI sources are exported as NIfTI so cleanCT does not invent missing DICOM acquisition metadata.

## 1. Start the app

1. Extract the complete portable ZIP to a folder on your PC. Keep the files together inside the `_pkg` folder.
2. Open `_pkg` and double-click `cleanCT.exe`. The first launch may take a little longer while the app prepares its runtime. No Python installation or administrator setup is needed.
3. Use a local drive with enough free space for processing results and exports. An NVIDIA GPU is used automatically when a compatible driver is available; otherwise cleanCT uses the CPU, which may take longer.

## 2. Choose a scan

The sidebar lists specimens already available on this computer. A new portable install may start with an empty list; this is normal. Select **Load specimen folder…** (or **Load scan…** in the empty-state card) and choose one source:

- **DICOM:** the folder containing one `.dcm` series, or its immediate parent if it contains one series folder. Do not select a folder containing multiple series.
- **TIFF:** one multipage grayscale `.tif`/`.tiff` stack, or a folder of grayscale TIFF slices with matching dimensions. Color TIFFs and mixed or mismatched stacks are rejected.
- **NIfTI:** one 3-D `.nii` or `.nii.gz` file. Four-dimensional data is not supported. NIfTI orientation, affine, and stored scaling are read when available.

Enter a short **Specimen ID** and select **Load & Register**. cleanCT validates the source and adds it under **Loaded specimens**. Registration keeps a reference to the original file or folder; it does not copy the scan. Keep the source in place while it is registered.

For TIFF or NIfTI data, **Auto-detect** is the recommended intensity setting. Choose **Stored values are already HU** only when you know the voxels are calibrated Hounsfield units. Otherwise, thresholds are estimated from sampled stored values and are reported as stored intensity, not HU. DICOM rescale metadata is used for DICOM HU. If TIFF physical spacing is missing, cleanCT marks geometry as assumed; verify the scale before interpreting measurements. A `.nii.gz` file is expanded into temporary storage for efficient random slice access, so the temp drive needs roughly the uncompressed file size plus a small reserve.

Select the registered specimen in the left-hand list to load it.

### Save and restore a preview checkpoint

- **Save checkpoint…** saves the current preview image, cut lines, intensity window, viewing plane, and related preview settings to a compact .ctcheckpoint.json file.
- **Load checkpoint…** restores the saved preview immediately. If the original registered source is still available at the same location, cleanCT reconnects it so you can continue processing. If it is missing or moved, the preview remains available as a snapshot; load and register the source again to process or export.
- A checkpoint stores a preview and settings, not the scan volume. Keep the original scan available separately.
- **Preview history · this session** keeps applied preview states available in the sidebar until you exit cleanCT. Choose a history entry to restore it. This history is not written to disk unless you save a checkpoint.

## 3. Review the scan and boundaries

The **Auto** tab shows the scan views. Open **Preferences** to inspect the reconstruction and its guide lines. cleanCT places the guides from its detection; review them against the scan before processing.

- The green **Top Line (Keep Start)** marks where the collected range begins.
- The red **Bottom Line (Platform Cut)** marks the cut boundary.
- **Margin Above Cut** controls how many safety slices are kept above the cut.
- **2 Lines (Z Range)** shows the keep/cut range. **4 Lines (Box Bounds)** also shows lateral box limits. Drag a guide or use its sliders to adjust it.
- **Snap to detection** and **Reset to detected** restore detected boundaries.
- **Auto-crop to wood (air detection)** is enabled by default. It trims near-empty air margins when safe; the crop stays within the tracked region.

The colorspace, density thresholds, and preview slice controls change the on-screen preview. They do not change the saved scan by themselves. After changing keep/cut or box bounds, select **Apply & process** to run processing with those settings.

## 4. Process and export

Choose one of these actions in the left sidebar:

- **Process selected** runs processing for the selected specimen.
- **Apply & process** (in Preferences) applies the adjusted boundaries and processes again.
- **Process & Export selected** processes and exports in one job, using the current destination and format.

To export a specimen that has already been processed:

1. In **Bundle Dest**, enter a destination folder or select **Browse…**. The selected folder is remembered for later sessions.
2. Choose a format for this export:
   - For DICOM sources: **DICOM + NIfTI** (default), **DICOM only**, or **NIfTI only**.
   - For TIFF/NIfTI sources: cleanCT uses **NIfTI only**, preserving source voxel values and physical affine where available.
3. Select **Export bundle** and wait for the completion status.

The bundle is saved in a subfolder named for the specimen. It includes the requested output files and a summary with processing and source details. Exports are separate from the source scan. Re-exporting updates that specimen’s bundle only after the new export is complete. For DICOM sources, an existing unrequested format is retained. To prevent source mixing, a TIFF/NIfTI export stops if the destination already contains a DICOM bundle with the same specimen ID; choose a different ID or destination.

## 5. Where files are stored

- Processing results: `%LOCALAPPDATA%\cleanCT\pipeline_output`
- Default exported bundles: `%LOCALAPPDATA%\cleanCT\export`
- If you change **Bundle Dest**, exports go to that folder instead.

The original scan remains at its source location. DICOM exports retain source metadata; review that metadata and follow your organization’s data-handling rules before sharing an export. TIFF/NIfTI bundles include source format, intensity, geometry, and threshold notes; missing TIFF spacing is identified as assumed.

## 6. If something goes wrong

- If a scan will not load, select one supported source at a time. For DICOM, choose the folder containing the series. For a TIFF folder, confirm it contains matching grayscale slices. For NIfTI, choose a single 3-D `.nii`/`.nii.gz` file and ensure the temp drive has enough free space.
- If **Export bundle** reports that the scan has not been processed, run **Process selected** first or use **Process & Export selected**.
- Processing time depends on scan size and available hardware. The progress panel and action log show the current stage. CPU mode is supported when a compatible NVIDIA GPU is unavailable.
- If an error appears, note its text and the specimen ID. Keep the source folder unchanged and include those details when asking for help.
