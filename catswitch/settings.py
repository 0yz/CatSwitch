import json
import os
import tempfile
import threading
from typing import Any, Callable, Dict, Optional, List

from catswitch.paths import (
    ensure_app_data_layout,
    get_app_data_dir,
    get_settings_file_path,
    resolve_data_path,
)

DEFAULT_SETTINGS_FILE = "settings.json"

# Serialize all settings.json read-modify-write (UI, updater, list edits, auth).
_settings_lock = threading.RLock()

# Default settings structure
DEFAULT_DETECTION_SETTINGS = {
    "default_category": "Just Chatting",
    "switch_delay_seconds": 0,
    "auto_lock_category_on_manual_update": True,
    "auto_lock_title_on_manual_update": True,
    "use_discord_detectable": True,
}

DEFAULT_THEME = "Default.css"


def normalize_theme_filename(theme: str) -> str:
    """Normalize stored/API theme values to an AppData CSS filename."""
    normalized = (theme or DEFAULT_THEME).strip() or DEFAULT_THEME
    if normalized.lower() == "default":
        return DEFAULT_THEME
    return normalized

DEFAULT_SETTINGS = {
    "excluded_apps": {
        "lists": []  # List of dicts with name, path, and source (local/url) keys
    },
    "window": {
        "x": 100,
        "y": 100,
        "always_on_top": False,
        "minimize_to_tray": False,
        "autostart_with_windows": False,
    },
    "detection": dict(DEFAULT_DETECTION_SETTINGS),
    "theme": DEFAULT_THEME,
}

def _resolve_config_path(path: str) -> str:
    """Resolve list paths relative to the AppData root."""
    return resolve_data_path(path)

def _paths_refer_to_same_file(path_a: str, path_b: str) -> bool:
    """Return True when two configured paths point to the same file."""
    if not path_a or not path_b:
        return False
    resolved_a = _resolve_config_path(path_a)
    resolved_b = _resolve_config_path(path_b)
    if os.path.normcase(resolved_a) == os.path.normcase(resolved_b):
        return True
    try:
        if os.path.exists(resolved_a) and os.path.exists(resolved_b):
            return os.path.samefile(resolved_a, resolved_b)
    except OSError:
        pass
    return False

def _normalize_stored_list_path(path: str) -> str:
    """Store list paths relative to AppData when possible."""
    if not path:
        return path
    abs_path = _resolve_config_path(path)
    app_data = os.path.normcase(get_app_data_dir())
    abs_norm = os.path.normcase(abs_path)
    if abs_norm == app_data or abs_norm.startswith(app_data + os.sep):
        rel = os.path.relpath(abs_path, get_app_data_dir())
        return rel.replace("\\", "/")
    return abs_path.replace("\\", "/")

