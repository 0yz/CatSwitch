import os
import io
import json
import threading
import time
import functools
import requests
import logging
from flask import Flask, render_template, jsonify, request, Response, send_from_directory, redirect, url_for, session
from ctypes import windll
import webview
import random
from difflib import SequenceMatcher
import shutil
from typing import Optional

from catswitch.update_twitch import (
    get_stream_info, 
    update_stream_category, 
    update_stream_title, 
    fetch_categories, 
    fetch_category_info,
    get_current_twitch_category
)
from catswitch.detect_game import on_window_change
from catswitch import category_cache
from catswitch.paths import get_category_images_dir
from catswitch.excluded_apps import (
    create_new_file, download_from_url, update_from_url, load_from_url_live,
    delete_file, read_file_content, get_file_info, reload_excluded_apps, get_excluded_apps_dir,
    add_excluded_app_file, resolve_url_list_name, find_local_excluded_list,
)
from catswitch.settings import (
    get_excluded_app_files, get_detected_app_files, add_detected_app_file,
    set_detected_app_list_enabled, set_excluded_app_list_enabled, update_detected_app_url_list,
)
from catswitch.detected_apps import (
    load_detected_apps, save_detected_app, get_all_detected_apps,
    remove_detected_app, add_to_excluded_apps, add_manual_detected_app,
    remove_matching_detected_app_for_exclude,
    add_detected_app_to_file, record_detection_result,
    loaded_detected_apps, saved_app_path_matches,
    move_detected_app_between_lists, get_detected_list_info_by_path,
    find_matching_detected_app_by_window_title,
)
from catswitch import title_presets
from catswitch.auth_twitch import (
    TWITCH_CLIENT_ID,
    start_device_login,
    poll_device_login,
    cancel_device_login,
    get_pending_device_login,
    register_account_session,
    fetch_twitch_user,
    probe_twitch_token,
    get_saved_account_profile,
    refresh_account_tokens,
    TOKEN_VALID,
    TOKEN_INVALID,
    TOKEN_UNREACHABLE,
    list_accounts,
    get_active_login,
    set_active_login,
    load_account_token,
    remove_account as remove_auth_account,
    validate_token,
)
from catswitch.paths import get_static_dir, get_templates_dir

app = Flask(
    __name__,
    static_folder=None,
    template_folder=get_templates_dir(),
)

# Setup logging
logger = logging.getLogger(__name__)

# Fixed local UI port (must match desktop_app.LOCAL_SERVER_PORT / Twitch redirect).
_LOCAL_UI_PORT = 51111
_ALLOWED_HOSTS = frozenset({
    f"127.0.0.1:{_LOCAL_UI_PORT}",
    f"localhost:{_LOCAL_UI_PORT}",
    f"[::1]:{_LOCAL_UI_PORT}",
})
_ALLOWED_ORIGINS = frozenset({
    f"http://127.0.0.1:{_LOCAL_UI_PORT}",
    f"http://localhost:{_LOCAL_UI_PORT}",
    f"http://[::1]:{_LOCAL_UI_PORT}",
})


@app.before_request
def _protect_local_api():
    """Block DNS-rebinding and cross-site calls to the loopback API."""
    host = (request.host or "").lower()
    if host not in _ALLOWED_HOSTS:
        logger.warning("Rejected request with Host=%r path=%r", request.host, request.path)
        return jsonify({"success": False, "error": "Forbidden"}), 403

    if not request.path.startswith("/api/"):
        return None

    site = (request.headers.get("Sec-Fetch-Site") or "").lower()
    if site and site != "same-origin":
        logger.warning(
            "Rejected cross-site API request Sec-Fetch-Site=%r path=%r",
            site,
            request.path,
        )
        return jsonify({"success": False, "error": "Forbidden"}), 403

    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin and origin not in _ALLOWED_ORIGINS:
        logger.warning("Rejected API request with Origin=%r path=%r", origin, request.path)
        return jsonify({"success": False, "error": "Forbidden"}), 403

    if not origin:
        referer = request.headers.get("Referer") or ""
        if referer and not any(
            referer == allowed or referer.startswith(allowed + "/")
            for allowed in _ALLOWED_ORIGINS
        ):
            logger.warning(
                "Rejected API request with Referer=%r path=%r", referer, request.path
            )
            return jsonify({"success": False, "error": "Forbidden"}), 403

    return None


# Global state
CLIENT_ID = None
OAUTH_TOKEN = None
OAUTH_TOKEN_VALID = True
_oauth_expiry_notified = False
_oauth_expiry_lock = threading.Lock()
_session_needs_online_check = False
CATEGORY_LOCKED = False
TITLE_LOCKED = False
active_title_mode = None  # 'assigned', 'default', 'manual', or None
user_info = None
current_stream_title = None
current_title_template = None  # Raw title with %cat before Twitch substitution

# Staged OAuth (browser completed login; app has not confirmed yet)
_pending_oauth = {"token": None, "user": None, "created_at": 0.0}
_pending_oauth_lock = threading.Lock()
PENDING_OAUTH_TTL = 600  # seconds


def _clear_pending_oauth():
    global _pending_oauth
    _pending_oauth = {"token": None, "user": None, "created_at": 0.0}


def stage_oauth_token(oauth_token: str) -> dict:
    """Validate a token from the browser callback without activating the session."""
    user = fetch_twitch_user(CLIENT_ID, oauth_token)
    if not user:
        raise ValueError("Invalid Twitch token")

    global _pending_oauth
    with _pending_oauth_lock:
        _pending_oauth = {
            "token": oauth_token,
            "user": user,
            "created_at": time.time(),
        }
    return user


def get_pending_oauth_user() -> dict | None:
    with _pending_oauth_lock:
        token = _pending_oauth.get("token")
        user = _pending_oauth.get("user")
        created_at = _pending_oauth.get("created_at") or 0
        if not token or not user:
            return None
        if time.time() - created_at > PENDING_OAUTH_TTL:
            _clear_pending_oauth()
            return None
        return dict(user)


def consume_pending_oauth_token() -> str | None:
    with _pending_oauth_lock:
        token = _pending_oauth.get("token")
        if not token:
            return None
        created_at = _pending_oauth.get("created_at") or 0
        if time.time() - created_at > PENDING_OAUTH_TTL:
            _clear_pending_oauth()
            return None
        _clear_pending_oauth()
        return token


def discard_pending_oauth() -> None:
    with _pending_oauth_lock:
        _clear_pending_oauth()


def _try_focus_app_window() -> None:
    try:
        import win32gui
        import win32con

        hwnd = win32gui.FindWindow(None, 'CatSwitch')
        if not hwnd:
            return
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
    except Exception:
        pass


def try_refresh_active_oauth_token() -> bool:
    """Refresh the active account access token in place. Returns True on success."""
    global OAUTH_TOKEN, OAUTH_TOKEN_VALID, _oauth_expiry_notified

    login = get_active_login()
    if not login:
        return False
    new_access = refresh_account_tokens(login, CLIENT_ID)
    if not new_access:
        return False

    OAUTH_TOKEN = new_access
    OAUTH_TOKEN_VALID = True
    with _oauth_expiry_lock:
        _oauth_expiry_notified = False
    try:
        category_cache.configure_twitch(CLIENT_ID, OAUTH_TOKEN)
    except Exception:
        pass
    logger.info("Active OAuth token refreshed for %s", login)
    return True


def notify_oauth_token_expired():
    """Mark the OAuth token invalid and prompt the user to re-authenticate.

    Tries a refresh-token exchange first so long sessions stay signed in.
    """
    global OAUTH_TOKEN_VALID, _oauth_expiry_notified
    if not OAUTH_TOKEN:
        return
    if try_refresh_active_oauth_token():
        return
    with _oauth_expiry_lock:
        if _oauth_expiry_notified or not OAUTH_TOKEN_VALID:
            OAUTH_TOKEN_VALID = False
            return
        OAUTH_TOKEN_VALID = False
        _oauth_expiry_notified = True
    logger.warning("OAuth token expired — user must re-authenticate")
    try:
        if webview.windows:
            webview.windows[0].evaluate_js(
                "showConfirmationModal('Authentication Expired', "
                "'Twitch authentication expired. Open account settings and sign in again.', "
                "null, null, 'OK')"
            )
    except Exception as e:
        logger.error(f"Error showing token expiry modal: {e}")

# Game detection thread state
game_detection_thread = None
latest_detected_game = None     # What the detection system found
manual_category = None          # What user manually selected
current_twitch_category = None  # What's currently set on Twitch
current_box_art_url = None      # Box art URL for the current category
game_detection_initialized = False  # Flag to prevent creating multiple threads
_game_detection_start_lock = threading.Lock()


def _join_game_detection_thread(timeout=2.0):
    """Wait for the current detection thread to exit after a stop signal."""
    global game_detection_thread
    with _game_detection_start_lock:
        thread = game_detection_thread
    if thread and thread.is_alive():
        thread.join(timeout=timeout)


def is_authenticated() -> bool:
    return bool(OAUTH_TOKEN and OAUTH_TOKEN_VALID)


def restart_game_detection():
    """Stop and restart game detection so it uses the current OAuth token."""
    global game_detection_initialized
    from catswitch.detect_game import stop_game_detection

    stop_game_detection()
    _join_game_detection_thread()
    with _game_detection_start_lock:
        game_detection_initialized = False
    if OAUTH_TOKEN:
        create_game_detection_thread()


def refresh_session_state_from_stream():
    """Load user and current category state from Twitch after login or account switch."""
    global user_info, current_twitch_category, current_box_art_url, OAUTH_TOKEN_VALID
    global _oauth_expiry_notified, current_stream_title, _session_needs_online_check

    if not OAUTH_TOKEN:
        user_info = None
        _session_needs_online_check = False
        return False

    status, user = probe_twitch_token(CLIENT_ID, OAUTH_TOKEN)

    if status == TOKEN_INVALID:
        if try_refresh_active_oauth_token():
            status, user = probe_twitch_token(CLIENT_ID, OAUTH_TOKEN)
        if status == TOKEN_INVALID:
            OAUTH_TOKEN_VALID = False
            user_info = None
            _session_needs_online_check = False
            return False

    if status == TOKEN_UNREACHABLE:
        # Keep session while offline — UI shows the offline overlay instead of welcome.
        OAUTH_TOKEN_VALID = True
        _session_needs_online_check = True
        if not user_info:
            user_info = get_saved_account_profile()
        with _oauth_expiry_lock:
            _oauth_expiry_notified = False
        logger.info("Twitch unreachable — keeping saved session until connectivity returns")
        return True

    user_info = user
    OAUTH_TOKEN_VALID = True
    _session_needs_online_check = False
    with _oauth_expiry_lock:
        _oauth_expiry_notified = False

    try:
        stream_info = get_stream_info(CLIENT_ID, OAUTH_TOKEN)
        if stream_info:
            title = stream_info.get("title")
            game_name = stream_info.get("game_name")
            processed_art = None
            if game_name:
                category_info = fetch_category_info(CLIENT_ID, OAUTH_TOKEN, game_name)
                if category_info and category_info.get("box_art_url"):
                    processed_art = process_box_art_url(
                        category_info["box_art_url"], game_name
                    )
            with app_state_lock:
                if title:
                    current_stream_title = title
                if game_name:
                    current_twitch_category = game_name
                    current_box_art_url = processed_art
    except Exception as e:
        logger.error(f"Error refreshing stream state: {e}")

    return True


def activate_oauth_session(oauth_token: str, refresh_token: str | None = None) -> dict:
    """Register or update an account and make it the active session."""
    global OAUTH_TOKEN

    user = register_account_session(oauth_token, CLIENT_ID, refresh_token=refresh_token)
    if not user:
        raise ValueError("Invalid Twitch token")

    OAUTH_TOKEN = oauth_token
    refresh_session_state_from_stream()
    restart_game_detection()
    return user


def switch_to_account(login: str) -> dict:
    """Switch the active session to a saved account."""
    global OAUTH_TOKEN, user_info

    token = load_account_token(login)
    if not token:
        raise ValueError(f"Saved token for '{login}' is invalid or expired")

    if not validate_token(CLIENT_ID, token):
        refreshed = refresh_account_tokens(login, CLIENT_ID)
        if refreshed:
            token = refreshed
        else:
            raise ValueError(f"Saved token for '{login}' is invalid or expired")

    set_active_login(login)
    OAUTH_TOKEN = token
    refresh_session_state_from_stream()
    restart_game_detection()
    return user_info or {"login": login}


