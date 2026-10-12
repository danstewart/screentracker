"""TV Show, Movie, Game & Video Manager - Flask app"""

import difflib
import os
import re
import secrets
from datetime import datetime

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

load_dotenv()

from lib import db, igdb, tmdb, youtube

# Media type -> (client module, label used in error messages).
_METADATA_SOURCES = {
    "movie": (tmdb, "TMDB"),
    "series": (tmdb, "TMDB"),
    "game": (igdb, "IGDB"),
    "youtube": (youtube, "YouTube"),
}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"

AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "")


@app.template_filter("typelabel")
def type_label_filter(value):
    """Human-readable media type, preserving YouTube's own capitalisation."""
    return {"youtube": "YouTube"}.get(value, (value or "").capitalize())


@app.template_filter("videotime")
def video_time_filter(value):
    """Render a stored YouTube offset as h:mm:ss or m:ss, or empty if unset."""
    return youtube.format_timestamp(value) if value else ""


@app.template_filter("watcheddate")
def watched_date_filter(value):
    if not value:
        return ""
    try:
        dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%-d %b %Y")
    except Exception:
        return ""


@app.before_request
def check_auth():
    if not AUTH_PASSWORD:
        return
    if request.endpoint in ("auth", "static"):
        return
    if not session.get("authenticated"):
        return redirect(url_for("auth"))


@app.route("/auth", methods=["GET", "POST"])
def auth():
    if not AUTH_PASSWORD:
        return redirect(url_for("index"))
    if session.get("authenticated"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if secrets.compare_digest(pin, AUTH_PASSWORD):
            session.permanent = True
            session["authenticated"] = True
            return redirect(url_for("index"))
        error = "Incorrect PIN"
    return render_template("auth.html", error=error)


# --- Routes -----------------------------------------------------------------
def _group_shows(conn, watched):
    """Genre-grouped titles plus the uncategorised ones.

    YouTube videos are excluded: they get their own section rather than a
    genre, so they must not fall into the "Uncategorised" bucket either.
    """
    flag = 1 if watched else 0
    genres = conn.execute("SELECT * FROM genres ORDER BY sort_order, name").fetchall()
    grouped = []
    for g in genres:
        shows = conn.execute(
            """SELECT * FROM shows
               WHERE genre_id = ? AND watched = ? AND media_type != 'youtube'
               ORDER BY title""",
            (g["id"], flag),
        ).fetchall()
        if shows:
            grouped.append({"genre": g, "shows": shows})
    orphans = conn.execute(
        """SELECT * FROM shows
           WHERE genre_id IS NULL AND watched = ? AND media_type != 'youtube'
           ORDER BY title""",
        (flag,),
    ).fetchall()
    return grouped, orphans


def _youtube_section(conn, watched):
    flag = 1 if watched else 0
    return conn.execute(
        """SELECT * FROM shows
           WHERE media_type = 'youtube' AND watched = ?
           ORDER BY title""",
        (flag,),
    ).fetchall()


def _fetch_metadata(media_type, source_id):
    """Fetch normalized metadata from whichever source owns a media type."""
    if media_type == "game":
        return igdb.details(source_id)
    if media_type == "youtube":
        return youtube.details(source_id)
    return tmdb.details(media_type, source_id)


@app.route("/")
def index():
    conn = db.get_db()
    watching_grouped, watching_orphans = _group_shows(conn, watched=False)
    watched_grouped, watched_orphans = _group_shows(conn, watched=True)
    watching_youtube = _youtube_section(conn, watched=False)
    watched_youtube = _youtube_section(conn, watched=True)
    conn.close()
    return render_template(
        "index.html",
        watching_grouped=watching_grouped,
        watching_orphans=watching_orphans,
        watching_youtube=watching_youtube,
        watched_grouped=watched_grouped,
        watched_orphans=watched_orphans,
        watched_youtube=watched_youtube,
        tmdb_configured=tmdb.is_configured(),
        igdb_configured=igdb.is_configured(),
        youtube_configured=youtube.is_configured(),
    )


def _fold(value):
    """Casefold a title and reduce punctuation to word separators."""
    return re.sub(r"[^a-z0-9 ]+", " ", str(value or "").casefold()).strip()


def _match_score(query, title):
    """Score how closely a title matches the query, from 0 (unrelated) to 1."""
    q = _fold(query)
    t = _fold(title)
    if not q or not t:
        return 0.0
    if t == q:
        return 1.0
    ratio = difflib.SequenceMatcher(None, q, t).ratio()
    if t.startswith(f"{q} "):
        return 0.7 + ratio * 0.3
    if f" {q} " in f" {t} ":
        return 0.6 + ratio * 0.3
    if q in t:
        return 0.5 + ratio * 0.3
    return ratio * 0.5


@app.route("/api/search")
def api_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"results": []})

    if not tmdb.is_configured():
        return jsonify(
            {
                "error": "TMDB is not configured. Set TMDB_API_TOKEN or TMDB_API_KEY."
            }
        ), 500

    # Movies and TV come from TMDB, games from IGDB. One source being down
    # must not hide the other's results, so failures are collected rather
    # than returned immediately.
    results = []
    errors = []

    try:
        results.extend(tmdb.search(query))
    except requests.HTTPError as e:
        errors.append(f"TMDB error: {e.response.status_code}")
    except Exception as e:
        errors.append(tmdb.safe_error(e))

    if igdb.is_configured():
        try:
            results.extend(igdb.search(query))
        except requests.HTTPError as e:
            errors.append(f"IGDB error: {e.response.status_code}")
        except Exception as e:
            errors.append(igdb.safe_error(e))

    # TMDB and IGDB each return their own relevance order, but concatenating
    # them puts every film and series ahead of every game. Re-rank the merged
    # list by title closeness so the best match leads, whatever its source.
    # Python's sort is stable, so equal scores keep each source's own order.
    results.sort(
        key=lambda result: _match_score(query, result.get("title")), reverse=True
    )

    if not results and errors:
        return jsonify({"error": "; ".join(errors)}), 502

    payload = {"results": results}
    if errors:
        payload["errors"] = errors
    return jsonify(payload)


