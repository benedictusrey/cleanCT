cleanCT 1.0.0 - Release and Installation
======================================================
Build date: 2026-11-18
Architecture: Windows x64
Bundled application runtime: CPython 3.12.3 x64
Launcher builder: PyInstaller 6.22.2
Classic installer compiler: Inno Setup 6

Choose one distribution:

Classic installer: cleanCT-1.0.0-setup.exe
  1. Double-click the installer and follow the setup prompts.
  2. The default destination is Program Files\cleanCT; Windows may
     ask for administrator approval.
  3. Start cleanCT from the Start menu or optional desktop shortcut.

Portable package: cleanCT-1.0.0-portable.zip
  1. Extract the complete ZIP to a folder you can write to.
  2. Open the cleanCT-1.0.0 folder and double-click cleanCT.exe.
  3. Keep the extracted cleanCT-1.0.0 folder together. No Python installation
     is required.

First launch and workflow:
  1. An empty specimen list is normal on a fresh installation.
     Select Load scan... to register scan data.
  2. Load a DICOM series (.dcm), TIFF stack (.tif/.tiff), or 3-D
     NIfTI file (.nii/.nii.gz), then review the preview and cut lines.
  3. Select Apply lines if you moved a line, then choose the destination
     on the Settings tab (Export section) and select Export.
  4. Preview history remains available until you exit cleanCT.
     Use Save checkpoint and Open checkpoint to save or restore a
     preview, cut lines, and view settings. The source scan stays
     separate; reconnect it to process or export a snapshot checkpoint.

The complete walkthrough is in USER_GUIDE.md. App data and processing
outputs are kept under %LOCALAPPDATA%\cleanCT, separately from the
installation folder.

The launcher was rebuilt from installer/launcher_main.py with the
Windows icon at assets/icons/app.ico. The production payload
includes the application graphics under app/icons.
