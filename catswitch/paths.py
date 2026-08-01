"""CatSwitch application data paths under %LOCALAPPDATA%\\CatSwitch."""

import logging
import os
import shutil
import sys

APP_NAME = "CatSwitch"
logger = logging.getLogger(__name__)


def get_app_data_dir() -> str:
    """Return %LOCALAPPDATA%\\CatSwitch, creating it if needed."""
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(local_appdata, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def get_settings_file_path() -> str:
    return os.path.join(get_app_data_dir(), "settings.json")


def get_tokens_dir() -> str:
    return os.path.join(get_app_data_dir(), "accounts", "tokens")


def get_detected_lists_dir() -> str:
    return os.path.join(get_app_data_dir(), "lists", "detected")


def _strip_detected_list_txt_extension(name: str) -> str:
    if name.lower().endswith(".txt"):
        return name[:-4]
    return name


def _detected_list_filename(stored: str) -> str:
    normalized = stored.replace("/", os.sep).replace("\\", os.sep)
    if normalized.lower().endswith(".txt"):
        return normalized
    return f"{normalized}.txt"


def relativize_detected_list_path(path: str) -> str:
    """Store paths under lists/detected as list ids (e.g. Local)."""
    if not path:
        return path
    abs_path = os.path.normpath(os.path.abspath(path))
    detected_dir = os.path.normpath(get_detected_lists_dir())
    try:
        in_detected_dir = os.path.commonpath([abs_path, detected_dir]) == detected_dir
    except ValueError:
        in_detected_dir = False
    if in_detected_dir:
        rel = os.path.relpath(abs_path, detected_dir).replace("\\", "/")
        if "/" not in rel:
            return _strip_detected_list_txt_extension(rel)
        return rel
    return abs_path.replace("\\", "/")


def resolve_detected_list_path(path: str) -> str:
    """Resolve a stored detected-list path to an absolute filesystem path."""
    if not path:
        return path
    if os.path.isabs(path):
        return os.path.normpath(path)
    normalized = path.replace("/", os.sep)
    detected_prefix = os.path.join("lists", "detected")
    if normalized == detected_prefix or normalized.startswith(detected_prefix + os.sep):
        return os.path.normpath(os.path.join(get_app_data_dir(), normalized))
    if os.sep not in normalized and "/" not in path:
        normalized = _detected_list_filename(normalized)
    return os.path.normpath(os.path.join(get_detected_lists_dir(), normalized))


def detected_list_paths_equal(path_a: str, path_b: str) -> bool:
    """Return True when two stored detected-list paths refer to the same file."""
    if not path_a or not path_b:
        return path_a == path_b
    resolved_a = os.path.normcase(resolve_detected_list_path(path_a))
    resolved_b = os.path.normcase(resolve_detected_list_path(path_b))
    return resolved_a == resolved_b


def get_excluded_lists_dir() -> str:
    return os.path.join(get_app_data_dir(), "lists", "excluded")


def get_cache_dir() -> str:
    return os.path.join(get_app_data_dir(), "cache")


def get_titles_dir() -> str:
    return os.path.join(get_app_data_dir(), "lists", "titles")


def get_title_presets_file_path() -> str:
    return os.path.join(get_titles_dir(), "Local.txt")


def get_detected_games_cache_path() -> str:
    return os.path.join(get_cache_dir(), "detected_games.cache")


def get_categories_cache_path() -> str:
    return os.path.join(get_cache_dir(), "categories.cache")


def get_discord_detectable_cache_path() -> str:
    return os.path.join(get_cache_dir(), "discord_detectable.json")


def get_category_images_dir() -> str:
    return os.path.join(get_cache_dir(), "images")


def get_themes_dir() -> str:
    return os.path.join(get_app_data_dir(), "themes")


def get_package_dir() -> str:
    """Return the catswitch package directory (dev or PyInstaller bundle)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "catswitch")
    return os.path.dirname(os.path.abspath(__file__))


def get_app_root_dir() -> str:
    """Directory that holds LICENSE / PRIVACY / notices (install dir or repo root)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(get_package_dir())


def get_resources_dir() -> str:
    """Return bundled resources (static, templates, themes, assets, lists)."""
    return os.path.join(get_package_dir(), "resources")


def get_bundled_themes_dir() -> str:
    """Return bundled default theme CSS files shipped with the app."""
    return os.path.join(get_resources_dir(), "themes")


def get_bundled_excluded_lists_dir() -> str:
    """Return bundled default excluded-app list files shipped with the app."""
    return os.path.join(get_resources_dir(), "lists", "excluded")


def get_app_icon_path() -> str:
    """Return the bundled white CatSwitch application icon."""
    return os.path.join(get_resources_dir(), "assets", "app-icon.ico")


def get_static_dir() -> str:
    return os.path.join(get_resources_dir(), "static")


def get_templates_dir() -> str:
    return os.path.join(get_resources_dir(), "templates")


def seed_bundled_themes() -> None:
    """Copy bundled theme CSS into AppData when missing. Never overwrites."""
    bundled_dir = get_bundled_themes_dir()
    themes_dir = get_themes_dir()
    os.makedirs(themes_dir, exist_ok=True)

    if not os.path.isdir(bundled_dir):
        logger.warning("Bundled themes directory not found: %s", bundled_dir)
        return

    for name in sorted(os.listdir(bundled_dir)):
        if not name.lower().endswith(".css"):
            continue
        src = os.path.join(bundled_dir, name)
        if not os.path.isfile(src):
            continue
        dest = os.path.join(themes_dir, name)
        if os.path.exists(dest):
            continue
        shutil.copy2(src, dest)
        logger.info("Seeded theme into AppData: %s", name)


def seed_bundled_excluded_lists() -> None:
    """Copy bundled excluded lists into AppData when missing. Never overwrites."""
    bundled_dir = get_bundled_excluded_lists_dir()
    dest_dir = get_excluded_lists_dir()
    os.makedirs(dest_dir, exist_ok=True)

    if not os.path.isdir(bundled_dir):
        logger.warning("Bundled excluded lists directory not found: %s", bundled_dir)
        return

    for name in sorted(os.listdir(bundled_dir)):
        if not name.lower().endswith(".txt"):
            continue
        src = os.path.join(bundled_dir, name)
        if not os.path.isfile(src):
            continue
        dest = os.path.join(dest_dir, name)
        if os.path.exists(dest):
            continue
        shutil.copy2(src, dest)
        logger.info("Seeded excluded list into AppData: %s", name)


def ensure_app_data_layout() -> None:
    """Create the AppData folder structure on first launch."""
    for path in (
        get_app_data_dir(),
        get_tokens_dir(),
        get_detected_lists_dir(),
        get_excluded_lists_dir(),
        get_titles_dir(),
        get_cache_dir(),
        get_category_images_dir(),
        get_themes_dir(),
    ):
        os.makedirs(path, exist_ok=True)

    seed_bundled_themes()
    seed_bundled_excluded_lists()


def resolve_data_path(path: str) -> str:
    """Resolve list paths relative to the AppData root."""
    if not path:
        return path
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(get_app_data_dir(), path))
