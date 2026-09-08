import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as application


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "shows.db")
        self.db_patch = patch.object(application.db, "DB_PATH", self.db_path)
        self.db_patch.start()
        application.db.init_db()
        application.app.config.update(TESTING=True)
        self.auth_password = application.AUTH_PASSWORD
        application.AUTH_PASSWORD = ""
        self.client = application.app.test_client()

    def tearDown(self):
        application.AUTH_PASSWORD = self.auth_password
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @patch("app.tmdb.details")
    def test_add_uses_tmdb_metadata_and_identity(self, details):
        details.return_value = {
            "tmdb_id": "1396",
            "media_type": "series",
            "title": "Breaking Bad",
            "year": "2008",
            "overview": "Updated overview",
            "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
            "imdb_url": "https://www.imdb.com/title/tt0903747/",
            "genres": ["Drama", "Crime"],
        }

        response = self.client.post(
            "/api/shows",
            json={
                "tmdb_id": "1396",
                "media_type": "series",
                "title": "Untrusted client title",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["show"]["tmdb_id"], "1396")
        self.assertEqual(response.json["show"]["title"], "Breaking Bad")
        self.assertEqual(response.json["genre_name"], "Crime")

        index = self.client.get("/api/shows/in-library")
        self.assertEqual(
            index.json["shows"], [{"media_type": "series", "tmdb_id": "1396"}]
        )

    @patch("app.tmdb.details")
    def test_tmdb_identity_prevents_duplicates(self, details):
        details.return_value = {
            "tmdb_id": "278",
            "media_type": "movie",
            "title": "The Shawshank Redemption",
            "year": "1994",
            "overview": "",
            "poster_url": "",
            "imdb_url": "https://www.imdb.com/title/tt0111161/",
            "genres": ["Drama"],
        }
        payload = {"tmdb_id": "278", "media_type": "movie", "title": "Film"}

        self.assertEqual(self.client.post("/api/shows", json=payload).status_code, 200)
        self.assertEqual(self.client.post("/api/shows", json=payload).status_code, 409)

    def test_footer_contains_required_tmdb_attribution(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"This product uses the TMDB API", response.data)
        self.assertIn(b"The Movie Database (TMDB)", response.data)

    @patch("app.tmdb.details")
    def test_overflow_menu_links_to_tmdb_and_imdb(self, details):
        details.return_value = {
            "tmdb_id": "278",
            "media_type": "movie",
            "title": "The Shawshank Redemption",
            "year": "1994",
            "overview": "",
            "poster_url": "",
            "imdb_url": "https://www.imdb.com/title/tt0111161/",
            "genres": ["Drama"],
        }
        self.client.post(
            "/api/shows",
            json={"tmdb_id": "278", "media_type": "movie", "title": "Film"},
        )

        response = self.client.get("/")

        self.assertIn(b'href="https://www.themoviedb.org/movie/278"', response.data)
        self.assertIn(b'href="https://www.imdb.com/title/tt0111161/"', response.data)


if __name__ == "__main__":
    unittest.main()
