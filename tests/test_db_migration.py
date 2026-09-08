import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import db


class FakeTMDBClient:
    @staticmethod
    def safe_error(exc):
        return str(exc)

    @staticmethod
    def find_legacy_match(**kwargs):
        if kwargs["title"] == "Unmatched":
            return None
        return {"tmdb_id": "1396", "media_type": "series"}

    @staticmethod
    def details(media_type, tmdb_id):
        return {
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "title": "Breaking Bad",
            "year": "2008",
            "overview": "A chemistry teacher changes careers.",
            "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
            "imdb_url": "https://www.imdb.com/title/tt0903747/",
            "genres": ["Drama", "Crime"],
        }


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "shows.db")
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE genres (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                sort_order INTEGER DEFAULT 0
            );
            INSERT INTO genres (name) VALUES ('Current genre');
            CREATE TABLE shows (
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
                watched_at TIMESTAMP
            );
            INSERT INTO shows (
                tvdb_id, tvdb_type, title, year, overview, poster_url,
                imdb_url, genre_id, watched, added_at, watched_at
            ) VALUES (
                '81189', 'series', 'Breaking Bad', '2008', 'Old overview',
                'old-poster', 'https://www.imdb.com/title/tt0903747/',
                1, 1, '2024-01-02 03:04:05', '2024-02-03 04:05:06'
            );
            INSERT INTO shows (tvdb_id, tvdb_type, title, year)
            VALUES ('999', 'series', 'Unmatched', '2020');
            """
        )
        conn.close()
        self.db_patch = patch.object(db, "DB_PATH", self.db_path)
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_schema_and_content_are_migrated_without_losing_user_state(self):
        db.init_db()
        report = db.migrate_legacy_content(FakeTMDBClient)

        self.assertEqual(report["checked"], 2)
        self.assertEqual(report["migrated"], 1)
        self.assertEqual(report["unmatched"], ["Unmatched"])

        conn = db.get_db()
        row = conn.execute("SELECT * FROM shows WHERE id = 1").fetchone()
        genres = {
            item["name"] for item in conn.execute("SELECT name FROM genres").fetchall()
        }
        conn.close()

        self.assertEqual(row["tvdb_id"], "81189")
        self.assertEqual(row["tmdb_id"], "1396")
        self.assertEqual(row["media_type"], "series")
        self.assertEqual(row["overview"], "A chemistry teacher changes careers.")
        self.assertEqual(row["genre_id"], 1)
        self.assertEqual(row["watched"], 1)
        self.assertEqual(row["added_at"], "2024-01-02 03:04:05")
        self.assertEqual(row["watched_at"], "2024-02-03 04:05:06")
        self.assertTrue({"Current genre", "Drama", "Crime"}.issubset(genres))


if __name__ == "__main__":
    unittest.main()
