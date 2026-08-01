"""python -m catswitch"""

import sys
from pathlib import Path

# Allow `python catswitch/__main__.py` or `python __main__.py` from inside
# the package folder — repo root must be on sys.path for `import catswitch`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from catswitch.console_log import install_console_capture

# Tee stdout/stderr before logging is configured so the Info console sees logs.
install_console_capture()

from catswitch.auth_twitch import TWITCH_CLIENT_ID, resolve_startup_token
from catswitch.desktop_app import run_desktop_app, ensure_single_instance
from catswitch.settings import *  # noqa: F401,F403 — initializes settings / AppData
from catswitch.settings import sync_autostart_on_launch


def main() -> None:
    debug_mode = "--debug" in sys.argv
    start_minimized = "--minimized" in sys.argv

    # Second launch: focus the existing window and exit immediately.
    if not ensure_single_instance():
        raise SystemExit(0)

    sync_autostart_on_launch()

    oauth_token = resolve_startup_token(TWITCH_CLIENT_ID)
    if oauth_token:
        print("Using saved account session")
    else:
        print("No valid saved account — welcome screen will be shown")

    run_desktop_app(
        TWITCH_CLIENT_ID,
        oauth_token,
        debug=debug_mode,
        start_minimized=start_minimized,
    )


if __name__ == "__main__":
    main()
