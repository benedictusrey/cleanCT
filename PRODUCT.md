# cleanCT: product context

## What it is

A Windows desktop tool that takes a CT scan of a wood sample with a metal base,
finds the wood and the metal, sets the cut lines, and exports the cut volume
(DICOM and/or NIfTI). It runs on one PC, usually with an NVIDIA GPU, and works
offline.

## Who uses it

A wood or materials scientist (or a technician working for one) at a lab
workstation, in long sessions, with many scans per week. They know CT data. They
do not want a dashboard; they want the scan, the cut lines and the numbers that
matter, with nothing in the way.

Assumption, labelled: the audience is inferred from the app's own user guide and
the way the scans are named. It was not checked with the user beyond the two
answers recorded below.

## The job, in order

1. Load a scan (DICOM series, TIFF stack, or NIfTI).
2. Check the detection guides (wood and metal) on the axial and longitudinal views.
3. Adjust the cut lines and the range, or accept the detection.
4. Process the scan.
5. Export the bundle.

## Mode

Operate. The user completes a task. Scanability, consistency and precise states
outrank expression. The brand lives in the details: one accent colour, a
display face for titles and numbers, and a calm grid.

## Decisions from the user

- Theme: dark and light, both available, switched in Preferences (Appearance).
  Dark is the default. The scan canvases stay dark in both, so the image keeps
  its contrast.
- Scope: a full redesign of the layout and the look, not a restyle.

## Principles

- The scan is the work. Chrome recedes.
- One accent (teal) means "this is the line you can move" and "this is the next
  action". Nothing else is saturated.
- Every control shows its state: active, disabled, focused.
- Plain labels in sentence case. No all-caps, no em dashes in labels, no
  pictographs in button text.
- A narrow window scrolls a page; it never forces the window wider than the screen.

## Constraints

- Windows 10 and 11, Qt Widgets (PySide6). Not a web page: the web-only rules of
  the design skills (Chrome gate, photographs, hero sections) do not apply.
- Fonts that ship with Windows: Segoe UI, Bahnschrift, Cascadia Mono or Consolas.
- Works with and without the GPU; the layout does not change either way.
