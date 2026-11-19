#!/usr/bin/env python
"""cleanCT 1.0.0 package builder.

Assembles the shipping payload into installer/_pkg:

    _pkg/
      cleanCT.exe            windowless launcher (PyInstaller onefile)
      README.txt             quick-start for recipients
      THIRD_PARTY_NOTICES.md license notices (MIT template)
      app/                   cleanCT GUI sources + assets + icons/
      engine/                frozen metal-remover pipeline (5 modules)
      runtime/               embedded CPython 3.12.3 + pinned wheels
                             (numpy, scipy, PySide6-Essentials, pydicom,
                              nibabel, Pillow, scikit-image,
                              cupy-cuda12x + NVRTC runtime wheels)

then produces:
    installer/out/cleanCT-<ver>-portable.zip
    installer/out/cleanCT-<ver>-setup.exe   (compiled with ISCC.exe)
    installer/cleanct.iss                   (Inno project, always written)

The payload is torch-free: GPU acceleration is delivered through CuPy
(cupy-cuda12x 13.4.1 + nvidia-cuda-nvrtc-cu12 12.8.93), and machines without
an NVIDIA GPU run the validated CPU backend. The pinned environment is copied
from tests/venv_notorch (audit 0Q); packaging removes only verified test/docs,
Qt authoring/QML assets, and the duplicate CuPy NVRTC DLLs. The resulting
payload was checked with the packaged GUI smoke and active CuPy GPU selfcheck.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = "cleanCT"
APP_VERSION = "1.0.0"
ZIP_ROOT = f"{APP_NAME}-{APP_VERSION}"     # top folder inside the portable ZIP
PY_EMBED_URL = ("https://www.python.org/ftp/python/3.12.3/"
                "python-3.12.3-embed-amd64.zip")
PY_EMBED_VERSION = "3.12.3"
# Published Python.org checksum for python-3.12.3-embed-amd64.zip.
PY_EMBED_MD5 = "38cce2bf5b4de76db19a31f46a0720de"

HERE = Path(__file__).resolve().parent          # installer/
SRC = HERE.parent                               # cleanCT checkout root
SRCDIR = SRC / "src"                            # application sources
ENGINE = SRC / "engine"
VENV = SRC / "tests" / "venv_notorch"
PKG = HERE / "_pkg"
CACHE = HERE / "_cache"
OUT = HERE / "out"
PKG_FINAL = PKG
PKG_STAGING = CACHE / "_pkg_staging"


# Explicit include list: the packaged app is exactly what it imports at
# runtime, immune to checkout clutter (export bundles, caches, the custom
# specimen registry with its junctions, stray exes).
APP_INCLUDE_DIRS = ["core", "widgets", "dialogs"]
APP_INCLUDE_FILES = ["main_window.py", "theme.py", "icon_utils.py"]
APP_ENTRY_FILE = SRC / "main.py"
# Production brand assets: the window icon files plus the canonical icon
# pack. Keep assets/icons as the single source of truth so the installer
# cannot silently fall back to a stale copy.
ASSET_FILES = ["app.ico", "app_icon_256.png"]
ICON_ASSET_DIR = SRC / "assets" / "icons"
REQUIRED_ICON_ASSETS = {
    "app.ico",
    "icon_256x256.png",
    "icon_1024x1024.png",
}
ENGINE_MODULES = [
    "tomograph.py", "roi_delivery.py", "wood_track.py", "air_crop.py",
    "gpu_backend.py", "volume_io.py",
]


def log(msg: str) -> None:
    print(f"[pkg] {msg}", flush=True)


def print_captured(text: str, stream) -> None:
    """Write captured subprocess text safely on legacy Windows consoles."""
    encoding = getattr(stream, "encoding", None) or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(
        encoding, errors="replace")
    print(safe_text, end="" if safe_text.endswith("\n") else "\n",
          file=stream, flush=True)


def copy_tree(src: Path, dst: Path, exclude_dirs: set[str] | None = None,
              exclude_files: set[str] | None = None) -> int:
    n = 0
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        dirs[:] = [d for d in dirs if d not in (exclude_dirs or set())]
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            if f in (exclude_files or set()) or f.endswith((".pyc", ".pyo")):
                continue
            shutil.copy2(Path(root) / f, dst / rel / f)
            n += 1
    return n


RUNTIME_EXCLUDE_DIRS = {
    "__pycache__", "tests", "docs", "doc", "benchmarks", "sphinxext",
}
PYSIDE_EXCLUDE_DIRS = RUNTIME_EXCLUDE_DIRS | {
    "qml", "include", "typesystems", "metatypes",
}
PYSIDE_UNUSED_FILES = {
    "Qt6Designer.dll", "Qt6DesignerComponents.dll", "Qt6Help.dll",
    "Qt6UiTools.dll", "Qt6Test.dll", "Qt6DBus.dll", "Qt6Sql.dll",
    "QtDesigner.pyd", "QtHelp.pyd", "QtUiTools.pyd", "QtTest.pyd",
    "QtDBus.pyd", "QtSql.pyd", "assistant.exe", "designer.exe",
    "linguist.exe", "lupdate.exe", "uic.exe", "qmlls.exe",
    "qmlformat.exe", "qmllint.exe",
}
PYSIDE_UNUSED_PREFIXES = ("Qt6Qml", "Qt6Quick", "QtQml", "QtQuick")
CUPY_DUPLICATE_NVRTC_FILES = {
    "nvrtc64_120_0.dll", "nvrtc64_120_0.alt.dll",
    "nvrtc-builtins64_129.dll",
}


def copy_runtime_tree(src: Path, dst: Path) -> int:
    """Copy runtime resources while omitting tests/docs and unused Qt/CUDA assets.

    Keep Python examples: pydicom imports its examples package at startup.
    Keep the pinned NVIDIA NVRTC 12.8.93 wheel. CuPy's bundled 12.9 NVRTC
    duplicate is not needed because gpu_backend preloads the tested wheel;
    this exact trimmed payload is validated by --selfcheck on CUDA hardware.
    """
    copied = 0
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        top = rel.parts[0] if rel.parts else ""
        excluded_dirs = PYSIDE_EXCLUDE_DIRS if top == "PySide6" else RUNTIME_EXCLUDE_DIRS
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                continue
            if top == "PySide6":
                if name.endswith(".pyi") or name in PYSIDE_UNUSED_FILES:
                    continue
                if name.startswith(PYSIDE_UNUSED_PREFIXES):
                    continue
            if rel.parts[:3] == ("cupy_backends", "cuda", "libs") \
                    and name in CUPY_DUPLICATE_NVRTC_FILES:
                continue
            shutil.copy2(Path(root) / name, dst / rel / name)
            copied += 1
    return copied


def _valid_embedded_python_archive(path: Path) -> bool:
    if not path.is_file():
        return False
    digest = hashlib.md5(usedforsecurity=False)
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == PY_EMBED_MD5


def _ensure_embedded_python_archive() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / Path(PY_EMBED_URL).name
    if _valid_embedded_python_archive(path):
        log("embedded Python archive: cached checksum OK")
        return path

    if path.exists():
        log("embedded Python archive cache failed checksum; refreshing it")
    else:
        log(f"downloading {PY_EMBED_URL}")

    import ssl
    import urllib.request

    download = path.with_name(f"{path.name}.download-{os.getpid()}")
    download.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(
                PY_EMBED_URL, context=ssl.create_default_context(), timeout=60) as response:
            with download.open("wb") as stream:
                shutil.copyfileobj(response, stream)
        if not _valid_embedded_python_archive(download):
            raise RuntimeError(
                "downloaded Python embeddable archive failed the Python.org checksum")
        os.replace(download, path)
    finally:
        download.unlink(missing_ok=True)
    log("embedded Python archive: download checksum OK")
    return path


def step_runtime() -> None:
    """Build embedded CPython plus the validated, runtime-only package set."""
    rt = PKG / "runtime"
    if (rt / "python.exe").is_file():
        log("runtime: already present, refreshing site-packages only")
        sp = rt / "Lib" / "site-packages"
        if sp.exists():
            shutil.rmtree(sp)
    else:
        shutil.rmtree(rt, ignore_errors=True)
        rt.mkdir(parents=True)
        zpath = _ensure_embedded_python_archive()
        log("extracting verified embedded Python")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(rt)
        pth = rt / "python312._pth"
        pth.write_text("python312.zip\n.\nLib\nLib/site-packages\n",
                       encoding="utf-8")

    sp_src = VENV / "Lib" / "site-packages"
    if not sp_src.exists():
        log("FATAL: tests/venv_notorch missing - run setup_env.ps1 first")
        sys.exit(2)
    sp = rt / "Lib" / "site-packages"
    log("copying runtime site-packages; pruning test/docs/unused Qt assets")
    count = copy_runtime_tree(sp_src, sp)
    log(f"runtime ready: {count} files")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_icon_assets(destination: Path) -> tuple[int, int]:
    source = ICON_ASSET_DIR
    if not source.is_dir() or source.is_symlink():
        raise RuntimeError(f"required production icon directory missing: {source}")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise RuntimeError(f"icon assets contain a symbolic link: {source}")

    # Keep every production graphic from the approved brand pack while
    # excluding its design README from the recipient application.
    source_files = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if (path.is_file() and path.suffix.lower() not in {".pyc", ".pyo"}
            and path.name.lower() != "readme.md")
    }
    missing = REQUIRED_ICON_ASSETS - source_files
    if missing:
        raise RuntimeError(
            "required cleanCT icon assets are missing: "
            + ", ".join(sorted(missing)))

    count = copy_tree(source, destination, exclude_files={"README.md"})
    staged_files = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() and path.suffix.lower() not in {".pyc", ".pyo"}
    }
    if staged_files != source_files or count != len(source_files):
        raise RuntimeError(
            "staged icon file list differs from assets/icons")
    total_bytes = 0
    for relative in sorted(source_files):
        source_file = source / Path(relative)
        staged_file = destination / Path(relative)
        if source_file.stat().st_size != staged_file.stat().st_size:
            raise RuntimeError(f"staged icon size mismatch: {relative}")
        if _file_sha256(source_file) != _file_sha256(staged_file):
            raise RuntimeError(f"staged icon checksum mismatch: {relative}")
        total_bytes += source_file.stat().st_size
    return count, total_bytes


def step_app() -> None:
    app = PKG / "app"
    shutil.rmtree(app, ignore_errors=True)
    app.mkdir(parents=True)
    n = 0
    for d in APP_INCLUDE_DIRS:
        src = SRCDIR / d
        if not src.is_dir():
            log(f"FATAL: expected app dir missing: {src}")
            sys.exit(2)
        n += copy_tree(src, app / d, exclude_dirs={"__pycache__"})
    for f in APP_INCLUDE_FILES:
        src = SRCDIR / f
        if not src.is_file():
            log(f"FATAL: expected app file missing: {src}")
            sys.exit(2)
        shutil.copy2(src, app / f)
        n += 1
    if not APP_ENTRY_FILE.is_file():
        log(f"FATAL: app entry point missing: {APP_ENTRY_FILE}")
        sys.exit(2)
    shutil.copy2(APP_ENTRY_FILE, app / "main.py")
    n += 1
    assets = app / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for f in ASSET_FILES:
        src = SRC / "assets" / f
        if not src.is_file():
            log(f"FATAL: expected asset missing: {src}")
            sys.exit(2)
        shutil.copy2(src, assets / f)
        n += 1
    icon_count, icon_bytes = copy_icon_assets(app / "icons")
    n += icon_count
    log(f"app: {n} files including {icon_count} verified icon assets "
        f"({icon_bytes / 1e6:.1f} MB)")


def step_engine() -> None:
    eng = PKG / "engine"
    shutil.rmtree(eng, ignore_errors=True)
    eng.mkdir(parents=True)
    for m in ENGINE_MODULES:
        shutil.copy2(ENGINE / m, eng / m)
    log(f"engine: {len(ENGINE_MODULES)} modules")


def step_launcher(pyinstaller_python: Path, pyinstaller_version: str) -> None:
    """Build a one-file launcher from source and require an embedded app icon."""
    src = HERE / "launcher_main.py"
    if not src.is_file():
        raise RuntimeError(f"installer launcher source is missing: {src}")
    if not pyinstaller_python.is_file():
        raise RuntimeError(f"PyInstaller interpreter is missing: {pyinstaller_python}")
    icon = ICON_ASSET_DIR / "app.ico"
    if not icon.is_file():
        raise RuntimeError(f"required Windows icon is missing: {icon}")
    icon_data = icon.read_bytes()
    if (len(icon_data) < 22 or icon_data[:4] != b"\x00\x00\x01\x00"
            or icon_data[4:6] == b"\x00\x00"):
        raise RuntimeError(f"invalid or empty Windows icon resource: {icon}")

    bwork = HERE / "_launcher_build"
    bdist = HERE / "_launcher_dist"
    shutil.rmtree(bwork, ignore_errors=True)
    shutil.rmtree(bdist, ignore_errors=True)
    cmd = [
        str(pyinstaller_python), "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", "cleanCT",
        "--distpath", str(bdist), "--workpath", str(bwork),
        "--specpath", str(bwork), "--icon", str(icon), str(src),
    ]
    log(f"building launcher from source with PyInstaller {pyinstaller_version}")
    r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-5000:])
        print(r.stderr[-5000:])
        raise RuntimeError(f"PyInstaller failed with exit code {r.returncode}")
    exe = bdist / "cleanCT.exe"
    if not exe.is_file() or exe.stat().st_size < 100_000:
        raise RuntimeError("PyInstaller did not produce a valid launcher executable")

    icon_check = (
        "import pefile,sys; "
        "p=pefile.PE(sys.argv[1], fast_load=True); "
        "p.parse_data_directories(directories=["
        "pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']]); "
        "ids=[e.id for e in p.DIRECTORY_ENTRY_RESOURCE.entries if e.id is not None]; "
        "assert 14 in ids and 3 in ids, ids; "
        "print('PE group-icon and icon resources verified')"
    )
    verify = subprocess.run(
        [str(pyinstaller_python), "-c", icon_check, str(exe)],
        cwd=str(HERE), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if verify.returncode != 0:
        print(verify.stdout[-2000:])
        print(verify.stderr[-2000:])
        raise RuntimeError("the rebuilt launcher is missing embedded icon resources")
    shutil.copy2(exe, PKG / "cleanCT.exe")
    shutil.rmtree(bwork, ignore_errors=True)
    shutil.rmtree(bdist, ignore_errors=True)
    log(verify.stdout.strip())
    log(f"fresh launcher copied into staged payload ({(PKG / 'cleanCT.exe').stat().st_size / 1e6:.1f} MB)")


def third_party_notices() -> str:
    """THIRD_PARTY_NOTICES.md for every package (Windows and POSIX)."""
    return (
        "# Third-party notices\n\n"
        f"{APP_NAME} {APP_VERSION} bundles the following open-source\n"
        "components. Each is available under its own license, reproduced\n"
        "or referenced in the listed package metadata inside\n"
        "the runtime's site-packages folder (`*-dist-info`).\n\n"
        "| Component | Version | License |\n"
        "|---|---|---|\n"
        "| CPython | " + PY_EMBED_VERSION + " | PSF-2.0 |\n"
        "| numpy | 1.26.4 | BSD-3-Clause |\n"
        "| scipy | 1.13.1 | BSD-3-Clause |\n"
        "| PySide6-Essentials | 6.9.2 | LGPL-3.0 |\n"
        "| pydicom | 3.0.2 | MIT |\n"
        "| nibabel | 5.4.2 | MIT |\n"
        "| tifffile | 2023.4.12 | BSD |\n"
        "| Pillow | 12.3.0 | HPND (MIT-CMU) |\n"
        "| scikit-image | 0.26.0 | BSD-3-Clause |\n"
        "| cupy-cuda12x | 13.4.1 | MIT |\n"
        "| nvidia-cuda-nvrtc-cu12 | 12.8.93 | NVIDIA SDK license |\n"
        "| nvidia-cuda-runtime-cu12 | 12.9.x | NVIDIA SDK license |\n"
        "\n"
        "PySide6 is used under the terms of the GNU Lesser General Public\n"
        "License v3; its dynamic linking in this application does not\n"
        "modify the library. Replace the bundled PySide6 at will - the\n"
        "application starts without modification using any conforming\n"
        "build of the listed versions.\n"
    )


def step_docs() -> None:
    guide_src = SRC / "docs" / "USER_GUIDE.md"
    if not guide_src.is_file():
        raise RuntimeError(f"required user guide is missing: {guide_src}")
    shutil.copy2(guide_src, PKG / "USER_GUIDE.md")
    license_src = SRC / "LICENSE"
    if not license_src.is_file():
        raise RuntimeError(f"required license file is missing: {license_src}")
    shutil.copy2(license_src, PKG / "LICENSE.txt")
    (PKG / "README.txt").write_text(
        f"{APP_NAME} {APP_VERSION}\n"
        f"{'=' * 40}\n\n"
        "Quick start:\n"
        f"  1. Extract the complete ZIP and keep the {ZIP_ROOT} folder together.\n"
        f"  2. Open the {ZIP_ROOT} folder and double-click cleanCT.exe. No Python\n"
        "     install or administrator setup is needed. First launch may take longer.\n"
        "  3. The specimen list shows data already available on this PC. A\n"
        "     fresh install may be empty; select 'Load scan…' to add\n"
        "     a DICOM series, TIFF stack, or 3-D NIfTI file.\n"
        "  4. Review the detected guide lines in Boundaries. Select\n"
        "     'Apply lines' to apply adjusted boundaries and process again.\n"
        "  5. On the Settings tab, Export section, choose the folder and\n"
        "     format; then select 'Export' in the export row\n"
        "     (or use 'Process and export' for a one-step run).\n\n"
        "Open USER_GUIDE.md for the complete short walkthrough and help.\n\n"
        "GPU acceleration is automatic with a compatible NVIDIA driver;\n"
        "otherwise cleanCT uses the CPU. A CUDA Toolkit is not required.\n\n"
        "Processing results: %LOCALAPPDATA%\\cleanCT\\pipeline_output\n"
        "Default exported bundles: %LOCALAPPDATA%\\cleanCT\\export\n"
        "Export to can be changed in the app and is remembered.\n\n"
        "DICOM exports retain source metadata. Review metadata and follow\n"
        "your data-handling rules before sharing exported files.\n\n"
        "Optional health check (run from this folder):\n"
        "  runtime\\python.exe -X utf8 app\\main.py --selfcheck\n"
        "cleanCT.exe --selfcheck also returns the status without a console.\n",
        encoding="utf-8")
    (PKG / "THIRD_PARTY_NOTICES.md").write_text(third_party_notices(), encoding="utf-8")
    log("docs: README.txt, USER_GUIDE.md, LICENSE.txt, THIRD_PARTY_NOTICES.md")


def step_installer_readme(pyinstaller_version: str,
                          inno_version: str) -> None:
    """Add recipient-facing release and installation instructions."""
    lines = [
        f"cleanCT {APP_VERSION} - Release and Installation",
        "=" * 54,
        f"Build date: {datetime.date.today().isoformat()}",
        "Architecture: Windows x64",
        f"Bundled application runtime: CPython {PY_EMBED_VERSION} x64",
        f"Launcher builder: PyInstaller {pyinstaller_version}",
        f"Classic installer compiler: {inno_version}",
        "",
        "Choose one distribution:",
        "",
        f"Classic installer: {APP_NAME}-{APP_VERSION}-setup.exe",
        "  1. Double-click the installer and follow the setup prompts.",
        "  2. The default destination is Program Files\\cleanCT; Windows may",
        "     ask for administrator approval.",
        "  3. Start cleanCT from the Start menu or optional desktop shortcut.",
        "",
        f"Portable package: {APP_NAME}-{APP_VERSION}-portable.zip",
        "  1. Extract the complete ZIP to a folder you can write to.",
        f"  2. Open the {ZIP_ROOT} folder and double-click cleanCT.exe.",
        f"  3. Keep the extracted {ZIP_ROOT} folder together. No Python installation",
        "     is required.",
        "",
        "First launch and workflow:",
        "  1. An empty specimen list is normal on a fresh installation.",
        "     Select Load scan... to register scan data.",
        "  2. Load a DICOM series (.dcm), TIFF stack (.tif/.tiff), or 3-D",
        "     NIfTI file (.nii/.nii.gz), then review the preview and cut lines.",
        "  3. Select Apply lines if you moved a line, then choose the destination",
        "     on the Settings tab (Export section) and select Export.",
        "  4. Preview history remains available until you exit cleanCT.",
        "     Use Save checkpoint and Open checkpoint to save or restore a",
        "     preview, cut lines, and view settings. The source scan stays",
        "     separate; reconnect it to process or export a snapshot checkpoint.",
        "",
        "The complete walkthrough is in USER_GUIDE.md. App data and processing",
        "outputs are kept under %LOCALAPPDATA%\\cleanCT, separately from the",
        "installation folder.",
        "",
        "The launcher was rebuilt from installer/launcher_main.py with the",
        "Windows icon at assets/icons/app.ico. The production payload",
        "includes the application graphics under app/icons.",
        "",
    ]
    (PKG / "README_INSTALLER.txt").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n")
    log("docs: README_INSTALLER.txt added to the release payload")


def step_portable() -> Path:
    """Create and CRC-check a compact candidate ZIP without replacing output."""
    OUT.mkdir(parents=True, exist_ok=True)
    candidate = OUT / (
        f"{APP_NAME}-{APP_VERSION}-portable.candidate-{os.getpid()}.zip")
    candidate_sha = candidate.with_name(candidate.name + ".sha256")
    temporary = candidate.with_name(candidate.name + ".tmp")
    temporary_sha = candidate_sha.with_name(candidate_sha.name + ".tmp")
    files = sorted(
        (p for p in PKG.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(PKG).as_posix().casefold(),
    )
    expected = [
        (Path(ZIP_ROOT) / p.relative_to(PKG)).as_posix()
        for p in files
    ]
    temporary.unlink(missing_ok=True)
    candidate.unlink(missing_ok=True)
    candidate_sha.unlink(missing_ok=True)
    temporary_sha.unlink(missing_ok=True)
    try:
        log(f"zipping {len(files)} portable payload files (DEFLATE level 9)...")
        with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED,
                compresslevel=9) as archive:
            for path in files:
                arcname = (Path(ZIP_ROOT) / path.relative_to(PKG)).as_posix()
                archive.write(path, arcname)
        with zipfile.ZipFile(temporary, "r") as archive:
            if archive.namelist() != expected:
                raise RuntimeError("portable ZIP entry list does not match the payload")
            corrupt = archive.testzip()
            if corrupt is not None:
                raise RuntimeError(f"portable ZIP CRC failure at {corrupt}")
        os.replace(temporary, candidate)
        digest = hashlib.sha256()
        with candidate.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        with temporary_sha.open("w", encoding="ascii", newline="\n") as sidecar:
            sidecar.write(
                f"{digest.hexdigest()}  {APP_NAME}-{APP_VERSION}-portable.zip\n")
            sidecar.flush()
            os.fsync(sidecar.fileno())
        os.replace(temporary_sha, candidate_sha)
    except Exception:
        temporary.unlink(missing_ok=True)
        candidate.unlink(missing_ok=True)
        candidate_sha.unlink(missing_ok=True)
        temporary_sha.unlink(missing_ok=True)
        raise
    log(f"portable candidate: {candidate.stat().st_size / 1e6:.1f} MB")
    return candidate


RELEASE_DIR = SRC / "version" / f"{APP_NAME}_v{APP_VERSION}"
RELEASE_NOTES_SRC = SRC / "docs" / "RELEASE_NOTES.md"


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def step_release(zip_path: Path, sha_path: Path, setup_path: Path | None) -> Path:
    """Copy the published release set into <checkout>\\version\\<release>.

    Each file lands as <name>.tmp and is renamed only once all are copied, so a
    half-copied release never appears. The copied ZIP is hashed again and
    compared with its sidecar."""
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    sources = [zip_path, sha_path]
    if setup_path is not None:
        sources.append(setup_path)
    sources += [PKG_FINAL / "README_INSTALLER.txt",
                PKG_FINAL / "USER_GUIDE.md",
                PKG_FINAL / "THIRD_PARTY_NOTICES.md"]
    if RELEASE_NOTES_SRC.is_file():
        sources.append(RELEASE_NOTES_SRC)
    staged: list[tuple[Path, Path]] = []
    for source in sources:
        if not source.is_file():
            raise RuntimeError(f"release file is missing: {source}")
        target = RELEASE_DIR / source.name
        temporary = target.with_name(target.name + ".tmp")
        temporary.unlink(missing_ok=True)
        shutil.copy2(source, temporary)
        staged.append((temporary, target))
    for temporary, target in staged:
        os.replace(temporary, target)
    expected = sha_path.read_text(encoding="ascii").split()[0]
    actual = _sha256_of(RELEASE_DIR / zip_path.name)
    if actual != expected:
        raise RuntimeError(
            f"copied ZIP hash {actual} does not match the sidecar {expected}")
    log(f"release: {RELEASE_DIR}")
    return RELEASE_DIR


def promote_package(staged: Path) -> Path | None:
    """Atomically swap in a complete package while retaining a rollback dir."""
    CACHE.mkdir(parents=True, exist_ok=True)
    backup = CACHE / f"_pkg_rollback-{os.getpid()}"
    if backup.exists():
        raise RuntimeError(f"package rollback path already exists: {backup}")
    had_previous = PKG_FINAL.exists()
    if had_previous:
        os.replace(PKG_FINAL, backup)
    try:
        os.replace(staged, PKG_FINAL)
    except Exception:
        if had_previous and backup.exists():
            os.replace(backup, PKG_FINAL)
        raise
    return backup if had_previous else None


def rollback_package(backup: Path | None) -> None:
    if PKG_FINAL.exists():
        shutil.rmtree(PKG_FINAL)
    if backup is not None and backup.exists():
        os.replace(backup, PKG_FINAL)


def _pid_alive(pid: int) -> bool:
    """True when a process with this id exists (Windows)."""
    if sys.platform != "win32":
        return False
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return ctypes.get_last_error() == 5    # ERROR_ACCESS_DENIED: it exists


def prune_stale_rollbacks(cache: Path) -> list[Path]:
    """Remove package rollbacks left by builds that were killed before they
    finished. A finished build removes its own rollback; a killed one cannot."""
    removed: list[Path] = []
    for old in cache.glob("_pkg_rollback-*"):
        try:
            pid = int(old.name.rsplit("-", 1)[1])
        except ValueError:
            continue
        if pid == os.getpid() or _pid_alive(pid):
            continue
        shutil.rmtree(old, ignore_errors=True)
        removed.append(old)
    return removed


def step_inno(iscc_path: Path) -> Path:
    """Generate the Inno script and compile a candidate setup executable."""
    total_mb = 0
    for root, _dirs, files in os.walk(PKG):
        for name in files:
            total_mb += (Path(root) / name).stat().st_size
    total_mb //= (1024 * 1024)
    iss = HERE / "cleanct.iss"
    iss_tpl = f"""; cleanCT {APP_VERSION} - Inno Setup project
