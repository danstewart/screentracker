import os
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

    @staticmethod
    def _youtube_metadata(title="A Video Title"):
        return {
            "tmdb_id": "dQw4w9WgXcQ",
            "media_type": "youtube",
            "title": title,
            "year": "2009",
            "overview": "A description",
            "poster_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
            "imdb_url": "",
            "network": "A Channel",
            "country": "",
            "status": "",
            "genres": [],
        }

    @staticmethod
    def _sections(html):
        """Split a rendered library page into (opening_tag, block_html) pairs."""
        sections = []
        for block in html.split('<section class="genre-block')[1:]:
            opening, _, rest = block.partition(">")
            body, _, _ = rest.partition("</section>")
            sections.append((opening, body))
        return sections

    @patch("app.youtube.details")
    def test_add_youtube_video_uses_the_api_and_gets_no_genre(self, details):
        details.return_value = self._youtube_metadata()

        response = self.client.post(
            "/api/shows",
            json={
                "media_type": "youtube",
                "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["show"]["media_type"], "youtube")
        self.assertEqual(response.json["show"]["title"], "A Video Title")
        self.assertEqual(response.json["genre_name"], "")

        # The client sends a URL; the id is extracted server-side.
        details.assert_called_once_with("dQw4w9WgXcQ")

        conn = application.db.get_db()
        row = conn.execute(
            "SELECT genre_id FROM shows WHERE media_type = 'youtube'"
        ).fetchone()
        conn.close()
        self.assertIsNone(row["genre_id"])

        # No genre was invented for the video.
        self.assertEqual(self.client.get("/api/genres").json["genres"], [])

    @patch("app.youtube.details")
    def test_youtube_video_renders_in_its_own_section(self, details):
        details.return_value = self._youtube_metadata()
        self.client.post(
            "/api/shows",
            json={"media_type": "youtube", "youtube_url": "dQw4w9WgXcQ"},
        )

        page = self.client.get("/").data.decode()
        sections = self._sections(page)

        youtube = [body for opening, body in sections if "youtube-block" in opening]
        self.assertEqual(len(youtube), 1, "expected one YouTube section")
        self.assertIn("A Video Title", youtube[0])
        self.assertIn(
            'href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"', youtube[0]
        )
        # YouTube is not a genre, so there is nothing to re-categorise.
        self.assertNotIn("Edit genre", youtube[0])
        # The media type keeps its own capitalisation.
        self.assertIn("· YouTube", youtube[0])

        # It must not be folded into the uncategorised bucket either.
        for opening, body in sections:
            if "orphan-block" in opening:
                self.assertNotIn("A Video Title", body)

    @patch("app.youtube.details")
    def test_videos_are_listed_separately_from_genre_blocks(self, details):
        details.return_value = self._youtube_metadata()
        self.client.post(
            "/api/shows",
            json={"media_type": "youtube", "youtube_url": "dQw4w9WgXcQ"},
        )
        # A plain manually added title with a genre, to compare against.
        self.client.post(
            "/api/shows", json={"title": "The Wire", "genre_name": "Drama"}
        )

        sections = self._sections(self.client.get("/").data.decode())
        labels = [opening for opening, _ in sections]

        self.assertTrue(any("data-genre-id" in label for label in labels))
        self.assertTrue(any("youtube-block" in label for label in labels))
        self.assertFalse(any("orphan-block" in label for label in labels))

    @patch("app.youtube.details")
    def test_youtube_genre_suggestions_are_empty(self, details):
        details.return_value = self._youtube_metadata()
        added = self.client.post(
            "/api/shows",
            json={"media_type": "youtube", "youtube_url": "dQw4w9WgXcQ"},
        )
        show_id = added.json["show"]["id"]

        response = self.client.get(f"/api/shows/{show_id}/tmdb-genres")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["genres"], [])

    @patch.dict(os.environ, {"YOUTUBE_API_KEY": "key"})
    def test_youtube_config_hint_is_hidden_when_configured(self):
        page = self.client.get("/").data.decode()

        self.assertNotIn("YouTube is not configured", page)

    def test_youtube_config_hint_is_shown_when_unconfigured(self):
        with patch.dict(os.environ, {}, clear=True):
            page = self.client.get("/").data.decode()

        self.assertIn("YouTube is not configured", page)

    @patch("app.youtube.details")
    def test_duplicate_youtube_video_is_rejected(self, details):
        details.return_value = self._youtube_metadata()
        payload = {"media_type": "youtube", "youtube_url": "dQw4w9WgXcQ"}

        first = self.client.post("/api/shows", json=payload)
        second = self.client.post("/api/shows", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)

    def test_add_youtube_rejects_a_non_youtube_url(self):
        response = self.client.post(
            "/api/shows",
            json={
                "media_type": "youtube",
                "youtube_url": "https://vimeo.com/12345678",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("YouTube", response.json["error"])


if __name__ == "__main__":
    unittest.main()
