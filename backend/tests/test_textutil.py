import unittest

from app.textutil import html_to_text


class HtmlToTextTests(unittest.TestCase):
    def test_strips_tags_and_keeps_words(self):
        raw = "<!DOCTYPE html><html><body><p>Fair warning: 40% OFF</p></body></html>"
        self.assertEqual(html_to_text(raw), "Fair warning: 40% OFF")

    def test_plain_passthrough(self):
        self.assertEqual(html_to_text("just a note"), "just a note")


if __name__ == "__main__":
    unittest.main()
