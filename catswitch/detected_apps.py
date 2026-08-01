"""
Detected Apps Management Module

This module handles the management of detected applications and their associated
Twitch categories for faster lookup in the future.
"""

import os
import logging
import threading
from difflib import SequenceMatcher
from typing import List, Dict, Optional, Tuple

from catswitch.list_format import (
    split_list_fields,
    join_list_fields,
    format_detected_app_line,
    split_window_titles,
    join_window_titles,
    build_list_file_header,
)
from catswitch.paths import get_detected_lists_dir

logger = logging.getLogger(__name__)

# Global storage for detected apps
loaded_detected_apps: Dict[str, Dict[str, str]] = {}

LOCAL_DETECTED_FILENAME = 'Local.txt'
LOCAL_DETECTED_LIST_NAME = 'Detected Games List'
DEFAULT_DETECTED_LOCAL_CONTENT = build_list_file_header(LOCAL_DETECTED_LIST_NAME, "detected")

def get_detected_apps_dir() -> str:
    """Get the directory path for detected apps list files."""
    os.makedirs(get_detected_lists_dir(), exist_ok=True)
    return get_detected_lists_dir()

def get_detected_local_file_path() -> str:
    """Return the path to the default detected apps Local.txt file."""
    return os.path.join(get_detected_apps_dir(), LOCAL_DETECTED_FILENAME)

def ensure_detected_local_file() -> str:
    """Ensure detected Local.txt exists and is registered in settings. Never overwrites."""
    detected_apps_dir = get_detected_apps_dir()
    os.makedirs(detected_apps_dir, exist_ok=True)
    local_file = get_detected_local_file_path()

    if not os.path.exists(local_file):
        with open(local_file, 'x', encoding='utf-8') as f:
            f.write(DEFAULT_DETECTED_LOCAL_CONTENT)
        logger.info(f"Created detected apps {LOCAL_DETECTED_FILENAME} at {local_file}")

    from catswitch.settings import add_detected_app_file
    add_detected_app_file(LOCAL_DETECTED_LIST_NAME, local_file, "local")
    return local_file

def is_detected_local_save_enabled() -> bool:
    """Return True when the default Local.txt list is enabled and can accept saves."""
    from catswitch.settings import get_detected_app_files, _paths_refer_to_same_file

    local_file = get_detected_local_file_path()
    for lst in get_detected_app_files():
        if _paths_refer_to_same_file(lst.get("path", ""), local_file):
            return lst.get("enabled", True) is not False
    return False

def normalize_utf8_string(s: str) -> str:
    """Normalize a string that might have UTF-8 encoding issues."""
    try:
        # If the string contains double-encoded UTF-8, fix it
        if 'Â' in s and any(char in s for char in ['²', '³', '¹', '°', '±']):
            # This looks like double-encoded UTF-8, try to fix it
            try:
                # First, encode as latin-1 then decode as utf-8
                fixed = s.encode('latin-1').decode('utf-8')
                return fixed
            except (UnicodeDecodeError, UnicodeEncodeError):
                # If that fails, return the original string
                return s
        return s
    except Exception:
        return s

WINDOW_TITLE_MATCH_THRESHOLD = 0.6

def compute_window_title_score(current_title: str, stored_title: str) -> float:
    """Combined window title similarity score in the range 0.0-1.0."""
    current = (current_title or "").lower()
    stored = (stored_title or "").lower()
    if not current or not stored:
        return 0.0
    if current == stored:
        return 1.0

    similarity = SequenceMatcher(None, current, stored).ratio()
    if current in stored or stored in current:
        length_ratio = min(len(current), len(stored)) / max(len(current), len(stored))
        if length_ratio > 0.6:
            return 0.9
        return similarity

    stored_words = set(stored.split())
    current_words = set(current.split())
    word_score = len(stored_words.intersection(current_words)) / len(stored_words) if stored_words else 0
    length_ratio = min(len(current), len(stored)) / max(len(current), len(stored))
    length_penalty = 1.0 if length_ratio > 0.5 else length_ratio * 2
    return (similarity * 0.5) + (word_score * 0.3) + (length_penalty * 0.2)

def window_titles_compatible(current_title: str, stored_title: str, threshold: float = WINDOW_TITLE_MATCH_THRESHOLD) -> bool:
    """Return True when stored and current window titles are similar enough to trust a saved mapping."""
    if not stored_title:
        return True
    if not current_title:
        return False
    return compute_window_title_score(current_title, stored_title) > threshold


def entry_titles_compatible(current_title: str, info: Dict[str, str]) -> bool:
    """True when an entry's stored titles accept the current window title.

    Entries with no stored titles are match-any wildcards. Otherwise the current
    title must be exactly equal or fuzzy-compatible with at least one stored title.
    """
    titles = entry_window_titles(info)
    if not titles:
        return True
    current = (current_title or '').strip()
    if not current:
        return False
    current_lower = current.lower()
    return any(
        t.lower() == current_lower or window_titles_compatible(current, t)
        for t in titles
    )

def parse_detected_app_line(line: str, file_path: str = "", list_name: str = "") -> Optional[Dict[str, str]]:
    """Parse one detected-apps file line into an app dict, or None if invalid/comment."""
    line = line.strip()
    if not line or line.startswith('#'):
        return None

    parts = split_list_fields(line, 4)  # process_path;app_name;twitch_category;window_title[;box_art_url]
    if len(parts) < 3 or not parts[0].strip():
        return None

    process_path = parts[0].strip()
    app_name = normalize_utf8_string(parts[1].strip() if len(parts) > 1 else "")
    twitch_category = normalize_utf8_string(parts[2].strip() if len(parts) > 2 else "")
    window_title = normalize_utf8_string(parts[3].strip() if len(parts) > 3 else "")

    app = {
        'process_path': process_path,
        'app_name': app_name,
        'twitch_category': twitch_category,
        'window_title': window_title,
        'window_titles': split_window_titles(window_title),
    }
    if file_path:
        app['file_path'] = file_path
    if list_name:
        app['list_name'] = list_name
    return app


