"""IGDB API client and ScreenTracker result normalization.

IGDB is a Twitch product, so it is authenticated with a Twitch application's
client credentials (OAuth "client_credentials" grant) rather than a static API
key. App access tokens are valid for weeks, so this module keeps a small
process-wide cache instead of requesting one per call.

Responses are normalized to the same shape as ``lib.tmdb`` so both sources can
feed the same templates and the same ``shows`` table. Games use the media type
``"game"`` and reuse the ``tmdb_id`` column as a generic source id.
"""

import os
import re
import threading
import time

import requests


IGDB_BASE = "https://api.igdb.com/v4"
IGDB_IMAGE_BASE = "https://images.igdb.com/igdb/image/upload/t_cover_big"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"

# IGDB dropped the `status` and `category` fields; `game_type` replaced
# `category`, and `status` has no usable replacement at the game level, so the
# release status is derived from `first_release_date` instead.
#
# Types that belong in a watch list: main games, plus remakes, remasters, ports
# and other standalone re-releases. Excluded: DLC, expansions, bundles, mods,
# episodes, seasons, packs and updates.
_GAME_TYPES = (0, 4, 8, 9, 10, 11, 12)
_GAME_TYPE_FILTER = (
    f"game_type = ({','.join(str(t) for t in _GAME_TYPES)})"
    " & version_parent = null"
)

_FIELDS = (
    "name,summary,first_release_date,cover.image_id,genres.name,"
    "involved_companies.company.name,involved_companies.developer,"
    "involved_companies.publisher"
)

_token_lock = threading.Lock()
_token = {"value": "", "expires_at": 0.0}


def is_configured():
    """Return whether both Twitch application credentials are configured."""
    return bool(_client_id() and _client_secret())


def _client_id():
    return os.environ.get("IGDB_CLIENT_ID", "").strip()


def _client_secret():
    return os.environ.get("IGDB_CLIENT_SECRET", "").strip()


def access_token():
    """Return a cached Twitch app access token, requesting it when needed."""
    with _token_lock:
        now = time.time()
        if _token["value"] and now < _token["expires_at"]:
            return _token["value"]

        client_id = _client_id()
        client_secret = _client_secret()
        if not client_id or not client_secret:
            raise RuntimeError(
                "IGDB is not configured. Set IGDB_CLIENT_ID and "
                "IGDB_CLIENT_SECRET."
            )

        # Sent as a form body so the client secret never reaches a URL.
        response = requests.post(
            TWITCH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()

        token = payload.get("access_token") or ""
        if not token:
            raise RuntimeError("Twitch did not return an access token.")

        # Refresh a little early so an in-flight request cannot race expiry.
        expires_in = int(payload.get("expires_in") or 0)
        _token["value"] = token
        _token["expires_at"] = now + max(expires_in - 60, 0)
        return token


def safe_error(exc):
    """Format an API error without exposing the Twitch client secret."""
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None):
        return f"IGDB HTTP {response.status_code}"
    return re.sub(r"(client_secret=)[^&\s]+", r"\1[redacted]", str(exc))


def igdb_post(path, query):
    """Send an Apicalypse query to IGDB and return the decoded list of rows."""
    headers = {
        "Client-ID": _client_id(),
        "Authorization": f"Bearer {access_token()}",
        "Accept": "application/json",
        "Content-Type": "text/plain",
    }
    response = requests.post(
        f"{IGDB_BASE}{path}",
        headers=headers,
        data=query,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def search(query, limit=12):
    """Search IGDB for main games and return normalized results."""
    term = _search_term(query)
    if not term:
        return []

    # Filtering server-side keeps `limit` worth of usable rows; filtering in
    # Python would return short pages full of DLC and collector's editions.
    return [
        _normalize(row)
        for row in igdb_post(
            "/games",
            f'fields {_FIELDS}; search "{term}"; '
            f"where {_GAME_TYPE_FILTER}; limit {_limit(limit)};",
        )
    ]


def details(igdb_id):
    """Return complete normalized metadata for one game."""
    game_id = str(igdb_id or "").strip()
    if not game_id.isdigit():
        raise ValueError(f"Unsupported IGDB id: {igdb_id}")

    rows = igdb_post(
        "/games",
        f"fields {_FIELDS}; where id = {game_id}; limit 1;",
    )
    if not rows:
        raise LookupError(f"No IGDB game with id {game_id}.")
    return _normalize(rows[0])


def fetch_genres(igdb_id):
    """Return genre names for a saved game."""
    try:
        return details(igdb_id).get("genres", [])
    except Exception:
        return []


def _search_term(value):
    """Collapse whitespace and escape a term for an Apicalypse string literal."""
    cleaned = " ".join(str(value or "").split())
    return cleaned.replace("\\", "\\\\").replace('"', '\\"')


def _limit(value):
    try:
        return max(1, min(int(value), 50))
    except (TypeError, ValueError):
        return 12


def _status(item):
    """Derive a release status, since IGDB no longer exposes one."""
    release = item.get("first_release_date")
    if not release:
        return ""
    try:
        return "Released" if int(release) <= time.time() else "Upcoming"
    except (TypeError, ValueError):
        return ""


def _year(release_timestamp):
    if not release_timestamp:
        return ""
    try:
        return time.strftime("%Y", time.gmtime(int(release_timestamp)))
    except (TypeError, ValueError, OSError):
        return ""


def _company(item):
    """Prefer the developer, then the publisher, as the card's "network"."""
    companies = item.get("involved_companies") or []
    for role in ("developer", "publisher"):
        for entry in companies:
            if entry.get(role):
                name = (entry.get("company") or {}).get("name")
                if name:
                    return name
    return ""


def _normalize(item):
    cover = item.get("cover") or {}
    image_id = cover.get("image_id") or ""

    return {
        "tmdb_id": str(item.get("id") or ""),
        "media_type": "game",
        "title": item.get("name") or "Untitled",
        "year": _year(item.get("first_release_date")),
        "overview": item.get("summary") or "",
        "poster_url": f"{IGDB_IMAGE_BASE}/{image_id}.jpg" if image_id else "",
        # IGDB carries no IMDb id; lib.tmdb returns one, so the card's IMDb
        # link is simply absent for games.
        "imdb_url": "",
        "network": _company(item),
        # IGDB has no single country-of-origin field.
        "country": "",
        "status": _status(item),
        "genres": [
            genre["name"] for genre in item.get("genres") or [] if genre.get("name")
        ],
    }
