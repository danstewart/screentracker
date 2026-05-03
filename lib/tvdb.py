"""TVDB v4 API client and result normalization."""

import os
import time

import requests

TVDB_API_KEY = os.environ.get("TVDB_API_KEY", "")
TVDB_BASE = "https://api4.thetvdb.com/v4"

_token_cache = {"token": None, "expires_at": 0}


def tvdb_token():
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now:
        return _token_cache["token"]

    if not TVDB_API_KEY:
        raise RuntimeError(
            "TVDB_API_KEY is not set. Get one at https://thetvdb.com/api-information "
            "and set the TVDB_API_KEY environment variable."
        )

    r = requests.post(f"{TVDB_BASE}/login", json={"apikey": TVDB_API_KEY}, timeout=15)
    r.raise_for_status()
    data = r.json()
    token = data.get("data", {}).get("token")
    if not token:
        raise RuntimeError(f"TVDB login failed: {data}")
    _token_cache["token"] = token
    # TVDB tokens are valid for ~30 days; refresh after 25 to be safe
    _token_cache["expires_at"] = now + (25 * 24 * 60 * 60)
    return token


def tvdb_get(path, params=None):
    headers = {"Authorization": f"Bearer {tvdb_token()}"}
    r = requests.get(
        f"{TVDB_BASE}{path}", headers=headers, params=params or {}, timeout=15
    )
    r.raise_for_status()
    return r.json()


def fetch_genres(tvdb_type, tvdb_id):
    """Return genre name strings from the TVDB extended endpoint."""
    path = f"/{'series' if tvdb_type == 'series' else 'movies'}/{tvdb_id}/extended"
    try:
        data = tvdb_get(path)
        genres = data.get("data", {}).get("genres") or []
        print(genres)
        return [g["name"] for g in genres if g.get("name")]
    except Exception:
        return []


def search(query, limit=12):
    """Search TVDB and return normalised results for series and movies only."""
    data = tvdb_get("/search", params={"query": query, "limit": limit})
    raw = data.get("data", []) or []
    return [_normalize(item) for item in raw if item.get("type") in ("series", "movie")]


def _normalize(item):
    tvdb_id = item.get("tvdb_id") or item.get("id") or ""
    if isinstance(tvdb_id, str) and "-" in tvdb_id:
        tvdb_id = tvdb_id.split("-", 1)[1]

    poster = item.get("image_url") or item.get("image") or item.get("thumbnail") or ""

    year = item.get("year") or ""
    first_aired = item.get("first_air_time") or item.get("firstAired") or ""
    if not year and first_aired:
        year = first_aired[:4]

    overview = item.get("overview") or ""
    if not overview:
        translations = item.get("overviews") or {}
        if isinstance(translations, dict) and translations:
            overview = (
                translations.get("eng")
                or translations.get("en")
                or next(iter(translations.values()), "")
            )

    name = (
        item.get("name")
        or item.get("translatedName")
        or item.get("seriesName")
        or "Untitled"
    )
    if isinstance(name, dict):
        name = (
            name.get("eng") or name.get("en") or next(iter(name.values()), "Untitled")
        )

    item_type = "movie" if item.get("type") == "movie" else "series"

    imdb_url = ""
    for rid in item.get("remote_ids") or []:
        if isinstance(rid, dict) and rid.get("sourceName", "").lower() == "imdb":
            val = rid.get("id", "")
            if val:
                imdb_url = f"https://www.imdb.com/title/{val}/"
                break

    return {
        "tvdb_id": str(tvdb_id),
        "tvdb_type": item_type,
        "title": name,
        "year": str(year),
        "overview": overview,
        "poster_url": poster,
        "imdb_url": imdb_url,
        "network": item.get("network") or "",
        "country": item.get("country") or "",
        "status": item.get("status") or "",
    }
