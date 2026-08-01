"""
GitHub Releases updater for CatSwitch.

Checks for a newer Setup.exe, downloads it, then runs a helper script from a
private mkdtemp folder under %TEMP% (never from the install dir). That script
waits until CatSwitch.exe is gone, runs Setup silently, then launches the new app.

Inno CloseApplications waits on any process still using {app} files — so the
helper must not live under {app}, and Setup must not start until the app exits.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

from catswitch.version import APP_VERSION

logger = logging.getLogger(__name__)

# Public releases-only repo (source repo may stay private).
UPDATE_OWNER = "0yz"
UPDATE_REPO = "catswitch"
GITHUB_API_LATEST = (
    f"https://api.github.com/repos/{UPDATE_OWNER}/{UPDATE_REPO}/releases/latest"
)
GITHUB_RELEASES_URL = f"https://github.com/{UPDATE_OWNER}/{UPDATE_REPO}/releases"
USER_AGENT = f"CatSwitch/{APP_VERSION}"
CHECK_TIMEOUT_SECONDS = 12
DOWNLOAD_TIMEOUT_SECONDS = 120
# Kept for API compatibility; startup always checks (see should_run_startup_check).
STARTUP_CHECK_INTERVAL_SECONDS = 0

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-+].*)?$", re.I)
_last_check_result: Optional[Dict[str, Any]] = None
_install_lock = threading.Lock()
_install_in_progress = False


def is_update_channel_configured() -> bool:
    return bool(UPDATE_OWNER and UPDATE_REPO)


def parse_version(value: str) -> Optional[Tuple[int, ...]]:
    text = (value or "").strip()
    match = _VERSION_RE.match(text)
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def compare_versions(current: str, latest: str) -> int:
    """Return 1 if latest > current, 0 if equal/unparsable, -1 if latest < current."""
    cur = parse_version(current)
    lat = parse_version(latest)
    if cur is None or lat is None:
        return 0
    length = max(len(cur), len(lat))
    cur = cur + (0,) * (length - len(cur))
    lat = lat + (0,) * (length - len(lat))
    if lat > cur:
        return 1
    if lat < cur:
        return -1
    return 0


def _normalize_tag(tag: str) -> str:
    tag = (tag or "").strip()
    if tag.lower().startswith("v"):
        return tag[1:]
    return tag


# Exact installer asset name: CatSwitch-Setup-0.1.0.exe (digits may be multi-digit)
_INSTALLER_ASSET_RE = re.compile(
    r"^CatSwitch-Setup-\d+\.\d+\.\d+\.exe$",
    re.IGNORECASE,
)
_SHA256_HEX_RE = re.compile(r"\b([a-fA-F0-9]{64})\b")
# Release body lines such as:
#   SHA256: deadbeef...
#   CatSwitch-Setup-0.1.0.exe  deadbeef...
#   sha256:deadbeef...
_NOTES_SHA256_RE = re.compile(
    r"(?im)(?:^|\n)\s*(?:sha-?256\s*[:=]\s*|checksum\s*[:=]\s*)?"
    r"(?:CatSwitch-Setup-\d+\.\d+\.\d+\.exe\s+)?"
    r"([a-fA-F0-9]{64})\b"
)


def _normalize_sha256(value: Optional[str]) -> Optional[str]:
    """Return lowercase 64-char hex digest, or None if invalid."""
    if not value:
        return None
    text = value.strip()
    if text.lower().startswith("sha256:"):
        text = text.split(":", 1)[1].strip()
    match = _SHA256_HEX_RE.fullmatch(text) or _SHA256_HEX_RE.search(text)
    if not match:
        return None
    return match.group(1).lower()


def _sha256_from_asset(asset: dict) -> Optional[str]:
    """Prefer GitHub's immutable asset digest field (sha256:…)."""
    return _normalize_sha256(asset.get("digest") if asset else None)


def _sha256_from_release_notes(notes: Optional[str], asset_name: Optional[str] = None) -> Optional[str]:
    """Parse a SHA256 from release notes when asset.digest is missing (older uploads)."""
    if not notes:
        return None
    if asset_name:
        named = re.search(
            rf"(?im){re.escape(asset_name)}\s*[:=]?\s*([a-fA-F0-9]{{64}})\b"
            rf"|([a-fA-F0-9]{{64}})\s+{re.escape(asset_name)}\b",
            notes,
        )
        if named:
            return (named.group(1) or named.group(2)).lower()
    match = _NOTES_SHA256_RE.search(notes)
    if match:
        return match.group(1).lower()
    return None


