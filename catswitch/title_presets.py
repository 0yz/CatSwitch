"""
Stream Title Presets Module

Presets live in a single hand-editable file (lists/titles/Local.txt). Each line is
`title;fp1|fp2|...` where the fingerprints bind the preset to detected game entries.

A fingerprint is 4 concatenated 10-char sha1 sub-hashes of the entry's stable fields:
process_path + twitch_category + window_title + app_name (custom title). Entries have
no explicit IDs, so when a field changes the fingerprint changes too; assignments are
healed by partial sub-hash matching (weighted, path counts most) either eagerly when
the app itself edits an entry, or lazily on reload by diffing against the hash cache.
"""

import hashlib
import logging
import os
import threading
from typing import Dict, List, Optional, Tuple

from catswitch.list_format import split_list_fields, join_list_fields, build_list_file_header, build_cache_file_header
from catswitch.paths import (
    get_title_presets_file_path,
    get_titles_dir,
    get_detected_games_cache_path,
    relativize_detected_list_path,
    detected_list_paths_equal,
)

logger = logging.getLogger(__name__)

SUBHASH_LEN = 10
FINGERPRINT_LEN = SUBHASH_LEN * 4
# path, category, window title, custom title
FIELD_WEIGHTS = (4, 3, 2, 1)
HEAL_SCORE_THRESHOLD = 5

CATEGORY_PLACEHOLDER = '%cat'

DEFAULT_PRESETS_CONTENT = build_list_file_header("Stream Title Presets", "title_presets")

_file_lock = threading.Lock()

# Parsed document: preserves comments/blank lines so manual edits survive rewrites.
# Items are {'kind': 'raw', 'text': str} or {'kind': 'preset', 'title': str, 'fingerprints': [str]}
_document: List[Dict] = []
_loaded = False


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------

def _subhash(value: str) -> str:
    normalized = (value or '').strip().lower()
    return hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:SUBHASH_LEN]


def compute_fingerprint(process_path: str, twitch_category: str, window_title: str = '', app_name: str = '') -> str:
    return (
        _subhash(process_path)
        + _subhash(twitch_category)
        + _subhash(window_title)
        + _subhash(app_name)
    )


def entry_fingerprint(entry: Dict[str, str]) -> str:
    return compute_fingerprint(
        entry.get('process_path', ''),
        entry.get('twitch_category', ''),
        entry.get('window_title', ''),
        entry.get('app_name', ''),
    )


def _split_fingerprint(fp: str) -> Tuple[str, str, str, str]:
    return (
        fp[0:SUBHASH_LEN],
        fp[SUBHASH_LEN:2 * SUBHASH_LEN],
        fp[2 * SUBHASH_LEN:3 * SUBHASH_LEN],
        fp[3 * SUBHASH_LEN:4 * SUBHASH_LEN],
    )


def _fingerprint_similarity(fp_a: str, fp_b: str) -> int:
    """Weighted count of matching sub-hashes between two fingerprints."""
    if len(fp_a) != FINGERPRINT_LEN or len(fp_b) != FINGERPRINT_LEN:
        return 0
    parts_a = _split_fingerprint(fp_a)
    parts_b = _split_fingerprint(fp_b)
    return sum(
        weight
        for weight, a, b in zip(FIELD_WEIGHTS, parts_a, parts_b)
        if a == b
    )


def _is_valid_fingerprint(fp: str) -> bool:
    return len(fp) == FINGERPRINT_LEN and all(c in '0123456789abcdef' for c in fp)


# ---------------------------------------------------------------------------
# Preset file load/save
# ---------------------------------------------------------------------------

def ensure_title_presets_file() -> str:
    os.makedirs(get_titles_dir(), exist_ok=True)
    path = get_title_presets_file_path()
    if not os.path.exists(path):
        with open(path, 'x', encoding='utf-8') as f:
            f.write(DEFAULT_PRESETS_CONTENT)
        logger.info(f"Created title presets file at {path}")
    return path


def load_title_presets() -> Tuple[bool, Optional[str]]:
    """(Re)load the presets file into the in-memory document."""
    global _document, _loaded
    try:
        path = ensure_title_presets_file()
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        document: List[Dict] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                document.append({'kind': 'raw', 'text': line})
                continue
            parts = split_list_fields(stripped, 1)
            title = parts[0].strip()
            if not title:
                document.append({'kind': 'raw', 'text': line})
                continue
            fp_field = parts[1].strip() if len(parts) > 1 else ''
            fingerprints = [fp for fp in (p.strip().lower() for p in fp_field.split('|')) if _is_valid_fingerprint(fp)]
            document.append({'kind': 'preset', 'title': title, 'fingerprints': fingerprints})

        with _file_lock:
            _document = document
            _loaded = True
        logger.info(f"Loaded {len(get_presets())} title presets")
        return True, None
    except Exception as e:
        error_msg = f"Error loading title presets: {e}"
        logger.error(error_msg)
        return False, error_msg


