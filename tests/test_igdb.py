import os
import unittest
from unittest.mock import Mock, patch

from lib import igdb


class IGDBClientTests(unittest.TestCase):
    def setUp(self):
        igdb._token["value"] = ""
        igdb._token["expires_at"] = 0.0

    @patch("lib.igdb.requests.post")
    def test_access_token_is_requested_once_and_cached(self, post):
        response = Mock()
        response.json.return_value = {
            "access_token": "app-token",
            "expires_in": 5184000,
        }
        post.return_value = response

        with patch.dict(
            os.environ,
            {"IGDB_CLIENT_ID": "cid", "IGDB_CLIENT_SECRET": "csecret"},
            clear=True,
        ):
            self.assertEqual(igdb.access_token(), "app-token")
            self.assertEqual(igdb.access_token(), "app-token")

        self.assertEqual(post.call_count, 1)
        # The secret is posted as a form body, never as a query parameter.
        self.assertNotIn("params", post.call_args.kwargs)
        self.assertEqual(post.call_args.kwargs["data"]["client_secret"], "csecret")
        self.assertIn("timeout", post.call_args.kwargs)

    @patch("lib.igdb.requests.post")
    def test_igdb_post_sends_client_id_and_bearer_token(self, post):
        response = Mock()
        response.json.return_value = []
        post.return_value = response

        with patch.dict(
            os.environ,
            {"IGDB_CLIENT_ID": "cid", "IGDB_CLIENT_SECRET": "csecret"},
            clear=True,
        ):
            igdb._token["value"] = "app-token"
            igdb._token["expires_at"] = float("inf")
            igdb.igdb_post("/games", "fields name; limit 1;")

        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Client-ID"], "cid")
        self.assertEqual(headers["Authorization"], "Bearer app-token")
        self.assertEqual(post.call_args.kwargs["data"], "fields name; limit 1;")

    @patch("lib.igdb.igdb_post")
    def test_search_normalizes_and_filters_server_side(self, post):
        post.return_value = [
            {
                "id": 740,
                "name": "Halo: Combat Evolved",
                "summary": "Sci-fi shooter",
                "first_release_date": 1001376000,
                "cover": {"image_id": "co1q3y"},
                "genres": [{"name": "Shooter"}],
                "involved_companies": [
                    {"developer": False, "publisher": True,
                     "company": {"name": "Microsoft"}},
                    {"developer": True, "publisher": False,
                     "company": {"name": "Bungie"}},
                ],
            }
        ]

        results = igdb.search("Halo")

        self.assertEqual([item["tmdb_id"] for item in results], ["740"])
        result = results[0]
        self.assertEqual(result["media_type"], "game")
        self.assertEqual(result["year"], "2001")
        self.assertEqual(result["overview"], "Sci-fi shooter")
        self.assertEqual(result["network"], "Bungie")
        self.assertEqual(result["status"], "Released")
        self.assertEqual(result["genres"], ["Shooter"])
        self.assertEqual(
            result["poster_url"], f"{igdb.IGDB_IMAGE_BASE}/co1q3y.jpg"
        )

    @patch("lib.igdb.igdb_post")
    def test_search_excludes_dlc_and_editions_in_the_query(self, post):
        post.return_value = []

        igdb.search("Halo")

        query = post.call_args.args[1]
        # IGDB removed `category`/`status`; `game_type` is the live field.
        self.assertNotIn("category", query)
        self.assertIn("game_type = (0,4,8,9,10,11,12)", query)
        self.assertIn("version_parent = null", query)

    @patch("lib.igdb.igdb_post")
    def test_upcoming_games_get_an_upcoming_status(self, post):
        post.return_value = [
            {"id": 1, "name": "Future Game", "first_release_date": 4102444800}
        ]

        self.assertEqual(igdb.search("future")[0]["status"], "Upcoming")

    @patch("lib.igdb.igdb_post")
    def test_undated_games_get_no_status(self, post):
        post.return_value = [{"id": 1, "name": "Undated"}]

        self.assertEqual(igdb.search("undated")[0]["status"], "")

    @patch("lib.igdb.igdb_post")
    def test_search_escapes_quotes_and_collapses_whitespace(self, post):
        post.return_value = []

        igdb.search('  Halo "2"\n')

        self.assertEqual(post.call_args.args[1], 'fields ' + igdb._FIELDS +
                         '; search "Halo \\"2\\""; where ' +
                         igdb._GAME_TYPE_FILTER + '; limit 12;')

    @patch("lib.igdb.igdb_post")
    def test_details_rejects_non_numeric_ids(self, post):
        with self.assertRaises(ValueError):
            igdb.details("series-1")

        post.assert_not_called()

    @patch("lib.igdb.igdb_post")
    def test_details_raises_when_no_game_matches(self, post):
        post.return_value = []

        with self.assertRaises(LookupError):
            igdb.details("1020")

    def test_error_message_redacts_client_secret(self):
        error = RuntimeError(
            "failed: https://id.twitch.tv/oauth2/token"
            "?client_id=cid&client_secret=s3cr3t&grant_type=client_credentials"
        )

        self.assertNotIn("s3cr3t", igdb.safe_error(error))
        self.assertIn("client_secret=[redacted]", igdb.safe_error(error))

    def test_is_configured_requires_both_credentials(self):
        with patch.dict(os.environ, {"IGDB_CLIENT_ID": "cid"}, clear=True):
            self.assertFalse(igdb.is_configured())
        with patch.dict(
            os.environ,
            {"IGDB_CLIENT_ID": "cid", "IGDB_CLIENT_SECRET": "csecret"},
            clear=True,
        ):
            self.assertTrue(igdb.is_configured())


if __name__ == "__main__":
    unittest.main()