def _pick_installer_asset(assets: list) -> Optional[dict]:
    """Accept only CatSwitch-Setup-X.X.X.exe (fail closed — no generic .exe fallback)."""
    if not assets:
        return None
    for asset in assets:
        name = asset.get("name") or ""
        url = asset.get("browser_download_url") or ""
        if url and _INSTALLER_ASSET_RE.match(name):
            return asset
    return None


def get_updates_last_checked() -> Optional[str]:
    from catswitch.settings import get_setting

    value = get_setting("updates_last_checked")
    return value if isinstance(value, str) and value else None


def set_updates_last_checked(iso_timestamp: str) -> None:
    from catswitch.settings import set_setting

    set_setting("updates_last_checked", iso_timestamp)


def get_cached_check_result() -> Optional[Dict[str, Any]]:
    return dict(_last_check_result) if _last_check_result else None


def check_for_updates(*, force: bool = True) -> Dict[str, Any]:
    """Query GitHub Releases for the latest version. Never raises to callers."""
    global _last_check_result

    checked_at = datetime.now(timezone.utc).isoformat()
    current = APP_VERSION
    base: Dict[str, Any] = {
        "success": True,
        "current": current,
        "latest": None,
        "update_available": False,
        "release_url": GITHUB_RELEASES_URL,
        "download_url": None,
        "asset_name": None,
        "sha256": None,
        "notes": None,
        "published_at": None,
        "checked_at": checked_at,
        "channel_configured": is_update_channel_configured(),
        "error": None,
    }

    if not is_update_channel_configured():
        base["success"] = False
        base["error"] = "Update channel is not configured"
        _last_check_result = base
        set_updates_last_checked(checked_at)
        return base

    try:
        response = requests.get(
            GITHUB_API_LATEST,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=CHECK_TIMEOUT_SECONDS,
        )
        if response.status_code in (401, 403, 404):
            # Private repo, missing Releases, or auth — don't claim "no releases yet".
            base["success"] = False
            base["error"] = "Could not reach update server"
            _last_check_result = base
            set_updates_last_checked(checked_at)
            return base
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.warning("Update check failed: %s", exc)
        base["success"] = False
        base["error"] = "Could not reach update server"
        _last_check_result = base
        set_updates_last_checked(checked_at)
        return base
    except Exception as exc:
        logger.error("Unexpected update check error: %s", exc)
        base["success"] = False
        base["error"] = "Update check failed"
        _last_check_result = base
        set_updates_last_checked(checked_at)
        return base

    tag = _normalize_tag(data.get("tag_name") or "")
    notes = (data.get("body") or "").strip() or None
    asset = _pick_installer_asset(data.get("assets") or [])
    base["latest"] = tag or None
    base["release_url"] = data.get("html_url") or GITHUB_RELEASES_URL
    base["notes"] = notes
    base["published_at"] = data.get("published_at")
    if asset:
        asset_name = asset.get("name")
        base["download_url"] = asset.get("browser_download_url")
        base["asset_name"] = asset_name
        base["sha256"] = _sha256_from_asset(asset) or _sha256_from_release_notes(
            notes, asset_name
        )

    if tag and compare_versions(current, tag) > 0:
        base["update_available"] = True
        if not base["download_url"]:
            base["error"] = (
                "Update found but no CatSwitch-Setup-X.X.X.exe asset attached"
            )
        elif not base["sha256"]:
            base["error"] = (
                "Update found but no SHA256 digest (GitHub asset digest or release notes)"
            )

    _last_check_result = base
    set_updates_last_checked(checked_at)
    return base


def should_run_startup_check() -> bool:
    """True when the UI should hit GitHub on launch (always — silent background check)."""
    return True


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_installer_sha256(path: str, expected_sha256: str) -> None:
    expected = _normalize_sha256(expected_sha256)
    if not expected:
        raise ValueError("Missing installer SHA256")
    actual = _file_sha256(path)
    if actual != expected:
        raise ValueError(
            f"Installer SHA256 mismatch (expected {expected}, got {actual})"
        )


def _download_installer(url: str, dest_path: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Installer download must use HTTPS")
    with requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        stream=True,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    ) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)


def _app_exe_path() -> str:
    if getattr(sys, "frozen", False) and os.path.isfile(sys.executable):
        return os.path.abspath(sys.executable)
    return os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Programs",
        "CatSwitch",
        "CatSwitch.exe",
    )


