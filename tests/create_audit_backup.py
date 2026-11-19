"""Create a scoped, hashed source-and-release snapshot in 0BACKUP."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
ENGINE = PROJECT.parent / "metal_remover"
BACKUP_TAG = "20261118_audit_fix_plan_r15"
BACKUP_DIR = PROJECT / "0BACKUP" / f"audit_{BACKUP_TAG}"
ARCHIVE = BACKUP_DIR / f"cleanCT_full_system_audit_{BACKUP_TAG}.zip"
SIDE_CAR = Path(str(ARCHIVE) + ".sha256")
MANIFEST_OUT = BACKUP_DIR / "BACKUP_MANIFEST.json"
TEXT_SUFFIXES = {".py", ".ps1", ".md", ".log", ".txt", ".json"}
UNCOMPRESSED_SUFFIXES = {".zip", ".exe", ".png", ".jpg", ".jpeg", ".ico"}
EXCLUDED_BUILD_DIRS = {
    "__pycache__", "venv_notorch", "cache", "cleanCT", "custom",
    "native_shots", "bounds_shots", "_export_stream_work",
    "version",   # release folders hold 500+ MB of binaries; not re-zipped per round
}


def is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_tree(base: Path, archive_prefix: str, *,
                 suffixes: set[str] | None = None,
                 excluded_dirs: set[str] | None = None) -> dict[str, Path]:
    if not base.is_dir() or is_link(base):
        return {}
    picked: dict[str, Path] = {}
    omitted = excluded_dirs or {"__pycache__"}
    for current, dirs, files in os.walk(base, followlinks=False):
        here = Path(current)
        dirs[:] = [name for name in dirs
                   if name not in omitted and not is_link(here / name)]
        for name in files:
            path = here / name
            if is_link(path) or path.suffix.lower() in {".pyc", ".pyo"}:
                continue
            if suffixes is not None and path.suffix.lower() not in suffixes:
                continue
            rel = path.relative_to(base).as_posix()
            arcname = f"{archive_prefix.rstrip('/')}/{rel}"
            picked[arcname] = path
    return picked


def collect_files() -> dict[str, Path]:
    files: dict[str, Path] = {}

    def add(path: Path, arcname: str) -> None:
        if path.is_file() and not is_link(path):
            files[arcname] = path

    project_files = (
        ".gitignore", "docs/AUDIT.md", "README.md", "docs/USER_GUIDE.md",
        "main.py",
    )
    for name in project_files:
        add(PROJECT / name, name)

    for folder in ("assets", "src"):
        files.update(collect_tree(PROJECT / folder, folder))

    files.update(collect_tree(
        PROJECT / "tests", "tests", suffixes=TEXT_SUFFIXES,
        excluded_dirs=EXCLUDED_BUILD_DIRS | {"venv_notorch", "screenshots"}))

    for name in ("build_installer.py", "cleanct.iss", "launcher_main.py",
                 "setup_env.ps1"):
        add(PROJECT / "installer" / name, f"installer/{name}")
    files.update(collect_tree(
        PROJECT / "installer" / "out", "installer/out",
        suffixes={".zip", ".sha256", ".exe"}))

    add(PROJECT / "dist" / "cleanCT.exe", "dist/cleanCT.exe")

    engine_files = ("README.md", "air_crop.py", "gpu_backend.py",
                    "requirements-gpu.txt", "requirements.txt",
                    "roi_delivery.py", "tomograph.py", "volume_io.py",
                    "wood_track.py")
    for name in engine_files:
        add(ENGINE / name, f"metal_remover/{name}")
    for folder in ("tests",):
        files.update(collect_tree(ENGINE / folder, f"metal_remover/{folder}",
                                  suffixes=TEXT_SUFFIXES))

    backup_docs = PROJECT / "0BACKUP"
    for name in (
        "README.md", "DETECTION_ENGINE_NOTES.md", "audit_0e_detection_round.md",
        "audit_0h_resolution_envelope.md", "audit_0i_pillow_preprocess.md",
        "audit_0j_organization.md", "audit_0k_nometal.md",
        "audit_0m_export_speed.md", "audit_0n_process_speed.md",
        "audit_0o_process_export.md", "audit_0p_stale_line_guard.md",
        "audit_0q_installer.md",
    ):
        add(backup_docs / name, f"0BACKUP/{name}")

    if len(files) != len(set(files)):
        raise RuntimeError("duplicate archive paths found")
    return dict(sorted(files.items()))


def main() -> int:
    if BACKUP_DIR.exists():
        raise FileExistsError(f"refusing to overwrite an existing backup: {BACKUP_DIR}")
    BACKUP_DIR.mkdir(parents=True)
    temp_archive = ARCHIVE.with_suffix(ARCHIVE.suffix + ".tmp")
    if temp_archive.exists():
        raise FileExistsError(f"temporary archive already exists: {temp_archive}")

    files = collect_files()
    if not files:
        raise RuntimeError("no backup inputs were found")
    records = [{"path": name, "size": path.stat().st_size,
                "sha256": file_hash(path)} for name, path in files.items()]
    readme = (
        "cleanCT full system audit snapshot\n"
        "Created: 2026-09-24 UTC\n\n"
        "Extract this archive beside the metal_remover folder to restore the "
        "captured project sources and release package. The portable installer "
        "ZIP and its SHA-256 are included. BACKUP_MANIFEST.json records a "
        "SHA-256 for each captured file.\n\n"
        "Excluded: original scan data, processed outputs, user exports, runtime "
        "logs, Python environments, generated caches/intermediates, and the "
        "external custom-sample junction targets. Earlier 0BACKUP snapshots "
        "remain in their original folders.\n"
    ).encode("utf-8")
    readme_record = {"path": "BACKUP_README.txt", "size": len(readme),
                     "sha256": hashlib.sha256(readme).hexdigest()}
    manifest = {
        "format": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(PROJECT),
        "sibling_engine_root": str(ENGINE),
        "file_count": len(records) + 1,
        "files": records + [readme_record],
        "excluded": [
            "specimen input data and external junction targets",
            "processed pipeline output and user exports",
            "runtime logs, virtual environments, caches, and intermediates",
        ],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False)
                      + "\n").encode("utf-8")

    with zipfile.ZipFile(temp_archive, "w", allowZip64=True) as archive:
        for arcname, path in files.items():
            method = (zipfile.ZIP_STORED
                      if path.suffix.lower() in UNCOMPRESSED_SUFFIXES
                      else zipfile.ZIP_DEFLATED)
            archive.write(path, arcname, compress_type=method,
                          compresslevel=6 if method == zipfile.ZIP_DEFLATED else None)
        archive.writestr("BACKUP_README.txt", readme,
                         compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        archive.writestr("BACKUP_MANIFEST.json", manifest_bytes,
                         compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)

    with zipfile.ZipFile(temp_archive, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"backup CRC check failed at {bad}")
        for record in manifest["files"]:
            digest = hashlib.sha256()
            with archive.open(record["path"]) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != record["sha256"]:
                raise RuntimeError(f"backup content hash mismatch: {record['path']}")

    os.replace(temp_archive, ARCHIVE)
    MANIFEST_OUT.write_bytes(manifest_bytes)
    archive_hash = file_hash(ARCHIVE)
    SIDE_CAR.write_text(f"{archive_hash}  {ARCHIVE.name}\n", encoding="ascii")
    print(f"BACKUP={ARCHIVE}")
    print(f"FILES={manifest['file_count']} ZIP_BYTES={ARCHIVE.stat().st_size}")
    print(f"ZIP_SHA256={archive_hash}")
    print("CRC_AND_PER_FILE_HASHES=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
