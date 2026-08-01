import os
import logging
import random
import re
import fnmatch
import requests
import tempfile
import shutil
from catswitch.list_format import (
    split_list_fields,
    join_list_fields,
    build_list_file_header,
)
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from catswitch.settings import (
    add_excluded_app_file,
    add_detected_app_file,
    remove_excluded_app_file,
    get_excluded_app_files,
    _paths_refer_to_same_file,
)
from catswitch.paths import get_detected_lists_dir, get_excluded_lists_dir

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('catswitch.excluded_apps')

# Loaded exclusion rules in list-priority order (first match wins for reporting).
# Each entry: executable (lower), list_name, line (raw text), line_number (1-based).
loaded_excluded_rules: List[Dict[str, object]] = []

LOCAL_EXCLUDED_FILENAME = 'Local.txt'
COMMON_EXCLUDED_FILENAME = 'Common.txt'
COMMON_EXCLUDED_DISPLAY_NAME = 'Common Apps'
AUTO_EXCLUDED_LIST_NAME = 'Auto-excluded apps'
DEFAULT_EXCLUDED_LOCAL_CONTENT = build_list_file_header("Custom Apps", "excluded")

# Path to store excluded app lists
def get_excluded_apps_dir() -> str:
    """Get the directory where excluded app lists are stored."""
    os.makedirs(get_excluded_lists_dir(), exist_ok=True)
    return get_excluded_lists_dir()

def get_excluded_local_file_path() -> str:
    """Return the path to the default excluded apps Local.txt file."""
    return os.path.join(get_excluded_apps_dir(), LOCAL_EXCLUDED_FILENAME)

def get_excluded_common_file_path() -> str:
    """Return the path to the seeded Common.txt excluded apps list."""
    return os.path.join(get_excluded_apps_dir(), COMMON_EXCLUDED_FILENAME)

def ensure_excluded_local_file() -> str:
    """Ensure excluded Local.txt exists and is registered in settings. Never overwrites."""
    excluded_apps_dir = get_excluded_apps_dir()
    local_file = get_excluded_local_file_path()

    if not os.path.exists(local_file):
        with open(local_file, 'x', encoding='utf-8') as f:
            f.write(DEFAULT_EXCLUDED_LOCAL_CONTENT)
        logger.info(f"Created excluded apps {LOCAL_EXCLUDED_FILENAME} at {local_file}")

    add_excluded_app_file(LOCAL_EXCLUDED_FILENAME, local_file, "local")
    return local_file


def ensure_excluded_common_file() -> Optional[str]:
    """Ensure bundled Common.txt is seeded and registered. Never overwrites."""
    from catswitch.paths import seed_bundled_excluded_lists

    seed_bundled_excluded_lists()
    common_file = get_excluded_common_file_path()
    if not os.path.exists(common_file):
        logger.warning("Bundled excluded list missing after seed: %s", common_file)
        return None

    display_name = COMMON_EXCLUDED_DISPLAY_NAME
    try:
        with open(common_file, 'r', encoding='utf-8', errors='replace') as handle:
            first_line = handle.readline().strip()
        if first_line.startswith('#'):
            header_name = first_line[1:].strip()
            if header_name:
                display_name = header_name
    except OSError as exc:
        logger.warning("Could not read Common.txt header: %s", exc)

    add_excluded_app_file(display_name, common_file, "local")
    return common_file


def _remove_stale_auto_excluded_registry_entry() -> None:
    """Drop a registry entry when the Auto-excluded apps file no longer exists."""
    entry = get_auto_excluded_list_entry()
    if not entry:
        return

    path = (entry.get('path') or '').strip()
    if path and os.path.exists(path):
        return

    if path:
        remove_excluded_app_file(path)
        return

    from catswitch.settings import mutate_settings

    def _apply(settings: dict):
        excluded_apps = dict(settings.get("excluded_apps") or {})
        lists = list(excluded_apps.get("lists", []))
        filtered = [item for item in lists if item.get("name") != AUTO_EXCLUDED_LIST_NAME]
        if len(filtered) == len(lists):
            return False
        excluded_apps["lists"] = filtered
        settings["excluded_apps"] = excluded_apps
        return True

    mutate_settings(_apply)


