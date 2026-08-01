"""Windows logon autostart via HKCU Run key."""

from __future__ import annotations

import logging
import os
import sys
import winreg

logger = logging.getLogger("catswitch.autostart")

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "CatSwitch"


def autostart_command() -> str:
    """Command line written to the Run key (always includes --minimized)."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return f'"{exe}" --minimized'

    python = sys.executable
    # Launch the package the same way packaging/dev expects.
    return f'"{python}" -m catswitch --minimized'


def is_windows_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _regtype = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Could not read autostart registry value: %s", exc)
        return False


def set_windows_autostart(enabled: bool) -> bool:
    """Enable or disable CatSwitch in the current-user Run key."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                command = autostart_command()
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, command)
                logger.info("Autostart enabled: %s", command)
            else:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                    logger.info("Autostart disabled")
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        logger.error("Failed to update autostart registry: %s", exc)
        return False


def sync_windows_autostart(enabled: bool) -> bool:
    """Apply setting to the registry (rewrites command when enabling)."""
    return set_windows_autostart(bool(enabled))