; Generated by installer/build_installer.py. Rebuild with:
;   ISCC.exe installer\\cleanct.iss
#define MyAppName "{APP_NAME}"
#define MyAppVersion "{APP_VERSION}"
#define MyAppExeName "cleanCT.exe"

[Setup]
AppName="{APP_NAME}"
AppId=8E4F2C1A-77B3-4A62-9D5E-CLEANCT1000
AppVersion={APP_VERSION}
DefaultDirName=@AUTOPF@\\{APP_NAME}
DefaultGroupName={APP_NAME}
UninstallDisplayIcon=@APP@\\cleanCT.exe
OutputDir=out
OutputBaseFilename={APP_NAME}-{APP_VERSION}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
MinVersion=10.0
; payload is ~{total_mb} MB uncompressed; lzma2/max compresses for distribution

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional icons:"

[Files]
Source: "_pkg\\*"; DestDir: "@APP@"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "@GROUP@\\{APP_NAME}"; Filename: "@APP@\\cleanCT.exe"
Name: "@AUTODESKTOP@\\{APP_NAME}"; Filename: "@APP@\\cleanCT.exe"; \
    Tasks: desktopicon

; start as the original user: an elevated cleanCT cannot traverse its junctions (WinError 448)
[Run]
Filename: "@APP@\\cleanCT.exe"; Description: "Launch {APP_NAME}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
; runtime logs/state live in %LOCALAPPDATA%\\cleanCT (left on purpose)
Type: filesandordirs; Name: "@APP@\\logs"
"""
    iss_txt = (iss_tpl
               .replace("@AUTOPF@", "{autopf}")
               .replace("@APP@", "{app}")
               .replace("@GROUP@", "{group}")
               .replace("@AUTODESKTOP@", "{autodesktop}"))
    iss.write_text(iss_txt, encoding="utf-8", newline="\n")
    log(f"inno: wrote cleanct.iss (payload {total_mb} MB)")

    OUT.mkdir(parents=True, exist_ok=True)
    candidate = OUT / (
        f"{APP_NAME}-{APP_VERSION}-setup-candidate-{os.getpid()}.exe")
    candidate.unlink(missing_ok=True)
    command = [
        str(iscc_path), "/Q", f"/O{OUT}", f"/F{candidate.stem}", str(iss),
    ]
    log(f"compiling classic setup with {iscc_path}")
    result = subprocess.run(command, cwd=str(HERE), capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(result.stdout[-5000:])
        print(result.stderr[-5000:])
        candidate.unlink(missing_ok=True)
        raise RuntimeError(f"Inno Setup compilation failed with exit code {result.returncode}")
    if not candidate.is_file() or candidate.stat().st_size < 1_000_000:
        candidate.unlink(missing_ok=True)
        raise RuntimeError("Inno Setup did not produce a complete setup executable")
    with candidate.open("rb") as setup_file:
        if setup_file.read(2) != b"MZ":
            candidate.unlink(missing_ok=True)
            raise RuntimeError("compiled setup executable does not have a valid PE header")
    log(f"classic setup candidate: {candidate.stat().st_size / 1e6:.1f} MB")
    return candidate


def get_pyinstaller_version(python_exe: Path) -> str:
    if not python_exe.is_file():
        raise RuntimeError(f"PyInstaller Python interpreter not found: {python_exe}")
    result = subprocess.run(
        [str(python_exe), "-m", "PyInstaller", "--version"],
        cwd=str(HERE), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"PyInstaller is not available through {python_exe}: "
            f"{result.stderr.strip()}")
    version = result.stdout.strip()
    if not version:
        raise RuntimeError("PyInstaller returned an empty version string")
    return version


def resolve_iscc(explicit: Path | None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    located = shutil.which("ISCC.exe") or shutil.which("iscc")
    if located:
        candidates.append(Path(located))
    candidates.extend([
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ])
    # Bounded per-user discovery: classic installs and IDE-bundled copies
    # (e.g. an editor shipping the Inno Setup CLI inside node_modules).
    local_programs = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"
    if local_programs.is_dir():
        for pattern in ("Inno Setup*/ISCC.exe",
                        "*/resources/app/node_modules/innosetup/bin/ISCC.exe"):
            try:
                candidates.extend(sorted(local_programs.glob(pattern)))
            except OSError:
                pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def get_iscc_version(iscc_path: Path) -> str:
    result = subprocess.run(
        [str(iscc_path), "/?"], cwd=str(HERE),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    output = result.stdout + "\n" + result.stderr
    match = re.search(
        r"Inno Setup\s+([0-9]+(?:\.[0-9]+)*)\s+Command-Line Compiler",
        output, flags=re.IGNORECASE,
    )
    if match:
        return f"Inno Setup {match.group(1)}"
    return "Inno Setup 6 (ISCC.exe)"

def step_launcher_smoke() -> None:
    """Exercise the freshly built launcher against the staged runtime payload."""
    launcher = PKG / "cleanCT.exe"
    if not launcher.is_file():
        raise RuntimeError(f"rebuilt launcher is missing from package: {launcher}")
    smoke_data = CACHE / f"_launcher_smoke-{os.getpid()}"
    smoke_data.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CLEANCT_DATA"] = str(smoke_data)
    env["LOCALAPPDATA"] = str(smoke_data)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["CLEANCT_OUTPUT_ROOT"] = str(smoke_data / "pipeline_output")
    try:
        result = subprocess.run(
            [str(launcher), "--selfcheck"], cwd=str(PKG), env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("rebuilt launcher self-check timed out after 180 seconds") from exc
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        log_file = smoke_data / "cleanCT" / "logs" / "cleanCT.log"
        if log_file.is_file():
            print(log_file.read_text(encoding="utf-8", errors="replace")[-5000:])
        raise RuntimeError(
            f"rebuilt launcher self-check failed with exit code {result.returncode}")
    shutil.rmtree(smoke_data, ignore_errors=True)
    removed = 0
    for cache_dir in list(PKG.rglob("__pycache__")):
        shutil.rmtree(cache_dir, ignore_errors=True)
        removed += 1
    for pattern in ("*.pyc", "*.pyo"):
        for bytecode in PKG.rglob(pattern):
            bytecode.unlink(missing_ok=True)
            removed += 1
    if any(PKG.rglob("*.pyc")) or any(PKG.rglob("*.pyo")):
        raise RuntimeError("Python bytecode remained in the production payload")
    log(f"removed {removed} Python bytecode/cache artifacts after launcher smoke-check")
    log("rebuilt launcher standalone --selfcheck: PASS")

def step_regressions() -> None:
    runner = SRC / "tests" / "run_cleanct_regressions.ps1"
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not runner.is_file():
        raise RuntimeError(f"required regression runner is missing: {runner}")
    if not powershell:
        raise RuntimeError("PowerShell is required to run the cleanCT regression gate")

    log("running focused regression suite before packaging")
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(runner)],
        cwd=str(SRC), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.stdout:
        print_captured(result.stdout, sys.stdout)
    if result.stderr:
        print_captured(result.stderr, sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"focused regression suite failed with exit code {result.returncode}")
    log("focused regression suite: PASS")


def main() -> int:
    global PKG
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-zip", action="store_true",
                    help="assemble and validate _pkg without publishing the portable ZIP")
    ap.add_argument("--skip-inno", action="store_true",
                    help="skip the classic installer (validation builds only)")
    ap.add_argument("--skip-launcher", action="store_true",
                    help="reuse the existing launcher (validation builds only)")
    ap.add_argument("--pyinstaller-python", type=Path, default=Path(sys.executable),
                    help="Python interpreter with PyInstaller installed")
    ap.add_argument("--iscc", type=Path,
                    help="path to the Inno Setup command-line compiler")
    args = ap.parse_args()

    log(f"checkout root: {SRC}")
    if not (SRC / "main.py").is_file():
        log(f"FATAL: cleanCT checkout not found at {SRC} (main.py is missing)")
        return 2
    if not SRCDIR.is_dir() or not (SRCDIR / "core" / "paths.py").is_file():
        log(f"FATAL: application sources not found at {SRCDIR}")
        return 2
    if not ENGINE.is_dir():
        log(f"FATAL: engine not found at {ENGINE}")
        return 2
    if not ICON_ASSET_DIR.joinpath("app.ico").is_file():
        log(f"FATAL: required embedded Windows icon not found at {ICON_ASSET_DIR / 'app.ico'}")
        return 2
    pyinstaller_python = args.pyinstaller_python.resolve()
    try:
        pyinstaller_version = get_pyinstaller_version(pyinstaller_python)
    except Exception as exc:
        log(f"FATAL: {exc}")
        return 2
    iscc_path = resolve_iscc(args.iscc)
    if not args.skip_inno and iscc_path is None:
        log("FATAL: ISCC.exe is required for a complete release. Pass --iscc PATH.")
        return 2
    inno_version = get_iscc_version(iscc_path) if iscc_path else "Not compiled"
    log(f"toolchain: PyInstaller {pyinstaller_version}; {inno_version}")

    for gone in prune_stale_rollbacks(CACHE):
        log(f"removed a package rollback left by an earlier build: {gone.name}")

    try:
        step_regressions()
    except Exception as exc:
        log(f"FATAL: {exc}")
        return 2

    CACHE.mkdir(parents=True, exist_ok=True)
    if PKG_STAGING.exists():
        log("removing an incomplete package staging directory")
        shutil.rmtree(PKG_STAGING)
    PKG = PKG_STAGING
    PKG.mkdir(parents=True)

    try:
        step_app()
        step_engine()
        step_runtime()
        if args.skip_launcher:
            previous_launcher = PKG_FINAL / "cleanCT.exe"
            if not previous_launcher.is_file():
                raise RuntimeError("--skip-launcher requested but no existing launcher is available")
            shutil.copy2(previous_launcher, PKG / "cleanCT.exe")
            log("launcher: reused existing _pkg/cleanCT.exe")
        else:
            step_launcher(pyinstaller_python, pyinstaller_version)
        step_docs()
        step_installer_readme(pyinstaller_version, inno_version)
    except Exception as exc:
        shutil.rmtree(PKG_STAGING, ignore_errors=True)
        log(f"FATAL: package assembly failed: {exc}")
        return 2

    candidate_zip = None
    candidate_sha = None
    setup_candidate = None
    package_backup = None
    package_promoted = False
    final_zip = OUT / f"{APP_NAME}-{APP_VERSION}-portable.zip"
    final_sha = final_zip.with_name(final_zip.name + ".sha256")
    final_setup = OUT / f"{APP_NAME}-{APP_VERSION}-setup.exe"
    final_readme = HERE / "README_INSTALLER.txt"
    zip_backup = OUT / f".{final_zip.name}.rollback-{os.getpid()}"
    sha_backup = OUT / f".{final_sha.name}.rollback-{os.getpid()}"
    setup_backup = OUT / f".{final_setup.name}.rollback-{os.getpid()}"
    readme_backup = HERE / f".{final_readme.name}.rollback-{os.getpid()}"
    readme_candidate = HERE / f".{final_readme.name}.candidate-{os.getpid()}"
    old_zip_backed_up = old_sha_backed_up = False
    old_setup_backed_up = old_readme_backed_up = False
    new_zip_published = new_sha_published = False
    new_setup_published = new_readme_published = False

    try:
        OUT.mkdir(parents=True, exist_ok=True)
        step_launcher_smoke()
        if not args.skip_zip:
            candidate_zip = step_portable()
            candidate_sha = candidate_zip.with_name(candidate_zip.name + ".sha256")
            if zip_backup.exists() or sha_backup.exists():
                raise RuntimeError("portable rollback path already exists")
            if final_zip.exists():
                os.replace(final_zip, zip_backup)
                old_zip_backed_up = True
            if final_sha.exists():
                os.replace(final_sha, sha_backup)
                old_sha_backed_up = True

        package_backup = promote_package(PKG)
        PKG = PKG_FINAL
        package_promoted = True

        if candidate_zip is not None:
            os.replace(candidate_zip, final_zip)
            new_zip_published = True
            os.replace(candidate_sha, final_sha)
            new_sha_published = True
            log(f"portable: published {final_zip.stat().st_size / 1e6:.1f} MB")
            log(f"portable SHA-256 sidecar: {final_sha}")

        if not args.skip_inno:
            setup_candidate = step_inno(iscc_path)
            if setup_backup.exists():
                raise RuntimeError("setup rollback path already exists")
            if final_setup.exists():
                os.replace(final_setup, setup_backup)
                old_setup_backed_up = True
            os.replace(setup_candidate, final_setup)
            setup_candidate = None
            new_setup_published = True
            log(f"classic installer: published {final_setup.stat().st_size / 1e6:.1f} MB")

        readme_candidate.unlink(missing_ok=True)
        shutil.copy2(PKG_FINAL / "README_INSTALLER.txt", readme_candidate)
        if readme_backup.exists():
            raise RuntimeError("installer README rollback path already exists")
        if final_readme.exists():
            os.replace(final_readme, readme_backup)
            old_readme_backed_up = True
        os.replace(readme_candidate, final_readme)
        new_readme_published = True

    except Exception as exc:
        log(f"FATAL: release publication failed: {exc}")
        if new_setup_published:
            final_setup.unlink(missing_ok=True)
        if old_setup_backed_up and setup_backup.exists():
            os.replace(setup_backup, final_setup)
        if setup_candidate is not None:
            setup_candidate.unlink(missing_ok=True)
        if new_readme_published:
            final_readme.unlink(missing_ok=True)
        if old_readme_backed_up and readme_backup.exists():
            os.replace(readme_backup, final_readme)
        readme_candidate.unlink(missing_ok=True)
        if new_zip_published:
            final_zip.unlink(missing_ok=True)
        if new_sha_published:
            final_sha.unlink(missing_ok=True)
        if old_zip_backed_up and zip_backup.exists():
            os.replace(zip_backup, final_zip)
        if old_sha_backed_up and sha_backup.exists():
            os.replace(sha_backup, final_sha)
        if candidate_zip is not None:
            candidate_zip.unlink(missing_ok=True)
        if candidate_sha is not None:
            candidate_sha.unlink(missing_ok=True)
        if package_promoted:
            rollback_package(package_backup)
            PKG = PKG_FINAL
        else:
            shutil.rmtree(PKG_STAGING, ignore_errors=True)
        return 2
    else:
        if package_backup is not None:
            shutil.rmtree(package_backup, ignore_errors=True)
        zip_backup.unlink(missing_ok=True)
        sha_backup.unlink(missing_ok=True)
        setup_backup.unlink(missing_ok=True)
        readme_backup.unlink(missing_ok=True)
        if not args.skip_zip:
            try:
                step_release(final_zip, final_sha,
                             None if args.skip_inno else final_setup)
            except Exception as exc:
                log(f"FATAL: release copy failed: {exc}")
                return 2

    size = sum(p.stat().st_size for p in PKG.rglob("*") if p.is_file())
    log(f"payload: {size / 1e6:.1f} MB in _pkg")
    log(f"release outputs: {final_zip if not args.skip_zip else 'portable ZIP skipped'}; "
        f"{final_setup if not args.skip_inno else 'classic setup skipped'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