def clear_active_session():
    """Log out the current account without removing it from the saved list."""
    global OAUTH_TOKEN, user_info, current_twitch_category, current_box_art_url, OAUTH_TOKEN_VALID
    from catswitch.detect_game import stop_game_detection

    stop_game_detection()
    _join_game_detection_thread()
    global game_detection_initialized
    with _game_detection_start_lock:
        game_detection_initialized = False

    OAUTH_TOKEN = None
    user_info = None
    current_twitch_category = None
    current_box_art_url = None
    OAUTH_TOKEN_VALID = True
    set_active_login(None)
app_state_lock = threading.Lock()

def is_category_locked():
    """Thread-safe read of the category lock flag."""
    with app_state_lock:
        return CATEGORY_LOCKED


def is_title_locked():
    """Thread-safe read of the title lock flag."""
    with app_state_lock:
        return TITLE_LOCKED

# Add tracking for API operations to prevent duplicates
api_operation_lock = threading.Lock()
api_operation_in_progress = {}

def prevent_duplicate_api_call(operation_name, timeout=2):
    """Decorator to prevent duplicate API calls for the same operation"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            global api_operation_in_progress
            
            operation_time = time.time()
            
            # First check if we need to block this operation
            should_skip = False
            with api_operation_lock:
                # Check if operation is in progress and not timed out
                if operation_name in api_operation_in_progress:
                    last_time = api_operation_in_progress[operation_name]
                    elapsed = operation_time - last_time
                    
                    # Only skip if the operation started very recently
                    if elapsed < 0.5:  # 500ms threshold for very rapid duplicates
                        logger.warning(f"Blocking duplicate API call: {operation_name} (too soon after previous call)")
                        should_skip = True
            
            # If we need to skip, return successful response (don't show error to user)
            if should_skip:
                return jsonify({"status": "success"})
            
            # Otherwise, mark operation as in progress and proceed
            with api_operation_lock:
                api_operation_in_progress[operation_name] = operation_time
            
            try:
                # Execute the actual function
                result = func(*args, **kwargs)
                return result
            finally:
                # Always clean up - no matter what
                with api_operation_lock:
                    if operation_name in api_operation_in_progress:
                        # Only remove if it's our operation or very old
                        current_time = time.time()
                        last_time = api_operation_in_progress[operation_name]
                        if last_time == operation_time or (current_time - last_time > timeout):
                            del api_operation_in_progress[operation_name]
                            logger.info(f"Cleaned up operation: {operation_name}")
        
        return wrapper
    return decorator

def create_game_detection_thread():
    """Create and start the game detection thread."""
    global game_detection_thread, game_detection_initialized
    from catswitch.detect_game import begin_game_detection_loop

    with _game_detection_start_lock:
        if not OAUTH_TOKEN:
            logger.warning("Skipping game detection thread — not authenticated")
            return

        if game_detection_initialized:
            logger.info("Game detection thread already initialized")
            return

        logger.info("Starting game detection thread")
        game_detection_initialized = True
        generation = begin_game_detection_loop()

        def game_callback(game, process_name=None, is_existing_match=False, box_art_url=None, window_title=None):
            """Callback for when a game is detected"""
            global latest_detected_game, manual_category, current_twitch_category, CATEGORY_LOCKED, current_box_art_url
            from catswitch.detect_game import is_detection_generation_current

            if not is_detection_generation_current(generation):
                logger.warning("Ignoring stale game-detection callback after stop/restart")
                return
            
            if not game:
                return
            if game == "SWITCH_TO_JUST_CHATTING" or game == "SWITCH_TO_DEFAULT_CATEGORY":
                from catswitch.settings import get_default_category
                game = get_default_category()

            with app_state_lock:
                if CATEGORY_LOCKED:
                    logger.warning(f"Category locked - skipping game detection for: {game}")
                    return

                logger.info(f"Game detected: {game}")
                latest_detected_game = game

                if manual_category:
                    if game != manual_category:
                        logger.info(f"Detected new game ({game}) different from manual selection ({manual_category})")
                        manual_category = None
                    else:
                        logger.info(f"Manual category active ({manual_category}) - not updating")
                        return

                if is_existing_match:
                    logger.info(f"Applying saved app category instantly: {game}")
                    current_twitch_category = game
                    if box_art_url and str(box_art_url).startswith('/'):
                        current_box_art_url = box_art_url
                    else:
                        current_box_art_url = category_cache.resolve_box_art(
                            game, box_art_url, fetch_if_missing=False
                        )
                    ui_game = game
                    ui_art = current_box_art_url
                else:
                    should_update_twitch = game != current_twitch_category
                    previous_category = current_twitch_category
                    unchanged_art = current_box_art_url

            if is_existing_match:
                update_ui_with_game(ui_game, ui_art, False, process_name, True, window_title)
                maybe_apply_title_preset(ui_game, process_name, window_title)
                logger.info(f"Saved app category applied instantly: {ui_game}")
                return

            if should_update_twitch:
                logger.info(f"Updating Twitch category: {game} (previous: {previous_category})")
                try:
                    updated, twitch_box_art_url = update_stream_category(
                        CLIENT_ID, OAUTH_TOKEN, game
                    )
                    with app_state_lock:
                        if CATEGORY_LOCKED or not is_detection_generation_current(generation):
                            return
                        if updated:
                            current_twitch_category = game
                            if twitch_box_art_url:
                                current_box_art_url = category_cache.upsert_template(
                                    game, twitch_box_art_url
                                )
                                ui_art = current_box_art_url
                            else:
                                ui_art = category_cache.resolve_box_art(
                                    game, fetch_if_missing=False
                                )
                                current_box_art_url = ui_art or current_box_art_url
                        else:
                            ui_art = None
                    if updated:
                        record_detection_result(process_name, window_title, game)
                        update_ui_with_game(game, ui_art, False, process_name, is_existing_match, window_title)
                        maybe_apply_title_preset(game, process_name, window_title)
                        logger.info(f"Game updated successfully to: {game}")
                    else:
                        logger.warning(f"Failed to update category to: {game}")
                except Exception as e:
                    logger.error(f"Error updating category: {e}")
            else:
                logger.info(f"Game unchanged from current Twitch category: {game}")
                record_detection_result(process_name, window_title, game)
                update_ui_with_game(game, unchanged_art, False, process_name, False, window_title)
                maybe_apply_title_preset(game, process_name, window_title)

        game_detection_thread = threading.Thread(
            target=lambda: on_window_change(
                game_callback,
                CLIENT_ID,
                OAUTH_TOKEN,
                generation,
            ),
            daemon=True,
        )
        game_detection_thread.start()
        logger.info("Game detection thread started")

@app.route('/')
def index():
    """Serve the main HTML interface."""
    from datetime import datetime

    from catswitch.version import APP_VERSION

    return render_template(
        'index.html',
        app_version=APP_VERSION,
        copyright_year=datetime.now().year,
    )


@app.route('/api/open-legal', methods=['POST'])
def api_open_legal():
    """Open a shipped legal file next to the app (LICENSE, PRIVACY, notices)."""
    from catswitch.paths import get_app_root_dir

    data = request.get_json(silent=True) or {}
    key = (data.get('file') or '').strip().lower()
    names = {
        'license': 'LICENSE',
        'privacy': 'PRIVACY.md',
        'notices': 'THIRD_PARTY_NOTICES.txt',
    }
    filename = names.get(key)
    if not filename:
        return jsonify({'success': False, 'error': 'Unknown file'}), 400

    path = os.path.join(get_app_root_dir(), filename)
    if not os.path.isfile(path):
        logger.error('Legal file missing: %s', path)
        return jsonify({'success': False, 'error': f'{filename} not found'}), 404

    try:
        os.startfile(path)
        return jsonify({'success': True})
    except OSError as exc:
        logger.error('Failed to open legal file %s: %s', path, exc)
        return jsonify({'success': False, 'error': str(exc)}), 500

@app.route('/static/<path:path>')
def serve_static(path):
    """Serve static files."""
    return send_from_directory(get_static_dir(), path)

@app.route('/api/connectivity-check')
def api_connectivity_check():
    """Return whether the machine can reach the public internet (Twitch API)."""
    try:
        requests.get(
            'https://api.twitch.tv/helix/games',
            headers={'Client-ID': CLIENT_ID or TWITCH_CLIENT_ID},
            timeout=4,
        )
        return jsonify({'online': True})
    except requests.RequestException as exc:
        logger.debug(f"Connectivity check failed: {exc}")
        return jsonify({'online': False})

@app.route('/api/cache/box-art')
def api_cache_box_art():
    """Fetch/cache box art for a single Twitch category (for progressive UI loading)."""
    category = request.args.get('category', '').strip()
    if not category:
        return jsonify({'error': 'Category is required'}), 400
    try:
        box_art_url = category_cache.resolve_box_art(category, fetch_if_missing=True)
        return jsonify({'category': category, 'box_art_url': box_art_url})
    except Exception as e:
        logger.error(f"Error resolving box art for '{category}': {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/cache/images/<path:filename>')
def api_cache_image(filename):
    """Serve cached category box art images."""
    safe_name = os.path.basename(filename)
    directory = get_category_images_dir()
    file_path = os.path.join(directory, safe_name)
    if not os.path.isfile(file_path):
        return jsonify({"error": "Image not found"}), 404
    return send_from_directory(directory, safe_name)

@app.route('/api/auth/status')
def api_auth_status():
    """Return authentication and saved account state."""
    # Re-probe after connectivity returns (startup may have been offline).
    if OAUTH_TOKEN and (
        _session_needs_online_check or not user_info or not OAUTH_TOKEN_VALID
    ):
        refresh_session_state_from_stream()
        if user_info and OAUTH_TOKEN_VALID and not game_detection_initialized:
            create_game_detection_thread()

    accounts = list_accounts()
    active_login = get_active_login()
    return jsonify(
        {
            "authenticated": is_authenticated(),
            "active_login": active_login,
            "accounts": accounts,
            "user": user_info,
        }
    )


@app.route('/api/auth/login-url')
def api_auth_login_url():
    """Return device-login bootstrap info (legacy path name kept for callers)."""
    try:
        info = start_device_login(CLIENT_ID, open_browser=False)
        return jsonify({"success": True, **info})
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 502


@app.route('/api/auth/open-login', methods=['POST'])
def api_auth_open_login():
    """Start Device Code Flow and open Twitch activate page in the browser."""
    try:
        info = start_device_login(CLIENT_ID, open_browser=True)
        return jsonify({"success": True, **info})
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 502


@app.route('/api/auth/device/start', methods=['POST'])
def api_auth_device_start():
    """Start Device Code Flow (same as open-login)."""
    data = request.get_json(silent=True) or {}
    open_browser = data.get("open_browser", True) is not False
    try:
        info = start_device_login(CLIENT_ID, open_browser=open_browser)
        return jsonify({"success": True, **info})
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 502


@app.route('/api/auth/device/poll', methods=['POST'])
def api_auth_device_poll():
    """Poll pending device authorization; activate session on success."""
    result = poll_device_login()
    status = result.get("status")
    if status == "success":
        try:
            user = activate_oauth_session(
                result["access_token"],
                refresh_token=result.get("refresh_token"),
            )
            _try_focus_app_window()
            return jsonify(
                {
                    "success": True,
                    "status": "success",
                    "user": user,
                    "accounts": list_accounts(),
                    "active_login": get_active_login(),
                }
            )
        except ValueError as e:
            return jsonify({"success": False, "status": "error", "error": str(e)}), 400

    payload = {"success": True, "status": status}
    if result.get("user_code"):
        payload["user_code"] = result["user_code"]
    if result.get("retry_after"):
        payload["retry_after"] = result["retry_after"]
    if result.get("error"):
        payload["error"] = result["error"]
        payload["success"] = status not in ("error", "denied", "expired")
    if status in ("denied", "expired", "error"):
        return jsonify(payload), 400 if status == "error" else 200
    return jsonify(payload)


@app.route('/api/auth/device/cancel', methods=['POST'])
def api_auth_device_cancel():
    cancel_device_login()
    return jsonify({"success": True})


@app.route('/api/auth/device/pending')
def api_auth_device_pending():
    pending = get_pending_device_login()
    return jsonify({"pending": bool(pending), "device": pending})


@app.route('/api/auth/stage', methods=['POST'])
def api_auth_stage():
    """Legacy implicit-flow staging (accepts access token if still used)."""
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"success": False, "error": "No token provided"}), 400

    try:
        user = stage_oauth_token(token)
        _try_focus_app_window()
        return jsonify({"success": True, "user": user})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/auth/pending')
def api_auth_pending():
    """Return staged OAuth user info if the browser login is awaiting confirmation."""
    user = get_pending_oauth_user()
    return jsonify({"pending": bool(user), "user": user})


@app.route('/api/auth/confirm', methods=['POST'])
def api_auth_confirm():
    """Confirm staged OAuth and activate the account session."""
    token = consume_pending_oauth_token()
    if not token:
        return jsonify({"success": False, "error": "No pending login to confirm"}), 400

    try:
        user = activate_oauth_session(token)
        return jsonify(
            {
                "success": True,
                "user": user,
                "accounts": list_accounts(),
                "active_login": get_active_login(),
            }
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/auth/cancel-pending', methods=['POST'])
def api_auth_cancel_pending():
    """Discard a staged OAuth login."""
    discard_pending_oauth()
    return jsonify({"success": True})


@app.route('/api/auth/complete', methods=['POST'])
def api_auth_complete():
    """Complete OAuth after the browser redirect; save account and activate session."""
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"success": False, "error": "No token provided"}), 400

    try:
        user = activate_oauth_session(token)
        _try_focus_app_window()
        return jsonify(
            {
                "success": True,
                "user": user,
                "accounts": list_accounts(),
                "active_login": get_active_login(),
            }
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/auth/switch', methods=['POST'])
def api_auth_switch():
    """Switch to another saved account."""
    data = request.get_json(silent=True) or {}
    login = (data.get("login") or "").strip().lower()
    if not login:
        return jsonify({"success": False, "error": "No account specified"}), 400

    try:
        user = switch_to_account(login)
        return jsonify(
            {
                "success": True,
                "user": user,
                "active_login": get_active_login(),
            }
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 401


@app.route('/api/auth/remove', methods=['POST'])
def api_auth_remove():
    """Remove a saved account."""
    data = request.get_json(silent=True) or {}
    login = (data.get("login") or "").strip().lower()
    if not login:
        return jsonify({"success": False, "error": "No account specified"}), 400

    was_active = get_active_login() == login
    if not remove_auth_account(login):
        return jsonify({"success": False, "error": "Account not found"}), 404

    if was_active:
        next_login = get_active_login()
        if next_login:
            try:
                switch_to_account(next_login)
            except ValueError:
                clear_active_session()
        else:
            clear_active_session()

    return jsonify(
        {
            "success": True,
            "accounts": list_accounts(),
            "active_login": get_active_login(),
            "authenticated": is_authenticated(),
        }
    )


@app.route('/api/stream-info')
def api_stream_info():
    """API endpoint to get stream info."""
    if not is_authenticated():
        return jsonify({"error": "Not authenticated"}), 401

    stream_info = get_stream_info(CLIENT_ID, OAUTH_TOKEN)
    if stream_info:
        global current_stream_title, current_title_template
        twitch_title = stream_info.get('title') or ''
        with app_state_lock:
            category = stream_info.get('game_name') or current_twitch_category
            existing_template = current_title_template
        if twitch_title:
            with app_state_lock:
                current_stream_title = twitch_title
        if not existing_template or (
            title_presets.CATEGORY_PLACEHOLDER in (existing_template or '')
            and title_presets.resolve_title_text(existing_template, category) != twitch_title
        ):
            from catswitch.detect_game import get_active_window_info
            _, active_path, _, active_window = get_active_window_info()
            inferred = _infer_title_template(
                twitch_title, category, active_path, active_window
            )
            with app_state_lock:
                current_title_template = inferred
                template = current_title_template or twitch_title
        else:
            with app_state_lock:
                template = current_title_template or twitch_title
        stream_info['title_template'] = template
        stream_info['title'] = (
            title_presets.resolve_title_text(template, category)
            if title_presets.CATEGORY_PLACEHOLDER in template
            else twitch_title
        )
        # After getting stream info, fetch the box art URL
        if 'game_name' in stream_info and stream_info['game_name']:
            category_info = fetch_category_info(CLIENT_ID, OAUTH_TOKEN, stream_info['game_name'])
            if category_info and 'box_art_url' in category_info:
                box_art_url = category_info['box_art_url']
                processed_url = process_box_art_url(box_art_url, stream_info['game_name'])
                stream_info['box_art_url'] = processed_url
        return jsonify(stream_info)
    return jsonify({"error": "Failed to get stream info"}), 500

@app.route('/api/categories')
def api_categories():
    """API endpoint to search for categories."""
    query = request.args.get('query', '')
    categories = fetch_categories(CLIENT_ID, OAUTH_TOKEN, query)
    return jsonify(categories)

@app.route('/api/update-category', methods=['POST'])
@prevent_duplicate_api_call("update_category")
def api_update_category():
    """API endpoint to update the category. Returns the new boxart URL."""
    
    global manual_category, latest_detected_game, current_twitch_category, current_box_art_url, CATEGORY_LOCKED
    
    # Get category name from request
    category_name = request.json.get('category_name')
    if not category_name:
        return jsonify({"error": "No category name provided"}), 400
    
    # Try finding the closest matching game using similarity
    try:
        # Get list of categories matching the search query
        categories = search_categories(category_name, CLIENT_ID, OAUTH_TOKEN)
        
        # If we found matching categories, find the closest match using similarity
        if categories and len(categories) > 0:
            # Get the best matching game using same similarity algorithm as auto detection
            best_match, similarity = find_best_match(category_name, categories)
            if best_match and similarity > 0.25:  # Use reasonable threshold
                logger.info(f"Found closest match for '{category_name}': '{best_match}' (Similarity: {similarity:.2f})")
                # Use the best matching game name instead of user input
                category_name = best_match
    except Exception as e:
        logger.error(f"Error finding similar category: {e}")
        # Continue with original category name if similarity matching fails
    
    # Update tracked manual category
    with app_state_lock:
        manual_category = category_name
        latest_detected_game = category_name
    
    # Attempt to update the category on Twitch
    try:
        # Try to get full category info first
        category_info = fetch_category_info(CLIENT_ID, OAUTH_TOKEN, category_name)
        full_category_name = category_name  # Default to user's input
        
        # If we have category info, get the official name
        if category_info and 'name' in category_info:
            full_category_name = category_info['name']
            logger.info(f"Found full category name: {full_category_name}")
        
        # Call the Twitch API to update the category
        updated, box_art_url = update_stream_category(CLIENT_ID, OAUTH_TOKEN, category_name)

        if updated:
            processed_url = process_box_art_url(box_art_url, full_category_name)
            with app_state_lock:
                current_twitch_category = full_category_name
                current_box_art_url = processed_url

            from catswitch.settings import get_auto_lock_category_on_manual
            auto_lock = get_auto_lock_category_on_manual()
            lock_applied = False
            with app_state_lock:
                if auto_lock and not CATEGORY_LOCKED:
                    CATEGORY_LOCKED = True
                    if current_twitch_category and not manual_category:
                        manual_category = current_twitch_category
                    lock_applied = True

            # Update UI using the helper function
            update_ui_with_game(full_category_name, processed_url, True)
            maybe_apply_title_preset(full_category_name)

            return jsonify({
                "status": "success",
                "box_art_url": processed_url,
                "full_category_name": full_category_name,
                "category_locked": CATEGORY_LOCKED if auto_lock else None,
                "lock_applied": lock_applied,
            })
        else:
            return jsonify({"error": "Failed to update category on Twitch"}), 500
    except Exception as e:
        logger.error(f"Error in manual category update: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/update-title', methods=['POST'])
def api_update_title():
    """API endpoint to update the stream title."""
    data = request.json
    title = data.get('title')
    
    if not title:
        return jsonify({"success": False, "error": "Title is required"}), 400

    global current_stream_title, current_title_template, active_title_mode, TITLE_LOCKED
    with app_state_lock:
        category = current_twitch_category
    resolved = title_presets.resolve_title_text(title, category)
    lock_applied = False
    success = update_stream_title(CLIENT_ID, OAUTH_TOKEN, resolved)
    if success:
        from catswitch.settings import get_auto_lock_title_on_manual
        auto_lock = get_auto_lock_title_on_manual()
        with app_state_lock:
            current_stream_title = resolved
            current_title_template = title
            active_title_mode = 'manual'
            if auto_lock and not TITLE_LOCKED:
                TITLE_LOCKED = True
                lock_applied = True
            title_locked_state = TITLE_LOCKED
    else:
        title_locked_state = None
    return jsonify({
        "success": success,
        "resolved_title": resolved,
        "title_template": title if success else None,
        "title_locked": title_locked_state if success else None,
        "lock_applied": lock_applied,
    })


def _fingerprint_from_request_game(game: dict) -> str:
    return title_presets.compute_fingerprint(
        game.get('process_path', ''),
        game.get('twitch_category', ''),
        game.get('window_title', ''),
        game.get('app_name', ''),
    )


def _detected_entries_by_fingerprint() -> dict:
    return {
        title_presets.entry_fingerprint(info): info
        for info in loaded_detected_apps.values()
    }


@app.route('/api/title-presets/list')
def api_title_presets_list():
    """List all title presets with their assigned games resolved for display."""
    entries = _detected_entries_by_fingerprint()
    presets = []
    for preset in title_presets.get_presets():
        games = []
        for fp in preset['fingerprints']:
            entry = entries.get(fp)
            if entry:
                games.append({
                    'resolved': True,
                    'process_path': entry.get('process_path', ''),
                    'app_name': entry.get('app_name', ''),
                    'twitch_category': entry.get('twitch_category', ''),
                    'window_title': entry.get('window_title', ''),
                    'box_art_url': entry.get('box_art_url') or category_cache.resolve_box_art(
                        entry.get('twitch_category', ''), fetch_if_missing=True
                    ),
                })
            else:
                games.append({'resolved': False})
        presets.append({
            'title': preset['title'],
            'games': games,
            'has_assignments': any(game.get('resolved') for game in games),
            'is_favorite': title_presets.is_favorite(preset['title']),
        })
    return jsonify({
        'presets': presets,
        'default_title': title_presets.get_default_title(),
        'favorite_titles': title_presets.get_favorite_titles(),
    })


@app.route('/api/title-presets/add', methods=['POST'])
def api_title_presets_add():
    data = request.get_json(silent=True) or {}
    success, error = title_presets.add_preset(data.get('title', ''))
    return jsonify({'success': success, 'error': error})


@app.route('/api/title-presets/rename', methods=['POST'])
def api_title_presets_rename():
    data = request.get_json(silent=True) or {}
    success, error = title_presets.rename_preset(data.get('old_title', ''), data.get('new_title', ''))
    return jsonify({'success': success, 'error': error})


@app.route('/api/title-presets/remove', methods=['POST'])
def api_title_presets_remove():
    data = request.get_json(silent=True) or {}
    success, error = title_presets.remove_preset(data.get('title', ''))
    return jsonify({'success': success, 'error': error})


@app.route('/api/title-presets/set-default', methods=['POST'])
def api_title_presets_set_default():
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'success': False, 'error': 'No title provided'}), 400
    success, error = title_presets.set_default_title(title)
    return jsonify({'success': success, 'error': error, 'default_title': title_presets.get_default_title()})


@app.route('/api/title-presets/clear-default', methods=['POST'])
def api_title_presets_clear_default():
    success, error = title_presets.clear_default_title()
    return jsonify({'success': success, 'error': error, 'default_title': title_presets.get_default_title()})


@app.route('/api/title-presets/apply-default', methods=['POST'])
def api_title_presets_apply_default():
    """Apply the default stream title preset immediately."""
    global current_stream_title, current_title_template, active_title_mode
    if not is_authenticated():
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    default_title = title_presets.get_default_title()
    if not default_title:
        return jsonify({'success': False, 'error': 'No default title set'}), 400

    with app_state_lock:
        category = current_twitch_category
    resolved = title_presets.resolve_title_text(default_title, category)
    if not resolved:
        return jsonify({'success': False, 'error': 'Resolved title is empty'}), 400

    success = update_stream_title(CLIENT_ID, OAUTH_TOKEN, resolved)
    if success:
        with app_state_lock:
            current_stream_title = resolved
            current_title_template = default_title
            active_title_mode = 'default'
        notify_title_updated(resolved, default_title)
        return jsonify({
            'success': True,
            'resolved_title': resolved,
            'title_template': default_title,
        })
    return jsonify({'success': False, 'error': 'Failed to update stream title'})


@app.route('/api/switch-default-category', methods=['POST'])
def api_switch_default_category():
    if not is_authenticated():
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    success = switch_to_default_category()
    if success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Failed to switch to default category'})


@app.route('/api/settings/detection', methods=['GET'])
def api_detection_settings_get():
    from catswitch.settings import get_detection_settings
    from catswitch.discord_detectable import consume_discord_disabled_notice

    payload = dict(get_detection_settings())
    notice = consume_discord_disabled_notice()
    if notice:
        payload['discord_disabled_notice'] = notice
    return jsonify(payload)


@app.route('/api/settings/detection', methods=['POST'])
def api_detection_settings_set():
    from catswitch.settings import save_detection_settings, get_detection_settings
    data = request.get_json(silent=True) or {}
    allowed_keys = {
        "default_category",
        "switch_delay_seconds",
        "auto_lock_category_on_manual_update",
        "auto_lock_title_on_manual_update",
        "use_discord_detectable",
    }
    updates = {key: data[key] for key in allowed_keys if key in data}
    if not updates:
        return jsonify({'success': False, 'error': 'No settings provided'}), 400

    if updates.get("use_discord_detectable") is True:
        from catswitch.discord_detectable import ensure_discord_detectable_ready
        ok, err = ensure_discord_detectable_ready()
        if not ok:
            return jsonify({
                'success': False,
                'error': err or 'Could not connect to Discord servers',
                'settings': get_detection_settings(),
            }), 503

    if not save_detection_settings(updates):
        return jsonify({'success': False, 'error': 'Failed to save settings'}), 500

    show_auto_exclusion_disabled_toast = False
    if "use_discord_detectable" in updates:
        from catswitch.excluded_apps import enable_auto_exclusion_setting_requires_list
        if updates.get("use_discord_detectable") is False:
            show_auto_exclusion_disabled_toast = True
        elif updates.get("use_discord_detectable") is True:
            enable_auto_exclusion_setting_requires_list()

    return jsonify({
        'success': True,
        'settings': get_detection_settings(),
        'show_auto_exclusion_disabled_toast': show_auto_exclusion_disabled_toast,
    })


@app.route('/api/settings/window', methods=['GET'])
def api_window_settings_get():
    from catswitch.settings import get_window_settings
    return jsonify(get_window_settings())


@app.route('/api/settings/window', methods=['POST'])
def api_window_settings_set():
    from catswitch.settings import save_window_settings, get_window_settings
    data = request.get_json(silent=True) or {}
    allowed_keys = {"minimize_to_tray", "autostart_with_windows"}
    updates = {key: data[key] for key in allowed_keys if key in data}
    if not updates:
        return jsonify({'success': False, 'error': 'No settings provided'}), 400
    if not save_window_settings(updates):
        return jsonify({'success': False, 'error': 'Failed to save settings'}), 500
    return jsonify({'success': True, 'settings': get_window_settings()})


@app.route('/api/settings/theme', methods=['GET'])
def api_theme_settings_get():
    from catswitch.settings import get_theme
    return jsonify({'theme': get_theme()})


@app.route('/api/settings/theme', methods=['POST'])
def api_theme_settings_set():
    from catswitch.settings import save_theme, get_theme, list_available_themes, normalize_theme_filename
    data = request.get_json(silent=True) or {}
    theme = normalize_theme_filename(data.get('theme') or '')
    if not theme:
        return jsonify({'success': False, 'error': 'No theme provided'}), 400

    allowed = {item['value'] for item in list_available_themes()}
    if theme not in allowed:
        return jsonify({'success': False, 'error': 'Theme not found'}), 400

    if not save_theme(theme):
        return jsonify({'success': False, 'error': 'Failed to save theme'}), 500
    return jsonify({'success': True, 'theme': get_theme()})


@app.route('/api/updates/status', methods=['GET'])
def api_updates_status():
    """Return cached update status plus last-checked timestamp (no network)."""
    from catswitch import updater
    from catswitch.version import APP_VERSION

    cached = updater.get_cached_check_result() or {}
    return jsonify({
        'success': True,
        'current': cached.get('current') or APP_VERSION,
        'latest': cached.get('latest'),
        'update_available': bool(cached.get('update_available')),
        'release_url': cached.get('release_url'),
        'download_url': cached.get('download_url'),
        'asset_name': cached.get('asset_name'),
        'notes': cached.get('notes'),
        'published_at': cached.get('published_at'),
        'checked_at': cached.get('checked_at'),
        'channel_configured': cached.get('channel_configured', updater.is_update_channel_configured()),
        'error': cached.get('error'),
        'last_checked': updater.get_updates_last_checked(),
        'should_check': updater.should_run_startup_check(),
    })


@app.route('/api/updates/check', methods=['POST'])
def api_updates_check():
    from catswitch import updater

    data = request.get_json(silent=True) or {}
    if 'force' in data:
        force = bool(data.get('force'))
    elif request.args.get('startup') == '1':
        force = updater.should_run_startup_check()
    else:
        force = True

    if not force:
        cached = updater.get_cached_check_result()
        if cached:
            return jsonify(cached)
        # No cache yet — fall through to a real check

    result = updater.check_for_updates(force=True)
    return jsonify(result)


@app.route('/api/updates/install', methods=['POST'])
def api_updates_install():
    """Download Setup, schedule temp helper install/launch, then exit this app."""
    from catswitch import updater

    result = updater.begin_install_update()
    if result.get('success'):
        threading.Timer(0.4, updater.request_app_exit_for_update).start()
        return jsonify(result)
    return jsonify(result), 400


@app.route('/api/themes/list', methods=['GET'])
def api_themes_list():
    from catswitch.settings import list_available_themes
    return jsonify({'themes': list_available_themes()})


@app.route('/api/themes/open-folder', methods=['GET'])
def api_themes_open_folder():
    from catswitch.paths import get_themes_dir
    try:
        folder = get_themes_dir()
        success, error = _open_in_os(folder)
        if success:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error opening themes folder: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/themes/css', methods=['GET'])
def api_themes_css():
    from catswitch.paths import get_themes_dir
    filename = request.args.get('file', '')
    if (
        not filename
        or '..' in filename
        or '/' in filename
        or '\\' in filename
        or not filename.lower().endswith('.css')
    ):
        return '', 400

    themes_dir = get_themes_dir()
    file_path = os.path.normpath(os.path.join(themes_dir, filename))
    if not _is_path_within(file_path, themes_dir) or not os.path.isfile(file_path):
        return '', 404

    return send_from_directory(themes_dir, filename, mimetype='text/css')


@app.route('/api/home-view', methods=['GET'])
def api_home_view_get():
    from catswitch.settings import load_home_compact_view, get_home_view_size
    compact = load_home_compact_view()
    width, height = get_home_view_size(compact)
    return jsonify({
        'compact': compact,
        'width': width,
        'height': height,
    })


@app.route('/api/home-view', methods=['POST'])
def api_home_view_set():
    from catswitch.settings import save_home_compact_view, get_home_view_size
    data = request.get_json(silent=True) or {}
    if 'compact' not in data:
        return jsonify({'success': False, 'error': 'No compact value provided'}), 400
    compact = bool(data.get('compact'))
    if not save_home_compact_view(compact):
        return jsonify({'success': False, 'error': 'Failed to save view preference'}), 500
    width, height = get_home_view_size(compact)
    return jsonify({'success': True, 'compact': compact, 'width': width, 'height': height})


@app.route('/api/title-presets/favorite', methods=['POST'])
def api_title_presets_favorite():
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'success': False, 'error': 'No title provided'}), 400
    success, error = title_presets.add_favorite(title)
    return jsonify({
        'success': success,
        'error': error,
        'favorite_titles': title_presets.get_favorite_titles(),
    })


@app.route('/api/title-presets/unfavorite', methods=['POST'])
def api_title_presets_unfavorite():
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'success': False, 'error': 'No title provided'}), 400
    success, error = title_presets.remove_favorite(title)
    return jsonify({
        'success': success,
        'error': error,
        'favorite_titles': title_presets.get_favorite_titles(),
    })


@app.route('/api/title-presets/apply', methods=['POST'])
def api_title_presets_apply():
    """Apply a preset as the live stream title (%cat resolved to current category)."""
    global current_stream_title
    if not is_authenticated():
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    data = request.get_json(silent=True) or {}
    preset_title = (data.get('title') or '').strip()
    if not preset_title:
        return jsonify({'success': False, 'error': 'No title provided'}), 400

    with app_state_lock:
        category = current_twitch_category
    resolved = title_presets.resolve_title_text(preset_title, category)
    if not resolved:
        return jsonify({'success': False, 'error': 'Resolved title is empty'}), 400

    from catswitch.detect_game import get_active_window_info
    _, active_path, _, active_window = get_active_window_info()
    assigned_template = _find_assigned_preset_template(category, active_path, active_window)
    default_title = title_presets.get_default_title()
    if assigned_template and preset_title == assigned_template:
        apply_mode = 'assigned'
    elif default_title and preset_title == default_title:
        apply_mode = 'default'
    else:
        apply_mode = 'manual'

    success = update_stream_title(CLIENT_ID, OAUTH_TOKEN, resolved)
    if success:
        global current_stream_title, current_title_template, active_title_mode
        with app_state_lock:
            current_stream_title = resolved
            current_title_template = preset_title
            active_title_mode = apply_mode
    return jsonify({
        'success': success,
        'resolved_title': resolved,
        'title_template': preset_title if success else None,
    })


@app.route('/api/title-presets/assign', methods=['POST'])
def api_title_presets_assign():
    """Assign games to a preset. Reports conflicts unless force is set."""
    data = request.get_json(silent=True) or {}
    preset_title = (data.get('title') or '').strip()
    games = data.get('games') or []
    force = bool(data.get('force'))

    if not preset_title or not games:
        return jsonify({'success': False, 'error': 'Title and games are required'}), 400

    if not force:
        conflicts = []
        for game in games:
            fp = _fingerprint_from_request_game(game)
            owner = title_presets.preset_for_fingerprint(fp)
            if owner and owner.casefold() != preset_title.casefold():
                conflicts.append({
                    'game': game,
                    'assigned_to': owner,
                })
        if conflicts:
            return jsonify({'success': False, 'conflicts': conflicts})

    for game in games:
        fp = _fingerprint_from_request_game(game)
        success, error = title_presets.assign_fingerprint(preset_title, fp)
        if not success:
            return jsonify({'success': False, 'error': error})
    return jsonify({'success': True})


@app.route('/api/title-presets/unassign', methods=['POST'])
def api_title_presets_unassign():
    data = request.get_json(silent=True) or {}
    game = data.get('game') or {}
    fp = _fingerprint_from_request_game(game)
    success, error = title_presets.unassign_fingerprint(fp)
    return jsonify({'success': success, 'error': error})


@app.route('/api/title-presets/for-game')
def api_title_presets_for_game():
    """Return the preset assigned to a specific game (if any)."""
    game = {
        'process_path': request.args.get('process_path', ''),
        'twitch_category': request.args.get('twitch_category', ''),
        'window_title': request.args.get('window_title', ''),
        'app_name': request.args.get('app_name', ''),
    }
    fp = _fingerprint_from_request_game(game)
    owner = title_presets.preset_for_fingerprint(fp)
    return jsonify({'title': owner})

@app.route('/api/always-on-top', methods=['POST'])
def api_always_on_top():
    """API endpoint to set always-on-top state."""
    data = request.json
    enabled = data.get('enabled', False)
    
    try:
        # Use ctypes to set window always on top
        import ctypes
        from ctypes import wintypes
        import win32gui
        import win32con
        
        # Try multiple methods to get the window handle
        user32 = ctypes.windll.user32
        
        # Method 1: Find by window title
        hwnd = win32gui.FindWindow(None, 'CatSwitch')
        logger.info(f"Found window handle by title: {hwnd}")
        
        # Method 2: Get foreground window as fallback
        if not hwnd or hwnd == 0:
            hwnd = user32.GetForegroundWindow()
            logger.info(f"Using foreground window handle: {hwnd}")
            
        if hwnd and hwnd != 0:
            # Method 1: Using win32gui
            try:
                if enabled:
                    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, 
                                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                else:
                    win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, 
                                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                logger.info(f"Successfully set always on top: {enabled} via win32gui")
                return jsonify({"success": True})
            except Exception as e:
                logger.error(f"Error setting always on top via win32gui: {e}")
            
            # Method 2: Using ctypes directly
            try:
                HWND_TOPMOST = -1
                HWND_NOTOPMOST = -2
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                
                flag = HWND_TOPMOST if enabled else HWND_NOTOPMOST
                result = user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                
                if result:
                    logger.info(f"Successfully set always on top: {enabled} via ctypes")
                    return jsonify({"success": True})
                else:
                    error = ctypes.WinError()
                    logger.error(f"SetWindowPos failed: {error}")
            except Exception as e:
                logger.error(f"Error in SetWindowPos: {e}")
        else:
            logger.warning(f"Could not get valid window handle, got: {hwnd}")
    except Exception as e:
        logger.error(f"Error setting always-on-top: {e}")
        import traceback
        traceback.print_exc()
    
    return jsonify({"success": False})

@app.route('/api/toggle-lock', methods=['POST'])
def api_toggle_lock():
    """API endpoint to toggle category lock."""
    global CATEGORY_LOCKED, manual_category, latest_detected_game, current_twitch_category, current_box_art_url
    
    try:
        data = request.json
        locked = data.get('locked')

        with app_state_lock:
            previous_lock_state = CATEGORY_LOCKED
            if locked is not None:
                CATEGORY_LOCKED = locked
            else:
                CATEGORY_LOCKED = not CATEGORY_LOCKED

            if CATEGORY_LOCKED:
                logger.info("Category lock ENABLED - Game detection is now paused")
            else:
                logger.info("Category lock DISABLED - Game detection is now active")

            apply_detected_on_unlock = (
                previous_lock_state
                and not CATEGORY_LOCKED
                and not manual_category
                and latest_detected_game
                and latest_detected_game != current_twitch_category
            )
            detected_to_apply = latest_detected_game if apply_detected_on_unlock else None

            if previous_lock_state and not CATEGORY_LOCKED and manual_category:
                logger.info(f"Unlocked - keeping manual category: {manual_category}")
            elif apply_detected_on_unlock:
                manual_category = None
                logger.info(f"Unlocked - applying detected game: {detected_to_apply}")

            if not previous_lock_state and CATEGORY_LOCKED:
                if current_twitch_category and not manual_category:
                    logger.info(f"Locked - setting manual category to current: {current_twitch_category}")
                    manual_category = current_twitch_category

            response_state = {
                "locked": CATEGORY_LOCKED,
                "current_category": current_twitch_category,
                "is_manual": manual_category is not None,
                "box_art_url": current_box_art_url,
            }

        if detected_to_apply:
            updated, _box_art = update_stream_category(
                CLIENT_ID, OAUTH_TOKEN, detected_to_apply
            )
            if updated:
                category_info = fetch_category_info(CLIENT_ID, OAUTH_TOKEN, detected_to_apply)
                with app_state_lock:
                    current_twitch_category = detected_to_apply
                    if category_info and 'box_art_url' in category_info:
                        current_box_art_url = process_box_art_url(
                            category_info.get('box_art_url'), detected_to_apply
                        )
                    response_state["current_category"] = current_twitch_category
                    response_state["box_art_url"] = current_box_art_url
                logger.info(f"Category successfully updated to: {detected_to_apply}")

        return jsonify({"success": True, **response_state})
    except Exception as e:
        logger.error(f"Error in toggle-lock: {e}")
        with app_state_lock:
            locked_state = CATEGORY_LOCKED
        return jsonify({
            "success": False,
            "error": str(e),
            "locked": locked_state
        })


@app.route('/api/toggle-title-lock', methods=['POST'])
def api_toggle_title_lock():
    """API endpoint to toggle stream title lock."""
    global TITLE_LOCKED

    try:
        data = request.json
        locked = data.get('locked')

        with app_state_lock:
            if locked is not None:
                TITLE_LOCKED = locked
            else:
                TITLE_LOCKED = not TITLE_LOCKED

            if TITLE_LOCKED:
                logger.info("Title lock ENABLED - Automatic title updates are now paused")
            else:
                logger.info("Title lock DISABLED - Automatic title updates are now active")

            title_locked_state = TITLE_LOCKED

        return jsonify({"success": True, "title_locked": title_locked_state})
    except Exception as e:
        logger.error(f"Error in toggle-title-lock: {e}")
        with app_state_lock:
            title_locked_state = TITLE_LOCKED
        return jsonify({
            "success": False,
            "error": str(e),
            "title_locked": title_locked_state
        })


@app.route('/api/game-detection')
def api_game_detection():
    """Server-sent events endpoint for game detection updates."""
    def generate():
        global latest_detected_game, manual_category, CATEGORY_LOCKED, TITLE_LOCKED, current_twitch_category, current_box_art_url
        
        last_game = None
        last_locked = None
        last_title_locked = None
        last_manual = None
        last_manual_category = None
        last_box_art = None
        last_update_time = 0
        
        with app_state_lock:
            initial_state = {
                'connected': True,
                'current_category': current_twitch_category,
                'game_name': current_twitch_category,
                'is_locked': CATEGORY_LOCKED,
                'title_locked': TITLE_LOCKED,
                'is_manual': manual_category is not None,
                'box_art_url': current_box_art_url,
                'timestamp': time.time()
            }
            last_game = current_twitch_category
            last_locked = CATEGORY_LOCKED
            last_title_locked = TITLE_LOCKED
            last_manual = manual_category is not None
            last_manual_category = manual_category
            last_box_art = current_box_art_url
            last_update_time = time.time()
        yield f"data: {json.dumps(initial_state)}\n\n"
        
        while True:
            current_time = time.time()

            with app_state_lock:
                effective_game = current_twitch_category
                is_locked = CATEGORY_LOCKED
                title_locked = TITLE_LOCKED
                is_manual = manual_category is not None
                manual_cat = manual_category
                latest_game = latest_detected_game
                box_art = current_box_art_url

            game_changed = effective_game != last_game
            lock_changed = is_locked != last_locked
            title_lock_changed = title_locked != last_title_locked
            manual_changed = (
                is_manual != last_manual or
                manual_cat != last_manual_category
            )
            box_art_changed = box_art != last_box_art
            keep_alive = (current_time - last_update_time) > 180

            should_send = (
                game_changed or
                lock_changed or
                title_lock_changed or
                manual_changed or
                box_art_changed or
                keep_alive
            )
            
            if should_send:
                data = json.dumps({
                    "game_name": effective_game,
                    "timestamp": current_time,
                    "is_update": game_changed,
                    "is_locked": is_locked,
                    "title_locked": title_locked,
                    "is_manual": is_manual,
                    "detected_game": latest_game,
                    "manual_category": manual_cat,
                    "current_category": effective_game,
                    "box_art_url": box_art
                })
                
                yield f"data: {data}\n\n"
                
                last_game = effective_game
                last_locked = is_locked
                last_title_locked = title_locked
                last_manual = is_manual
                last_manual_category = manual_cat
                last_box_art = box_art
                last_update_time = current_time
            
            time.sleep(1)
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/console/logs')
def api_console_logs():
    """Return captured console output lines."""
    from catswitch.console_log import get_logs_since, get_latest_id

    since_id = request.args.get('since', default=0, type=int)
    return jsonify({
        'success': True,
        'logs': get_logs_since(since_id),
        'latest_id': get_latest_id(),
    })


@app.route('/api/console/stream')
def api_console_stream():
    """Stream new console output lines via SSE."""
    from catswitch.console_log import get_logs_since

    since_id = request.args.get('since', default=0, type=int)

    def generate():
        last_id = since_id
        while True:
            entries = get_logs_since(last_id)
            for entry in entries:
                yield f"data: {json.dumps(entry)}\n\n"
                last_id = entry['id']
            time.sleep(0.25)

    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/search-categories', methods=['GET'])
def api_search_categories():
    """Search for Twitch categories/games."""
    query = request.args.get('query', '')
    
    if not query:
        return jsonify({"error": "No search query provided"}), 400
    
    try:
        # Use the original function to search for categories
        categories_raw = fetch_categories(CLIENT_ID, OAUTH_TOKEN, query)
        
        # Format the results to match the expected structure
        categories = []
        for category in categories_raw:
            categories.append({
                'id': category.get('id', ''),
                'name': category['name'],
                'box_art_url': process_box_art_url(
                    category.get('box_art_url', ''), category.get('name', '')
                )
            })
        
        return jsonify({"success": True, "categories": categories})
    except Exception as e:
        logger.error(f"Error searching categories: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/category-info')
def api_category_info():
    """API endpoint to get detailed info for a specific category."""
    category_name = request.args.get('name', '')
    
    if not category_name:
        return jsonify({"error": "Category name is required"}), 400
        
    try:
        # Get category info using the original function
        category_info = fetch_category_info(CLIENT_ID, OAUTH_TOKEN, category_name)
        
        if category_info:
            # Process box art URL
            box_art_url = process_box_art_url(
                category_info.get('box_art_url', ''), category_name
            )
            
            return jsonify({
                "id": category_info.get('id', ''),
                "name": category_name,
                "box_art_url": box_art_url
            })
        else:
            return jsonify({"error": "Category not found"}), 404
    except Exception as e:
        logger.error(f"Error getting category info: {str(e)}")
        return jsonify({"error": str(e)}), 500

def process_box_art_url(box_art_url, category=None):
    """Resolve box art for display via the category cache."""
    if isinstance(box_art_url, str) and box_art_url.startswith(('/api/cache/', '/static/')):
        return box_art_url
    if category:
        return category_cache.resolve_box_art(category, box_art_url)
    return category_cache.PLACEHOLDER

def update_ui_with_game(game_name, box_art_url, is_manual=False, process_name=None, is_existing_match=False, window_title=None):
    """Safely update the UI with game information"""
    try:
        windows = webview.windows
        if windows:
            w = windows[0]
            js_parts = [f"window.current_twitch_category = {json.dumps(game_name or '')};"]
            if process_name:
                logger.info(f"Setting process path in JS: {process_name}")
                js_parts.append(f"window.current_process_path = {json.dumps(process_name)};")
            if window_title:
                logger.info(f"Setting window title in JS: {window_title}")
                js_parts.append(f"window.current_window_title = {json.dumps(window_title)};")
            js_parts.append(
                "gameDetected("
                f"{json.dumps(game_name or '')}, {json.dumps(box_art_url or '')}, "
                f"{json.dumps(is_manual)}, {json.dumps(is_existing_match)}"
                ");"
            )
            js_code = "".join(js_parts)
            logger.info(f"Updating UI with JS: {js_code}")
            w.evaluate_js(js_code)
            return True
        else:
            logger.info("No window found to update UI")
            return False
    except Exception as e:
        logger.error(f"Error updating UI: {e}")
        return False

def notify_title_updated(resolved, template=None):
    """Push the resolved display title and raw template to the UI."""
    try:
        windows = webview.windows
        if windows:
            payload = {
                "resolved_title": resolved or "",
                "title_template": template if template is not None else (current_title_template or resolved or ""),
            }
            windows[0].evaluate_js(f"streamTitleUpdated({json.dumps(payload)})")
    except Exception as e:
        logger.error(f"Error pushing stream title to UI: {e}")


def _find_assigned_preset_template(category, process_path=None, window_title=None) -> Optional[str]:
    """Return the preset title template assigned to the active game, if any."""
    if process_path:
        entry = find_matching_detected_app_by_window_title(
            os.path.basename(process_path), process_path, window_title or ''
        )
        if entry:
            return title_presets.find_preset_for_entry(entry)

    if category:
        return title_presets.find_preset_for_category(category)
    return None


def _infer_title_template(
    resolved_title: str,
    category: str,
    process_path=None,
    window_title=None,
) -> str:
    """Best-effort recovery of the raw title template from a resolved Twitch title."""
    if not resolved_title:
        return ''
    assigned = _find_assigned_preset_template(category, process_path, window_title)
    if assigned and title_presets.resolve_title_text(assigned, category) == resolved_title:
        return assigned
    default = title_presets.get_default_title()
    if default and title_presets.resolve_title_text(default, category) == resolved_title:
        return default
    if active_title_mode == 'assigned' and assigned:
        return assigned
    if active_title_mode == 'default' and default:
        return default
    return resolved_title


def _apply_stream_title_if_changed(template: str, mode: str) -> bool:
    """Update Twitch and local state when the resolved title differs."""
    global current_stream_title, current_title_template, active_title_mode
    with app_state_lock:
        category = current_twitch_category
        existing_title = current_stream_title
    resolved = title_presets.resolve_title_text(template, category)
    if not resolved or resolved == existing_title:
        return False
    if update_stream_title(CLIENT_ID, OAUTH_TOKEN, resolved):
        with app_state_lock:
            current_stream_title = resolved
            current_title_template = template
            active_title_mode = mode
        notify_title_updated(resolved, template)
        return True
    return False


def _apply_title_preset_now(category, process_path=None, window_title=None):
    """Apply an assigned preset, or fall back to the default title when appropriate."""
    global active_title_mode
    try:
        if is_title_locked():
            logger.warning("Title locked - skipping auto title update")
            return

        assigned_template = _find_assigned_preset_template(category, process_path, window_title)
        if assigned_template:
            resolved = title_presets.resolve_title_text(assigned_template, category)
            if _apply_stream_title_if_changed(assigned_template, 'assigned'):
                logger.info(f"Auto-applying assigned title preset: {resolved}")
            return

        with app_state_lock:
            mode = active_title_mode
        if mode == 'manual':
            return

        default_title = title_presets.get_default_title()
        if not default_title:
            return

        resolved = title_presets.resolve_title_text(default_title, category)
        if _apply_stream_title_if_changed(default_title, 'default'):
            logger.info(f"Auto-applying default title preset: {resolved}")
    except Exception as e:
        logger.error(f"Error auto-applying title preset: {e}")


def apply_default_title_on_shutdown(timeout_sec: float = 1.5):
    """Restore the default stream title when the app closes.

    Runs the Twitch call on a short-lived thread so WM_CLOSE / installer
    shutdown never hangs the process waiting on the network.
    """
    if not is_authenticated():
        return
    default_title = title_presets.get_default_title()
    if not default_title:
        return
    with app_state_lock:
        category = current_twitch_category
        current_title = current_stream_title
    resolved = title_presets.resolve_title_text(default_title, category)
    if not resolved or resolved == current_title:
        return
    logger.info(f"Applying default stream title on shutdown: {resolved}")

    def _apply():
        try:
            update_stream_title(CLIENT_ID, OAUTH_TOKEN, resolved)
        except Exception as exc:
            logger.error("Shutdown title restore failed: %s", exc)

    worker = threading.Thread(
        target=_apply, name="CatSwitchShutdownTitle", daemon=True
    )
    worker.start()
    worker.join(timeout=max(0.0, timeout_sec))
    if worker.is_alive():
        logger.warning(
            "Shutdown title restore still running after %.1fs — continuing exit",
            timeout_sec,
        )


def maybe_apply_title_preset(category, process_path=None, window_title=None):
    """Apply the assigned title preset for a category change, off the caller's thread."""
    threading.Thread(
        target=_apply_title_preset_now,
        args=(category, process_path, window_title),
        daemon=True,
    ).start()