def _ensure_loaded():
    if not _loaded:
        load_title_presets()


def _write_document() -> Tuple[bool, Optional[str]]:
    try:
        path = ensure_title_presets_file()
        lines = []
        for item in _document:
            if item['kind'] == 'raw':
                lines.append(item['text'])
            else:
                fp_field = '|'.join(item['fingerprints'])
                if fp_field:
                    lines.append(join_list_fields(item['title'], fp_field))
                else:
                    lines.append(join_list_fields(item['title']))
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        return True, None
    except Exception as e:
        error_msg = f"Error writing title presets: {e}"
        logger.error(error_msg)
        return False, error_msg


def _preset_items() -> List[Dict]:
    return [item for item in _document if item['kind'] == 'preset']


def _find_preset_item(title: str) -> Optional[Dict]:
    title_cf = title.strip().casefold()
    for item in _preset_items():
        if item['title'].casefold() == title_cf:
            return item
    return None


def get_presets() -> List[Dict]:
    """Presets in file order: [{'title': str, 'fingerprints': [str]}, ...]."""
    _ensure_loaded()
    return [
        {'title': item['title'], 'fingerprints': list(item['fingerprints'])}
        for item in _preset_items()
    ]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def add_preset(title: str) -> Tuple[bool, Optional[str]]:
    _ensure_loaded()
    title = (title or '').strip()
    if not title:
        return False, "Title cannot be empty"
    with _file_lock:
        if _find_preset_item(title):
            return False, "A preset with this title already exists"
        _document.append({'kind': 'preset', 'title': title, 'fingerprints': []})
        return _write_document()


def rename_preset(old_title: str, new_title: str) -> Tuple[bool, Optional[str]]:
    _ensure_loaded()
    new_title = (new_title or '').strip()
    if not new_title:
        return False, "Title cannot be empty"
    with _file_lock:
        item = _find_preset_item(old_title)
        if not item:
            return False, "Preset not found"
        existing = _find_preset_item(new_title)
        if existing and existing is not item:
            return False, "A preset with this title already exists"
        item['title'] = new_title
        success, error = _write_document()
        if success:
            _migrate_default_title(old_title, new_title)
            _migrate_favorite_title(old_title, new_title)
        return success, error


def remove_preset(title: str) -> Tuple[bool, Optional[str]]:
    global _document
    _ensure_loaded()
    with _file_lock:
        item = _find_preset_item(title)
        if not item:
            return False, "Preset not found"
        _document = [i for i in _document if i is not item]
        success, error = _write_document()
        if success:
            _clear_default_if_matches(title)
            _remove_favorite_if_matches(title)
        return success, error


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

def preset_for_fingerprint(fp: str) -> Optional[str]:
    """Exact-match owning preset title for a fingerprint (first in file order)."""
    _ensure_loaded()
    fp = (fp or '').lower()
    for item in _preset_items():
        if fp in item['fingerprints']:
            return item['title']
    return None


def assign_fingerprint(title: str, fp: str) -> Tuple[bool, Optional[str]]:
    """Assign a game fingerprint to a preset, removing it from any other preset."""
    _ensure_loaded()
    fp = (fp or '').lower()
    if not _is_valid_fingerprint(fp):
        return False, "Invalid fingerprint"
    with _file_lock:
        item = _find_preset_item(title)
        if not item:
            return False, "Preset not found"
        for other in _preset_items():
            if other is not item and fp in other['fingerprints']:
                other['fingerprints'].remove(fp)
        if fp not in item['fingerprints']:
            item['fingerprints'].append(fp)
        return _write_document()


def unassign_fingerprint(fp: str) -> Tuple[bool, Optional[str]]:
    _ensure_loaded()
    fp = (fp or '').lower()
    with _file_lock:
        removed = False
        for item in _preset_items():
            if fp in item['fingerprints']:
                item['fingerprints'].remove(fp)
                removed = True
        if not removed:
            return True, None
        return _write_document()


