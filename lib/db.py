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
            tvdb_id TEXT,
            tvdb_type TEXT,
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
    # Migration for existing databases
    try:
        conn.execute("ALTER TABLE shows ADD COLUMN watched INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


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
