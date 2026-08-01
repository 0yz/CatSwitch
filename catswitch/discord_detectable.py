"""Discord detectable applications list for game detection confidence."""

import json
import logging
import os
import threading
from typing import Dict, Optional, Tuple

import requests

from catswitch.paths import get_cache_dir, get_discord_detectable_cache_path

logger = logging.getLogger('catswitch.discord_detectable')

DISCORD_DETECTABLE_URL = 'https://discord.com/api/v9/applications/detectable'
CACHE_VERSION = 2
DISCORD_UNREACHABLE_MESSAGE = (
    "Could not connect to Discord servers — Discord support disabled. "
    "Re-enable in Settings to try again."
)

_cache_lock = threading.Lock()
_executable_to_app_name: Dict[str, str] = {}
_etag: Optional[str] = None
_cache_loaded = False
_disabled_notice: Optional[str] = None


def _normalize_executable_entry(name: str) -> str:
    return name.replace('\\', '/').lower().strip()


def _path_matches_discord_executable(path_norm: str, partial: str) -> bool:
    """Match Discord's partial executable path against a full process path."""
    partial = partial.strip('/')
    if not partial or not path_norm:
        return False
    if path_norm.endswith('/' + partial) or path_norm == partial:
        return True
    return False


def _extract_win32_executable_entries(apps) -> Dict[str, str]:
    """Map normalized win32 executable partial paths to Discord app names."""
    result: Dict[str, str] = {}
    for app in apps:
        app_name = (app.get('name') or '').strip()
        if not app_name:
            continue
        for exe in app.get('executables') or []:
            if exe.get('os') != 'win32':
                continue
            partial = _normalize_executable_entry(exe.get('name') or '')
            if partial:
                result[partial] = app_name
    return result


def _save_cache(entries: Dict[str, str], etag: Optional[str]) -> None:
    os.makedirs(get_cache_dir(), exist_ok=True)
    payload = {
        'version': CACHE_VERSION,
        'etag': etag,
        'executable_app_names': entries,
    }
    with open(get_discord_detectable_cache_path(), 'w', encoding='utf-8') as f:
        json.dump(payload, f)


def _load_cache_from_disk() -> bool:
    global _executable_to_app_name, _etag, _cache_loaded

    path = get_discord_detectable_cache_path()
    if not os.path.exists(path):
        return False

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if int(data.get('version') or 0) < CACHE_VERSION:
            logger.info('Discord detectable cache is outdated — will refresh from API')
            return False

        raw_entries = data.get('executable_app_names') or {}
        _executable_to_app_name = {
            _normalize_executable_entry(key): value
            for key, value in raw_entries.items()
            if key and value
        }
        _etag = data.get('etag')
        _cache_loaded = bool(_executable_to_app_name)
        logger.info(
            'Loaded %d Discord detectable executables from cache',
            len(_executable_to_app_name),
        )
        return _cache_loaded
    except Exception as exc:
        logger.warning('Failed to load Discord detectable cache: %s', exc)
        return False


def _fetch_from_api(if_none_match: Optional[str] = None) -> bool:
    global _executable_to_app_name, _etag, _cache_loaded

    headers = {'Accept': 'application/json'}
    if if_none_match:
        headers['If-None-Match'] = if_none_match

    try:
        response = requests.get(DISCORD_DETECTABLE_URL, headers=headers, timeout=60)
        if response.status_code == 304:
            logger.info('Discord detectable list unchanged (304)')
            _cache_loaded = _cache_loaded or bool(_executable_to_app_name)
            return bool(_executable_to_app_name)

        response.raise_for_status()
        apps = response.json()
        if not isinstance(apps, list):
            logger.warning('Unexpected Discord detectable payload type: %s', type(apps))
            return False

        entries = _extract_win32_executable_entries(apps)
        new_etag = response.headers.get('ETag') or response.headers.get('etag')
        _executable_to_app_name = entries
        _etag = new_etag
        _cache_loaded = bool(entries)
        _save_cache(entries, new_etag)
        logger.info('Fetched %d Discord detectable executables', len(entries))
        return bool(entries)
    except Exception as exc:
        logger.warning('Failed to fetch Discord detectable list: %s', exc)
        return False


