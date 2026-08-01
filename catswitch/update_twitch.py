import re
import logging
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

TWITCH_REQUEST_TIMEOUT = 10
TWITCH_GQL_URL = "https://gql.twitch.tv/gql"
TWITCH_GQL_CLIENT_ID_FALLBACK = "kimne78kx3ncx6brgo4mv6wki5h1ko"
_twitch_gql_client_id = None

def _get_twitch_gql_client_id():
    """Twitch's public web Client-ID (required for directory follower counts)."""
    global _twitch_gql_client_id
    if _twitch_gql_client_id:
        return _twitch_gql_client_id
    try:
        response = requests.get(
            "https://www.twitch.tv/directory",
            timeout=TWITCH_REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code == 200:
            match = re.search(r"(kimne78kx3ncx6brgo4[a-z0-9]+)", response.text)
            if match:
                _twitch_gql_client_id = match.group(1)
                return _twitch_gql_client_id
    except Exception as e:
        logger.warning(f"Could not fetch Twitch GQL Client-ID: {e}")
    _twitch_gql_client_id = TWITCH_GQL_CLIENT_ID_FALLBACK
    return _twitch_gql_client_id


def _game_name_to_slug(game_name: str) -> str:
    slug = game_name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug.strip("-")


def _gql_game_followers(game_id=None, game_slug=None):
    """Fetch directory followersCount via Twitch's public GraphQL API."""
    if game_id:
        query = (
            "query GameFollowers($id: ID!) { "
            "game(id: $id) { id name displayName followersCount } }"
        )
        variables = {"id": str(game_id)}
    elif game_slug:
        query = (
            "query GameFollowers($slug: String!) { "
            "game(slug: $slug) { id name displayName followersCount } }"
        )
        variables = {"slug": game_slug}
    else:
        return None

    try:
        response = requests.post(
            TWITCH_GQL_URL,
            json=[{"query": query, "variables": variables}],
            headers={
                "Client-ID": _get_twitch_gql_client_id(),
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=TWITCH_REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        if not payload or not isinstance(payload, list):
            return None
        game = payload[0].get("data", {}).get("game")
        if not game:
            return None
        followers = game.get("followersCount")
        return int(followers) if followers is not None else None
    except Exception as e:
        logger.error(f"Error fetching game followers from GQL: {e}")
        return None


def fetch_game_followers_count(game_id=None, game_name=None):
    """
    Get Twitch directory follower count for a game/category.

    Helix does not expose this; uses Twitch's public GraphQL (same data as the directory page).
    """
    if game_id:
        count = _gql_game_followers(game_id=game_id)
        if count is not None:
            return count
    if game_name:
        return _gql_game_followers(game_slug=_game_name_to_slug(game_name))
    return None

def _notify_token_expired(response):
    """Notify the app layer when Twitch returns 401 Unauthorized."""
    if response.status_code != 401:
        return False
    logger.error("Error: Access token expired or invalid (401 Unauthorized)")
    try:
        from catswitch.web_interface import OAUTH_TOKEN, notify_oauth_token_expired
        if not OAUTH_TOKEN:
            return True
        notify_oauth_token_expired()
    except ImportError:
        pass
    return True

def update_stream_category(
    client_id, oauth_token, category_name
) -> Tuple[bool, Optional[str]]:
    """Update the stream category on Twitch.

    Returns:
        (success, box_art_url) — box_art_url may be None even when success is True
        if the follow-up category lookup did not return art.
    """
    target = (category_name or "").strip()
    if not target:
        return False, None

    try:
        from catswitch.web_interface import current_twitch_category

        if (
            current_twitch_category
            and current_twitch_category.strip().casefold() == target.casefold()
        ):
            logger.info(f"Category already '{target}' — skipping Twitch update")
            return True, None
    except ImportError:
        pass

    game_id = get_game_id(client_id, oauth_token, target)
    if not game_id:
        logger.warning(f"Could not find game ID for {target}")
        return False, None

    user_id = get_user_id(client_id, oauth_token)
    if not user_id:
        logger.warning("Could not get user ID")
        return False, None

    url = "https://api.twitch.tv/helix/channels"
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {oauth_token}",
        "Content-Type": "application/json"
    }
    data = {
        "broadcaster_id": user_id,
        "game_id": game_id
    }

    response = requests.patch(url, headers=headers, json=data, timeout=TWITCH_REQUEST_TIMEOUT)

    if response.status_code == 204:
        logger.info("Category updated successfully")
        category_info = fetch_category_info(client_id, oauth_token, target)
        box_art_url = None
        if category_info and category_info.get("box_art_url"):
            box_art_url = category_info["box_art_url"]
        return True, box_art_url
    if _notify_token_expired(response):
        return False, None
    logger.warning(f"Failed to update category: {response.status_code}")
    if response.text:
        logger.info(f"Response: {response.text}")
    return False, None

def get_game_id(client_id, oauth_token, game_name):
    """Get game ID from game name"""
    url = "https://api.twitch.tv/helix/games"
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {oauth_token}"
    }
    params = {"name": game_name}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=TWITCH_REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json().get("data", [])
            if data:
                return data[0]["id"]
            logger.info(f"No game data found for: {game_name}")
        elif _notify_token_expired(response):
            return None
        else:
            logger.warning(f"Failed to get game ID: {response.text}")
    except Exception as e:
        logger.error(f"Error getting game ID: {e}")
    return None

def get_stream_info(client_id, oauth_token):
    """Get current stream information"""
    # First get user ID
    user_id = get_user_id(client_id, oauth_token)
    if not user_id:
        logger.warning("Could not get user ID")
        return None
        
    url = f"https://api.twitch.tv/helix/channels?broadcaster_id={user_id}"
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {oauth_token}"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=TWITCH_REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json().get("data", [])
            if data:
                return data[0]
            logger.info("No channel data found")
        elif _notify_token_expired(response):
            return None
        else:
            logger.warning(f"Failed to get stream info: {response.text}")
    except Exception as e:
        logger.error(f"Error fetching stream info: {e}")
    return None

def update_stream_title(client_id, oauth_token, new_title):
    """Update stream title on Twitch.

    ``new_title`` should already be resolved (e.g. after ``%cat`` substitution).
    Skips the PATCH when it matches the title we last set locally.
    """
    target = new_title if new_title is not None else ""

    try:
        from catswitch.web_interface import current_stream_title

        if current_stream_title is not None and current_stream_title == target:
            logger.info("Title unchanged — skipping Twitch update")
            return True
    except ImportError:
        pass

    user_id = get_user_id(client_id, oauth_token)
    if not user_id:
        logger.warning("Could not get user ID")
        return False
        
    url = f"https://api.twitch.tv/helix/channels?broadcaster_id={user_id}"
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {oauth_token}",
        "Content-Type": "application/json"
    }
    data = {"title": target}
    
    try:
        logger.info(f"Sending title update request to Twitch: {target}")
        response = requests.patch(url, headers=headers, json=data, timeout=TWITCH_REQUEST_TIMEOUT)
        logger.info(f"Twitch response status: {response.status_code}")
        
        if response.status_code == 204:
            logger.info("Title updated successfully on Twitch")
            return True
        if _notify_token_expired(response):
            return False
        logger.warning(f"Failed to update title. Response: {response.text}")
        return False
            
    except Exception as e:
        logger.error(f"Error updating stream title: {e}")
        return False

