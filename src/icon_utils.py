"""Windows native taskbar and window icon management for cleanCT."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from PySide6.QtGui import QIcon

APP_ID = "cleanCT.WoodCT.MetalRemover.Native.1.0"
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
GCLP_HICON = -14
GCLP_HICONSM = -34
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010


def set_windows_app_id() -> None:
    """Set Windows AppUserModelID so taskbar groups under cleanCT and uses its icon."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


def icons_dir(root_dir: Path) -> Path | None:
    """First existing icon-pack directory for the running layout:
    ``<root>/icons`` (packaged/dev flat) or ``<root>/assets/icons``
    (structured checkout)."""
    for candidate in (root_dir / "icons", root_dir / "assets" / "icons"):
        if candidate.is_dir():
            return candidate
    return None


def get_app_icon(root_dir: Path | None = None) -> QIcon:
    """Build a multi-resolution QIcon from all HD PNG assets and app.ico."""
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent

    icon = QIcon()
    icons = icons_dir(root_dir) or root_dir / "assets"

    # Add all explicit pixel mipmaps so Qt never downscales naively
    for sz in [16, 24, 32, 40, 48, 64, 96, 128, 256, 512, 1024]:
        p = icons / f"icon_{sz}x{sz}.png"
        if p.exists():
            icon.addFile(str(p))

    # Also add app_icon_256.png if available
    p_256 = icons / "icon_256x256.png"
    if not p_256.exists():
        p_256 = root_dir / "assets" / "app_icon_256.png"
    if p_256.exists():
        icon.addFile(str(p_256))

    return icon


def apply_native_window_icon(hwnd: int, root_dir: Path | None = None) -> None:
    """Explicitly inject native Win32 HICON handles via WM_SETICON and SetClassLongPtrW.

    Forces Windows Desktop Window Manager (DWM) and Explorer taskbar to render
    the crisp native icon directly from the .ico resource.
    """
    if sys.platform != "win32" or not hwnd:
        return

    if root_dir is None:
        root_dir = Path(__file__).resolve().parent

    ico_path = (icons_dir(root_dir) or root_dir) / "app.ico"
    if not ico_path.exists():
        ico_path = root_dir / "assets" / "app.ico"
    if not ico_path.exists():
        return

    try:
        user32 = ctypes.windll.user32
        path_str = str(ico_path)

        # Load standard taskbar size (48x48 on 150%, 32x32 on 100%)
        hicon_big = user32.LoadImageW(None, path_str, IMAGE_ICON, 48, 48, LR_LOADFROMFILE)
        hicon_small = user32.LoadImageW(None, path_str, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)

        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
            if hasattr(user32, "SetClassLongPtrW"):
                user32.SetClassLongPtrW(hwnd, GCLP_HICON, hicon_big)
            elif hasattr(user32, "SetClassLongW"):
                user32.SetClassLongW(hwnd, GCLP_HICON, hicon_big)

        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            if hasattr(user32, "SetClassLongPtrW"):
                user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, hicon_small)
            elif hasattr(user32, "SetClassLongW"):
                user32.SetClassLongW(hwnd, GCLP_HICONSM, hicon_small)

        # Windows Shell PropertyStore: guarantees Windows Taskbar links the window
        # directly to cleanCT's native icon resource even before pinning or grouping
        try:
            from win32com.propsys import propsys, pscon
            store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
            store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID))
            store.SetValue(pscon.PKEY_AppUserModel_RelaunchIconResource, propsys.PROPVARIANTType(f"{path_str},0"))
            store.SetValue(pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, propsys.PROPVARIANTType("cleanCT"))
            store.Commit()
        except Exception:
            pass
    except Exception:
        pass
