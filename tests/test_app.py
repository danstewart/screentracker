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

    def test_filter_chips_are_inactive_by_default(self):
        response = self.client.get("/")

        self.assertIn(b'class="filter-chip">', response.data)
        self.assertNotIn(b'class="filter-chip active">', response.data)
        self.assertNotIn(b'class="type-filter" value="series" checked', response.data)
        self.assertNotIn(b'class="type-filter" value="movie" checked', response.data)
        self.assertNotIn(b'id="year-filter"', response.data)
        self.assertIn(b'filter-group filter-group--title', response.data)

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
        self.assertIn(b'class="genre-toggle"', response.data)
        self.assertIn(b'aria-expanded="true"', response.data)

    def test_footer_contains_required_igdb_attribution(self):
        response = self.client.get("/")

        self.assertIn(b"Powered by", response.data)
        self.assertIn(b"https://www.igdb.com/", response.data)

    @patch("app.igdb.search")
    @patch("app.tmdb.search")
    @patch("app.igdb.is_configured", return_value=True)
    @patch("app.tmdb.is_configured", return_value=True)
    def test_search_merges_tmdb_and_igdb_results(
        self, _tmdb_configured, _igdb_configured, tmdb_search, igdb_search
    ):
        tmdb_search.return_value = [
            {"tmdb_id": "278", "media_type": "movie", "title": "A Film"}
        ]
        igdb_search.return_value = [
            {"tmdb_id": "1020", "media_type": "game", "title": "A Game"}
        ]

        response = self.client.get("/api/search?q=halo")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["title"] for item in response.json["results"]],
            ["A Film", "A Game"],
        )
        self.assertNotIn("errors", response.json)

    @patch("app.igdb.search")
    @patch("app.tmdb.search")
    @patch("app.igdb.is_configured", return_value=False)
    @patch("app.tmdb.is_configured", return_value=True)
    def test_search_skips_igdb_when_unconfigured(
        self, _tmdb_configured, _igdb_configured, tmdb_search, igdb_search
    ):
        tmdb_search.return_value = [
            {"tmdb_id": "278", "media_type": "movie", "title": "A Film"}
        ]

        response = self.client.get("/api/search?q=halo")

        titles = [item["title"] for item in response.json["results"]]
        self.assertEqual(titles, ["A Film"])
        igdb_search.assert_not_called()

    @patch("app.igdb.search", side_effect=RuntimeError("client_secret=leaked"))
    @patch("app.tmdb.search")
    @patch("app.igdb.is_configured", return_value=True)
    @patch("app.tmdb.is_configured", return_value=True)
    def test_search_survives_a_broken_game_source(
        self, _tmdb_configured, _igdb_configured, tmdb_search, _igdb_search
    ):
        tmdb_search.return_value = [
            {"tmdb_id": "278", "media_type": "movie", "title": "A Film"}
        ]

        response = self.client.get("/api/search?q=halo")

        self.assertEqual(response.status_code, 200)
        titles = [item["title"] for item in response.json["results"]]
        self.assertEqual(titles, ["A Film"])
        self.assertNotIn("leaked", response.json["errors"][0])

    @patch("app.igdb.details")
    def test_add_game_uses_igdb_metadata_and_identity(self, details):
        details.return_value = {
            "tmdb_id": "1020",
            "media_type": "game",
            "title": "Halo: Combat Evolved",
            "year": "2001",
            "overview": "Sci-fi shooter",
            "poster_url": (
                "https://images.igdb.com/igdb/image/upload/t_cover_big/co1q3y.jpg"
            ),
            "imdb_url": "",
            "genres": ["Role-playing (RPG)", "Simulator", "Indie"],
        }

        response = self.client.post(
            "/api/shows",
            json={"tmdb_id": "1020", "media_type": "game", "title": "Untrusted"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["show"]["media_type"], "game")
        self.assertEqual(response.json["show"]["title"], "Halo: Combat Evolved")
        # IGDB returns genres in id order, so the first is the most defining.
        self.assertEqual(response.json["genre_name"], "Role-playing (RPG)")

        index = self.client.get("/api/shows/in-library")
        self.assertEqual(
            index.json["shows"], [{"media_type": "game", "tmdb_id": "1020"}]
        )

        # A game has no TMDB page, so the overflow menu must not link to one.
        page = self.client.get("/")
        self.assertNotIn(b"https://www.themoviedb.org/tv/1020", page.data)
        self.assertIn(b"data-type=\"game\"", page.data)

    def test_add_rejects_unknown_media_type(self):
        response = self.client.post(
            "/api/shows",
            json={"tmdb_id": "1", "media_type": "book", "title": "A Book"},
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
