"""System tray icon support for CatSwitch on Windows."""

from __future__ import annotations

import logging
import threading

import win32api
import win32con
import win32gui

from catswitch.app_icons import load_app_icon_handle

logger = logging.getLogger(__name__)

WM_TRAYICON = win32con.WM_USER + 42
TRAY_ICON_ID = 1
MENU_SHOW = 1001
MENU_QUIT = 1002


class TrayIcon:
    """Background message-window tray icon with activate + context menu."""

    def __init__(
        self,
        icon_path: str,
        tooltip: str = "CatSwitch",
        on_activate=None,
        on_show=None,
        on_quit=None,
    ):
        self.icon_path = icon_path
        self.tooltip = tooltip
        self.on_show = on_show or on_activate
        self.on_quit = on_quit
        self._hwnd = None
        self._thread = None
        self._visible = False
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run_message_loop,
            name="CatSwitchTray",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=5):
            logger.warning("Tray icon message loop did not start in time")

    def stop(self) -> None:
        if self._hwnd:
            try:
                self._notify(win32gui.NIM_DELETE)
            except Exception:
                pass
            try:
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        self._visible = False
        self._hwnd = None

    def show(self) -> None:
        self.start()
        if self._hwnd and not self._visible:
            self._notify(win32gui.NIM_ADD)
            self._visible = True

    def hide(self) -> None:
        if self._hwnd and self._visible:
            self._notify(win32gui.NIM_DELETE)
            self._visible = False

    def _notify(self, message: int) -> None:
        hicon = load_app_icon_handle(16)
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        nid = (self._hwnd, TRAY_ICON_ID, flags, WM_TRAYICON, hicon, self.tooltip)
        win32gui.Shell_NotifyIcon(message, nid)

    def _show_context_menu(self) -> None:
        menu = win32gui.CreatePopupMenu()
        try:
            win32gui.AppendMenu(menu, win32con.MF_STRING, MENU_SHOW, "Show app")
            win32gui.AppendMenu(menu, win32con.MF_STRING, MENU_QUIT, "Quit app")
            cursor_x, cursor_y = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(self._hwnd)
            win32gui.TrackPopupMenu(
                menu,
                win32con.TPM_LEFTALIGN | win32con.TPM_BOTTOMALIGN,
                cursor_x,
                cursor_y,
                0,
                self._hwnd,
                None,
            )
        finally:
            win32gui.DestroyMenu(menu)

    def _run_message_loop(self) -> None:
        try:
            wc = win32gui.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName = "CatSwitchTrayMessageWindow"
            wc.lpfnWndProc = self._wnd_proc
            class_atom = win32gui.RegisterClass(wc)
            self._hwnd = win32gui.CreateWindow(
                class_atom,
                "CatSwitchTray",
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                wc.hInstance,
                None,
            )
            self._ready.set()
            win32gui.PumpMessages()
        except Exception as exc:
            logger.error("Tray message loop failed: %s", exc, exc_info=True)
            self._ready.set()

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            if lparam == win32con.WM_RBUTTONUP:
                self._show_context_menu()
                return 0
            if lparam in (
                win32con.WM_LBUTTONUP,
                win32con.WM_LBUTTONDBLCLK,
            ):
                if self.on_show:
                    self.on_show()
                return 0
        if msg == win32con.WM_COMMAND:
            command_id = win32api.LOWORD(wparam)
            if command_id == MENU_SHOW and self.on_show:
                self.on_show()
            elif command_id == MENU_QUIT and self.on_quit:
                self.on_quit()
            return 0
        if msg == win32con.WM_DESTROY:
            if self._visible:
                try:
                    self._notify(win32gui.NIM_DELETE)
                except Exception:
                    pass
                self._visible = False
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
