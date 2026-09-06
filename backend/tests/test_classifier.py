import unittest
from unittest.mock import patch

from app.classifier import classify_email
from app.config import settings
from app.llm_router import LlmUnavailable, complete_json, llm_configured, resolve_llm_provider


class LlmConfiguredTests(unittest.TestCase):
    def test_either_key_is_enough(self):
        with (
            patch.object(settings, "openai_api_key", ""),
            patch.object(settings, "anthropic_api_key", "sk-ant"),
            patch.object(settings, "gemini_api_key", ""),
        ):
            self.assertTrue(llm_configured())
        with (
            patch.object(settings, "openai_api_key", "sk-openai"),
            patch.object(settings, "anthropic_api_key", ""),
            patch.object(settings, "gemini_api_key", ""),
        ):
            self.assertTrue(llm_configured())
        with (
            patch.object(settings, "openai_api_key", ""),
            patch.object(settings, "anthropic_api_key", ""),
            patch.object(settings, "gemini_api_key", "gk"),
        ):
            self.assertTrue(llm_configured())
        with (
            patch.object(settings, "openai_api_key", ""),
            patch.object(settings, "anthropic_api_key", ""),
            patch.object(settings, "gemini_api_key", ""),
        ):
            self.assertFalse(llm_configured())

    def test_explicit_provider_wins_then_key_order(self):
        with (
            patch.object(settings, "llm_provider", "gemini"),
            patch.object(settings, "openai_api_key", "sk-openai"),
            patch.object(settings, "anthropic_api_key", "sk-ant"),
            patch.object(settings, "gemini_api_key", "gk"),
        ):
            self.assertEqual(resolve_llm_provider(), "gemini")
        with (
            patch.object(settings, "llm_provider", "openai"),
            patch.object(settings, "openai_api_key", ""),
            patch.object(settings, "anthropic_api_key", ""),
            patch.object(settings, "gemini_api_key", "gk"),
        ):
            self.assertEqual(resolve_llm_provider(), "gemini")

    def test_complete_json_routes_to_gemini(self):
        with (
            patch.object(settings, "llm_provider", "gemini"),
            patch.object(settings, "gemini_api_key", "gk"),
            patch.object(settings, "openai_api_key", "sk-openai"),
            patch("app.llm_router._gemini", return_value={"ok": True}) as gem,
            patch("app.llm_router._openai") as oai,
        ):
            out = complete_json("sys", "user", {"type": "object"}, "n")
        self.assertEqual(out, {"ok": True})
        gem.assert_called_once()
        oai.assert_not_called()


class ClassifierLlmTests(unittest.TestCase):
    def test_no_key_uses_heuristic(self):
        with patch("app.classifier.llm_configured", return_value=False):
            out = classify_email(
                "Morning Brew <crew@morningbrew.com>",
                "☕ markets",
                "Good morning. Unsubscribe at the bottom.\n",
                labels=["CATEGORY_PROMOTIONS"],
                list_unsubscribe="<mailto:unsub@morningbrew.com>",
            )
        self.assertFalse(out.used_llm)
        self.assertEqual(out.autonomy_level, "proceed_silently")
        self.assertEqual(out.action_type, "archive")

    def test_llm_is_primary_when_configured(self):
        raw = {
            "autonomy_level": "ask_first",
            "confidence": 0.81,
            "action_type": "draft_reply",
            "reasoning": "This is a person, not a newsletter.",
            "draft": "Thanks, I'll take a look.",
            "label": None,
        }
        with patch("app.classifier.llm_configured", return_value=True), patch(
            "app.classifier.complete_decision", return_value=raw
        ):
            out = classify_email(
                "Morning Brew <crew@morningbrew.com>",
                "☕ markets",
                "Good morning. Unsubscribe at the bottom.\n",
                labels=["CATEGORY_PROMOTIONS"],
            )
        self.assertTrue(out.used_llm)
        self.assertEqual(out.autonomy_level, "ask_first")
        self.assertEqual(out.action_type, "draft_reply")
        self.assertEqual(out.reasoning, "This is a person, not a newsletter.")

    def test_llm_failure_falls_back_to_heuristic(self):
        with patch("app.classifier.llm_configured", return_value=True), patch(
            "app.classifier.complete_decision", side_effect=LlmUnavailable("down")
        ):
            out = classify_email(
                "Morning Brew <crew@morningbrew.com>",
                "☕ markets",
                "Good morning. Unsubscribe at the bottom.\n",
                labels=["CATEGORY_PROMOTIONS"],
                list_unsubscribe="<mailto:unsub@morningbrew.com>",
            )
        self.assertFalse(out.used_llm)
        self.assertEqual(out.autonomy_level, "proceed_silently")

    def test_invalid_llm_level_falls_back_to_heuristic_level(self):
        raw = {
            "autonomy_level": "yolo",
            "confidence": 0.9,
            "action_type": "teleport",
            "reasoning": "n/a",
            "draft": None,
            "label": None,
        }
        with patch("app.classifier.llm_configured", return_value=True), patch(
            "app.classifier.complete_decision", return_value=raw
        ):
            out = classify_email(
                "Morning Brew <crew@morningbrew.com>",
                "☕ markets",
                "Good morning. Unsubscribe at the bottom.\n",
                labels=["CATEGORY_PROMOTIONS"],
                list_unsubscribe="<mailto:unsub@morningbrew.com>",
            )
        self.assertTrue(out.used_llm)
        self.assertEqual(out.autonomy_level, "proceed_silently")
        self.assertEqual(out.action_type, "archive")


if __name__ == "__main__":
    unittest.main()
