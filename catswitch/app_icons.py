"""Windows taskbar icon helpers for CatSwitch."""

from __future__ import annotations

import logging
import os

import win32con
import win32gui

from catswitch.paths import get_app_icon_path

logger = logging.getLogger(__name__)


def resolve_app_window_handle(app_window=None) -> int | None:
    """Return the native HWND for the PyWebView window."""
    hwnd = None

    if app_window is not None:
        if hasattr(app_window, "gui") and hasattr(app_window.gui, "handle"):
            hwnd = app_window.gui.handle
        elif hasattr(app_window, "gui") and hasattr(app_window.gui, "main_window"):
            main_window = app_window.gui.main_window
            if hasattr(main_window, "Handle"):
                hwnd = int(main_window.Handle.ToInt64())

    if not hwnd:
        hwnd = win32gui.FindWindow(None, "CatSwitch")

    return hwnd or None


def load_app_icon_handle(size: int = 16) -> int:
    """Load a white CatSwitch icon handle at the requested size."""
    icon_path = get_app_icon_path()
    if size:
        return win32gui.LoadImage(
            0,
            icon_path,
            win32con.IMAGE_ICON,
            size,
            size,
            win32con.LR_LOADFROMFILE,
        )
    return win32gui.LoadImage(
        0,
        icon_path,
        win32con.IMAGE_ICON,
        0,
        0,
        win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE,
    )


def apply_app_window_icon(app_window=None) -> bool:
    """Apply the bundled white CatSwitch icon to the taskbar/window chrome."""
    icon_path = get_app_icon_path()
    if not os.path.isfile(icon_path):
        logger.warning("App icon not found: %s", icon_path)
        return False

    hwnd = resolve_app_window_handle(app_window)
    if hwnd:
        try:
            large_icon = load_app_icon_handle(32)
            small_icon = load_app_icon_handle(16)
            win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, large_icon)
            win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, small_icon)
        except Exception as exc:
            logger.error("Failed to set window icon via Win32: %s", exc, exc_info=True)
            return False

    if app_window is not None and hasattr(app_window, "gui") and hasattr(app_window.gui, "main_window"):
        try:
            from System.Drawing import Icon

            app_window.gui.main_window.Icon = Icon(icon_path)
        except Exception as exc:
            logger.debug("Could not set WinForms window icon: %s", exc)

    return bool(hwnd)


def hide_app_window(app_window=None) -> bool:
    hwnd = resolve_app_window_handle(app_window)
    if not hwnd:
        return False
    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
    return True


def show_app_window(app_window=None) -> bool:
    hwnd = resolve_app_window_handle(app_window)
    if not hwnd:
        return False
    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    return True