def _schedule_silent_install(
    installer_path: str,
    work_dir: Optional[str] = None,
    expected_version: Optional[str] = None,
) -> None:
    """Run apply_update.bat from a private temp dir so Inno is not blocked by us.

    Deadlock to avoid: anything still running from {app} (or waiting on Setup
    while locking {app}) makes CloseApplications hang forever.

    ``work_dir`` should be a unique ``mkdtemp`` folder (not a fixed %TEMP%\\CatSwitch path).
    Logs are kept under %LOCALAPPDATA%\\CatSwitch so a failed update can be diagnosed.
    """
    app_exe = _app_exe_path()
    app_dir = os.path.dirname(app_exe)
    if not work_dir:
        work_dir = tempfile.mkdtemp(prefix="CatSwitch-update-")

    log_dir = os.path.join(
        os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
        "CatSwitch",
    )
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = work_dir

    bat_path = os.path.join(work_dir, "apply_update.bat")
    log_path = os.path.join(log_dir, "update.log")
    setup_log_path = os.path.join(log_dir, "update-setup.log")

    installer_q = os.path.abspath(installer_path).replace('"', "")
    app_q = os.path.abspath(app_exe).replace('"', "")
    app_dir_q = os.path.abspath(app_dir).replace('"', "")
    bat_q = bat_path.replace('"', "")
    log_q = log_path.replace('"', "")
    setup_log_q = setup_log_path.replace('"', "")
    work_q = os.path.abspath(work_dir).replace('"', "")
    expected = (expected_version or "").strip().lstrip("vV")

    # Wait for CatSwitch.exe to exit, settle locks, run Setup (with retries),
    # only relaunch when Setup succeeded (and ProductVersion matches when known).
    script = (
        "@echo off\r\n"
        "setlocal EnableExtensions EnableDelayedExpansion\r\n"
        f'set "LOG={log_q}"\r\n'
        f'set "SETUPLOG={setup_log_q}"\r\n'
        f'set "INSTALLER={installer_q}"\r\n'
        f'set "APP={app_q}"\r\n'
        f'set "APPDIR={app_dir_q}"\r\n'
        f'set "WORKDIR={work_q}"\r\n'
        f'set "EXPECTED={expected}"\r\n'
        "echo %DATE% %TIME% Waiting for CatSwitch.exe to exit>>\"%LOG%\"\r\n"
        ":wait\r\n"
        'tasklist /FI "IMAGENAME eq CatSwitch.exe" /FO CSV /NH 2>nul '
        '| find /I "CatSwitch.exe" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  ping -n 2 127.0.0.1 >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        "echo %DATE% %TIME% App gone; settling file locks>>\"%LOG%\"\r\n"
        "ping -n 4 127.0.0.1 >nul\r\n"
        'taskkill /F /IM "CatSwitch.exe" /T >nul 2>&1\r\n'
        "ping -n 2 127.0.0.1 >nul\r\n"
        "set ATTEMPT=0\r\n"
        ":runsetup\r\n"
        "set /a ATTEMPT+=1\r\n"
        "echo %DATE% %TIME% Starting Setup attempt %ATTEMPT%>>\"%LOG%\"\r\n"
        '"%INSTALLER%" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES '
        "/CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /NORESTARTAPPLICATIONS "
        '/DIR="%APPDIR%" /LOG="%SETUPLOG%"\r\n'
        "set SETUP_EXIT=%ERRORLEVEL%\r\n"
        "echo %DATE% %TIME% Setup exit code %SETUP_EXIT% (attempt %ATTEMPT%)>>\"%LOG%\"\r\n"
        "if not \"%SETUP_EXIT%\"==\"0\" (\r\n"
        "  if %ATTEMPT% LSS 3 (\r\n"
        "    echo %DATE% %TIME% Retrying after delay>>\"%LOG%\"\r\n"
        "    ping -n 4 127.0.0.1 >nul\r\n"
        "    goto runsetup\r\n"
        "  )\r\n"
        ")\r\n"
        'if exist "%INSTALLER%" del /f /q "%INSTALLER%" >nul 2>&1\r\n'
        "if not \"%SETUP_EXIT%\"==\"0\" (\r\n"
        "  echo %DATE% %TIME% Setup failed; not launching old build>>\"%LOG%\"\r\n"
        "  goto cleanup\r\n"
        ")\r\n"
        'if not exist "%APP%" (\r\n'
        "  echo %DATE% %TIME% App exe missing after successful Setup>>\"%LOG%\"\r\n"
        "  set SETUP_EXIT=1\r\n"
        "  goto cleanup\r\n"
        ")\r\n"
        "if not \"%EXPECTED%\"==\"\" (\r\n"
        "  for /f \"usebackq delims=\" %%V in (`powershell -NoProfile -Command "
        "\"try { (Get-Item -LiteralPath '%APP%').VersionInfo.ProductVersion } "
        "catch { '' }\"`) do set \"GOT=%%V\"\r\n"
        "  echo %DATE% %TIME% Installed ProductVersion=[!GOT!] expected=[%EXPECTED%]>>\"%LOG%\"\r\n"
        "  if /I not \"!GOT!\"==\"%EXPECTED%\" (\r\n"
        "    echo %DATE% %TIME% Version mismatch after Setup; not launching>>\"%LOG%\"\r\n"
        "    set SETUP_EXIT=1\r\n"
        "    goto cleanup\r\n"
        "  )\r\n"
        ")\r\n"
        "echo %DATE% %TIME% Launching updated app>>\"%LOG%\"\r\n"
        'start "" /D "%APPDIR%" "%APP%"\r\n'
        ":cleanup\r\n"
        f'del /f /q "{bat_q}" >nul 2>&1\r\n'
        'cd /d "%TEMP%"\r\n'
        'rd /s /q "%WORKDIR%" >nul 2>&1\r\n'
        "exit /b %SETUP_EXIT%\r\n"
    )
    with open(bat_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(script)

    # start breaks away so our process tree exit / taskkill cannot kill the helper.
    cmd = ["cmd.exe", "/d", "/c", "start", "", "/MIN", bat_path]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
    subprocess.Popen(
        cmd,
        cwd=work_dir,
        close_fds=True,
        creationflags=creationflags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info("Scheduled update helper: %s (log: %s)", bat_path, log_path)


def begin_install_update() -> Dict[str, Any]:
    """Download Setup, schedule temp helper, then caller should quit."""
    global _install_in_progress
    with _install_lock:
        if _install_in_progress:
            return {"success": False, "error": "Update already in progress"}
        _install_in_progress = True

    dest_path: Optional[str] = None
    work_dir: Optional[str] = None
    try:
        status = check_for_updates(force=True)
        if not status.get("update_available"):
            return {
                "success": False,
                "error": status.get("error") or "No update available",
                "status": status,
            }
        download_url = status.get("download_url")
        if not download_url:
            return {"success": False, "error": "No installer download URL", "status": status}

        expected_sha256 = _normalize_sha256(status.get("sha256"))
        if not expected_sha256:
            return {
                "success": False,
                "error": "No SHA256 digest available for this release — refusing to install",
                "status": status,
            }

        parsed = urlparse(download_url)
        if parsed.scheme != "https" or "github" not in (parsed.netloc or "").lower():
            return {"success": False, "error": "Unexpected download host"}

        asset_name = status.get("asset_name") or "CatSwitch-Setup-0.0.0.exe"
        safe_name = re.sub(r"[^\w.\-]+", "_", asset_name)
        work_dir = tempfile.mkdtemp(prefix="CatSwitch-update-")
        dest_path = os.path.join(work_dir, safe_name)

        logger.info("Downloading update to %s", dest_path)
        _download_installer(download_url, dest_path)
        if not os.path.isfile(dest_path) or os.path.getsize(dest_path) < 1024:
            return {"success": False, "error": "Downloaded installer is invalid"}

        try:
            _verify_installer_sha256(dest_path, expected_sha256)
        except ValueError as exc:
            logger.error("Installer integrity check failed: %s", exc)
            try:
                os.unlink(dest_path)
            except OSError:
                pass
            return {
                "success": False,
                "error": "Installer integrity check failed (SHA256 mismatch)",
                "status": status,
            }

        _schedule_silent_install(
            dest_path,
            work_dir=work_dir,
            expected_version=status.get("latest") or "",
        )
        return {
            "success": True,
            "message": "Installer ready. The app will close and update.",
            "installer_path": dest_path,
            "status": status,
        }
    except requests.RequestException as exc:
        logger.error("Update download failed: %s", exc)
        if dest_path:
            try:
                os.unlink(dest_path)
            except OSError:
                pass
        return {"success": False, "error": "Failed to download update"}
    except Exception as exc:
        logger.error("Update install failed: %s", exc)
        if dest_path:
            try:
                os.unlink(dest_path)
            except OSError:
                pass
        return {"success": False, "error": str(exc)}
    finally:
        with _install_lock:
            _install_in_progress = False
        # On failure before scheduling, drop the private temp dir.
        if work_dir and dest_path and not os.path.isfile(
            os.path.join(work_dir, "apply_update.bat")
        ):
            try:
                import shutil

                shutil.rmtree(work_dir, ignore_errors=True)
            except OSError:
                pass


def request_app_exit_for_update() -> None:
    """Quit so the temp helper can run Setup without CloseApplications deadlock."""
    from catswitch.desktop_app import schedule_force_process_exit

    schedule_force_process_exit(2.5)
    try:
        import webview

        if webview.windows:
            webview.windows[0].destroy()
    except Exception as exc:
        logger.warning("Could not destroy window for update: %s", exc)
