"""
Category box art cache.

Maps Twitch category names to locally cached images. Index lives in
cache/categories.cache (tab-separated). Image files live in cache/images/.
"""

import hashlib
import logging
import os
import re
import threading
from typing import Dict, Optional, Set, Tuple, Iterable, Union
from urllib.error import URLError
from urllib.request import Request, urlopen

from catswitch.paths import (
    get_categories_cache_path,
    get_category_images_dir,
    get_cache_dir,
)
from catswitch.list_format import build_cache_file_header

logger = logging.getLogger(__name__)

PLACEHOLDER = ""
TAB = "\t"
MAX_IMAGE_BYTES = 2 * 1024 * 1024
TWITCH_BOX_ART_URL_TEMPLATE = (
    "https://static-cdn.jtvnw.net/ttv-boxart/{art_id}-{width}x{height}.jpg"
)
BOX_ART_ID_RE = re.compile(r"/ttv-boxart/(.+?)-\{width\}x\{height\}", re.I)

_file_lock = threading.Lock()
_twitch_client_id: Optional[str] = None
_twitch_oauth_token: Optional[str] = None


def configure_twitch(client_id: Optional[str], oauth_token: Optional[str]) -> None:
    global _twitch_client_id, _twitch_oauth_token
    _twitch_client_id = client_id or None
    _twitch_oauth_token = oauth_token or None


def _category_key(category: str) -> str:
    return (category or "").strip().lower()


def _display_category(category: str) -> str:
    return (category or "").strip()


def _is_remote_template(url: str) -> bool:
    return bool(url) and "{width}" in url and "{height}" in url


def art_id_from_source(source: str) -> str:
    """Normalize a Twitch template URL or bare art id to the id segment."""
    source = (source or "").strip()
    if not source:
        return ""
    if _is_remote_template(source):
        match = BOX_ART_ID_RE.search(source)
        if match:
            return match.group(1)
    if source.startswith("http"):
        return source
    return source


def template_from_art_id(art_id: str) -> str:
    return TWITCH_BOX_ART_URL_TEMPLATE.replace("{art_id}", art_id)


def _entry_template(entry: Dict[str, str]) -> str:
    art_id = (entry.get("art_id") or "").strip()
    if art_id and not art_id.startswith("http"):
        return template_from_art_id(art_id)
    return art_id if _is_remote_template(art_id) else ""


def _resolved_download_url(template_url: str) -> str:
    return template_url.replace("{width}", "100").replace("{height}", "133")


def _serve_url(filename: str) -> str:
    return f"/api/cache/images/{filename}"


def _ensure_layout() -> None:
    os.makedirs(get_category_images_dir(), exist_ok=True)
    os.makedirs(get_cache_dir(), exist_ok=True)


def _load_index() -> Dict[str, Dict[str, str]]:
    path = get_categories_cache_path()
    index: Dict[str, Dict[str, str]] = {}
    if not os.path.exists(path):
        return index
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(TAB)
                if len(parts) < 3:
                    continue
                category = parts[0].strip()
                raw_source = parts[1].strip()
                local_file = parts[2].strip()
                if not category or not local_file:
                    continue
                key = _category_key(category)
                art_id = art_id_from_source(raw_source)
                index[key] = {
                    "category": category,
                    "art_id": art_id,
                    "local_file": local_file,
                }
    except Exception as exc:
        logger.error(f"Error reading categories cache: {exc}")
    return index


def _write_index(index: Dict[str, Dict[str, str]]) -> None:
    path = get_categories_cache_path()
    _ensure_layout()
    lines = [build_cache_file_header().rstrip("\n")]
    for key in sorted(index.keys()):
        entry = index[key]
        art_id = entry.get("art_id") or ""
        lines.append(
            TAB.join([
                entry["category"],
                art_id,
                entry["local_file"],
            ])
        )
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _local_image_path(filename: str) -> str:
    return os.path.join(get_category_images_dir(), filename)


def _image_file_exists(filename: str) -> bool:
    if not filename:
        return False
    path = _local_image_path(filename)
    return os.path.isfile(path) and os.path.getsize(path) > 0


def _new_filename(category_key: str, content: bytes) -> str:
    digest = hashlib.sha1(category_key.encode("utf-8") + content[:128]).hexdigest()[:12]
    return f"{digest}.jpg"


def _fetch_image(template_url: str) -> Optional[bytes]:
    if not _is_remote_template(template_url):
        return None
    download_url = _resolved_download_url(template_url)
    try:
        request = Request(download_url, headers={"User-Agent": "CatSwitch/1.0"})
        with urlopen(request, timeout=12) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if content_type and not content_type.startswith("image/"):
                logger.warning(f"Unexpected content type for box art: {content_type}")
            data = response.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                logger.warning("Box art image too large, skipping cache")
                return None
            if not data:
                return None
            return data
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning(f"Failed to download box art from {download_url}: {exc}")
        return None


def _helix_template(category: str) -> Optional[str]:
    if not _twitch_client_id or not _twitch_oauth_token:
        return None
    try:
        from catswitch.update_twitch import fetch_category_info

        info = fetch_category_info(_twitch_client_id, _twitch_oauth_token, category)
        if info and info.get("box_art_url"):
            return info["box_art_url"]
    except Exception as exc:
        logger.warning(f"Helix lookup failed for category '{category}': {exc}")
    return None