def _merge_list_entry(existing: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    """Merge duplicate list settings, preserving intentional disable."""
    if incoming.get("enabled", True) is False:
        existing["enabled"] = False
    for key in ("name", "source", "url"):
        if not existing.get(key) and incoming.get(key):
            existing[key] = incoming[key]

def _consolidate_detected_app_lists(settings: Dict[str, Any]) -> bool:
    """Merge detected list entries that refer to the same file."""
    detected_apps = settings.get("detected_apps", {})
    lists = detected_apps.get("lists", [])
    if not lists:
        return False

    consolidated: List[Dict[str, Any]] = []
    changed = False

    for lst in lists:
        normalized = dict(lst)
        if normalized.get("path"):
            stored_path = _normalize_stored_list_path(normalized["path"])
            if stored_path != normalized.get("path"):
                changed = True
            normalized["path"] = stored_path

        merged = False
        for existing in consolidated:
            same_path = (
                normalized.get("path")
                and existing.get("path")
                and _paths_refer_to_same_file(existing.get("path", ""), normalized.get("path", ""))
            )
            same_url = (
                normalized.get("source") == "url"
                and existing.get("source") == "url"
                and normalized.get("url")
                and existing.get("url") == normalized.get("url")
            )
            if same_path or same_url:
                _merge_list_entry(existing, normalized)
                merged = True
                changed = True
                break

        if not merged:
            consolidated.append(normalized)

    if len(consolidated) != len(lists):
        changed = True

    if changed:
        detected_apps["lists"] = consolidated
        settings["detected_apps"] = detected_apps
    return changed

def _consolidate_excluded_app_lists(settings: Dict[str, Any]) -> bool:
    """Merge excluded list entries that refer to the same file."""
    excluded_apps = settings.get("excluded_apps", {})
    lists = excluded_apps.get("lists", [])
    if not lists:
        return False

    consolidated: List[Dict[str, Any]] = []
    changed = False

    for lst in lists:
        normalized = dict(lst)
        if normalized.get("path"):
            stored_path = _normalize_stored_list_path(normalized["path"])
            if stored_path != normalized.get("path"):
                changed = True
            normalized["path"] = stored_path

        merged = False
        for existing in consolidated:
            same_path = (
                normalized.get("path")
                and existing.get("path")
                and _paths_refer_to_same_file(existing.get("path", ""), normalized.get("path", ""))
            )
            same_url = (
                normalized.get("source") == "url"
                and existing.get("source") == "url"
                and normalized.get("url")
                and existing.get("url") == normalized.get("url")
            )
            if same_path or same_url:
                _merge_list_entry(existing, normalized)
                merged = True
                changed = True
                break

        if not merged:
            consolidated.append(normalized)

    if len(consolidated) != len(lists):
        changed = True

    if changed:
        excluded_apps["lists"] = consolidated
        settings["excluded_apps"] = excluded_apps
    return changed


def _sync_local_list_registry_with_folder(
    settings: Dict[str, Any],
    section_key: str,
    folder_path: str,
) -> bool:
    """
    Sync a list registry with .txt files on disk.

    Drops local entries whose files are missing, keeps URL-based lists, and adds
    newly discovered files from the folder.
    """
    section = settings.setdefault(section_key, {"lists": []})
    lists = section.get("lists", [])
    changed = False

    kept_lists: List[Dict[str, Any]] = []
    for lst in lists:
        if lst.get("source") == "url":
            kept_lists.append(lst)
            continue

        path = lst.get("path", "")
        if path and os.path.isfile(_resolve_config_path(path)):
            kept_lists.append(lst)
        elif path:
            changed = True
        else:
            changed = True

    lists = kept_lists

    if os.path.isdir(folder_path):
        for filename in os.listdir(folder_path):
            if not filename.lower().endswith('.txt'):
                continue
            file_path = os.path.join(folder_path, filename)
            if not os.path.isfile(file_path):
                continue

            already_registered = any(
                _paths_refer_to_same_file(lst.get("path", ""), file_path)
                for lst in lists
            )
            if already_registered:
                continue

            lists.append({
                "name": filename,
                "path": _normalize_stored_list_path(file_path),
                "source": "local",
                "enabled": True,
            })
            changed = True

    if changed:
        section["lists"] = lists
        settings[section_key] = section

    return changed


def _list_entry_matches(lst: Dict[str, Any], path: str, url: Optional[str] = None) -> bool:
    """Return True when a settings list entry matches the given path or URL."""
    if url and lst.get("url") == url:
        return True
    if path and _paths_refer_to_same_file(lst.get("path", ""), path):
        return True
    return False

def _normalize_list_enabled(lst: Dict[str, Any]) -> None:
    """Ensure list entries expose an enabled flag (defaults to True)."""
    lst["enabled"] = lst.get("enabled", True)

def initialize_settings() -> None:
    """Initialize the settings file if it doesn't exist."""
    with _settings_lock:
        settings_file = get_settings_file_path()
        if not os.path.exists(settings_file):
            _save_settings_unlocked(DEFAULT_SETTINGS)


def _load_settings_unlocked() -> Dict[str, Any]:
    """Load settings from disk. Caller must hold `_settings_lock`."""
    settings_file = get_settings_file_path()
    if not os.path.exists(settings_file):
        return {}

    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            settings = json.load(f)
            return settings if isinstance(settings, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings_unlocked(settings: Dict[str, Any]) -> bool:
    """Atomically write settings to disk. Caller must hold `_settings_lock`."""
    settings_file = get_settings_file_path()
    directory = os.path.dirname(settings_file) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix="settings_",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, settings_file)
        return True
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False


def load_settings() -> Dict[str, Any]:
    """Load settings from the settings file. If the file doesn't exist, return an empty dict."""
    with _settings_lock:
        return _load_settings_unlocked()


def save_settings(settings: Dict[str, Any]) -> bool:
    """Save settings to the settings file. Returns True if successful, False otherwise."""
    with _settings_lock:
        return _save_settings_unlocked(settings)


def get_setting(key: str, default: Any = None) -> Any:
    """Get a specific setting value. Returns the default value if the setting doesn't exist."""
    with _settings_lock:
        settings = _load_settings_unlocked()
        return settings.get(key, default)


def set_setting(key: str, value: Any) -> bool:
    """Set a specific setting value. Returns True if successful, False otherwise."""
    with _settings_lock:
        settings = _load_settings_unlocked()
        settings[key] = value
        return _save_settings_unlocked(settings)


def delete_setting(key: str) -> bool:
    """Delete a specific setting. Returns True if successful, False otherwise."""
    with _settings_lock:
        settings = _load_settings_unlocked()
        if key in settings:
            del settings[key]
            return _save_settings_unlocked(settings)
        return True


def mutate_settings(mutator: Callable[[Dict[str, Any]], Any]) -> bool:
    """Run a read-modify-write under the settings lock.

    ``mutator(settings)`` may mutate ``settings`` in place.
    Return ``False`` from the mutator to abort without writing.
    """
    with _settings_lock:
        settings = _load_settings_unlocked()
        outcome = mutator(settings)
        if outcome is False:
            return False
        return _save_settings_unlocked(settings)

def get_excluded_app_files() -> List[Dict[str, str]]:
    """Get the list of excluded app lists."""
    with _settings_lock:
        settings = _load_settings_unlocked()
        if settings and _consolidate_excluded_app_lists(settings):
            _save_settings_unlocked(settings)

        lists = (
            settings.get("excluded_apps", {}).get("lists", [])
            if settings
            else []
        )

    if not lists:
        initialize_default_excluded_apps()
        with _settings_lock:
            settings = _load_settings_unlocked()
            lists = settings.get("excluded_apps", {}).get("lists", [])

    # Process each list to extract name from hash if present
    for lst in lists:
        if lst.get("source") == "local" and lst.get("path"):
            lst["path"] = _resolve_config_path(lst["path"])
            # Try to read the first line to check for hash name
            try:
                with open(lst["path"], 'r', encoding='utf-8', errors='replace') as f:
                    first_line = f.readline().strip()
                    if first_line.startswith('#'):
                        # Extract name from hash line
                        name = first_line[1:].strip()
                        if name:
                            lst["name"] = name
            except Exception:
                pass  # Keep original name if we can't read the file
        _normalize_list_enabled(lst)
    
    return lists

def get_detected_app_files() -> List[Dict[str, str]]:
    """Get the list of detected app lists."""
    with _settings_lock:
        settings = _load_settings_unlocked()
        if settings and _consolidate_detected_app_lists(settings):
            _save_settings_unlocked(settings)

        lists = (
            settings.get("detected_apps", {}).get("lists", [])
            if settings
            else []
        )

    from catswitch.detected_apps import get_detected_local_file_path
    default_local = get_detected_local_file_path()

    # Process each list to extract name from hash if present
    for lst in lists:
        if lst.get("source") == "local" and lst.get("path"):
            lst["path"] = _resolve_config_path(lst["path"])
            if _paths_refer_to_same_file(lst.get("path", ""), default_local):
                lst["is_default_local"] = True
            # Try to read the first line to check for hash name
            try:
                with open(lst["path"], 'r', encoding='utf-8', errors='replace') as f:
                    first_line = f.readline().strip()
                    if first_line.startswith('#'):
                        # Extract name from hash line
                        name = first_line[1:].strip()
                        if name:
                            lst["name"] = name
            except Exception:
                pass  # Keep original name if we can't read the file
        _normalize_list_enabled(lst)
    
    return lists

def set_detected_app_list_enabled(path: str, enabled: bool, url: Optional[str] = None) -> bool:
    """Enable or disable a detected apps list."""
    try:
        def _mutate(settings: Dict[str, Any]) -> Any:
            lists = settings.get("detected_apps", {}).get("lists", [])
            for lst in lists:
                if _list_entry_matches(lst, path, url):
                    lst["enabled"] = enabled
                    settings.setdefault("detected_apps", {})["lists"] = lists
                    return True
            return False

        return mutate_settings(_mutate)
    except Exception as e:
        print(f"Error setting detected app list enabled state: {e}")
        return False

def set_excluded_app_list_enabled(path: str, enabled: bool, url: Optional[str] = None) -> bool:
    """Enable or disable an excluded apps list."""
    try:
        def _mutate(settings: Dict[str, Any]) -> Any:
            excluded_apps = settings.get("excluded_apps") or {}
            lists = excluded_apps.get("lists", [])
            for lst in lists:
                if _list_entry_matches(lst, path, url):
                    lst["enabled"] = enabled
                    excluded_apps["lists"] = lists
                    settings["excluded_apps"] = excluded_apps
                    return True
            return False

        return mutate_settings(_mutate)
    except Exception as e:
        print(f"Error setting excluded app list enabled state: {e}")
        return False

def initialize_default_detected_apps():
    """Initialize default detected apps settings with Local.txt."""
    try:
        from catswitch.detected_apps import ensure_detected_local_file
        ensure_detected_local_file()
    except Exception as e:
        print(f"Error initializing default detected apps: {e}")

def initialize_default_excluded_apps():
    """Initialize default excluded apps settings with Local.txt and Common.txt."""
    try:
        from catswitch.excluded_apps import (
            ensure_excluded_local_file,
            ensure_excluded_common_file,
        )
        ensure_excluded_local_file()
        ensure_excluded_common_file()
    except Exception as e:
        print(f"Error initializing default excluded apps: {e}")

def discover_detected_app_lists() -> None:
    """Sync detected app list settings with .txt files in the detected apps folder."""
    try:
        from catswitch.detected_apps import get_detected_apps_dir

        def _mutate(settings: Dict[str, Any]) -> Any:
            _consolidate_detected_app_lists(settings)
            changed = _sync_local_list_registry_with_folder(
                settings,
                "detected_apps",
                get_detected_apps_dir(),
            )
            if _consolidate_detected_app_lists(settings):
                changed = True
            if not changed:
                return False
            return True

        mutate_settings(_mutate)
    except Exception as e:
        print(f"Error discovering detected app lists: {e}")

def discover_excluded_app_lists() -> None:
    """Sync excluded app list settings with .txt files in the excluded apps folder."""
    try:
        from catswitch.excluded_apps import get_excluded_apps_dir

        def _mutate(settings: Dict[str, Any]) -> Any:
            _consolidate_excluded_app_lists(settings)
            changed = _sync_local_list_registry_with_folder(
                settings,
                "excluded_apps",
                get_excluded_apps_dir(),
            )
            if _consolidate_excluded_app_lists(settings):
                changed = True
            if not changed:
                return False
            return True

        mutate_settings(_mutate)
    except Exception as e:
        print(f"Error discovering excluded app lists: {e}")

def add_detected_app_file(name: str, path: str, source: str = "local", url: str = None) -> bool:
    """
    Add a detected app list to the settings.
    
    Args:
        name: The name of the list
        path: The file path
        source: The source type ('local' or 'url')
        url: The URL if source is 'url'
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with _settings_lock:
            settings = _load_settings_unlocked()
            if "detected_apps" not in settings:
                settings["detected_apps"] = {"lists": []}
            for lst in settings["detected_apps"]["lists"]:
                if _paths_refer_to_same_file(lst.get("path", ""), path):
                    return True
            new_list = {
                "name": name,
                "path": _normalize_stored_list_path(path) if path else path,
                "source": source,
            }
            if url:
                new_list["url"] = url
            settings["detected_apps"]["lists"].append(new_list)
            return _save_settings_unlocked(settings)
    except Exception as e:
        print(f"Error adding detected app file: {e}")
        return False

def update_detected_app_url_list(current_url: str, name: str, new_url: str) -> bool:
    """Update name and URL for a detected apps URL-based list."""
    try:
        with _settings_lock:
            settings = _load_settings_unlocked()
            if "detected_apps" not in settings:
                return False

            lists = settings["detected_apps"].get("lists", [])
            for lst in lists:
                if lst.get("source") == "url" and lst.get("url") == current_url:
                    for other in lists:
                        if (
                            other is not lst
                            and other.get("source") == "url"
                            and other.get("url") == new_url
                        ):
                            return False
                    lst["name"] = name
                    lst["url"] = new_url
                    settings["detected_apps"]["lists"] = lists
                    return _save_settings_unlocked(settings)
            return False
    except Exception as e:
        print(f"Error updating detected app URL list: {e}")
        return False

def remove_detected_app_file(path: str) -> bool:
    """
    Remove a detected app list from the settings.
    
    Args:
        path: The file path to remove
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with _settings_lock:
            settings = _load_settings_unlocked()
            if "detected_apps" not in settings:
                return False

            lists = settings["detected_apps"].get("lists", [])
            original_length = len(lists)
            lists = [
                list_item
                for list_item in lists
                if not _paths_refer_to_same_file(list_item.get("path", ""), path)
            ]

            if len(lists) == original_length:
                return False

            settings["detected_apps"]["lists"] = lists
            return _save_settings_unlocked(settings)
    except Exception as e:
        print(f"Error removing detected app file: {e}")
        return False

def reorder_detected_app_file(path: str, direction: str) -> bool:
    """Move a detected app list up or down in priority order."""
    if direction not in ("up", "down"):
        return False

    try:
        with _settings_lock:
            settings = _load_settings_unlocked()
            lists = settings.get("detected_apps", {}).get("lists", [])
            index = next(
                (
                    i
                    for i, lst in enumerate(lists)
                    if _paths_refer_to_same_file(lst.get("path", ""), path)
                ),
                -1,
            )
            if index < 0:
                return False

            if direction == "up" and index > 0:
                lists[index - 1], lists[index] = lists[index], lists[index - 1]
            elif direction == "down" and index < len(lists) - 1:
                lists[index + 1], lists[index] = lists[index], lists[index + 1]
            else:
                return False

            settings.setdefault("detected_apps", {})["lists"] = lists
            return _save_settings_unlocked(settings)
    except Exception as e:
        print(f"Error reordering detected app file: {e}")
        return False

def add_excluded_app_file(name: str, path: str, source: str = "local", url: str = None) -> bool:
    """
    Add an excluded app list to the settings.
    
    Args:
        name: Display name of the list
        path: Path to the list
        source: Either "local" or "url"
        url: URL source if the list was downloaded
        
    Returns:
        True if successful, False otherwise
    """
    with _settings_lock:
        settings = _load_settings_unlocked()
        excluded_apps = settings.get("excluded_apps") or {}
        lists = list(excluded_apps.get("lists", []))

        for i, list_item in enumerate(lists):
            if _paths_refer_to_same_file(list_item.get("path", ""), path):
                lists[i] = {
                    "name": name,
                    "path": _normalize_stored_list_path(path) if path else path,
                    "source": source,
                }
                if url:
                    lists[i]["url"] = url
                excluded_apps["lists"] = lists
                settings["excluded_apps"] = excluded_apps
                return _save_settings_unlocked(settings)

        list_info = {
            "name": name,
            "path": _normalize_stored_list_path(path) if path else path,
            "source": source,
        }
        if url:
            list_info["url"] = url

        lists.append(list_info)
        excluded_apps["lists"] = lists
        settings["excluded_apps"] = excluded_apps
        return _save_settings_unlocked(settings)

def remove_excluded_app_file(path: str) -> bool:
    """Remove an excluded app list from the settings."""
    with _settings_lock:
        settings = _load_settings_unlocked()
        excluded_apps = settings.get("excluded_apps") or {}
        lists = [
            list_item
            for list_item in excluded_apps.get("lists", [])
            if list_item.get("path") != path
        ]
        excluded_apps["lists"] = lists
        settings["excluded_apps"] = excluded_apps
        return _save_settings_unlocked(settings)

def save_window_position(x: int, y: int) -> bool:
    """Save window position to settings."""
    with _settings_lock:
        settings = _load_settings_unlocked()
        window_settings = dict(settings.get("window") or {})
        window_settings["x"] = x
        window_settings["y"] = y
        settings["window"] = window_settings
        return _save_settings_unlocked(settings)

def load_window_position() -> tuple[int, int]:
    """Load window position from settings. Returns (x, y) tuple."""
    window_settings = get_setting("window", {})
    return window_settings.get("x", 100), window_settings.get("y", 100)

def save_always_on_top(enabled: bool) -> bool:
    """Save always on top setting."""
    with _settings_lock:
        settings = _load_settings_unlocked()
        window_settings = dict(settings.get("window") or {})
        window_settings["always_on_top"] = enabled
        settings["window"] = window_settings
        return _save_settings_unlocked(settings)

def load_always_on_top() -> bool:
    """Load always on top setting. Returns False if not set."""
    window_settings = get_setting("window", {})
    return window_settings.get("always_on_top", False)


def get_window_settings() -> Dict[str, Any]:
    """Return user-facing window settings."""
    window_settings = get_setting("window", {})
    return {
        "minimize_to_tray": bool(window_settings.get("minimize_to_tray", False)),
        "autostart_with_windows": bool(window_settings.get("autostart_with_windows", False)),
    }


def save_window_settings(updates: Dict[str, Any]) -> bool:
    """Persist window settings updates."""
    if "autostart_with_windows" in updates:
        from catswitch.autostart import sync_windows_autostart

        if not sync_windows_autostart(bool(updates["autostart_with_windows"])):
            return False

    with _settings_lock:
        settings = _load_settings_unlocked()
        window_settings = dict(settings.get("window") or {})
        if "minimize_to_tray" in updates:
            window_settings["minimize_to_tray"] = bool(updates["minimize_to_tray"])
        if "autostart_with_windows" in updates:
            window_settings["autostart_with_windows"] = bool(
                updates["autostart_with_windows"]
            )
        settings["window"] = window_settings
        return _save_settings_unlocked(settings)


def load_minimize_to_tray() -> bool:
    """Load minimize-to-tray setting."""
    return bool(get_window_settings()["minimize_to_tray"])


def load_autostart_with_windows() -> bool:
    """Load start-with-Windows setting."""
    return bool(get_window_settings()["autostart_with_windows"])


def sync_autostart_on_launch() -> None:
    """Re-apply Run key from settings (repairs path after moves/reinstalls)."""
    from catswitch.autostart import sync_windows_autostart

    sync_windows_autostart(load_autostart_with_windows())


HOME_VIEW_FULL_WIDTH = 550
HOME_VIEW_FULL_HEIGHT = 440
HOME_VIEW_COMPACT_WIDTH = 490
HOME_VIEW_COMPACT_HEIGHT = 225


def load_home_compact_view() -> bool:
    window_settings = get_setting("window", {})
    return bool(window_settings.get("home_compact_view", False))


def save_home_compact_view(compact: bool) -> bool:
    with _settings_lock:
        settings = _load_settings_unlocked()
        window_settings = dict(settings.get("window") or {})
        window_settings["home_compact_view"] = compact
        settings["window"] = window_settings
        return _save_settings_unlocked(settings)


def get_home_view_size(compact: bool) -> tuple[int, int]:
    """Return logical window size for full or compact home view."""
    window_settings = get_setting("window", {})
    if compact:
        width = int(window_settings.get("compact_width", HOME_VIEW_COMPACT_WIDTH))
        height = int(window_settings.get("compact_height", HOME_VIEW_COMPACT_HEIGHT))
    else:
        width = int(window_settings.get("full_width", HOME_VIEW_FULL_WIDTH))
        height = int(window_settings.get("full_height", HOME_VIEW_FULL_HEIGHT))
    return width, height


def get_home_view_min_size() -> tuple[int, int]:
    """Minimum window size — must allow both full and compact modes."""
    full_w, full_h = get_home_view_size(False)
    compact_w, compact_h = get_home_view_size(True)
    return min(full_w, compact_w), min(full_h, compact_h)


def _normalize_detection_settings(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return detection settings with defaults applied."""
    merged = dict(DEFAULT_DETECTION_SETTINGS)
    if not raw:
        return merged

    default_category = raw.get("default_category")
    if isinstance(default_category, str) and default_category.strip():
        merged["default_category"] = default_category.strip()

    try:
        delay = float(raw.get("switch_delay_seconds", merged["switch_delay_seconds"]))
        merged["switch_delay_seconds"] = max(0.0, delay)
    except (TypeError, ValueError):
        pass

    if "auto_lock_category_on_manual_update" in raw:
        merged["auto_lock_category_on_manual_update"] = bool(
            raw.get("auto_lock_category_on_manual_update")
        )
    if "auto_lock_title_on_manual_update" in raw:
        merged["auto_lock_title_on_manual_update"] = bool(
            raw.get("auto_lock_title_on_manual_update")
        )
    if "use_discord_detectable" in raw:
        merged["use_discord_detectable"] = bool(raw.get("use_discord_detectable"))
    return merged


def get_detection_settings() -> Dict[str, Any]:
    """Load detection/category automation settings."""
    settings = load_settings()
    return _normalize_detection_settings(settings.get("detection"))


def save_detection_settings(updates: Dict[str, Any]) -> bool:
    """Merge and persist detection settings."""
    with _settings_lock:
        settings = _load_settings_unlocked()
        current = _normalize_detection_settings(settings.get("detection"))
        merged = dict(current)

        if "default_category" in updates:
            category = updates.get("default_category")
            if isinstance(category, str) and category.strip():
                merged["default_category"] = category.strip()

        if "switch_delay_seconds" in updates:
            try:
                delay = float(updates.get("switch_delay_seconds"))
                merged["switch_delay_seconds"] = max(0.0, delay)
            except (TypeError, ValueError):
                return False

        if "auto_lock_category_on_manual_update" in updates:
            merged["auto_lock_category_on_manual_update"] = bool(
                updates.get("auto_lock_category_on_manual_update")
            )
        if "auto_lock_title_on_manual_update" in updates:
            merged["auto_lock_title_on_manual_update"] = bool(
                updates.get("auto_lock_title_on_manual_update")
            )
        if "use_discord_detectable" in updates:
            merged["use_discord_detectable"] = bool(updates.get("use_discord_detectable"))

        settings["detection"] = merged
        return _save_settings_unlocked(settings)


def get_default_category() -> str:
    return get_detection_settings()["default_category"]


def get_switch_delay_seconds() -> float:
    return float(get_detection_settings()["switch_delay_seconds"])


def get_auto_lock_category_on_manual() -> bool:
    return bool(get_detection_settings()["auto_lock_category_on_manual_update"])


def get_auto_lock_title_on_manual() -> bool:
    return bool(get_detection_settings()["auto_lock_title_on_manual_update"])


def get_use_discord_detectable() -> bool:
    return bool(get_detection_settings()["use_discord_detectable"])


def get_theme() -> str:
    theme = get_setting("theme", DEFAULT_THEME)
    if not isinstance(theme, str) or not theme.strip():
        return DEFAULT_THEME
    return normalize_theme_filename(theme)


def save_theme(theme: str) -> bool:
    normalized = normalize_theme_filename(theme)
    return set_setting("theme", normalized)


def _theme_sort_key(name: str) -> tuple:
    if name.lower() == DEFAULT_THEME.lower():
        return (0, name.lower())
    return (1, name.lower())


def list_available_themes() -> List[Dict[str, str]]:
    """Return theme dropdown options from the AppData themes folder."""
    from catswitch.paths import get_themes_dir

    items: List[Dict[str, str]] = []
    themes_dir = get_themes_dir()
    if not os.path.isdir(themes_dir):
        return [{"value": DEFAULT_THEME, "label": "Default"}]

    for name in sorted(os.listdir(themes_dir), key=_theme_sort_key):
        if not name.lower().endswith(".css"):
            continue
        file_path = os.path.join(themes_dir, name)
        if not os.path.isfile(file_path):
            continue
        items.append({
            "value": name,
            "label": os.path.splitext(name)[0],
        })

    if not items:
        return [{"value": DEFAULT_THEME, "label": "Default"}]
    return items


# Initialize settings file when module is imported
ensure_app_data_layout()
initialize_settings() 