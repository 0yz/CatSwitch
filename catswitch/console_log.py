"""
In-app console log capture.

Tees stdout/stderr so every line that would appear in the terminal is also
stored in a bounded in-memory buffer for the Info tab console.
"""

from __future__ import annotations

import sys
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional

MAX_CONSOLE_LINES = 10000

_lock = threading.Lock()
_next_id = 1
_lines: Deque[Dict[str, object]] = deque(maxlen=MAX_CONSOLE_LINES)
_installed = False


def _append_line(text: str, stream: str) -> Dict[str, object]:
    global _next_id

    entry = {
        'id': _next_id,
        'text': text,
        'stream': stream,
        'timestamp': time.time(),
    }
    _next_id += 1

    with _lock:
        _lines.append(entry)
    return entry


def get_logs_since(since_id: int = 0) -> List[Dict[str, object]]:
    with _lock:
        if since_id <= 0:
            return [dict(entry) for entry in _lines]
        return [dict(entry) for entry in _lines if entry['id'] > since_id]


def get_latest_id() -> int:
    with _lock:
        if not _lines:
            return 0
        return int(_lines[-1]['id'])


class _TeeStream:
    """Mirror writes to the original stream and record complete lines."""

    def __init__(self, original, stream_name: str):
        # Frozen --windowed builds often have sys.__stdout__/__stderr__ as None.
        self._original = original
        self._stream_name = stream_name
        self._buffer = ''

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            text = str(text)

        written = len(text)
        if self._original is not None:
            try:
                written = self._original.write(text)
            except Exception:
                written = len(text)

        if text:
            self._buffer += text
            while '\n' in self._buffer:
                line, self._buffer = self._buffer.split('\n', 1)
                if line:
                    _append_line(line, self._stream_name)
        return written

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass
        if self._buffer:
            line = self._buffer.rstrip('\r\n')
            self._buffer = ''
            if line:
                _append_line(line, self._stream_name)

    def isatty(self) -> bool:
        if self._original is None:
            return False
        try:
            return bool(self._original.isatty())
        except Exception:
            return False

    def fileno(self) -> int:
        if self._original is None:
            raise OSError(9, "Bad file descriptor")
        return self._original.fileno()

    @property
    def encoding(self) -> Optional[str]:
        if self._original is None:
            return "utf-8"
        return getattr(self._original, 'encoding', None) or "utf-8"

    def __getattr__(self, name: str):
        if self._original is None:
            raise AttributeError(name)
        return getattr(self._original, name)


def install_console_capture() -> None:
    """Install stdout/stderr tees once for the process."""
    global _installed

    if _installed:
        return

    # Prefer the real interpreter streams; fall back when windowed/frozen.
    stdout_orig = sys.__stdout__ if sys.__stdout__ is not None else sys.stdout
    stderr_orig = sys.__stderr__ if sys.__stderr__ is not None else sys.stderr

    sys.stdout = _TeeStream(stdout_orig, 'stdout')
    sys.stderr = _TeeStream(stderr_orig, 'stderr')

    # If logging was already configured against the real streams, point handlers
    # at the tees so the Info console keeps receiving logger output.
    import logging

    for handler in logging.root.handlers:
        if not isinstance(handler, logging.StreamHandler):
            continue
        stream = getattr(handler, "stream", None)
        if stream is sys.__stderr__ or stream is stderr_orig:
            handler.setStream(sys.stderr)
        elif stream is sys.__stdout__ or stream is stdout_orig:
            handler.setStream(sys.stdout)

    _installed = True