DEFAULT_STREAM_CATEGORY = "Just Chatting"  # fallback only; prefer get_default_category()


def get_configured_default_category() -> str:
    from catswitch.settings import get_default_category
    return get_default_category() or DEFAULT_STREAM_CATEGORY


def is_currently_active_detected_game(process_path: str, twitch_category: str) -> bool:
    """Return True when the excluded app matches the active foreground game and stream category."""
    from catswitch.detect_game import get_active_window_info

    _, active_path, _, _ = get_active_window_info()
    if not active_path or not process_path:
        return False

    if not saved_app_path_matches(active_path, {"process_path": process_path}):
        return False

    with app_state_lock:
        active_category = current_twitch_category

    if not active_category or not twitch_category:
        return False

    return active_category.lower() == twitch_category.lower()


def should_switch_to_default_after_exclude(process_path: str, twitch_category: str) -> bool:
    """Return True when excluding should revert the live stream category."""
    if is_currently_active_detected_game(process_path, twitch_category):
        return True

    with app_state_lock:
        active_category = current_twitch_category

    return bool(
        active_category
        and twitch_category
        and active_category.lower() == twitch_category.lower()
    )


def switch_to_default_category() -> bool:
    """Switch the live stream category to the configured default without locking."""
    global manual_category, latest_detected_game, current_twitch_category, current_box_art_url

    from catswitch.detect_game import clear_active_game_tracking

    if not OAUTH_TOKEN or not CLIENT_ID:
        return False

    default_category = get_configured_default_category()

    try:
        category_info = fetch_category_info(CLIENT_ID, OAUTH_TOKEN, default_category)
        full_category_name = (
            category_info.get("name", default_category)
            if category_info else default_category
        )

        updated, box_art_url = update_stream_category(
            CLIENT_ID, OAUTH_TOKEN, default_category
        )
        if not updated:
            return False

        processed_url = process_box_art_url(box_art_url, full_category_name)
        with app_state_lock:
            current_twitch_category = full_category_name
            current_box_art_url = processed_url
            manual_category = None
            latest_detected_game = full_category_name

        clear_active_game_tracking()
        update_ui_with_game(full_category_name, processed_url, False)
        logger.info("Switched to default category after excluding active game")
        return True
    except Exception as e:
        logger.error(f"Error switching to default category: {e}")
        return False