def ensure_auto_excluded_list_file() -> str:
    """Ensure the Auto-excluded apps list exists and return its path."""
    entry = get_auto_excluded_list_entry()
    if entry:
        path = entry.get('path') or ''
        if path and os.path.exists(path):
            return path
        _remove_stale_auto_excluded_registry_entry()

    success, file_path, error = create_new_file(AUTO_EXCLUDED_LIST_NAME, "excluded")
    if not success or not file_path:
        raise OSError(error or f"Failed to create {AUTO_EXCLUDED_LIST_NAME}")

    logger.info("Created excluded apps list '%s' at %s", AUTO_EXCLUDED_LIST_NAME, file_path)
    return file_path


def get_auto_excluded_list_entry() -> Optional[Dict[str, object]]:
    """Return settings metadata for the Auto-excluded apps list."""
    for list_info in get_excluded_app_files():
        if list_info.get('name') == AUTO_EXCLUDED_LIST_NAME:
            return list_info
    return None


def is_auto_excluded_list_enabled() -> bool:
    """True when the Auto-excluded apps list exists and is enabled."""
    entry = get_auto_excluded_list_entry()
    if not entry:
        return False
    return entry.get('enabled', True) is not False


def sync_auto_excluded_list_enabled(enabled: bool) -> None:
    """Set the Auto-excluded apps list enabled flag (no Discord setting changes)."""
    if enabled:
        try:
            ensure_auto_excluded_list_file()
        except OSError as exc:
            logger.error("Failed to ensure Auto-excluded apps list: %s", exc)
            return

    entry = get_auto_excluded_list_entry()
    if not entry:
        return

    path = entry.get('path') or ''
    if not path:
        return

    if entry.get('enabled', True) == enabled:
        return

    from catswitch.settings import set_excluded_app_list_enabled

    if set_excluded_app_list_enabled(path, enabled):
        reload_excluded_apps()


def disable_auto_exclusion_setting_only() -> None:
    """Turn off the detection setting without changing the Auto-excluded apps list."""
    from catswitch.settings import get_use_discord_detectable, save_detection_settings

    if get_use_discord_detectable():
        save_detection_settings({"use_discord_detectable": False})


def enable_auto_exclusion_setting_requires_list(*, reload_lists: bool = True) -> None:
    """
    When enabling the detection setting, the Auto-excluded apps list must be on too.
    """
    sync_auto_excluded_list_enabled(True)

    if reload_lists:
        reload_excluded_apps()


def repair_auto_exclusion_state_if_invalid() -> None:
    """
    When the detection setting is on, the Auto-excluded apps list must be enabled too.
    Missing lists are created on the next auto-exclude attempt instead.
    """
    from catswitch.settings import get_use_discord_detectable

    if not get_use_discord_detectable():
        return

    entry = get_auto_excluded_list_entry()
    if not entry or is_auto_excluded_list_enabled():
        return

    logger.info(
        "Auto-exclusion setting on but auto-excluded list disabled; enabling list"
    )
    sync_auto_excluded_list_enabled(True)


def matches_auto_excluded_list(path: str = "", url: str = "") -> bool:
    """True when path/url refers to the Auto-excluded apps list."""
    entry = get_auto_excluded_list_entry()
    if not entry:
        return False

    entry_path = (entry.get('path') or '').strip()
    entry_url = (entry.get('url') or '').strip()
    if url and entry_url:
        return url.strip() == entry_url
    if path and entry_path:
        return _paths_refer_to_same_file(path, entry_path)
    return False


def apply_auto_excluded_list_created_state(file_path: str) -> None:
    """Align a newly created Auto-excluded apps list with the detection setting."""
    from catswitch.settings import get_use_discord_detectable, set_excluded_app_list_enabled

    if get_use_discord_detectable():
        set_excluded_app_list_enabled(file_path, True)
    reload_excluded_apps()


_auto_excluded_processes: set[str] = set()


