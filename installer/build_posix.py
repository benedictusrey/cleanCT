"""Linux and macOS packages: a portable tarball, and a macOS app in a DMG.

    python installer/build_posix.py linux-x86_64
    python installer/build_posix.py macos-arm64
    python installer/build_posix.py macos-x86_64

Each build fetches CPython 3.12 from python-build-standalone (the release tag is
pinned below; the archive is checked against that release's SHA256SUMS), installs
the pinned requirements, runs the regression gate, self-checks the launcher, then
packages. The Intel macOS build runs under Rosetta 2 on Apple silicon, so it needs
no Intel runner.
"""
from __future__ import annotations

import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

import build_installer as bi  # app, engine and docs lists shared with Windows

PBS_TAG = "20261110"          # python-build-standalone release (pinned)
PBS_PYTHON = "3.12.16"
PBS_URL = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}/"
TARGETS = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
}
MAC_MIN_VERSION = "12.0"

HERE = Path(__file__).resolve().parent
SRC = bi.SRC
CACHE = HERE / "_cache"
WORK = HERE / "_posix"
OUT = HERE / "out"


def log(msg: str) -> None:
    print(f"[posix] {msg}", flush=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _download(url: str, dest: Path) -> None:
    log(f"download {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=900) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


def fetch_runtime(target: str, work: Path) -> Path:
    """Extract the pinned CPython to ``work/runtime``; the archive must match SHA256SUMS."""
    name = f"cpython-{PBS_PYTHON}+{PBS_TAG}-{TARGETS[target]}-install_only.tar.gz"
    sums = CACHE / f"SHA256SUMS-{PBS_TAG}"
    if not sums.is_file():
        _download(PBS_URL + "SHA256SUMS", sums)
    expected = next((line.split()[0] for line in sums.read_text().splitlines()
                     if line.split()[-1] == name), None)
    if expected is None:
        raise SystemExit(f"{name} is not listed in SHA256SUMS of release {PBS_TAG}")
    archive = CACHE / name
    if not archive.is_file() or _sha256(archive) != expected:
        _download(PBS_URL + name, archive)
    if _sha256(archive) != expected:
        raise SystemExit(f"SHA-256 mismatch for {name}")
    runtime = work / "runtime"
    shutil.rmtree(runtime, ignore_errors=True)
    shutil.rmtree(work / "python", ignore_errors=True)
    with tarfile.open(archive) as tar:
        tar.extractall(work, filter="data")
    (work / "python").rename(runtime)
    return runtime


def run_py(target: str, runtime: Path, *args: str) -> None:
    """Run the bundled Python; the Intel build runs under Rosetta 2 on Apple silicon."""
    prefix = ["arch", "-x86_64"] if target == "macos-x86_64" else []
    subprocess.run([*prefix, str(runtime / "bin" / "python3"), *args], check=True)


def install_requirements(target: str, runtime: Path) -> None:
    run_py(target, runtime, "-m", "ensurepip", "--upgrade")
    reqs = ["requirements-core.txt"]
    if target.startswith("linux"):           # CUDA wheels exist for Linux only
        reqs.append("requirements-gpu.txt")
    for req in reqs:
        run_py(target, runtime, "-m", "pip", "install", "-r", str(HERE / req))


def gate(runtime: Path) -> None:
    gate_script = SRC / "tests" / "run_cleanct_regressions.ps1"
    subprocess.run(["pwsh", "-NoProfile", "-File", str(gate_script),
                    "-Python", str(runtime / "bin" / "python3")], check=True)


def copy_payload(res: Path, runtime: Path) -> None:
    """runtime/, app/, engine/, icons and the docs, laid out like the Windows package."""
    shutil.move(str(runtime), str(res / "runtime"))
    bi.PKG = res                  # bi.step_app and bi.step_engine write under PKG
    bi.step_app()
    bi.step_engine()
    shutil.copy2(SRC / "docs" / "USER_GUIDE.md", res / "USER_GUIDE.md")
    shutil.copy2(SRC / "LICENSE", res / "LICENSE.txt")
    (res / "THIRD_PARTY_NOTICES.md").write_text(bi.third_party_notices(), encoding="utf-8")


def write_launcher(path: Path, res_rel: str) -> None:
    path.write_text(
        "#!/bin/sh\n"
        "# cleanCT launcher: runs the bundled CPython 3.12 with the app.\n"
        f'here=$(cd "$(dirname "$0")/{res_rel}" && pwd)\n'
        'exec "$here/runtime/bin/python3" -X utf8 "$here/app/main.py" "$@"\n',
        encoding="utf-8", newline="\n")  # LF on every host: a CRLF shebang breaks the launcher
    path.chmod(0o755)


def selfcheck(launcher: Path) -> None:
    """The packaged app must start its health check before anything is packed."""
    subprocess.run([str(launcher), "--selfcheck"], check=True,
                   env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    log(f"self-check passed: {launcher}")


def build_linux(target: str, runtime: Path, name: str, pkg: Path) -> Path:
    root = pkg / name
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    copy_payload(root, runtime)
    write_launcher(root / "cleanCT", ".")
    shutil.copy2(HERE / "posix" / "install.sh", root / "install.sh")
    (root / "install.sh").chmod(0o755)
    selfcheck(root / "cleanCT")
    OUT.mkdir(parents=True, exist_ok=True)
    archive = OUT / f"{name}.tar.gz"
    archive.unlink(missing_ok=True)
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(root, arcname=name)
    return archive


def build_macos(target: str, runtime: Path, name: str, pkg: Path) -> Path:
    base = pkg / "mac"
    shutil.rmtree(base, ignore_errors=True)
    app = base / "cleanCT.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    res = contents / "Resources"
    res.mkdir()
    copy_payload(res, runtime)
    write_launcher(contents / "MacOS" / "cleanCT", "../Resources")
    iconset = base / "icon.iconset"
    iconset.mkdir()
    icon_png = SRC / "assets" / "icons" / "icon_1024x1024.png"
    for size in (16, 32, 128, 256, 512):          # iconset names: size, size@2x
        for scale in (1, 2):
            px = size * scale
            suffix = "" if scale == 1 else "@2x"
            subprocess.run(["sips", "-z", str(px), str(px), str(icon_png), "--out",
                            str(iconset / f"icon_{size}x{size}{suffix}.png")],
                           check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(res / "cleanCT.icns")],
                   check=True)
    plist = {
        "CFBundleName": "cleanCT", "CFBundleDisplayName": "cleanCT",
        "CFBundleIdentifier": "io.github.benedictusrey.cleanct",
        "CFBundleExecutable": "cleanCT", "CFBundleIconFile": "cleanCT",
        "CFBundlePackageType": "APPL", "CFBundleVersion": bi.APP_VERSION,
        "CFBundleShortVersionString": bi.APP_VERSION,
        "LSMinimumSystemVersion": MAC_MIN_VERSION, "NSHighResolutionCapable": True,
    }
    with open(contents / "Info.plist", "wb") as fh:
        plistlib.dump(plist, fh)
    selfcheck(contents / "MacOS" / "cleanCT")
    # ad-hoc signature: keeps the bundle intact; it does not replace notarization
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    dmg_root = base / "dmg"
    dmg_root.mkdir()
    shutil.copytree(app, dmg_root / "cleanCT.app", symlinks=True)
    os.symlink("/Applications", dmg_root / "Applications")
    OUT.mkdir(parents=True, exist_ok=True)
    dmg = OUT / f"{name}.dmg"
    dmg.unlink(missing_ok=True)
    subprocess.run(["hdiutil", "create", "-volname", f"cleanCT {bi.APP_VERSION}",
                    "-srcfolder", str(dmg_root), "-ov", "-format", "UDZO", str(dmg)],
                   check=True)
    return dmg


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in TARGETS:
        print(__doc__)
        return 2
    target = argv[0]
    name = f"{bi.APP_NAME}-{bi.APP_VERSION}-{target}"
    work = WORK / target
    work.mkdir(parents=True, exist_ok=True)
    runtime = fetch_runtime(target, work)
    install_requirements(target, runtime)
    gate(runtime)
    pkg = work / "pkg"
    if target.startswith("macos"):
        package = build_macos(target, runtime, name, pkg)
    else:
        package = build_linux(target, runtime, name, pkg)
    digest = _sha256(package)
    (package.parent / f"{package.name}.sha256").write_text(f"{digest}  {package.name}\n",
                                                          encoding="utf-8")
    log(f"wrote {package} sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