@app.route("/api/genres")
def api_genres():
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM genres ORDER BY sort_order, name").fetchall()
    conn.close()
    return jsonify({"genres": [dict(r) for r in rows]})


@app.route("/api/genres", methods=["POST"])
def api_create_genre():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Genre name is required"}), 400

    conn = db.get_db()
    try:
        genre_id = db.resolve_genre(conn, genre_name=name)
        row = conn.execute("SELECT * FROM genres WHERE id = ?", (genre_id,)).fetchone()
        return jsonify({"genre": dict(row)})
    finally:
        conn.close()


@app.route("/api/shows/in-library")
def api_in_library():
    conn = db.get_db()
    rows = conn.execute(
        "SELECT tmdb_id, media_type FROM shows WHERE tmdb_id != ''"
    ).fetchall()
    conn.close()
    return jsonify({"shows": [dict(r) for r in rows]})


@app.route("/api/shows", methods=["POST"])
def api_add_show():
    data = request.get_json(force=True)
    genre_name = (data.get("genre_name") or "").strip()
    genre_id = data.get("genre_id")

    tmdb_id = str(data.get("tmdb_id") or "")
    media_type = data.get("media_type") or ""
    source_genres = []

    if media_type == "youtube":
        tmdb_id = youtube.video_id(data.get("youtube_url") or "")
        if not tmdb_id:
            return jsonify(
                {"error": "Enter a YouTube video URL or 11-character video ID"}
            ), 400

    if tmdb_id:
        if media_type not in _METADATA_SOURCES:
            return jsonify({"error": "Invalid media type"}), 400
        client, label = _METADATA_SOURCES[media_type]
        try:
            metadata = _fetch_metadata(media_type, tmdb_id)
        except requests.HTTPError as exc:
            status = exc.response.status_code
            return jsonify({"error": f"{label} error: {status}"}), 502
        except Exception as exc:
            return jsonify({"error": client.safe_error(exc)}), 500
        data.update(metadata)
        source_genres = metadata.get("genres") or []

    if not genre_name and not genre_id and source_genres:
        # TMDB orders genres from broadest to most specific, so the last is the
        # best default. IGDB returns genres in id order instead, where the
        # first is the most defining one.
        genre_name = source_genres[0] if media_type == "game" else source_genres[-1]

    conn = db.get_db()
    if tmdb_id:
        dup = conn.execute(
            "SELECT id FROM shows WHERE tmdb_id = ? AND media_type = ?",
            (tmdb_id, media_type),
        ).fetchone()
    else:
        dup = conn.execute(
            "SELECT id FROM shows WHERE LOWER(title) = LOWER(?)",
            (data.get("title", ""),),
        ).fetchone()
    if dup:
        conn.close()
        return jsonify({"error": "Already in your library"}), 409

    # Seed source genres into the DB so they appear as suggestions.
    for g in source_genres:
        db.resolve_genre(conn, genre_name=g)
    genre_id = db.resolve_genre(conn, genre_name=genre_name, genre_id=genre_id)

    cur = conn.execute(
        """INSERT INTO shows (tmdb_id, media_type, title, year, overview,
                              poster_url, imdb_url, genre_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tmdb_id,
            media_type,
            data.get("title", "Untitled"),
            data.get("year", ""),
            data.get("overview", ""),
            data.get("poster_url", ""),
            data.get("imdb_url", ""),
            genre_id,
        ),
    )
    conn.commit()
    show_id = cur.lastrowid
    row = conn.execute("SELECT * FROM shows WHERE id = ?", (show_id,)).fetchone()
    genre_row = (
        conn.execute("SELECT name FROM genres WHERE id = ?", (genre_id,)).fetchone()
        if genre_id
        else None
    )
    conn.close()
    return jsonify(
        {"show": dict(row), "genre_name": genre_row["name"] if genre_row else ""}
    )


@app.route("/api/shows/<int:show_id>/watched", methods=["PUT"])
def api_watched_show(show_id):
    data = request.get_json(force=True)
    watched = 1 if data.get("watched") else 0
    conn = db.get_db()
    if watched:
        conn.execute(
            "UPDATE shows SET watched = ?, watched_at = CURRENT_TIMESTAMP WHERE id = ?",
            (watched, show_id),
        )
    else:
        conn.execute(
            "UPDATE shows SET watched = ?, watched_at = NULL WHERE id = ?",
            (watched, show_id),
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/shows/<int:show_id>", methods=["DELETE"])
def api_delete_show(show_id):
    conn = db.get_db()
    row = conn.execute("SELECT genre_id FROM shows WHERE id = ?", (show_id,)).fetchone()
    genre_id = row["genre_id"] if row else None
    conn.execute("DELETE FROM shows WHERE id = ?", (show_id,))
    if genre_id:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM shows WHERE genre_id = ?", (genre_id,)
        ).fetchone()[0]
        if remaining == 0:
            conn.execute("DELETE FROM genres WHERE id = ?", (genre_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/shows/<int:show_id>/genre", methods=["PUT"])
def api_move_show(show_id):
    data = request.get_json(force=True)
    conn = db.get_db()
    row = conn.execute("SELECT genre_id FROM shows WHERE id = ?", (show_id,)).fetchone()
    old_genre_id = row["genre_id"] if row else None
    new_genre_id = db.resolve_genre(
        conn,
        genre_name=(data.get("genre_name") or "").strip(),
        genre_id=data.get("genre_id"),
    )
    conn.execute("UPDATE shows SET genre_id = ? WHERE id = ?", (new_genre_id, show_id))
    if old_genre_id and old_genre_id != new_genre_id:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM shows WHERE genre_id = ?", (old_genre_id,)
        ).fetchone()[0]
        if remaining == 0:
            conn.execute("DELETE FROM genres WHERE id = ?", (old_genre_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/shows/<int:show_id>/timestamp", methods=["PUT"])
def api_timestamp_show(show_id):
    data = request.get_json(force=True)
    try:
        seconds = youtube.parse_timestamp(data.get("timestamp"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    conn = db.get_db()
    row = conn.execute(
        "SELECT media_type FROM shows WHERE id = ?", (show_id,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    if row["media_type"] != "youtube":
        conn.close()
        return jsonify({"error": "Timestamps apply to YouTube videos only"}), 400

    conn.execute(
        "UPDATE shows SET youtube_timestamp = ? WHERE id = ?", (seconds, show_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "timestamp": seconds})


@app.route("/api/shows/<int:show_id>/tmdb-genres")
def api_show_tmdb_genres(show_id):
    conn = db.get_db()
    row = conn.execute(
        "SELECT tmdb_id, media_type FROM shows WHERE id = ?", (show_id,)
    ).fetchone()
    conn.close()
    if not row or not row["tmdb_id"]:
        return jsonify({"genres": []})
    if row["media_type"] == "youtube":
        genres = []
    elif row["media_type"] == "game":
        genres = igdb.fetch_genres(row["tmdb_id"])
    else:
        genres = tmdb.fetch_genres(row["media_type"], row["tmdb_id"])
    return jsonify({"genres": genres})


@app.route("/api/genres/<int:genre_id>", methods=["DELETE"])
def api_delete_genre(genre_id):
    conn = db.get_db()
    conn.execute("UPDATE shows SET genre_id = NULL WHERE genre_id = ?", (genre_id,))
    conn.execute("DELETE FROM genres WHERE id = ?", (genre_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# --- Bootstrap --------------------------------------------------------------
db.init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=1234, debug=True)
