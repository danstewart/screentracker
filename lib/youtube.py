"""YouTube Data API v3 client and ScreenTracker result normalization.

Only the `videos.list` endpoint is used. It costs a single quota unit of the
10,000/day free allowance and returns everything a card needs, so there is no
need for the far more expensive `search.list` endpoint.

Unlike IGDB there is no token exchange: the API takes a plain API key.
"""

import os
import re

import requests


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_THUMB_BASE = "https://i.ytimg.com/vi"

# Video ids are 11 characters of URL-safe base64.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# The id appears after youtu.be/, after a v= parameter, or as an /embed/,
# /shorts/, /live/ or /v/ path segment. Matching exactly 11 characters means
# trailing query strings and timestamps are ignored for free; the trailing
# lookahead stops a longer token being truncated into a valid-looking id.
_EMBEDDED_ID_RE = re.compile(
    r"(?:youtu\.be/|[?&]v=|/(?:embed|shorts|live|v)/)"
    r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
)

# Best first. The API omits sizes it has not generated.
_THUMBNAIL_ORDER = ("maxres", "standard", "high", "medium", "default")

# Clock form ("1:23", "1:02:03") and the h/m/s form YouTube prints ("1h2m3s").
_CLOCK_RE = re.compile(r"^\d+(?::\d+){1,2}$")
_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", re.IGNORECASE)


def is_configured():
    """Return whether a YouTube API key is configured."""
    return bool(_api_key())


def _api_key():
    return os.environ.get("YOUTUBE_API_KEY", "").strip()


def safe_error(exc):
    """Format an API error without exposing the API key from its URL."""
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None):
        return f"YouTube HTTP {response.status_code}"
    return re.sub(r"([?&]key=)[^&\s]+", r"\1[redacted]", str(exc))


def parse_timestamp(value):
    """Return a start offset in whole seconds, or None when the value is empty.

    Accepts plain seconds ("90"), clock form ("1:23", "1:02:03") and the
    h/m/s form YouTube prints ("1h2m3s"). Raises ValueError on anything else
    so callers can reject bad input instead of silently losing it.
    """
    text = str(value if value is not None else "").strip().lower()
    if not text:
        return None

    if text.isdigit():
        return int(text) or None

    if _CLOCK_RE.match(text):
        parts = [int(part) for part in text.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            if seconds < 60:
                return minutes * 60 + seconds
        else:
            hours, minutes, seconds = parts
            if minutes < 60 and seconds < 60:
                return hours * 3600 + minutes * 60 + seconds

    match = _DURATION_RE.match(text)
    if match and any(match.groups()):
        hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
        if minutes < 60 and seconds < 60:
            return hours * 3600 + minutes * 60 + seconds

    raise ValueError("Enter a time like 1:23, 1:02:03 or 90")


def format_timestamp(seconds):
    """Format whole seconds as h:mm:ss or m:ss for display in the menu."""
    total = int(seconds or 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def video_id(value):
    """Return the video id from a YouTube URL, or from a bare id.

    Returns an empty string when the input is neither, so callers can tell
    "not a YouTube link" apart from "the video does not exist".
    """
    text = str(value or "").strip()
    if not text:
        return ""

    if _VIDEO_ID_RE.match(text):
        return text

    if "youtube.com" not in text and "youtu.be" not in text:
        return ""

    match = _EMBEDDED_ID_RE.search(text)
    return match.group(1) if match else ""


def details(value):
    """Return normalized metadata for one YouTube video."""
    vid = video_id(value)
    if not vid:
        raise ValueError(f"Unsupported YouTube video: {value}")

    if not _api_key():
        raise RuntimeError("YouTube is not configured. Set YOUTUBE_API_KEY.")

    response = requests.get(
        f"{YOUTUBE_API_BASE}/videos",
        params={"part": "snippet", "id": vid, "key": _api_key()},
        timeout=15,
    )
    response.raise_for_status()

    items = (response.json() or {}).get("items") or []
    if not items:
        raise LookupError(f"No YouTube video with id {vid}.")
    return _normalize(items[0])


def _thumbnail(thumbnails, vid):
    for name in _THUMBNAIL_ORDER:
        url = (thumbnails.get(name) or {}).get("url")
        if url:
            return url
    # hqdefault exists for every valid id, even if the API omitted thumbnails.
    return f"{YOUTUBE_THUMB_BASE}/{vid}/hqdefault.jpg"


def _normalize(item):
    snippet = item.get("snippet") or {}
    vid = str(item.get("id") or "")

    return {
        "tmdb_id": vid,
        "media_type": "youtube",
        "title": snippet.get("title") or "Untitled",
        "year": (snippet.get("publishedAt") or "")[:4],
        "overview": snippet.get("description") or "",
        "poster_url": _thumbnail(snippet.get("thumbnails") or {}, vid),
        # The card builds the watch link from the video id, so this stays empty.
        "imdb_url": "",
        "network": snippet.get("channelTitle") or "",
        "country": "",
        "status": "",
        "genres": [],
    }
