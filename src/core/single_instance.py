"""One cleanCT window per user session.

Every window reads and rewrites the same registry and settings files. Two
windows that register a scan at about the same time can each write back a
list that lacks the other's entry, so one scan silently disappears. Windows
uses a named mutex; Linux and macOS use an exclusive lock on a file in the
user's state folder. The second start does not open a window.
"""
from __future__ import annotations

import os
import sys

ERROR_ALREADY_EXISTS = 183
DEFAULT_NAME = "Local\\cleanCT-main-window"

_handle = None   # held for the life of the process; releasing it frees the name


def _acquire_posix(name: str) -> bool:
    global _handle
    import fcntl
    from core import paths

    lock_name = "".join(ch if ch.isalnum() else "_" for ch in name) + ".lock"
    try:
        folder = paths.state_root()
        fh = open(os.path.join(folder, lock_name), "a+")
    except OSError:
        return True                   # a broken check must never block the user
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return False
    except OSError:
        fh.close()
        return True
    _handle = fh                      # the lock is released when the process exits
    return True


def acquire(name: str = DEFAULT_NAME) -> bool:
    """True when this process is the first window; False when one is open.

    If the lock cannot be created at all, the window opens anyway: a broken
    check must never block the user.
    """
    global _handle
    if sys.platform != "win32":
        return _acquire_posix(name)
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _handle = handle
    return True
