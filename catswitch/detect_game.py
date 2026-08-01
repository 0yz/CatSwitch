import logging
import psutil
import math
import threading
from difflib import SequenceMatcher
from ctypes import WINFUNCTYPE, windll, byref, create_unicode_buffer, wintypes
from catswitch.update_twitch import (
    search_twitch_categories,
    fetch_category_info,
    get_game_id,
    fetch_game_followers_count,
)
import time
from time import sleep
import os
import re
from typing import Optional
from catswitch.excluded_apps import find_exclusion_match, format_exclusion_skip_message
from catswitch.detected_apps import (
    find_matching_detected_app,
    find_matching_detected_app_by_window_title,
    saved_app_path_matches,
    entry_titles_compatible,
)

logger = logging.getLogger(__name__)

# Global state tracking
last_game_process = None
last_game_name = None
last_game_pid = None
game_detection_running = False  # Flag to control game detection loop
game_detection_generation = 0  # Incremented on stop so old loops exit cleanly
game_detection_lock = threading.Lock()

_PATH_SKIP_FOLDERS = frozenset({
    'bin', 'binaries', 'cache', 'common', 'content', 'data', 'dotnet', 'engine',
    'epic games', 'ea games', 'game', 'games', 'goggalaxy', 'logs', 'plugins',
    'program files', 'program files (x86)', 'redist', 'riot games', 'saved',
    'steam', 'steamapps', 'support', 'temp', 'tools', 'ubisoft', 'windows',
    'win32', 'win64', 'xboxgames',
})

_PATH_TECHNICAL_FOLDERS = frozenset({'binaries', 'win32', 'win64', 'engine', 'bin', 'content'})

CLOSE_MATCH_SCORE_SPAN = 0.15
MAX_FOLLOWER_BOOST = 0.25
BOX_ART_BOOST = 0.10
MISSING_BOX_ART_PENALTY = 0.10
EXACT_LOOKUP_PENALTY = 0.10
MIN_CONTENDER_SCORE = 0.5
MAX_SCORED_CANDIDATES = 5
QUALITY_PASS_POOL = 10
NON_DISCORD_DETECTABLE_SCORE_PENALTY = 0.35
NON_DISCORD_MIN_CONTENDER_SCORE = 0.90
NON_DISCORD_MIN_MATCH_SCORE = 0.90
PATH_CONFIRMED_MIN_MATCH_SCORE = 0.75
PATH_CONFIRMED_EXACT_BOOST = 0.74
DISCORD_NAME_MATCH_BOOST = 0.12
STRICT_EXACT_TITLE_MIN_CATEGORY_WORDS = 2

TRIM_THRESHOLD_DEFAULT = 0.5
TRIM_THRESHOLD_THREE_WORDS = 0.65
TRIM_THRESHOLD_TWO_WORDS = 0.75
TRIM_THRESHOLD_SINGLE_WORD = 0.85
ANCHOR_POPULARITY_RATIO_MIN = 20
ANCHOR_OVERRIDE_MIN_SCORE = 0.5
ANCHOR_MIN_WORD_LEN = 4
FOLLOWER_BOOST_MIN_TITLE_PATH = 0.5

_ANCHOR_STOPWORDS = frozenset({
    'a', 'an', 'and', 'at', 'by', 'for', 'in', 'of', 'on', 'or', 'the', 'to',
})

_RENDERER_SUFFIX_RE = re.compile(
    r'\s*-\s*(?:'
    r'Direct3D\s*\d+|D3D\d+|Vulkan|OpenGL|'
    r'Software\s+Renderer|Hardware\s+Renderer'
    r').*$',
    re.IGNORECASE,
)

_LAUNCHER_SUFFIX_RE = re.compile(r'\s+launcher$', re.IGNORECASE)


def _follower_popularity_boost(my_count, all_counts):
    """
    Log-scaled popularity boost from directory follower counts.
    3 vs 90 followers -> large swing; 2000 vs 2100 -> negligible.
    """
    counts = [max(int(c or 0), 0) for c in all_counts if c is not None]
    if len(counts) < 2:
        return 0.0

    my = max(int(my_count or 0), 0)
    max_c = max(counts)
    min_c = min(counts)
    if max_c == min_c:
        return 0.0

    if my <= 0 and max_c >= 20:
        return -0.08
    if my <= 0:
        return -0.03

    ratio = max_c / max(min_c, 1)
    log_span = math.log2(ratio)
    if log_span <= 0.04:
        return 0.0

    my_ratio = my / max(min_c, 1)
    normalized = max(0.0, min(1.0, math.log2(my_ratio) / log_span))
    max_boost = min(MAX_FOLLOWER_BOOST, log_span * 0.05)
    return round(normalized * max_boost, 3)


def _fetch_followers_for_candidates(client_id, oauth_token, entries, cache):
    """Fetch directory follower counts for a list of (name, game_id) pairs."""
    followers = {}
    for name, game_id in entries:
        cache_key = game_id or name
        if cache_key in cache:
            followers[name] = cache[cache_key]
            continue
        count = fetch_game_followers_count(game_id=game_id, game_name=name)
        cache[cache_key] = count
        followers[name] = count
        if count is not None:
            logger.info(f"Directory followers for '{name}' (id={game_id or '?'}): {count}")
    return followers


def _apply_follower_boost_if_close(scored_rows, client_id, oauth_token, follower_cache):
    """
    Apply follower boost when top candidates are similarly scored.
    scored_rows: list of tuples whose index 1 is the score; last element is meta dict with game_id.
    Returns updated list of tuples.
    """
    if len(scored_rows) < 2:
        return scored_rows

    scores = [row[1] for row in scored_rows]
    if max(scores) - min(scores) > CLOSE_MATCH_SCORE_SPAN:
        return scored_rows

    entries = []
    for row in scored_rows:
        name = row[0]
        meta = row[-1] if isinstance(row[-1], dict) else {}
        game_id = row[3] if len(row) > 3 and row[3] else meta.get("game_id")
        entries.append((name, game_id))

    follower_map = _fetch_followers_for_candidates(
        client_id, oauth_token, entries, follower_cache
    )
    all_counts = list(follower_map.values())
    if not any(c is not None for c in all_counts):
        return scored_rows

    logger.info("Close match — applying follower boost: "
        + ", ".join(f"'{n}'={c}" for n, c in follower_map.items()))

    updated = []
    for row in scored_rows:
        name = row[0]
        score = row[1]
        boost = _follower_popularity_boost(follower_map.get(name), all_counts)
        if boost:
            new_score = _round_score(score + boost)
            logger.info(f"Follower boost for '{name}': +{fmt_sim(boost)} -> {fmt_sim(new_score)}")
            row = row[:1] + (new_score,) + row[2:]
        updated.append(row)
    return updated


def fmt_sim(score: float) -> str:
    """Format a similarity score for logs (3 decimal places)."""
    return f"{round(score, 3):.3f}"


def _round_score(score: float) -> float:
    """Round a running match total; never cap — boosts and penalties stack additively."""
    return round(max(score, 0.0), 3)


def _split_camel_case(name: str) -> str:
    return re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', name)