def add_to_auto_excluded_apps(
    process_name: str,
    process_path: str = "",
    window_title: str = "",
) -> Tuple[bool, Optional[str]]:
    """Append a failed non-game process to the Auto-excluded apps list."""
    from catswitch.settings import get_use_discord_detectable

    if not get_use_discord_detectable():
        return True, None

    entry = get_auto_excluded_list_entry()
    if entry and entry.get('enabled', True) is False:
        return True, None

    exclusion_rule = (process_name or '').strip().lower()
    if not exclusion_rule and process_path:
        exclusion_rule = os.path.basename(process_path).strip().lower()
    if not exclusion_rule:
        return False, "Process name is required"

    cache_key = exclusion_rule
    if cache_key in _auto_excluded_processes:
        return True, None

    try:
        list_path = ensure_auto_excluded_list_file()

        with open(list_path, 'r', encoding='utf-8') as f:
            content = f.read()

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            parts = split_list_fields(stripped, 1)
            existing_rule = (parts[0] if parts else '').strip().lower()
            if existing_rule.lstrip('!') == exclusion_rule:
                _auto_excluded_processes.add(cache_key)
                return True, None

        app_name = (window_title or process_name or exclusion_rule).strip()
        entry_line = join_list_fields(exclusion_rule, app_name)
        if not content.endswith('\n'):
            content += '\n'
        content += entry_line + '\n'

        with open(list_path, 'w', encoding='utf-8') as f:
            f.write(content)

        reload_excluded_apps()
        _auto_excluded_processes.add(cache_key)
        logger.info("Auto-excluded process %s in %s", exclusion_rule, AUTO_EXCLUDED_LIST_NAME)
        return True, None
    except Exception as exc:
        error_msg = f"Error adding to auto-excluded apps: {exc}"
        logger.error(error_msg)
        return False, error_msg