def fetch_categories(client_id, oauth_token, search_term):
    """Fetch category suggestions from Twitch with full data including box art URLs"""
    if not search_term:
        search_term = "a"  # Get some default results when empty
        
    url = "https://api.twitch.tv/helix/search/categories"
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {oauth_token}",
    }
    params = {
        "query": search_term,
        "first": 5  # Limit to 5 results
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=TWITCH_REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json().get("data", [])
            # Return full category data including box art URLs
            return [{
                "id": item.get("id", ""),
                "name": item["name"],
                "box_art_url": item.get("box_art_url", "").replace("{width}", "100").replace("{height}", "133")
            } for item in data]
        if _notify_token_expired(response):
            return []
    except Exception as e:
        logger.error(f"Error fetching categories: {e}")
    return []

def fetch_category_info(client_id, oauth_token, category_name):
    """Get information about a specific category by name"""
    # Get the game ID first
    game_id = get_game_id(client_id, oauth_token, category_name)
    if not game_id:
        logger.warning(f"Could not find game ID for {category_name}")
        return None
    
    # Get game details
    url = f"https://api.twitch.tv/helix/games?id={game_id}"
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {oauth_token}"
    }
    
    try:
        # Get basic game info first
        response = requests.get(url, headers=headers, timeout=TWITCH_REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            if data["data"] and len(data["data"]) > 0:
                return data["data"][0]
        if _notify_token_expired(response):
            return None
        return None
    except Exception as e:
        logger.error(f"Error fetching category info: {e}")
        return None

def get_current_twitch_category(client_id, oauth_token):
    """Get current stream category"""
    stream_info = get_stream_info(client_id, oauth_token)
    if stream_info:
        return stream_info.get("game_name")
    return None

def get_user_id(client_id, oauth_token):
    """Get user ID from OAuth token"""
    url = "https://api.twitch.tv/helix/users"
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {oauth_token}"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=TWITCH_REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json().get("data", [])
            if data:
                return data[0]["id"]
            else:
                logger.error("Error: No user data returned despite successful API call")
        elif _notify_token_expired(response):
            return None
        else:
            logger.error(f"Error: Twitch API returned status code {response.status_code}")
            logger.info(f"Response body: {response.text}")
    except requests.exceptions.ConnectionError:
        logger.error("Error: Could not connect to Twitch API. Check your internet connection.")
    except requests.exceptions.Timeout:
        logger.error("Error: Request to Twitch API timed out.")
    except Exception as e:
        logger.error(f"Error getting user ID: {e}")
    return None

def search_twitch_categories(client_id, oauth_token, query, limit=5):
    """Search for categories on Twitch"""
    url = f"https://api.twitch.tv/helix/search/categories"
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {oauth_token}"
    }
    params = {
        "query": query,
        "first": limit
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=TWITCH_REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            if "data" in data:
                return data["data"]
        if _notify_token_expired(response):
            return []
        return []
    except Exception as e:
        logger.error(f"Error searching Twitch categories: {e}")
        return []

__all__ = [
    'update_stream_category',
    'get_game_id',
    'get_stream_info',
    'update_stream_title',
    'fetch_categories',
    'fetch_category_info',
    'get_user_id',
    'get_current_twitch_category',
    'search_twitch_categories',
    'fetch_game_followers_count',
]