def _normalize_name_for_path_match(name: str) -> str:
    """Normalize folder/game names for comparison."""
    s = _split_camel_case(name).lower().strip()
    s = re.sub(r'[_\-]+', ' ', s)
    s = re.sub(r'\s*&\s*', ' and ', s)
    s = re.sub(r'[^\w\s]', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def _compact_normalize(name: str) -> str:
    return _normalize_name_for_path_match(name).replace(' ', '')


def _whole_word_in(needle: str, haystack: str) -> bool:
    if not needle or not haystack:
        return False
    return bool(re.search(r'\b' + re.escape(needle) + r'\b', haystack, re.IGNORECASE))


def _compact_equivalent(name_a: str, name_b: str) -> bool:
    """True when two names differ only by spacing/punctuation (Gunmetal vs Gun Metal)."""
    return _compact_normalize(name_a) == _compact_normalize(name_b)


def _content_tokens(text: str) -> set:
    """Normalized content tokens excluding stopwords."""
    tokens = _normalize_name_for_path_match(text).split()
    return {t for t in tokens if t and t not in _ANCHOR_STOPWORDS}


def _split_search_words(search_term: str) -> list:
    """Split a search term into words, ignoring stray dash tokens."""
    return [w for w in (search_term or '').split() if w and w != '-']


def _clean_window_title_for_detection(window_title: str) -> str:
    """Strip renderer suffixes and normalize punctuation from a window title."""
    title = (window_title or '').strip()
    title = _RENDERER_SUFFIX_RE.sub('', title).strip()
    title = _LAUNCHER_SUFFIX_RE.sub('', title).strip()
    title = re.sub(r'[^\w\s\-&]', '', title)
    title = re.sub(r'\s*&\s*', ' and ', title)
    title = re.sub(r'[^\w\s\-]', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    title = re.sub(r'\s*-\s*$', '', title).strip()
    return title


# Dotted version at end-ish of a title: "1.23", "1.2.3-dev", "1.2.3-c8a9d3".
# Requires at least one dot so bare sequels ("Portal 2") are never touched.
_DOTTED_VERSION_CORE = r'\d+(?:\.\d+)+(?:-[A-Za-z0-9]+)?'
_VERSION_BRACKET_RE = re.compile(
    r'\(\s*' + _DOTTED_VERSION_CORE + r'\s*\)',
    re.IGNORECASE,
)
_VERSION_SPACE_RE = re.compile(
    r'(?<=\s)' + _DOTTED_VERSION_CORE + r'(?=\s|$|[^\w.-])',
    re.IGNORECASE,
)


def _is_acceptable_version_trailer(suffix: str) -> bool:
    """True when text after a stripped version is empty or a short end tag (x64, etc.)."""
    s = (suffix or '').strip()
    if not s:
        return True
    s = re.sub(r'^[\s\-–_|:·•]+', '', s).strip()
    if not s:
        return True
    # One short token only — rejects "Remastered Collection" style leftovers.
    if re.fullmatch(r'[A-Za-z0-9+][A-Za-z0-9+\-]{0,15}', s):
        return True
    return False


def _strip_endish_dotted_version(window_title: str) -> Optional[str]:
    """
    Remove a trailing-ish dotted version from a raw window title.

    Matches space-prefixed forms (``Bejeweled 1.23``, ``Game 1.2.3-dev``) and
    bracketed forms (``Game (1.2.3)``). Integer sequels without dots are never
    stripped. Returns None when nothing safe to remove.
    """
    title = (window_title or '').strip()
    if not title:
        return None

    matches = list(_VERSION_BRACKET_RE.finditer(title))
    matches.extend(_VERSION_SPACE_RE.finditer(title))
    if not matches:
        return None

    match = max(matches, key=lambda m: m.start())
    prefix = title[: match.start()].rstrip()
    if not prefix:
        return None

    suffix = title[match.end() :]
    if not _is_acceptable_version_trailer(suffix):
        return None

    trailer = suffix.strip()
    trailer = re.sub(r'^[\s\-–_|:·•]+', '', trailer).strip()
    if trailer:
        result = f'{prefix} {trailer}'
    else:
        result = prefix

    result = re.sub(r'\s+', ' ', result).strip()
    result = re.sub(r'[\s\-–_|:·•]+$', '', result).strip()
    if not result or result.casefold() == title.casefold():
        return None
    return result


def _last_resort_title_without_version(window_title: str) -> Optional[str]:
    """
    Build a cleaned search term with end-ish dotted versions removed.

    Returns None when stripping does not change the cleaned detection term.
    """
    stripped = _strip_endish_dotted_version(window_title)
    if stripped is None:
        return None

    cleaned = _clean_window_title_for_detection(stripped)
    if not cleaned:
        return None

    original_cleaned = _clean_window_title_for_detection(window_title)
    if cleaned.casefold() == (original_cleaned or '').casefold():
        return None
    return cleaned


def _trim_acceptance_threshold(content_word_count: int) -> float:
    """Minimum score required to accept a match at a given trim length."""
    if content_word_count <= 1:
        return TRIM_THRESHOLD_SINGLE_WORD
    if content_word_count == 2:
        return TRIM_THRESHOLD_TWO_WORDS
    if content_word_count == 3:
        return TRIM_THRESHOLD_THREE_WORDS
    return TRIM_THRESHOLD_DEFAULT


def _normalized_title_tokens(text: str) -> list:
    """Tokenize a title for comparison; punctuation/separators are ignored."""
    return _normalize_name_for_path_match(text).split()


def _tokens_are_ordered_subsequence(needle_tokens: list, haystack_tokens: list) -> bool:
    """True when needle_tokens appear in haystack_tokens in the same order."""
    if not needle_tokens:
        return True
    idx = 0
    for token in haystack_tokens:
        if idx < len(needle_tokens) and token == needle_tokens[idx]:
            idx += 1
    return idx == len(needle_tokens)


def _token_conflict_penalty(search_term: str, game_name: str) -> float:
    """
    Penalize when search and category each have unique tokens that disagree,
    e.g. 'Portal with' vs 'Portal Touch' (with != touch).

    Uses the full normalized category name so window titles that omit part of a
    long Twitch name (before/after any punctuation) are not treated as conflicts.
    """
    search_tokens = _normalized_title_tokens(search_term)
    game_tokens = _normalized_title_tokens(game_name)
    if not search_tokens or not game_tokens:
        return 0.0

    if _tokens_are_ordered_subsequence(search_tokens, game_tokens):
        return 0.0
    if _tokens_are_ordered_subsequence(game_tokens, search_tokens):
        return 0.0

    if (
        len(game_tokens) <= len(search_tokens)
        and game_tokens == search_tokens[: len(game_tokens)]
    ):
        return 0.0
    if (
        len(search_tokens) <= len(game_tokens)
        and search_tokens == game_tokens[: len(search_tokens)]
    ):
        return 0.0

    search_only = [t for t in search_tokens if t not in game_tokens]
    game_only = [t for t in game_tokens if t not in search_tokens]
    if search_only and game_only:
        conflict_count = min(len(search_only), len(game_only))
        return min(0.35 * conflict_count, 0.75)
    return 0.0


def _has_token_conflict(search_term: str, game_name: str) -> bool:
    """True when search and category have mutually conflicting tokens."""
    return _token_conflict_penalty(search_term, game_name) > 0.0


def _category_base_name(game_name: str) -> str:
    return (game_name or '').split(': ', 1)[0].strip()


def _path_discord_confirms_match(
    match: str,
    score: float,
    process_path: Optional[str],
    second_score: float = 0.0,
) -> bool:
    """True when install folder and Discord both identify this Twitch category."""
    if not process_path or not match:
        return False
    if score < PATH_CONFIRMED_MIN_MATCH_SCORE:
        return False

    path_hints = extract_path_hints(process_path)
    path_boost, path_reason = path_match_boost(match, path_hints)
    if not _is_path_confirmed_match(path_boost, path_reason):
        return False

    from catswitch.discord_detectable import get_discord_app_name

    discord_name = get_discord_app_name(process_path)
    if not discord_name or discord_name.casefold() != match.casefold():
        return False

    if second_score and score - second_score <= CLOSE_MATCH_SCORE_SPAN:
        return False

    return True


def _token_conflict_blocks_acceptance(
    search_term: str,
    match: str,
    score: float,
    process_path: Optional[str] = None,
    second_score: float = 0.0,
) -> bool:
    """True when a token conflict should reject an otherwise strong match."""
    if not _has_token_conflict(search_term, match):
        return False

    if _compact_equivalent(search_term, _category_base_name(match)):
        logger.info(f"Compact-equivalent override for '{match}' despite token conflict "
            f"with '{search_term}'")
        return False

    if _path_discord_confirms_match(match, score, process_path, second_score):
        logger.info(f"Path + Discord override for '{match}' despite token conflict "
            f"with '{search_term}' (score {fmt_sim(score)})")
        return False

    return True


def _weak_match_well_aligned(search_term: str, category_name: str) -> bool:
    """True when category shares 2+ content tokens with the trim term (don't override)."""
    search_content = _content_tokens(search_term)
    category_content = _content_tokens(category_name)
    return len(search_content & category_content) >= 2


def _extract_anchor_word(search_term: str) -> str:
    """First significant content word suitable for anchor fallback."""
    for word in _split_search_words(search_term):
        if word.lower() in _ANCHOR_STOPWORDS:
            continue
        if len(word) < ANCHOR_MIN_WORD_LEN:
            continue
        return word
    return ''


def _is_anchor_exact_category(anchor: str, category_name: str) -> bool:
    """True when the Twitch category name is exactly the anchor word."""
    base = category_name.split(': ', 1)[0].strip()
    return _normalize_name_for_path_match(anchor) == _normalize_name_for_path_match(base)


def _extra_token_penalty(search_term, game_name) -> float:
    """
    Penalize category names that add words beyond the search term.
    Prefix matches with trailing words (Crypt -> Crypt of the NecroDancer) are penalized.
    Spacing-only differences (Gunmetal vs Gun Metal) are not penalized.
    """
    search_norm = _normalize_name_for_path_match(search_term)
    base = game_name.split(': ', 1)[0]
    game_norm = _normalize_name_for_path_match(base)

    if search_norm == game_norm or _compact_equivalent(search_term, base):
        return 0.0

    search_tokens = search_norm.split()
    game_tokens = game_norm.split()
    if not search_tokens or not game_tokens:
        return 0.0

    if game_tokens[: len(search_tokens)] == search_tokens:
        extra_count = len(game_tokens) - len(search_tokens)
        if extra_count > 0:
            return min(0.12 * extra_count, 0.50)

    extra_tokens = [token for token in game_tokens if token not in search_tokens]
    if extra_tokens:
        return min(0.12 * len(extra_tokens), 0.50)

    return 0.0


def _best_path_similarity(hint_norm, hint_compact, game_norm, game_compact, game_base_norm, game_base_compact):
    """How closely a Twitch category name matches an install-path folder hint."""
    ratios = [
        SequenceMatcher(None, hint_norm, game_norm).ratio(),
        SequenceMatcher(None, hint_compact, game_compact).ratio(),
    ]
    if game_base_norm:
        ratios.append(SequenceMatcher(None, hint_norm, game_base_norm).ratio())
    if game_base_compact:
        ratios.append(SequenceMatcher(None, hint_compact, game_base_compact).ratio())
    return max(ratios)


def _hint_tokens_align_with_game(hint_norm, game_norm, game_base_norm):
    """Every path-hint word must appear as its own word in the category name."""
    hint_tokens = hint_norm.split()
    if not hint_tokens:
        return False

    for candidate in (game_norm, game_base_norm):
        if not candidate:
            continue
        game_tokens = candidate.split()
        if all(token in game_tokens for token in hint_tokens):
            return True
    return False


def _boost_from_path_similarity(ratio, primary, hint_weight):
    """Map path-name similarity to a boost; exact folder spelling scores highest."""
    if ratio < 0.55:
        return 0.0, None

    clamped = max(0.55, min(ratio, 1.0))
    progress = (clamped - 0.55) / 0.45
    max_boost = 0.75 if primary else 0.30
    min_boost = 0.10 if primary else 0.04
    boost = min_boost + progress * (max_boost - min_boost)
    return round(boost * hint_weight, 3), fmt_sim(ratio)


def extract_path_hints(process_path: str) -> list:
    """
    Extract weighted folder hints from an install path.

    Primary hints (weight 1.0): folder after steamapps/common, Epic Games, GOG, etc.
    Secondary hints (weight 0.55): one meaningful subfolder above Binaries/Win64.
    """
    if not process_path:
        return []

    parts = [p for p in process_path.replace('\\', '/').split('/') if p]
    if len(parts) < 2:
        return []

    hints = []
    seen = set()
    normalized_parts = [p.lower() for p in parts]

    def add_hint(folder: str, weight: float):
        norm = _normalize_name_for_path_match(folder)
        if len(norm) < 3 or norm in _PATH_SKIP_FOLDERS:
            return
        if norm in seen:
            return
        seen.add(norm)
        hints.append((folder, weight))

    for marker in ('common', 'games'):
        if marker in normalized_parts:
            idx = normalized_parts.index(marker)
            if idx + 1 < len(parts):
                add_hint(parts[idx + 1], 1.0)

    for i, part in enumerate(normalized_parts):
        if part == 'epic games' and i + 1 < len(parts):
            add_hint(parts[i + 1], 1.0)
        if part == 'goggalaxy' and i + 2 < len(parts) and normalized_parts[i + 1] == 'games':
            add_hint(parts[i + 2], 1.0)

    for i in range(len(parts) - 2, 0, -1):
        folder_lower = parts[i].lower()
        if folder_lower in _PATH_TECHNICAL_FOLDERS or folder_lower.endswith('.exe'):
            continue
        add_hint(parts[i], 0.55)
        break

    return hints


def path_match_boost(game_name: str, path_hints: list) -> tuple:
    """
    Boost score when a Twitch category aligns with install-path folder names.
    Boost scales with how closely the category spelling matches the folder name.
    """
    if not path_hints or not game_name:
        return 0.0, None

    game_norm = _normalize_name_for_path_match(game_name)
    game_compact = _compact_normalize(game_name)
    game_base = game_name.split(': ', 1)[0].strip()
    game_base_norm = _normalize_name_for_path_match(game_base)
    game_base_compact = _compact_normalize(game_base)
    game_subtitle_norm = (
        _normalize_name_for_path_match(game_name.split(': ', 1)[1])
        if ': ' in game_name else ''
    )

    best_boost = 0.0
    best_reason = None

    for hint_raw, hint_weight in path_hints:
        hint_norm = _normalize_name_for_path_match(hint_raw)
        hint_compact = _compact_normalize(hint_raw)
        if not hint_norm:
            continue

        boost = 0.0
        reason = None
        primary = hint_weight >= 0.9

        if hint_norm == game_norm or hint_compact == game_compact:
            boost = round((0.75 if primary else 0.30) * hint_weight, 3)
            reason = f"exact path folder '{hint_raw}'"
        elif hint_norm == game_base_norm or hint_compact == game_base_compact:
            boost = round((0.65 if primary else 0.28) * hint_weight, 3)
            reason = f"path folder '{hint_raw}' matches base title"
        elif game_subtitle_norm and hint_norm == game_subtitle_norm:
            boost = round((0.55 if primary else 0.22) * hint_weight, 3)
            reason = f"path folder '{hint_raw}' matches subtitle"
        else:
            if not _hint_tokens_align_with_game(hint_norm, game_norm, game_base_norm):
                boost = 0.0
            else:
                ratio = _best_path_similarity(
                    hint_norm, hint_compact, game_norm, game_compact,
                    game_base_norm, game_base_compact,
                )
                boost, ratio_label = _boost_from_path_similarity(ratio, primary, hint_weight)
                if boost:
                    reason = f"path similarity to '{hint_raw}' ({ratio_label})"

        if boost > best_boost:
            best_boost = boost
            best_reason = reason

    return round(min(best_boost, 0.80), 3), best_reason

def remember_active_game(process_name, game_name, pid=None):
    """Track the active game process so we can switch to Just Chatting when it exits."""
    global last_game_process, last_game_name, last_game_pid
    last_game_process = process_name
    last_game_name = game_name
    last_game_pid = pid


def clear_active_game_tracking() -> None:
    """Clear tracked active game state."""
    global last_game_process, last_game_name, last_game_pid
    last_game_process = None
    last_game_name = None
    last_game_pid = None

def apply_saved_app_match(detected_app, process_name, process_path, callback, pid=None, window_title=None):
    """Apply a saved detected-app mapping to the Twitch category callback."""
    game_name = detected_app.get('twitch_category')
    if not game_name:
        return False
    remember_active_game(process_name, game_name, pid)
    callback(
        game_name,
        process_path,
        is_existing_match=True,
        box_art_url=detected_app.get('box_art_url', ''),
        window_title=window_title,
    )
    return True

def get_active_window_info():
    """Get process name, process path, and window title of active window"""
    try:
        # Get the foreground window handle
        hwnd = windll.user32.GetForegroundWindow()
        if not hwnd:
            return None, None, None, None
            
        # Get window title
        length = windll.user32.GetWindowTextLengthW(hwnd)
        buff = create_unicode_buffer(length + 1)
        windll.user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value
        
        # Get process ID
        pid = wintypes.DWORD()
        windll.user32.GetWindowThreadProcessId(hwnd, byref(pid))
        
        # Get process name and path
        try:
            process = psutil.Process(pid.value)
            process_name = process.name()
            process_path = process.exe()
            # Only return if we have process name, path, and title
            if process_name and process_path and title:
                return process_name, process_path, title, pid.value
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
            
        return None, None, None, None
    except Exception as e:
        logger.error(f"Error getting window info: {e}")
        return None, None, None, None


_GWL_EXSTYLE = -20
_GW_OWNER = 4
_WS_EX_TOOLWINDOW = 0x00000080
_OWN_PROCESS_NAMES = frozenset({'python.exe', 'pythonw.exe', 'catswitch.exe'})


def _is_selectable_foreground_window(hwnd):
    """True for normal visible top-level windows (not tray/tool/owned/minimized)."""
    if not windll.user32.IsWindow(hwnd):
        return False
    if not windll.user32.IsWindowVisible(hwnd):
        return False
    if windll.user32.IsIconic(hwnd):
        return False
    if windll.user32.GetWindow(hwnd, _GW_OWNER):
        return False

    ex_style = windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    if ex_style & _WS_EX_TOOLWINDOW:
        return False

    title_length = windll.user32.GetWindowTextLengthW(hwnd)
    if title_length <= 0:
        return False

    return True


def _window_title_for_handle(hwnd):
    length = windll.user32.GetWindowTextLengthW(hwnd)
    buff = create_unicode_buffer(length + 1)
    windll.user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value


def _pid_for_window(hwnd):
    pid = wintypes.DWORD()
    windll.user32.GetWindowThreadProcessId(hwnd, byref(pid))
    return pid.value


def _should_skip_foreground_process(process_name, process_path, pid):
    if pid == os.getpid():
        return True

    process_name_lower = (process_name or '').lower()
    if process_name_lower in _OWN_PROCESS_NAMES:
        return True

    process_path_lower = (process_path or '').lower()
    if 'catswitch' in process_path_lower:
        return True

    return False


def _process_usage_score(pid):
    try:
        times = psutil.Process(pid).cpu_times()
        return float(times.user + times.system)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return 0.0


def list_foreground_app_processes():
    """
    Return visible foreground-style app processes for manual game selection.

    Each entry includes process_path, process_name, window_title, is_foreground,
    and usage_score (CPU time, for sorting by likely recent use).
    """
    foreground_hwnd = windll.user32.GetForegroundWindow()
    foreground_pid = _pid_for_window(foreground_hwnd) if foreground_hwnd else None
    own_pid = os.getpid()
    window_entries = []

    def enum_callback(hwnd, _lparam):
        if not _is_selectable_foreground_window(hwnd):
            return True
        window_entries.append({
            'hwnd': hwnd,
            'pid': _pid_for_window(hwnd),
            'window_title': _window_title_for_handle(hwnd),
            'z_index': len(window_entries),
        })
        return True

    enum_proc = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_callback)
    windll.user32.EnumWindows(enum_proc, 0)

    by_path = {}
    for entry in window_entries:
        pid = entry['pid']
        if not pid or pid == own_pid:
            continue

        try:
            process = psutil.Process(pid)
            process_name = process.name()
            process_path = process.exe()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

        if _should_skip_foreground_process(process_name, process_path, pid):
            continue

        process_path_key = process_path.lower()
        is_foreground = pid == foreground_pid and entry['hwnd'] == foreground_hwnd
        usage_score = _process_usage_score(pid)
        candidate = {
            'process_path': process_path,
            'process_name': process_name,
            'window_title': entry['window_title'],
            'is_foreground': is_foreground,
            'usage_score': usage_score,
            'z_index': entry['z_index'],
        }

        existing = by_path.get(process_path_key)
        if existing is None:
            by_path[process_path_key] = candidate
            continue

        existing_rank = (
            0 if existing['is_foreground'] else 1,
            existing['z_index'],
        )
        candidate_rank = (
            0 if candidate['is_foreground'] else 1,
            candidate['z_index'],
        )
        if candidate_rank < existing_rank:
            candidate['usage_score'] = max(existing['usage_score'], candidate['usage_score'])
            by_path[process_path_key] = candidate
        else:
            existing['usage_score'] = max(existing['usage_score'], candidate['usage_score'])
            if candidate['is_foreground']:
                existing['is_foreground'] = True
                existing['window_title'] = candidate['window_title']

    processes = list(by_path.values())
    processes.sort(key=lambda item: (
        0 if item['is_foreground'] else 1,
        -item['usage_score'],
        item['z_index'],
        (item['process_name'] or '').lower(),
    ))

    for item in processes:
        item.pop('z_index', None)
        item.pop('usage_score', None)

    return processes


def is_tracked_game_running():
    """Check if the tracked game process is still running (by PID only)."""
    global last_game_pid
    if last_game_pid is None:
        return False
    try:
        return psutil.Process(last_game_pid).is_running()
    except psutil.NoSuchProcess:
        return False
    except Exception as e:
        logger.error(f"Error checking tracked process by PID: {e}")
        return False

def _maybe_upgrade_folder_chain_wildcard(chain, current_process_path):
    """Widen a same-folder exact save to *.exe when a second exe appears in the chain."""
    from catswitch.folder_chain import chain_needs_wildcard_upgrade
    from catswitch.detected_apps import upgrade_detected_app_to_folder_wildcard

    if not chain_needs_wildcard_upgrade(chain):
        return True

    exact_path = chain.saved_exact_path
    if not exact_path:
        return False

    success, error = upgrade_detected_app_to_folder_wildcard(
        exact_path,
        chain.twitch_category,
    )
    if not success:
        return False

    return True


def _apply_folder_chain_category(
    chain,
    current_process_name,
    current_process_path,
    current_pid,
    current_window_title,
    callback,
):
    """Apply a prior same-folder chain match without running detection again."""
    from catswitch.detected_apps import find_matching_detected_app
    from catswitch.folder_chain import sync_chain_from_saved_app

    if _maybe_upgrade_folder_chain_wildcard(chain, current_process_path):
        detected_app = find_matching_detected_app(
            current_process_name,
            current_process_path,
        )
        if detected_app:
            sync_chain_from_saved_app(chain, detected_app)
            apply_saved_app_match(
                detected_app,
                current_process_name,
                current_process_path,
                callback,
                current_pid,
                window_title=current_window_title,
            )
            return True

    if chain.twitch_category:
        apply_saved_app_match(
            {
                'twitch_category': chain.twitch_category,
                'box_art_url': '',
            },
            current_process_name,
            current_process_path,
            callback,
            current_pid,
            window_title=current_window_title,
        )
        return True

    return False


def _evaluate_focused_window(
    current_process_name,
    current_process_path,
    current_window_title,
    current_pid,
    callback,
    client_id,
    oauth_token,
):
    """Run category matching/detection for the currently focused window."""
    if not current_process_name or not current_process_path:
        return

    exclusion_match = find_exclusion_match(current_process_name, current_process_path)
    if exclusion_match:
        logger.info(format_exclusion_skip_message(current_process_name, exclusion_match))
        return

    from catswitch.folder_chain import (
        note_exe_seen,
        should_skip_detection_for_chain,
        sync_chain_from_saved_app,
    )

    chain = note_exe_seen(current_process_path)

    detected_app = find_matching_detected_app_by_window_title(
        current_process_name, current_process_path, current_window_title
    )
    should_detect = False

    if detected_app:
        sync_chain_from_saved_app(chain, detected_app)
        _maybe_upgrade_folder_chain_wildcard(chain, current_process_path)
        apply_saved_app_match(
            detected_app,
            current_process_name,
            current_process_path,
            callback,
            current_pid,
            window_title=current_window_title,
        )
        return

    detected_app = find_matching_detected_app(current_process_name, current_process_path)

    if detected_app:
        if (
            saved_app_path_matches(current_process_path, detected_app)
            and entry_titles_compatible(current_window_title, detected_app)
        ):
            sync_chain_from_saved_app(chain, detected_app)
            _maybe_upgrade_folder_chain_wildcard(chain, current_process_path)
            apply_saved_app_match(
                detected_app,
                current_process_name,
                current_process_path,
                callback,
                current_pid,
                window_title=current_window_title,
            )
            return

        should_detect = True
    else:
        should_detect = True

    if should_skip_detection_for_chain(chain):
        _apply_folder_chain_category(
            chain,
            current_process_name,
            current_process_path,
            current_pid,
            current_window_title,
            callback,
        )
        return

    if not should_detect:
        return

    try:
        from catswitch.web_interface import is_category_locked
        if is_category_locked():
            logger.warning("Category locked - skipping game detection")
            return
    except ImportError:
        pass

    result = handle_window_change(
        client_id,
        oauth_token,
        current_window_title,
        current_process_path,
        strict_detection=_should_use_strict_detection(current_process_path),
    )

    if result:
        if isinstance(result, tuple):
            game_name, process_path = result
            from catswitch.folder_chain import (
                get_chain_for_path,
                mark_chain_after_save,
                resolve_detection_save_target,
            )

            result_chain = get_chain_for_path(process_path)
            save_path, _ = resolve_detection_save_target(
                result_chain,
                process_path,
                current_window_title,
            )
            mark_chain_after_save(result_chain, save_path, game_name)
            callback(game_name, process_path, False, None, current_window_title)
            remember_active_game(os.path.basename(process_path), game_name, current_pid)
        else:
            callback(result)
        return

    fallback_app = find_matching_detected_app(current_process_name, current_process_path)
    if fallback_app and saved_app_path_matches(current_process_path, fallback_app):
        apply_saved_app_match(
            fallback_app,
            current_process_name,
            current_process_path,
            callback,
            current_pid,
            window_title=current_window_title,
        )
        return

    _handle_failed_game_detection(
        current_process_name,
        current_process_path,
        current_window_title,
    )


def _should_use_strict_detection(process_path: Optional[str]) -> bool:
    """Use stricter matching when Discord does not recognize the process as a game."""
    from catswitch.settings import get_use_discord_detectable
    from catswitch.discord_detectable import is_process_discord_detectable

    if not get_use_discord_detectable():
        return False
    if not process_path:
        return False
    return not is_process_discord_detectable(process_path)


def _handle_failed_game_detection(process_name, process_path, window_title) -> None:
    """Auto-exclude processes that fail detection and are not Discord-detectable games."""
    from catswitch.settings import get_use_discord_detectable
    from catswitch.discord_detectable import is_process_discord_detectable
    from catswitch.excluded_apps import add_to_auto_excluded_apps

    if not get_use_discord_detectable():
        return

    if is_process_discord_detectable(process_path):
        return

    add_to_auto_excluded_apps(process_name, process_path, window_title)


def begin_game_detection_loop():
    """Activate the detection loop and return the current generation token."""
    global game_detection_running
    with game_detection_lock:
        game_detection_running = True
        return game_detection_generation


def is_detection_generation_current(generation: Optional[int]) -> bool:
    """True when this loop generation is still the active one (not stopped/restarted)."""
    if generation is None:
        return False
    with game_detection_lock:
        return game_detection_running and generation == game_detection_generation


def on_window_change(callback, client_id=None, oauth_token=None, generation=None):
    """Monitor active window changes and invoke the callback on change."""
    if generation is None:
        with game_detection_lock:
            generation = game_detection_generation

    def guarded_callback(*args, **kwargs):
        # Helix work can finish after stop/join timeout — drop stale results.
        if not is_detection_generation_current(generation):
            logger.warning("Ignoring stale game-detection callback after stop/restart")
            return
        callback(*args, **kwargs)

    tracked_process_name = None
    tracked_window_title = None
    focus_started_at = 0.0
    handled_for_current_focus = False
    
    while game_detection_running and generation == game_detection_generation:
        try:
            current_time = time.time()

            try:
                from catswitch.web_interface import is_category_locked
                category_locked = is_category_locked()
            except ImportError:
                category_locked = False
            
            # Check if previous game process is still running - do this first
            global last_game_process, last_game_name, last_game_pid
            if last_game_process and not is_tracked_game_running():
                logger.info(f"Game process {last_game_process} has ended")
                # Callback no-ops Twitch/UI updates while locked; still clear tracking.
                guarded_callback("SWITCH_TO_DEFAULT_CATEGORY")
                last_game_process = None
                last_game_name = None
                last_game_pid = None
                tracked_process_name = None
                tracked_window_title = None
                handled_for_current_focus = False
                sleep(1)  # Add a delay after process change detection
                continue
            
            current_process_name, current_process_path, current_window_title, current_pid = get_active_window_info()

            from catswitch.settings import get_switch_delay_seconds
            switch_delay_seconds = get_switch_delay_seconds()

            window_identity_changed = (
                current_process_name != tracked_process_name
                or current_window_title != tracked_window_title
            )

            if window_identity_changed:
                tracked_process_name = current_process_name
                tracked_window_title = current_window_title
                focus_started_at = current_time
                handled_for_current_focus = False
                if switch_delay_seconds <= 0 and not category_locked:
                    logger.info("Detected window change!")
                    _evaluate_focused_window(
                        current_process_name,
                        current_process_path,
                        current_window_title,
                        current_pid,
                        guarded_callback,
                        client_id,
                        oauth_token,
                    )
                    handled_for_current_focus = True
            elif (
                not handled_for_current_focus
                and current_process_name
                and current_process_path
                and (current_time - focus_started_at) >= switch_delay_seconds
            ):
                if not category_locked:
                    logger.info(f"Focused window held for {switch_delay_seconds}s - evaluating category switch")
                    _evaluate_focused_window(
                        current_process_name,
                        current_process_path,
                        current_window_title,
                        current_pid,
                        guarded_callback,
                        client_id,
                        oauth_token,
                    )
                    handled_for_current_focus = True
                        
            # Sleep between polls (1s is enough for category switching; cuts Win32/psutil churn)
            sleep(1)
        except Exception as e:
            logger.error(f"Error in window change monitor: {e}")
            sleep(2)  # Longer sleep on error

def calculate_similarity(search_term, game_name):
    """Calculate similarity between search term and game name."""
    search_lower = search_term.lower().strip()
    game_lower = game_name.lower().strip()
    search_norm = _normalize_name_for_path_match(search_term)

    if ': ' in game_name:
        base_part = game_name.split(': ', 1)[0].strip()
        base_norm = _normalize_name_for_path_match(base_part)
        if (
            search_lower == base_part.lower()
            or search_norm == base_norm
            or _compact_equivalent(search_term, base_part)
        ):
            return _round_score(1.0 - _extra_token_penalty(search_term, game_name))

    search_words = search_lower.split()
    word_match = all(_whole_word_in(word, game_name) for word in search_words)

    if ': ' in game_name:
        main_name = game_name.split(': ', 1)[1].strip().lower()

        if search_lower == main_name:
            logger.info(f"Exact match after colon for '{search_term}' in '{game_name}'")
            return 0.95
        if search_lower in main_name or main_name in search_lower:
            logger.info(f"Strong partial match after colon for '{search_term}' in '{game_name}'")
            return 0.85
        if word_match:
            logger.info(f"Word match after colon for '{search_term}' in '{game_name}'")
            return 0.75

    if search_norm == _normalize_name_for_path_match(game_name):
        return 1.0

    game_base = game_name.split(': ', 1)[0]
    if _compact_equivalent(search_term, game_base):
        return 1.0

    base_similarity = SequenceMatcher(None, search_lower, game_lower).ratio()

    if word_match and _extra_token_penalty(search_term, game_name) == 0.0:
        base_similarity += 0.2

    len_ratio = min(len(search_term), len(game_name)) / max(len(search_term), len(game_name))
    adjusted_similarity = base_similarity * (len_ratio * 0.5 + 0.5)

    if word_match:
        adjusted_similarity += 0.15

    penalty = _extra_token_penalty(search_term, game_name)
    if penalty:
        adjusted_similarity -= penalty
        logger.info(f"Extra-token penalty for '{game_name}' vs '{search_term}': "
            f"-{fmt_sim(penalty)}")

    conflict_penalty = _token_conflict_penalty(search_term, game_name)
    if conflict_penalty:
        adjusted_similarity -= conflict_penalty
        logger.info(f"Token conflict penalty for '{game_name}' vs '{search_term}': "
            f"-{fmt_sim(conflict_penalty)}")

    return round(max(min(adjusted_similarity, 1.0), 0.0), 3)


def _is_exact_title_match(search_term: str, game_name: str) -> bool:
    """True when the search term and category name are the same (ignoring case/punctuation)."""
    search = (search_term or '').strip()
    game = (game_name or '').strip()
    if not search or not game:
        return False
    if search.casefold() == game.casefold():
        return True
    if _normalize_name_for_path_match(search) == _normalize_name_for_path_match(game):
        return True
    return _compact_equivalent(search, game)


def _is_path_confirmed_match(path_boost: float, path_reason: str) -> bool:
    """True when a primary install-folder hint exactly matches the Twitch category."""
    if path_boost < PATH_CONFIRMED_EXACT_BOOST:
        return False
    return bool(path_reason and path_reason.startswith("exact path folder"))


def _strict_min_score_for_meta(meta: dict, strict_detection: bool) -> float:
    """Minimum score a candidate needs under strict detection."""
    if not strict_detection:
        return MIN_CONTENDER_SCORE
    if _is_path_confirmed_match(meta.get('path_boost', 0), meta.get('path_reason', '')):
        return PATH_CONFIRMED_MIN_MATCH_SCORE
    return NON_DISCORD_MIN_CONTENDER_SCORE


def _strict_detection_score_penalty(
    search_term: str,
    game_name: str,
    path_boost: float = 0.0,
    path_reason: str = '',
) -> float:
    """
    Penalty applied in strict (non-Discord) mode.

    Exact title matches waive the penalty only when the Twitch category name
    itself is multi-word (at least two words). Single-word categories like
    "Firefox" stay penalized even on an exact window-title match.

    Exact install-folder matches also waive the penalty — generic exe/window
    titles like 'coophorror' are overridden by steamapps/common folder names.
    """
    if _is_path_confirmed_match(path_boost, path_reason):
        return 0.0
    if not _is_exact_title_match(search_term, game_name):
        return NON_DISCORD_DETECTABLE_SCORE_PENALTY
    if len((game_name or '').split()) >= STRICT_EXACT_TITLE_MIN_CATEGORY_WORDS:
        return 0.0
    return NON_DISCORD_DETECTABLE_SCORE_PENALTY


def _apply_colon_subtitle_adjustment(score, search_term, game_name):
    """Boost series titles when the search term matches the subtitle after a colon."""
    if ': ' not in game_name:
        return score

    base_part = game_name.split(': ', 1)[0].strip()
    if _normalize_name_for_path_match(search_term) == _normalize_name_for_path_match(base_part):
        return score

    subtitle = game_name.split(': ', 1)[1].strip().lower()
    search_lower = search_term.lower()
    if search_lower == subtitle:
        adjusted = _round_score(score + 0.2)
        logger.info(f"Boosting score for '{game_name}' - exact match after colon (+0.2)")
        return adjusted
    if search_lower in subtitle or subtitle in search_lower:
        adjusted = _round_score(score + 0.1)
        logger.info(f"Boosting score for '{game_name}' - partial match after colon (+0.1)")
        return adjusted

    adjusted = _round_score(score + 0.05)
    logger.info(f"Minor boost for '{game_name}' as series title (+0.05)")
    return adjusted


def _title_path_score(search_term, game_name, path_hints):
    """Base score from window-title similarity and install-path hints."""
    similarity = calculate_similarity(search_term, game_name)
    path_boost, path_reason = path_match_boost(game_name, path_hints)
    if path_boost:
        similarity = _round_score(similarity + path_boost)
        logger.info(f"Path boost for '{game_name}': +{fmt_sim(path_boost)} "
            f"({path_reason}) -> {fmt_sim(similarity)}")
    score = _apply_colon_subtitle_adjustment(similarity, search_term, game_name)
    return score, path_boost, path_reason or ''


def _resolve_box_art_url(client_id, oauth_token, game_name, meta, helix_cache):
    """Return a box art URL from search metadata or Helix, using a per-call cache."""
    search_art = (meta.get('search_box_art_url') or '').strip()
    if search_art:
        return search_art

    if game_name in helix_cache:
        return helix_cache[game_name]

    art_url = ''
    try:
        game_info = fetch_category_info(client_id, oauth_token, game_name)
        if game_info:
            art_url = (game_info.get('box_art_url') or '').strip()
    except Exception as e:
        logger.error(f"Error fetching category info for '{game_name}': {e}")

    helix_cache[game_name] = art_url
    return art_url


def _apply_listing_quality_adjustments(
    base_score, game_name, meta, client_id, oauth_token, helix_cache
):
    """
    Adjust score for listing quality signals: box art presence and exact-lookup stubs.
    Exact title matches without box art are penalized so better listings stay in contention.
    """
    score = base_score
    box_art_url = _resolve_box_art_url(client_id, oauth_token, game_name, meta, helix_cache)

    if box_art_url:
        score = _round_score(score + BOX_ART_BOOST)
        logger.info(f"Listing quality for '{game_name}': box art present (+{fmt_sim(BOX_ART_BOOST)})")
    else:
        score = _round_score(score - MISSING_BOX_ART_PENALTY)
        logger.info(f"Listing quality for '{game_name}': no box art "
            f"(-{fmt_sim(MISSING_BOX_ART_PENALTY)})")

    if meta.get('exact_lookup_only') and not box_art_url:
        score = _round_score(score - EXACT_LOOKUP_PENALTY)
        logger.info(f"Listing quality for '{game_name}': exact lookup only stub "
            f"(-{fmt_sim(EXACT_LOOKUP_PENALTY)})")

    return score


def _gather_category_candidates(client_id, oauth_token, search_term, path_hints):
    """Collect Twitch category names from search; exact name lookup is fallback only."""
    candidates = []
    candidate_meta = {}

    def add_from_search(name, search_rank, game_id=None, box_art_url=None, from_title_query=False):
        if not name:
            return
        if name not in candidate_meta:
            candidates.append(name)
            candidate_meta[name] = {
                'search_rank': search_rank,
                'title_search_rank': search_rank if from_title_query else 999,
                'exact_lookup_only': False,
                'game_id': game_id,
                'search_box_art_url': box_art_url or '',
            }
        else:
            candidate_meta[name]['search_rank'] = min(
                candidate_meta[name]['search_rank'], search_rank
            )
            if from_title_query:
                candidate_meta[name]['title_search_rank'] = min(
                    candidate_meta[name]['title_search_rank'], search_rank
                )
            candidate_meta[name]['exact_lookup_only'] = False
            if game_id and not candidate_meta[name].get('game_id'):
                candidate_meta[name]['game_id'] = game_id
            if box_art_url and not candidate_meta[name].get('search_box_art_url'):
                candidate_meta[name]['search_box_art_url'] = box_art_url

    def add_from_exact_lookup(name):
        if not name:
            return
        if name not in candidate_meta:
            candidates.append(name)
            candidate_meta[name] = {
                'search_rank': 999,
                'title_search_rank': 999,
                'exact_lookup_only': True,
                'game_id': get_game_id(client_id, oauth_token, name),
                'search_box_art_url': '',
            }
        else:
            candidate_meta[name]['exact_lookup_only'] = True
            if not candidate_meta[name].get('game_id'):
                candidate_meta[name]['game_id'] = get_game_id(client_id, oauth_token, name)

    queries = [search_term]
    for hint_name, hint_weight in path_hints:
        if hint_weight >= 0.9 and hint_name not in queries:
            queries.append(hint_name)

    for query_index, query in enumerate(queries):
        from_title_query = query_index == 0
        for result_index, category in enumerate(
            search_twitch_categories(client_id, oauth_token, query, limit=10)
        ):
            add_from_search(
                category.get('name', ''),
                query_index * 20 + result_index,
                category.get('id'),
                category.get('box_art_url'),
                from_title_query=from_title_query,
            )

    if not candidates:
        if get_game_id(client_id, oauth_token, search_term):
            add_from_exact_lookup(search_term)
        for hint_name, hint_weight in path_hints:
            if hint_weight >= 0.9 and get_game_id(client_id, oauth_token, hint_name):
                add_from_exact_lookup(hint_name)

    return candidates, candidate_meta


def try_find_game(client_id, oauth_token, search_term, process_path=None, strict_detection=False):
    """Attempt to find a game based on the search term."""
    path_hints = extract_path_hints(process_path) if process_path else []
    if path_hints:
        logger.info(f"Install path hints: {[f'{name} ({weight})' for name, weight in path_hints]}")

    category_names, candidate_meta = _gather_category_candidates(
        client_id, oauth_token, search_term, path_hints
    )

    if not category_names:
        logger.info(f"No games found for search term '{search_term}'")
        return None, 0.0, 0.0

    logger.info(f"Twitch candidates for '{search_term}': {category_names}")

    discord_app_name = None
    if process_path and not strict_detection:
        from catswitch.discord_detectable import get_discord_app_name
        discord_app_name = get_discord_app_name(process_path)
        if discord_app_name:
            logger.info(f"Discord detectable app name: {discord_app_name}")

    helix_cache = {}
    title_scored = []
    for name in category_names:
        try:
            base_score, path_boost, path_reason = _title_path_score(search_term, name, path_hints)
            meta = dict(candidate_meta.get(name, {}))
            meta['title_path_score'] = base_score
            meta['path_boost'] = path_boost
            meta['path_reason'] = path_reason
            title_scored.append((name, base_score, meta))
        except Exception as e:
            logger.error(f"Error scoring '{name}': {e}")

    if not title_scored:
        return None, 0.0, 0.0

    title_scored.sort(key=lambda x: x[1], reverse=True)
    quality_pool = title_scored[:QUALITY_PASS_POOL]

    scored_candidates = []
    for name, base_score, meta in quality_pool:
        final_score = _apply_listing_quality_adjustments(
            base_score, name, meta, client_id, oauth_token, helix_cache
        )
        if strict_detection:
            candidate_penalty = _strict_detection_score_penalty(
                search_term,
                name,
                meta.get('path_boost', 0),
                meta.get('path_reason', ''),
            )
            if candidate_penalty:
                final_score = _round_score(max(0.0, final_score - candidate_penalty))
                logger.info(f"Score for '{name}': {fmt_sim(final_score)} "
                    f"after non-Discord penalty (-{fmt_sim(candidate_penalty)})")
            elif _is_path_confirmed_match(
                meta.get('path_boost', 0), meta.get('path_reason', ''),
            ):
                logger.info(f"Score for '{name}': {fmt_sim(final_score)} "
                    f"(exact install-folder match — no strict penalty)")
            elif _is_exact_title_match(search_term, name):
                meta['exact_title_match'] = True
                logger.info(f"Score for '{name}': {fmt_sim(final_score)} "
                    f"(exact title match on multi-word category — no strict penalty)")
        elif final_score != base_score:
            logger.info(f"Score for '{name}': {fmt_sim(base_score)} -> {fmt_sim(final_score)} "
                f"after listing quality")
        if (
            discord_app_name
            and name.casefold() == discord_app_name.casefold()
        ):
            boosted = _round_score(final_score + DISCORD_NAME_MATCH_BOOST)
            logger.info(f"Discord name match boost for '{name}': "
                f"{fmt_sim(final_score)} -> {fmt_sim(boosted)} "
                f"(+{fmt_sim(DISCORD_NAME_MATCH_BOOST)})")
            final_score = boosted
            meta['discord_name_boost'] = DISCORD_NAME_MATCH_BOOST
        scored_candidates.append((name, final_score, meta))

    scored_candidates.sort(key=lambda x: x[1], reverse=True)
    top_candidates = scored_candidates[:MAX_SCORED_CANDIDATES]

    logger.info(f"Top {len(top_candidates)} matches for '{search_term}':")
    for i, (game_name, score, _meta) in enumerate(top_candidates):
        logger.info(f"  {i + 1}. '{game_name}': score={fmt_sim(score)}")

    contenders = [
        (name, score, meta)
        for name, score, meta in top_candidates
        if score >= _strict_min_score_for_meta(meta, strict_detection)
    ]
    if not contenders:
        return None, 0.0, 0.0

    best_title_path = max(meta.get('title_path_score', 0) for _, _, meta in contenders)
    best_score = max(score for _, score, _ in contenders)
    close_contenders = [
        (name, score, meta)
        for name, score, meta in contenders
        if best_score - score <= CLOSE_MATCH_SCORE_SPAN
        and best_title_path - meta.get('title_path_score', 0) <= CLOSE_MATCH_SCORE_SPAN
    ]

    if len(close_contenders) >= 2:
        if best_title_path < FOLLOWER_BOOST_MIN_TITLE_PATH:
            logger.warning("Skipping follower boost: title/path scores too weak "
                f"(best title/path={fmt_sim(best_title_path)})")
        else:
            logger.info("Close match on title/path — applying follower boost: "
                + ", ".join(f"'{name}'={fmt_sim(score)}" for name, score, _ in close_contenders))
            follower_cache = {}
            close_rows = [
                (
                    name,
                    score,
                    bool(meta.get('search_box_art_url')),
                    meta.get('game_id'),
                    meta,
                )
                for name, score, meta in close_contenders
            ]
            boosted_rows = _apply_follower_boost_if_close(
                close_rows, client_id, oauth_token, follower_cache
            )
            boosted_by_name = {}
            for row in boosted_rows:
                name = row[0]
                new_score = row[1]
                boosted_by_name[name] = new_score
                orig_score = next(s for n, s, _ in close_contenders if n == name)
                boost_delta = round(new_score - orig_score, 3)
                for i, (c_name, c_score, c_meta) in enumerate(contenders):
                    if c_name == name:
                        c_meta['follower_boost'] = boost_delta
                        break

            contenders = [
                (name, boosted_by_name.get(name, score), meta)
                for name, score, meta in contenders
            ]

    contenders.sort(
        key=lambda x: (
            x[1],
            1 if x[2].get('exact_title_match') else 0,
            x[2].get('follower_boost', 0),
            x[2].get('title_path_score', 0),
            x[2].get('path_boost', 0),
            bool(x[2].get('search_box_art_url')),
            -x[2].get('title_search_rank', 999),
        ),
        reverse=True,
    )
    best_match, best_score, _meta = contenders[0]
    second_score = contenders[1][1] if len(contenders) > 1 else 0.0
    logger.info(f"Best match found: {best_match} with score {fmt_sim(best_score)}")
    return best_match, best_score, second_score

def handle_window_change(
    client_id,
    oauth_token,
    window_title,
    process_path=None,
    strict_detection=False,
):
    """Handle logic when the active window changes.

    On success returns (game_name, process_path). The caller should call
    remember_active_game(..., pid=) so exit tracking always has a PID.
    """
    if not process_path:
        process_name, process_path, _, _ = get_active_window_info()
    else:
        process_name = os.path.basename(process_path)

    if not process_name or not process_path:
        return None

    logger.info(f"Detected process: {process_name}")
    logger.info(f"Process path: {process_path}")
    logger.info(f"Window title: {window_title}")

    exclusion_match = find_exclusion_match(process_name, process_path)
    if exclusion_match:
        logger.info(format_exclusion_skip_message(process_name, exclusion_match))
        return None

    logger.info("Starting game detection...")
    if not window_title:
        return None

    logger.info(f"Game detected: {window_title}")

    cleaned_title = _clean_window_title_for_detection(window_title)
    if cleaned_title != window_title:
        logger.info(f"Cleaned title: {cleaned_title}")

    game_name = find_matching_game(
        client_id,
        oauth_token,
        cleaned_title,
        process_path,
        strict_detection=strict_detection,
    )

    # If no match by title, try process name (skip useless Unreal shipping exe names)
    if not game_name and not process_name.lower().endswith('-win64-shipping.exe'):
        search_term = process_name.replace('.exe', '')
        logger.info(f"Trying process name: {search_term}")
        game_name = find_matching_game(
            client_id,
            oauth_token,
            search_term,
            process_path,
            strict_detection=strict_detection,
        )

    # Last resort: dotted version tokens mangled the search (Bejeweled 1.23 → 123)
    if not game_name:
        deversioned = _last_resort_title_without_version(window_title)
        if deversioned:
            logger.info(
                "Retrying without end-ish dotted version: %r (from %r)",
                deversioned,
                window_title,
            )
            game_name = find_matching_game(
                client_id,
                oauth_token,
                deversioned,
                process_path,
                strict_detection=strict_detection,
            )

    if game_name:
        return (game_name, process_path)

    return None

def _remember_weak_match(best_weak, match_name, score, search_term):
    """Track the strongest rejected trim match for anchor comparison."""
    if score < MIN_CONTENDER_SCORE:
        return best_weak
    if _weak_match_well_aligned(search_term, match_name):
        return best_weak
    if best_weak is None or score > best_weak['score']:
        logger.info(f"Remembering weak match '{match_name}' ({fmt_sim(score)}) "
            f"from '{search_term}' for anchor comparison")
        return {'name': match_name, 'score': score, 'search_term': search_term}
    return best_weak


def _try_anchor_popularity_override(
    client_id,
    oauth_token,
    anchor,
    original_search_term,
    best_weak,
    process_path=None,
):
    """
    Last-resort fallback: pick an exact anchor-word category when it has box art
    and is massively more popular than a remembered weak trim match.
    """
    weak_name = best_weak['name']
    weak_score = best_weak['score']
    weak_term = best_weak['search_term']

    logger.info(f"Anchor fallback: testing '{anchor}' against remembered weak match "
        f"'{weak_name}' ({fmt_sim(weak_score)} from '{weak_term}')")

    anchor_match, anchor_score, _ = try_find_game(
        client_id, oauth_token, anchor, process_path, strict_detection=False,
    )
    if not anchor_match:
        logger.info(f"No match found for anchor word '{anchor}'")
        return None

    if not _is_anchor_exact_category(anchor, anchor_match):
        logger.warning(f"Anchor category '{anchor_match}' is not an exact match for "
            f"anchor word '{anchor}' — skipping override")
        return None

    if anchor_score < ANCHOR_OVERRIDE_MIN_SCORE:
        logger.info(f"Anchor match '{anchor_match}' score {fmt_sim(anchor_score)} "
            f"below minimum ({fmt_sim(ANCHOR_OVERRIDE_MIN_SCORE)})")
        return None

    if _weak_match_well_aligned(weak_term, weak_name):
        logger.warning(f"Weak match '{weak_name}' aligns with its trim term '{weak_term}' "
            f"— skipping anchor override")
        return None

    helix_cache = {}
    box_art = _resolve_box_art_url(client_id, oauth_token, anchor_match, {}, helix_cache)
    if not box_art:
        logger.warning(f"Anchor category '{anchor_match}' has no box art — skipping override")
        return None

    game_id_anchor = get_game_id(client_id, oauth_token, anchor_match)
    game_id_weak = get_game_id(client_id, oauth_token, weak_name)
    followers_anchor = fetch_game_followers_count(
        game_id=game_id_anchor, game_name=anchor_match,
    ) or 0
    followers_weak = fetch_game_followers_count(
        game_id=game_id_weak, game_name=weak_name,
    ) or 0

    ratio = followers_anchor / max(followers_weak, 1)
    logger.info(f"Anchor '{anchor_match}' followers: {followers_anchor}, "
        f"weak '{weak_name}' followers: {followers_weak}, ratio: {ratio:.1f}x")

    if ratio < ANCHOR_POPULARITY_RATIO_MIN:
        logger.warning(f"Follower ratio {ratio:.1f}x below threshold "
            f"({ANCHOR_POPULARITY_RATIO_MIN}x) — skipping anchor override")
        return None

    logger.info(f"Anchor popularity override: '{anchor_match}' selected over "
        f"'{weak_name}' ({ratio:.1f}x followers, box art present)")
    return anchor_match


def _find_with_progressive_trim(
    client_id,
    oauth_token,
    search_term,
    process_path=None,
):
    """Try full title, progressively trim from the end, then anchor override."""
    words = _split_search_words(search_term)
    if not words:
        return None

    best_weak = None

    for trim_count in range(0, len(words)):
        term = ' '.join(words[:-trim_count]) if trim_count else ' '.join(words)
        if not term.strip():
            continue

        if trim_count:
            logger.info(f"Trying shortened search term: '{term}'")

        match, score, second_score = try_find_game(
            client_id, oauth_token, term, process_path, strict_detection=False,
        )
        if not match:
            continue

        content_word_count = len(_split_search_words(term))
        threshold = _trim_acceptance_threshold(content_word_count)

        if _token_conflict_blocks_acceptance(term, match, score, process_path, second_score):
            logger.info(f"Rejected '{match}' for '{term}': token conflict "
                f"(score {fmt_sim(score)}, needed {fmt_sim(threshold)})")
            best_weak = _remember_weak_match(best_weak, match, score, term)
            continue

        if score >= threshold:
            logger.info(f"Accepted match '{match}' for '{term}' "
                f"(score {fmt_sim(score)}, threshold {fmt_sim(threshold)})")
            return match

        logger.info(f"Match '{match}' for '{term}' below threshold "
            f"({fmt_sim(score)} < {fmt_sim(threshold)})")
        best_weak = _remember_weak_match(best_weak, match, score, term)

    if best_weak:
        anchor = _extract_anchor_word(search_term)
        if anchor:
            return _try_anchor_popularity_override(
                client_id,
                oauth_token,
                anchor,
                search_term,
                best_weak,
                process_path,
            )

    return None


def find_matching_game(
    client_id,
    oauth_token,
    search_term,
    process_path=None,
    strict_detection=False,
):
    """Try to find a matching game from the Twitch API."""
    search_term = _clean_window_title_for_detection(search_term)
    logger.info(f"Trying to find game for search term: {search_term}")
    if strict_detection:
        logger.info("Using strict Discord-assisted detection (non-discord process)")

    if strict_detection:
        best_match, best_similarity, _ = try_find_game(
            client_id,
            oauth_token,
            search_term,
            process_path,
            strict_detection=True,
        )
        if best_match:
            if best_similarity >= NON_DISCORD_MIN_MATCH_SCORE:
                logger.info(f"Closest matching game detected: {best_match} (score: {fmt_sim(best_similarity)})")
                return best_match
            path_hints = extract_path_hints(process_path) if process_path else []
            path_boost, path_reason = path_match_boost(best_match, path_hints)
            if (
                _is_path_confirmed_match(path_boost, path_reason)
                and best_similarity >= PATH_CONFIRMED_MIN_MATCH_SCORE
            ):
                logger.info(f"Path-confirmed match: {best_match} "
                    f"(score: {fmt_sim(best_similarity)}, folder '{path_reason}')")
                return best_match
        logger.info(f"No strict match found for '{search_term}'")
        return None

    words = _split_search_words(search_term)
    if not words:
        return None

    if len(words) == 1:
        match, score, second_score = try_find_game(
            client_id, oauth_token, search_term, process_path, strict_detection=False,
        )
        if (
            match
            and score >= TRIM_THRESHOLD_SINGLE_WORD
            and not _token_conflict_blocks_acceptance(
                search_term, match, score, process_path, second_score,
            )
        ):
            logger.info(f"Closest matching game detected: {match} (score: {fmt_sim(score)})")
            return match
        logger.info(f"No matching game found for '{search_term}'")
        return None

    logger.info(f"Trying progressive trim for '{search_term}'...")
    trimmed = _find_with_progressive_trim(
        client_id, oauth_token, search_term, process_path,
    )
    if trimmed:
        logger.info(f"Closest matching game detected: {trimmed}")
        return trimmed

    logger.info(f"No matching game found for '{search_term}', even after trimming")
    return None


def stop_game_detection():
    """Stop the game detection loop and invalidate any in-flight loops/callbacks."""
    global game_detection_running, game_detection_generation
    with game_detection_lock:
        game_detection_generation += 1
        game_detection_running = False
    logger.info("Game detection stopped")