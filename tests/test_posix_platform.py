"""Platform branches: per-user data folder, folder links, reveal in file manager.

The Windows branches ship today; the Linux and macOS branches are used by the
POSIX packages. The folder-link check runs on every platform.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "src"))

from core import custom_series as csx  # noqa: E402
from core import paths  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""),
          flush=True)
    if not ok:
        failures.append(name)


check("macOS keeps user data in Application Support",
      Path(paths._user_data_base("darwin")).parts[-2:] == ("Library", "Application Support"))
check("Linux keeps user data in the XDG data folder",
      Path(paths._user_data_base("linux")).name == "share")
check("Explorer selects the file on Windows",
      paths.reveal_command("C:/scan/y.dcm", "win32") == ["explorer", "/select,C:/scan/y.dcm"])
check("Finder reveals the file on macOS",
      paths.reveal_command("/scan/y.dcm", "darwin") == ["open", "-R", "/scan/y.dcm"])
check("Linux opens the containing folder",
      paths.reveal_command("/scan/y.dcm", "linux") == ["xdg-open", "/scan"])

with tempfile.TemporaryDirectory() as tmp:
    target = Path(tmp) / "scan"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    link = Path(tmp) / "link"
    csx._mklink_junction(link, target)
    check("a folder link resolves to its target", link.is_dir() and (link / "keep.txt").exists())
    csx._rmdir_junction(link)
    check("removing the link keeps the target contents",
          not os.path.lexists(link) and (target / "keep.txt").exists())

print("RESULT: ALL PASS" if not failures else f"RESULT: {len(failures)} failed", flush=True)
sys.exit(1 if failures else 0)