def _parsed_window_title_from_parts(parts: List[str]) -> str:
    """Extract window title from list fields."""
    if len(parts) < 4:
        return ""
    return normalize_utf8_string(parts[3].strip())


def attach_cached_box_art_urls(apps: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Attach already-cached box art URLs without downloading."""
    if not apps:
        return apps
    try:
        from catswitch import category_cache
        for app in apps:
            category_cache.enrich_app_dict(app, fetch_if_missing=False)
    except Exception as exc:
        logger.warning(f"Failed to attach cached box art URLs: {exc}")
    return apps

def read_file_content(file_path: str) -> Tuple[bool, str, Optional[str]]:
    """Read content from a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return True, content, None
    except Exception as e:
        error_msg = f"Error reading file {file_path}: {str(e)}"
        logger.error(error_msg)
        return False, "", error_msg

def write_file_content(file_path: str, content: str) -> Tuple[bool, Optional[str]]:
    """Write content to a file."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, None
    except Exception as e:
        error_msg = f"Error writing file {file_path}: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def load_detected_apps() -> Tuple[bool, Optional[str]]:
    """Load detected apps from configured lists in priority order (top list wins duplicates)."""
    try:
        from catswitch.settings import get_detected_app_files
        from catswitch.excluded_apps import load_from_url_live

        # Build into a fresh dict, then swap contents in place: other modules
        # import loaded_detected_apps by name, so the dict object must not be
        # replaced or their references go stale.
        new_apps: Dict[str, Dict[str, str]] = {}
        lists = get_detected_app_files()

        for list_info in lists:
            if list_info.get("enabled", True) is False:
                logger.info(f"Skipping disabled detected apps list: {list_info.get('name', 'unknown')}")
                continue

            path = list_info.get("path")
            name = list_info.get("name", "unknown")
            source = list_info.get("source", "local")
            url = list_info.get("url")
            content = None

            if source == "url" and url:
                success, content, error = load_from_url_live(url)
                if not success:
                    logger.error(f"Failed to load {name} from URL: {error}")
                    continue
            elif path and os.path.exists(path):
                success, content, error = read_file_content(path)
                if not success:
                    logger.error(f"Failed to read {name}: {error}")
                    continue
            else:
                logger.warning(f"Detected apps list not found: {name} at {path}")
                continue

            logger.info(f"Processing detected apps list: {name}")
            lines_loaded = 0
            for line in content.splitlines():
                app = parse_detected_app_line(line, file_path=path or "", list_name=name)
                if not app:
                    continue
                cache_key = f"{app['process_path'].lower()}|{app['window_title']}"
                if cache_key in new_apps:
                    continue
                new_apps[cache_key] = app
                lines_loaded += 1

            logger.info(f"Loaded {lines_loaded} detected apps from {name}")

        loaded_detected_apps.clear()
        loaded_detected_apps.update(new_apps)
        logger.info(f"Loaded {len(loaded_detected_apps)} total detected apps")

        try:
            from catswitch import category_cache
            needed = category_cache.collect_needed_categories(loaded_detected_apps)
            category_cache.prune_unused(needed)

            def _warm_detected_game_art() -> None:
                try:
                    category_cache.prefetch_categories_for_apps(loaded_detected_apps)
                    for info in loaded_detected_apps.values():
                        category_cache.enrich_app_dict(info, fetch_if_missing=False)
                    logger.info("Prefetched box art for detected game categories")
                except Exception as exc:
                    logger.error(f"Error prefetching detected game box art: {exc}")

            threading.Thread(target=_warm_detected_game_art, daemon=True).start()
        except Exception as exc:
            logger.error(f"Error syncing category box art cache: {exc}")

        try:
            from catswitch import title_presets
            title_presets.sync_with_detected_apps(loaded_detected_apps)
        except Exception as e:
            logger.error(f"Error syncing title presets after reload: {e}")

        return True, None
    except Exception as e:
        error_msg = f"Error loading detected apps: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def save_detected_app(process_path: str, app_name: str, twitch_category: str, window_title: str = "") -> Tuple[bool, Optional[str]]:
    """Save a detected app to the local file."""
    try:
        local_file = ensure_detected_local_file()

        if not is_detected_local_save_enabled():
            logger.info("Skipping save: Local.txt is disabled")
            return True, None
        
        # Read existing content
        success, content, error = read_file_content(local_file)
        if not success:
            return False, error
        
        # Check if entry already exists with the same window title
        process_path_lower = process_path.lower()
        lines = content.splitlines()
        new_lines = []
        entry_updated = False
        
        for line in lines:
            if line.strip() and not line.startswith('#'):
                parts = split_list_fields(line, 4)
                if len(parts) >= 1 and parts[0].strip().lower() == process_path_lower:
                    existing_window_title = _parsed_window_title_from_parts(parts)
                    if existing_window_title == window_title:
                        new_line = format_detected_app_line(process_path, app_name, twitch_category, window_title)
                        new_lines.append(new_line)
                        entry_updated = True
                    else:
                        # Keep existing entry with different window title
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        # Add new entry if not updated (new window title for same process)
        if not entry_updated:
            new_line = format_detected_app_line(process_path, app_name, twitch_category, window_title)
            new_lines.append(new_line)
        
        # Write back to file
        new_content = '\n'.join(new_lines)
        success, error = write_file_content(local_file, new_content)
        if not success:
            return False, error
        
        # Update in-memory cache - create a unique key for this entry
        cache_key = f"{process_path_lower}|{window_title}"
        loaded_detected_apps[cache_key] = {
            'process_path': process_path,  # Keep original case
            'app_name': app_name,
            'twitch_category': twitch_category,
            'window_title': window_title,
            'window_titles': split_window_titles(window_title),
            'file_path': local_file,
            'list_name': _resolve_list_name_for_file(local_file),
        }
        try:
            from catswitch import category_cache
            category_cache.enrich_app_dict(loaded_detected_apps[cache_key])
        except Exception as exc:
            logger.warning(f"Failed to resolve box art after save: {exc}")
        
        logger.info(f"Saved detected app: {process_path} -> {twitch_category}")
        return True, None
    except Exception as e:
        error_msg = f"Error saving detected app: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def get_detected_list_info_by_path(file_path: str) -> Optional[Dict[str, str]]:
    """Return settings metadata for a detected apps list file."""
    from catswitch.settings import get_detected_app_files, _paths_refer_to_same_file

    for lst in get_detected_app_files():
        if _paths_refer_to_same_file(lst.get("path", ""), file_path):
            return lst
    return None

def _resolve_list_name_for_file(file_path: str) -> str:
    """Resolve the display name for a detected apps list file."""
    if not file_path:
        return 'Unknown List'

    info = get_detected_list_info_by_path(file_path)
    if info and info.get('name'):
        return info['name']

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            first_line = f.readline().strip()
            if first_line.startswith('#'):
                name = first_line[1:].strip()
                if name:
                    return name
    except Exception:
        pass

    return 'Unknown List'

def is_detected_list_writable(file_path: str) -> bool:
    """Return True when a detected list can be edited on disk."""
    info = get_detected_list_info_by_path(file_path)
    if not info:
        return False
    if info.get("enabled", True) is False:
        return False
    if info.get("source") == "url":
        return False
    resolved = info.get("path", "")
    return bool(resolved and os.path.exists(resolved))

def add_detected_app_to_file(
    process_path: str,
    app_name: str,
    twitch_category: str,
    window_title: str,
    file_path: str,
) -> Tuple[bool, Optional[str]]:
    """Add or update a detected app entry in a specific local list file."""
    try:
        if not is_detected_list_writable(file_path):
            return False, "Target list is not writable"

        list_info = get_detected_list_info_by_path(file_path)
        target_file = list_info.get("path", file_path) if list_info else file_path

        success, content, error = read_file_content(target_file)
        if not success:
            return False, error

        process_path_lower = process_path.lower()
        lines = content.splitlines()
        new_lines = []
        entry_updated = False

        for line in lines:
            if line.strip() and not line.startswith('#'):
                parts = split_list_fields(line, 4)
                if len(parts) >= 1 and parts[0].strip().lower() == process_path_lower:
                    existing_window_title = _parsed_window_title_from_parts(parts)
                    if existing_window_title == window_title:
                        new_line = format_detected_app_line(
                            process_path, app_name, twitch_category, window_title
                        )
                        new_lines.append(new_line)
                        entry_updated = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        if not entry_updated:
            new_line = format_detected_app_line(
                process_path, app_name, twitch_category, window_title
            )
            new_lines.append(new_line)

        new_content = '\n'.join(new_lines)
        success, error = write_file_content(target_file, new_content)
        if not success:
            return False, error

        cache_key = f"{process_path_lower}|{window_title}"
        loaded_detected_apps[cache_key] = {
            'process_path': process_path,
            'app_name': app_name,
            'twitch_category': twitch_category,
            'window_title': window_title,
            'window_titles': split_window_titles(window_title),
            'file_path': target_file,
            'list_name': _resolve_list_name_for_file(target_file),
        }
        try:
            from catswitch import category_cache
            category_cache.enrich_app_dict(loaded_detected_apps[cache_key])
        except Exception as exc:
            logger.warning(f"Failed to resolve box art after add: {exc}")

        logger.info(f"Saved detected app to {target_file}: {process_path} -> {twitch_category}")
        return True, None
    except Exception as e:
        error_msg = f"Error adding detected app to file: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def move_detected_app_between_lists(
    process_path: str,
    app_name: str,
    twitch_category: str,
    window_title: str,
    source_file_path: str,
    target_file_path: str,
) -> Tuple[bool, Optional[str]]:
    """Move a detected app from one local list file to another."""
    from catswitch.settings import _paths_refer_to_same_file

    if _paths_refer_to_same_file(source_file_path, target_file_path):
        return True, None

    if not is_detected_list_writable(source_file_path):
        return False, "Source list is not writable"
    if not is_detected_list_writable(target_file_path):
        return False, "Target list is not writable"

    # Keep the title preset assignment: the fingerprint ignores the list file,
    # so it stays valid after the move.
    success, error = remove_detected_app_from_file(
        process_path, source_file_path, app_name, twitch_category, window_title,
        unassign_titles=False,
    )
    if not success:
        return False, error

    return add_detected_app_to_file(
        process_path, app_name, twitch_category, window_title, target_file_path
    )

def is_process_name_in_detected_apps(process_name: str) -> bool:
    """Check if a process name exists in the detected apps list."""
    try:
        process_name_lower = process_name.lower()
        for key, info in loaded_detected_apps.items():
            # Check both app_name and process_name fields
            app_name = info.get('app_name', '').lower()
            process_path = info.get('process_path', '')
            process_name_from_path = os.path.basename(process_path).lower()
            
            if app_name == process_name_lower or process_name_from_path == process_name_lower:
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking process name in detected apps: {str(e)}")
        return False


def saved_app_path_matches(process_path: str, detected_app: Dict[str, str]) -> bool:
    """True when the running process path matches a saved detected-app entry."""
    detected_path = detected_app.get('process_path', '').lower()
    process_path_lower = process_path.lower()
    if detected_path == process_path_lower:
        return True
    if '*' in detected_path:
        return _matches_wildcard_pattern(process_path_lower, detected_path)
    return False


def entry_window_titles(info: Dict[str, str]) -> List[str]:
    """Return the parsed list of window titles for an entry (parses lazily if needed)."""
    titles = info.get('window_titles')
    if titles is None:
        titles = split_window_titles(info.get('window_title', ''))
        info['window_titles'] = titles
    return titles


def find_matching_detected_app_by_window_title(process_name: str, process_path: str, window_title: str) -> Optional[Dict[str, str]]:
    """
    Find a saved detected app when the install path matches and the window title agrees.

    Only entries whose process_path matches the running process (exact or wildcard) are
    considered. Among those, matching is tiered:
      1. exact title match (case-insensitive) against any stored title,
      2. best fuzzy title match above the threshold,
      3. entries without stored titles act as match-any wildcards.
    Entries with stored titles that all reject the current title do NOT match, so a
    fresh detection can run (and merge/create via record_detection_result).
    """
    try:
        logger.debug(f"Window title matching: process={process_name}, path={process_path}, window={window_title}")

        matching_apps = []
        for info in loaded_detected_apps.values():
            if saved_app_path_matches(process_path, info):
                matching_apps.append(info)
                logger.debug(
                    f"Path match: {info.get('process_path')} -> "
                    f"{info.get('twitch_category')} (titles: {entry_window_titles(info)})"
                )

        if not matching_apps:
            logger.debug("No saved app with a matching process path")
            return None

        current = (window_title or '').strip()
        current_lower = current.lower()

        # Tier 1: exact title match, in list priority order
        if current_lower:
            for app in matching_apps:
                if any(t.lower() == current_lower for t in entry_window_titles(app)):
                    logger.debug(f"Exact window title match: {app.get('twitch_category')}")
                    return app

        # Tier 2: best fuzzy title match above threshold
        if current:
            best_app = None
            best_score = WINDOW_TITLE_MATCH_THRESHOLD
            for app in matching_apps:
                for stored in entry_window_titles(app):
                    score = compute_window_title_score(current, stored)
                    if score > best_score:
                        best_score = score
                        best_app = app
            if best_app:
                logger.debug(
                    f"Fuzzy window title match: {best_app.get('twitch_category')} "
                    f"(score: {best_score:.2f})"
                )
                return best_app

        # Tier 3: entries without stored titles match any window title
        for app in matching_apps:
            if not entry_window_titles(app):
                logger.debug(f"Wildcard (no stored titles) match: {app.get('twitch_category')}")
                return app

        logger.debug("Path matched but no window title agreed — deferring to detection")
        return None

    except Exception as e:
        logger.error(f"Error finding matching detected app by window title: {str(e)}")
        return None


MAX_WINDOW_TITLES_PER_ENTRY = 8


def _rewrite_entry_window_titles(entry: Dict[str, str], new_titles: List[str]) -> Tuple[bool, Optional[str]]:
    """Rewrite the window-title field of an existing entry's line in its list file."""
    file_path = entry.get('file_path', '')
    success, content, error = read_file_content(file_path)
    if not success:
        return False, error

    entry_path_lower = entry.get('process_path', '').lower()
    entry_title_field = entry.get('window_title', '')
    entry_category = entry.get('twitch_category', '')
    new_title_field = join_window_titles(new_titles)

    lines = content.splitlines()
    new_lines = []
    updated = False

    for line in lines:
        if not updated and line.strip() and not line.startswith('#'):
            parts = split_list_fields(line, 4)
            if len(parts) >= 3:
                line_path = parts[0].strip().lower()
                line_category = parts[2].strip()
                line_title_field = _parsed_window_title_from_parts(parts)
                if (
                    line_path == entry_path_lower
                    and line_category == entry_category
                    and line_title_field == entry_title_field
                ):
                    new_lines.append(format_detected_app_line(
                        parts[0].strip(),
                        parts[1].strip() if len(parts) > 1 else entry.get('app_name', ''),
                        line_category,
                        new_title_field,
                    ))
                    updated = True
                    continue
        new_lines.append(line)

    if not updated:
        return False, "Entry line not found for window title update"

    success, error = write_file_content(file_path, '\n'.join(new_lines))
    if not success:
        return False, error

    old_key = f"{entry_path_lower}|{entry_title_field}"
    loaded_detected_apps.pop(old_key, None)

    try:
        from catswitch import title_presets
        old_fp = title_presets.entry_fingerprint(entry)
        entry['window_title'] = new_title_field
        entry['window_titles'] = list(new_titles)
        title_presets.migrate_fingerprint(old_fp, title_presets.entry_fingerprint(entry))
    except Exception as e:
        entry['window_title'] = new_title_field
        entry['window_titles'] = list(new_titles)
        logger.error(f"Error migrating title preset assignment: {e}")

    loaded_detected_apps[f"{entry_path_lower}|{new_title_field}"] = entry

    logger.info(f"Appended window title for {entry.get('twitch_category')}: {new_titles[-1]}")
    return True, None


def record_detection_result(process_path: str, window_title: str, twitch_category: str) -> Tuple[bool, Optional[str]]:
    """
    Persist the outcome of a fresh game detection.

    If a path-matching entry already has the detected category, the current window
    title is appended to that entry as an alternative title. Otherwise a new entry
    (path + title + category) is created in Local.txt.

    When multiple exes in the same folder were seen this session, the first confident
    match is saved as a folder *.exe wildcard with an empty window title.
    """
    try:
        if not process_path or not twitch_category:
            return True, None

        from catswitch.folder_chain import (
            get_chain_for_path,
            mark_chain_after_save,
            resolve_detection_save_target,
        )

        chain = get_chain_for_path(process_path)
        save_path, title = resolve_detection_save_target(chain, process_path, window_title)
        category_lower = twitch_category.strip().lower()

        target = None
        for info in loaded_detected_apps.values():
            if not saved_app_path_matches(process_path, info):
                continue
            if info.get('twitch_category', '').strip().lower() == category_lower:
                target = info
                break

        if target is not None:
            titles = entry_window_titles(target)
            if not titles:
                mark_chain_after_save(chain, target.get('process_path', save_path), twitch_category)
                return True, None
            if not title:
                mark_chain_after_save(chain, target.get('process_path', save_path), twitch_category)
                return True, None
            if any(t.lower() == title.lower() for t in titles):
                mark_chain_after_save(chain, target.get('process_path', save_path), twitch_category)
                return True, None
            if len(titles) >= MAX_WINDOW_TITLES_PER_ENTRY:
                logger.info(
                    f"Title cap reached for {target.get('twitch_category')} "
                    f"({MAX_WINDOW_TITLES_PER_ENTRY}); not adding '{title}'"
                )
                mark_chain_after_save(chain, target.get('process_path', save_path), twitch_category)
                return True, None
            if not is_detected_list_writable(target.get('file_path', '')):
                result = save_detected_app(save_path, '', twitch_category, title)
                if result[0]:
                    mark_chain_after_save(chain, save_path, twitch_category)
                return result
            rewrite_result = _rewrite_entry_window_titles(target, titles + [title])
            if rewrite_result[0]:
                mark_chain_after_save(chain, target.get('process_path', save_path), twitch_category)
            return rewrite_result

        result = save_detected_app(save_path, '', twitch_category, title)
        if result[0]:
            mark_chain_after_save(chain, save_path, twitch_category)
            if '*' in save_path:
                from catswitch.folder_chain import cleanup_auto_excluded_for_wildcard_chain
                cleanup_auto_excluded_for_wildcard_chain(chain)
        return result

    except Exception as e:
        error_msg = f"Error recording detection result: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def find_matching_detected_app(process_name: str, process_path: str) -> Optional[Dict[str, str]]:
    r"""
    Find a matching detected app using partial matching logic with wildcard support.
    
    Args:
        process_name: The executable name (e.g., "Game.exe")
        process_path: The full process path (e.g., "C:\Games\Steam\steamapps\common\Game\Game.exe")
        
    Returns:
        The matching detected app info if found, None otherwise
    """
    try:
        process_name_lower = process_name.lower()
        process_path_lower = process_path.lower()
        
        for info in loaded_detected_apps.values():
            detected_path = info.get('process_path', '').lower()
            app_name = info.get('app_name', '').lower()
            
            # Check for exact path match first
            if detected_path == process_path_lower:
                logger.debug(f"Exact path match found: {detected_path}")
                return info
            
            # Check for wildcard pattern match
            if '*' in detected_path:
                if _matches_wildcard_pattern(process_path_lower, detected_path):
                    logger.debug(f"Wildcard pattern match found: {detected_path} matches {process_path}")
                    return info
            
            # Check for exact executable name match
            detected_name = os.path.basename(detected_path)
            if detected_name == process_name_lower:
                logger.debug(f"Exact executable name match found: {detected_name}")
                return info
            
            # Check for partial path match
            # If the detected path contains forward slashes or backslashes, it's a partial path
            if '/' in detected_path or '\\' in detected_path:
                # Extract the relevant part of the current process path
                # For Steam games: Steam/steamapps/common/Game/Game.exe
                # We want to match the part after the last "steamapps" or similar
                path_parts = detected_path.split('/') if '/' in detected_path else detected_path.split('\\')
                
                # Find the matching part in the current process path
                current_parts = process_path_lower.split('/') if '/' in process_path_lower else process_path_lower.split('\\')
                
                # Check if the detected path parts match the end of the current path
                if len(path_parts) <= len(current_parts):
                    # Check if the last N parts match
                    if current_parts[-len(path_parts):] == path_parts:
                        logger.debug(f"Partial path match found: {detected_path} matches {process_path}")
                        return info
            
            # Check for app name match (if different from executable name)
            if app_name and app_name == process_name_lower:
                logger.debug(f"App name match found: {app_name}")
                return info
                
        return None
    except Exception as e:
        logger.error(f"Error finding matching detected app: {str(e)}")
        return None


def detected_entry_overrides_exclusion(process_name: str, process_path: Optional[str] = None) -> bool:
    """Return True when a saved detected-app entry should beat an exclusion rule."""
    if process_path:
        return find_matching_detected_app(process_name, process_path) is not None
    if process_name:
        return is_process_name_in_detected_apps(process_name)
    return False


def _matches_wildcard_pattern(process_path: str, pattern: str) -> bool:
    r"""
    Check if a process path matches a wildcard pattern.
    
    Args:
        process_path: The actual process path (e.g., "C:\Steam\steamapps\common\Game\Game.exe")
        pattern: The wildcard pattern (e.g., "C:\Steam\steamapps\Game\*.exe" or "C:\Steam\*\game.exe")
        
    Returns:
        True if the path matches the pattern, False otherwise
    """
    try:
        import fnmatch
        
        # Normalize paths to use forward slashes for consistent matching
        process_path_normalized = process_path.replace('\\', '/')
        pattern_normalized = pattern.replace('\\', '/')

        # Same-folder *.exe wildcard (direct siblings only)
        if pattern_normalized.lower().endswith('/*.exe'):
            folder_pattern = pattern_normalized[:-len('/*.exe')]
            if '/' in process_path_normalized:
                proc_dir = process_path_normalized.rsplit('/', 1)[0]
            else:
                proc_dir = ''
            if proc_dir.lower() != folder_pattern.lower():
                return False
            return process_path_normalized.lower().endswith('.exe')
        
        # Use fnmatch for wildcard pattern matching
        return fnmatch.fnmatch(process_path_normalized, pattern_normalized)
        
    except Exception as e:
        logger.error(f"Error in wildcard pattern matching: {str(e)}")
        return False


def _remove_detected_app_entries_by_path(process_path: str) -> int:
    """Remove every detected-app entry matching process_path (any window title)."""
    local_file = ensure_detected_local_file()
    if not os.path.exists(local_file):
        return 0

    success, content, error = read_file_content(local_file)
    if not success:
        logger.error(f"Failed to read detected apps while removing path entries: {error}")
        return 0

    process_path_lower = process_path.lower().replace('\\', '/')
    new_lines = []
    removed = 0

    for line in content.splitlines():
        if line.strip() and not line.startswith('#'):
            parts = split_list_fields(line, 4)
            if parts:
                line_path = parts[0].strip().replace('\\', '/').lower()
                if line_path == process_path_lower:
                    removed += 1
                    continue
        new_lines.append(line)

    if removed:
        write_file_content(local_file, '\n'.join(new_lines))

    keys_to_delete = [
        key for key, info in loaded_detected_apps.items()
        if (info.get('process_path') or '').lower().replace('\\', '/') == process_path_lower
    ]
    for key in keys_to_delete:
        loaded_detected_apps.pop(key, None)

    return removed


def upgrade_detected_app_to_folder_wildcard(
    exact_process_path: str,
    twitch_category: str,
) -> Tuple[bool, Optional[str]]:
    """
    Replace an exact-path detected-app entry with a same-folder *.exe wildcard.

    Window title is cleared so any exe in that folder matches.
    """
    from catswitch.folder_chain import folder_exe_wildcard_path

    if not exact_process_path or not twitch_category:
        return False, "Process path and Twitch category are required"

    wildcard_path = folder_exe_wildcard_path(exact_process_path)
    removed = _remove_detected_app_entries_by_path(exact_process_path)
    result = save_detected_app(wildcard_path, '', twitch_category, '')
    if result[0]:
        from catswitch.folder_chain import (
            get_chain_for_path,
            mark_chain_after_save,
            cleanup_auto_excluded_for_wildcard_chain,
        )

        chain = get_chain_for_path(exact_process_path)
        mark_chain_after_save(chain, wildcard_path, twitch_category)
        cleanup_auto_excluded_for_wildcard_chain(chain)
    return result

def get_all_detected_apps() -> List[Dict[str, str]]:
    """Get all detected apps as a list."""
    apps = []
    for info in loaded_detected_apps.values():
        file_path = info.get('file_path', '')
        list_name = info.get('list_name') or _resolve_list_name_for_file(file_path)
        if list_name and not info.get('list_name'):
            info['list_name'] = list_name
        apps.append({
            'process_path': info.get('process_path', ''),
            'app_name': info.get('app_name', ''),
            'twitch_category': info.get('twitch_category', ''),
            'window_title': info.get('window_title', ''),
            'file_path': file_path,
            'list_name': list_name,
        })
    return attach_cached_box_art_urls(apps)

def remove_detected_app(process_path: str, app_name: str = "", twitch_category: str = "", window_title: str = "") -> Tuple[bool, Optional[str]]:
    """Remove a detected app from the local file using ALL identifying fields (Title, Category, Location, Window Title)."""
    try:
        detected_apps_dir = get_detected_apps_dir()
        local_file = os.path.join(detected_apps_dir, 'Local.txt')
        
        if not os.path.exists(local_file):
            return True, None  # Nothing to remove
        
        # Read existing content
        success, content, error = read_file_content(local_file)
        if not success:
            return False, error
        
        # Remove the entry using ALL identifying fields
        process_path_lower = process_path.lower()
        lines = content.splitlines()
        new_lines = []
        removed = False
        
        logger.info(f"Looking for exact match to remove: path='{process_path}', app='{app_name}', category='{twitch_category}', window='{window_title}'")
        
        for line in lines:
            if line.strip() and not line.startswith('#'):
                parts = split_list_fields(line, 4)
                if len(parts) >= 3:
                    line_path = parts[0].strip()
                    line_path_normalized = line_path.replace('\\', '/').lower()
                    line_app_name = parts[1].strip() if len(parts) > 1 else ""
                    line_twitch_category = parts[2].strip() if len(parts) > 2 else ""
                    line_window_title = _parsed_window_title_from_parts(parts)
                    
                    # Check if this line matches ALL identifying fields
                    if (line_path_normalized == process_path_lower.replace('\\', '/') and 
                        line_app_name == app_name and
                        line_twitch_category == twitch_category and
                        line_window_title == window_title):
                        # Skip this line (remove it)
                        removed = True
                        logger.info(f"Removed entry: {line.strip()}")
                        continue
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        if not removed:
            logger.warning(f"No exact match found with all fields: path='{process_path}', app='{app_name}', category='{twitch_category}', window='{window_title}'")
            return False, f"No exact match found with all fields: path='{process_path}', app='{app_name}', category='{twitch_category}', window='{window_title}'"
        
        # Write back to file
        new_content = '\n'.join(new_lines)
        success, error = write_file_content(local_file, new_content)
        if not success:
            return False, error
        
        # Remove from in-memory cache using composite key
        cache_key = f"{process_path_lower}|{window_title}"
        if cache_key in loaded_detected_apps:
            del loaded_detected_apps[cache_key]
            logger.info(f"Removed from cache: {cache_key}")

        _unassign_title_preset(process_path, twitch_category, window_title, app_name)

        logger.info(f"Removed detected app: {process_path} (app: {app_name}, category: {twitch_category}, window: {window_title})")
        return True, None
    except Exception as e:
        error_msg = f"Error removing detected app: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def add_to_excluded_apps(process_path: str, app_name: str = "", twitch_category: str = "", window_title: str = "") -> Tuple[bool, Optional[str]]:
    """Add a detected app to the excluded apps list."""
    try:
        from catswitch.excluded_apps import ensure_excluded_local_file, reload_excluded_apps

        exclusion_rule = (process_path or "").strip()
        if not exclusion_rule:
            return False, "Process path is required"

        if not app_name:
            app_name = os.path.basename(exclusion_rule)

        local_file = ensure_excluded_local_file()

        with open(local_file, 'r', encoding='utf-8') as f:
            content = f.read()

        exclusion_rule_lower = exclusion_rule.lower()
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            parts = split_list_fields(stripped, 1)
            existing_rule = (parts[0] if parts else '').strip().lower()
            if existing_rule == exclusion_rule_lower:
                return False, "App already in excluded list"

        entry_line = join_list_fields(exclusion_rule, app_name)
        if not content.endswith('\n'):
            content += '\n'
        content += entry_line + '\n'

        with open(local_file, 'w', encoding='utf-8') as f:
            f.write(content)

        reload_excluded_apps()
        logger.info(f"Added {exclusion_rule} to excluded apps Local.txt")
        return True, None
    except Exception as e:
        error_msg = f"Error adding to excluded apps: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def remove_matching_detected_app_for_exclude(
    process_path: str,
    app_name: str = "",
    twitch_category: str = "",
    window_title: str = "",
    list_name: str = "",
    file_path: str = "",
) -> Tuple[bool, Optional[str]]:
    """Remove a detected app entry when it is moved to excluded apps."""
    from catswitch.settings import get_detected_app_files

    target_file_path = (file_path or "").strip()
    if not target_file_path and list_name:
        for list_info in get_detected_app_files():
            if list_info.get('name') == list_name:
                target_file_path = list_info.get('path', '') or ''
                break

    if target_file_path:
        success, error = remove_detected_app_from_file(
            process_path,
            target_file_path,
            app_name,
            twitch_category,
            window_title,
        )
        if success:
            return True, None
        logger.warning(f"Could not remove from specified list file: {error}")

    process_path_norm = process_path.replace('\\', '/').lower()
    for info in loaded_detected_apps.values():
        line_path = info.get('process_path', '')
        line_path_norm = line_path.replace('\\', '/').lower()
        path_matches = (
            line_path_norm == process_path_norm
            or saved_app_path_matches(process_path, info)
            or saved_app_path_matches(line_path, {'process_path': process_path})
        )
        if not path_matches:
            continue

        if app_name and info.get('app_name', '') != app_name:
            continue
        if twitch_category and info.get('twitch_category', '').lower() != twitch_category.lower():
            continue
        if window_title and (info.get('window_title', '') or '') != (window_title or ''):
            continue

        entry_file = info.get('file_path', '')
        if not entry_file:
            continue

        return remove_detected_app_from_file(
            line_path,
            entry_file,
            info.get('app_name', ''),
            info.get('twitch_category', ''),
            info.get('window_title', ''),
        )

    return False, "App not found in detected apps"

