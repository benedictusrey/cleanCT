from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile


PROJECT = Path(os.environ["CLEANCT_APP_ROOT"]).resolve()
sys.path.insert(0, str(PROJECT))
from installer import build_installer


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    source = build_installer.ICON_ASSET_DIR
    if not source.is_dir():
        raise AssertionError(f"production icon source is missing: {source}")
    if not (source / "app.ico").is_file():
        raise AssertionError("launcher icon asset is missing")

    scratch = Path(os.environ["CLEANCT_TEST_TMP_DIR"])
    with tempfile.TemporaryDirectory(prefix="cleanct-installer-icons-", dir=scratch) as temp:
        build_installer.PKG = Path(temp) / "_pkg"
        build_installer.step_app()
        staged = build_installer.PKG / "app" / "icons"
        expected = {
            path.relative_to(source).as_posix()
            for path in source.rglob("*")
            if (path.is_file() and path.suffix.lower() not in {".pyc", ".pyo"}
                and path.name.lower() != "readme.md")
        }
        actual = {
            path.relative_to(staged).as_posix()
            for path in staged.rglob("*")
            if path.is_file() and path.suffix.lower() not in {".pyc", ".pyo"}
        }
        if actual != expected:
            raise AssertionError(
                f"installer icon inventory differs: missing={expected - actual}, "
                f"extra={actual - expected}")
        for relative in sorted(expected):
            original = source / relative
            packed = staged / relative
            if file_sha256(original) != file_sha256(packed):
                raise AssertionError(f"installer icon checksum differs: {relative}")
        size = sum((source / name).stat().st_size for name in expected)

        from PySide6.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication([])
        sys.path.insert(0, str(build_installer.PKG / "app"))
        from icon_utils import get_app_icon
        app_icon = get_app_icon(build_installer.PKG / "app")
        if app_icon.isNull():
            raise AssertionError("Qt could not load the staged cleanCT logo")
        if qt_app is None:
            raise AssertionError("Qt application could not be initialized")

    print(
        f"PASS installer stages all {len(expected)} production icon assets "
        f"byte-identically ({size:,} bytes)")
    print("PASS Qt loads the staged cleanCT application logo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
