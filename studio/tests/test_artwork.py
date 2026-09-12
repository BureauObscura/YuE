"""Network-isolated artwork tests. These never submit a paid generation."""

import io
import json
import threading
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from studio.server import artwork


KEY = "unit-test-key-never-real"
POLL = "https://api.eu.bfl.ai/v1/get_result?id=test-job"
SAMPLE = "https://delivery.eu1.bfl.ai/results/test.png?signature=private-value"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + b"\0" * 17


def response(value, headers=None):
    blob = json.dumps(value).encode() if isinstance(value, (dict, list)) else value
    result = MagicMock()
    result.headers = headers or {}
    result.read1.side_effect = io.BytesIO(blob).read1
    result.__enter__.return_value = result
    return result


class ArtworkTests(unittest.TestCase):
    def setUp(self):
        # Every test replaces the opener at the network boundary.
        self.opener_patch = patch.object(artwork.urllib.request, "build_opener")
        self.opener = self.opener_patch.start().return_value
        self.addCleanup(self.opener_patch.stop)

    def ready(self, sample=SAMPLE, image=PNG):
        self.opener.open.side_effect = [
            response({"id": "test-job", "polling_url": POLL}),
            response({"status": "Ready", "result": {"sample": sample}}),
            response(image),
        ]

    def test_generation_uses_returned_polling_url_and_downloads_without_key(self):
        self.ready()
        data, mime, metadata = artwork.generate_artwork("  An empty railway platform  ", KEY)
        self.assertEqual((data, mime), (PNG, "image/png"))
        requests = [call.args[0] for call in self.opener.open.call_args_list]
        self.assertEqual([r.full_url for r in requests], [artwork.API_URL, POLL, SAMPLE])
        self.assertEqual([r.get_method() for r in requests], ["POST", "GET", "GET"])
        self.assertEqual(requests[0].get_header("X-key"), KEY)
        self.assertEqual(requests[1].get_header("X-key"), KEY)
        self.assertIsNone(requests[2].get_header("X-key"))
        self.assertEqual(json.loads(requests[0].data), {"prompt": "An empty railway platform", "width": 1024, "height": 1024, "output_format": "png", "disable_pup": True})
        serialized = json.dumps(metadata)
        self.assertNotIn(KEY, serialized)
        self.assertNotIn("https", serialized)
        self.assertNotIn("private-value", serialized)
        self.assertEqual(metadata["model"], "flux-2-pro")
        self.assertEqual(metadata["request_id"], "test-job")

    def test_pending_polls_again_without_resubmitting(self):
        self.opener.open.side_effect = [
            response({"id": "test-job", "polling_url": POLL}),
            response({"status": "Pending"}),
            response({"status": "Ready", "result": {"sample": SAMPLE}}),
            response(PNG),
        ]
        with patch.object(artwork, "POLL_INTERVAL_SECONDS", 0):
            artwork.generate_artwork("Cover", KEY)
        methods = [call.args[0].get_method() for call in self.opener.open.call_args_list]
        self.assertEqual(methods, ["POST", "GET", "GET", "GET"])

    def test_submission_errors_are_safe_and_never_retried(self):
        for code, expected in ((401, "key"), (402, "credit"), (429, "limiting"), (500, "dashboard")):
            with self.subTest(code=code):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = urllib.error.HTTPError(artwork.API_URL, code, KEY, {}, io.BytesIO(KEY.encode()))
                with self.assertRaises(artwork.ArtworkError) as caught:
                    artwork.generate_artwork("Cover", KEY)
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn(KEY, str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)
                self.assertEqual(self.opener.open.call_count, 1)

    def test_network_failure_does_not_repeat_paid_submission(self):
        self.opener.open.side_effect = urllib.error.URLError(KEY + SAMPLE)
        with self.assertRaises(artwork.ArtworkError) as caught:
            artwork.generate_artwork("Cover", KEY)
        self.assertNotIn(KEY, str(caught.exception))
        self.assertNotIn(SAMPLE, str(caught.exception))
        self.assertEqual(self.opener.open.call_count, 1)

    def test_untrusted_polling_never_receives_key(self):
        for url in ("https://evil.example/v1/get_result", "https://api.bfl.ai.evil.example/v1/get_result", "http://api.bfl.ai/v1/get_result", "https://localhost/v1/get_result", "https://api.bfl.ai:8080/v1/get_result", "https://x@api.bfl.ai/v1/get_result", "https://api.bfl.ai/anything", "https://127.0.0.1/v1/get_result"):
            with self.subTest(url=url):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = [response({"id": "test-job", "polling_url": url})]
                with self.assertRaisesRegex(artwork.ArtworkError, "untrusted"):
                    artwork.generate_artwork("Cover", KEY)
                self.assertEqual(self.opener.open.call_count, 1)

    def test_untrusted_download_never_fetches_url(self):
        for url in ("https://evil.example/image.png", "https://127.0.0.1/a", "https://delivery.eu.bfl.ai.evil.example/a", "file:///tmp/image.png", "https://delivery.eu.bfl.ai/a#fragment"):
            with self.subTest(url=url):
                self.opener.open.reset_mock()
                self.ready(sample=url)
                with self.assertRaisesRegex(artwork.ArtworkError, "untrusted"):
                    artwork.generate_artwork("Cover", KEY)
                self.assertEqual(self.opener.open.call_count, 2)

    def test_redirects_are_rejected(self):
        with self.assertRaisesRegex(artwork.ArtworkError, "redirect"):
            artwork._NoRedirect().redirect_request(None, None, 307, "", {}, "https://evil.example/")

    def test_cancellation_before_submission_does_not_contact_provider(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(artwork.ArtworkCancelled):
            artwork.generate_artwork("Cover", KEY, cancelled=cancelled)
        self.opener.open.assert_not_called()

    def test_cancellation_after_submission_stops_polling(self):
        cancelled = threading.Event()
        def submitted(*args, **kwargs):
            cancelled.set()
            return response({"id": "test-job", "polling_url": POLL})
        self.opener.open.side_effect = submitted
        with self.assertRaises(artwork.ArtworkCancelled):
            artwork.generate_artwork("Cover", KEY, cancelled=cancelled.is_set)
        self.assertEqual(self.opener.open.call_count, 1)

    def test_total_timeout_is_bounded(self):
        with patch.object(artwork, "TOTAL_TIMEOUT_SECONDS", 0):
            with self.assertRaisesRegex(artwork.ArtworkError, "timed out"):
                artwork.generate_artwork("Cover", KEY)
        self.opener.open.assert_not_called()

    def test_moderated_and_unknown_statuses_end_cleanly(self):
        for status in ("Request Moderated", "Content Moderated", "Task not found", "Failed", "Error", "Something new", None):
            with self.subTest(status=status):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = [response({"id": "test-job", "polling_url": POLL}), response({"status": status, "details": KEY})]
                with self.assertRaises(artwork.ArtworkError) as caught:
                    artwork.generate_artwork("Cover", KEY)
                self.assertNotIn(KEY, str(caught.exception))
                self.assertEqual(self.opener.open.call_count, 2)

    def test_oversized_response_is_rejected_with_or_without_length(self):
        for headers in ({"Content-Length": "999999999"}, {}):
            with self.subTest(headers=headers):
                self.opener.open.side_effect = [response(b"x" * 20, headers)]
                with patch.object(artwork, "MAX_JSON_BYTES", 10):
                    with self.assertRaisesRegex(artwork.ArtworkError, "larger"):
                        artwork.generate_artwork("Cover", KEY)

    def test_non_images_are_rejected_even_if_response_claims_png(self):
        self.ready(image=b"<svg><script>alert(1)</script></svg>")
        with self.assertRaisesRegex(artwork.ArtworkError, "supported PNG"):
            artwork.generate_artwork("Cover", KEY)

    def test_signature_formats(self):
        self.assertEqual(artwork.image_mime(PNG), "image/png")
        self.assertEqual(artwork.image_mime(b"\xff\xd8\xff\xe0stuff\xff\xd9"), "image/jpeg")
        self.assertEqual(artwork.image_mime(b"RIFF\x14\0\0\0WEBPVP8X" + b"\0" * 8), "image/webp")

    def test_inputs_fail_before_network(self):
        for prompt, key in (("", KEY), ("x" * 6001, KEY), ("Cover", ""), ("Cover", "key\r\ninjected"), ("Cover", "x" * 513), (None, KEY)):
            with self.subTest(prompt_type=type(prompt), key_length=len(key)):
                with self.assertRaises(artwork.ArtworkError):
                    artwork.generate_artwork(prompt, key)
        self.opener.open.assert_not_called()

    def test_invalid_provider_json_is_not_echoed(self):
        for content in (b"not-json-" + KEY.encode(), [KEY]):
            with self.subTest(content_type=type(content)):
                self.opener.open.side_effect = [response(content)]
                with self.assertRaises(artwork.ArtworkError) as caught:
                    artwork.generate_artwork("Cover", KEY)
                self.assertNotIn(KEY, str(caught.exception))

    def test_provider_echo_of_key_is_never_saved_as_job_id(self):
        self.opener.open.side_effect = [response({"id": KEY, "polling_url": POLL})]
        with self.assertRaisesRegex(artwork.ArtworkError, "identifier"):
            artwork.generate_artwork("Cover", KEY)

    def test_oversized_image_is_rejected_during_download(self):
        self.ready(image=PNG + b"x" * 100)
        with patch.object(artwork, "MAX_IMAGE_BYTES", 50):
            with self.assertRaisesRegex(artwork.ArtworkError, "larger"):
                artwork.generate_artwork("Cover", KEY)


if __name__ == "__main__":
    unittest.main()
