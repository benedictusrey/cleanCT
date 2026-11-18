"""One cleanCT window per Windows session.

Every window reads and rewrites the same registry and settings files. Two
windows that register a scan at about the same time can each write back a
list that lacks the other's entry, so one scan silently disappears. A named
mutex keeps the second start from opening a window.
"""
from __future__ import annotations

import sys

ERROR_ALREADY_EXISTS = 183
DEFAULT_NAME = "Local\\cleanCT-main-window"

_handle = None   # held for the life of the process; releasing it frees the name


def acquire(name: str = DEFAULT_NAME) -> bool:
    """True when this process is the first window; False when one is open.

    If the mutex cannot be created at all, the window opens anyway: a broken
    check must never block the user.
    """
    global _handle
    if sys.platform != "win32":
        return True
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
