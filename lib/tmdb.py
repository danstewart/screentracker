"""TMDB v3 API client and ScreenTracker result normalization."""

import os
import re
import unicodedata

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


def find_legacy_match(tvdb_id, media_type, title, year="", imdb_url=""):
    """Find a TMDB item for a legacy TVDB-backed library row.

    TVDB IDs can be resolved directly for series. Movies are resolved through
    their IMDb ID where available, then both types fall back to a conservative
    exact title/year search.
    """
    tmdb_type = _tmdb_type(media_type)

    if tmdb_type == "tv" and tvdb_id:
        data = tmdb_get(
            f"/find/{tvdb_id}",
            params={"external_source": "tvdb_id", "language": "en-GB"},
        )
        match = _best_match(data.get("tv_results") or [], tmdb_type, title, year)
        if match:
            return match

    imdb_match = re.search(r"tt\d+", imdb_url or "", re.IGNORECASE)
    if imdb_match:
        data = tmdb_get(
            f"/find/{imdb_match.group(0).lower()}",
            params={"external_source": "imdb_id", "language": "en-GB"},
        )
        result_types = (
            [(tmdb_type, "movie_results" if tmdb_type == "movie" else "tv_results")]
            if tmdb_type
            else [("movie", "movie_results"), ("tv", "tv_results")]
        )
        for result_type, result_key in result_types:
            match = _best_match(
                data.get(result_key) or [], result_type, title, year
            )
            if match:
                return match

    if not tmdb_type:
        return None
    params = {"query": title, "language": "en-GB", "include_adult": "false"}
    if year:
        params["year" if tmdb_type == "movie" else "first_air_date_year"] = year
    data = tmdb_get(f"/search/{tmdb_type}", params=params)
    return _best_match(
        data.get("results") or [], tmdb_type, title, year, require_exact=True
    )


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


def _match_text(value):
    normalized = unicodedata.normalize("NFKD", value or "").casefold()
    return "".join(char for char in normalized if char.isalnum())


def _best_match(items, tmdb_type, title, year, require_exact=False):
    if not items:
        return None

    expected_title = _match_text(title)
    expected_year = str(year or "")[:4]
    ranked = []
    for position, item in enumerate(items):
        item_title = item.get("title") or item.get("name") or ""
        item_date = item.get("release_date") or item.get("first_air_date") or ""
        title_exact = bool(expected_title and _match_text(item_title) == expected_title)
        year_exact = bool(expected_year and item_date[:4] == expected_year)
        score = (4 if title_exact else 0) + (2 if year_exact else 0) - position / 1000
        ranked.append((score, title_exact, year_exact, item_date, item))

    ranked.sort(key=lambda candidate: candidate[0], reverse=True)
    _, title_exact, year_exact, match_date, match = ranked[0]
    if require_exact and not title_exact:
        return None
    if require_exact and expected_year and match_date and not year_exact:
        return None
    return {
        "tmdb_id": str(match.get("id") or ""),
        "media_type": _screen_type(tmdb_type),
    }
