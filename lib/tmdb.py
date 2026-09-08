"""TMDB v3 API client and ScreenTracker result normalization."""

import os
import re

import requests


TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def is_configured():
    """Return whether either supported application credential is configured."""
    return bool(
        os.environ.get("TMDB_API_TOKEN", "").strip()
        or os.environ.get("TMDB_API_KEY", "").strip()
    )


def safe_error(exc):
    """Format an API error without exposing a v3 API key from its URL."""
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None):
        return f"TMDB HTTP {response.status_code}"
    return re.sub(r"([?&]api_key=)[^&\s]+", r"\1[redacted]", str(exc))


def tmdb_get(path, params=None):
    """Make an authenticated GET request to TMDB."""
    token = os.environ.get("TMDB_API_TOKEN", "").strip()
    api_key = os.environ.get("TMDB_API_KEY", "").strip()
    if not token and not api_key:
        raise RuntimeError(
            "TMDB is not configured. Set TMDB_API_TOKEN (recommended) or "
            "TMDB_API_KEY."
        )

    request_params = dict(params or {})
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        request_params["api_key"] = api_key

    response = requests.get(
        f"{TMDB_BASE}{path}",
        headers=headers,
        params=request_params,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def search(query, limit=12):
    """Search movies and TV series and return normalized results."""
    data = tmdb_get(
        "/search/multi",
        params={"query": query, "include_adult": "false", "language": "en-GB"},
    )
    results = []
    for item in data.get("results") or []:
        if item.get("media_type") not in ("movie", "tv"):
            continue
        results.append(_normalize(item))
        if len(results) >= limit:
            break
    return results


def details(media_type, tmdb_id):
    """Return complete normalized metadata for one movie or TV series."""
    tmdb_type = _tmdb_type(media_type)
    if not tmdb_type:
        raise ValueError(f"Unsupported media type: {media_type}")
    data = tmdb_get(
        f"/{tmdb_type}/{tmdb_id}",
        params={"append_to_response": "external_ids", "language": "en-GB"},
    )
    return _normalize(data, media_type=tmdb_type, detailed=True)


def fetch_genres(media_type, tmdb_id):
    """Return genre names for a saved item."""
    try:
        return details(media_type, tmdb_id).get("genres", [])
    except Exception:
        return []


def _tmdb_type(media_type):
    if media_type == "movie":
        return "movie"
    if media_type in ("series", "tv"):
        return "tv"
    return None


def _screen_type(tmdb_type):
    return "movie" if tmdb_type == "movie" else "series"


def _normalize(item, media_type=None, detailed=False):
    tmdb_type = media_type or item.get("media_type") or "tv"
    title = item.get("title") or item.get("name") or "Untitled"
    release_date = item.get("release_date") or item.get("first_air_date") or ""
    poster_path = item.get("poster_path") or ""

    origin_countries = item.get("origin_country") or []
    if not origin_countries:
        origin_countries = [
            country.get("iso_3166_1", "")
            for country in item.get("production_countries") or []
        ]

    networks = item.get("networks") or []
    external_ids = item.get("external_ids") or {}
    imdb_id = item.get("imdb_id") or external_ids.get("imdb_id") or ""

    genres = []
    if detailed:
        genres = [
            genre["name"] for genre in item.get("genres") or [] if genre.get("name")
        ]

    return {
        "tmdb_id": str(item.get("id") or ""),
        "media_type": _screen_type(tmdb_type),
        "title": title,
        "year": release_date[:4],
        "overview": item.get("overview") or "",
        "poster_url": f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else "",
        "imdb_url": f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else "",
        "network": networks[0].get("name", "") if networks else "",
        "country": next((country for country in origin_countries if country), ""),
        "status": item.get("status") or "",
        "genres": genres,
    }
