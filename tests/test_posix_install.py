"""install.sh and the launcher it installs: the Linux and macOS packages.

The checks use a fake bundled runtime, so they run without PySide6. POSIX only:
Windows has no sh-based installer, so the checks are skipped there.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "installer"))

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail and not ok else ""),
          flush=True)
    if not ok:
        failures.append(name)


if os.name == "nt":
    print("SKIP install.sh checks on Windows (POSIX shell installer)", flush=True)
    print("RESULT: ALL PASS", flush=True)
    sys.exit(0)

import build_posix as bp  # noqa: E402  (writes the same launcher the packages ship)

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    package = tmp / "pkg" / "cleanCT-1.0.0-linux-x86_64"
    (package / "runtime" / "bin").mkdir(parents=True)
    (package / "app").mkdir()
    fake = package / "runtime" / "bin" / "python3"
    fake.write_text('#!/bin/sh\necho "fake-python $*"\n', encoding="utf-8")
    fake.chmod(0o755)
    (package / "app" / "main.py").write_text("print(1)\n", encoding="utf-8")
    bp.write_launcher(package / "cleanCT", ".")
    shutil.copy2(ROOT / "installer" / "posix" / "install.sh", package / "install.sh")
    home = tmp / "home dir"      # a space in the path exercises the menu entry quoting
    home.mkdir()
    env = dict(os.environ, HOME=str(home))
    env.pop("XDG_DATA_HOME", None)

    def run(cmd):
        return subprocess.run(cmd, env=env, capture_output=True, text=True)

    installed = run(["sh", str(package / "install.sh")])
    check("install.sh completes", installed.returncode == 0, installed.stderr)
    wrapper = home / ".local" / "bin" / "cleanct"
    check("cleanct is a wrapper, not a symlink", wrapper.is_file() and not wrapper.is_symlink())
    started = run([str(wrapper), "--selfcheck"])
    check("cleanct starts the bundled runtime",
          started.returncode == 0 and "fake-python" in started.stdout and "--selfcheck" in started.stdout,
          started.stdout + started.stderr)
    desktop = (home / ".local" / "share" / "applications" / "cleanct.desktop").read_text(encoding="utf-8")
    check("menu entry quotes the Exec path", 'Exec="' in desktop and str(home) in desktop)
    app_dir = home / ".local" / "share" / "cleanCT-app"
    again = run(["sh", str(app_dir / "install.sh")])
    check("running the installed copy is refused",
          again.returncode != 0 and (app_dir / "runtime" / "bin" / "python3").is_file(),
          again.stderr)
    # a trailing slash names the same folder: the installed copy must still refuse
    slashed = dict(env, XDG_DATA_HOME=str(home / ".local" / "share") + "/")
    again = subprocess.run(["sh", str(app_dir / "install.sh")], env=slashed,
                           capture_output=True, text=True)
    check("a trailing slash in XDG_DATA_HOME cannot delete the installed copy",
          again.returncode != 0 and (app_dir / "runtime" / "bin" / "python3").is_file(),
          again.stderr)

print("RESULT: ALL PASS" if not failures else f"RESULT: {len(failures)} failed", flush=True)
sys.exit(1 if failures else 0)
