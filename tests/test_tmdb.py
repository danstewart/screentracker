import os
import unittest
from unittest.mock import Mock, patch

from lib import tmdb


class TMDBClientTests(unittest.TestCase):
    @patch("lib.tmdb.requests.get")
    def test_api_token_is_sent_as_bearer_header(self, get):
        response = Mock()
        response.json.return_value = {"results": []}
        get.return_value = response

        with patch.dict(os.environ, {"TMDB_API_TOKEN": "token"}, clear=True):
            tmdb.tmdb_get("/search/multi", {"query": "Alien"})

        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer token")
        self.assertNotIn("api_key", get.call_args.kwargs["params"])

    @patch("lib.tmdb.tmdb_get")
    def test_search_filters_people_and_normalizes_movies_and_series(self, get):
        get.return_value = {
            "results": [
                {"id": 1, "media_type": "person", "name": "Someone"},
                {
                    "id": 2,
                    "media_type": "movie",
                    "title": "A Film",
                    "release_date": "2026-04-02",
                    "poster_path": "/film.jpg",
                    "overview": "Film overview",
                },
                {
                    "id": 3,
                    "media_type": "tv",
                    "name": "A Series",
                    "first_air_date": "2025-09-01",
                    "origin_country": ["GB"],
                },
            ]
        }

        results = tmdb.search("A")

        self.assertEqual([item["tmdb_id"] for item in results], ["2", "3"])
        self.assertEqual(results[0]["media_type"], "movie")
        self.assertEqual(results[0]["year"], "2026")
        self.assertEqual(results[0]["poster_url"], f"{tmdb.TMDB_IMAGE_BASE}/film.jpg")
        self.assertEqual(results[1]["media_type"], "series")
        self.assertEqual(results[1]["country"], "GB")

    @patch("lib.tmdb.tmdb_get")
    def test_details_includes_genres_network_and_imdb_url(self, get):
        get.return_value = {
            "id": 1396,
            "name": "Breaking Bad",
            "first_air_date": "2008-01-20",
            "genres": [{"name": "Drama"}, {"name": "Crime"}],
            "networks": [{"name": "AMC"}],
            "origin_country": ["US"],
            "external_ids": {"imdb_id": "tt0903747"},
        }

        result = tmdb.details("series", "1396")

        self.assertEqual(result["genres"], ["Drama", "Crime"])
        self.assertEqual(result["network"], "AMC")
        self.assertEqual(result["imdb_url"], "https://www.imdb.com/title/tt0903747/")

    @patch("lib.tmdb.tmdb_get")
    def test_legacy_series_prefers_direct_tvdb_lookup(self, get):
        get.return_value = {
            "tv_results": [
                {"id": 1396, "name": "Breaking Bad", "first_air_date": "2008-01-20"}
            ]
        }

        result = tmdb.find_legacy_match("81189", "series", "Breaking Bad", "2008")

        self.assertEqual(result, {"tmdb_id": "1396", "media_type": "series"})
        self.assertEqual(get.call_args.args[0], "/find/81189")
        self.assertEqual(get.call_args.kwargs["params"]["external_source"], "tvdb_id")

    @patch("lib.tmdb.tmdb_get")
    def test_manual_imdb_link_can_determine_movie_type(self, get):
        get.return_value = {"movie_results": [{"id": 278, "title": "The Shawshank Redemption"}]}

        result = tmdb.find_legacy_match(
            "", "", "The Shawshank Redemption", imdb_url="https://www.imdb.com/title/tt0111161/"
        )

        self.assertEqual(result, {"tmdb_id": "278", "media_type": "movie"})

    @patch("lib.tmdb.tmdb_get")
    def test_title_fallback_rejects_inexact_match(self, get):
        get.return_value = {
            "results": [{"id": 10, "title": "A Different Film", "release_date": "2020-01-01"}]
        }

        result = tmdb.find_legacy_match("123", "movie", "Expected Film", "2020")

        self.assertIsNone(result)

    def test_error_message_redacts_v3_api_key(self):
        error = RuntimeError(
            "request failed: https://api.themoviedb.org/3/movie/1?api_key=secret&language=en"
        )

        self.assertNotIn("secret", tmdb.safe_error(error))
        self.assertIn("api_key=[redacted]", tmdb.safe_error(error))


if __name__ == "__main__":
    unittest.main()