def migrate_fingerprint(old_fp: str, new_fp: str) -> Tuple[bool, Optional[str]]:
    """Replace an assigned fingerprint after its game entry changed (eager healing)."""
    _ensure_loaded()
    old_fp = (old_fp or '').lower()
    new_fp = (new_fp or '').lower()
    if old_fp == new_fp or not _is_valid_fingerprint(new_fp):
        return True, None
    with _file_lock:
        changed = False
        for item in _preset_items():
            if old_fp in item['fingerprints']:
                item['fingerprints'] = [new_fp if fp == old_fp else fp for fp in item['fingerprints']]
                changed = True
        if not changed:
            return True, None
        logger.info(f"Migrated title preset assignment {old_fp[:10]}... -> {new_fp[:10]}...")
        return _write_document()


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def find_preset_for_entry(entry: Dict[str, str]) -> Optional[str]:
    """
    Find the preset title assigned to a detected game entry.

    Tier 1: exact fingerprint match.
    Tier 2: best weighted partial match (path=4, category=3, window=2, custom=1,
            threshold >= 5). A partial hit heals the stored fingerprint in place.
    """
    _ensure_loaded()
    fp = entry_fingerprint(entry)
    exact = preset_for_fingerprint(fp)
    if exact is not None:
        return exact

    best_title = None
    best_fp = None
    best_score = HEAL_SCORE_THRESHOLD - 1
    for item in _preset_items():
        for stored_fp in item['fingerprints']:
            score = _fingerprint_similarity(fp, stored_fp)
            if score > best_score:
                best_score = score
                best_title = item['title']
                best_fp = stored_fp

    if best_title is not None and best_fp is not None:
        logger.info(
            f"Healing title preset assignment for '{best_title}' "
            f"(partial match score {best_score})"
        )
        migrate_fingerprint(best_fp, fp)
        return best_title
    return None


def find_preset_for_category(category: str) -> Optional[str]:
    """Fallback lookup by category sub-hash only (used for manual category picks)."""
    _ensure_loaded()
    cat_hash = _subhash(category)
    for item in _preset_items():
        for fp in item['fingerprints']:
            if len(fp) == FINGERPRINT_LEN and fp[SUBHASH_LEN:2 * SUBHASH_LEN] == cat_hash:
                return item['title']
    return None


def resolve_title_text(title: str, category: Optional[str]) -> str:
    """Substitute %cat with the current category name."""
    return (title or '').replace(CATEGORY_PLACEHOLDER, category or '')


# ---------------------------------------------------------------------------
# Default title (stored in settings.json)
# ---------------------------------------------------------------------------

_DEFAULT_TITLE_KEY = 'title_presets_default'


def get_default_title() -> Optional[str]:
    from catswitch.settings import get_setting
    title = get_setting(_DEFAULT_TITLE_KEY)
    if not title or not isinstance(title, str):
        return None
    title = title.strip()
    return title or None


def set_default_title(title: str) -> Tuple[bool, Optional[str]]:
    title = (title or '').strip()
    if not title:
        return False, "Title cannot be empty"
    _ensure_loaded()
    if not _find_preset_item(title):
        return False, "Preset not found"
    from catswitch.settings import set_setting
    if set_setting(_DEFAULT_TITLE_KEY, title):
        logger.info(f"Set default stream title preset: {title}")
        return True, None
    return False, "Failed to save default title"


def clear_default_title() -> Tuple[bool, Optional[str]]:
    from catswitch.settings import delete_setting
    if not get_default_title():
        return True, None
    if delete_setting(_DEFAULT_TITLE_KEY):
        logger.info("Cleared default stream title preset")
        return True, None
    return False, "Failed to clear default title"


def _migrate_default_title(old_title: str, new_title: str) -> None:
    if get_default_title() == old_title:
        from catswitch.settings import set_setting
        set_setting(_DEFAULT_TITLE_KEY, new_title)


def _clear_default_if_matches(title: str) -> None:
    if get_default_title() == title:
        clear_default_title()


# ---------------------------------------------------------------------------
# Favorites (stored in settings.json)
# ---------------------------------------------------------------------------

_FAVORITES_KEY = 'title_presets_favorites'


def get_favorite_titles() -> List[str]:
    from catswitch.settings import get_setting
    raw = get_setting(_FAVORITES_KEY, [])
    if not isinstance(raw, list):
        return []
    favorites: List[str] = []
    seen = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        title = item.strip()
        if not title or title in seen:
            continue
        seen.add(title)
        favorites.append(title)
    return favorites


def is_favorite(title: str) -> bool:
    title = (title or '').strip()
    return title in get_favorite_titles()