def has_discord_detectable_data() -> bool:
    with _cache_lock:
        return bool(_executable_to_app_name)


def consume_discord_disabled_notice() -> Optional[str]:
    """Return and clear a one-shot UI notice after auto-disable."""
    global _disabled_notice
    notice = _disabled_notice
    _disabled_notice = None
    return notice


def _disable_discord_support(reason: str) -> None:
    """Turn off the Discord setting when no detectable list is available."""
    global _disabled_notice
    from catswitch.settings import get_use_discord_detectable, save_detection_settings

    if not get_use_discord_detectable():
        return

    save_detection_settings({"use_discord_detectable": False})
    _disabled_notice = reason
    logger.warning(reason)


def ensure_discord_detectable_ready() -> Tuple[bool, Optional[str]]:
    """
    Ensure a Discord detectable list is available (disk cache and/or live fetch).

    Returns (ok, error_message). Does not change the user setting by itself.
    """
    with _cache_lock:
        if not _executable_to_app_name:
            _load_cache_from_disk()
        if _executable_to_app_name:
            # Prefer a refresh, but keep using cache if Discord is unreachable.
            _fetch_from_api(_etag)
            return True, None

        if _fetch_from_api(None) and _executable_to_app_name:
            return True, None

    return False, DISCORD_UNREACHABLE_MESSAGE


def initialize_discord_detectable_cache() -> bool:
    """Load cached executables and refresh from Discord when possible.

    If nothing can be loaded (no cache and Discord unreachable), disable the
    Discord support setting so detection does not fail-open.
    """
    with _cache_lock:
        loaded = _load_cache_from_disk()
        if not _executable_to_app_name:
            _fetch_from_api(None)
        else:
            refreshed = _fetch_from_api(_etag if loaded else None)
            if not refreshed and _executable_to_app_name:
                logger.info(
                    'Discord refresh failed — continuing with %d cached executables',
                    len(_executable_to_app_name),
                )
        available = bool(_executable_to_app_name)

    if not available:
        _disable_discord_support(DISCORD_UNREACHABLE_MESSAGE)
    return available


def refresh_discord_detectable_if_changed() -> None:
    """Check Discord headers and reload the list when it changed."""
    with _cache_lock:
        if not _cache_loaded:
            _load_cache_from_disk()
        if _executable_to_app_name:
            _fetch_from_api(_etag)
        else:
            _fetch_from_api(None)


def _match_discord_entry(process_path: str) -> Optional[str]:
    """Return the Discord app name when the process path matches an executable entry."""
    if not process_path:
        return None

    path_norm = process_path.replace('\\', '/').lower()
    for partial, app_name in _executable_to_app_name.items():
        if _path_matches_discord_executable(path_norm, partial):
            return app_name
    return None


def is_process_discord_detectable(process_path: str) -> bool:
    """
    Return True when the process path matches Discord's detectable executables list.

    When the feature is disabled, returns False (callers should check the setting
    first). When the cache is empty, returns False (fail closed — unknown ≠ game).
    """
    from catswitch.settings import get_use_discord_detectable

    if not get_use_discord_detectable():
        return False

    if not process_path:
        return False

    with _cache_lock:
        if not _cache_loaded or not _executable_to_app_name:
            return False
        return _match_discord_entry(process_path) is not None


def get_discord_app_name(process_path: str) -> Optional[str]:
    """Return Discord's application name for a matching process path, if any."""
    from catswitch.settings import get_use_discord_detectable

    if not get_use_discord_detectable() or not process_path:
        return None

    with _cache_lock:
        if not _cache_loaded or not _executable_to_app_name:
            return None
        return _match_discord_entry(process_path)
