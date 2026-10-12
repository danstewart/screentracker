import os
import unittest
from unittest.mock import Mock, patch

from lib import youtube


class YouTubeVideoIdTests(unittest.TestCase):
    def test_accepts_a_bare_video_id(self):
        self.assertEqual(youtube.video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_accepts_the_common_url_shapes(self):
        cases = {
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/live/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/v/dQw4w9WgXcQ": "dQw4w9WgXcQ",
        }

        for value, expected in cases.items():
            self.assertEqual(youtube.video_id(value), expected, value)

    def test_ignores_query_strings_timestamps_and_fragments(self):
        cases = {
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s": "dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123": "dQw4w9WgXcQ",
            "https://www.youtube.com/watch?list=PL123&v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?t=1": "dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ#t=1": "dQw4w9WgXcQ",
        }

        for value, expected in cases.items():
            self.assertEqual(youtube.video_id(value), expected, value)

    def test_rejects_anything_else(self):
        cases = [
            "",
            None,
            "   ",
            "not a url",
            "https://vimeo.com/12345678",
            "https://www.youtube.com/playlist?list=PL123",
            "https://www.youtube.com/watch?v=tooshort",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQextra",
            "https://www.youtube.com/watch?v=",
        ]

        for value in cases:
            self.assertEqual(youtube.video_id(value), "", repr(value))


class YouTubeTimestampTests(unittest.TestCase):
    def test_parses_the_supported_forms_to_seconds(self):
        cases = {
            "90": 90,
            "1:23": 83,
            "1:02:03": 3723,
            "1h2m3s": 3723,
            "2m": 120,
            "45s": 45,
            "1h": 3600,
        }

        for value, expected in cases.items():
            self.assertEqual(youtube.parse_timestamp(value), expected, value)

    def test_empty_and_zero_clear_the_timestamp(self):
        for value in ("", "   ", None, "0"):
            self.assertIsNone(youtube.parse_timestamp(value), repr(value))

    def test_rejects_input_it_cannot_parse(self):
        for value in ("abc", "1:90", "1h90m", "1:2:3:4", "1.5", "-5"):
            with self.assertRaises(ValueError, msg=repr(value)):
                youtube.parse_timestamp(value)

    def test_formats_seconds_for_display(self):
        cases = {45: "0:45", 83: "1:23", 3723: "1:02:03"}

        for value, expected in cases.items():
            self.assertEqual(youtube.format_timestamp(value), expected, value)


class YouTubeDetailsTests(unittest.TestCase):
    def _response(self, payload):
        response = Mock()
        response.json.return_value = payload
        return response

    @patch("lib.youtube.requests.get")
    def test_details_normalizes_a_video(self, get):
        get.return_value = self._response(
            {
                "items": [
                    {
                        "id": "dQw4w9WgXcQ",
                        "snippet": {
                            "title": "Never Gonna Give You Up",
                            "description": "The official video",
                            "channelTitle": "Rick Astley",
                            "publishedAt": "2009-10-25T06:57:33Z",
                            "thumbnails": {
                                "default": {"url": "https://ex/default.jpg"},
                                "high": {"url": "https://ex/hqdefault.jpg"},
                                "maxres": {"url": "https://ex/maxresdefault.jpg"},
                            },
                        },
                    }
                ]
            }
        )

        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "key"}, clear=True):
            result = youtube.details(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            )

        self.assertEqual(result["tmdb_id"], "dQw4w9WgXcQ")
        self.assertEqual(result["media_type"], "youtube")
        self.assertEqual(result["title"], "Never Gonna Give You Up")
        self.assertEqual(result["year"], "2009")
        self.assertEqual(result["network"], "Rick Astley")
        self.assertEqual(result["overview"], "The official video")
        self.assertEqual(result["poster_url"], "https://ex/maxresdefault.jpg")
        self.assertEqual(result["genres"], [])
        self.assertEqual(result["imdb_url"], "")

        params = get.call_args.kwargs["params"]
        self.assertEqual(params["id"], "dQw4w9WgXcQ")
        self.assertEqual(params["key"], "key")

    @patch("lib.youtube.requests.get")
    def test_details_uses_the_largest_available_thumbnail(self, get):
        get.return_value = self._response(
            {
                "items": [
                    {
                        "id": "dQw4w9WgXcQ",
                        "snippet": {
                            "title": "T",
                            "thumbnails": {
                                "medium": {"url": "https://ex/mqdefault.jpg"}
                            },
                        },
                    }
                ]
            }
        )

        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "key"}, clear=True):
            result = youtube.details("dQw4w9WgXcQ")

        self.assertEqual(result["poster_url"], "https://ex/mqdefault.jpg")

    @patch("lib.youtube.requests.get")
    def test_details_falls_back_to_a_constructed_thumbnail(self, get):
        get.return_value = self._response(
            {"items": [{"id": "dQw4w9WgXcQ", "snippet": {"title": "T"}}]}
        )

        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "key"}, clear=True):
            result = youtube.details("dQw4w9WgXcQ")

        self.assertEqual(
            result["poster_url"], "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
        )
        self.assertEqual(result["year"], "")
        self.assertEqual(result["network"], "")

    @patch("lib.youtube.requests.get")
    def test_details_raises_when_the_video_is_missing(self, get):
        get.return_value = self._response({"items": []})

        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "key"}, clear=True):
            with self.assertRaises(LookupError):
                youtube.details("dQw4w9WgXcQ")

    def test_details_rejects_a_non_youtube_value(self):
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "key"}, clear=True):
            with self.assertRaises(ValueError):
                youtube.details("https://vimeo.com/12345678")

    @patch("lib.youtube.requests.get")
    def test_details_requires_an_api_key_before_calling_the_api(self, get):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                youtube.details("dQw4w9WgXcQ")

        get.assert_not_called()

    def test_error_message_redacts_the_api_key(self):
        error = RuntimeError(
            "failed: https://www.googleapis.com/youtube/v3/videos"
            "?part=snippet&id=x&key=s3cr3t"
        )

        self.assertNotIn("s3cr3t", youtube.safe_error(error))
        self.assertIn("key=[redacted]", youtube.safe_error(error))

    def test_is_configured_needs_a_key(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(youtube.is_configured())
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "key"}, clear=True):
            self.assertTrue(youtube.is_configured())


if __name__ == "__main__":
    unittest.main()