def add_favorite(title: str) -> Tuple[bool, Optional[str]]:
    title = (title or '').strip()
    if not title:
        return False, "Title cannot be empty"
    _ensure_loaded()
    if not _find_preset_item(title):
        return False, "Preset not found"
    from catswitch.settings import mutate_settings

    already = {"yes": False}

    def _apply(settings: dict):
        raw = settings.get(_FAVORITES_KEY, [])
        favorites = list(raw) if isinstance(raw, list) else []
        if title in favorites:
            already["yes"] = True
            return False
        settings[_FAVORITES_KEY] = favorites + [title]
        return True

    if mutate_settings(_apply) or already["yes"]:
        if not already["yes"]:
            logger.info(f"Favorited stream title preset: {title}")
        return True, None
    return False, "Failed to save favorite"


def remove_favorite(title: str) -> Tuple[bool, Optional[str]]:
    title = (title or '').strip()
    if not title:
        return False, "Title cannot be empty"
    from catswitch.settings import mutate_settings

    missing = {"yes": False}

    def _apply(settings: dict):
        raw = settings.get(_FAVORITES_KEY, [])
        favorites = list(raw) if isinstance(raw, list) else []
        if title not in favorites:
            missing["yes"] = True
            return False
        settings[_FAVORITES_KEY] = [item for item in favorites if item != title]
        return True

    if mutate_settings(_apply) or missing["yes"]:
        if not missing["yes"]:
            logger.info(f"Removed favorite stream title preset: {title}")
        return True, None
    return False, "Failed to update favorites"


def _migrate_favorite_title(old_title: str, new_title: str) -> None:
    from catswitch.settings import mutate_settings

    def _apply(settings: dict):
        raw = settings.get(_FAVORITES_KEY, [])
        favorites = list(raw) if isinstance(raw, list) else []
        if old_title not in favorites:
            return False
        settings[_FAVORITES_KEY] = [
            new_title if item == old_title else item for item in favorites
        ]
        return True

    mutate_settings(_apply)


def _remove_favorite_if_matches(title: str) -> None:
    remove_favorite(title)


# ---------------------------------------------------------------------------
# Hash cache (fingerprints of all loaded detected games, diffed across reloads)
# ---------------------------------------------------------------------------

def _load_hash_cache() -> Dict[str, str]:
    """Previous fingerprint table: {fingerprint: source_file_path}."""
    path = get_detected_games_cache_path()
    table: Dict[str, str] = {}
    try:
        if not os.path.exists(path):
            return table
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                fp, _, file_path = line.partition('\t')
                if _is_valid_fingerprint(fp):
                    table[fp] = file_path
    except Exception as e:
        logger.error(f"Error reading detected games hash cache: {e}")
    return table


def _write_hash_cache(table: Dict[str, str]) -> None:
    path = get_detected_games_cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lines = [build_cache_file_header().rstrip("\n")]
        for fp, file_path in sorted(table.items(), key=lambda kv: (kv[1], kv[0])):
            lines.append(f"{fp}\t{file_path}")
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    except Exception as e:
        logger.error(f"Error writing detected games hash cache: {e}")


def sync_with_detected_apps(loaded_apps: Dict[str, Dict[str, str]]) -> None:
    """
    Rebuild the fingerprint cache after detected apps (re)load and heal preset
    assignments whose fingerprints disappeared (e.g. lines edited externally).
    """
    try:
        _ensure_loaded()
        new_table: Dict[str, str] = {}
        for info in loaded_apps.values():
            new_table[entry_fingerprint(info)] = relativize_detected_list_path(
                info.get('file_path', '')
            )

        old_table = _load_hash_cache()

        assigned = {
            fp: item
            for item in _preset_items()
            for fp in item['fingerprints']
        }
        orphaned = [fp for fp in assigned if fp not in new_table]

        for old_fp in orphaned:
            old_file = old_table.get(old_fp, '')
            best_fp = None
            best_score = HEAL_SCORE_THRESHOLD - 1
            for new_fp, new_file in new_table.items():
                if new_fp in assigned:
                    continue
                score = _fingerprint_similarity(old_fp, new_fp)
                if old_file and detected_list_paths_equal(old_file, new_file):
                    score += 1  # prefer candidates from the same list file
                if score > best_score:
                    best_score = score
                    best_fp = new_fp
            if best_fp:
                logger.info(
                    f"Healing orphaned title preset assignment "
                    f"(score {best_score}): {old_fp[:10]}... -> {best_fp[:10]}..."
                )
                migrate_fingerprint(old_fp, best_fp)
                assigned[best_fp] = assigned.pop(old_fp)

        _write_hash_cache(new_table)
    except Exception as e:
        logger.error(f"Error syncing title presets with detected apps: {e}")
