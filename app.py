"""TV Show & Movie Manager - Flask app"""

import os
import secrets

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from lib import db, tvdb

load_dotenv()

app = Flask(__name__)

AUTH_USER = os.environ.get("AUTH_USER", "admin")
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "")


@app.before_request
def check_auth():
    if not AUTH_PASSWORD:
        return
    auth = request.authorization
    if not auth or not (
        secrets.compare_digest(auth.username, AUTH_USER)
        and secrets.compare_digest(auth.password, AUTH_PASSWORD)
    ):
        return (
            "Unauthorised",
            401,
            {"WWW-Authenticate": 'Basic realm="ScreenTracker"'},
        )


# --- Routes -----------------------------------------------------------------
def _group_shows(conn, watched):
    flag = 1 if watched else 0
    genres = conn.execute("SELECT * FROM genres ORDER BY sort_order, name").fetchall()
    grouped = []
    for g in genres:
        shows = conn.execute(
            "SELECT * FROM shows WHERE genre_id = ? AND watched = ? ORDER BY title",
            (g["id"], flag),
        ).fetchall()
        if shows:
            grouped.append({"genre": g, "shows": shows})
    orphans = conn.execute(
        "SELECT * FROM shows WHERE genre_id IS NULL AND watched = ? ORDER BY title",
        (flag,),
    ).fetchall()
    return grouped, orphans


@app.route("/")
def index():
    conn = db.get_db()
    watching_grouped, watching_orphans = _group_shows(conn, watched=False)
    watched_grouped, watched_orphans = _group_shows(conn, watched=True)
    conn.close()
    return render_template(
        "index.html",
        watching_grouped=watching_grouped,
        watching_orphans=watching_orphans,
        watched_grouped=watched_grouped,
        watched_orphans=watched_orphans,
        tvdb_configured=bool(tvdb.TVDB_API_KEY),
    )


@app.route("/api/search")
def api_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"results": []})

    if not tvdb.TVDB_API_KEY:
        return jsonify(
            {
                "error": "TVDB API key not configured. Set TVDB_API_KEY environment variable."
            }
        ), 500

    try:
        return jsonify({"results": tvdb.search(query)})
    except requests.HTTPError as e:
        return jsonify({"error": f"TVDB error: {e.response.status_code}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
        "SELECT tvdb_id, tvdb_type FROM shows WHERE tvdb_id != ''"
    ).fetchall()
    conn.close()
    return jsonify({"shows": [dict(r) for r in rows]})


@app.route("/api/shows", methods=["POST"])
def api_add_show():
    data = request.get_json(force=True)
    genre_name = (data.get("genre_name") or "").strip()
    genre_id = data.get("genre_id")

    tvdb_genres = []
    if not genre_name and not genre_id:
        tvdb_genres = tvdb.fetch_genres(
            data.get("tvdb_type", "series"), data.get("tvdb_id", "")
        )
        if tvdb_genres:
            # The last genre seems to be the most specific/accurate
            genre_name = tvdb_genres[-1]

    conn = db.get_db()
    tvdb_id = data.get("tvdb_id", "")
    if tvdb_id:
        dup = conn.execute(
            "SELECT id FROM shows WHERE tvdb_id = ? AND tvdb_type = ?",
            (tvdb_id, data.get("tvdb_type", "")),
        ).fetchone()
    else:
        dup = conn.execute(
            "SELECT id FROM shows WHERE LOWER(title) = LOWER(?)",
            (data.get("title", ""),),
        ).fetchone()
    if dup:
        conn.close()
        return jsonify({"error": "Already in your library"}), 409

    # Seed all TVDB genres into the DB so they appear as suggestions
    for g in tvdb_genres:
        db.resolve_genre(conn, genre_name=g)
    genre_id = db.resolve_genre(conn, genre_name=genre_name, genre_id=genre_id)

    cur = conn.execute(
        """INSERT INTO shows (tvdb_id, tvdb_type, title, year, overview,
                              poster_url, imdb_url, genre_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data.get("tvdb_id", ""),
            data.get("tvdb_type", ""),
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
    conn.execute("UPDATE shows SET watched = ? WHERE id = ?", (watched, show_id))
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


@app.route("/api/shows/<int:show_id>/tvdb-genres")
def api_show_tvdb_genres(show_id):
    conn = db.get_db()
    row = conn.execute(
        "SELECT tvdb_id, tvdb_type FROM shows WHERE id = ?", (show_id,)
    ).fetchone()
    conn.close()
    if not row or not row["tvdb_id"]:
        return jsonify({"genres": []})
    genres = tvdb.fetch_genres(row["tvdb_type"], row["tvdb_id"])
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