def initialize_app(client_id, oauth_token=None):
    """Initialize the Flask app with Twitch credentials."""
    global CLIENT_ID, OAUTH_TOKEN, user_info, current_twitch_category, current_box_art_url, OAUTH_TOKEN_VALID

    CLIENT_ID = client_id or TWITCH_CLIENT_ID
    OAUTH_TOKEN = oauth_token
    category_cache.configure_twitch(CLIENT_ID, oauth_token)

    get_excluded_apps_dir()

    from catswitch.detected_apps import ensure_detected_local_file
    from catswitch.excluded_apps import ensure_excluded_local_file, ensure_excluded_common_file
    ensure_excluded_local_file()
    ensure_excluded_common_file()
    ensure_detected_local_file()

    try:
        from catswitch.settings import discover_excluded_app_lists, discover_detected_app_lists
        discover_excluded_app_lists()
        discover_detected_app_lists()
    except Exception as e:
        logger.warning(f"Failed to sync app list folders: {e}")

    try:
        from catswitch.discord_detectable import initialize_discord_detectable_cache
        initialize_discord_detectable_cache()
    except Exception as e:
        logger.warning(f"Failed to initialize Discord detectable cache: {e}")

    try:
        from catswitch.excluded_apps import repair_auto_exclusion_state_if_invalid
        repair_auto_exclusion_state_if_invalid()
    except Exception as e:
        logger.warning(f"Failed to repair auto-exclusion settings: {e}")

    success, error = reload_excluded_apps()
    if success:
        logger.info("Excluded apps loaded successfully at startup")
    else:
        logger.warning(f"Failed to load excluded apps at startup: {error}")

    success, error = load_detected_apps()
    if success:
        logger.info("Detected apps loaded successfully at startup")
    else:
        logger.warning(f"Failed to load detected apps at startup: {error}")

    if not oauth_token:
        OAUTH_TOKEN_VALID = False
        logger.info("Starting without an authenticated Twitch session")
        return app

    try:
        refresh_session_state_from_stream()
        if OAUTH_TOKEN_VALID:
            if user_info:
                logger.info(f"Initialized with user: {user_info.get('display_name')}")
            else:
                logger.info("Initialized with saved session (profile pending)")
            logger.info(f"Current Twitch category: {current_twitch_category}")
            create_game_detection_thread()
        else:
            logger.info("Saved token is invalid — welcome screen will be shown")
    except Exception as e:
        # Do not clear a saved session on unexpected errors during refresh.
        logger.error(f"Error getting user info: {e}")
        if OAUTH_TOKEN and not user_info:
            user_info = get_saved_account_profile()
        if OAUTH_TOKEN:
            OAUTH_TOKEN_VALID = True
            create_game_detection_thread()

    initial_category = current_twitch_category if user_info else None
    if initial_category:
        def initialize_js_variables():
            def set_current_category():
                try:
                    if webview.windows:
                        webview.windows[0].evaluate_js(
                            f"window.current_twitch_category = {json.dumps(initial_category or '')};"
                        )
                        logger.info(f"Set initial window.current_twitch_category to: {initial_category}")
                except Exception as e:
                    logger.error(f"Error setting initial category: {e}")

            threading.Timer(1.0, set_current_category).start()

        try:
            initialize_js_variables()
        except Exception as e:
            logger.error(f"Error initializing JS variables: {e}")

    return app