def add_manual_detected_app(title: str, category: str, location: str, window_title: str = "") -> bool:
    """Add a detected app manually"""
    try:
        detected_file = ensure_detected_local_file()

        if not is_detected_local_save_enabled():
            logger.info("Cannot add manual detected app: Local.txt is disabled")
            return False
        
        with open(detected_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if already exists
        if location in content:
            logger.info(f"App already in detected list: {location}")
            return True
        
        # Add the new entry using the same format as existing detected apps
        entry = format_detected_app_line(location, title, category, window_title)
        
        if not content.endswith('\n'):
            content += '\n'
        content += f"{entry}\n"
        
        # Write back to file
        with open(detected_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Reload the detected apps cache to include the new entry
        load_detected_apps()
        
        logger.info(f"Added manual detected app: {title} - {category}")
        return True
        
    except Exception as e:
        logger.error(f"Error adding manual detected app: {e}")
        return False

def edit_detected_app(old_process_path: str, process_path: str, app_name: str, twitch_category: str, window_title: str = "", old_app_name: str = "", old_twitch_category: str = "", old_window_title: str = "", file_path: str = "") -> bool:
    """Edit an existing detected app in a list file using ALL identifying fields."""
    try:
        if file_path:
            if not is_detected_list_writable(file_path):
                logger.info(f"Cannot edit detected app: list is not writable ({file_path})")
                return False
            list_info = get_detected_list_info_by_path(file_path)
            detected_file = list_info.get("path", file_path) if list_info else file_path
        else:
            detected_file = ensure_detected_local_file()
            if not is_detected_local_save_enabled():
                logger.info("Cannot edit detected app: Local.txt is disabled")
                return False
        
        if not os.path.exists(detected_file):
            logger.error(f"No detected apps file found: {detected_file}")
            return False
        
        # Read all lines
        with open(detected_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Find and update the matching line using ALL identifying fields
        updated = False
        logger.info(f"Looking for exact match: path='{old_process_path}', app='{old_app_name}', category='{old_twitch_category}', window='{old_window_title}'")
        
        # Normalize paths for comparison (handle both forward and backward slashes)
        old_path_normalized = old_process_path.replace('\\', '/').lower()
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if line_stripped and not line_stripped.startswith('#'):
                # Parse the line to get all fields
                parts = split_list_fields(line_stripped, 4)
                if len(parts) >= 3:
                    line_path = parts[0].strip()
                    line_path_normalized = line_path.replace('\\', '/').lower()
                    line_app_name = parts[1].strip() if len(parts) > 1 else ""
                    line_twitch_category = parts[2].strip() if len(parts) > 2 else ""
                    line_window_title = _parsed_window_title_from_parts(parts)
                    
                    # Check if this line matches ALL identifying fields
                    if (line_path_normalized == old_path_normalized and 
                        line_app_name == old_app_name and
                        line_twitch_category == old_twitch_category and
                        line_window_title == old_window_title):
                        new_entry = format_detected_app_line(process_path, app_name, twitch_category, window_title) + '\n'
                        lines[i] = new_entry
                        updated = True
                        logger.info(f"Updated line {i}: {line_stripped} -> {new_entry.strip()}")
                        break
                    else:
                        logger.debug(f"Line {i} doesn't match: path='{line_path_normalized}' (expected: '{old_path_normalized}'), app='{line_app_name}' (expected: '{old_app_name}'), category='{line_twitch_category}' (expected: '{old_twitch_category}'), window='{line_window_title}' (expected: '{old_window_title}')")
        
        if not updated:
            logger.error(f"Could not find exact match with all fields: path='{old_process_path}', app='{old_app_name}', category='{old_twitch_category}', window='{old_window_title}'")
            return False
        
        # Write back all lines
        with open(detected_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        # Migrate any title preset assignment to the new fingerprint before reloading
        try:
            from catswitch import title_presets
            old_fp = title_presets.compute_fingerprint(
                old_process_path, old_twitch_category, old_window_title, old_app_name
            )
            new_fp = title_presets.compute_fingerprint(
                process_path, twitch_category, window_title, app_name
            )
            title_presets.migrate_fingerprint(old_fp, new_fp)
        except Exception as e:
            logger.error(f"Error migrating title preset assignment: {e}")

        # Reload the cache to reflect changes
        load_detected_apps()
        
        logger.info(f"Edited detected app: {app_name} - {twitch_category}")
        return True
        
    except Exception as e:
        logger.error(f"Error editing detected app: {e}")
        return False

def _unassign_title_preset(process_path: str, twitch_category: str, window_title: str, app_name: str) -> None:
    """Drop any title preset assignment pointing at a removed entry."""
    try:
        from catswitch import title_presets
        fp = title_presets.compute_fingerprint(process_path, twitch_category, window_title, app_name)
        title_presets.unassign_fingerprint(fp)
    except Exception as e:
        logger.error(f"Error unassigning title preset: {e}")

def remove_detected_app_from_file(process_path: str, file_path: str, app_name: str = "", twitch_category: str = "", window_title: str = "", unassign_titles: bool = True) -> tuple[bool, str]:
    """
    Remove a detected app from a specific file using ALL identifying fields (Title, Category, Location, Window Title).
    
    Args:
        process_path: The process path to remove
        file_path: The file path to remove from
        app_name: The app name to match
        twitch_category: The twitch category to match
        window_title: The window title to match
        
    Returns:
        (success, error_message)
    """
    try:
        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}"
        
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        updated = False
        new_lines = []
        process_path_normalized = process_path.replace('\\', '/').lower()
        
        logger.info(f"Looking for exact match to remove from {file_path}: path='{process_path}', app='{app_name}', category='{twitch_category}', window='{window_title}'")
        
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and not line_stripped.startswith('#'):
                line_parts = split_list_fields(line_stripped, 4)
                if len(line_parts) >= 3:
                    line_path = line_parts[0].strip()
                    line_path_normalized = line_path.replace('\\', '/').lower()
                    line_app_name = line_parts[1].strip() if len(line_parts) > 1 else ""
                    line_twitch_category = line_parts[2].strip() if len(line_parts) > 2 else ""
                    line_window_title = _parsed_window_title_from_parts(line_parts)
                    
                    # Check if this line matches ALL identifying fields
                    if (line_path_normalized == process_path_normalized and 
                        line_app_name == app_name and
                        line_twitch_category == twitch_category and
                        line_window_title == window_title):
                        updated = True
                        logger.info(f"Removed from {file_path}: {line_stripped}")
                        continue  # Skip this line (remove it)
            
            new_lines.append(line)
        
        if not updated:
            return False, f"App not found in {file_path} with exact match: path='{process_path}', app='{app_name}', category='{twitch_category}', window='{window_title}'"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        if unassign_titles:
            _unassign_title_preset(process_path, twitch_category, window_title, app_name)

        # Reload the detected apps cache
        load_detected_apps()
        
        logger.info(f"Successfully removed app from {file_path}")
        return True, ""
        
    except Exception as e:
        logger.error(f"Error removing detected app from file: {e}")
        return False, str(e)
