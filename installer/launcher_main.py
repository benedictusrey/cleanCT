#!/usr/bin/env python
"""cleanCT windowless launcher (packaged as cleanCT.exe).

Frozen with PyInstaller (onefile, windowed) by installer/build_installer.py.
Responsibilities, in order:

  1. Locate the payload next to the executable:
         <exe_dir>/app/main.py        GUI sources
         <exe_dir>/engine/tomograph.py frozen pipeline
         <exe_dir>/runtime/python.exe embedded interpreter
  2. Point the app at the frozen engine via CLEANCT_ENGINE (core/paths.py
     resolves it; user state still lands in %LOCALAPPDATA%/cleanCT).
  3. Spawn runtime\\python.exe -X utf8 app\\main.py with stdout/stderr
     captured into the rotating runtime log (logs/cleanCT.log, 5 MB),
     living under %LOCALAPPDATA%/cleanCT/logs (writable regardless of
     install location); falls back to <exe_dir>/logs.
  4. Show a Windows message box instead of failing silently if the payload
     is damaged (e.g. an antivirus quarantined files).

This launcher contains no application logic: every behaviour is owned by
main.py and the engine, exactly as in development.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


def payload_dirs() -> tuple[str, str, str] | None:
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    app = os.path.join(exe_dir, "app")
    engine = os.path.join(exe_dir, "engine")
    py = os.path.join(exe_dir, "runtime", "python.exe")
    if (os.path.isfile(os.path.join(app, "main.py"))
            and os.path.isfile(os.path.join(engine, "tomograph.py"))
            and os.path.isfile(py)):
        return app, engine, py
    return None


def _rotate(log_path: str, max_bytes: int = 5 * 1024 * 1024) -> None:
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > max_bytes:
            prev = log_path + ".1"
            if os.path.exists(prev):
                os.remove(prev)
            os.replace(log_path, prev)
    except OSError:
        pass


def open_log(app_dir: str):
    """Open the rotating log. Returns (file or None, log path)."""
    base = os.environ.get("LOCALAPPDATA") or app_dir
    log_dir = os.path.join(base, "cleanCT", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = os.path.join(app_dir, "logs")
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            log_dir = app_dir
    log_path = os.path.join(log_dir, "cleanCT.log")
    _rotate(log_path)
    try:
        return open(log_path, "a", buffering=1, encoding="utf-8"), log_path
    except OSError:
        return None, log_path


def fail_box(msg: str) -> None:
    print(msg, file=sys.stderr)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, msg, "cleanCT - cannot start", 0x10)  # MB_ICONERROR
    except Exception:
        pass


def is_elevated() -> bool:
    """True when this process runs with administrator rights (UAC elevated)."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def main() -> int:
    found = payload_dirs()
    if found is None:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        fail_box(
            "cleanCT payload is incomplete.\n\n"
            "Expected next to the executable:\n"
            "    app\\main.py\n"
            "    engine\\tomograph.py\n"
            "    runtime\\python.exe\n\n"
            "Reinstall cleanCT, or if you use the portable edition make\n"
            "sure the folder was extracted completely (an antivirus may\n"
            "have removed files).\n\n"
            f"Looked in: {exe_dir}")
        return 1

    app_dir, engine_dir, py_exe = found
    os.environ["CLEANCT_ENGINE"] = engine_dir
    state_root = os.environ.get("CLEANCT_DATA")
    if not state_root:
        local_app_data = os.environ.get("LOCALAPPDATA")
        state_root = (os.path.join(local_app_data, "cleanCT")
                      if local_app_data else
                      os.path.join(os.path.expanduser("~"), "AppData",
                                   "Local", "cleanCT"))
    os.environ.setdefault("CLEANCT_DATA", state_root)
    # Processing results must stay writable in Program Files installs and
    # portable builds. Keep the developer pipeline path unless the launcher
    # supplies this per-user location (or the caller explicitly overrides it).
    os.environ.setdefault(
        "CLEANCT_OUTPUT_ROOT",
        os.path.join(state_root, "pipeline_output"),
    )

    args = [py_exe, "-X", "utf8", os.path.join(app_dir, "main.py")]
    # pass through the headless health check and any app arguments
    if len(sys.argv) > 1:
        args += list(sys.argv[1:])

    if is_elevated():
        # scans are linked with junctions that an elevated process cannot traverse
        fail_box("cleanCT is running as administrator. Scans linked in a normal "
                 "session cannot be opened in this mode. Close cleanCT and start "
                 "it normally from the Start menu.")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log, log_path = open_log(app_dir)
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            args, cwd=app_dir,
            stdout=log if log is not None else subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=os.environ,
        )
        code = proc.wait()
        # a non-zero exit within seconds of starting is a start-up failure:
        # say where the details are (the windowless launcher shows nothing)
        if code != 0 and time.monotonic() - started < 20:
            fail_box(f"cleanCT closed unexpectedly. Details are in:\n{log_path}")
        return code
    except KeyboardInterrupt:
        return 0
    finally:
        if log is not None:
            log.close()


if __name__ == "__main__":
    sys.exit(main())