def run_app(client_id, oauth_token, debug=False, port=51111):
    """Run the Flask app."""
    app = initialize_app(client_id, oauth_token)
    app.run(debug=debug, port=port)

def find_best_match(search_term, category_list):
    """Find the best matching category using string similarity with additional metrics.
    
    Args:
        search_term (str): The user's search term
        category_list (list): List of category names to match against
        
    Returns:
        tuple: (best_match, similarity_score)
    """
    if not search_term or not category_list:
        return None, 0.0
        
    # First pass: calculate base similarity for all categories
    candidates = []
    search_term = search_term.lower()
    
    for category in category_list:
        try:
            # Calculate similarity based on string matching
            base_similarity = SequenceMatcher(None, search_term, category.lower()).ratio()
            
            # Debug
            logger.info(f"Comparing '{search_term}' with '{category}': similarity={base_similarity}")
            
            # Add to candidates if similarity is reasonable
            if base_similarity >= 0.25:  # Low threshold for initial filtering
                candidates.append({
                    'name': category,
                    'base_similarity': base_similarity,
                    'adjusted_similarity': base_similarity  # Will be adjusted below
                })
        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            continue
    
    # If no candidates, return None
    if not candidates:
        return None, 0.0
    
    # If only one candidate, return it
    if len(candidates) == 1:
        return candidates[0]['name'], candidates[0]['base_similarity']
    
    # Sort by base similarity and keep only the top 5 matches for second pass
    candidates.sort(key=lambda x: x['base_similarity'], reverse=True)
    candidates = candidates[:5]  # Limit to top 5 matches
    
    # Check for exact match or near exact match (>0.9) - if found, return immediately
    exact_matches = [c for c in candidates if c['base_similarity'] > 0.9]
    if exact_matches:
        best_match = exact_matches[0]
        logger.info(f"Found high-confidence match: {best_match['name']} with similarity {best_match['base_similarity']}")
        return best_match['name'], best_match['base_similarity']
        
    # Second pass: adjust similarity scores based on box art
    # Only do this for high similarity candidates
    high_similarity_candidates = [c for c in candidates if c['base_similarity'] >= 0.5]
    
    if high_similarity_candidates:
        logger.info("Multiple good matches, checking box art")
        
        # Use a set to track which categories we've already adjusted to prevent duplicates
        processed_categories = set()
        
        for candidate in high_similarity_candidates:
            category_name = candidate['name']
            
            # Skip if we've already processed this category name
            if category_name in processed_categories:
                continue
                
            processed_categories.add(category_name)
            
            # Get detailed info about this category
            category_info = fetch_category_info(CLIENT_ID, OAUTH_TOKEN, category_name)
            
            if category_info:
                has_box_art = 'box_art_url' in category_info and category_info['box_art_url']
                adjustment = 0.0
                
                if not has_box_art:
                    logger.info(f"No box art for {category_name}, reducing score")
                    adjustment -= 0.2
                
                candidate['adjusted_similarity'] = max(0.0, min(1.0, candidate['base_similarity'] + adjustment))
                logger.info(f"Adjusted similarity for {category_name}: {candidate['adjusted_similarity']} (base: {candidate['base_similarity']}, adj: {adjustment})")
    
    # Sort by adjusted similarity
    candidates.sort(key=lambda x: x['adjusted_similarity'], reverse=True)
    best_candidate = candidates[0]
    
    logger.info(f"Best match after adjustments: {best_candidate['name']} with similarity {best_candidate['adjusted_similarity']}")
    return best_candidate['name'], best_candidate['adjusted_similarity']