def remove_from_auto_excluded_app(process_name: str) -> bool:
    """
    Remove one auto-excluded entry for a process name, if present.

    Auto-exclude only ever stores at most one row per executable name.
    """
    if not is_auto_excluded_list_enabled():
        return False

    rule = (process_name or '').strip().lower()
    if not rule:
        return False

    try:
        list_path = ensure_auto_excluded_list_file()
    except OSError:
        return False

    if not os.path.exists(list_path):
        return False

    try:
        with open(list_path, 'r', encoding='utf-8') as f:
            content = f.read()

        new_lines = []
        removed = False

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                new_lines.append(line)
                continue

            parts = split_list_fields(stripped, 1)
            existing_rule = (parts[0] if parts else '').strip().lower().lstrip('!')
            if not removed and existing_rule == rule:
                removed = True
                _auto_excluded_processes.discard(rule)
                continue

            new_lines.append(line)

        if not removed:
            return False

        new_content = '\n'.join(new_lines)
        if new_content and not new_content.endswith('\n'):
            new_content += '\n'
        with open(list_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        reload_excluded_apps()
        logger.info("Removed auto-excluded entry for %s from %s", rule, AUTO_EXCLUDED_LIST_NAME)
        return True
    except Exception as exc:
        logger.error("Error removing from auto-excluded apps: %s", exc)
        return False


def remove_from_auto_excluded_apps(process_names: List[str]) -> int:
    """Remove auto-excluded entries for each process name (at most one per name)."""
    removed = 0
    seen = set()
    for name in process_names:
        key = (name or '').strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        if remove_from_auto_excluded_app(name):
            removed += 1
    return removed


def display_name_to_filename(display_name: str) -> str:
    """Convert a list display name into a safe lowercase filename stem."""
    slug = display_name.strip().lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = slug.strip('-')
    return slug or 'list'


def unique_list_filename(target_dir: str, display_name: str) -> str:
    """Build a unique .txt filename from a display name."""
    base = display_name_to_filename(display_name)
    filename = f"{base}.txt"
    if not os.path.exists(os.path.join(target_dir, filename)):
        return filename

    for _ in range(100):
        candidate = f"{base}-{random.randint(10000, 99999)}.txt"
        if not os.path.exists(os.path.join(target_dir, candidate)):
            return candidate

    raise OSError(f"Could not generate a unique filename for '{display_name}'")


def create_new_file(display_name: str, list_type: str = "excluded") -> Tuple[bool, str, Optional[str]]:
    """
    Create a new app list file from a display name.

    The file starts with a # header containing the display name. The filename is
    derived from that name and made unique within the target directory.
    """
    display_name = display_name.strip()
    if not display_name:
        return False, "", "List name is required"

    if list_type == "detected":
        target_dir = get_detected_lists_dir()
    else:
        target_dir = get_excluded_lists_dir()

    os.makedirs(target_dir, exist_ok=True)

    try:
        filename = unique_list_filename(target_dir, display_name)
        file_path = os.path.join(target_dir, filename)
        list_kind = "detected" if list_type == "detected" else "excluded"
        content = build_list_file_header(display_name, list_kind)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        if list_type == "excluded":
            add_excluded_app_file(display_name, file_path, "local")
            if display_name == AUTO_EXCLUDED_LIST_NAME:
                apply_auto_excluded_list_created_state(file_path)
        else:
            add_detected_app_file(display_name, file_path, "local")

        return True, file_path, None
    except Exception as e:
        error_msg = f"Error creating list: {str(e)}"
        logger.error(error_msg)
        return False, "", error_msg

def extract_list_name_from_content(content: str) -> Optional[str]:
    """Extract list display name from the first-line # header in list file content."""
    if not content:
        return None

    first_line = content.splitlines()[0].strip()
    if first_line.startswith('#'):
        name = first_line[1:].strip()
        return name or None
    return None


def resolve_url_list_name(content: str, url: str, custom_name: Optional[str] = None) -> str:
    """Resolve the display name for a URL-based list."""
    if custom_name and custom_name.strip():
        return custom_name.strip()

    baked_name = extract_list_name_from_content(content)
    if baked_name:
        return baked_name

    name = os.path.basename(url)
    if not name or not name.strip():
        name = "url_list"
    if not name.endswith(".txt"):
        name = f"{name}.txt"
    return name


def download_from_url(url: str, name: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
    """
    Download an excluded apps list from a URL.
    
    Args:
        url: URL to download from
        name: Optional name for the list (if not provided, uses filename from URL)
        
    Returns:
        Tuple of (success, path, error_message)
    """
    try:
        # Get filename from URL if not provided
        if not name:
            name = os.path.basename(url)
            if not name or not name.strip():
                name = "downloaded_list.txt"
                
        if not name.endswith(".txt"):
            name = f"{name}.txt"
            
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            error_msg = f"Failed to download list: Status code {response.status_code}"
            logger.error(error_msg)
            return False, "", error_msg
        
        # Check content type to ensure it's a text file
        content_type = response.headers.get('content-type', '').lower()
        if not any(text_type in content_type for text_type in ['text/plain', 'text/', 'application/octet-stream']):
            error_msg = f"Invalid content type: {content_type}. Expected text file (text/plain)."
            logger.error(error_msg)
            return False, "", error_msg
        
        # Additional validation: check if content looks like a text file
        content_preview = response.text[:200].lower()
        if any(html_indicator in content_preview for html_indicator in ['<html', '<!doctype', '<head', '<body', '<script', '<style']):
            error_msg = f"Content appears to be HTML, not a text file. Expected plain text format."
            logger.error(error_msg)
            return False, "", error_msg
            
        file_path = os.path.join(get_excluded_apps_dir(), name)
        
        with open(file_path, 'wb') as f:
            f.write(response.content)
            
        # Add to settings with URL source
        add_excluded_app_file(name, file_path, "url", url)
        return True, file_path, None
    except Exception as e:
        error_msg = f"Error downloading list: {str(e)}"
        logger.error(error_msg)
        return False, "", error_msg

def load_from_url_live(url: str) -> Tuple[bool, str, Optional[str]]:
    """
    Load excluded apps list content directly from URL without saving to disk.
    This is used for live loading of URL-based lists.
    
    Args:
        url: URL to load from
        
    Returns:
        Tuple of (success, content, error_message)
    """
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            error_msg = f"Failed to load list: Status code {response.status_code}"
            logger.error(error_msg)
            return False, "", error_msg
        
        # Check content type to ensure it's a text file
        content_type = response.headers.get('content-type', '').lower()
        if not any(text_type in content_type for text_type in ['text/plain', 'text/', 'application/octet-stream']):
            error_msg = f"Invalid content type: {content_type}. Expected text file (text/plain)."
            logger.error(error_msg)
            return False, "", error_msg
        
        # Additional validation: check if content looks like a text file
        content_preview = response.text[:200].lower()
        if any(html_indicator in content_preview for html_indicator in ['<html', '<!doctype', '<head', '<body', '<script', '<style']):
            error_msg = f"Content appears to be HTML, not a text file. Expected plain text format."
            logger.error(error_msg)
            return False, "", error_msg
            
        return True, response.text, None
    except Exception as e:
        error_msg = f"Error loading from URL: {str(e)}"
        logger.error(error_msg)
        return False, "", error_msg

def update_from_url(path: str) -> Tuple[bool, Optional[str]]:
    """
    Update an excluded apps list from its stored URL.
    
    Args:
        path: Path to the list to update
    
    Returns:
        Tuple of (success, error_message)
    """
    try:
        # Find the list in settings
        list_info = next((f for f in get_excluded_app_files() if f.get("path") == path), None)
        if not list_info:
            return False, "List not found in settings"
            
        url = list_info.get("url")
        if not url:
            return False, "No URL found for this list"
            
        # Download the list to a temporary location
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            error_msg = f"Failed to download list: Status code {response.status_code}"
            logger.error(error_msg)
            return False, error_msg
            
        # Write to the original path
        with open(path, 'wb') as f:
            f.write(response.content)
            
        return True, None
    except Exception as e:
        error_msg = f"Error updating list: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def delete_file(path: str, remove_from_disk: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Remove an excluded apps list from settings and optionally delete it.
    
    Args:
        path: Path to the list to remove
        remove_from_disk: Whether to also delete the file from disk
        
    Returns:
        Tuple of (success, error_message)
    """
    try:
        was_auto_excluded = matches_auto_excluded_list(path)

        # Remove from settings
        if not remove_excluded_app_file(path):
            return False, "Failed to remove list from settings"
            
        # Delete file if requested
        if remove_from_disk and os.path.exists(path):
            os.remove(path)

        if was_auto_excluded:
            reload_excluded_apps()

        return True, None
    except Exception as e:
        error_msg = f"Error deleting list: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def find_local_excluded_list(path: str) -> Optional[Dict[str, str]]:
    """Find a local excluded list entry by path, tolerating relative/absolute paths."""
    if not path:
        return None
    for lst in get_excluded_app_files():
        if lst.get('source') != 'local':
            continue
        if _paths_refer_to_same_file(lst.get('path', ''), path):
            return lst
    return None


def read_file_content(path: str) -> Tuple[bool, str, Optional[str]]:
    """
    Read the content of an excluded apps list.
    
    Args:
        path: Path to the list to read
        
    Returns:
        Tuple of (success, content, error_message)
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return True, content, None
    except Exception as e:
        error_msg = f"Error reading list: {str(e)}"
        logger.error(error_msg)
        return False, "", error_msg

def get_file_info(path: str) -> Optional[Dict[str, str]]:
    """
    Get information about an excluded apps list.
    
    Args:
        path: Path to the list
        
    Returns:
        Dict with list information or None if not found
    """
    return next((f for f in get_excluded_app_files() if f.get("path") == path), None)

def reload_excluded_apps() -> Tuple[bool, Optional[str]]:
    """
    Reload all excluded app lists into memory.
    
    Returns:
        Tuple of (success, error_message)
    """
    global loaded_excluded_rules
    
    try:
        loaded_excluded_rules = []
        
        # Get all lists from settings
        lists = get_excluded_app_files()
        
        # Process each list
        for list_info in lists:
            if list_info.get("enabled", True) is False:
                logger.info(f"Skipping disabled excluded apps list: {list_info.get('name', 'unknown')}")
                continue

            path = list_info.get("path")
            name = list_info.get("name", "unknown")
            source = list_info.get("source", "local")
            url = list_info.get("url")
            
            logger.info(f"Processing excluded apps list: {name} at {path} (source: {source})")
            
            content = None
            success = False
            error = None
            
            if source == "url" and url:
                # Load from URL live
                success, content, error = load_from_url_live(url)
                if success:
                    logger.info(f"Loaded {name} live from URL: {url}")
                else:
                    logger.error(f"Failed to load {name} from URL: {error}")
            elif path and os.path.exists(path):
                # Read from local file
                success, content, error = read_file_content(path)
                if success:
                    logger.info(f"Loaded {name} from local file")
                else:
                    logger.error(f"Failed to read {name}: {error}")
            else:
                logger.warning(f"Excluded apps list not found: {name} at {path}")
                continue
            
            # Parse and load the content
            if success and content:
                lines_loaded = 0
                # Parse and load each line (format: executable.exe;Description)
                for line_number, raw_line in enumerate(content.splitlines(), start=1):
                    line = raw_line.strip()
                    if line and not line.startswith('#'):
                        # Split by semicolon and get the executable name
                        parts = split_list_fields(line, 1)
                        raw_executable = parts[0].strip() if parts else ''
                        is_inverse = raw_executable.startswith('!')
                        executable = raw_executable[1:].strip() if is_inverse else raw_executable
                        if executable:
                            loaded_excluded_rules.append({
                                'executable': executable.lower(),
                                'is_inverse': is_inverse,
                                'list_name': name,
                                'line': raw_line.rstrip('\r\n'),
                                'line_number': line_number,
                            })
                            lines_loaded += 1
                logger.info(f"Loaded {lines_loaded} apps from {name}")
        
        logger.info(f"Reloaded {len(loaded_excluded_rules)} excluded apps")
        return True, None
    except Exception as e:
        error_msg = f"Error reloading excluded apps: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def _normalize_exclusion_rule_text(rule_text: str) -> str:
    """Strip a leading ! used for inverse (exception) exclusion rules."""
    rule = (rule_text or '').strip()
    if rule.startswith('!'):
        return rule[1:].strip()
    return rule


def _is_path_exclusion_rule(rule_text: str) -> bool:
    """True when a rule looks like a process path or wildcard pattern."""
    text = _normalize_exclusion_rule_text(rule_text)
    if not text:
        return False
    if '*' in text or '?' in text:
        return True
    return ':' in text or '\\' in text or '/' in text


def _path_pattern_has_segments(pattern: str) -> bool:
    """True when a pattern includes folder segments (not a bare glob like *.exe)."""
    normalized = pattern.replace('\\', '/')
    return '/' in normalized


def _split_path_segments(value: str) -> List[str]:
    normalized = value.replace('\\', '/').strip('/')
    if not normalized:
        return []
    return [part for part in normalized.split('/') if part]


def _match_path_segments(path_segments: List[str], pattern_segments: List[str]) -> bool:
    """Match path segments where * is one segment and ** spans folders."""

    def match_at(pi: int, pj: int) -> bool:
        while pj < len(pattern_segments):
            pat = pattern_segments[pj]
            if pat == '**':
                if pj == len(pattern_segments) - 1:
                    return True
                next_pj = pj + 1
                for skip in range(pi, len(path_segments) + 1):
                    if match_at(skip, next_pj):
                        return True
                return False
            if pi >= len(path_segments):
                return False
            if not fnmatch.fnmatchcase(path_segments[pi], pat):
                return False
            pi += 1
            pj += 1
        return pi == len(path_segments)

    return match_at(0, 0)


def _matches_exclusion_path_pattern(process_path: str, pattern: str) -> bool:
    """
    Match a process path against an exclusion path pattern.

    * and ? match within a single path segment. ** matches zero or more folders.
    Patterns without path separators (e.g. *.exe) still match the full path string.
    """
    process_path_normalized = process_path.replace('\\', '/')
    pattern_normalized = pattern.replace('\\', '/')

    if not _path_pattern_has_segments(pattern_normalized):
        return fnmatch.fnmatch(process_path_normalized, pattern_normalized)

    path_segments = _split_path_segments(process_path_normalized.lower())
    pattern_segments = _split_path_segments(pattern_normalized.lower())
    return _match_path_segments(path_segments, pattern_segments)


def _exclusion_rule_matches(rule_text: str, process_name: str, process_path: Optional[str] = None) -> bool:
    """Return True when an exclusion rule matches the running process."""
    rule = _normalize_exclusion_rule_text(rule_text).lower()
    if not rule:
        return False

    if _is_path_exclusion_rule(rule):
        if not process_path:
            return False
        return _matches_exclusion_path_pattern(process_path.lower(), rule)

    process_name_lower = (process_name or '').strip().lower()
    if not process_name_lower:
        return False

    return process_name_lower == rule or process_name_lower == os.path.basename(rule)


def _find_matching_inverse_exclusion_rule(
    process_name: str,
    process_path: Optional[str] = None,
) -> Optional[Dict[str, object]]:
    """Return the first inverse rule that exempts this process from exclusion."""
    for rule in loaded_excluded_rules:
        if not rule.get('is_inverse'):
            continue
        rule_text = str(rule.get('executable', ''))
        if _exclusion_rule_matches(rule_text, process_name, process_path):
            return rule
    return None


def find_exclusion_match(executable: str, process_path: Optional[str] = None) -> Optional[Dict[str, object]]:
    """
    Return the first matching exclusion rule for a process, or None.

    Rules may be executable names (e.g. SnippingTool.exe) or path patterns with
    wildcards. In path patterns, * matches within one folder segment; use **
    to match across subfolders (e.g. C:\\Games\\*.exe vs C:\\Games\\**\\*.exe).

    Prefix a rule with ! for an inverse exclude: matching processes are never
    excluded, even when another rule would match (e.g. !**\\Steam\\steamapps\\**
    exempts games under steamapps from a broader **\\Steam\\** rule).

    Detected apps take priority — if the executable is in the detected games
    list, no exclusion rule applies.
    """
    if not executable and not process_path:
        return None

    process_name = executable or (os.path.basename(process_path) if process_path else '')

    try:
        from catswitch.detected_apps import detected_entry_overrides_exclusion
        if detected_entry_overrides_exclusion(process_name, process_path):
            logger.debug(
                f"Detected app entry overrides exclusion for '{process_name}'"
            )
            return None
    except Exception as e:
        logger.warning(f"Error checking detected apps for '{process_name}': {e}")

    inverse_match = _find_matching_inverse_exclusion_rule(process_name, process_path)
    if inverse_match:
        logger.debug(
            f"App '{process_name}' exempted by inverse rule in {inverse_match.get('list_name')} "
            f"line {inverse_match.get('line_number')}: {inverse_match.get('line')}"
        )
        return None

    for rule in loaded_excluded_rules:
        if rule.get('is_inverse'):
            continue
        rule_text = str(rule.get('executable', ''))
        if _exclusion_rule_matches(rule_text, process_name, process_path):
            logger.debug(
                f"App '{process_name}' excluded by {rule.get('list_name')} "
                f"line {rule.get('line_number')}: {rule.get('line')}"
            )
            return rule

    return None


def is_app_excluded(executable: str, process_path: Optional[str] = None) -> bool:
    """Check if a process is in the excluded apps list."""
    return find_exclusion_match(executable, process_path) is not None


def format_exclusion_skip_message(executable: str, match: Dict[str, object]) -> str:
    """Build the console line for a skipped excluded application."""
    list_name = match.get('list_name', 'unknown list')
    line_number = match.get('line_number', '?')
    line_text = match.get('line', '')
    return (
        f"Skipping excluded application: {executable} "
        f"({list_name}, line {line_number}: {line_text})"
    ) 