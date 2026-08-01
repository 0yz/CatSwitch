"""Twitch authentication: Device Code Flow, DPAPI token storage, refresh."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import webbrowser
from typing import Any

import requests
import win32crypt

from catswitch.paths import get_tokens_dir

logger = logging.getLogger("catswitch.auth_twitch")

TWITCH_CLIENT_ID = "vkzd8y0un4r81asaiqfi10ojdohy39"
# Local Flask/UI port (Device Code Flow has no OAuth redirect URI).
REDIRECT_URI = "http://localhost:51111"

AUTH_SCOPES = "channel:manage:broadcast user:edit:broadcast"
_DEVICE_URL = "https://id.twitch.tv/oauth2/device"
_TOKEN_URL = "https://id.twitch.tv/oauth2/token"

TOKEN_VALID = "valid"
TOKEN_INVALID = "invalid"
TOKEN_UNREACHABLE = "unreachable"

_pending_device_lock = threading.Lock()
_pending_device: dict[str, Any] = {}


def _tokens_dir():
    path = get_tokens_dir()
    os.makedirs(path, exist_ok=True)
    return path


def _token_file_for_login(login: str) -> str:
    safe = login.lower().strip()
    for ch in ("/", "\\", ":", "*", "?", '"', "<", ">", "|"):
        safe = safe.replace(ch, "_")
    return os.path.join(_tokens_dir(), f"{safe}.bin")


def _encrypt_blob(text: str) -> bytes:
    return win32crypt.CryptProtectData(text.encode(), None)


def _decrypt_blob(blob: bytes) -> str:
    return win32crypt.CryptUnprotectData(blob)[1].decode()


def save_account_tokens(
    login: str,
    access_token: str,
    refresh_token: str | None = None,
) -> None:
    """Persist access (+ optional refresh) tokens encrypted with DPAPI."""
    payload = json.dumps(
        {
            "access_token": access_token,
            "refresh_token": refresh_token or "",
        }
    )
    with open(_token_file_for_login(login), "wb") as handle:
        handle.write(_encrypt_blob(payload))


def save_account_token(login: str, token: str) -> None:
    """Backward-compatible: save access token; keep existing refresh if any."""
    _access, refresh = load_account_tokens(login)
    save_account_tokens(login, token, refresh)


def load_account_tokens(login: str) -> tuple[str | None, str | None]:
    """Return (access_token, refresh_token). Legacy single-token blobs still work."""
    if not login:
        return None, None
    try:
        with open(_token_file_for_login(login), "rb") as handle:
            raw = _decrypt_blob(handle.read())
    except FileNotFoundError:
        return None, None
    except Exception:
        return None, None

    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("access_token"):
            access = data.get("access_token") or None
            refresh = data.get("refresh_token") or None
            return access, refresh
    except (json.JSONDecodeError, TypeError):
        pass

    # Pre-refresh format: entire blob was the access token string.
    return raw or None, None


def load_account_token(login: str) -> str | None:
    access, _refresh = load_account_tokens(login)
    return access


def delete_account_token(login: str) -> None:
    try:
        os.remove(_token_file_for_login(login))
    except FileNotFoundError:
        pass


def _get_auth_settings() -> dict:
    from catswitch.settings import get_setting

    auth = get_setting("auth", None)
    if not isinstance(auth, dict):
        return {"active_login": None, "accounts": []}
    auth.setdefault("active_login", None)
    auth.setdefault("accounts", [])
    return auth


def _mutate_auth_settings(mutator) -> None:
    """Apply mutator(auth_dict) under the settings lock."""
    from catswitch.settings import mutate_settings

    def _apply(settings: dict):
        auth = settings.get("auth")
        if not isinstance(auth, dict):
            auth = {"active_login": None, "accounts": []}
        auth.setdefault("active_login", None)
        auth.setdefault("accounts", [])
        mutator(auth)
        settings["auth"] = auth

    mutate_settings(_apply)


def list_accounts() -> list:
    return list(_get_auth_settings().get("accounts", []))


def get_active_login() -> str | None:
    return _get_auth_settings().get("active_login")


def set_active_login(login: str | None) -> None:
    def _apply(auth: dict) -> None:
        auth["active_login"] = login

    _mutate_auth_settings(_apply)


def probe_twitch_token(client_id: str, oauth_token: str) -> tuple[str, dict | None]:
    """Check a Twitch token without treating network failures as expiry.

    Returns:
        (TOKEN_VALID, user_dict) — token works
        (TOKEN_INVALID, None) — Twitch rejected the token (401/403) or empty user
        (TOKEN_UNREACHABLE, None) — timeout, connection error, or transient HTTP errors
    """
    if not oauth_token:
        return TOKEN_INVALID, None

    try:
        response = requests.get(
            "https://api.twitch.tv/helix/users",
            headers={
                "Client-ID": client_id,
                "Authorization": f"Bearer {oauth_token}",
            },
            timeout=10,
        )
    except requests.RequestException:
        return TOKEN_UNREACHABLE, None

    if response.status_code in (401, 403):
        return TOKEN_INVALID, None
    if response.status_code != 200:
        return TOKEN_UNREACHABLE, None

    try:
        data = response.json().get("data") or []
    except ValueError:
        return TOKEN_UNREACHABLE, None

    if not data:
        return TOKEN_INVALID, None

    user = data[0]
    return TOKEN_VALID, {
        "id": user.get("id"),
        "login": user.get("login"),
        "display_name": user.get("display_name"),
        "profile_image_url": user.get("profile_image_url"),
    }


def fetch_twitch_user(client_id: str, oauth_token: str) -> dict | None:
    status, user = probe_twitch_token(client_id, oauth_token)
    if status == TOKEN_VALID:
        return user
    return None


def validate_token(client_id: str, oauth_token: str) -> bool:
    """True only when Twitch confirms the token (not when offline)."""
    status, _user = probe_twitch_token(client_id, oauth_token)
    return status == TOKEN_VALID


def refresh_user_token(
    client_id: str,
    refresh_token: str,
) -> tuple[str, str | None] | None:
    """Exchange a refresh token for a new access (+ refresh) pair. No client secret."""
    if not refresh_token:
        return None
    try:
        response = requests.post(
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.warning("Token refresh request failed: %s", exc)
        return None

    if response.status_code != 200:
        logger.info(
            "Token refresh rejected (%s): %s",
            response.status_code,
            (response.text or "")[:200],
        )
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    access = data.get("access_token")
    if not access:
        return None
    new_refresh = data.get("refresh_token") or refresh_token
    return access, new_refresh


def refresh_account_tokens(
    login: str,
    client_id: str = TWITCH_CLIENT_ID,
) -> str | None:
    """Refresh stored tokens for login; return new access token or None."""
    _access, refresh = load_account_tokens(login)
    if not refresh:
        return None
    pair = refresh_user_token(client_id, refresh)
    if not pair:
        return None
    new_access, new_refresh = pair
    save_account_tokens(login, new_access, new_refresh)
    logger.info("Refreshed Twitch token for %s", login)
    return new_access


def get_saved_account_profile(login: str | None = None) -> dict | None:
    """Return cached account profile fields from settings (no network)."""
    target = login or get_active_login()
    if not target:
        return None
    for account in list_accounts():
        if account.get("login") == target:
            return {
                "id": account.get("id"),
                "login": account.get("login"),
                "display_name": account.get("display_name"),
                "profile_image_url": account.get("profile_image_url"),
            }
    return None


def upsert_account(user: dict) -> None:
    login = user.get("login")
    if not login:
        return

    def _apply(auth: dict) -> None:
        accounts = auth.get("accounts", [])
        updated = False
        for account in accounts:
            if account.get("login") == login:
                account.update(
                    {
                        "id": user.get("id"),
                        "display_name": user.get("display_name"),
                        "login": login,
                        "profile_image_url": user.get("profile_image_url"),
                    }
                )
                updated = True
                break

        if not updated:
            accounts.append(
                {
                    "id": user.get("id"),
                    "login": login,
                    "display_name": user.get("display_name"),
                    "profile_image_url": user.get("profile_image_url"),
                }
            )

        auth["accounts"] = accounts

    _mutate_auth_settings(_apply)


def remove_account(login: str) -> bool:
    found = {"ok": False}

    from catswitch.settings import mutate_settings

    def _outer(settings: dict):
        auth = settings.get("auth")
        if not isinstance(auth, dict):
            auth = {"active_login": None, "accounts": []}
        auth.setdefault("active_login", None)
        auth.setdefault("accounts", [])
        accounts = auth.get("accounts", [])
        new_accounts = [a for a in accounts if a.get("login") != login]
        if len(new_accounts) == len(accounts):
            return False
        auth["accounts"] = new_accounts
        if auth.get("active_login") == login:
            auth["active_login"] = new_accounts[0]["login"] if new_accounts else None
        settings["auth"] = auth
        found["ok"] = True
        return True

    mutate_settings(_outer)
    if found["ok"]:
        delete_account_token(login)
    return found["ok"]


def register_account_session(
    oauth_token: str,
    client_id: str = TWITCH_CLIENT_ID,
    refresh_token: str | None = None,
) -> dict | None:
    """Validate token, persist it (and refresh if given), set active account."""
    user = fetch_twitch_user(client_id, oauth_token)
    if not user:
        return None
    login = user["login"]
    if refresh_token is None:
        _old_access, old_refresh = load_account_tokens(login)
        refresh_token = old_refresh
    save_account_tokens(login, oauth_token, refresh_token)
    upsert_account(user)
    set_active_login(login)
    return user


def resolve_startup_token(client_id: str = TWITCH_CLIENT_ID) -> str | None:
    """Load the last active account token for app startup.

    Online: token must validate with Twitch (or refresh successfully).
    Offline / unreachable: keep a saved token so the offline screen can show
    instead of forcing the welcome/login flow.
    """
    auth = _get_auth_settings()

    def _accept(login: str | None, token: str | None) -> str | None:
        if not token or not login:
            return None
        status, _user = probe_twitch_token(client_id, token)
        if status == TOKEN_VALID:
            return token
        if status == TOKEN_UNREACHABLE:
            return token
        if status == TOKEN_INVALID:
            refreshed = refresh_account_tokens(login, client_id)
            if refreshed:
                return refreshed
        return None

    active_login = auth.get("active_login")
    if active_login:
        access, _refresh = load_account_tokens(active_login)
        accepted = _accept(active_login, access)
        if accepted:
            return accepted

    for account in auth.get("accounts", []):
        login = account.get("login")
        access, _refresh = load_account_tokens(login)
        accepted = _accept(login, access)
        if accepted:
            if login:
                set_active_login(login)
            return accepted

    return None


def _clear_pending_device() -> None:
    global _pending_device
    _pending_device = {}


def start_device_login(
    client_id: str = TWITCH_CLIENT_ID,
    open_browser: bool = True,
) -> dict[str, Any]:
    """Begin Twitch Device Code Flow; optionally open the verification URI."""
    try:
        response = requests.post(
            _DEVICE_URL,
            data={
                "client_id": client_id,
                "scopes": AUTH_SCOPES,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Twitch login: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"Twitch device login failed ({response.status_code}): "
            f"{(response.text or '')[:200]}"
        )

    data = response.json()
    device_code = data.get("device_code")
    user_code = data.get("user_code")
    verification_uri = data.get("verification_uri")
    if not device_code or not user_code or not verification_uri:
        raise RuntimeError("Twitch device login returned incomplete data")

    interval = int(data.get("interval") or 5)
    expires_in = int(data.get("expires_in") or 1800)

    with _pending_device_lock:
        _pending_device.clear()
        _pending_device.update(
            {
                "device_code": device_code,
                "user_code": user_code,
                "verification_uri": verification_uri,
                "interval": max(interval, 1),
                "expires_at": time.time() + expires_in,
                "client_id": client_id,
                "status": "pending",
                "last_poll_at": 0.0,
            }
        )

    if open_browser:
        webbrowser.open(verification_uri)

    return {
        "user_code": user_code,
        "verification_uri": verification_uri,
        "interval": max(interval, 1),
        "expires_in": expires_in,
    }


def get_pending_device_login() -> dict[str, Any] | None:
    with _pending_device_lock:
        if not _pending_device:
            return None
        return {
            "user_code": _pending_device.get("user_code"),
            "verification_uri": _pending_device.get("verification_uri"),
            "interval": _pending_device.get("interval", 5),
            "status": _pending_device.get("status", "pending"),
            "expires_in": max(
                0, int((_pending_device.get("expires_at") or 0) - time.time())
            ),
        }


def cancel_device_login() -> None:
    with _pending_device_lock:
        _clear_pending_device()


def poll_device_login() -> dict[str, Any]:
    """Poll Twitch once for the pending device authorization.

    Returns status: pending | slow_down | success | denied | expired | error | none
    On success, includes access_token and refresh_token.
    """
    with _pending_device_lock:
        if not _pending_device or _pending_device.get("status") != "pending":
            status = (_pending_device or {}).get("status") or "none"
            return {"status": status}

        if time.time() >= float(_pending_device.get("expires_at") or 0):
            _pending_device["status"] = "expired"
            return {"status": "expired"}

        interval = float(_pending_device.get("interval") or 5)
        last = float(_pending_device.get("last_poll_at") or 0)
        now = time.time()
        if last and (now - last) < interval:
            return {
                "status": "pending",
                "user_code": _pending_device.get("user_code"),
                "retry_after": max(1, int(interval - (now - last))),
            }

        device_code = _pending_device["device_code"]
        client_id = _pending_device.get("client_id") or TWITCH_CLIENT_ID
        _pending_device["last_poll_at"] = now

    try:
        response = requests.post(
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "device_code": device_code,
                "scopes": AUTH_SCOPES,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        return {"status": "error", "error": str(exc)}

    if response.status_code == 200:
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "error": "Invalid token response"}
        access = data.get("access_token")
        refresh = data.get("refresh_token")
        if not access:
            return {"status": "error", "error": "No access token in response"}
        with _pending_device_lock:
            _clear_pending_device()
        return {
            "status": "success",
            "access_token": access,
            "refresh_token": refresh,
        }

    try:
        body = response.json() or {}
    except ValueError:
        body = {}
    message = (body.get("message") or body.get("error") or "").lower()
    error_code = (body.get("error") or "").lower()

    if "authorization_pending" in message or error_code == "authorization_pending":
        return {"status": "pending"}
    if "slow_down" in message or error_code == "slow_down":
        with _pending_device_lock:
            if _pending_device:
                _pending_device["interval"] = (
                    float(_pending_device.get("interval") or 5) + 5
                )
        return {"status": "slow_down", "retry_after": 10}
    if "expired" in message or error_code == "expired_token":
        with _pending_device_lock:
            _clear_pending_device()
        return {"status": "expired"}
    if "access_denied" in message or error_code == "access_denied":
        with _pending_device_lock:
            _clear_pending_device()
        return {"status": "denied"}

    logger.warning(
        "Unexpected device poll response %s: %s",
        response.status_code,
        (response.text or "")[:300],
    )
    return {
        "status": "error",
        "error": body.get("message")
        or body.get("error")
        or f"HTTP {response.status_code}",
    }


def build_auth_url(
    client_id: str = TWITCH_CLIENT_ID,
    redirect_uri: str = REDIRECT_URI,
    force_verify: bool = False,
) -> str:
    """Deprecated implicit grant URL (Device Code Flow is the login path)."""
    url = (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=token"
        f"&scope=channel:manage:broadcast+user:edit:broadcast"
    )
    if force_verify:
        url += "&force_verify=true"
    return url


def open_twitch_login(
    client_id: str = TWITCH_CLIENT_ID,
    redirect_uri: str = REDIRECT_URI,
    force_verify: bool = False,
) -> str:
    """Deprecated: opens implicit authorize URL. Prefer start_device_login()."""
    url = build_auth_url(client_id, redirect_uri, force_verify=force_verify)
    webbrowser.open(url)
    return url
