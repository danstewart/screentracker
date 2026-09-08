"""Database access and schema management."""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "db", "shows.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS genres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            sort_order INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_id TEXT,
            media_type TEXT,
            title TEXT NOT NULL,
            year TEXT,
            overview TEXT,
            poster_url TEXT,
            imdb_url TEXT,
            genre_id INTEGER,
            watched INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (genre_id) REFERENCES genres(id) ON DELETE SET NULL
        )
    """)
    # Migrations for existing databases
    try:
        conn.execute("ALTER TABLE shows ADD COLUMN watched INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE shows ADD COLUMN watched_at TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    columns = {row[1] for row in conn.execute("PRAGMA table_info(shows)")}
    if "tmdb_id" not in columns:
        conn.execute("ALTER TABLE shows ADD COLUMN tmdb_id TEXT")
    if "media_type" not in columns:
        conn.execute("ALTER TABLE shows ADD COLUMN media_type TEXT")
    if "tvdb_type" in columns:
        conn.execute(
            """UPDATE shows
               SET media_type = tvdb_type
               WHERE (media_type IS NULL OR media_type = '')
                 AND tvdb_type IS NOT NULL"""
        )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS shows_tmdb_identity
           ON shows (tmdb_id, media_type)
           WHERE tmdb_id IS NOT NULL AND tmdb_id != ''"""
    )
    conn.commit()
    conn.close()


def migrate_legacy_content(tmdb_client):
    """Replace legacy TVDB identities and metadata with their TMDB equivalents.

    Existing user state (genre, watched state, and timestamps) is deliberately
    untouched. Rows without a confident match remain available and will be
    retried on the next startup.
    """
    conn = get_db()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(shows)")}
    report = {"checked": 0, "migrated": 0, "unmatched": [], "errors": []}
    if not {"tvdb_id", "tvdb_type"}.issubset(columns):
        conn.close()
        return report

    rows = conn.execute(
        """SELECT id, tvdb_id, tvdb_type, title, year, imdb_url
           FROM shows
           WHERE (tmdb_id IS NULL OR tmdb_id = '')
             AND (
                 (tvdb_id IS NOT NULL AND tvdb_id != '')
                 OR imdb_url LIKE '%imdb.com/title/tt%'
             )
           ORDER BY id"""
    ).fetchall()
    report["checked"] = len(rows)

    for row in rows:
        try:
            match = tmdb_client.find_legacy_match(
                tvdb_id=row["tvdb_id"],
                media_type=row["tvdb_type"],
                title=row["title"],
                year=row["year"],
                imdb_url=row["imdb_url"],
            )
            if not match:
                report["unmatched"].append(row["title"])
                continue

            duplicate = conn.execute(
                """SELECT id FROM shows
                   WHERE tmdb_id = ? AND media_type = ? AND id != ?""",
                (match["tmdb_id"], match["media_type"], row["id"]),
            ).fetchone()
            if duplicate:
                report["errors"].append(
                    f"{row['title']}: matches existing library row {duplicate['id']}"
                )
                continue

            metadata = tmdb_client.details(match["media_type"], match["tmdb_id"])
            conn.execute(
                """UPDATE shows
                   SET tmdb_id = ?, media_type = ?, title = ?, year = ?,
                       overview = CASE WHEN ? != '' THEN ? ELSE overview END,
                       poster_url = CASE WHEN ? != '' THEN ? ELSE poster_url END,
                       imdb_url = CASE WHEN ? != '' THEN ? ELSE imdb_url END
                   WHERE id = ?""",
                (
                    metadata["tmdb_id"],
                    metadata["media_type"],
                    metadata["title"],
                    metadata["year"] or row["year"],
                    metadata["overview"],
                    metadata["overview"],
                    metadata["poster_url"],
                    metadata["poster_url"],
                    metadata["imdb_url"],
                    metadata["imdb_url"],
                    row["id"],
                ),
            )
            for genre in metadata.get("genres") or []:
                resolve_genre(conn, genre_name=genre)
            conn.commit()
            report["migrated"] += 1
        except Exception as exc:
            conn.rollback()
            report["errors"].append(
                f"{row['title']}: {tmdb_client.safe_error(exc)}"
            )

    conn.close()
    return report


def resolve_genre(conn, genre_name=None, genre_id=None):
    """Return a genre_id for the given name or id, creating the genre if needed."""
    if genre_id:
        return genre_id
    if not genre_name:
        return None
    try:
        cur = conn.execute("INSERT INTO genres (name) VALUES (?)", (genre_name,))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT id FROM genres WHERE name = ?", (genre_name,)).fetchone()
        return row["id"] if row else None
