"""Helpers for semicolon-delimited list file fields.

Only \\; and \\\\ are escape sequences so Windows paths stay intact.
"""

LIST_FILE_VERSION = 1
CACHE_FILE_VERSION = 1

FIELD_SEP = ';'

LIST_FORMAT_FIELDS = {
    "detected": ("process_path", "app_name", "twitch_category", "window_title"),
    "excluded": ("executable", "description"),
    "title_presets": ("title", "assignments"),
}


def build_list_file_header(list_name: str, list_kind: str) -> str:
    """Standard header for user-editable list files."""
    fields = LIST_FORMAT_FIELDS.get(list_kind)
    if not fields:
        raise ValueError(f"Unknown list kind: {list_kind}")
    format_line = ",".join(fields)
    return (
        f"# {list_name}\n"
        f"# Version: {LIST_FILE_VERSION}\n"
        f"# Format: {format_line}\n"
    )


def build_cache_file_header() -> str:
    """Standard header for auto-managed cache files."""
    return f"# Version: {CACHE_FILE_VERSION}\n"


def escape_list_field(value: str) -> str:
    if value is None:
        return ''
    text = str(value)
    result = []
    for ch in text:
        if ch == '\\':
            result.append('\\\\')
        elif ch == FIELD_SEP:
            result.append('\\;')
        else:
            result.append(ch)
    return ''.join(result)


def split_list_fields(line: str, max_splits: int = -1) -> list[str]:
    """Split a line on unescaped semicolons."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    length = len(line)
    splits = 0

    while i < length:
        ch = line[i]
        if ch == '\\' and i + 1 < length:
            nxt = line[i + 1]
            if nxt == ';':
                current.append(';')
                i += 2
                continue
            if nxt == '\\':
                current.append('\\')
                i += 2
                continue
        if ch == FIELD_SEP and (max_splits < 0 or splits < max_splits):
            parts.append(''.join(current))
            current = []
            splits += 1
            i += 1
            continue
        current.append(ch)
        i += 1

    parts.append(''.join(current))
    return parts


def join_list_fields(*fields: str) -> str:
    return FIELD_SEP.join(escape_list_field(field) for field in fields)


def format_detected_app_line(
    process_path: str,
    app_name: str,
    twitch_category: str,
    window_title: str = '',
) -> str:
    return join_list_fields(process_path, app_name, twitch_category, window_title)


# The window-title field can hold multiple alternative titles separated by
# unescaped pipes. Escapes: \| for a literal pipe, \\ for a literal backslash.
TITLE_SEP = '|'


def escape_window_title(title: str) -> str:
    if title is None:
        return ''
    result = []
    for ch in str(title):
        if ch == '\\':
            result.append('\\\\')
        elif ch == TITLE_SEP:
            result.append('\\|')
        else:
            result.append(ch)
    return ''.join(result)


def split_window_titles(field: str) -> list[str]:
    """Split a window-title field into individual titles (unescaped, trimmed, non-empty)."""
    if not field:
        return []

    titles: list[str] = []
    current: list[str] = []
    i = 0
    length = len(field)

    while i < length:
        ch = field[i]
        if ch == '\\' and i + 1 < length:
            nxt = field[i + 1]
            if nxt == TITLE_SEP:
                current.append(TITLE_SEP)
                i += 2
                continue
            if nxt == '\\':
                current.append('\\')
                i += 2
                continue
        if ch == TITLE_SEP:
            titles.append(''.join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1

    titles.append(''.join(current))
    return [t.strip() for t in titles if t.strip()]


def join_window_titles(titles: list[str]) -> str:
    """Join individual titles into a window-title field, skipping empties."""
    cleaned = [str(t).strip() for t in (titles or []) if t and str(t).strip()]
    return TITLE_SEP.join(escape_window_title(t) for t in cleaned)
