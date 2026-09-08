"""TV Show & Movie Manager - Flask app"""

import os
import secrets
from datetime import datetime

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

load_dotenv()

from lib import db, tmdb

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"

AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "")


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
        tmdb_configured=tmdb.is_configured(),
    )


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

    try:
        return jsonify({"results": tmdb.search(query)})
    except requests.HTTPError as e:
        return jsonify({"error": f"TMDB error: {e.response.status_code}"}), 502
    except Exception as e:
        return jsonify({"error": tmdb.safe_error(e)}), 500


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
    tmdb_genres = []
    if tmdb_id:
        if media_type not in ("movie", "series"):
            return jsonify({"error": "Invalid media type"}), 400
        try:
            metadata = tmdb.details(media_type, tmdb_id)
        except requests.HTTPError as exc:
            return jsonify({"error": f"TMDB error: {exc.response.status_code}"}), 502
        except Exception as exc:
            return jsonify({"error": tmdb.safe_error(exc)}), 500
        data.update(metadata)
        tmdb_genres = metadata.get("genres") or []

    if not genre_name and not genre_id and tmdb_genres:
        # Prefer the final (usually most specific) TMDB genre.
        genre_name = tmdb_genres[-1]

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

    # Seed TMDB genres into the DB so they appear as suggestions.
    for g in tmdb_genres:
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


@app.route("/api/shows/<int:show_id>/tmdb-genres")
def api_show_tmdb_genres(show_id):
    conn = db.get_db()
    row = conn.execute(
        "SELECT tmdb_id, media_type FROM shows WHERE id = ?", (show_id,)
    ).fetchone()
    conn.close()
    if not row or not row["tmdb_id"]:
        return jsonify({"genres": []})
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
if tmdb.is_configured():
    migration = db.migrate_legacy_content(tmdb)
    if migration["checked"]:
        print(
            "TMDB migration: "
            f"{migration['migrated']}/{migration['checked']} migrated, "
            f"{len(migration['unmatched'])} unmatched, "
            f"{len(migration['errors'])} errors"
        )
        for title in migration["unmatched"]:
            print(f"TMDB migration unmatched: {title}")
        for error in migration["errors"]:
            print(f"TMDB migration error: {error}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=1234, debug=True)