def search_categories(query, client_id, oauth_token):
    """Search for Twitch categories matching the query."""
    try:
        from catswitch.update_twitch import search_twitch_categories
        categories = search_twitch_categories(client_id, oauth_token, query)
        
        # Extract just the category names from the response
        if categories and isinstance(categories, list):
            return [category.get('name', '') for category in categories if 'name' in category]
        return []
    except Exception as e:
        logger.error(f"Error searching categories: {e}")
        return []

# Excluded Apps API Routes
@app.route('/api/excluded-apps/list', methods=['GET'])
def api_excluded_apps_list():
    """API endpoint to get the list of excluded apps lists."""
    try:
        lists = get_excluded_app_files()
        return jsonify(lists)
    except Exception as e:
        logger.error(f"Error getting excluded apps list: {e}")
        return jsonify([])

@app.route('/api/excluded-apps/create', methods=['POST'])
def api_excluded_apps_create():
    """API endpoint to create a new excluded apps list."""
    try:
        data = request.json
        name = data.get('name', '').strip()

        if not name:
            return jsonify({'success': False, 'error': 'Name is required'})

        success, path, error = create_new_file(name)

        if success:
            return jsonify({'success': True, 'name': name, 'path': path})
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error creating excluded apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excluded-apps/add-local', methods=['POST'])
def add_local_list():
    """Add a local excluded apps list"""
    try:
        data = request.json
        name = data.get('name', '')
        path = data.get('path', '')
        
        if not name or not path:
            return jsonify({
                'success': False,
                'error': 'Missing required parameters: name and path'
            })
        
        # Make sure name ends with .txt
        if not name.lower().endswith('.txt'):
            name = name + '.txt'
            
        # Check if the file exists
        if not os.path.exists(path):
            return jsonify({
                'success': False,
                'error': f'File does not exist: {path}'
            })
            
        # Get the excluded apps directory
        excluded_apps_dir = get_excluded_apps_dir()
        
        # Get the destination path
        dest_path = os.path.join(excluded_apps_dir, name)
        
        # Copy the file to the excluded apps directory
        try:
            shutil.copy2(path, dest_path)
            logger.info(f"Copied file from {path} to {dest_path}")
        except Exception as e:
            logger.error(f"Error copying file: {e}")
            return jsonify({
                'success': False,
                'error': f'Error copying file: {str(e)}'
            })
            
        # Add the file to the settings
        add_excluded_app_file(name, dest_path)
        
        # Reload the excluded apps
        reload_excluded_apps()
        
        return jsonify({
            'success': True,
            'name': name
        })
    except Exception as e:
        logger.error(f"Error adding local list: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/excluded-apps/download', methods=['POST'])
def api_excluded_apps_download():
    """API endpoint to download an excluded apps list from a URL."""
    try:
        data = request.json
        url = data.get('url', '')
        name = data.get('name', None)
        
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'})
            
        success, path, error = download_from_url(url, name)
        
        if success:
            return jsonify({'success': True, 'path': path})
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error downloading excluded apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excluded-apps/add-url', methods=['POST'])
def api_excluded_apps_add_url():
    """API endpoint to add an excluded apps list from a URL (live loading)."""
    try:
        data = request.json
        url = data.get('url', '')
        name = data.get('name', None)

        if not url:
            return jsonify({'success': False, 'error': 'URL is required'})

        # Test the URL first to validate it's a proper text file
        success, content, error = load_from_url_live(url)
        if not success:
            return jsonify({'success': False, 'error': f'Invalid URL: {error}'})

        name = resolve_url_list_name(content, url, name)

        # Only add to settings if validation passed
        add_excluded_app_file(name, "", "url", url)

        # Reload the excluded apps to load from URL
        reload_excluded_apps()

        return jsonify({'success': True, 'name': name})
    except Exception as e:
        logger.error(f"Error adding URL excluded apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excluded-apps/get-content', methods=['GET'])
def api_excluded_apps_get_content():
    """API endpoint to get the content of a local excluded apps list."""
    try:
        path = request.args.get('path', '')
        
        if not path:
            return jsonify({'success': False, 'error': 'Path is required'})
        
        list_info = find_local_excluded_list(path)
        if not list_info:
            return jsonify({'success': False, 'error': 'List not found or not a local file'})
        
        file_path = list_info.get('path') or path
        success, content, error = read_file_content(file_path)
        if not success:
            return jsonify({'success': False, 'error': error})
        
        return jsonify({'success': True, 'content': content})
    except Exception as e:
        logger.error(f"Error getting excluded apps list content: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excluded-apps/save-content', methods=['POST'])
def api_excluded_apps_save_content():
    """API endpoint to save content to a local excluded apps list."""
    try:
        data = request.json
        path = data.get('path', '')
        content = data.get('content', '')
        
        if not path:
            return jsonify({'success': False, 'error': 'Path is required'})
        
        list_info = find_local_excluded_list(path)
        if not list_info:
            return jsonify({'success': False, 'error': 'List not found or not a local file'})
        
        file_path = list_info.get('path') or path

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            reload_ok, reload_error = reload_excluded_apps()
            if not reload_ok:
                logger.error(
                    "Excluded list saved to %s but reload failed: %s",
                    file_path,
                    reload_error,
                )
                return jsonify({
                    'success': False,
                    'error': reload_error or 'Saved to disk but failed to reload excluded apps',
                })

            logger.info("Saved and reloaded excluded list: %s", file_path)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': f'Failed to write file: {str(e)}'})
    except Exception as e:
        logger.error(f"Error saving excluded apps list content: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excluded-apps/update', methods=['POST'])
def api_excluded_apps_update():
    """API endpoint to update an excluded apps list from its source URL."""
    try:
        data = request.get_json(silent=True) or {}
        path = data.get('path', '')
        
        if not path:
            return jsonify({'success': False, 'error': 'Path is required'})
            
        success, error = update_from_url(path)
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error updating excluded apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excluded-apps/remove', methods=['POST'])
def api_excluded_apps_remove():
    """API endpoint to remove an excluded apps list."""
    try:
        data = request.get_json(silent=True) or {}
        path = data.get('path', '')
        delete_file_param = bool(data.get('delete', False))
        
        if not path:
            return jsonify({'success': False, 'error': 'Path is required'})

        success, error = delete_file(path, delete_file_param)
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error removing excluded apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excluded-apps/content', methods=['GET'])
def api_excluded_apps_content():
    """API endpoint to get the content of an excluded apps list."""
    try:
        path = request.args.get('path', '')
        
        if not path:
            return jsonify({'success': False, 'error': 'Path is required'})
            
        success, content, error = read_file_content(path)
        
        if success:
            return jsonify({'success': True, 'content': content})
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error reading excluded apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

def _is_path_within(path, directory):
    try:
        abs_path = os.path.realpath(path)
        abs_dir = os.path.realpath(directory)
        return os.path.commonpath([abs_path.casefold(), abs_dir.casefold()]) == abs_dir.casefold()
    except (ValueError, OSError):
        return False

def _open_in_os(path):
    import subprocess
    import sys

    abs_path = os.path.normpath(os.path.abspath(path))
    if not os.path.exists(abs_path):
        return False, f'Path not found: {abs_path}'

    try:
        if sys.platform == 'win32':
            os.startfile(abs_path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', abs_path])
        else:
            subprocess.Popen(['xdg-open', abs_path])
        return True, None
    except Exception as e:
        return False, str(e)

@app.route('/api/excluded-apps/open-file', methods=['GET'])
def api_excluded_apps_open_file():
    """Open a local excluded-apps list file in the default application."""
    try:
        path = request.args.get('path', '')
        if not path:
            return jsonify({'success': False, 'error': 'Path is required'})

        abs_path = os.path.normpath(os.path.abspath(path))
        if not _is_path_within(abs_path, get_excluded_apps_dir()):
            return jsonify({'success': False, 'error': 'Invalid file path'})

        success, error = _open_in_os(abs_path)
        if success:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error opening excluded apps file: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excluded-apps/open-folder', methods=['POST'])
def api_excluded_apps_open_folder():
    """Open the excluded apps lists folder in the file manager."""
    try:
        folder = get_excluded_apps_dir()
        success, error = _open_in_os(folder)
        if success:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error opening excluded apps folder: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excluded-apps/set-enabled', methods=['POST'])
def api_excluded_apps_set_enabled():
    """API endpoint to enable or disable an excluded apps list."""
    try:
        data = request.get_json() or {}
        path = data.get('path', '')
        url = data.get('url', '')
        enabled = data.get('enabled', True)

        if not path and not url:
            return jsonify({'success': False, 'error': 'Path or URL is required'})

        from catswitch.excluded_apps import matches_auto_excluded_list, reload_excluded_apps

        if not set_excluded_app_list_enabled(path, enabled, url or None):
            return jsonify({'success': False, 'error': 'List not found'})

        if matches_auto_excluded_list(path, url):
            reload_excluded_apps()

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error setting excluded apps list enabled state: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/excluded-apps/reload', methods=['GET'])
def api_excluded_apps_reload():
    """API endpoint to reload all excluded apps lists into memory."""
    try:
        from catswitch.settings import discover_excluded_app_lists
        discover_excluded_app_lists()
        success, error = reload_excluded_apps()
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error reloading excluded apps: {e}")
        return jsonify({'success': False, 'error': str(e)})

# Apps API Endpoints

@app.route('/api/apps/list', methods=['GET'])
def api_apps_list():
    """API endpoint to get the list of app lists."""
    try:
        lists = get_detected_app_files()
        return jsonify(lists)
    except Exception as e:
        logger.error(f"Error getting apps list: {e}")
        return jsonify([])

@app.route('/api/apps/open-file', methods=['GET'])
def api_apps_open_file():
    """Open a local apps list file in the default application."""
    try:
        from catswitch.detected_apps import get_detected_apps_dir

        path = request.args.get('path', '')
        if not path:
            return jsonify({'success': False, 'error': 'Path is required'})

        abs_path = os.path.normpath(os.path.abspath(path))
        if not _is_path_within(abs_path, get_detected_apps_dir()):
            return jsonify({'success': False, 'error': 'Invalid file path'})

        success, error = _open_in_os(abs_path)
        if success:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error opening apps list file: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/apps/open-folder', methods=['POST'])
def api_apps_open_folder():
    """Open the apps lists folder in the file manager."""
    try:
        from catswitch.detected_apps import get_detected_apps_dir

        folder = get_detected_apps_dir()
        success, error = _open_in_os(folder)
        if success:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error opening apps folder: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/apps/reload', methods=['GET'])
def api_apps_reload():
    """API endpoint to reload all app lists into memory."""
    try:
        from catswitch.settings import discover_detected_app_lists
        discover_detected_app_lists()
        # Reload detected apps
        success, error = load_detected_apps()
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error reloading apps: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/apps/set-enabled', methods=['POST'])
def api_apps_set_enabled():
    """API endpoint to enable or disable a detected games list."""
    try:
        data = request.get_json() or {}
        path = data.get('path', '')
        url = data.get('url', '')
        enabled = data.get('enabled', True)

        if not path and not url:
            return jsonify({'success': False, 'error': 'Path or URL is required'})

        if not set_detected_app_list_enabled(path, enabled, url or None):
            return jsonify({'success': False, 'error': 'List not found'})

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error setting apps list enabled state: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/apps/reorder', methods=['POST'])
def api_apps_reorder():
    """API endpoint to change detected games list priority order."""
    try:
        data = request.get_json() or {}
        path = data.get('path', '')
        direction = data.get('direction', '')

        if not path:
            return jsonify({'success': False, 'error': 'Path is required'})

        from catswitch.settings import reorder_detected_app_file
        success = reorder_detected_app_file(path, direction)
        if not success:
            return jsonify({'success': False, 'error': 'Failed to reorder list'})

        load_success, error = load_detected_apps()
        if not load_success:
            return jsonify({'success': False, 'error': error or 'Failed to reload detected apps'})

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error reordering apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/apps/remove', methods=['POST'])
def api_apps_remove():
    """API endpoint to remove an app list."""
    try:
        data = request.get_json(silent=True) or {}
        path = data.get('path', '')
        
        if not path:
            return jsonify({'success': False, 'error': 'Path is required'})

        from catswitch.settings import (
            remove_detected_app_file,
            _resolve_config_path,
            _paths_refer_to_same_file,
            get_detected_app_files,
        )

        resolved_path = _resolve_config_path(path)
        list_info = next(
            (
                lst for lst in get_detected_app_files()
                if _paths_refer_to_same_file(lst.get("path", ""), path)
            ),
            None,
        )

        success = remove_detected_app_file(path)
        
        if not success:
            return jsonify({'success': False, 'error': 'Failed to remove list from settings'})

        should_delete_file = (
            list_info is None
            or list_info.get("source", "local") != "url"
        )
        if should_delete_file and resolved_path and os.path.exists(resolved_path):
            try:
                os.remove(resolved_path)
                logger.info(f"Deleted file: {resolved_path}")
            except Exception as e:
                logger.warning(f"Could not delete file {resolved_path}: {e}")

        load_success, load_error = load_detected_apps()
        if not load_success:
            logger.warning(f"Removed list but failed to reload detected apps: {load_error}")
        
        logger.info(f"Successfully removed app list: {path}")
        return jsonify({'success': True, 'message': 'App list removed successfully'})
        
    except Exception as e:
        logger.error(f"Error removing app list: {e}")
        return jsonify({'success': False, 'error': str(e)})

# Detected Apps API Endpoints

@app.route('/api/processes/foreground-apps', methods=['GET'])
def api_foreground_app_processes():
    """Return visible foreground app processes for the add/edit game dialog."""
    try:
        from catswitch.detect_game import list_foreground_app_processes
        processes = list_foreground_app_processes()
        return jsonify({'success': True, 'processes': processes})
    except Exception as e:
        logger.error(f"Error listing foreground app processes: {e}")
        return jsonify({'success': False, 'error': str(e), 'processes': []})


@app.route('/api/detected-apps/list', methods=['GET'])
def api_detected_apps_list():
    """API endpoint to get detected apps from the in-memory cache."""
    try:
        return jsonify({'success': True, 'apps': get_all_detected_apps()})
    except Exception as e:
        logger.error(f"Error getting detected apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/detected-apps/save', methods=['POST'])
def api_detected_apps_save():
    """API endpoint to save a detected app."""
    try:
        data = request.json
        process_path = data.get('process_path', '')
        app_name = data.get('app_name', '')
        twitch_category = data.get('twitch_category', '')
        window_title = data.get('window_title', '')
        
        if not process_path or not twitch_category:
            return jsonify({'success': False, 'error': 'Process path and Twitch category are required'})

        from catswitch.detected_apps import is_detected_local_save_enabled
        if not is_detected_local_save_enabled():
            return jsonify({'success': True, 'skipped': True})
        
        success, error = save_detected_app(process_path, app_name, twitch_category, window_title)
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error saving detected app: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/detected-apps/get', methods=['GET'])
def api_detected_apps_get():
    """API endpoint to get a single detected app by process path and window title."""
    try:
        process_path = request.args.get('process_path', '')
        window_title = request.args.get('window_title', '')
        
        if not process_path:
            return jsonify({'success': False, 'error': 'Process path is required'})
        
        # Create the composite cache key
        cache_key = f"{process_path.lower()}|{window_title}"
        
        logger.info(f"Looking for app with cache_key: '{cache_key}'")
        logger.info(f"Available cache keys: {list(loaded_detected_apps.keys())}")
        
        # Get the app from the cache using the composite key
        app = loaded_detected_apps.get(cache_key)
        if app:
            category_cache.prefetch_categories_for_apps([app])
            category_cache.enrich_app_dict(app, fetch_if_missing=False)
            logger.info(f"Found app: {app}")
            return jsonify({'success': True, 'app': app})
        else:
            logger.warning(f"App not found with cache_key: '{cache_key}'")
            return jsonify({'success': False, 'error': 'App not found'})
    except Exception as e:
        logger.error(f"Error getting detected app: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/detected-apps/remove', methods=['POST'])
def api_detected_apps_remove():
    """API endpoint to remove a detected app from a specific list."""
    try:
        data = request.json
        process_path = data.get('process_path', '')
        app_name = data.get('app_name', '')
        twitch_category = data.get('twitch_category', '')
        window_title = data.get('window_title', '')
        list_name = data.get('list_name', '')
        
        if not process_path:
            return jsonify({'success': False, 'error': 'Process path is required'})
        
        if not list_name:
            return jsonify({'success': False, 'error': 'List name is required'})
        
        # Find the list file path from the list name
        lists = get_detected_app_files()
        target_list_path = None
        
        for list_info in lists:
            if list_info.get('name') == list_name:
                target_list_path = list_info.get('path')
                break
        
        if not target_list_path:
            return jsonify({'success': False, 'error': f'List "{list_name}" not found'})
        
        # Remove from the specific list file using ALL identifying fields
        from catswitch.detected_apps import remove_detected_app_from_file
        success, error = remove_detected_app_from_file(process_path, target_list_path, app_name, twitch_category, window_title)
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error removing detected app: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/detected-apps/move-list', methods=['POST'])
def api_detected_apps_move_list():
    """API endpoint to move a detected app from one list file to another."""
    try:
        data = request.json or {}
        process_path = data.get('process_path', '')
        app_name = data.get('app_name', '')
        twitch_category = data.get('twitch_category', '')
        window_title = data.get('window_title', '')
        source_file_path = data.get('source_file_path', '')
        target_file_path = data.get('target_file_path', '')

        if not process_path or not twitch_category:
            return jsonify({'success': False, 'error': 'Process path and Twitch category are required'})
        if not source_file_path or not target_file_path:
            return jsonify({'success': False, 'error': 'Source and target list paths are required'})

        success, error = move_detected_app_between_lists(
            process_path,
            app_name,
            twitch_category,
            window_title,
            source_file_path,
            target_file_path,
        )
        if success:
            target_info = get_detected_list_info_by_path(target_file_path)
            return jsonify({
                'success': True,
                'file_path': target_info.get('path', target_file_path) if target_info else target_file_path,
                'list_name': target_info.get('name', 'Unknown List') if target_info else 'Unknown List',
            })
        return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error moving detected app between lists: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/detected-apps/add-to-excluded', methods=['POST'])
def api_detected_apps_add_to_excluded():
    """API endpoint to add a detected app to excluded apps."""
    try:
        data = request.json
        process_path = data.get('process_path', '')
        app_name = data.get('app_name', '')
        twitch_category = data.get('twitch_category', '')
        window_title = data.get('window_title', '')
        list_name = data.get('list_name', '')
        file_path = data.get('file_path', '')
        
        if not process_path:
            return jsonify({'success': False, 'error': 'Process path is required'})
        
        success, error = add_to_excluded_apps(process_path, app_name, twitch_category, window_title)
        if success:
            removed_from_detected, remove_error = remove_matching_detected_app_for_exclude(
                process_path,
                app_name,
                twitch_category,
                window_title,
                list_name=list_name,
                file_path=file_path,
            )
            if not removed_from_detected and remove_error:
                logger.warning(f"Excluded app but failed to remove from detected list: {remove_error}")

            if should_switch_to_default_after_exclude(process_path, twitch_category):
                threading.Thread(
                    target=switch_to_default_category,
                    daemon=True,
                ).start()

            return jsonify({
                'success': True,
                'removed_from_detected': removed_from_detected,
            })
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error adding detected app to excluded apps: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/detected-apps/reload', methods=['POST'])
def api_detected_apps_reload():
    """API endpoint to reload detected apps from files."""
    try:
        success, error = load_detected_apps()
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': error})
    except Exception as e:
        logger.error(f"Error reloading detected apps: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/detected-apps/add-manual', methods=['POST'])
def api_detected_apps_add_manual():
    """API endpoint to add a detected app manually."""
    try:
        data = request.get_json()
        title = data.get('title', '').strip()
        category = data.get('category', '').strip()
        location = data.get('location', '').strip()
        window_title = data.get('window_title', '').strip()
        file_path = data.get('file_path', '').strip()
        
        if not category or not location:
            return jsonify({'status': 'error', 'error': 'Category and location are required'})
        
        # Warm category box art cache for the new entry
        try:
            category_info = fetch_category_info(CLIENT_ID, OAUTH_TOKEN, category)
            if category_info and category_info.get('box_art_url'):
                category_cache.upsert_template(category, category_info['box_art_url'])
        except Exception as e:
            logger.warning(f"Could not cache box art for category '{category}': {e}")
        
        # Add to detected apps
        if file_path:
            success, error = add_detected_app_to_file(
                location,
                title,
                category,
                window_title,
                file_path,
            )
        else:
            success = add_manual_detected_app(
                title=title,
                category=category,
                location=location,
                window_title=window_title
            )
            error = None
        
        if success:
            return jsonify({
                'status': 'success',
                'message': 'Detected app added successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'error': error or 'Failed to add detected app. Enable Local.txt to save detected games.'
            })
            
    except Exception as e:
        logger.error(f"Error adding manual detected app: {e}")
        return jsonify({'status': 'error', 'error': 'Failed to add detected app'})

@app.route('/api/detected-apps/edit', methods=['POST'])
def api_detected_apps_edit():
    """API endpoint to edit an existing detected app."""
    try:
        data = request.get_json()
        old_process_path = data.get('old_process_path', '').strip()
        old_app_name = data.get('old_app_name', '').strip()
        old_twitch_category = data.get('old_twitch_category', '').strip()
        old_window_title = data.get('old_window_title', '').strip()
        process_path = data.get('process_path', '').strip()
        app_name = data.get('app_name', '').strip()
        twitch_category = data.get('twitch_category', '').strip()
        window_title = data.get('window_title', '').strip()
        file_path = data.get('file_path', '').strip()
        
        if not old_process_path or not process_path or not twitch_category:
            return jsonify({'status': 'error', 'error': 'Old path, new path, and category are required'})
        
        # Import the edit function
        from catswitch.detected_apps import edit_detected_app
        
        # Edit the detected app using ALL identifying fields
        success = edit_detected_app(
            old_process_path, process_path, app_name, twitch_category, window_title,
            old_app_name, old_twitch_category, old_window_title, file_path
        )
        
        if success:
            if twitch_category != old_twitch_category:
                try:
                    category_info = fetch_category_info(CLIENT_ID, OAUTH_TOKEN, twitch_category)
                    if category_info and category_info.get('box_art_url'):
                        category_cache.upsert_template(twitch_category, category_info['box_art_url'])
                except Exception as e:
                    logger.warning(f"Could not cache box art for edited category '{twitch_category}': {e}")
            logger.info(f"Successfully edited detected app: {app_name} - {twitch_category}")
            return jsonify({
                'status': 'success',
                'message': 'Detected app edited successfully'
            })
        else:
            logger.error(f"Failed to edit detected app: {app_name} - {twitch_category}")
            return jsonify({'status': 'error', 'error': 'Failed to edit detected app'})
            
    except Exception as e:
        logger.error(f"Error editing detected app: {e}")
        return jsonify({'status': 'error', 'error': 'Failed to edit detected app'})

# Detected Apps List Management API Endpoints

@app.route('/api/detected-apps/create', methods=['POST'])
def api_detected_apps_create():
    """API endpoint to create a new detected apps list."""
    try:
        data = request.json
        name = data.get('name', '').strip()

        if not name:
            return jsonify({'success': False, 'error': 'Name is required'})

        success, path, error = create_new_file(name, list_type='detected')
        if not success:
            return jsonify({'success': False, 'error': error})

        return jsonify({'success': True, 'name': name, 'path': path})
    except Exception as e:
        logger.error(f"Error creating detected apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/detected-apps/add-local', methods=['POST'])
def api_detected_apps_add_local():
    """API endpoint to add a local detected apps list."""
    try:
        data = request.json
        name = data.get('name', '')
        file_path = data.get('path', '')
        
        if not name or not file_path:
            return jsonify({'success': False, 'error': 'Name and path are required'})
        
        # Handle file path - copy only if not already in detected_apps directory
        try:
            import shutil
            import os
            from catswitch.detected_apps import get_detected_apps_dir
            
            # Normalize paths for comparison
            file_path_normalized = os.path.normpath(file_path)
            detected_apps_dir = os.path.normpath(get_detected_apps_dir())
            
            logger.info(f"File path: {file_path_normalized}")
            logger.info(f"Detected apps dir: {detected_apps_dir}")
            
            # Check if file is already in detected_apps directory
            if file_path_normalized.startswith(detected_apps_dir):
                # File is already in detected_apps directory, use it directly
                logger.info("File is already in detected_apps directory, using directly")
                dest_path = file_path
            else:
                # File is outside detected_apps directory, copy it
                logger.info("File is outside detected_apps directory, copying")
                os.makedirs(detected_apps_dir, exist_ok=True)
                dest_path = os.path.join(detected_apps_dir, os.path.basename(file_path))
                shutil.copy2(file_path, dest_path)
            
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Error handling file: {str(e)}'
            })
            
        # Add the file to the settings
        add_detected_app_file(name, dest_path)
        
        return jsonify({
            'success': True,
            'name': name,
            'path': dest_path
        })
    except Exception as e:
        logger.error(f"Error adding local detected apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/detected-apps/add-url', methods=['POST'])
def api_detected_apps_add_url():
    """API endpoint to add a detected apps list from URL."""
    try:
        data = request.json
        name = data.get('name', None)
        url = data.get('url', '')

        if not url:
            return jsonify({'success': False, 'error': 'URL is required'})

        # Validate URL
        success, content, error = load_from_url_live(url)
        if not success:
            return jsonify({'success': False, 'error': f'Invalid URL: {error}'})

        name = resolve_url_list_name(content, url, name)

        # Only add to settings if validation passed
        add_detected_app_file(name, "", "url", url)

        return jsonify({'success': True, 'name': name})
    except Exception as e:
        logger.error(f"Error adding URL detected apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/detected-apps/edit-url', methods=['POST'])
def api_detected_apps_edit_url():
    """API endpoint to edit a detected apps URL-based list."""
    try:
        data = request.json
        current_url = data.get('current_url', '')
        new_url = data.get('url', '')
        custom_name = data.get('name', None)

        if not current_url or not new_url:
            return jsonify({'success': False, 'error': 'Current URL and new URL are required'})

        success, content, error = load_from_url_live(new_url)
        if not success:
            return jsonify({'success': False, 'error': f'Invalid URL: {error}'})

        name = resolve_url_list_name(content, new_url, custom_name)

        for list_info in get_detected_app_files():
            if (
                list_info.get('source') == 'url'
                and list_info.get('url') == new_url
                and list_info.get('url') != current_url
            ):
                return jsonify({'success': False, 'error': 'A list with this URL already exists'})

        if not update_detected_app_url_list(current_url, name, new_url):
            return jsonify({'success': False, 'error': 'Failed to update URL list'})

        return jsonify({'success': True, 'name': name, 'url': new_url})
    except Exception as e:
        logger.error(f"Error editing URL detected apps list: {e}")
        return jsonify({'success': False, 'error': str(e)})

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        run_app(sys.argv[1], sys.argv[2])
    else:
        logger.info("Usage: python web_interface.py <client_id> <oauth_token>") 