def upsert_template(
    category: str,
    source_template: str,
    *,
    fetch_if_missing: bool = True,
) -> str:
    """Store or refresh a category template and return a serve URL."""
    category = _display_category(category)
    source_template = (source_template or "").strip()
    if not category:
        return PLACEHOLDER
    art_id = art_id_from_source(source_template)
    template = template_from_art_id(art_id) if art_id and not art_id.startswith("http") else source_template
    if not _is_remote_template(template):
        return resolve_box_art(category, fetch_if_missing=fetch_if_missing)

    key = _category_key(category)
    with _file_lock:
        index = _load_index()
        entry = index.get(key)
        entry_art_id = entry.get("art_id") if entry else ""
        if entry and entry_art_id == art_id and _image_file_exists(entry.get("local_file", "")):
            return _serve_url(entry["local_file"])

        image_bytes = _fetch_image(template) if fetch_if_missing else None
        if not image_bytes:
            if entry and _image_file_exists(entry.get("local_file", "")):
                entry["art_id"] = art_id
                entry["category"] = category
                index[key] = entry
                _write_index(index)
                return _serve_url(entry["local_file"])
            return PLACEHOLDER

        filename = _new_filename(key, image_bytes)
        _ensure_layout()
        path = _local_image_path(filename)
        with open(path, "wb") as handle:
            handle.write(image_bytes)

        old_file = entry.get("local_file") if entry else None
        index[key] = {
            "category": category,
            "art_id": art_id,
            "local_file": filename,
        }
        _write_index(index)
        if old_file and old_file != filename:
            _delete_image_file(old_file)

    return _serve_url(filename)


def resolve_box_art(
    category: str,
    source_template: Optional[str] = None,
    *,
    fetch_if_missing: bool = True,
) -> str:
    """Resolve a Twitch category to a cached image URL."""
    category = _display_category(category)
    if not category:
        return PLACEHOLDER

    template = (source_template or "").strip()
    if _is_remote_template(template):
        return upsert_template(category, template, fetch_if_missing=fetch_if_missing)

    key = _category_key(category)
    with _file_lock:
        index = _load_index()
        entry = index.get(key)
        if entry and _image_file_exists(entry.get("local_file", "")):
            return _serve_url(entry["local_file"])
        cached_template = _entry_template(entry) if entry else None

    if cached_template and _is_remote_template(cached_template):
        return upsert_template(category, cached_template, fetch_if_missing=fetch_if_missing)

    if fetch_if_missing:
        helix_template = _helix_template(category)
        if helix_template:
            return upsert_template(category, helix_template, fetch_if_missing=True)

    return PLACEHOLDER


def collect_needed_categories(
    loaded_apps: Dict[str, Dict[str, str]],
    extra_categories: Optional[Set[str]] = None,
) -> Set[str]:
    needed: Set[str] = set()
    for info in loaded_apps.values():
        category = _display_category(info.get("twitch_category", ""))
        if category:
            needed.add(_category_key(category))
    if extra_categories:
        for category in extra_categories:
            category = _display_category(category)
            if category:
                needed.add(_category_key(category))
    return needed


def _delete_image_file(filename: str) -> None:
    if not filename:
        return
    path = _local_image_path(filename)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.warning(f"Failed to delete cached image {path}: {exc}")


def prune_unused(needed_category_keys: Set[str]) -> int:
    """Remove cache rows (and files) for categories that are no longer referenced."""
    removed = 0
    with _file_lock:
        index = _load_index()
        stale_keys = [key for key in index if key not in needed_category_keys]
        if not stale_keys:
            return 0
        for key in stale_keys:
            entry = index.pop(key, None)
            if entry:
                _delete_image_file(entry.get("local_file", ""))
                removed += 1
        _write_index(index)
    if removed:
        logger.info(f"Pruned {removed} unused category box art cache entries")
    return removed


def prefetch_category_box_art(categories: Iterable[str]) -> None:
    """Download and cache box art for each unique Twitch category."""
    seen: Set[str] = set()
    for raw in categories:
        category = _display_category(raw)
        if not category:
            continue
        key = _category_key(category)
        if key in seen:
            continue
        seen.add(key)
        try:
            resolve_box_art(category, fetch_if_missing=True)
        except Exception as exc:
            logger.warning(f"Failed to prefetch box art for '{category}': {exc}")


def prefetch_categories_for_apps(
    apps: Union[Dict[str, Dict[str, str]], Iterable[Dict[str, str]]],
) -> None:
    """Prefetch cached box art for every unique category referenced by app entries."""
    if isinstance(apps, dict):
        values = apps.values()
    else:
        values = apps
    prefetch_category_box_art(
        info.get("twitch_category", "")
        for info in values
        if isinstance(info, dict)
    )


def enrich_app_dict(app: Dict[str, str], fetch_if_missing: bool = True) -> Dict[str, str]:
    category = app.get("twitch_category", "")
    app["box_art_url"] = resolve_box_art(category, fetch_if_missing=fetch_if_missing)
    return app
