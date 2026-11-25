import unittest

from app.security import RateLimiter, UploadError, detect_image_type, sanitize_text, validate_upload

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 20
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"0" * 10


class UploadTests(unittest.TestCase):
    def test_detects_supported_types(self):
        self.assertEqual(detect_image_type(PNG), "image/png")
        self.assertEqual(detect_image_type(JPEG), "image/jpeg")
        self.assertEqual(detect_image_type(WEBP), "image/webp")

    def test_rejects_other_content(self):
        for bad in (b"<html><script>alert(1)</script>", b"%PDF-1.7", b"GIF89a....", b"MZ\x90\x00"):
            with self.subTest(bad=bad[:8]):
                with self.assertRaises(UploadError):
                    validate_upload(bad, 1024)

    def test_rejects_empty_and_oversize(self):
        with self.assertRaises(UploadError):
            validate_upload(b"", 1024)
        with self.assertRaises(UploadError):
            validate_upload(PNG + b"0" * 2048, 1024)

    def test_accepts_valid_image(self):
        self.assertEqual(validate_upload(PNG, 1024), "image/png")


class SanitizeTests(unittest.TestCase):
    def test_strips_controls_bidi_and_collapses_spaces(self):
        self.assertEqual(sanitize_text("  Shri\u202e  Ram\x00   Stores \n"), "Shri Ram Stores")

    def test_caps_length_and_rejects_non_strings(self):
        self.assertEqual(len(sanitize_text("x" * 500, 80)), 80)
        self.assertEqual(sanitize_text(None), "")
        self.assertEqual(sanitize_text(123), "")

    def test_markup_is_left_as_inert_text(self):
        # Escaping happens at render time (textContent); we just make sure nothing is executed here.
        self.assertEqual(sanitize_text("<img src=x onerror=alert(1)>"), "<img src=x onerror=alert(1)>")


class RateLimiterTests(unittest.TestCase):
    def test_blocks_after_limit_and_recovers(self):
        limiter = RateLimiter(limit=2, window_s=60)
        self.assertTrue(limiter.allow("a", now=0))
        self.assertTrue(limiter.allow("a", now=1))
        self.assertFalse(limiter.allow("a", now=2))
        self.assertTrue(limiter.allow("b", now=2))  # separate key
        self.assertTrue(limiter.allow("a", now=61))  # window passed

    def test_memory_is_bounded(self):
        limiter = RateLimiter(limit=1, window_s=1, max_keys=10)
        for i in range(100):
            limiter.allow(f"k{i}", now=float(i))
        self.assertLessEqual(len(limiter._hits), 12)


if __name__ == "__main__":
    unittest.main()
